"""
Auto-renew expired contracts that have auto_renew=True and have just passed
their end_date. Run nightly via cron. Idempotent — guards against duplicate
renewals via parent_contract linkage.

v3.17.600 — the renewal now carries the billing schedule. It used to be
created without `billing_frequency` / `recurring_amount` /
`next_billing_date`, i.e. with recurring billing switched off, while the old
contract was marked expired, so recurring invoicing silently stopped at the
first renewal. Meters are copied too, and contracts flagged
cancel-at-period-end are no longer renewed.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Auto-renew expired contracts that have auto_renew=True. Applies rollover.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would happen, do nothing')

    def handle(self, *args, **opts):
        from psa.models import Contract, ContractMeter
        from dateutil.relativedelta import relativedelta

        today = timezone.now().date()
        # Candidates: status active, auto_renew, end_date passed, no child renewal yet
        candidates = Contract.objects.filter(
            status='active',
            auto_renew=True,
            end_date__lt=today,
            end_date__isnull=False,
            renewals__isnull=True,  # no renewal child created yet
        ).exclude(
            # The client asked to stop at the end of the period: renewing
            # would bill them for a term they declined.
            # `psa_advance_subscription_lifecycle` cancels these.
            cancel_at_period_end=True,
        ).distinct()

        renewed = 0
        for c in candidates:
            # Compute rollover. `hours_used_minutes` is kept current by the
            # time-entry save/delete hooks (and was corrected once by
            # migration psa.0070), so it is read as stored.
            rolled_minutes = 0
            if c.rollover_percent and c.total_hours:
                base_minutes = int(float(c.total_hours) * 60)
                unused = max(0, base_minutes - (c.hours_used_minutes or 0))
                rolled_minutes = int(unused * float(c.rollover_percent) / 100)

            new_start = c.end_date + timedelta(days=1)
            new_end = new_start + relativedelta(months=c.auto_renew_period_months or 12) - timedelta(days=1)
            rollover_expires_at = None
            if rolled_minutes and c.rollover_expiry_days:
                rollover_expires_at = new_start + timedelta(days=c.rollover_expiry_days)
            next_billing = self._continue_cadence(c, new_start)

            self.stdout.write(
                f'Renewing {c.id} {c.name}: {new_start} -> {new_end}, '
                f'rollover_minutes={rolled_minutes}, '
                f'next_billing_date={next_billing}'
            )
            if opts['dry_run']:
                continue

            with transaction.atomic():
                # Old contract: mark expired
                c.status = 'expired'
                c.save(update_fields=['status', 'updated_at'])

                # New contract: copy every field that defines the commercial
                # terms (allowance, rates, billing schedule, role gates, SLA,
                # renewal policy), bump dates, reset usage, apply rollover.
                #
                # Deliberately NOT copied:
                #   hours_used_minutes   — new period; recomputed below from
                #                          entries already in the new window
                #   rolled_over_minutes / rollover_expires_at — computed above
                #   status               — always 'active'
                #   cancel_at_period_end — such contracts are not renewed
                #                          (candidate filter above)
                #   created_by / created_at / updated_at — new row, made by
                #                          the cron (created_by stays empty)
                #   parent_contract      — set to the old contract
                new_c = Contract.objects.create(
                    organization=c.organization,
                    client_org=c.client_org,
                    name=c.name,
                    contract_type=c.contract_type,
                    status='active',
                    start_date=new_start,
                    end_date=new_end,
                    total_hours=c.total_hours,
                    hours_used_minutes=0,
                    hourly_rate=c.hourly_rate,
                    overage_rate=c.overage_rate,
                    rollover_percent=c.rollover_percent,
                    rollover_expiry_days=c.rollover_expiry_days,
                    rolled_over_minutes=rolled_minutes,
                    rollover_expires_at=rollover_expires_at,
                    auto_renew=c.auto_renew,
                    auto_renew_period_months=c.auto_renew_period_months,
                    billing_frequency=c.billing_frequency,
                    next_billing_date=next_billing,
                    recurring_amount=c.recurring_amount,
                    # Carried so the renewal's first invoice is not treated
                    # as a brand-new subscription by `_proration_factor`.
                    last_billed_at=c.last_billed_at,
                    # A paused subscription stays paused across renewal.
                    paused_at=c.paused_at,
                    paused_until=c.paused_until,
                    proration_enabled=c.proration_enabled,
                    billable_role_codes=list(c.billable_role_codes or []),
                    excluded_role_codes=list(c.excluded_role_codes or []),
                    parent_contract=c,
                    sla_matrix=dict(c.sla_matrix or {}),
                    notes=c.notes,
                )
                # Copy bundle items
                for b in c.bundle_items.all():
                    b.pk = None
                    b.id = None
                    b._state.adding = True
                    b.contract = new_c
                    b.save()

                # Copy usage meters. Unbilled usage moves with the meter: the
                # old contract is expired and will not be invoiced again, so
                # leaving it there would drop it.
                for m in c.meters.all():
                    ContractMeter.objects.create(
                        contract=new_c,
                        name=m.name,
                        unit=m.unit,
                        unit_price=m.unit_price,
                        current_quantity=m.current_quantity or 0,
                        is_active=m.is_active,
                        last_billed_at=m.last_billed_at,
                        notes=m.notes,
                    )
                    if m.current_quantity:
                        m.current_quantity = 0
                        m.save(update_fields=['current_quantity', 'updated_at'])

                # Time already logged in the new window (the renewal cron ran
                # late) counts against the new allowance.
                new_c.recompute_hours_used()

                renewed += 1

        self.stdout.write(self.style.SUCCESS(
            f'{"Would renew" if opts["dry_run"] else "Renewed"} {renewed} '
            f'contract{"s" if renewed != 1 else ""}'
        ))

    @staticmethod
    def _continue_cadence(old, new_start):
        """The renewal's first billing date: the period right after the old
        contract's last billed one, so the cadence carries on unbroken.

        `old.next_billing_date` is normally exactly that — the recurring
        generator advances it in the same transaction as each invoice. It is
        still checked against the old contract's invoices, because the
        per-period uniqueness constraint is per contract and so cannot stop
        the renewal re-billing a period the old contract already invoiced
        (e.g. after someone moved the old cursor back by hand).

        A billed contract with no cursor continues after its last invoice;
        one never billed and without a cursor starts on the renewal's start
        date. Billing disabled ('none') keeps whatever was there.
        """
        from psa.models import Contract, Invoice
        if old.billing_frequency == 'none':
            return old.next_billing_date
        last_billed = (Invoice.objects
                       .filter(source_contract=old, is_credit_memo=False,
                               billing_period_start__isnull=False)
                       .order_by('-billing_period_start')
                       .values_list('billing_period_start', flat=True)
                       .first())
        nxt = old.next_billing_date
        if nxt is None:
            if last_billed is None:
                return new_start
            nxt = last_billed
        guard = 0
        while (last_billed is not None and nxt is not None
               and nxt <= last_billed and guard < 1000):
            nxt = Contract._advance_billing(nxt, old.billing_frequency)
            guard += 1
        return nxt
