"""
Locally maintained catalog entries.

Two kinds:

* **Documented models** missing from the community library, entered from the
  manufacturer's own documentation, with the source and the remaining
  uncertainty recorded on the model and its layout.
* **Generic templates** (``is_generic``): clearly named "Generic …", meant to
  be adapted per device. Their layouts are ``generic`` by definition.

`ensure_local_models()` is idempotent: it creates what is missing and leaves
existing rows (and any staff edits to them) untouched.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils.text import slugify

from . import connectors as C
from .layout import EAR_W, auto_layout, get_layout, save_layout
from .models import ComponentTemplate, HardwareModel, LayoutTemplate, Manufacturer, PortMappingTemplate

DELL_3448P_GUIDE = ("https://dl.dell.com/manuals/all-products/esuprt_ser_stor_net/esuprt_powerconnect/"
                    "powerconnect-3448p_user's%20guide_en-us.pdf")

DELL_3448P_SPEC_NOTES = (
    "Source: Dell PowerConnect 34XX Systems User's Guide (PowerConnect 3448P edition).\n"
    "• p.22: \"The PowerConnect 3448P provides 48 10/100Mbps ports, two SFP ports, and two copper ports that can "
    "be used to forward traffic when the device is in stand-alone mode, or as stacking ports … one RS-232 console "
    "port. In addition, PowerConnect 3448P provides PoE.\"\n"
    "• p.38 (3448 port description, same chassis family): 48 FE ports — RJ-45 10/100Base-T; 2 fiber ports — "
    "1000Base-X SFP (G1–G2); 2 gigabit ports — 1000Base-T (G3–G4), usable as stacking ports. The guide does not "
    "describe any combo ports, so G1–G4 are modelled as four independent ports.\n"
    "• p.39: console is one DB-9 (RS-232, default 9600 bps) on the back panel, with an RPS connector and the AC "
    "power connector.\n"
    "• p.40: PoE model 440 × 387 × 43.2 mm (1U).\n"
    "• p.46: internal 470 W supply, 370 W PoE total (stated for the 24-port PoE device; not restated for 48).\n"
    "• PoE is provided on all 48 FE ports (p.?? Power over Ethernet page: \"all PowerConnect 3448P’s 48 FE ports\").\n"
    "Not stated in the guide and therefore left blank: the IEEE PoE standard/class (802.3af/at), per-port PoE "
    "budget, and the exact AC inlet type (drawn as IEC C14 from the figure's outline).\n"
    "CLI interface names follow the guide's examples: 1/e1–1/e48 and 1/g1–1/g4 (unit 1)."
).replace('(p.?? Power over Ethernet page: ', '(System → General → Power over Ethernet page: ')

DELL_3448P_LAYOUT_NOTES = (
    "Front — verified: arrangement checked against Figure 1-2 (\"PowerConnect 3448 and PowerConnect 3448P\") and "
    "Figure 2-3: four blocks of 6 × 2 RJ-45 ports numbered odd on the top row (1–47) and even on the bottom row "
    "(2–48); G1–G2 SFP cages lower right; G3–G4 RJ-45 stacking ports at the far right; stack-ID LEDs, Select and "
    "Reset buttons and system LEDs (DIAG, EPS, FAN, TEMP, PWR) above them. Millimetre positions are scaled from "
    "the line drawing and are accurate to about ±1.5 mm, not mechanical drawing precision.\n"
    "Rear — approximate: Figure 2-4 shows the non-PoE PowerConnect 3448 back panel (console left, RPS centre, AC "
    "inlet right). The 3448P's deeper PoE chassis is not pictured, so the rear positions are carried over from the "
    "3448 and have not been verified for the 3448P."
)


def _mfr(name):
    m = Manufacturer.objects.filter(name=name).first()
    if m:
        return m
    base = slugify(name) or 'manufacturer'
    slug, n = base, 2
    while Manufacturer.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return Manufacturer.objects.create(name=name, slug=slug)


def _tpl(hm, cls, name, t='', **kw):
    eff, conn = C.classify(cls, t)
    return ComponentTemplate(hardware_model=hm, component_class=eff, name=name, type=t, connector=conn,
                             origin='local', **kw)


def _create_model(spec):
    hm = HardwareModel.objects.create(**spec['model'])
    comps = []
    for i, c in enumerate(spec['components'], 1):
        c = dict(c)
        cls, name, t = c.pop('cls'), c.pop('name'), c.pop('type', '')
        comps.append(_tpl(hm, cls, name, t, sort_order=i, **c))
    ComponentTemplate.objects.bulk_create(comps)
    by = {(c.component_class, c.name): c for c in hm.components.all()}
    for fn, rn in spec.get('mappings', []):
        PortMappingTemplate.objects.create(hardware_model=hm, front_port=by[(C.CLASS_FRONT_PORT, fn)],
                                           rear_port=by[(C.CLASS_REAR_PORT, rn)])
    return hm


# --------------------------------------------------------------------------- Dell PowerConnect 3448P

def _dell_3448p_spec():
    comps = []
    for n in range(1, 49):
        comps.append(dict(cls=C.CLASS_INTERFACE, name=f'1/e{n}', type='100base-tx', label=str(n),
                          poe_mode='pse', description='10/100Base-T, PoE'))
    comps.append(dict(cls=C.CLASS_INTERFACE, name='1/g1', type='1000base-x-sfp', label='G1',
                      description='1000Base-X SFP'))
    comps.append(dict(cls=C.CLASS_INTERFACE, name='1/g2', type='1000base-x-sfp', label='G2',
                      description='1000Base-X SFP'))
    comps.append(dict(cls=C.CLASS_INTERFACE, name='1/g3', type='1000base-t', label='G3',
                      description='1000Base-T; stacking port when stacked'))
    comps.append(dict(cls=C.CLASS_INTERFACE, name='1/g4', type='1000base-t', label='G4',
                      description='1000Base-T; stacking port when stacked'))
    comps.append(dict(cls=C.CLASS_CONSOLE, name='Console', type='de-9', description='RS-232, 9600 8N1 default'))
    comps.append(dict(cls=C.CLASS_POWER_PORT, name='AC', type='iec-60320-c14',
                      description='100–240 VAC inlet (connector type drawn from the figure)'))
    comps.append(dict(cls=C.CLASS_POWER_PORT, name='RPS', type='other',
                      description='Redundant power supply input (PowerConnect RPS)'))
    return {
        'model': dict(
            manufacturer=_mfr('Dell'), model='PowerConnect 3448P', slug='local-dell-powerconnect-3448p',
            kind=HardwareModel.KIND_DEVICE, part_number='', category='switch', category_source='manual',
            description='48-port 10/100 PoE managed stackable switch with 2 SFP and 2 copper gigabit ports.',
            u_height=Decimal('1'), is_full_depth=True, spec_provenance='manufacturer',
            spec_source_url=DELL_3448P_GUIDE, spec_notes=DELL_3448P_SPEC_NOTES),
        'components': comps,
    }


def _dell_3448p_faces(hm):
    keys = {c.name: str(c.key) for c in hm.components.all()}
    sx = lambda px: round((px - 30) * 440 / 1945 + EAR_W, 2)       # figure px → face mm
    sy = lambda px: round((px - 45) * 43.2 / 200 + 0.6, 2)
    els = []
    for n in range(1, 49):
        col = (n - 1) // 2
        block, c = divmod(col, 6)
        top = n % 2 == 1
        x = round(EAR_W + 6.1 + block * 88.9 + c * 14.7, 2)
        y = 11.0 if top else 21.6
        els.append({'key': keys[f'1/e{n}'], 'kind': 'port', 'connector': 'rj45', 'x': x, 'y': y, 'w': 12.6,
                    'h': 9.4, 'label': str(n), 'label_pos': 'above' if top else 'below', 'name': f'1/e{n}'})
    for name, px, lab in (('1/g1', 1635, 'G1'), ('1/g2', 1730, 'G2')):
        els.append({'key': keys[name], 'kind': 'port', 'connector': 'sfp', 'x': sx(px), 'y': 27.4, 'w': 14.0,
                    'h': 8.8, 'label': lab, 'label_pos': 'below', 'name': name})
    for name, px, lab in (('1/g3', 1815, 'G3'), ('1/g4', 1885, 'G4')):
        els.append({'key': keys[name], 'kind': 'port', 'connector': 'rj45', 'x': sx(px), 'y': 19.2, 'w': 13.4,
                    'h': 11.4, 'label': lab, 'label_pos': 'below', 'name': name})
    decor = [{'type': 'ears'},
             {'type': 'text', 'text': 'DELL', 'x': sx(55), 'y': 7.4, 'size': 4.6, 'weight': '700', 'color': '#1d3d8f'},
             {'type': 'text', 'text': 'PowerConnect 3448P', 'x': sx(1810), 'y': 4.6, 'size': 2.4, 'weight': '600'},
             {'type': 'text', 'text': 'STACK ID', 'x': sx(1720), 'y': 4.4, 'size': 1.4, 'anchor': 'middle'},
             {'type': 'led', 'x': sx(1655), 'y': sy(85), 'r': 1.1, 'text': 'Master'},
             {'type': 'text', 'text': 'Stacking Port', 'x': sx(1880), 'y': 43.0, 'size': 1.5, 'anchor': 'middle'},
             {'type': 'box', 'x': sx(1812), 'y': 18.4, 'w': sx(1945) - sx(1812) + 0.6, 'h': 22.2, 'sw': 0.25},
             {'type': 'button', 'x': sx(1800), 'y': sy(100), 'r': 1.5, 'text': 'SELECT'},
             {'type': 'button', 'x': sx(1835), 'y': sy(100), 'r': 1.1, 'text': 'RESET'}]
    for i, (px, py) in enumerate(((1690, 85), (1722, 85), (1752, 85), (1690, 112), (1722, 112), (1752, 112))):
        decor.append({'type': 'led', 'x': sx(px), 'y': sy(py), 'r': 1.0, 'text': str((i % 3) * 2 + 1 + i // 3)})
    for px, py, t in ((1880, 85, 'DIAG'), (1915, 85, 'EPS'), (1880, 112, 'FAN'), (1915, 112, 'TEMP'), (1948, 112, 'PWR')):
        decor.append({'type': 'led', 'x': sx(px), 'y': sy(py) - 1.2, 'r': 1.0, 'text': t})
    decor.append({'type': 'led', 'x': round(sx(1715), 2), 'y': 28.8, 'r': 0.8})
    decor.append({'type': 'led', 'x': round(sx(1715), 2), 'y': 34.4, 'r': 0.8, 'text': 'LNK/ACT'})
    front = {'width': 482.6, 'height': 44.45, 'rack': True, 'accuracy': 'verified', 'elements': els, 'decor': decor}
    rear = {'width': 482.6, 'height': 44.45, 'rack': True, 'inset_x': EAR_W, 'accuracy': 'approximate',
            'elements': [
                {'key': keys['Console'], 'kind': 'port', 'connector': 'de9', 'x': round(EAR_W + 19.4, 2), 'y': 15.9,
                 'w': 30.8, 'h': 12.6, 'label': 'Console', 'label_pos': 'above', 'name': 'Console'},
                {'key': keys['RPS'], 'kind': 'port', 'connector': 'power_other', 'x': round(EAR_W + 163.0, 2),
                 'y': 15.0, 'w': 26.0, 'h': 13.0, 'label': 'RPS', 'label_pos': 'above', 'name': 'RPS'},
                {'key': keys['AC'], 'kind': 'port', 'connector': 'iec_c14', 'x': round(EAR_W + 400.1, 2), 'y': 13.0,
                 'w': 27.0, 'h': 20.0, 'label': '100–240VAC', 'label_pos': 'above', 'name': 'AC'},
            ],
            'decor': [{'type': 'vent', 'x': EAR_W + 230.0, 'y': 6.0, 'w': 140.0, 'h': 32.0}]}
    return {'front': front, 'rear': rear}


# --------------------------------------------------------------------------- generic templates

def _generic_specs():
    g = _mfr('Generic')
    nic = lambda n, t='1000base-t', **kw: dict(cls=C.CLASS_INTERFACE, name=n, type=t, **kw)
    specs = [
        dict(model=dict(model='Generic Workstation (1× RJ45 NIC)', category='workstation', u_height=0,
                        description='Desktop or tower PC. Add or remove NICs to match the machine.'),
             components=[nic('NIC1', label='LAN'), dict(cls=C.CLASS_POWER_PORT, name='PSU', type='iec-60320-c14')]),
        dict(model=dict(model='Generic Laptop / Docking station', category='workstation', u_height=0),
             components=[nic('LAN', label='LAN'), dict(cls=C.CLASS_INTERFACE, name='Wi-Fi', type='ieee802.11ax')]),
        dict(model=dict(model='Generic 8-port Desktop Switch', category='switch', u_height=0),
             components=[nic(f'Port {i}', label=str(i)) for i in range(1, 9)]),
        dict(model=dict(model='Generic 24-port Switch + 4 SFP (1U)', category='switch', u_height=1),
             components=[nic(f'Port {i}', label=str(i)) for i in range(1, 25)]
             + [nic(f'SFP {i}', '10gbase-x-sfpp', label=f'S{i}') for i in range(1, 5)]
             + [dict(cls=C.CLASS_CONSOLE, name='Console', type='rj-45'),
                dict(cls=C.CLASS_POWER_PORT, name='PSU1', type='iec-60320-c14')]),
        dict(model=dict(model='Generic 48-port Switch + 4 SFP (1U)', category='switch', u_height=1),
             components=[nic(f'Port {i}', label=str(i)) for i in range(1, 49)]
             + [nic(f'SFP {i}', '10gbase-x-sfpp', label=f'S{i}') for i in range(1, 5)]
             + [dict(cls=C.CLASS_CONSOLE, name='Console', type='rj-45'),
                dict(cls=C.CLASS_POWER_PORT, name='PSU1', type='iec-60320-c14')]),
        dict(model=dict(model='Generic Firewall / Router (1U, 8× RJ45)', category='firewall', u_height=1),
             components=[nic(f'Port {i}', label=str(i)) for i in range(1, 9)]
             + [dict(cls=C.CLASS_CONSOLE, name='Console', type='rj-45'),
                dict(cls=C.CLASS_POWER_PORT, name='PSU1', type='iec-60320-c14')]),
        dict(model=dict(model='Generic 1U Server', category='server', u_height=1,
                        description='Configurable: install NIC/PSU modules in the bays to match the build.'),
             components=[nic('NIC1', label='1'), nic('NIC2', label='2'), nic('iDRAC/BMC', mgmt_only=True, label='MGMT'),
                         dict(cls=C.CLASS_MODULE_BAY, name='PCIe Slot 1', bay_position='1'),
                         dict(cls=C.CLASS_MODULE_BAY, name='PCIe Slot 2', bay_position='2'),
                         dict(cls=C.CLASS_MODULE_BAY, name='PSU1', bay_position='1'),
                         dict(cls=C.CLASS_MODULE_BAY, name='PSU2', bay_position='2')]),
        dict(model=dict(model='Generic 2U Server', category='server', u_height=2),
             components=[nic(f'NIC{i}', label=str(i)) for i in range(1, 5)]
             + [nic('iDRAC/BMC', mgmt_only=True, label='MGMT')]
             + [dict(cls=C.CLASS_MODULE_BAY, name=f'PCIe Slot {i}', bay_position=str(i)) for i in range(1, 4)]
             + [dict(cls=C.CLASS_MODULE_BAY, name=f'PSU{i}', bay_position=str(i)) for i in range(1, 3)]),
        dict(model=dict(model='Generic Access Point (1× PoE uplink)', category='access_point', u_height=0),
             components=[nic('eth0', poe_mode='pd', label='PoE'),
                         dict(cls=C.CLASS_INTERFACE, name='radio0', type='ieee802.11ax', rf_role='ap'),
                         dict(cls=C.CLASS_INTERFACE, name='radio1', type='ieee802.11ax', rf_role='ap')]),
        dict(model=dict(model='Generic Wall Plate, 2 Jacks', category='wall_jack', u_height=0, is_full_depth=False),
             components=[dict(cls=C.CLASS_FRONT_PORT, name='Jack A', type='8p8c', label='A'),
                         dict(cls=C.CLASS_FRONT_PORT, name='Jack B', type='8p8c', label='B'),
                         dict(cls=C.CLASS_REAR_PORT, name='Jack A', type='110-punch', label='A'),
                         dict(cls=C.CLASS_REAR_PORT, name='Jack B', type='110-punch', label='B')],
             mappings=[('Jack A', 'Jack A'), ('Jack B', 'Jack B')]),
        dict(model=dict(model='Generic Power Outlet (duplex)', category='outlet', u_height=0),
             components=[dict(cls=C.CLASS_POWER_OUTLET, name='Outlet 1', type='nema-5-15r'),
                         dict(cls=C.CLASS_POWER_OUTLET, name='Outlet 2', type='nema-5-15r')]),
        dict(model=dict(model='Generic UPS (2U, 8× C13)', category='ups', u_height=2),
             components=[dict(cls=C.CLASS_POWER_PORT, name='AC In', type='iec-60320-c20')]
             + [dict(cls=C.CLASS_POWER_OUTLET, name=f'Outlet {i}', type='iec-60320-c13', power_port_name='AC In')
                for i in range(1, 9)]),
        dict(model=dict(model='Generic PDU (1U, 8× C13)', category='pdu', u_height=1),
             components=[dict(cls=C.CLASS_POWER_PORT, name='Input', type='iec-60320-c20')]
             + [dict(cls=C.CLASS_POWER_OUTLET, name=f'Outlet {i}', type='iec-60320-c13', power_port_name='Input')
                for i in range(1, 9)]),
        dict(model=dict(model='Generic Device (configurable)', category='other', u_height=0,
                        description='Blank template: add the ports this equipment has.'),
             components=[]),
    ]
    modules = [
        dict(model=dict(model='Generic 2-port 10GbE SFP+ NIC', category='nic', kind=HardwareModel.KIND_MODULE),
             components=[nic('{module}-p1', '10gbase-x-sfpp', label='1'), nic('{module}-p2', '10gbase-x-sfpp', label='2')]),
        dict(model=dict(model='Generic 4-port 1GbE NIC', category='nic', kind=HardwareModel.KIND_MODULE),
             components=[nic(f'{{module}}-p{i}', label=str(i)) for i in range(1, 5)]),
        dict(model=dict(model='Generic PSU (C14)', category='psu', kind=HardwareModel.KIND_MODULE),
             components=[dict(cls=C.CLASS_POWER_PORT, name='PSU{module}', type='iec-60320-c14')]),
    ]
    out = []
    for s in specs + modules:
        m = s['model']
        m.setdefault('kind', HardwareModel.KIND_DEVICE)
        m.update(manufacturer=g, slug='local-' + slugify(m['model'])[:200], is_generic=True,
                 spec_provenance='generic', category_source='manual',
                 u_height=Decimal(str(m.get('u_height', 0))))
        out.append(s)
    return out


@transaction.atomic
def ensure_local_models(stdout=None):
    created = []
    # Upstream "Generic" definitions are generic by nature: say so.
    HardwareModel.objects.filter(manufacturer__name='Generic', is_generic=False).update(is_generic=True)

    if not HardwareModel.objects.filter(slug='local-dell-powerconnect-3448p').exists():
        hm = _create_model(_dell_3448p_spec())
        save_layout(hm, _dell_3448p_faces(hm), accuracy=LayoutTemplate.ACCURACY_APPROXIMATE,
                    auto_generated=False, source_url=DELL_3448P_GUIDE, source_notes=DELL_3448P_LAYOUT_NOTES,
                    bump_model=False)
        created.append(hm)
    for spec in _generic_specs():
        m = spec['model']
        if HardwareModel.objects.filter(manufacturer=m['manufacturer'], kind=m['kind'], slug=m['slug']).exists():
            continue
        hm = _create_model(spec)
        get_layout(hm)
        created.append(hm)
    if stdout:
        for hm in created:
            stdout.write(f'  created {hm}')
    return created
