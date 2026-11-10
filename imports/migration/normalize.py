"""Source record -> canonical record.

A canonical record says which kind of ClientSt0r record a source record
becomes, with which field values, which secrets and which links to other
*source* records. It is pure: the same staged record (and the same type
overrides) always gives the same canonical record, which is what lets apply
re-derive secrets from staging without re-fetching.

The legacy all-organizations importer (imports/services) uses the same
functions for contacts, locations and networks.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from .redact import CONFIDENTIAL_FIELD_TYPES

KINDS = ('location', 'contact', 'network', 'asset', 'ip_address', 'password',
         'document', 'website', 'relation', 'attachment')

# Order in which kinds are applied: what others link to goes first.
APPLY_ORDER = {k: i for i, k in enumerate(KINDS)}


@dataclass
class Canonical:
    kind: str
    name: str
    fields: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)
    # [{'role': ..., 'source_type': ..., 'source_id': ...}]
    links: list = field(default_factory=list)
    skipped_fields: list = field(default_factory=list)
    unavailable: str = ''
    unavailable_kind: str = ''  # permission / api_gap / not_supported / invalid


def _s(value, limit=None):
    if value is None:
        return ''
    text = str(value).strip()
    return text[:limit] if limit else text


def _link(role, source_type, source_id):
    if source_id in (None, '', 0):
        return None
    return {'role': role, 'source_type': source_type, 'source_id': str(source_id)}


def clean_ip(value):
    value = _s(value)
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def clean_network(value):
    value = _s(value)
    if not value:
        return None
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError:
        return None


def split_name(full):
    parts = _s(full).split()
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return ' '.join(parts[:-1]), parts[-1]


ASSET_TYPE_WORDS = [
    ('server', 'server'), ('laptop', 'laptop'), ('desktop', 'desktop'),
    ('workstation', 'workstation'), ('computer', 'desktop'), ('firewall', 'firewall'),
    ('switch', 'switch'), ('router', 'router'), ('access point', 'wireless_ap'),
    ('wireless', 'wireless_ap'), ('printer', 'printer'), ('ups', 'ups'), ('nas', 'nas'),
    ('tablet', 'tablet'), ('phone', 'phone'), ('mobile', 'mobile'),
]


def asset_type_for(type_name):
    """Source configuration type / layout name -> Asset.asset_type."""
    from assets.models import Asset
    valid = {k for k, _ in Asset.ASSET_TYPES}
    lowered = _s(type_name).lower()
    if lowered.replace(' ', '_') in valid:
        return lowered.replace(' ', '_')
    import re
    for word, value in ASSET_TYPE_WORDS:
        if re.search(rf'\b{re.escape(word)}s?\b', lowered) and value in valid:
            return value
    return 'other'


# ---------------------------------------------------------------------------
# IT Glue
# ---------------------------------------------------------------------------

ITGLUE_RESOURCE_TYPES = {
    'configuration': 'configuration', 'configurations': 'configuration',
    'contact': 'contact', 'contacts': 'contact',
    'location': 'location', 'locations': 'location',
    'document': 'document', 'documents': 'document',
    'password': 'password', 'passwords': 'password',
    'flexible asset': 'flexible_asset', 'flexible-asset': 'flexible_asset',
    'flexible_asset': 'flexible_asset', 'flexibleasset': 'flexible_asset',
    'flexible-assets': 'flexible_asset', 'flexible_assets': 'flexible_asset',
}


def itglue_resource_type(value):
    return ITGLUE_RESOURCE_TYPES.get(_s(value).lower())


def itglue_flexible_kind(type_name, overrides):
    choice = (overrides.get('itglue_flexible_types') or {}).get(type_name)
    if choice:
        return choice
    lowered = _s(type_name).lower()
    if any(w in lowered for w in ('network', 'subnet', 'lan', 'vlan')):
        return 'network'
    return 'skip'


def _first(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, '', []):
            return v
    return None


def _primary(values):
    """IT Glue contact-emails / contact-phones -> primary value."""
    if not isinstance(values, list):
        return ''
    best = None
    for v in values:
        if not isinstance(v, dict):
            continue
        if v.get('primary'):
            best = v
            break
        best = best or v
    if not best:
        return ''
    value = _s(best.get('value'))
    if best.get('extension'):
        value = f"{value} x{best['extension']}"
    return value


def itglue_canonical(source_type, raw, secrets, overrides):
    a = raw.get('attributes', {}) or {}
    sid = raw.get('id')
    if source_type == 'location':
        return Canonical('location', _s(a.get('name')) or f'Location {sid}', fields={
            'name': _s(a.get('name')) or f'Location {sid}',
            'street_address': _s(a.get('address-1')),
            'street_address_2': _s(a.get('address-2')),
            'city': _s(a.get('city')),
            'state': _s(a.get('region-name')),
            'postal_code': _s(a.get('postal-code')),
            'country': _s(a.get('country-name')) or 'United States',
            'phone': _s(a.get('phone')),
            'notes': _s(a.get('notes')),
            'is_primary': bool(a.get('primary')),
        })
    if source_type == 'contact':
        first, last = _s(a.get('first-name')), _s(a.get('last-name'))
        if not first and not last:
            first, last = split_name(a.get('name'))
        c = Canonical('contact', f'{first} {last}'.strip() or f'Contact {sid}', fields={
            'first_name': first or '(unknown)',
            'last_name': last,
            'email': _s(_primary(a.get('contact-emails'))),
            'phone': _s(_primary(a.get('contact-phones'))),
            'title': _s(a.get('title')),
            'notes': _s(a.get('notes')),
        })
        c.links = [l for l in [_link('location', 'location', a.get('location-id'))] if l]
        return c
    if source_type == 'configuration':
        type_name = a.get('configuration-type-name') or ''
        c = Canonical('asset', _s(a.get('name')) or f'Configuration {sid}', fields={
            'name': _s(a.get('name')) or f'Configuration {sid}',
            'asset_type': asset_type_for(type_name),
            'serial_number': _s(a.get('serial-number')),
            'asset_tag': _s(a.get('asset-tag')),
            'manufacturer': _s(a.get('manufacturer-name')),
            'model': _s(a.get('model-name')),
            'hostname': _s(a.get('hostname')),
            'ip_address': clean_ip(a.get('primary-ip')),
            'mac_address': _s(a.get('mac-address'))[:17],
            'os_name': _s(a.get('operating-system-name')),
            'notes': _s(a.get('notes')),
            'custom_fields': {'imported_from': 'itglue', 'itglue_id': str(sid),
                              'configuration_type': _s(type_name)},
        })
        c.links = [l for l in [
            _link('primary_contact', 'contact', a.get('contact-id')),
            _link('location', 'location', a.get('location-id')),
        ] if l]
        if a.get('primary-ip') and not clean_ip(a.get('primary-ip')):
            c.skipped_fields.append('primary-ip (not a valid IP address)')
        return c
    if source_type == 'password':
        c = Canonical('password', _s(a.get('name')) or f'Password {sid}', fields={
            'title': _s(a.get('name')) or f'Password {sid}',
            'username': _s(a.get('username')),
            'url': _s(a.get('url')),
            'notes': _s(a.get('notes')),
        })
        if 'password' in secrets:
            c.secrets['password'] = secrets['password']
        if secrets.get('otp_secret'):
            c.secrets['otp_secret'] = secrets['otp_secret']
        if raw.get('_value_unreadable'):
            c.unavailable = raw['_value_unreadable']
            c.unavailable_kind = 'permission'
        rtype = itglue_resource_type(a.get('resource-type'))
        if rtype and a.get('resource-id'):
            c.links.append(_link('resource', rtype, a.get('resource-id')))
        return c
    if source_type == 'document':
        return Canonical('document', _s(a.get('name')) or f'Document {sid}', fields={
            'title': _s(a.get('name')) or f'Document {sid}',
            'body': a.get('body') or a.get('content') or '',
            'content_type': 'html' if '<' in str(a.get('body') or '') else 'markdown',
        })
    if source_type == 'flexible_asset':
        type_name = _s(a.get('flexible-asset-type-name')) or _s(raw.get('_type_name'))
        kind = itglue_flexible_kind(type_name, overrides)
        name = _s(a.get('name')) or f'Flexible asset {sid}'
        if kind != 'network':
            return Canonical('asset', name, unavailable=(
                f'flexible asset type "{type_name}" has no ClientSt0r mapping'),
                unavailable_kind='not_supported')
        traits = a.get('traits') or {}
        lowered = {str(k).lower(): v for k, v in traits.items()}
        cidr = clean_network(_first(lowered, 'network', 'subnet', 'network-address', 'cidr',
                                    'ip-range', 'address'))
        vlan = _first(lowered, 'vlan', 'vlan-id', 'vlan-number')
        c = Canonical('network', _s(lowered.get('name')) or name, fields={
            'name': (_s(lowered.get('name')) or name)[:100],
            'network': cidr or '',
            'description': _s(_first(lowered, 'description', 'notes')),
            'gateway': clean_ip(_first(lowered, 'gateway', 'default-gateway')),
            'dns_servers': [ip for ip in (clean_ip(x) for x in str(
                _first(lowered, 'dns-servers', 'dns') or '').replace(';', ',').split(',')) if ip],
        })
        if vlan not in (None, ''):
            c.fields['_vlan_number'] = _s(vlan)
        loc = _first(lowered, 'location', 'locations', 'site')
        loc_ids = []
        if isinstance(loc, dict) and loc.get('values'):
            loc = loc['values']
        if isinstance(loc, list):
            loc_ids = [x.get('id') for x in loc if isinstance(x, dict)]
        elif isinstance(loc, dict):
            loc_ids = [loc.get('id')]
        if loc_ids:
            c.links.append(_link('location', 'location', loc_ids[0]))
        if not cidr:
            c.unavailable = 'no valid network address (CIDR) in the source record'
            c.unavailable_kind = 'invalid'
        return c
    if source_type == 'related_item':
        parent = raw.get('_parent') or {}
        dest = itglue_resource_type(a.get('destination-type'))
        c = Canonical('relation', _s(a.get('destination-name')) or f'Related item {sid}', fields={
            'relation_type': 'related', 'notes': _s(a.get('notes')),
        })
        c.links = [l for l in [
            _link('from', parent.get('source_type'), parent.get('source_id')),
            _link('to', dest, a.get('destination-id')) if dest else None,
        ] if l]
        if not dest:
            c.unavailable = f'related item type "{a.get("destination-type")}" is not supported'
            c.unavailable_kind = 'not_supported'
        return c
    if source_type == 'attachment':
        return _attachment_canonical(raw)
    return Canonical('asset', f'{source_type} {sid}', unavailable=f'"{source_type}" is not supported',
                     unavailable_kind='not_supported')


def _attachment_canonical(raw):
    parent = raw.get('_parent') or {}
    meta = raw.get('_file') or {}
    c = Canonical('attachment', meta.get('file_name') or f"Attachment {raw.get('id')}", fields={
        'original_filename': _s(meta.get('file_name'), 255),
        'file_size': meta.get('size') or 0,
        'content_type': _s(meta.get('content_type'), 100),
        'description': _s(meta.get('description')),
    })
    c.links = [l for l in [_link('parent', parent.get('source_type'), parent.get('source_id'))] if l]
    if meta.get('rejected'):
        c.unavailable = meta['rejected']
        c.unavailable_kind = meta.get('rejected_kind') or 'invalid'
    return c


# ---------------------------------------------------------------------------
# Hudu
# ---------------------------------------------------------------------------

HUDU_TYPES = {
    'asset': 'asset', 'article': 'article', 'assetpassword': 'asset_password',
    'asset_password': 'asset_password', 'website': 'website', 'network': 'network',
    'ipaddress': 'ip_address', 'ip_address': 'ip_address', 'company': 'company',
}


def hudu_type(value):
    return HUDU_TYPES.get(_s(value).lower().replace(' ', ''))


def hudu_layout_kind(layout_name, overrides):
    choice = (overrides.get('hudu_layouts') or {}).get(layout_name)
    if choice:
        return choice
    lowered = _s(layout_name).lower()
    if any(w in lowered for w in ('people', 'person', 'contact', 'employee')):
        return 'contact'
    if any(w in lowered for w in ('location', 'site', 'office', 'branch')):
        return 'location'
    return 'asset'


def hudu_fields(raw):
    """Hudu asset fields -> {lowercased label: value} (confidential ones are
    already blanked at staging) plus the list of confidential labels."""
    values, confidential = {}, []
    for f in raw.get('fields') or raw.get('asset_fields') or []:
        if not isinstance(f, dict):
            continue
        label = _s(f.get('label')).lower()
        if not label:
            continue
        if _s(f.get('field_type') or f.get('type')).lower().replace(' ', '') in CONFIDENTIAL_FIELD_TYPES:
            confidential.append(_s(f.get('label')))
            continue
        values[label] = f.get('value')
    return values, confidential


def hudu_canonical(source_type, raw, secrets, overrides):
    sid = raw.get('id')
    if source_type == 'company':
        name = _s(raw.get('name'))
        return Canonical('location', f'{name} (main address)', fields={
            'name': f'{name or "Company"} - main address'[:255],
            'street_address': _s(raw.get('address_line_1')),
            'street_address_2': _s(raw.get('address_line_2')),
            'city': _s(raw.get('city')),
            'state': _s(raw.get('state')),
            'postal_code': _s(raw.get('zip')),
            'country': _s(raw.get('country_name')) or 'United States',
            'phone': _s(raw.get('phone_number')),
            'notes': '',
            'is_primary': True,
        })
    if source_type == 'asset':
        layout = _s(raw.get('asset_layout_name') or raw.get('asset_type'))
        kind = hudu_layout_kind(layout, overrides)
        fv, confidential = hudu_fields(raw)
        name = _s(raw.get('name')) or f'Asset {sid}'
        skipped = [f'{label} (confidential field)' for label in confidential]
        if kind == 'skip':
            return Canonical('asset', name, unavailable=f'layout "{layout}" is set to skip',
                             unavailable_kind='not_supported')
        if kind == 'contact':
            first = _s(_first(fv, 'first name', 'first_name'))
            last = _s(_first(fv, 'last name', 'last_name'))
            if not first and not last:
                first, last = split_name(name)
            return Canonical('contact', name, fields={
                'first_name': first or '(unknown)', 'last_name': last,
                'email': _s(_first(fv, 'email', 'email address', 'e-mail')),
                'phone': _s(_first(fv, 'phone', 'phone number', 'mobile', 'office phone')),
                'title': _s(_first(fv, 'title', 'job title', 'role')),
                'notes': _s(raw.get('notes') or _first(fv, 'notes')),
            }, skipped_fields=skipped)
        if kind == 'location':
            return Canonical('location', name, fields={
                'name': name,
                'street_address': _s(_first(fv, 'address', 'address 1', 'address line 1', 'street')),
                'street_address_2': _s(_first(fv, 'address 2', 'address line 2')),
                'city': _s(_first(fv, 'city')),
                'state': _s(_first(fv, 'state', 'region', 'province')),
                'postal_code': _s(_first(fv, 'zip', 'postal code', 'zip code', 'postcode')),
                'country': _s(_first(fv, 'country')) or 'United States',
                'phone': _s(_first(fv, 'phone', 'phone number')),
                'notes': _s(raw.get('notes') or _first(fv, 'notes')),
                'is_primary': False,
            }, skipped_fields=skipped)
        ip_raw = _first(fv, 'ip address', 'ip', 'primary ip')
        c = Canonical('asset', name, fields={
            'name': name,
            'asset_type': asset_type_for(layout),
            'serial_number': _s(raw.get('primary_serial') or _first(fv, 'serial number', 'serial')),
            'asset_tag': _s(_first(fv, 'asset tag')),
            'manufacturer': _s(raw.get('primary_manufacturer') or _first(fv, 'manufacturer')),
            'model': _s(raw.get('primary_model') or _first(fv, 'model')),
            'hostname': _s(_first(fv, 'hostname', 'host name')),
            'ip_address': clean_ip(ip_raw),
            'mac_address': _s(_first(fv, 'mac address', 'mac'))[:17],
            'os_name': _s(_first(fv, 'operating system', 'os')),
            'notes': _s(raw.get('notes') or ''),
            'custom_fields': {'imported_from': 'hudu', 'hudu_id': str(sid), 'asset_layout': layout,
                              'all_fields': {k: _s(v) for k, v in sorted(fv.items())}},
        }, skipped_fields=skipped)
        if ip_raw and not clean_ip(ip_raw):
            c.skipped_fields.append('ip address (not a valid IP address)')
        return c
    if source_type == 'asset_password':
        c = Canonical('password', _s(raw.get('name')) or f'Password {sid}', fields={
            'title': _s(raw.get('name')) or f'Password {sid}',
            'username': _s(raw.get('username')),
            'url': _s(raw.get('url')),
            'notes': _s(raw.get('description')),
        })
        if 'password' in secrets:
            c.secrets['password'] = secrets['password']
        if secrets.get('otp_secret'):
            c.secrets['otp_secret'] = secrets['otp_secret']
        ptype = hudu_type(raw.get('passwordable_type'))
        if ptype and raw.get('passwordable_id'):
            c.links.append(_link('resource', ptype, raw.get('passwordable_id')))
        return c
    if source_type == 'article':
        return Canonical('document', _s(raw.get('name')) or f'Article {sid}', fields={
            'title': _s(raw.get('name')) or f'Article {sid}',
            'body': raw.get('content') or '',
            'content_type': 'html' if '<' in str(raw.get('content') or '') else 'markdown',
        })
    if source_type == 'website':
        url = _s(raw.get('name') or raw.get('url'))
        if url and '://' not in url:
            url = 'https://' + url
        c = Canonical('website', url or f'Website {sid}', fields={
            'name': _s(raw.get('name')) or url, 'url': url[:500],
        })
        if not url:
            c.unavailable, c.unavailable_kind = 'website has no address', 'invalid'
        return c
    if source_type == 'network':
        cidr = clean_network(raw.get('address'))
        c = Canonical('network', _s(raw.get('name')) or _s(raw.get('address')), fields={
            'name': (_s(raw.get('name')) or _s(raw.get('address')) or f'Network {sid}')[:100],
            'network': cidr or '',
            'description': _s(raw.get('description')),
            'gateway': clean_ip(raw.get('gateway')),
            'dns_servers': [],
        })
        vlan = raw.get('_vlan_number')
        if vlan not in (None, ''):
            c.fields['_vlan_number'] = _s(vlan)
        if raw.get('location_id'):
            c.links.append(_link('location', 'asset', raw.get('location_id')))
        if not cidr:
            c.unavailable, c.unavailable_kind = 'no valid network address (CIDR)', 'invalid'
        return c
    if source_type == 'ip_address':
        ip = clean_ip(raw.get('address'))
        status = _s(raw.get('status')).lower()
        status = {'assigned': 'assigned', 'reserved': 'reserved', 'dhcp': 'dhcp'}.get(status, 'available')
        c = Canonical('ip_address', _s(raw.get('address')) or f'IP {sid}', fields={
            'ip_address': ip or '', 'status': status,
            'hostname': _s(raw.get('fqdn')), 'description': _s(raw.get('description')),
            'notes': _s(raw.get('notes')),
        })
        c.links = [l for l in [_link('subnet', 'network', raw.get('network_id')),
                               _link('asset', 'asset', raw.get('asset_id'))] if l]
        if not ip:
            c.unavailable, c.unavailable_kind = 'not a valid IP address', 'invalid'
        return c
    if source_type == 'relation':
        ft, tt = hudu_type(raw.get('fromable_type')), hudu_type(raw.get('toable_type'))
        c = Canonical('relation', f"{raw.get('fromable_type')} {raw.get('fromable_id')} -> "
                                  f"{raw.get('toable_type')} {raw.get('toable_id')}",
                      fields={'relation_type': 'related', 'notes': _s(raw.get('description'))})
        c.links = [l for l in [_link('from', ft, raw.get('fromable_id')) if ft else None,
                               _link('to', tt, raw.get('toable_id')) if tt else None] if l]
        if not ft or not tt:
            c.unavailable = 'relation end type is not supported'
            c.unavailable_kind = 'not_supported'
        return c
    if source_type == 'upload':
        return _attachment_canonical(raw)
    return Canonical('asset', f'{source_type} {sid}', unavailable=f'"{source_type}" is not supported',
                     unavailable_kind='not_supported')


def canonical_for(source_system, source_type, raw, secrets, overrides=None):
    overrides = overrides or {}
    if source_system == 'itglue':
        return itglue_canonical(source_type, raw, secrets or {}, overrides)
    if source_system == 'hudu':
        return hudu_canonical(source_type, raw, secrets or {}, overrides)
    raise ValueError(f'unknown source system {source_system}')
