"""
Document export — turn a Knowledge Base document into Markdown, print-ready
HTML, DOCX or PDF.

Issue #144: "Document Export". The import side (issue #140) already pulls
DOCX/PDF/TXT/MD *in*; this is the matching outbound half, for handing a client
their documentation on the way out the door.

Design notes:
- The rendered (sanitised) HTML of a document is parsed once into a neutral
  block structure by `parse_blocks()`. Every writer below consumes that same
  structure, so all four formats stay in step: fix the parser, fix everything.
- DOCX is written dependency-free with ``zipfile`` + hand-rolled
  WordprocessingML, mirroring how `document_import` reads DOCX without
  python-docx. Real Word styles, real bullet/number lists, real tables.
- PDF uses ReportLab, already a hard requirement for the PSA quote/invoice
  PDFs, so nothing new is pulled in.
- Print-friendliness is a first-class requirement of the issue: exported HTML
  ships an ``@media print`` block that strips background images/colours and
  forces black-on-white body text, and the DOCX/PDF writers never emit a
  background fill.
"""

from __future__ import annotations

import html as _html
import io
import re
import zipfile
from html.parser import HTMLParser
from typing import Any

# Formats offered in the UI. Key -> (label, file extension, MIME type).
EXPORT_FORMATS: dict[str, tuple[str, str, str]] = {
    'md': ('Markdown', 'md', 'text/markdown; charset=utf-8'),
    'html': ('HTML (print-ready)', 'html', 'text/html; charset=utf-8'),
    'docx': ('Word (DOCX)', 'docx',
             'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    'pdf': ('PDF', 'pdf', 'application/pdf'),
}


# ---------------------------------------------------------------------------
# HTML -> neutral block structure
# ---------------------------------------------------------------------------

# Inline tags that only decorate the runs inside a block.
_BOLD_TAGS = {'b', 'strong'}
_ITALIC_TAGS = {'i', 'em', 'cite', 'var'}
_CODE_TAGS = {'code', 'kbd', 'samp', 'tt'}

# Block tags that start a fresh paragraph-ish block.
_HEADINGS = {'h1': 1, 'h2': 2, 'h3': 3, 'h4': 4, 'h5': 5, 'h6': 6}
_IGNORED_CONTENT = {'script', 'style', 'head', 'title'}

# Tags with no end tag — they must never open a "skip this subtree" scope.
_VOID_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
}

# Classes marking an element as chrome rather than content. Editors emit these
# around code blocks (a floating "CODE" / "POWERSHELL" language badge pinned to
# the corner via `position-absolute`), and they read fine in the browser but
# flatten into stray one-word paragraphs in a linear export. `d-print-none`
# and the screen-reader-only classes say outright that the element isn't meant
# for a printed page, which is exactly what an export is.
_DECORATIVE_CLASSES = frozenset({
    'position-absolute',
    'visually-hidden', 'visually-hidden-focusable', 'sr-only', 'sr-only-focusable',
    'd-print-none', 'no-print',
})


def _is_decorative(attrs: dict) -> bool:
    classes = (attrs.get('class') or '').split()
    return any(c in _DECORATIVE_CLASSES for c in classes)


class _BlockParser(HTMLParser):
    """Flatten sanitised document HTML into a list of block dicts.

    Block shapes (all carry `type`):
      heading    level (1-6), runs
      paragraph  runs
      list_item  ordered (bool), level (int, 0-based), runs
      quote      runs
      code       text
      table      rows (list of list of str), has_header (bool)
      rule       -
      image      src, alt

    A `run` is ``{'text', 'bold', 'italic', 'code', 'href'}``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._runs: list[dict[str, Any]] = []
        self._bold = 0
        self._italic = 0
        self._code = 0
        self._href: str | None = None
        self._skip = 0
        # Nesting depth inside a decorative subtree being dropped wholesale.
        self._drop = 0
        # Stack of 'ul' / 'ol' for nested lists.
        self._list_stack: list[str] = []
        self._pending: dict[str, Any] | None = None
        self._pre = 0
        self._pre_text: list[str] = []
        # Table state.
        self._table: dict[str, Any] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_thead = False

    # -- helpers ----------------------------------------------------------
    def _flush(self) -> None:
        """Emit the block under construction, if it has any content."""
        pending, self._pending = self._pending, None
        runs = [r for r in self._runs if r['text']]
        self._runs = []
        if not runs:
            return
        block = pending or {'type': 'paragraph'}
        block['runs'] = runs
        self.blocks.append(block)

    def _start_block(self, block: dict[str, Any]) -> None:
        self._flush()
        self._pending = block

    def _add_text(self, text: str) -> None:
        if self._cell is not None:
            self._cell.append(text)
            return
        if not self._runs and not text.strip():
            return
        self._runs.append({
            'text': text,
            'bold': self._bold > 0,
            'italic': self._italic > 0,
            'code': self._code > 0,
            'href': self._href,
        })

    # -- HTMLParser hooks --------------------------------------------------
    def handle_starttag(self, tag, attrs):  # noqa: C901 — flat tag dispatch
        attrs_d = {k: (v or '') for k, v in attrs}
        # Inside a dropped subtree: track nesting so we know where it ends.
        if self._drop:
            if tag not in _VOID_TAGS:
                self._drop += 1
            return
        if _is_decorative(attrs_d):
            if tag not in _VOID_TAGS:
                self._drop = 1
            return
        if self._skip:
            return
        if tag in _IGNORED_CONTENT:
            self._skip += 1
            return

        if tag == 'pre':
            self._flush()
            self._pre += 1
            self._pre_text = []
        elif self._pre:
            return
        elif tag in _HEADINGS:
            self._start_block({'type': 'heading', 'level': _HEADINGS[tag]})
        elif tag == 'p':
            self._start_block({'type': 'paragraph'})
        elif tag == 'blockquote':
            self._start_block({'type': 'quote'})
        elif tag in ('ul', 'ol'):
            self._flush()
            self._list_stack.append(tag)
        elif tag == 'li':
            ordered = bool(self._list_stack) and self._list_stack[-1] == 'ol'
            self._start_block({
                'type': 'list_item',
                'ordered': ordered,
                'level': max(0, len(self._list_stack) - 1),
            })
        elif tag == 'table':
            self._flush()
            self._table = {'type': 'table', 'rows': [], 'has_header': False}
        elif tag == 'thead':
            self._in_thead = True
            if self._table is not None:
                self._table['has_header'] = True
        elif tag == 'tr' and self._table is not None:
            self._row = []
        elif tag in ('td', 'th') and self._row is not None:
            self._cell = []
            if tag == 'th':
                self._table['has_header'] = True
        elif tag in ('hr',):
            self._flush()
            self.blocks.append({'type': 'rule'})
        elif tag == 'br':
            self._add_text('\n')
        elif tag == 'img':
            self._flush()
            self.blocks.append({
                'type': 'image',
                'src': attrs_d.get('src', ''),
                'alt': attrs_d.get('alt', ''),
            })
        elif tag in _BOLD_TAGS:
            self._bold += 1
        elif tag in _ITALIC_TAGS:
            self._italic += 1
        elif tag in _CODE_TAGS:
            self._code += 1
        elif tag == 'a':
            href = attrs_d.get('href', '')
            self._href = href or None
        elif tag in ('div', 'section', 'article', 'header', 'footer', 'main',
                     'aside', 'figure', 'figcaption', 'dl', 'dd', 'dt'):
            # Container: close whatever paragraph was open so text inside a
            # bare <div> doesn't glue onto the previous block.
            self._flush()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ('br', 'hr', 'img'):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):  # noqa: C901 — flat tag dispatch
        if self._drop:
            self._drop -= 1
            return
        if tag in _IGNORED_CONTENT:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return

        if tag == 'pre':
            self._pre = max(0, self._pre - 1)
            text = ''.join(self._pre_text).strip('\n')
            self._pre_text = []
            if text:
                self.blocks.append({'type': 'code', 'text': text})
        elif self._pre:
            return
        elif tag in _HEADINGS or tag in ('p', 'li', 'blockquote'):
            self._flush()
        elif tag in ('ul', 'ol'):
            self._flush()
            if self._list_stack:
                self._list_stack.pop()
        elif tag == 'thead':
            self._in_thead = False
        elif tag in ('td', 'th') and self._cell is not None:
            text = re.sub(r'\s+', ' ', ''.join(self._cell)).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif tag == 'tr' and self._table is not None and self._row is not None:
            if self._row:
                self._table['rows'].append(self._row)
            self._row = None
        elif tag == 'table' and self._table is not None:
            if self._table['rows']:
                self.blocks.append(self._table)
            self._table = None
        elif tag in _BOLD_TAGS:
            self._bold = max(0, self._bold - 1)
        elif tag in _ITALIC_TAGS:
            self._italic = max(0, self._italic - 1)
        elif tag in _CODE_TAGS:
            self._code = max(0, self._code - 1)
        elif tag == 'a':
            self._href = None
        elif tag in ('div', 'section', 'article', 'header', 'footer', 'main',
                     'aside', 'figure', 'figcaption', 'dl', 'dd', 'dt'):
            self._flush()

    def handle_data(self, data):
        if self._drop or self._skip:
            return
        if self._pre:
            self._pre_text.append(data)
            return
        # Collapse runs of whitespace — HTML semantics, and it keeps DOCX/PDF
        # from inheriting the editor's indentation.
        text = re.sub(r'[ \t\r\n]+', ' ', data)
        if text:
            self._add_text(text)

    def close(self):
        super().close()
        self._flush()


def parse_blocks(html_text: str) -> list[dict[str, Any]]:
    """Parse rendered document HTML into the neutral block list."""
    parser = _BlockParser()
    parser.feed(html_text or '')
    parser.close()
    return parser.blocks


def blocks_to_plain_text(blocks: list[dict[str, Any]]) -> str:
    """Flatten blocks to plain text (used for previews and search snippets)."""
    out: list[str] = []
    for b in blocks:
        if b['type'] == 'code':
            out.append(b['text'])
        elif b['type'] == 'table':
            out.extend(' | '.join(r) for r in b['rows'])
        elif b['type'] == 'rule':
            out.append('---')
        elif b['type'] == 'image':
            out.append(b.get('alt') or '')
        else:
            out.append(''.join(r['text'] for r in b['runs']))
    return '\n\n'.join(s for s in out if s.strip())


# ---------------------------------------------------------------------------
# Document metadata shared by every writer
# ---------------------------------------------------------------------------

def document_meta(document) -> dict[str, str]:
    """Human-readable header metadata for the export cover block."""
    org = getattr(document, 'organization', None)
    updated = getattr(document, 'updated_at', None)
    category = getattr(document, 'category', None)
    meta = {
        'title': document.title or 'Untitled document',
        'organization': org.name if org else 'Global Knowledge Base',
        'category': category.name if category else '',
        'updated': updated.strftime('%Y-%m-%d %H:%M UTC') if updated else '',
    }
    try:
        tags = ', '.join(t.name for t in document.tags.all())
    except Exception:  # noqa: BLE001 — unsaved/mock objects have no m2m
        tags = ''
    meta['tags'] = tags
    return meta


def export_filename(document, fmt: str) -> str:
    """Safe download filename, e.g. ``network-overview.docx``."""
    from django.utils.text import slugify
    _, ext, _ = EXPORT_FORMATS[fmt]
    stem = slugify(document.title or '') or (document.slug or 'document')
    return f'{stem}.{ext}'


def _document_html(document) -> str:
    """Rendered + sanitised body HTML for a document."""
    render = getattr(document, 'render_content', None)
    return render() if callable(render) else (document.body or '')


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------

_MD_ESCAPE = re.compile(r'([\\`*_\[\]])')


def _md_runs(runs: list[dict[str, Any]]) -> str:
    parts = []
    for r in runs:
        text = r['text']
        if r['code']:
            parts.append(f"`{text.strip()}`" if text.strip() else text)
            continue
        text = _MD_ESCAPE.sub(r'\\\1', text)
        if r['bold']:
            text = f'**{text.strip()}**' if text.strip() else text
        if r['italic']:
            text = f'*{text.strip()}*' if text.strip() else text
        if r['href']:
            text = f"[{text.strip()}]({r['href']})"
        parts.append(text)
    return ''.join(parts).strip()


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    out: list[str] = []
    counters: dict[int, int] = {}
    for b in blocks:
        kind = b['type']
        if kind != 'list_item':
            counters.clear()
        if kind == 'heading':
            out.append('#' * b['level'] + ' ' + _md_runs(b['runs']))
        elif kind == 'paragraph':
            out.append(_md_runs(b['runs']))
        elif kind == 'quote':
            body = _md_runs(b['runs'])
            out.append('\n'.join('> ' + line for line in body.split('\n')))
        elif kind == 'list_item':
            level = b.get('level', 0)
            indent = '    ' * level
            if b.get('ordered'):
                counters[level] = counters.get(level, 0) + 1
                marker = f"{counters[level]}."
            else:
                counters.pop(level, None)
                marker = '-'
            out.append(f'{indent}{marker} {_md_runs(b["runs"])}')
        elif kind == 'code':
            out.append('```\n' + b['text'] + '\n```')
        elif kind == 'rule':
            out.append('---')
        elif kind == 'image':
            out.append(f"![{b.get('alt', '')}]({b.get('src', '')})")
        elif kind == 'table':
            rows = b['rows']
            if not rows:
                continue
            width = max(len(r) for r in rows)
            def _row(cells):
                padded = list(cells) + [''] * (width - len(cells))
                return '| ' + ' | '.join(c.replace('|', r'\|') for c in padded) + ' |'
            lines = [_row(rows[0]), '|' + '|'.join([' --- '] * width) + '|']
            lines.extend(_row(r) for r in rows[1:])
            out.append('\n'.join(lines))

    # Consecutive list items belong in one block, everything else gets a blank
    # line between it and its neighbour.
    # Consecutive items of the *same* list hug each other; everything else
    # (including a switch from bullets to numbers, which CommonMark reads as a
    # new list) gets a blank line.
    text = ''
    prev_kind = None
    list_marker = re.compile(r'^(?:(- )|\d+\. )')
    for chunk in out:
        match = list_marker.match(chunk.lstrip()) if '\n' not in chunk else None
        kind = ('ul' if match.group(1) else 'ol') if match else None
        if text:
            text += '\n' if (kind and kind == prev_kind) else '\n\n'
        text += chunk
        prev_kind = kind
    return text + '\n'


def export_markdown(document) -> bytes:
    """Markdown export.

    A document authored *as* Markdown is emitted verbatim (lossless round-trip
    with the import side); HTML documents are converted from their rendered
    body.
    """
    meta = document_meta(document)
    header = [f"# {meta['title']}", '']
    detail = [f"**Organization:** {meta['organization']}"]
    if meta['category']:
        detail.append(f"**Category:** {meta['category']}")
    if meta['tags']:
        detail.append(f"**Tags:** {meta['tags']}")
    if meta['updated']:
        detail.append(f"**Last updated:** {meta['updated']}")
    header.append('  \n'.join(detail))
    header.extend(['', '---', '', ''])

    if getattr(document, 'content_type', '') == 'markdown' and (document.body or '').strip():
        body = document.body.strip() + '\n'
    else:
        body = blocks_to_markdown(parse_blocks(_document_html(document)))

    return ('\n'.join(header) + body).encode('utf-8')


# ---------------------------------------------------------------------------
# HTML writer (print-ready standalone page)
# ---------------------------------------------------------------------------

# Issue #144 explicitly asks for "easy to print visibility ie obscure
# background images etc" — hence the aggressive print reset below.
_PRINT_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 2.5rem 1.5rem; max-width: 46rem;
  background: #fff; color: #1a1a1a;
  font: 15px/1.65 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
h1, h2, h3, h4, h5, h6 { color: #16222e; line-height: 1.25; margin: 1.8em 0 .6em; }
h1 { font-size: 1.9rem; margin-top: 0; }
h2 { font-size: 1.4rem; border-bottom: 1px solid #dde3e8; padding-bottom: .25em; }
h3 { font-size: 1.15rem; }
p, li { orphans: 3; widows: 3; }
a { color: #1b6ec2; }
code, kbd, samp { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .9em; }
pre { background: #f5f7f9; border: 1px solid #e2e8ee; border-radius: 4px;
      padding: .8em 1em; overflow-x: auto; }
pre code { background: none; }
blockquote { margin: 1em 0; padding: .2em 1em; border-left: 3px solid #cbd5dd; color: #445; }
table { border-collapse: collapse; width: 100%; margin: 1.2em 0; }
th, td { border: 1px solid #cbd5dd; padding: .45em .6em; text-align: left; vertical-align: top; }
th { background: #eef2f5; font-weight: 600; }
img { max-width: 100%; height: auto; }
hr { border: 0; border-top: 1px solid #dde3e8; margin: 2em 0; }
.doc-meta { color: #5a6772; font-size: .85rem; margin: 0 0 1.5rem;
            border-bottom: 1px solid #dde3e8; padding-bottom: 1rem; }
.doc-meta span { margin-right: 1.2rem; white-space: nowrap; }
.doc-footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #dde3e8;
              color: #77838d; font-size: .8rem; }

@media print {
  @page { margin: 18mm 16mm; }
  html, body { background: #fff !important; color: #000 !important; }
  /* Kill decorative fills so the page prints legibly and doesn't eat toner. */
  *, *::before, *::after {
    background-image: none !important;
    box-shadow: none !important;
    text-shadow: none !important;
  }
  a { color: #000 !important; text-decoration: underline; }
  /* Expand link targets so a printed copy stays useful offline. */
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: .82em; word-break: break-all; }
  pre, blockquote, table, img, figure { page-break-inside: avoid; }
  h1, h2, h3, h4 { page-break-after: avoid; }
  th { background: #eee !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .doc-footer, .doc-meta { color: #333 !important; }
}
"""


def export_html(document) -> bytes:
    """Standalone, self-contained, print-optimised HTML."""
    meta = document_meta(document)
    body_html = _document_html(document)

    bits = [f"<span><strong>Organization:</strong> {_html.escape(meta['organization'])}</span>"]
    if meta['category']:
        bits.append(f"<span><strong>Category:</strong> {_html.escape(meta['category'])}</span>")
    if meta['tags']:
        bits.append(f"<span><strong>Tags:</strong> {_html.escape(meta['tags'])}</span>")
    if meta['updated']:
        bits.append(f"<span><strong>Updated:</strong> {_html.escape(meta['updated'])}</span>")

    from django.utils import timezone
    generated = timezone.now().strftime('%Y-%m-%d %H:%M UTC')

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{_html.escape(meta["title"])}</title>\n'
        f'<style>{_PRINT_CSS}</style>\n'
        '</head>\n<body>\n'
        f'<h1>{_html.escape(meta["title"])}</h1>\n'
        f'<div class="doc-meta">{"".join(bits)}</div>\n'
        f'{body_html}\n'
        f'<div class="doc-footer">Exported {generated}</div>\n'
        '</body>\n</html>\n'
    ).encode('utf-8')


# ---------------------------------------------------------------------------
# DOCX writer (dependency-free WordprocessingML)
# ---------------------------------------------------------------------------

_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_W_XMLNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_R_XMLNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _style(style_id, name, *, size_half_pt, bold=False, color=None,
           before=0, after=120, based_on='Normal', outline=None, italic=False,
           mono=False):
    rpr = [f'<w:sz w:val="{size_half_pt}"/><w:szCs w:val="{size_half_pt}"/>']
    if bold:
        rpr.append('<w:b/>')
    if italic:
        rpr.append('<w:i/>')
    if color:
        rpr.append(f'<w:color w:val="{color}"/>')
    if mono:
        rpr.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>')
    outline_xml = f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else ''
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}">'
        f'<w:name w:val="{name}"/><w:basedOn w:val="{based_on}"/>'
        f'<w:pPr><w:spacing w:before="{before}" w:after="{after}"/>{outline_xml}</w:pPr>'
        f'<w:rPr>{"".join(rpr)}</w:rPr></w:style>'
    )


def _styles_xml() -> str:
    styles = [
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
        '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/>'
        '</w:pPr></w:pPrDefault></w:docDefaults>',
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>',
        _style('Title', 'Title', size_half_pt=52, bold=True, color='16222E', after=80),
        _style('Subtitle', 'Subtitle', size_half_pt=18, color='5A6772', after=240),
        _style('Heading1', 'heading 1', size_half_pt=32, bold=True, color='16222E',
               before=280, after=120, outline=0),
        _style('Heading2', 'heading 2', size_half_pt=26, bold=True, color='1F3040',
               before=240, after=100, outline=1),
        _style('Heading3', 'heading 3', size_half_pt=24, bold=True, color='2C3E50',
               before=200, after=80, outline=2),
        _style('Heading4', 'heading 4', size_half_pt=22, bold=True, color='2C3E50',
               before=180, after=80, outline=3),
        _style('Heading5', 'heading 5', size_half_pt=22, bold=True, italic=True,
               color='445560', before=160, after=60, outline=4),
        _style('Heading6', 'heading 6', size_half_pt=21, italic=True, color='445560',
               before=160, after=60, outline=5),
        _style('Quote', 'Quote', size_half_pt=22, italic=True, color='445560',
               before=120, after=120),
        _style('SourceCode', 'Source Code', size_half_pt=19, mono=True,
               before=120, after=120),
        _style('DocFooter', 'Doc Footer', size_half_pt=16, color='77838D',
               before=240, after=0),
        '<w:style w:type="paragraph" w:styleId="ListParagraph">'
        '<w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:after="40"/></w:pPr></w:style>',
        '<w:style w:type="table" w:styleId="DocTable"><w:name w:val="Doc Table"/>'
        '<w:tblPr><w:tblBorders>'
        + ''.join(
            f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="CBD5DD"/>'
            for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')
        )
        + '</w:tblBorders></w:tblPr></w:style>',
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:styles {_W_XMLNS}>{"".join(styles)}</w:styles>'
    )


def _numbering_xml() -> str:
    """Two abstract numberings: 0 = bullets, 1 = decimal. Three levels each."""
    # Word's own defaults for the three bullet levels: Symbol disc, Courier
    # New hollow "o", Wingdings square — each needs its matching font.
    BULLETS = [('\uf0b7', 'Symbol'), ('o', 'Courier New'), ('\uf0a7', 'Wingdings')]

    def levels(bullet: bool):
        out = []
        for lvl in range(3):
            if bullet:
                char, font = BULLETS[lvl]
                fmt = ('<w:numFmt w:val="bullet"/>'
                       f'<w:lvlText w:val="{char}"/>'
                       f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" '
                       f'w:hint="default"/></w:rPr>')
            else:
                fmt = ('<w:numFmt w:val="decimal"/>'
                       f'<w:lvlText w:val="%{lvl + 1}."/>')
            indent = 360 + lvl * 360
            out.append(
                f'<w:lvl w:ilvl="{lvl}"><w:start w:val="1"/>{fmt}'
                '<w:lvlJc w:val="left"/><w:pPr><w:ind '
                f'w:left="{indent + 360}" w:hanging="360"/></w:pPr></w:lvl>'
            )
        return ''.join(out)

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:numbering {_W_XMLNS}>'
        f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>'
        f'{levels(True)}</w:abstractNum>'
        f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>'
        f'{levels(False)}</w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>'
        '</w:numbering>'
    )


def _xml_escape(text: str) -> str:
    return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                .replace('"', '&quot;'))


class _DocxBuilder:
    """Accumulates WordprocessingML body XML plus hyperlink relationships."""

    def __init__(self) -> None:
        self.body: list[str] = []
        self.rels: list[tuple[str, str]] = []  # (rId, target)

    def _rel_for(self, href: str) -> str:
        rid = f'hl{len(self.rels) + 1}'
        self.rels.append((rid, href))
        return rid

    def run(self, text: str, *, bold=False, italic=False, code=False,
            link=False) -> str:
        props = []
        if bold:
            props.append('<w:b/>')
        if italic:
            props.append('<w:i/>')
        if code:
            props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>'
                         '<w:sz w:val="19"/>')
        if link:
            props.append('<w:color w:val="1B6EC2"/><w:u w:val="single"/>')
        rpr = f'<w:rPr>{"".join(props)}</w:rPr>' if props else ''
        return (f'<w:r>{rpr}<w:t xml:space="preserve">'
                f'{_xml_escape(text)}</w:t></w:r>')

    def runs_xml(self, runs: list[dict[str, Any]]) -> str:
        out = []
        for r in runs:
            xml = self.run(r['text'], bold=r['bold'], italic=r['italic'],
                           code=r['code'], link=bool(r['href']))
            href = r['href']
            if href and href.startswith(('http://', 'https://', 'mailto:')):
                rid = self._rel_for(href)
                xml = (f'<w:hyperlink r:id="{rid}">{xml}</w:hyperlink>')
            out.append(xml)
        return ''.join(out)

    def para(self, runs_xml: str, *, style: str | None = None,
             num_id: int | None = None, level: int = 0) -> None:
        props = []
        if style:
            props.append(f'<w:pStyle w:val="{style}"/>')
        if num_id is not None:
            props.append(f'<w:numPr><w:ilvl w:val="{min(level, 2)}"/>'
                         f'<w:numId w:val="{num_id}"/></w:numPr>')
        ppr = f'<w:pPr>{"".join(props)}</w:pPr>' if props else ''
        self.body.append(f'<w:p>{ppr}{runs_xml}</w:p>')

    def rule(self) -> None:
        self.body.append(
            '<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" '
            'w:space="1" w:color="DDE3E8"/></w:pBdr></w:pPr></w:p>'
        )

    def table(self, rows: list[list[str]], has_header: bool) -> None:
        width = max(len(r) for r in rows)
        col_w = int(9360 / width)
        xml = ['<w:tbl><w:tblPr><w:tblStyle w:val="DocTable"/>'
               '<w:tblW w:w="5000" w:type="pct"/><w:tblBorders>'
               + ''.join(
                   f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="CBD5DD"/>'
                   for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')
               )
               + '</w:tblBorders></w:tblPr><w:tblGrid>'
               + ''.join(f'<w:gridCol w:w="{col_w}"/>' for _ in range(width))
               + '</w:tblGrid>']
        for idx, row in enumerate(rows):
            header = has_header and idx == 0
            cells = list(row) + [''] * (width - len(row))
            xml.append('<w:tr>')
            if header:
                xml.append('<w:trPr><w:tblHeader/></w:trPr>')
            for cell in cells:
                shading = ('<w:shd w:val="clear" w:color="auto" w:fill="EEF2F5"/>'
                           if header else '')
                run = self.run(cell, bold=header)
                xml.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{col_w}" w:type="dxa"/>{shading}'
                    f'</w:tcPr><w:p>{run}</w:p></w:tc>'
                )
            xml.append('</w:tr>')
        xml.append('</w:tbl>')
        # Word needs a paragraph after a table or the next table merges into it.
        xml.append('<w:p/>')
        self.body.append(''.join(xml))


def blocks_to_docx_body(builder: _DocxBuilder, blocks: list[dict[str, Any]]) -> None:
    for b in blocks:
        kind = b['type']
        if kind == 'heading':
            builder.para(builder.runs_xml(b['runs']),
                         style=f"Heading{min(b['level'], 6)}")
        elif kind == 'paragraph':
            builder.para(builder.runs_xml(b['runs']))
        elif kind == 'quote':
            builder.para(builder.runs_xml(b['runs']), style='Quote')
        elif kind == 'list_item':
            builder.para(builder.runs_xml(b['runs']), style='ListParagraph',
                         num_id=2 if b.get('ordered') else 1,
                         level=b.get('level', 0))
        elif kind == 'code':
            for line in b['text'].split('\n'):
                builder.para(builder.run(line or ' ', code=True),
                             style='SourceCode')
        elif kind == 'rule':
            builder.rule()
        elif kind == 'image':
            alt = b.get('alt') or b.get('src') or ''
            if alt:
                builder.para(builder.run(f'[image: {alt}]', italic=True))
        elif kind == 'table' and b['rows']:
            builder.table(b['rows'], b.get('has_header', False))


def export_docx(document) -> bytes:
    """Word .docx export, built straight into the OOXML package."""
    from django.utils import timezone

    meta = document_meta(document)
    builder = _DocxBuilder()

    builder.para(builder.run(meta['title']), style='Title')
    subtitle_bits = [meta['organization']]
    if meta['category']:
        subtitle_bits.append(meta['category'])
    if meta['updated']:
        subtitle_bits.append(f"Updated {meta['updated']}")
    builder.para(builder.run('  •  '.join(subtitle_bits)), style='Subtitle')

    blocks_to_docx_body(builder, parse_blocks(_document_html(document)))

    generated = timezone.now().strftime('%Y-%m-%d %H:%M UTC')
    builder.rule()
    builder.para(builder.run(f'Exported {generated}'), style='DocFooter')

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document {_W_XMLNS} {_R_XMLNS}><w:body>'
        + ''.join(builder.body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
          '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/>'
          '</w:sectPr></w:body></w:document>'
    )

    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rIdNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>']
    for rid, target in builder.rels:
        rels.append(
            f'<Relationship Id="{rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{_xml_escape(target)}" TargetMode="External"/>'
        )
    rels.append('</Relationships>')

    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{_xml_escape(meta["title"])}</dc:title>'
        f'<dc:creator>{_xml_escape(meta["organization"])}</dc:creator>'
        f'<cp:lastModifiedBy>{_xml_escape(meta["organization"])}</cp:lastModifiedBy>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">'
        f'{timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")}</dcterms:modified>'
        '</cp:coreProperties>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES_XML)
        zf.writestr('_rels/.rels', _ROOT_RELS_XML)
        zf.writestr('docProps/core.xml', core_xml)
        zf.writestr('word/document.xml', document_xml)
        zf.writestr('word/_rels/document.xml.rels', ''.join(rels))
        zf.writestr('word/styles.xml', _styles_xml())
        zf.writestr('word/numbering.xml', _numbering_xml())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF writer (ReportLab)
# ---------------------------------------------------------------------------

def _pdf_inline(runs: list[dict[str, Any]]) -> str:
    """Render runs as ReportLab's inline mini-markup."""
    parts = []
    for r in runs:
        text = _xml_escape(r['text'])
        if r['code']:
            text = f'<font face="Courier">{text}</font>'
        if r['bold']:
            text = f'<b>{text}</b>'
        if r['italic']:
            text = f'<i>{text}</i>'
        href = r['href']
        if href and href.startswith(('http://', 'https://', 'mailto:')):
            text = (f'<link href="{_xml_escape(href)}" color="#1b6ec2">'
                    f'{text}</link>')
        parts.append(text)
    return ''.join(parts) or '&nbsp;'


def export_pdf(document) -> bytes:
    """Letter-size PDF matching the house style used by the PSA/report PDFs."""
    from django.utils import timezone
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable, ListFlowable, ListItem, PageBreak, Paragraph,
        SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    primary = colors.HexColor('#16222e')
    muted = colors.HexColor('#5a6772')
    rule = colors.HexColor('#cbd5dd')

    base = getSampleStyleSheet()
    st = {
        'title': ParagraphStyle('doc_title', parent=base['Heading1'], fontSize=22,
                                leading=26, textColor=primary, spaceAfter=4),
        'subtitle': ParagraphStyle('doc_subtitle', parent=base['Normal'], fontSize=9,
                                   leading=12, textColor=muted, spaceAfter=14),
        'body': ParagraphStyle('doc_body', parent=base['Normal'], fontSize=10,
                               leading=14.5, spaceAfter=8, alignment=TA_LEFT),
        'quote': ParagraphStyle('doc_quote', parent=base['Normal'], fontSize=10,
                                leading=14.5, leftIndent=14, textColor=muted,
                                borderPadding=0, spaceAfter=8),
        'code': ParagraphStyle('doc_code', parent=base['Code'], fontSize=8.5,
                               leading=11, backColor=colors.HexColor('#f5f7f9'),
                               borderColor=colors.HexColor('#e2e8ee'), borderWidth=0.5,
                               borderPadding=6, spaceAfter=8),
        'cell': ParagraphStyle('doc_cell', parent=base['Normal'], fontSize=9, leading=12),
        'cell_head': ParagraphStyle('doc_cell_head', parent=base['Normal'], fontSize=9,
                                    leading=12, textColor=primary, fontName='Helvetica-Bold'),
        'footer': ParagraphStyle('doc_footer', parent=base['Normal'], fontSize=8,
                                 leading=10, textColor=muted, spaceBefore=6),
    }
    for lvl, (size, lead, space_before) in enumerate(
            [(16, 20, 14), (13, 17, 12), (11.5, 15, 10),
             (10.5, 14, 9), (10, 13, 8), (9.5, 12.5, 8)], start=1):
        st[f'h{lvl}'] = ParagraphStyle(
            f'doc_h{lvl}', parent=base['Heading2'], fontSize=size, leading=lead,
            textColor=primary, spaceBefore=space_before, spaceAfter=4)

    meta = document_meta(document)
    story: list[Any] = [Paragraph(_xml_escape(meta['title']), st['title'])]
    subtitle_bits = [meta['organization']]
    if meta['category']:
        subtitle_bits.append(meta['category'])
    if meta['tags']:
        subtitle_bits.append(meta['tags'])
    if meta['updated']:
        subtitle_bits.append(f"Updated {meta['updated']}")
    story.append(Paragraph(_xml_escape('  •  '.join(subtitle_bits)), st['subtitle']))
    story.append(HRFlowable(width='100%', color=rule, spaceAfter=12))

    blocks = parse_blocks(_document_html(document))
    pending_list: list[Any] = []
    pending_ordered = False

    def flush_list():
        nonlocal pending_list, pending_ordered
        if pending_list:
            story.append(ListFlowable(
                pending_list, bulletType='1' if pending_ordered else 'bullet',
                bulletFontSize=8, leftIndent=18, spaceAfter=8,
            ))
            pending_list = []

    for b in blocks:
        kind = b['type']
        if kind != 'list_item':
            flush_list()
        if kind == 'heading':
            story.append(Paragraph(_pdf_inline(b['runs']), st[f"h{min(b['level'], 6)}"]))
        elif kind == 'paragraph':
            story.append(Paragraph(_pdf_inline(b['runs']), st['body']))
        elif kind == 'quote':
            story.append(Paragraph(_pdf_inline(b['runs']), st['quote']))
        elif kind == 'list_item':
            ordered = bool(b.get('ordered'))
            if pending_list and ordered != pending_ordered:
                flush_list()
            pending_ordered = ordered
            pending_list.append(ListItem(
                Paragraph(_pdf_inline(b['runs']), st['body']),
                leftIndent=18 + 14 * b.get('level', 0),
            ))
        elif kind == 'code':
            escaped = _xml_escape(b['text']).replace('\n', '<br/>').replace(' ', '&nbsp;')
            story.append(Paragraph(escaped, st['code']))
        elif kind == 'rule':
            story.append(HRFlowable(width='100%', color=rule, spaceBefore=6, spaceAfter=10))
        elif kind == 'image':
            alt = b.get('alt') or b.get('src') or ''
            if alt:
                story.append(Paragraph(f'<i>[image: {_xml_escape(alt)}]</i>', st['body']))
        elif kind == 'table' and b['rows']:
            width = max(len(r) for r in b['rows'])
            has_header = b.get('has_header', False)
            data = []
            for idx, row in enumerate(b['rows']):
                cells = list(row) + [''] * (width - len(row))
                style = st['cell_head'] if (has_header and idx == 0) else st['cell']
                data.append([Paragraph(_xml_escape(c), style) for c in cells])
            avail = 6.5 * inch
            table = Table(data, colWidths=[avail / width] * width, repeatRows=1 if has_header else 0)
            cmds = [
                ('GRID', (0, 0), (-1, -1), 0.5, rule),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
            if has_header:
                cmds.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2f5')))
            table.setStyle(TableStyle(cmds))
            story.append(table)
            story.append(Spacer(1, 10))
    flush_list()

    generated = timezone.now().strftime('%Y-%m-%d %H:%M UTC')
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width='100%', color=rule, spaceAfter=4))
    story.append(Paragraph(f'Exported {generated}', st['footer']))

    def _page_furniture(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(0.9 * inch, 0.6 * inch, meta['title'][:90])
        canvas.drawRightString(letter[0] - 0.9 * inch, 0.6 * inch,
                               f'Page {canvas.getPageNumber()}')
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.85 * inch, bottomMargin=0.85 * inch,
        title=meta['title'], author=meta['organization'],
    )
    doc.build(story, onFirstPage=_page_furniture, onLaterPages=_page_furniture)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Dispatch + bulk archive
# ---------------------------------------------------------------------------

_WRITERS = {
    'md': export_markdown,
    'html': export_html,
    'docx': export_docx,
    'pdf': export_pdf,
}


def export_document(document, fmt: str) -> tuple[bytes, str, str]:
    """Export one document.

    Returns ``(payload, filename, content_type)``. Raises ``ValueError`` on an
    unknown format so the view can 404 rather than guess.
    """
    if fmt not in _WRITERS:
        raise ValueError(f'Unsupported export format: {fmt}')
    _, _, mime = EXPORT_FORMATS[fmt]
    return _WRITERS[fmt](document), export_filename(document, fmt), mime


def export_archive(documents, fmt: str, *, archive_title: str = 'Documentation') -> bytes:
    """Bundle many documents into one ZIP, with an index.

    Built for the departing-client handover in issue #144: one archive holding
    every document the client should walk away with, plus an `index` listing so
    the recipient can navigate it without the app.
    """
    if fmt not in _WRITERS:
        raise ValueError(f'Unsupported export format: {fmt}')
    from django.utils import timezone

    writer = _WRITERS[fmt]
    _, ext, _ = EXPORT_FORMATS[fmt]

    buf = io.BytesIO()
    used: set[str] = set()
    index: list[tuple[str, str, str]] = []  # (title, filename, category)

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in documents:
            name = export_filename(doc, fmt)
            stem, _, suffix = name.rpartition('.')
            counter = 1
            while name.lower() in used:
                name = f'{stem}-{counter}.{suffix}'
                counter += 1
            used.add(name.lower())
            try:
                payload = writer(doc)
            except Exception as e:  # noqa: BLE001 — one bad doc shouldn't kill the archive
                payload = (f'Export failed for "{doc.title}": {e}\n').encode('utf-8')
                name = f'{name.rpartition(".")[0]}.error.txt'
                used.add(name.lower())
            zf.writestr(name, payload)
            category = doc.category.name if getattr(doc, 'category', None) else ''
            index.append((doc.title, name, category))

        generated = timezone.now().strftime('%Y-%m-%d %H:%M UTC')
        lines = [f'# {archive_title}', '',
                 f'{len(index)} document(s) exported {generated} as {ext.upper()}.', '']
        by_category: dict[str, list[tuple[str, str]]] = {}
        for title, name, category in index:
            by_category.setdefault(category or 'Uncategorized', []).append((title, name))
        for category in sorted(by_category):
            lines.append(f'## {category}')
            lines.append('')
            for title, name in sorted(by_category[category]):
                lines.append(f'- [{title}]({name})')
            lines.append('')
        zf.writestr('index.md', '\n'.join(lines).encode('utf-8'))

    return buf.getvalue()
