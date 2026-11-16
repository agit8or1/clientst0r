"""TaxJar API v2 adapter.

  calculate    POST /v2/taxes (amount_to_collect + breakdown per line)
  commit       POST /v2/transactions/orders   (invoice: reported to TaxJar)
               POST /v2/transactions/refunds  (credit memo, negative amounts,
                                               referencing the invoice)
  test         GET  /v2/nexus/regions
  void         DELETE /v2/transactions/orders/{transaction_id}

Auth: `Authorization: Bearer <api_key>`. Credentials (sealed on the
TaxConnection): api_key. Sandbox https://api.sandbox.taxjar.com,
production https://api.taxjar.com.

API reference: https://developers.taxjar.com/api/reference/
"""
from __future__ import annotations

from decimal import Decimal
from typing import Tuple
from urllib.parse import quote as urlquote

from .base import BaseTaxProvider, TaxRequest, TaxResult, money

JURISDICTION_KEYS = (
    ('state', 'state_tax_collectable', 'state_tax_rate'),
    ('county', 'county_tax_collectable', 'county_tax_rate'),
    ('city', 'city_tax_collectable', 'city_tax_rate'),
    ('special', 'special_district_tax_collectable', 'special_tax_rate'),
)


class TaxJarProvider(BaseTaxProvider):
    provider_type = 'taxjar'
    provider_name = 'TaxJar'
    DEFAULT_BASE_URL = 'https://api.taxjar.com'
    SANDBOX_BASE_URL = 'https://api.sandbox.taxjar.com'
    # TaxJar's "exempt / other exempt" product tax code.
    NON_TAXABLE_CODE = '99999'

    def missing_credentials(self) -> str:
        return '' if self.credentials.get('api_key') else 'TaxJar API key not configured'

    def _auth(self):
        return {'headers': {'Authorization': f'Bearer {self.credentials.get("api_key", "")}',
                            'Content-Type': 'application/json'}}

    def _error_text(self, status, body) -> str:
        if isinstance(body, dict) and (body.get('detail') or body.get('error')):
            return f'TaxJar {body.get("status") or status} {body.get("error") or ""}: {body.get("detail") or ""}'.strip()
        return f'TaxJar returned HTTP {status}'

    def test_connection(self) -> Tuple[bool, str]:
        missing = self.missing_credentials()
        if missing:
            return False, missing
        status, body, error = self._call('GET', '/v2/nexus/regions')
        if error:
            return False, error
        regions = (body or {}).get('regions') if isinstance(body, dict) else None
        if regions is None:
            return False, 'TaxJar answered without a regions list.'
        names = ', '.join(sorted(r.get('region_code') or r.get('region') or '' for r in regions)) or 'none'
        return True, f'Authenticated; nexus regions on file: {names}'

    @staticmethod
    def _addresses(req: TaxRequest) -> dict:
        f, t = req.ship_from, req.ship_to
        return {
            'from_country': f.get('country') or 'US', 'from_zip': f.get('postal_code', ''),
            'from_state': f.get('region', ''), 'from_city': f.get('city', ''), 'from_street': f.get('line1', ''),
            'to_country': t.get('country') or 'US', 'to_zip': t.get('postal_code', ''),
            'to_state': t.get('region', ''), 'to_city': t.get('city', ''), 'to_street': t.get('line1', ''),
        }

    def _line_items(self, req: TaxRequest, sign=Decimal('1')):
        items = []
        for ln in req.lines:
            item = {'id': ln.number, 'quantity': 1,
                    # quantity 1 at the line total: the line total is the
                    # amount ClientSt0r bills, already rounded.
                    'unit_price': float(money(ln.amount) * sign)}
            code = ln.tax_code if ln.taxable else self.NON_TAXABLE_CODE
            if code:
                item['product_tax_code'] = code
            items.append(item)
        return items

    def build_payload(self, req: TaxRequest) -> dict:
        payload = dict(self._addresses(req))
        payload['amount'] = float(sum((money(ln.amount) for ln in req.lines), Decimal('0')))
        payload['shipping'] = 0
        payload['line_items'] = self._line_items(req)
        if req.customer_code:
            payload['customer_id'] = req.customer_code
        if req.exemption_type:
            payload['exemption_type'] = req.exemption_type
        return payload

    def calculate(self, req: TaxRequest) -> TaxResult:
        missing = self.missing_credentials()
        if missing:
            return TaxResult.failure(missing)
        status, body, error = self._call('POST', '/v2/taxes', json=self.build_payload(req))
        if error:
            return TaxResult.failure(error)
        tax = (body or {}).get('tax') if isinstance(body, dict) else None
        if not isinstance(tax, dict) or tax.get('amount_to_collect') is None:
            return TaxResult.failure('TaxJar answered without amount_to_collect; nothing was applied.')
        breakdown = tax.get('breakdown') or {}
        lines = [{'number': str(li.get('id', '')), 'tax': str(money(li.get('tax_collectable'))),
                  'taxable_amount': str(money(li.get('taxable_amount'))),
                  'rate': str(li.get('combined_tax_rate', ''))}
                 for li in breakdown.get('line_items') or []]
        names = tax.get('jurisdictions') or {}
        juris = []
        for jtype, amount_key, rate_key in JURISDICTION_KEYS:
            if breakdown.get(amount_key) is None:
                continue
            juris.append({'name': names.get(jtype, '') or jtype.upper(), 'type': jtype,
                          'region': names.get('state', ''), 'rate': str(breakdown.get(rate_key, '')),
                          'tax': str(money(breakdown.get(amount_key)))})
        total = money(tax.get('amount_to_collect'))
        result = TaxResult(success=True, total_tax=total, lines=lines, jurisdictions=juris)
        if req.document_type == 'credit_memo':
            result.total_tax = -total
            for ln in result.lines:
                ln['tax'] = str(-money(ln['tax']))
        if req.commit:
            return self._report(req, result)
        return result

    def _report(self, req: TaxRequest, result: TaxResult) -> TaxResult:
        """Record the transaction with TaxJar so it is reported. A failure
        here fails the whole calculation (finalization stays blocked)."""
        credit = req.document_type == 'credit_memo'
        sign = Decimal('-1') if credit else Decimal('1')
        per_line = {ln['number']: money(ln['tax']) for ln in result.lines}
        payload = dict(self._addresses(req))
        payload.update({
            'transaction_id': req.document_code,
            'transaction_date': req.document_date.isoformat(),
            'amount': float(sum((money(ln.amount) for ln in req.lines), Decimal('0')) * sign),
            'shipping': 0,
            'sales_tax': float(result.total_tax),
            'line_items': [dict(item, sales_tax=float(per_line.get(item['id'], Decimal('0'))))
                           for item in self._line_items(req, sign)],
        })
        if req.customer_code:
            payload['customer_id'] = req.customer_code
        if req.exemption_type:
            payload['exemption_type'] = req.exemption_type
        if credit:
            payload['transaction_reference_id'] = req.original_document_code
            path = '/v2/transactions/refunds'
        else:
            path = '/v2/transactions/orders'
        status, body, error = self._call('POST', path, json=payload)
        if error:
            return TaxResult.failure(f'Tax calculated but not recorded with TaxJar: {error}')
        result.committed = True
        result.transaction_code = req.document_code
        return result

    def void(self, transaction_code: str) -> Tuple[bool, str]:
        missing = self.missing_credentials()
        if missing:
            return False, missing
        status, body, error = self._call(
            'DELETE', f'/v2/transactions/orders/{urlquote(str(transaction_code), safe="")}')
        if error:
            return False, error
        return True, 'Deleted from TaxJar reporting'
