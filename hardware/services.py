"""
Inventory operations. Views and the API call these; they hold the rules.

Every function that writes takes the acting user and records a
``HardwareChange`` row, and every function that accepts a record from a
request re-checks that it belongs to the organization it is operating in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from . import connectors as C
from .models import (
    Cable, CableTermination, ComponentTemplate, DeviceInventoryItem, DevicePort, HardwareChange,
    HardwareDevice, HardwareModel, InstalledModule, LinkAggregationGroup, LogicalInterface, ModuleBay,
    PortMapping, PortVLAN, WirelessRadio,
)

PORT_CONFIG_FIELDS = ('description', 'tech_label', 'configured_speed', 'admin_state', 'mode', 'untagged_vlan',
                      'voice_vlan', 'lag', 'poe_setting', 'poe_notes', 'notes', 'mac_address', 'is_populated',
                      'breakout_mode')
VLAN_CLASSES = {C.CLASS_INTERFACE}


def record(user, action, obj, changes=None, device=None, organization=None, hardware_model=None):
    HardwareChange.objects.create(
        organization=organization or getattr(obj, 'organization', None), device=device,
        hardware_model=hardware_model, object_type=type(obj).__name__.lower(), object_id=obj.pk,
        object_repr=str(obj)[:200], action=action, changes=changes or {}, user=user)


def _fmt(v):
    if v is None:
        return None
    if hasattr(v, 'pk'):
        return str(v)
    return v if isinstance(v, (int, float, bool)) else str(v)


# --------------------------------------------------------------------------- instantiation

def _module_token(name: str, bay: ModuleBay | None):
    if bay is None or '{module}' not in name:
        return name
    return name.replace('{module}', bay.position or re.sub(r'\D', '', bay.name) or bay.name)


def _ports_from_templates(device, templates, module=None, bay=None):
    """Create DevicePort/ModuleBay/... rows for `templates`. Returns created ports by template id."""
    org = device.organization
    ports, by_tpl = [], {}
    bays, logical, radios, items = [], [], [], []
    for t in templates:
        name = _module_token(t.name, bay)
        if t.component_class in dict(C.PHYSICAL_PORT_CLASSES):
            p = DevicePort(
                organization=org, device=device, module=module, template_key=t.key,
                component_class=t.component_class, name=name, label=_module_token(t.label, bay), type=t.type,
                connector=t.connector, description='', mgmt_only=t.mgmt_only, positions=t.positions,
                combo_group=t.combo_group, speed_capability=C.speed_capability(t.component_class, t.type),
                poe_mode=t.poe_mode, poe_type=t.poe_type, maximum_draw=t.maximum_draw,
                allocated_draw=t.allocated_draw, feed_leg=t.feed_leg, color=t.color, sort_order=t.sort_order)
            ports.append(p)
            by_tpl[t.pk] = p
        elif t.component_class in (C.CLASS_MODULE_BAY, C.CLASS_DEVICE_BAY):
            bays.append(ModuleBay(organization=org, device=device, parent_module=module, template_key=t.key,
                                  bay_kind='device' if t.component_class == C.CLASS_DEVICE_BAY else 'module',
                                  name=name, label=t.label, position=_module_token(t.bay_position, bay),
                                  description=t.description, sort_order=t.sort_order))
        elif t.component_class == C.CLASS_LOGICAL:
            kind = {'lag': 'lag', 'bridge': 'bridge'}.get(t.type, 'virtual')
            logical.append(LogicalInterface(organization=org, device=device, template_key=t.key, name=name,
                                            kind=kind, description=t.description))
        elif t.component_class == C.CLASS_WIRELESS:
            radios.append(WirelessRadio(organization=org, device=device, template_key=t.key, name=name,
                                        standard=t.type, rf_role=t.rf_role, description=t.description))
        elif t.component_class == C.CLASS_INVENTORY_ITEM:
            items.append(DeviceInventoryItem(organization=org, device=device, template_key=t.key, name=name,
                                             label=t.label, manufacturer=t.item_manufacturer, part_id=t.part_id,
                                             description=t.description))
    DevicePort.objects.bulk_create(ports)
    ModuleBay.objects.bulk_create(bays)
    LogicalInterface.objects.bulk_create(logical)
    WirelessRadio.objects.bulk_create(radios)
    DeviceInventoryItem.objects.bulk_create(items)
    # Outlets fed by an inlet
    tpl_by_name = {t.name: t for t in templates if t.component_class == C.CLASS_POWER_PORT}
    for t in templates:
        if t.component_class == C.CLASS_POWER_OUTLET and t.power_port_name in tpl_by_name:
            outlet, inlet = by_tpl.get(t.pk), by_tpl.get(tpl_by_name[t.power_port_name].pk)
            if outlet and inlet:
                DevicePort.objects.filter(pk=outlet.pk).update(power_port=inlet)
    return by_tpl


def _mappings_from_templates(device, hm, by_tpl):
    rows = []
    for m in hm.port_mappings.all():
        f, r = by_tpl.get(m.front_port_id), by_tpl.get(m.rear_port_id)
        if f and r:
            rows.append(PortMapping(organization=device.organization, device=device, front_port=f,
                                    front_position=m.front_position, rear_port=r, rear_position=m.rear_position))
    PortMapping.objects.bulk_create(rows)


@transaction.atomic
def create_device(organization, hardware_model: HardwareModel, name, user=None, **fields) -> HardwareDevice:
    """Asset + HardwareDevice + every component from the model, in one transaction."""
    from assets.models import Asset
    if hardware_model.kind != HardwareModel.KIND_DEVICE:
        raise ValidationError('Only device models can be installed as devices; modules go into a module bay.')
    asset_fields = {k: fields.pop(k) for k in list(fields) if k in (
        'hostname', 'serial_number', 'asset_tag', 'ip_address', 'firmware_version', 'notes', 'warranty_expiry',
        'mac_address')}
    asset_type = _asset_type_for(hardware_model.category)
    asset = Asset.objects.create(
        organization=organization, name=name, asset_type=asset_type,
        manufacturer=hardware_model.manufacturer.name[:255], model=hardware_model.model[:255],
        is_rackmount=bool(hardware_model.is_rackmount),
        rack_units=int(hardware_model.u_height) if hardware_model.is_rackmount else None,
        equipment_model=hardware_model.equipment_model, created_by=user,
        os_name=fields.get('platform', '')[:100], **asset_fields)
    site = fields.get('site')
    if site is not None and site.organization_id not in (None, organization.id):
        raise ValidationError('That site belongs to a different client.')
    device = HardwareDevice.objects.create(organization=organization, asset=asset, hardware_model=hardware_model,
                                           template_revision=hardware_model.revision, updated_by=user, **fields)
    templates = list(hardware_model.components.all())
    by_tpl = _ports_from_templates(device, templates)
    _mappings_from_templates(device, hardware_model, by_tpl)
    asset.port_count = sum(1 for p in by_tpl.values() if p.component_class == C.CLASS_INTERFACE) or None
    asset.save(update_fields=['port_count'])
    record(user, 'create', device, {'model': [None, str(hardware_model)]}, device=device)
    return device


def _asset_type_for(category):
    from assets.models import Asset
    valid = {k for k, _ in Asset.ASSET_TYPES}
    mapping = {
        'switch': 'switch', 'router': 'router', 'firewall': 'firewall', 'access_point': 'wireless_ap',
        'wireless_controller': 'wireless_controller', 'server': 'server', 'blade_server': 'server',
        'blade_chassis': 'server', 'storage': 'nas', 'storage_shelf': 'san', 'patch_panel': 'patch_panel',
        'fiber_panel': 'fiber_panel', 'ups': 'ups', 'pdu': 'pdu', 'workstation': 'workstation', 'phone': 'phone',
        'camera': 'security_camera', 'console_server': 'console_server', 'kvm': 'kvm', 'wall_jack': 'patch_panel',
    }
    for candidate in (mapping.get(category), 'network', 'other'):
        if candidate in valid:
            return candidate
    return 'other'


@transaction.atomic
def install_module(device: HardwareDevice, bay: ModuleBay, module_model: HardwareModel, user=None,
                   serial_number='', asset_tag='', status='active') -> InstalledModule:
    if bay.device_id != device.id:
        raise ValidationError('That bay is not on this device.')
    if module_model.kind != HardwareModel.KIND_MODULE:
        raise ValidationError('Only module models can be installed in a bay.')
    if hasattr(bay, 'installed_module'):
        raise ValidationError(f'{bay.name} already holds {bay.installed_module.hardware_model}.')
    mod = InstalledModule.objects.create(organization=device.organization, device=device, bay=bay,
                                         hardware_model=module_model, template_revision=module_model.revision,
                                         serial_number=serial_number, asset_tag=asset_tag, status=status)
    templates = list(module_model.components.all())
    clash = DevicePort.objects.filter(device=device, name__in=[_module_token(t.name, bay) for t in templates
                                                               if t.is_socket])
    if clash.exists():
        raise ValidationError('This module would create ports whose names already exist on the device: '
                              + ', '.join(clash.values_list('name', flat=True)[:6]))
    by_tpl = _ports_from_templates(device, templates, module=mod, bay=bay)
    _mappings_from_templates(device, module_model, by_tpl)
    record(user, 'install_module', mod, {'bay': [None, bay.name], 'module': [None, str(module_model)]},
           device=device)
    return mod


@transaction.atomic
def remove_module(mod: InstalledModule, user=None):
    cabled = DevicePort.objects.filter(module=mod, cable_termination__isnull=False)
    if cabled.exists():
        raise ValidationError('Disconnect the cables on this module first: '
                              + ', '.join(cabled.values_list('name', flat=True)[:6]))
    device = mod.device
    record(user, 'remove_module', mod, {'bay': [mod.bay.name, None]}, device=device)
    PortMapping.objects.filter(Q(front_port__module=mod) | Q(rear_port__module=mod)).delete()
    mod.ports.all().delete()
    mod.delete()


# --------------------------------------------------------------------------- template updates

@dataclass
class TemplateDiff:
    add: list = field(default_factory=list)       # ComponentTemplate
    update: list = field(default_factory=list)    # (DevicePort, {field: (old, new)})
    orphaned: list = field(default_factory=list)  # DevicePort whose template component was removed
    unchanged: int = 0

    @property
    def empty(self):
        return not (self.add or self.update or self.orphaned)


CATALOG_OWNED = ('name', 'label', 'type', 'connector', 'positions', 'mgmt_only', 'poe_mode', 'poe_type',
                 'combo_group')


def template_diff(device: HardwareDevice) -> TemplateDiff:
    """What applying the model's current template to this device would change.

    Matching is by template key only. Ports are never matched by name, so a
    renamed component updates the same port (same id, same cable).
    """
    diff = TemplateDiff()
    templates = {t.key: t for t in device.hardware_model.components.all()}
    ports = {p.template_key: p for p in device.ports.filter(module__isnull=True, template_key__isnull=False)}
    for key, t in templates.items():
        if not t.is_socket:
            continue
        p = ports.get(key)
        if p is None:
            diff.add.append(t)
            continue
        changes = {}
        for f in CATALOG_OWNED:
            new = getattr(t, f)
            if f == 'connector' and not new:
                continue
            if getattr(p, f) != new:
                changes[f] = (getattr(p, f), new)
        if changes:
            diff.update.append((p, changes))
        else:
            diff.unchanged += 1
    for key, p in ports.items():
        if key not in templates:
            diff.orphaned.append(p)
    return diff


@transaction.atomic
def apply_template_update(device: HardwareDevice, user=None) -> TemplateDiff:
    """Apply `template_diff`. Never deletes a port and never touches cables or
    technician-entered configuration; ports removed upstream are kept and flagged."""
    diff = template_diff(device)
    hm = device.hardware_model
    by_tpl = _ports_from_templates(device, diff.add) if diff.add else {}
    for p, changes in diff.update:
        for f, (_, new) in changes.items():
            setattr(p, f, new)
        p.speed_capability = C.speed_capability(p.component_class, p.type)
        try:
            with transaction.atomic():
                p.save()
        except IntegrityError:
            raise ValidationError(f'Renaming {p.name} would clash with another port on this device.')
    if by_tpl:
        # Map every template to the device's port (new or existing), then add
        # only the mappings the device does not have yet.
        key_to_tpl = {t.key: t.pk for t in hm.components.all()}
        all_ports = {key_to_tpl[p.template_key]: p for p in device.ports.filter(
            module__isnull=True, template_key__in=list(key_to_tpl))}
        have = set(PortMapping.objects.filter(device=device).values_list('front_port_id', 'front_position'))
        rows = []
        for m in hm.port_mappings.all():
            f, r = all_ports.get(m.front_port_id), all_ports.get(m.rear_port_id)
            if f and r and (f.pk, m.front_position) not in have and (
                    f.pk in {x.pk for x in by_tpl.values()} or r.pk in {x.pk for x in by_tpl.values()}):
                rows.append(PortMapping(organization=device.organization, device=device, front_port=f,
                                        front_position=m.front_position, rear_port=r, rear_position=m.rear_position))
        PortMapping.objects.bulk_create(rows)
    for p in diff.orphaned:
        if 'Removed from catalog' not in p.notes:
            p.notes = (p.notes + '\n' if p.notes else '') + f'Removed from catalog in revision {hm.revision}; kept.'
            p.save(update_fields=['notes'])
    old = device.template_revision
    device.template_revision = hm.revision
    device.save(update_fields=['template_revision', 'updated_at'])
    record(user, 'template_update', device, {
        'template_revision': [old, hm.revision], 'added': len(diff.add), 'updated': len(diff.update),
        'orphaned': len(diff.orphaned)}, device=device)
    return diff


# --------------------------------------------------------------------------- port configuration

def validate_port_config(port: DevicePort, data: dict, tagged=None):
    """Raise ValidationError for an inconsistent documented configuration."""
    errors = {}
    org_id = port.organization_id
    vlans = [v for v in (data.get('untagged_vlan'), data.get('voice_vlan')) if v is not None] + list(tagged or [])
    for v in vlans:
        if v.organization_id != org_id:
            errors['vlan'] = f'VLAN {v.vlan_id} belongs to a different client.'
        elif v.vlan_group_id and v.vlan_group.site_id and port.device.site_id != v.vlan_group.site_id:
            errors['vlan'] = (f'VLAN {v.vlan_id} ({v.vlan_group.name}) is scoped to another site than '
                              f'{port.device}.')
    mode = data.get('mode', port.mode)
    if vlans and port.component_class not in VLAN_CLASSES:
        errors['mode'] = 'Only network interfaces carry VLANs.'
    if mode == 'access' and tagged:
        errors['tagged_vlans'] = 'An access port has no tagged VLANs. Use trunk or hybrid mode.'
    if mode in ('routed', 'none') and vlans:
        errors['mode'] = f'A {dict(DevicePort.MODE_CHOICES)[mode].lower()} port carries no VLANs.'
    untagged = data.get('untagged_vlan')
    if untagged is not None and tagged and untagged in tagged:
        errors['tagged_vlans'] = f'VLAN {untagged.vlan_id} cannot be both native (untagged) and tagged.'
    lag = data.get('lag')
    if lag is not None and lag.device_id != port.device_id:
        errors['lag'] = 'That LAG is on a different device.'
    poe = data.get('poe_setting', port.poe_setting)
    if poe in ('auto', 'static') and port.poe_mode != 'pse':
        errors['poe_setting'] = 'The catalog does not list this port as a PoE source.'
    if poe == 'pd' and port.poe_mode not in ('pd', ''):
        errors['poe_setting'] = 'This port is a PoE source, not a powered device.'
    speed = data.get('configured_speed')
    if speed and port.component_class != C.CLASS_INTERFACE:
        errors['configured_speed'] = 'Speed applies to network interfaces only.'
    if data.get('breakout_mode') and not port.breakout_lanes.exists() and port.connector != 'qsfp':
        errors['breakout_mode'] = 'Breakout applies to QSFP-family cages.'
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def update_port(port: DevicePort, data: dict, tagged=None, user=None, set_tagged=True):
    """Apply documented configuration. `tagged` (list of VLAN) replaces the tagged set."""
    port = DevicePort.objects.select_for_update().get(pk=port.pk)
    validate_port_config(port, data, tagged if set_tagged else list(
        v.vlan for v in port.tagged_memberships.select_related('vlan')))
    changes = {}
    for f in PORT_CONFIG_FIELDS:
        if f in data:
            old = getattr(port, f)
            if old != data[f]:
                changes[f] = [_fmt(old), _fmt(data[f])]
                setattr(port, f, data[f])
    if data.get('mode') in ('routed', 'none'):
        port.untagged_vlan = port.voice_vlan = None
    if set_tagged and tagged is not None:
        before = set(port.tagged_memberships.values_list('vlan_id', flat=True))
        after = {v.pk for v in tagged}
        if data.get('mode', port.mode) in ('access', 'routed', 'none'):
            after = set()
        if before != after:
            PortVLAN.objects.filter(port=port).exclude(vlan_id__in=after).delete()
            PortVLAN.objects.bulk_create([PortVLAN(port=port, vlan_id=v) for v in after - before])
            changes['tagged_vlans'] = [sorted(before), sorted(after)]
    if changes:
        port.updated_by = user
        port.save()
        record(user, 'update', port, changes, device=port.device)
    return port, changes


def bulk_update_ports(ports, data, user=None, tagged_add=(), tagged_remove=(), label_pattern='',
                      label_start=1):
    """Apply the same change to many ports; optional sequential technician labels.

    `label_pattern` takes {n} (with format spec, e.g. {n:02}) and {port}.
    All-or-nothing: one invalid port rolls the whole batch back.
    """
    results = []
    with transaction.atomic():
        for i, port in enumerate(ports):
            d = dict(data)
            if label_pattern:
                try:
                    d['tech_label'] = label_pattern.format(n=label_start + i, port=port.name)[:100]
                except (KeyError, ValueError, IndexError):
                    raise ValidationError({'label_pattern': 'Use {n}, {n:02} or {port} in the pattern.'})
            tagged = None
            if tagged_add or tagged_remove:
                current = {m.vlan for m in port.tagged_memberships.select_related('vlan')}
                tagged = list((current | set(tagged_add)) - set(tagged_remove))
            try:
                results.append(update_port(port, d, tagged=tagged, user=user, set_tagged=tagged is not None)[1])
            except ValidationError as e:
                raise ValidationError(f'{port.name}: ' + '; '.join(
                    m for msgs in getattr(e, 'message_dict', {'': e.messages}).values() for m in msgs))
    return results


# --------------------------------------------------------------------------- cables

def _same_org(org, *objs):
    for o in objs:
        if o.organization_id != org.id:
            raise ValidationError('A cable cannot connect records of different clients.')


def validate_endpoints(org, a_ports, b_ports, cable_type=''):
    if not a_ports or not b_ports:
        raise ValidationError('A cable needs at least one port on each end.')
    all_ports = list(a_ports) + list(b_ports)
    _same_org(org, *all_ports)
    ids = [p.pk for p in all_ports]
    if len(ids) != len(set(ids)):
        raise ValidationError('The same port cannot be on both ends of a cable.')
    if len(a_ports) > 1 and len(b_ports) > 1:
        raise ValidationError('Only one end of a breakout cable can split.')
    for p in all_ports:
        if not p.is_populated:
            raise ValidationError(f'{p.device} {p.name} is not fitted in this configuration.')
        if p.is_breakout_lane:
            raise ValidationError(f'{p.name} is a breakout lane; cable the cage {p.breakout_parent.name} instead.')
        term = getattr(p, 'cable_termination', None)
        if term is not None:
            raise ValidationError(f'{p.device} {p.name} already has cable {term.cable}.')
        if p.combo_group:
            busy = DevicePort.objects.filter(device=p.device, combo_group=p.combo_group,
                                             cable_termination__isnull=False).exclude(pk=p.pk).first()
            if busy:
                raise ValidationError(f'{p.device} {p.name} shares a combo port with {busy.name}, which is in use; '
                                      f'only one of them can be connected.')
        if not C.cable_fits(cable_type, p.connector):
            raise ValidationError(f'A {dict(C.CABLE_TYPES).get(cable_type, cable_type)} cable does not fit '
                                  f'{p.name} ({C.CONNECTORS.get(p.connector, {}).get("label", p.connector)}).')
    if len(a_ports) > 1 or len(b_ports) > 1:
        single = a_ports[0] if len(a_ports) == 1 else b_ports[0]
        if single.connector not in ('qsfp', 'osfp', 'cfp', 'mpo'):
            raise ValidationError('A split (breakout) cable must start from a QSFP/OSFP/CFP cage or an MPO port.')
    for a in a_ports:
        for b in b_ports:
            ok, why = C.endpoints_compatible(a.component_class, a.connector, b.component_class, b.connector)
            if not ok:
                raise ValidationError(f'{a.name} ↔ {b.name}: {why}')


@transaction.atomic
def connect(org, a_ports, b_ports, user=None, **cable_fields) -> Cable:
    a_ports = list(DevicePort.objects.select_for_update().filter(pk__in=[p.pk for p in a_ports]))
    b_ports = list(DevicePort.objects.select_for_update().filter(pk__in=[p.pk for p in b_ports]))
    validate_endpoints(org, a_ports, b_ports, cable_fields.get('cable_type', ''))
    label = (cable_fields.get('label') or '').strip()
    if label and Cable.objects.filter(organization=org, label=label).exists():
        raise ValidationError(f'Cable ID {label} is already used at this client.')
    cable = Cable.objects.create(organization=org, created_by=user, updated_by=user, **cable_fields)
    try:
        CableTermination.objects.bulk_create(
            [CableTermination(organization=org, cable=cable, end='A', port=p) for p in a_ports]
            + [CableTermination(organization=org, cable=cable, end='B', port=p) for p in b_ports])
    except IntegrityError:
        raise ValidationError('One of those ports was connected by someone else a moment ago. Reload and retry.')
    record(user, 'connect', cable, {
        'a': [None, ', '.join(f'{p.device} {p.name}' for p in a_ports)],
        'b': [None, ', '.join(f'{p.device} {p.name}' for p in b_ports)]}, device=a_ports[0].device)
    return cable


@transaction.atomic
def disconnect(cable: Cable, user=None):
    ends = [f'{t.port.device} {t.port.name}' for t in cable.terminations.select_related('port__device__asset')]
    first = cable.terminations.select_related('port__device').first()
    record(user, 'disconnect', cable, {'ends': [', '.join(ends), None]},
           device=first.port.device if first else None)
    cable.terminations.all().delete()
    cable.delete()


def default_cable_end_labels(cable: Cable):
    """Short, human-readable "where does the other end go" text for each end."""
    ends = cable.ends()

    def short(terms):
        if not terms:
            return '—'
        p = terms[0].port
        name = p.tech_label or (f'Port {p.label}' if p.label.isdigit() else p.label) or p.name
        extra = f' +{len(terms) - 1}' if len(terms) > 1 else ''
        return f'{p.device.asset.name} / {name}{extra}'
    a, b = short(ends['A']), short(ends['B'])
    return f'→ {b}', f'→ {a}'


# --------------------------------------------------------------------------- tracing

@dataclass
class TraceStep:
    kind: str          # 'port' | 'cable' | 'internal'
    port: DevicePort | None = None
    position: int | None = None
    cable: Cable | None = None
    mapping: PortMapping | None = None
    note: str = ''


@dataclass
class TraceResult:
    steps: list
    status: str                     # complete | incomplete | loop | split | ambiguous
    problems: list = field(default_factory=list)

    @property
    def ports(self):
        return [s.port for s in self.steps if s.kind == 'port']

    @property
    def cables(self):
        return [s.cable for s in self.steps if s.kind == 'cable']


MAX_HOPS = 64


def _walk(port, position, cross_cable_first, problems):
    """Follow a path from `port`. Alternates cable / internal mapping."""
    steps, status = [], 'complete'
    visited = {(port.pk, position)}
    cur, pos, via_cable = port, position, cross_cable_first
    for _ in range(MAX_HOPS):
        if via_cable:
            term = CableTermination.objects.filter(port=cur).select_related('cable').first()
            if term is None:
                if cur.is_passive or cur == port:
                    status = 'incomplete'
                    problems.append(f'{cur.device} {cur.name}: no cable documented.')
                return steps, status
            far = list(CableTermination.objects.filter(cable=term.cable).exclude(end=term.end)
                       .select_related('port__device__asset'))
            steps.append(TraceStep('cable', cable=term.cable))
            if not far:
                problems.append(f'Cable {term.cable} has no far end documented.')
                return steps, 'incomplete'
            if len(far) > 1:
                for t in far:
                    steps.append(TraceStep('port', port=t.port, note='breakout leg'))
                return steps, 'split'
            cur = far[0].port
            steps.append(TraceStep('port', port=cur, position=pos))
            if not cur.is_passive:
                return steps, status
            via_cable = False
        else:
            if cur.component_class == C.CLASS_FRONT_PORT:
                fpos = pos if (pos and cur.positions > 1) else 1
                m = PortMapping.objects.filter(front_port=cur, front_position=fpos).select_related('rear_port').first()
                if m is None:
                    problems.append(f'{cur.device} {cur.name}: no internal mapping to a rear port.')
                    return steps, 'incomplete'
                nxt, npos = m.rear_port, (m.rear_position if m.rear_port.positions > 1 else None)
            elif cur.component_class == C.CLASS_REAR_PORT:
                if cur.positions > 1 and not pos:
                    problems.append(f'{cur.device} {cur.name} carries {cur.positions} positions; '
                                    f'trace from a front port to follow one.')
                    return steps, 'ambiguous'
                m = PortMapping.objects.filter(rear_port=cur, rear_position=pos or 1).select_related('front_port').first()
                if m is None:
                    problems.append(f'{cur.device} {cur.name}: position {pos or 1} is not mapped to a front port.')
                    return steps, 'incomplete'
                nxt, npos = m.front_port, None
            else:
                return steps, status
            steps.append(TraceStep('internal', mapping=m, note=f'{cur.device} internal'))
            cur, pos = nxt, npos
            steps.append(TraceStep('port', port=cur, position=pos))
            via_cable = True
        key = (cur.pk, pos)
        if key in visited:
            problems.append(f'The path returns to {cur.device} {cur.name}; stopping (loop).')
            return steps, 'loop'
        visited.add(key)
    problems.append(f'Stopped after {MAX_HOPS} hops.')
    return steps, 'loop'


def trace(port: DevicePort) -> TraceResult:
    """Full physical path through `port`, in both directions.

    Starting on an endpoint (a switch port), the path runs one way. Starting
    on a passive port (patch panel, wall jack) it runs both ways — out of the
    cable side and through the internal mapping — and is joined end to end.
    Redundant networks contain loops; the walk never rejects them, it stops
    when it revisits a port and says so.
    """
    problems = []
    if port.is_breakout_lane:
        port = port.breakout_parent
    forward, s1 = _walk(port, None, True, problems)
    if port.is_passive:
        backward, s2 = _walk(port, None, False, problems)
        steps = list(reversed(backward)) + [TraceStep('port', port=port)] + forward
        statuses = {s1, s2}
    else:
        steps = [TraceStep('port', port=port)] + forward
        statuses = {s1}
    for bad in ('loop', 'split', 'ambiguous', 'incomplete'):
        if bad in statuses:
            status = bad
            break
    else:
        status = 'complete'
    ends = [s.port for s in steps if s.kind == 'port']
    if status == 'complete' and ends and (ends[0].is_passive or ends[-1].is_passive):
        status = 'incomplete'
    if len(ends) == 1 and status == 'complete':
        status = 'incomplete'
    return TraceResult(steps=steps, status=status, problems=problems)


def trace_json(result: TraceResult):
    out = []
    for s in result.steps:
        if s.kind == 'port':
            p = s.port
            out.append({'kind': 'port', 'id': p.pk, 'device_id': p.device_id, 'device': p.device.asset.name,
                        'name': p.name, 'label': p.tech_label or p.label, 'class': p.component_class,
                        'position': s.position, 'key': str(p.template_key or ''), 'module': p.module_id,
                        'note': s.note})
        elif s.kind == 'cable':
            c = s.cable
            out.append({'kind': 'cable', 'id': c.pk, 'label': c.label or f'#{c.pk}', 'type': c.get_cable_type_display(),
                        'color': c.color, 'color_name': c.color_name,
                        'length': f'{c.length.normalize():f} {c.length_unit}' if c.length else '', 'status': c.status})
        else:
            out.append({'kind': 'internal', 'note': s.note})
    return {'status': result.status, 'problems': result.problems, 'steps': out}


# --------------------------------------------------------------------------- clone / rack

@transaction.atomic
def clone_device(device: HardwareDevice, new_name, user=None, copy_port_config=True) -> HardwareDevice:
    """A new device of the same model. Never copies serials, asset tags, MACs,
    management IPs or cables. Optionally copies documented port configuration."""
    src = device.asset
    new = create_device(device.organization, device.hardware_model, new_name, user=user,
                        site=device.site, room=device.room, location_detail=device.location_detail,
                        status='planned', platform=device.platform, firmware_version=src.firmware_version)
    new.asset.tags.set(src.tags.all())
    if copy_port_config:
        src_ports = {(p.template_key, p.module_id is None): p for p in device.ports.filter(module__isnull=True)}
        for p in new.ports.all():
            s = src_ports.get((p.template_key, True))
            if not s:
                continue
            for f in ('mode', 'untagged_vlan_id', 'voice_vlan_id', 'admin_state', 'configured_speed', 'poe_setting'):
                setattr(p, f, getattr(s, f))
            p.save()
            PortVLAN.objects.bulk_create([PortVLAN(port=p, vlan_id=m.vlan_id) for m in s.tagged_memberships.all()])
    record(user, 'clone', new, {'cloned_from': [None, str(device)]}, device=new)
    return new


def place_in_rack(device: HardwareDevice, rack, start_unit, face='front', user=None):
    """Create or move the device's RackDevice placement, enforcing U space."""
    from monitoring.models import RackDevice
    if rack.organization_id != device.organization_id:
        raise ValidationError('That rack belongs to a different client.')
    hm = device.hardware_model
    if not hm.is_rackmount:
        raise ValidationError(f'{hm} is not rack-mountable (0U).')
    units = max(1, int(-(-hm.u_height // 1)))
    rd = device.asset.rack_devices.first() or RackDevice(asset=device.asset, name=device.asset.name)
    old = (rd.rack_id, rd.start_unit, rd.face) if rd.pk else None
    rd.rack, rd.start_unit, rd.units, rd.face = rack, int(start_unit), units, face
    rd.is_full_depth = hm.is_full_depth
    rd.equipment_model = hm.equipment_model
    rd.name = device.asset.name
    rd.full_clean(exclude=['photo'])
    rd.save()
    record(user, 'rack_place', device, {'rack': [str(old), f'{rack.name} U{start_unit} {face}']}, device=device)
    return rd
