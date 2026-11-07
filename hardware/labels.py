"""
Printable labels.

PDF output is drawn with reportlab in millimetres, so a 25.4 × 12.7 mm label is
exactly that on paper when printed at 100 % / "Actual size". Browser print
scaling is not relied on; the HTML preview is only a preview. A calibration
page (rulers + label outlines) lets a technician check their printer and set
per-template X/Y offsets.

QR codes encode ``https://<host>/hardware/q/<kind>/<opaque uuid>/``. The URL
only opens for a signed-in user with access to that client and carries no
credentials or configuration.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from . import connectors as C
from .models import Cable, DevicePort, HardwareDevice, LabelTemplate
from .services import default_cable_end_labels

MM = 72 / 25.4
PAGE_SIZES = {'letter': (215.9, 279.4), 'a4': (210.0, 297.0)}


@dataclass
class LabelItem:
    lines: list
    qr: str = ''                 # absolute URL or ''
    cells: list = field(default_factory=list)   # patch strip cells
    ref: dict = field(default_factory=dict)


def port_text(p: DevicePort):
    return p.tech_label or (f'Port {p.label}' if p.label and p.label.isdigit() else p.label) or p.name


def build_items(org, kind, request, *, devices=(), ports=(), cables=(), racks=(), concise=False,
                sequence=None, include_qr=False):
    """LabelItems for the selection. Every object is re-fetched within `org`."""
    def qr(k, uid):
        return request.build_absolute_uri(reverse('hardware:qr', args=[k, uid])) if include_qr else ''
    items = []
    if sequence:
        pattern, start, count = sequence
        if count < 1 or count > 2000:
            raise ValidationError('Print between 1 and 2000 sequential labels at a time.')
        for n in range(start, start + count):
            try:
                items.append(LabelItem([pattern.format(n=n)], ref={'type': 'sequence', 'n': n}))
            except (KeyError, ValueError, IndexError):
                raise ValidationError('Use {n} (or {n:04}) in the sequence pattern.')
        return items
    if kind == 'device':
        for d in HardwareDevice.objects.filter(organization=org, pk__in=devices).select_related(
                'asset', 'hardware_model__manufacturer'):
            a = d.asset
            sub = ' · '.join(x for x in (a.asset_tag and f'Tag {a.asset_tag}', a.serial_number and f'S/N {a.serial_number}') if x)
            items.append(LabelItem([a.name, str(d.hardware_model), sub] if sub else [a.name, str(d.hardware_model)],
                                   qr=qr('d', d.public_id), ref={'type': 'device', 'id': d.pk}))
    elif kind == 'rack':
        from monitoring.models import Rack
        for r in Rack.objects.filter(organization=org, pk__in=racks).select_related('site'):
            where = ' · '.join(x for x in (r.site.name if r.site_id else '', r.room, r.location) if x)
            items.append(LabelItem([r.name, where] if where else [r.name], ref={'type': 'rack', 'id': r.pk}))
    elif kind in ('port', 'wall_jack'):
        for p in DevicePort.objects.filter(organization=org, pk__in=ports).select_related('device__asset').order_by(
                'device__asset__name', 'sort_order'):
            items.append(LabelItem([f'{p.device.asset.name} / {port_text(p)}'], qr=qr('p', p.public_id),
                                   ref={'type': 'port', 'id': p.pk}))
    elif kind == 'patch_strip':
        for d in HardwareDevice.objects.filter(organization=org, pk__in=devices).select_related('asset'):
            fronts = list(d.ports.filter(component_class=C.CLASS_FRONT_PORT).order_by('sort_order', 'id'))
            items.append(LabelItem([d.asset.name], cells=[p.tech_label or p.label or p.name for p in fronts],
                                   ref={'type': 'device', 'id': d.pk}))
    elif kind == 'cable':
        for c in Cable.objects.filter(organization=org, pk__in=cables).prefetch_related(
                'terminations__port__device__asset').order_by('label', 'id'):
            da, db = default_cable_end_labels(c)
            ident = c.label or f'#{c.pk}'
            ends = c.ends()
            if concise:
                def short(ts):
                    if not ts:
                        return '?'
                    p = ts[0].port
                    return f'{p.device.asset.name}/{p.tech_label or p.label or p.name}'
                a_txt = b_txt = f'{short(ends["A"])} ⇄ {short(ends["B"])}'
            else:
                a_txt, b_txt = c.label_a or da, c.label_b or db
            items.append(LabelItem([ident, a_txt], qr=qr('c', c.public_id), ref={'type': 'cable', 'id': c.pk, 'end': 'A'}))
            items.append(LabelItem([ident, b_txt], qr=qr('c', c.public_id), ref={'type': 'cable', 'id': c.pk, 'end': 'B'}))
    else:
        raise ValidationError('Unknown label kind.')
    return items


def apply_format(tpl: LabelTemplate, items, request=None):
    """Optional per-template text override, e.g. "{device} / {port}"."""
    if not tpl.text_format:
        return items
    out = []
    for i, it in enumerate(items, 1):
        parts = it.lines[0].split(' / ', 1)
        ctx = {'device': parts[0], 'port': parts[1] if len(parts) > 1 else '', 'text': it.lines[0], 'n': i}
        try:
            first = tpl.text_format.format(**ctx)
        except (KeyError, ValueError, IndexError):
            first = it.lines[0]
        out.append(LabelItem([first] + it.lines[1:], it.qr, it.cells, it.ref))
    return out


# --------------------------------------------------------------------------- geometry

def page_geometry(tpl: LabelTemplate):
    """(page_w_mm, page_h_mm, [ (x_mm, y_mm) top-left of each label slot ])."""
    w, h = float(tpl.width_mm), float(tpl.height_mm)
    if tpl.page_size == 'label':
        return w, h, [(0.0, 0.0)]
    pw, ph = PAGE_SIZES[tpl.page_size]
    cols, rows = max(1, tpl.columns), max(1, tpl.rows)
    ml, mt = float(tpl.page_margin_left_mm), float(tpl.page_margin_top_mm)
    gx, gy = float(tpl.gap_x_mm), float(tpl.gap_y_mm)
    if ml + cols * w + (cols - 1) * gx > pw + 0.01 or mt + rows * h + (rows - 1) * gy > ph + 0.01:
        raise ValidationError(f'{cols}×{rows} labels of {w}×{h} mm do not fit on {tpl.get_page_size_display()}.')
    slots = [(ml + c * (w + gx), mt + r * (h + gy)) for r in range(rows) for c in range(cols)]
    return pw, ph, slots


def _qr_image(url):
    import qrcode
    from reportlab.lib.utils import ImageReader
    img = qrcode.make(url, box_size=8, border=1)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return ImageReader(buf)


def _fit(canvas, text, font, size, max_w):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    s = size
    while s > 3.5 and stringWidth(text, font, s) > max_w:
        s -= 0.25
    if stringWidth(text, font, s) > max_w:
        while text and stringWidth(text + '…', font, s) > max_w:
            text = text[:-1]
        text += '…'
    return text, s


def _font():
    """A TrueType font with arrows/ellipsis when available; Helvetica otherwise."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for name, path, bold in (('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),):
        try:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
                pdfmetrics.registerFont(TTFont(name + '-Bold', bold))
            return name, name + '-Bold'
        except Exception:  # noqa: BLE001
            continue
    return 'Helvetica', 'Helvetica-Bold'


def _draw_label(c, tpl, it, x, y, fonts):
    """Draw one label with its top-left at (x, y) mm (y from page top)."""
    regular, bold = fonts
    w, h = float(tpl.width_mm), float(tpl.height_mm)
    m = float(tpl.margin_mm)
    c.saveState()
    c.translate(x * MM, -y * MM)          # caller set origin at page top-left with y down
    if tpl.show_border:
        c.setLineWidth(0.25)
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.rect(0, -h * MM, w * MM, h * MM, stroke=1, fill=0)
    c.setFillColorRGB(0, 0, 0)
    tx, tw = m, w - 2 * m
    if it.qr and tpl.include_qr:
        q = h - 2 * m
        c.drawImage(_qr_image(it.qr), m * MM, -(m + q) * MM, q * MM, q * MM)
        tx, tw = m + q + m, w - q - 3 * m
    if it.cells:
        n = max(1, tpl.strip_cells or len(it.cells))
        cw = w / n
        c.setLineWidth(0.2)
        for i, cell in enumerate(it.cells[:n]):
            if i:
                c.line(i * cw * MM, 0, i * cw * MM, -h * MM)
            txt, s = _fit(c, cell, bold, float(tpl.font_size_pt), cw * MM - 1.5)
            c.setFont(bold, s)
            c.drawCentredString((i + 0.5) * cw * MM, -(h / 2) * MM - s / 3, txt)
        c.restoreState()
        return
    size = float(tpl.font_size_pt)
    lines = [l for l in it.lines if l]
    sizes = [size] + [max(4.0, size * 0.72)] * (len(lines) - 1)
    total = sum(sizes) * 1.15
    avail = (h - 2 * m) * MM
    if total > avail:
        k = avail / total
        sizes = [s * k for s in sizes]
        total = avail
    ypos = -(m * MM) - (avail - total) / 2
    for i, line in enumerate(lines):
        font = bold if i == 0 else regular
        txt, s = _fit(c, line, font, sizes[i], tw * MM)
        ypos -= s * 1.15
        c.setFont(font, s)
        c.drawString(tx * MM, ypos + s * 0.2, txt)
    c.restoreState()


def render_pdf(tpl: LabelTemplate, items, start_slot=0) -> bytes:
    """Labels laid out on pages at true size. `start_slot` skips used labels on a part sheet."""
    from reportlab.pdfgen import canvas as rl
    pw, ph, slots = page_geometry(tpl)
    buf = io.BytesIO()
    c = rl.Canvas(buf, pagesize=(pw * MM, ph * MM))
    c.setTitle(f'Labels — {tpl.name}')
    fonts = _font()
    ox, oy = float(tpl.offset_x_mm), float(tpl.offset_y_mm)
    i = 0
    slot = start_slot % len(slots)
    if not items:
        raise ValidationError('Nothing to print.')
    while i < len(items):
        c.saveState()
        c.translate(0, ph * MM)            # origin top-left, y grows downward via negative coordinates
        while slot < len(slots) and i < len(items):
            sx, sy = slots[slot]
            _draw_label(c, tpl, items[i], sx + ox, sy + oy, fonts)
            slot += 1
            i += 1
        c.restoreState()
        c.showPage()
        slot = 0
    c.save()
    return buf.getvalue()


def calibration_pdf(tpl: LabelTemplate) -> bytes:
    """Rulers and every label outline for this template, to check scale and offsets."""
    from reportlab.pdfgen import canvas as rl
    pw, ph, slots = page_geometry(tpl)
    buf = io.BytesIO()
    c = rl.Canvas(buf, pagesize=(pw * MM, ph * MM))
    c.setTitle(f'Calibration — {tpl.name}')
    regular, bold = _font()
    c.translate(0, ph * MM)
    ox, oy = float(tpl.offset_x_mm), float(tpl.offset_y_mm)
    w, h = float(tpl.width_mm), float(tpl.height_mm)
    c.setLineWidth(0.3)
    c.setStrokeColorRGB(0.2, 0.4, 0.8)
    for sx, sy in slots:
        c.rect((sx + ox) * MM, -(sy + oy + h) * MM, w * MM, h * MM, stroke=1, fill=0)
    # 100 mm (or shorter, to fit) rulers from a 10 mm inset
    c.setStrokeColorRGB(0, 0, 0)
    L = min(100.0, pw - 20, ph - 20)
    x0, y0 = min(10.0, pw / 4), min(10.0, ph / 4)
    if L >= 20:
        c.setLineWidth(0.4)
        c.line(x0 * MM, -y0 * MM, (x0 + L) * MM, -y0 * MM)
        c.line(x0 * MM, -y0 * MM, x0 * MM, -(y0 + L) * MM)
        for mm in range(0, int(L) + 1):
            t = 3 if mm % 10 == 0 else (2 if mm % 5 == 0 else 1)
            c.setLineWidth(0.2)
            c.line((x0 + mm) * MM, -y0 * MM, (x0 + mm) * MM, -(y0 + t) * MM)
            c.line(x0 * MM, -(y0 + mm) * MM, (x0 + t) * MM, -(y0 + mm) * MM)
        c.setFont(regular, 6)
        c.drawString((x0 + 2) * MM, -(y0 + 6) * MM, f'{L:.0f} mm — measure both rulers after printing')
    c.setFont(bold, 8)
    c.drawString(x0 * MM, -(ph - 12) * MM, f'{tpl.name}: {w:g} × {h:g} mm labels, offset X {ox:+g} / Y {oy:+g} mm')
    c.setFont(regular, 7)
    c.drawString(x0 * MM, -(ph - 7) * MM, 'Print at 100 % / "Actual size" with scaling off. If outlines are shifted, '
                                          'adjust the template offsets.')
    c.showPage()
    c.save()
    return buf.getvalue()


def preview_svg(tpl: LabelTemplate, items, max_labels=60) -> str:
    """An SVG preview in millimetres (first page only)."""
    from .renderer import esc
    pw, ph, slots = page_geometry(tpl)
    w, h, m = float(tpl.width_mm), float(tpl.height_mm), float(tpl.margin_mm)
    fs = float(tpl.font_size_pt) * 25.4 / 72
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {pw} {ph}" width="{pw}mm" height="{ph}mm" '
             f'class="hw-label-preview"><rect width="{pw}" height="{ph}" fill="#fff"/>']
    for (sx, sy), it in zip(slots, items[:max_labels]):
        parts.append(f'<g transform="translate({sx} {sy})"><rect width="{w}" height="{h}" fill="#fff" '
                     f'stroke="#999" stroke-width="0.2" stroke-dasharray="1 0.6"/>')
        tx = m
        if it.qr and tpl.include_qr:
            q = h - 2 * m
            parts.append(f'<rect x="{m}" y="{m}" width="{q}" height="{q}" fill="#222"/>'
                         f'<text x="{m + q / 2}" y="{m + q / 2 + 1}" font-size="{min(q / 3, 3)}" fill="#fff" '
                         f'text-anchor="middle" font-family="sans-serif">QR</text>')
            tx = 2 * m + q
        if it.cells:
            n = max(1, tpl.strip_cells or len(it.cells))
            cw = w / n
            for i, cell in enumerate(it.cells[:n]):
                parts.append(f'<line x1="{i * cw}" y1="0" x2="{i * cw}" y2="{h}" stroke="#bbb" stroke-width="0.15"/>'
                             f'<text x="{(i + .5) * cw}" y="{h / 2 + fs / 3}" font-size="{min(fs, cw * 0.5)}" '
                             f'text-anchor="middle" font-family="sans-serif" font-weight="700">{esc(cell)}</text>')
        else:
            y = m + fs
            for i, line in enumerate(x for x in it.lines if x):
                size = fs if i == 0 else fs * 0.72
                parts.append(f'<text x="{tx}" y="{y}" font-size="{size}" font-family="sans-serif" '
                             f'font-weight="{700 if i == 0 else 400}">{esc(line)}</text>')
                y += size * 1.2
        parts.append('</g>')
    parts.append('</svg>')
    return ''.join(parts)


DEFAULT_TEMPLATES = [
    dict(name='Asset label 2" × 1" (50.8 × 25.4 mm), roll, QR', kind='device', width_mm=50.8, height_mm=25.4,
         font_size_pt=10, include_qr=True, page_size='label'),
    dict(name='Asset label 2" × 1", Letter 3 × 10', kind='device', width_mm=66.7, height_mm=25.4, font_size_pt=10,
         include_qr=True, page_size='letter', columns=3, rows=10, page_margin_left_mm=4.8, page_margin_top_mm=12.7,
         gap_x_mm=3.2),
    dict(name='Rack ID 4" × 2" (101.6 × 50.8 mm)', kind='rack', width_mm=101.6, height_mm=50.8, font_size_pt=28,
         page_size='label'),
    dict(name='Port label 25 × 10 mm, Letter 7 × 25', kind='port', width_mm=25, height_mm=10, font_size_pt=6,
         page_size='letter', columns=7, rows=25, page_margin_left_mm=12, page_margin_top_mm=12, gap_x_mm=2,
         gap_y_mm=0.5),
    dict(name='Wall jack 25 × 10 mm, Letter 7 × 25', kind='wall_jack', width_mm=25, height_mm=10, font_size_pt=7,
         page_size='letter', columns=7, rows=25, page_margin_left_mm=12, page_margin_top_mm=12, gap_x_mm=2,
         gap_y_mm=0.5),
    dict(name='Patch strip 24 ports × 14.7 mm pitch (353 × 9 mm)', kind='patch_strip', width_mm=352.8,
         height_mm=9, font_size_pt=7, page_size='label', strip_cells=24),
    dict(name='Cable flag 38 × 19 mm, both ends, roll', kind='cable', width_mm=38, height_mm=19, font_size_pt=8,
         include_qr=False, page_size='label'),
    dict(name='Cable label 25.4 × 12.7 mm, Letter 7 × 20', kind='cable', width_mm=25.4, height_mm=12.7,
         font_size_pt=6, page_size='letter', columns=7, rows=20, page_margin_left_mm=8, page_margin_top_mm=12.7,
         gap_x_mm=3, gap_y_mm=0),
]


def ensure_default_templates():
    for spec in DEFAULT_TEMPLATES:
        LabelTemplate.objects.get_or_create(organization=None, name=spec['name'], defaults={
            k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in spec.items() if k != 'name'})
