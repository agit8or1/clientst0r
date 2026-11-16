"""
BasePaymentProvider — Phase 15 v8 (v3.17.296) interface for ACH / card
processor adapters.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional


logger = logging.getLogger('integrations.payment')


class PaymentProviderError(Exception):
    pass


class BasePaymentProvider:
    """Subclasses MUST set:
      provider_type
      provider_name
      DEFAULT_BASE_URL

    And SHOULD implement:
      test_connection() -> bool
      charge(payment_intent) -> Dict
        payment_intent: {amount: Decimal, currency: str,
                          customer_token: str, description: str}

    The live adapters (stripe.py, gocardless.py) also implement
    verify_credentials(), verify_webhook(payload, headers), customer /
    checkout / mandate helpers and create_refund(); payments.services is
    the caller.
    """
    provider_type = 'base'
    provider_name = 'Base Payment Provider'
    DEFAULT_BASE_URL = ''

    def __init__(self, connection):
        self.connection = connection
        if not connection.base_url and self.DEFAULT_BASE_URL:
            connection.base_url = self.DEFAULT_BASE_URL

    @property
    def credentials(self) -> Dict[str, Any]:
        return self.connection.get_credentials()

    def test_connection(self) -> bool:
        """Return True if credentials look usable (present). No network
        call; verify_credentials() asks the provider."""
        creds = self.credentials
        return bool(creds.get('api_key') or creds.get('access_token'))

    def charge(self, payment_intent: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a charge. Returns
        {success: bool, charge_id: str|None, error: str|None}.
        Stub raises NotImplementedError so callers don't silently
        no-op when the live integration is missing."""
        raise NotImplementedError(
            f'{self.provider_name} charge() not yet wired — '
            f'connect a real account to enable.')
