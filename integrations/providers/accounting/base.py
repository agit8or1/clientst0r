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
