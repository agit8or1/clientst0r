"""The ONLYOFFICE save callback (``editorConfig.callbackUrl``).

    POST /office/api/onlyoffice/callback/<session id>/

Order of checks, each failing closed:

1. Rate limit per session (OFFICE_ONLYOFFICE_CALLBACK_RATE per minute).
2. The session exists, belongs to the ONLYOFFICE provider and has an instance.
3. The outbox JWT: ``Authorization: Bearer`` (or the instance's configured
   header), HS256 only, signed with the instance secret, not expired,
   ``operation`` = ``callback`` where present, request wrapped in
   ``payload``. The body token (``{"token": ...}``) is accepted only for an
   instance configured with ``body_token`` (Docs ``token.outbox.inBody``).
   Every field used afterwards comes from the verified claims, never from the
   unsigned body; a body that contradicts the claims is refused.
4. ``key`` equals the editor key of this session. A session of another file
   or organization has another key, so a callback (or a replay) addressed to
   it can never write this file, and the other way round.

Statuses [OO-CB]:

    1  being edited            record users; reply 0
    2  ready for saving        mark the key spent, download ``url``, store a
                               revision, close the group's closing sessions
    3  saving error            keep ``url`` in quarantine when it downloads,
                               record a visible failure; reply 0
    4  closed, no changes      close the session(s); reply 0
    6  force-save              download ``url``, store a revision, session
                               stays open
    7  force-save error        as 3, session stays open

Replies: ``{"error": 0}`` only after the bytes are durable — stored as a
revision, recognised as an already-stored duplicate, or kept in quarantine
(stale base, revoked session, lost permission, invalid content: a retry
would deliver the same refused bytes). Anything that leaves nothing durable
(download failed, URL on a foreign host, over the size limit, storage
failure) answers HTTP 500 ``{"error": 1}`` so Docs retries and keeps its copy
(Docs' own "forgotten files" hold it if retries run out).
"""
from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from office import audit, net, quarantine, sessions, storage
from office.logging_filters import get_logger
from office.targets import target_of

from . import client, signing, state

log = get_logger('office.onlyoffice')

MAX_BODY = 1024 * 1024
OK = (200, {'error': 0})
STATUS_LABELS = {1: 'editing', 2: 'ready for saving', 3: 'saving error', 4: 'closed without changes',
                 6: 'force-save', 7: 'force-save error'}


def _fail(http_status, message):
    return http_status, {'error': 1, 'message': message}


def rate_limited(session_id) -> bool:
    limit = int(getattr(settings, 'OFFICE_ONLYOFFICE_CALLBACK_RATE', 120))
    minute = int(timezone.now().timestamp() // 60)
    key = f'office.oo.cb.{session_id}.{minute}'
    if cache.add(key, 1, 90):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, 90)
            count = 1
    return count > limit


def authenticate(request, instance, body):
    """Verified callback fields, or raises signing.InvalidToken."""
    header = signing.header_name(instance)
    raw = request.headers.get(header, '')
    token = signing.bearer(raw) if raw else ''
    if token:
        claims = signing.decode(token, instance.shared_secret, operation='callback')
        data = claims.get('payload')
        if not isinstance(data, dict):
            raise signing.InvalidToken('payload', 'The header token has no payload.')
    elif signing.instance_option(instance, 'body_token', False) and isinstance(body, dict) \
            and body.get('token'):
        claims = signing.decode(body['token'], instance.shared_secret, operation='callback')
        data = claims.get('payload') if isinstance(claims.get('payload'), dict) else claims
    else:
        raise signing.InvalidToken('missing', 'No callback token.')
    # The unsigned body must not contradict what was signed.
    if isinstance(body, dict):
        for field in ('key', 'status', 'url'):
            if field in body and field in data and body[field] != data[field]:
                raise signing.InvalidToken('payload', f'Body {field} differs from the token.')
    return data


def handle(request, session_id):
    """(http status, reply dict) for one callback request."""
    from office.models import EditSession
    if rate_limited(session_id):
        return _fail(429, 'rate limited')
    session = (EditSession.objects.select_related('instance', 'user', 'base_revision')
               .filter(pk=session_id, provider='onlyoffice').first())
    if session is None or session.instance is None:
        return _fail(404, 'unknown session')
    instance = session.instance
    if len(request.body or b'') > MAX_BODY:
        return _fail(413, 'body too large')
    try:
        body = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        body = None
    try:
        data = authenticate(request, instance, body)
    except signing.InvalidToken as e:
        log.warning('ONLYOFFICE callback for session %s refused: %s', session.pk, e.reason)
        return _fail(403, 'invalid token')

    key = data.get('key')
    if not key or key != (session.provider_state or {}).get('oo_key'):
        log.warning('ONLYOFFICE callback for session %s refused: key mismatch', session.pk)
        return _fail(403, 'key mismatch')
    try:
        status = int(data.get('status'))
    except (TypeError, ValueError):
        return _fail(400, 'bad status')

    state.update(session.pk, oo_last_callback_at=state.now_iso(), oo_last_status=status)
    sessions.touch(session)

    if status == 1:
        return _editing(session, data)
    if status == 2:
        return _save(session, data, final=True)
    if status == 6:
        return _save(session, data, final=False)
    if status in (3, 7):
        return _save_error(session, data, status)
    if status == 4:
        _close_group(session, key, reason='closed in the editor without changes')
        return OK
    # Unknown/undocumented status: acknowledge, change nothing.
    log.info('ONLYOFFICE callback status %s ignored', status)
    return OK


def _editing(session, data):
    users = [str(u)[:128] for u in (data.get('users') or []) if u][:50]
    state.update(session.pk, oo_users=users, oo_users_at=state.now_iso())
    return OK


def _close_group(session, key, *, reason):
    """Close every session of this editor key that was waiting for the
    editor (``closing``), plus this one when it is closing."""
    for s in state.with_key(session, key):
        if s.state == 'closing':
            sessions.close(s, reason=reason)


def pick_session(url_session, data):
    """The session to attribute a save to: the live edit session in the same
    group whose editor user Docs names as the last editor; else the session
    the callback was addressed to. Only sessions of the same file and key
    are considered."""
    key = (url_session.provider_state or {}).get('oo_key')
    ids = [str(u) for u in (data.get('users') or [])]
    if not ids:
        return url_session
    candidates = [s for s in state.with_key(url_session, key) if s.mode == 'edit']
    for uid in ids:
        matching = [s for s in candidates if (s.provider_state or {}).get('oo_user') == uid]
        live = [s for s in matching if s.is_live]
        chosen = sorted(live or matching, key=lambda s: s.opened_at, reverse=True)
        if chosen:
            return chosen[0]
    return url_session


def record_error(session, status, message):
    state.update(session.pk, oo_last_error={'at': state.now_iso(), 'status': status,
                                            'message': message[:300]})


def _download(session, url):
    instance = session.instance
    return client.download(instance, url, storage.max_bytes(instance))


def _save(url_session, data, *, final):
    status = 2 if final else 6
    key = data['key']
    target_session = pick_session(url_session, data)
    if final:
        # Before anything else: no new open may reuse this key, whatever
        # happens to the download below.
        state.mark_spent(url_session, key)
    url = data.get('url')
    if not url:
        record_error(target_session, status, 'The editor sent no file to save.')
        return _fail(500, 'no url')
    try:
        content = _download(url_session, url)
    except net.DestinationNotAllowed as e:
        log.warning('ONLYOFFICE save URL refused for session %s: %s', url_session.pk, e)
        record_error(target_session, status, 'The editor offered the file from a host that is not '
                                             'the approved editor host.')
        audit.save_failed(target_of(target_session), target_session.user, session=target_session,
                          reason='validation', detail='download URL not on the editor host')
        return _fail(500, 'url not allowed')
    except net.OfficeFetchError as e:
        log.warning('ONLYOFFICE save download failed for session %s: %s', url_session.pk, e)
        too_large = 'larger than' in str(e)
        record_error(target_session, status,
                     'The saved file is larger than the size limit.' if too_large else
                     'clientst0r could not download the saved file from the editor.')
        audit.save_failed(target_of(target_session), target_session.user, session=target_session,
                          reason='validation' if too_large else 'storage_error',
                          detail=str(e)[:300])
        return _fail(500, 'download failed')
    outcome = persist(target_session, content, status=status, filetype=data.get('filetype'))
    if outcome is None:
        return _fail(500, 'not stored')
    if final:
        _close_group(url_session, key, reason='saved by the editor')
    return OK


def persist(session, content, *, status, filetype=None):
    """Store bytes the editor produced for `session`. Returns a SaveOutcome
    (ok / duplicate / quarantined) when the bytes are durable, None when
    nothing could be kept. Also used by the round-trip test."""
    target = target_of(session)
    sha = hashlib.sha256(content).hexdigest()
    if target is None:
        q = quarantine.keep_bytes(None, content, session=session, user=session.user,
                                  reason='revoked', detail='The file was deleted while it was open.')
        audit.save_failed(None, session.user, session=session, reason='revoked',
                          detail='file deleted', quarantined=q)
        record_error(session, status, 'The file was deleted; the save is kept in quarantine.')
        return storage.SaveOutcome(quarantined=q, error=storage.SessionRevoked('file deleted'))

    # A repeated delivery of a save already stored: the current revision has
    # these exact bytes and came from this co-editing group. (save_new_revision
    # detects this too, but only while the session is live; after a status-2
    # save closed the group a retry must still be recognised.)
    cur = storage.current(target)
    if cur is not None and cur.sha256 == sha and cur.editor_session_id is not None \
            and cur.editor_session.document_key == session.document_key:
        cur.duplicate = True
        return storage.SaveOutcome(revision=cur)

    ext = target.extension
    if filetype and str(filetype).lower() != ext:
        q = quarantine.keep_bytes(target, content, session=session, user=session.user,
                                  reason='validation',
                                  detail=f'The editor returned .{str(filetype)[:10]}, expected .{ext}.')
        audit.save_failed(target, session.user, session=session, reason='validation',
                          detail='wrong file type from editor', quarantined=q)
        record_error(session, status, 'The editor returned a different file type; kept in quarantine.')
        return storage.SaveOutcome(quarantined=q, error=storage.RevisionRejected('file type'))

    outcome = storage.save_or_quarantine(
        target, content, user=session.user, source='editor_save',
        expected_base_revision=sessions.expected_base(session), session=session,
        original_name=target.filename)
    if outcome.ok:
        rev = outcome.revision
        state.update(session.pk, oo_last_saved={'at': state.now_iso(), 'status': status,
                                                'revision': rev.revision_number})
        return outcome
    if outcome.quarantined is not None:
        record_error(session, status, f'Not saved: {outcome.error.message or outcome.error.reason}'
                                      f' — kept in quarantine.')
        return outcome
    record_error(session, status, f'Not saved: {getattr(outcome.error, "message", "") or "storage error"}')
    return None


def _save_error(url_session, data, status):
    target_session = pick_session(url_session, data)
    message = ('ONLYOFFICE reported an error while saving the document.' if status == 3 else
               'ONLYOFFICE reported an error while force-saving the document.')
    target = target_of(target_session)
    kept = None
    url = data.get('url')
    if url:
        try:
            content = _download(url_session, url)
        except net.OfficeFetchError as e:
            log.warning('ONLYOFFICE error-state download failed: %s', e)
        else:
            kept = quarantine.keep_bytes(target, content, session=target_session,
                                         user=target_session.user, reason='storage_error',
                                         detail=f'{message} (status {status})')
    audit.save_failed(target, target_session.user, session=target_session, reason='storage_error',
                      detail=f'editor status {status}', quarantined=kept)
    record_error(target_session, status, message + (' The last state is kept in quarantine.'
                                                    if kept else ''))
    return OK
