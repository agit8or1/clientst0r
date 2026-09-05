"""
Phase 40.1 (v3.17.538) — trim the website check history.

`MonitorCheck` is append-only and is the highest-volume table in the app: a
monitor on the default hourly interval writes ~8,760 rows a year, one on a
five-minute interval ~105,000. Nothing reads further back than the longest
uptime window a status page offers (365 days), so anything older is pure cost.

Default retention is 400 days rather than 365 so a full-year figure stays
computable right up to the moment the prune runs, instead of losing its oldest
day the day before someone looks.

Run daily from the scheduler:  manage.py prune_monitor_checks
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from monitoring.models import MonitorCheck

DEFAULT_RETENTION_DAYS = 400


class Command(BaseCommand):
    help = 'Delete website monitor check history older than the retention window.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=DEFAULT_RETENTION_DAYS,
            help=f'Retention window in days (default {DEFAULT_RETENTION_DAYS}).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be deleted without deleting it.',
        )
        parser.add_argument(
            '--batch-size', type=int, default=5000,
            help='Rows to delete per statement (default 5000). Keeps the '
                 'transaction short enough not to lock the table on a big '
                 'backlog.',
        )

    def handle(self, *args, **options):
        days = options['days']
        if days < 1:
            self.stderr.write(self.style.ERROR('--days must be at least 1.'))
            return

        cutoff = timezone.now() - timedelta(days=days)
        stale = MonitorCheck.objects.filter(checked_at__lt=cutoff)
        total = stale.count()

        if options['dry_run']:
            self.stdout.write(
                f'[dry-run] {total} check(s) older than {cutoff:%Y-%m-%d %H:%M} '
                f'({days}d) would be deleted.')
            return

        if not total:
            self.stdout.write(f'Nothing to prune (retention {days}d).')
            return

        batch = max(1, options['batch_size'])
        deleted = 0
        # Delete by explicit id batches. A bare queryset .delete() on a table
        # this size holds one long transaction and can lock out the checker
        # that is trying to append to it.
        while True:
            ids = list(
                MonitorCheck.objects.filter(checked_at__lt=cutoff)
                .values_list('id', flat=True)[:batch]
            )
            if not ids:
                break
            count, _ = MonitorCheck.objects.filter(id__in=ids).delete()
            deleted += count

        self.stdout.write(self.style.SUCCESS(
            f'Pruned {deleted} check(s) older than {days}d '
            f'(cutoff {cutoff:%Y-%m-%d %H:%M}).'))
