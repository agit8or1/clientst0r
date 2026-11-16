"""
GoCardless adapter — REST over `requests`, no SDK.

Collect-only, like the Stripe adapter: no GoCardless subscriptions or
instalment schedules are created. Mandates are set up through a billing
request + hosted billing request flow; money is collected with one payment
per ClientSt0r invoice against the mandate.

Credentials (sealed on the PaymentConnection):
  access_token     read-write access token
  webhook_secret   the webhook endpoint secret
  environment      'live' (default) or 'sandbox'

API reference: https://developer.gocardless.com/api-reference/
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict, Optional

from .base import BasePaymentProvider, PaymentProviderError
from .stripe import from_minor, to_minor

API_VERSION = '2015-07-06'
LIVE_URL = 'https://api.gocardless.com'
SANDBOX_URL = 'https://api-sandbox.gocardless.com'


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Webhook-Signature: hex HMAC-SHA256 of the raw body with the endpoint secret."""
    if not signature or not secret or payload is None:
        return False
    if isinstance(payload, str):
        payload = payload.encode()
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


class GoCardlessError(PaymentProviderError):
    def __init__(self, message, *, status=None, code='', body=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body or {}


class GoCardlessProvider(BasePaymentProvider):
    provider_type = 'gocardless'
    provider_name = 'GoCardless'
    DEFAULT_BASE_URL = LIVE_URL
    TIMEOUT = 30

    def __init__(self, connection):
        super().__init__(connection)
        if (connection.get_credentials() or {}).get('environment') == 'sandbox' and \
                connection.base_url in ('', LIVE_URL):
            connection.base_url = SANDBOX_URL

    # --- transport -------------------------------------------------------
    def _request(self, method: str, path: str, data: Optional[dict] = None, *,
                 idempotency_key: str = '') -> Dict[str, Any]:
        import requests
        token = self.credentials.get('access_token')
        if not token:
            raise GoCardlessError('GoCardless access token is not configured.')
        headers = {'Authorization': f'Bearer {token}', 'GoCardless-Version': API_VERSION,
                   'Accept': 'application/json', 'Content-Type': 'application/json'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        url = (self.connection.base_url or self.DEFAULT_BASE_URL).rstrip('/') + path
        try:
            resp = requests.request(method, url, headers=headers, json=data, timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise GoCardlessError(f'Could not reach GoCardless: {exc}') from exc
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {}
        if resp.status_code == 409 and idempotency_key:
            # Idempotent creation conflict: the resource already exists from a
            # previous request with this key. GoCardless names it in
            # error.errors[0].links.conflicting_resource_id.
            err = body.get('error') or {}
            for e in err.get('errors') or []:
                rid = (e.get('links') or {}).get('conflicting_resource_id')
                if rid:
                    return {'_conflicting_resource_id': rid}
        if resp.status_code >= 400:
            err = body.get('error') or {}
            first = (err.get('errors') or [{}])[0]
            raise GoCardlessError(err.get('message') or f'GoCardless returned HTTP {resp.status_code}',
                                  status=resp.status_code, code=first.get('reason') or err.get('type') or '',
                                  body=body)
        return body

    def verify_credentials(self) -> bool:
        self._request('GET', '/creditors')
        return True

    def verify_webhook(self, payload: bytes, headers) -> bool:
        return verify_signature(payload, headers.get('Webhook-Signature', ''),
                                self.credentials.get('webhook_secret', ''))

    # --- mandate setup -------------------------------------------------------
    def create_mandate_flow(self, *, currency: str, metadata: dict, redirect_uri: str, exit_uri: str,
                            customer_id: str = '', idempotency_key: str = '') -> Dict[str, Any]:
        """Billing request with a mandate request, plus its hosted flow.
        Returns {billing_request_id, url}."""
        br = {'mandate_request': {'currency': currency.upper()},
              'metadata': {k: str(v)[:500] for k, v in list(metadata.items())[:3]}}
        if customer_id:
            br['links'] = {'customer': customer_id}
        body = self._request('POST', '/billing_requests', {'billing_requests': br},
                             idempotency_key=idempotency_key and f'{idempotency_key}:br')
        br_id = body.get('_conflicting_resource_id') or body['billing_requests']['id']
        flow = self._request('POST', '/billing_request_flows', {'billing_request_flows': {
            'redirect_uri': redirect_uri, 'exit_uri': exit_uri,
            'links': {'billing_request': br_id}}})
        return {'billing_request_id': br_id,
                'url': flow['billing_request_flows']['authorisation_url']}

    def retrieve_billing_request(self, br_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/billing_requests/{br_id}')['billing_requests']

    def retrieve_mandate(self, mandate_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/mandates/{mandate_id}')['mandates']

    def retrieve_bank_account(self, account_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/customer_bank_accounts/{account_id}')['customer_bank_accounts']

    def cancel_mandate(self, mandate_id: str) -> Dict[str, Any]:
        return self._request('POST', f'/mandates/{mandate_id}/actions/cancel', {'data': {}})

    def mandate_details(self, mandate_id: str) -> Dict[str, Any]:
        """Display details of a mandate's bank account (no account number)."""
        mandate = self.retrieve_mandate(mandate_id)
        out = {'method_type': 'direct_debit', 'brand': mandate.get('scheme') or '', 'last4': '',
               'exp_month': None, 'exp_year': None, 'bank_name': '',
               'mandate_status': mandate.get('status', ''),
               'customer_id': (mandate.get('links') or {}).get('customer', '')}
        acct_id = (mandate.get('links') or {}).get('customer_bank_account')
        if acct_id:
            try:
                acct = self.retrieve_bank_account(acct_id)
                out['last4'] = (acct.get('account_number_ending') or '')[-4:]
                out['bank_name'] = acct.get('bank_name') or ''
            except GoCardlessError:
                pass
        return out

    # --- payments ------------------------------------------------------------
    def create_payment(self, *, mandate_id: str, amount, currency: str, description: str, metadata: dict,
                       idempotency_key: str) -> Dict[str, Any]:
        body = self._request('POST', '/payments', {'payments': {
            'amount': to_minor(amount, currency),
            'currency': currency.upper(),
            'description': description[:100],
            'metadata': {k: str(v)[:500] for k, v in list(metadata.items())[:3]},
            'links': {'mandate': mandate_id},
        }}, idempotency_key=idempotency_key)
        if body.get('_conflicting_resource_id'):
            return self.retrieve_payment(body['_conflicting_resource_id'])
        return body['payments']

    def retrieve_payment(self, payment_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/payments/{payment_id}')['payments']

    def charge(self, payment_intent: Dict[str, Any]) -> Dict[str, Any]:
        """Back-compatible single call: payment against a mandate.
        payment_intent: {amount, currency, mandate, description, idempotency_key}."""
        if not self.credentials.get('access_token'):
            return {'success': False, 'charge_id': None, 'error': 'GoCardless OAuth not completed'}
        try:
            p = self.create_payment(mandate_id=payment_intent.get('mandate') or payment_intent.get('customer_token', ''),
                                    amount=payment_intent['amount'], currency=payment_intent.get('currency', 'GBP'),
                                    description=payment_intent.get('description', ''),
                                    metadata=payment_intent.get('metadata') or {},
                                    idempotency_key=payment_intent.get('idempotency_key', ''))
        except GoCardlessError as exc:
            return {'success': False, 'charge_id': None, 'error': str(exc)}
        return {'success': True, 'charge_id': p.get('id'), 'status': p.get('status'), 'error': None}

    # --- refunds -------------------------------------------------------------
    def create_refund(self, *, payment_object_id: str, amount, currency: str, metadata: dict,
                      idempotency_key: str, total_refunded_after=None) -> Dict[str, Any]:
        """Refunds must be enabled on the GoCardless account.
        `total_amount_confirmation` is the total refunded on the payment
        after this refund, as GoCardless requires."""
        total = total_refunded_after if total_refunded_after is not None else amount
        body = self._request('POST', '/refunds', {'refunds': {
            'amount': to_minor(amount, currency),
            'total_amount_confirmation': to_minor(total, currency),
            'metadata': {k: str(v)[:500] for k, v in list(metadata.items())[:3]},
            'links': {'payment': payment_object_id},
        }}, idempotency_key=idempotency_key)
        rid = body.get('_conflicting_resource_id') or body['refunds']['id']
        return {'id': rid, 'status': 'pending'}

    def retrieve_refund(self, refund_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/refunds/{refund_id}')['refunds']

    @staticmethod
    def amount_from_minor(value, currency):
        return from_minor(value, currency)
