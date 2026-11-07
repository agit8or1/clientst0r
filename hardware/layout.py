"""
Artwork geometry: the auto-layout and helpers around ``LayoutTemplate``.

Coordinate system (shared by artwork, hit targets, labels and exports):

* one face = one panel, origin at its top-left corner, units millimetres;
* a rack-mount face is 482.6 mm wide (19" including ears) and
  ``u_height × 44.45`` mm tall; ears are the outer 21.3 mm each side;
* every element is an axis-aligned rectangle ``x, y, w, h`` plus an optional
  ``rot`` (0/90/180/270) for connectors mounted rotated.

The auto-layout only knows what the catalog knows: which components exist
and their connector types. It does **not** know where the manufacturer put
them, so every layout it produces is ``approximate`` (or ``generic`` for a
generic template) — never ``verified``. Verification is a person comparing
the layout with documentation in the layout editor.
"""
from __future__ import annotations

import math
import re
from collections import OrderedDict

from django.db import IntegrityError, OperationalError, transaction

from . import connectors as C
from .models import ComponentTemplate, HardwareModel, LayoutTemplate

U_MM = 44.45
RACK_W = 482.6
EAR_W = 21.3
LABEL_H = 3.4
GAP = 1.6
GROUP_GAP = 5.0
BLOCK = 6           # columns per visual block in a two-row group
BLOCK_GAP = 3.2
# Bump when the auto-layout rules change: stored auto layouts from an older
# generator are regenerated on next use. Hand-placed layouts are never touched.
AUTO_LAYOUT_VERSION = 3

FRONT_CLASSES = {C.CLASS_INTERFACE, C.CLASS_CONSOLE, C.CLASS_CONSOLE_SERVER, C.CLASS_FRONT_PORT}
REAR_CLASSES = {C.CLASS_POWER_PORT, C.CLASS_POWER_OUTLET, C.CLASS_REAR_PORT}
NOT_DRAWN_CONNECTORS = {'backplane'}

_NUM_RE = re.compile(r'(\d+)(?!.*\d)')


def printed_label(comp) -> str:
    """The short number shown next to a port: its label, else its last number."""
    label = comp.label if hasattr(comp, 'label') else comp.get('label', '')
    if label:
        return label[:8]
    name = comp.name if hasattr(comp, 'name') else comp['name']
    if getattr(comp, 'mgmt_only', False):
        return name[:6] if len(name) <= 6 else 'MGMT'
    m = _NUM_RE.search(name)
    if m:
        return m.group(1)
    return name[:6]


def _conn_size(connector):
    spec = C.CONNECTORS.get(connector) or C.CONNECTORS['generic']
    return spec['w'], spec['h']


def _face_for(comp, category) -> str | None:
    cls = comp.component_class
    if comp.connector in NOT_DRAWN_CONNECTORS:
        return None
    if cls in (C.CLASS_LOGICAL, C.CLASS_WIRELESS, C.CLASS_INVENTORY_ITEM):
        return None
    if cls == C.CLASS_POWER_OUTLET and category in ('pdu',) :
        return 'front'
    if cls in FRONT_CLASSES:
        if category == 'access_point':
            return 'bottom'
        # Rack servers and storage put their network and serial ports at the back.
        if category in ('server', 'storage', 'storage_shelf', 'blade_server', 'ups') and cls != C.CLASS_FRONT_PORT:
            return 'rear'
        return 'front'
    if cls in REAR_CLASSES:
        if category == 'access_point':
            return 'bottom'
        if category in ('wall_jack',) and cls == C.CLASS_REAR_PORT:
            return 'rear'
        return 'rear'
    if cls in (C.CLASS_MODULE_BAY, C.CLASS_DEVICE_BAY):
        n = comp.name.lower()
        if cls == C.CLASS_DEVICE_BAY:
            return 'front'
        if category in ('server', 'storage', 'storage_shelf') and re.search(r'bay|drive|disk|hdd|ssd|nvme|slot \d+$', n) \
                and not re.search(r'psu|power|pcie|riser|ocp|nic|fan|lom', n):
            return 'front'
        return 'rear'
    return None


def _group_key(comp):
    """Components drawn together: same face role and same connector."""
    cls = comp.component_class
    if cls in (C.CLASS_MODULE_BAY, C.CLASS_DEVICE_BAY):
        return ('bay', cls)
    if cls == C.CLASS_INTERFACE and comp.mgmt_only:
        return ('mgmt', comp.connector)
    if cls in (C.CLASS_CONSOLE,):
        return ('console', comp.connector)
    return (cls, comp.connector)


def _bay_size(comp, category, face_h):
    n = comp.name.lower()
    if re.search(r'psu|power', n):
        return 86.0, min(face_h - 6, 40.0)
    if re.search(r'fan', n):
        return 40.0, min(face_h - 6, 40.0)
    if category in ('server', 'storage', 'storage_shelf') and re.search(r'bay|drive|disk|hdd|ssd|nvme', n):
        return 26.0, min(face_h - 6, 38.0)   # 2.5" carrier seen edge-on, approximate
    if comp.component_class == C.CLASS_DEVICE_BAY:
        return 48.0, max(face_h - 8, 20.0)
    return 70.0, min(face_h - 6, 36.0)


def _layout_group(items, category, area_h):
    """Lay out one group as a grid. Returns (width, height, [elements])."""
    first = items[0]
    if first.component_class in (C.CLASS_MODULE_BAY, C.CLASS_DEVICE_BAY):
        els, x, row_h = [], 0.0, 0.0
        for comp in items:
            w, h = _bay_size(comp, category, area_h)
            els.append({'key': str(comp.key), 'kind': 'bay', 'x': x, 'y': 0.0, 'w': w, 'h': h,
                        'label': comp.label or comp.name, 'name': comp.name})
            x += w + GAP
            row_h = max(row_h, h)
        return x - GAP, row_h, els

    w, h = _conn_size(first.connector)
    cell_h = h + LABEL_H
    max_rows = max(1, int((area_h + 0.01) // (cell_h + 0.8)))
    n = len(items)
    rows = 1
    if n >= 8 and max_rows >= 2:
        rows = 2
    while rows < max_rows and math.ceil(n / rows) * (w + GAP) > 400:
        rows += 1
    cols = math.ceil(n / rows)
    els = []
    for i, comp in enumerate(items):
        # Two-row groups are numbered column-first (1 above 2), the common
        # switch convention — an assumption, which is why this is approximate.
        col, row = (i // rows, i % rows) if rows > 1 else (i, 0)
        bx = col * (w + GAP) + (col // BLOCK) * BLOCK_GAP * (1 if rows == 2 and n >= 12 else 0)
        by = row * (cell_h + 0.8)
        label_pos = 'above' if (rows == 1 or row == 0) else 'below'
        y = by + (LABEL_H if label_pos == 'above' else 0)
        if rows == 2 and row == 1:
            y = by
        els.append({'key': str(comp.key), 'kind': 'port', 'connector': comp.connector or 'generic',
                    'x': round(bx, 2), 'y': round(y, 2), 'w': w, 'h': h,
                    'label': printed_label(comp), 'label_pos': label_pos, 'name': comp.name})
    width = cols * (w + GAP) - GAP + ((cols - 1) // BLOCK) * BLOCK_GAP * (1 if rows == 2 and n >= 12 else 0)
    height = rows * (cell_h + 0.8) - 0.8
    return width, height, els


def _face_size(hm, category, face, content_w, content_h):
    if hm.kind == HardwareModel.KIND_DEVICE and hm.u_height and hm.u_height > 0:
        return RACK_W, float(hm.u_height) * U_MM, True
    pad = 12.0
    w = max(content_w + 2 * pad, 120.0)
    h = max(content_h + 2 * 8.0, 34.0)
    if hm.kind == HardwareModel.KIND_MODULE:
        w = max(content_w + 2 * 6.0, 40.0)
        h = max(content_h + 2 * 4.0, 18.0)
    if category == 'access_point' and face == 'top':
        return 200.0, 200.0, False
    return round(w, 1), round(h, 1), False


def auto_layout(hm: HardwareModel, components=None) -> dict:
    """Build an approximate layout for `hm` from its component templates."""
    comps = list(components if components is not None else hm.components.all().order_by('sort_order', 'id'))
    category = hm.category
    faces = OrderedDict()
    by_face = OrderedDict()
    for comp in comps:
        face = _face_for(comp, category)
        if face is None:
            continue
        by_face.setdefault(face, OrderedDict()).setdefault(_group_key(comp), []).append(comp)

    if category == 'access_point':
        faces['top'] = {'width': 200.0, 'height': 200.0, 'shape': 'disc', 'elements': [],
                        'decor': [{'type': 'brand', 'x': 100.0, 'y': 92.0, 'size': 9.0, 'anchor': 'middle'},
                                  {'type': 'led_ring', 'x': 100.0, 'y': 100.0, 'r': 58.0}]}

    rack = hm.kind == HardwareModel.KIND_DEVICE and hm.u_height and hm.u_height > 0
    order = ['front', 'rear', 'bottom']
    if (rack or not by_face) and hm.kind != HardwareModel.KIND_RACK and 'front' not in by_face:
        # Rack gear always shows a front panel (brand, model, ears), even blank.
        by_face['front'] = OrderedDict()
    for face in order:
        if face not in by_face:
            continue
        groups = by_face[face]
        face_h = float(hm.u_height) * U_MM if rack else 60.0
        area_h = face_h - 7.0 if rack else 40.0
        laid = [_layout_group(items, category, area_h) for items in groups.values()]
        content_w = sum(g[0] for g in laid) + GROUP_GAP * max(0, len(laid) - 1)
        content_h = max([g[1] for g in laid] or [0])
        width, height, is_rack = _face_size(hm, category, face, content_w, content_h)
        x0 = EAR_W + 8.0 if is_rack else (width - content_w) / 2
        avail = width - (2 * (EAR_W + 8.0) if is_rack else 12.0)
        reserve = 70.0 if (is_rack and face == 'front') else 0.0   # brand/model/LED area at left
        scale = 1.0
        if content_w > avail - reserve:
            scale = max(0.35, (avail - reserve) / content_w) if content_w else 1.0
        if content_h * scale > height - 6:
            scale = min(scale, (height - 6) / content_h)
        if is_rack:
            x0 = EAR_W + 8.0 + reserve if content_w * scale <= avail - reserve else EAR_W + 6.0
            # Right-align ports the way most front panels do.
            x0 = max(x0, width - EAR_W - 8.0 - content_w * scale)
        y0 = (height - content_h * scale) / 2
        elements = []
        cx = x0
        for gw, gh, els in laid:
            gy = y0 + (content_h - gh) * scale / 2
            for e in els:
                e = dict(e)
                e['x'] = round(cx + e['x'] * scale, 2)
                e['y'] = round(gy + e['y'] * scale, 2)
                e['w'] = round(e['w'] * scale, 2)
                e['h'] = round(e['h'] * scale, 2)
                elements.append(e)
            cx += (gw + GROUP_GAP) * scale
        decor = []
        if is_rack:
            if face != 'rear':
                decor.append({'type': 'ears'})
            if face == 'front':
                decor.append({'type': 'brand', 'x': EAR_W + 6.0, 'y': min(height * 0.42, 14.0), 'size': 5.2})
                decor.append({'type': 'model', 'x': EAR_W + 6.0, 'y': min(height * 0.42, 14.0) + 6.0, 'size': 3.2})
            else:
                if category in ('server', 'storage', 'switch', 'router', 'firewall'):
                    decor.append({'type': 'vent', 'x': EAR_W + 6.0, 'y': 4.0, 'w': 60.0, 'h': height - 8.0})
        elif face in ('front', 'bottom') and hm.kind != HardwareModel.KIND_MODULE:
            decor.append({'type': 'model', 'x': 6.0, 'y': 6.5, 'size': 3.0})
        faces[face] = {'width': width, 'height': round(height, 2), 'rack': bool(is_rack),
                       'elements': elements, 'decor': decor, 'scale': round(scale, 3)}
        if is_rack and face == 'rear':
            faces[face]['inset_x'] = EAR_W
    accuracy = LayoutTemplate.ACCURACY_GENERIC if hm.is_generic else LayoutTemplate.ACCURACY_APPROXIMATE
    for f in faces.values():
        f['accuracy'] = accuracy
    return {'units': 'mm', 'faces': faces}


def get_layout(hm: HardwareModel) -> LayoutTemplate:
    """Current layout, creating the auto layout on first use (lazy, cached in DB)."""
    lay = hm.layouts.filter(is_current=True).first()
    if lay and lay.auto_generated and lay.generator_version < AUTO_LAYOUT_VERSION:
        try:
            lay = save_layout(hm, auto_layout(hm)['faces'], accuracy=lay.accuracy, auto_generated=True,
                              source_notes=lay.source_notes, bump_model=False)
        except (OperationalError, IntegrityError):
            pass  # another request is regenerating it; serve the stored one this time
        return lay
    if lay:
        return lay
    data = auto_layout(hm)
    accuracy = LayoutTemplate.ACCURACY_GENERIC if hm.is_generic else LayoutTemplate.ACCURACY_APPROXIMATE
    fields = dict(is_current=True, accuracy=accuracy, faces=data['faces'], auto_generated=True,
                  generator_version=AUTO_LAYOUT_VERSION,
                  source_notes='Generated automatically from the component list. Placement, grouping '
                               'and numbering direction are not verified against the hardware.')
    try:
        with transaction.atomic():
            lay, _ = LayoutTemplate.objects.get_or_create(hardware_model=hm, version=1, defaults=fields)
        return lay
    except (OperationalError, IntegrityError):
        # Another request is writing (SQLite allows one writer) or created it a
        # moment ago. The auto layout is deterministic, so serve it unsaved;
        # a later request stores it.
        existing = hm.layouts.filter(is_current=True).first()
        return existing or LayoutTemplate(hardware_model=hm, version=1, **fields)


def refresh_auto_layout(hm: HardwareModel):
    """After a component change: regenerate an auto layout; leave a hand-made one alone."""
    lay = hm.layouts.filter(is_current=True).first()
    if lay is None:
        return None
    if lay.auto_generated:
        return save_layout(hm, auto_layout(hm)['faces'], accuracy=lay.accuracy, auto_generated=True,
                           source_notes=lay.source_notes, bump_model=False)
    return lay


def validate_faces(hm: HardwareModel, faces: dict) -> list[str]:
    """Problems with a submitted layout. Empty list = acceptable."""
    errors = []
    keys = {str(k) for k in hm.components.values_list('key', flat=True)}
    seen = set()
    if not isinstance(faces, dict) or not faces:
        return ['A layout needs at least one face.']
    for name, face in faces.items():
        if name not in ('front', 'rear', 'top', 'bottom', 'left', 'right'):
            errors.append(f'Unknown face "{name}".')
            continue
        try:
            W, H = float(face['width']), float(face['height'])
        except (KeyError, TypeError, ValueError):
            errors.append(f'{name}: width and height are required.')
            continue
        if not (5 <= W <= 2000 and 5 <= H <= 2000):
            errors.append(f'{name}: size {W}×{H} mm is out of range.')
        if face.get('accuracy') and face['accuracy'] not in dict(LayoutTemplate.ACCURACY_CHOICES):
            errors.append(f'{name}: unknown accuracy "{face["accuracy"]}".')
        for e in face.get('elements', []):
            k = str(e.get('key', ''))
            if k not in keys:
                errors.append(f'{name}: element refers to a component that is not on this model ({k[:8]}…).')
                continue
            if k in seen:
                errors.append(f'{name}: component {e.get("name") or k[:8]} is placed twice.')
            seen.add(k)
            try:
                x, y, w, h = (float(e[a]) for a in ('x', 'y', 'w', 'h'))
            except (KeyError, TypeError, ValueError):
                errors.append(f'{name}: element {e.get("name") or k[:8]} needs x, y, w, h.')
                continue
            if w <= 0 or h <= 0 or x < -0.01 or y < -0.01 or x + w > W + 0.01 or y + h > H + 0.01:
                errors.append(f'{name}: {e.get("name") or k[:8]} lies outside the {W}×{H} mm face.')
            if e.get('rot', 0) not in (0, 90, 180, 270):
                errors.append(f'{name}: rotation must be 0, 90, 180 or 270.')
    return errors


def save_layout(hm, faces, accuracy, user=None, auto_generated=False, source_url='', source_notes='',
                bump_model=True) -> LayoutTemplate:
    """Store a new layout version and make it current. Old versions stay."""
    from .catalog_import import ensure_revision_snapshot
    with transaction.atomic():
        HardwareModel.objects.select_for_update().filter(pk=hm.pk).first()
        prev = hm.layouts.order_by('-version').first()
        if bump_model:
            ensure_revision_snapshot(hm, user=user, reason='Before layout change')
        hm.layouts.filter(is_current=True).update(is_current=False)
        lay = LayoutTemplate.objects.create(
            hardware_model=hm, version=(prev.version + 1 if prev else 1), is_current=True,
            accuracy=accuracy, faces=faces, auto_generated=auto_generated, source_url=source_url,
            source_notes=source_notes, created_by=user,
            generator_version=AUTO_LAYOUT_VERSION if auto_generated else 0)
        if bump_model:
            hm.revision += 1
            hm.save(update_fields=['revision', 'updated_at'])
    return lay


def unplaced_components(hm: HardwareModel, layout: LayoutTemplate):
    placed = {e['key'] for f in layout.faces.values() for e in f.get('elements', [])}
    return [c for c in hm.components.all() if str(c.key) not in placed
            and c.component_class not in (C.CLASS_LOGICAL, C.CLASS_WIRELESS, C.CLASS_INVENTORY_ITEM)]
