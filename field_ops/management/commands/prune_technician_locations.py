"""
Prune expired TechnicianLocation rows.

Phase 8.5 — runs nightly. Each ping has its `retention_until` pre-set on
insert; this command is a one-shot WHERE retention_until < today() so we
don't have to re-query the per-org policy.

Usage:
    python manage.py prune_technician_locations [--dry-run]
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from field_ops.models import TechnicianLocation


class Command(BaseCommand):
    help = 'Delete TechnicianLocation rows whose retention_until is in the past.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Count expired rows without deleting them.',
        )

    def handle(self, *args, **options):
        today = timezone.now().date()
        qs = TechnicianLocation.objects.filter(retention_until__lt=today)
        count = qs.count()
        if options.get('dry_run'):
            self.stdout.write(self.style.WARNING(
                f'[dry-run] Would delete {count} expired TechnicianLocation row(s) '
                f'(retention_until < {today.isoformat()}).'
            ))
            return
        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted} expired TechnicianLocation row(s) '
            f'(retention_until < {today.isoformat()}).'
        ))
        # Geo-aware dispatch keeps one last-known position per consenting
        # technician; it has its own, much shorter, retention in hours.
        from field_ops.geo_dispatch import purge_expired
        purged = purge_expired()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {purged} expired dispatch position(s).'
        ))
