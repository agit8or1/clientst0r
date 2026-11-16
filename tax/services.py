"""Sales tax calculation.

    calculate_tax(document, lines=None, ship_to=None, customer=None,
                  commit=False, user=None, purpose='preview') -> TaxOutcome
    finalize_document(document, user) -> TaxOutcome      (gate before sending)
    apply_manual_override(document, user, amount, reason, request=None)

HARD RULE: when the configured provider fails, the outcome is status
'error' with no tax amount, the document's tax is left as it was, and
finalize_document refuses to let the document be sent. Nothing here falls
back to zero. Only a user holding `manage_tax_settings` can unblock it, with
an explicit, audited manual override (apply_manual_override).

Every call records a TaxCalculation (the audit / reconciliation trail); the
newest one for a document is its current one.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    CustomerTaxExemption, LineTaxCategory, ManualTaxRate, TaxCalculation, TaxCategory, TaxSettings,
)

logger = logging.getLogger('tax')

CENT = Decimal('0.01')
OK, ERROR, EXEMPT, NOT_CONFIGURED = (TaxCalculation.STATUS_OK, TaxCalculation.STATUS_ERROR,
                                     TaxCalculation.STATUS_EXEMPT, TaxCalculation.STATUS_NOT_CONFIGURED)
APPLIED_STATUSES = (OK, EXEMPT, NOT_CONFIGURED)

COUNTRY_CODES = {
    'united states': 'US', 'united states of america': 'US', 'usa': 'US', 'us': 'US', 'u.s.': 'US',
    'canada': 'CA', 'united kingdom': 'GB', 'uk': 'GB', 'great britain': 'GB', 'australia': 'AU',
    'new zealand': 'NZ', 'ireland': 'IE', 'germany': 'DE', 'france': 'FR', 'mexico': 'MX',
}


def _money(v) -> Decimal:
    return Decimal(str(v or '0')).quantize(CENT, rounding=ROUND_HALF_UP)


def country_code(value: str) -> str:
    v = (value or '').strip()
    if not v:
        return 'US'
    if len(v) == 2:
        return v.upper()
    return COUNTRY_CODES.get(v.lower(), v[:2].upper())


# --- documents ----------------------------------------------------------------------

def document_type(document) -> str:
    name = document._meta.model_name
    if name == 'invoice':
        return 'invoice'
    if name == 'quote':
        return 'quote'
    raise ValueError(f'Sales tax applies to quotes and invoices, not {name}')


def document_number(document) -> str:
    return getattr(document, 'invoice_number', None) or getattr(document, 'quote_number', '') or str(document.pk)


def line_type_for(document) -> str:
    return 'invoice_line' if document_type(document) == 'invoice' else 'quote_line'


def document_date(document):
    d = getattr(document, 'invoice_date', None) or timezone.localdate()
    if isinstance(d, str):  # an unsaved / unrefreshed instance built with a string
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            d = timezone.localdate()
    return d


def ship_to_for(document=None, customer=None) -> Dict[str, str]:
    """The customer's billing address (core.Organization address fields)."""
    org = customer or document.client_org
    return {
        'line1': org.street_address or '', 'line2': org.street_address_2 or '',
        'city': org.city or '', 'county': getattr(org, 'county', '') or '',
        'region': (org.state or '').strip().upper(), 'postal_code': (org.postal_code or '').strip(),
        'country': country_code(org.country),
    }


def region_key(ship_to) -> str:
    return f'{ship_to.get("country") or "US"}-{ship_to.get("region") or ""}'.upper()


# --- configuration lookup ------------------------------------------------------------

def settings_for(org=None) -> Optional[TaxSettings]:
    """The install-wide tax settings, or None. One MSP per install: tax
    settings, rates and categories are MSP-wide (organization blank); `org`
    is accepted for call-site symmetry and ignored."""
    return (TaxSettings.objects.filter(organization__isnull=True).select_related('connection')
            .order_by('pk').first())


def effective_mode(org=None) -> str:
    """No settings at all keeps the historical flat-rate behaviour."""
    s = settings_for()
    return s.mode if s is not None else TaxSettings.MODE_FLAT


def categories_for(org=None) -> Dict[str, TaxCategory]:
    """code -> install-wide category."""
    return {c.code: c for c in TaxCategory.objects.filter(organization__isnull=True)}


def _default_category(cats: Dict[str, TaxCategory], kind: str = '') -> Optional[TaxCategory]:
    if kind:
        of_kind = [c for c in cats.values() if c.kind == kind]
        if of_kind:
            return sorted(of_kind, key=lambda c: (not c.is_default, c.code))[0]
        return None
    defaults = [c for c in cats.values() if c.is_default]
    return sorted(defaults, key=lambda c: c.code)[0] if defaults else None


def resolve_line_category(line, document, cats=None) -> Optional[TaxCategory]:
    """Explicit assignment, else labor for time-entry lines, else the default."""
    cats = cats if cats is not None else categories_for(document.organization_id)
    allowed = {c.pk for c in cats.values()}
    if getattr(line, 'pk', None):
        a = LineTaxCategory.objects.filter(line_type=line_type_for(document), line_id=line.pk,
                                           category_id__in=allowed).select_related('category').first()
        if a is not None:
            return a.category
    if getattr(line, 'source', '') == 'time':
        labor = _default_category(cats, 'labor')
        if labor is not None:
            return labor
    return _default_category(cats)


def _specificity(rate: ManualTaxRate) -> int:
    if rate.zip_pattern and not rate.zip_pattern.endswith('*'):
        return 5
    if rate.zip_pattern:
        return 4
    if rate.city:
        return 3
    if rate.county:
        return 2
    if rate.state:
        return 1
    return 0


def _rate_matches(rate: ManualTaxRate, ship_to) -> bool:
    if (rate.country or 'US').upper() != (ship_to.get('country') or 'US').upper():
        return False
    if rate.state and rate.state.strip().upper() != (ship_to.get('region') or '').upper():
        return False
    if rate.county and rate.county.strip().lower() != (ship_to.get('county') or '').strip().lower():
        return False
    if rate.city and rate.city.strip().lower() != (ship_to.get('city') or '').strip().lower():
        return False
    if rate.zip_pattern:
        z = (ship_to.get('postal_code') or '').strip()
        pat = rate.zip_pattern.strip()
        if pat.endswith('*'):
            if not z.startswith(pat[:-1]):
                return False
        elif z[:len(pat)] != pat or (len(z) > len(pat) and z[len(pat)] not in '-'):
            return False
    return True


def match_manual_rate(org, ship_to, on_date) -> Optional[ManualTaxRate]:
    """The single most specific active install-wide rate for the address
    (the customer's billing address) on that date; at equal specificity the
    most recent effective_from wins. `org` is ignored (MSP-wide rates)."""
    qs = (ManualTaxRate.objects.filter(organization__isnull=True, is_active=True)
          .filter(Q(effective_from__isnull=True) | Q(effective_from__lte=on_date))
          .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
          .prefetch_related('applies_to'))
    candidates = [r for r in qs if _rate_matches(r, ship_to)]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (_specificity(r), r.effective_from or date.min, r.pk), reverse=True)
    return candidates[0]


def active_exemption(customer, on_date, ship_to) -> Optional[CustomerTaxExemption]:
    rk = region_key(ship_to)
    for ex in CustomerTaxExemption.objects.filter(client=customer, is_active=True):
        if ex.covers(on_date, rk):
            return ex
    return None


# --- fingerprints ---------------------------------------------------------------------

def _line_rows(document, lines, cats):
    rows = []
    for li in lines:
        cat = resolve_line_category(li, document, cats)
        rows.append({'line': li, 'category': cat, 'amount': _money(li.line_total)})
    return rows


def lines_fingerprint(document, lines=None, ship_to=None, cats=None) -> str:
    lines = list(document.line_items.all()) if lines is None else list(lines)
    cats = cats if cats is not None else categories_for(document.organization_id)
    ship_to = ship_to or ship_to_for(document)
    body = {
        'client': document.client_org_id,
        'ship_to': {k: ship_to.get(k, '') for k in ('city', 'county', 'region', 'postal_code', 'country')},
        'lines': [[li.pk, str(li.description), str(li.quantity), str(li.unit_price), bool(li.is_taxable),
                   getattr(resolve_line_category(li, document, cats), 'code', '')] for li in lines],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def current_calculation(document) -> Optional[TaxCalculation]:
    return (TaxCalculation.objects.filter(document_type=document_type(document), document_id=document.pk,
                                          is_current=True).order_by('-created_at', '-pk').first())


def calculation_history(document):
    return TaxCalculation.objects.filter(document_type=document_type(document), document_id=document.pk)


# --- outcome --------------------------------------------------------------------------

@dataclass
class TaxOutcome:
    status: str
    total_tax: Optional[Decimal]
    provider: str
    message: str = ''
    lines: List[Dict[str, Any]] = field(default_factory=list)
    jurisdictions: List[Dict[str, Any]] = field(default_factory=list)
    calculation: Optional[TaxCalculation] = None
    exemption: Optional[CustomerTaxExemption] = None

    @property
    def ok(self) -> bool:
        return self.status != ERROR

    @property
    def blocked(self) -> bool:
        return self.status == ERROR


# --- line taxability ----------------------------------------------------------------

def line_taxable(line, category, tax_settings, rate=None) -> (bool, str):
    """(taxable, why-not). The line's own is_taxable flag, then the
    category, with labor and shipping following the settings (a jurisdiction
    rate may override labor), then the rate's category list."""
    if not getattr(line, 'is_taxable', True):
        return False, 'line marked non-taxable'
    if category is not None:
        if category.kind == 'labor':
            labor = tax_settings.labor_taxable if tax_settings is not None else False
            if rate is not None and rate.labor_taxable is not None:
                labor = rate.labor_taxable
            if not labor:
                return False, 'labor not taxable'
            if not category.taxable:
                return False, f'category {category.code} not taxable'
        elif category.kind == 'shipping':
            if not (tax_settings is not None and tax_settings.shipping_taxable):
                return False, 'shipping not taxable'
        elif not category.taxable:
            return False, f'category {category.code} not taxable'
    if rate is not None:
        applies = list(rate.applies_to.all())
        if applies and (category is None or category.pk not in {c.pk for c in applies}):
            return False, f'{rate.name} does not tax this category'
    return True, ''


# --- calculation ---------------------------------------------------------------------

def _record(document, outcome: TaxOutcome, *, purpose, user, ship_to, fingerprint, request_hash='',
            taxable_amount=Decimal('0'), committed=False, transaction_code='', error='', reason=''):
    # A failed attempt never displaces a still-valid manual override: the
    # failure is kept in the history, the override stays current.
    keep = False
    if outcome.status == ERROR:
        cur = current_calculation(document)
        keep = bool(cur is not None and cur.provider == 'override' and cur.lines_fingerprint == fingerprint)
    with transaction.atomic():
        if not keep:
            TaxCalculation.objects.filter(document_type=document_type(document), document_id=document.pk,
                                          is_current=True).update(is_current=False)
        calc = TaxCalculation.objects.create(
            organization_id=document.organization_id, document_type=document_type(document),
            document_id=document.pk, document_number=document_number(document),
            provider=outcome.provider, purpose=purpose, status=outcome.status,
            request_hash=request_hash, lines_fingerprint=fingerprint, ship_to=ship_to,
            line_breakdown=outcome.lines, jurisdiction_breakdown=outcome.jurisdictions,
            taxable_amount=_money(taxable_amount), total_tax=outcome.total_tax,
            committed=committed, committed_at=timezone.now() if committed else None,
            provider_transaction_code=transaction_code or '', error=error or '', reason=reason or '',
            exemption=outcome.exemption, is_current=not keep, created_by=user if getattr(user, 'pk', None) else None,
        )
    outcome.calculation = calc
    return calc


def _document_applies(document) -> bool:
    """Only a draft's stored amounts may change (a sent invoice changes only
    through a credit memo; a signed quote is bound to what was signed)."""
    if getattr(document, 'is_signature_locked', False):
        return False
    return getattr(document, 'status', 'draft') == 'draft'


def _apply(document, outcome: TaxOutcome, apply: bool):
    if apply and outcome.status in APPLIED_STATUSES and _document_applies(document):
        document.recompute_totals()


def calculate_tax(document, lines=None, ship_to=None, customer=None, commit=False, user=None,
                  purpose='preview', apply=True) -> TaxOutcome:
    """Determine the tax for `document` (a psa Quote or Invoice).

    lines     the document's line items (default: all of them)
    ship_to   address dict (default: the customer's billing address)
    customer  core.Organization (default: document.client_org)
    commit    invoices only: record the transaction with the provider so it
              is reported (Avalara SalesInvoice commit=true, TaxJar order)
    apply     write the result to a draft document's tax_amount / total

    Returns a TaxOutcome; outcome.blocked means finalization must not go ahead.
    """
    customer = customer or document.client_org
    ship_to = ship_to or ship_to_for(document, customer)
    lines = list(document.line_items.all()) if lines is None else list(lines)
    org_id = document.organization_id
    cats = categories_for(org_id)
    tax_settings = settings_for(org_id)
    mode = tax_settings.mode if tax_settings is not None else TaxSettings.MODE_FLAT
    on_date = document_date(document)
    fingerprint = lines_fingerprint(document, lines, ship_to, cats)
    rows = _line_rows(document, lines, cats)
    commit = bool(commit and document_type(document) == 'invoice')
    exemption = active_exemption(customer, on_date, ship_to)
    rec = dict(purpose=purpose, user=user, ship_to=ship_to, fingerprint=fingerprint)

    if mode == TaxSettings.MODE_NONE:
        out = TaxOutcome(NOT_CONFIGURED, Decimal('0.00'), 'none',
                         'Tax not configured: sales tax is turned off in Tax settings, so no tax is charged.',
                         lines=[{'number': str(r['line'].pk), 'tax': '0.00', 'taxable_amount': '0.00',
                                 'reason': 'tax not configured'} for r in rows])
        _record(document, out, reason='mode none', **rec)
        _apply(document, out, apply)
        return out

    if exemption is not None and mode in (TaxSettings.MODE_FLAT, TaxSettings.MODE_MANUAL):
        reason = (f'Customer exempt: {exemption.get_reason_display()}, certificate '
                  f'{exemption.certificate_number}')
        out = TaxOutcome(EXEMPT, Decimal('0.00'), mode, reason, exemption=exemption,
                         lines=[{'number': str(r['line'].pk), 'tax': '0.00', 'taxable_amount': '0.00',
                                 'reason': 'exempt'} for r in rows])
        _record(document, out, reason=reason, **rec)
        _apply(document, out, apply)
        return out

    if mode == TaxSettings.MODE_FLAT:
        try:
            rate = Decimal(str(document.tax_rate or '0'))
        except (InvalidOperation, ValueError, TypeError):
            rate = Decimal('0')
        out_lines, taxable_sum = [], Decimal('0')
        for r in rows:
            taxable = bool(getattr(r['line'], 'is_taxable', True))
            if taxable:
                taxable_sum += r['amount']
            out_lines.append({'number': str(r['line'].pk), 'taxable_amount': str(r['amount'] if taxable else '0.00'),
                              'rate': str(rate), 'tax': None})
        total = _money(taxable_sum * rate)
        if rate == 0:
            out = TaxOutcome(NOT_CONFIGURED, Decimal('0.00'), 'flat',
                             'Tax not configured: the flat tax rate on this document is 0%.', lines=out_lines)
        else:
            out = TaxOutcome(OK, total, 'flat', f'Flat rate {rate * 100:.4f}% on taxable lines.', lines=out_lines,
                             jurisdictions=[{'name': 'Flat rate', 'type': 'flat', 'rate': str(rate),
                                             'tax': str(total)}])
        _record(document, out, taxable_amount=taxable_sum, reason='flat rate', **rec)
        return out  # flat: recompute_totals already applies rate x taxable lines

    if mode == TaxSettings.MODE_MANUAL:
        return _calculate_manual(document, rows, tax_settings, ship_to, on_date, rec, apply)

    return _calculate_provider(document, rows, tax_settings, ship_to, customer, on_date, commit,
                               exemption, rec, apply)


def _address_problem(ship_to) -> str:
    if not ship_to.get('region') and not ship_to.get('postal_code'):
        return ("The customer's billing address has no state or postal code, so its tax jurisdiction "
                'cannot be determined. Add the address on the client page.')
    return ''


def _calculate_manual(document, rows, tax_settings, ship_to, on_date, rec, apply) -> TaxOutcome:
    problem = _address_problem(ship_to)
    if problem:
        out = TaxOutcome(ERROR, None, 'manual', problem)
        _record(document, out, error=problem, **rec)
        return out
    nexus = [n.upper() for n in (tax_settings.nexus_regions or [])]
    rk = region_key(ship_to)
    if nexus and rk not in nexus:
        reason = f'No nexus in {rk}: no sales tax is collected there (Tax settings).'
        out = TaxOutcome(OK, Decimal('0.00'), 'manual', reason,
                         lines=[{'number': str(r['line'].pk), 'tax': '0.00', 'taxable_amount': '0.00',
                                 'reason': 'no nexus'} for r in rows])
        _record(document, out, reason=reason, **rec)
        _apply(document, out, apply)
        return out
    rate = match_manual_rate(document.organization_id, ship_to, on_date)
    if rate is None:
        msg = (f'No manual tax rate matches {ship_to.get("city") or ""} {rk} {ship_to.get("postal_code") or ""}'
               f' on {on_date}. Add a rate under Tax settings, or remove the region from the nexus list.')
        out = TaxOutcome(ERROR, None, 'manual', ' '.join(msg.split()))
        _record(document, out, error=out.message, **rec)
        return out
    out_lines, total, taxable_sum = [], Decimal('0'), Decimal('0')
    for r in rows:
        taxable, why = line_taxable(r['line'], r['category'], tax_settings, rate)
        tax = _money(r['amount'] * rate.rate) if taxable else Decimal('0.00')
        if taxable:
            taxable_sum += r['amount']
        total += tax
        out_lines.append({'number': str(r['line'].pk), 'category': getattr(r['category'], 'code', ''),
                          'taxable_amount': str(r['amount'] if taxable else Decimal('0.00')),
                          'rate': str(rate.rate), 'tax': str(tax), 'reason': why})
    total = _money(total)
    out = TaxOutcome(OK, total, 'manual', f'{rate.name}: {rate.rate_percent}% (manual rate).', lines=out_lines,
                     jurisdictions=[{'name': rate.name, 'type': 'manual', 'region': rk,
                                     'rate': str(rate.rate), 'tax': str(total), 'rate_id': rate.pk}])
    _record(document, out, taxable_amount=taxable_sum, reason=f'manual rate #{rate.pk}', **rec)
    _apply(document, out, apply)
    return out


def _calculate_provider(document, rows, tax_settings, ship_to, customer, on_date, commit, exemption,
                        rec, apply) -> TaxOutcome:
    from integrations.providers.tax import TaxLine, TaxRequest, get_tax_provider
    mode = tax_settings.mode
    label = dict(TaxSettings.MODES).get(mode, mode)
    conn = tax_settings.connection
    if conn is None or not conn.is_active or conn.provider_type != mode:
        msg = f'{label} is selected in Tax settings but no active {label} connection is configured.'
        out = TaxOutcome(ERROR, None, mode, msg)
        _record(document, out, error=msg, **rec)
        return out
    problem = _address_problem(ship_to)
    if problem:
        out = TaxOutcome(ERROR, None, mode, problem)
        _record(document, out, error=problem, **rec)
        return out

    # Reuse a committed calculation for exactly these lines: re-sending an
    # invoice must not report it twice.
    if commit:
        cur = current_calculation(document)
        if (cur is not None and cur.committed and cur.status in APPLIED_STATUSES
                and cur.lines_fingerprint == rec['fingerprint'] and cur.provider == mode):
            out = TaxOutcome(cur.status, cur.total_tax, mode, 'Already recorded with the provider.',
                             lines=cur.line_breakdown, jurisdictions=cur.jurisdiction_breakdown,
                             calculation=cur, exemption=cur.exemption)
            return out

    provider = get_tax_provider(conn, sandbox=tax_settings.sandbox)
    tax_lines = []
    for r in rows:
        cat = r['category']
        taxable, _why = line_taxable(r['line'], cat, tax_settings)
        code = ''
        if cat is not None:
            code = cat.avalara_tax_code if mode == 'avalara' else cat.taxjar_product_tax_code
        tax_lines.append(TaxLine(number=str(r['line'].pk), amount=r['amount'],
                                 quantity=Decimal(str(getattr(r['line'], 'quantity', 1) or 1)),
                                 description=str(getattr(r['line'], 'description', ''))[:255],
                                 tax_code=code or '', taxable=taxable))
    is_credit = bool(getattr(document, 'is_credit_memo', False))
    original = getattr(document, 'credits_invoice', None) if is_credit else None
    req = TaxRequest(
        document_type='credit_memo' if is_credit else document_type(document),
        document_code=document_number(document), document_date=on_date,
        customer_code=str(getattr(customer, 'slug', '') or customer.pk),
        ship_from=tax_settings.origin(), ship_to=ship_to, lines=tax_lines,
        currency=getattr(document, 'currency', 'USD') or 'USD', commit=commit,
        exemption_number=exemption.certificate_number if exemption else '',
        entity_use_code=CustomerTaxExemption.AVALARA_ENTITY_USE.get(exemption.reason, '') if exemption else '',
        exemption_type=CustomerTaxExemption.TAXJAR_EXEMPTION.get(exemption.reason, '') if exemption else '',
        original_document_code=document_number(original) if original is not None else '',
    )
    request_hash = hashlib.sha256(json.dumps(
        {'p': provider.build_payload(req), 'commit': commit}, sort_keys=True, default=str).encode()).hexdigest()
    try:
        result = provider.calculate(req)
    except Exception as exc:  # an adapter bug must still block, never zero
        logger.exception('tax provider %s raised', mode)
        from integrations.providers.tax import TaxResult
        result = TaxResult.failure(f'{label} adapter error: {exc.__class__.__name__}')
    conn.last_lookup_at = timezone.now()
    conn.last_error = '' if result.success else result.error[:1000]
    conn.save(update_fields=['last_lookup_at', 'last_error'])

    if not result.success or result.total_tax is None:
        out = TaxOutcome(ERROR, None, mode, f'{label} could not calculate tax: {result.error}')
        _record(document, out, request_hash=request_hash, error=result.error, **rec)
        return out

    by_number = {str(ln.get('number')): ln for ln in result.lines}
    taxable_sum = sum((r['amount'] for r, tl in zip(rows, tax_lines) if tl.taxable), Decimal('0'))
    out_lines = []
    for r, tl in zip(rows, tax_lines):
        got = by_number.get(tl.number, {})
        out_lines.append({'number': tl.number, 'category': getattr(r['category'], 'code', ''),
                          'tax_code': tl.tax_code or (provider.NON_TAXABLE_CODE if not tl.taxable else ''),
                          'taxable_amount': got.get('taxable_amount'), 'rate': got.get('rate'),
                          'tax': got.get('tax', '0.00')})
    total = _money(result.total_tax)
    status, reason = OK, ''
    if exemption is not None:
        reason = (f'Customer exempt: {exemption.get_reason_display()}, certificate '
                  f'{exemption.certificate_number} (sent to {label})')
        status = EXEMPT if total == 0 else OK
        if total != 0:
            reason += f'; {label} still charged {total}'
    out = TaxOutcome(status, total, mode,
                     reason or f'{label}: {total} tax{" (recorded)" if result.committed else " (preview)"}.',
                     lines=out_lines, jurisdictions=result.jurisdictions, exemption=exemption)
    _record(document, out, request_hash=request_hash, taxable_amount=taxable_sum,
            committed=result.committed, transaction_code=result.transaction_code, reason=reason, **rec)
    _apply(document, out, apply)
    return out


# --- hooks used by the psa models / views -------------------------------------------

def applied_tax_amount(document) -> Optional[Decimal]:
    """Called from Quote / Invoice.recompute_totals. The tax amount that
    overrides rate x taxable lines, or None to keep that calculation.

      mode none, on a draft          -> 0 (and the page says "not configured")
      a current calculation for exactly these lines (ok / exempt / override)
                                     -> its total
      otherwise                      -> None (rate-based; finalize recalculates)
    """
    if document.pk is None:
        return None
    try:
        mode = effective_mode(document.organization_id)
        if mode == TaxSettings.MODE_NONE and _document_applies(document):
            # Drafts only: a sent invoice keeps what it was sent with.
            return Decimal('0.00')
        cur = current_calculation(document)
        if cur is None or cur.status not in APPLIED_STATUSES or cur.total_tax is None:
            return None
        if mode == TaxSettings.MODE_FLAT and cur.status != EXEMPT and cur.provider != 'override':
            return None
        if cur.lines_fingerprint != lines_fingerprint(document):
            return None
        return _money(cur.total_tax)
    except Exception:  # never break saving a document over the tax lookup
        logger.exception('applied_tax_amount failed for %s', document)
        return None


def is_stale(document) -> bool:
    cur = current_calculation(document)
    return cur is not None and cur.lines_fingerprint != lines_fingerprint(document)


def finalize_document(document, user=None) -> TaxOutcome:
    """Run before a quote / invoice is sent. outcome.blocked: do not send,
    show outcome.message. Provider modes commit invoices (reported)."""
    cur = current_calculation(document)
    if (cur is not None and cur.provider == 'override' and cur.status in APPLIED_STATUSES
            and cur.lines_fingerprint == lines_fingerprint(document)):
        return TaxOutcome(cur.status, cur.total_tax, 'override',
                          f'Manual tax override by {cur.created_by or "unknown"}: {cur.reason}',
                          calculation=cur)
    outcome = calculate_tax(document, commit=True, user=user, purpose='finalize')
    if outcome.blocked:
        kind = 'invoice' if document_type(document) == 'invoice' else 'quote'
        outcome.message = (
            f'{outcome.message} The {kind} was not sent: tax could not be determined, and it is never '
            f'silently set to zero. Fix the problem and try again, or a user with the '
            f'manage_tax_settings permission can enter a manual tax override on the {kind} page.')
    return outcome


def may_manage_tax(user, organization) -> bool:
    from accounts.permission_utils import user_has_org_perm
    return bool(user is not None and user.is_authenticated
                and user_has_org_perm(user, getattr(organization, 'pk', organization), 'manage_tax_settings'))


def apply_manual_override(document, user, amount, reason, request=None) -> TaxCalculation:
    """Explicit tax amount for the document's current lines. Needs
    manage_tax_settings for the document's organization; audited."""
    if not may_manage_tax(user, document.organization_id):
        raise PermissionDenied("Manual tax overrides need the 'manage_tax_settings' permission.")
    reason = (reason or '').strip()
    if not reason:
        raise ValueError('A reason is required for a manual tax override.')
    try:
        amount = _money(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('The override amount must be a number.')
    if amount < 0 and not getattr(document, 'is_credit_memo', False):
        raise ValueError('The override amount cannot be negative.')
    if not _document_applies(document):
        raise ValueError('Only a draft can have its tax overridden.')
    previous = current_calculation(document)
    ship_to = ship_to_for(document)
    out = TaxOutcome(OK, amount, 'override', reason)
    calc = _record(document, out, purpose='override', user=user, ship_to=ship_to,
                   fingerprint=lines_fingerprint(document, ship_to=ship_to),
                   reason=reason,
                   error=(f'Replaces calculation #{previous.pk} ({previous.status}: {previous.error})'
                          if previous is not None and previous.status == ERROR else ''))
    document.recompute_totals()
    from audit.models import AuditLog
    AuditLog.log(
        user=user, action='update', organization=document.organization,
        object_type=f'psa.{document._meta.object_name}', object_id=document.pk,
        object_repr=document_number(document),
        description=(f'Manual tax override on {document_number(document)}: tax set to {amount} '
                     f'(reason: {reason[:300]}); tax calculation #{calc.pk}'),
        ip_address=(request.META.get('REMOTE_ADDR') if request is not None else None),
        path=getattr(request, 'path', '') if request is not None else '',
    )
    return calc


def void_committed_tax(invoice, user=None) -> Optional[str]:
    """Void the provider transaction of a committed invoice. Returns an
    error message, or None when there was nothing to do / it worked."""
    from integrations.providers.tax import get_tax_provider
    calcs = TaxCalculation.objects.filter(document_type='invoice', document_id=invoice.pk, committed=True,
                                          voided_at__isnull=True).exclude(provider_transaction_code='')
    error = None
    for calc in calcs:
        tax_settings = settings_for(invoice.organization_id)
        conn = tax_settings.connection if tax_settings is not None else None
        if conn is None or conn.provider_type != calc.provider:
            calc.void_error = 'No matching tax connection to void with'
            calc.save(update_fields=['void_error'])
            error = calc.void_error
            continue
        try:
            ok, msg = get_tax_provider(conn, sandbox=tax_settings.sandbox).void(calc.provider_transaction_code)
        except Exception as exc:
            ok, msg = False, exc.__class__.__name__
        if ok:
            calc.voided_at = timezone.now()
            calc.void_error = ''
            calc.save(update_fields=['voided_at', 'void_error'])
        else:
            calc.void_error = msg[:2000]
            calc.save(update_fields=['void_error'])
            error = msg
    return error
