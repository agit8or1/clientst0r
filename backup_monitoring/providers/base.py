"""Common interface for backup providers.

A provider turns one BackupConnection into plain dataclasses; it never writes
to the database (polling.py does). Push-style providers have no server API:
their data arrives through the signed ingest endpoint, so the list_* methods
return nothing and only test_connection reports on the last accepted report.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


class ProviderError(Exception):
    """A provider call failed (network, auth, unexpected response).

    Messages are written by the providers themselves (never exception text),
    so they are safe to show; callers read ``public_message``."""

    def __init__(self, message='The backup provider call failed.', health_reason='', retry_after=None):
        super().__init__(message)
        self.public_message = str(message)[:1000]
        # Monitoring health contract reason (events.source_health.REASON_VALUES);
        # empty = classified from the message.
        self.health_reason = health_reason
        self.retry_after = retry_after


@dataclass
class JobInfo:
    external_id: str
    name: str
    system_external_id: str = ''
    system_name: str = ''
    schedule: str = ''
    retention: str = ''


@dataclass
class RunInfo:
    external_id: str
    job_external_id: str
    started_at: datetime
    status: str
    finished_at: Optional[datetime] = None
    bytes_processed: Optional[int] = None
    message: str = ''
    job_name: str = ''
    system_external_id: str = ''
    system_name: str = ''


@dataclass
class RepositoryInfo:
    external_id: str
    name: str
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    available: bool = True
    message: str = ''


class BaseBackupProvider:
    kind = ''
    label = ''
    push = False

    def __init__(self, connection):
        self.connection = connection

    def test_connection(self) -> dict:
        raise NotImplementedError

    def list_jobs(self) -> List[JobInfo]:
        raise NotImplementedError

    def list_runs(self, since: Optional[datetime] = None) -> List[RunInfo]:
        raise NotImplementedError

    def list_repositories(self) -> List[RepositoryInfo]:
        raise NotImplementedError


class PushProvider(BaseBackupProvider):
    """restic / Borg / Kopia: nothing to poll."""
    push = True

    def test_connection(self):
        c = self.connection
        if c.last_ingest_at:
            return {'ok': True, 'message': f'Last report accepted {c.last_ingest_at:%Y-%m-%d %H:%M} UTC.'}
        return {'ok': False, 'message': 'No report received yet. Send one from the backup host '
                                        '(see docs/BACKUP_MONITORING.md).'}

    def list_jobs(self):
        return []

    def list_runs(self, since=None):
        return []

    def list_repositories(self):
        return []
