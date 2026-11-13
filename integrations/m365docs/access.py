"""Who may do what, and the allowed-locations rule.

clientst0r's own permissions are checked here *before* any Graph call;
Microsoft's are enforced by the delegated token on the call itself.

Permissions (all on the connection's organization):

    use the feature (connect, browse)     docs_view
    open / import from a linked file      view permission on the link's parent
    link / unlink                         edit permission on the link's parent
    create a file in Microsoft 365        docs_create + read-write mode
    import a copy (new Document)          docs_create
    export a copy to Microsoft 365        view permission on the file + docs_edit
                                          + read-write mode
    settings and allowed locations        org admin with integrations_configure

A platform-owned connection (the MSP's own tenant, organization empty) is
used only by MSP staff (sign-in and Edit in Microsoft 365) and configured
only by platform administrators (integrations/ownership.py).

Parents of a link: the organization's documents library (``org``), a
Document (``doc:<pk>``), an asset (``asset:<pk>``) or a ticket
(``ticket:<pk>``, MSP staff only — customers never see them).

Allowed locations (M365AllowedLocation) are checked for every item by
``locate``: the item is fetched from Graph, and it is allowed only when it is
in a permitted drive (directly, through a permitted site, or the user's own
OneDrive when that is permitted) or inside a permitted folder — proven by
walking ``parentReference.id`` up from the item to the folder, so a renamed
or moved folder can never widen the rule.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.http import Http404

from . import graph

MAX_DEPTH = 64


class NotPermitted(Exception):
    """Outside the allowed locations, or not allowed by clientst0r."""


def _perm(user, org_id, flag):
    from accounts.permission_utils import has_perm_for_org
    return bool(user and user.is_authenticated and user.is_active
                and has_perm_for_org(user, org_id, flag))


def _staff(user):
    from psa.visibility import is_msp_staff
    return is_msp_staff(user)


# ---------------------------------------------------------------------------
# Connection-level rules
# ---------------------------------------------------------------------------

def enabled(connection) -> bool:
    return bool(connection and connection.is_active and connection.docs_enabled)


def can_use(user, connection) -> bool:
    """A customer's own connection: ``docs_view`` at that customer. A
    platform-owned connection (the MSP's own tenant, organization empty):
    MSP staff only; customer users never use it."""
    if not enabled(connection):
        return False
    if connection.organization_id is None:
        return bool(user and user.is_authenticated and user.is_active and _staff(user))
    return _perm(user, connection.organization_id, 'docs_view')


def can_configure(user, connection) -> bool:
    """Platform-owned: platform administrators (integrations/ownership.py);
    a customer's own: ``integrations_configure`` at that customer."""
    if connection.organization_id is None:
        from integrations.ownership import can_manage_platform
        return can_manage_platform(user)
    return _perm(user, connection.organization_id, 'integrations_configure')


def writes_allowed(connection) -> bool:
    return enabled(connection) and connection.docs_access == 'readwrite'


def can_create_in_m365(user, connection) -> bool:
    return writes_allowed(connection) and _perm(user, connection.organization_id, 'docs_create')


def can_import(user, connection) -> bool:
    return can_use(user, connection) and _perm(user, connection.organization_id, 'docs_create')


def can_export(user, connection, target) -> bool:
    return (writes_allowed(connection) and can_use(user, connection)
            and target.organization_id == connection.organization_id
            and target.can_view(user)
            and _perm(user, connection.organization_id, 'docs_edit')
            and (target.kind != 'ticket_attachment' or _staff(user)))


def connections_for(user, org):
    """Documents-enabled connections of `org` (an Organization or its pk) the user may use."""
    from integrations.models import M365Connection
    org_id = getattr(org, 'pk', org)
    if org_id is None:
        return []
    rows = M365Connection.objects.filter(organization_id=org_id, is_active=True,
                                         docs_enabled=True)
    return [c for c in rows if can_use(user, c)]


# ---------------------------------------------------------------------------
# Parents
# ---------------------------------------------------------------------------

@dataclass
class Parent:
    kind: str                # org | doc | asset | ticket
    org_id: int
    obj: object = None

    @property
    def param(self):
        return 'org' if self.kind == 'org' else f'{self.kind}:{self.obj.pk}'

    def link_kwargs(self):
        return {'org': {}, 'doc': {'document': self.obj}, 'asset': {'asset': self.obj},
                'ticket': {'ticket': self.obj}}[self.kind]

    def label(self):
        if self.kind == 'org':
            return 'the organization\'s documents'
        if self.kind == 'doc':
            return f'document “{self.obj.title}”'
        if self.kind == 'asset':
            return f'asset “{self.obj.name}”'
        return f'ticket {self.obj.ticket_number}'

    def url(self):
        from django.urls import reverse
        from core.org_handoff import with_org
        if self.kind == 'doc':
            return with_org(reverse('docs:document_detail', args=[self.obj.slug]), self.org_id)
        if self.kind == 'asset':
            return with_org(reverse('assets:asset_detail', args=[self.obj.pk]), self.org_id)
        if self.kind == 'ticket':
            return with_org(reverse('psa:ticket_detail', args=[self.obj.ticket_number]),
                            self.org_id)
        return reverse('integrations:m365docs_home')

    def can_view(self, user) -> bool:
        if not (user and user.is_authenticated and user.is_active):
            return False
        if self.kind == 'org':
            return _perm(user, self.org_id, 'docs_view')
        if self.kind == 'doc':
            from core.media_views import _document
            return self.obj.organization_id is not None and bool(_document(user, self.obj))
        if self.kind == 'asset':
            return _perm(user, self.org_id, 'assets_view')
        return _staff(user) and _perm(user, self.org_id, 'tickets_view')

    def can_link(self, user) -> bool:
        if not self.can_view(user):
            return False
        if self.kind == 'org':
            return _perm(user, self.org_id, 'docs_edit')
        if self.kind == 'doc':
            from docs.permissions import can_edit
            return can_edit(user, self.obj)
        if self.kind == 'asset':
            return _perm(user, self.org_id, 'assets_edit')
        return _perm(user, self.org_id, 'tickets_edit')


def parent_from_param(value, connection) -> Parent:
    """Parse ``org`` / ``doc:5`` / ``asset:3`` / ``ticket:9``; the object must
    belong to the connection's organization (Http404 otherwise)."""
    org_id = connection.organization_id
    value = (value or 'org').strip()
    if value == 'org':
        return Parent('org', org_id)
    kind, _, pk = value.partition(':')
    if not pk.isdigit():
        raise Http404('Not found')
    if kind == 'doc':
        from docs.models import Document
        obj = Document.objects.filter(pk=int(pk), organization_id=org_id).first()
    elif kind == 'asset':
        from assets.models import Asset
        obj = Asset.objects.filter(pk=int(pk), organization_id=org_id).first()
    elif kind == 'ticket':
        from psa.models import Ticket
        obj = Ticket.objects.filter(pk=int(pk), organization_id=org_id).first()
    else:
        obj = None
    if obj is None:
        raise Http404('Not found')
    return Parent(kind, org_id, obj)


def parent_of(link) -> Parent:
    if link.document_id:
        return Parent('doc', link.organization_id, link.document)
    if link.asset_id:
        return Parent('asset', link.organization_id, link.asset)
    if link.ticket_id:
        return Parent('ticket', link.organization_id, link.ticket)
    return Parent('org', link.organization_id)


def can_view_link(user, link) -> bool:
    return can_use(user, link.connection) and parent_of(link).can_view(user)


def can_edit_link(user, link) -> bool:
    return can_use(user, link.connection) and parent_of(link).can_link(user)


# ---------------------------------------------------------------------------
# Allowed locations
# ---------------------------------------------------------------------------

def locations(connection):
    return list(connection.docs_locations.filter(organization_id=connection.organization_id))


def location_root(client, location):
    """(drive_id, item_id) a location opens at; for a site, (None, None)."""
    if location.kind == 'my_onedrive':
        return client.my_drive()['id'], 'root'
    if location.kind == 'drive':
        return location.drive_id, 'root'
    if location.kind == 'folder':
        return location.drive_id, location.item_id
    return None, None


def _site_drive_ids(client, location, cache):
    key = ('site', location.site_id)
    if key not in cache:
        cache[key] = {d.get('id') for d in client.site_drives(location.site_id)}
    return cache[key]


def _within_folder(client, drive_id, meta, folder_id):
    if meta.get('id') == folder_id:
        return True
    current = meta
    for _ in range(MAX_DEPTH):
        parent = current.get('parentReference') or {}
        if parent.get('driveId') and parent.get('driveId') != drive_id:
            return False
        parent_id = parent.get('id')
        if not parent_id:
            return False
        if parent_id == folder_id:
            return True
        current = client.item(drive_id, parent_id, select='id,parentReference')
    return False


def drive_permitted(client, connection, drive_id, location, cache=None):
    """Is the whole drive permitted by `location` (not just a folder in it)?"""
    cache = {} if cache is None else cache
    if location.kind == 'drive':
        return location.drive_id == drive_id
    if location.kind == 'my_onedrive':
        return client.my_drive().get('id') == drive_id
    if location.kind == 'site':
        return drive_id in _site_drive_ids(client, location, cache)
    return False


def locate(client, connection, drive_id, item_id, *, location=None):
    """Fetch the item and return (location, metadata) if it is inside an
    allowed location; NotPermitted otherwise. With `location`, only that
    entry is considered. IDs are validated before any call."""
    graph.valid_id(drive_id)
    if item_id not in ('root', ''):
        graph.valid_id(item_id)
    candidates = [location] if location is not None else locations(connection)
    candidates = [c for c in candidates
                  if c is not None and c.connection_id == connection.pk
                  and c.organization_id == connection.organization_id]
    if not candidates:
        raise NotPermitted('No allowed Microsoft 365 location covers this item.')
    meta = client.item(drive_id, item_id or 'root')
    parent = meta.get('parentReference') or {}
    if parent.get('driveId') and parent['driveId'] != drive_id:
        raise NotPermitted('The item is not in the requested drive.')
    cache = {}
    for loc in candidates:
        if loc.kind == 'folder':
            if loc.drive_id == drive_id and _within_folder(client, drive_id, meta, loc.item_id):
                return loc, meta
        elif drive_permitted(client, connection, drive_id, loc, cache):
            return loc, meta
    raise NotPermitted('This item is outside the allowed Microsoft 365 locations.')


def locate_folder(client, connection, drive_id, item_id, *, location=None):
    loc, meta = locate(client, connection, drive_id, item_id, location=location)
    if 'folder' not in meta and not (meta.get('root') is not None or item_id == 'root'):
        raise NotPermitted('Choose a folder.')
    return loc, meta
