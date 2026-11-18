"""Rollback window for API access changes (roadmap 81.6).

``arm()`` takes a snapshot of the global settings (modes and limits) and every
API access rule, and sets a time. Changes made after that are undone at that
time by ``revert_if_due()`` unless an administrator calls ``keep()``. A second
``arm()`` inside the window keeps the first snapshot (it is the last state known
to work) and moves the deadline.

``revert_if_due()`` runs from the policy loader (so the first API request after
the deadline reverts, even when the API is otherwise refusing everything), from
the API Access Control page, and from the scheduler (when nothing calls the API).
Trusted proxies are not part of the snapshot.
"""
import logging
from datetime import timedelta

from django.core import serializers
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

WINDOW_CHOICES = ((0, 'No automatic undo'), (5, '5 minutes'), (10, '10 minutes'),
                  (30, '30 minutes'), (60, '1 hour'))
DEFAULT_MINUTES = 10
SETTINGS_FIELDS = ('api_mode', 'webhook_mode', 'api_rate_per_address', 'webhook_rate_per_address',
                   'api_max_body_kb', 'webhook_max_body_kb')


def parse_minutes(value):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return 0
    return minutes if minutes in dict(WINDOW_CHOICES) else 0


def snapshot():
    from .models import ApiAccessRule, ApiAccessSettings
    s = ApiAccessSettings.get()
    return {'settings': {f: getattr(s, f) for f in SETTINGS_FIELDS},
            'rules': serializers.serialize('json', ApiAccessRule.objects.order_by('pk')),
            'taken_at': timezone.now().isoformat(),
            'policy_version': s.policy_version}


def arm(user, minutes):
    """Start (or extend) the window. Call before making the change."""
    from .models import ApiAccessSettings
    if minutes <= 0:
        return None
    with transaction.atomic():
        s = ApiAccessSettings.objects.select_for_update().get(pk=ApiAccessSettings.get().pk)
        fields = {'revert_at': timezone.now() + timedelta(minutes=minutes)}
        if s.revert_at is None:
            fields.update(revert_snapshot=snapshot(), revert_armed_by=user)
        ApiAccessSettings.objects.filter(pk=s.pk).update(**fields)
    _audit(user, f'API access rollback window armed: changes undo at {fields["revert_at"]:%Y-%m-%d %H:%M} '
                 'unless kept', {'minutes': minutes})
    return fields['revert_at']


def keep(user):
    from .models import ApiAccessSettings
    n = ApiAccessSettings.objects.filter(revert_at__isnull=False).update(
        revert_at=None, revert_snapshot={}, revert_armed_by=None)
    if n:
        _audit(user, 'API access changes kept; rollback window closed', {})
    return bool(n)


def revert_if_due(now=None, force=False, user=None):
    """Restore the snapshot if the window has ended (or ``force``). Returns True if it reverted."""
    from . import policy as P
    from .models import ApiAccessRule, ApiAccessSettings
    now = now or timezone.now()
    with transaction.atomic():
        s = ApiAccessSettings.objects.select_for_update().filter(revert_at__isnull=False).first()
        if s is None or (not force and s.revert_at > now):
            return False
        snap = s.revert_snapshot or {}
        restored = list(serializers.deserialize('json', snap.get('rules') or '[]'))
        keep_pks = {obj.object.pk for obj in restored}
        removed = ApiAccessRule.objects.exclude(pk__in=keep_pks).delete()[0]
        for obj in restored:
            obj.save()
        ApiAccessSettings.objects.filter(pk=s.pk).update(
            revert_at=None, revert_snapshot={}, revert_armed_by=None, **(snap.get('settings') or {}))
        ApiAccessSettings.bump(user)
    P.reset_cache()
    _audit(user, 'API access changes undone: rollback window '
                 + ('ended without the changes being kept' if not force else 'reverted by an administrator'),
           {'restored_rules': len(restored), 'removed_rules': removed,
            'snapshot_taken_at': snap.get('taken_at'), 'settings': snap.get('settings')})
    logger.warning('API access rollback applied (%s rules restored, %s removed)', len(restored), removed)
    return True


def _audit(user, description, extra):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='update', object_type='ApiAccessSettings',
                 object_repr='API access settings', description=description, extra_data=extra)
