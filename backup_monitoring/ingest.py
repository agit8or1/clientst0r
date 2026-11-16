"""Signed push reports (restic / BorgBackup / Kopia).

Request:  POST /backup-monitoring/ingest/<connection ingest_id>/
Headers:  X-Backup-Timestamp: <unix seconds>
          X-Backup-Signature: sha256=<hex HMAC-SHA256(secret, f"{timestamp}.{raw body}")>
The secret is per connection and shown once when issued.
"""
import hashlib
import hmac
import time
from datetime import timedelta
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import BackupConnection
from .recording import VALID_STATUSES, ensure_job, record_repository, record_run

MAX_SKEW_SECONDS = 300
MAX_BODY_BYTES = 256 * 1024


class IngestRejected(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256)
    return 'sha256=' + mac.hexdigest()


def verify_request(connection: BackupConnection, timestamp: str, signature: str, body: bytes, now=None):
    """Raise IngestRejected unless the signature is valid and fresh."""
    secret = connection.get_ingest_secret()
    if not secret or not timestamp or not signature:
        raise IngestRejected(401, 'invalid signature')
    try:
        ts = int(timestamp)
    except ValueError:
        raise IngestRejected(401, 'invalid signature')
    if abs((now or time.time()) - ts) > MAX_SKEW_SECONDS:
        raise IngestRejected(401, 'timestamp outside the accepted window')
    if not hmac.compare_digest(sign(secret, timestamp, body), signature.strip()):
        raise IngestRejected(401, 'invalid signature')


def _dt(value, field, required=True):
    if value in (None, ''):
        if required:
            raise IngestRejected(400, f'{field} is required')
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=dt_timezone.utc)
    parsed = parse_datetime(str(value).replace('Z', '+00:00'))
    if parsed is None:
        raise IngestRejected(400, f'{field} is not an ISO 8601 timestamp')
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def _int(value, field):
    if value in (None, ''):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise IngestRejected(400, f'{field} must be an integer')
    if n < 0:
        raise IngestRejected(400, f'{field} must not be negative')
    return n


def process_report(connection: BackupConnection, payload, now=None) -> dict:
    """Apply one verified report. Idempotent per run id."""
    now = now or timezone.now()
    if not isinstance(payload, dict):
        raise IngestRejected(400, 'body must be a JSON object')
    job_in = payload.get('job') or {}
    run_in = payload.get('run')
    system_in = payload.get('system') or {}
    repo_in = payload.get('repository')
    for name, value in (('job', job_in), ('system', system_in)):
        if not isinstance(value, dict):
            raise IngestRejected(400, f'{name} must be an object')
    result = {'run': None, 'repository': None}

    job = None
    if run_in is not None or job_in:
        job_id = str(job_in.get('id') or '').strip()
        if not job_id:
            raise IngestRejected(400, 'job.id is required')
        job = ensure_job(
            connection, job_id, str(job_in.get('name') or ''), str(system_in.get('id') or ''),
            str(system_in.get('name') or ''), str(job_in.get('schedule') or ''),
            str(job_in.get('retention') or ''))
    if run_in is not None:
        if not isinstance(run_in, dict):
            raise IngestRejected(400, 'run must be an object')
        run_id = str(run_in.get('id') or '').strip()
        if not run_id:
            raise IngestRejected(400, 'run.id is required')
        status = str(run_in.get('status') or '').lower()
        if status not in VALID_STATUSES - {'missed'}:
            raise IngestRejected(400, 'run.status must be success, warning, failed or running')
        started = _dt(run_in.get('started_at'), 'run.started_at')
        finished = _dt(run_in.get('finished_at'), 'run.finished_at', required=False)
        if started > now + timedelta(minutes=10):
            raise IngestRejected(400, 'run.started_at is in the future')
        _run, outcome = record_run(job, run_id, started, status, finished,
                                   _int(run_in.get('bytes'), 'run.bytes'), str(run_in.get('message') or ''))
        result['run'] = outcome
    if repo_in is not None:
        if not isinstance(repo_in, dict) or not str(repo_in.get('id') or '').strip():
            raise IngestRejected(400, 'repository.id is required')
        record_repository(connection, str(repo_in['id']), str(repo_in.get('name') or repo_in['id']),
                          _int(repo_in.get('total_bytes'), 'repository.total_bytes'),
                          _int(repo_in.get('used_bytes'), 'repository.used_bytes'),
                          bool(repo_in.get('available', True)), str(repo_in.get('message') or ''), now)
        result['repository'] = 'recorded'
    if result['run'] is None and result['repository'] is None and job is None:
        raise IngestRejected(400, 'nothing to record: send job/run and/or repository')
    connection.last_ingest_at = now
    connection.last_poll_at = now
    connection.last_poll_attempt_at = now
    connection.last_poll_status, connection.last_poll_error = 'ok', ''
    connection.save(update_fields=['last_ingest_at', 'last_poll_at', 'last_poll_attempt_at',
                                   'last_poll_status', 'last_poll_error'])
    return result
