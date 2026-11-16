"""restic, BorgBackup and Kopia have no server API to poll: the backup host
POSTs a signed JSON report after each run (backup_monitoring.ingest)."""
from .base import PushProvider


class ResticProvider(PushProvider):
    kind = 'restic'
    label = 'restic (push reports)'


class BorgProvider(PushProvider):
    kind = 'borg'
    label = 'BorgBackup (push reports)'


class KopiaProvider(PushProvider):
    kind = 'kopia'
    label = 'Kopia (push reports)'
