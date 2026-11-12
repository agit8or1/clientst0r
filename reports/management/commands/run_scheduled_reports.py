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
        from core.feature_gates import feature_on
        from reports.models import ScheduledReport
        if not feature_on('reports_enabled'):
            # Settings -> Features -> Reports & Analytics is off: nothing is
            # generated or emailed, and next_run is left alone so schedules
            # pick up again when it is turned back on.
            self.stdout.write('Reports & Analytics is turned off; no scheduled reports run.')
            return
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
            refusal = self._owner_refusal(sched)
            if refusal:
                # A delayed run acts on its creator's authority: recheck it now.
                # The schedule is paused rather than retried every tick.
                sched.is_active = False
                sched.save(update_fields=['is_active'])
                self.stderr.write(f'  x {sched.name} paused: {refusal}')
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

    @staticmethod
    def _owner_refusal(sched):
        """Why the schedule's creator may no longer have it run, or ''.

        Reports are MSP tooling (/reports/ is staff-only); the creator must
        still be an active MSP staff account holding reports_manage_scheduled
        for the schedule's customer. Schedules without a recorded creator
        are left as they were (no person to recheck)."""
        user = sched.created_by
        if user is None:
            return ''
        if not user.is_active:
            return f'its creator {user.username} is deactivated'
        from psa.visibility import is_msp_staff
        if not is_msp_staff(user):
            return f'its creator {user.username} is no longer MSP staff'
        from accounts.permission_utils import has_perm_for_org
        if not has_perm_for_org(user, sched.organization_id, 'reports_manage_scheduled'):
            return f'its creator {user.username} no longer manages scheduled reports for this customer'
        return ''

    def _run_one(self, sched):
        from django.core.files.base import ContentFile
        from reports.generators import generate_report
        from reports.models import GeneratedReport

        output_format = (sched.output_format or 'pdf').lower()

        # The schedule acts for whoever set it up, so that person's access is
        # checked again now, not only when they saved the form: a role or
        # membership change since then, or a deactivated account, stops the
        # report instead of e-mailing data its creator may no longer see.
        refusal, parameters = self._authorize(sched)
        if refusal:
            GeneratedReport.objects.create(
                template=sched.template, scheduled_report=sched,
                organization=sched.organization, generated_by=None,
                format=self._normalize_format(output_format), status='failed',
                parameters=parameters, error_message=refusal[:2000],
            )
            self.stderr.write(f'  ! {sched.name}: {refusal}')
            sched.last_run = timezone.now()
            sched.next_run = self._next_run(sched, sched.last_run)
            sched.save(update_fields=['last_run', 'next_run'])
            return

        # Generate the artifact (filename + bytes)
        filename, artifact_bytes = generate_report(
            template=sched.template,
            output_format=output_format,
            organization=sched.organization,
            parameters=parameters,
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
            parameters=parameters,
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

    # Report types whose data is sensitive enough that a schedule nobody
    # owns (creator deleted, or added through the Django admin) won't run.
    OWNERLESS_REFUSED_TYPES = ('password_audit', 'user_activity')

    @classmethod
    def _authorize(cls, sched):
        """(refusal message or None, parameters to generate with).

        With a creator: they must still be active, hold
        reports_manage_scheduled, and hold the report type's view flag for
        the schedule's customer; vault figures follow their vault_view.
        Without one there is no person to check, so the report runs as a
        restricted service identity: no vault figures, and the most
        sensitive types are refused."""
        from accounts.permission_utils import has_perm_for_org, user_has_org_perm
        from reports.access import may_see_report_type, report_type_perm

        params = dict(sched.parameters or {})
        org = sched.organization
        rtype = getattr(sched.template, 'report_type', '')
        creator = sched.created_by
        if creator is None:
            params['include_vault'] = False
            if rtype in cls.OWNERLESS_REFUSED_TYPES:
                return ('Not run: this schedule has no owner, and a '
                        f'"{rtype}" report needs a person whose access can be checked.'), params
            return None, params
        if not creator.is_active:
            return f'Not run: {creator.username} is no longer active.', params

        def holds(flag):
            return (has_perm_for_org(creator, org, flag)
                    or user_has_org_perm(creator, org, flag))

        if not holds('reports_manage_scheduled'):
            return (f"Not run: {creator.username} no longer has the "
                    "'reports_manage_scheduled' permission for this customer."), params
        if not may_see_report_type(creator, rtype, org):
            return (f"Not run: {creator.username} no longer has the "
                    f"'{report_type_perm(rtype)}' permission for this customer."), params
        params['include_vault'] = holds('vault_view')
        return None, params

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
