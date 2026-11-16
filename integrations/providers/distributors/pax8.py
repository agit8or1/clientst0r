"""
Pax8 distributor adapter — cloud-software / SaaS distributor.

Production-ready for catalog, pricing, and webhook surfaces. Order
placement is implemented and disabled-by-default per
DistributorConnection.sync_enabled.

API docs: https://docs.pax8.com (Pax8 API v1).
Auth: OAuth2 client-credentials → bearer token (cached for ~50 min).

Endpoints used:
  POST   /v1/token                       — token
  GET    /v1/products                    — product catalog
  GET    /v1/products/{id}               — product detail
  GET    /v1/orders/products             — pricing for a product (or POST /v1/orders for an order)
  POST   /v1/orders                      — order placement
  GET    /v1/subscriptions               — subscriptions (licensing app sync)
  GET    /v1/companies                   — customer companies (licensing app sync)

Webhook signature header: `X-Pax8-Signature: <hex>` over the raw body,
HMAC'd with the connection's webhook_secret.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from .base import BaseDistributorProvider
from ..base import AuthenticationError, ProviderError


logger = logging.getLogger('integrations.distributors.pax8')


DEFAULT_BASE_URL = 'https://api.pax8.com'
TOKEN_TTL_SECONDS = 50 * 60


class Pax8Provider(BaseDistributorProvider):
    provider_name = 'Pax8'
    DEFAULT_BASE_URL = DEFAULT_BASE_URL

    def __init__(self, connection):
        super().__init__(connection)
        self._token = None
        self._token_expires_at = 0

    # ---- auth --------------------------------------------------------------

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        client_id = self.credentials.get('client_id') or ''
        client_secret = self.credentials.get('client_secret') or ''
        if not client_id or not client_secret:
            raise AuthenticationError('Pax8 client_id / client_secret missing')
        try:
            resp = self.session.post(
                f'{self.base_url}/v1/token',
                json={
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'audience': 'api://pax8.com',
                    'grant_type': 'client_credentials',
                },
                timeout=15,
            )
        except requests.RequestException as e:
            raise ProviderError(f'Pax8 token endpoint unreachable: {e}')
        if resp.status_code != 200:
            raise AuthenticationError(f'Pax8 token request failed: {resp.status_code}')
        data = resp.json()
        self._token = data.get('access_token') or ''
        self._token_expires_at = time.time() + TOKEN_TTL_SECONDS
        return self._token

    def _auth_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self._get_token()}',
            'Accept': 'application/json',
        }

    # ---- public interface --------------------------------------------------

    def test_connection(self) -> bool:
        try:
            self._get_token()
            return True
        except Exception as exc:
            logger.warning('Pax8 test_connection failed: %s', exc)
            return False

    def list_products(self, *, search: Optional[str] = None,
                      page_size: int = 50, **kwargs) -> List[Dict[str, Any]]:
        params = {'size': min(page_size, 200)}
        if search:
            params['name'] = search
        try:
            r = self.session.get(
                f'{self.base_url}/v1/products',
                headers=self._auth_headers(),
                params=params, timeout=30,
            )
        except requests.RequestException as e:
            raise ProviderError(f'Pax8 catalog call failed: {e}')
        if r.status_code != 200:
            return []
        items = r.json().get('content') or []
        rows = []
        for it in items:
            rows.append({
                'sku': it.get('id') or it.get('sku') or '',
                'name': it.get('name') or '',
                'manufacturer': it.get('vendorName') or it.get('vendor') or '',
                'manufacturer_part_number': it.get('vendorSku') or '',
                'category': (it.get('categories') or [{}])[0].get('name', '') if isinstance(it.get('categories'), list) else '',
                'short_description': it.get('shortDescription') or '',
            })
        return rows

    def _get_pages(self, path: str, params: Optional[Dict[str, Any]] = None,
                   max_pages: int = 200) -> List[Dict[str, Any]]:
        """Walk a paged Pax8 list endpoint ({page: {totalPages}, content: [...]}).
        Raises ProviderError on any failure (callers record it)."""
        rows: List[Dict[str, Any]] = []
        page = 0
        while page < max_pages:
            q = dict(params or {})
            q.update({'page': page, 'size': 200})
            try:
                r = self.session.get(f'{self.base_url}{path}', headers=self._auth_headers(),
                                     params=q, timeout=30)
            except requests.RequestException as e:
                raise ProviderError(f'Pax8 {path} call failed: {e}')
            if r.status_code != 200:
                raise ProviderError(f'Pax8 {path} returned HTTP {r.status_code}')
            try:
                payload = r.json()
            except ValueError:
                raise ProviderError(f'Pax8 {path} returned unparseable JSON')
            rows.extend(payload.get('content') or [])
            total_pages = (payload.get('page') or {}).get('totalPages') or 1
            page += 1
            if page >= total_pages:
                break
        return rows

    def list_subscriptions(self) -> List[Dict[str, Any]]:
        """GET /v1/subscriptions: every subscription the partner has (raw rows:
        id, companyId, productId, quantity, status, billingTerm, price,
        partnerCost, startDate, endDate, ...)."""
        return self._get_pages('/v1/subscriptions')

    def get_product(self, product_id: str) -> Dict[str, Any]:
        """GET /v1/products/{id}: name and vendor of one product, {} when
        it cannot be read (callers fall back to a generic name)."""
        try:
            r = self.session.get(f'{self.base_url}/v1/products/{product_id}',
                                 headers=self._auth_headers(), timeout=30)
            return r.json() if r.status_code == 200 else {}
        except (requests.RequestException, ValueError):
            return {}

    def list_companies(self) -> List[Dict[str, Any]]:
        """GET /v1/companies: the partner's customer companies (id, name)."""
        return self._get_pages('/v1/companies')

    def get_pricing(self, sku: str, *, qty: int = 1,
                    customer_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            r = self.session.get(
                f'{self.base_url}/v1/products/{sku}',
                headers=self._auth_headers(), timeout=30,
            )
        except requests.RequestException as e:
            return {'error': f'Pax8 pricing call failed: {e}'}
        if r.status_code != 200:
            return {'error': f'HTTP {r.status_code}'}
        try:
            payload = r.json()
        except ValueError:
            return {'error': 'unparseable JSON'}
        # Pax8 returns price tiers under priceBands; take the first MSRP/cost.
        bands = payload.get('priceBands') or []
        first = bands[0] if bands else {}
        return {
            'sku': sku,
            'currency': first.get('currency') or 'USD',
            'unit_price': float(first.get('cost') or 0),
            'list_price': float(first.get('msrp') or 0),
            'qty': qty,
            'available_qty': 0 if not payload.get('active', True) else 999999,
            'valid_until': '',
        }

    def check_stock(self, sku: str, *,
                    location: Optional[str] = None) -> Dict[str, Any]:
        # Pax8 is SaaS — products are unlimited unless deactivated.
        out = self.get_pricing(sku, qty=1)
        if 'error' in out:
            return {'error': out['error']}
        return {'sku': sku, 'total_qty': out['available_qty']}

    def place_order(self, *, items: List[Dict[str, Any]],
                    ship_to: Dict[str, Any],
                    purchase_order: Optional[str] = None,
                    customer_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.connection.sync_enabled:
            return {'error': 'Distributor connection is disabled — enable sync_enabled first'}
        if not customer_id:
            return {'error': 'Pax8 orders require a customer_id (companyId)'}
        body = {
            'companyId': customer_id,
            'purchaseOrderNumber': purchase_order or f'CS{int(time.time())}',
            'items': [
                {
                    'productId': it.get('sku'),
                    'quantity': int(it.get('qty') or 1),
                }
                for it in items
            ],
        }
        try:
            r = self.session.post(
                f'{self.base_url}/v1/orders',
                headers={**self._auth_headers(), 'Content-Type': 'application/json'},
                data=json.dumps(body), timeout=30,
            )
        except requests.RequestException as e:
            return {'error': f'Pax8 order call failed: {e}'}
        if r.status_code not in (200, 201):
            return {'error': f'HTTP {r.status_code}: {r.text[:300]}'}
        data = r.json()
        return {
            'order_id': data.get('id') or '',
            'status': data.get('status') or '',
            'total': data.get('total') or 0,
            'items': data.get('items') or [],
        }

    # ---- webhook -----------------------------------------------------------

    def handle_webhook(self, *, headers: Dict[str, str], raw_body: bytes) -> Dict[str, Any]:
        secret = self.connection.get_webhook_secret()
        sig_header = (
            headers.get('X-Pax8-Signature')
            or headers.get('HTTP_X_PAX8_SIGNATURE')
            or ''
        )
        sig_header = sig_header.split('=', 1)[-1].strip()
        valid = False
        if secret and sig_header:
            expected = hmac.new(
                secret.encode('utf-8'), raw_body or b'', hashlib.sha256
            ).hexdigest()
            valid = hmac.compare_digest(expected, sig_header)
        try:
            parsed = json.loads(raw_body.decode('utf-8') or '{}')
        except (UnicodeDecodeError, ValueError):
            parsed = {}
        event_type = (parsed.get('eventType') or parsed.get('event') or '')[:80]
        return {'event_type': event_type, 'signature_valid': valid, 'parsed': parsed}
