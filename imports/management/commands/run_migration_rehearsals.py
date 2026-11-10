"""Run queued migration-rehearsal work (fetch / build / apply / rollback).

The scheduler runs this every minute as task ``run_migration_rehearsals``.
Safe to run concurrently: each plan's task is claimed with a lease, see
imports/migration/tasks.py. Does nothing when nothing is queued.
"""
from django.core.management.base import BaseCommand

from imports.migration.tasks import run_pending


class Command(BaseCommand):
    help = 'Run queued IT Glue / Hudu migration rehearsal tasks.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=10)

    def handle(self, *args, **opts):
        results = run_pending(limit=opts['limit'])
        for plan_id, state in results:
            self.stdout.write(f'rehearsal {plan_id}: {state}')
        if not results:
            self.stdout.write('no rehearsal work queued')
