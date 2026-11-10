"""Builders for the sample Word, Excel, PDF and CSV files (v3.17.659).

Everything is generated in code so no binaries live in the repository:

- ``build_docx`` writes a minimal, valid WordprocessingML package with the
  standard library (python-docx is not a dependency): content types,
  relationships, styles (Title, Heading 1/2, List Bullet, Table Grid), a
  bullet numbering definition and core properties. Word, LibreOffice and
  Google Docs open it.
- ``build_xlsx`` uses openpyxl (a requirement already).
- ``build_pdf`` uses reportlab (a requirement already).
- ``build_csv`` is plain UTF-8 CSV.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
PDF_MIME = 'application/pdf'
CSV_MIME = 'text/csv'

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/numbering.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    '<Override PartName="/docProps/core.xml" '
    'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    '</Types>'
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
    'Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
    'Target="docProps/app.xml"/>'
    '</Relationships>'
)

_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" '
    'Target="numbering.xml"/>'
    '</Relationships>'
)

_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{W_NS}">'
    '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
    '<w:sz w:val="22"/></w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
    '<w:next w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr>'
    '<w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="48"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
    '<w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/>'
    '<w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="2F5496"/><w:sz w:val="32"/></w:rPr>'
    '</w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
    '<w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/>'
    '<w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="2F5496"/><w:sz w:val="26"/></w:rPr>'
    '</w:style>'
    '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/>'
    '<w:basedOn w:val="Normal"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    '<w:spacing w:after="60"/></w:pPr></w:style>'
    '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/>'
    '<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:left w:w="108" w:type="dxa"/>'
    '<w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
    '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>'
    '<w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders>'
    '<w:top w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    '<w:left w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    '<w:right w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
    '</w:tblBorders></w:tblPr></w:style>'
    '</w:styles>'
)

_NUMBERING = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:numbering xmlns:w="{W_NS}">'
    '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>'
    '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/>'
    '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>'
    '</w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    '</w:numbering>'
)

_APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    '<Application>Client St0r</Application></Properties>'
)


def _run(text, bold=False):
    rpr = '<w:rPr><w:b/></w:rPr>' if bold else ''
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _para(text, style=None, bold=False):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{ppr}{_run(text, bold)}</w:p>'


def _table(rows):
    cols = max(len(r) for r in rows)
    width = 9000 // cols
    grid = ''.join(f'<w:gridCol w:w="{width}"/>' for _ in range(cols))
    out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/>'
           f'<w:tblLook w:val="04A0" w:firstRow="1"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    for i, row in enumerate(rows):
        header = i == 0
        trpr = '<w:trPr><w:tblHeader/></w:trPr>' if header else ''
        cells = []
        for value in list(row) + [''] * (cols - len(row)):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="D9E2F3"/>' if header else ''
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                         f'{_para(str(value), bold=header)}</w:tc>')
        out.append(f'<w:tr>{trpr}{"".join(cells)}</w:tr>')
    out.append('</w:tbl>')
    return ''.join(out)


def build_docx(title, blocks, author='Client St0r'):
    """A .docx from ``blocks``: ('title'|'h1'|'h2'|'p'|'bullet', text) or ('table', rows)."""
    styles = {'title': 'Title', 'h1': 'Heading1', 'h2': 'Heading2', 'bullet': 'ListBullet', 'p': None}
    body = []
    for kind, value in blocks:
        if kind == 'table':
            body.append(_table(value))
            body.append(_para(''))
        else:
            body.append(_para(value, styles[kind]))
    body.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>{"".join(body)}</w:body></w:document>')
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            '</cp:coreProperties>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES)
        zf.writestr('_rels/.rels', _ROOT_RELS)
        zf.writestr('word/document.xml', document)
        zf.writestr('word/_rels/document.xml.rels', _DOC_RELS)
        zf.writestr('word/styles.xml', _STYLES)
        zf.writestr('word/numbering.xml', _NUMBERING)
        zf.writestr('docProps/core.xml', core)
        zf.writestr('docProps/app.xml', _APP)
    return buf.getvalue()


def build_xlsx(sheet_title, header, rows, *, widths=None, number_formats=None, total_row=None,
               title=''):
    """An .xlsx with a styled, frozen header row. ``rows`` may contain
    formula strings ("=C2*E2"); ``{r}`` in a formula is replaced with the
    row number. ``total_row`` is (label, {column letter: formula}) and is
    written below the data."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    if title:
        wb.properties.title = title
    wb.properties.creator = 'Client St0r'
    ws.append(list(header))
    fill = PatternFill('solid', fgColor='1F4E78')
    thin = Side(style='thin', color='BFBFBF')
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = fill
        cell.alignment = Alignment(vertical='center')
        cell.border = Border(bottom=thin)
    for r, row in enumerate(rows, start=2):
        ws.append([v.format(r=r) if isinstance(v, str) and v.startswith('=') else v for v in row])
    last = len(rows) + 1
    if total_row:
        label, formulas = total_row
        ws.cell(row=last + 1, column=1, value=label).font = Font(bold=True)
        for letter, formula in formulas.items():
            c = ws[f'{letter}{last + 1}']
            c.value = formula.format(last=last)
            c.font = Font(bold=True)
            c.border = Border(top=thin)
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for letter, fmt in (number_formats or {}).items():
        for r in range(2, ws.max_row + 1):
            ws[f'{letter}{r}'].number_format = fmt
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{get_column_letter(len(header))}{last}'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pdf(title, sections, *, subtitle=''):
    """A PDF from ``sections``: ('h', text), ('p', text), ('steps', [..]),
    ('bullets', [..]) or ('table', rows)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, author='Client St0r',
                            leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = [Paragraph(escape(title), styles['Title'])]
    if subtitle:
        story += [Paragraph(escape(subtitle), styles['Italic']), Spacer(1, 6 * mm)]
    for kind, value in sections:
        if kind == 'h':
            story.append(Paragraph(escape(value), styles['Heading2']))
        elif kind == 'p':
            story.append(Paragraph(escape(value), styles['BodyText']))
        elif kind in ('steps', 'bullets'):
            items = [ListItem(Paragraph(escape(v), styles['BodyText'])) for v in value]
            story.append(ListFlowable(items, bulletType='1' if kind == 'steps' else 'bullet', leftIndent=14))
        elif kind == 'table':
            data = [[Paragraph(escape(str(c)), styles['BodyText']) for c in row] for row in value]
            t = Table(data, repeatRows=1, hAlign='LEFT')
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E78')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#BFBFBF')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')]),
            ]))
            story.append(t)
        story.append(Spacer(1, 3 * mm))
    doc.build(story)
    return buf.getvalue()


def build_csv(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\r\n')
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode('utf-8')
