"""
Phase 14 v3 (v3.17.286): SLA-driven workflow automation tick.

Wire to a 5-minute systemd timer. For each open ticket whose
`resolution_due_at` is set, fires the workflow engine with the new
`sla_threshold_crossed` trigger. Rules using `sla_pct_at_least` in
their conditions and `fire_once_per_ticket=True` will land their
actions exactly once per ticket per crossing.

Closed / terminal-status tickets are skipped — there's no SLA to chase.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from psa.models import Ticket
from psa.sla import refresh_breach_flags
from psa.workflow_engine import fire


class Command(BaseCommand):
    help = 'Fire SLA-threshold workflow rules against open tickets.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=5000,
                            help='Cap on tickets evaluated per tick.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        limit = options['limit']

        # Open tickets only — terminal statuses are excluded so we don't
        # alert on closed work.
        qs = (Ticket.objects
              .filter(resolution_due_at__isnull=False)
              .filter(~Q(status__is_terminal=True))
              .select_related('status', 'priority')
              .order_by('pk')[:limit])

        evaluated = 0
        fired_total = 0
        flagged = 0
        for ticket in qs:
            evaluated += 1
            if dry:
                continue

            # v3.17.563 — persist breach state here as well as on save. A
            # ticket that simply runs out of time is never saved, so nothing
            # else would ever notice it had breached, and the breach report
            # reads these columns rather than recomputing.
            try:
                if refresh_breach_flags(ticket):
                    flagged += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f'{ticket.ticket_number}: breach flag refresh failed: {exc}'))

            try:
                n = fire('sla_threshold_crossed', ticket)
                fired_total += n
            except Exception as exc:  # pragma: no cover — engine catches per-rule
                self.stdout.write(self.style.ERROR(
                    f'{ticket.ticket_number}: {exc}'))

        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}Evaluated {evaluated} ticket(s); '
            f'{fired_total} rule(s) fired; {flagged} breach flag(s) updated.'
        ))
