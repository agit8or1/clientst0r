"""
Phase 33.2 (v3.17.558) — turning neighbour and bridge-table data into topology.

Two ingest paths, both idempotent. A collector runs nightly and re-reports the
same adjacencies every time, so "seen again" has to move a timestamp rather than
write another row — otherwise a year of nightly scans buries the one link that
changed under three hundred and sixty-four identical ones.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from assets.models import Asset

from .models import NetworkLink, SwitchPortEntry, normalise_mac, valid_ipv4

logger = logging.getLogger(__name__)

MAX_LINKS_PER_UPLOAD = 5000
MAX_PORT_ENTRIES_PER_UPLOAD = 20000


def _resolve_asset(organization, *, mac='', name='', ip=''):
    """Find the asset a neighbour refers to, or None.

    MAC first for the same reason the Phase 32 importer prefers it: it names a
    device rather than a place. Hostname is last and case-insensitive, because
    LLDP reports a system name that may or may not match how anyone recorded it.
    """
    mac = normalise_mac(mac)
    if mac:
        found = Asset.objects.filter(
            organization=organization, mac_address__iexact=mac).first()
        if found is not None:
            return found

    if ip and valid_ipv4(ip):
        found = Asset.objects.filter(
            organization=organization, ip_address=ip).first()
        if found is not None:
            return found

    name = (name or '').strip()
    if name:
        found = Asset.objects.filter(
            organization=organization, hostname__iexact=name).first()
        if found is not None:
            return found
        found = Asset.objects.filter(
            organization=organization, name__iexact=name).first()
        if found is not None:
            return found

    return None


def ingest_links(site, neighbours):
    """Record LLDP/CDP adjacencies. Returns `{created, updated, skipped}`.

    A neighbour whose *local* device is unknown is skipped: without knowing
    which of our switches reported it, the edge has no anchor and would float
    unattached on any map.
    """
    now = timezone.now()
    counts = {'created': 0, 'updated': 0, 'skipped': 0}

    for raw in (neighbours or [])[:MAX_LINKS_PER_UPLOAD]:
        if not isinstance(raw, dict):
            counts['skipped'] += 1
            continue

        local = _resolve_asset(
            site.organization,
            mac=raw.get('local_mac') or '',
            name=raw.get('local_name') or '',
            ip=raw.get('local_ip') or '')
        if local is None:
            counts['skipped'] += 1
            continue

        remote_name = str(raw.get('remote_name') or '').strip()[:255]
        remote_port = str(raw.get('remote_port') or '').strip()[:120]
        remote_mac = normalise_mac(raw.get('remote_mac') or '')
        remote = _resolve_asset(
            site.organization, mac=remote_mac, name=remote_name,
            ip=raw.get('remote_ip') or '')

        source = str(raw.get('source') or 'lldp').lower()
        if source not in ('lldp', 'cdp', 'manual'):
            source = 'lldp'

        link, created = NetworkLink.objects.get_or_create(
            local_asset=local,
            local_port=str(raw.get('local_port') or '').strip()[:120],
            remote_name=remote_name,
            remote_port=remote_port,
            defaults={
                'organization': site.organization,
                'location': site.location,
                'site': site,
                'remote_asset': remote,
                'remote_mac': remote_mac,
                'remote_description': str(
                    raw.get('remote_description') or '').strip()[:255],
                'source': source,
                'last_seen_at': now,
            },
        )
        if created:
            counts['created'] += 1
            continue

        # Seen again. Move the timestamp, and fill in the far end if it has
        # since become something we know about — a neighbour swept last week is
        # an asset this week.
        fields = ['last_seen_at']
        link.last_seen_at = now
        if remote is not None and link.remote_asset_id is None:
            link.remote_asset = remote
            fields.append('remote_asset')
        if remote_mac and not link.remote_mac:
            link.remote_mac = remote_mac
            fields.append('remote_mac')
        link.save(update_fields=fields)
        counts['updated'] += 1

    return counts


def ingest_switch_ports(site, entries):
    """Record bridge-table entries. Returns `{created, updated, skipped}`."""
    now = timezone.now()
    counts = {'created': 0, 'updated': 0, 'skipped': 0}

    for raw in (entries or [])[:MAX_PORT_ENTRIES_PER_UPLOAD]:
        if not isinstance(raw, dict):
            counts['skipped'] += 1
            continue

        mac = normalise_mac(raw.get('mac') or raw.get('mac_address') or '')
        port = str(raw.get('port') or raw.get('port_name') or '').strip()[:120]
        if not mac or not port:
            counts['skipped'] += 1
            continue

        switch = _resolve_asset(
            site.organization,
            mac=raw.get('switch_mac') or '',
            name=raw.get('switch_name') or '',
            ip=raw.get('switch_ip') or '')
        if switch is None:
            counts['skipped'] += 1
            continue

        vlan = raw.get('vlan')
        try:
            vlan = int(vlan) if vlan not in (None, '') else None
            if vlan is not None and not (0 <= vlan <= 4094):
                vlan = None
        except (TypeError, ValueError):
            vlan = None

        ip = str(raw.get('ip') or '').strip()
        ip = ip if valid_ipv4(ip) else None

        # The device on the port, if we happen to know it. Left None rather
        # than guessed: a port entry naming the wrong device sends somebody to
        # the wrong socket, which is worse than sending them nowhere.
        device = _resolve_asset(site.organization, mac=mac, ip=ip or '')

        entry, created = SwitchPortEntry.objects.get_or_create(
            switch_asset=switch, port_name=port, vlan_id=vlan, mac_address=mac,
            defaults={
                'organization': site.organization,
                'location': site.location,
                'site': site,
                'device_asset': device,
                'ip_address': ip,
                'last_seen_at': now,
            },
        )
        if created:
            counts['created'] += 1
            continue

        fields = ['last_seen_at']
        entry.last_seen_at = now
        if device is not None and entry.device_asset_id is None:
            entry.device_asset = device
            fields.append('device_asset')
        if ip and entry.ip_address is None:
            entry.ip_address = ip
            fields.append('ip_address')
        entry.save(update_fields=fields)
        counts['updated'] += 1

    return counts


def topology_graph(organization, location=None, *, stale_after_days=30):
    """Nodes and edges for the network map.

    Shaped like the Phase 16 relationship graph so the same rendering ideas
    apply. Links not seen for `stale_after_days` are included but flagged
    rather than dropped: a cable that stopped being reported is information,
    and silently removing it makes a map that only ever agrees with itself.
    """
    links = NetworkLink.objects.filter(organization=organization)
    if location is not None:
        links = links.filter(location=location)
    links = links.select_related('local_asset', 'remote_asset')

    cutoff = timezone.now() - timezone.timedelta(days=stale_after_days)

    nodes = {}
    edges = []

    def _add_node(key, label, asset=None, resolved=True):
        if key not in nodes:
            nodes[key] = {
                'key': key,
                'label': label,
                'asset_id': asset.pk if asset is not None else None,
                'asset_type': getattr(asset, 'asset_type', '') if asset else '',
                'resolved': resolved,
            }
        return nodes[key]

    for link in links:
        local_key = f'asset:{link.local_asset_id}'
        _add_node(local_key, link.local_asset.name, link.local_asset)

        if link.remote_asset_id:
            remote_key = f'asset:{link.remote_asset_id}'
            _add_node(remote_key, link.remote_asset.name, link.remote_asset)
        else:
            # An unmanaged neighbour still belongs on the map — "there is
            # something on port 12 we do not manage" is worth seeing.
            remote_key = f'unknown:{link.remote_name or link.remote_mac or link.pk}'
            _add_node(remote_key, link.remote_label, None, resolved=False)

        edges.append({
            'source': local_key,
            'target': remote_key,
            # Labels as well as keys: the keys are for the graph, the labels
            # are what a person reads in the table beneath it.
            'source_label': link.local_asset.name,
            'target_label': link.remote_label,
            'local_port': link.local_port,
            'remote_port': link.remote_port,
            'source_protocol': link.source,
            'is_stale': link.last_seen_at < cutoff,
            'last_seen_at': link.last_seen_at,
        })

    return {'nodes': list(nodes.values()), 'edges': edges}
