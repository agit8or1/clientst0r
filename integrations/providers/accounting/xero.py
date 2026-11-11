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
            # A fresh consent may grant what the last one lacked; let the
            # payments pull try again rather than staying parked.
            payments_forbidden='',
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
            return self.session.request(method, url, headers=headers, timeout=30,
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

        v3.17.531: shares AccountingCustomerLink with QBO instead of keeping a
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

    # ---- Pull (Phase 27 gap: payments, invoice state, customers) ----------

    # Xero answers 403 when the token is valid but the consent did not cover
    # the endpoint (or the organisation disconnected the app). That will not
    # fix itself on the next run, so it is reported as something to do, not as
    # an error to repeat every hour.
    PAYMENTS_FORBIDDEN_MESSAGE = (
        'Xero refused access to Payments (HTTP 403): this connection was not '
        'granted permission to read payments. Click Connect on the connection '
        'and approve access again; if your Xero app uses granular scopes, '
        'include accounting.payments.read (or the broad '
        'accounting.transactions scope). Payment import is paused until then.')

    @staticmethod
    def _xero_date(row: Dict[str, Any], key: str = 'Date'):
        """Xero JSON dates arrive as '/Date(1518652800000+0000)/' and, on most
        documents, also as an ISO `<key>String`. Returns 'YYYY-MM-DD' or None."""
        import re
        from datetime import datetime, timezone as _tz
        iso = row.get(f'{key}String')
        if isinstance(iso, str) and len(iso) >= 10:
            return iso[:10]
        raw = row.get(key)
        if isinstance(raw, str):
            m = re.match(r'/Date\((-?\d+)([+-]\d{4})?\)/', raw)
            if m:
                return datetime.fromtimestamp(int(m.group(1)) / 1000,
                                              tz=_tz.utc).date().isoformat()
            if len(raw) >= 10 and raw[4] == '-':
                return raw[:10]
        return None

    def fetch_payments(self, since=None, limit: int = 500) -> Dict[str, Any]:
        """Read Xero Payment records against sales invoices.

        GET /Payments, paged (100 per page), with If-Modified-Since so an edit
        or a deletion made after the window opened is seen, not just new rows.
        Each Xero payment settles exactly one invoice, so a partial payment is
        simply a payment smaller than the invoice. A payment removed or
        reversed in Xero comes back with Status DELETED and is reported as
        voided. Bill payments (ACCPAY), credit-note refunds and
        prepayment/overpayment allocations are left out: they are not money
        received against an invoice this system raised.
        """
        from decimal import Decimal as _D

        if self.credentials.get('payments_forbidden'):
            return {'success': False, 'needs_attention': True,
                    'error': self.PAYMENTS_FORBIDDEN_MESSAGE, 'payments': []}

        headers = {}
        if since is not None:
            from datetime import timezone as _tz
            stamp = since.astimezone(_tz.utc) if since.tzinfo else since
            headers['If-Modified-Since'] = stamp.strftime('%Y-%m-%dT%H:%M:%S')

        payments, page_no, page_size = [], 1, 100
        while len(payments) < limit:
            resp = self._api('GET', f'/Payments?page={page_no}&pageSize={page_size}',
                             headers=headers)
            if resp.status_code == 403:
                self.connection.update_credentials(payments_forbidden='1')
                self.connection.save(update_fields=['encrypted_credentials',
                                                    'updated_at'])
                log_accounting_call(
                    connection=self.connection, action='pull_payments',
                    resource_type='payment', success=False, http_status=403,
                    error_message=self.PAYMENTS_FORBIDDEN_MESSAGE,
                    response_summary=resp.text[:500])
                return {'success': False, 'needs_attention': True,
                        'error': self.PAYMENTS_FORBIDDEN_MESSAGE,
                        'payments': payments}
            if resp.status_code != 200:
                return {'success': False,
                        'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                        'payments': payments}
            rows = (resp.json() or {}).get('Payments') or []
            if not rows:
                break

            for row in rows:
                invoice = row.get('Invoice') or {}
                if row.get('PaymentType', 'ACCRECPAYMENT') != 'ACCRECPAYMENT':
                    continue
                if invoice.get('Type', 'ACCREC') != 'ACCREC':
                    continue
                invoice_id = invoice.get('InvoiceID')
                status = str(row.get('Status') or '').upper()
                payments.append({
                    'external_id': str(row.get('PaymentID') or ''),
                    'amount': _D(str(row.get('Amount') or '0')),
                    'txn_date': self._xero_date(row),
                    'reference': (row.get('Reference') or '')[:120],
                    'invoice_external_ids': [str(invoice_id)] if invoice_id else [],
                    'voided': status in ('DELETED', 'VOIDED'),
                })

            if len(rows) < page_size:
                break
            page_no += 1

        return {'success': True, 'payments': payments[:limit], 'error': None}

    def fetch_invoice(self, external_id: str) -> Dict[str, Any]:
        """The whole Xero invoice, in the shape sync_invoice_state reads."""
        from decimal import Decimal as _D
        resp = self._api('GET', f'/Invoices/{external_id}')
        if resp.status_code != 200:
            return {'success': False,
                    'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                    'invoice': None}
        rows = (resp.json() or {}).get('Invoices') or []
        if not rows:
            return {'success': False,
                    'error': 'HTTP 404: no invoice in the Xero response',
                    'invoice': None}
        data = rows[0]
        status = str(data.get('Status') or '').upper()
        return {
            'success': True,
            'error': None,
            'invoice': {
                'external_id': str(data.get('InvoiceID') or ''),
                'balance': _D(str(data.get('AmountDue', '0'))),
                'total': _D(str(data.get('Total', '0'))),
                'txn_date': self._xero_date(data, 'Date'),
                'due_date': self._xero_date(data, 'DueDate'),
                'doc_number': data.get('InvoiceNumber') or '',
                # Xero keeps a voided or deleted invoice and says so in Status.
                'voided': status in ('VOIDED', 'DELETED'),
            },
        }

    def pull_customers(self, limit: int = 500) -> Dict[str, Any]:
        """Link Xero customer contacts to organizations by exact name.

        Same rules as the QBO pull: never creates an organization; a contact
        with no matching organization is reported as unmatched.
        """
        from urllib.parse import quote
        from core.models import Organization
        from integrations.models import AccountingCustomerLink

        linked, unmatched, already = 0, [], 0
        page_no, page_size, seen = 1, 100, 0
        where = quote('IsCustomer==true')
        while seen < limit:
            resp = self._api('GET', f'/Contacts?where={where}&page={page_no}'
                                    f'&pageSize={page_size}')
            if resp.status_code != 200:
                return {'success': False,
                        'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                        'linked': linked, 'unmatched': unmatched}
            rows = (resp.json() or {}).get('Contacts') or []
            if not rows:
                break
            for row in rows:
                seen += 1
                name = (row.get('Name') or '').strip()
                contact_id = str(row.get('ContactID') or '')
                if not name or not contact_id:
                    continue
                if str(row.get('ContactStatus') or 'ACTIVE').upper() != 'ACTIVE':
                    continue
                if AccountingCustomerLink.objects.filter(
                        connection=self.connection,
                        provider_customer_id=contact_id).exists():
                    already += 1
                    continue
                org = Organization.objects.filter(name__iexact=name).first()
                if org is None:
                    unmatched.append(name)
                    continue
                try:
                    self._save_link(org, contact_id, source='pull',
                                    display_name=name)
                    linked += 1
                except AccountingProviderError:
                    unmatched.append(name)
            if len(rows) < page_size:
                break
            page_no += 1

        log_accounting_call(
            connection=self.connection, action='pull_customers',
            resource_type='customer', success=True,
            request_summary=f'limit={limit}',
            response_summary=f'linked={linked} already={already} '
                             f'unmatched={len(unmatched)}')
        return {'success': True, 'linked': linked, 'already_linked': already,
                'unmatched': unmatched, 'error': None}

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
