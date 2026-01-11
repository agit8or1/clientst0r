"""
RMM Provider Registry
Maps RMM provider types to their implementation classes.
"""
import logging

logger = logging.getLogger('integrations')


# Provider registry will be populated as providers are implemented
RMM_PROVIDER_REGISTRY = {
    # Providers will be added in subsequent phases:
    # 'ninjaone': NinjaOneProvider,
    # 'datto_rmm': DattoRMMProvider,
    # 'connectwise_automate': ConnectWiseAutomateProvider,
    # 'atera': AteraProvider,
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

__all__ = ['BaseRMMProvider', 'get_rmm_provider', 'RMM_PROVIDER_REGISTRY']
