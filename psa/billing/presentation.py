"""Phase 102.5: invoice presentation — one rendering model for the HTML
(staff and portal) and the PDF invoice.

Four layouts of the SAME lines:

    itemized        every line (today's look; the default)
    by_ticket       lines under a heading per ticket (number, subject,
                    subtotal); lines with no ticket under "Other charges"
    monthly         one row per category (labour, items and expenses, fees,
                    agreement fee, account charges, other) with totals;
                    the itemized lines are an optional appendix
    service_report  the monthly summary plus a service report of the
                    tickets worked: number, subject, dates, hours,
                    technicians, resolution summary

Presentation never changes amounts, tax, the line set or the totals: it only
groups and labels lines that already exist, and every group's subtotal is
the sum of its lines' totals. The layout resolves per invoice:

    Invoice.presentation (stored; frozen when the invoice leaves draft)
      > contract override > customer override > Settings → Billing

The service report is written for the customer: it never reads ticket
comments, time-entry notes or anything marked internal. A ticket the
customer may not see (client_can_view off) appears by number only, with
its hours, and no subject or resolution.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal

ITEMIZED, BY_TICKET, MONTHLY, SERVICE_REPORT = 'itemized', 'by_ticket', 'monthly', 'service_report'
LAYOUTS = (
    (ITEMIZED, 'Itemized'),
    (BY_TICKET, 'Grouped by ticket'),
    (MONTHLY, 'Monthly summary'),
    (SERVICE_REPORT, 'Summary + service report'),
)
LAYOUT_KEYS = tuple(k for k, _ in LAYOUTS)
DEFAULT = ITEMIZED
OTHER_CHARGES = 'Other charges'
FOOTER_MAX = 1000

CATEGORIES = (
    ('time', 'Labour'),
    ('expense', 'Items and expenses'),
    ('fee', 'Fees'),
    ('contract', 'Agreement fee'),
    ('charge', 'Account charges'),
    ('other', 'Other'),
)
_CATEGORY_OF = {'time': 'time', 'expense': 'expense', 'fee': 'fee', 'contract': 'contract', 'charge': 'charge'}
_ZERO = Decimal('0.00')


def resolve_layout(invoice):
    """The layout key this invoice renders with right now."""
    if invoice.presentation in LAYOUT_KEYS:
        return invoice.presentation
    from . import config as cfg
    val = cfg.for_invoice(invoice, ['invoice_presentation']).get('invoice_presentation')
    return val if val in LAYOUT_KEYS else DEFAULT


def _line(li):
    return {'description': li.description or '', 'quantity': li.quantity, 'unit_price': li.unit_price,
            'line_total': li.line_total, 'source': li.source, 'source_label': li.get_source_display()}


def _time_entries(lines):
    from psa.models import TicketTimeEntry
    ids = [int(li.source_id) for li in lines if li.source == 'time' and str(li.source_id).isdigit()]
    if not ids:
        return {}
    return {e.pk: e for e in TicketTimeEntry.objects.filter(pk__in=ids).select_related('user', 'ticket')}


def _line_tickets(invoice, lines):
    """{line pk: Ticket or None} for the invoice's own customer only."""
    from psa.models import Ticket
    entries = _time_entries(lines)
    wanted = {}
    for li in lines:
        if li.ticket_id:
            wanted[li.pk] = li.ticket_id
        elif li.source == 'time' and str(li.source_id).isdigit() and int(li.source_id) in entries:
            wanted[li.pk] = entries[int(li.source_id)].ticket_id
        elif invoice.source_ticket_id and li.source in ('manual', 'expense', 'quote_line'):
            wanted[li.pk] = invoice.source_ticket_id
    # A ticket of another customer is never named on this invoice.
    tickets = {t.pk: t for t in Ticket.objects.filter(pk__in=set(wanted.values()),
                                                       organization_id=invoice.client_org_id)}
    return {li.pk: tickets.get(wanted.get(li.pk)) for li in lines}, entries


def _visible_subject(ticket):
    return ticket.subject if ticket.client_can_view else 'Support request'


def build(invoice, layout=None, *, detail=False):
    """The rendering model for `invoice`: {'layout', 'layout_label', 'lines',
    'groups', 'categories', 'report', 'detail'}. Only the parts the layout
    needs are filled."""
    layout = layout if layout in LAYOUT_KEYS else resolve_layout(invoice)
    lines = list(invoice.line_items.all().order_by('sort_order', 'pk'))
    model = {'layout': layout, 'layout_label': dict(LAYOUTS)[layout], 'lines': [_line(li) for li in lines],
             'groups': [], 'categories': [], 'report': [], 'detail': detail}
    if layout == ITEMIZED:
        return model
    if layout in (BY_TICKET, SERVICE_REPORT):
        by_line, entries = _line_tickets(invoice, lines)
    if layout == BY_TICKET:
        groups = OrderedDict()
        other = []
        for li in lines:
            t = by_line.get(li.pk)
            row = _line(li)
            if t is None:
                other.append(row)
                continue
            prefix = f'{t.ticket_number} — '
            if row['description'].startswith(prefix):
                row['description'] = row['description'][len(prefix):]
            g = groups.setdefault(t.pk, {'heading': t.ticket_number, 'subject': _visible_subject(t), 'lines': []})
            g['lines'].append(row)
        out = list(groups.values())
        if other:
            out.append({'heading': OTHER_CHARGES, 'subject': '', 'lines': other})
        for g in out:
            g['subtotal'] = sum((r['line_total'] for r in g['lines']), _ZERO)
        model['groups'] = out
    if layout in (MONTHLY, SERVICE_REPORT):
        cats = OrderedDict((k, {'key': k, 'label': lab, 'count': 0, 'amount': _ZERO}) for k, lab in CATEGORIES)
        for li in lines:
            c = cats[_CATEGORY_OF.get(li.source, 'other')]
            c['count'] += 1
            c['amount'] += li.line_total
        model['categories'] = [c for c in cats.values() if c['count']]
    if layout == SERVICE_REPORT:
        model['report'] = _service_report(by_line, entries, lines)
    return model


def _service_report(by_line, entries, lines):
    rows = OrderedDict()
    for li in lines:
        t = by_line.get(li.pk)
        if t is None:
            continue
        r = rows.setdefault(t.pk, {'number': t.ticket_number, 'subject': _visible_subject(t),
                                   'opened': t.created_at, 'closed': t.closed_at or t.resolved_at,
                                   'minutes': 0, 'first': None, 'last': None, 'technicians': [],
                                   'resolution': (t.resolution_summary or '').strip() if t.client_can_view else ''})
        e = entries.get(int(li.source_id)) if li.source == 'time' and str(li.source_id).isdigit() else None
        if e is None:
            continue
        r['minutes'] += e.duration_minutes or 0
        for attr, fn in (('first', min), ('last', max)):
            r[attr] = e.started_at if r[attr] is None else fn(r[attr], e.started_at)
        if e.user_id:
            name = (e.user.get_full_name() or e.user.get_username() or '').strip()
            if name and name not in r['technicians']:
                r['technicians'].append(name)
    out = list(rows.values())
    for r in out:
        r['hours'] = (Decimal(r['minutes']) / Decimal(60)).quantize(Decimal('0.01'))
        r['technician_names'] = ', '.join(r['technicians'])
    return out


# --- branding ---------------------------------------------------------------------

def branding(invoice):
    """The MSP's branding for an invoice, from existing settings: the MSP
    organization (name, address, contact, logo), falling back to Settings →
    General branding (company name, logo); plus the footer / payment text
    from Settings → Billing. Plain values; every renderer escapes them. The
    logo comes only from the app's own media storage (an ImageField)."""
    from core.models import SystemSetting
    ss = SystemSetting.get_settings()
    org = invoice.organization
    name = (getattr(org, 'name', '') or ss.custom_company_name or ss.site_name or '').strip()
    logo = None
    for field in (getattr(org, 'logo', None), getattr(ss, 'custom_logo', None)):
        if field and getattr(field, 'name', ''):
            logo = field
            break
    lines = [v for v in (getattr(org, 'street_address', ''), getattr(org, 'street_address_2', '')) if v]
    city = ' '.join(filter(None, [getattr(org, 'city', '') or '', getattr(org, 'state', '') or '',
                                   getattr(org, 'postal_code', '') or '']))
    if city.strip():
        lines.append(city)
    country = getattr(org, 'country', '') or ''
    if country and country != 'United States':
        lines.append(country)
    contact = [v for v in (getattr(org, 'phone', ''), getattr(org, 'email', '')) if v]
    return {'name': name, 'logo': logo, 'logo_url': _logo_url(logo), 'address': lines, 'contact': contact,
            'footer': (ss.invoice_footer_text or '').strip()}


def _logo_url(field):
    if not field:
        return ''
    try:
        return field.url
    except Exception:  # noqa: BLE001 — a missing file never breaks the invoice
        return ''
