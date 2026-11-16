"""Backup provider registry (same shape as integrations/providers/rmm).

Only providers that really work are registered. Veeam, Acronis, Cove, Datto
and Synology are planned and deliberately have no class here.
"""
from .base import BaseBackupProvider, JobInfo, ProviderError, RepositoryInfo, RunInfo
from .pbs import ProxmoxBackupServerProvider
from .push import BorgProvider, KopiaProvider, ResticProvider

BACKUP_PROVIDER_REGISTRY = {
    'pbs': ProxmoxBackupServerProvider,
    'restic': ResticProvider,
    'borg': BorgProvider,
    'kopia': KopiaProvider,
}


def get_backup_provider(connection):
    cls = BACKUP_PROVIDER_REGISTRY.get(connection.provider)
    if cls is None:
        raise ValueError(f"Unknown backup provider: '{connection.provider}'. "
                         f"Available: {', '.join(BACKUP_PROVIDER_REGISTRY)}")
    return cls(connection)


def is_push_provider(kind) -> bool:
    cls = BACKUP_PROVIDER_REGISTRY.get(kind)
    return bool(cls and cls.push)


__all__ = ['BaseBackupProvider', 'BACKUP_PROVIDER_REGISTRY', 'get_backup_provider', 'is_push_provider',
           'JobInfo', 'RunInfo', 'RepositoryInfo', 'ProviderError']
