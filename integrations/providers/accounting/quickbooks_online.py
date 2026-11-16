"""
QuickBooks Online (Intuit) accounting adapter.

OAuth2 with refresh-token rotation. Production-ready for invoice push;
customer matching falls back to creating a new Customer if the client_org
isn't already mapped (the response Id is then stored in the AccountingConnection
credentials as a per-client lookup table).

Docs:
  https://developer.intuit.com/app/developer/qbo/docs
  Auth:    https://appcenter.intuit.com/connect/oauth2
  Token:   https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer_authorization_code
  API:     https://quickbooks.api.intuit.com/v3/company/<realm_id>/...
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

import requests

from .base import (
    AccountingAmbiguousError,
    AccountingAuthError,
    AccountingPreflightError,
    AccountingProviderError,
    BaseAccountingProvider,
    log_accounting_call,
    push_key_note,
)


logger = logging.getLogger('integrations.accounting.qbo')


class QuickBooksOnlineProvider(BaseAccountingProvider):
    provider_type = 'quickbooks_online'
    provider_name = 'QuickBooks Online'
    DEFAULT_BASE_URL = 'https://quickbooks.api.intuit.com'
    AUTHORIZE_URL = 'https://appcenter.intuit.com/connect/oauth2'
    TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer_authorization_code'
    DEFAULT_SCOPES = ['com.intuit.quickbooks.accounting']

    # ---- OAuth ------------------------------------------------------------

    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        creds = self.credentials
        client_id = creds.get('client_id') or ''
        if not client_id:
            raise AccountingAuthError('client_id not configured for this connection')
        params = {
            'client_id': client_id,
            'response_type': 'code',
            'scope': ' '.join(self.DEFAULT_SCOPES),
            'redirect_uri': redirect_uri,
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
                headers={'Accept': 'application/json'},
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri,
                },
                timeout=20,
            )
        except requests.RequestException as e:
            raise AccountingProviderError(f'QBO token exchange unreachable: {e}')
        if resp.status_code != 200:
            raise AccountingAuthError(f'QBO token exchange failed: {resp.status_code} {resp.text[:200]}')
        data = resp.json()
        self._save_tokens(
            access_token=data['access_token'],
            refresh_token=data.get('refresh_token'),
            expires_in=int(data.get('expires_in', 3600)),
            realm_id=realm_id or creds.get('realm_id') or '',
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
                headers={'Accept': 'application/json'},
                data={'grant_type': 'refresh_token', 'refresh_token': refresh_token},
                timeout=20,
            )
        except requests.RequestException as e:
            raise AccountingProviderError(f'QBO token refresh unreachable: {e}')
        if resp.status_code != 200:
            raise AccountingAuthError(f'QBO token refresh failed: {resp.status_code}')
        data = resp.json()
        self._save_tokens(
            access_token=data['access_token'],
            refresh_token=data.get('refresh_token') or refresh_token,
            expires_in=int(data.get('expires_in', 3600)),
        )
        return data['access_token']

    # ---- API surface ------------------------------------------------------

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        """One QBO API call, with retry (Phase 44.4, v3.17.531).

        Previously a single attempt: a rate-limit response or a momentary 503
        surfaced as a hard failure, and for an invoice push that meant somebody
        had to notice and click the button again.
        """
        creds = self.credentials
        realm_id = creds.get('realm_id') or ''
        if not realm_id:
            raise AccountingAuthError('realm_id missing — re-run OAuth connect')
        url = f'{self.base_url}/v3/company/{realm_id}{path}'

        def send():
            token = self.refresh_access_token()
            headers = dict(kwargs.get('headers') or {})
            headers.setdefault('Authorization', f'Bearer {token}')
            headers.setdefault('Accept', 'application/json')
            if 'json' in kwargs:
                headers.setdefault('Content-Type', 'application/json')
            call_kwargs = {k: v for k, v in kwargs.items() if k != 'headers'}
            return self.session.request(method, url, headers=headers, timeout=30,
                                        **call_kwargs)

        def force_refresh():
            # Expire the cached token so the replay fetches a new one. A 401
            # after a successful refresh means the grant itself is gone, and
            # that needs a human — the second attempt will surface it.
            self.connection.update_credentials(expires_at=0)
            self.connection.save(update_fields=['encrypted_credentials',
                                                'updated_at'])

        return self._request_with_retry(send, method=method,
                                        on_auth_failure=force_refresh)

    # ---- Customers (Phase 44.1, v3.17.531) ---------------------------------

    def customer_payload(self, client_org) -> Dict[str, Any]:
        """Everything QBO will accept, not just the name.

        Fields are omitted when blank rather than sent empty: QBO rejects some
        empty structures, and an absent key leaves any value already set on the
        provider side alone.
        """
        body: Dict[str, Any] = {'DisplayName': client_org.name[:100]}
        if client_org.legal_name:
            body['CompanyName'] = client_org.legal_name[:100]
        if client_org.email:
            body['PrimaryEmailAddr'] = {'Address': client_org.email}
        if client_org.phone:
            body['PrimaryPhone'] = {'FreeFormNumber': client_org.phone[:30]}
        if client_org.website:
            body['WebAddr'] = {'URI': client_org.website}

        addr = {
            'Line1': client_org.street_address,
            'Line2': client_org.street_address_2,
            'City': client_org.city,
            'CountrySubDivisionCode': client_org.state,
            'PostalCode': client_org.postal_code,
            'Country': client_org.country,
        }
        addr = {k: v for k, v in addr.items() if v}
        if addr:
            body['BillAddr'] = addr

        if client_org.primary_contact_name:
            parts = client_org.primary_contact_name.split(None, 1)
            body['GivenName'] = parts[0][:25]
            if len(parts) > 1:
                body['FamilyName'] = parts[1][:25]
        return body

    def _find_customer_by_name(self, name: str):
        """Return (id, display_name) for an exact DisplayName match, else None."""
        from urllib.parse import quote
        # Escape single quotes — an apostrophe in a client name would otherwise
        # break the query, and this string is interpolated into QBO's SQL-ish
        # query language.
        safe = name.replace("'", "\\'")
        q = quote(f"select * from Customer where DisplayName = '{safe}'")
        resp = self._api('GET', f'/query?query={q}')
        if resp.status_code != 200:
            return None
        results = (resp.json().get('QueryResponse') or {}).get('Customer') or []
        if not results:
            return None
        return str(results[0]['Id']), results[0].get('DisplayName', '')

    def _ensure_customer(self, client_org) -> str:
        """Find, match or create the QBO customer for `client_org`.

        v3.17.531: reads and writes AccountingCustomerLink rather than a dict
        inside the encrypted credentials blob, and sends the full customer
        payload on create instead of a bare DisplayName.
        """
        link = self._link_for(client_org)
        if link:
            return link.provider_customer_id

        found = self._find_customer_by_name(client_org.name)
        if found:
            customer_id, display_name = found
            self._save_link(client_org, customer_id, source='matched',
                            display_name=display_name)
            return customer_id

        resp = self._api('POST', '/customer', json=self.customer_payload(client_org))
        if resp.status_code not in (200, 201):
            raise AccountingProviderError(
                f'QBO create-customer failed: {resp.status_code} {resp.text[:200]}')
        data = resp.json()['Customer']
        customer_id = str(data['Id'])
        self._save_link(client_org, customer_id, source='push',
                        display_name=data.get('DisplayName', ''))
        log_accounting_call(
            connection=self.connection, action='push_customer',
            resource_type='customer', resource_id=client_org.pk,
            external_id=customer_id, success=True,
            http_status=resp.status_code,
            request_summary=f'create {client_org.name}',
            response_summary=f'qbo_customer_id={customer_id}',
        )
        return customer_id

    def push_customer(self, client_org) -> Dict[str, Any]:
        """Create the customer, or update an already-linked one.

        QBO updates are full-replace and require the current SyncToken, so an
        update reads the record first. A stale token means somebody edited the
        customer in QBO since; that surfaces as an error rather than silently
        overwriting their edit.
        """
        link = self._link_for(client_org)
        if link is None:
            try:
                customer_id = self._ensure_customer(client_org)
                return {'success': True, 'customer_id': customer_id, 'created': True}
            except Exception as exc:
                return {'success': False, 'error': str(exc)}

        read = self._api('GET', f'/customer/{link.provider_customer_id}')
        if read.status_code != 200:
            err = f'HTTP {read.status_code}: {read.text[:200]}'
            log_accounting_call(
                connection=self.connection, action='push_customer',
                resource_type='customer', resource_id=client_org.pk,
                external_id=link.provider_customer_id, success=False,
                http_status=read.status_code, error_message=err)
            return {'success': False, 'error': err}

        current = (read.json() or {}).get('Customer') or {}
        body = self.customer_payload(client_org)
        body['Id'] = link.provider_customer_id
        body['SyncToken'] = current.get('SyncToken', '0')
        body['sparse'] = True

        resp = self._api('POST', '/customer', json=body)
        if resp.status_code not in (200, 201):
            err = f'HTTP {resp.status_code}: {resp.text[:200]}'
            link.last_error = err[:500]
            link.save(update_fields=['last_error', 'updated_at'])
            log_accounting_call(
                connection=self.connection, action='push_customer',
                resource_type='customer', resource_id=client_org.pk,
                external_id=link.provider_customer_id, success=False,
                http_status=resp.status_code, error_message=err,
                response_summary=resp.text[:500])
            return {'success': False, 'error': err}

        from django.utils import timezone
        link.last_pushed_at = timezone.now()
        link.last_error = ''
        link.display_name = (resp.json().get('Customer') or {}).get(
            'DisplayName', link.display_name)[:255]
        link.save(update_fields=['last_pushed_at', 'last_error',
                                 'display_name', 'updated_at'])
        log_accounting_call(
            connection=self.connection, action='push_customer',
            resource_type='customer', resource_id=client_org.pk,
            external_id=link.provider_customer_id, success=True,
            http_status=resp.status_code,
            request_summary=f'update {client_org.name}')
        return {'success': True, 'customer_id': link.provider_customer_id,
                'created': False}

    def pull_customers(self, limit: int = 500) -> Dict[str, Any]:
        """Import QBO customers and link them to organizations by exact name.

        Deliberately does NOT create organizations. A QBO customer with no
        matching org is reported as unmatched and left alone: inventing tenants
        from an accounting system is not a decision a sync job should make on
        its own.
        """
        from urllib.parse import quote
        from core.models import Organization

        linked, unmatched, already = 0, [], 0
        start_position, page = 1, 100
        while start_position <= limit:
            q = quote(f'select * from Customer startposition {start_position} '
                      f'maxresults {page}')
            resp = self._api('GET', f'/query?query={q}')
            if resp.status_code != 200:
                return {'success': False,
                        'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                        'linked': linked, 'unmatched': unmatched}
            rows = (resp.json().get('QueryResponse') or {}).get('Customer') or []
            if not rows:
                break

            for row in rows:
                name = (row.get('DisplayName') or '').strip()
                customer_id = str(row.get('Id') or '')
                if not name or not customer_id:
                    continue
                from integrations.models import AccountingCustomerLink
                if AccountingCustomerLink.objects.filter(
                        connection=self.connection,
                        provider_customer_id=customer_id).exists():
                    already += 1
                    continue
                org = Organization.objects.filter(name__iexact=name).first()
                if org is None:
                    unmatched.append(name)
                    continue
                try:
                    self._save_link(org, customer_id, source='pull',
                                    display_name=name)
                    linked += 1
                except AccountingProviderError:
                    unmatched.append(name)

            if len(rows) < page:
                break
            start_position += page

        log_accounting_call(
            connection=self.connection, action='pull_customers',
            resource_type='customer', success=True,
            request_summary=f'limit={limit}',
            response_summary=f'linked={linked} already={already} '
                             f'unmatched={len(unmatched)}')
        return {'success': True, 'linked': linked, 'already_linked': already,
                'unmatched': unmatched, 'error': None}

    def _item_ref_resolver(self):
        """Map a line's GL code to a QBO Item id.

        QBO's SalesItemLineDetail.ItemRef is an *Item* id; the income account
        is a property of the Item, so there is no AccountRef on a sales line.
        Before this, the line's GL account code was sent as the ItemRef, which
        names an Item that does not exist (QBO rejects the invoice) or, worse,
        an unrelated Item whose id happens to equal the code.

        Resolution: AccountingItemMapping for the code, else the connection's
        default_item_id. A coded line with neither is refused — guessing where
        revenue lands is not something to do silently. An uncoded line with no
        default keeps the old behaviour (no ItemRef; QBO applies its own
        default) so invoices that pushed fine before still do.
        """
        from integrations.models import AccountingItemMapping
        mapping = dict(AccountingItemMapping.objects.filter(
            connection=self.connection).values_list(
                'gl_account_code', 'provider_item_id'))
        default = (getattr(self.connection, 'default_item_id', '') or '').strip()

        def resolve(li):
            code = (getattr(li, 'gl_account_code', '') or '').strip()
            if code:
                item_id = mapping.get(code) or default
                if not item_id:
                    raise AccountingPreflightError(
                        f'Line "{li.description[:60]}" has GL code {code}, which '
                        f'has no QuickBooks item mapping on connection '
                        f'"{self.connection.name}", and the connection has no '
                        f'default item. Map the GL code to a QuickBooks Item '
                        f'(or set a default item) on the connection, then push '
                        f'again.')
                return item_id
            return default or None
        return resolve

    def _build_invoice_body(self, invoice, customer_id, idempotency_key=None):
        resolve = self._item_ref_resolver()

        def _line(li):
            detail = {
                'Qty': float(li.quantity),
                'UnitPrice': float(li.unit_price),
            }
            item_id = resolve(li)
            if item_id:
                detail['ItemRef'] = {'value': str(item_id)}
            return {
                'DetailType': 'SalesItemLineDetail',
                'Amount': float(li.line_total),
                'Description': li.description[:1000],
                'SalesItemLineDetail': detail,
            }
        body = {
            'CustomerRef': {'value': customer_id},
            'Line': [_line(li) for li in invoice.line_items.all()],
            'TxnDate': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            'DueDate': invoice.due_date.isoformat() if invoice.due_date else None,
            'CustomerMemo': {'value': (invoice.notes or invoice.title or '')[:1000]},
        }
        if idempotency_key:
            # DocNumber (max 21) carries our invoice number; PrivateNote (not
            # shown to the customer) carries the push key reconciliation
            # searches for.
            if invoice.invoice_number:
                body['DocNumber'] = invoice.invoice_number[:21]
            body['PrivateNote'] = push_key_note(idempotency_key)[:4000]
        return {k: v for k, v in body.items() if v is not None}

    def push_invoice(self, invoice, *, idempotency_key=None, request_id=None) -> Dict[str, Any]:
        """Create the invoice in QBO.

        Returns {'success': bool, 'invoice_id', 'error', 'ambiguous': bool,
        'preflight': bool}. `ambiguous` means the invoice may exist in QBO even
        though we have no id (timeout / 5xx) — the caller must reconcile before
        any retry. Callers go through integrations.services.invoice_push, which
        supplies the keys and records the attempt.
        """
        from django.utils import timezone

        def _fail(err, *, http_status=None, ambiguous=False, preflight=False,
                  response_summary='', action='push_invoice'):
            invoice.last_push_error = str(err)[:500]
            invoice.save(update_fields=['last_push_error', 'updated_at'])
            log_accounting_call(
                connection=self.connection, action=action,
                resource_type='invoice', resource_id=invoice.pk,
                success=False, http_status=http_status, error_message=str(err),
                request_summary=f'invoice={invoice.invoice_number} key={idempotency_key or "-"}',
                response_summary=response_summary,
            )
            return {'success': False, 'error': str(err), 'ambiguous': ambiguous,
                    'preflight': preflight}

        # Item mapping first: a refusal must happen before anything (even a
        # customer) is written provider-side.
        try:
            resolve = self._item_ref_resolver()
            for li in invoice.line_items.all():
                resolve(li)
        except AccountingPreflightError as exc:
            return _fail(exc, preflight=True, action='push_refused')

        try:
            customer_id = self._ensure_customer(invoice.client_org)
        except Exception as exc:
            # No invoice has been sent yet, so this is a definite failure.
            return _fail(exc)

        try:
            body = self._build_invoice_body(invoice, customer_id, idempotency_key)
        except AccountingPreflightError as exc:
            return _fail(exc, preflight=True, action='push_refused')

        path = '/invoice'
        if request_id:
            # QBO request-id idempotency: a replay with the same requestid
            # returns the original response instead of creating again.
            path = f'/invoice?requestid={quote(str(request_id))}'
        try:
            resp = self._api('POST', path, json=body)
        except AccountingAmbiguousError as exc:
            return _fail(exc, ambiguous=True)
        if resp.status_code not in (200, 201):
            err = f'HTTP {resp.status_code}: {resp.text[:500]}'
            return _fail(err, http_status=resp.status_code,
                         ambiguous=resp.status_code >= 500,
                         response_summary=resp.text[:500])

        try:
            data = resp.json().get('Invoice') or {}
        except Exception as exc:
            return _fail(f'unreadable QBO response: {exc}',
                         http_status=resp.status_code, ambiguous=True)
        if not data.get('Id'):
            return _fail('QBO returned no invoice Id',
                         http_status=resp.status_code, ambiguous=True)
        invoice.accounting_provider = self.provider_type
        invoice.accounting_external_id = str(data.get('Id') or '')
        invoice.pushed_to_accounting_at = timezone.now()
        invoice.last_push_error = ''
        # Phase 27 v4 (v3.17.267): capture QBO-side tax for reconciliation
        try:
            from decimal import Decimal as _D
            qbo_tax = (data.get('TxnTaxDetail') or {}).get('TotalTax')
            if qbo_tax is not None:
                invoice.provider_tax_amount = _D(str(qbo_tax))
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
            request_summary=f'invoice={invoice.invoice_number} lines={len(body.get("Line", []))} key={idempotency_key or "-"}',
            response_summary=f'qbo_id={invoice.accounting_external_id}',
        )
        return {'success': True, 'invoice_id': invoice.accounting_external_id}

    def find_invoice_by_key(self, invoice, key: str) -> Dict[str, Any]:
        """Look for a live QBO invoice carrying our push key.

        PrivateNote is not queryable, so candidates are narrowed by DocNumber
        (we set it to our invoice number) and, when the customer is linked, by
        customer + transaction date (in case the company's numbering overrode
        DocNumber). A candidate matches only when its PrivateNote holds the
        key. Voided invoices are ignored. Any failed query means absence is
        unconfirmed -> 'error'.
        """
        from urllib.parse import quote as _q
        queries = []
        if invoice.invoice_number:
            doc = invoice.invoice_number[:21].replace("'", "\\'")
            queries.append(f"select * from Invoice where DocNumber = '{doc}'")
        link = self._link_for(invoice.client_org)
        if link is not None and invoice.invoice_date:
            cid = str(link.provider_customer_id).replace("'", "\\'")
            queries.append(
                f"select * from Invoice where CustomerRef = '{cid}' "
                f"and TxnDate = '{invoice.invoice_date.isoformat()}'")
        if not queries:
            return {'status': 'error', 'external_id': '', 'data': {},
                    'error': 'nothing to search QBO by'}

        found = None
        for q in queries:
            try:
                resp = self._api('GET', f'/query?query={_q(q)}')
            except AccountingProviderError as exc:
                return self._reconcile_logged(invoice, key, 'error', error=str(exc))
            if resp.status_code != 200:
                return self._reconcile_logged(
                    invoice, key, 'error', http_status=resp.status_code,
                    error=f'HTTP {resp.status_code}: {resp.text[:200]}')
            rows = (resp.json().get('QueryResponse') or {}).get('Invoice') or []
            for row in rows:
                note = str(row.get('PrivateNote') or '')
                if key not in note:
                    continue
                if note.upper().startswith('VOIDED'):
                    continue
                found = row
                break
            if found:
                break
        if found:
            return self._reconcile_logged(invoice, key, 'found',
                                          external_id=str(found.get('Id') or ''),
                                          data=found)
        return self._reconcile_logged(invoice, key, 'absent')

    def _reconcile_logged(self, invoice, key, status, *, external_id='', data=None,
                          error='', http_status=None):
        log_accounting_call(
            connection=self.connection, action='reconcile_invoice',
            resource_type='invoice', resource_id=invoice.pk,
            external_id=external_id, success=status != 'error',
            http_status=http_status, error_message=error,
            request_summary=f'invoice={invoice.invoice_number} key={key}',
            response_summary=f'status={status}',
        )
        return {'status': status, 'external_id': external_id,
                'data': data or {}, 'error': error}

    def record_payment(self, payment) -> Dict[str, Any]:
        invoice = payment.invoice
        if not invoice.accounting_external_id:
            return {'skipped': True, 'reason': 'invoice not yet pushed'}
        # v3.17.531: reads the link row, not the credentials blob.
        link = self._link_for(invoice.client_org)
        if link is None:
            return {'skipped': True, 'reason': 'customer not mapped'}
        customer_id = link.provider_customer_id
        body = {
            'CustomerRef': {'value': customer_id},
            'TotalAmt': float(payment.amount),
            'TxnDate': payment.paid_on.isoformat(),
            'Line': [{
                'Amount': float(payment.amount),
                'LinkedTxn': [{
                    'TxnId': invoice.accounting_external_id,
                    'TxnType': 'Invoice',
                }],
            }],
        }
        try:
            resp = self._api('POST', '/payment', json=body)
        except AccountingProviderError as exc:
            log_accounting_call(
                connection=self.connection, action='record_payment',
                resource_type='payment', resource_id=payment.pk,
                success=False, error_message=str(exc),
                request_summary=f'payment={payment.pk} amount={payment.amount} invoice={invoice.invoice_number}',
            )
            return {'success': False, 'error': str(exc),
                    'ambiguous': isinstance(exc, AccountingAmbiguousError)}
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
        ext_id = resp.json().get('Payment', {}).get('Id') or ''
        log_accounting_call(
            connection=self.connection, action='record_payment',
            resource_type='payment', resource_id=payment.pk,
            external_id=str(ext_id),
            success=True, http_status=resp.status_code,
            request_summary=f'payment={payment.pk} amount={payment.amount} invoice={invoice.invoice_number}',
            response_summary=f'qbo_payment_id={ext_id}',
        )
        return {'success': True, 'payment_id': ext_id}

    # ---- Real pull (Phase 44.2, v3.17.531) ---------------------------------

    def fetch_payments(self, since=None, limit: int = 500) -> Dict[str, Any]:
        """Read QBO Payment records, with the invoices each one settles.

        This is what "bidirectional payment sync" was supposed to mean. The
        v3.17.280 implementation never looked at a Payment at all — it polled an
        invoice's Balance and, when that hit zero, wrote a local payment for the
        whole outstanding amount dated today with method 'other'. That could not
        see a partial payment (a non-zero balance was skipped entirely), could
        not report the real payment date, method or reference, and had no id to
        make a re-run idempotent.

        Each returned payment carries `invoice_external_ids`, taken from
        LinkedTxn, so a payment spanning several invoices is allocated rather
        than dropped.
        """
        from decimal import Decimal as _D
        from urllib.parse import quote

        clauses = []
        if since is not None:
            # QBO wants an ISO timestamp; MetaData.LastUpdatedTime is the field
            # that moves when a payment is edited or voided, not just created.
            clauses.append(f"MetaData.LastUpdatedTime > '{since.isoformat()}'")
        where = (' where ' + ' and '.join(clauses)) if clauses else ''

        payments, start_position, page = [], 1, 100
        while len(payments) < limit:
            q = quote(f'select * from Payment{where} '
                      f'startposition {start_position} maxresults {page}')
            resp = self._api('GET', f'/query?query={q}')
            if resp.status_code != 200:
                return {'success': False,
                        'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                        'payments': payments}
            rows = (resp.json().get('QueryResponse') or {}).get('Payment') or []
            if not rows:
                break

            for row in rows:
                linked = []
                for line in row.get('Line') or []:
                    for txn in line.get('LinkedTxn') or []:
                        if txn.get('TxnType') == 'Invoice' and txn.get('TxnId'):
                            linked.append(str(txn['TxnId']))
                payments.append({
                    'external_id': str(row.get('Id') or ''),
                    'amount': _D(str(row.get('TotalAmt') or '0')),
                    'txn_date': row.get('TxnDate'),
                    'reference': (row.get('PaymentRefNum') or '')[:120],
                    'invoice_external_ids': linked,
                    # QBO marks a voided payment by zeroing it and stamping the
                    # memo; there is no dedicated status field to read.
                    'voided': str(row.get('PrivateNote') or '').upper().startswith('VOIDED'),
                })

            if len(rows) < page:
                break
            start_position += page

        return {'success': True, 'payments': payments[:limit], 'error': None}

    def fetch_invoice(self, external_id: str) -> Dict[str, Any]:
        """The whole invoice, not just its balance."""
        from decimal import Decimal as _D
        resp = self._api('GET', f'/invoice/{external_id}')
        if resp.status_code != 200:
            return {'success': False,
                    'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                    'invoice': None}
        data = (resp.json() or {}).get('Invoice') or {}
        return {
            'success': True,
            'error': None,
            'invoice': {
                'external_id': str(data.get('Id') or ''),
                'balance': _D(str(data.get('Balance', '0'))),
                'total': _D(str(data.get('TotalAmt', '0'))),
                'txn_date': data.get('TxnDate'),
                'due_date': data.get('DueDate'),
                'doc_number': data.get('DocNumber') or '',
                # A deleted QBO invoice 404s; a voided one survives with zero
                # total and a VOIDED memo.
                'voided': str(data.get('PrivateNote') or '').upper().startswith('VOIDED'),
            },
        }

    def poll_invoice_balance(self, invoice):
        """Phase 27 v8 (v3.17.280): GET /invoice/<id> and pull `Balance`."""
        from decimal import Decimal as _D
        if not invoice.accounting_external_id:
            return {'success': False, 'error': 'invoice not pushed yet',
                    'balance': None, 'status': None}
        resp = self._api('GET', f'/invoice/{invoice.accounting_external_id}')
        if resp.status_code != 200:
            return {'success': False,
                    'error': f'HTTP {resp.status_code}: {resp.text[:200]}',
                    'balance': None, 'status': None}
        data = (resp.json() or {}).get('Invoice') or {}
        balance = data.get('Balance')
        if balance is None:
            return {'success': False, 'error': 'no Balance in QBO response',
                    'balance': None, 'status': None}
        return {
            'success': True,
            'balance': _D(str(balance)),
            'status': 'paid' if _D(str(balance)) == 0 else 'open',
            'error': None,
        }
