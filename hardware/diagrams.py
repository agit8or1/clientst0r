"""
Diagrams generated from inventory records.

Nothing here draws a link the records don't contain. A cable is drawn when a
``Cable`` joins two ports; a VLAN edge when a port is configured with that
VLAN. Where documentation stops (a patch-panel front port is cabled but its
rear has no cable, a cable has no far end), the diagram shows a dashed
"undocumented" stub instead of guessing where it goes.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

from django.db.models import Q
from django.urls import reverse

from . import connectors as C
from .layout import U_MM, get_layout
from .models import Cable, CableTermination, DevicePort, HardwareDevice, PortMapping, PortVLAN
from .payloads import vlan_color
from .renderer import _f, esc, finish_defs, finish_for, render_face_body, shared_defs

CATEGORY_RANK = {
    'firewall': 0, 'router': 0, 'wireless_controller': 1, 'switch': 1, 'console_server': 2,
    'patch_panel': 2, 'fiber_panel': 2, 'server': 2, 'storage': 2, 'storage_shelf': 2, 'blade_chassis': 2,
    'ups': 2, 'pdu': 2, 'wall_jack': 4, 'outlet': 4, 'access_point': 5, 'workstation': 5, 'phone': 5,
    'camera': 5,
}


def _devices(org, site_id=None):
    qs = HardwareDevice.objects.filter(organization=org).select_related('asset', 'hardware_model__manufacturer', 'site')
    if site_id:
        qs = qs.filter(site_id=site_id)
    return list(qs)


# --------------------------------------------------------------------------- connectivity

def connectivity_data(org, site_id=None):
    devices = _devices(org, site_id)
    ids = {d.pk for d in devices}
    by_id = {d.pk: d for d in devices}
    terms = list(CableTermination.objects.filter(organization=org, port__device_id__in=ids)
                 .select_related('port', 'cable'))
    cable_ends = defaultdict(lambda: {'A': [], 'B': []})
    for t in CableTermination.objects.filter(cable_id__in={t.cable_id for t in terms}).select_related('port'):
        cable_ends[t.cable_id][t.end].append(t)
    edges = {}
    stubs = defaultdict(int)
    for cid, ends in cable_ends.items():
        a, b = ends['A'], ends['B']
        if not a or not b:
            only = (a or b)[0]
            stubs[only.port.device_id] += 1
            continue
        for ta in a:
            for tb in b:
                da, db = ta.port.device_id, tb.port.device_id
                if da not in ids or db not in ids:
                    continue
                key = tuple(sorted((da, db)))
                e = edges.setdefault(key, {'source': f'device:{by_id[key[0]].public_id}',
                                           'target': f'device:{by_id[key[1]].public_id}', 'cables': []})
                c = ta.cable
                e['cables'].append({'id': c.pk, 'label': c.label or f'#{c.pk}', 'type': c.cable_type,
                                    'color': c.color, 'a': ta.port.name if da == key[0] else tb.port.name,
                                    'b': tb.port.name if da == key[0] else ta.port.name, 'status': c.status})
    # Passive ports whose other side is undocumented
    for m in PortMapping.objects.filter(organization=org, device_id__in=ids).select_related(
            'front_port__cable_termination', 'rear_port__cable_termination'):
        f_c = hasattr(m.front_port, 'cable_termination')
        r_c = hasattr(m.rear_port, 'cable_termination')
        if f_c != r_c:
            stubs[m.device_id] += 1
    nodes = []
    for d in devices:
        hm = d.hardware_model
        nodes.append({'key': f'device:{d.public_id}', 'id': d.pk, 'name': d.asset.name, 'model': str(hm),
                      'category': hm.category, 'category_label': hm.get_category_display(),
                      'rank': CATEGORY_RANK.get(hm.category, 4), 'site': d.site.name if d.site_id else '',
                      'url': reverse('hardware:device_detail', args=[d.pk]),
                      'thumb': reverse('hardware:model_art', args=[hm.pk, 'front']) + '?v=thumb',
                      'undocumented': stubs.get(d.pk, 0), 'status': d.status})
    for e in edges.values():
        e['count'] = len(e['cables'])
    return {'nodes': nodes, 'edges': list(edges.values())}


def vlan_data(org, site_id=None):
    devices = _devices(org, site_id)
    ids = {d.pk for d in devices}
    by_id = {d.pk: d for d in devices}
    from monitoring.models import VLAN
    vlans = {v.pk: v for v in VLAN.objects.filter(organization=org).select_related('vlan_group')}
    rel = defaultdict(lambda: {'untagged': 0, 'tagged': 0, 'voice': 0, 'ports': []})
    for p in DevicePort.objects.filter(organization=org, device_id__in=ids).filter(
            Q(untagged_vlan__isnull=False) | Q(voice_vlan__isnull=False)):
        if p.untagged_vlan_id:
            r = rel[(p.device_id, p.untagged_vlan_id)]
            r['untagged'] += 1
            r['ports'].append(p.name)
        if p.voice_vlan_id:
            r = rel[(p.device_id, p.voice_vlan_id)]
            r['voice'] += 1
            r['ports'].append(p.name)
    for m in PortVLAN.objects.filter(port__organization=org, port__device_id__in=ids).select_related('port'):
        r = rel[(m.port.device_id, m.vlan_id)]
        r['tagged'] += 1
        r['ports'].append(m.port.name)
    used_devices = {d for d, _ in rel}
    nodes = [{'key': f'vlan:{v.pk}', 'kind': 'vlan', 'vid': v.vlan_id, 'name': f'VLAN {v.vlan_id} {v.name}',
              'color': vlan_color(v), 'group': v.vlan_group.name if v.vlan_group_id else '', 'rank': 0}
             for v in sorted(vlans.values(), key=lambda v: v.vlan_id)]
    for d in devices:
        if d.pk in used_devices:
            nodes.append({'key': f'device:{d.public_id}', 'kind': 'device', 'id': d.pk, 'name': d.asset.name,
                          'model': str(d.hardware_model), 'category': d.hardware_model.category,
                          'category_label': d.hardware_model.get_category_display(),
                          'rank': 1 + (CATEGORY_RANK.get(d.hardware_model.category, 4) // 2),
                          'url': reverse('hardware:device_detail', args=[d.pk]),
                          'thumb': reverse('hardware:model_art', args=[d.hardware_model_id, 'front']) + '?v=thumb'})
    edges = []
    for (did, vid), r in rel.items():
        v = vlans.get(vid)
        if v is None:
            continue
        mode = 'untagged' if r['untagged'] else ('tagged' if r['tagged'] else 'voice')
        edges.append({'source': f'device:{by_id[did].public_id}', 'target': f'vlan:{vid}', 'mode': mode,
                      'untagged': r['untagged'], 'tagged': r['tagged'], 'voice': r['voice'],
                      'color': vlan_color(v), 'ports': r['ports'][:20], 'count': len(r['ports'])})
    return {'nodes': nodes, 'edges': edges}


def auto_positions(nodes, saved=None, edges=None):
    """Layered default positions; saved positions always win.

    Rows are ordered by rank (firewalls at the top, endpoints at the bottom).
    Within a row, nodes are placed under the average position of the nodes
    they connect to above them (barycenter), and a node is nudged sideways
    when an edge from a higher row would otherwise pass straight through it.
    """
    saved = saved or {}
    edges = edges or []
    nbr = defaultdict(set)
    for e in edges:
        nbr[e['source']].add(e['target'])
        nbr[e['target']].add(e['source'])
    rows = defaultdict(list)
    for n in nodes:
        rows[n.get('rank', 4)].append(n)
    rank_of = {n['key']: n.get('rank', 4) for n in nodes}
    pos = {}
    GAP_X, GAP_Y, CX = 240, 150, 600
    for rank, items in sorted(rows.items()):
        def bary(n):
            xs = [pos[m]['x'] for m in nbr[n['key']] if m in pos]
            return (sum(xs) / len(xs)) if xs else CX
        items.sort(key=lambda n: (bary(n), n['name']))
        width = (len(items) - 1) * GAP_X
        start = (sum(bary(n) for n in items) / len(items)) - width / 2 if items else CX
        y = 80 + rank * GAP_Y
        for i, n in enumerate(items):
            pos[n['key']] = {'x': start + i * GAP_X, 'y': y}
        # An edge from a node above to a node in a later row runs (roughly)
        # straight down from the upper node; keep this row's nodes off it.
        skipping = [pos[a_key]['x'] for a_key in pos if rank_of.get(a_key, 0) < rank
                    and any(rank_of.get(b_key, 0) > rank for b_key in nbr[a_key])]
        taken = []
        for n in items:
            p = pos[n['key']]
            for _ in range(6):
                if any(abs(x - p['x']) < 60 for x in skipping) or any(abs(t - p['x']) < GAP_X - 1 for t in taken):
                    p['x'] += GAP_X / 2
                else:
                    break
            taken.append(p['x'])
    for k, v in saved.items():
        if k in pos and isinstance(v, dict) and 'x' in v and 'y' in v:
            try:
                pos[k] = {'x': float(v['x']), 'y': float(v['y'])}
            except (TypeError, ValueError):
                pass
    return pos


# --------------------------------------------------------------------------- export drawing

NODE_W, NODE_H = 190, 54


def _frame(title, subtitle, legend, W, H, body):
    date = datetime.date.today().isoformat()
    leg = []
    lx = 20
    for sw, text in legend:
        leg.append(f'<g transform="translate({lx} {H - 26})">{sw}<text x="26" y="12" font-size="11" '
                   f'font-family="DejaVu Sans, Arial, sans-serif" fill="#333">{esc(text)}</text></g>')
        lx += 30 + 7 * len(text)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(W)}" height="{_f(H)}" viewBox="0 0 {_f(W)} {_f(H)}">'
            f'<rect width="{_f(W)}" height="{_f(H)}" fill="#ffffff"/>'
            f'<text x="20" y="30" font-size="18" font-weight="700" font-family="DejaVu Sans, Arial, sans-serif" '
            f'fill="#111">{esc(title)}</text>'
            f'<text x="20" y="50" font-size="12" font-family="DejaVu Sans, Arial, sans-serif" fill="#555">'
            f'{esc(subtitle)} · generated {date} from documented records</text>'
            f'{body}<line x1="0" y1="{H - 40}" x2="{W}" y2="{H - 40}" stroke="#ddd"/>{"".join(leg)}</svg>')


def graph_svg(data, positions, title, subtitle, kind='connectivity'):
    nodes = {n['key']: n for n in data['nodes']}
    if not nodes:
        return _frame(title, subtitle, [], 600, 220,
                      '<text x="20" y="110" font-size="13" font-family="sans-serif" fill="#666">'
                      'No documented connections yet.</text>')
    xs = [positions[k]['x'] for k in nodes]
    ys = [positions[k]['y'] for k in nodes]
    ox, oy = min(xs) - NODE_W / 2 - 40, min(ys) - NODE_H / 2 - 70
    W = max(xs) - min(xs) + NODE_W + 80
    H = max(ys) - min(ys) + NODE_H + 170
    P = lambda k: (positions[k]['x'] - ox, positions[k]['y'] - oy)
    body = []
    for e in data['edges']:
        if e['source'] not in nodes or e['target'] not in nodes:
            continue
        (x1, y1), (x2, y2) = P(e['source']), P(e['target'])
        if kind == 'vlan':
            dash = '' if e['mode'] == 'untagged' else ' stroke-dasharray="6 4"'
            body.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" stroke="{e["color"]}" '
                        f'stroke-width="2"{dash}/>')
            lab = f'{e["untagged"]}U/{e["tagged"]}T' + (f'/{e["voice"]}V' if e['voice'] else '')
        else:
            body.append(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" stroke="#4a6fa5" '
                        f'stroke-width="{min(6, 1.5 + e["count"] * 0.5)}"/>')
            first = e['cables'][0]
            lab = f'{first["a"]} ⇄ {first["b"]}' if e['count'] == 1 else f'{e["count"]} cables'
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        body.append(f'<rect x="{_f(mx - 4 * len(lab) - 4)}" y="{_f(my - 9)}" width="{_f(8 * len(lab) + 8)}" height="16" '
                    f'rx="3" fill="#fff" fill-opacity="0.9" stroke="#ccc" stroke-width="0.5"/>'
                    f'<text x="{_f(mx)}" y="{_f(my + 3)}" font-size="10" text-anchor="middle" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" fill="#333">{esc(lab)}</text>')
    for k, n in nodes.items():
        x, y = P(k)
        if n.get('kind') == 'vlan':
            body.append(f'<rect x="{_f(x - 80)}" y="{_f(y - 18)}" width="160" height="36" rx="18" fill="{n["color"]}"/>'
                        f'<text x="{_f(x)}" y="{_f(y + 4)}" font-size="12" font-weight="700" text-anchor="middle" '
                        f'font-family="DejaVu Sans, Arial, sans-serif" fill="#fff">{esc(n["name"][:24])}</text>')
            continue
        stroke = '#c0392b' if n.get('undocumented') else '#667'
        body.append(f'<rect x="{_f(x - NODE_W / 2)}" y="{_f(y - NODE_H / 2)}" width="{NODE_W}" height="{NODE_H}" rx="6" '
                    f'fill="#f7f9fb" stroke="{stroke}" stroke-width="1.2"/>'
                    f'<text x="{_f(x)}" y="{_f(y - 6)}" font-size="13" font-weight="700" text-anchor="middle" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" fill="#111">{esc(n["name"][:26])}</text>'
                    f'<text x="{_f(x)}" y="{_f(y + 10)}" font-size="9.5" text-anchor="middle" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" fill="#555">{esc(n["model"][:36])}</text>'
                    f'<text x="{_f(x)}" y="{_f(y + 22)}" font-size="9" text-anchor="middle" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" fill="#777">{esc(n.get("category_label", ""))}</text>')
        if n.get('undocumented'):
            body.append(f'<line x1="{_f(x + NODE_W / 2)}" y1="{_f(y)}" x2="{_f(x + NODE_W / 2 + 34)}" y2="{_f(y)}" '
                        f'stroke="#c0392b" stroke-width="1.5" stroke-dasharray="4 3"/>'
                        f'<text x="{_f(x + NODE_W / 2 + 4)}" y="{_f(y - 5)}" font-size="9" '
                        f'font-family="DejaVu Sans, Arial, sans-serif" fill="#c0392b">{n["undocumented"]} undocumented</text>')
    if kind == 'vlan':
        legend = [('<line x1="0" y1="8" x2="20" y2="8" stroke="#333" stroke-width="2"/>', 'native / untagged'),
                  ('<line x1="0" y1="8" x2="20" y2="8" stroke="#333" stroke-width="2" stroke-dasharray="6 4"/>',
                   'tagged or voice'),
                  ('<text x="0" y="12" font-size="10" font-family="sans-serif">U/T/V</text>', 'port counts')]
    else:
        legend = [('<line x1="0" y1="8" x2="20" y2="8" stroke="#4a6fa5" stroke-width="3"/>', 'documented cable(s)'),
                  ('<line x1="0" y1="8" x2="20" y2="8" stroke="#c0392b" stroke-width="1.5" stroke-dasharray="4 3"/>',
                   'path continues undocumented'),
                  ('<rect x="0" y="0" width="20" height="16" rx="3" fill="#f7f9fb" stroke="#667"/>', 'device')]
    return _frame(title, subtitle, legend, W, H, f'<g transform="translate(0 0)">{"".join(body)}</g>')


# --------------------------------------------------------------------------- rack elevation

RAIL = 34.0


def rack_svg(rack, face='front', for_export=False, title_prefix=''):
    """One face of a rack, drawn from RackDevice placements and catalog artwork."""
    from monitoring.models import RackDevice
    units = rack.units
    W = 482.6 + 2 * RAIL
    top = 16.0
    H = units * U_MM + 2 * top
    finish_cache = {}
    defs = [shared_defs()]
    body = [f'<rect x="0" y="0" width="{_f(W)}" height="{_f(H)}" rx="3" fill="#2b2f34"/>',
            f'<rect x="{_f(RAIL - 6)}" y="{_f(top - 4)}" width="{_f(482.6 + 12)}" height="{_f(units * U_MM + 8)}" '
            f'fill="#15171a"/>']
    for u in range(1, units + 1):
        y = top + (units - u) * U_MM
        body.append(f'<line x1="{_f(RAIL)}" y1="{_f(y)}" x2="{_f(RAIL + 482.6)}" y2="{_f(y)}" stroke="#2c3035" '
                    f'stroke-width="0.4"/>'
                    f'<text x="{_f(RAIL - 10)}" y="{_f(y + U_MM / 2 + 2.5)}" font-size="7" text-anchor="middle" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" fill="#9aa3ab">{u}</text>'
                    f'<text x="{_f(W - RAIL + 10)}" y="{_f(y + U_MM / 2 + 2.5)}" font-size="7" text-anchor="middle" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" fill="#9aa3ab">{u}</text>')
    placements = list(RackDevice.objects.filter(rack=rack, board_position_x__isnull=True)
                      .select_related('asset__hardware__hardware_model__manufacturer'))
    for i, rd in enumerate(placements):
        own_face = rd.face == face
        if not own_face and not rd.is_full_depth:
            y = top + (units - rd.end_unit) * U_MM
            body.append(f'<rect x="{_f(RAIL)}" y="{_f(y + 0.5)}" width="482.6" height="{_f(rd.units * U_MM - 1)}" '
                        f'fill="none" stroke="#6c757d" stroke-dasharray="4 3" stroke-width="0.6"/>'
                        f'<text x="{_f(RAIL + 241)}" y="{_f(y + rd.units * U_MM / 2 + 2)}" font-size="6" '
                        f'text-anchor="middle" fill="#8f979e" font-family="DejaVu Sans, Arial, sans-serif">'
                        f'{esc(rd.name)} (mounted {rd.face}, half depth)</text>')
            continue
        y = top + (units - rd.end_unit) * U_MM
        hw = getattr(rd.asset, 'hardware', None) if rd.asset_id else None
        drawn = False
        if hw is not None:
            hm = hw.hardware_model
            lay = get_layout(hm)
            show = 'front' if own_face else 'rear'
            fdata = lay.faces.get(show)
            if fdata and fdata.get('rack'):
                uid = f'r{i}'
                f = finish_for(hm)
                defs.append(finish_defs(f, uid, filters=False))
                sy = (rd.units * U_MM) / float(fdata['height'])
                inner = render_face_body(hm, show, fdata, uid=uid, labels=not for_export or True, filters=False,
                                         finish=f)
                href = reverse('hardware:device_detail', args=[hw.pk])
                body.append(f'<a href="{href}" class="hw-rack-dev" data-device="{hw.pk}">'
                            f'<title>{esc(rd.name)} — {esc(hm)} (U{rd.start_unit}–U{rd.end_unit}, {show} face)</title>'
                            f'<g transform="translate({_f(RAIL)} {_f(y)}) scale(1 {sy:.5f})">{inner}</g></a>')
                drawn = True
        if not drawn:
            color = rd.color or '#0d6efd'
            href = reverse('hardware:device_detail', args=[hw.pk]) if hw else reverse(
                'monitoring:rack_detail', args=[rack.pk])
            body.append(f'<a href="{href}"><rect x="{_f(RAIL + 0.5)}" y="{_f(y + 0.5)}" width="481.6" '
                        f'height="{_f(rd.units * U_MM - 1)}" rx="1.5" fill="{esc(color)}" fill-opacity="0.85" '
                        f'stroke="#000" stroke-opacity="0.4"/>'
                        f'<text x="{_f(RAIL + 241)}" y="{_f(y + rd.units * U_MM / 2 + 3)}" font-size="9" '
                        f'text-anchor="middle" font-family="DejaVu Sans, Arial, sans-serif" fill="#fff">'
                        f'{esc(rd.name)}{" (" + ("rear view" if not own_face else "no artwork") + ")" if hw else ""}'
                        f'</text></a>')
        # On the page the name follows the theme (class), in exports it is dark on white.
        name_fill = 'fill="#333"' if for_export else 'class="hw-rack-name"'
        body.append(f'<text x="{_f(W + 6)}" y="{_f(y + rd.units * U_MM / 2 + 3)}" font-size="8" '
                    f'font-family="DejaVu Sans, Arial, sans-serif" {name_fill}>{esc(rd.name)}</text>')
    inner_svg = (f'<defs>{"".join(defs)}</defs>{"".join(body)}')
    if not for_export:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" class="hw-rack" viewBox="0 0 {_f(W + 140)} {_f(H)}" '
                f'width="{_f((W + 140) * 1.4)}" height="{_f(H * 1.4)}" data-face="{face}">{inner_svg}</svg>')
    sub = ' · '.join(x for x in (rack.organization.name, rack.site.name if rack.site_id else '', rack.room) if x)
    scale = 1.6
    framed_w, framed_h = (W + 160) * scale + 40, H * scale + 120
    body2 = (f'<g transform="translate(20 70) scale({scale})">{inner_svg}</g>')
    legend = [('<rect x="0" y="0" width="20" height="14" fill="#cfd4d9" stroke="#888"/>', 'catalog artwork'),
              ('<rect x="0" y="0" width="20" height="14" fill="none" stroke="#6c757d" stroke-dasharray="4 3"/>',
               'half-depth device on the other face')]
    return _frame(f'{title_prefix}Rack {rack.name} — {face} elevation', sub, legend, framed_w, framed_h, body2)
