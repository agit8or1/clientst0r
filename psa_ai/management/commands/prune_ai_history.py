"""Delete ticket AI and automation history older than each customer's
retention window now (psa_ai/services/history.py). The scheduled task
`poll_analysis_jobs` already does this every six hours; this is the manual
equivalent."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Purge ticket AI and automation history past each customer's retention window."

    def handle(self, *args, **opts):
        from django.utils import timezone
        from psa_ai.models import AIHistoryPurgeState
        from psa_ai.services import history
        now = timezone.now()
        counts = history.purge_expired(now)
        AIHistoryPurgeState.objects.update_or_create(pk=1, defaults={'last_run_at': now, 'last_deleted': counts})
        self.stdout.write(', '.join(f'{v} {k}' for k, v in counts.items()) + ' deleted.')
