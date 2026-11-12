"""Phase 9.4: weekly e-mail digest of unresolved security alerts for a
customer's opted-in contacts.

What goes into a digest is decided here and only here (`digest_rows`), so the
customer-facing content stays narrow: severity, the alert title, the device
it named, when it was first seen and whether someone is on it. Never the
vendor payload, the description, the vendor connection, internal rules,
tickets or who acknowledged it.

Alerts belong to a customer when pinned to it (`client_org`), or when not
pinned to any client and ingested into the customer's own organization.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core import signing
from django.core.mail import EmailMessage
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.mailer import brand_name, default_from_email, get_smtp_connection, site_url

logger = logging.getLogger('security_alerts')

UNSUBSCRIBE_SALT = 'security_alerts.digest.unsubscribe'
UNRESOLVED = ('new', 'acknowledged')
SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
# A digest already sent in the last six days is not sent again, so a manual
# run (or a rescheduled task) cannot mail the same customer twice in a week.
MIN_INTERVAL = timedelta(days=6)
MAX_ROWS = 50


def customer_alerts(org):
    from .models import SecurityAlert
    return (SecurityAlert.objects
            .filter(Q(client_org=org) | Q(client_org__isnull=True, organization=org))
            .filter(status__in=UNRESOLVED))


def digest_rows(org):
    """The customer-safe rows for `org`, most severe first."""
    rows = []
    for a in customer_alerts(org).only('severity', 'title', 'asset_hint', 'seen_at', 'status'):
        rows.append({
            'severity': a.severity,
            'severity_label': a.get_severity_display(),
            'title': (a.title or '')[:200],
            'device': (a.asset_hint or '')[:120],
            'first_seen': a.seen_at,
            'state': 'Being investigated' if a.status == 'acknowledged' else 'Open',
        })
    rows.sort(key=lambda r: (SEVERITY_ORDER.get(r['severity'], 9), r['first_seen']))
    return rows


def unsubscribe_token(sub):
    return signing.dumps({'s': sub.pk, 'e': sub.email.lower()}, salt=UNSUBSCRIBE_SALT, compress=True)


def subscription_for_token(token):
    from .models import SecurityDigestSubscription
    try:
        data = signing.loads(token or '', salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None
    sub = SecurityDigestSubscription.objects.filter(pk=data.get('s')).select_related('organization').first()
    if sub is None or sub.email.lower() != data.get('e'):
        return None
    return sub


def unsubscribe_url(sub, base=''):
    return f'{base}{reverse("security_alerts:digest_unsubscribe", kwargs={"token": unsubscribe_token(sub)})}'


def render_digest(org, rows, *, brand, unsubscribe):
    counts = {}
    for r in rows:
        counts[r['severity_label']] = counts.get(r['severity_label'], 0) + 1
    summary = ', '.join(f'{n} {label.lower()}' for label, n in
                        sorted(counts.items(), key=lambda kv: SEVERITY_ORDER.get(kv[0].lower(), 9)))
    lines = [
        f'Security alerts for {org.name} that are not resolved yet ({len(rows)}: {summary}).',
        '',
    ]
    for r in rows[:MAX_ROWS]:
        device = f' on {r["device"]}' if r['device'] else ''
        lines.append(f'- [{r["severity_label"]}] {r["title"]}{device} — first seen '
                     f'{timezone.localtime(r["first_seen"]):%Y-%m-%d}, {r["state"].lower()}')
    if len(rows) > MAX_ROWS:
        lines.append(f'...and {len(rows) - MAX_ROWS} more.')
    lines += [
        '',
        f'Your {brand} team is notified of each of these already; this weekly summary is for your records.',
        '',
        'You receive this because you opted in to the weekly security alert digest.',
        f'Stop these e-mails: {unsubscribe}',
    ]
    subject = f'[{brand}] Weekly security alert digest — {org.name}: {len(rows)} unresolved'
    return subject, '\n'.join(lines)


def render_all_clear(org, *, brand, unsubscribe):
    """The short weekly note for a customer that opted in to all-clear mails."""
    lines = [
        f'There are no unresolved security alerts for {org.name} this week.',
        '',
        f'Your {brand} team checks these continuously; this note confirms the '
        'weekly digest ran and found nothing open.',
        '',
        'You receive this because you opted in to the weekly security alert digest.',
        f'Stop these e-mails: {unsubscribe}',
    ]
    subject = f'[{brand}] Weekly security alert digest \u2014 {org.name}: all clear'
    return subject, '\n'.join(lines)


def send_digests(*, org=None, dry_run=False, force=False, now=None, connection=None, stdout=None):
    """Send each opted-in contact their customer's digest. Returns a dict of counts.

    Customers with nothing unresolved get no e-mail. Without a usable SMTP
    configuration nothing is sent and the run says so."""
    from core.models import SystemSetting
    from .models import SecurityDigestCustomerSetting, SecurityDigestSubscription

    now = now or timezone.now()
    ss = SystemSetting.get_settings()
    out = {'customers': 0, 'sent': 0, 'all_clear': 0, 'skipped_recent': 0, 'empty': 0, 'failed': 0,
           'no_smtp': False}
    subs = (SecurityDigestSubscription.objects
            .filter(is_subscribed=True, organization__is_active=True)
            .select_related('organization').order_by('organization_id', 'email'))
    if org is not None:
        subs = subs.filter(organization=org)
    subs = list(subs)
    if not subs:
        return out

    if connection is None and not dry_run:
        connection = get_smtp_connection(ss)
        if connection is None:
            out['no_smtp'] = True
            return out
    brand = brand_name(ss)
    # Sent to customers: links go to the portal host when one is set.
    from core.portal_surface import portal_site_url
    base = portal_site_url(ss)
    from_email = default_from_email(ss)

    all_clear_orgs = set(SecurityDigestCustomerSetting.objects.filter(
        send_all_clear=True, organization_id__in={s.organization_id for s in subs},
    ).values_list('organization_id', flat=True))

    by_org = {}
    for s in subs:
        by_org.setdefault(s.organization_id, []).append(s)
    for org_subs in by_org.values():
        customer = org_subs[0].organization
        rows = digest_rows(customer)
        out['customers'] += 1
        if not rows:
            out['empty'] += 1
            if customer.pk not in all_clear_orgs:
                continue
        for sub in org_subs:
            if not force and sub.last_sent_at and now - sub.last_sent_at < MIN_INTERVAL:
                out['skipped_recent'] += 1
                continue
            unsub = unsubscribe_url(sub, base)
            if rows:
                subject, body = render_digest(customer, rows, brand=brand, unsubscribe=unsub)
            else:
                subject, body = render_all_clear(customer, brand=brand, unsubscribe=unsub)
            if dry_run:
                out['sent'] += 1
                if not rows:
                    out['all_clear'] += 1
                if stdout:
                    stdout.write(f'[dry-run] {sub.email}: {subject}')
                continue
            msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[sub.email],
                               connection=connection,
                               headers={'List-Unsubscribe': f'<{unsub}>',
                                        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'})
            try:
                msg.send(fail_silently=False)
            except Exception as exc:
                out['failed'] += 1
                logger.warning('security digest to %s failed: %s', sub.email, exc)
                continue
            sub.last_sent_at = now
            sub.save(update_fields=['last_sent_at'])
            out['sent'] += 1
            if not rows:
                out['all_clear'] += 1
    return out
