"""Avalara AvaTax REST v2 adapter.

  calculate    POST /api/v2/transactions/create
               SalesOrder (a preview: never recorded by Avalara) or, when
               the request commits, SalesInvoice / ReturnInvoice with
               commit=true (recorded and reported by Avalara).
  test         GET  /api/v2/utilities/ping (authenticated must be true)
  void         POST /api/v2/companies/{companyCode}/transactions/{code}/void

Auth: HTTP basic accountId:licenseKey. Credentials (sealed on the
TaxConnection): account_id, license_key, company_code.
Sandbox: https://sandbox-rest.avatax.com, production https://rest.avatax.com.

API reference: https://developer.avalara.com/api-reference/avatax/rest/v2/
"""
from __future__ import annotations

from decimal import Decimal
from typing import Tuple
from urllib.parse import quote as urlquote

from .base import BaseTaxProvider, TaxRequest, TaxResult, money


def _address(a):
    return {
        'line1': a.get('line1', ''), 'line2': a.get('line2', ''),
        'city': a.get('city', ''), 'region': a.get('region', ''),
        'postalCode': a.get('postal_code', ''), 'country': a.get('country', '') or 'US',
    }


class AvalaraProvider(BaseTaxProvider):
    provider_type = 'avalara'
    provider_name = 'Avalara AvaTax'
    DEFAULT_BASE_URL = 'https://rest.avatax.com'
    SANDBOX_BASE_URL = 'https://sandbox-rest.avatax.com'
    NON_TAXABLE_CODE = 'NT'

    def missing_credentials(self) -> str:
        c = self.credentials
        missing = [k for k in ('account_id', 'license_key', 'company_code') if not c.get(k)]
        return f'Avalara credentials missing: {", ".join(missing)}' if missing else ''

    def _auth(self):
        c = self.credentials
        return {'auth': (str(c.get('account_id', '')), str(c.get('license_key', ''))),
                'headers': {'X-Avalara-Client': 'clientst0r; 1.0; REST; v2'}}

    def _error_text(self, status, body) -> str:
        err = (body or {}).get('error') if isinstance(body, dict) else None
        if isinstance(err, dict):
            detail = ''
            details = err.get('details') or []
            if details and isinstance(details[0], dict):
                detail = details[0].get('description') or details[0].get('message') or ''
            return f'Avalara {err.get("code") or status}: {err.get("message") or ""} {detail}'.strip()
        return f'Avalara returned HTTP {status}'

    def test_connection(self) -> Tuple[bool, str]:
        missing = self.missing_credentials()
        if missing:
            return False, missing
        status, body, error = self._call('GET', '/api/v2/utilities/ping')
        if error:
            return False, error
        if isinstance(body, dict) and body.get('authenticated'):
            return True, f'Authenticated (AvaTax {body.get("version", "")})'.strip()
        return False, 'Avalara answered but the credentials were not accepted (authenticated=false).'

    def build_payload(self, req: TaxRequest) -> dict:
        credit = req.document_type == 'credit_memo'
        if req.commit:
            doc_type = 'ReturnInvoice' if credit else 'SalesInvoice'
        else:
            doc_type = 'ReturnOrder' if credit else 'SalesOrder'
        sign = Decimal('-1') if credit else Decimal('1')
        lines = []
        for ln in req.lines:
            item = {
                'number': ln.number,
                'quantity': float(ln.quantity or 1),
                'amount': float(money(ln.amount) * sign),
                'description': (ln.description or '')[:255],
            }
            code = ln.tax_code if ln.taxable else self.NON_TAXABLE_CODE
            if code:
                item['taxCode'] = code
            lines.append(item)
        payload = {
            'type': doc_type,
            'companyCode': self.credentials.get('company_code', ''),
            'date': req.document_date.isoformat(),
            'customerCode': req.customer_code or 'unknown',
            'currencyCode': req.currency or 'USD',
            'commit': bool(req.commit),
            'addresses': {'shipFrom': _address(req.ship_from), 'shipTo': _address(req.ship_to)},
            'lines': lines,
        }
        if req.document_code and req.commit:
            payload['code'] = req.document_code
        if req.exemption_number:
            payload['exemptionNo'] = req.exemption_number
        if req.entity_use_code:
            payload['entityUseCode'] = req.entity_use_code
        if credit and req.original_document_code:
            payload['referenceCode'] = req.original_document_code
        return payload

    def calculate(self, req: TaxRequest) -> TaxResult:
        missing = self.missing_credentials()
        if missing:
            return TaxResult.failure(missing)
        status, body, error = self._call('POST', '/api/v2/transactions/create', json=self.build_payload(req))
        if error:
            return TaxResult.failure(error)
        if not isinstance(body, dict) or body.get('totalTax') is None:
            return TaxResult.failure('Avalara answered without a totalTax; nothing was applied.')
        # Avalara answers a return (credit memo) with negative amounts already.
        flip = money
        lines = [{'number': str(li.get('lineNumber', '')), 'tax': str(flip(li.get('tax'))),
                  'taxable_amount': str(flip(li.get('taxableAmount'))),
                  'rate': None}
                 for li in body.get('lines') or []]
        juris = [{'name': s.get('jurisName', ''), 'type': s.get('jurisType', ''),
                  'region': s.get('region', ''), 'rate': str(s.get('rate', '')),
                  'tax': str(flip(s.get('tax')))}
                 for s in body.get('summary') or []]
        return TaxResult(success=True, total_tax=flip(body.get('totalTax')), lines=lines,
                         jurisdictions=juris, transaction_code=str(body.get('code') or ''),
                         committed=bool(req.commit) and body.get('status') in ('Committed', None))

    def void(self, transaction_code: str) -> Tuple[bool, str]:
        missing = self.missing_credentials()
        if missing:
            return False, missing
        company = urlquote(str(self.credentials.get('company_code', '')), safe='')
        code = urlquote(str(transaction_code), safe='')
        status, body, error = self._call(
            'POST', f'/api/v2/companies/{company}/transactions/{code}/void', json={'code': 'DocVoided'})
        if error:
            return False, error
        return True, 'Voided in Avalara'
