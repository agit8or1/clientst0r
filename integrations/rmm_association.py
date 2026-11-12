"""Which customer an RMM device belongs to, and which asset it is.

Every RMM adapter normalizes its payloads to the same shape; the decisions
here are shared so the five providers behave alike:

* Customer first. A device is never linked to an asset, and its status,
  alerts and software are never shown, until its customer is settled. A
  single-customer connection settles it by configuration; a multi-customer
  connection resolves the RMM's own customer identity through a persistent
  mapping. Anything unresolved — no customer in the payload, an import
  error, a customer nobody has mapped, or a device the RMM now reports under
  a different customer — is held with no organization for staff review.
  Nothing falls back to the connection owner's organization.
* Then the asset, inside that customer only. A unique usable serial matches
  automatically; a unique hostname matches only when no hardware identity
  conflicts and the site evidence agrees. Duplicates, conflicts and possible
  replacements go to review with the candidates and a plain reason. An IP
  address is never identity: private ranges repeat across customers.
* Technician decisions stick: a confirmed link, an explicit unlink and a
  confirmed customer survive later syncs until the RMM reports something
  different about that device.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('integrations')

# Serials that OEMs, hypervisors and imaging tools ship by the thousand.
PLACEHOLDER_SERIALS = {
    'to be filled by o.e.m.', 'to be filled by o.e.m', 'default string',
    'not specified', 'not applicable', 'none', 'null', 'n/a', 'na', 'system serial number',
    'chassis serial number', 'serial number', 'invalid', 'unknown', 'xxxxxxxxxxx',
    '0', '00000000', '0000000000', '000000000000', '1234567890', '123456789',
    '12345678', '0123456789', 'base board serial number', 'oem', 'empty',
}

# Hardware fields an RMM may keep up to date on a linked asset.
RMM_ASSET_FIELDS = ('serial_number', 'manufacturer', 'model', 'hostname', 'ip_address',
                    'mac_address', 'os_name', 'os_version', 'cpu', 'ram_gb', 'storage')

BLANK_IDS = {'', 'none', 'null', 'undefined', '0'}


def clean_external_id(value):
    """The device ID as a string, or '' when the payload has no usable one."""
    if value is None:
        return ''
    text = str(value).strip()
    return '' if text.lower() in BLANK_IDS else text


def usable_serial(serial):
    s = (serial or '').strip()
    if len(s) < 4:
        return False
    low = s.lower()
    if low in PLACEHOLDER_SERIALS:
        return False
    # A run of one repeated character ("0000000", "FFFFFFFF").
    return len(set(low)) > 1


def short_host(name):
    """'FRONTDESK.corp.local' and 'frontdesk' are the same machine name."""
    return (name or '').strip().split('.')[0].casefold()


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

@dataclass
class CustomerIdentity:
    key: str
    client_id: str
    client_name: str
    name_only: bool

    @property
    def label(self):
        if self.name_only:
            return f'"{self.client_name}"'
        return f'"{self.client_name}" (ID {self.client_id})' if self.client_name else f'ID {self.client_id}'


def customer_identity(data):
    """The RMM's customer for a normalized device, or None if it reported none.

    Adapters set `client_id` to the provider's real customer ID. When a
    payload only carries a name, they leave `client_id` empty and the name
    becomes the key, explicitly marked as name-only.
    """
    client_id = clean_external_id(data.get('client_id'))
    client_name = (data.get('client_name') or '').strip()
    if client_id:
        return CustomerIdentity(f'id:{client_id}', client_id, client_name, False)
    if client_name:
        return CustomerIdentity(f'name:{client_name.casefold()}', '', client_name, True)
    return None


def _map_types(identity):
    # Only customer-level mappings. Older 'rmm_site' rows hold site IDs, which
    # can equal another customer's ID numerically, so they are never used to
    # place a device; such devices go to review instead.
    return ('rmm_client_name',) if identity.name_only else ('rmm_client',)


def _map_value(identity):
    return identity.client_name.casefold() if identity.name_only else identity.client_id


def mapped_organization(connection, identity):
    """The organization this RMM customer is mapped to on this connection."""
    from core.models import Organization
    from .org_import import _eom_filter
    for external_type in _map_types(identity):
        row = _eom_filter(connection, external_type=external_type,
                          external_id=_map_value(identity), local_type='organization').first()
        if row:
            org = Organization.objects.filter(pk=row.local_id).first()
            if org:
                return org
    return None


def map_customer(connection, identity, org):
    """Record that this RMM customer is `org` on this connection."""
    from django.contrib.contenttypes.models import ContentType
    from .models import ExternalObjectMap
    ExternalObjectMap.objects.update_or_create(
        connection_type=ContentType.objects.get_for_model(connection),
        connection_id=connection.pk,
        external_type=_map_types(identity)[0],
        external_id=_map_value(identity),
        defaults={'organization': org, 'local_type': 'organization', 'local_id': org.pk},
    )


@dataclass
class CustomerDecision:
    organization: object = None
    status: str = 'resolved'
    note: str = ''
    pending: object = None
    created: bool = False


def resolve_customer(connection, data, device=None, *, legacy_keys=()):
    """Decide which customer a normalized device belongs to.

    `device` is the existing RMMDevice (or None for a new one). `legacy_keys`
    are earlier client IDs an adapter used for the same customer (Tactical
    RMM used name slugs), so existing mappings carry over.
    """
    from .models import RMMDevice
    # Single customer means "the owner's": a platform-owned connection has no
    # customer of its own, so it always resolves each device's customer.
    if connection.is_single_customer and connection.organization_id is not None:
        return CustomerDecision(connection.organization)

    identity = customer_identity(data)
    if identity is None:
        return CustomerDecision(None, RMMDevice.OWNERSHIP_UNRESOLVED,
                                "The RMM didn't report a customer for this device.")

    previous_key = device.customer_key if device is not None else ''
    if device is not None and device.confirmed_customer_key == identity.key and device.organization_id:
        return CustomerDecision(device.organization)

    mapped = mapped_organization(connection, identity)
    if mapped is None and legacy_keys:
        from core.models import Organization
        from .org_import import _eom_filter
        for legacy in legacy_keys:
            row = _eom_filter(connection, external_type='rmm_client', external_id=legacy,
                              local_type='organization').first()
            org = Organization.objects.filter(pk=row.local_id).first() if row else None
            if org:
                map_customer(connection, identity, org)
                mapped = org
                break

    # The same customer, now reported with its real ID where an earlier sync
    # only had its name (Tactical RMM when /clients/ was unreachable): carry
    # the name mapping over instead of treating it as a move.
    upgraded = (bool(previous_key) and not identity.name_only and bool(identity.client_name)
                and previous_key == f'name:{identity.client_name.casefold()}')
    if upgraded and mapped is None:
        mapped = mapped_organization(connection, CustomerIdentity(previous_key, '', identity.client_name, True))
        if mapped is not None:
            map_customer(connection, identity, mapped)

    # The RMM moved the device (or, for name-only payloads, renamed its
    # customer): stop showing it under the old customer until someone looks.
    if (previous_key and previous_key != identity.key and not upgraded
            and device.ownership_status != RMMDevice.OWNERSHIP_UNRESOLVED):
        old = device.organization.name if device.organization_id else 'no customer'
        return CustomerDecision(
            None, RMMDevice.OWNERSHIP_MOVED,
            f'The RMM now reports this device under customer {identity.label}; '
            f'it was with {old}. Confirm the customer before it is shown again.',
            pending=mapped)

    if mapped is not None:
        return CustomerDecision(mapped)

    # Name-only customers are never imported automatically: a renamed
    # customer would look new and silently become a second organization.
    # A technician maps the name once in the review queue.
    if identity.name_only:
        return CustomerDecision(None, RMMDevice.OWNERSHIP_UNRESOLVED,
                                f'The RMM reports customer {identity.label} by name only. '
                                f'Map it to a customer once and later syncs follow that mapping.')

    if connection.import_organizations and identity.client_name:
        from .org_import import import_organization_from_rmm
        try:
            with transaction.atomic():
                org = import_organization_from_rmm(connection, {
                    'external_id': identity.client_id,
                    'client_id': identity.client_id,
                    'client_name': identity.client_name,
                    'name': identity.client_name,
                })
        except Exception as exc:  # an import error never falls back to the owner
            logger.error('RMM customer import failed for %s on %s: %s', identity.label, connection, exc)
            org = None
        if org is not None:
            return CustomerDecision(org, created=True)
        return CustomerDecision(None, RMMDevice.OWNERSHIP_UNRESOLVED,
                                f'Importing RMM customer {identity.label} failed.')

    return CustomerDecision(None, RMMDevice.OWNERSHIP_UNRESOLVED,
                            f'No customer is mapped to RMM customer {identity.label}.')


def apply_customer_decision(device, decision, identity):
    """Put a `resolve_customer` decision on the device (not saved)."""
    from .models import RMMDevice
    device.ownership_status = decision.status
    device.ownership_note = decision.note
    if decision.status == RMMDevice.OWNERSHIP_RESOLVED:
        device.organization = decision.organization
        device.pending_organization = None
        device.customer_key = identity.key if identity else ''
    elif decision.status == RMMDevice.OWNERSHIP_MOVED:
        # Keep the old key: the move stays under review until someone
        # confirms it, however many syncs run in between.
        device.organization = None
        device.pending_organization = decision.pending
    else:
        device.organization = None
        device.pending_organization = None
        device.customer_key = identity.key if identity else ''


def set_device_organization(device, org):
    """Move a device's cached alerts and software with it; drop its kept lists."""
    from .models import RMMAlert, RMMSoftware
    RMMAlert.objects.filter(device=device).exclude(organization=org).update(organization=org)
    RMMSoftware.objects.filter(device=device).exclude(organization=org).update(organization=org)
    # Kept lists (services) were collected under the old customer: dropped.
    from .rmm_snapshots import forget_device
    forget_device(device, org)


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

@dataclass
class AssetDecision:
    action: str            # keep | match | create | review | clear | none
    asset: object = None
    note: str = ''
    candidates: list = field(default_factory=list)


def _site_names_for(asset, connection_id):
    # Sites as this same RMM names them: another RMM's site names (Datto's
    # site is the customer) aren't comparable.
    names = set()
    for other in asset.rmm_devices.filter(connection_id=connection_id):
        if other.site_name:
            names.add(other.site_name.strip().casefold())
    site = (asset.custom_fields or {}).get('site') if isinstance(asset.custom_fields, dict) else None
    if isinstance(site, str) and site.strip():
        names.add(site.strip().casefold())
    return names


def _site_conflict(device, asset):
    if not device.site_name:
        return False
    known = _site_names_for(asset, device.connection_id)
    return bool(known) and device.site_name.strip().casefold() not in known


def _linked_elsewhere_on_connection(device, asset):
    return asset.rmm_devices.filter(connection_id=device.connection_id).exclude(pk=device.pk).first()


def decide_asset(device, *, auto_create=True):
    """What to do about this device's asset link. Never crosses customers."""
    from assets.models import Asset
    from .models import RMMDevice

    if not device.is_exposed:
        return AssetDecision('none')

    linked = device.linked_asset
    if linked is not None:
        if linked.organization_id != device.organization_id:
            return AssetDecision('clear', note=(
                f'The linked asset "{linked.name}" belongs to another customer, so the link was removed.'))
        if device.link_status == RMMDevice.LINK_CONFIRMED:
            return AssetDecision('keep', linked)
        if (usable_serial(device.serial_number) and usable_serial(linked.serial_number)
                and device.serial_number.strip().casefold() != linked.serial_number.strip().casefold()):
            return AssetDecision('review', linked, note=(
                f'The RMM reports serial {device.serial_number} but the linked asset "{linked.name}" '
                f'has serial {linked.serial_number}. The hardware may have been replaced.'),
                candidates=[linked.pk])
        return AssetDecision('keep', linked)

    if device.link_status in (RMMDevice.LINK_UNLINKED, RMMDevice.LINK_REVIEW):
        return AssetDecision('none')

    assets = Asset.objects.filter(organization_id=device.organization_id)
    name = device.hostname or device.device_name

    # Asset this connection created for this device earlier (a retry, or an
    # overlapping sync that already got there).
    own = assets.filter(custom_fields__rmm_connection_id=device.connection_id,
                        custom_fields__rmm_external_id=device.external_id).first()
    if own is not None:
        return AssetDecision('match', own)

    if usable_serial(device.serial_number):
        by_serial = list(assets.filter(serial_number__iexact=device.serial_number.strip()))
        if len(by_serial) > 1:
            return AssetDecision('review', note=(
                f'{len(by_serial)} assets at this customer have serial {device.serial_number}. '
                f'Choose the correct one.'), candidates=[a.pk for a in by_serial])
        if len(by_serial) == 1:
            asset = by_serial[0]
            other = _linked_elsewhere_on_connection(device, asset)
            if other is not None:
                return AssetDecision('review', note=(
                    f'"{asset.name}" has the same serial and is already linked to '
                    f'{other.device_name} in this RMM. It may be a duplicate agent.'),
                    candidates=[asset.pk])
            return AssetDecision('match', asset)

    host = short_host(name)
    if host:
        by_host = [a for a in assets.exclude(hostname='') if short_host(a.hostname) == host]
        by_name = [a for a in assets.filter(hostname='') if short_host(a.name) == host]
        if len(by_host) > 1:
            return AssetDecision('review', note=(
                f'{len(by_host)} assets at this customer have the hostname {name.upper()}. '
                f'Choose the correct one.'), candidates=[a.pk for a in by_host])
        if len(by_host) == 1:
            asset = by_host[0]
            if (usable_serial(device.serial_number) and usable_serial(asset.serial_number)
                    and device.serial_number.strip().casefold() != asset.serial_number.strip().casefold()):
                return AssetDecision('review', note=(
                    f'"{asset.name}" has the hostname {name.upper()} but serial {asset.serial_number}, '
                    f'and the RMM reports {device.serial_number}. It may be a replacement machine.'),
                    candidates=[asset.pk])
            if _site_conflict(device, asset):
                return AssetDecision('review', note=(
                    f'"{asset.name}" has the hostname {name.upper()} but is recorded at a different '
                    f'site than {device.site_name}.'), candidates=[asset.pk])
            other = _linked_elsewhere_on_connection(device, asset)
            if other is not None:
                return AssetDecision('review', note=(
                    f'"{asset.name}" has the hostname {name.upper()} and is already linked to '
                    f'{other.device_name} in this RMM.'), candidates=[asset.pk])
            return AssetDecision('match', asset)
        if by_name:
            return AssetDecision('review', note=(
                f'{"An asset" if len(by_name) == 1 else str(len(by_name)) + " assets"} at this customer '
                f'{"is" if len(by_name) == 1 else "are"} named {name.upper()} with no hostname recorded. '
                f'Link it if it is this device.'), candidates=[a.pk for a in by_name])

    return AssetDecision('create' if auto_create else 'none')


def _legacy_owned(asset, device):
    cf = asset.custom_fields if isinstance(asset.custom_fields, dict) else {}
    return bool(cf.get('rmm_synced')) and str(cf.get('rmm_external_id', '')) == device.external_id


def device_hardware(device):
    """Asset field values the RMM reports for this device."""
    raw = device.raw_data or {}
    cpu_raw = raw.get('cpu_model') or raw.get('cpu') or raw.get('_norm_cpu') or ''
    cpu = ', '.join(str(c) for c in cpu_raw if c) if isinstance(cpu_raw, list) else str(cpu_raw or '')
    ram_gb = None
    try:
        if raw.get('total_ram'):
            ram_gb = int(round(float(raw['total_ram'])))
        elif raw.get('_norm_ram_gb') is not None:
            ram_gb = int(round(float(raw['_norm_ram_gb'])))
    except (TypeError, ValueError):
        ram_gb = None
    storage_parts = []
    for disk in raw.get('disks') or []:
        if not isinstance(disk, dict):
            continue
        try:
            total = float(disk.get('total_gb') or disk.get('total') or 0)
            used = float(disk.get('used_gb') or disk.get('used') or 0)
        except (TypeError, ValueError):
            continue
        if total:
            pct = disk.get('percent')
            pct = round(float(pct)) if pct is not None else round(used / total * 100)
            storage_parts.append(f"{disk.get('device') or disk.get('dev', '?')} {int(total)}GB ({pct}% used)")
    return {
        'serial_number': device.serial_number if usable_serial(device.serial_number) else '',
        'manufacturer': device.manufacturer,
        'model': device.model,
        'hostname': device.hostname,
        'ip_address': device.ip_address or None,
        'mac_address': device.mac_address,
        'os_name': device.os_type,
        'os_version': device.os_version,
        'cpu': cpu,
        'ram_gb': ram_gb or None,
        'storage': ', '.join(storage_parts) or raw.get('_norm_storage') or '',
    }


def apply_hardware(asset, device):
    """Update the asset's hardware fields from the RMM without overwriting a
    technician's edits.

    The RMM fills empty fields. It keeps a field up to date only while that
    field still holds the value this same device last wrote; once anyone
    edits it, or another RMM device wrote it first, it is left alone. Two
    RMMs managing one asset therefore never fight over a field.
    """
    tag = f'{device.connection_id}:{device.external_id}'
    cf = dict(asset.custom_fields) if isinstance(asset.custom_fields, dict) else {}
    sources = dict(cf.get('rmm_field_sources') or {})
    legacy = _legacy_owned(asset, device)
    changed = []
    for name, value in device_hardware(device).items():
        if value in (None, ''):
            continue
        current = getattr(asset, name)
        record = sources.get(name)
        empty = current in (None, '')
        ours = record is not None and record.get('src') == tag and str(current) == record.get('v')
        if empty or ours or (record is None and legacy):
            if str(current or '') != str(value):
                setattr(asset, name, value)
                changed.append(name)
            sources[name] = {'src': tag, 'v': str(value)}
    if sources != cf.get('rmm_field_sources'):
        cf['rmm_field_sources'] = sources
        asset.custom_fields = cf
        changed.append('custom_fields')
    if changed:
        asset.save(update_fields=changed + (['updated_at'] if hasattr(asset, 'updated_at') else []))
    return changed


def create_asset_from_device(device):
    from assets.models import Asset
    type_map = {'workstation': 'computer', 'laptop': 'computer', 'server': 'server',
                'virtual': 'server', 'cloud': 'server', 'network': 'network', 'mobile': 'mobile'}
    raw = device.raw_data or {}
    asset = Asset.objects.create(
        organization_id=device.organization_id,
        name=device.device_name or device.hostname or f'RMM device {device.external_id}',
        asset_type=type_map.get(device.device_type, 'other'),
        notes=raw.get('notes') or raw.get('description') or
        f'Created from {device.connection.get_provider_type_display()} device {device.external_id}.',
        custom_fields={
            'rmm_synced': True,
            'rmm_provider': device.connection.provider_type,
            'rmm_connection_id': device.connection_id,
            'rmm_external_id': device.external_id,
        },
    )
    apply_hardware(asset, device)
    return asset


def associate(device, *, auto_create=True, auto_match=True):
    """Apply `decide_asset` to the device. Returns the action taken."""
    from .models import RMMDevice
    decision = decide_asset(device, auto_create=auto_create)
    if decision.action == 'clear':
        device.linked_asset = None
        device.link_status = RMMDevice.LINK_REVIEW
        device.link_note = decision.note
        device.link_candidates = []
        device.save(update_fields=['linked_asset', 'link_status', 'link_note', 'link_candidates'])
        return 'review'
    if decision.action == 'keep':
        apply_hardware(decision.asset, device)
        if device.link_status not in (RMMDevice.LINK_AUTO, RMMDevice.LINK_CONFIRMED):
            device.link_status = RMMDevice.LINK_AUTO
            device.save(update_fields=['link_status'])
        return 'keep'
    if decision.action == 'review':
        device.link_status = RMMDevice.LINK_REVIEW
        device.link_note = decision.note
        device.link_candidates = decision.candidates
        # A suspected replacement keeps showing nothing until confirmed.
        device.linked_asset = None
        device.save(update_fields=['link_status', 'link_note', 'link_candidates', 'linked_asset'])
        return 'review'
    if decision.action == 'match' and auto_match:
        _link(device, decision.asset, RMMDevice.LINK_AUTO)
        apply_hardware(decision.asset, device)
        return 'match'
    if decision.action == 'create' and auto_create:
        asset = create_asset_from_device(device)
        _link(device, asset, RMMDevice.LINK_AUTO)
        return 'create'
    return 'none'


def _link(device, asset, status, note=''):
    device.linked_asset = asset
    device.link_status = status
    device.link_note = note
    device.link_candidates = []
    device.save(update_fields=['linked_asset', 'link_status', 'link_note', 'link_candidates'])


# ---------------------------------------------------------------------------
# Technician decisions
# ---------------------------------------------------------------------------

def _audit(user, device, description, **extra):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='update', organization=device.organization or device.connection.organization,
                 object_type='rmm_device', object_id=device.pk, object_repr=device.device_name,
                 description=description, extra_data=extra or None)


def reported_identity(device):
    """The customer the RMM reported for this device at the last sync."""
    return customer_identity({'client_id': device.client_id, 'client_name': device.client_name})


def devices_reporting(connection, identity):
    from .models import RMMDevice
    qs = RMMDevice.objects.filter(connection=connection)
    if identity.name_only:
        return [d for d in qs.filter(client_id='', client_name__iexact=identity.client_name)
                if d.client_name.casefold() == identity.client_name.casefold()]
    return list(qs.filter(client_id=identity.client_id))


@transaction.atomic
def assign_customer(device, org, user, *, map_all=False):
    """A technician settles the device's customer. With `map_all`, the RMM
    customer is mapped to `org` and every device it reports follows."""
    from .models import RMMDevice
    identity = reported_identity(device)
    targets = [device]
    if map_all and identity is not None:
        map_customer(device.connection, identity, org)
        targets = devices_reporting(device.connection, identity)
    for d in targets:
        key = identity.key if identity is not None else ''
        d.organization = org
        d.ownership_status = RMMDevice.OWNERSHIP_RESOLVED
        d.ownership_note = ''
        d.pending_organization = None
        d.customer_key = key
        d.confirmed_customer_key = key
        if d.linked_asset_id and d.linked_asset.organization_id != org.pk:
            d.linked_asset = None
            d.link_status = ''
            d.link_note = ''
        d.save()
        set_device_organization(d, org)
        if d.connection.map_to_assets or d.linked_asset_id:
            associate(d, auto_create=d.connection.map_to_assets, auto_match=d.connection.map_to_assets)
        _audit(user, d, f'Assigned RMM device {d.device_name} to {org.name}',
               customer_key=d.customer_key)
    return targets


@transaction.atomic
def link_asset(device, asset, user):
    from .models import RMMDevice
    if not device.is_exposed or asset.organization_id != device.organization_id:
        raise ValueError("That asset belongs to a different customer.")
    _link(device, asset, RMMDevice.LINK_CONFIRMED)
    apply_hardware(asset, device)
    _audit(user, device, f'Linked RMM device {device.device_name} to asset {asset.name}', asset_id=asset.pk)


@transaction.atomic
def create_linked_asset(device, user):
    from .models import RMMDevice
    if not device.is_exposed:
        raise ValueError("Settle the device's customer first.")
    asset = create_asset_from_device(device)
    _link(device, asset, RMMDevice.LINK_CONFIRMED)
    _audit(user, device, f'Created asset {asset.name} from RMM device {device.device_name}', asset_id=asset.pk)
    return asset


@transaction.atomic
def leave_unlinked(device, user):
    from .models import RMMDevice
    previous = device.linked_asset_id
    device.linked_asset = None
    device.link_status = RMMDevice.LINK_UNLINKED
    device.link_note = ''
    device.link_candidates = []
    device.save(update_fields=['linked_asset', 'link_status', 'link_note', 'link_candidates'])
    _audit(user, device, f'Left RMM device {device.device_name} unlinked', previous_asset_id=previous)


@transaction.atomic
def match_automatically(device, user):
    """Undo an explicit unlink: the next sync may match the device again."""
    device.link_status = ''
    device.link_note = ''
    device.link_candidates = []
    device.save(update_fields=['link_status', 'link_note', 'link_candidates'])
    _audit(user, device, f'Allowed automatic asset matching for RMM device {device.device_name}')


# ---------------------------------------------------------------------------
# What a technician sees
# ---------------------------------------------------------------------------

def exposed_devices(asset):
    """RMM devices that may be shown on this asset: same customer, settled."""
    from .models import RMMDevice
    if asset is None or not asset.pk:
        return RMMDevice.objects.none()
    return (asset.rmm_devices.filter(organization_id=asset.organization_id,
                                     ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
            .select_related('connection'))


def stale_after(connection):
    return max(timedelta(minutes=3 * (connection.sync_interval_minutes or 60)), timedelta(hours=2))


def device_status(device, now=None):
    """Status as the RMM last reported it, never older data dressed as current.

    Returns a dict with `state` (online, offline, stale, unknown), a short
    `label` and a `detail` sentence.
    """
    now = now or timezone.now()
    refreshed = device.data_refreshed_at
    if refreshed is None:
        return {'state': 'unknown', 'label': 'Unknown',
                'detail': 'This device has not been refreshed from the RMM yet.'}
    if now - refreshed > stale_after(device.connection):
        when = timezone.localtime(refreshed).strftime('%Y-%m-%d %H:%M')
        return {'state': 'stale', 'label': 'Stale',
                'detail': f'No fresh data from the RMM since {when}; the last reported status was '
                          f'{"online" if device.is_online else "offline"}.'}
    if device.is_online:
        return {'state': 'online', 'label': 'Online', 'detail': 'Online at the last RMM refresh.'}
    if device.last_seen:
        return {'state': 'offline', 'label': 'Offline',
                'detail': 'The RMM reports this device offline.'}
    return {'state': 'unknown', 'label': 'Unknown',
            'detail': "The RMM hasn't reported whether this device is online."}


def console_link(device):
    """Where "Open in <provider>" goes for this device, or '' for no link.

    'static' providers get the validated vendor URL itself. 'on_demand'
    providers (NinjaOne) get a ClientSt0r URL that asks the vendor for a
    short-lived link when clicked, so nothing is fetched while the page
    renders and no credential ever reaches the browser.
    """
    from django.urls import reverse
    from .providers.rmm import RMM_PROVIDER_REGISTRY
    from .providers.rmm.console import validated_console_url
    provider = RMM_PROVIDER_REGISTRY.get(device.connection.provider_type)
    mode = getattr(provider, 'console_link_mode', 'none') if provider else 'none'
    try:
        hosts = provider.console_hosts(device.connection) if provider else set()
        if mode == 'on_demand':
            return reverse('integrations:rmm_device_open', args=[device.pk]) if hosts else ''
        if mode == 'static':
            url = provider.device_console_url(device.connection, device)
            return validated_console_url(url, hosts) if url else ''
    except Exception:  # never let a link break the page
        logger.exception('Building the RMM console link failed for device %s', device.pk)
    return ''


def console_label(device):
    """The console button's text: "Open in <provider>" unless the adapter names it."""
    from .providers.rmm import RMM_PROVIDER_REGISTRY
    provider = RMM_PROVIDER_REGISTRY.get(device.connection.provider_type)
    return (getattr(provider, 'console_link_label', '')
            or f'Open in {device.connection.get_provider_type_display()}')


def summary(device, now=None):
    """Everything the asset and ticket pages show about one RMM device."""
    return {
        'device': device,
        'provider': device.connection.get_provider_type_display(),
        'connection': device.connection.name,
        'status': device_status(device, now),
        'console_url': console_link(device),
        'console_label': console_label(device),
    }


def summaries_for_asset(asset):
    now = timezone.now()
    return [summary(d, now) for d in exposed_devices(asset).order_by('-last_seen')]
