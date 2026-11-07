"""JSON shapes shared by the device page, the session API and diagrams."""
from __future__ import annotations

from . import connectors as C
from .models import CableTermination, DevicePort, PortVLAN

# Colour-blind-safe-ish palette for VLANs without a colour of their own.
VLAN_PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf',
                '#bcbd22', '#7f7f7f', '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173']


def vlan_color(v):
    if v is None:
        return None
    if v.color:
        return v.color
    return VLAN_PALETTE[v.vlan_id % len(VLAN_PALETTE)]


def vlan_json(v):
    if v is None:
        return None
    return {'id': v.pk, 'vid': v.vlan_id, 'name': v.name, 'color': vlan_color(v),
            'group': v.vlan_group.name if v.vlan_group_id else ''}


def port_queryset(device):
    return (device.ports.select_related('untagged_vlan__vlan_group', 'voice_vlan', 'lag', 'module__bay',
                                        'cable_termination__cable', 'updated_by', 'breakout_parent')
            .prefetch_related('tagged_memberships__vlan'))


def _peer_map(ports):
    """port id -> list of (far port) for documented cables, in two queries."""
    terms = {p.pk: p.cable_termination for p in ports if hasattr(p, 'cable_termination')}
    if not terms:
        return {}
    cable_ids = {t.cable_id for t in terms.values()}
    far = {}
    for t in CableTermination.objects.filter(cable_id__in=cable_ids).select_related('port__device__asset'):
        far.setdefault(t.cable_id, []).append(t)
    out = {}
    for pid, t in terms.items():
        out[pid] = [x.port for x in far.get(t.cable_id, []) if x.end != t.end]
    return out


def port_json(p, peers=None):
    term = getattr(p, 'cable_termination', None) if hasattr(p, 'cable_termination') else None
    cable = term.cable if term else None
    far = (peers or {}).get(p.pk, [])
    return {
        'id': p.pk, 'public_id': str(p.public_id), 'key': str(p.template_key) if p.template_key else '',
        'module': p.module_id, 'module_bay': p.module.bay.name if p.module_id else '',
        'name': p.name, 'label': p.label, 'class': p.component_class, 'class_label': p.get_component_class_display(),
        'type': p.type, 'connector': p.connector,
        'connector_label': C.CONNECTORS.get(p.connector, {}).get('label', p.connector or ''),
        'description': p.description, 'tech_label': p.tech_label, 'is_custom': p.is_custom,
        'populated': p.is_populated, 'mgmt_only': p.mgmt_only, 'positions': p.positions,
        'combo_group': p.combo_group, 'breakout_parent': p.breakout_parent_id, 'breakout_mode': p.breakout_mode,
        'speed_capability': p.speed_capability, 'configured_speed': p.configured_speed,
        'admin_state': p.admin_state, 'oper_state': p.oper_state, 'oper_source': p.oper_source,
        'oper_observed_at': p.oper_observed_at.isoformat() if p.oper_observed_at else None,
        'mode': p.mode, 'untagged_vlan': vlan_json(p.untagged_vlan), 'voice_vlan': vlan_json(p.voice_vlan),
        'tagged_vlans': sorted((vlan_json(m.vlan) for m in p.tagged_memberships.all()), key=lambda v: v['vid']),
        'lag': {'id': p.lag_id, 'name': p.lag.name} if p.lag_id else None,
        'poe_mode': p.poe_mode, 'poe_type': p.poe_type, 'poe_setting': p.poe_setting, 'poe_notes': p.poe_notes,
        'notes': p.notes, 'mac_address': p.mac_address,
        'vlan_capable': p.component_class == C.CLASS_INTERFACE,
        'passive': p.is_passive,
        'cable': ({'id': cable.pk, 'label': cable.label or f'#{cable.pk}', 'type': cable.cable_type,
                   'type_label': cable.get_cable_type_display(), 'color': cable.color, 'color_name': cable.color_name,
                   'length': str(cable.length.normalize()) if cable.length else '', 'length_unit': cable.length_unit,
                   'status': cable.status, 'label_a': cable.label_a, 'label_b': cable.label_b,
                   'end': term.end} if cable else None),
        'peers': [{'id': f.pk, 'device_id': f.device_id, 'device': f.device.asset.name, 'name': f.name,
                   'label': f.tech_label or f.label, 'passive': f.is_passive} for f in far],
        'updated_at': p.updated_at.isoformat() if p.updated_at else None,
        'updated_by': p.updated_by.get_username() if p.updated_by_id else '',
    }


def device_ports_json(device):
    ports = list(port_queryset(device))
    peers = _peer_map(ports)
    return [port_json(p, peers) for p in ports]


def device_summary(device):
    a = device.asset
    hm = device.hardware_model
    return {'id': device.pk, 'public_id': str(device.public_id), 'name': a.name, 'hostname': a.hostname,
            'model': str(hm), 'model_id': hm.pk, 'category': hm.category, 'status': device.status,
            'site': device.site.name if device.site_id else '', 'room': device.room}
