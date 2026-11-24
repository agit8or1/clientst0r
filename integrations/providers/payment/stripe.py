"""
Stripe adapter — REST over `requests`, no SDK.

Collect-only: Clientst0r owns invoices and the billing schedule. This adapter
never creates Stripe Invoices, Prices, Products or Subscriptions; it creates
Checkout Sessions (mode=payment / mode=setup) and PaymentIntents for an
amount that names a Clientst0r invoice in its metadata.

Credentials (sealed on the PaymentConnection):
  api_key          secret key (sk_live_... / sk_test_... / rk_...)
  publishable_key  pk_... (not secret; kept with the rest for one place)
  webhook_secret   whsec_... signing secret of the webhook endpoint

API reference: https://docs.stripe.com/api
"""
from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from .base import BasePaymentProvider, PaymentProviderError

ZERO_DECIMAL = {'bif', 'clp', 'djf', 'gnf', 'jpy', 'kmf', 'krw', 'mga', 'pyg', 'rwf', 'ugx',
                'vnd', 'vuv', 'xaf', 'xof', 'xpf'}
SIGNATURE_TOLERANCE = 300  # seconds


def to_minor(amount, currency: str) -> int:
    amount = Decimal(str(amount))
    if (currency or '').lower() in ZERO_DECIMAL:
        return int(amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def from_minor(value, currency: str) -> Optional[Decimal]:
    if value is None:
        return None
    if (currency or '').lower() in ZERO_DECIMAL:
        return Decimal(int(value)).quantize(Decimal('0.01'))
    return (Decimal(int(value)) / Decimal(100)).quantize(Decimal('0.01'))


def _flatten(data, prefix=''):
    """Stripe form encoding: nested dicts / lists as a[b][0][c]=v."""
    out = []
    if isinstance(data, dict):
        for k, v in data.items():
            key = f'{prefix}[{k}]' if prefix else str(k)
            out.extend(_flatten(v, key))
    elif isinstance(data, (list, tuple)):
        for i, v in enumerate(data):
            out.extend(_flatten(v, f'{prefix}[{i}]'))
    elif data is None:
        pass
    elif isinstance(data, bool):
        out.append((prefix, 'true' if data else 'false'))
    else:
        out.append((prefix, str(data)))
    return out


def verify_signature(payload: bytes, header: str, secret: str, *, tolerance: int = SIGNATURE_TOLERANCE,
                     now: Optional[float] = None) -> bool:
    """Stripe-Signature: `t=<unix>,v1=<hex hmac>[,v1=...]`. HMAC-SHA256 of
    `<t>.<raw body>` with the endpoint's signing secret; reject timestamps
    more than `tolerance` seconds away from now (replay protection)."""
    if not header or not secret or payload is None:
        return False
    ts = None
    sigs = []
    for part in header.split(','):
        k, _, v = part.strip().partition('=')
        if k == 't':
            ts = v
        elif k == 'v1':
            sigs.append(v)
    if not ts or not sigs:
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    now = time.time() if now is None else now
    if abs(now - ts_int) > tolerance:
        return False
    if isinstance(payload, str):
        payload = payload.encode()
    expected = hmac.new(secret.encode(), f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


class StripeError(PaymentProviderError):
    def __init__(self, message, *, status=None, code='', body=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body or {}


class StripeProvider(BasePaymentProvider):
    provider_type = 'stripe'
    provider_name = 'Stripe'
    DEFAULT_BASE_URL = 'https://api.stripe.com'
    TIMEOUT = 30

    # --- transport -------------------------------------------------------
    def _request(self, method: str, path: str, data: Optional[dict] = None, *,
                 idempotency_key: str = '', params=None) -> Dict[str, Any]:
        import requests
        key = self.credentials.get('api_key')
        if not key:
            raise StripeError('Stripe secret key is not configured.')
        headers = {'Authorization': f'Bearer {key}'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        url = (self.connection.base_url or self.DEFAULT_BASE_URL).rstrip('/') + path
        try:
            resp = requests.request(method, url, headers=headers, data=_flatten(data or {}) or None,
                                    params=params, timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise StripeError(f'Could not reach Stripe: {exc}') from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            err = body.get('error') or {}
            raise StripeError(err.get('message') or f'Stripe returned HTTP {resp.status_code}',
                              status=resp.status_code, code=err.get('decline_code') or err.get('code') or '',
                              body=body)
        return body

    # --- connection --------------------------------------------------------
    def verify_credentials(self) -> bool:
        self._request('GET', '/v1/balance')
        return True

    def verify_webhook(self, payload: bytes, headers) -> bool:
        return verify_signature(payload, headers.get('Stripe-Signature', ''),
                                self.credentials.get('webhook_secret', ''))

    # --- customers -----------------------------------------------------------
    def create_customer(self, *, name: str, email: str = '', reference: str = '',
                        idempotency_key: str = '') -> str:
        body = self._request('POST', '/v1/customers', {
            'name': name, 'email': email or None,
            'metadata': {'clientst0r_client': reference},
        }, idempotency_key=idempotency_key)
        return body['id']

    # --- checkout --------------------------------------------------------------
    def create_checkout_payment(self, *, customer_id: str, amount, currency: str, description: str,
                                reference: str, metadata: dict, success_url: str, cancel_url: str,
                                save_for_future: bool, idempotency_key: str) -> Dict[str, Any]:
        """Checkout Session, mode=payment, for one Clientst0r invoice balance.
        `price_data` is an inline, one-off line — no Product / Price objects
        are created and no Stripe invoice is generated."""
        pi_data = {'metadata': metadata, 'description': description}
        if save_for_future:
            pi_data['setup_future_usage'] = 'off_session'
        body = self._request('POST', '/v1/checkout/sessions', {
            'mode': 'payment',
            'customer': customer_id,
            'client_reference_id': reference,
            'success_url': success_url,
            'cancel_url': cancel_url,
            'metadata': metadata,
            'payment_intent_data': pi_data,
            'line_items': [{
                'quantity': 1,
                'price_data': {
                    'currency': currency.lower(),
                    'unit_amount': to_minor(amount, currency),
                    'product_data': {'name': description[:250]},
                },
            }],
        }, idempotency_key=idempotency_key)
        return {'session_id': body['id'], 'url': body.get('url', ''),
                'payment_intent': body.get('payment_intent') or ''}

    def create_checkout_setup(self, *, customer_id: str, currency: str, reference: str, metadata: dict,
                              success_url: str, cancel_url: str, idempotency_key: str) -> Dict[str, Any]:
        body = self._request('POST', '/v1/checkout/sessions', {
            'mode': 'setup',
            'customer': customer_id,
            'currency': currency.lower(),
            'client_reference_id': reference,
            'success_url': success_url,
            'cancel_url': cancel_url,
            'metadata': metadata,
            'setup_intent_data': {'metadata': metadata},
        }, idempotency_key=idempotency_key)
        return {'session_id': body['id'], 'url': body.get('url', '')}

    def retrieve_checkout_session(self, session_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/v1/checkout/sessions/{session_id}')

    # --- payment intents ---------------------------------------------------------
    def retrieve_payment_intent(self, pi_id: str) -> Dict[str, Any]:
        """With the latest charge and its balance transaction (for the fee)."""
        return self._request('GET', f'/v1/payment_intents/{pi_id}',
                             params=[('expand[]', 'latest_charge.balance_transaction')])

    def charge_off_session(self, *, customer_id: str, payment_method_id: str, amount, currency: str,
                           description: str, metadata: dict, idempotency_key: str) -> Dict[str, Any]:
        """Autopay: confirm a PaymentIntent off-session against a saved
        method. Returns the PaymentIntent; a card decline comes back as a
        StripeError carrying the failed PaymentIntent in `body`."""
        return self._request('POST', '/v1/payment_intents', {
            'amount': to_minor(amount, currency),
            'currency': currency.lower(),
            'customer': customer_id,
            'payment_method': payment_method_id,
            'off_session': True,
            'confirm': True,
            'description': description,
            'metadata': metadata,
        }, idempotency_key=idempotency_key)

    def charge(self, payment_intent: Dict[str, Any]) -> Dict[str, Any]:
        """Back-compatible single call: off-session charge.
        payment_intent: {amount, currency, customer_token, payment_method,
        description, idempotency_key}."""
        if not self.credentials.get('api_key'):
            return {'success': False, 'charge_id': None, 'error': 'Stripe API key not configured'}
        try:
            pi = self.charge_off_session(
                customer_id=payment_intent.get('customer_token', ''),
                payment_method_id=payment_intent.get('payment_method', ''),
                amount=payment_intent['amount'], currency=payment_intent.get('currency', 'usd'),
                description=payment_intent.get('description', ''), metadata=payment_intent.get('metadata') or {},
                idempotency_key=payment_intent.get('idempotency_key', ''))
        except StripeError as exc:
            return {'success': False, 'charge_id': None, 'error': str(exc)}
        return {'success': pi.get('status') in ('succeeded', 'processing'), 'charge_id': pi.get('id'),
                'status': pi.get('status'), 'error': None}

    # --- methods -----------------------------------------------------------------
    def retrieve_setup_intent(self, si_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/v1/setup_intents/{si_id}', params=[('expand[]', 'payment_method')])

    def retrieve_payment_method(self, pm_id: str) -> Dict[str, Any]:
        return self._request('GET', f'/v1/payment_methods/{pm_id}')

    def detach_payment_method(self, pm_id: str) -> Dict[str, Any]:
        return self._request('POST', f'/v1/payment_methods/{pm_id}/detach')

    # --- refunds -----------------------------------------------------------------
    def create_refund(self, *, payment_object_id: str, amount, currency: str, metadata: dict,
                      idempotency_key: str) -> Dict[str, Any]:
        body = self._request('POST', '/v1/refunds', {
            'payment_intent': payment_object_id,
            'amount': to_minor(amount, currency),
            'metadata': metadata,
        }, idempotency_key=idempotency_key)
        return {'id': body['id'], 'status': {'succeeded': 'succeeded', 'pending': 'pending',
                                             'requires_action': 'pending', 'failed': 'failed',
                                             'canceled': 'canceled'}.get(body.get('status'), 'pending')}

    def list_refunds(self, pi_id: str):
        return self._request('GET', '/v1/refunds', params=[('payment_intent', pi_id), ('limit', '100')]).get('data', [])

    def expire_checkout_session(self, session_id: str):
        return self._request('POST', f'/v1/checkout/sessions/{session_id}/expire')

    # --- helpers -----------------------------------------------------------------
    @staticmethod
    def fee_details(pi: Dict[str, Any]):
        """(amount_received, fee, net) as Decimals from an expanded PaymentIntent."""
        currency = pi.get('currency', 'usd')
        received = from_minor(pi.get('amount_received') or pi.get('amount'), currency)
        fee = net = None
        charge = pi.get('latest_charge')
        if isinstance(charge, dict):
            bt = charge.get('balance_transaction')
            if isinstance(bt, dict):
                bt_cur = bt.get('currency', currency)
                fee = from_minor(bt.get('fee'), bt_cur)
                net = from_minor(bt.get('net'), bt_cur)
        return received, fee, net

    @staticmethod
    def method_details(pm: Dict[str, Any]) -> Dict[str, Any]:
        """Display details only — Stripe never returns a full card number."""
        ptype = pm.get('type', 'card')
        out = {'method_type': ptype if ptype in ('card', 'us_bank_account', 'sepa_debit', 'bacs_debit') else 'other',
               'brand': '', 'last4': '', 'exp_month': None, 'exp_year': None, 'bank_name': ''}
        detail = pm.get(ptype) or {}
        out['last4'] = (detail.get('last4') or '')[-4:]
        if ptype == 'card':
            out['brand'] = detail.get('brand') or ''
            out['exp_month'] = detail.get('exp_month')
            out['exp_year'] = detail.get('exp_year')
        else:
            out['bank_name'] = detail.get('bank_name') or ''
        return out
