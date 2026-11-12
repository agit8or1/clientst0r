"""Views for Microsoft 365 documents. URLs are under /integrations/m365/.

Every view checks clientst0r permissions first (access.py), then calls Graph
as the signed-in user. Every state-changing request is a CSRF-protected POST,
except Microsoft's redirect back to the callback, which is protected by the
single-use OAuth state bound to the user's session.
"""
from __future__ import annotations

from functools import wraps
from urllib.parse import urlencode, urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.decorators import require_admin
from core.middleware import get_request_organization
from core.tenancy import get_org_object_or_404
from office import creation, formats, targets
from office.net import OfficeFetchError

from . import access, audit, graph, http, oauth, scopes, services
from .graph import GraphClient, GraphError


def _models():
    from integrations.models import LinkedCloudDocument, M365AllowedLocation, M365Connection
    return M365Connection, M365AllowedLocation, LinkedCloudDocument


def _org(request):
    org = get_request_organization(request)
    if org is None:
        raise Http404('Select an organization first')
    return org


def _connection(request, pk, *, configure=False):
    M365Connection, _, _ = _models()
    conn = get_org_object_or_404(M365Connection, _org(request), pk=pk)
    if configure:
        if not access.can_configure(request.user, conn):
            raise PermissionDenied('Not allowed')
    elif not access.can_use(request.user, conn):
        raise Http404('Not found')
    return conn


def _safe_next(request, url, fallback):
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return url
    return fallback


def _home_url(**params):
    url = reverse('integrations:m365docs_home')
    params = {k: v for k, v in params.items() if v}
    return url + ('?' + urlencode(params) if params else '')


def _browse_url(conn, **params):
    url = reverse('integrations:m365docs_browse', args=[conn.pk])
    params = {k: v for k, v in params.items() if v}
    return url + ('?' + urlencode(params) if params else '')


def handles_microsoft_errors(view):
    """Turn the expected failures into a message and a redirect back."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        back = _safe_next(request, request.POST.get('next') or request.GET.get('next')
                          or request.META.get('HTTP_REFERER', ''), _home_url())
        try:
            return view(request, *args, **kwargs)
        except oauth.NotConnected as e:
            messages.warning(request, str(e))
        except oauth.OAuthError as e:
            messages.error(request, str(e))
        except GraphError as e:
            messages.error(request, e.user_message)
        except access.NotPermitted as e:
            messages.error(request, str(e))
        except services.ServiceError as e:
            messages.error(request, str(e))
        except http.RefusedURL as e:
            messages.error(request, f'Refused: {e}')
        except OfficeFetchError:
            messages.error(request, 'Microsoft 365 could not be reached. Try again later.')
        except ValueError:
            raise Http404('Not found')
        return redirect(back)
    return wrapper


def _location(conn, value, *, required=True):
    _, M365AllowedLocation, _ = _models()
    if not value or not str(value).isdigit():
        if required:
            raise Http404('Not found')
        return None
    loc = M365AllowedLocation.objects.filter(
        pk=int(value), connection=conn, organization_id=conn.organization_id).first()
    if loc is None:
        raise Http404('Not found')
    return loc


def _grant(user, conn):
    from integrations.models import M365DocsGrant
    return M365DocsGrant.objects.filter(connection=conn, user=user).first()


def _grant_status(user, conn):
    grant = _grant(user, conn)
    if grant is None:
        return {'connected': False, 'missing': []}
    return {'connected': True, 'grant': grant,
            'missing': scopes.missing(conn, grant.scope_set)}


# ---------------------------------------------------------------------------
# Settings (organization admin)
# ---------------------------------------------------------------------------

def _settings_context(request, conn, **extra):
    from django.conf import settings as dj
    return {
        'connection': conn,
        'permissions': scopes.describe(conn),
        'all_modes': scopes.all_modes(),
        'access_choices': conn.DOCS_ACCESS_CHOICES,
        'sharepoint_choices': conn.DOCS_SHAREPOINT_CHOICES,
        'redirect_uri': oauth.redirect_uri(request),
        'locations': access.locations(conn),
        'kinds': conn.docs_locations.model.KIND_CHOICES,
        'status': _grant_status(request.user, conn),
        'grant_count': conn.docs_grants.count(),
        'tenant_read_scope': scopes.TENANT_READ_SCOPE,
        'redirect_configured': bool(getattr(dj, 'M365_DOCS_REDIRECT_URI', '')),
        **extra,
    }


@login_required
@require_admin
@require_http_methods(['GET', 'POST'])
def docs_settings(request, pk):
    conn = _connection(request, pk, configure=True)
    if request.method == 'GET':
        return render(request, 'integrations/m365docs/settings.html',
                      _settings_context(request, conn))
    step = request.POST.get('step', 'review')
    enabled = request.POST.get('docs_enabled') == 'on'
    access_mode = request.POST.get('docs_access', 'read')
    sharepoint = request.POST.get('docs_sharepoint', 'none')
    host = (request.POST.get('docs_sharepoint_host') or '').strip().lower()
    if access_mode not in dict(conn.DOCS_ACCESS_CHOICES) or \
            sharepoint not in dict(conn.DOCS_SHAREPOINT_CHOICES):
        messages.error(request, 'Choose a valid mode.')
        return redirect('integrations:m365docs_settings', pk=conn.pk)
    if host and not http.valid_sharepoint_host(host):
        messages.error(request, 'The SharePoint host must look like contoso.sharepoint.com.')
        return redirect('integrations:m365docs_settings', pk=conn.pk)
    if host.endswith('-my.sharepoint.com'):
        host = host.replace('-my.sharepoint.com', '.sharepoint.com')
    if enabled and step != 'confirm':
        # Show exactly what will be requested before anything changes.
        return render(request, 'integrations/m365docs/settings_review.html', {
            'connection': conn, 'docs_access': access_mode, 'docs_sharepoint': sharepoint,
            'docs_sharepoint_host': host,
            'permissions': scopes.describe(access=access_mode, sharepoint=sharepoint),
            'access_label': dict(conn.DOCS_ACCESS_CHOICES)[access_mode],
            'sharepoint_label': dict(conn.DOCS_SHAREPOINT_CHOICES)[sharepoint],
            'tenant_read_scope': scopes.TENANT_READ_SCOPE,
            'redirect_uri': oauth.redirect_uri(request),
        })
    before = (conn.docs_enabled, conn.docs_access, conn.docs_sharepoint, conn.docs_sharepoint_host)
    M365Connection, _, _ = _models()
    # Only the documents columns are written: the tenant-read / mail
    # credentials, scopes and consent are left exactly as they were.
    M365Connection.objects.filter(pk=conn.pk).update(
        docs_enabled=enabled, docs_access=access_mode, docs_sharepoint=sharepoint,
        docs_sharepoint_host=host)
    removed = 0
    if before[0] and not enabled:
        removed, _ = conn.docs_grants.all().delete()
    audit.log('m365_settings', user=request.user, organization_id=conn.organization_id,
              object_type='integrations.m365connection', object_id=conn.pk,
              object_repr=conn.name, request=request,
              description=(f'Microsoft 365 documents {"enabled" if enabled else "disabled"} on '
                           f'{conn.name} (access {access_mode}, SharePoint {sharepoint})'
                           + (f'; {removed} stored sign-in(s) deleted' if removed else '')),
              extra={'before': list(before), 'after': [enabled, access_mode, sharepoint, host],
                     'scopes': scopes.short_scopes(access_mode, sharepoint) if enabled else []})
    messages.success(request, 'Document settings saved.' + (
        ' Users must connect again if they signed in with fewer permissions.' if enabled else ''))
    return redirect('integrations:m365docs_settings', pk=conn.pk)


def _admin_client(request, conn):
    return GraphClient(services.grant_for(request.user, conn))


def _app_client(conn):
    return GraphClient(bearer=oauth.app_token(conn))


def _site_lookup(request, conn, call):
    """Run `call(client)` as the admin; if Microsoft refuses the delegated
    token (e.g. Files.*.All cannot read site metadata), retry with the
    connection's existing tenant-read app token (Sites.Read.All application,
    already consented for the tenant-read features). Read-only metadata."""
    try:
        return call(_admin_client(request, conn)), 'delegated'
    except (GraphError, oauth.NotConnected) as e:
        if isinstance(e, GraphError) and e.status not in (401, 403):
            raise
        return call(_app_client(conn)), 'application'


@login_required
@require_admin
@require_POST
@handles_microsoft_errors
def location_add(request, pk):
    _, M365AllowedLocation, _ = _models()
    conn = _connection(request, pk, configure=True)
    if not conn.docs_enabled:
        raise services.ServiceError('Enable documents first.')
    kind = request.POST.get('kind', '')
    fields = {'connection': conn, 'organization_id': conn.organization_id,
              'site_id': '', 'drive_id': '', 'item_id': ''}
    if kind == 'my_onedrive':
        fields.update(kind='my_onedrive', display_name="Each user's own OneDrive")
    elif kind == 'site_url':
        parts = urlsplit((request.POST.get('site_url') or '').strip())
        if parts.scheme != 'https' or not http.valid_sharepoint_host(parts.hostname or ''):
            raise services.ServiceError('Enter a SharePoint site URL such as '
                                        'https://contoso.sharepoint.com/sites/Finance.')
        site, how = _site_lookup(request, conn,
                                 lambda c: c.site_by_path(parts.hostname, parts.path or '/'))
        fields.update(kind='site', site_id=graph.valid_site_id(site['id']),
                      display_name=str(site.get('displayName') or site.get('name') or parts.path),
                      web_url=str(site.get('webUrl', ''))[:2000])
    elif kind == 'drive':
        drive_id = graph.valid_id(request.POST.get('drive_id', ''))
        drive = _admin_client(request, conn).drive(drive_id)
        fields.update(kind='drive', drive_id=drive_id, site_id=request.POST.get('site_id', '')[:300],
                      display_name=str(request.POST.get('label') or drive.get('name') or drive_id),
                      web_url=str(drive.get('webUrl', ''))[:2000])
    elif kind == 'folder':
        drive_id = graph.valid_id(request.POST.get('drive_id', ''))
        item_id = graph.valid_id(request.POST.get('item_id', ''))
        item = _admin_client(request, conn).item(drive_id, item_id)
        if 'folder' not in item:
            raise services.ServiceError('Choose a folder.')
        fields.update(kind='folder', drive_id=drive_id, item_id=item['id'],
                      display_name=str(request.POST.get('label') or item.get('name')),
                      web_url=str(item.get('webUrl', ''))[:2000])
    else:
        raise services.ServiceError('Choose what to allow.')
    fields['display_name'] = fields['display_name'][:500]
    loc, created = M365AllowedLocation.objects.get_or_create(
        connection=conn, kind=fields['kind'], site_id=fields['site_id'],
        drive_id=fields['drive_id'], item_id=fields['item_id'],
        defaults={'organization_id': conn.organization_id,
                  'display_name': fields['display_name'],
                  'web_url': fields.get('web_url', ''), 'created_by': request.user})
    if created:
        audit.log('m365_location_add', user=request.user, organization_id=conn.organization_id,
                  object_type='integrations.m365allowedlocation', object_id=loc.pk,
                  object_repr=loc.display_name, request=request,
                  description=f'Allowed Microsoft 365 location {loc} on {conn.name}',
                  extra={'kind': loc.kind, 'site_id': loc.site_id, 'drive_id': loc.drive_id,
                         'item_id': loc.item_id})
        messages.success(request, f'Allowed: {loc}.')
    else:
        messages.info(request, f'{loc} is already allowed.')
    return redirect('integrations:m365docs_settings', pk=conn.pk)


@login_required
@require_admin
@require_POST
def location_delete(request, pk, lid):
    conn = _connection(request, pk, configure=True)
    loc = _location(conn, str(lid))
    audit.log('m365_location_remove', user=request.user, organization_id=conn.organization_id,
              object_type='integrations.m365allowedlocation', object_id=loc.pk,
              object_repr=loc.display_name, request=request,
              description=f'Removed allowed Microsoft 365 location {loc} from {conn.name}')
    loc.delete()
    messages.success(request, 'Location removed. Existing links to files there can no longer '
                              'be opened or imported until it is allowed again.')
    return redirect('integrations:m365docs_settings', pk=conn.pk)


@login_required
@require_admin
@require_GET
@handles_microsoft_errors
def location_pick(request, pk):
    """Admin picker: a site's libraries, or the folders in a library, to allow."""
    conn = _connection(request, pk, configure=True)
    site_id = request.GET.get('site', '')
    drive_id = request.GET.get('drive', '')
    item_id = request.GET.get('item', 'root') or 'root'
    ctx = {'connection': conn, 'site_id': site_id, 'drive_id': drive_id, 'item_id': item_id}
    if drive_id:
        client = _admin_client(request, conn)
        ctx['mode'] = 'folders'
        ctx['folder'] = client.item(drive_id, item_id)
        ctx['children'] = [c for c in client.children(drive_id, item_id) if 'folder' in c]
    elif site_id:
        graph.valid_site_id(site_id)
        drives, how = _site_lookup(request, conn, lambda c: c.site_drives(site_id))
        ctx.update(mode='drives', drives=drives, lookup=how)
    else:
        raise Http404('Not found')
    return render(request, 'integrations/m365docs/pick.html', ctx)


# ---------------------------------------------------------------------------
# Connect / disconnect (each user)
# ---------------------------------------------------------------------------

@login_required
@require_POST
@handles_microsoft_errors
def connect(request, pk):
    conn = _connection(request, pk)
    nxt = _safe_next(request, request.POST.get('next', ''), '')
    return HttpResponseRedirect(oauth.start(request, conn, nxt))


@login_required
@require_GET
def callback(request):
    try:
        grant, nxt = oauth.finish(request)
    except oauth.OAuthError as e:
        messages.error(request, str(e))
        return redirect('integrations:m365docs_home')
    conn = grant.connection
    client = GraphClient(grant)
    try:
        drive = client.my_drive()
        owner = ((drive.get('owner') or {}).get('user') or {})
        grant.ms_user_id = str(owner.get('id', ''))[:64]
        grant.ms_display_name = str(owner.get('displayName', ''))[:255]
        grant.save(update_fields=['ms_user_id', 'ms_display_name'])
        services.learn_sharepoint_host(client, conn)
    except Exception:
        pass   # no OneDrive (unlicensed); SharePoint can still work
    audit.log('m365_connect', user=request.user, organization_id=conn.organization_id,
              object_type='integrations.m365connection', object_id=conn.pk,
              object_repr=conn.name, request=request,
              description=f'Connected Microsoft 365 documents for {request.user.username} '
                          f'on {conn.name}',
              extra={'scopes': sorted(grant.scope_set)})
    missing = scopes.missing(conn, grant.scope_set)
    if missing:
        messages.warning(request, 'Microsoft did not grant: ' + ', '.join(missing)
                         + '. Some actions will fail until an administrator consents.')
    else:
        messages.success(request, 'Microsoft 365 documents connected.')
    return redirect(_safe_next(request, nxt, _home_url()))


@login_required
@require_POST
def disconnect(request, pk):
    M365Connection, _, _ = _models()
    conn = get_org_object_or_404(M365Connection, _org(request), pk=pk)
    grant = _grant(request.user, conn)
    if grant is not None:
        oauth.disconnect(grant, request=request, user=request.user)
        messages.success(request, 'Disconnected. Your stored Microsoft 365 tokens were deleted.')
    return redirect(_safe_next(request, request.POST.get('next', ''), _home_url()))


# ---------------------------------------------------------------------------
# Documents → Microsoft 365 tab
# ---------------------------------------------------------------------------

def _export_target(request, value):
    if not value:
        return None
    code, _, pk = value.partition(':')
    if not pk.isdigit():
        raise Http404('Not found')
    return targets.resolve_for(request.user, code, int(pk))


@login_required
@require_GET
def home(request):
    _, _, LinkedCloudDocument = _models()
    org = _org(request)
    conns = access.connections_for(request.user, org)
    export = _export_target(request, request.GET.get('export', ''))
    parent_param = request.GET.get('for', 'org')
    rows = []
    for c in conns:
        links = LinkedCloudDocument.objects.filter(
            connection=c, organization_id=org.pk, document__isnull=True, ticket__isnull=True,
            asset__isnull=True)
        rows.append({'connection': c, 'status': _grant_status(request.user, c),
                     'locations': access.locations(c), 'links': links,
                     'can_link': access.Parent('org', org.pk).can_link(request.user),
                     'can_import': access.can_import(request.user, c),
                     'can_configure': access.can_configure(request.user, c)})
    return render(request, 'integrations/m365docs/home.html', {
        'rows': rows, 'export_target': export, 'export_param': request.GET.get('export', ''),
        'for_param': parent_param, 'organization': org,
    })


@login_required
@require_GET
@handles_microsoft_errors
def browse(request, pk):
    conn = _connection(request, pk)
    loc = _location(conn, request.GET.get('loc'))
    client = services.client_for(request.user, conn)
    parent_param = request.GET.get('for', 'org')
    parent = access.parent_from_param(parent_param, conn)
    if not parent.can_view(request.user):
        raise Http404('Not found')
    export_param = request.GET.get('export', '')
    export = _export_target(request, export_param)
    drive_id = request.GET.get('drive', '')
    item_id = request.GET.get('item', '')
    ctx = {'connection': conn, 'location': loc, 'parent': parent, 'for_param': parent.param,
           'export_target': export, 'export_param': export_param,
           'can_link': parent.can_link(request.user),
           'can_import': access.can_import(request.user, conn),
           'can_create': access.can_create_in_m365(request.user, conn),
           'can_export': bool(export and access.can_export(request.user, conn, export)),
           'formats': [(f, creation.FORMAT_LABELS[f]) for f in creation.NEW_FORMATS]}
    if loc.kind == 'site' and not drive_id:
        ctx['drives'] = client.site_drives(loc.site_id)
        return render(request, 'integrations/m365docs/browse.html', ctx)
    if not drive_id:
        drive_id, item_id = access.location_root(client, loc)
    item_id = item_id or 'root'
    _loc, folder = access.locate_folder(client, conn, drive_id, item_id, location=loc)
    children = client.children(drive_id, folder.get('id') or item_id)
    parent_ref = folder.get('parentReference') or {}
    if loc.kind == 'folder':
        at_top = folder.get('id') == loc.item_id
    else:
        at_top = not parent_ref.get('id')
    ctx.update(drive_id=drive_id, folder=folder, folder_id=folder.get('id') or item_id,
               at_top=at_top, parent_folder_id='' if at_top else parent_ref.get('id', ''),
               folders=[c for c in children if 'folder' in c],
               files=[dict(c, is_office=formats.is_office(c.get('name', '')))
                      for c in children if 'file' in c])
    return render(request, 'integrations/m365docs/browse.html', ctx)


@login_required
@require_POST
@handles_microsoft_errors
def link_item(request, pk):
    conn = _connection(request, pk)
    parent = access.parent_from_param(request.POST.get('for', 'org'), conn)
    row = services.link(request.user, conn, parent, request.POST.get('drive', ''),
                        request.POST.get('item', ''), request=request)
    messages.success(request, f'Linked {row.name}. It stays in Microsoft 365; nothing is copied.')
    return redirect(parent.url())


def _link_row(request, lid):
    _, _, LinkedCloudDocument = _models()
    row = get_org_object_or_404(LinkedCloudDocument.objects.select_related('connection'),
                                _org(request), pk=lid)
    if not access.can_view_link(request.user, row):
        raise Http404('Not found')
    return row


@login_required
@require_POST
@handles_microsoft_errors
def open_link(request, lid):
    row = _link_row(request, lid)
    url = services.open_url(request.user, row, request=request)
    response = HttpResponseRedirect(url)
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_POST
@handles_microsoft_errors
def unlink_link(request, lid):
    row = _link_row(request, lid)
    back = access.parent_of(row).url()
    services.unlink(request.user, row, request=request)
    messages.success(request, 'Link removed. The file is unchanged in Microsoft 365.')
    return redirect(_safe_next(request, request.POST.get('next', ''), back))


@login_required
@require_POST
@handles_microsoft_errors
def create_item(request, pk):
    conn = _connection(request, pk)
    loc = _location(conn, request.POST.get('loc'))
    parent = access.parent_from_param(request.POST.get('for', 'org'), conn)
    result = services.create(request.user, conn, loc, request.POST.get('drive', ''),
                             request.POST.get('folder', ''), request.POST.get('fmt', ''),
                             request.POST.get('title', ''), parent=parent, request=request)
    messages.success(request, f'Created {result.name} in Microsoft 365 and linked it.')
    return redirect(parent.url())


@login_required
@require_http_methods(['GET', 'POST'])
@handles_microsoft_errors
def import_item(request, pk):
    conn = _connection(request, pk)
    src = request.POST if request.method == 'POST' else request.GET
    drive_id, item_id = src.get('drive', ''), src.get('item', '')
    if request.method == 'GET':
        loc, meta = services.import_preview(request.user, conn, drive_id, item_id)
        return render(request, 'integrations/m365docs/confirm_import.html', {
            'connection': conn, 'location': loc, 'item': meta, 'drive_id': drive_id,
            'organization': conn.organization, 'next': src.get('next', '')})
    target = services.import_copy(request.user, conn, drive_id, item_id,
                                  title=src.get('title') or None, request=request)
    messages.success(request, f'Imported a copy as {target.filename}. The Microsoft 365 file '
                              'is unchanged and the two are not kept in sync.')
    return redirect(target.back_url())


@login_required
@require_http_methods(['GET', 'POST'])
@handles_microsoft_errors
def export_item(request, pk):
    conn = _connection(request, pk)
    src = request.POST if request.method == 'POST' else request.GET
    target = _export_target(request, src.get('export', ''))
    if target is None:
        raise Http404('Not found')
    if not access.can_export(request.user, conn, target):
        raise PermissionDenied('Not allowed')
    loc = _location(conn, src.get('loc'))
    drive_id, folder_id = src.get('drive', ''), src.get('folder', '')
    if request.method == 'GET':
        client = services.client_for(request.user, conn)
        _loc, folder = access.locate_folder(client, conn, drive_id, folder_id, location=loc)
        return render(request, 'integrations/m365docs/confirm_export.html', {
            'connection': conn, 'location': loc, 'folder': folder, 'drive_id': drive_id,
            'folder_id': folder.get('id') or folder_id, 'target': target,
            'export_param': src.get('export', ''), 'name': target.filename})
    meta = services.export_copy(request.user, target, conn, loc, drive_id, folder_id,
                                src.get('name') or None, request=request)
    messages.success(request, f'Exported a copy to Microsoft 365 as {meta.get("name")}. '
                              'The two copies are not kept in sync.')
    return redirect(target.back_url())
