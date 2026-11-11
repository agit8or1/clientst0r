"""Poll the paired RMMs for unfinished analysis jobs and RMM requests,
expire stale ones, and refresh pairings' capabilities, so a missed callback
never leaves anything hanging. Safe to run every minute; the scheduler runs
it as task `poll_analysis_jobs`.

It also purges ticket AI and automation history past each customer's
retention window (services/history.py), at most every six hours."""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from psa_ai.models import AnalysisJob
from psa_ai.services import processor, rmm_actions

logger = logging.getLogger('psa_ai')

CAPABILITIES_EVERY = timedelta(hours=1)
CAPABILITIES_RETRY = timedelta(minutes=10)


class Command(BaseCommand):
    help = 'Recover missed RMM job events, expire old jobs and refresh pairing capabilities.'

    def handle(self, *args, **opts):
        n = failed = 0
        cutoff = timezone.now() - timedelta(seconds=processor.POLL_MIN_SECONDS)
        jobs = (AnalysisJob.objects.exclude(status__in=AnalysisJob.TERMINAL).filter(created_at__lt=cutoff)
                .select_related('connection').order_by('created_at')[:200])
        for job in jobs:
            # One broken pairing must not stop the others being checked.
            try:
                processor.poll(job)
            except Exception:
                failed += 1
                logger.exception('polling analysis job %s failed', job.pk)
            n += 1
        self.stdout.write(f'{n} job(s) checked, {failed} failed.')
        try:
            r = rmm_actions.expire_stale()
            if r:
                self.stdout.write(f'{r} RMM request(s) expired.')
        except Exception:
            logger.exception('expiring RMM requests failed')
        self._refresh_capabilities()
        self._rem0te()
        self._purge_history()

    def _purge_history(self):
        from psa_ai.services import history
        try:
            counts = history.purge_if_due()
        except Exception:
            logger.exception('purging ticket AI history failed')
            return
        if counts and any(counts.values()):
            self.stdout.write('AI history purged: ' + ', '.join(f'{v} {k}' for k, v in counts.items() if v))

    def _rem0te(self):
        """Rem0te: reconciliation (integrations/rem0te/reconcile.py) —
        capabilities re-check with backoff, alert events missed while
        ClientSt0r was down, ticket link retries, open action proposals —
        with every outcome on the connection's integration health."""
        from integrations.rem0te.reconcile import reconcile_all
        try:
            reconcile_all(self.stdout)
        except Exception:
            logger.exception('reconciling Rem0te connections failed')

    def _refresh_capabilities(self):
        from integrations.models import RMMConnection
        from integrations.ticket_rmm import check, settings
        from django.utils.dateparse import parse_datetime
        now = timezone.now()
        # Rem0te connections are re-checked by their reconciliation (with backoff).
        for conn in RMMConnection.objects.filter(is_active=True).exclude(provider_type='rem0te'):
            try:
                if not settings(conn)['enabled']:
                    continue
                doc = check(conn)
                when = parse_datetime(str(doc.get('checked_at') or '').replace('Z', '+00:00'))
                every = CAPABILITIES_EVERY if doc.get('ok') else CAPABILITIES_RETRY
                if when is not None and now - when < every:
                    continue
                processor.refresh_capabilities(conn)
            except Exception:
                logger.exception('refreshing capabilities for RMM connection %s failed', conn.pk)
