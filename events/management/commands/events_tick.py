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
        summary = projection.run(budget_seconds=opts['budget'])
        if summary.get('disabled'):
            self.stdout.write('Event ingestion is switched off.')
            return
        self.stdout.write('Projected {drained} queued, {scanned} scanned, {rechecked} rechecked; '
                          '{failed} failed; pruned {pruned}.'.format(**summary))
