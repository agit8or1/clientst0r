"""Office file actions and the full-screen editor page.

Every view that takes a file resolves it with targets.resolve_for(), which
404s both for a missing row and for a row the user may not see — another
tenant's file is indistinguishable from no file. Writes re-check edit
permission (resolve_for(..., edit=True)) and office.storage checks it again
inside the write transaction.
"""
from __future__ import annotations

from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from django.middleware.csrf import get_token

from core.middleware import get_request_organization

from . import audit, creation, formats, policy, sessions, storage, targets
from .logging_filters import get_logger
from .models import EditSession, FileRevision, OfficeFile, QuarantinedSave
from .providers import NotConfigured, NotSupported, get_provider

logger = get_logger('office.views')


def _back(request, target):
    nxt = request.POST.get('next') or request.GET.get('next') or ''
    from django.utils.http import url_has_allowed_host_and_scheme
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return redirect(nxt)
    return redirect(reverse('office:target_detail', args=[target.code, target.pk]))


def _stream(request, path_name, download_name, *, inline=False):
    from core.media_views import resolve_under_media_root, stream_file
    full = resolve_under_media_root(path_name)
    response = stream_file(request, full, download_name, download_name)
    response['Content-Type'] = formats.mime_for(download_name)
    from django.utils.http import content_disposition_header
    response['Content-Disposition'] = content_disposition_header(not inline, download_name)
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


# ---------------------------------------------------------------------------
# File page, history, download
# ---------------------------------------------------------------------------

@login_required
@require_GET
def target_detail(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    file_error = ''
    try:
        rev = storage.ensure_current(target)
    except storage.StorageError as e:
        rev, file_error = None, e.message or 'The stored file cannot be used.'
    av = policy.availability(request.user, target)
    preview = None
    if target.has_file():
        from docs.services.file_preview import build_preview
        preview = build_preview(target.file)
    audit.log('open', user=request.user, target=target, request=request,
              description=f'Viewed {target.filename}')
    return render(request, 'office/target_detail.html', {
        'target': target, 'revision': rev, 'file_error': file_error, 'av': av,
        'file_preview': preview,
        # docs/_file_preview.html links its download through `document`.
        'document': SimpleNamespace(
            file=SimpleNamespace(url=reverse('office:download', args=[target.code, target.pk])),
            file_size=target.size, file_type=formats.mime_for(target.filename)),
        'revisions': storage.revisions(target).select_related('created_by')[:10],
        'can_copy': creation.can_copy(target, request.user),
        'can_edit_file': target.can_edit(request.user),
        'back_url': target.back_url(),
    })


@login_required
@require_GET
def target_versions(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    try:
        storage.ensure_current(target)
    except storage.StorageError:
        pass
    can_edit = target.can_edit(request.user)
    quarantined = QuarantinedSave.objects.filter(**target.fk_id()).select_related('user') \
        if can_edit else QuarantinedSave.objects.none()
    return render(request, 'office/versions.html', {
        'target': target,
        'revisions': storage.revisions(target).select_related('created_by', 'restored_from'),
        'quarantined': quarantined, 'can_edit_file': can_edit, 'back_url': target.back_url(),
    })


@login_required
@require_GET
def download(request, code, pk, number=None):
    target = targets.resolve_for(request.user, code, pk)
    if number is None:
        try:
            rev = storage.ensure_current(target)
        except storage.StorageError:
            rev = None
        if rev is None:
            if not target.has_file():
                raise Http404('Not found')
            name = target.file.name
        else:
            name = rev.file.name
    else:
        rev = storage.revisions(target).filter(revision_number=number).first()
        if rev is None:
            raise Http404('Not found')
        name = rev.file.name
    download_name = storage.safe_filename(target.filename)
    if number is not None:
        ext = target.extension
        stem = download_name[:-(len(ext) + 1)] if ext else download_name
        download_name = storage.safe_filename(f'{stem} (revision {number}).{ext}')
    audit.log('download', user=request.user, target=target, request=request,
              description=f'Downloaded {target.filename}'
                          + (f' revision {number}' if number else ''),
              extra={'revision': number or (rev.revision_number if rev else None)})
    return _stream(request, name, download_name)


# ---------------------------------------------------------------------------
# Rename / copy / restore / export / convert
# ---------------------------------------------------------------------------

@login_required
@require_POST
def rename(request, code, pk):
    target = targets.resolve_for(request.user, code, pk, edit=True)
    old = target.filename
    new = storage.safe_filename(request.POST.get('name', ''), fallback='Untitled')
    ext = target.extension
    if formats.extension(new) != ext:
        new = creation.filename_for(new, ext)
    if new != old:
        target.rename(new, request.user)
        audit.log('rename', user=request.user, target=target, request=request,
                  description=f'Renamed {old} to {target.filename}')
        messages.success(request, f'Renamed to {target.filename}.')
    return _back(request, target)


@login_required
@require_POST
def copy(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    try:
        new = creation.make_copy(target, request.user, new_name=request.POST.get('name') or None,
                                 request=request)
    except PermissionDenied:
        raise Http404('Not found')
    except storage.StorageError as e:
        messages.error(request, f'Could not copy the file: {e.message}')
        return _back(request, target)
    messages.success(request, f'Saved a copy as {new.filename}.')
    return redirect(new.back_url() if new.kind == 'document' else
                    reverse('office:target_detail', args=[new.code, new.pk]))


@login_required
@require_POST
def restore(request, code, pk, number):
    target = targets.resolve_for(request.user, code, pk, edit=True)
    rev = storage.revisions(target).filter(revision_number=number).first()
    if rev is None:
        raise Http404('Not found')
    try:
        new = storage.restore(target, rev, request.user)
    except storage.StorageError as e:
        messages.error(request, f'Could not restore: {e.message}')
        return _back(request, target)
    audit.log('restore', user=request.user, target=target, request=request,
              description=f'Restored revision {number} of {target.filename} '
                          f'as revision {new.revision_number}',
              extra={'restored': number, 'revision': new.revision_number})
    messages.success(request, f'Revision {number} restored as revision {new.revision_number}.')
    return _back(request, target)


@login_required
@require_POST
def export_pdf(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    av = policy.availability(request.user, target)
    if not (av.capabilities and av.capabilities.can_export_pdf(target.extension)):
        messages.error(request, 'PDF export is not available for this file.')
        return _back(request, target)
    rev = storage.ensure_current(target)
    try:
        data = av.provider.convert(av.instance, rev, 'pdf', user=request.user)
    except (NotConfigured, NotSupported) as e:
        messages.error(request, str(e) or 'PDF export is not available.')
        return _back(request, target)
    except Exception:
        logger.exception('PDF export failed')
        messages.error(request, 'The editor could not export this file to PDF.')
        return _back(request, target)
    audit.log('export', user=request.user, target=target, request=request,
              description=f'Exported revision {rev.revision_number} of {target.filename} to PDF',
              extra={'revision': rev.revision_number, 'format': 'pdf', 'instance': av.instance.pk})
    stem = target.filename[:-(len(target.extension) + 1)]
    response = HttpResponse(data, content_type='application/pdf')
    from django.utils.http import content_disposition_header
    response['Content-Disposition'] = content_disposition_header(True, storage.safe_filename(f'{stem}.pdf'))
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_POST
def convert(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    av = policy.availability(request.user, target)
    try:
        new = creation.convert_to_copy(target, request.user, av, request=request)
    except PermissionDenied:
        messages.error(request, 'Conversion is not available for this file.')
        return _back(request, target)
    except (NotConfigured, NotSupported, storage.StorageError) as e:
        messages.error(request, f'Conversion failed: {getattr(e, "message", "") or e}')
        return _back(request, target)
    messages.success(request, f'Converted to a new copy: {new.filename}. The original is unchanged.')
    return redirect(new.back_url() if new.kind == 'document' else
                    reverse('office:target_detail', args=[new.code, new.pk]))


@login_required
@require_GET
def quarantine_download(request, code, pk, qid):
    target = targets.resolve_for(request.user, code, pk, edit=True)
    q = QuarantinedSave.objects.filter(pk=qid, **target.fk_id()).first()
    if q is None:
        raise Http404('Not found')
    audit.log('quarantine_download', user=request.user, target=target, request=request,
              description=f'Downloaded quarantined save #{q.pk} of {target.filename}')
    ext = target.extension
    stem = target.filename[:-(len(ext) + 1)] if ext else target.filename
    return _stream(request, q.file.name,
                   storage.safe_filename(f'{stem} (unsaved {q.received_at:%Y-%m-%d %H%M}).{ext}'))


@login_required
@require_POST
def quarantine_restore(request, code, pk, qid):
    target = targets.resolve_for(request.user, code, pk, edit=True)
    q = QuarantinedSave.objects.filter(pk=qid, **target.fk_id()).first()
    if q is None:
        raise Http404('Not found')
    try:
        with open(storage._abs(q.file.name), 'rb') as fh:
            rev = storage.save_new_revision(target, fh, user=request.user, source='restore')
    except storage.StorageError as e:
        messages.error(request, f'Could not restore the quarantined save: {e.message}')
        return _back(request, target)
    QuarantinedSave.objects.filter(pk=q.pk).update(recovered_revision=rev)
    audit.log('quarantine_restore', user=request.user, target=target, request=request,
              description=f'Restored quarantined save #{q.pk} as revision {rev.revision_number}',
              extra={'quarantine_id': q.pk, 'revision': rev.revision_number})
    messages.success(request, f'Saved as revision {rev.revision_number}.')
    return _back(request, target)


# ---------------------------------------------------------------------------
# Creating files
# ---------------------------------------------------------------------------

@login_required
@require_POST
def new_document(request, fmt):
    if fmt not in creation.NEW_FORMATS:
        raise Http404('Not found')
    org = get_request_organization(request)
    if org is None:
        messages.error(request, 'Select an organization first.')
        return redirect('docs:document_list')
    try:
        target = creation.new_document(org, fmt, request.POST.get('title', ''), request.user,
                                       request=request)
    except PermissionDenied:
        messages.error(request, 'Your role does not allow creating documents for this organization.')
        return redirect('docs:document_list')
    except storage.StorageError as e:
        messages.error(request, f'Could not create the file: {e.message}')
        return redirect('docs:document_list')
    messages.success(request, f'Created {target.filename}.')
    return redirect(target.back_url())


_NEW_ATTACHMENT_ENTITIES = {'asset', 'document'}


@login_required
@require_POST
def new_attachment(request, fmt):
    if fmt not in creation.NEW_FORMATS:
        raise Http404('Not found')
    org = get_request_organization(request)
    entity_type = request.POST.get('entity_type', '')
    try:
        entity_id = int(request.POST.get('entity_id', ''))
    except ValueError:
        raise Http404('Not found')
    from files.views import _entity_exists
    if org is None or entity_type not in _NEW_ATTACHMENT_ENTITIES \
            or not _entity_exists(entity_type, entity_id, org):
        raise Http404('Not found')
    try:
        target = creation.new_attachment(org, entity_type, entity_id, fmt,
                                         request.POST.get('title', ''), request.user,
                                         request=request)
    except PermissionDenied:
        raise Http404('Not found')
    except storage.StorageError as e:
        messages.error(request, f'Could not create the file: {e.message}')
        return redirect(request.POST.get('next') or 'docs:document_list')
    messages.success(request, f'Created {target.filename}.')
    return redirect(reverse('office:target_detail', args=[target.code, target.pk]))


def _templates_for(user, org):
    from django.db.models import Q
    qs = OfficeFile.objects.filter(purpose='template', is_active=True)
    qs = qs.filter(Q(organization__isnull=True) | Q(organization=org)) if org else \
        qs.filter(organization__isnull=True)
    return [t for t in qs.order_by('organization_id', 'name')
            if targets.OfficeFileTarget(t).can_view(user)]


@login_required
@require_http_methods(['GET', 'POST'])
def new_from_template(request):
    org = get_request_organization(request)
    if org is None:
        messages.error(request, 'Select an organization first.')
        return redirect('docs:document_list')
    if not creation.can_create_document(request.user, org):
        raise PermissionDenied('Your role does not allow creating documents here.')
    available = _templates_for(request.user, org)
    if request.method == 'POST':
        chosen = next((t for t in available if str(t.pk) == request.POST.get('template')), None)
        if chosen is None:
            raise Http404('Not found')
        try:
            target = creation.from_template(targets.OfficeFileTarget(chosen), org,
                                            request.POST.get('title', ''), request.user,
                                            request=request)
        except PermissionDenied:
            raise Http404('Not found')
        except storage.StorageError as e:
            messages.error(request, f'Could not create the file: {e.message}')
            return redirect('office:new_from_template')
        messages.success(request, f'Created {target.filename} from {chosen.name}.')
        return redirect(target.back_url())
    return render(request, 'office/new_from_template.html', {
        'templates': available, 'org': org,
        'can_manage': request.user.is_superuser or targets._has_perm_for_org(
            request.user, org.pk, 'org_manage_settings'),
    })


# ---------------------------------------------------------------------------
# Editor page
# ---------------------------------------------------------------------------

@login_required
@require_POST
def open_editor(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    mode = 'edit' if request.POST.get('mode') == 'edit' else 'view'
    av = policy.availability(request.user, target)
    if (mode == 'edit' and not av.can_edit) or (mode == 'view' and not av.can_view_in_editor):
        messages.error(request, av.reason or 'The editor is not available for this file.')
        return _back(request, target)
    try:
        session = sessions.open_session(target, request.user, mode=mode, instance=av.instance,
                                        request=request)
    except PermissionDenied:
        raise Http404('Not found')
    except NotConfigured as e:
        messages.error(request, str(e))
        return _back(request, target)
    except storage.StorageError as e:
        messages.error(request, f'This file cannot be opened in the editor: {e.message}')
        return _back(request, target)
    return redirect('office:editor', session_id=session.pk)


_CSP_KEYS = ('script-src', 'frame-src', 'connect-src', 'form-action', 'img-src', 'child-src',
             'worker-src')


def _origin_str(url):
    from .net import _origin
    scheme, host, port = _origin(url)
    default = 443 if scheme == 'https' else 80
    host_part = f'[{host}]' if ':' in host else host
    return f'{scheme}://{host_part}' + ('' if port == default else f':{port}')


def editor_csp(request, response, instance, extra):
    """Set the editor page's CSP: the site policy plus the instance's browser
    origin (and its WebSocket form) for the directives the provider asked
    for. Any other source the provider names is dropped."""
    from django.conf import settings
    from core.csp_middleware import build_csp_header
    origin = _origin_str(instance.browser_url)
    ws = origin.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
    allowed = {origin, ws}
    policy_cfg = {k: list(v) for k, v in getattr(settings, 'CSP_POLICY', {}).items()}
    for key, sources in (extra or {}).items():
        if key not in _CSP_KEYS:
            continue
        keep = [s for s in sources if s.rstrip('/') in allowed]
        if keep:
            policy_cfg.setdefault(key, [])
            policy_cfg[key] = list(dict.fromkeys(policy_cfg[key] + keep))
    if not getattr(settings, 'CSP_ENABLED', True):
        return response
    header, value, extra_headers = build_csp_header(request, response, policy=policy_cfg)
    if value:
        response[header] = value
        for k, v in extra_headers.items():
            response[k] = v
    return response


@login_required
@require_GET
def editor(request, session_id):
    session = sessions.get_live(session_id, user=request.user)
    target = targets.target_of(session)
    if target is None or not sessions.still_allowed(session):
        sessions.revoke(session, 'permission lost' if target else 'file deleted')
        raise Http404('Not found')
    instance = session.instance
    page = None
    error = ''
    try:
        page = get_provider(session.provider).editor_page_context(session, request)
    except NotConfigured as e:
        error = str(e) or 'The editor connector is not available.'
        EditSession.objects.filter(pk=session.pk).update(
            state='failed', closed_at=timezone.now(), end_reason=error[:255])
    origin = _origin_str(instance.browser_url) if instance else ''
    script_urls = [u for u in (page.script_urls if page else [])
                   if instance and _origin_str(u) == origin and u.startswith(('https://', 'http://'))]
    office_config = {
        'sessionId': str(session.pk),
        'mode': session.mode,
        'readOnly': session.mode != 'edit',
        'statusUrl': reverse('office:editor_status', args=[session.pk]),
        'renewUrl': reverse('office:editor_renew', args=[session.pk]),
        'closeUrl': reverse('office:editor_close', args=[session.pk]),
        'downloadUrl': reverse('office:download', args=[target.code, target.pk]),
        'baseRevision': session.base_revision.revision_number if session.base_revision else None,
        'editorOrigin': origin,
        'failed': bool(error),
        'csrfToken': get_token(request),
    }
    response = render(request, 'office/editor.html', {
        'session': session, 'target': target, 'page': page, 'error': error,
        'office_config': office_config,
        'provider_config': page.config if page else {},
        'script_urls': script_urls,
        'back_url': target.back_url(),
        'organization': target.organization,
    })
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    if page and instance:
        editor_csp(request, response, instance, page.csp)
    return response


def _session_for_owner(request, session_id):
    session = (EditSession.objects.select_related('base_revision', 'user', 'instance')
               .filter(pk=session_id, user=request.user).first())
    if session is None:
        raise Http404('Not found')
    return session


@login_required
@require_GET
def editor_status(request, session_id):
    """Save status for the editor page's indicator (polled by office-editor.js)."""
    session = _session_for_owner(request, session_id)
    target = targets.target_of(session)
    cur = storage.current(target) if target is not None else None
    last_session_save = (FileRevision.objects.filter(editor_session__document_key=session.document_key,
                                                     **(target.fk_id() if target else {}))
                         .order_by('-revision_number').first()) if target else None
    q = session.quarantined_saves.order_by('-received_at').first()
    return JsonResponse({
        'state': session.state if session.expires_at > timezone.now() or session.state not in
        EditSession.LIVE_STATES else 'expired',
        'mode': session.mode,
        'baseRevision': session.base_revision.revision_number if session.base_revision else None,
        'currentRevision': cur.revision_number if cur else None,
        'lastSavedRevision': last_session_save.revision_number if last_session_save else None,
        'lastSavedAt': last_session_save.created_at.isoformat() if last_session_save else None,
        'lastFailure': ({'at': q.received_at.isoformat(), 'reason': q.reason,
                         'label': q.get_reason_display()} if q else None),
        'expiresAt': session.expires_at.isoformat(),
    })


@login_required
@require_POST
def editor_renew(request, session_id):
    session = _session_for_owner(request, session_id)
    try:
        session = sessions.renew(session)
    except storage.SessionRevoked as e:
        return JsonResponse({'ok': False, 'error': e.message}, status=409)
    return JsonResponse({'ok': True, 'expiresAt': session.expires_at.isoformat()})


@login_required
@require_POST
def editor_close(request, session_id):
    session = _session_for_owner(request, session_id)
    sessions.close(session, reason='closed by user', pending_final_save=session.mode == 'edit',
                   request=request)
    if request.headers.get('Accept', '').startswith('application/json') or \
            request.POST.get('beacon'):
        return JsonResponse({'ok': True})
    target = targets.target_of(session)
    return redirect(target.back_url() if target else 'docs:document_list')
