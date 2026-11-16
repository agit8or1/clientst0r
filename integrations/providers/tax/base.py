"""Sales-tax provider interface.

The tax app (tax/services.py) builds a provider-neutral `TaxRequest`, a
provider turns it into one HTTP call (or two, when it must also report a
committed transaction) and answers with a `TaxResult`.

HARD RULE for every adapter: a failure is `success=False` with an error and
`total_tax=None`. An adapter never reports a zero tax amount it did not get
from the provider — the caller blocks finalization on a failure instead of
quietly billing no tax.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.safe_http import configured_service_policy, guard_session

logger = logging.getLogger('integrations.tax')

CENT = Decimal('0.01')
DEFAULT_TIMEOUT = 20  # seconds; a tax lookup blocks a person waiting on a page


def money(value) -> Decimal:
    return Decimal(str(value or '0')).quantize(CENT, rounding=ROUND_HALF_UP)


class TaxProviderError(Exception):
    pass


@dataclass
class TaxLine:
    number: str                  # stable per document ("1", "2", ...)
    amount: Decimal              # line total, before tax
    quantity: Decimal = Decimal('1')
    description: str = ''
    tax_code: str = ''           # provider-specific code ('' = provider default)
    taxable: bool = True         # False: sent with the provider's non-taxable code


@dataclass
class TaxRequest:
    document_type: str           # quote | invoice | credit_memo | preview
    document_code: str           # quote / invoice number
    document_date: Any           # datetime.date
    customer_code: str
    ship_from: Dict[str, str]
    ship_to: Dict[str, str]
    lines: List[TaxLine]
    currency: str = 'USD'
    commit: bool = False
    exemption_number: str = ''
    entity_use_code: str = ''    # Avalara entity/use code (e.g. 'E' charitable)
    exemption_type: str = ''     # TaxJar: wholesale | government | marketplace | other | non_exempt
    original_document_code: str = ''  # credit memo: the invoice it credits


@dataclass
class TaxResult:
    success: bool
    total_tax: Optional[Decimal] = None
    lines: List[Dict[str, Any]] = field(default_factory=list)          # {number, tax, taxable_amount, rate}
    jurisdictions: List[Dict[str, Any]] = field(default_factory=list)  # {name, type, rate, tax}
    transaction_code: str = ''
    committed: bool = False
    error: str = ''

    @classmethod
    def failure(cls, error: str) -> 'TaxResult':
        return cls(success=False, total_tax=None, error=(error or 'Tax provider error')[:2000])


class BaseTaxProvider:
    """Subclasses set provider_type, provider_name, DEFAULT_BASE_URL,
    SANDBOX_BASE_URL and implement test_connection / calculate / void."""
    provider_type = 'base'
    provider_name = 'Base Tax Provider'
    DEFAULT_BASE_URL = ''
    SANDBOX_BASE_URL = ''
    NON_TAXABLE_CODE = ''

    def __init__(self, connection, sandbox: bool = False, timeout: int = DEFAULT_TIMEOUT):
        self.connection = connection
        self.sandbox = bool(sandbox or self.credentials.get('sandbox'))
        if not connection.base_url and self.DEFAULT_BASE_URL:
            # Keeps the historical behaviour: an unset URL reads as production.
            connection.base_url = self.DEFAULT_BASE_URL
        self.timeout = timeout
        self.session = guard_session(requests.Session(), configured_service_policy())

    @property
    def credentials(self) -> Dict[str, Any]:
        return self.connection.get_credentials() or {}

    @property
    def base_url(self) -> str:
        if self.sandbox and self.SANDBOX_BASE_URL:
            # An explicit non-default URL wins (a proxy or a regional host).
            if self.connection.base_url and self.connection.base_url.rstrip('/') != self.DEFAULT_BASE_URL:
                return self.connection.base_url.rstrip('/')
            return self.SANDBOX_BASE_URL
        return (self.connection.base_url or self.DEFAULT_BASE_URL).rstrip('/')

    # -- HTTP -----------------------------------------------------------------------

    def _auth(self) -> Dict[str, Any]:
        return {}

    def _call(self, method: str, path: str, *, json: Any = None) -> Tuple[Optional[int], Any, str]:
        """(status, parsed body or None, error). Never raises; writes are not
        retried (a retried create could double-report a transaction)."""
        url = f'{self.base_url}{path}'
        kwargs = dict(self._auth())
        headers = kwargs.pop('headers', {})
        headers.setdefault('Accept', 'application/json')
        try:
            resp = self.session.request(method, url, json=json, headers=headers,
                                        timeout=self.timeout, **kwargs)
        except requests.Timeout:
            return None, None, f'{self.provider_name} did not answer within {self.timeout}s (timed out)'
        except requests.RequestException as exc:
            return None, None, f'{self.provider_name} could not be reached: {exc.__class__.__name__}'
        try:
            body = resp.json() if resp.content else None
        except ValueError:
            body = None
        if resp.status_code >= 400:
            return resp.status_code, body, self._error_text(resp.status_code, body)
        return resp.status_code, body, ''

    def _error_text(self, status, body) -> str:
        return f'{self.provider_name} returned HTTP {status}'

    # -- interface ----------------------------------------------------------------------

    def missing_credentials(self) -> str:
        """'' when the credentials needed are present, else what is missing."""
        return ''

    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def calculate(self, request: TaxRequest) -> TaxResult:
        raise NotImplementedError

    def void(self, transaction_code: str) -> Tuple[bool, str]:
        raise NotImplementedError

    def compute_tax(self, invoice) -> Dict[str, Any]:
        """Legacy (v3.17.297) entry point. Use tax.services.calculate_tax,
        which builds the request from a document. Kept so older callers get
        a clear failure rather than a zero."""
        return {'success': False, 'tax_amount': None, 'breakdown': [],
                'error': 'Call tax.services.calculate_tax(document, ...) instead of compute_tax().'}
