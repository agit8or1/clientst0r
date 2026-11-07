"""
Import the community devicetype-library into the hardware catalog.

Source: https://github.com/netbox-community/devicetype-library (CC0 1.0).
The importer reads the YAML files directly — no NetBox installation — and
writes our own tables.

Properties the command relies on:

* **Pinned revision.** A run imports exactly one commit. ``DEFAULT_REVISION``
  is the commit this release was tested against.
* **Idempotent.** A model is identified by its path in the repository. The
  file's SHA-256 is stored; an unchanged file is recorded as ``unchanged`` and
  not touched, so re-running never duplicates anything.
* **Resumable.** Work happens in batches, one transaction per batch, with a
  ``CatalogImportRecord`` per file. ``--resume <job>`` skips every file the
  job already recorded.
* **Local changes win.** A model staff edited (``locally_modified``) is not
  overwritten; its record says ``conflict`` and shows what upstream changed,
  unless the run passes ``--overwrite-local``.
* **Nothing silently dropped.** The parsed file is stored verbatim in
  ``upstream_data``; keys this application has no column for are listed in
  ``unsupported_fields`` and in the job's coverage report.
* **No invention.** Category is inferred from components and model name and
  marked ``inferred``; nothing else is filled in that the file doesn't say.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from . import connectors as C
from .models import (
    CatalogImportJob, CatalogImportRecord, CatalogSource, ComponentTemplate,
    HardwareModel, Manufacturer, ModelRevision, PortMappingTemplate,
)

log = logging.getLogger(__name__)

SOURCE_KEY = 'devicetype-library'
SOURCE_URL = 'https://github.com/netbox-community/devicetype-library'
LICENSE_NAME = 'CC0 1.0 Universal'
LICENSE_URL = 'https://creativecommons.org/publicdomain/zero/1.0/'
DEFAULT_REVISION = '8fc1eaf44a3e608041f04eba0f555a8d9f96222f'

KIND_DIRS = {
    'device-types': HardwareModel.KIND_DEVICE,
    'module-types': HardwareModel.KIND_MODULE,
    'rack-types': HardwareModel.KIND_RACK,
}

# Top-level keys we store in columns / rows. Anything else is "unsupported":
# preserved in upstream_data and listed, never discarded.
SUPPORTED_KEYS = {
    HardwareModel.KIND_DEVICE: {
        'manufacturer', 'model', 'slug', 'part_number', 'u_height', 'is_full_depth', 'airflow',
        'weight', 'weight_unit', 'subdevice_role', 'is_powered', 'description', 'comments',
        *C.UPSTREAM_SECTIONS.keys(), 'port-mappings',
    },
    HardwareModel.KIND_MODULE: {
        'manufacturer', 'model', 'part_number', 'airflow', 'weight', 'weight_unit', 'description',
        'comments', 'profile', *C.UPSTREAM_SECTIONS.keys(), 'port-mappings',
    },
    HardwareModel.KIND_RACK: {
        'manufacturer', 'model', 'slug', 'description', 'form_factor', 'width', 'u_height',
        'outer_width', 'outer_height', 'outer_depth', 'outer_unit', 'weight', 'max_weight',
        'weight_unit', 'mounting_depth', 'starting_unit', 'desc_units', 'comments',
    },
}
# Per-component keys with a column. Others go to ComponentTemplate.extra and
# are reported as unsupported ("interfaces.bridge").
COMPONENT_KEYS = {
    'name', 'label', 'type', 'description', 'mgmt_only', 'enabled', 'poe_mode', 'poe_type', 'rf_role',
    'positions', 'color', 'maximum_draw', 'allocated_draw', 'feed_leg', 'power_port', 'position',
    'manufacturer', 'part_id', 'rear_port', 'rear_port_position',
}

CATALOG_DIR = Path(getattr(settings, 'HARDWARE_CATALOG_DIR', Path(settings.BASE_DIR) / 'data' / 'hardware-catalog'))


class ImportFileError(Exception):
    pass


# --------------------------------------------------------------------------- source

def ensure_checkout(revision: str = DEFAULT_REVISION, directory: Path | None = None, fetch: bool = True) -> Path:
    """A git checkout of the library at `revision`. Only data is read from it."""
    directory = Path(directory or CATALOG_DIR / 'devicetype-library')
    directory.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    if not (directory / '.git').exists():
        if not fetch:
            raise ImportFileError(f'No checkout at {directory}; run without --no-fetch.')
        subprocess.run(['git', 'init', '-q', str(directory)], check=True, env=env)
        subprocess.run(['git', '-C', str(directory), 'remote', 'add', 'origin', SOURCE_URL], check=True, env=env)
    if fetch:
        target = revision if revision != 'latest' else 'HEAD'
        subprocess.run(['git', '-C', str(directory), 'fetch', '-q', '--depth', '1', 'origin', target],
                       check=True, env=env, timeout=900)
        subprocess.run(['git', '-C', str(directory), 'checkout', '-q', '--force', 'FETCH_HEAD'],
                       check=True, env=env)
    return directory


def checkout_revision(directory: Path) -> tuple[str, str]:
    out = subprocess.run(['git', '-C', str(directory), 'log', '-1', '--format=%H %cI'],
                         check=True, capture_output=True, text=True).stdout.split()
    return out[0], out[1] if len(out) > 1 else ''


def list_files(root: Path, kinds=None, manufacturers=None):
    """Sorted (relative path, kind). Sorting makes batches and resume stable."""
    out = []
    for d, kind in KIND_DIRS.items():
        if kinds and kind not in kinds:
            continue
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob('*'):
            if p.suffix.lower() not in ('.yaml', '.yml') or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if manufacturers and rel.split('/')[1].lower() not in manufacturers:
                continue
            out.append((rel, kind))
    out.sort()
    return out


def get_source(revision='', revision_date=None) -> CatalogSource:
    src, _ = CatalogSource.objects.get_or_create(
        key=SOURCE_KEY,
        defaults=dict(name='NetBox community devicetype-library', url=SOURCE_URL,
                      license_name=LICENSE_NAME, license_url=LICENSE_URL),
    )
    return src


# --------------------------------------------------------------------------- parsing

_LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)


def load_file(path: Path):
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.load(raw, Loader=_LOADER)
    except yaml.YAMLError as e:
        raise ImportFileError(f'YAML error: {e}'.splitlines()[0]) from None
    if not isinstance(data, dict):
        raise ImportFileError('File is not a mapping.')
    return data, sha


def _dec(v, what):
    if v is None or v == '':
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ImportFileError(f'{what} is not a number: {v!r}') from None


@dataclass
class ParsedModel:
    kind: str
    manufacturer: str
    model: str
    slug: str
    fields: dict
    components: list = field(default_factory=list)   # dicts with component_class etc.
    mappings: list = field(default_factory=list)     # (front name, fpos, rear name, rpos)
    unsupported: list = field(default_factory=list)


def parse_definition(data: dict, kind: str, rel_path: str) -> ParsedModel:
    for req in ('manufacturer', 'model'):
        if not data.get(req):
            raise ImportFileError(f'Missing required field "{req}".')
    manufacturer = str(data['manufacturer']).strip()
    model = str(data['model']).strip()
    if len(model) > 200:
        raise ImportFileError('Model name longer than 200 characters.')
    slug = str(data.get('slug') or '').strip() or slugify(f'{manufacturer}-{model}')[:240]
    if not slug:
        slug = slugify(Path(rel_path).stem)[:240]
    unsupported = sorted(k for k in data if k not in SUPPORTED_KEYS[kind])

    f = {
        'part_number': str(data.get('part_number') or '')[:200],
        'description': str(data.get('description') or ''),
        'comments': str(data.get('comments') or ''),
        'airflow': str(data.get('airflow') or '')[:30],
        'weight': _dec(data.get('weight'), 'weight'),
        'weight_unit': str(data.get('weight_unit') or '')[:5],
    }
    if kind == HardwareModel.KIND_DEVICE:
        uh = _dec(data.get('u_height', 0), 'u_height') or Decimal(0)
        if uh < 0 or uh > 100:
            raise ImportFileError(f'Implausible u_height {uh}.')
        f.update(u_height=uh, is_full_depth=bool(data.get('is_full_depth', True)),
                 subdevice_role=str(data.get('subdevice_role') or '')[:10],
                 is_powered=bool(data.get('is_powered', True)))
    elif kind == HardwareModel.KIND_RACK:
        uh = _dec(data.get('u_height', 0), 'u_height') or Decimal(0)
        f.update(u_height=uh, rack_spec={k: data[k] for k in (
            'form_factor', 'width', 'u_height', 'outer_width', 'outer_height', 'outer_depth', 'outer_unit',
            'max_weight', 'mounting_depth', 'starting_unit', 'desc_units') if k in data})
    else:
        f.update(u_height=Decimal(0))

    components, mappings = [], []
    if kind != HardwareModel.KIND_RACK:
        seen = set()
        order = 0
        for section, cls in C.UPSTREAM_SECTIONS.items():
            items = data.get(section) or []
            if not isinstance(items, list):
                raise ImportFileError(f'"{section}" is not a list.')
            for item in items:
                if not isinstance(item, dict) or not item.get('name'):
                    raise ImportFileError(f'An entry in "{section}" has no name.')
                name = str(item['name'])[:100]
                eff_cls, connector = C.classify(cls, str(item.get('type') or ''))
                ident = (eff_cls if eff_cls not in (C.CLASS_LOGICAL, C.CLASS_WIRELESS) else C.CLASS_INTERFACE, name)
                if ident in seen:
                    raise ImportFileError(f'Duplicate {section[:-1]} name "{name}".')
                seen.add(ident)
                extra = {k: v for k, v in item.items() if k not in COMPONENT_KEYS}
                for k in extra:
                    tag = f'{section}.{k}'
                    if tag not in unsupported:
                        unsupported.append(tag)
                order += 1
                comp = dict(
                    component_class=eff_cls, name=name, label=str(item.get('label') or '')[:100],
                    type=str(item.get('type') or '')[:50], connector=connector,
                    description=str(item.get('description') or '')[:250],
                    mgmt_only=bool(item.get('mgmt_only', False)), enabled=bool(item.get('enabled', True)),
                    poe_mode=str(item.get('poe_mode') or '')[:10], poe_type=str(item.get('poe_type') or '')[:30],
                    rf_role=str(item.get('rf_role') or '')[:10],
                    positions=int(item.get('positions') or 1),
                    color=str(item.get('color') or '')[:6],
                    maximum_draw=item.get('maximum_draw') if isinstance(item.get('maximum_draw'), int) else None,
                    allocated_draw=item.get('allocated_draw') if isinstance(item.get('allocated_draw'), int) else None,
                    feed_leg=str(item.get('feed_leg') or '')[:1],
                    power_port_name=str(item.get('power_port') or '')[:100],
                    bay_position=str(item.get('position') or '')[:30],
                    part_id=str(item.get('part_id') or '')[:60],
                    item_manufacturer=str(item.get('manufacturer') or '')[:100],
                    sort_order=order, extra=extra,
                )
                components.append(comp)
                # Older files map a front port inline.
                if cls == C.CLASS_FRONT_PORT and item.get('rear_port'):
                    mappings.append((name, 1, str(item['rear_port']), int(item.get('rear_port_position') or 1)))
        for m in data.get('port-mappings') or []:
            try:
                mappings.append((str(m['front_port']), int(m.get('front_port_position') or 1),
                                 str(m['rear_port']), int(m.get('rear_port_position') or 1)))
            except (KeyError, TypeError, ValueError):
                raise ImportFileError('Malformed port-mappings entry.') from None
        fronts = {c['name']: c for c in components if c['component_class'] == C.CLASS_FRONT_PORT}
        rears = {c['name']: c for c in components if c['component_class'] == C.CLASS_REAR_PORT}
        for fn, fp, rn, rp in mappings:
            if fn not in fronts or rn not in rears:
                raise ImportFileError(f'Port mapping refers to a missing port ({fn} → {rn}).')
            if rp > rears[rn]['positions'] or fp > fronts[fn]['positions']:
                raise ImportFileError(f'Port mapping position out of range ({fn}:{fp} → {rn}:{rp}).')

    if kind == HardwareModel.KIND_MODULE and data.get('profile'):
        f['_profile'] = str(data['profile'])
    return ParsedModel(kind=kind, manufacturer=manufacturer, model=model, slug=slug[:250], fields=f,
                       components=components, mappings=mappings, unsupported=unsupported)


# --------------------------------------------------------------------------- category

# Manufacturer-scoped rules first: model naming is only meaningful within one
# vendor ("R510" is a Ruckus access point and a Dell server). Each rule is
# (category, regex on "model part_number"), first match wins.
_VENDOR_RULES = {
    'cisco': [('firewall', r'asa|firepower|fpr|^meraki mx|^mx\d'),
              ('wireless_controller', r'wlc|air-ct|^ct\d|c98\d\d|catalyst 98'),
              ('access_point', r'aironet|^air-|cw91|^c91\d\d|catalyst 91|^mr\d'),
              ('router', r'isr|asr|csr|c8\d{3}|catalyst 8\d|^c1\d{3}|ncs|^ir\d|^c11\d'),
              ('server', r'^ucs|ucsc'),
              ('switch', r'catalyst|nexus|ws-c|c9\d{3}|^sg\d|cbs|^ie-?\d|^n\dk|^ms\d|^c\d{4}|^n\d')],
    'ubiquiti': [('firewall', r'udm|uxg|usg|dream|gateway|ucg|efg'),
                 ('router', r'edgerouter|^er-'),
                 ('switch', r'usw|switch|edgeswitch|^es-|^us-|ecs'),
                 ('access_point', r'uap|^u6|^u7|nanohd|^ac|flexhd|beacon|nano|litebeam|powerbeam|airmax|'
                                  r'loco|rocket|^ap|unifi ap|mesh|in-wall|iw')],
    'mikrotik': [('switch', r'crs|css|netpower|netfiber'),
                 ('access_point', r'^cap|^wap|audience|^sxt|^lhg|^ldf|^mantbox'),
                 ('router', r'.')],
    'fortinet': [('switch', r'fortiswitch|^fs-|^fs\d'), ('access_point', r'fortiap|^fap'),
                 ('firewall', r'fortigate|^fg|fortiwifi|^fwf')],
    'sonicwall': [('access_point', r'sonicwave|sonicpoint'), ('switch', r'^sws|switch'), ('firewall', r'.')],
    'sophos': [('access_point', r'^apx|^ap\s?\d|^ap\d'), ('switch', r'^cs\d|switch'), ('firewall', r'.')],
    'watchguard': [('access_point', r'^ap\d|^aP\d'), ('firewall', r'.')],
    'netgate': [('firewall', r'.')],
    'ruckus': [('wireless_controller', r'smartzone|^sz|zonedirector|^zd'),
               ('switch', r'icx'), ('access_point', r'^r\d|^t\d|^h\d|^m\d|zoneflex|^e\d')],
    'synology': [('storage_shelf', r'^dx|^rx|expansion'), ('switch', r'^sw'), ('router', r'^rt|^wrx'),
                 ('storage', r'.')],
    'qnap': [('switch', r'^qsw'), ('storage_shelf', r'^tl-|^rx|^ux|^tr-|expansion|jbod'), ('storage', r'.')],
    'apc': [('pdu', r'^ap\d{4}|pdu|^apdu'),
            ('ups', r'ups|^sm[tcx]|^srt|^sur|symmetra|^sua|^bx|^br\d|^bv|^bn|^srv')],
    'eaton': [('pdu', r'pdu|^epdu|^e?p\d|^em\w'),
              ('ups', r'ups|9px|9sx|5px|^5p|^5s|^93|9355|^9e|ellipse|powerware|^5sc')],
    'supermicro': [('switch', r'^sse-|switch'), ('storage_shelf', r'jbod|^cse-.*j'), ('server', r'.')],
    'tp-link': [('access_point', r'^eap|^ap\d|^wa\d|^cpe'), ('router', r'^er\d|router|tl-er'),
                ('switch', r'^sg|^sx|^tl-s|^t\d{4}|switch|jetstream|^ds\d|^es\d')],
    'hpe': [('access_point', r'^ap-|^iap|instant on ap|^ap \d|^ap\d|^ap\s'),
            ('wireless_controller', r'^70\d\d|^72\d\d|^90\d\d|mobility controller'),
            ('storage', r'msa|3par|primera|alletra|nimble|storeonce|storeeasy'),
            ('server', r'proliant|^dl\d|^ml\d|apollo|^bl\d|edgeline|superdome|synergy'),
            ('switch', r'aruba|procurve|^jl\d|^j\d{4}|officeconnect|flexfabric|flexnetwork|^cx|'
                       r'\b\d{4}[a-z]?\b|switch|instant on')],
    'dell': [('storage', r'powervault|powerstore|unity|equallogic|compellent|^me\d|^md\d|^sc\d'),
             ('server', r'poweredge|^r\d{3}|^t\d{3}|^c\d{4}|^m\d{3}|^mx\d|^xc|vxrail|^xr\d'),
             ('switch', r'powerswitch|powerconnect|force10|^s\d{4}|^n\d{4}|^z\d{4}|^x\d{4}|networking|'
                        r'^e\d{2}|^s\d{3}')],
    'juniper': [('firewall', r'^srx'), ('router', r'^mx|^acx|^ptx|^ssr|^nfx|^m\d'),
                ('access_point', r'^ap\d|mist'), ('switch', r'^ex|^qfx|^ocx')],
    'lenovo': [('storage', r'thinksystem d[em]|^de\d|^dm\d'),
               ('server', r'thinksystem|thinkagile|system x|^sr\d|^st\d|^se\d|^sd\d'),
               ('switch', r'rackswitch|^ne\d|^g\d{4}')],
    'extreme networks': [('access_point', r'^ap|ap\d'), ('wireless_controller', r'controller|^vx\d|^c\d{4}'),
                         ('router', r'^slx|router'), ('switch', r'.')],
}
# Manufacturers whose small single-uplink devices are IP cameras / IP phones.
CAMERA_VENDORS = {v.lower() for v in (
    'Dahua', 'i-PRO', 'Vivotek', 'TVT Digital', 'Uniview', 'Hikvision', 'LILIN', 'HiLook', 'Kedacom',
    'Arecont Vision', 'NOVUS', 'AVYCON', 'Safire', 'CP Plus', 'HikMicro', 'Illustra', 'Interlogix', 'AVTech',
    'Reolink', 'GeoVision', 'Axis', 'Hanwha', 'Hanwha Vision', 'Verkada', 'ASECAM', 'Ajax', 'CNB', 'Srihome',
    'Swann', 'VIGI', 'Zavio', 'Mobotix', 'Milesight', 'Amcrest', 'Lorex', 'Pelco', 'Avigilon', 'Annke',
    'Provision-ISR', 'Hyundai', 'Grundig', 'Bosch', 'Sony', 'Matrix', 'Ezviz', 'Imou', 'Tiandy', 'Honeywell')}
PHONE_VENDORS = {v.lower() for v in ('Yealink', 'Poly', 'Polycom', 'Grandstream', 'Snom', 'Fanvil', 'Avaya',
                                     'Mitel', 'Gigaset', 'Htek', 'Alcatel-Lucent Enterprise')}
_VENDOR_ALIASES = {'hp': 'hpe', 'aruba': 'hpe', 'hewlett packard enterprise': 'hpe', 'force10': 'dell',
                   'extreme': 'extreme networks', 'ubiquiti networks': 'ubiquiti', 'tp-link': 'tp-link'}
_VENDOR_RULES = {v: [(c, re.compile(rx, re.I)) for c, rx in rules] for v, rules in _VENDOR_RULES.items()}

# Generic keywords — only words that mean the same thing for every vendor.
_KW = [
    ('wireless_controller', r'\b(wireless (lan )?controller|mobility controller)\b'),
    ('ups', r'\b(ups|uninterruptible)\b'),
    ('pdu', r'\b(pdu|power distribution)\b'),
    ('storage_shelf', r'\b(disk shelf|jbod|drive enclosure|storage shelf)\b'),
    ('storage', r'\b(nas|san|storage array|storage system)\b'),
    ('firewall', r'\b(firewall|utm|next-generation firewall|ngfw)\b'),
    ('access_point', r'\b(access point|wireless ap)\b'),
    ('console_server', r'\b(console server|terminal server)\b'),
    ('kvm', r'\bkvm\b'),
    ('phone', r'\b(ip phone|desk phone)\b'),
    ('camera', r'\b(camera|nvr)\b'),
    ('blade_chassis', r'\b(blade (chassis|enclosure))\b'),
    ('router', r'\brouter\b'),
    ('switch', r'\bswitch\b'),
    ('server', r'\bserver\b'),
]
_KW = [(c, re.compile(p, re.I)) for c, p in _KW]

# Endpoint product lines, matched on the model name only ("desktop" in a
# description also describes desktop firewalls). Checked before the radio
# rule so a laptop's Wi-Fi does not make it an access point; mounting kits
# named after the computer they hold are not the computer.
_ENDPOINT = re.compile(r'\b(laptop|notebook|latitude|optiplex|vostro|inspiron|thinkpad|thinkcentre|thinkstation|'
                       r'ideapad|elitebook|elitedesk|prodesk|probook|zbook|macbook|imac|mac mini|mac studio)\b', re.I)
_MOUNT = re.compile(r'\b(mount|bracket|shelf|kit|tray|holder)\b|rackify', re.I)

_MODULE_PROFILE = {'power supply': 'psu', 'expansion card': 'nic', 'fan': 'fan', 'transceiver': 'transceiver',
                   'cpu': 'module_other', 'memory': 'module_other', 'hard disk': 'drive', 'gpu': 'nic'}


def infer_category(p: ParsedModel) -> str:
    comps = p.components
    by_cls = Counter(c['component_class'] for c in comps)
    text = ' '.join([p.manufacturer, p.model, p.fields.get('part_number', ''), p.fields.get('description', '')])

    if p.kind == HardwareModel.KIND_RACK:
        return 'rack'
    if p.kind == HardwareModel.KIND_MODULE:
        prof = (p.fields.get('_profile') or '').lower()
        if prof in _MODULE_PROFILE:
            return _MODULE_PROFILE[prof]
        if re.search(r'\b(sfp|qsfp|xfp|gbic|transceiver|optic|cfp|osfp)', text, re.I) and by_cls[C.CLASS_INTERFACE] <= 2:
            return 'transceiver'
        if re.search(r'\b(psu|power supply|power module|ac power|dc power)\b', text, re.I) or (
                by_cls[C.CLASS_POWER_PORT] and not by_cls[C.CLASS_INTERFACE]):
            return 'psu'
        if re.search(r'\bfan\b', text, re.I):
            return 'fan'
        if re.search(r'\b(nic|adapter|ocp|mezz|lom|network card|hba|ethernet card|pcie)\b', text, re.I):
            return 'nic'
        if re.search(r'\b(drive|ssd|hdd|disk)\b', text, re.I):
            return 'drive'
        if by_cls[C.CLASS_INTERFACE] or by_cls[C.CLASS_FRONT_PORT]:
            return 'line_card'
        return 'module_other'

    if p.fields.get('subdevice_role') == 'child':
        return 'blade_server'
    wired = by_cls[C.CLASS_INTERFACE]
    if by_cls[C.CLASS_FRONT_PORT] and by_cls[C.CLASS_REAR_PORT] and not wired:
        fiber = any(c['connector'] in ('lc', 'sc', 'st', 'fc', 'mpo', 'mini_fiber')
                    for c in comps if c['component_class'] == C.CLASS_FRONT_PORT)
        if re.search(r'\b(wall ?plate|faceplate|wall jack|surface)\b', text, re.I):
            return 'wall_jack'
        return 'fiber_panel' if fiber else 'patch_panel'
    vendor = p.manufacturer.lower()
    vendor = _VENDOR_ALIASES.get(vendor, vendor)
    model_text = f'{p.model} {p.fields.get("part_number", "")}'.strip()
    if _ENDPOINT.search(p.model) and not _MOUNT.search(f'{p.manufacturer} {p.model}'):
        return 'workstation'
    for cat, rx in _VENDOR_RULES.get(vendor, ()):
        if rx.search(model_text) or rx.search(p.model):
            if cat in ('ups', 'pdu') and not by_cls[C.CLASS_POWER_OUTLET]:
                continue
            if cat == 'access_point' and wired > 8:
                continue
            return cat
    for cat, rx in _KW:
        if rx.search(text):
            if cat in ('ups', 'pdu') and not by_cls[C.CLASS_POWER_OUTLET]:
                continue
            if cat == 'access_point' and wired > 8:
                continue
            return cat
    if vendor in CAMERA_VENDORS and wired <= 2 and not by_cls[C.CLASS_POWER_OUTLET] \
            and not re.search(r'nvr|dvr|xvr|switch|recorder|decoder|controller|keyboard', model_text, re.I):
        return 'camera'
    if vendor in PHONE_VENDORS and wired <= 3 and not re.search(r'switch|gateway|router|ap\b', model_text, re.I):
        return 'phone'
    if by_cls[C.CLASS_POWER_OUTLET] >= 4 and not wired:
        return 'pdu'
    if by_cls[C.CLASS_WIRELESS] and wired <= 4:
        return 'access_point'
    if by_cls[C.CLASS_CONSOLE_SERVER] >= 4:
        return 'console_server'
    if p.fields.get('subdevice_role') == 'parent' and by_cls[C.CLASS_DEVICE_BAY]:
        return 'blade_chassis'
    data_ifaces = [c for c in comps if c['component_class'] == C.CLASS_INTERFACE and not c['mgmt_only']]
    if len(data_ifaces) >= 8:
        return 'switch'
    return 'other'


# --------------------------------------------------------------------------- writing

MODEL_FIELDS = ('part_number', 'description', 'comments', 'airflow', 'weight', 'weight_unit', 'u_height',
                'is_full_depth', 'subdevice_role', 'is_powered', 'rack_spec')
COMPONENT_FIELDS = ('component_class', 'label', 'type', 'connector', 'description', 'mgmt_only', 'enabled',
                    'poe_mode', 'poe_type', 'rf_role', 'positions', 'color', 'maximum_draw', 'allocated_draw',
                    'feed_leg', 'power_port_name', 'bay_position', 'part_id', 'item_manufacturer',
                    'sort_order', 'extra')


def _component_ident(c):
    cls = c['component_class'] if isinstance(c, dict) else c.component_class
    name = c['name'] if isinstance(c, dict) else c.name
    group = C.CLASS_INTERFACE if cls in (C.CLASS_LOGICAL, C.CLASS_WIRELESS) else cls
    return group, name


def snapshot(hm: HardwareModel) -> dict:
    comps = [{'key': str(c.key), 'class': c.component_class, 'name': c.name, 'label': c.label, 'type': c.type,
              'connector': c.connector, 'positions': c.positions, 'poe_mode': c.poe_mode, 'poe_type': c.poe_type,
              'mgmt_only': c.mgmt_only, 'combo_group': c.combo_group}
             for c in hm.components.order_by('sort_order', 'id')]
    lay = hm.current_layout
    return {'components': comps, 'layout_version': lay.version if lay else None}


def ensure_revision_snapshot(hm: HardwareModel, user=None, reason=''):
    """Record the current revision before it changes (lazy snapshots)."""
    if not ModelRevision.objects.filter(hardware_model=hm, number=hm.revision).exists():
        ModelRevision.objects.create(hardware_model=hm, number=hm.revision, snapshot=snapshot(hm),
                                     created_by=user, reason=reason or 'Snapshot before change')


def diff_model(hm: HardwareModel, p: ParsedModel) -> dict:
    changes = {}
    for f in MODEL_FIELDS:
        if f in p.fields and getattr(hm, f) != p.fields[f]:
            old = getattr(hm, f)
            changes[f] = [str(old), str(p.fields[f])]
    existing = {_component_ident(c): c for c in hm.components.all()}
    incoming = {_component_ident(c): c for c in p.components}
    added = sorted(f'{k[0]}:{k[1]}' for k in incoming.keys() - existing.keys())
    removed = sorted(f'{k[0]}:{k[1]}' for k in existing.keys() - incoming.keys())
    changed = []
    for k in incoming.keys() & existing.keys():
        e, i = existing[k], incoming[k]
        diffs = [f for f in COMPONENT_FIELDS if f != 'sort_order' and getattr(e, f) != i[f]]
        if diffs:
            changed.append(f'{k[0]}:{k[1]} ({", ".join(diffs)})')
    if added:
        changes['components_added'] = added
    if removed:
        changes['components_removed'] = removed
    if changed:
        changes['components_changed'] = sorted(changed)
    return changes


def _write_components(hm: HardwareModel, p: ParsedModel):
    """Reconcile templates by (class group, name), keeping existing keys."""
    existing = {_component_ident(c): c for c in hm.components.all()}
    incoming = {_component_ident(c): c for c in p.components}
    for k, obj in existing.items():
        if k not in incoming and obj.origin == 'upstream':
            obj.delete()
    to_create, to_update = [], []
    for k, data in incoming.items():
        obj = existing.get(k)
        if obj is None:
            to_create.append(ComponentTemplate(hardware_model=hm, name=data['name'],
                                               **{f: data[f] for f in COMPONENT_FIELDS}))
        else:
            dirty = False
            for f in COMPONENT_FIELDS:
                if getattr(obj, f) != data[f]:
                    setattr(obj, f, data[f])
                    dirty = True
            if dirty:
                to_update.append(obj)
    if to_create:
        ComponentTemplate.objects.bulk_create(to_create, batch_size=500)
    if to_update:
        ComponentTemplate.objects.bulk_update(to_update, list(COMPONENT_FIELDS), batch_size=500)
    PortMappingTemplate.objects.filter(hardware_model=hm).delete()
    if p.mappings:
        by = {(c.component_class, c.name): c for c in hm.components.filter(
            component_class__in=(C.CLASS_FRONT_PORT, C.CLASS_REAR_PORT))}
        PortMappingTemplate.objects.bulk_create([
            PortMappingTemplate(hardware_model=hm, front_port=by[(C.CLASS_FRONT_PORT, fn)], front_position=fp,
                                rear_port=by[(C.CLASS_REAR_PORT, rn)], rear_position=rp)
            for fn, fp, rn, rp in p.mappings])


class Importer:
    def __init__(self, root: Path, job: CatalogImportJob, stdout=None):
        self.root = Path(root)
        self.job = job
        self.stdout = stdout
        self.manufacturers = {m.name: m for m in Manufacturer.objects.all()}
        self.by_path = {}
        self.counts = Counter(job.counts or {})

    def _manufacturer(self, name):
        m = self.manufacturers.get(name)
        if m is None:
            base = slugify(name)[:190] or 'manufacturer'
            slug, n = base, 2
            while Manufacturer.objects.filter(slug=slug).exists():
                slug, n = f'{base}-{n}', n + 1
            m = Manufacturer.objects.create(name=name, slug=slug, source=self.job.source)
            self.manufacturers[name] = m
        return m

    def _existing(self, rel, p: ParsedModel):
        hm = HardwareModel.objects.filter(source=self.job.source, upstream_path=rel).first()
        if hm:
            return hm
        return None

    def _free_slug(self, manufacturer, kind, slug, rel):
        if manufacturer.pk is None or not HardwareModel.objects.filter(manufacturer=manufacturer, kind=kind, slug=slug).exists():
            return slug
        alt = f'{slug}-{slugify(Path(rel).stem)}'[:240]
        n = 2
        while HardwareModel.objects.filter(manufacturer=manufacturer, kind=kind, slug=alt).exists():
            alt = f'{slug}-{n}'
            n += 1
        return alt

    def process(self, rel: str, kind: str):
        job = self.job
        path = self.root / rel
        rec = dict(path=rel, kind=kind, manufacturer=rel.split('/')[1][:200])
        try:
            data, sha = load_file(path)
            rec['sha'] = sha
            p = parse_definition(data, kind, rel)
            if p.manufacturer != rec['manufacturer']:
                # The directory and the file disagree; the file is authoritative.
                rec['manufacturer'] = p.manufacturer[:200]
            category = infer_category(p)
            rec['category'] = category
            rec['unsupported_fields'] = p.unsupported
            hm = self._existing(rel, p)
            if hm is None:
                if job.is_preview:
                    return self._record(rec, 'would_create')
                with transaction.atomic():
                    m = self._manufacturer(p.manufacturer)
                    hm = HardwareModel(
                        manufacturer=m, model=p.model, slug=self._free_slug(m, kind, p.slug, rel), kind=kind,
                        category=category, category_source='inferred', source=job.source, upstream_path=rel,
                        upstream_revision=job.revision, upstream_sha=sha, upstream_data=data,
                        unsupported_fields=p.unsupported, imported_at=timezone.now(), spec_provenance='upstream',
                        **{k: v for k, v in p.fields.items() if not k.startswith('_')})
                    hm.save()
                    _write_components(hm, p)
                rec['hardware_model'] = hm
                return self._record(rec, 'created')
            rec['hardware_model'] = hm
            if hm.upstream_sha == sha:
                if hm.upstream_revision != job.revision and not job.is_preview:
                    HardwareModel.objects.filter(pk=hm.pk).update(upstream_revision=job.revision)
                return self._record(rec, 'unchanged')
            changes = diff_model(hm, p)
            rec['changes'] = changes
            if hm.locally_modified and not job.overwrite_local:
                return self._record(rec, 'conflict', 'Has local changes; upstream changes listed, not applied.')
            if job.is_preview:
                return self._record(rec, 'would_update')
            with transaction.atomic():
                ensure_revision_snapshot(hm, reason=f'Before upstream update to {job.revision[:10]}')
                for k, v in p.fields.items():
                    if not k.startswith('_'):
                        setattr(hm, k, v)
                hm.model = p.model
                if hm.category_source == 'inferred':
                    hm.category = category
                hm.upstream_revision, hm.upstream_sha, hm.upstream_data = job.revision, sha, data
                hm.unsupported_fields, hm.imported_at = p.unsupported, timezone.now()
                if any(k.startswith('components_') for k in changes):
                    hm.revision += 1
                if job.overwrite_local:
                    hm.locally_modified, hm.local_fields = False, []
                hm.save()
                _write_components(hm, p)
                if any(k.startswith('components_') for k in changes):
                    from .layout import refresh_auto_layout
                    refresh_auto_layout(hm)
            return self._record(rec, 'updated')
        except ImportFileError as e:
            return self._record(rec, 'failed', str(e))
        except Exception as e:  # noqa: BLE001 — one bad file must not stop the run
            log.exception('Catalog import failed for %s', rel)
            return self._record(rec, 'failed', f'{type(e).__name__}: {e}'[:500])

    def _record(self, rec, status, message=''):
        CatalogImportRecord.objects.create(job=self.job, status=status, message=message, **rec)
        self.counts[status] += 1
        if rec.get('unsupported_fields'):
            self.counts['with_unsupported_fields'] += 1
        return status

    def run(self, files, batch_size=250, limit=None):
        job = self.job
        done = set(job.records.values_list('path', flat=True))
        todo = [(r, k) for r, k in files if r not in done]
        if limit:
            todo = todo[:limit]
        job.total_files = len(files)
        job.status = 'preview' if job.is_preview else 'running'
        job.save(update_fields=['total_files', 'status'])
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            with transaction.atomic():
                for rel, kind in batch:
                    self.process(rel, kind)
                job.processed_files = job.records.count()
                job.counts = dict(self.counts)
                job.save(update_fields=['processed_files', 'counts', 'updated_at'])
            if self.stdout:
                self.stdout.write(f'  {job.processed_files}/{job.total_files} files  {dict(self.counts)}')
        return self.counts


def start_job(revision, preview=False, overwrite_local=False, user=None, revision_date=None):
    src = get_source()
    return CatalogImportJob.objects.create(source=src, revision=revision, is_preview=preview,
                                           overwrite_local=overwrite_local, started_by=user)


def finish_job(job: CatalogImportJob, revision_date=None, complete=True):
    job.processed_files = job.records.count()
    counts = Counter(job.records.values_list('status', flat=True))
    counts['with_unsupported_fields'] = job.records.exclude(unsupported_fields=[]).count()
    job.counts = dict(counts)
    job.finished_at = timezone.now()
    if job.is_preview:
        job.status = 'preview'
    elif not complete:
        job.status = 'paused'
    else:
        job.status = 'completed_with_errors' if counts.get('failed') else 'completed'
        src = job.source
        src.revision = job.revision
        src.imported_at = job.finished_at
        if revision_date:
            from django.utils.dateparse import parse_datetime
            src.revision_date = parse_datetime(revision_date)
        src.save()
    job.save()
    return job


def recategorize(stdout=None):
    """Recompute inferred categories from stored upstream data (no files read).

    Only models whose category is still ``inferred`` change; a category staff
    set is never touched. Returns {old→new: count}.
    """
    from collections import Counter as _C
    moves = _C()
    qs = HardwareModel.objects.filter(category_source='inferred').exclude(upstream_data={})
    for hm in qs.iterator(chunk_size=500):
        try:
            p = parse_definition(hm.upstream_data, hm.kind, hm.upstream_path)
        except ImportFileError:
            continue
        cat = infer_category(p)
        if cat != hm.category:
            moves[f'{hm.category}→{cat}'] += 1
            HardwareModel.objects.filter(pk=hm.pk).update(category=cat)
            # The automatic layout (and so the artwork) depends on the category,
            # e.g. an access point is drawn from the top. Hand-made layouts stay.
            from .layout import refresh_auto_layout
            hm.category = cat
            refresh_auto_layout(hm)
    return moves
