"""
BaseAccountingProvider — interface every accounting connector implements.

Methods cover the OAuth2 lifecycle (authorize URL → token exchange →
refresh) plus the customer / invoice / payment surface we actually push
to. Subclasses that integrate via a different auth flow (API-key only,
HMAC-signed, etc.) should still implement these but can no-op the
OAuth helpers.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger('integrations.accounting')


class AccountingProviderError(Exception):
    pass


class AccountingAuthError(AccountingProviderError):
    pass


class BaseAccountingProvider:
    """
    Subclasses MUST set:
      provider_type   — matches AccountingConnection.provider_type
      provider_name   — display name
      DEFAULT_BASE_URL
      AUTHORIZE_URL   — OAuth2 redirect endpoint
      TOKEN_URL       — OAuth2 token-exchange endpoint

    And MUST implement:
      build_authorize_url(state)       → str  (the URL to send the user to)
      handle_callback(query_dict)      → (sets refresh_token + access_token on connection)
      refresh_access_token()           → ensures we have a fresh access token
      push_invoice(invoice)            → posts the invoice to the provider; sets
                                          accounting_external_id on success
      record_payment(payment)          → optional; record a payment against the
                                          provider's invoice (no-op if not supported)
      test_connection()                → bool
    """

    provider_type = 'base'
    provider_name = 'Base Accounting Provider'
    DEFAULT_BASE_URL = ''
    AUTHORIZE_URL = ''
    TOKEN_URL = ''
    DEFAULT_SCOPES: list[str] = []

    def __init__(self, connection):
        self.connection = connection
        # Apply default base URL when blank
        if not connection.base_url and self.DEFAULT_BASE_URL:
            connection.base_url = self.DEFAULT_BASE_URL
        self.session = requests.Session()

    @property
    def credentials(self) -> Dict[str, Any]:
        return self.connection.get_credentials()

    @property
    def base_url(self) -> str:
        return (self.connection.base_url or self.DEFAULT_BASE_URL).rstrip('/')

    # ---- OAuth ------------------------------------------------------------

    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError

    def handle_callback(self, *, code: str, redirect_uri: str,
                        realm_id: Optional[str] = None) -> None:
        raise NotImplementedError

    def refresh_access_token(self) -> str:
        """Refresh the access token if it's expired or close to it. Returns
        a usable access token. Subclasses should call this from any HTTP
        helper that hits the provider's API."""
        raise NotImplementedError

    def _is_access_token_fresh(self) -> bool:
        creds = self.credentials
        token = creds.get('access_token') or ''
        expires_at = creds.get('expires_at') or 0
        # Consider 60 seconds before expiry as "stale"
        return bool(token) and time.time() < float(expires_at) - 60

    def _save_tokens(self, *, access_token: str, refresh_token: Optional[str],
                     expires_in: int, **extra) -> None:
        kwargs = dict(extra)
        kwargs['access_token'] = access_token
        if refresh_token:
            kwargs['refresh_token'] = refresh_token
        kwargs['expires_at'] = time.time() + max(0, int(expires_in or 0))
        self.connection.update_credentials(**kwargs)
        self.connection.save(update_fields=['encrypted_credentials', 'updated_at'])

    # ---- Retry (Phase 44.4) -----------------------------------------------

    # Transient by nature: rate limiting and the 5xx family. A 400 means the
    # request itself is wrong and retrying just repeats the mistake.
    RETRY_STATUSES = (429, 500, 502, 503, 504)
    MAX_ATTEMPTS = 4
    BACKOFF_BASE_SECONDS = 1.0

    def _request_with_retry(self, send, *, method='GET', on_auth_failure=None):
        """Call `send()`, retrying transient failures with exponential backoff.

        **What may be retried depends on the method, and this matters.** A POST
        to /invoice creates a new invoice every time; the provider offers no
        idempotency key. A 500, a 503 or a timeout does not tell us whether the
        write landed, so replaying one risks putting a second invoice in front
        of a client — the very failure the v3.17.526 push guard exists to stop.

        So for a write:
          * 429 is retried. A rate-limited request was rejected before it was
            processed, so a replay is safe.
          * 5xx and connection errors are NOT retried. Ambiguous, and the cost
            of guessing wrong is a duplicate invoice. It surfaces as an error
            and a human decides.
        For a read, everything transient is retried — replaying a GET costs
        nothing.

        A 401 is replayed once after a forced token refresh regardless of
        method: an expired access token means the request was rejected before
        it was processed, so that is unambiguous too.
        """
        import time as _time

        is_write = method.upper() not in ('GET', 'HEAD', 'OPTIONS')
        retry_statuses = (429,) if is_write else self.RETRY_STATUSES

        auth_retried = False
        last_response = None

        for attempt in range(self.MAX_ATTEMPTS):
            try:
                response = send()
            except requests.RequestException as exc:
                if is_write:
                    raise AccountingProviderError(
                        f'{self.provider_name} {method} failed and cannot be '
                        f'safely retried (it may or may not have been '
                        f'applied): {exc}')
                if attempt == self.MAX_ATTEMPTS - 1:
                    raise AccountingProviderError(
                        f'{self.provider_name} unreachable after '
                        f'{self.MAX_ATTEMPTS} attempts: {exc}')
                _time.sleep(self._backoff(attempt))
                continue

            last_response = response

            if response.status_code == 401 and not auth_retried:
                auth_retried = True
                if on_auth_failure is not None:
                    on_auth_failure()
                continue

            if response.status_code not in retry_statuses:
                return response

            if attempt == self.MAX_ATTEMPTS - 1:
                return response

            delay = self._backoff(attempt)
            if response.status_code == 429:
                header = (response.headers or {}).get('Retry-After')
                try:
                    delay = max(delay, float(header))
                except (TypeError, ValueError):
                    pass
            logger.warning('%s HTTP %s — retrying in %.1fs (attempt %s/%s)',
                           self.provider_name, response.status_code, delay,
                           attempt + 1, self.MAX_ATTEMPTS)
            _time.sleep(delay)

        return last_response

    def _backoff(self, attempt: int) -> float:
        """Exponential, with jitter so concurrent workers don't sync up."""
        import random
        return self.BACKOFF_BASE_SECONDS * (2 ** attempt) * (1 + random.random() * 0.1)

    # ---- API surface ------------------------------------------------------

    def test_connection(self) -> bool:
        try:
            self.refresh_access_token()
            return True
        except Exception as exc:
            logger.warning('%s test_connection failed: %s', self.provider_name, exc)
            return False

    def push_invoice(self, invoice) -> Dict[str, Any]:
        """Push an `Invoice` row to the provider. On success, sets
        invoice.accounting_external_id and pushed_to_accounting_at and
        clears last_push_error. On failure, sets last_push_error."""
        raise NotImplementedError

    def record_payment(self, payment) -> Dict[str, Any]:
        """Optional. Record a Payment row against the provider's invoice
        (when accounting_external_id is set)."""
        return {'skipped': True, 'reason': 'record_payment not supported'}

    # ---- Customers (Phase 44.1) -------------------------------------------

    def _link_for(self, client_org):
        from integrations.models import AccountingCustomerLink
        return AccountingCustomerLink.objects.filter(
            connection=self.connection, client_org=client_org).first()

    def _save_link(self, client_org, customer_id, *, source, display_name=''):
        """Record the mapping, tolerating a customer already claimed elsewhere.

        The unique constraint on (connection, provider_customer_id) is what
        stops two clients silently sharing one QBO customer. Hitting it is a
        real conflict an operator has to resolve, so it is surfaced rather than
        swallowed.
        """
        from django.db import IntegrityError
        from django.utils import timezone
        from integrations.models import AccountingCustomerLink

        try:
            link, _created = AccountingCustomerLink.objects.update_or_create(
                connection=self.connection, client_org=client_org,
                defaults={
                    'organization': self.connection.organization,
                    'provider_customer_id': str(customer_id),
                    'display_name': (display_name or client_org.name)[:255],
                    'source': source,
                    'last_pushed_at': timezone.now() if source != 'pull' else None,
                    'last_pulled_at': timezone.now() if source == 'pull' else None,
                    'last_error': '',
                },
            )
            return link
        except IntegrityError as exc:
            raise AccountingProviderError(
                f'QBO customer {customer_id} is already linked to a different '
                f'client on this connection; unlink it first ({exc})')


    def customer_payload(self, client_org) -> Dict[str, Any]:
        """Provider-shaped customer body. Subclasses override.

        Before 44.1 only the display name was ever sent, so a customer created
        by a push arrived in the accounting system with no address, email or
        phone and somebody had to retype it.
        """
        raise NotImplementedError

    def push_customer(self, client_org) -> Dict[str, Any]:
        """Create or update the provider customer for `client_org`."""
        raise NotImplementedError

    def pull_customers(self, limit: int = 500) -> Dict[str, Any]:
        """Import provider customers, linking to organizations by name."""
        raise NotImplementedError

    def fetch_payments(self, since=None, limit: int = 500) -> Dict[str, Any]:
        """Read provider payment records (not inferred from an invoice balance).

        Returns {'success': bool, 'payments': [...], 'error': str|None}, each
        payment a dict with at least: external_id, amount, txn_date, and
        `invoice_external_ids` naming the invoices it settles.
        """
        raise NotImplementedError

    def fetch_invoice(self, external_id: str) -> Dict[str, Any]:
        """Full provider invoice, not just its balance."""
        raise NotImplementedError

    def poll_invoice_balance(self, invoice) -> Dict[str, Any]:
        """Phase 27 v8 (v3.17.280): query the provider for the current
        balance on a previously-pushed invoice. Used by the
        `accounting_sync_payments` command to detect "paid in QBO but our
        copy still says unpaid" cases. That command is run by hand — nothing
        schedules it (see its module docstring).

        Returns a dict:
          {success: bool, balance: Decimal | None, status: str | None,
           error: str | None}

        Subclasses must implement; default raises NotImplementedError so
        a misconfigured provider doesn't silently no-op the sync.
        """
        raise NotImplementedError(
            f'{self.provider_name} does not implement poll_invoice_balance')


def log_accounting_call(*, connection, action, resource_type='', resource_id='',
                         external_id='', success=False, http_status=None,
                         error_message='', request_summary='',
                         response_summary=''):
    """Phase 27 v2 helper — one-line write into AccountingAuditLog.

    Best-effort: a logging failure must never break a push. All callers wrap
    their try/except around their existing API call; this just records what
    happened.
    """
    try:
        from integrations.models import AccountingAuditLog
        AccountingAuditLog.objects.create(
            organization=connection.organization,
            connection=connection,
            provider_type=connection.provider_type,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id or ''),
            external_id=str(external_id or ''),
            success=bool(success),
            http_status=http_status,
            error_message=(error_message or '')[:500],
            request_summary=(request_summary or '')[:500],
            response_summary=(response_summary or '')[:500],
        )
    except Exception:
        logger.exception('AccountingAuditLog write failed')
