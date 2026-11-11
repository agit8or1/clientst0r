"""
Opt-in device lists (services today) kept from what an RMM's existing API
client already returns, for the Device Workspace.

  * Opt-in per connection (RMMConnection.sync_services) and only for
    providers whose client already fetches the list (`supports_services`).
    Nothing here adds an API call or a scope.
  * Latest only: one RMMDeviceSnapshot per device and kind, replaced on each
    collection, and deleted once older than RETENTION_DAYS. A list older
    than that is never shown.
  * Customer-scoped: the row carries the device's customer, reads require
    that it still matches, and a device that changes customer loses its
    rows (set_device_organization).
  * Only the fields the page shows are kept (no binary paths, service
    account names or descriptions), at most MAX_ITEMS rows.
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from django.utils import timezone

RETENTION_DAYS = 14
MAX_ITEMS = 500

# Tactical RMM's service record (trmm-shared WindowsService): name,
# display_name, status, start_type, pid, binpath, username, description,
# autodelay. Kept: the first four.
SERVICE_FIELDS = ('name', 'display_name', 'status', 'start_type')


def normalize_services(raw_list) -> List[dict]:
    out = []
    for s in raw_list or []:
        if not isinstance(s, dict):
            continue
        row = {k: str(s.get(k) or '')[:120] for k in SERVICE_FIELDS}
        if row['name'] or row['display_name']:
            out.append(row)
    out.sort(key=lambda r: (r['display_name'] or r['name']).casefold())
    return out


def collecting(connection, kind='services', provider=None) -> bool:
    if kind != 'services' or not getattr(connection, 'sync_services', False):
        return False
    if provider is None:
        from .providers.rmm import RMM_PROVIDER_REGISTRY
        provider = RMM_PROVIDER_REGISTRY.get(connection.provider_type)
    return bool(provider is not None and getattr(provider, 'supports_services', False))


def store(device, kind, items, now=None):
    """Replace this device's list of `kind`. Items are already normalized."""
    from .models import RMMDeviceSnapshot
    now = now or timezone.now()
    items = list(items or [])
    snap, _ = RMMDeviceSnapshot.objects.update_or_create(
        device=device, kind=kind,
        defaults={'organization_id': device.organization_id, 'connection_id': device.connection_id,
                  'items': items[:MAX_ITEMS], 'item_count': len(items), 'truncated': len(items) > MAX_ITEMS,
                  'collected_at': now})
    return snap


def latest(device, kind='services', now=None):
    """This device's current list of `kind`, or None: only within retention
    and only while it carries the device's own customer."""
    from .models import RMMDeviceSnapshot
    if not device.organization_id:
        return None
    now = now or timezone.now()
    return (RMMDeviceSnapshot.objects
            .filter(device=device, kind=kind, organization_id=device.organization_id,
                    connection_id=device.connection_id, collected_at__gte=now - timedelta(days=RETENTION_DAYS))
            .first())


def purge(connection=None, now=None) -> int:
    """Delete lists older than the retention window, and every list of a
    connection that no longer collects them."""
    from .models import RMMDeviceSnapshot
    now = now or timezone.now()
    qs = RMMDeviceSnapshot.objects.filter(collected_at__lt=now - timedelta(days=RETENTION_DAYS))
    n = qs.delete()[0]
    if connection is not None and not collecting(connection):
        n += RMMDeviceSnapshot.objects.filter(connection=connection).delete()[0]
    return n


def forget_device(device, org=None):
    """The device changed customer: what was collected under the old one goes."""
    from .models import RMMDeviceSnapshot
    qs = RMMDeviceSnapshot.objects.filter(device=device)
    if org is not None:
        qs = qs.exclude(organization=org)
    return qs.delete()[0]


def take_from_raw(raw: dict, kind='services') -> Optional[list]:
    """Remove a list from a raw payload (it is never kept in raw_data) and
    return it, or None when the payload didn't carry one."""
    if not isinstance(raw, dict) or kind not in raw:
        return None
    value = raw.pop(kind)
    return value if isinstance(value, list) else None
