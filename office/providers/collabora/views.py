"""Browser-side helpers for the Collabora editor page (signed-in owner only,
CSRF-protected like every other POST in the app).

    POST /office/api/collabora/s/<session>/renew/   extend the session and its WOPI tokens
    POST /office/api/collabora/s/<session>/event/   record frame_ready / document_loaded /
                                                    load_failed (diagnostics' browser probe)
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ... import sessions, storage

EVENTS = ('frame_ready', 'document_loaded', 'load_failed')


def _own_live_session(request, session_id):
    from ...models import EditSession
    session = (EditSession.objects.select_related('instance', 'user')
               .filter(pk=session_id, user=request.user, provider='collabora').first())
    if session is None:
        raise Http404('Not found')
    return session


def renew_tokens(session):
    """Extend every live WOPI token of `session` by the token TTL (never past
    the session's hard limit). Returns the new expiry."""
    from ...models import AccessToken, OfficeSettings
    now = timezone.now()
    ttl = OfficeSettings.get().token_ttl_minutes or 60
    expires = min(now + timedelta(minutes=ttl), session.max_expires_at)
    AccessToken.objects.filter(session=session, purpose='wopi', revoked_at__isnull=True,
                               expires_at__gt=now).update(expires_at=expires)
    return expires


@login_required
@require_POST
def renew(request, session_id):
    session = _own_live_session(request, session_id)
    if not session.is_live:
        return JsonResponse({'ok': False, 'error': 'the editing session is over'}, status=409)
    if not sessions.still_allowed(session):
        sessions.revoke(session, 'permission lost')
        return JsonResponse({'ok': False, 'error': 'you no longer have access to this file'},
                            status=403)
    try:
        session = sessions.renew(session)
    except storage.SessionRevoked as e:
        return JsonResponse({'ok': False, 'error': e.message}, status=409)
    expires = renew_tokens(session)
    return JsonResponse({'ok': True, 'expiresAt': session.expires_at.isoformat(),
                         'tokenExpiresAt': expires.isoformat()})


@login_required
@require_POST
def event(request, session_id):
    from .wopi import note
    session = _own_live_session(request, session_id)
    name = request.POST.get('event', '')
    if name not in EVENTS:
        return JsonResponse({'ok': False, 'error': 'unknown event'}, status=400)
    state = (session.provider_state or {}).get('collabora') or {}
    browser = dict(state.get('browser') or {})
    browser[name] = timezone.now().isoformat()
    note(session, browser=browser)
    return JsonResponse({'ok': True})
