"""
Phase 15 v13 (v3.17.298): subscription lifecycle advancement.

Daily cron. Three jobs:
  1. **Auto-resume** — contracts with `paused_until` <= today get
     `paused_at` cleared.
  2. **Cancel-at-period-end** — contracts with `cancel_at_period_end=True`
     whose next_billing_date is past get transitioned to `status='cancelled'`.
  3. **Expire** — contracts whose `end_date` has passed and which are not
     going to renew get `status='expired'` (v3.17.581).

All three are idempotent — already-resumed, already-cancelled and
already-expired contracts are filtered out at the SQL level.

On (3): `expired` has been a valid Contract status since the model was
written and nothing ever set it. `psa_auto_renew_contracts` handles
auto_renew=True, and job (2) handles an explicit cancel-at-period-end, but a
contract that simply ran out stayed `active` forever — and the recurring
invoice cron billed it forever with it.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from django.db import models

from psa.models import Contract


class Command(BaseCommand):
    help = 'Advance Contract subscription lifecycle (auto-resume + cancel-at-period-end).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        today = date.today()
        resumed = 0
        cancelled = 0
        expired = 0

        # Auto-resume
        resume_qs = Contract.objects.filter(
            paused_at__isnull=False,
            paused_until__isnull=False,
            paused_until__lte=today,
        )
        for c in resume_qs:
            if dry:
                self.stdout.write(f'[dry] would resume {c.name}')
            else:
                c.resume()
                resumed += 1
                self.stdout.write(self.style.SUCCESS(
                    f'Resumed {c.name}'))

        # Cancel-at-period-end
        cancel_qs = Contract.objects.filter(
            cancel_at_period_end=True,
            status='active',
            next_billing_date__isnull=False,
            next_billing_date__lt=today,
        )
        for c in cancel_qs:
            if dry:
                self.stdout.write(f'[dry] would cancel {c.name}')
            else:
                c.status = 'cancelled'
                c.cancel_at_period_end = False
                c.save(update_fields=['status', 'cancel_at_period_end',
                                        'updated_at'])
                cancelled += 1
                self.stdout.write(self.style.SUCCESS(
                    f'Cancelled {c.name} (period ended)'))

        # Expire contracts that have run out.
        #
        # Deliberately narrow. A contract is only expired here when it cannot
        # be renewed into: `auto_renew` contracts belong to
        # `psa_auto_renew_contracts`, which creates the successor and would
        # otherwise race this, and one that already has a renewal child has
        # been succeeded and is no longer the live agreement to bill.
        expire_qs = Contract.objects.filter(
            status='active',
            end_date__isnull=False,
            end_date__lt=today,
        ).filter(
            models.Q(auto_renew=False) | models.Q(renewals__isnull=False)
        ).distinct()
        for c in expire_qs:
            if dry:
                self.stdout.write(
                    f'[dry] would expire {c.name} (ended {c.end_date})')
                expired += 1
            else:
                c.status = 'expired'
                c.save(update_fields=['status', 'updated_at'])
                expired += 1
                self.stdout.write(self.style.SUCCESS(
                    f'Expired {c.name} (ended {c.end_date})'))

        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}{resumed} resumed; {cancelled} '
            f'cancelled; {expired} expired.'
        ))
