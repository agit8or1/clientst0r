"""Sales-tax provider adapters (Avalara AvaTax, TaxJar).

Callers go through tax.services.calculate_tax(), which builds the request
from a quote / invoice and records a TaxCalculation; see docs/TAX.md.
"""
from .base import BaseTaxProvider, TaxLine, TaxProviderError, TaxRequest, TaxResult
from .avalara import AvalaraProvider
from .taxjar import TaxJarProvider


PROVIDER_REGISTRY = {
    'avalara': AvalaraProvider,
    'taxjar': TaxJarProvider,
}


def get_tax_provider(connection, sandbox=False):
    cls = PROVIDER_REGISTRY.get(connection.provider_type)
    if cls is None:
        return None
    return cls(connection, sandbox=sandbox)
