"""
Network-controller devices → asset registry: the one shared implementation.

Both the scheduled path (`manage.py sync_network_assets`) and the manual path
(Integrations → UniFi → Import to Assets, and Sync Now when auto-import is on)
go through `import_unifi_assets()`. Before v3.17.660 they had separate copies:
the scheduled one typed every device as a wireless AP and put every site's
devices under the connection's own organization, ignoring the site → customer
mapping; the manual one honoured the mapping only for cloud connections.

This module owns:

* `classify_unifi_device()` — gateway/router, switch, AP, UPS, ... → asset type
* `resolve_unifi_sites()` — controller site → customer organization, with
  unmapped / ambiguous / invalid sites reported instead of guessed
* `import_devices()` — create / update with a stable dedup key
  (source + connection + device MAC or serial, scoped by organization),
  recorded in `NetworkAssetLink`
* `build_unifi_placement_report()` — read-only: assets earlier syncs put under
  the wrong customer, gave the wrong type, or created twice
* `apply_unifi_corrections()` — the separate, explicit, audited fix for
  selected report findings, logging before-values for every change
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import health

logger = logging.getLogger('integrations')

SOURCE_UNIFI = 'unifi'

# ---------------------------------------------------------------------------
# Device normalisation + classification
# ---------------------------------------------------------------------------

# Legacy controller API `type` codes.
_UNIFI_TYPE_CODES = {
    'uap': 'wireless_ap', 'ubb': 'wireless_ap',
    'usw': 'switch',
    'ugw': 'router', 'usg': 'router', 'udm': 'router', 'uxg': 'router', 'udr': 'router',
    'ucg': 'router', 'ux': 'router',
    'uph': 'phone',
}

# Cloud Site Manager / integration API product types, compared with
# separators removed and lower-cased ('NETWORK_SWITCH' → 'networkswitch').
_UNIFI_PRODUCT_TYPES = [
    ('accesspoint', 'wireless_ap'), ('wireless', 'wireless_ap'), ('uap', 'wireless_ap'),
    ('networkswitch', 'switch'), ('switching', 'switch'), ('switch', 'switch'), ('usw', 'switch'),
    ('securitygateway', 'router'), ('cloudgateway', 'router'), ('dreammachine', 'router'),
    ('dreamrouter', 'router'), ('dreamwall', 'router'), ('gateway', 'router'),
    ('routing', 'router'), ('router', 'router'), ('ugw', 'router'), ('udm', 'router'),
    ('powerunit', 'ups'), ('ups', 'ups'),
    ('firewall', 'firewall'),
]

# Model / shortname prefixes (lower-cased, spaces → '-'): 'UDM Pro' → 'udm-pro'.
_UNIFI_MODEL_PREFIXES = [
    ('uap', 'wireless_ap'), ('u6', 'wireless_ap'), ('u7', 'wireless_ap'), ('u2', 'wireless_ap'),
    ('uaf', 'wireless_ap'), ('ubb', 'wireless_ap'), ('ual', 'wireless_ap'), ('e7', 'wireless_ap'),
    ('usw', 'switch'), ('usl', 'switch'), ('us8', 'switch'), ('us16', 'switch'), ('us24', 'switch'),
    ('us48', 'switch'), ('usf', 'switch'), ('usmini', 'switch'), ('ecs', 'switch'),
    ('udm', 'router'), ('udr', 'router'), ('udw', 'router'), ('uxg', 'router'), ('ugw', 'router'),
    ('usg', 'router'), ('ucg', 'router'), ('ux', 'router'), ('efg', 'router'),
    ('ups', 'ups'), ('usp-pdu', 'pdu'),
]


def normalize_mac(raw) -> str:
    mac = (str(raw or '')).strip().lower().replace('-', ':').replace('.', '')
    hexonly = mac.replace(':', '')
    if len(hexonly) == 12 and re.fullmatch(r'[0-9a-f]{12}', hexonly):
        return ':'.join(hexonly[i:i + 2] for i in range(0, 12, 2))
    return mac[:17]


def device_key(mac: str, serial: str) -> str:
    """Stable per-device key: MAC when known, else serial."""
    mac = normalize_mac(mac)
    if mac:
        return f'mac:{mac}'
    serial = (serial or '').strip()
    if serial:
        return f'serial:{serial.lower()}'
    return ''


def classify_unifi_device(raw: dict) -> str:
    """Asset type for a UniFi device dict from any controller API."""
    code = str(raw.get('type') or '').strip().lower()
    if code in _UNIFI_TYPE_CODES:
        return _UNIFI_TYPE_CODES[code]

    for key in ('productType', 'type', 'deviceType'):
        pt = re.sub(r'[\s_\-]', '', str(raw.get(key) or '').lower())
        if not pt:
            continue
        for keyword, atype in _UNIFI_PRODUCT_TYPES:
            if pt.startswith(keyword):
                return atype

    features = raw.get('features') or []
    if isinstance(features, dict):
        features = [k for k, v in features.items() if v]
    feats = {re.sub(r'[\s_\-]', '', str(f).lower()) for f in features if f}
    if feats & {'gateway', 'routing', 'securitygateway'}:
        return 'router'
    if feats & {'accesspoint', 'wireless'}:
        return 'wireless_ap'
    if feats & {'switching', 'switch'}:
        return 'switch'

    for key in ('model', 'shortname', 'modelName'):
        model = re.sub(r'\s+', '-', str(raw.get(key) or '').strip().lower())
        if not model:
            continue
        for prefix, atype in _UNIFI_MODEL_PREFIXES:
            if model.startswith(prefix):
                return atype
    return 'other'


def _clean_ip(raw) -> str:
    from django.core.validators import validate_ipv46_address
    try:
        validate_ipv46_address(str(raw))
        return str(raw)
    except Exception:
        return ''


def normalize_unifi_device(raw: dict) -> dict:
    mac = normalize_mac(raw.get('mac') or raw.get('macAddress') or '')
    serial = str(raw.get('serial') or raw.get('serialNumber') or raw.get('serialno') or '').strip()
    return {
        'name': raw.get('name') or raw.get('hostname') or mac or 'Unknown Device',
        'mac': mac,
        'ip': _clean_ip(raw.get('ip') or raw.get('ipAddress') or ''),
        'model': raw.get('model') or raw.get('shortname') or '',
        'asset_type': classify_unifi_device(raw),
        'manufacturer': 'Ubiquiti',
        'serial_number': serial,
        'os_version': raw.get('version') or raw.get('firmwareVersion') or '',
        'hostname': raw.get('hostname') or '',
    }


# ---------------------------------------------------------------------------
# Site → customer mapping
# ---------------------------------------------------------------------------

MAPPED = 'mapped'
DEFAULT = 'default'      # single-site controller with no mapping at all → connection's org
UNMAPPED = 'unmapped'
AMBIGUOUS = 'ambiguous'
INVALID = 'invalid'


@dataclass
class SiteResolution:
    site_id: str
    site_name: str
    map_key: str           # key the UI should save this site's mapping under
    status: str
    organization: Optional[object] = None
    reason: str = ''
    action: str = ''
    devices: list = field(default_factory=list)

    @property
    def importable(self) -> bool:
        return self.status in (MAPPED, DEFAULT) and self.organization is not None

    def as_dict(self) -> dict:
        return {
            'site_id': self.site_id, 'site_name': self.site_name, 'map_key': self.map_key,
            'status': self.status, 'reason': self.reason, 'action': self.action,
            'organization_id': getattr(self.organization, 'pk', None),
            'organization_name': getattr(self.organization, 'name', ''),
            'device_count': len(self.devices),
        }


def _org_ids(value) -> list:
    if value in (None, '', [], {}):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            out.append(None)  # unparseable → reported as invalid
    return out


def _mapping_hint(connection, site_name) -> str:
    return (f'Map site "{site_name}" to exactly one customer in Integrations → UniFi '
            f'"{connection.name}" → Site → customer mapping.')


def resolve_unifi_sites(connection, sites: list) -> list:
    """Resolve each controller site to one customer organization, or say why not."""
    from core.models import Organization

    site_map = connection.site_org_map or {}
    names = Counter((s.get('name') or '') for s in sites)
    raw = []
    wanted_ids = set()
    for s in sites:
        sid = str(s.get('id') or '')
        name = s.get('name') or sid or 'default'
        ids = []
        by_id = bool(sid) and sid in site_map
        if by_id:
            ids += _org_ids(site_map.get(sid))
        if name in site_map and name != sid:
            if names[s.get('name') or ''] > 1:
                # A name key cannot tell same-named sites apart; an id key can.
                if not by_id:
                    raw.append((s, sid, name, None, 'shared_name'))
                    continue
            else:
                # Both an id key and a name key: they must agree (else ambiguous).
                ids += _org_ids(site_map.get(name))
        uniq = sorted({i for i in ids if i is not None})
        if None in ids:
            raw.append((s, sid, name, None, 'bad_value'))
            continue
        wanted_ids.update(uniq)
        raw.append((s, sid, name, uniq, ''))

    orgs = {o.pk: o for o in Organization.objects.filter(pk__in=wanted_ids)}
    results = []
    for s, sid, name, ids, flag in raw:
        devices = s.get('devices') or []
        key = sid or name
        if flag == 'shared_name':
            results.append(SiteResolution(
                sid, name, key, AMBIGUOUS, None,
                reason=f'{names[s.get("name") or ""]} controller sites are named "{name}" and the mapping '
                       'is by name, so it cannot tell them apart.',
                action=_mapping_hint(connection, name) + ' Re-save the mapping so it is stored per site id.',
                devices=devices))
            continue
        if flag == 'bad_value':
            results.append(SiteResolution(
                sid, name, key, INVALID, None,
                reason=f'The mapping for site "{name}" is not a customer id.',
                action=_mapping_hint(connection, name), devices=devices))
            continue
        if len(ids) > 1:
            customer_names = ', '.join(orgs[i].name if i in orgs else f'#{i}' for i in ids)
            results.append(SiteResolution(
                sid, name, key, AMBIGUOUS, None,
                reason=f'Site "{name}" is mapped to {len(ids)} customers ({customer_names}).',
                action=_mapping_hint(connection, name), devices=devices))
            continue
        if not ids:
            if not site_map and len(sites) == 1 and connection.organization_id:
                results.append(SiteResolution(
                    sid, name, key, DEFAULT, connection.organization,
                    reason='Only site on this controller and no mapping set: imported into the '
                           "connection's own organization.",
                    devices=devices))
            else:
                results.append(SiteResolution(
                    sid, name, key, UNMAPPED, None,
                    reason=f'Site "{name}" is not mapped to a customer.',
                    action=_mapping_hint(connection, name), devices=devices))
            continue
        org = orgs.get(ids[0])
        if org is None or not getattr(org, 'is_active', True):
            results.append(SiteResolution(
                sid, name, key, INVALID, None,
                reason=f'Site "{name}" is mapped to customer #{ids[0]}, which no longer exists or is inactive.',
                action=_mapping_hint(connection, name), devices=devices))
            continue
        results.append(SiteResolution(sid, name, key, MAPPED, org, devices=devices))
    return results


# ---------------------------------------------------------------------------
# Import (shared by every network controller)
# ---------------------------------------------------------------------------

def _empty_counts():
    return {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0}


def import_devices(org, devices: list, *, source: str = '', connection=None,
                   site_id: str = '', site_name: str = '', issues: Optional[list] = None) -> dict:
    """Create or update assets in `org` for normalised `devices`.

    Dedup order: this connection's link for the device key → an asset in `org`
    with the same MAC → same serial → create. Existing assets keep their
    asset type and customer; only the placement-report correction changes
    those. A device whose link points at an asset under a different customer
    is skipped and reported, never moved silently.
    """
    from assets.models import Asset
    from .models import NetworkAssetLink

    counts = _empty_counts()
    issues = issues if issues is not None else []
    conn_id = getattr(connection, 'pk', None)
    for d in devices:
        try:
            mac = normalize_mac(d.get('mac') or '')
            serial = (d.get('serial_number') or '').strip()
            key = device_key(mac, serial)
            if not key:
                counts['skipped'] += 1
                continue
            name = (d.get('name') or '').strip() or mac or serial or 'Unknown Device'
            fields = {
                'name': name,
                'manufacturer': d.get('manufacturer') or '',
                'model': d.get('model') or '',
                'serial_number': serial,
                'mac_address': mac,
                'os_version': d.get('os_version') or '',
                'hostname': (d.get('hostname') or '').strip(),
                'ip_address': _clean_ip(d.get('ip') or '') or None,
            }

            with transaction.atomic():
                link = None
                if source and conn_id:
                    link = (NetworkAssetLink.objects.select_related('asset')
                            .filter(source=source, connection_id=conn_id, device_key=key).first())
                asset = link.asset if link else None
                if asset is not None and asset.organization_id != org.pk:
                    counts['skipped'] += 1
                    issues.append(health.issue(
                        f'"{name}" is linked to an asset under another customer; the site now maps '
                        f'to {org.name}. Not moved automatically.',
                        customer=org.name, site=site_name, kind='placement',
                        action='Review it in the placement report (UniFi connection → Placement report).'))
                    continue
                if asset is None:
                    match = Q(pk__in=[])
                    if mac:
                        match |= Q(mac_address__iexact=mac)
                    if serial:
                        match |= Q(serial_number__iexact=serial)
                    asset = Asset.objects.filter(organization=org).filter(match).order_by('pk').first()

                if asset is not None:
                    changed = False
                    for k, v in fields.items():
                        if v and getattr(asset, k, '') != v:
                            setattr(asset, k, v)
                            changed = True
                    if asset.asset_type in ('', 'other') and d.get('asset_type') not in ('', None, 'other'):
                        # Unclassified before: filling in a type is not a correction.
                        asset.asset_type = d['asset_type']
                        changed = True
                    if changed:
                        asset.save()
                        counts['updated'] += 1
                    else:
                        counts['skipped'] += 1
                else:
                    asset = Asset.objects.create(
                        organization=org, asset_type=d.get('asset_type') or 'other',
                        **{k: v for k, v in fields.items() if v})
                    counts['created'] += 1

                if source and conn_id:
                    NetworkAssetLink.objects.update_or_create(
                        source=source, connection_id=conn_id, device_key=key,
                        defaults={'asset': asset, 'organization': org,
                                  'site_id': site_id or '', 'site_name': site_name or ''})
        except Exception as exc:
            counts['failed'] += 1
            issues.append(health.issue(
                f'Could not import "{d.get("name") or d.get("mac") or "device"}": '
                f'{health.redact(exc)}', customer=getattr(org, 'name', ''), site=site_name,
                kind='device'))
            logger.exception('network asset import failed for %s', d.get('mac'))
    return counts


def import_unifi_assets(connection, data: Optional[dict] = None, *, site_filter: str = '') -> dict:
    """Import a UniFi connection's devices into the mapped customers.

    Returns {'created','updated','skipped','failed','sites','issues','status',
    'skipped_sites'} where `sites` is the per-site resolution and
    `skipped_sites` the number of sites left out because their mapping needs
    correcting.
    """
    data = data if data is not None else (connection.cached_data or {})
    resolutions = resolve_unifi_sites(connection, data.get('sites', []))
    if site_filter:
        resolutions = [r for r in resolutions
                       if r.site_name == site_filter or r.site_id == site_filter]

    totals = _empty_counts()
    issues = []
    skipped_sites = 0
    for res in resolutions:
        if not res.importable:
            skipped_sites += 1
            totals['skipped'] += len(res.devices)
            issues.append(health.issue(
                f'{res.reason} {len(res.devices)} device(s) skipped.',
                site=res.site_name, action=res.action, kind=res.status))
            continue
        normalized = [normalize_unifi_device(d) for d in res.devices]
        counts = import_devices(res.organization, normalized, source=SOURCE_UNIFI,
                                connection=connection, site_id=res.site_id,
                                site_name=res.site_name, issues=issues)
        for k in totals:
            totals[k] += counts[k]

    status = health.STATUS_SUCCESS
    if skipped_sites or totals['failed'] or any(i.get('kind') == 'placement' for i in issues):
        status = health.STATUS_PARTIAL
    return {**totals, 'sites': [r.as_dict() for r in resolutions], 'issues': issues,
            'status': status, 'skipped_sites': skipped_sites}


def record_unifi_import(connection, result: dict, *, error: str = ''):
    """Write the import outcome to the connection's standard health."""
    return health.record_sync(
        connection, 'unifi', status=result.get('status', health.STATUS_SUCCESS),
        created=result.get('created', 0), updated=result.get('updated', 0),
        skipped=result.get('skipped', 0), failed=result.get('failed', 0),
        error=error, issues=result.get('issues', []))


def summary_message(result: dict) -> str:
    msg = (f"{result['created']} created, {result['updated']} updated, "
           f"{result['skipped']} unchanged/skipped, {result['failed']} failed")
    if result.get('skipped_sites'):
        msg += (f"; {result['skipped_sites']} site(s) skipped because their customer mapping "
                "needs correcting (see Site → customer mapping)")
    return msg


def get_unifi_provider(connection):
    from integrations.models import UnifiConnection
    from integrations.providers.unifi import UnifiProvider, UnifiCloudProvider
    creds = connection.get_credentials()
    if getattr(connection, 'mode', 'self_hosted') == UnifiConnection.MODE_CLOUD:
        return UnifiCloudProvider(api_key=creds.get('api_key', ''))
    return UnifiProvider(connection.host, creds.get('api_key', ''), connection.verify_ssl,
                         username=creds.get('username', ''), password=creds.get('password', ''))


def sync_unifi_connection(connection, *, import_assets: bool = True) -> dict:
    """Fetch from the controller, cache it, and (optionally) import assets.

    Used by the scheduled command. Records standard health either way and
    re-raises nothing: the result's 'status' says what happened.
    """
    now = timezone.now()
    try:
        data = get_unifi_provider(connection).sync()
    except Exception as exc:
        err = health.redact_for(connection, exc)
        health.record_sync(connection, 'unifi', status=health.STATUS_ERROR, error=err, when=now)
        return {**_empty_counts(), 'status': health.STATUS_ERROR, 'error': err, 'sites': [],
                'issues': [], 'skipped_sites': 0}
    connection.cached_data = data
    connection.save(update_fields=['cached_data'])
    if not import_assets:
        health.record_sync(connection, 'unifi', status=health.STATUS_SUCCESS, when=now)
        return {**_empty_counts(), 'status': health.STATUS_SUCCESS, 'sites': [], 'issues': [],
                'skipped_sites': 0, 'error': ''}
    result = import_unifi_assets(connection, data)
    connection.last_asset_sync_at = now
    connection.save(update_fields=['last_asset_sync_at'])
    record_unifi_import(connection, result)
    result['error'] = ''
    return result


# ---------------------------------------------------------------------------
# Placement report (read-only) + corrections (explicit, audited)
# ---------------------------------------------------------------------------

FIX_MOVE = 'move'
FIX_RETYPE = 'retype'
FIX_REMOVE_DUPLICATE = 'remove_duplicate'


def build_unifi_placement_report(connection, data: Optional[dict] = None) -> dict:
    """Find assets earlier syncs misplaced, misclassified or duplicated.

    Read-only. Compares the controller's last cached data with the asset
    registry of the connection's organization and every customer a site maps
    to. Each finding carries a stable id the correction action accepts.
    """
    from assets.models import Asset
    from .models import NetworkAssetLink

    data = data if data is not None else (connection.cached_data or {})
    resolutions = resolve_unifi_sites(connection, data.get('sites', []))
    scope = {connection.organization_id} | {r.organization.pk for r in resolutions if r.importable}
    links = NetworkAssetLink.objects.filter(source=SOURCE_UNIFI, connection_id=connection.pk)
    # Customers this controller imported into before (e.g. a site later re-mapped).
    scope |= set(links.values_list('organization_id', flat=True))
    scope.discard(None)
    linked = set(links.values_list('asset_id', flat=True))

    findings = []
    seen = set()

    def _add(fid, **kw):
        if fid in seen:
            return
        seen.add(fid)
        findings.append({'id': fid, **kw})

    for res in resolutions:
        if not res.importable:
            continue
        expected = res.organization
        for raw in res.devices:
            d = normalize_unifi_device(raw)
            if not device_key(d['mac'], d['serial_number']):
                continue
            match = Q(pk__in=[])
            if d['mac']:
                match |= Q(mac_address__iexact=d['mac'])
            if d['serial_number']:
                match |= Q(serial_number__iexact=d['serial_number'])
            matches = list(Asset.objects.filter(organization_id__in=scope).filter(match)
                           .select_related('organization').order_by('pk'))
            in_place = [a for a in matches if a.organization_id == expected.pk]
            # Keep the linked copy if there is one, else the oldest.
            in_place.sort(key=lambda a: (a.pk not in linked, a.pk))
            keeper = in_place[0] if in_place else None
            base = {'device_name': d['name'], 'mac': d['mac'], 'serial': d['serial_number'],
                    'site_name': res.site_name, 'expected_org_id': expected.pk,
                    'expected_org_name': expected.name, 'expected_type': d['asset_type']}

            for a in matches:
                if a.organization_id == expected.pk:
                    continue
                if keeper is None:
                    _add(f'{FIX_MOVE}:{a.pk}:{expected.pk}', problem='misplaced', fix=FIX_MOVE,
                         asset_id=a.pk, asset_name=a.name, current_org_name=a.organization.name,
                         current_org_id=a.organization_id, current_type=a.asset_type,
                         detail=f'Under {a.organization.name}; site "{res.site_name}" maps to {expected.name}.',
                         **base)
                    keeper = a  # once moved this is the copy that stays
                else:
                    _add(f'{FIX_REMOVE_DUPLICATE}:{a.pk}:{keeper.pk}', problem='misplaced duplicate',
                         fix=FIX_REMOVE_DUPLICATE, asset_id=a.pk, asset_name=a.name,
                         current_org_name=a.organization.name, current_org_id=a.organization_id,
                         current_type=a.asset_type, keep_asset_id=keeper.pk,
                         detail=f'Copy under {a.organization.name}; {expected.name} already has '
                                f'asset #{keeper.pk} for this device.', **base)
            for a in in_place[1:]:
                _add(f'{FIX_REMOVE_DUPLICATE}:{a.pk}:{keeper.pk}', problem='duplicate',
                     fix=FIX_REMOVE_DUPLICATE, asset_id=a.pk, asset_name=a.name,
                     current_org_name=a.organization.name, current_org_id=a.organization_id,
                     current_type=a.asset_type, keep_asset_id=keeper.pk,
                     detail=f'Second asset for the same device; asset #{keeper.pk} is kept.', **base)
            if keeper is not None and d['asset_type'] != 'other' and keeper.asset_type != d['asset_type']:
                _add(f'{FIX_RETYPE}:{keeper.pk}:{d["asset_type"]}', problem='misclassified',
                     fix=FIX_RETYPE, asset_id=keeper.pk, asset_name=keeper.name,
                     current_org_name=keeper.organization.name, current_org_id=keeper.organization_id,
                     current_type=keeper.asset_type,
                     detail=f'Recorded as "{keeper.asset_type}"; the controller reports a '
                            f'"{d["asset_type"]}".', **base)

    return {
        'findings': findings,
        'sites': [r.as_dict() for r in resolutions],
        'sites_needing_mapping': [r.as_dict() for r in resolutions if not r.importable],
        'generated_at': timezone.now(),
        'data_synced_at': connection.last_sync_at,
    }


def _asset_snapshot(asset) -> dict:
    from django.forms.models import model_to_dict
    snap = {}
    for k, v in model_to_dict(asset).items():
        if k in ('photo',):
            v = str(v or '')
        elif hasattr(v, 'pk'):
            v = v.pk
        elif isinstance(v, (list, tuple)):
            v = [getattr(x, 'pk', x) for x in v]
        elif not isinstance(v, (str, int, float, bool, type(None), dict)):
            v = str(v)
        snap[k] = v
    snap['id'] = asset.pk
    snap['organization_name'] = asset.organization.name
    return snap


def apply_unifi_corrections(connection, finding_ids, *, user, request=None) -> dict:
    """Apply selected placement-report findings. Every change is audit-logged
    with the asset's before-values; nothing outside the selection is touched.
    The caller is responsible for the staff-admin permission check.
    """
    from assets.models import Asset
    from audit.models import AuditLog
    from core.models import Organization
    from .models import NetworkAssetLink

    report = build_unifi_placement_report(connection)
    by_id = {f['id']: f for f in report['findings']}
    selected = [by_id[i] for i in dict.fromkeys(finding_ids) if i in by_id]
    stale = [i for i in finding_ids if i not in by_id]
    order = {FIX_RETYPE: 0, FIX_MOVE: 1, FIX_REMOVE_DUPLICATE: 2}
    selected.sort(key=lambda f: order[f['fix']])

    ip, path, ua = None, '', ''
    if request is not None:
        ip = request.META.get('REMOTE_ADDR') or None
        path = request.path
        ua = request.META.get('HTTP_USER_AGENT', '')[:500]

    applied, failed = [], []
    removed = set()
    for f in selected:
        try:
            with transaction.atomic():
                asset = Asset.objects.select_for_update().select_related('organization').get(pk=f['asset_id'])
                if asset.pk in removed:
                    continue
                before = _asset_snapshot(asset)
                old_org = asset.organization
                extra = {'correction': f['fix'], 'finding': f['id'], 'source': 'unifi',
                         'connection_id': connection.pk, 'connection_name': connection.name,
                         'before': before}
                if f['fix'] == FIX_RETYPE:
                    asset.asset_type = f['expected_type']
                    asset.save(update_fields=['asset_type', 'updated_at'])
                    extra['after'] = {'asset_type': asset.asset_type}
                    desc = (f'UniFi placement correction: type {before["asset_type"]} → '
                            f'{asset.asset_type} for "{asset.name}"')
                    orgs_to_log = [old_org]
                elif f['fix'] == FIX_MOVE:
                    target = Organization.objects.get(pk=f['expected_org_id'])
                    # Tags and the primary contact belong to the old customer.
                    asset.organization = target
                    asset.primary_contact = None
                    asset.save()
                    asset.tags.clear()
                    NetworkAssetLink.objects.filter(asset=asset).update(organization=target)
                    extra['after'] = {'organization': target.pk, 'organization_name': target.name,
                                      'primary_contact': None, 'tags': []}
                    desc = (f'UniFi placement correction: moved "{asset.name}" from '
                            f'{old_org.name} to {target.name}')
                    orgs_to_log = [old_org, target]
                else:
                    keep = Asset.objects.get(pk=f['keep_asset_id'])
                    NetworkAssetLink.objects.filter(asset=asset).update(asset=keep, organization=keep.organization)
                    extra['after'] = {'deleted': True, 'kept_asset_id': keep.pk}
                    desc = (f'UniFi placement correction: removed duplicate asset #{asset.pk} '
                            f'"{asset.name}" (kept #{keep.pk})')
                    asset_pk = asset.pk
                    asset.delete()
                    removed.add(asset_pk)
                    orgs_to_log = [old_org]
                for org in orgs_to_log:
                    AuditLog.log(
                        user=user, action='delete' if f['fix'] == FIX_REMOVE_DUPLICATE else 'update',
                        organization=org, object_type='asset', object_id=f['asset_id'],
                        object_repr=before.get('name', '')[:255], description=desc,
                        ip_address=ip, user_agent=ua, path=path, extra_data=extra)
                applied.append(f['id'])
        except Exception as exc:
            logger.exception('UniFi correction %s failed', f['id'])
            failed.append({'id': f['id'], 'error': health.redact(exc)})
    return {'applied': applied, 'failed': failed, 'stale': stale}


# ---------------------------------------------------------------------------
# Single-customer controllers (Omada, Grandstream)
# ---------------------------------------------------------------------------

def import_flat_devices(connection, kind: str, data: dict) -> dict:
    """Import every site's devices into the connection's own organization."""
    totals = _empty_counts()
    issues = []
    for s in data.get('sites', []):
        counts = import_devices(connection.organization, s.get('devices', []), source=kind,
                                connection=connection, site_id=str(s.get('id') or ''),
                                site_name=s.get('name') or '', issues=issues)
        for k in totals:
            totals[k] += counts[k]
    status = health.STATUS_PARTIAL if totals['failed'] else health.STATUS_SUCCESS
    return {**totals, 'issues': issues, 'status': status, 'skipped_sites': 0, 'sites': []}


def sync_flat_connection(connection, kind: str, provider, *, import_assets: bool) -> dict:
    """Fetch, cache, optionally import, and record health. Never raises."""
    now = timezone.now()
    try:
        data = provider.sync()
    except Exception as exc:
        err = health.redact_for(connection, exc)
        health.record_sync(connection, kind, status=health.STATUS_ERROR, error=err, when=now)
        return {**_empty_counts(), 'status': health.STATUS_ERROR, 'error': err, 'issues': [],
                'skipped_sites': 0, 'sites': [], 'site_count': 0}
    connection.cached_data = data
    fields = ['cached_data']
    result = {**_empty_counts(), 'status': health.STATUS_SUCCESS, 'issues': [], 'skipped_sites': 0,
              'sites': []}
    if import_assets:
        result = import_flat_devices(connection, kind, data)
        connection.last_asset_sync_at = now
        fields.append('last_asset_sync_at')
    connection.save(update_fields=fields)
    health.record_sync(connection, kind, status=result['status'], created=result['created'],
                       updated=result['updated'], skipped=result['skipped'], failed=result['failed'],
                       issues=result['issues'], when=now)
    result['error'] = ''
    result['site_count'] = len(data.get('sites', []))
    return result
