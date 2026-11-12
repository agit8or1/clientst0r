"""Link, open, create, import a copy and export a copy. Every action is
explicit, checked (clientst0r first, then Microsoft through the delegated
token) and audited. Nothing here syncs: a linked file stays canonical in
Microsoft 365, an imported copy is a new clientst0r Document, and an exported
copy is a new file in Microsoft 365.

Never called: createLink, invite, permissions, shares or preview endpoints
(m365docs.http refuses them in any case).
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from office import creation, formats, storage, targets

from . import access, audit, graph, http, oauth

OBJECT_TYPE = 'integrations.linkedclouddocument'


class ServiceError(Exception):
    """A user-facing failure (message is safe to show)."""


def grant_for(user, connection):
    from integrations.models import M365DocsGrant
    grant = M365DocsGrant.objects.filter(connection=connection, user=user).select_related(
        'connection').first()
    if grant is None:
        raise oauth.NotConnected('Connect your Microsoft 365 documents first.', 'no_grant')
    return grant


def client_for(user, connection):
    if not access.can_use(user, connection):
        raise PermissionDenied('Not allowed')
    return graph.GraphClient(grant_for(user, connection))


def _log(event, user, connection, *, request=None, link=None, description='', extra=None,
         success=True):
    audit.log(event, user=user, organization_id=connection.organization_id, request=request,
              object_type=OBJECT_TYPE if link is not None else 'integrations.m365connection',
              object_id=link.pk if link is not None else connection.pk,
              object_repr=(link.name if link is not None else connection.name),
              description=description, success=success,
              extra={'connection': connection.pk, **(extra or {})})


def _item_extra(meta, drive_id):
    return {'drive_id': drive_id, 'item_id': meta.get('id'), 'etag': meta.get('eTag', '')}


def check_web_url(connection, url):
    hosts = http.sharepoint_hosts(connection)
    if not hosts or not http.is_allowed(url, hosts):
        raise ServiceError("Microsoft 365 returned a link outside this tenant's SharePoint "
                           'host, so it was not opened. Check the SharePoint host in the '
                           'connection\'s document settings.')
    return url


def learn_sharepoint_host(client, connection):
    """Fill docs_sharepoint_host from the user's OneDrive URL the first time
    (https://<tenant>-my.sharepoint.com/personal/...)."""
    if connection.docs_sharepoint_host:
        return
    try:
        url = client.my_drive().get('webUrl') or ''
    except Exception:
        return
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or '').lower()
    prefix = http.tenant_prefix(host)
    if prefix:
        connection.docs_sharepoint_host = f'{prefix}.sharepoint.com'
        type(connection).objects.filter(pk=connection.pk).update(
            docs_sharepoint_host=connection.docs_sharepoint_host)


# ---------------------------------------------------------------------------
# Link / unlink / open
# ---------------------------------------------------------------------------

def link(user, connection, parent, drive_id, item_id, *, request=None):
    from integrations.models import LinkedCloudDocument
    if not access.can_use(user, connection) or not parent.can_link(user):
        raise PermissionDenied('Not allowed')
    client = client_for(user, connection)
    loc, meta = access.locate(client, connection, drive_id, item_id)
    if 'file' not in meta:
        raise ServiceError('Only files can be linked.')
    existing = LinkedCloudDocument.objects.filter(
        organization_id=connection.organization_id, connection=connection,
        drive_id=drive_id, item_id=meta['id'], **{
            'document': parent.obj if parent.kind == 'doc' else None,
            'asset': parent.obj if parent.kind == 'asset' else None,
            'ticket': parent.obj if parent.kind == 'ticket' else None}).first()
    if existing:
        return existing
    row = LinkedCloudDocument.objects.create(
        organization_id=connection.organization_id, connection=connection, location=loc,
        drive_id=drive_id, item_id=meta['id'], name=str(meta.get('name', ''))[:500],
        web_url=str(meta.get('webUrl', ''))[:2000], etag=str(meta.get('eTag', ''))[:300],
        size=meta.get('size'), linked_by=user, last_seen_at=timezone.now(),
        **parent.link_kwargs())
    _log('m365_link', user, connection, request=request, link=row,
         description=f'Linked Microsoft 365 file {row.name} to {parent.label()}',
         extra={**_item_extra(meta, drive_id), 'location': loc.pk, 'parent': parent.param})
    return row


def unlink(user, link_row, *, request=None):
    if not access.can_edit_link(user, link_row):
        raise PermissionDenied('Not allowed')
    parent = access.parent_of(link_row)
    _log('m365_unlink', user, link_row.connection, request=request, link=link_row,
         description=f'Unlinked Microsoft 365 file {link_row.name} from {parent.label()} '
                     '(the file itself is unchanged in Microsoft 365)',
         extra={'drive_id': link_row.drive_id, 'item_id': link_row.item_id,
                'parent': parent.param})
    link_row.delete()


def open_url(user, link_row, *, request=None):
    """A fresh ``webUrl`` fetched from Graph as the user. If Microsoft no
    longer lets the user see the file, this fails — clientst0r never falls
    back to a stored URL or a sharing link."""
    if not access.can_view_link(user, link_row):
        raise PermissionDenied('Not allowed')
    connection = link_row.connection
    client = client_for(user, connection)
    try:
        _loc, meta = access.locate(client, connection, link_row.drive_id, link_row.item_id)
    except graph.GraphError as e:
        _log('m365_open', user, connection, request=request, link=link_row, success=False,
             description=f'Open of {link_row.name} refused by Microsoft 365 ({e.status})',
             extra={'status': e.status})
        raise
    learn_sharepoint_host(client, connection)
    url = check_web_url(connection, str(meta.get('webUrl') or ''))
    link_row.name = str(meta.get('name', link_row.name))[:500]
    link_row.web_url = url[:2000]
    link_row.etag = str(meta.get('eTag', ''))[:300]
    link_row.size = meta.get('size')
    link_row.last_seen_at = timezone.now()
    link_row.save(update_fields=['name', 'web_url', 'etag', 'size', 'last_seen_at'])
    _log('m365_open', user, connection, request=request, link=link_row,
         description=f'Opened {link_row.name} in Microsoft 365',
         extra={'drive_id': link_row.drive_id, 'item_id': link_row.item_id})
    return url


# ---------------------------------------------------------------------------
# Create in Microsoft 365
# ---------------------------------------------------------------------------

def create(user, connection, location, drive_id, folder_id, fmt, title, *, parent=None,
           request=None):
    if fmt not in creation.NEW_FORMATS:
        raise ServiceError('Unsupported format.')
    if not access.can_create_in_m365(user, connection):
        raise PermissionDenied('Not allowed')
    if parent is not None and not parent.can_link(user):
        raise PermissionDenied('Not allowed')
    client = client_for(user, connection)
    loc, folder = access.locate_folder(client, connection, drive_id, folder_id,
                                       location=location)
    name = creation.filename_for(title, fmt)
    try:
        graph.valid_name(name)
    except ValueError as e:
        raise ServiceError(str(e))
    meta = client.upload_new(drive_id, folder.get('id') or folder_id, name,
                             creation.blank_bytes(fmt), formats.mime_for(name))
    _log('m365_create', user, connection, request=request,
         description=f'Created {name} in Microsoft 365 ({loc.display_name})',
         extra={**_item_extra(meta, drive_id), 'location': loc.pk,
                'folder_id': folder.get('id'), 'conflict_behavior': 'fail'})
    if parent is not None:
        return link(user, connection, parent, drive_id, meta['id'], request=request)
    return meta


# ---------------------------------------------------------------------------
# Import a copy into clientst0r
# ---------------------------------------------------------------------------

def import_preview(user, connection, drive_id, item_id):
    """What an import would do, for the confirmation page."""
    if not access.can_import(user, connection):
        raise PermissionDenied('Not allowed')
    client = client_for(user, connection)
    loc, meta = access.locate(client, connection, drive_id, item_id)
    if 'file' not in meta:
        raise ServiceError('Only files can be imported.')
    name = str(meta.get('name') or '')
    if not formats.is_office(name):
        raise ServiceError('Only Word, Excel and PowerPoint files can be imported.')
    return loc, meta


def import_copy(user, connection, drive_id, item_id, *, title=None, request=None):
    from core.models import Organization
    loc, meta = import_preview(user, connection, drive_id, item_id)
    client = client_for(user, connection)
    learn_sharepoint_host(client, connection)
    limit = storage.max_bytes()
    try:
        meta, data = client.download(drive_id, meta['id'], limit,
                                     http.sharepoint_hosts(connection))
    except ValueError as e:
        raise ServiceError(str(e))
    except http.RefusedURL as e:
        raise ServiceError(str(e))
    org = Organization.objects.get(pk=connection.organization_id)
    name = storage.safe_filename(title or meta.get('name') or 'Imported',
                                 fallback='Imported')
    if formats.extension(name) != formats.extension(meta.get('name', '')):
        name = creation.filename_for(name, formats.extension(meta.get('name', '')))
    target = targets.create_document(org, name, user)
    try:
        rev = storage.store_initial(target, data, user=user, source='import',
                                    original_name=name)
    except Exception:
        type(target.obj)._base_manager.filter(pk=target.pk).delete()
        raise
    target.refresh()
    audit.log('m365_import', user=user, organization_id=target.organization_id,
              object_type=f'office.{target.kind}', object_id=target.pk,
              object_repr=target.filename, request=request,
              description=f'Imported a copy of Microsoft 365 file {meta.get("name")} '
                          f'({loc.display_name}) as {target.filename}',
              extra={'revision': rev.revision_number, 'sha256': rev.sha256,
                     'connection': connection.pk, **_item_extra(meta, drive_id),
                     'location': loc.pk})
    return target


# ---------------------------------------------------------------------------
# Export a copy to Microsoft 365
# ---------------------------------------------------------------------------

def export_copy(user, target, connection, location, drive_id, folder_id, name=None, *,
                request=None):
    if not access.can_export(user, connection, target):
        raise PermissionDenied('Not allowed')
    client = client_for(user, connection)
    loc, folder = access.locate_folder(client, connection, drive_id, folder_id,
                                       location=location)
    rev = storage.ensure_current(target, user)
    if rev is None:
        raise ServiceError('The file has no content yet.')
    name = (name or target.filename).strip()
    if formats.extension(name) != target.extension:
        name = creation.filename_for(name, target.extension)
    try:
        graph.valid_name(name)
    except ValueError as e:
        raise ServiceError(str(e))
    with storage.open_revision(rev) as fh:
        data = fh.read()
    meta = client.upload_new(drive_id, folder.get('id') or folder_id, name, data,
                             formats.mime_for(name))
    audit.log('m365_export', user=user, organization_id=target.organization_id,
              object_type=f'office.{target.kind}', object_id=target.pk,
              object_repr=target.filename, request=request,
              description=f'Exported a copy of {target.filename} (revision '
                          f'{rev.revision_number}) to Microsoft 365: {loc.display_name} / '
                          f'{folder.get("name", "")} / {name}',
              extra={'destination': 'm365', 'connection': connection.pk,
                     'revision': rev.revision_number, 'sha256': rev.sha256,
                     **_item_extra(meta, drive_id), 'location': loc.pk,
                     'folder_id': folder.get('id'), 'conflict_behavior': 'fail'})
    return meta
