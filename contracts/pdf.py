"""Contract PDFs (ReportLab, already used for quotes, invoices and document
export).

Safe by construction: section HTML is sanitised (no images or other
resources) and then parsed into plain blocks by the document exporter's
parser; every piece of text is XML-escaped before it reaches ReportLab's
paragraph markup, so contract text can never become an <img> or <link> tag
that ReportLab would resolve. The only images drawn are drawn signatures,
which are decoded from the stored, re-encoded PNG in memory. Nothing is
fetched from the network or read from disk.
"""
from __future__ import annotations

import base64
import io
from decimal import Decimal

from docs.services.document_export import _xml_escape, parse_blocks

from .content import fmt_date, fmt_money, key_terms, line_total
from .sanitize import clean_html, split_page_breaks


def final_filename(v) -> str:
    from django.utils.text import slugify
    ref = v.content['contract']['reference']
    return f'{ref}-v{v.version_number}-{slugify(v.content["contract"]["title"])[:50] or "contract"}-signed.pdf'


def issued_filename(v) -> str:
    from django.utils.text import slugify
    ref = v.content['contract']['reference']
    return f'{ref}-v{v.version_number}-{slugify(v.content["contract"]["title"])[:50] or "contract"}.pdf'


def _inline(runs) -> str:
    parts = []
    for r in runs:
        text = _xml_escape(r['text']).replace('\n', '<br/>')
        if r.get('code'):
            text = f'<font face="Courier">{text}</font>'
        if r.get('bold'):
            text = f'<b>{text}</b>'
        if r.get('italic'):
            text = f'<i>{text}</i>'
        href = r.get('href') or ''
        if href.startswith(('http://', 'https://', 'mailto:')):
            text = f'<link href="{_xml_escape(href)}" color="#1b6ec2">{text}</link>'
        parts.append(text)
    return ''.join(parts) or '&nbsp;'


def build_pdf(content, *, version_number=None, draft=False, signatures=None, certificate=None,
              issued_hash='') -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (CondPageBreak, HRFlowable, Image, KeepTogether, ListFlowable, ListItem,
                                    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

    primary = colors.HexColor('#16222e')
    muted = colors.HexColor('#5a6772')
    rule = colors.HexColor('#cbd5dd')
    base = getSampleStyleSheet()
    st = {
        'title': ParagraphStyle('c_title', parent=base['Heading1'], fontSize=20, leading=24, textColor=primary,
                                spaceAfter=2),
        'sub': ParagraphStyle('c_sub', parent=base['Normal'], fontSize=9, leading=12, textColor=muted, spaceAfter=10),
        'h2': ParagraphStyle('c_h2', parent=base['Heading2'], fontSize=13, leading=17, textColor=primary,
                             spaceBefore=12, spaceAfter=4),
        'h3': ParagraphStyle('c_h3', parent=base['Heading3'], fontSize=11, leading=14, textColor=primary,
                             spaceBefore=8, spaceAfter=3),
        'body': ParagraphStyle('c_body', parent=base['Normal'], fontSize=10, leading=14, spaceAfter=6),
        'quote': ParagraphStyle('c_quote', parent=base['Normal'], fontSize=10, leading=14, leftIndent=14,
                                textColor=muted, spaceAfter=6),
        'code': ParagraphStyle('c_code', parent=base['Code'], fontSize=8.5, leading=11, spaceAfter=6),
        'cell': ParagraphStyle('c_cell', parent=base['Normal'], fontSize=9, leading=12),
        'cellr': ParagraphStyle('c_cellr', parent=base['Normal'], fontSize=9, leading=12, alignment=2),
        'head': ParagraphStyle('c_head', parent=base['Normal'], fontSize=9, leading=12, fontName='Helvetica-Bold'),
        'small': ParagraphStyle('c_small', parent=base['Normal'], fontSize=7.5, leading=10, textColor=muted),
        'mark': ParagraphStyle('c_mark', parent=base['Normal'], fontSize=16, leading=20, fontName='Times-Italic'),
    }
    for lvl in (1, 2, 3, 4):
        st[f'b_h{lvl}'] = ParagraphStyle(f'c_bh{lvl}', parent=base['Heading4'], fontSize=12 - lvl * 0.5,
                                         leading=15, textColor=primary, spaceBefore=6, spaceAfter=3)
    avail = 6.7 * inch

    def table(rows, widths, header=True, right_cols=()):
        data = []
        for ri, row in enumerate(rows):
            cells = []
            for ci, c in enumerate(row):
                style = st['head'] if header and ri == 0 else (st['cellr'] if ci in right_cols else st['cell'])
                cells.append(c if not isinstance(c, str) else Paragraph(_xml_escape(c).replace('\n', '<br/>'), style))
            data.append(cells)
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        cmds = [('GRID', (0, 0), (-1, -1), 0.5, rule), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5)]
        if header:
            cmds.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2f5')))
        t.setStyle(TableStyle(cmds))
        return t

    def html_blocks(html_text, story):
        chunks = split_page_breaks(clean_html(html_text))
        for ci, chunk in enumerate(chunks):
            if ci:
                story.append(PageBreak())
            pending, ordered = [], False

            def flush():
                nonlocal pending
                if pending:
                    story.append(ListFlowable(pending, bulletType='1' if ordered else 'bullet', bulletFontSize=8,
                                              leftIndent=16, spaceAfter=6))
                    pending = []
            for b in parse_blocks(chunk):
                kind = b['type']
                if kind != 'list_item':
                    flush()
                if kind == 'heading':
                    story.append(Paragraph(_inline(b['runs']), st[f'b_h{min(b["level"], 4)}']))
                elif kind == 'paragraph':
                    story.append(Paragraph(_inline(b['runs']), st['body']))
                elif kind == 'quote':
                    story.append(Paragraph(_inline(b['runs']), st['quote']))
                elif kind == 'list_item':
                    if pending and bool(b.get('ordered')) != ordered:
                        flush()
                    ordered = bool(b.get('ordered'))
                    pending.append(ListItem(Paragraph(_inline(b['runs']), st['body']),
                                            leftIndent=16 + 12 * b.get('level', 0)))
                elif kind == 'code':
                    story.append(Paragraph(_xml_escape(b['text']).replace('\n', '<br/>'), st['code']))
                elif kind == 'rule':
                    story.append(HRFlowable(width='100%', color=rule, spaceBefore=4, spaceAfter=8))
                elif kind == 'table' and b['rows']:
                    width = max(len(r) for r in b['rows'])
                    rows = [list(r) + [''] * (width - len(r)) for r in b['rows']]
                    story.append(table(rows, [avail / width] * width, header=b.get('has_header', False)))
                    story.append(Spacer(1, 6))
            flush()

    c = content
    cur = c['terms']['currency']
    story = []
    if draft:
        story.append(Paragraph('<b>DRAFT PREVIEW — not for signature</b>',
                               ParagraphStyle('c_draft', parent=st['body'], textColor=colors.HexColor('#b02a37'))))
    story.append(Paragraph(_xml_escape(c['contract']['title']), st['title']))
    story.append(Paragraph(_xml_escape(f'Contract {c["contract"]["reference"]}'
                                       + (f' · Version {version_number}' if version_number else '')), st['sub']))
    p, cl = c['provider'], c['client']
    story.append(table([['Provider', 'Client'],
                        ['\n'.join(x for x in [p['name'], p['address'], p['email'], p['phone']] if x),
                         '\n'.join(x for x in [cl['legal_name'] or cl['name'], cl['address']] if x)]],
                       [avail / 2, avail / 2]))
    story.append(Spacer(1, 6))
    story.append(table([[k, v] for k, v in key_terms(c)], [avail * 0.35, avail * 0.65], header=False))
    by_ref = {}
    for s in signatures or []:
        by_ref[s.invitation.signer_ref] = s
    for n, sec in enumerate(c['sections'], start=1):
        story.append(CondPageBreak(1.2 * inch))
        story.append(Paragraph(f'{n}. ' + _xml_escape(_strip_tags(sec['title'])), st['h2']))
        html_blocks(sec['html'], story)
        if sec['type'] == 'pricing':
            items = c['line_items']
            if not items:
                story.append(Paragraph('<i>No priced items.</i>', st['body']))
            for kind, label in (('one_time', 'One-time charges'),
                                ('recurring', f'Recurring charges ({c["terms"]["billing_frequency_label"]})')):
                rows = [li for li in items if li['kind'] == kind]
                if not rows:
                    continue
                t = c['totals'][kind]
                story.append(Paragraph(_xml_escape(label), st['h3']))
                data = [['Description', 'Qty', 'Unit price', 'Discount', 'Amount']]
                for li in rows:
                    d = Decimal(li['discount_percent'])
                    data.append([li['description'] + (' *' if li['taxable'] else ''),
                                 f'{Decimal(li["quantity"]).normalize():f}', fmt_money(li['unit_price'], cur),
                                 f'{d.normalize():f}%' if d else '', fmt_money(line_total(li), cur)])
                data.append(['Subtotal', '', '', '', fmt_money(t['subtotal'], cur)])
                if Decimal(t['discount']):
                    data.append(['Discounts', '', '', '', '-' + fmt_money(t['discount'], cur)])
                if Decimal(t['tax']):
                    data.append([f'Tax ({c["terms"]["tax_rate"]}%)', '', '', '', fmt_money(t['tax'], cur)])
                data.append(['Total' + (' per period' if kind == 'recurring' else ''), '', '', '',
                             fmt_money(t['total'], cur)])
                story.append(table(data, [avail * 0.44, avail * 0.1, avail * 0.16, avail * 0.12, avail * 0.18],
                                   right_cols=(1, 2, 3, 4)))
            if c['terms']['payment_terms']:
                story.append(Paragraph(_xml_escape(f'Payment terms: {c["terms"]["payment_terms"]}'), st['body']))
        elif sec['type'] == 'signatures':
            for spec in c['signers']:
                party = cl['name'] if spec['role'] == 'client' else p['name']
                sig = by_ref.get(spec['ref'])
                block = [Paragraph(_xml_escape(f'{spec["label"]} — for {party}'), st['head'])]
                if sig is not None:
                    if sig.method == 'drawn' and sig.signature_image:
                        png = base64.b64decode(sig.signature_image.split(',', 1)[1])
                        img = Image(io.BytesIO(png))
                        scale = min(2.6 * inch / img.imageWidth, 0.8 * inch / img.imageHeight)
                        img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
                        img.hAlign = 'LEFT'
                        block.append(img)
                    else:
                        block.append(Paragraph(_xml_escape(sig.typed_signature), st['mark']))
                    block.append(Paragraph(_xml_escape(
                        f'{sig.printed_name}{", " + sig.title if sig.title else ""} — signed electronically '
                        f'{sig.signed_at:%Y-%m-%d %H:%M} UTC ({sig.get_verification_level_display()})'), st['body']))
                else:
                    block += [Spacer(1, 18), HRFlowable(width='60%', color=muted, hAlign='LEFT'),
                              Paragraph('Signature', st['small']),
                              Paragraph('Name / title: ______________________   Date: ____________', st['body'])]
                story.append(KeepTogether(block + [Spacer(1, 10)]))
    if c['attachments']:
        story.append(Paragraph('Exhibits', st['h2']))
        story.append(table([['Exhibit', 'Size', 'SHA-256']] + [[a['name'], f'{a["size"]} bytes', a['sha256']]
                                                               for a in c['attachments']],
                           [avail * 0.35, avail * 0.15, avail * 0.5]))
    if certificate:
        story.append(PageBreak())
        story.append(Paragraph('Signature summary and audit certificate', st['title']))
        story.append(Paragraph(_xml_escape(certificate['note']), st['sub']))
        v = certificate['version']
        story.append(table([['Item', 'Value'],
                            ['Contract', f'{c["contract"]["reference"]} — {c["contract"]["title"]}'],
                            ['Version', f'{v["number"]} (issued {v["issued_at"][:19].replace("T", " ")} UTC)'],
                            ['Content SHA-256', v['content_hash']], ['Snapshot SHA-256', v['snapshot_hash']],
                            ['Issued PDF SHA-256', v['issued_pdf_hash'] or '—'],
                            ['Completed', (certificate['completed_at'] or '')[:19].replace('T', ' ') + ' UTC']],
                           [avail * 0.28, avail * 0.72]))
        if certificate['approvals']:
            story.append(Paragraph('Internal approval', st['h3']))
            story.append(table([['Decision', 'By', 'At (UTC)']] + [
                [a['decision'], a['by'], a['at'][:19].replace('T', ' ')] for a in certificate['approvals']],
                [avail * 0.2, avail * 0.45, avail * 0.35]))
        story.append(Paragraph('Signatures', st['h3']))
        story.append(table([['Signer', 'Method / verification', 'Signed (UTC)', 'IP address / browser']] + [
            [f'{s["printed_name"]}{", " + s["title"] if s["title"] else ""}\n{s["invited_email"]} ({s["role"]})',
             f'{s["method"]}\n{s["verification_level"].replace("_", " ")}', s['signed_at'][:19].replace('T', ' '),
             f'{s["ip_address"] or "—"}\n{s["user_agent"][:90]}'] for s in certificate['signatures']],
            [avail * 0.3, avail * 0.2, avail * 0.2, avail * 0.3]))
        story.append(Paragraph('Evidence hashes', st['h3']))
        story.append(table([['Signer', 'Evidence SHA-256']] + [[s['printed_name'], s['evidence_hash']]
                                                               for s in certificate['signatures']],
                           [avail * 0.3, avail * 0.7]))
        story.append(Paragraph('History', st['h3']))
        story.append(table([['At (UTC)', 'Event']] + [[e['at'][:19].replace('T', ' '), e['message'] or e['kind']]
                                                     for e in certificate['events'][-60:]],
                           [avail * 0.25, avail * 0.75]))
        story.append(Paragraph('Electronic-signature consent shown to each signer', st['h3']))
        story.append(Paragraph(_xml_escape(certificate['consent_text']), st['body']))

    footer_hash = (issued_hash or '')[:16]
    title = c['contract']['title'][:70]
    ref = c['contract']['reference']

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(muted)
        left = f'{ref}' + (f' v{version_number}' if version_number else '') + f' · {title}'
        if footer_hash:
            left += f' · SHA-256 {footer_hash}…'
        if draft:
            left = 'DRAFT · ' + left
        canvas.drawString(0.9 * inch, 0.55 * inch, left[:120])
        canvas.drawRightString(letter[0] - 0.9 * inch, 0.55 * inch, f'Page {canvas.getPageNumber()}')
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                            topMargin=0.8 * inch, bottomMargin=0.85 * inch, title=c['contract']['title'],
                            author=p['name'], invariant=1)
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return buf.getvalue()


def _strip_tags(s):
    import html
    import re
    return html.unescape(re.sub(r'<[^>]+>', '', s or ''))


__all__ = ['build_pdf', 'final_filename', 'issued_filename', 'fmt_date']
