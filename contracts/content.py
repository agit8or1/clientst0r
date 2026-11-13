"""Draft content: sections, line items, totals, merge fields, and the frozen
content of an issued version.

Merge fields are written `{{client.name}}`. They are looked up in a fixed
dictionary of plain strings and inserted HTML-escaped — nothing in a template
is ever evaluated as code. Text in double square brackets, `[[like this]]`, is
a note for whoever prepares the contract ("describe the project scope") and
blocks sending until it is replaced.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import ContractSigner
from .sanitize import clean_html, plain_text

SECTION_TYPES = [('text', 'Text'), ('pricing', 'Pricing table'), ('signatures', 'Signature blocks')]
LINE_KINDS = [('one_time', 'One-time'), ('recurring', 'Recurring')]
MAX_SECTIONS = 80
MAX_LINES = 200
MAX_SECTION_HTML = 200_000

MERGE_FIELDS = [
    ('Client', [('client.name', 'Client name'), ('client.legal_name', 'Client legal name'),
                ('client.address', 'Client address'), ('client.email', 'Client e-mail'),
                ('client.phone', 'Client phone')]),
    ('Provider', [('provider.name', 'Provider name'), ('provider.address', 'Provider address'),
                  ('provider.email', 'Provider e-mail'), ('provider.phone', 'Provider phone'),
                  ('provider.website', 'Provider website')]),
    ('Contacts', [('contact.name', 'Primary client contact'), ('contact.email', 'Primary contact e-mail'),
                  ('contact.title', 'Primary contact title'), ('owner.name', 'Contract owner'),
                  ('owner.email', 'Owner e-mail'), ('account_manager.name', 'Account manager'),
                  ('account_manager.email', 'Account manager e-mail')]),
    ('Signers', [('signer1.name', 'Client signer 1 name'), ('signer1.title', 'Client signer 1 title'),
                 ('signer2.name', 'Client signer 2 name'), ('signer2.title', 'Client signer 2 title'),
                 ('countersigner.name', 'Countersigner name'), ('countersigner.title', 'Countersigner title')]),
    ('Contract', [('contract.reference', 'Contract number'), ('contract.title', 'Contract title'),
                  ('contract.effective_date', 'Effective date'), ('contract.expiration_date', 'Expiration date'),
                  ('contract.duration_months', 'Duration (months)'), ('contract.renewal_terms', 'Renewal terms'),
                  ('contract.notice_period_days', 'Notice period (days)'),
                  ('contract.acceptance_deadline', 'Acceptance deadline'), ('today', "Today's date")]),
    ('Pricing', [('pricing.one_time_total', 'One-time total'), ('pricing.recurring_total', 'Recurring total'),
                 ('pricing.billing_frequency', 'Billing frequency'), ('pricing.payment_terms', 'Payment terms'),
                 ('pricing.currency', 'Currency'), ('services.list', 'List of services')]),
]
MERGE_KEYS = {k for _g, items in MERGE_FIELDS for k, _l in items}
_FIELD_RE = re.compile(r'\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*)\s*\}\}')
_NOTE_RE = re.compile(r'\[\[(.{1,300}?)\]\]', re.S)
TWO = Decimal('0.01')


class ContentError(ValueError):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__('; '.join(self.errors))


def money(value) -> Decimal:
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def _dec(value, field, errors, default='0', minimum=Decimal('0'), maximum=Decimal('100000000')):
    raw = str(value if value not in (None, '') else default).strip().replace(',', '')
    try:
        d = Decimal(raw)
    except InvalidOperation:
        errors.append(f'{field}: "{raw[:20]}" is not a number.')
        return Decimal(default)
    if not d.is_finite() or d < minimum or d > maximum:
        errors.append(f'{field}: must be between {minimum} and {maximum}.')
        return Decimal(default)
    return d


def new_key() -> str:
    return uuid.uuid4().hex[:10]


def normalize_sections(raw, errors=None) -> list[dict]:
    errors = errors if errors is not None else []
    out = []
    for i, s in enumerate((raw or [])[:MAX_SECTIONS]):
        if not isinstance(s, dict):
            continue
        stype = s.get('type') if s.get('type') in dict(SECTION_TYPES) else 'text'
        body = s.get('body') or ''
        if len(body) > MAX_SECTION_HTML:
            errors.append(f'Section {i + 1} is too long.')
            body = body[:MAX_SECTION_HTML]
        key = str(s.get('key') or '')[:20]
        if not re.fullmatch(r'[a-z0-9]{1,20}', key):
            key = new_key()
        out.append({'key': key, 'title': plain_text(s.get('title'), 200), 'type': stype,
                    'body': clean_html(body), 'include': bool(s.get('include', True)),
                    'optional': bool(s.get('optional', False))})
    keys = set()
    for s in out:
        if s['key'] in keys:
            s['key'] = new_key()
        keys.add(s['key'])
    return out


def normalize_line_items(raw, errors=None) -> list[dict]:
    errors = errors if errors is not None else []
    out = []
    for i, li in enumerate((raw or [])[:MAX_LINES]):
        if not isinstance(li, dict):
            continue
        desc = plain_text(li.get('description'), 300)
        if not desc and not str(li.get('unit_price') or '').strip():
            continue
        label = f'Line {i + 1}'
        if not desc:
            errors.append(f'{label}: enter a description.')
        kind = li.get('kind') if li.get('kind') in dict(LINE_KINDS) else 'one_time'
        out.append({
            'description': desc, 'kind': kind,
            'quantity': str(_dec(li.get('quantity'), f'{label} quantity', errors, '1')),
            'unit_price': str(money(_dec(li.get('unit_price'), f'{label} unit price', errors))),
            'discount_percent': str(_dec(li.get('discount_percent'), f'{label} discount', errors, '0',
                                         maximum=Decimal('100'))),
            'taxable': bool(li.get('taxable', False)),
        })
    return out


def totals(line_items, tax_rate) -> dict:
    rate = Decimal(str(tax_rate or 0))
    out = {}
    for kind in ('one_time', 'recurring'):
        sub = disc = taxable = Decimal('0')
        for li in line_items:
            if li['kind'] != kind:
                continue
            gross = Decimal(li['quantity']) * Decimal(li['unit_price'])
            d = gross * Decimal(li['discount_percent']) / Decimal('100')
            sub += gross
            disc += d
            if li['taxable']:
                taxable += gross - d
        tax = taxable * rate / Decimal('100')
        out[kind] = {'subtotal': str(money(sub)), 'discount': str(money(disc)), 'tax': str(money(tax)),
                     'total': str(money(sub - disc + tax))}
    return out


def line_total(li) -> Decimal:
    gross = Decimal(li['quantity']) * Decimal(li['unit_price'])
    return money(gross - gross * Decimal(li['discount_percent']) / Decimal('100'))


def fmt_date(d) -> str:
    if not d:
        return ''
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d)
        except ValueError:
            return d
    return f'{d:%B} {d.day}, {d.year}'


def fmt_money(value, currency='USD') -> str:
    d = money(Decimal(str(value or 0)))
    symbol = {'USD': '$', 'CAD': '$', 'AUD': '$', 'NZD': '$', 'EUR': '€', 'GBP': '£'}.get(currency, '')
    text = f'{d:,.2f}'
    return f'{symbol}{text}' if symbol else f'{text} {currency}'


def _user_name(u):
    return (u.get_full_name() or u.username) if u is not None else ''


def merge_context(contract, settings, signers=None) -> dict:
    org = contract.organization
    signers = list(signers if signers is not None else contract.signers.all())
    client_signers = [s for s in signers if s.role == ContractSigner.CLIENT]
    internal = [s for s in signers if s.role == ContractSigner.INTERNAL]
    t = totals(contract.line_items or [], contract.tax_rate)
    addr = ''
    if org is not None:
        parts = [org.street_address, org.street_address_2,
                 ' '.join(p for p in [org.city, org.state, org.postal_code] if p), org.country]
        addr = ', '.join(p for p in parts if p)
    ctx = {
        'client.name': org.name if org else contract.organization_name,
        'client.legal_name': (org.legal_name or org.name) if org else contract.organization_name,
        'client.address': addr, 'client.email': org.email if org else '', 'client.phone': org.phone if org else '',
        'provider.name': settings.provider_display_name(), 'provider.address': settings.provider_address,
        'provider.email': settings.provider_email, 'provider.phone': settings.provider_phone,
        'provider.website': settings.provider_website,
        'contact.name': client_signers[0].name if client_signers else (org.primary_contact_name if org else ''),
        'contact.email': client_signers[0].email if client_signers else (org.primary_contact_email if org else ''),
        'contact.title': client_signers[0].title if client_signers else (org.primary_contact_title if org else ''),
        'owner.name': _user_name(contract.owner), 'owner.email': contract.owner.email if contract.owner else '',
        'account_manager.name': _user_name(contract.account_manager),
        'account_manager.email': contract.account_manager.email if contract.account_manager else '',
        'countersigner.name': internal[0].name if internal else '',
        'countersigner.title': internal[0].title if internal else '',
        'contract.reference': contract.reference, 'contract.title': contract.title,
        'contract.effective_date': fmt_date(contract.effective_date),
        'contract.expiration_date': fmt_date(contract.expiration_date),
        'contract.duration_months': str(contract.duration_months) if contract.duration_months else '',
        'contract.renewal_terms': contract.renewal_terms,
        'contract.notice_period_days': str(contract.notice_period_days) if contract.notice_period_days else '',
        'contract.acceptance_deadline': fmt_date(contract.acceptance_deadline),
        'today': fmt_date(date.today()),
        'pricing.one_time_total': fmt_money(t['one_time']['total'], contract.currency),
        'pricing.recurring_total': fmt_money(t['recurring']['total'], contract.currency),
        'pricing.billing_frequency': contract.get_billing_frequency_display(),
        'pricing.payment_terms': contract.payment_terms, 'pricing.currency': contract.currency,
        'services.list': ', '.join(li['description'] for li in (contract.line_items or [])),
    }
    for i in range(1, 6):
        s = client_signers[i - 1] if len(client_signers) >= i else None
        ctx[f'signer{i}.name'] = s.name if s else ''
        ctx[f'signer{i}.email'] = s.email if s else ''
        ctx[f'signer{i}.title'] = s.title if s else ''
    return ctx


def resolve(text_html: str, ctx: dict, *, preview=False):
    """(html, unresolved) — merge fields replaced with escaped values."""
    unresolved = []

    def field(m):
        key = m.group(1)
        value = ctx.get(key)
        if value:
            return html.escape(str(value))
        unresolved.append('{{' + key + '}}' + ('' if key in ctx else ' (unknown field)'))
        return f'<span class="cd-unresolved">{m.group(0)}</span>' if preview else m.group(0)

    out = _FIELD_RE.sub(field, text_html or '')
    for m in _NOTE_RE.finditer(out):
        unresolved.append(f'[[{m.group(1)[:60]}]]')
    if preview:
        out = _NOTE_RE.sub(lambda m: f'<span class="cd-unresolved">{m.group(0)}</span>', out)
    return out, unresolved


def resolve_plain(text: str, ctx: dict) -> str:
    return _FIELD_RE.sub(lambda m: str(ctx.get(m.group(1), '')), text or '')


# --- issued content ----------------------------------------------------------

def signer_specs(signers) -> list[dict]:
    """Who signs, by role and order, as frozen in the version. Names and
    addresses live on the invitations, so a mistyped address can be
    corrected (replace the invitation) without changing the agreement."""
    client = sorted([s for s in signers if s.role == ContractSigner.CLIENT], key=lambda s: (s.order, s.pk or 0))
    internal = sorted([s for s in signers if s.role == ContractSigner.INTERNAL], key=lambda s: (s.order, s.pk or 0))
    specs = []
    for i, s in enumerate(client, start=1):
        specs.append({'ref': len(specs), 'role': 'client', 'label': f'Client signer {i}', 'order': i})
    for i, s in enumerate(internal, start=1):
        specs.append({'ref': len(specs), 'role': 'internal',
                      'label': 'Countersignature' if len(internal) == 1 else f'Countersignature {i}',
                      'order': len(client) + i})
    return specs


def ordered_signers(signers):
    client = sorted([s for s in signers if s.role == ContractSigner.CLIENT], key=lambda s: (s.order, s.pk or 0))
    internal = sorted([s for s in signers if s.role == ContractSigner.INTERNAL], key=lambda s: (s.order, s.pk or 0))
    return client + internal


def build_content(contract, settings, signing, *, preview=False):
    """(content dict, unresolved list). `signing` is the effective signing
    configuration {order, verification, countersignature, approval}."""
    signers = list(contract.signers.all())
    ctx = merge_context(contract, settings, signers)
    unresolved = []
    sections = []
    for s in normalize_sections(contract.sections):
        if not s['include']:
            continue
        body, missing = resolve(s['body'], ctx, preview=preview)
        title, missing_t = resolve(html.escape(s['title']), ctx, preview=preview)
        unresolved += [f'{s["title"] or "Untitled section"}: {m}' for m in missing + missing_t]
        sections.append({'key': s['key'], 'type': s['type'], 'title': title, 'html': body})
    items = normalize_line_items(contract.line_items)
    org = contract.organization
    content = {
        'schema': 'clientst0r.contract.v1',
        'contract': {'id': contract.pk, 'reference': contract.reference, 'title': contract.title,
                     'kind': contract.kind},
        'client': {'id': org.pk if org else None, 'name': ctx['client.name'],
                   'legal_name': ctx['client.legal_name'], 'address': ctx['client.address']},
        'provider': {'name': ctx['provider.name'], 'address': settings.provider_address,
                     'email': settings.provider_email, 'phone': settings.provider_phone,
                     'website': settings.provider_website},
        'terms': {
            'effective_date': contract.effective_date.isoformat() if contract.effective_date else '',
            'duration_months': contract.duration_months or None,
            'expiration_date': contract.expiration_date.isoformat() if contract.expiration_date else '',
            'renewal_terms': contract.renewal_terms, 'auto_renew': contract.auto_renew,
            'notice_period_days': contract.notice_period_days or None,
            'payment_terms': contract.payment_terms, 'billing_frequency': contract.billing_frequency,
            'billing_frequency_label': contract.get_billing_frequency_display(),
            'currency': contract.currency, 'tax_rate': str(contract.tax_rate),
            'acceptance_deadline': contract.acceptance_deadline.isoformat() if contract.acceptance_deadline else '',
        },
        'sections': sections,
        'line_items': items,
        'totals': totals(items, contract.tax_rate),
        'signers': signer_specs(signers),
        'attachments': [{'id': a.pk, 'name': a.name, 'size': a.size, 'sha256': a.sha256}
                        for a in contract.attachments.filter(removed_at__isnull=True).order_by('pk')],
        'signing': signing,
    }
    return content, unresolved


def validate_for_issue(contract, unresolved, signing) -> list[str]:
    errors = []
    if not contract.title.strip():
        errors.append('Enter a contract title.')
    if contract.organization_id is None:
        errors.append('The contract has no client.')
    signers = list(contract.signers.all())
    client = [s for s in signers if s.role == ContractSigner.CLIENT]
    internal = [s for s in signers if s.role == ContractSigner.INTERNAL]
    if not client:
        errors.append('Add at least one client signer.')
    for s in signers:
        if not s.name.strip() or not s.email.strip():
            errors.append('Every signer needs a name and an e-mail address.')
            break
    emails = [s.email.lower() for s in signers]
    if len(emails) != len(set(emails)):
        errors.append('Each signer needs a different e-mail address.')
    if signing.get('countersignature') and not internal:
        errors.append('Countersignature is required: add an internal countersigner.')
    if not any(s.get('include', True) for s in (contract.sections or [])):
        errors.append('Include at least one section.')
    if contract.effective_date and contract.expiration_date and contract.expiration_date < contract.effective_date:
        errors.append('The expiration date is before the effective date.')
    item_errors = []
    normalize_line_items(contract.line_items, item_errors)
    errors += item_errors
    if unresolved:
        errors.append('Replace every placeholder before sending: ' + ', '.join(unresolved[:12])
                      + (' …' if len(unresolved) > 12 else ''))
    return errors


# --- rendering -----------------------------------------------------------------

def _esc(v):
    return html.escape(str(v or ''))


def _pricing_html(content) -> str:
    items = content['line_items']
    cur = content['terms']['currency']
    if not items:
        return '<p><em>No priced items.</em></p>'
    out = []
    for kind, label in (('one_time', 'One-time charges'), ('recurring',
                                                           f'Recurring charges ({_esc(content["terms"]["billing_frequency_label"])})')):
        rows = [li for li in items if li['kind'] == kind]
        if not rows:
            continue
        t = content['totals'][kind]
        out.append(f'<h3>{label}</h3><table class="cd-pricing"><thead><tr><th>Description</th><th>Qty</th>'
                   '<th>Unit price</th><th>Discount</th><th>Amount</th></tr></thead><tbody>')
        for li in rows:
            disc = f'{Decimal(li["discount_percent"]).normalize():f}%' if Decimal(li['discount_percent']) else ''
            out.append(f'<tr><td>{_esc(li["description"])}{" *" if li["taxable"] else ""}</td>'
                       f'<td>{Decimal(li["quantity"]).normalize():f}</td><td>{fmt_money(li["unit_price"], cur)}</td>'
                       f'<td>{disc}</td><td>{fmt_money(line_total(li), cur)}</td></tr>')
        out.append(f'</tbody><tfoot><tr><td colspan="4">Subtotal</td><td>{fmt_money(t["subtotal"], cur)}</td></tr>')
        if Decimal(t['discount']):
            out.append(f'<tr><td colspan="4">Discounts</td><td>-{fmt_money(t["discount"], cur)}</td></tr>')
        if Decimal(t['tax']):
            out.append(f'<tr><td colspan="4">Tax ({_esc(content["terms"]["tax_rate"])}%)</td>'
                       f'<td>{fmt_money(t["tax"], cur)}</td></tr>')
        out.append(f'<tr><th colspan="4">Total {"per period" if kind == "recurring" else ""}</th>'
                   f'<th>{fmt_money(t["total"], cur)}</th></tr></tfoot></table>')
    if any(li['taxable'] for li in items):
        out.append('<p class="cd-note">* taxable</p>')
    if content['terms']['payment_terms']:
        out.append(f'<p>Payment terms: {_esc(content["terms"]["payment_terms"])}</p>')
    return ''.join(out)


def _signatures_html(content, signatures=None) -> str:
    by_ref = {s['ref']: s for s in (signatures or [])}
    out = ['<div class="cd-signatures">']
    for spec in content['signers']:
        sig = by_ref.get(spec['ref'])
        party = content['client']['name'] if spec['role'] == 'client' else content['provider']['name']
        out.append(f'<div class="cd-sigblock"><p class="cd-sigparty">{_esc(spec["label"])} — for {_esc(party)}</p>')
        if sig:
            out.append(f'<p class="cd-sigmark">{_esc(sig["mark"])}</p>'
                       f'<p>{_esc(sig["printed_name"])}{", " + _esc(sig["title"]) if sig["title"] else ""}<br>'
                       f'Signed {_esc(sig["signed_at"])}</p>')
        else:
            out.append('<p class="cd-sigline">Signature: ______________________</p>'
                       '<p>Name / title: ______________________<br>Date: ____________</p>')
        out.append('</div>')
    out.append('</div>')
    return ''.join(out)


def key_terms(content) -> list[tuple[str, str]]:
    t = content['terms']
    rows = []
    if t['effective_date']:
        rows.append(('Effective date', fmt_date(t['effective_date'])))
    if t['duration_months']:
        rows.append(('Term', f'{t["duration_months"]} months'))
    if t['expiration_date']:
        rows.append(('Expiration date', fmt_date(t['expiration_date'])))
    if t['renewal_terms'] or t['auto_renew']:
        rows.append(('Renewal', (t['renewal_terms'] or '') + (' (renews automatically)' if t['auto_renew'] else '')))
    if t['notice_period_days']:
        rows.append(('Notice period', f'{t["notice_period_days"]} days'))
    if t['payment_terms']:
        rows.append(('Payment terms', t['payment_terms']))
    rows.append(('Billing frequency', t['billing_frequency_label']))
    if t['acceptance_deadline']:
        rows.append(('Accept by', fmt_date(t['acceptance_deadline'])))
    return rows


def render_body(content, *, version_number=None, signatures=None) -> str:
    c, p = content['client'], content['provider']
    ver = f' · Version {version_number}' if version_number else ''
    out = [f'<div class="cd-doc"><h1>{_esc(content["contract"]["title"])}</h1>'
           f'<p class="cd-ref">Contract {_esc(content["contract"]["reference"])}{ver}</p>',
           '<table class="cd-parties"><tr><th>Provider</th><th>Client</th></tr><tr>'
           f'<td>{_esc(p["name"])}<br>{_esc(p["address"])}<br>{_esc(p["email"])} {_esc(p["phone"])}</td>'
           f'<td>{_esc(c["legal_name"] or c["name"])}<br>{_esc(c["address"])}</td></tr></table>',
           '<table class="cd-terms">']
    for k, v in key_terms(content):
        out.append(f'<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>')
    out.append('</table>')
    n = 0
    for s in content['sections']:
        n += 1
        out.append(f'<section class="cd-section"><h2>{n}. {s["title"]}</h2>')
        if s['type'] == 'pricing':
            out.append(s['html'] + _pricing_html(content))
        elif s['type'] == 'signatures':
            out.append(s['html'] + _signatures_html(content, signatures))
        else:
            out.append(s['html'])
        out.append('</section>')
    if content['attachments']:
        out.append('<section class="cd-section"><h2>Exhibits</h2><ul>')
        for a in content['attachments']:
            out.append(f'<li>{_esc(a["name"])} ({a["size"]} bytes, SHA-256 {a["sha256"][:16]}…)</li>')
        out.append('</ul></section>')
    out.append('</div>')
    return ''.join(out)


DOC_CSS = """
.cd-doc{font-family:Georgia,'Times New Roman',serif;color:#1d232a;line-height:1.5;max-width:860px;margin:0 auto}
.cd-doc h1{font-size:1.7rem;margin:0 0 .2rem}
.cd-doc h2{font-size:1.2rem;margin:1.6rem 0 .5rem;border-bottom:1px solid #d5dbe1;padding-bottom:.2rem}
.cd-doc h3{font-size:1rem;margin:1rem 0 .4rem}
.cd-ref{color:#5a6772;margin:0 0 1rem;font-size:.9rem}
.cd-doc table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}
.cd-doc th,.cd-doc td{border:1px solid #d5dbe1;padding:.35rem .5rem;text-align:left;vertical-align:top}
.cd-doc .cd-terms th{width:35%;background:#f3f6f8}
.cd-pricing td:not(:first-child),.cd-pricing th:not(:first-child){text-align:right}
.cd-note{font-size:.85rem;color:#5a6772}
.cd-signatures{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
.cd-sigblock{border:1px solid #d5dbe1;padding:.75rem;border-radius:4px}
.cd-sigparty{font-weight:bold;margin:0 0 .5rem}
.cd-sigmark{font-style:italic;font-size:1.4rem;margin:.2rem 0}
.cd-unresolved{background:#ffe08a;padding:0 .15rem}
hr.page-break{border:0;border-top:1px dashed #9aa5b1;margin:1.5rem 0}
@media print{hr.page-break{border:0;page-break-after:always;break-after:page}}
@media (max-width:600px){.cd-doc h1{font-size:1.35rem}.cd-doc table{font-size:.85rem}}
"""


def snapshot_html(content, body) -> str:
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<title>{_esc(content["contract"]["title"])}</title>\n<style>{DOC_CSS}</style>\n</head>\n'
            f'<body>\n{body}\n</body>\n</html>\n')
