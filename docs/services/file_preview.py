"""Inline previews of uploaded spreadsheets, CSV files and Word documents.

The document page shows images and PDFs natively; everything else used to be
only a "Download File" button. ``build_preview`` turns the first part of an
.xlsx, .csv or .docx file into plain data (rows of strings, paragraphs) that
the template renders with autoescaping on, so nothing in the file is ever
emitted as markup.

Safety limits, all checked before anything is decompressed or parsed:

- the file on disk must be at most ``MAX_FILE_BYTES``;
- a ZIP-based file (xlsx, docx) may have at most ``MAX_ZIP_MEMBERS`` members
  and their declared uncompressed sizes (``ZipInfo.file_size``) must add up to
  at most ``MAX_UNCOMPRESSED_BYTES`` — a zip bomb is refused unopened. Reads
  are capped at the declared size too, so a member that lies about its size
  can't expand past it;
- Word XML is parsed with ``defusedxml`` (DTDs, entities and external
  references forbidden) and any part that contains a DOCTYPE is refused
  outright: real WordprocessingML never has one;
- openpyxl uses defusedxml itself when it is installed;
- only the first ``MAX_ROWS`` rows × ``MAX_COLS`` columns / ``MAX_BLOCKS``
  paragraphs are kept, and each cell is cut at ``MAX_CELL_CHARS``.

Any failure gives ``{'error': ...}``; the page then says "Preview not
available — download the file" and the download link keeps working.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import os
import zipfile

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
MAX_ZIP_MEMBERS = 2000
MAX_XML_PART_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200
MAX_COLS = 30
MAX_BLOCKS = 600
MAX_CELL_CHARS = 500
MAX_CSV_BYTES = 2 * 1024 * 1024

PREVIEW_KINDS = {'.xlsx': 'xlsx', '.csv': 'csv', '.docx': 'docx'}

_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class PreviewError(Exception):
    """A user-facing reason the file can't be previewed."""


def preview_kind(name: str):
    """'xlsx' / 'csv' / 'docx' for a stored file name, else None."""
    return PREVIEW_KINDS.get(os.path.splitext(name or '')[1].lower())


def _cell(value) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        text = value.date().isoformat() if value.time() == datetime.time() else value.isoformat(sep=' ')
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + '…'
    return text


def check_zip(zf: zipfile.ZipFile) -> None:
    """Refuse archives that would decompress to more than the limits."""
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise PreviewError('The file has too many parts to preview.')
    total = 0
    for info in infos:
        if info.file_size < 0:
            raise PreviewError('The file is damaged.')
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise PreviewError('The file is too large to preview once decompressed.')


def _read_member(zf: zipfile.ZipFile, name: str, limit: int = MAX_XML_PART_BYTES) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise PreviewError('The document is too large to preview.')
    with zf.open(info) as fh:
        data = fh.read(info.file_size + 1)
    if len(data) > info.file_size or len(data) > limit:
        raise PreviewError('The file is damaged.')
    return data


def _no_doctype(data: bytes) -> None:
    upper = data.upper()
    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
        raise PreviewError('The document contains a DTD and is not previewed.')


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _para_text(p) -> str:
    parts = []
    for node in p.iter():
        if node.tag == f'{_W}t':
            parts.append(node.text or '')
        elif node.tag == f'{_W}tab':
            parts.append('\t')
        elif node.tag in (f'{_W}br', f'{_W}cr'):
            parts.append('\n')
    return ''.join(parts)


def _para_style(p) -> str:
    ppr = p.find(f'{_W}pPr')
    if ppr is None:
        return ''
    style = ppr.find(f'{_W}pStyle')
    if style is None:
        return ''
    return (style.get(f'{_W}val') or '').lower()


def _block_for_paragraph(p):
    text = _para_text(p)
    style = _para_style(p)
    level = 0
    if style == 'title':
        level = 1
    elif style.startswith('heading'):
        digits = ''.join(ch for ch in style if ch.isdigit())
        level = min(int(digits) + 1, 6) if digits else 2
    is_list = style.startswith('list') or (p.find(f'{_W}pPr/{_W}numPr') is not None)
    if not text.strip():
        return None
    if level:
        return {'type': 'heading', 'level': level, 'text': _cell(text)}
    return {'type': 'list_item' if is_list else 'paragraph', 'text': text[:5000]}


def _block_for_table(tbl):
    rows = []
    for tr in tbl.findall(f'{_W}tr')[:MAX_ROWS]:
        cells = []
        for tc in tr.findall(f'{_W}tc')[:MAX_COLS]:
            cells.append(_cell('\n'.join(_para_text(p) for p in tc.findall(f'{_W}p')).strip()))
        rows.append(cells)
    return {'type': 'table', 'rows': rows}


def preview_docx(fh) -> dict:
    from defusedxml.ElementTree import fromstring
    try:
        with zipfile.ZipFile(fh) as zf:
            check_zip(zf)
            try:
                data = _read_member(zf, 'word/document.xml')
            except KeyError:
                raise PreviewError('This is not a Word document.')
    except zipfile.BadZipFile:
        raise PreviewError('The file is not a valid Word document.')
    _no_doctype(data)
    root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    body = root.find(f'{_W}body')
    if body is None:
        raise PreviewError('The Word document has no body.')
    blocks, truncated = [], False
    for child in body:
        if len(blocks) >= MAX_BLOCKS:
            truncated = True
            break
        if child.tag == f'{_W}p':
            block = _block_for_paragraph(child)
        elif child.tag == f'{_W}tbl':
            block = _block_for_table(child)
        else:
            block = None
        if block:
            blocks.append(block)
    if not blocks:
        raise PreviewError('No readable text in this document.')
    return {'kind': 'docx', 'blocks': blocks, 'truncated': truncated}


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def preview_xlsx(fh) -> dict:
    import openpyxl
    data = fh.read()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            check_zip(zf)
            for name in zf.namelist():
                if name.endswith('.xml') or name.endswith('.rels'):
                    _no_doctype(_read_member(zf, name))
    except zipfile.BadZipFile:
        raise PreviewError('The file is not a valid Excel workbook.')

    def first_sheet(data_only):
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=data_only)
        ws = wb.worksheets[0] if wb.worksheets else None
        rows = []
        title = ws.title if ws is not None else ''
        names = list(wb.sheetnames)
        if ws is not None:
            for row in ws.iter_rows(min_row=1, max_row=MAX_ROWS + 1, max_col=MAX_COLS, values_only=True):
                rows.append(list(row))
        wb.close()
        return title, names, rows

    title, names, values = first_sheet(True)
    # Formulas written by tools that don't store a cached result read back
    # as None with data_only=True; show the formula itself instead.
    _, _, formulas = first_sheet(False)
    truncated = len(values) > MAX_ROWS
    rows = []
    for r, row in enumerate(values[:MAX_ROWS]):
        out = []
        for c, value in enumerate(row):
            if value is None and r < len(formulas) and c < len(formulas[r]):
                f = formulas[r][c]
                value = f if isinstance(f, str) and f.startswith('=') else None
            out.append(_cell(value))
        rows.append(out)
    while rows and not any(rows[-1]):
        rows.pop()
    width = max((len(r) for r in rows), default=0)
    while width and not any(len(r) >= width and r[width - 1] for r in rows):
        width -= 1
    rows = [(r + [''] * width)[:width] for r in rows]
    if not rows:
        raise PreviewError('The first sheet is empty.')
    return {'kind': 'table', 'sheet': title, 'sheets': names, 'header': rows[0], 'rows': rows[1:],
            'truncated': truncated}


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def preview_csv(fh) -> dict:
    raw = fh.read(MAX_CSV_BYTES + 1)
    truncated = len(raw) > MAX_CSV_BYTES
    text = raw[:MAX_CSV_BYTES].decode('utf-8-sig', errors='replace')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i > MAX_ROWS:
            truncated = True
            break
        rows.append([_cell(v) for v in row[:MAX_COLS]])
    rows = [r for r in rows if any(r)]
    if not rows:
        raise PreviewError('The file is empty.')
    width = max(len(r) for r in rows)
    rows = [r + [''] * (width - len(r)) for r in rows]
    return {'kind': 'table', 'sheet': '', 'sheets': [], 'header': rows[0], 'rows': rows[1:MAX_ROWS],
            'truncated': truncated or len(rows) > MAX_ROWS}


_BUILDERS = {'xlsx': preview_xlsx, 'csv': preview_csv, 'docx': preview_docx}


def build_preview(field_file) -> dict | None:
    """Preview data for a stored FileField value, None when the type has no
    preview, or ``{'error': reason}`` when it can't be previewed."""
    if not field_file:
        return None
    kind = preview_kind(field_file.name)
    if kind is None:
        return None
    try:
        size = field_file.size
        if size > MAX_FILE_BYTES:
            raise PreviewError('The file is too large to preview.')
        with field_file.storage.open(field_file.name, 'rb') as fh:
            return _BUILDERS[kind](fh)
    except PreviewError as exc:
        return {'error': str(exc)}
    except Exception:  # noqa: BLE001 — a bad upload must never break the document page
        logger.info('No preview for %s', field_file.name, exc_info=True)
        return {'error': 'The file could not be read.'}
