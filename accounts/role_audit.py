"""
Audit trail for roles, permissions, assignments, scopes, invitations,
ownership and denied privileged attempts.

Entries go to audit.AuditLog (the one audit trail), with
extra_data = {'event': <event>, 'before': {...}, 'after': {...}, ...}.
Values are reduced to safe, small representations: permission booleans,
role names and ids, scope names, organization ids. Passwords, secret values,
tokens and signing links are never recorded (any key that looks like one is
dropped before writing).

Events:
  role.created / role.updated / role.deleted / role.archived / role.cloned
  membership.created / membership.updated / membership.deleted
  membership.roles_changed            additional roles added / removed
  profile.access_changed              user type, global role, client / record scope
  account.status_changed              is_active / is_superuser / is_staff
  invite.sent                         invitations (portal / member add)
  ownership.transferred
  access.denied                       a privileged or sensitive permission refused
  delegation.denied                   a role / membership change refused
"""
from __future__ import annotations

import logging

logger = logging.getLogger('accounts.role_audit')

_SECRET_HINTS = ('password', 'secret', 'token', 'otp', 'key_hash', 'signing_link', 'api_key', 'credential')


def _safe(value):
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()
                if not any(h in str(k).lower() for h in _SECRET_HINTS)}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value][:200]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:300]


def _request_bits(request):
    if request is None:
        from .authz_cache import current_request
        request = current_request()
    if request is None:
        return None, {}
    user = getattr(request, 'user', None)
    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None
    try:
        from core.client_ip import get_client_ip
        ip = get_client_ip(request)
    except Exception:
        ip = request.META.get('REMOTE_ADDR') if hasattr(request, 'META') else None
    return user, {'ip_address': ip or None, 'path': (getattr(request, 'path', '') or '')[:500],
                  'user_agent': (request.META.get('HTTP_USER_AGENT', '') if hasattr(request, 'META') else '')[:255]}


def record(event, *, target_type='', target_id=None, target_repr='', organization=None, before=None,
           after=None, extra=None, success=True, request=None, actor=None, description=''):
    """Write one role/access audit entry. Never raises."""
    try:
        from audit.models import AuditLog
        req_actor, bits = _request_bits(request)
        actor = actor or req_actor
        action = {'created': 'create', 'deleted': 'delete'}.get(event.rsplit('.', 1)[-1], 'update')
        if event.endswith('.denied'):
            action = 'access_denied'
        data = {'event': event}
        if before is not None:
            data['before'] = _safe(before)
        if after is not None:
            data['after'] = _safe(after)
        if extra:
            data.update(_safe(extra))
        org = organization
        if org is not None and not hasattr(org, 'pk'):
            from core.models import Organization
            org = Organization.objects.filter(pk=org).first()
        AuditLog.objects.create(
            user=actor, username=getattr(actor, 'username', '') or 'system', action=action,
            object_type=target_type, object_id=target_id if isinstance(target_id, int) else None,
            object_repr=str(target_repr)[:255], description=description or event,
            organization=org, extra_data=data, success=success, **bits)
    except Exception:  # pragma: no cover - auditing never breaks the change itself
        logger.exception('role audit write failed for %s', event)


def diff(before: dict, after: dict):
    """(before, after) restricted to the keys that changed."""
    keys = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def record_denied(request, perm, organization=None, reason=''):
    """Log a refused privileged / sensitive permission (others are not worth
    an audit row each)."""
    from .permission_registry import PRIVILEGED_KEYS, SENSITIVE_KEYS
    if perm not in PRIVILEGED_KEYS and perm not in SENSITIVE_KEYS:
        return
    if organization is None and request is not None:
        organization = getattr(request, 'current_organization', None)
    record('access.denied', target_type='permission', target_repr=perm, organization=organization,
           extra={'permission': perm, 'reason': reason}, success=False, request=request,
           description=f'Denied: {perm}' + (f' ({reason})' if reason else ''))


def record_delegation_denied(request, what, reason, organization=None, target=None):
    record('delegation.denied', target_type=type(target).__name__.lower() if target is not None else '',
           target_id=getattr(target, 'pk', None), target_repr=str(target or what), organization=organization,
           extra={'attempt': what, 'reason': reason}, success=False, request=request,
           description=f'Refused: {what}: {reason}')
