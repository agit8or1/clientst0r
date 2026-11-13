"""Views for Edit in Microsoft 365 (m365docs.editing). URLs are under
/integrations/m365/documents/edit/.

Every request is a CSRF-protected POST. The file is resolved with
office.targets.resolve_for (a file the user may not see is a 404), sessions
are looked up by id *and* owner (anyone else's is a 404), and the service
re-checks edit permission before any Graph call.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.decorators import require_admin
from office import targets

from . import audit, editing
from .views import _connection, _location, handles_microsoft_errors


def _permission_message(view):
    """A permission lost mid-session ends the session (editing.py); say so
    instead of showing a bare 403."""
    from functools import wraps

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except PermissionDenied as e:
            messages.error(request, str(e) or 'Not allowed.')
            return redirect(reverse('integrations:m365docs_home'))
    return wrapper


def _no_referrer(response):
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response


def _file_page(target):
    return reverse('office:target_detail', args=[target.code, target.pk])


def _session_back(session):
    from office.targets import target_of
    target = target_of(session)
    return _file_page(target) if target is not None else reverse('integrations:m365docs_home')


@login_required
@require_POST
@handles_microsoft_errors
def start(request, code, pk):
    target = targets.resolve_for(request.user, code, pk)
    conns = editing.edit_connections(request.user, target)
    wanted = request.POST.get('connection', '')
    conn = next((c for c in conns if str(c.pk) == wanted), None) if wanted else \
        (conns[0] if conns else None)
    if conn is None:
        raise Http404('Not found')
    try:
        session, created = editing.start(request.user, target, conn, request=request)
    except PermissionDenied:
        raise Http404('Not found')
    if session.state != 'open':
        messages.info(request, 'The working copy is still being prepared. Try again in a moment.')
        return redirect(_file_page(target))
    if not created:
        url = editing.open_url(request.user, session, request=request)
    else:
        url = session.web_url
    return _no_referrer(HttpResponseRedirect(url))


def _session(request, sid):
    return editing.session_for(request.user, sid)


@login_required
@require_POST
@handles_microsoft_errors
@_permission_message
def open_session(request, sid):
    session = _session(request, sid)
    url = editing.open_url(request.user, session, request=request)
    return _no_referrer(HttpResponseRedirect(url))


@login_required
@require_POST
@handles_microsoft_errors
@_permission_message
def check(request, sid):
    session = _session(request, sid)
    back = _session_back(session)
    info = editing.check_changes(request.user, session, request=request)
    if info['changed']:
        who = f' by {info["modified_by"]}' if info['modified_by'] else ''
        messages.info(request, f'The Microsoft 365 copy has changed{who} since clientst0r last '
                               'had it. Nothing was imported: choose "Save back to clientst0r" '
                               'to keep the changes.')
    else:
        messages.info(request, 'No changes in the Microsoft 365 copy since clientst0r last had it.')
    return redirect(back)


@login_required
@require_POST
@handles_microsoft_errors
@_permission_message
def save(request, sid):
    session = _session(request, sid)
    back = _session_back(session)
    result = editing.save_back(request.user, session, request=request)
    level = {'saved': messages.success, 'duplicate': messages.info, 'unchanged': messages.info,
             'conflict': messages.warning}.get(result.status, messages.error)
    level(request, result.message)
    return redirect(back)


@login_required
@require_POST
@handles_microsoft_errors
@_permission_message
def finish(request, sid):
    session = _session(request, sid)
    back = _session_back(session)
    discard = request.POST.get('discard') == '1'
    note = editing.finish(request.user, session, discard=discard, request=request)
    messages.success(request, ('Discarded the Microsoft 365 edit session.' if discard else
                               'Finished editing in Microsoft 365.') + (f' {note}' if note else ''))
    return redirect(back)


# ---------------------------------------------------------------------------
# Settings (organization admin with integrations_configure)
# ---------------------------------------------------------------------------

@login_required
@require_admin
@require_POST
def edit_settings(request, pk):
    conn = _connection(request, pk, configure=True)
    enabled = request.POST.get('docs_edit_enabled') == 'on'
    loc = _location(conn, request.POST.get('docs_edit_location'), required=False)
    cleanup = request.POST.get('docs_edit_cleanup', 'delete')
    folder = (request.POST.get('docs_edit_folder_name') or '').strip()
    try:
        hours = int(request.POST.get('docs_edit_stale_hours') or 72)
    except ValueError:
        hours = -1
    back = redirect('integrations:m365docs_settings', pk=conn.pk)
    if cleanup not in dict(conn.DOCS_EDIT_CLEANUP_CHOICES) or not 1 <= hours <= 24 * 60:
        messages.error(request, 'Choose a valid working-copy policy and an idle time between 1 '
                                'and 1440 hours.')
        return back
    if loc is not None and loc.kind not in editing.WORKING_COPY_KINDS:
        messages.error(request, "Working copies go to each user's own OneDrive or to one "
                                'library or folder, not to a whole site.')
        return back
    if folder:
        from . import graph
        try:
            folder = graph.valid_name(folder)[:120]
        except ValueError as e:
            messages.error(request, str(e))
            return back
    if enabled and (conn.docs_access != 'readwrite' or not conn.docs_enabled or loc is None):
        messages.error(request, 'Edit in Microsoft 365 needs documents on, read and write access, '
                                'and a working-copy location.')
        return back
    before = [conn.docs_edit_enabled, conn.docs_edit_location_id, conn.docs_edit_folder_name,
              conn.docs_edit_cleanup, conn.docs_edit_stale_hours]
    type(conn).objects.filter(pk=conn.pk).update(
        docs_edit_enabled=enabled, docs_edit_location=loc, docs_edit_folder_name=folder,
        docs_edit_cleanup=cleanup, docs_edit_stale_hours=hours)
    audit.log('m365_edit_settings', user=request.user, organization_id=conn.organization_id,
              object_type='integrations.m365connection', object_id=conn.pk,
              object_repr=conn.name, request=request,
              description=f'Edit in Microsoft 365 {"enabled" if enabled else "disabled"} on '
                          f'{conn.name}',
              extra={'before': before, 'after': [enabled, loc.pk if loc else None, folder,
                                                 cleanup, hours]})
    if not enabled:
        conn.refresh_from_db()
        editing.recheck_all('Edit in Microsoft 365 turned off')
    messages.success(request, 'Edit in Microsoft 365 settings saved.')
    return back
