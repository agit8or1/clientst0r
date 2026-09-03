"""
Xero accounting adapter.

OAuth2 with refresh-token rotation. Production-ready for invoice push.
Customer matching falls back to creating a new Contact when the
client_org isn't already mapped (the response ContactID is then stored
in the AccountingConnection credentials as a per-client lookup table).

Docs:
  https://developer.xero.com/documentation/guides/oauth2/auth-flow/
  Auth:    https://login.xero.com/identity/connect/authorize
  Token:   https://identity.xero.com/connect/token
  API:     https://api.xero.com/api.xro/2.0/...   (header `xero-tenant-id`)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from .base import (
    AccountingAuthError,
    AccountingProviderError,
    BaseAccountingProvider,
    log_accounting_call,
)


logger = logging.getLogger('integrations.accounting.xero')


class XeroProvider(BaseAccountingProvider):
    provider_type = 'xero'
    provider_name = 'Xero'
    DEFAULT_BASE_URL = 'https://api.xero.com'
    AUTHORIZE_URL = 'https://login.xero.com/identity/connect/authorize'
    TOKEN_URL = 'https://identity.xero.com/connect/token'
    DEFAULT_SCOPES = [
        'offline_access',
        'accounting.transactions',
        'accounting.contacts',
    ]

    # ---- OAuth ------------------------------------------------------------

    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        creds = self.credentials
        client_id = creds.get('client_id') or ''
        if not client_id:
            raise AccountingAuthError('client_id not configured for this connection')
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(self.DEFAULT_SCOPES),
            'state': state,
        }
        return f'{self.AUTHORIZE_URL}?{urlencode(params)}'

    def handle_callback(self, *, code: str, redirect_uri: str,
                        realm_id: Optional[str] = None) -> None:
        creds = self.credentials
        client_id = creds.get('client_id') or ''
        client_secret = creds.get('client_secret') or ''
        if not client_id or not client_secret:
            raise AccountingAuthError('client_id / client_secret missing')
        try:
            resp = requests.post(
                self.TOKEN_URL,
                auth=(client_id, client_secret),
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri,
                },
                timeout=20,
            )
        except requests.RequestException as e:
            raise AccountingProviderError(f'Xero token exchange unreachable: {e}')
        if resp.status_code != 200:
            raise AccountingAuthError(f'Xero token exchange failed: {resp.status_code} {resp.text[:200]}')
        data = resp.json()

        # Discover tenant_id (required for every API call)
        try:
            tenant_resp = requests.get(
                'https://api.xero.com/connections',
                headers={'Authorization': f'Bearer {data["access_token"]}',
                         'Accept': 'application/json'},
                timeout=15,
            )
            tenants = tenant_resp.json() if tenant_resp.status_code == 200 else []
            tenant_id = tenants[0]['tenantId'] if tenants else ''
        except Exception:
            tenant_id = ''

        self._save_tokens(
            access_token=data['access_token'],
            refresh_token=data.get('refresh_token'),
            expires_in=int(data.get('expires_in', 1800)),
            tenant_id=tenant_id,
        )

    def refresh_access_token(self) -> str:
        if self._is_access_token_fresh():
            return self.credentials.get('access_token', '')
        creds = self.credentials
        client_id = creds.get('client_id') or ''
        client_secret = creds.get('client_secret') or ''
        refresh_token = creds.get('refresh_token') or ''
        if not (client_id and client_secret and refresh_token):
            raise AccountingAuthError('OAuth not yet completed — connect via /integrations/accounting/<id>/connect/')
        try:
            resp = requests.post(
                self.TOKEN_URL,
                auth=(client_id, client_secret),
                data={'grant_type': 'refresh_token', 'refresh_token': refresh_token},
                timeout=20,
            )
        except requests.RequestException as e:
            raise AccountingProviderError(f'Xero token refresh unreachable: {e}')
        if resp.status_code != 200:
            raise AccountingAuthError(f'Xero token refresh failed: {resp.status_code}')
        data = resp.json()
        self._save_tokens(
            access_token=data['access_token'],
            refresh_token=data.get('refresh_token') or refresh_token,
            expires_in=int(data.get('expires_in', 1800)),
        )
        return data['access_token']

    # ---- API surface ------------------------------------------------------

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        """One Xero API call, with the same retry treatment as QBO
        (Phase 44.4, v3.17.531)."""
        creds = self.credentials
        tenant_id = creds.get('tenant_id') or ''
        if not tenant_id:
            raise AccountingAuthError('tenant_id missing — re-run OAuth connect')
        url = f'{self.base_url}/api.xro/2.0{path}'

        def send():
            token = self.refresh_access_token()
            headers = dict(kwargs.get('headers') or {})
            headers.setdefault('Authorization', f'Bearer {token}')
            headers.setdefault('Accept', 'application/json')
            headers['Xero-tenant-id'] = tenant_id
            if 'json' in kwargs:
                headers.setdefault('Content-Type', 'application/json')
            call_kwargs = {k: v for k, v in kwargs.items() if k != 'headers'}
            return requests.request(method, url, headers=headers, timeout=30,
                                    **call_kwargs)

        def force_refresh():
            self.connection.update_credentials(expires_at=0)
            self.connection.save(update_fields=['encrypted_credentials',
                                                'updated_at'])

        return self._request_with_retry(send, method=method,
                                        on_auth_failure=force_refresh)

    def customer_payload(self, client_org) -> Dict[str, Any]:
        """Xero Contact body. Same intent as the QBO one: send what we know."""
        body: Dict[str, Any] = {'Name': client_org.name[:255]}
        if client_org.email:
            body['EmailAddress'] = client_org.email
        if client_org.primary_contact_name:
            parts = client_org.primary_contact_name.split(None, 1)
            body['FirstName'] = parts[0][:50]
            if len(parts) > 1:
                body['LastName'] = parts[1][:50]
        if client_org.phone:
            body['Phones'] = [{'PhoneType': 'DEFAULT',
                               'PhoneNumber': client_org.phone[:50]}]
        addr = {
            'AddressType': 'STREET',
            'AddressLine1': client_org.street_address,
            'AddressLine2': client_org.street_address_2,
            'City': client_org.city,
            'Region': client_org.state,
            'PostalCode': client_org.postal_code,
            'Country': client_org.country,
        }
        if any(v for k, v in addr.items() if k != 'AddressType'):
            body['Addresses'] = [{k: v for k, v in addr.items() if v}]
        return body

    def _ensure_contact(self, client_org) -> str:
        """Find, match or create the Xero contact for `client_org`.

        v3.17.528: shares AccountingCustomerLink with QBO instead of keeping a
        `contact_map` dict inside the encrypted credentials blob.
        """
        link = self._link_for(client_org)
        if link:
            return link.provider_customer_id

        from urllib.parse import quote
        # Escape embedded quotes; the name goes into Xero's where-clause.
        safe = client_org.name.replace('"', '\\"')
        where = quote(f'Name=="{safe}"')
        resp = self._api('GET', f'/Contacts?where={where}')
        if resp.status_code == 200:
            results = (resp.json() or {}).get('Contacts') or []
            if results:
                contact_id = results[0]['ContactID']
                self._save_link(client_org, contact_id, source='matched',
                                display_name=results[0].get('Name', ''))
                return contact_id

        resp = self._api('POST', '/Contacts',
                         json={'Contacts': [self.customer_payload(client_org)]})
        if resp.status_code not in (200, 201):
            raise AccountingProviderError(
                f'Xero create-contact failed: {resp.status_code} {resp.text[:200]}')
        contacts = (resp.json() or {}).get('Contacts') or []
        if not contacts:
            raise AccountingProviderError('Xero create-contact returned no rows')
        contact_id = contacts[0]['ContactID']
        self._save_link(client_org, contact_id, source='push',
                        display_name=contacts[0].get('Name', ''))
        return contact_id

    def push_invoice(self, invoice) -> Dict[str, Any]:
        from django.utils import timezone
        try:
            contact_id = self._ensure_contact(invoice.client_org)
        except Exception as exc:
            invoice.last_push_error = str(exc)[:500]
            invoice.save(update_fields=['last_push_error', 'updated_at'])
            log_accounting_call(
                connection=self.connection, action='push_invoice',
                resource_type='invoice', resource_id=invoice.pk,
                success=False, error_message=str(exc),
                request_summary=f'invoice={invoice.invoice_number}',
            )
            return {'success': False, 'error': str(exc)}

        # Phase 27 v6 (v3.17.278): include AccountCode when the line has
        # gl_account_code set, so revenue lands in the right Xero account.
        def _line(li):
            row = {
                'Description': li.description[:4000],
                'Quantity': float(li.quantity),
                'UnitAmount': float(li.unit_price),
            }
            if getattr(li, 'gl_account_code', '') and li.gl_account_code:
                row['AccountCode'] = li.gl_account_code
            return row
        body = {
            'Invoices': [{
                'Type': 'ACCREC',
                'Contact': {'ContactID': contact_id},
                'Date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                'DueDate': invoice.due_date.isoformat() if invoice.due_date else None,
                'LineItems': [_line(li) for li in invoice.line_items.all()],
                'Status': 'AUTHORISED',
            }],
        }
        # Strip None
        body['Invoices'][0] = {k: v for k, v in body['Invoices'][0].items() if v is not None}

        resp = self._api('POST', '/Invoices', json=body)
        if resp.status_code not in (200, 201):
            err = f'HTTP {resp.status_code}: {resp.text[:500]}'
            invoice.last_push_error = err
            invoice.save(update_fields=['last_push_error', 'updated_at'])
            log_accounting_call(
                connection=self.connection, action='push_invoice',
                resource_type='invoice', resource_id=invoice.pk,
                success=False, http_status=resp.status_code,
                error_message=err,
                request_summary=f'invoice={invoice.invoice_number} lines={len(body["Invoices"][0].get("LineItems", []))}',
                response_summary=resp.text[:500],
            )
            return {'success': False, 'error': err}

        data = resp.json() or {}
        invoices = data.get('Invoices') or []
        ext_id = (invoices[0].get('InvoiceID') if invoices else '') or ''
        invoice.accounting_provider = self.provider_type
        invoice.accounting_external_id = str(ext_id)
        invoice.pushed_to_accounting_at = timezone.now()
        invoice.last_push_error = ''
        # Phase 27 v4 (v3.17.267): capture Xero-side tax for reconciliation
        try:
            from decimal import Decimal as _D
            xero_tax = invoices[0].get('TotalTax') if invoices else None
            if xero_tax is not None:
                invoice.provider_tax_amount = _D(str(xero_tax))
        except Exception:
            pass
        invoice.save(update_fields=[
            'accounting_provider', 'accounting_external_id',
            'pushed_to_accounting_at', 'last_push_error',
            'provider_tax_amount', 'updated_at',
        ])
        log_accounting_call(
            connection=self.connection, action='push_invoice',
            resource_type='invoice', resource_id=invoice.pk,
            external_id=invoice.accounting_external_id,
            success=True, http_status=resp.status_code,
            request_summary=f'invoice={invoice.invoice_number} lines={len(body["Invoices"][0].get("LineItems", []))}',
            response_summary=f'xero_id={invoice.accounting_external_id}',
        )
        return {'success': True, 'invoice_id': invoice.accounting_external_id}

    def record_payment(self, payment) -> Dict[str, Any]:
        invoice = payment.invoice
        if not invoice.accounting_external_id:
            return {'skipped': True, 'reason': 'invoice not yet pushed'}
        body = {
            'Payments': [{
                'Invoice': {'InvoiceID': invoice.accounting_external_id},
                'Amount': float(payment.amount),
                'Date': payment.paid_on.isoformat(),
                'Account': {'Code': payment.reference[:10] or '090'},  # let admin override
            }],
        }
        resp = self._api('POST', '/Payments', json=body)
        if resp.status_code not in (200, 201):
            err = f'HTTP {resp.status_code}: {resp.text[:200]}'
            log_accounting_call(
                connection=self.connection, action='record_payment',
                resource_type='payment', resource_id=payment.pk,
                success=False, http_status=resp.status_code,
                error_message=err,
                request_summary=f'payment={payment.pk} amount={payment.amount} invoice={invoice.invoice_number}',
                response_summary=resp.text[:500],
            )
            return {'success': False, 'error': err}
        log_accounting_call(
            connection=self.connection, action='record_payment',
            resource_type='payment', resource_id=payment.pk,
            success=True, http_status=resp.status_code,
            request_summary=f'payment={payment.pk} amount={payment.amount} invoice={invoice.invoice_number}',
            response_summary='ok',
        )
        return {'success': True}

    def poll_invoice_balance(self, invoice):
        """Phase 27 v8 (v3.17.280): GET /Invoices/<id> and pull AmountDue."""
        from decimal import Decimal as _D
        if not invoice.accounting_external_id:
            return {'success': False, 'error': 'invoice not pushed yet',
                    'balance': None, 'status': None}
        resp = self._api('GET', f'/Invoices/{invoice.accounting_external_id}')
        if resp.status_code != 200:
            return {'success': False,
                    'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                    'balance': None, 'status': None}
        data = resp.json() or {}
        invoices = data.get('Invoices') or []
        if not invoices:
            return {'success': False, 'error': 'no invoice in Xero response',
                    'balance': None, 'status': None}
        amount_due = invoices[0].get('AmountDue')
        if amount_due is None:
            return {'success': False, 'error': 'no AmountDue in Xero response',
                    'balance': None, 'status': None}
        return {
            'success': True,
            'balance': _D(str(amount_due)),
            'status': 'paid' if _D(str(amount_due)) == 0 else 'open',
            'error': None,
        }
