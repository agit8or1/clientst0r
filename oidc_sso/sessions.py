"""Django session <-> OP session (sid) index for back-channel logout."""
import logging
from importlib import import_module

from django.conf import settings
from django.utils import timezone

from .models import OIDCIdentity, OIDCSession

logger = logging.getLogger('oidc_sso')


def _store(session_key):
    engine = import_module(getattr(settings, 'SESSION_ENGINE', 'django.contrib.sessions.backends.db'))
    return engine.SessionStore(session_key=session_key)


def record(request, provider, claims, user):
    if not request.session.session_key:
        request.session.save()
    sid = claims.get('sid') if isinstance(claims.get('sid'), str) else ''
    OIDCSession.objects.create(provider=provider, issuer=provider.issuer_normalized, sid=sid[:255],
                               sub=claims['sub'], user=user, session_key=request.session.session_key)


def forget_session_key(session_key):
    if session_key:
        OIDCSession.objects.filter(session_key=session_key).delete()


def _kill(rows):
    killed = 0
    for row in rows:
        try:
            store = _store(row.session_key)
            if store.exists(row.session_key):
                store.delete(row.session_key)
                killed += 1
        except Exception:
            logger.exception('Could not end a session for back-channel logout')
        row.delete()
    return killed


def logout_sid(provider, sid):
    rows = list(OIDCSession.objects.filter(provider=provider, issuer=provider.issuer_normalized, sid=sid))
    users = {r.user_id for r in rows}
    return _kill(rows), users


def logout_sub(provider, sub):
    identity = OIDCIdentity.objects.filter(issuer=provider.issuer_normalized, sub=sub).select_related('user').first()
    rows = list(OIDCSession.objects.filter(provider=provider, issuer=provider.issuer_normalized, sub=sub))
    killed = _kill(rows)
    users = {r.user_id for r in rows}
    if identity is not None:
        users.add(identity.user_id)
        # Web "sign out everywhere" (dev/signout-everywhere) when present:
        # every session of the user, not only SSO ones.
        profile = getattr(identity.user, 'profile', None)
        if profile is not None and hasattr(profile, 'sessions_valid_after'):
            try:
                profile.sessions_valid_after = timezone.now()
                profile.save(update_fields=['sessions_valid_after'])
            except Exception:
                logger.exception('Could not set sessions_valid_after')
    return killed, users
