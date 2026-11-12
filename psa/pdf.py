"""
PDF rendering for Quotes + Invoices.

Single ReportLab-based renderer with a shared layout — quotes and
invoices use the same design with different titles, totals, and
footer text. The MSP organization's `logo` ImageField drives the
top-left brand mark; if no logo is set, the org name renders in a
heavy font instead.
"""
from __future__ import annotations

import io
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.conf import settings as django_settings
from django.core.files.storage import default_storage

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, Image,
)


logger = logging.getLogger('psa.pdf')


# ---- Styling helpers -------------------------------------------------------

BRAND_PRIMARY = colors.HexColor('#2c3e50')   # deep slate
BRAND_ACCENT = colors.HexColor('#3498db')    # blue accent
BRAND_MUTED = colors.HexColor('#7f8c8d')


def _styles():
    base = getSampleStyleSheet()
    out = {
        'title': ParagraphStyle('title', parent=base['Heading1'], fontSize=22,
                                textColor=BRAND_PRIMARY, leading=24, spaceAfter=4),
        'subtitle': ParagraphStyle('subtitle', parent=base['Normal'], fontSize=10,
                                   textColor=BRAND_MUTED, leading=12),
        'h2': ParagraphStyle('h2', parent=base['Heading2'], fontSize=12,
                             textColor=BRAND_PRIMARY, leading=15, spaceAfter=4),
        'normal': ParagraphStyle('normal', parent=base['Normal'], fontSize=10, leading=13),
        'small': ParagraphStyle('small', parent=base['Normal'], fontSize=8.5, leading=11,
                                textColor=BRAND_MUTED),
        'right': ParagraphStyle('right', parent=base['Normal'], fontSize=10,
                                leading=13, alignment=TA_RIGHT),
        'kicker': ParagraphStyle('kicker', parent=base['Normal'], fontSize=8.5,
                                 textColor=BRAND_MUTED, leading=11, alignment=TA_RIGHT),
        'big': ParagraphStyle('big', parent=base['Normal'], fontSize=14,
                              textColor=BRAND_PRIMARY, alignment=TA_RIGHT, leading=18),
        'totalbig': ParagraphStyle('totalbig', parent=base['Normal'], fontSize=18,
                                   textColor=BRAND_PRIMARY, alignment=TA_RIGHT, leading=22),
        'footer': ParagraphStyle('footer', parent=base['Normal'], fontSize=8.5,
                                 textColor=BRAND_MUTED, leading=11, alignment=TA_CENTER),
    }
    return out


def _resolve_logo_path(org) -> Optional[str]:
    """Return a filesystem path to the org's logo, or None.

    Falls back to the SystemSetting custom_logo when org has none.
    """
    candidate = getattr(org, 'logo', None) or None
    try:
        if candidate and candidate.name:
            # ImageField — resolve via storage
            return default_storage.path(candidate.name)
    except (NotImplementedError, ValueError, AttributeError):
        pass
    # Fallback: system custom_logo
    try:
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        if ss.custom_logo and ss.custom_logo.name:
            return default_storage.path(ss.custom_logo.name)
    except Exception:
        pass
    return None


# ---- Document builder ------------------------------------------------------

class _NumberedDocTemplate(BaseDocTemplate):
    """Adds a footer with page numbers."""

    def __init__(self, *args, footer_text: str = '', **kwargs):
        self._footer_text = footer_text
        super().__init__(*args, **kwargs)
        frame = Frame(0.6 * inch, 0.7 * inch, 7.3 * inch, 9.4 * inch, id='main')
        self.addPageTemplates([PageTemplate(id='main', frames=[frame],
                                            onPage=self._draw_footer)])

    def _draw_footer(self, c: canvas.Canvas, doc):
        c.saveState()
        c.setFont('Helvetica', 8)
        c.setFillColor(BRAND_MUTED)
        # Footer text (left)
        c.drawString(0.6 * inch, 0.45 * inch, self._footer_text or '')
        # Page x of y (right)
        c.drawRightString(7.9 * inch, 0.45 * inch, f'Page {doc.page}')
        c.restoreState()


def _header_block(org, brand_name: str, kicker: str) -> Table:
    """Logo (or org name) on the left, kicker text on the right."""
    styles = _styles()
    logo_cell: Any = ''
    logo_path = _resolve_logo_path(org)
    if logo_path:
        try:
            img = Image(logo_path, width=1.6 * inch, height=0.6 * inch, kind='proportional')
            logo_cell = img
        except Exception as exc:
            logger.warning('logo render failed: %s', exc)
            logo_cell = Paragraph(f'<b>{brand_name}</b>', styles['title'])
    else:
        logo_cell = Paragraph(f'<b>{brand_name}</b>', styles['title'])

    right_block = Paragraph(kicker, styles['kicker'])
    t = Table([[logo_cell, right_block]], colWidths=[3.5 * inch, 3.8 * inch])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


def _addr_block(org) -> str:
    """Build a multi-line address paragraph from an Organization."""
    parts = [getattr(org, 'name', '') or '']
    addr_lines = []
    if getattr(org, 'street_address', ''):
        addr_lines.append(org.street_address)
    if getattr(org, 'street_address_2', ''):
        addr_lines.append(org.street_address_2)
    city_state = ' '.join(filter(None, [
        getattr(org, 'city', '') or '',
        getattr(org, 'state', '') or '',
        getattr(org, 'postal_code', '') or '',
    ]))
    if city_state.strip():
        addr_lines.append(city_state)
    if getattr(org, 'country', '') and org.country != 'United States':
        addr_lines.append(org.country)
    if getattr(org, 'phone', ''):
        addr_lines.append(org.phone)
    if getattr(org, 'email', ''):
        addr_lines.append(org.email)
    return '<br/>'.join([p for p in [parts[0]] + addr_lines if p])


def _line_items_table(line_items, currency: str = 'USD') -> Table:
    styles = _styles()
    rows = [[
        Paragraph('<b>Description</b>', styles['normal']),
        Paragraph('<b>Qty</b>', styles['right']),
        Paragraph('<b>Unit price</b>', styles['right']),
        Paragraph('<b>Line total</b>', styles['right']),
    ]]
    for li in line_items:
        rows.append([
            Paragraph(li.description or '', styles['normal']),
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


def _totals_table(subtotal, tax_amount, total, currency: str = 'USD',
                  amount_paid: Optional[Decimal] = None,
                  balance: Optional[Decimal] = None) -> Table:
    styles = _styles()
    rows = [
        ['', Paragraph('Subtotal', styles['right']),
         Paragraph(f'{subtotal:,.2f} {currency}', styles['right'])],
        ['', Paragraph('Tax', styles['right']),
         Paragraph(f'{tax_amount:,.2f} {currency}', styles['right'])],
    ]
    if amount_paid is not None:
        rows.append(['', Paragraph('Total', styles['right']),
                     Paragraph(f'{total:,.2f} {currency}', styles['right'])])
        rows.append(['', Paragraph('Paid', styles['right']),
                     Paragraph(f'{amount_paid:,.2f} {currency}', styles['right'])])
        rows.append(['', Paragraph('<b>Balance due</b>', styles['big']),
                     Paragraph(f'<b>{balance:,.2f} {currency}</b>', styles['totalbig'])])
        big_row = len(rows) - 1
    else:
        rows.append(['', Paragraph('<b>Total</b>', styles['big']),
                     Paragraph(f'<b>{total:,.2f} {currency}</b>', styles['totalbig'])])
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


# ---- Public API ------------------------------------------------------------

def render_quote_pdf(quote, *, sign_url: str = '') -> bytes:
    """Render a Quote to PDF bytes. If `sign_url` is provided, an
    'Accept & Sign' link is rendered prominently for the customer."""
    styles = _styles()
    msp = quote.organization
    client = quote.client_org
    brand_name = getattr(msp, 'name', '') or 'Quote'

    buf = io.BytesIO()
    kicker = (
        f'<font size=18 color="#2c3e50"><b>QUOTE</b></font><br/>'
        f'<font size=10>{quote.quote_number}</font><br/>'
        f'<font size=8 color="#7f8c8d">Date: {quote.created_at:%Y-%m-%d}'
        + (f'<br/>Valid until: {quote.valid_until:%Y-%m-%d}' if quote.valid_until else '')
        + '</font>'
    )
    doc = _NumberedDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.5 * inch, bottomMargin=0.7 * inch,
        title=f'Quote {quote.quote_number}',
        author=brand_name,
        footer_text=f'{brand_name}  ·  {quote.quote_number}',
    )

    story: List[Any] = [
        _header_block(msp, brand_name, kicker),
        Spacer(1, 12),
        Table([
            [Paragraph('<b>From</b>', styles['small']),
             Paragraph('<b>Bill to</b>', styles['small'])],
            [Paragraph(_addr_block(msp), styles['normal']),
             Paragraph(_addr_block(client), styles['normal'])],
        ], colWidths=[3.6 * inch, 3.7 * inch]),
        Spacer(1, 14),
        Paragraph(f'<b>{quote.title}</b>', styles['h2']),
    ]
    if quote.description:
        story += [Paragraph(quote.description.replace('\n', '<br/>'), styles['normal']),
                  Spacer(1, 8)]

    story += [
        Spacer(1, 4),
        _line_items_table(quote.line_items.all()),
        Spacer(1, 8),
        _totals_table(quote.subtotal, quote.tax_amount, quote.total),
    ]

    if sign_url:
        story += [
            Spacer(1, 18),
            Paragraph(
                f'<para alignment="center">'
                f'<font size=12 color="#2c3e50"><b>To accept this quote, click below to sign:</b></font><br/><br/>'
                f'<a href="{sign_url}"><font color="#3498db" size=11><b>{sign_url}</b></font></a>'
                f'</para>',
                styles['normal'],
            ),
        ]

    if quote.status == 'accepted' and hasattr(quote, 'signature'):
        sig = quote.signature
        story += [
            Spacer(1, 14),
            Paragraph(
                f'<font color="#27ae60" size=11><b>✓ Accepted</b></font> '
                f'by {sig.signed_by_name} ({sig.signed_by_email}) on {sig.signed_at:%Y-%m-%d %H:%M}',
                styles['normal'],
            ),
        ]

    doc.build(story)
    return buf.getvalue()


def render_invoice_pdf(invoice) -> bytes:
    """Render an Invoice to PDF bytes."""
    styles = _styles()
    msp = invoice.organization
    client = invoice.client_org
    brand_name = getattr(msp, 'name', '') or 'Invoice'

    buf = io.BytesIO()
    kicker_lines = [f'<font size=18 color="#2c3e50"><b>INVOICE</b></font>',
                    f'<font size=10>{invoice.invoice_number}</font>',
                    f'<font size=8 color="#7f8c8d">Date: {invoice.invoice_date:%Y-%m-%d}']
    if invoice.due_date:
        kicker_lines.append(f'Due: {invoice.due_date:%Y-%m-%d}')
    kicker_lines.append('</font>')
    kicker = '<br/>'.join(kicker_lines)

    doc = _NumberedDocTemplate(
        buf, pagesize=letter,
        rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.5 * inch, bottomMargin=0.7 * inch,
        title=f'Invoice {invoice.invoice_number}',
        author=brand_name,
        footer_text=f'{brand_name}  ·  {invoice.invoice_number}',
    )

    story: List[Any] = [
        _header_block(msp, brand_name, kicker),
        Spacer(1, 12),
        Table([
            [Paragraph('<b>From</b>', styles['small']),
             Paragraph('<b>Bill to</b>', styles['small'])],
            [Paragraph(_addr_block(msp), styles['normal']),
             Paragraph(_addr_block(client), styles['normal'])],
        ], colWidths=[3.6 * inch, 3.7 * inch]),
        Spacer(1, 14),
        Paragraph(f'<b>{invoice.title}</b>', styles['h2']),
    ]
    if invoice.description:
        story += [Paragraph(invoice.description.replace('\n', '<br/>'), styles['normal']),
                  Spacer(1, 8)]

    story += [
        Spacer(1, 4),
        _line_items_table(invoice.line_items.all(), currency=invoice.currency),
        Spacer(1, 8),
        _totals_table(
            invoice.subtotal, invoice.tax_amount, invoice.total,
            currency=invoice.currency,
            amount_paid=invoice.amount_paid, balance=invoice.balance,
        ),
    ]
    if invoice.notes:
        story += [
            Spacer(1, 12),
            Paragraph('<b>Notes</b>', styles['h2']),
            Paragraph(invoice.notes.replace('\n', '<br/>'), styles['normal']),
        ]
    if invoice.status == 'paid':
        story += [Spacer(1, 14), Paragraph(
            '<font color="#27ae60" size=14><b>✓ PAID</b></font>', styles['normal'])]

    doc.build(story)
    return buf.getvalue()


# ---- Email helpers ---------------------------------------------------------

def email_quote(quote, *, recipient: str, subject: str = '', body: str = '',
                request=None) -> bool:
    """Email a quote PDF + signing link to the recipient."""
    from django.core.mail import EmailMessage
    sign_url = ''
    if request and quote.customer_token:
        from core.portal_surface import portal_absolute_url
        sign_url = portal_absolute_url(
            f'/portal/quote/{quote.customer_token}/sign/', request
        )
    pdf_bytes = render_quote_pdf(quote, sign_url=sign_url)

    subj = subject or f'Quote {quote.quote_number} from {quote.organization.name}'
    msg_body = body or (
        f'Hello,\n\n'
        f'Please find attached quote {quote.quote_number} for your review.\n'
        + (f'\nTo accept and sign electronically: {sign_url}\n' if sign_url else '')
        + f'\nQuote total: {quote.total:,.2f}\n\n'
        f'Thank you,\n{quote.organization.name}'
    )

    e = EmailMessage(
        subject=subj, body=msg_body,
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    e.attach(f'{quote.quote_number}.pdf', pdf_bytes, 'application/pdf')
    return e.send(fail_silently=False) > 0


def email_invoice(invoice, *, recipient: str, subject: str = '', body: str = '') -> bool:
    """Email an invoice PDF to the recipient."""
    from django.core.mail import EmailMessage
    pdf_bytes = render_invoice_pdf(invoice)

    subj = subject or f'Invoice {invoice.invoice_number} from {invoice.organization.name}'
    msg_body = body or (
        f'Hello,\n\n'
        f'Please find attached invoice {invoice.invoice_number}.\n\n'
        f'Total: {invoice.total:,.2f} {invoice.currency}\n'
        f'Balance due: {invoice.balance:,.2f} {invoice.currency}\n'
        + (f'Due date: {invoice.due_date:%Y-%m-%d}\n' if invoice.due_date else '')
        + f'\nThank you,\n{invoice.organization.name}'
    )

    e = EmailMessage(
        subject=subj, body=msg_body,
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    e.attach(f'{invoice.invoice_number}.pdf', pdf_bytes, 'application/pdf')
    return e.send(fail_silently=False) > 0
