"""Scheduled API Access Control maintenance (every minute, via run_scheduler).

* Undo changes whose rollback window ended without being kept.
* Delete refused-request records older than the retention setting.
* Delete webhook replay records whose window has passed.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api_access import rollback
from api_access.models import ApiAccessDecision, ApiAccessSettings, WebhookDelivery


class Command(BaseCommand):
    help = 'Apply due API access rollbacks and prune old records.'

    def handle(self, *args, **opts):
        now = timezone.now()
        if rollback.revert_if_due(now=now):
            self.stdout.write(self.style.WARNING('Rollback window ended unkept: changes undone.'))
        days = ApiAccessSettings.get().decision_retention_days or 30
        old = ApiAccessDecision.objects.filter(last_seen_at__lt=now - timedelta(days=days)).delete()[0]
        expired = WebhookDelivery.objects.filter(expires_at__lt=now).delete()[0]
        if old or expired:
            self.stdout.write(f'Pruned {old} refused-request records and {expired} webhook replay records.')
