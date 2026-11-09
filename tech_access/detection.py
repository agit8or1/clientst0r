"""
Read-only theft detection.

A stolen technician session doesn't need to change anything to do damage:
reading every ticket of every customer, or exporting them, is enough. This
counts, per identity and across the web UI, the REST API and the mobile API:

  tickets            distinct tickets opened
  customers          distinct customers whose tickets were opened
  exports            distinct file downloads (attachment responses)
  diagnostic_bytes   diagnostic output received through rem0te

over a short (1 hour) and a long (24 hour) window. Crossing a threshold
raises a TheftAlert and, depending on the technician's level, contains
them (Containment): every optional capability turns off, exports are
refused, and only tickets assigned to them still open. An administrator
lifts containment.

On by default. Alerts name the identity, rule, count and customers only —
never ticket text, comments or secrets.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

logger = logging.getLogger('tech_access')

WINDOWS = {'1h': timedelta(hours=1), '24h': timedelta(hours=24)}
DEFAULT_THRESHOLDS = {
    'tickets': {'1h': 150, '24h': 600},
    'customers': {'1h': 15, '24h': 40},
    'exports': {'1h': 10, '24h': 30},
    'diagnostic_bytes': {'1h': 50 * 1024 * 1024, '24h': 200 * 1024 * 1024},
}
DEFAULT_CONTAINMENT = {'0': 'contain', '1': 'contain', '2': 'contain', '3': 'contain'}
RULE_LABELS = {'tickets': 'distinct tickets read', 'customers': 'distinct customers read',
               'exports': 'exports', 'diagnostic_bytes': 'diagnostic bytes received'}


def thresholds(settings_obj=None):
    from .models import DetectionSettings
    s = settings_obj or DetectionSettings.load()
    out = {rule: dict(windows) for rule, windows in DEFAULT_THRESHOLDS.items()}
    for rule, windows in (s.thresholds or {}).items():
        if rule in out and isinstance(windows, dict):
            for w, v in windows.items():
                if w in WINDOWS:
                    try:
                        out[rule][w] = max(1, int(v))
                    except (TypeError, ValueError):
                        pass
    return out


def containment_mode(level, settings_obj=None) -> str:
    from .models import DetectionSettings
    s = settings_obj or DetectionSettings.load()
    modes = dict(DEFAULT_CONTAINMENT, **{str(k): v for k, v in (s.containment or {}).items()})
    return 'alert' if modes.get(str(level)) == 'alert' else 'contain'


def loosens(current, values) -> list:
    """Which proposed detection settings are looser than today's."""
    out = []
    if 'enabled' in values and current.enabled and not values['enabled']:
        out.append('detection disabled')
    now_t, new_t = thresholds(current), dict(thresholds(current))
    for rule, windows in (values.get('thresholds') or {}).items():
        for w, v in (windows or {}).items():
            if rule in now_t and w in WINDOWS and int(v) > now_t[rule][w]:
                out.append(f'{rule} {w} threshold raised')
    if 'containment' in values:
        for level, mode in values['containment'].items():
            if mode == 'alert' and containment_mode(level, current) == 'contain':
                out.append(f'level {level} alert-only')
    if 'notify_customers' in values and current.notify_customers and not values['notify_customers']:
        out.append('customer reports off')
    if 'recipients' in values:
        before = {r.strip().lower() for r in (current.recipients or '').splitlines() if r.strip()}
        after = {r.strip().lower() for r in (values['recipients'] or '').splitlines() if r.strip()}
        if before - after:
            out.append('alert recipients removed')
    return out


def _hour(now):
    return now.replace(minute=0, second=0, microsecond=0)


def record(user, kind, key, organization_id=None, channel='ui', amount=0, now=None):
    """Count one read. Returns the alerts it raised (usually none)."""
    from .models import DetectionSettings, ReadEvent
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    s = DetectionSettings.load()
    if not s.enabled:
        return []
    now = now or timezone.now()
    hour = _hour(now)
    key = str(key)[:64]
    try:
        with transaction.atomic():
            ev, created = ReadEvent.objects.get_or_create(
                user=user, kind=kind, key=key, hour=hour,
                defaults={'organization_id': organization_id, 'channel': channel, 'amount': amount})
    except IntegrityError:
        ev, created = ReadEvent.objects.get(user=user, kind=kind, key=key, hour=hour), False
    if not created and amount:
        ReadEvent.objects.filter(pk=ev.pk).update(amount=F('amount') + amount)
    if kind == 'ticket' and organization_id:
        record(user, 'customer', organization_id, organization_id, channel, now=now)
    if not created and not amount:
        return []  # nothing new; counts unchanged
    return evaluate(user, now, s)


def counts(user, now=None):
    from .models import ReadEvent
    now = now or timezone.now()
    out = {}
    for w, delta in WINDOWS.items():
        since = _hour(now - delta) if w == '24h' else now - delta
        qs = ReadEvent.objects.filter(user=user, hour__gte=_hour(since))
        out[w] = {
            'tickets': qs.filter(kind='ticket').values('key').distinct().count(),
            'customers': qs.filter(kind='customer').values('key').distinct().count(),
            'exports': qs.filter(kind='export').values('key').distinct().count(),
            'diagnostic_bytes': qs.filter(kind='diagnostic_bytes').aggregate(n=Sum('amount'))['n'] or 0,
        }
    return out


def level_of(user) -> int:
    from .models import AccessAssignment
    from django.db.models import Max, Q
    lvl = (AccessAssignment.objects.live().filter(Q(user=user) | Q(group__members=user))
           .aggregate(m=Max('preset__level'))['m'])
    return int(lvl or 0)


def evaluate(user, now=None, settings_obj=None):
    from .models import Containment, ReadEvent, TheftAlert
    now = now or timezone.now()
    limits = thresholds(settings_obj)
    raised = []
    observed = counts(user, now)
    for rule, windows in limits.items():
        for w, limit in windows.items():
            value = observed[w][rule]
            if value < limit:
                continue
            if TheftAlert.objects.filter(user=user, rule=rule, window=w,
                                         created_at__gte=now - WINDOWS[w]).exists():
                continue
            orgs = sorted({int(k) for k in ReadEvent.objects.filter(
                user=user, kind='customer', hour__gte=_hour(now - WINDOWS[w])).values_list('key', flat=True)
                if str(k).isdigit()})
            level = level_of(user)
            contain = containment_mode(level, settings_obj) == 'contain'
            alert = TheftAlert.objects.create(user=user, rule=rule, window=w, observed=value, threshold=limit,
                                              organizations=orgs[:200], contained=contain)
            if contain and not Containment.objects.filter(user=user, lifted_at__isnull=True).exists():
                Containment.objects.create(user=user, alert=alert,
                                           reason=f'{value} {RULE_LABELS[rule]} in {w} (limit {limit})')
            _announce(alert, settings_obj)
            raised.append(alert)
    return raised


def _announce(alert, settings_obj=None):
    from audit.models import AuditLog
    from .models import DetectionSettings, ProtectionSettings
    s = settings_obj or DetectionSettings.load()
    text = (f'{alert.user.get_username()}: {alert.observed} {RULE_LABELS[alert.rule]} in {alert.window} '
            f'(limit {alert.threshold}). ' + ('Access contained until an administrator reviews it.'
                                               if alert.contained else 'Alert only; access not contained.'))
    AuditLog.log(user=alert.user, action='read', object_type='theft_alert', object_id=alert.pk,
                 object_repr=text[:255], description=text, success=False,
                 extra_data={'rule': alert.rule, 'window': alert.window, 'observed': alert.observed,
                             'threshold': alert.threshold, 'customers': len(alert.organizations)})
    recipients = {r.strip() for r in (s.recipients or '').splitlines() if r.strip()}
    p = ProtectionSettings.load()
    if p.recovery_email and p.recovery_verified_at:
        recipients.add(p.recovery_email)
    from django.contrib.auth import get_user_model
    recipients |= {e for e in get_user_model().objects.filter(is_superuser=True, is_active=True)
                   .exclude(pk=alert.user_id).exclude(email='').values_list('email', flat=True)}
    if recipients:
        try:
            send_mail('[ClientSt0r] Possible bulk data access', text + '\n\nReview: Settings → Security → '
                      'Technician Access → Alerts.', None, sorted(recipients), fail_silently=True)
        except Exception:
            logger.exception('theft alert mail failed')
    if s.notify_customers and alert.organizations:
        _customer_reports(alert)


def _customer_reports(alert):
    """A short note to each affected customer's primary contacts: who, when,
    which rule. No counts of other customers, no ticket text."""
    from core.models import Organization
    for org in Organization.objects.filter(pk__in=alert.organizations):
        email = org.primary_contact_email or org.email
        if not email:
            continue
        try:
            send_mail(f'[{org.name}] Security notice from your IT provider',
                      'Our monitoring flagged unusually broad read access to support tickets by one '
                      f'technician account on {alert.created_at:%Y-%m-%d %H:%M} UTC. The account was '
                      + ('suspended from bulk access ' if alert.contained else 'flagged ')
                      + 'pending review. We will follow up with details.', None, [email], fail_silently=True)
        except Exception:
            logger.exception('customer report failed')


# --- request hooks ---------------------------------------------------------

def contained(user) -> bool:
    from .resolver import active_containment
    return bool(user and getattr(user, 'is_authenticated', False) and active_containment(user) is not None)


def export_key(request) -> str:
    return hashlib.sha256(request.get_full_path().encode()).hexdigest()[:32]
