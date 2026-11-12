"""Who owns an integration connection, and who may manage it.

Integrations belong to the platform owner (the MSP). A connection with no
organization is platform-owned; one with an organization is that customer's
own (their Microsoft 365 tenant, their on-site UniFi controller).

Authorization
-------------

Platform-owned connections are managed only from global view (no customer
selected) and only by platform administrators:

* manage (create, edit, delete, test, mappings, "Make platform-owned"):
  a superuser, a Django staff account, or an MSP technician (user type
  Staff) whose *global* role grants ``integrations_configure``;
* sync / import: the above, or an MSP technician whose global role grants
  ``integrations_sync``;
* view (list, detail pages, review queues of unassigned data): the above, or
  an MSP technician whose global role grants ``integrations_view``.

An MSP technician without a global role does not get platform rights here:
platform connections carry credentials that reach every customer, so the
capability has to be granted explicitly. Customer users (user type
Organization User) never qualify, whatever role they hold at their own
organization.

Inside a customer (an organization selected) nothing changes: that
customer's own connections follow the existing per-organization decorators
(``require_admin`` / ``require_write``, plus ``rmm_staff_only`` on RMM pages),
and platform connections are never returned by any lookup, so a customer's
Owner or Admin can neither open, edit, sync nor delete one, and never sees its
credentials. The per-customer page only says, read-only, that platform
connections supply the customer's mapped data.

Data from a platform connection is assigned to customers through each type's
mapping (RMM customer → organization, UniFi/Omada/Grandstream site →
organization, PSA company → organization, accounting customer links). Data
that maps to no customer stays unassigned (organization empty) and is shown
only to platform staff in global view. Nothing falls back to "some"
organization.
"""
from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404


# ---------------------------------------------------------------------------
# Who may do what with platform connections
# ---------------------------------------------------------------------------

def _active(user):
    return bool(user is not None and user.is_authenticated and user.is_active)


def _global_flag(user, flag):
    """True when `user` is an MSP technician whose global role grants `flag`."""
    profile = getattr(user, 'profile', None)
    if profile is None or not getattr(profile, 'is_staff_user', lambda: False)():
        return False
    role = profile.get_global_permissions()
    return bool(role is not None and getattr(role, flag, False))


def can_manage_platform(user):
    if not _active(user):
        return False
    return bool(user.is_superuser or user.is_staff or _global_flag(user, 'integrations_configure'))


def can_sync_platform(user):
    return can_manage_platform(user) or (_active(user) and _global_flag(user, 'integrations_sync'))


def can_view_platform(user):
    return can_sync_platform(user) or (_active(user) and _global_flag(user, 'integrations_view'))


PLATFORM_CHECKS = {
    'admin': can_manage_platform,
    'write': can_sync_platform,
    'read': can_view_platform,
}

_DENIED = {
    'admin': 'Managing platform integrations needs a platform administrator.',
    'write': 'Syncing platform integrations needs a platform administrator or the integration sync permission.',
    'read': 'Platform integrations are shown to platform staff only.',
}


def platform_allowed(user, level):
    return PLATFORM_CHECKS[level](user)


def integration_access(level):
    """View decorator: in global view, the platform rule for `level`
    ('admin', 'write' or 'read'); inside a customer, the existing
    per-organization decorator for that level, unchanged."""
    from core.decorators import require_admin, require_write
    per_org = {'admin': require_admin, 'write': require_write, 'read': None}[level]

    def decorator(view_func):
        org_view = per_org(view_func) if per_org else view_func

        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if getattr(request, 'current_organization', None) is None:
                if not platform_allowed(request.user, level):
                    raise PermissionDenied(_DENIED[level])
                return view_func(request, *args, **kwargs)
            return org_view(request, *args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Looking connections up
# ---------------------------------------------------------------------------

def connection_queryset(request, model, level='read'):
    """The connections of `model` this request may reach.

    Inside a customer: that customer's own connections (and its
    descendants'), never a platform one. In global view: every connection for
    platform staff allowed at `level`, otherwise none.
    """
    from core.utils import descendant_org_ids
    org = getattr(request, 'current_organization', None)
    qs = model._default_manager.all()
    if org is not None:
        return qs.filter(organization_id__in=descendant_org_ids(org))
    if not platform_allowed(request.user, level):
        return qs.none()
    return qs


def get_connection_or_404(request, model, pk, level='read'):
    return get_object_or_404(connection_queryset(request, model, level), pk=pk)


def platform_connections(model):
    return model._default_manager.filter(organization__isnull=True)


def owner_choices(user):
    """Owner options for a connection created in global view: the platform
    (default) or one specific customer. Only platform administrators create
    there, and they may reach every active customer."""
    from core.models import Organization
    if not can_manage_platform(user):
        return []
    return [('', 'Platform (the MSP) — data is assigned to customers by mapping')] + [
        (str(o.pk), o.name) for o in Organization.objects.filter(is_active=True).order_by('name')]


# ---------------------------------------------------------------------------
# Connection types
# ---------------------------------------------------------------------------

def connection_types():
    """key → (model, label, detail URL name). The keys are what
    `manage.py integrations_ownership` and the "Make platform-owned" action
    take."""
    from . import models as m
    return {
        'psa': (m.PSAConnection, 'PSA', 'integrations:integration_detail'),
        'rmm': (m.RMMConnection, 'RMM', 'integrations:rmm_detail'),
        'unifi': (m.UnifiConnection, 'UniFi', 'integrations:unifi_detail'),
        'omada': (m.OmadaConnection, 'Omada', 'integrations:omada_detail'),
        'grandstream': (m.GrandstreamConnection, 'Grandstream', 'integrations:grandstream_detail'),
        'm365': (m.M365Connection, 'Microsoft 365', 'integrations:m365_detail'),
        'distributor': (m.DistributorConnection, 'Distributor', 'integrations:distributor_edit'),
        'accounting': (m.AccountingConnection, 'Accounting', 'integrations:accounting_edit'),
        'payment': (m.PaymentConnection, 'Payment', None),
        'warranty': (m.WarrantyConnection, 'Warranty', None),
        'tax': (m.TaxConnection, 'Tax', None),
    }


def type_key_for(connection):
    for key, (model, _label, _url) in connection_types().items():
        if isinstance(connection, model):
            return key
    raise ValueError(f'Not an integration connection: {connection!r}')


# ---------------------------------------------------------------------------
# Customer-owned → platform-owned
# ---------------------------------------------------------------------------

class OwnershipError(ValueError):
    pass


def make_platform_refusal(connection):
    """Why this connection can't become platform-owned, or ''."""
    from .models import RMMConnection
    if connection.organization_id is None:
        return 'It is already platform-owned.'
    if isinstance(connection, RMMConnection):
        if connection.provider_type == 'rem0te':
            return ('A Rem0te key belongs to one business, so a Rem0te connection is always '
                    "one customer's own.")
        from .ticket_rmm import settings as pairing_settings
        try:
            if pairing_settings(connection)['requested']:
                return ('A ticket integration pairing serves one customer. Switch the pairing off '
                        'first, then make the connection platform-owned.')
        except Exception:  # noqa: BLE001 — an unreadable pairing is refused, not ignored
            return "The connection's ticket integration pairing could not be read."
    model = type(connection)
    if platform_connections(model).filter(name=connection.name).exclude(pk=connection.pk).exists():
        return f'A platform-owned {model._meta.verbose_name} is already named "{connection.name}". Rename one first.'
    return ''


def _preserve_rmm(connection, summary):
    """Keep every resolved device with its customer once the connection
    stops being single-customer: the technician-confirmed key holds while the
    RMM keeps reporting the same customer, and each RMM customer whose
    devices all sit with one organization is mapped to it."""
    from .models import RMMConnection, RMMDevice
    from .rmm_association import customer_identity, map_customer, mapped_organization
    resolved = RMMDevice.objects.filter(connection=connection, organization__isnull=False,
                                        ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
    confirmed = 0
    by_identity = {}
    for d in resolved:
        identity = customer_identity({'client_id': d.client_id, 'client_name': d.client_name})
        if identity is not None:
            by_identity.setdefault(identity.key, (identity, set()))[1].add(d.organization_id)
        key = d.customer_key or (identity.key if identity else '')
        if key and not d.confirmed_customer_key:
            RMMDevice.objects.filter(pk=d.pk).update(customer_key=key, confirmed_customer_key=key)
            confirmed += 1
    from core.models import Organization
    mapped = 0
    for identity, org_ids in by_identity.values():
        if len(org_ids) != 1 or mapped_organization(connection, identity) is not None:
            continue
        org = Organization.objects.filter(pk=next(iter(org_ids))).first()
        if org is not None:
            map_customer(connection, identity, org)
            mapped += 1
    if connection.customer_scope != RMMConnection.CUSTOMER_SCOPE_MULTI:
        connection.customer_scope = RMMConnection.CUSTOMER_SCOPE_MULTI
        summary['customer_scope'] = 'single → multi'
    summary.update(devices_confirmed=confirmed, customers_mapped=mapped)


def _preserve_sites(connection, summary, *, unifi):
    """Write the site → customer mapping the connection used implicitly
    (everything into the owner) so those sites keep going there."""
    owner = connection.organization_id
    site_map = dict(connection.site_org_map or {})
    added = 0
    if unifi:
        from .network_assets import DEFAULT, resolve_unifi_sites
        for res in resolve_unifi_sites(connection, (connection.cached_data or {}).get('sites', [])):
            if res.status == DEFAULT and res.map_key and res.map_key not in site_map:
                site_map[res.map_key] = owner
                added += 1
    else:
        for s in (connection.cached_data or {}).get('sites', []):
            key = str(s.get('id') or '') or (s.get('name') or '')
            if key and key not in site_map:
                site_map[key] = owner
                added += 1
    connection.site_org_map = site_map
    summary['sites_mapped'] = added


@transaction.atomic
def make_platform_owned(connection, user=None, *, request=None):
    """Turn a customer's connection into a platform-owned one.

    Nothing already assigned changes hands: devices, alerts, software,
    companies, contacts, tickets, assets, documents and accounting links keep
    their organization, and the mapping each type used implicitly ("every
    site / device belongs to the owner") is written out so the same data
    keeps going to the same customer. Data that maps to no customer from now
    on stays unassigned for platform staff to place. Audit-logged.
    """
    from audit.models import AuditLog
    from .models import (AccountingConnection, AccountingCustomerLink, GrandstreamConnection,
                         OmadaConnection, RMMConnection, UnifiConnection)
    connection = type(connection)._default_manager.select_for_update().get(pk=connection.pk)
    why = make_platform_refusal(connection)
    if why:
        raise OwnershipError(why)
    previous = connection.organization
    summary = {'type': type_key_for(connection), 'connection_id': connection.pk,
               'previous_owner_id': previous.pk, 'previous_owner': previous.name}
    if isinstance(connection, RMMConnection):
        _preserve_rmm(connection, summary)
    elif isinstance(connection, UnifiConnection):
        _preserve_sites(connection, summary, unifi=True)
    elif isinstance(connection, (OmadaConnection, GrandstreamConnection)):
        _preserve_sites(connection, summary, unifi=False)
    elif isinstance(connection, AccountingConnection):
        # The link's `organization` mirrors the connection owner; the customer
        # each link represents (`client_org`) is unchanged.
        summary['accounting_links'] = AccountingCustomerLink.objects.filter(
            connection=connection).update(organization=None)
    connection.organization = None
    connection.save()
    from .health import record_owner_change
    record_owner_change(connection)
    for org in (previous, None):
        AuditLog.log(
            user=user, action='update', organization=org,
            object_type=f'integrations.{type(connection).__name__}', object_id=connection.pk,
            object_repr=str(getattr(connection, 'name', connection))[:255],
            description=(f'Made {summary["type"]} connection "{connection.name}" platform-owned '
                         f'(was owned by {previous.name}); assigned data kept its customers'),
            ip_address=(request.META.get('REMOTE_ADDR') or None) if request is not None else None,
            path=request.path if request is not None else '',
            extra_data=summary)
    return summary


# --- accounting ----------------------------------------------------------------
#
# Invoices belong to the customer billed (Invoice.organization). A customer's
# own accounting connection covers that customer's invoices; a platform-owned
# one covers every customer that has no active connection of its own for the
# same provider.

def accounting_connection_for(organization, *, platform_fallback=True):
    """The sync-enabled accounting connection an invoice for `organization`
    is pushed to when it is not pinned: the customer's own first, else (when
    allowed) a platform-owned one."""
    from .models import AccountingConnection
    active = AccountingConnection.objects.filter(is_active=True, sync_enabled=True)
    conn = active.filter(organization=organization).order_by('pk').first() if organization is not None else None
    if conn is None and platform_fallback:
        conn = active.filter(organization__isnull=True).order_by('pk').first()
    return conn


def invoices_for_connection(connection):
    """Invoices an accounting connection reconciles (payments, voids,
    balances). Never another customer's invoices for a customer-owned
    connection."""
    from psa.models import Invoice
    from .models import AccountingConnection
    if connection.organization_id is not None:
        return Invoice.objects.filter(organization_id=connection.organization_id)
    own = (AccountingConnection.objects.filter(is_active=True, provider_type=connection.provider_type,
                                               organization__isnull=False)
           .values_list('organization_id', flat=True))
    return Invoice.objects.exclude(organization_id__in=own)
