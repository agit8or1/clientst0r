"""Email notifications for expiring SSL certificates and domains.

Both scheduled tasks used to end at a `# TODO: Send email notifications`: they
counted what was expiring, wrote the count to the scheduler log, and returned
success. Enabled by default, they had reported a healthy green check every day
since they were written while sending nothing.

Three things the counting version also got wrong, fixed here:

* It excluded anything already expired (`expires_at__gte=now`), so the one state
  that actually takes a site down produced no notification at all.
* It read the global warning window and ignored the per-monitor
  `ssl_warning_days` / `domain_warning_days` and the per-item `warning_days`,
  which the edit forms present as if they meant something.
* It ignored the per-monitor `notify_on_ssl_expiry` / `notify_on_domain_expiry`
  opt-outs.

Re-notification is keyed rather than flagged. The key is
`"<expiry>:<phase>"`, so a renewed certificate — new expiry — re-arms its own
warning with nothing having to reset a flag, and crossing from `warning` into
`expired` re-arms it once more for the escalation. A daily task with a plain
"sent" boolean would otherwise go quiet for good after the first send.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from core.mailer import (
    brand_name,
    default_from_email,
    get_smtp_connection,
    notification_recipients,
    send_to_recipients,
    site_url,
)

logger = logging.getLogger('core')


class Due:
    """One thing that is expiring, flattened out of whichever model holds it."""

    def __init__(self, obj, key_field, org_id, label, expires_at, path, extra=''):
        self.obj = obj
        self.key_field = key_field
        self.org_id = org_id
        self.label = label
        self.expires_at = expires_at
        self.path = path
        self.extra = extra
        self.phase = 'expired' if expires_at < timezone.now() else 'warning'
        self.key = f'{expires_at.isoformat()}:{self.phase}'

    @property
    def already_notified(self):
        return getattr(self.obj, self.key_field, '') == self.key

    def describe(self):
        now = timezone.now()
        if self.phase == 'expired':
            # Elapsed time rounds down: 2.9 days ago is "2 days ago".
            days = (now - self.expires_at).days
            when = 'EXPIRED today' if days < 1 else f'EXPIRED {days} days ago'
            if days == 1:
                when = 'EXPIRED 1 day ago'
        else:
            # Remaining time rounds up, or a certificate with 4 days and 23
            # hours left reads as "expires in 4 days" — the plain subtraction
            # the counting version would have used truncates towards zero.
            remaining = self.expires_at - now
            days = -((-remaining.total_seconds()) // 86400)
            days = int(days)
            if days <= 1:
                when = 'expires within a day'
            else:
                when = f'expires in {days} days'
        detail = f' — {self.extra}' if self.extra else ''
        return f'{self.label} ({when}, {self.expires_at.date()}){detail}'


def _within_window(expires_at, warning_days, now):
    """Due if already expired, or inside its own warning window."""
    return expires_at <= now + timedelta(days=warning_days)


def collect_ssl_due(settings):
    """SSL certificates past, or inside, their monitor's warning window."""
    from monitoring.models import WebsiteMonitor

    now = timezone.now()
    global_days = int(getattr(settings, 'ssl_expiry_warning_days', 30) or 30)

    due = []
    monitors = WebsiteMonitor.objects.filter(
        ssl_enabled=True,
        notify_on_ssl_expiry=True,
        ssl_expires_at__isnull=False,
    ).select_related('organization')

    for m in monitors:
        # The per-monitor window is the one the monitor's own edit form sets.
        # The global setting is the default for monitors that have never been
        # given one, so the larger of the two is the safe reading: it warns no
        # later than either setting asked for.
        warning_days = max(int(m.ssl_warning_days or 0), global_days)
        if not _within_window(m.ssl_expires_at, warning_days, now):
            continue
        due.append(Due(
            obj=m,
            key_field='ssl_expiry_notified_key',
            org_id=m.organization_id,
            label=f'{m.name} — SSL certificate',
            expires_at=m.ssl_expires_at,
            path=f'/monitoring/websites/{m.pk}/',
            extra=m.ssl_issuer or '',
        ))
    return due


def collect_domain_due(settings):
    """Domains from both places the application tracks them.

    `Expiration` rows of type 'domain' are the ones entered by hand on the
    Expirations page. `WebsiteMonitor.domain_expires_at` is the WHOIS column;
    nothing populates it automatically today, but it is writable over the API
    and through the monitor form, and a date someone entered there should not be
    silently ignored.
    """
    from monitoring.models import Expiration, WebsiteMonitor

    now = timezone.now()
    global_days = int(getattr(settings, 'domain_expiry_warning_days', 30) or 30)

    due = []

    for e in Expiration.objects.filter(
        expiration_type='domain', expires_at__isnull=False,
    ).select_related('organization'):
        warning_days = max(int(e.warning_days or 0), global_days)
        if not _within_window(e.expires_at, warning_days, now):
            continue
        due.append(Due(
            obj=e,
            key_field='notification_key',
            org_id=e.organization_id,
            label=f'{e.name} — domain registration',
            expires_at=e.expires_at,
            path='/monitoring/expirations/',
            extra='auto-renew is on' if e.auto_renew else '',
        ))

    for m in WebsiteMonitor.objects.filter(
        notify_on_domain_expiry=True, domain_expires_at__isnull=False,
    ).select_related('organization'):
        warning_days = max(int(m.domain_warning_days or 0), global_days)
        if not _within_window(m.domain_expires_at, warning_days, now):
            continue
        due.append(Due(
            obj=m,
            key_field='domain_expiry_notified_key',
            org_id=m.organization_id,
            label=f'{m.name} — domain registration',
            expires_at=m.domain_expires_at,
            path=f'/monitoring/websites/{m.pk}/',
            extra=m.domain_registrar or '',
        ))

    return due


def _mark_notified(items):
    """Persist the notification key, and the legacy flag where one exists."""
    for item in items:
        setattr(item.obj, item.key_field, item.key)
        fields = [item.key_field]
        if hasattr(item.obj, 'notification_sent'):
            item.obj.notification_sent = True
            fields.append('notification_sent')
        item.obj.save(update_fields=fields)


def _plural(n, word):
    return f'{n} {word}{"s" if n != 1 else ""}'


def notify(kind, due, settings, log=None, review_path='/monitoring/websites/'):
    """Email the outstanding items in `due`, grouped by organization.

    Returns a {'due', 'notified', 'skipped'} count dict. `skipped` covers items
    whose notification has already gone out for this expiry and phase.
    """
    def say(msg):
        if log:
            log(msg)

    counts = {'due': len(due), 'notified': 0, 'skipped': 0}

    outstanding = []
    for item in due:
        if item.already_notified:
            counts['skipped'] += 1
        else:
            outstanding.append(item)

    if not outstanding:
        say(f'    No new {kind} expiry notifications '
            f'({counts["due"]} within the warning window, all already sent)')
        return counts

    connection = get_smtp_connection(settings)
    if connection is None:
        # Deliberately not marked as notified: nothing was sent, so the next run
        # with SMTP working should still send it.
        say(f'    SMTP not configured — {len(outstanding)} {kind} expiry '
            f'notification(s) not sent')
        return counts

    from_email = default_from_email(settings)
    base = site_url(settings)
    brand = brand_name(settings)

    by_org = {}
    for item in outstanding:
        by_org.setdefault(item.org_id, []).append(item)

    for org_id, items in by_org.items():
        recipients = notification_recipients(org_id)
        if not recipients:
            say(f'    No recipients for organization {org_id} — '
                f'{len(items)} {kind} notification(s) not sent')
            continue

        items.sort(key=lambda i: i.expires_at)
        org_name = getattr(items[0].obj.organization, 'name', None) or 'Global'
        expired = [i for i in items if i.phase == 'expired']

        headline = _plural(len(items), kind)
        if expired:
            subject = f'[{brand}] {_plural(len(expired), kind)} EXPIRED — {org_name}'
        else:
            subject = f'[{brand}] {headline} expiring — {org_name}'

        lines = [f'{headline} tracked for {org_name} need attention:', '']
        for item in items:
            lines.append(f'  • {item.describe()}')
            lines.append(f'      → {base}{item.path}' if base else f'      → {item.path}')
        lines.append('')
        lines.append(f'Review: {base}{review_path}' if base else f'Review: {review_path}')
        body = '\n'.join(lines)

        sent = send_to_recipients(connection, from_email, recipients, subject, body)
        if sent:
            _mark_notified(items)
            counts['notified'] += len(items)
            say(f'    Notified {sent} recipient(s) about {len(items)} '
                f'{kind}(s) for {org_name}')
        else:
            say(f'    No recipient accepted the {kind} notification for {org_name}')

    return counts


def check_ssl_expiry(settings, log=None):
    if not settings.notify_on_ssl_expiry:
        if log:
            log('    SSL expiry notifications disabled — skipping')
        return {'due': 0, 'notified': 0, 'skipped': 0}
    return notify('SSL certificate', collect_ssl_due(settings), settings, log=log)


def check_domain_expiry(settings, log=None):
    if not settings.notify_on_domain_expiry:
        if log:
            log('    Domain expiry notifications disabled — skipping')
        return {'due': 0, 'notified': 0, 'skipped': 0}
    return notify(
        'domain', collect_domain_due(settings), settings, log=log,
        review_path='/monitoring/expirations/',
    )
