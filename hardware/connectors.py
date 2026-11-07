"""
Connector vocabulary shared by the importer, the renderer and cable validation.

Upstream component data (devicetype-library) names an interface by its
*standard* (``1000base-t``, ``10gbase-x-sfpp``) or a passive port by its
*connector* (``8p8c``, ``lc``). Drawing a port, deciding whether two ports can
be cabled, and deciding whether a component is a physical socket at all all
need the same answer to "what does this look like and what plugs into it", so
it lives here once.

Nothing in this module guesses beyond the type string: a type that is not
recognised maps to ``generic`` and is drawn as a plain labelled socket.
"""
from __future__ import annotations

import re

# --- Component classes ------------------------------------------------------

CLASS_INTERFACE = 'interface'
CLASS_CONSOLE = 'console'
CLASS_CONSOLE_SERVER = 'console_server'
CLASS_POWER_PORT = 'power_port'
CLASS_POWER_OUTLET = 'power_outlet'
CLASS_FRONT_PORT = 'front_port'
CLASS_REAR_PORT = 'rear_port'

PHYSICAL_PORT_CLASSES = (
    (CLASS_INTERFACE, 'Network interface'),
    (CLASS_CONSOLE, 'Console port'),
    (CLASS_CONSOLE_SERVER, 'Console server port'),
    (CLASS_POWER_PORT, 'Power inlet'),
    (CLASS_POWER_OUTLET, 'Power outlet'),
    (CLASS_FRONT_PORT, 'Passive front port'),
    (CLASS_REAR_PORT, 'Passive rear port'),
)

# Template-only classes: they are instantiated into other tables, never as
# cable sockets.
CLASS_MODULE_BAY = 'module_bay'
CLASS_DEVICE_BAY = 'device_bay'
CLASS_INVENTORY_ITEM = 'inventory_item'
CLASS_LOGICAL = 'logical'      # virtual / lag / bridge interfaces
CLASS_WIRELESS = 'wireless'    # radios

TEMPLATE_CLASSES = PHYSICAL_PORT_CLASSES + (
    (CLASS_MODULE_BAY, 'Module bay'),
    (CLASS_DEVICE_BAY, 'Device bay'),
    (CLASS_INVENTORY_ITEM, 'Inventory item'),
    (CLASS_LOGICAL, 'Logical interface'),
    (CLASS_WIRELESS, 'Wireless radio'),
)

# Upstream YAML key -> component class
UPSTREAM_SECTIONS = {
    'interfaces': CLASS_INTERFACE,
    'console-ports': CLASS_CONSOLE,
    'console-server-ports': CLASS_CONSOLE_SERVER,
    'power-ports': CLASS_POWER_PORT,
    'power-outlets': CLASS_POWER_OUTLET,
    'front-ports': CLASS_FRONT_PORT,
    'rear-ports': CLASS_REAR_PORT,
    'module-bays': CLASS_MODULE_BAY,
    'device-bays': CLASS_DEVICE_BAY,
    'inventory-items': CLASS_INVENTORY_ITEM,
}

LOGICAL_INTERFACE_TYPES = {'virtual', 'bridge', 'lag'}
WIRELESS_PREFIXES = ('ieee802.11', 'ieee802.15', 'other-wireless', 'gsm', 'cdma', 'lte', '4g', '5g')

# --- Connector families -----------------------------------------------------
# Each family has a drawing (renderer.CONNECTOR_SHAPES) and a nominal face
# size in millimetres. Sizes are the visible opening plus surround, rounded;
# they are drawing sizes, not mechanical drawings.

CONNECTORS = {
    'rj45':      {'label': 'RJ45 (8P8C)',     'w': 11.8, 'h': 10.4, 'medium': 'copper'},
    'rj11':      {'label': 'RJ11/RJ12',       'w': 9.6,  'h': 8.4,  'medium': 'copper'},
    'sfp':       {'label': 'SFP-family cage', 'w': 14.0, 'h': 9.0,  'medium': 'cage'},
    'qsfp':      {'label': 'QSFP-family cage', 'w': 19.0, 'h': 9.2, 'medium': 'cage'},
    'osfp':      {'label': 'OSFP cage',       'w': 23.0, 'h': 10.0, 'medium': 'cage'},
    'cfp':       {'label': 'CFP-family cage', 'w': 30.0, 'h': 14.0, 'medium': 'cage'},
    'xfp':       {'label': 'XFP/XENPAK/X2 cage', 'w': 19.0, 'h': 10.0, 'medium': 'cage'},
    'gbic':      {'label': 'GBIC cage',       'w': 15.0, 'h': 11.0, 'medium': 'cage'},
    'lc':        {'label': 'LC duplex',       'w': 12.8, 'h': 7.0,  'medium': 'fiber'},
    'sc':        {'label': 'SC',              'w': 9.4,  'h': 9.4,  'medium': 'fiber'},
    'st':        {'label': 'ST',              'w': 9.0,  'h': 9.0,  'medium': 'fiber'},
    'fc':        {'label': 'FC',              'w': 9.0,  'h': 9.0,  'medium': 'fiber'},
    'mpo':       {'label': 'MPO/MTP',         'w': 13.0, 'h': 6.5,  'medium': 'fiber'},
    'mini_fiber': {'label': 'Small-form fiber (CS/SN/MDC/MU/E2000)', 'w': 7.5, 'h': 6.5, 'medium': 'fiber'},
    'coax':      {'label': 'Coaxial (BNC/F/N/SMA)', 'w': 9.0, 'h': 9.0, 'medium': 'coax'},
    'de9':       {'label': 'DE-9 serial',     'w': 30.8, 'h': 12.6, 'medium': 'serial'},
    'db25':      {'label': 'DB-25 serial',    'w': 53.0, 'h': 12.6, 'medium': 'serial'},
    'mini_din':  {'label': 'Mini-DIN',        'w': 10.0, 'h': 10.0, 'medium': 'serial'},
    'usb_a':     {'label': 'USB-A',           'w': 13.2, 'h': 6.0,  'medium': 'usb'},
    'usb_b':     {'label': 'USB-B',           'w': 9.0,  'h': 8.5,  'medium': 'usb'},
    'usb_c':     {'label': 'USB-C',           'w': 9.2,  'h': 3.6,  'medium': 'usb'},
    'usb_micro': {'label': 'USB Mini/Micro',  'w': 7.8,  'h': 3.4,  'medium': 'usb'},
    'iec_c14':   {'label': 'IEC C14 inlet',   'w': 27.0, 'h': 20.0, 'medium': 'power_in'},
    'iec_c13':   {'label': 'IEC C13 outlet',  'w': 22.0, 'h': 16.0, 'medium': 'power_out'},
    'iec_c20':   {'label': 'IEC C20 inlet',   'w': 30.0, 'h': 23.0, 'medium': 'power_in'},
    'iec_c19':   {'label': 'IEC C19 outlet',  'w': 26.0, 'h': 19.0, 'medium': 'power_out'},
    'iec_small': {'label': 'IEC C6/C8/C5/C7', 'w': 18.0, 'h': 11.0, 'medium': 'power'},
    'nema':      {'label': 'NEMA',            'w': 30.0, 'h': 34.0, 'medium': 'power'},
    'iec_60309': {'label': 'IEC 60309',       'w': 40.0, 'h': 40.0, 'medium': 'power'},
    'dc':        {'label': 'DC terminal / barrel', 'w': 16.0, 'h': 10.0, 'medium': 'power'},
    'power_other': {'label': 'Power (other)', 'w': 18.0, 'h': 14.0, 'medium': 'power'},
    'punch':     {'label': '110 punch-down',  'w': 12.0, 'h': 6.0,  'medium': 'copper'},
    'keystone':  {'label': 'Keystone RJ45',   'w': 14.6, 'h': 16.0, 'medium': 'copper'},
    'backplane': {'label': 'Backplane / internal', 'w': 10.0, 'h': 6.0, 'medium': 'internal'},
    'stack':     {'label': 'Stacking connector', 'w': 16.0, 'h': 9.0, 'medium': 'stack'},
    'generic':   {'label': 'Other connector', 'w': 12.0, 'h': 10.0, 'medium': 'other'},
}

CONNECTOR_CHOICES = [(k, v['label']) for k, v in CONNECTORS.items()]


def _speed_from_type(t: str) -> str:
    m = re.match(r'^(\d+(?:\.\d+)?)(g|t)?base', t)
    if m:
        num, unit = m.group(1), m.group(2)
        if unit == 't':
            return f'{num} Tb/s'
        if unit == 'g':
            return f'{num} Gb/s'
        return f'{num} Mb/s'
    if 'gfc' in t:
        return t.split('gfc')[0] + 'G Fibre Channel'
    if t.startswith('infiniband'):
        return 'InfiniBand ' + t.split('-', 1)[1].upper()
    return ''


def interface_connector(t: str) -> str:
    """Connector family for an upstream *interface* type."""
    t = (t or '').lower()
    if t in LOGICAL_INTERFACE_TYPES or t.startswith(WIRELESS_PREFIXES):
        return ''
    if t.startswith(('cisco-stackwise', 'cisco-flexstack', 'juniper-vcp', 'extreme-summitstack')):
        return 'stack'
    if any(x in t for x in ('qsfp', 'qsfpp', 'qsfp28', 'qsfp56', 'qsfpdd', 'qsfp112', 'cdfp')):
        return 'qsfp'
    if 'osfp' in t:
        return 'osfp'
    if 'cfp' in t or 'cpak' in t or 'cxp' in t:
        return 'cfp'
    if any(x in t for x in ('xenpak', 'xfp', '-x2')):
        return 'xfp'
    if 'gbic' in t:
        return 'gbic'
    if 'sfp' in t or 'dsfp' in t or t.endswith('gfc-sfpp') or 'sfpdd' in t:
        return 'sfp'
    if re.search(r'base-(t|tx|t1)$', t) or t in ('2.5gbase-t', '5gbase-t', '10gbase-t', '25gbase-t'):
        return 'rj45'
    if re.search(r'base-k[rxp]', t) or t == 'hpe-synergy-interconnect-link':
        return 'backplane'
    if re.search(r'base-(cr|cx)', t) or t == '10gbase-cu':
        # Direct-attach copper: on a fixed port this is a cage; keep it a cage.
        return 'qsfp' if re.search(r'cr[248]|cx4', t) else 'sfp'
    if re.search(r'base-(sx|lx|lx10|ex|zx|bx|fx|lfx|lsx|sr|lr|er|zr|dr|fr|vr|lrm|br|cwdm|dwdm)', t):
        # A fibre standard on a fixed port: the optic is integral, draw LC.
        return 'lc'
    if 'gfc' in t:
        return 'sfp'
    if t in ('t1', 'e1', 'xdsl'):
        return 'rj45' if t in ('t1', 'e1') else 'rj11'
    if t in ('t3', 'e3', 'docsis', 'moca'):
        return 'coax'
    if 'pon' in t or t.startswith('sonet'):
        return 'sc' if 'pon' in t else 'lc'
    if t.startswith('infiniband'):
        return 'qsfp'
    return 'generic'


def passive_connector(t: str) -> str:
    """Connector family for an upstream front/rear port type."""
    t = (t or '').lower()
    if t in ('8p8c', '8p6c', '8p4c', '8p2c', 'gg45', 'tera-4p', 'tera-2p', 'tera-1p'):
        return 'rj45'
    if t in ('6p6c', '6p4c', '6p2c', '4p4c', '4p2c'):
        return 'rj11'
    if t == '110-punch':
        return 'punch'
    if t.startswith('lc'):
        return 'lc'
    if t.startswith('sc'):
        return 'sc'
    if t == 'st':
        return 'st'
    if t.startswith('fc'):
        return 'fc'
    if t in ('mpo', 'mtrj', 'mrj21'):
        return 'mpo'
    if t.startswith(('mu', 'lsh', 'lx5')) or t in ('cs', 'sn', 'mdc'):
        return 'mini_fiber'
    if t in ('bnc', 'f', 'n') or t.startswith('sma'):
        return 'coax'
    if t == 'splice' or t.startswith('urm'):
        return 'generic'
    if t.startswith('usb'):
        return usb_connector(t)
    return 'generic'


def usb_connector(t: str) -> str:
    if t in ('usb-a',):
        return 'usb_a'
    if t in ('usb-b', 'usb-3-b'):
        return 'usb_b'
    if t == 'usb-c':
        return 'usb_c'
    return 'usb_micro'


def console_connector(t: str) -> str:
    t = (t or '').lower()
    if t == 'de-9':
        return 'de9'
    if t == 'db-25':
        return 'db25'
    if t == 'rj-45':
        return 'rj45'
    if t in ('rj-11', 'rj-12'):
        return 'rj11'
    if t == 'mini-din-8':
        return 'mini_din'
    if t.startswith('usb'):
        return usb_connector(t)
    return 'generic'


def power_connector(t: str, outlet: bool) -> str:
    t = (t or '').lower()
    if t.startswith('iec-60320-'):
        n = t.rsplit('-', 1)[1]
        return {
            'c14': 'iec_c14', 'c16': 'iec_c14', 'c13': 'iec_c13', 'c15': 'iec_c13',
            'c20': 'iec_c20', 'c22': 'iec_c20', 'c19': 'iec_c19', 'c21': 'iec_c19',
        }.get(n, 'iec_small')
    if t.startswith('iec-60309'):
        return 'iec_60309'
    if t.startswith(('nema', 'cs', 'nbr', 'ita', 'iec-60906')):
        return 'nema'
    if t.startswith('usb'):
        return usb_connector(t)
    if t.startswith(('dc', 'molex', 'saf-d')):
        return 'dc'
    return 'power_other'


def classify(component_class: str, t: str):
    """Return (effective_class, connector) for an upstream component.

    Interfaces whose type is virtual/lag/bridge become logical interfaces and
    radios become wireless — neither is ever drawn as a cable socket.
    """
    t = (t or '').lower()
    if component_class == CLASS_INTERFACE:
        if t in LOGICAL_INTERFACE_TYPES:
            return CLASS_LOGICAL, ''
        if t.startswith(WIRELESS_PREFIXES):
            return CLASS_WIRELESS, ''
        return CLASS_INTERFACE, interface_connector(t)
    if component_class in (CLASS_CONSOLE, CLASS_CONSOLE_SERVER):
        return component_class, console_connector(t)
    if component_class == CLASS_POWER_PORT:
        return component_class, power_connector(t, outlet=False)
    if component_class == CLASS_POWER_OUTLET:
        return component_class, power_connector(t, outlet=True)
    if component_class in (CLASS_FRONT_PORT, CLASS_REAR_PORT):
        return component_class, passive_connector(t)
    return component_class, ''


def speed_capability(component_class: str, t: str) -> str:
    """Human-readable nominal speed implied by the upstream type, or ''."""
    if component_class != CLASS_INTERFACE:
        return ''
    t = (t or '').lower()
    if t == '100base-tx':
        return '10/100 Mb/s'
    if t in ('1000base-t', '1000base-tx'):
        return '10/100/1000 Mb/s'
    if t == '2.5gbase-t':
        return '100M/1G/2.5 Gb/s'
    if t == '5gbase-t':
        return '100M/1G/2.5G/5 Gb/s'
    if t == '10gbase-t':
        return '100M/1G/10 Gb/s'
    return _speed_from_type(t)


def medium(connector: str) -> str:
    return CONNECTORS.get(connector, CONNECTORS['generic'])['medium']


# --- Cable compatibility ----------------------------------------------------

CABLE_TYPES = [
    ('cat5e', 'Cat5e UTP'),
    ('cat6', 'Cat6 UTP'),
    ('cat6a', 'Cat6a'),
    ('cat7', 'Cat7/Cat8 shielded'),
    ('smf', 'Singlemode fiber (OS1/OS2)'),
    ('mmf', 'Multimode fiber (OM1–OM5)'),
    ('aoc', 'Active optical cable'),
    ('dac', 'Direct-attach copper (DAC)'),
    ('coax', 'Coaxial'),
    ('console', 'Console / serial'),
    ('usb', 'USB'),
    ('power', 'Power cord'),
    ('stack', 'Stacking cable'),
    ('other', 'Other'),
]
CABLE_TYPE_KEYS = {k for k, _ in CABLE_TYPES}

# Which cable media can terminate on which connector medium. "cage" accepts
# whatever transceiver is fitted, so it accepts fibre, DAC, AOC and (with a
# copper SFP) twisted pair.
_COPPER = {'cat5e', 'cat6', 'cat6a', 'cat7'}
_FIBER = {'smf', 'mmf'}
CABLE_MEDIA = {
    'copper': _COPPER | {'console', 'other'},
    'fiber': _FIBER | {'other'},
    'cage': _COPPER | _FIBER | {'aoc', 'dac', 'other'},
    'coax': {'coax', 'other'},
    'serial': {'console', 'other'},
    'usb': {'usb', 'console', 'other'},
    'power_in': {'power', 'other'},
    'power_out': {'power', 'other'},
    'power': {'power', 'other'},
    'stack': {'stack', 'dac', 'other'},
    'internal': {'other'},
    'other': CABLE_TYPE_KEYS,
}

POWER_CLASSES = {CLASS_POWER_PORT, CLASS_POWER_OUTLET}
CONSOLE_CLASSES = {CLASS_CONSOLE, CLASS_CONSOLE_SERVER}


def endpoints_compatible(a_class, a_connector, b_class, b_connector):
    """(ok, reason). Checks that two sockets can be joined by one cable.

    Deliberately permissive where real installs are permissive (an SFP cage
    takes a copper module, a console port may be RJ45) and strict where they
    are not (power never meets data, two inlets never meet).
    """
    a_power, b_power = a_class in POWER_CLASSES, b_class in POWER_CLASSES
    if a_power or b_power:
        if not (a_power and b_power):
            return False, 'A power connector can only be cabled to another power connector.'
        if a_class == b_class:
            word = 'inlet' if a_class == CLASS_POWER_PORT else 'outlet'
            return False, f'Two power {word}s cannot be cabled together; connect an inlet to an outlet.'
        return True, ''
    ma, mb = medium(a_connector), medium(b_connector)
    if 'internal' in (ma, mb):
        return False, 'Backplane connections are internal to a chassis and are not cabled.'
    if ma == 'cage' or mb == 'cage' or 'other' in (ma, mb):
        return True, ''
    copperish = {'copper', 'serial', 'usb'}
    if a_class in CONSOLE_CLASSES or b_class in CONSOLE_CLASSES:
        if ma in copperish and mb in copperish:
            return True, ''
    if ma == mb:
        return True, ''
    if {ma, mb} <= {'copper'}:
        return True, ''
    return False, (f'{CONNECTORS.get(a_connector, {}).get("label", a_connector)} and '
                   f'{CONNECTORS.get(b_connector, {}).get("label", b_connector)} cannot share a cable.')


def cable_fits(cable_type, connector):
    if not cable_type:
        return True
    return cable_type in CABLE_MEDIA.get(medium(connector), CABLE_TYPE_KEYS)
