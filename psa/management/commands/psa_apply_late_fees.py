"""
Phase 15 v7 (v3.17.294): late fee automation.

Daily cron. For every Invoice that's been past due_date by at least
`SystemSetting.late_fee_min_days_overdue` and isn't paid/void, apply
a Charge equal to `late_fee_pct` * outstanding_balance. Idempotent —
skips invoices that already have a "Late fee for INV-..." charge.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import F, Q

from core.models import SystemSetting
from psa.models import Charge, Invoice


class Command(BaseCommand):
    help = 'Apply late fees to overdue invoices per SystemSetting thresholds.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        ss = SystemSetting.get_settings()
        pct = Decimal(str(ss.late_fee_pct or 0))
        min_days = int(ss.late_fee_min_days_overdue or 0)
        if pct <= 0 or min_days <= 0:
            self.stdout.write(self.style.WARNING(
                'Late fees disabled (pct or min-days is 0).'))
            return

        cutoff = date.today() - timedelta(days=min_days)
        invs = (Invoice.objects
                .filter(due_date__lte=cutoff, is_credit_memo=False)
                .filter(~Q(status__in=['paid', 'void'])
                        & Q(amount_paid__lt=F('total')))
                .prefetch_related('credit_memos'))

        applied = 0
        for inv in invs:
            tag = f'Late fee for {inv.invoice_number}'
            if Charge.objects.filter(
                client_org=inv.client_org,
                description__startswith=tag,
            ).exists():
                continue
            # Net off any credit memos first. Issuing one does not touch the
            # invoice's `amount_paid` or `status`, so a fully-credited invoice
            # still read as the full amount overdue and was charged a late fee
            # on money the customer no longer owed.
            balance = inv.net_balance_due
            if balance <= 0:
                continue
            fee = (balance * pct / Decimal('100')).quantize(Decimal('0.01'))
            if fee <= 0:
                continue
            if dry:
                self.stdout.write(
                    f'[dry] would charge ${fee} on {inv.invoice_number} '
                    f'(balance ${balance}, {pct}%)'
                )
            else:
                Charge.objects.create(
                    organization=inv.organization,
                    client_org=inv.client_org,
                    description=f'{tag} (overdue ${balance}, '
                                f'{pct}% applied)',
                    amount=fee,
                    currency=inv.currency or 'USD',
                    charge_date=date.today(),
                    is_credit=False,
                    recurrence='once',
                    notes=f'Auto-applied by psa_apply_late_fees on '
                          f'{date.today()}; source invoice '
                          f'{inv.invoice_number}',
                )
                applied += 1
                self.stdout.write(self.style.SUCCESS(
                    f'Charged ${fee} late fee on {inv.invoice_number}'
                ))

        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}{applied} late fee(s) applied.'
        ))
