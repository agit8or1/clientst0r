"""Artwork for one installed device: the catalog face plus its fitted modules.

With no modules fitted this is the cached catalog artwork verbatim. With
modules, each module's own (catalog) face is nested into its bay rectangle
and wrapped in ``<g data-module="<installed module id>">`` so the page can map
``(module, key)`` to that module's ports.
"""
from __future__ import annotations

from .layout import get_layout
from .renderer import _f, common_defs, esc, finish_for, nest_face, render_face_body, cached_face_svg


def device_faces(device):
    layout = get_layout(device.hardware_model)
    return layout, [f for f in ('front', 'rear', 'top', 'bottom', 'left', 'right') if f in layout.faces]


def device_face_svg(device, face_name, px_per_mm=3.0):
    hm = device.hardware_model
    layout = get_layout(hm)
    face = layout.faces.get(face_name)
    if not face:
        return ''
    modules = {m.bay.template_key: m for m in device.modules.select_related('bay', 'hardware_model__manufacturer')
               if m.bay.template_key}
    bay_keys = {e['key'] for e in face.get('elements', []) if e.get('kind') == 'bay'}
    if not (bay_keys & {str(k) for k in modules}):
        return cached_face_svg(hm, layout, face_name)
    W, H = float(face['width']), float(face['height'])
    f = finish_for(hm)
    extra_defs, nested = [], []
    for e in face.get('elements', []):
        if e.get('kind') != 'bay':
            continue
        mod = modules.get(_uuid(e['key']))
        if not mod:
            continue
        mlay = get_layout(mod.hardware_model)
        mface = 'front' if 'front' in mlay.faces else next(iter(mlay.faces), None)
        if not mface:
            continue
        markup, defs = nest_face(mod.hardware_model, mlay, mface, e['x'] + 0.4, e['y'] + 0.4, e['w'] - 0.8,
                                 e['h'] - 0.8, uid=f'm{mod.pk}')
        extra_defs.append(defs)
        nested.append(f'<g class="hw-module" data-module="{mod.pk}" data-bay-key="{esc(e["key"])}">'
                      f'<title>{esc(mod.hardware_model)} in {esc(mod.bay.name)}</title>{markup}</g>')
    defs = common_defs(f, uid='a').replace('</defs>', ''.join(extra_defs) + '</defs>')
    title = esc(f'{device.asset.name} — {face_name}')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="hw-art" viewBox="0 0 {_f(W)} {_f(H)}" '
            f'width="{_f(W * px_per_mm)}" height="{_f(H * px_per_mm)}" data-face="{esc(face_name)}" '
            f'data-width-mm="{_f(W)}" data-height-mm="{_f(H)}" role="img" aria-label="{title}"><title>{title}</title>'
            f'{defs}{render_face_body(hm, face_name, face, uid="a", finish=f)}{"".join(nested)}</svg>')


def _uuid(s):
    import uuid
    try:
        return uuid.UUID(str(s))
    except ValueError:
        return None
