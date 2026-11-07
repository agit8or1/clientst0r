"""SVG → PNG / PDF without new dependencies (PyMuPDF is already installed).

MuPDF's SVG reader handles paths, text, opacity and ``<use>`` with a
transform, but not gradients, patterns, filters or sized ``<symbol>``
references. Our artwork uses those for shading, so exports go through
``flatten_svg`` first: each gradient becomes its middle stop colour, patterns
become a translucent fill, filters are dropped and symbol instances become
transformed groups. Geometry is untouched, so the exported drawing lines up
with the interactive one.
"""
from __future__ import annotations

import re

_GRAD_RE = re.compile(r'<(linearGradient|radialGradient)\s+id="([^"]+)"[^>]*>(.*?)</\1>', re.S)
_STOP_RE = re.compile(r'stop-color="([^"]+)"')
_SYMBOL_RE = re.compile(r'<symbol id="([^"]+)" viewBox="0 0 ([\d.]+) ([\d.]+)"[^>]*>(.*?)</symbol>', re.S)
_USE_RE = re.compile(r'<use href="#([^"]+)" x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"'
                     r'(?: transform="([^"]+)")?/>')


def flatten_svg(svg: str) -> str:
    colors = {}
    for _, gid, body in _GRAD_RE.findall(svg):
        stops = _STOP_RE.findall(body)
        if stops:
            colors[gid] = stops[len(stops) // 2]
    svg = _GRAD_RE.sub('', svg)
    for gid, color in colors.items():
        svg = svg.replace(f'url(#{gid})', color)
    svg = re.sub(r'fill="url\(#pBrush\w*\)"', 'fill="none"', svg)
    svg = svg.replace('fill="url(#pVent)"', 'fill="#000000" fill-opacity="0.28"')
    svg = re.sub(r'<pattern\b.*?</pattern>', '', svg, flags=re.S)
    svg = re.sub(r'\sfilter="url\(#[^"]+\)"', '', svg)
    svg = re.sub(r'<filter\b.*?</filter>', '', svg, flags=re.S)

    sizes = {}

    def sym(m):
        sid, w, h, body = m.groups()
        sizes[sid] = (float(w), float(h))
        return f'<g id="{sid}">{body}</g>'
    svg = _SYMBOL_RE.sub(sym, svg)

    def use(m):
        sid, x, y, w, h, extra = m.groups()
        if sid not in sizes:
            return m.group(0)
        sw, sh = sizes[sid]
        t = f'translate({x} {y}) scale({float(w) / sw:.6f} {float(h) / sh:.6f})'
        if extra:
            t = f'{extra} {t}'
        return f'<use href="#{sid}" transform="{t}"/>'
    svg = _USE_RE.sub(use, svg)
    # Hit targets are invisible already; drop them from print output.
    svg = re.sub(r'<rect class="hw-hit"[^>]*/>', '', svg)
    return svg


def _doc(svg: str):
    import fitz
    return fitz.open(stream=flatten_svg(svg).encode('utf-8'), filetype='svg')


def svg_to_png(svg: str, dpi: int = 150) -> bytes:
    doc = _doc(svg)
    return doc[0].get_pixmap(dpi=dpi, alpha=False).tobytes('png')


def svg_to_pdf(svg: str) -> bytes:
    doc = _doc(svg)
    return doc.convert_to_pdf()


def file_response(content: bytes | str, fmt: str, filename: str):
    from django.http import HttpResponse
    types = {'svg': 'image/svg+xml', 'png': 'image/png', 'pdf': 'application/pdf'}
    resp = HttpResponse(content, content_type=types[fmt])
    resp['Content-Disposition'] = f'attachment; filename="{filename}.{fmt}"'
    return resp


def export(svg: str, fmt: str, filename: str):
    if fmt == 'svg':
        return file_response(svg, 'svg', filename)
    if fmt == 'png':
        return file_response(svg_to_png(svg), 'png', filename)
    if fmt == 'pdf':
        return file_response(svg_to_pdf(svg), 'pdf', filename)
    from django.http import Http404
    raise Http404('Unknown export format')
