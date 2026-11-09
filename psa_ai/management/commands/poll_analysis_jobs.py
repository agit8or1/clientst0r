"""Poll rem0te for unfinished analysis jobs and expire stale ones, so a
missed callback never leaves a job hanging. Safe to run every minute."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from psa_ai.models import AnalysisJob
from psa_ai.services import processor


class Command(BaseCommand):
    help = 'Recover missed rem0te job events and expire old jobs.'

    def handle(self, *args, **opts):
        n = 0
        cutoff = timezone.now() - timedelta(seconds=processor.POLL_MIN_SECONDS)
        for job in AnalysisJob.objects.exclude(status__in=AnalysisJob.TERMINAL).filter(created_at__lt=cutoff)[:200]:
            processor.poll(job)
            n += 1
        self.stdout.write(f'{n} job(s) checked.')
