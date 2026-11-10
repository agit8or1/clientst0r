"""Per-customer inventory export: metadata only, never secrets.

Each section is included only when the user holds its view permission in
that customer (``accounts.permission_utils.has_perm_for_org``; vault entries
additionally go through ``vault.permissions.visible_passwords``). Password
rows carry no password, OTP seed or notes - only whether an OTP is set.
"""
from __future__ import annotations

import csv
import io

from django.utils import timezone

SECTIONS = [
    # (section, permission)
    ('locations', 'assets_view'),
    ('contacts', 'assets_view'),
    ('assets', 'assets_view'),
    ('networks', 'monitoring_view'),
    ('ip_addresses', 'monitoring_view'),
    ('documents', 'docs_view'),
    ('passwords', 'vault_view'),
]

CSV_COLUMNS = ['section', 'id', 'name', 'type', 'detail', 'updated_at']


def allowed_sections(user, org):
    from accounts.permission_utils import has_perm_for_org
    return [s for s, perm in SECTIONS if has_perm_for_org(user, org, perm)]


def _iso(dt):
    return dt.isoformat() if dt else ''


def _rows(user, org, section):
    if section == 'locations':
        from locations.models import Location
        for l in Location.objects.filter(organization=org).order_by('name'):
            yield {'id': l.pk, 'name': l.name, 'type': l.location_type,
                   'detail': ', '.join(filter(None, [l.street_address, l.city, l.state, l.postal_code,
                                                     l.country])),
                   'is_primary': l.is_primary, 'updated_at': _iso(l.updated_at)}
    elif section == 'contacts':
        from assets.models import Contact
        for c in Contact.objects.filter(organization=org).order_by('last_name', 'first_name'):
            yield {'id': c.pk, 'name': c.full_name, 'type': c.title, 'detail': c.email,
                   'phone': c.phone, 'updated_at': _iso(c.updated_at)}
    elif section == 'assets':
        from assets.models import Asset
        for a in Asset.objects.filter(organization=org).order_by('name'):
            yield {'id': a.pk, 'name': a.name, 'type': a.asset_type,
                   'detail': ' '.join(filter(None, [a.manufacturer, a.model, a.serial_number])),
                   'hostname': a.hostname, 'ip_address': a.ip_address or '',
                   'primary_contact_id': a.primary_contact_id, 'updated_at': _iso(a.updated_at)}
    elif section == 'networks':
        from monitoring.models import Subnet
        for s in Subnet.objects.filter(organization=org).select_related('vlan').order_by('network'):
            yield {'id': s.pk, 'name': s.name, 'type': 'subnet', 'detail': s.network,
                   'gateway': s.gateway or '', 'vlan': s.vlan.vlan_id if s.vlan else '',
                   'location': s.location, 'updated_at': _iso(s.updated_at)}
    elif section == 'ip_addresses':
        from monitoring.models import IPAddress
        for ip in IPAddress.objects.filter(subnet__organization=org).order_by('subnet_id', 'ip_address'):
            yield {'id': ip.pk, 'name': ip.ip_address, 'type': ip.status, 'detail': ip.hostname,
                   'subnet_id': ip.subnet_id, 'asset_id': ip.asset_id, 'updated_at': _iso(ip.updated_at)}
    elif section == 'documents':
        from docs.models import Document
        for d in Document.objects.filter(organization=org).order_by('title'):
            yield {'id': d.pk, 'name': d.title, 'type': d.content_type,
                   'detail': 'published' if d.is_published else 'unpublished',
                   'updated_at': _iso(d.updated_at)}
    elif section == 'passwords':
        from vault.models import Password
        from vault.permissions import visible_passwords
        qs = visible_passwords(user, Password.objects.filter(organization=org, is_personal=False))
        for p in qs.order_by('title'):
            yield {'id': p.pk, 'name': p.title, 'type': p.password_type, 'detail': p.username,
                   'url': p.url, 'has_otp': bool(p.otp_secret), 'updated_at': _iso(p.updated_at)}


def export_inventory(user, org):
    sections = allowed_sections(user, org)
    data = {s: list(_rows(user, org, s)) for s in sections}
    return {
        'generated_at': timezone.now().isoformat(),
        'customer': {'id': org.pk, 'name': org.name},
        'sections': sections,
        'omitted_sections': [s for s, _ in SECTIONS if s not in sections],
        'counts': {s: len(rows) for s, rows in data.items()},
        'data': data,
        'note': 'Metadata only. Passwords, OTP secrets and secure notes are never exported.',
    }


def inventory_csv(export):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction='ignore')
    writer.writeheader()
    for section in export['sections']:
        for row in export['data'][section]:
            writer.writerow(dict(row, section=section))
    return buf.getvalue()
