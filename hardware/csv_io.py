"""CSV export and validated, previewed, all-or-nothing import."""
from __future__ import annotations

import csv
import io
import ipaddress

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from monitoring.models import Rack

from . import connectors as C
from . import services as S
from .models import Cable, DevicePort, HardwareDevice, HardwareModel

DEVICE_COLUMNS = ['name', 'hostname', 'manufacturer', 'model', 'serial_number', 'asset_tag', 'status', 'site',
                  'room', 'rack', 'position', 'face', 'ip_address', 'platform', 'firmware_version', 'install_date',
                  'warranty_expiry', 'notes']
CABLE_COLUMNS = ['cable_id', 'device_a', 'port_a', 'device_b', 'port_b', 'cable_type', 'color', 'length',
                 'length_unit', 'label_a', 'label_b']


def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, '') for c in cols])
    return buf.getvalue()


def export_devices(org):
    rows = []
    for d in HardwareDevice.objects.filter(organization=org).select_related(
            'asset', 'hardware_model__manufacturer', 'site'):
        a, rp = d.asset, d.rack_placement
        rows.append({'name': a.name, 'hostname': a.hostname, 'manufacturer': d.hardware_model.manufacturer.name,
                     'model': d.hardware_model.model, 'serial_number': a.serial_number, 'asset_tag': a.asset_tag,
                     'status': d.status, 'site': d.site.name if d.site_id else '', 'room': d.room,
                     'rack': rp.rack.name if rp else '', 'position': rp.start_unit if rp else '',
                     'face': rp.face if rp else '', 'ip_address': a.ip_address or '', 'platform': d.platform,
                     'firmware_version': a.firmware_version, 'install_date': d.install_date or '',
                     'warranty_expiry': a.warranty_expiry or '', 'notes': a.notes})
    return _csv(rows, DEVICE_COLUMNS)


def export_cables(org):
    rows = []
    for c in Cable.objects.filter(organization=org).prefetch_related('terminations__port__device__asset'):
        ends = c.ends()
        for ta in ends['A'] or [None]:
            for tb in ends['B'] or [None]:
                rows.append({'cable_id': c.label, 'device_a': ta.port.device.asset.name if ta else '',
                             'port_a': ta.port.name if ta else '', 'device_b': tb.port.device.asset.name if tb else '',
                             'port_b': tb.port.name if tb else '', 'cable_type': c.cable_type, 'color': c.color,
                             'length': c.length or '', 'length_unit': c.length_unit, 'label_a': c.label_a,
                             'label_b': c.label_b})
    return _csv(rows, CABLE_COLUMNS)


def _find_model(manufacturer, model):
    qs = HardwareModel.objects.filter(kind=HardwareModel.KIND_DEVICE, is_active=True)
    for q in (Q(manufacturer__name__iexact=manufacturer, model__iexact=model),
              Q(manufacturer__name__iexact=manufacturer, part_number__iexact=model),
              Q(manufacturer__name__iexact=manufacturer, slug__iexact=model)):
        hits = list(qs.filter(q)[:2])
        if len(hits) == 1:
            return hits[0], ''
        if len(hits) > 1:
            return None, f'"{manufacturer} {model}" matches more than one catalog model; use the exact model name.'
    return None, f'"{manufacturer} {model}" is not in the catalog. Request it, or use a Generic template.'


def validate(org, what, text):
    reader = csv.DictReader(io.StringIO(text))
    cols = DEVICE_COLUMNS if what == 'devices' else CABLE_COLUMNS
    missing = [c for c in (('name', 'manufacturer', 'model') if what == 'devices' else
                           ('device_a', 'port_a', 'device_b', 'port_b')) if c not in (reader.fieldnames or [])]
    if missing:
        return [{'line': 1, 'data': {}, 'errors': [f'Missing column(s): {", ".join(missing)}. Expected: '
                                                   f'{", ".join(cols)}']}]
    out = []
    seen = set()
    used_ports = set()
    for i, raw in enumerate(reader, start=2):
        if i > 5001:
            out.append({'line': i, 'data': {}, 'errors': ['More than 5000 rows; split the file.']})
            break
        row = {k: (raw.get(k) or '').strip() for k in cols}
        errors = []
        if what == 'devices':
            if not row['name']:
                errors.append('Name is required.')
            elif row['name'].lower() in seen:
                errors.append(f'Duplicate name {row["name"]} in this file.')
            seen.add(row['name'].lower())
            from assets.models import Asset
            if row['name'] and Asset.objects.filter(organization=org, name__iexact=row['name'],
                                                    hardware__isnull=False).exists():
                errors.append(f'{row["name"]} already exists at this client.')
            hm, why = _find_model(row['manufacturer'], row['model'])
            if hm is None:
                errors.append(why)
            else:
                row['_model'] = hm.pk
            if row['status'] and row['status'] not in dict(HardwareDevice.STATUS_CHOICES):
                errors.append(f'Unknown status "{row["status"]}".')
            if row['ip_address']:
                try:
                    ipaddress.ip_address(row['ip_address'])
                except ValueError:
                    errors.append(f'"{row["ip_address"]}" is not an IP address.')
            if row['site']:
                from locations.models import Location
                s = Location.objects.filter(organization=org, name__iexact=row['site']).first()
                if s is None:
                    errors.append(f'Site "{row["site"]}" does not exist for this client.')
                else:
                    row['_site'] = s.pk
            if row['rack']:
                r = Rack.objects.filter(organization=org, name__iexact=row['rack']).first()
                if r is None:
                    errors.append(f'Rack "{row["rack"]}" does not exist for this client.')
                elif not row['position'].isdigit():
                    errors.append('A rack needs a numeric position (lowest U).')
                else:
                    row['_rack'] = r.pk
                if row['face'] and row['face'] not in ('front', 'rear'):
                    errors.append('Face must be front or rear.')
            for f in ('install_date', 'warranty_expiry'):
                if row[f]:
                    import datetime
                    try:
                        datetime.date.fromisoformat(row[f])
                    except ValueError:
                        errors.append(f'{f} must be YYYY-MM-DD.')
        else:
            ports = []
            for side in ('a', 'b'):
                dname, pname = row[f'device_{side}'], row[f'port_{side}']
                p = DevicePort.objects.filter(organization=org, device__asset__name__iexact=dname, name__iexact=pname,
                                              breakout_parent__isnull=True).first()
                if p is None:
                    p = DevicePort.objects.filter(organization=org, device__asset__name__iexact=dname,
                                                  tech_label__iexact=pname).first()
                if p is None:
                    errors.append(f'Port {dname} / {pname} not found.')
                elif p.pk in used_ports:
                    errors.append(f'{dname} / {pname} appears twice in this file.')
                else:
                    used_ports.add(p.pk)
                    ports.append(p)
                    row[f'_{side}'] = p.pk
            if len(ports) == 2:
                try:
                    S.validate_endpoints(org, [ports[0]], [ports[1]], row['cable_type'])
                except ValidationError as e:
                    errors.extend(e.messages)
            if row['cable_type'] and row['cable_type'] not in C.CABLE_TYPE_KEYS:
                errors.append(f'Unknown cable type "{row["cable_type"]}". Use one of: '
                              + ', '.join(sorted(C.CABLE_TYPE_KEYS)))
            if row['cable_id']:
                if row['cable_id'].lower() in seen:
                    errors.append(f'Cable ID {row["cable_id"]} appears twice.')
                seen.add(row['cable_id'].lower())
                if Cable.objects.filter(organization=org, label=row['cable_id']).exists():
                    errors.append(f'Cable ID {row["cable_id"]} already exists.')
        out.append({'line': i, 'data': row, 'errors': errors})
    return out


def apply(org, what, rows, user):
    """Write validated rows. Re-validates inside one transaction; any error rolls everything back."""
    from locations.models import Location
    n = 0
    with transaction.atomic():
        if what == 'devices':
            for r in rows:
                hm = HardwareModel.objects.get(pk=r['_model'])
                site = Location.objects.filter(pk=r.get('_site'), organization=org).first() if r.get('_site') else None
                d = S.create_device(org, hm, r['name'], user=user, site=site, room=r['room'][:100],
                                    status=r['status'] or 'active', platform=r['platform'][:100],
                                    install_date=r['install_date'] or None,
                                    hostname=r['hostname'] or r['name'], serial_number=r['serial_number'],
                                    asset_tag=r['asset_tag'], ip_address=r['ip_address'] or None,
                                    firmware_version=r['firmware_version'], notes=r['notes'],
                                    warranty_expiry=r['warranty_expiry'] or None)
                if r.get('_rack'):
                    S.place_in_rack(d, Rack.objects.get(pk=r['_rack'], organization=org), int(r['position']),
                                    r['face'] or 'front', user=user)
                n += 1
        else:
            for r in rows:
                a = DevicePort.objects.get(pk=r['_a'], organization=org)
                b = DevicePort.objects.get(pk=r['_b'], organization=org)
                fields = {'label': r['cable_id'], 'cable_type': r['cable_type'], 'color': r['color'][:7],
                          'label_a': r['label_a'], 'label_b': r['label_b']}
                if r['length']:
                    from decimal import Decimal, InvalidOperation
                    try:
                        fields['length'] = Decimal(r['length'])
                    except InvalidOperation:
                        raise ValidationError(f'Line with {r["cable_id"]}: length is not a number.')
                    fields['length_unit'] = r['length_unit'] or 'm'
                S.connect(org, [a], [b], user=user, **fields)
                n += 1
    return n
