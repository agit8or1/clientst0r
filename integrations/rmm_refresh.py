"""
"Refresh from RMM" for one device (Device Workspace).

Runs the provider's own single-device read (`get_device`, the call each
client already makes) and stores what it returned, the way a sync would for
that device. It never runs while a page renders: only from the POST route
(assets/workspace_refresh.py).

  * Rate limited per device: one refresh per REFRESH_INTERVAL, claimed with
    one conditional UPDATE so two workers can't both run it.
  * It never changes who the device belongs to. If the RMM now reports a
    different customer, nothing is stored and the next full sync reviews
    the move as usual.
  * Inventory fields only. Customer resolution, asset linking and alerts
    stay with the full sync.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

REFRESH_INTERVAL = timedelta(minutes=5)

OK, RATE_LIMITED, UNAVAILABLE, REFUSED, FAILED = 'ok', 'rate_limited', 'unavailable', 'refused', 'failed'


@dataclass
class RefreshResult:
    outcome: str
    message: str
    retry_after: int = 0

    @property
    def ok(self):
        return self.outcome == OK


def provider_class(connection):
    from .providers.rmm import RMM_PROVIDER_REGISTRY
    return RMM_PROVIDER_REGISTRY.get(connection.provider_type)


def availability(device):
    """(available, reason) without calling the provider."""
    from .providers.rmm_base import BaseRMMProvider
    conn = device.connection
    cls = provider_class(conn)
    if cls is None or getattr(cls, 'get_device', None) is BaseRMMProvider.get_device:
        return False, f"{conn.get_provider_type_display()} has no single-device refresh in ClientSt0r."
    if not conn.is_active or not conn.sync_enabled:
        return False, f'The {conn.name} connection is switched off.'
    if not device.is_exposed:
        return False, "The device's customer is under review."
    return True, ''


def claim(device, now=None) -> int:
    """Take this device's refresh slot. 0 when taken, else seconds to wait."""
    from .models import RMMDevice
    now = now or timezone.now()
    got = (RMMDevice.objects.filter(pk=device.pk)
           .filter(Q(manual_refresh_at__isnull=True) | Q(manual_refresh_at__lte=now - REFRESH_INTERVAL))
           .update(manual_refresh_at=now))
    if got:
        device.manual_refresh_at = now
        return 0
    last = RMMDevice.objects.filter(pk=device.pk).values_list('manual_refresh_at', flat=True).first()
    if last is None:
        return int(REFRESH_INTERVAL.total_seconds())
    return max(1, int((last + REFRESH_INTERVAL - now).total_seconds()))


def _same_customer(device, data) -> bool:
    from .rmm_association import clean_external_id, customer_identity
    conn = device.connection
    if conn.provider_type == 'rem0te':
        # A Rem0te key sees one business; the sync pins it on first use.
        from .providers.rmm.rem0te import BUSINESS_PIN
        pinned = (conn.field_mappings or {}).get(BUSINESS_PIN)
        if pinned and clean_external_id(data.get('client_id')) != pinned:
            return False
    if conn.is_single_customer:
        return True
    identity = customer_identity(data)
    if identity is None:
        return False
    if identity.key == device.customer_key:
        return True
    # The same customer, now reported by ID where the stored key was its name.
    return (not identity.name_only and bool(identity.client_name)
            and device.customer_key == f'name:{identity.client_name.casefold()}')


def refresh_device(device, now=None) -> RefreshResult:
    """Refresh one device from its RMM. The caller has checked permission
    and audits the outcome."""
    from . import rmm_snapshots
    from .models import RMMDevice
    from .providers.rmm import get_rmm_provider
    from .rmm_association import clean_external_id
    now = now or timezone.now()
    ok, reason = availability(device)
    if not ok:
        return RefreshResult(UNAVAILABLE, reason)
    wait = claim(device, now)
    if wait:
        return RefreshResult(RATE_LIMITED, f'This device was refreshed less than {int(REFRESH_INTERVAL.total_seconds() // 60)} '
                                           f'minutes ago. Try again in {wait} seconds.', wait)
    conn = device.connection
    label = conn.get_provider_type_display()
    try:
        provider = get_rmm_provider(conn)
        data = provider.get_device(device.external_id)
    except Exception as exc:  # noqa: BLE001 — the RMM's answer, redacted
        from .health import redact_for
        return RefreshResult(FAILED, f'{label} did not answer the refresh: {redact_for(conn, exc)}'[:300])
    if not isinstance(data, dict) or clean_external_id(data.get('external_id')) != device.external_id:
        return RefreshResult(REFUSED, f'{label} returned a different device; nothing was stored.')
    if not _same_customer(device, data):
        return RefreshResult(REFUSED, f'{label} now reports this device under another customer. Nothing was '
                                      'stored; the next sync puts the move up for review.')

    services = None
    with transaction.atomic():
        d = RMMDevice.objects.select_for_update().get(pk=device.pk)
        raw = dict(data.get('raw_data') or {})
        for key in getattr(provider, 'refresh_keep_raw_keys', ()):
            if key not in raw and key in (d.raw_data or {}):
                raw[key] = d.raw_data[key]
        if getattr(provider, 'supports_services', False):
            services = rmm_snapshots.take_from_raw(raw, 'services')
        for key in ('ram_gb', 'storage', 'cpu'):
            if data.get(key):
                raw[f'_norm_{key}'] = data[key]
        d.device_name = data.get('device_name') or data.get('hostname') or d.device_name
        d.device_type = data.get('device_type') or d.device_type
        d.manufacturer = data.get('manufacturer') or ''
        d.model = data.get('model') or ''
        d.serial_number = (data.get('serial_number') or '').strip()
        d.os_type = data.get('os_type') or ''
        d.os_version = data.get('os_version') or ''
        d.hostname = data.get('hostname') or ''
        d.ip_address = data.get('ip_address') or None
        d.mac_address = (data.get('mac_address') or '')[:17]
        d.is_online = bool(data.get('is_online', False))
        d.last_seen = data.get('last_seen') or d.last_seen
        d.raw_data = raw
        d.data_refreshed_at = now
        d.save()
        if services is not None and rmm_snapshots.collecting(conn, provider=provider) and d.is_exposed:
            rmm_snapshots.store(d, 'services', rmm_snapshots.normalize_services(services), now=now)
    device.refresh_from_db()
    return RefreshResult(OK, f'Refreshed from {label}.')
