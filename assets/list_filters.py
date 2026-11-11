"""Server-side filters, sort and paging for the asset list.

Every filter narrows the queryset the view already scoped to the current
customer (or, in Global View, to what MSP staff may reach), so a filter can
only ever hide rows, never add any. The customer filter accepts only ids that
are present in that scoped queryset.

RMM filters (online / offline / stale / not linked, has active alerts) read
the RMM devices linked to the asset that belong to the asset's own customer
and whose ownership is settled, the same rule the asset page uses
(``integrations.rmm_association.exposed_devices``). They are MSP-staff only:
a customer user's list keeps the filters it always had.

The query parameters are the list's public contract (saved views store them,
``core.workspace.SAVED_VIEW_LISTS['assets']``): ``client type manufacturer
status location needs_reorder rmm alerts q search sort per_page``.
"""
from __future__ import annotations

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

SORTS = {
    'name': ('Name (A–Z)', ('name', 'pk')),
    '-name': ('Name (Z–A)', ('-name', '-pk')),
    'type': ('Type', ('asset_type', 'name', 'pk')),
    'customer': ('Customer', ('organization__name', 'name', 'pk')),
    'manufacturer': ('Manufacturer', ('manufacturer', 'model', 'name', 'pk')),
    '-updated': ('Recently updated', ('-updated_at', '-pk')),
    '-created': ('Recently added', ('-created_at', '-pk')),
}
DEFAULT_SORT = 'name'
PAGE_SIZES = (25, 50, 100, 200)
DEFAULT_PAGE_SIZE = 50

RMM_STATES = (
    ('online', 'Online'),
    ('offline', 'Offline'),
    ('stale', 'Stale (no fresh RMM data)'),
    ('linked', 'Any RMM device'),
    ('unlinked', 'No RMM device'),
)


def _linked_devices():
    from integrations.models import RMMDevice
    return RMMDevice.objects.filter(
        linked_asset_id=OuterRef('pk'),
        organization_id=OuterRef('organization_id'),
        ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
    )


def _fresh_q(now=None):
    """Devices whose RMM data is fresh, per connection's own sync interval
    (rmm_association.stale_after)."""
    from integrations.models import RMMConnection
    from integrations.rmm_association import stale_after
    now = now or timezone.now()
    q = Q(pk__in=[])
    for conn in RMMConnection.objects.only('pk', 'sync_interval_minutes'):
        q |= Q(connection_id=conn.pk, data_refreshed_at__gte=now - stale_after(conn))
    return q


def rmm_filter(qs, state):
    devices = _linked_devices()
    if state == 'linked':
        return qs.filter(Exists(devices))
    if state == 'unlinked':
        return qs.filter(~Exists(devices))
    fresh = _fresh_q()
    if state == 'online':
        return qs.filter(Exists(devices.filter(fresh, is_online=True)))
    if state == 'offline':
        return qs.filter(Exists(devices.filter(fresh, is_online=False)))
    if state == 'stale':
        return qs.filter(Exists(devices.filter(data_refreshed_at__isnull=False).exclude(fresh)))
    return qs


def alerts_filter(qs):
    from integrations.models import RMMAlert
    return qs.filter(Exists(RMMAlert.objects.filter(
        status='active', device__in=_linked_devices())))


def text_filter(qs, text):
    text = text.strip()[:100]
    if not text:
        return qs
    return qs.filter(Q(name__icontains=text) | Q(serial_number__icontains=text)
                     | Q(asset_tag__icontains=text) | Q(hostname__icontains=text)
                     | Q(manufacturer__icontains=text) | Q(model__icontains=text))


def page_size(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return n if n in PAGE_SIZES else DEFAULT_PAGE_SIZE


def rmm_rows(assets):
    """{asset pk: {'status': device_status dict, 'alerts': n}} for one page."""
    from django.db.models import Count
    from integrations.models import RMMDevice
    from integrations.rmm_association import device_status
    by_pk = {a.pk: a for a in assets}
    if not by_pk:
        return {}
    devices = (RMMDevice.objects.filter(linked_asset_id__in=list(by_pk),
                                        ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
               .select_related('connection')
               .annotate(active_alerts=Count('alerts', filter=Q(alerts__status='active'))))
    now = timezone.now()
    out = {}
    for d in devices:
        asset = by_pk.get(d.linked_asset_id)
        if asset is None or d.organization_id != asset.organization_id:
            continue
        row = out.setdefault(asset.pk, {'status': None, 'alerts': 0, 'devices': 0})
        row['devices'] += 1
        row['alerts'] += d.active_alerts
        status = device_status(d, now)
        # Show the most reassuring-to-least order consistently: an offline or
        # stale device on a multi-device asset wins over an online one.
        rank = {'offline': 0, 'stale': 1, 'unknown': 2, 'online': 3}
        if row['status'] is None or rank[status['state']] < rank[row['status']['state']]:
            row['status'] = status
    return out
