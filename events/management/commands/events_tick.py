"""Shared event layer maintenance (every minute, via run_scheduler).

Drains the projection queue, finds source rows created without a save signal,
revisits live events, and applies retention and the storage quota.
"""
from django.core.management.base import BaseCommand

from events import projection


class Command(BaseCommand):
    help = 'Project source alerts into the shared event layer and apply retention.'

    def add_arguments(self, parser):
        parser.add_argument('--budget', type=int, default=40, help='Seconds this run may spend')

    def handle(self, *args, **opts):
        # Monitoring source freshness (82.10): a collector that stopped
        # running writes nothing, so only this sweep sees it go stale. It
        # runs even with event ingestion switched off.
        from events.source_health_store import sweep
        try:
            changed = sweep()
        except Exception as exc:  # noqa: BLE001 - never stop the projection
            self.stderr.write(f'Source health sweep failed: {type(exc).__name__}')
            changed = 0
        if changed:
            self.stdout.write(f'Monitoring source health: {changed} state change(s).')
        # Monitoring coverage (82.17, 82.19): backfill the windows recovered
        # sources missed, then the once-per-gap notifications. Its own time
        # budget; never blocks the projection below.
        from events import coverage
        try:
            done = coverage.backfill_tick(budget_seconds=min(20, max(5, opts['budget'] // 2)))
            if done['windows']:
                self.stdout.write('Coverage backfill: {windows} window(s), {pages} page(s), '
                                  '{resolved} resolved.'.format(**done))
            coverage.notify_tick()
        except Exception as exc:  # noqa: BLE001 - never stop the projection
            self.stderr.write(f'Coverage backfill failed: {type(exc).__name__}')
        summary = projection.run(budget_seconds=opts['budget'])
        if summary.get('disabled'):
            self.stdout.write('Event ingestion is switched off.')
            return
        self.stdout.write('Projected {drained} queued, {scanned} scanned, {rechecked} rechecked; '
                          '{failed} failed; pruned {pruned}.'.format(**summary))
