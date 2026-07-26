"""
Process queued Microsoft Graph outbound email jobs (issue #142, outbound).

Sends are enqueued as EmailOutboundJob rows and attempted inline at request
time; this worker retries any that were left queued by a transient failure
(429 / 5xx / connect timeout), honoring their backoff schedule. Each job is
claimed with an atomic status transition before submission, so running this on
a cron alongside the inline attempt can never double-send.

Cron (installed by deploy/update_instructions.sh):
    */5 * * * * manage.py psa_send_outbound
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from psa.graph_outbound import process_job
from psa.models import EmailOutboundJob


class Command(BaseCommand):
    help = 'Submit/retry queued Microsoft Graph outbound email jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100,
                            help='Max jobs to process this run.')
        parser.add_argument('--job-id', type=int,
                            help='Process a single job by id (ignores schedule).')

    def handle(self, *args, **options):
        now = timezone.now()
        qs = EmailOutboundJob.objects.filter(status=EmailOutboundJob.STATUS_QUEUED)
        if options.get('job_id'):
            qs = qs.filter(pk=options['job_id'])
        else:
            # Only jobs whose backoff has elapsed (or that never had one).
            qs = qs.filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        qs = qs.order_by('created_at')[:options['limit']]

        sent = failed = retried = skipped = 0
        for job in qs:
            claimed = process_job(job)
            if not claimed:
                skipped += 1
                continue
            job.refresh_from_db()
            if job.status == EmailOutboundJob.STATUS_SENT:
                sent += 1
            elif job.status == EmailOutboundJob.STATUS_QUEUED:
                retried += 1
            else:  # failed / uncertain
                failed += 1

        self.stdout.write(self.style.SUCCESS(
            f'outbound: {sent} sent, {retried} requeued, {failed} failed, {skipped} skipped'
        ))
