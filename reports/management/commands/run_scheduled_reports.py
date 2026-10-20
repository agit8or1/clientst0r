"""
Process scheduled reports whose next_run <= now. Runs every 15 min via
cron. For each due schedule:
  1. Generate the report (PDF or CSV) using the existing
     reports.generators module
  2. Email it to recipients
  3. Update last_run + compute next_run from frequency
  4. Save a GeneratedReport row for audit trail

v3.17.147 — Phase 3.6 wave B.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Process scheduled reports whose next_run is due.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Don't generate / email / advance — just list due rows.")
        parser.add_argument('--force-id', type=int,
                            help='Force-run a specific schedule by id (ignores next_run).')

    def handle(self, *args, **opts):
        from reports.models import ScheduledReport
        now = timezone.now()
        if opts.get('force_id'):
            qs = ScheduledReport.objects.filter(pk=opts['force_id'])
        else:
            qs = ScheduledReport.objects.filter(
                is_active=True, next_run__lte=now,
            )
        ran = 0
        for sched in qs:
            self.stdout.write(
                f'Running #{sched.id} {sched.name} (next_run={sched.next_run})'
            )
            if opts.get('dry_run'):
                continue
            try:
                self._run_one(sched)
                ran += 1
            except Exception as exc:
                self.stderr.write(f'  x {sched.name} failed: {exc}')
                # Don't update next_run on failure — let next tick retry
                continue
        verb = 'Would run' if opts.get('dry_run') else 'Ran'
        suffix = '' if ran == 1 else 's'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {ran} schedule{suffix}'
        ))

    # ------------------------------------------------------------------ helpers

    def _run_one(self, sched):
        from django.core.files.base import ContentFile
        from reports.generators import generate_report
        from reports.models import GeneratedReport

        output_format = (sched.output_format or 'pdf').lower()

        # Generate the artifact (filename + bytes)
        filename, artifact_bytes = generate_report(
            template=sched.template,
            output_format=output_format,
            organization=sched.organization,
            parameters=sched.parameters or {},
        )

        # Save GeneratedReport row for audit trail. Persist the artifact
        # via the FileField so it shows up in the Generated list.
        gen = GeneratedReport.objects.create(
            template=sched.template,
            scheduled_report=sched,
            organization=sched.organization,
            generated_by=None,  # cron-generated
            format=self._normalize_format(output_format),
            status='completed',
            parameters=sched.parameters or {},
        )
        try:
            gen.file.save(filename, ContentFile(artifact_bytes), save=False)
            gen.file_size = len(artifact_bytes)
            gen.completed_at = timezone.now()
            gen.save(update_fields=['file', 'file_size', 'completed_at'])
        except Exception:
            # Storing the file is best-effort — don't fail the schedule run.
            pass

        # Email to recipients, unless the schedule is "Download Only". An
        # email problem is recorded on the generated report; the schedule
        # still rolls forward so it doesn't regenerate every tick.
        if sched.recipients and sched.delivery_method in ('email', 'both'):
            try:
                sent = self._email_artifact(sched, gen, filename, artifact_bytes,
                                            output_format)
            except Exception as exc:
                sent = None
                gen.error_message = f'Email not sent: {exc}'[:2000]
            if sent == 0 and not gen.error_message:
                gen.error_message = 'Email not sent: SMTP is not configured in Settings → Email.'
            if gen.error_message:
                gen.save(update_fields=['error_message'])
                self.stderr.write(f'  ! {sched.name}: {gen.error_message}')

        # Roll forward
        sched.last_run = timezone.now()
        sched.next_run = self._next_run(sched, sched.last_run)
        sched.save(update_fields=['last_run', 'next_run'])

    @staticmethod
    def _normalize_format(fmt):
        # GeneratedReport.format choices: pdf | excel | csv | json
        f = (fmt or 'pdf').lower()
        if f in ('pdf', 'csv', 'json', 'excel'):
            return f
        if f in ('xlsx', 'xls'):
            return 'excel'
        return 'pdf'

    def _next_run(self, sched, from_dt):
        freq = (sched.frequency or 'daily').lower()
        if freq == 'hourly':
            return from_dt + timedelta(hours=1)
        if freq == 'daily':
            return from_dt + timedelta(days=1)
        if freq == 'weekly':
            return from_dt + timedelta(days=7)
        if freq == 'monthly':
            return from_dt + timedelta(days=30)
        if freq == 'quarterly':
            return from_dt + timedelta(days=90)
        return from_dt + timedelta(days=1)

    def _email_artifact(self, sched, gen, filename, artifact_bytes,
                        output_format):
        """Send the report to each recipient through the SMTP settings in
        Settings → Email (the same connection every other notification
        uses). Returns how many messages were accepted; 0 when SMTP is not
        configured."""
        from django.core.mail import EmailMessage

        from core.mailer import brand_name, default_from_email, get_smtp_connection
        from core.models import SystemSetting

        recipients = sched.recipients
        if isinstance(recipients, str):
            recipients = [r.strip()
                          for r in recipients.replace(';', ',').split(',')
                          if r.strip()]
        if not recipients:
            return 0
        system = SystemSetting.get_settings()
        connection = get_smtp_connection(system)
        if connection is None:
            return 0

        subject = f'[{brand_name(system)}] Scheduled report: {sched.name}'
        body = (
            f'Your scheduled report "{sched.name}" was generated at '
            f'{gen.created_at:%Y-%m-%d %H:%M %Z}.\n\nThe report is attached.'
        )
        mime = {
            'pdf': 'application/pdf',
            'csv': 'text/csv',
            'json': 'application/json',
        }.get((output_format or 'pdf').lower(), 'application/octet-stream')
        sent = 0
        # One message per recipient, so recipients don't see each other.
        for address in recipients:
            msg = EmailMessage(subject=subject, body=body,
                               from_email=default_from_email(system),
                               to=[address], connection=connection)
            msg.attach(filename, artifact_bytes, mime)
            sent += msg.send(fail_silently=False)
        return sent
