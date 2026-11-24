"""Send compliance-recertification reminder emails.

Run daily via cron. Idempotent + 7-day dedup so techs aren't spammed.

For each `OrganizationCompliance` with `recertification_emails_enabled=True`:
- Compute `recertification_due_at` (= last_recertified_at + interval; or
  enrolled_at + interval if never recertified).
- If now() >= recertification_due_at AND no `RecertificationReminder` row
  exists for this enrollment in the last 7 days, send the email and
  log a `RecertificationReminder` row.
- Email goes to `OrganizationCompliance.notify_email` if set, else to
  the org's primary admin (via the Membership table — `role='owner'`
  or 'admin'), else falls back to the project's DEFAULT_FROM_EMAIL.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from compliance.models import (
    OrganizationCompliance, RecertificationReminder,
)


def _resolve_recipient(oc):
    """Pick the best email address to remind."""
    if oc.notify_email:
        return oc.notify_email
    # Try the first owner/admin Membership for the org.
    try:
        from accounts.models import Membership
        m = (Membership.objects
             .filter(organization=oc.organization, is_active=True,
                     role__in=['owner', 'admin'])
             .select_related('user')
             .order_by('id')
             .first())
        if m and m.user.email:
            return m.user.email
    except Exception:
        pass
    return getattr(settings, 'DEFAULT_FROM_EMAIL', '') or ''


def _build_email(oc):
    org = oc.organization
    fw = oc.framework
    days = oc.days_until_recertification
    if days < 0:
        timing = f'is overdue by {abs(days)} days'
    elif days == 0:
        timing = 'is due today'
    else:
        timing = f'is due in {days} days'

    subject = (
        f'[{fw.name}] Recertification {timing} for {org.name}'
    )
    site_url = getattr(settings, 'SITE_URL', '') or ''
    checklist_path = reverse(
        'compliance:checklist',
        kwargs={'org_id': org.pk, 'framework_slug': fw.slug},
    )
    checklist_url = f'{site_url}{checklist_path}' if site_url else checklist_path
    body = (
        f'Hi,\n\n'
        f'This is an automated reminder that the {fw.name} {fw.version} '
        f'compliance attestation for {org.name} {timing}.\n\n'
        f'Open the checklist:\n'
        f'  {checklist_url}\n\n'
        f'Walk through every control, set the appropriate status, attach '
        f'evidence, then click "Mark recertified now" on the dashboard '
        f'when finished. The next reminder will fire after another '
        f'{oc.recertification_interval_days} days.\n\n'
        f'— Clientst0r compliance scheduler\n'
    )
    return subject, body


class Command(BaseCommand):
    help = (
        'Send compliance recertification reminder emails. '
        'Run daily via cron. Idempotent + 7-day dedup.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Identify enrollments due for reminder; do not send email or write RecertificationReminder rows.',
        )

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        sent = 0
        skipped_dedup = 0
        not_due = 0
        no_recipient = 0
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)

        for oc in OrganizationCompliance.objects.filter(
                recertification_emails_enabled=True,
        ).select_related('organization', 'framework'):
            due_at = oc.recertification_due_at
            if now < due_at:
                not_due += 1
                continue

            recent = RecertificationReminder.objects.filter(
                org_compliance=oc, sent_at__gte=seven_days_ago,
            ).exists()
            if recent:
                skipped_dedup += 1
                continue

            recipient = _resolve_recipient(oc)
            if not recipient:
                no_recipient += 1
                self.stderr.write(self.style.WARNING(
                    f'No recipient resolvable for {oc.organization} :: '
                    f'{oc.framework.name} — skipping.'
                ))
                continue

            subject, body = _build_email(oc)
            if not dry:
                send_mail(
                    subject=subject, message=body,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    recipient_list=[recipient],
                    fail_silently=False,
                )
                RecertificationReminder.objects.create(
                    org_compliance=oc, recipient_email=recipient,
                )
            sent += 1
            self.stdout.write(
                f'{"[dry-run] " if dry else ""}Reminded {recipient} '
                f'for {oc.organization} :: {oc.framework.name} '
                f'(due {due_at:%Y-%m-%d})'
            )

        self.stdout.write(self.style.SUCCESS(
            f'\nSummary: {sent} sent · {skipped_dedup} skipped (7-day dedup) '
            f'· {not_due} not yet due · {no_recipient} no recipient.'
        ))
