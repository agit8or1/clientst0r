"""
PDF rendering + email helpers for Purchase Orders (Phase 4.1).

Mirrors the Quote/Invoice ReportLab generator in psa/pdf.py — same
brand colors, footer, header block, and totals layout. Output is a
branded PO PDF with vendor info + ship-to + line items + totals.
"""
from __future__ import annotations

import io
import logging
from decimal import Decimal
from typing import Any, List

from django.conf import settings as django_settings
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle,
)

from .pdf import (
    BRAND_PRIMARY, BRAND_MUTED,
    _styles, _header_block, _addr_block, _NumberedDocTemplate,
)


logger = logging.getLogger('psa.po_pdf')


def _po_line_items_table(line_items, currency: str = 'USD') -> Table:
    styles = _styles()
    rows = [[
        Paragraph('<b>Description / SKU</b>', styles['normal']),
        Paragraph('<b>Qty</b>', styles['right']),
        Paragraph('<b>Unit price</b>', styles['right']),
        Paragraph('<b>Line total</b>', styles['right']),
    ]]
    for li in line_items:
        desc = li.description or ''
        if li.sku:
            desc = f'{desc}<br/><font size=8 color="#7f8c8d">SKU: {li.sku}'
            if li.distributor_provider:
                desc += f' &middot; {li.distributor_provider}'
            desc += '</font>'
        rows.append([
            Paragraph(desc, styles['normal']),
            Paragraph(f'{li.quantity}', styles['right']),
            Paragraph(f'{li.unit_price:,.2f}', styles['right']),
            Paragraph(f'{li.line_total:,.2f}', styles['right']),
        ])
    if len(rows) == 1:
        rows.append([Paragraph('<i>No items</i>', styles['small']), '', '', ''])
    t = Table(rows, colWidths=[3.6 * inch, 0.7 * inch, 1.3 * inch, 1.4 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f8fa')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def _po_totals_table(po) -> Table:
    styles = _styles()
    currency = po.currency or 'USD'
    rows = [
        ['', Paragraph('Subtotal', styles['right']),
         Paragraph(f'{po.subtotal:,.2f} {currency}', styles['right'])],
        ['', Paragraph(f'Tax ({po.tax_rate}%)', styles['right']),
         Paragraph(f'{po.tax_amount:,.2f} {currency}', styles['right'])],
        ['', Paragraph('Shipping', styles['right']),
         Paragraph(f'{po.shipping_cost:,.2f} {currency}', styles['right'])],
        ['', Paragraph('<b>Total</b>', styles['big']),
         Paragraph(f'<b>{po.total:,.2f} {currency}</b>', styles['totalbig'])],
    ]
    big_row = len(rows) - 1
    t = Table(rows, colWidths=[3.5 * inch, 2.4 * inch, 1.5 * inch])
    t.setStyle(TableStyle([
        ('LINEABOVE', (1, big_row), (-1, big_row), 1, BRAND_PRIMARY),
        ('TOPPADDING', (1, big_row), (-1, big_row), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def _vendor_block(po) -> str:
    parts = [po.vendor_name or '']
    if po.vendor_address:
        parts.extend(po.vendor_address.split('\n'))
    if po.vendor_phone:
        parts.append(po.vendor_phone)
    if po.vendor_email:
        parts.append(po.vendor_email)
    return '<br/>'.join([p for p in parts if p])


def _ship_to_block(po) -> str:
    """Drop-ship overrides MSP address with client address."""
    if po.is_drop_ship and po.client_org:
        return _addr_block(po.client_org)
    if po.ship_to_name or po.ship_to_address:
        parts = [po.ship_to_name or '']
        if po.ship_to_address:
            parts.extend(po.ship_to_address.split('\n'))
        return '<br/>'.join([p for p in parts if p])
    # Default: ship to MSP
    return _addr_block(po.organization)


def render_po_pdf(po) -> bytes:
    """Render a PurchaseOrder to PDF bytes."""
    styles = _styles()
    msp = po.organization
    brand_name = getattr(msp, 'name', '') or 'Purchase Order'

    buf = io.BytesIO()
    kicker_lines = [
        f'<font size=18 color="#2c3e50"><b>PURCHASE ORDER</b></font>',
        f'<font size=10>{po.po_number}</font>',
        f'<font size=8 color="#7f8c8d">'
        f'Issue date: {po.issue_date or timezone.localtime(po.created_at).date():%Y-%m-%d}',
    ]
    if po.expected_delivery_date:
        kicker_lines.append(f'Expected: {po.expected_delivery_date:%Y-%m-%d}')
    kicker_lines.append('</font>')
    kicker = '<br/>'.join(kicker_lines)

    doc = _NumberedDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.5 * inch, bottomMargin=0.7 * inch,
        title=f'PO {po.po_number}',
        author=brand_name,
        footer_text=f'{brand_name}  -  {po.po_number}',
    )

    story: List[Any] = [
        _header_block(msp, brand_name, kicker),
        Spacer(1, 12),
        Table([
            [Paragraph('<b>From (MSP)</b>', styles['small']),
             Paragraph('<b>Vendor</b>', styles['small']),
             Paragraph('<b>Ship to</b>', styles['small'])],
            [Paragraph(_addr_block(msp), styles['normal']),
             Paragraph(_vendor_block(po), styles['normal']),
             Paragraph(_ship_to_block(po), styles['normal'])],
        ], colWidths=[2.4 * inch, 2.4 * inch, 2.5 * inch]),
        Spacer(1, 14),
        Paragraph(f'<b>{po.title}</b>', styles['h2']),
    ]

    if po.is_drop_ship:
        story.append(Paragraph(
            '<font color="#3498db"><b>DROP SHIP</b></font> &mdash; '
            'ship directly to the client address shown above.',
            styles['small']))
        story.append(Spacer(1, 6))

    story += [
        Spacer(1, 4),
        _po_line_items_table(po.line_items.all(), currency=po.currency),
        Spacer(1, 8),
        _po_totals_table(po),
    ]

    if po.notes:
        story += [
            Spacer(1, 12),
            Paragraph('<b>Notes</b>', styles['h2']),
            Paragraph(po.notes.replace('\n', '<br/>'), styles['normal']),
        ]

    story += [
        Spacer(1, 18),
        Paragraph(
            'Payment terms: per vendor agreement. Reference '
            f'<b>{po.po_number}</b> on all correspondence and invoices.',
            styles['small'],
        ),
    ]

    doc.build(story)
    return buf.getvalue()


def email_po(po, *, recipient: str, subject: str = '', body: str = '') -> bool:
    """Email a PO PDF as attachment to the vendor."""
    from django.core.mail import EmailMessage
    pdf_bytes = render_po_pdf(po)

    subj = subject or f'Purchase Order {po.po_number} from {po.organization.name}'
    msg_body = body or (
        f'Hello,\n\n'
        f'Please find attached purchase order {po.po_number}.\n\n'
        f'Total: {po.total:,.2f} {po.currency}\n'
        + (f'Expected delivery: {po.expected_delivery_date:%Y-%m-%d}\n'
           if po.expected_delivery_date else '')
        + f'\nPlease reference {po.po_number} on the invoice.\n\n'
        f'Thank you,\n{po.organization.name}'
    )

    e = EmailMessage(
        subject=subj, body=msg_body,
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    e.attach(f'{po.po_number}.pdf', pdf_bytes, 'application/pdf')
    return e.send(fail_silently=False) > 0
