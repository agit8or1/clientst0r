"""Poll rem0te for unfinished analysis jobs and expire stale ones, so a
missed callback never leaves a job hanging. Safe to run every minute; the
scheduler runs it as task `poll_analysis_jobs`."""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from psa_ai.models import AnalysisJob
from psa_ai.services import processor

logger = logging.getLogger('psa_ai')


class Command(BaseCommand):
    help = 'Recover missed rem0te job events and expire old jobs.'

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
