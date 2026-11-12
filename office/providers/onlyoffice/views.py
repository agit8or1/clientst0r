"""ONLYOFFICE endpoints, mounted under /office/api/onlyoffice/.

Reached by the Document Server (csrf_exempt, authenticated by the outbox JWT
plus an Office access token or a signed source link, never request.user):

    callback/<session>/          save callback (callback.handle)
    file/<session>/?access_token=  the document.url: the session's revision
    source/<signed>/             a revision (or the blank probe file) for the
                                 conversion service

Reached by the signed-in user's browser (login + CSRF, owner of the session):

    session/<session>/status/    editor-reported errors and collaborators
    session/<session>/forcesave/ "Save now" (command service forcesave)
    session/<session>/save-as/   onRequestSaveAs: store a copy

Superusers only:

    instances/<pk>/browser-probe/          loads api.js in the admin's browser
    instances/<pk>/browser-probe/result/   records what the browser saw
"""
from __future__ import annotations

import json
import re

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core import signing as dj_signing
from django.middleware.csrf import get_token
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from office import audit, creation, formats, net, sessions, storage, tokens
from office.logging_filters import get_logger
from office.models import EditorInstance, EditSession, FileRevision
from office.targets import target_of

from . import callback as cb
from . import client, signing, state

log = get_logger('office.onlyoffice')

SOURCE_SALT = 'office.onlyoffice.source'


# ---------------------------------------------------------------------------
# Document Server -> clientst0r
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def callback(request, session_id):
    status, reply = cb.handle(request, session_id)
    return JsonResponse(reply, status=status)


def verify_download_jwt(request, instance):
    """Docs signs its downloads with the outbox secret (operation 'download'
    since 10.0). Raises signing.InvalidToken."""
    raw = request.headers.get(signing.header_name(instance), '')
    token = signing.bearer(raw)
    if not token:
        raise signing.InvalidToken('missing')
    return signing.decode(token, instance.shared_secret, operation='download')


def _file_response(path_name, name):
    from core.media_views import resolve_under_media_root
    full = resolve_under_media_root(path_name)
    response = FileResponse(open(full, 'rb'), content_type=formats.mime_for(name))
    response['Content-Disposition'] = 'attachment'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def session_revision(session):
    """The revision the session's editor key stands for: the newest revision
    its co-editing group saved, else the one it opened on."""
    target = target_of(session)
    if target is None:
        return None
    number = sessions.expected_base(session)
    return storage.revisions(target).filter(revision_number=number).first()


@csrf_exempt
@require_GET
def document_file(request, session_id):
    raw = request.GET.get('access_token', '')
    try:
        token = tokens.validate(raw, op='read', session_id=session_id)
    except tokens.TokenError:
        raise Http404('Not found')
    session = token.session
    if session.provider != 'onlyoffice' or session.instance is None:
        raise Http404('Not found')
    try:
        verify_download_jwt(request, session.instance)
    except signing.InvalidToken as e:
        log.warning('ONLYOFFICE document download for session %s refused: %s', session.pk, e.reason)
        return HttpResponse(status=403)
    rev = session_revision(session)
    if rev is None:
        raise Http404('Not found')
    state.update(session.pk, oo_file_fetched_at=state.now_iso())
    audit.log('download', user=session.user, target=token.target,
              description=f'Editor {session.instance.name} fetched revision '
                          f'{rev.revision_number} of {token.target.filename}',
              extra={'by': 'editor', 'session': str(session.pk), 'instance': session.instance.pk,
                     'revision': rev.revision_number})
    return _file_response(rev.file.name, token.target.filename)


def source_link(instance, revision=None, *, probe_ext=None) -> str:
    """Signed, expiring URL the conversion service downloads from."""
    payload = {'i': instance.pk}
    if revision is not None:
        payload['r'] = revision.pk
    else:
        payload['p'] = probe_ext or 'docx'
    value = dj_signing.dumps(payload, salt=SOURCE_SALT, compress=True)
    from django.urls import reverse
    return instance.callback_base_url.rstrip('/') + reverse('office:onlyoffice_source', args=[value])


@csrf_exempt
@require_GET
def source(request, signed):
    instance_max_age = 600
    try:
        payload = dj_signing.loads(signed, salt=SOURCE_SALT, max_age=instance_max_age)
    except dj_signing.BadSignature:
        raise Http404('Not found')
    instance = EditorInstance.objects.filter(pk=payload.get('i'), provider='onlyoffice').first()
    if instance is None:
        raise Http404('Not found')
    try:
        verify_download_jwt(request, instance)
    except signing.InvalidToken as e:
        log.warning('ONLYOFFICE source download refused: %s', e.reason)
        return HttpResponse(status=403)
    if 'p' in payload:
        if payload['p'] not in creation.NEW_FORMATS:
            raise Http404('Not found')
        response = HttpResponse(creation.blank_bytes(payload['p']),
                                content_type=formats.mime_for('x.' + payload['p']))
        response['Cache-Control'] = 'no-store'
        return response
    rev = FileRevision.objects.filter(pk=payload.get('r')).first()
    if rev is None:
        raise Http404('Not found')
    target = target_of(rev)
    audit.log('download', user=None, target=target, organization_id=rev.organization_id,
              description=f'Editor {instance.name} fetched revision {rev.revision_number} '
                          f'for conversion',
              extra={'by': 'editor', 'instance': instance.pk, 'revision': rev.revision_number})
    return _file_response(rev.file.name, rev.original_name)


# ---------------------------------------------------------------------------
# Browser (editor page) helpers
# ---------------------------------------------------------------------------

def _owned_session(request, session_id, *, live=True):
    session = (EditSession.objects.select_related('instance', 'user')
               .filter(pk=session_id, user=request.user, provider='onlyoffice').first())
    if session is None or (live and not session.is_live):
        raise Http404('Not found')
    return session


@login_required
@require_GET
def session_status(request, session_id):
    session = _owned_session(request, session_id, live=False)
    members = list(state.group(session).select_related('user'))
    key = (session.provider_state or {}).get('oo_key')
    error, users, users_at = None, [], ''
    for s in members:
        ps = s.provider_state or {}
        e = ps.get('oo_last_error')
        if e and ps.get('oo_key') == key and (error is None or e.get('at', '') > error.get('at', '')):
            error = e
        if ps.get('oo_key') == key and ps.get('oo_users_at', '') > users_at:
            users, users_at = ps.get('oo_users') or [], ps['oo_users_at']
    names = {}
    for s in members:
        uid = (s.provider_state or {}).get('oo_user')
        if uid in users and s.is_live:
            names[uid] = state.display_name(s.user)
    return JsonResponse({
        'editorError': ({'at': error.get('at'), 'message': error.get('message', '')}
                        if error else None),
        'collaborators': [{'id': uid, 'name': name} for uid, name in names.items()],
    })


@login_required
@require_POST
def forcesave(request, session_id):
    session = _owned_session(request, session_id)
    if session.mode != 'edit':
        return JsonResponse({'ok': False, 'error': 'This session is read-only.'}, status=409)
    if not sessions.still_allowed(session):
        sessions.revoke(session, 'permission lost')
        raise Http404('Not found')
    key = (session.provider_state or {}).get('oo_key')
    if not key:
        return JsonResponse({'ok': False, 'error': 'The editor has not opened the document yet.'},
                            status=409)
    try:
        client.command(session.instance, 'forcesave', key=key, userdata=str(session.pk))
    except client.DocsError as e:
        if e.code == 4:
            return JsonResponse({'ok': True, 'noChanges': True})
        log.warning('ONLYOFFICE forcesave failed for session %s: %s', session.pk, e)
        return JsonResponse({'ok': False, 'error': 'The editor refused the save request.'},
                            status=502)
    except net.OfficeFetchError as e:
        log.warning('ONLYOFFICE forcesave unreachable for session %s: %s', session.pk, e)
        return JsonResponse({'ok': False, 'error': 'The editor service is unreachable.'}, status=502)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def save_as(request, session_id):
    """onRequestSaveAs: the editor offers a file URL on its own host; it is
    fetched server-side (net.fetch: approved origin only) and stored as a new
    copy next to the original."""
    session = _owned_session(request, session_id)
    target = target_of(session)
    if target is None or not creation.can_copy(target, request.user):
        raise Http404('Not found')
    url = request.POST.get('url', '')
    ext = (request.POST.get('fileType') or '').lower()
    if ext not in formats.EDITABLE or formats.EDITABLE[ext] != formats.kind_for(target.filename):
        return JsonResponse({'ok': False, 'error': 'That file type cannot be saved here.'}, status=400)
    try:
        data = client.download(session.instance, url, storage.max_bytes(session.instance))
    except net.DestinationNotAllowed:
        return JsonResponse({'ok': False, 'error': 'The file is not on the editor host.'}, status=400)
    except net.OfficeFetchError:
        return JsonResponse({'ok': False, 'error': 'The file could not be downloaded.'}, status=502)
    title = request.POST.get('title') or creation.copy_name(target)
    stem = title.rsplit('.', 1)[0] if '.' in title else title
    copy = target.create_copy(creation.filename_for(stem, ext), request.user)
    try:
        copy = creation._store_or_discard(copy, data, request.user, 'copy', 'copy', request,
                                          f'Saved a copy of {target.filename} from the editor',
                                          {'source_target': f'{target.code}:{target.pk}'})
    except storage.StorageError as e:
        return JsonResponse({'ok': False, 'error': e.message or 'The copy was refused.'}, status=400)
    from django.urls import reverse
    return JsonResponse({'ok': True, 'name': copy.filename,
                         'url': reverse('office:target_detail', args=[copy.code, copy.pk])})


# ---------------------------------------------------------------------------
# Browser reachability probe (superusers)
# ---------------------------------------------------------------------------

def _superuser(user):
    return user.is_authenticated and user.is_superuser


@login_required
@user_passes_test(_superuser)
@require_GET
def browser_probe(request, pk):
    from office.views import editor_csp
    instance = get_object_or_404(EditorInstance, pk=pk, provider='onlyoffice')
    api_js = client.browser_base(instance) + '/web-apps/apps/api/documents/api.js'
    from django.urls import reverse
    response = render(request, 'office/providers/onlyoffice/browser_probe.html', {
        'instance': instance, 'active_page': 'office_documents',
        'probe_config': {'apiUrl': api_js, 'csrfToken': get_token(request),
                         'resultUrl': reverse('office:onlyoffice_browser_probe_result', args=[pk])},
    })
    response['Cache-Control'] = 'no-store'
    origin = _origin(instance.browser_url)
    return editor_csp(request, response, instance, {'script-src': [origin], 'connect-src': [origin]})


def _origin(url):
    from office.views import _origin_str
    return _origin_str(url)


_VERSION_RE = re.compile(r'^[0-9][0-9.]{0,30}$')


@login_required
@user_passes_test(_superuser)
@require_POST
def browser_probe_result(request, pk):
    instance = get_object_or_404(EditorInstance, pk=pk, provider='onlyoffice')
    outcome = request.POST.get('outcome', '')
    if outcome not in ('loaded', 'error', 'timeout', 'no_api'):
        return JsonResponse({'ok': False}, status=400)
    version = request.POST.get('version', '')
    version = version if _VERSION_RE.match(version) else ''
    audit.log('browser_probe', user=request.user, request=request, object_type='office.instance',
              object_id=instance.pk, object_repr=instance.name, success=outcome == 'loaded',
              description=f'Browser probe of {instance.name}: {outcome}',
              extra={'outcome': outcome, 'api_version': version,
                     'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200]})
    return JsonResponse({'ok': True})


def last_browser_probe(instance):
    from audit.models import AuditLog
    return (AuditLog.objects.filter(object_type='office.instance', object_id=instance.pk,
                                    extra_data__office_event='browser_probe')
            .order_by('-pk').first())
