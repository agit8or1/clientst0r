"""Sign out everywhere: a per-user session epoch.

Every web session carries the moment it was signed in
(session[ISSUED_AT_KEY], epoch seconds, written by the user_logged_in
receiver below). UserProfile.sessions_valid_after is the user's epoch:
SessionEpochMiddleware ends any session issued before it on that session's
next request. Moving the epoch forward therefore signs the user out of every
browser at once without touching django_session (on SQLite a scan of that
table on every sign-out would be costly; stale rows expire with the session
cookie age and are removed by `clearsessions` as before).

Scopes:
  * SCOPE_OTHERS - the epoch moves and the current session is re-stamped so
    it survives (the user's own "Sign out of all other sessions", password
    change, removing a 2FA device of one's own).
  * SCOPE_ALL - every session ends, the current one too.

The epoch is read from request.user.profile, which the request already
loads (UserLanguageMiddleware and the 2FA checks read it on every request),
so the check costs no extra query and is correct across worker processes
(the default cache is per-process LocMem, which could not be invalidated
across gunicorn workers).
"""
from __future__ import annotations

import logging
import time

from django.utils import timezone

logger = logging.getLogger(__name__)

ISSUED_AT_KEY = '_auth_issued_at'
SCOPE_OTHERS = 'others'
SCOPE_ALL = 'all'


# --- session stamps -------------------------------------------------------

def stamp(request, when=None):
    """Mark the request's session as issued now (or at `when`)."""
    session = getattr(request, 'session', None)
    if session is None:
        return
    session[ISSUED_AT_KEY] = float(when if when is not None else time.time())


def issued_at(session):
    """The session's issue time, or None when it carries none.

    Sessions created before this feature have no stamp; the idle-timeout
    middleware's `_auth_started` (first authenticated request) stands in for
    them, so an epoch moved after the upgrade still ends them.
    """
    for key in (ISSUED_AT_KEY, '_auth_started'):
        value = session.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def valid_after_ts(user):
    """The user's epoch as epoch seconds, or None. Reads the profile the
    request has (or will have) loaded anyway."""
    try:
        profile = user.profile
    except Exception:  # no profile row
        return None
    value = getattr(profile, 'sessions_valid_after', None)
    return value.timestamp() if value else None


def is_revoked(session, user):
    after = valid_after_ts(user)
    if after is None:
        return False
    issued = issued_at(session)
    return issued is None or issued < after


# --- moving the epoch -----------------------------------------------------

def bump(user, when=None, create=True):
    """Move the user's epoch to now; returns the new value.

    `create=False` (signal paths, incl. cascading deletes) never creates a
    profile row, it only updates an existing one.
    """
    from .models import UserProfile
    when = when or timezone.now()
    updated = UserProfile.objects.filter(user_id=user.pk).update(sessions_valid_after=when)
    if not updated and create:
        UserProfile.objects.get_or_create(user=user, defaults={'sessions_valid_after': when})
        UserProfile.objects.filter(user_id=user.pk).update(sessions_valid_after=when)
    # Keep any loaded profile in step (the request's user object in particular).
    cached = getattr(user, '_state', None) and user._state.fields_cache.get('profile')
    if cached is not None:
        cached.sessions_valid_after = when
    return when


def bump_many(user_ids, when=None):
    """Move the epoch of several users in one UPDATE (organization
    deactivation). Returns how many profiles changed."""
    from .models import UserProfile
    user_ids = list(user_ids)
    if not user_ids:
        return 0
    return UserProfile.objects.filter(user_id__in=user_ids).update(
        sessions_valid_after=when or timezone.now())


def _current_request():
    try:
        from tech_access import actor
        return getattr(actor._local, 'request', None)
    except Exception:
        return None


def sign_out(user, scope, *, actor=None, request=None, reason='', revoke_mobile=False, audit=True):
    """End `user`'s web sessions (and optionally mobile app sessions).

    `request` is the request being served. When it belongs to `user` and the
    scope is SCOPE_OTHERS, its session is re-stamped and stays signed in;
    with SCOPE_ALL it is logged out too. Returns the number of mobile
    sessions revoked. Writes an audit entry (never any session key).
    """
    when = bump(user)
    own = bool(request is not None and getattr(request, 'user', None) is not None
               and getattr(request.user, 'pk', None) == user.pk)
    if own and scope == SCOPE_OTHERS:
        # Strictly after the epoch, so this session is not "issued before".
        stamp(request, max(time.time(), when.timestamp()))
    revoked = 0
    if revoke_mobile:
        try:
            from api_mobile.models import MobileAuthToken
            revoked = MobileAuthToken.revoke_all_for(user)
        except Exception:
            logger.exception('Revoking mobile sessions failed')
    if audit:
        record(user, scope, actor=actor, request=request, reason=reason, mobile_revoked=revoked)
    if own and scope == SCOPE_ALL:
        from django.contrib.auth import logout
        logout(request)
    return revoked


def sign_out_from_signal(user, reason):
    """Epoch change caused by a model change (2FA device removed,
    account / membership / organization deactivated). If the user is the one
    making the change in this request, their own session stays."""
    request = _current_request()
    actor = None
    if request is not None:
        u = getattr(request, 'user', None)
        if u is not None and getattr(u, 'is_authenticated', False):
            actor = u
    own = actor is not None and actor.pk == user.pk
    when = bump(user, create=False)
    if own:
        stamp(request, max(time.time(), when.timestamp()))
    record(user, SCOPE_OTHERS if own else SCOPE_ALL, actor=actor, request=request, reason=reason)


def record(user, scope, *, actor=None, request=None, reason='', mobile_revoked=0):
    try:
        from audit.models import AuditLog
        ip, ua, path = None, '', ''
        if request is not None:
            try:
                from core.client_ip import get_client_ip
                ip = get_client_ip(request)
            except Exception:
                ip = None
            ua = (request.META.get('HTTP_USER_AGENT', '') or '')[:255]
            path = (getattr(request, 'path', '') or '')[:500]
        what = 'all web sessions' if scope == SCOPE_ALL else 'all other web sessions'
        AuditLog.log(
            user=actor, action='logout', object_type='user', object_id=user.pk,
            object_repr=user.username,
            description=f'Signed {user.username} out of {what}'
                        + (f' and {mobile_revoked} mobile app session(s)' if mobile_revoked else '')
                        + (f' ({reason})' if reason else ''),
            ip_address=ip, user_agent=ua, path=path,
            extra_data={'op': 'sign_out_sessions', 'scope': scope, 'reason': reason,
                        'target_user_id': user.pk, 'mobile_sessions_revoked': mobile_revoked},
        )
    except Exception:
        logger.exception('Audit entry for a session sign-out failed')


# --- signal receivers -----------------------------------------------------

def on_user_logged_in(sender, request, user, **kwargs):
    if request is not None:
        stamp(request)


def _user_post_save(sender, instance, created, raw=False, **kwargs):
    if created or raw:
        return
    before = getattr(instance, '_authz_before', None) or {}
    if before.get('is_active') and not instance.is_active:
        sign_out_from_signal(instance, 'account deactivated')


def _is_customer_user(user):
    from psa.visibility import is_msp_staff
    try:
        return not (user.is_superuser or user.is_staff or is_msp_staff(user))
    except Exception:
        return False


def _membership_post_save(sender, instance, created, raw=False, **kwargs):
    if created or raw:
        return
    before = getattr(instance, '_authz_before', None) or {}
    if before.get('is_active') and not instance.is_active:
        user = instance.user
        if _is_customer_user(user):
            sign_out_from_signal(user, 'membership deactivated')


def _membership_post_delete(sender, instance, **kwargs):
    from django.contrib.auth.models import User
    if not instance.is_active:
        return
    user = User.objects.filter(pk=instance.user_id).first()
    if user is not None and _is_customer_user(user):
        sign_out_from_signal(user, 'membership removed')


def _org_pre_save(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._epoch_was_active = None
        return
    instance._epoch_was_active = (sender._default_manager.filter(pk=instance.pk)
                                  .values_list('is_active', flat=True).first())


def _org_post_save(sender, instance, created, raw=False, **kwargs):
    if created or raw:
        return
    if getattr(instance, '_epoch_was_active', None) and not instance.is_active:
        from django.contrib.auth.models import User
        from psa.visibility import msp_staff_q
        ids = list(User.objects.filter(memberships__organization=instance)
                   .exclude(msp_staff_q()).values_list('pk', flat=True).distinct())
        n = bump_many(ids)
        if n:
            try:
                from audit.models import AuditLog
                req = _current_request()
                u = getattr(req, 'user', None) if req is not None else None
                AuditLog.log(
                    user=u if getattr(u, 'is_authenticated', False) else None,
                    action='logout', object_type='organization', object_id=instance.pk,
                    object_repr=str(instance)[:255],
                    description=f'Signed {n} customer user(s) of a deactivated organization out of all web sessions',
                    extra_data={'op': 'sign_out_sessions', 'scope': SCOPE_ALL,
                                'reason': 'organization deactivated', 'users': n},
                )
            except Exception:
                logger.exception('Audit entry for an organization sign-out failed')


def _device_post_delete(sender, instance, **kwargs):
    from django_otp.models import Device
    if not isinstance(instance, Device) or not getattr(instance, 'confirmed', False):
        return
    user_id = getattr(instance, 'user_id', None)
    if not user_id:
        return
    from django.contrib.auth.models import User
    user = User.objects.filter(pk=user_id).first()
    if user is not None:
        sign_out_from_signal(user, 'two-factor device removed')


def _totp_post_init(sender, instance, **kwargs):
    # The seed as loaded (no query; saves on every code check stay cheap).
    d = instance.__dict__
    instance._epoch_old_key = d.get('key') if (d.get('id') and d.get('confirmed')) else None


def _totp_post_save(sender, instance, created, raw=False, **kwargs):
    old = getattr(instance, '_epoch_old_key', None)
    instance._epoch_old_key = instance.key if instance.confirmed else None
    if created or raw or not old or old == instance.key:
        return
    from django.contrib.auth.models import User
    user = User.objects.filter(pk=instance.user_id).first()
    if user is not None:
        sign_out_from_signal(user, 'two-factor device reset')


def connect():
    from django.contrib.auth.models import User
    from django.contrib.auth.signals import user_logged_in
    from django.db.models.signals import post_delete, post_init, post_save, pre_save
    from core.models import Organization
    from .models import Membership

    uid = 'accounts.session_epoch.'
    user_logged_in.connect(on_user_logged_in, dispatch_uid=uid + 'login')
    post_save.connect(_user_post_save, sender=User, dispatch_uid=uid + 'user')
    post_save.connect(_membership_post_save, sender=Membership, dispatch_uid=uid + 'membership')
    post_delete.connect(_membership_post_delete, sender=Membership, dispatch_uid=uid + 'membership_del')
    pre_save.connect(_org_pre_save, sender=Organization, dispatch_uid=uid + 'org_pre')
    post_save.connect(_org_post_save, sender=Organization, dispatch_uid=uid + 'org_post')
    # Every concrete django-otp device type (TOTP, static backup codes,
    # WebAuthn, ...): connected without a sender, filtered by isinstance.
    post_delete.connect(_device_post_delete, dispatch_uid=uid + 'device_del')
    try:
        from django_otp.plugins.otp_totp.models import TOTPDevice
        post_init.connect(_totp_post_init, sender=TOTPDevice, dispatch_uid=uid + 'totp_init')
        post_save.connect(_totp_post_save, sender=TOTPDevice, dispatch_uid=uid + 'totp_post')
    except Exception:  # pragma: no cover
        pass
