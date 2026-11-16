"""Payment receipt PDF, built with the same ReportLab layout as invoices
(psa.pdf). Customer-facing fields only."""
from __future__ import annotations

import io

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table

from psa.pdf import _NumberedDocTemplate, _addr_block, _header_block, _styles


def _esc(value) -> str:
    from xml.sax.saxutils import escape
    return escape(str(value or ''))


def render_receipt_pdf(payment) -> bytes:
    invoice = payment.invoice
    styles = _styles()
    msp, client = invoice.organization, invoice.client_org
    brand = getattr(msp, 'name', '') or 'Receipt'
    attempt = getattr(payment, 'gateway_attempt', None) if hasattr(payment, 'gateway_attempt') else None
    method = payment.get_method_display()
    if attempt is not None and attempt.payment_method_id:
        method = attempt.payment_method.display
    elif attempt is not None:
        method = f'{method} via {attempt.get_provider_display()}'

    buf = io.BytesIO()
    kicker = (f'<font size=18 color="#2c3e50"><b>RECEIPT</b></font><br/>'
              f'<font size=10>{_esc(invoice.invoice_number)}</font><br/>'
              f'<font size=8 color="#7f8c8d">Paid: {payment.paid_on:%Y-%m-%d}</font>')
    doc = _NumberedDocTemplate(buf, pagesize=letter, rightMargin=0.6 * inch, leftMargin=0.6 * inch,
                               topMargin=0.5 * inch, bottomMargin=0.7 * inch,
                               title=f'Receipt {invoice.invoice_number}', author=brand,
                               footer_text=f'{brand}  ·  receipt {payment.pk}')
    rows = [
        ['Invoice', _esc(invoice.invoice_number)],
        ['Description', _esc(invoice.title)],
        ['Amount paid', f'{payment.amount:,.2f} {_esc(invoice.currency)}'],
        ['Payment method', _esc(method)],
        ['Reference', _esc(payment.reference)],
        ['Invoice total', f'{invoice.total:,.2f} {_esc(invoice.currency)}'],
        ['Balance remaining', f'{invoice.net_balance_due:,.2f} {_esc(invoice.currency)}'],
    ]
    story = [
        _header_block(msp, brand, kicker), Spacer(1, 12),
        Table([[Paragraph('<b>From</b>', styles['small']), Paragraph('<b>Received from</b>', styles['small'])],
               [Paragraph(_addr_block(msp), styles['normal']), Paragraph(_addr_block(client), styles['normal'])]],
              colWidths=[3.6 * inch, 3.7 * inch]),
        Spacer(1, 14),
        Table([[Paragraph(f'<b>{k}</b>', styles['normal']), Paragraph(v, styles['normal'])] for k, v in rows],
              colWidths=[2.0 * inch, 5.3 * inch]),
        Spacer(1, 14),
        Paragraph('Thank you for your payment.', styles['normal']),
    ]
    doc.build(story)
    return buf.getvalue()
