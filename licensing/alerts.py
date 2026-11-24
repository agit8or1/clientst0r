"""License alerts: renewals within 30/60/90 days, unused licenses and
over-allocation.

`collect_alerts` is pure (what is true right now, used by the dashboard).
`send_alerts` mails it and records each condition in LicenseAlertLog so the
same condition is sent once: a renewal once per (renewal date, window), the
utilization conditions once per (purchased, assigned, calendar month).
Mail goes to MSP staff who hold manage_licensing for the customer; no cost
figure is ever put in a message.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from django.core.mail import send_mail
from django.utils import timezone

from .models import LicenseAlertLog, LicenseSubscription

WINDOWS = (30, 60, 90)


@dataclass(frozen=True)
class Alert:
    kind: str            # renewal / unused / over_allocated
    subscription: LicenseSubscription
    key: str
    text: str


def renewal_window(days):
    """The smallest of 30/60/90 that covers `days`, or None."""
    if days is None or days < 0:
        return None
    for w in WINDOWS:
        if days <= w:
            return w
    return None


def live_subscriptions(qs=None):
    qs = LicenseSubscription.objects.all() if qs is None else qs
    return qs.filter(status__in=LicenseSubscription.LIVE_STATUSES).select_related(
        'organization', 'product').prefetch_related('assignments')


def collect_alerts(qs=None, today=None):
    today = today or timezone.localdate()
    out = []
    month = today.strftime('%Y-%m')
    for sub in live_subscriptions(qs):
        name = f'{sub.product} ({sub.quantity_purchased} licenses)'
        if sub.renewal_date:
            days = (sub.renewal_date - today).days
            w = renewal_window(days)
            if w is not None:
                renew = 'auto-renews' if sub.auto_renew else 'does NOT auto-renew'
                out.append(Alert('renewal', sub, f'{sub.renewal_date.isoformat()}:{w}',
                                 f'{name} renews {sub.renewal_date.isoformat()} ({days} days; {renew})'))
        if sub.has_usage_data:
            if sub.over_allocated:
                out.append(Alert('over_allocated', sub, f'{sub.quantity_purchased}:{sub.assigned}:{month}',
                                 f'{name}: {sub.assigned} assigned, {sub.over_allocated} over what is purchased'))
            elif sub.available:
                out.append(Alert('unused', sub, f'{sub.quantity_purchased}:{sub.assigned}:{month}',
                                 f'{name}: {sub.available} of {sub.quantity_purchased} unused '
                                 f'({sub.utilization_pct}% in use)'))
    return out


def recipients(org):
    """Active MSP staff with an e-mail address who may manage licensing for `org`."""
    from django.contrib.auth import get_user_model
    from accounts.permission_utils import is_msp_staff, user_has_org_perm
    out = []
    for u in get_user_model().objects.filter(is_active=True).exclude(email=''):
        if is_msp_staff(u) or u.is_superuser:
            if user_has_org_perm(u, org, 'manage_licensing'):
                out.append(u.email)
    return out


def send_alerts(*, dry_run=False, today=None, qs=None):
    """Mail new alerts, one digest per customer. Returns
    {'orgs': n, 'alerts': n, 'sent': n}."""
    pending = []
    for a in collect_alerts(qs, today):
        if not LicenseAlertLog.objects.filter(subscription=a.subscription, kind=a.kind, key=a.key).exists():
            pending.append(a)
    per_org = defaultdict(list)
    for a in pending:
        per_org[a.subscription.organization].append(a)
    sent = 0
    for org, alerts in per_org.items():
        to = recipients(org)
        if not to:
            continue
        if dry_run:
            sent += 1
            continue
        lines = [f'Software license notices for {org.name}:', '']
        for title, kind in (('Upcoming renewals', 'renewal'), ('Unused licenses', 'unused'),
                            ('Over-allocated', 'over_allocated')):
            rows = [a for a in alerts if a.kind == kind]
            if rows:
                lines.append(title)
                lines += [f'  - {a.text}' for a in rows]
                lines.append('')
        lines.append('Open Licensing in Clientst0r to review or reassign.')
        try:
            send_mail(f'[{org.name}] {len(alerts)} software license notice(s)', '\n'.join(lines),
                      None, to, fail_silently=False)
        except Exception:
            continue
        sent += 1
        for a in alerts:
            LicenseAlertLog.objects.get_or_create(subscription=a.subscription, kind=a.kind, key=a.key)
    return {'orgs': len(per_org), 'alerts': len(pending), 'sent': sent}
