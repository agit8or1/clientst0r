"""
Management command to send email/SMS alerts for upcoming and overdue scheduled tasks.

Runs periodically via the core task scheduler (task_type='scheduling_alerts').

Alert logic:
  - Upcoming: task is pending/in_progress, due within alert_before_hours, and either
    no alert has been sent yet OR the previous alert was sent more than alert_before_hours/2
    ago (so a re-alert fires when very close to due).
  - Overdue: task is pending/in_progress and past due_date — alert once, then every 24h.
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail, get_connection

logger = logging.getLogger('core')


def _get_task_url(task, site_url=''):
    """Build an absolute URL to the task detail page."""
    from django.urls import reverse
    path = reverse('scheduling:task_detail', kwargs={'pk': task.pk})
    base = site_url.rstrip('/') if site_url else ''
    return f'{base}{path}'


def _get_smtp_connection(settings):
    """Return a configured SMTP connection or None if SMTP not set up."""
    if not settings.smtp_enabled or not settings.smtp_host:
        return None
    # EncryptedTextField: the attribute is already the plaintext.
    password = settings.smtp_password or ''

    return get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=password,
        use_tls=settings.smtp_use_tls,
        use_ssl=settings.smtp_use_ssl,
        timeout=15,
    )


def _send_task_email(connection, from_email, recipient, subject, body):
    """Send a single alert email; return True on success."""
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[recipient],
            connection=connection,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f'[scheduling_alerts] Email to {recipient} failed: {e}')
        return False


def _send_task_sms(to_number, message):
    """Send an SMS alert; return True on success."""
    from core.sms import send_sms
    if not to_number:
        return False
    result = send_sms(to_number, message)
    return result.get('success', False)


def _build_email_body(task, task_url, alert_type):
    """Build plain-text email body for a task alert."""
    status_label = 'OVERDUE' if alert_type == 'overdue' else 'UPCOMING'
    due_str = task.due_date.strftime('%Y-%m-%d %H:%M UTC') if task.due_date else 'No due date set'

    lines = [
        f'Task Alert: {status_label}',
        '',
        f'Task:     {task.title}',
        f'Priority: {task.get_priority_display()}',
        f'Status:   {task.get_status_display()}',
        f'Due:      {due_str}',
        f'Org:      {task.organization.name}',
    ]

    if task.description:
        lines += ['', 'Description:', task.description[:500]]

    if task.psa_ticket:
        ticket = task.psa_ticket
        ticket_ref = ticket.ticket_number or ticket.external_id
        lines += ['', f'Linked Ticket: #{ticket_ref} — {ticket.subject}']

    lines += [
        '',
        f'View task: {task_url}',
        '(You will need to log in if not already signed in.)',
        '',
        '---',
        'Client St0r — Automated Scheduling Alert',
    ]
    return '\n'.join(lines)


def _build_sms_body(task, task_url, alert_type):
    """Build short SMS body for a task alert."""
    status_label = 'OVERDUE' if alert_type == 'overdue' else 'DUE SOON'
    due_str = task.due_date.strftime('%m/%d %H:%M') if task.due_date else '?'
    msg = f'[{status_label}] {task.title} — due {due_str}. View: {task_url}'
    if task.psa_ticket:
        ticket_ref = task.psa_ticket.ticket_number or task.psa_ticket.external_id
        msg += f' (Ticket #{ticket_ref})'
    return msg[:160]


class Command(BaseCommand):
    help = 'Send email/SMS alerts for upcoming and overdue scheduled tasks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be sent without actually sending'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        from core.models import SystemSetting
        from scheduling.models import ScheduledTask

        sys_settings = SystemSetting.get_settings()
        site_url = sys_settings.site_url or ''

        smtp_conn = None
        if not dry_run:
            smtp_conn = _get_smtp_connection(sys_settings)

        from_email = None
        if sys_settings.smtp_from_name and sys_settings.smtp_from_email:
            from_email = f'{sys_settings.smtp_from_name} <{sys_settings.smtp_from_email}>'
        elif sys_settings.smtp_from_email:
            from_email = sys_settings.smtp_from_email

        now = timezone.now()
        sent_count = 0
        skip_count = 0

        # --- Upcoming tasks ------------------------------------------------
        # Tasks that are pending/in_progress with a future due_date within alert window
        active_statuses = ['pending', 'in_progress']
        upcoming_tasks = ScheduledTask.objects.filter(
            status__in=active_statuses,
            alert_email=True,  # check at least one alert type is on
            due_date__gt=now,
        ).select_related('organization', 'psa_ticket').prefetch_related(
            'task_assignments__user__profile'
        )

        for task in upcoming_tasks:
            # Only alert if due within the configured window
            alert_window = timedelta(hours=task.alert_before_hours)
            if task.due_date > now + alert_window:
                continue  # too far away

            # Avoid re-sending if we already alerted recently (within half the window,
            # minimum 1 hour)
            if task.last_alert_sent_at:
                resend_after = max(alert_window / 2, timedelta(hours=1))
                if now < task.last_alert_sent_at + resend_after:
                    skip_count += 1
                    continue

            sent = self._alert_task(
                task, 'upcoming', site_url, smtp_conn, from_email,
                sys_settings, dry_run
            )
            if sent:
                sent_count += 1
                if not dry_run:
                    task.last_alert_sent_at = now
                    task.save(update_fields=['last_alert_sent_at'])

        # --- Overdue tasks -------------------------------------------------
        overdue_tasks = ScheduledTask.objects.filter(
            status__in=active_statuses,
            due_date__lt=now,
        ).select_related('organization', 'psa_ticket').prefetch_related(
            'task_assignments__user__profile'
        )

        for task in overdue_tasks:
            # Alert once, then re-alert every 24h
            if task.last_alert_sent_at:
                if now < task.last_alert_sent_at + timedelta(hours=24):
                    skip_count += 1
                    continue

            sent = self._alert_task(
                task, 'overdue', site_url, smtp_conn, from_email,
                sys_settings, dry_run
            )
            if sent:
                sent_count += 1
                if not dry_run:
                    task.last_alert_sent_at = now
                    task.save(update_fields=['last_alert_sent_at'])

        verb = '[DRY RUN] Would send' if dry_run else 'Sent'
        self.stdout.write(
            self.style.SUCCESS(
                f'{verb} {sent_count} alert(s); {skip_count} skipped (recently alerted)'
            )
        )

    def _alert_task(self, task, alert_type, site_url, smtp_conn, from_email,
                    sys_settings, dry_run):
        """Send alerts for a single task to all assigned users. Returns True if any sent."""
        task_url = _get_task_url(task, site_url)
        email_body = _build_email_body(task, task_url, alert_type)
        sms_body = _build_sms_body(task, task_url, alert_type)

        status_label = 'OVERDUE' if alert_type == 'overdue' else 'Due Soon'
        subject = f'[{task.organization.name}] Task {status_label}: {task.title}'

        assignments = task.task_assignments.all()
        if not assignments.exists():
            # Fall back to task creator
            if task.created_by and task.created_by.email:
                assignments = None  # handled below
            else:
                return False

        any_sent = False

        if assignments is None:
            # Creator only
            recipients = [(task.created_by, getattr(task.created_by, 'profile', None))]
        else:
            recipients = [(a.user, getattr(a.user, 'profile', None)) for a in assignments]

        for user, profile in recipients:
            # Email
            if task.alert_email and user.email and smtp_conn and from_email:
                if dry_run:
                    self.stdout.write(
                        f'  [DRY RUN] Email to {user.email}: {subject}'
                    )
                    any_sent = True
                else:
                    ok = _send_task_email(smtp_conn, from_email, user.email, subject, email_body)
                    if ok:
                        any_sent = True
                        logger.info(
                            f'[scheduling_alerts] Email sent to {user.email} for task #{task.pk}'
                        )

            # SMS
            if task.alert_sms and profile:
                phone = getattr(profile, 'phone', '')
                if phone:
                    # Normalise phone to E.164 if needed
                    if not phone.startswith('+'):
                        self.stdout.write(
                            f'  Skipping SMS for {user.username}: phone not in E.164 format ({phone})'
                        )
                    elif dry_run:
                        self.stdout.write(f'  [DRY RUN] SMS to {phone}: {sms_body}')
                        any_sent = True
                    else:
                        ok = _send_task_sms(phone, sms_body)
                        if ok:
                            any_sent = True
                            logger.info(
                                f'[scheduling_alerts] SMS sent to {phone} for task #{task.pk}'
                            )

        return any_sent
