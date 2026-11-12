"""The WOPI host Collabora Online talks to.

    GET  /office/api/wopi/files/<file_id>?access_token=...            CheckFileInfo
    POST /office/api/wopi/files/<file_id>?access_token=...            X-WOPI-Override:
         LOCK (also UNLOCK_AND_RELOCK with X-WOPI-OldLock), UNLOCK, REFRESH_LOCK,
         GET_LOCK, RENAME_FILE; PUT_RELATIVE answers 501 (not offered)
    GET  /office/api/wopi/files/<file_id>/contents?access_token=...   GetFile
    POST /office/api/wopi/files/<file_id>/contents?access_token=...   PutFile (X-WOPI-Override: PUT)

``file_id`` is the session's ``document_key``: an opaque random string
shared by everyone co-editing the same revision of the same file (Collabora
groups co-editors by WOPISrc, so it must be shared). It is only a name; the
``access_token`` decides everything. A request is served only when

  1. file_id matches ``[A-Za-z0-9_-]{16,128}`` (no path, nothing to traverse);
  2. the token is known, and its session is a Collabora session whose
     document_key is exactly this file_id (a token for another file or
     another tenant's file gets 401, like an unknown token);
  3. the WOPI proof verifies, when the instance's discovery publishes a
     proof key and the instance's ``require_proof`` option is on (500
     otherwise, as the WOPI proof-key rules require);
  4. ``office.tokens.validate`` passes for the operation's scope
     (read / write / lock / rename), which re-checks expiry, revocation,
     the session, the user and the user's permission right now.

Errors: unknown/expired/revoked/wrong-scope token -> 401; permission lost ->
403 (the session is revoked by tokens.validate). A PutFile refused for any
of those reasons, or for a lock or timestamp conflict, keeps the body as a
QuarantinedSave so nothing typed is lost.

Access tokens arrive in the query string by protocol. They are never
logged: office.* loggers redact them and the provider attaches the same
filter to django.request / django.server / gunicorn.access.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlsplit

from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ... import audit, formats, sessions, storage, tokens
from ...logging_filters import get_logger
from . import discovery as disco
from . import locks, options
from . import proof as proofs

logger = get_logger('office.collabora.wopi')

FILE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{16,128}$')
CHUNK = 1024 * 1024
DOC_CHANGED = 1010   # Collabora common/Common.hpp: "Document changed externally in storage"


class WopiError(Exception):
    def __init__(self, status, detail='', *, headers=None, body=None, session=None,
                 target=None, reason=''):
        super().__init__(detail or str(status))
        self.status = status
        self.detail = detail
        self.headers = headers or {}
        self.body = body
        self.session = session
        self.target = target
        self.reason = reason

    def response(self):
        if self.body is not None:
            resp = JsonResponse(self.body, status=self.status)
        else:
            resp = HttpResponse(status=self.status, content_type='text/plain')
        for k, v in self.headers.items():
            resp[k] = v
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso_z(dt) -> str:
    """ISO 8601 UTC with 'Z' and microseconds; Collabora refuses offsets."""
    return dt.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


_ISO = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]00:?00)?$')


def same_time(header, dt) -> bool:
    """Does the X-COOL-WOPI-Timestamp `header` name `dt`? Compared at the
    precision the header carries (Collabora echoes the LastModifiedTime it
    saw; whether it keeps the exact string or re-formats it is not verified,
    so a re-formatted value with fewer fraction digits still matches)."""
    header = (header or '').strip()
    if header == iso_z(dt):
        return True
    m = _ISO.match(header)
    if not m:
        return False
    utc = dt.astimezone(dt_timezone.utc)
    if m.group(1) != utc.strftime('%Y-%m-%dT%H:%M:%S'):
        return False
    frac = (m.group(2) or '')
    if not frac:
        return True
    ours = utc.strftime('%f')
    n = min(len(frac), 6)
    return frac[:n].ljust(n, '0') == ours[:n] and (len(frac) <= 6 or set(frac[6:]) <= {'0'})


def version_of(rev) -> str:
    return f'{rev.revision_number}-{rev.sha256[:16]}'


def _raw_token(request):
    raw = request.GET.get('access_token', '')
    if not raw:
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if auth[:7].lower() == 'bearer ':
            raw = auth[7:].strip()
    return raw


def note(session, **values):
    """Merge non-critical evidence into session.provider_state['collabora']
    (diagnostics read it). Lost updates here are harmless; locks live in
    WopiLock rows, never here."""
    from ...models import EditSession
    try:
        fresh = EditSession.objects.filter(pk=session.pk).values_list('provider_state', flat=True).first()
        state = dict(fresh or {})
        mine = dict(state.get('collabora') or {})
        mine.update(values)
        state['collabora'] = mine
        EditSession.objects.filter(pk=session.pk).update(provider_state=state)
        session.provider_state = state
    except Exception:
        logger.exception('Could not record Collabora session evidence')


def _proof_urls(request, instance):
    full = request.get_full_path()
    out = []
    base = urlsplit(instance.callback_base_url or '')
    if base.scheme and base.netloc:
        out.append(f'{base.scheme}://{base.netloc}{full}')
    try:
        out.append(request.build_absolute_uri())
    except Exception:
        pass
    return out


def _check_proof(request, instance, raw):
    """'verified' | 'absent' (no key published) | 'off' (require_proof off).
    Raises WopiError(500) for a missing or bad signature."""
    if getattr(request, '_office_wopi_selftest', False):
        return 'selftest'
    if not options.get(instance)['require_proof']:
        return 'off'
    try:
        disc = disco.get_discovery(instance)
    except disco.DiscoveryError as e:
        logger.warning('WOPI request refused: discovery unavailable for proof check (%s)', e)
        raise WopiError(500, 'proof key unavailable')
    if not disc.proof_key.present:
        return 'absent'
    kwargs = dict(access_token=raw, urls=_proof_urls(request, instance),
                  timestamp=request.META.get('HTTP_X_WOPI_TIMESTAMP', ''),
                  proof=request.META.get('HTTP_X_WOPI_PROOF', ''),
                  proof_old=request.META.get('HTTP_X_WOPI_PROOFOLD', ''))
    try:
        proofs.verify(disc.proof_key, **kwargs)
        return 'verified'
    except proofs.ProofError as first:
        # The key may have been rotated since discovery was cached.
        import time
        if time.time() - (disc.fetched_at or 0) > 60:
            try:
                disc = disco.get_discovery(instance, refresh=True)
                if not disc.proof_key.present:
                    return 'absent'
                proofs.verify(disc.proof_key, **kwargs)
                return 'verified'
            except (disco.DiscoveryError, proofs.ProofError):
                pass
        logger.warning('WOPI request refused: %s', first)
        raise WopiError(500, 'proof verification failed')


def authenticate(request, file_id, op):
    """(AccessToken with .target, session) or WopiError."""
    if not FILE_ID_RE.match(file_id or ''):
        raise WopiError(404)
    raw = _raw_token(request)
    if not raw:
        raise WopiError(401, 'no access token')
    try:
        found = tokens._lookup(raw)
    except tokens.TokenError:
        raise WopiError(401, 'unknown token')
    session = found.session
    if session.provider != 'collabora' or session.document_key != file_id \
            or session.instance is None:
        raise WopiError(401, 'token is for another file')
    proof_state = _check_proof(request, session.instance, raw)
    try:
        token = tokens.validate(raw, op=op, session_id=session.pk)
    except tokens.TokenError as e:
        from ...targets import target_of
        raise WopiError(403 if e.reason == 'permission' else 401, f'token {e.reason}',
                        session=session, target=target_of(session), reason=e.reason)
    token.proof_state = proof_state
    return token, token.session


def _wrap(handler):
    def view(request, file_id, *args):
        try:
            return handler(request, file_id, *args)
        except WopiError as e:
            if e.status >= 500 or e.status == 401:
                logger.info('WOPI %s %s -> %s (%s)', request.method,
                            handler.__name__, e.status, e.detail)
            return e.response()
    view.__name__ = handler.__name__
    return view


# ---------------------------------------------------------------------------
# CheckFileInfo
# ---------------------------------------------------------------------------

def file_info(token, session, rev):
    from ...providers import get_provider
    target = token.target
    user = session.user
    ext = target.extension
    try:
        caps = get_provider('collabora').capabilities(session.instance)
        editable_here = caps.can_edit(ext)
    except Exception:
        editable_here = False
    can_write = (session.mode == 'edit' and 'write' in token.ops and editable_here
                 and not formats.is_read_only_format(target.filename)
                 and sessions.still_allowed(session))
    can_rename = can_write and 'rename' in token.ops
    opts = options.get(session.instance)
    state = (session.provider_state or {}).get('collabora') or {}
    name = storage.safe_filename(target.filename).replace('/', '_')
    info = {
        'BaseFileName': name,
        'BreadcrumbDocName': name,
        'Size': rev.size,
        'Version': version_of(rev),
        'LastModifiedTime': iso_z(rev.created_at),
        'OwnerId': f'org-{target.organization_id}' if target.organization_id else 'system',
        'UserId': f'user-{user.pk}',
        'UserFriendlyName': (user.get_full_name() or user.username or f'User {user.pk}')[:100],
        'UserCanWrite': bool(can_write),
        'ReadOnly': not can_write,
        'UserCanNotWriteRelative': True,     # PutRelativeFile is not implemented
        'UserCanRename': bool(can_rename),
        'SupportsRename': True,
        'SupportsLocks': True,
        'SupportsGetLock': True,
        'SupportsUpdate': True,              # WOPI spec field; Collabora 26.04 does not read it
        'SupportsExtendedLockLength': True,  # lock ids up to 1024 characters
        'IsAnonymousUser': False,
        'IsAdminUser': False,
        'EnableShare': False,
        'EnableInsertRemoteImage': False,
        'EnableInsertRemoteFile': False,
        'EnableRemoteAIContent': False,
        'DisablePrint': opts['disable_print'],
        'HidePrintOption': opts['disable_print'],
        'DisableExport': opts['hide_export'],
        'HideExportOption': opts['hide_export'],
    }
    origin = state.get('host_origin')
    if origin:
        info['PostMessageOrigin'] = origin
    return info


@_wrap
def _check_file_info(request, file_id):
    token, session = authenticate(request, file_id, 'read')
    target = token.target
    try:
        rev = storage.ensure_current(target)
    except storage.StorageError:
        rev = storage.current(target)
    if rev is None:
        raise WopiError(404, 'no content')
    info = file_info(token, session, rev)
    st = (session.provider_state or {}).get('collabora') or {}
    if not st.get('wopi_seen_at') or st.get('proof') != token.proof_state:
        note(session, wopi_seen_at=timezone.now().isoformat(), proof=token.proof_state)
    resp = JsonResponse(info)
    resp['Cache-Control'] = 'no-store'
    return resp


# ---------------------------------------------------------------------------
# Lock family, RenameFile
# ---------------------------------------------------------------------------

def _lock_response(result, ok_status=200):
    if result.ok:
        resp = HttpResponse(status=ok_status)
        return resp
    resp = HttpResponse(status=409)
    resp['X-WOPI-Lock'] = result.current or ''
    if result.reason:
        resp['X-WOPI-LockFailureReason'] = result.reason[:200]
    return resp


def _holder_gone(target, session):
    """True when the lock's holder session (and its whole co-editing group)
    is no longer live — e.g. the editor crashed without UNLOCK."""
    from ...models import EditSession, WopiLock
    row = WopiLock.objects.filter(target_kind=target.kind, target_pk=target.pk).select_related(
        'session').first()
    if row is None or not row.lock_id:
        return False
    holder = row.session
    if holder is not None and holder.document_key == session.document_key:
        return False
    if holder is None:
        return True
    return not sessions.live_sessions().filter(document_key=holder.document_key).exists()


def _lock(target, session, lock_id, old):
    if old:
        return locks.unlock_and_relock(target, old, lock_id, session)
    result = locks.lock(target, lock_id, session)
    if not result.ok and result.current and _holder_gone(target, session):
        from ...models import WopiLock
        WopiLock.objects.filter(target_kind=target.kind, target_pk=target.pk,
                                lock_id=result.current).update(expires_at=timezone.now())
        result = locks.lock(target, lock_id, session)
    return result


def _rename(request, token, session):
    target = token.target
    lock_id = request.META.get('HTTP_X_WOPI_LOCK', '')
    current = locks.get(target)
    if current and current != lock_id:
        return _lock_response(locks.LockResult(False, current, 'locked by another editor'))
    requested = request.META.get('HTTP_X_WOPI_REQUESTEDNAME', '')
    try:
        requested = requested.encode('latin-1').decode('utf-7')
    except (UnicodeError, ValueError):
        requested = ''
    from ...creation import filename_for
    stem = storage.safe_filename(requested, fallback='').strip()
    if formats.extension(stem) == target.extension:
        stem = stem[:-(len(target.extension) + 1)]
    if not stem or len(stem) > 200:
        resp = HttpResponse(status=400)
        resp['X-WOPI-InvalidFileNameError'] = 'The name is empty, too long or not allowed.'
        return resp
    old = target.filename
    new = filename_for(stem, target.extension)
    target.rename(new, session.user)
    audit.log('rename', user=session.user, target=target,
              description=f'Renamed {old} to {target.filename} from Collabora Online',
              extra={'session': str(session.pk)})
    return JsonResponse({'Name': new[:-(len(target.extension) + 1)]})


@_wrap
def _file_post(request, file_id):
    override = request.META.get('HTTP_X_WOPI_OVERRIDE', '').strip().upper()
    if override == 'PUT_RELATIVE':
        raise WopiError(501, 'PutRelativeFile is not supported')
    if override == 'RENAME_FILE':
        token, session = authenticate(request, file_id, 'rename')
        return _rename(request, token, session)
    if override not in ('LOCK', 'UNLOCK', 'REFRESH_LOCK', 'GET_LOCK'):
        raise WopiError(501 if override else 400, 'unsupported operation')
    token, session = authenticate(request, file_id, 'lock')
    target = token.target
    lock_id = request.META.get('HTTP_X_WOPI_LOCK', '')
    if override == 'GET_LOCK':
        resp = HttpResponse(status=200)
        resp['X-WOPI-Lock'] = locks.get(target)
        return resp
    if override == 'LOCK':
        old = request.META.get('HTTP_X_WOPI_OLDLOCK', '')
        return _lock_response(_lock(target, session, lock_id, old))
    if override == 'REFRESH_LOCK':
        return _lock_response(locks.refresh(target, lock_id, session))
    result = locks.unlock(target, lock_id)
    if result.ok and session.state == 'closing':
        sessions.close(session, reason='editor unlocked the file after the page closed')
    return _lock_response(result)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def wopi_file(request, file_id):
    if request.method == 'GET':
        return _check_file_info(request, file_id)
    return _file_post(request, file_id)


# ---------------------------------------------------------------------------
# GetFile / PutFile
# ---------------------------------------------------------------------------

@_wrap
def _get_file(request, file_id):
    token, session = authenticate(request, file_id, 'read')
    rev = storage.current(token.target)
    if rev is None:
        raise WopiError(404, 'no content')
    expected = request.META.get('HTTP_X_WOPI_MAXEXPECTEDSIZE', '')
    if expected.isdigit() and rev.size > int(expected):
        raise WopiError(412, 'file larger than X-WOPI-MaxExpectedSize')
    if rev.size > storage.max_bytes(session.instance):
        raise WopiError(413, 'file larger than the instance limit')
    resp = FileResponse(storage.open_revision(rev), content_type='application/octet-stream')
    resp['Content-Length'] = str(rev.size)
    resp['X-WOPI-ItemVersion'] = version_of(rev)
    resp['Cache-Control'] = 'no-store'
    return resp


class _Body:
    """The request body in a temp file, hashed, under the size limit."""

    def __init__(self, request, limit):
        self.file = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        digest = hashlib.sha256()
        self.size = 0
        while True:
            chunk = request.read(CHUNK)
            if not chunk:
                break
            self.size += len(chunk)
            if self.size > limit:
                self.file.close()
                raise WopiError(413, 'file too large')
            digest.update(chunk)
            self.file.write(chunk)
        self.sha256 = digest.hexdigest()
        self.file.seek(0)

    def rewind(self):
        self.file.seek(0)
        return self.file

    def close(self):
        self.file.close()


def _flag(request, name):
    for prefix in ('HTTP_X_COOL_WOPI_', 'HTTP_X_LOOL_WOPI_'):
        value = request.META.get(prefix + name)
        if value is not None:
            return value.strip().lower() == 'true'
    return None


def _quarantine(target, body, session, reason, detail):
    from ... import quarantine
    try:
        q = quarantine.keep_bytes(target, body.rewind(), session=session, user=session.user,
                                  reason=reason, detail=detail,
                                  original_name=target.filename if target else None)
        audit.save_failed(target, session.user, session=session, reason=reason, detail=detail,
                          quarantined=q)
        return q
    except Exception:
        logger.exception('Could not quarantine a refused Collabora save')
        return None


def _put_ok(rev):
    resp = JsonResponse({'LastModifiedTime': iso_z(rev.created_at)})
    resp['X-WOPI-ItemVersion'] = version_of(rev)
    return resp


@_wrap
def _put_file(request, file_id):
    if request.META.get('HTTP_X_WOPI_OVERRIDE', '').strip().upper() != 'PUT':
        raise WopiError(400, 'X-WOPI-Override must be PUT')
    declared = request.META.get('CONTENT_LENGTH', '')
    try:
        token, session = authenticate(request, file_id, 'write')
    except WopiError as e:
        # Revoked / expired / permission lost: keep what was sent.
        if e.session is not None and e.status in (401, 403):
            body = _Body(request, storage.max_bytes(e.session.instance))
            try:
                _quarantine(e.target, body, e.session,
                            'permission' if e.reason == 'permission' else 'revoked',
                            f'WOPI PutFile refused: token {e.reason}')
            finally:
                body.close()
        raise
    target = token.target
    limit = storage.max_bytes(session.instance)
    if declared.isdigit() and int(declared) > limit:
        raise WopiError(413, 'file too large')
    body = _Body(request, limit)
    try:
        cur = storage.current(target)
        if cur is None:
            raise WopiError(404, 'no content')
        modified_by_user = _flag(request, 'ISMODIFIEDBYUSER')
        autosave = _flag(request, 'ISAUTOSAVE')
        exit_save = _flag(request, 'ISEXITSAVE')

        lock_id = request.META.get('HTTP_X_WOPI_LOCK', '')
        lock = locks.check_write(target, lock_id, file_size=cur.size)
        if not lock.ok:
            _quarantine(target, body, session, 'stale', f'WOPI lock conflict ({lock.reason})')
            resp = HttpResponse(status=409)
            resp['X-WOPI-Lock'] = lock.current or ''
            return resp

        stamp = (request.META.get('HTTP_X_COOL_WOPI_TIMESTAMP')
                 or request.META.get('HTTP_X_LOOL_WOPI_TIMESTAMP'))
        if stamp and not same_time(stamp, cur.created_at):
            if (cur.sha256 == body.sha256 and cur.editor_session_id is not None
                    and cur.editor_session.document_key == session.document_key):
                # A retry of a save we already stored (the reply was lost).
                return _put_ok(cur)
            _quarantine(target, body, session, 'stale',
                        f'Document changed in storage since the editor loaded it '
                        f'(current revision {cur.revision_number})')
            return JsonResponse({'COOLStatusCode': DOC_CHANGED}, status=409)

        outcome = storage.save_or_quarantine(
            target, body.rewind(), user=session.user, source='editor_save',
            expected_base_revision=cur.revision_number, session=session,
            original_name=target.filename)
    finally:
        body.close()

    if outcome.ok:
        rev = outcome.revision
        note(session, last_put={
            'revision': rev.revision_number, 'duplicate': outcome.duplicate,
            'modified_by_user': modified_by_user, 'autosave': autosave, 'exit_save': exit_save,
            'forced': not stamp, 'at': timezone.now().isoformat()})
        logger.info('Collabora save stored as revision %s (autosave=%s exit=%s user_modified=%s '
                    'duplicate=%s)', rev.revision_number, autosave, exit_save, modified_by_user,
                    outcome.duplicate)
        return _put_ok(rev)
    err = outcome.error
    if isinstance(err, storage.StaleRevision):
        return JsonResponse({'COOLStatusCode': DOC_CHANGED}, status=409)
    if isinstance(err, storage.SessionRevoked):
        return HttpResponse(status=401)
    if isinstance(err, storage.PermissionRevoked):
        return HttpResponse(status=403)
    if isinstance(err, storage.RevisionRejected):
        return HttpResponse(status=413 if getattr(err, 'code', '') == 'too_large' else 400)
    return HttpResponse(status=500)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def wopi_contents(request, file_id):
    if request.method == 'GET':
        return _get_file(request, file_id)
    return _put_file(request, file_id)
