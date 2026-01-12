"""
PSA Provider implementations
"""
from .base import BaseProvider
from .connectwise import ConnectWiseManageProvider
from .autotask import AutotaskProvider
from .halo import HaloPSAProvider
from .kaseya import KaseyaBMSProvider
from .syncro import SyncroProvider
from .freshservice import FreshserviceProvider
from .zendesk import ZendeskProvider
from .itflow import ITFlowProvider

# Registry of available providers
PROVIDER_REGISTRY = {
    'connectwise_manage': ConnectWiseManageProvider,
    'autotask': AutotaskProvider,
    'halo_psa': HaloPSAProvider,
    'kaseya_bms': KaseyaBMSProvider,
    'syncro': SyncroProvider,
    'freshservice': FreshserviceProvider,
    'zendesk': ZendeskProvider,
    'itflow': ITFlowProvider,
}

def get_provider(connection):
    """
    Get provider instance for a PSAConnection.
    """
    provider_class = PROVIDER_REGISTRY.get(connection.provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider type: {connection.provider_type}")
    return provider_class(connection)
