"""
Payment processor adapters (Stripe, GoCardless), REST over `requests`.

Collect-only: invoices and the billing schedule stay in ClientSt0r. The
`payments` app drives these adapters (portal checkout, autopay, webhooks,
refunds).
"""
from .base import BasePaymentProvider, PaymentProviderError
from .stripe import StripeProvider
from .gocardless import GoCardlessProvider


PROVIDER_REGISTRY = {
    'stripe': StripeProvider,
    'gocardless': GoCardlessProvider,
}


def get_payment_provider(connection):
    """Resolve a connection to its provider adapter instance."""
    cls = PROVIDER_REGISTRY.get(connection.provider_type)
    if cls is None:
        return None
    return cls(connection)
