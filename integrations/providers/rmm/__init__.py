"""
RMM Provider Registry
Maps RMM provider types to their implementation classes.
"""
import logging
from .ninjaone import NinjaOneProvider
from .datto import DattoRMMProvider
from .atera import AteraProvider
from .connectwise_automate import ConnectWiseAutomateProvider
from .tactical_rmm import TacticalRMMProvider
from .rem0te import Rem0teProvider

logger = logging.getLogger('integrations')


# Provider registry - maps provider_type to implementation class
RMM_PROVIDER_REGISTRY = {
    'ninjaone': NinjaOneProvider,
    'datto_rmm': DattoRMMProvider,
    'atera': AteraProvider,
    'connectwise_automate': ConnectWiseAutomateProvider,
    'tactical_rmm': TacticalRMMProvider,
    'rem0te': Rem0teProvider,
}


def get_rmm_provider(connection):
    """
    Get RMM provider instance for an RMMConnection.

    Args:
        connection: RMMConnection instance

    Returns:
        Provider instance (subclass of BaseRMMProvider)

    Raises:
        ValueError: If provider type is unknown
    """
    provider_type = connection.provider_type
    ProviderClass = RMM_PROVIDER_REGISTRY.get(provider_type)

    if not ProviderClass:
        available = ', '.join(RMM_PROVIDER_REGISTRY.keys()) if RMM_PROVIDER_REGISTRY else 'none'
        raise ValueError(
            f"Unknown RMM provider: '{provider_type}'. "
            f"Available providers: {available}"
        )

    logger.debug(f"Creating {ProviderClass.__name__} for connection {connection.id}")
    return ProviderClass(connection)


# Export base provider for subclassing
from ..rmm_base import BaseRMMProvider

__all__ = [
    'BaseRMMProvider',
    'get_rmm_provider',
    'RMM_PROVIDER_REGISTRY',
    'NinjaOneProvider',
    'DattoRMMProvider',
    'AteraProvider',
    'ConnectWiseAutomateProvider',
    'TacticalRMMProvider',
    'Rem0teProvider',
]
