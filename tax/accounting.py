"""What the accounting push should send for tax.

The QuickBooks Online / Xero push code (integrations/providers/accounting)
does not call this yet; it is the single function it should call when it
starts sending tax data:

    from tax.accounting import tax_mapping_for_push
    mapping = tax_mapping_for_push(invoice, 'quickbooks_online')   # or 'xero'

Returns:
    {
      'mode': 'manual' | 'avalara' | 'taxjar' | 'flat' | 'none',
      'authoritative': 'clientst0r' | 'provider' | 'accounting',
      'send_tax': bool,          # False: let the accounting system tax it
      'total_tax': Decimal|None, # the amount Clientst0r billed
      'calculation_id': int|None,
      'stale': bool,             # lines changed since the calculation
      'lines': {line_pk: {
          'tax_code': str,       # QBO TaxCode Id or Xero TaxType ('' = unmapped)
          'taxable': bool,
          'tax': Decimal|None,   # per-line tax from the calculation
          'category': str,       # tax category code
      }},
    }

Guidance for the push (see docs/TAX.md): when `send_tax` is True, send
`total_tax` as the document's tax (QBO TxnTaxDetail.TotalTax with the line
TaxCodeRef; Xero LineAmountTypes=Exclusive with each line's TaxType and
TaxAmount) so the accounting system records the amount the customer was
billed rather than recalculating it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from .models import TaxSettings
from .services import (
    categories_for, current_calculation, effective_mode, lines_fingerprint, line_taxable,
    resolve_line_category, settings_for,
)


def map_line_tax_code(category, accounting_provider: str, taxable: bool) -> str:
    """Accounting tax code for a line in a category. Non-taxable lines map
    to the provider's non-taxable code when the category has none set."""
    if accounting_provider in ('quickbooks_online', 'qbo'):
        code = getattr(category, 'qbo_tax_code_id', '') if category is not None else ''
        return code or ('TAX' if taxable else 'NON')
    if accounting_provider == 'xero':
        code = getattr(category, 'xero_tax_type', '') if category is not None else ''
        return code or ('OUTPUT' if taxable else 'NONE')
    return ''


def tax_mapping_for_push(invoice, accounting_provider: str) -> Dict[str, Any]:
    org_id = invoice.organization_id
    tax_settings = settings_for(org_id)
    mode = effective_mode(org_id)
    authority = tax_settings.authoritative_system if tax_settings is not None else 'clientst0r'
    cats = categories_for(org_id)
    calc = current_calculation(invoice)
    by_line = {str(ln.get('number')): ln for ln in (calc.line_breakdown if calc else [])}
    lines = {}
    for li in invoice.line_items.all():
        cat = resolve_line_category(li, invoice, cats)
        taxable, _ = line_taxable(li, cat, tax_settings)
        got = by_line.get(str(li.pk), {})
        tax = got.get('tax')
        lines[li.pk] = {
            'tax_code': map_line_tax_code(cat, accounting_provider, taxable),
            'taxable': taxable,
            'tax': Decimal(str(tax)) if tax not in (None, '') else None,
            'category': getattr(cat, 'code', ''),
        }
    return {
        'mode': mode,
        'authoritative': authority,
        'send_tax': authority != 'accounting' and mode != TaxSettings.MODE_NONE,
        'total_tax': invoice.tax_amount,
        'calculation_id': calc.pk if calc else None,
        'stale': bool(calc and calc.lines_fingerprint != lines_fingerprint(invoice)),
        'lines': lines,
    }
