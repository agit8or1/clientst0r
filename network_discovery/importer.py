"""
Phase 32 (v3.17.556) — turning a discovery payload into Asset records.

The matching order is from the roadmap and is not arbitrary: MAC first because
it identifies a device, IP second because it only identifies a device *at a
place at a time*. DHCP moves addresses around, so IP matching is scoped to one
organization and location and is a fallback rather than the primary key.

The rule that matters most on update: **never overwrite something a person
typed.** A discovery sweep knows a device answered at an address. It does not
know better than the technician who named it.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from assets.models import Asset

from .models import (
    MAX_DEVICES_PER_UPLOAD, NetworkDiscoveryAssetResult, normalise_mac,
    valid_ipv4,
)

logger = logging.getLogger(__name__)

# What a discovered-but-unclassified device becomes. A real type can be set by
# hand later; guessing "server" from an open port would put a fiction in the
# asset register.
DEFAULT_ASSET_TYPE = 'other'

# Port-based classification the script may send. Deliberately coarse — these
# are hints, not facts, and the mapping only picks an asset type when the
# answer is not really in doubt.
DEVICE_TYPE_TO_ASSET_TYPE = {
    'printer': 'printer',
    'router': 'router',
    'switch': 'switch',
    'firewall': 'firewall',
    'server': 'server',
    'workstation': 'desktop',
    'access_point': 'wireless_ap',
}

DISCOVERY_NOTE = 'Discovered by Remote Network Discovery Import'


def clean_device(raw):
    """Validate and normalise one device entry.

    Returns `(device, error)`. Anything that is not a dict with at least an IP
    or a MAC is rejected — a row with neither cannot be matched or created, and
    silently importing it would produce a nameless asset nobody can act on.
    """
    if not isinstance(raw, dict):
        return None, 'not an object'

    ip = str(raw.get('ip') or raw.get('ip_address') or '').strip()
    if ip and not valid_ipv4(ip):
        return None, f'invalid IPv4 address: {ip[:40]}'

    mac = normalise_mac(raw.get('mac') or raw.get('mac_address') or '')
    if not ip and not mac:
        return None, 'neither an IP nor a MAC'

    hostname = str(raw.get('hostname') or '').strip()[:255]
    # A hostname is a label, not a command. Strip anything that is not
    # plausible in one rather than trusting whatever the network returned.
    if hostname and not all(c.isalnum() or c in '-._' for c in hostname):
        hostname = ''.join(c for c in hostname if c.isalnum() or c in '-._')

    return {
        'ip': ip,
        'mac': mac,
        'hostname': hostname,
        'vendor': str(raw.get('vendor') or '').strip()[:255],
        'device_type': str(raw.get('device_type') or '').strip()[:60],
        'discovery_method': str(raw.get('method') or raw.get('discovery_method')
                                or '').strip()[:60],
        'open_ports': raw.get('open_ports') if isinstance(
            raw.get('open_ports'), list) else [],
    }, None


def _asset_type_for(device):
    return DEVICE_TYPE_TO_ASSET_TYPE.get(
        (device.get('device_type') or '').lower(), DEFAULT_ASSET_TYPE)


def _asset_name_for(device):
    """hostname → IP → MAC, per the roadmap. Something is always available
    because `clean_device` rejects rows with neither IP nor MAC."""
    return (device.get('hostname') or device.get('ip')
            or device.get('mac') or 'Unknown device')[:255]


def find_existing_asset(organization, location, device):
    """MAC first, then organization+location+IP. None if neither matches."""
    mac = device.get('mac')
    if mac:
        match = Asset.objects.filter(
            organization=organization, mac_address__iexact=mac).first()
        if match is not None:
            return match, 'mac'

    ip = device.get('ip')
    if ip:
        # Scoped to the location as well as the org: the same private address
        # exists at every site an MSP looks after, and 192.168.1.10 at one
        # client's office is not 192.168.1.10 at another's.
        qs = Asset.objects.filter(organization=organization, ip_address=ip)
        location_field = _asset_location_field()
        if location_field:
            qs = qs.filter(**{location_field: location})
        match = qs.first()
        if match is not None:
            return match, 'ip'

    return None, ''


def _asset_location_field():
    """The Asset field holding a location, if this install's model has one.

    Asset carries location in `custom_fields` on some installs and as a real
    relation on others. Rather than assume, look — and fall back to org-only IP
    matching when there is no such field, which is narrower than wrong.
    """
    for name in ('location', 'site'):
        try:
            field = Asset._meta.get_field(name)
        except Exception:
            continue
        if field.is_relation:
            return name
    return None


def apply_device(organization, location, device, *, dry_run=False):
    """Match or create one asset. Returns `(asset, status, detail)`."""
    existing, matched_on = find_existing_asset(organization, location, device)

    if existing is not None:
        if dry_run:
            return existing, 'preview', f'would update (matched on {matched_on})'
        changed = _fill_missing_fields(existing, device)
        if changed:
            existing.save(update_fields=changed)
            return existing, 'updated', (
                f'matched on {matched_on}; filled ' + ', '.join(sorted(changed)))
        return existing, 'matched', f'matched on {matched_on}; nothing missing'

    if dry_run:
        return None, 'preview', 'would create a new asset'

    fields = {
        'organization': organization,
        'name': _asset_name_for(device),
        'asset_type': _asset_type_for(device),
        'hostname': device.get('hostname') or '',
        'mac_address': device.get('mac') or '',
        'notes': DISCOVERY_NOTE,
    }
    if device.get('ip'):
        fields['ip_address'] = device['ip']
    if device.get('vendor'):
        fields['manufacturer'] = device['vendor'][:100]

    location_field = _asset_location_field()
    if location_field:
        fields[location_field] = location

    asset = Asset.objects.create(**fields)
    # Stamped after creation and then saved. Setting it on the instance without
    # this second write left the metadata in memory only — caught by the test
    # that asserts a created asset carries its last-seen timestamp.
    _stamp_discovery_metadata(asset, device)
    asset.save(update_fields=['custom_fields'])
    return asset, 'created', 'new asset'


def _fill_missing_fields(asset, device):
    """Fill blanks only. Returns the list of field names changed.

    This is the heart of the safety story on update. A sweep knows a device
    answered at an address; it does not know better than the technician who
    named it, so a populated field is left exactly as it is — including a name
    that happens to look auto-generated.
    """
    changed = []

    if device.get('mac') and not (asset.mac_address or '').strip():
        asset.mac_address = device['mac']
        changed.append('mac_address')

    if device.get('ip') and not asset.ip_address:
        asset.ip_address = device['ip']
        changed.append('ip_address')

    if device.get('hostname') and not (asset.hostname or '').strip():
        asset.hostname = device['hostname']
        changed.append('hostname')

    if device.get('vendor') and not (asset.manufacturer or '').strip():
        asset.manufacturer = device['vendor'][:100]
        changed.append('manufacturer')

    if _stamp_discovery_metadata(asset, device):
        changed.append('custom_fields')

    if changed:
        changed.append('updated_at')
    return changed


def _stamp_discovery_metadata(asset, device):
    """Record when discovery last saw this device, in `custom_fields`.

    Kept out of the visible columns deliberately: last-seen is discovery
    bookkeeping, and promoting it to a first-class field would imply the asset
    register knows something continuous about the device, which after a
    one-shot sweep it does not.
    """
    custom = asset.custom_fields if isinstance(asset.custom_fields, dict) else {}
    custom['network_discovery_last_seen'] = timezone.now().isoformat()
    if device.get('discovery_method'):
        custom['network_discovery_method'] = device['discovery_method']
    if device.get('open_ports'):
        custom['network_discovery_open_ports'] = device['open_ports'][:20]
    asset.custom_fields = custom
    return True


def import_payload(discovery_import, devices, *, dry_run=False):
    """Import a validated device list against one import row.

    Never raises for a bad device: one malformed entry in a sweep of two
    hundred must not throw the other hundred and ninety-nine away, so failures
    are recorded per device and the run continues.
    """
    organization = discovery_import.organization
    location = discovery_import.location

    counts = {'device': 0, 'imported': 0, 'updated': 0, 'skipped': 0, 'error': 0}
    seen_keys = set()

    for raw in devices[:MAX_DEVICES_PER_UPLOAD]:
        counts['device'] += 1
        device, error = clean_device(raw)

        if error:
            counts['error'] += 1
            NetworkDiscoveryAssetResult.objects.create(
                discovery_import=discovery_import,
                organization=organization, location=location,
                status='error', detail=error[:255],
                raw=raw if isinstance(raw, dict) else {'value': str(raw)[:500]},
            )
            continue

        # A sweep can list the same device twice — once from ping, once from
        # ARP. Collapse them here rather than creating two assets.
        key = device['mac'] or f"ip:{device['ip']}"
        if key in seen_keys:
            counts['skipped'] += 1
            NetworkDiscoveryAssetResult.objects.create(
                discovery_import=discovery_import,
                organization=organization, location=location,
                ip_address=device['ip'] or None, mac_address=device['mac'],
                hostname=device['hostname'], vendor=device['vendor'],
                device_type=device['device_type'],
                discovery_method=device['discovery_method'],
                status='skipped', detail='duplicate of an earlier entry',
                raw=device,
            )
            continue
        seen_keys.add(key)

        try:
            asset, status, detail = apply_device(
                organization, location, device, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 — one bad row must not stop the run
            logger.exception('Discovery import failed for one device')
            counts['error'] += 1
            NetworkDiscoveryAssetResult.objects.create(
                discovery_import=discovery_import,
                organization=organization, location=location,
                ip_address=device['ip'] or None, mac_address=device['mac'],
                hostname=device['hostname'], status='error',
                detail=str(exc)[:255], raw=device,
            )
            continue

        if status == 'created':
            counts['imported'] += 1
        elif status == 'updated':
            counts['updated'] += 1
        elif status in ('matched', 'preview'):
            counts['skipped'] += 1

        NetworkDiscoveryAssetResult.objects.create(
            discovery_import=discovery_import,
            organization=organization, location=location, asset=asset,
            ip_address=device['ip'] or None, mac_address=device['mac'],
            hostname=device['hostname'], vendor=device['vendor'],
            device_type=device['device_type'],
            discovery_method=device['discovery_method'],
            status=status, detail=detail[:255], raw=device,
        )

    discovery_import.device_count = counts['device']
    discovery_import.imported_count = counts['imported']
    discovery_import.updated_count = counts['updated']
    discovery_import.skipped_count = counts['skipped']
    discovery_import.error_count = counts['error']
    discovery_import.save(update_fields=[
        'device_count', 'imported_count', 'updated_count',
        'skipped_count', 'error_count',
    ])
    return counts
