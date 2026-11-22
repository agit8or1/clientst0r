"""Writing what providers and ingest reports tell us into the models."""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (RUN_FAILED, RUN_MISSED, RUN_RUNNING, RUN_STATUS_CHOICES, RUN_SUCCESS, RUN_WARNING,
                     BackupJob, BackupRepository, BackupRun, ProtectedSystem)

logger = logging.getLogger('backup_monitoring')

VALID_STATUSES = {c[0] for c in RUN_STATUS_CHOICES}
GOOD = (RUN_SUCCESS, RUN_WARNING)   # a completed backup (warnings still produced one)


def ensure_system(connection, external_id, name):
    external_id = (external_id or '')[:255]
    if not external_id:
        return None
    system, _ = ProtectedSystem.objects.get_or_create(
        connection=connection, external_id=external_id,
        defaults={'customer': connection.default_customer, 'name': (name or external_id)[:255]})
    return system


def ensure_job(connection, external_id, name='', system_external_id='', system_name='', schedule='',
               retention=''):
    external_id = external_id[:255]
    system = ensure_system(connection, system_external_id, system_name)
    job = BackupJob.objects.filter(connection=connection, external_id=external_id).first()
    if job is None:
        job = BackupJob.objects.create(
            connection=connection, external_id=external_id, name=(name or external_id)[:255],
            organization=system.customer if system else connection.default_customer, system=system,
            schedule=schedule[:255], retention=retention[:255])
        return job
    changed = []
    for field, value in (('name', name), ('schedule', schedule), ('retention', retention)):
        value = (value or '')[:255]
        if value and getattr(job, field) != value:
            setattr(job, field, value)
            changed.append(field)
    if system is not None and job.system_id is None:
        job.system, job.organization = system, system.customer
        changed += ['system', 'organization']
    if changed:
        job.save(update_fields=changed)
    return job


def refresh_job_summary(job):
    last = job.runs.order_by('-started_at').first()
    good = job.runs.filter(status__in=GOOD).order_by('-started_at').first()
    job.last_run_at = last.started_at if last else None
    job.last_status = last.status if last else ''
    job.last_success_at = (good.finished_at or good.started_at) if good else None
    job.save(update_fields=['last_run_at', 'last_status', 'last_success_at'])


def record_run(job, external_id, started_at, status, finished_at=None, bytes_processed=None, message=''):
    """Idempotent: a run is identified by (connection, external_id). A repeat
    of an already-final run changes nothing (this is the replay guard); a
    run first seen as `running` is updated when it finishes.
    Returns (run, outcome) with outcome in created / updated / duplicate."""
    if status not in VALID_STATUSES:
        status = RUN_FAILED
    duration = None
    if finished_at and started_at and finished_at >= started_at:
        duration = int((finished_at - started_at).total_seconds())
    external_id = external_id[:255]
    run = BackupRun.objects.filter(connection=job.connection, external_id=external_id).first()
    if run is not None:
        if run.status == RUN_RUNNING and status != RUN_RUNNING:
            run.status, run.finished_at, run.duration_seconds = status, finished_at, duration
            run.bytes_processed, run.message = bytes_processed, message[:5000]
            run.save()
            refresh_job_summary(run.job)
            return run, 'updated'
        return run, 'duplicate'
    try:
        with transaction.atomic():
            run = BackupRun.objects.create(
                job=job, connection=job.connection, external_id=external_id, started_at=started_at,
                finished_at=finished_at, status=status, bytes_processed=bytes_processed,
                duration_seconds=duration, message=message[:5000])
    except IntegrityError:
        return BackupRun.objects.get(connection=job.connection, external_id=external_id), 'duplicate'
    refresh_job_summary(job)
    return run, 'created'


def record_repository(connection, external_id, name, total_bytes=None, used_bytes=None, available=True,
                      message='', now=None):
    repo, created = BackupRepository.objects.get_or_create(
        connection=connection, external_id=external_id[:255],
        defaults={'organization': connection.default_customer, 'name': (name or external_id)[:255]})
    repo.name = (name or external_id)[:255]
    repo.total_bytes, repo.used_bytes = total_bytes, used_bytes
    repo.available, repo.message = bool(available), (message or '')[:500]
    repo.last_checked_at = now or timezone.now()
    repo.save()
    return repo


def poll_connection(connection, now=None):
    """One poll of an API provider. Always records the attempt; only a
    complete success moves `last_poll_at`, so a broken connection ages in the
    UI instead of looking current. Returns {'ok', 'message', counts...}."""
    from .providers import ProviderError, get_backup_provider
    now = now or timezone.now()
    connection.last_poll_attempt_at = now
    provider = get_backup_provider(connection)
    if provider.push:
        connection.save(update_fields=['last_poll_attempt_at'])
        return {'ok': True, 'message': 'Push provider: nothing to poll.', 'runs': 0}
    try:
        since = now - timedelta(days=30) if connection.last_poll_at is None else \
            connection.last_poll_at - timedelta(days=2)
        repos = provider.list_repositories()
        jobs = provider.list_jobs()
        runs = provider.list_runs(since)
    except ProviderError as exc:
        connection.last_poll_status, connection.last_poll_error = 'error', exc.public_message
        connection.save(update_fields=['last_poll_attempt_at', 'last_poll_status', 'last_poll_error'])
        _record_health(connection, now, error=exc, diagnostic=exc.public_message)
        return {'ok': False, 'message': exc.public_message, 'runs': 0}
    except Exception as exc:  # a provider bug must not stop the other connections
        logger.exception('backup poll failed for connection %s', connection.pk)
        # The exception text stays in the server log: it can carry URLs, hostnames
        # or library internals, and this message is shown in the UI and API.
        connection.last_poll_status, connection.last_poll_error = (
            'error', f'Unexpected error while polling ({exc.__class__.__name__}). See the server log.')
        connection.save(update_fields=['last_poll_attempt_at', 'last_poll_status', 'last_poll_error'])
        _record_health(connection, now, error=exc, diagnostic=connection.last_poll_error)
        return {'ok': False, 'message': connection.last_poll_error, 'runs': 0}

    since_window = since
    rejected = 0
    with transaction.atomic():
        for r in repos:
            record_repository(connection, r.external_id, r.name, r.total_bytes, r.used_bytes, r.available,
                              r.message, now)
        for j in jobs:
            ensure_job(connection, j.external_id, j.name, j.system_external_id, j.system_name, j.schedule,
                       j.retention)
        created = 0
        for run in runs:
            job = ensure_job(connection, run.job_external_id, run.job_name or run.job_external_id,
                             run.system_external_id, run.system_name)
            _, outcome = record_run(job, run.external_id, run.started_at, run.status, run.finished_at,
                                    run.bytes_processed, run.message)
            created += outcome == 'created'
        connection.last_poll_at = now
        connection.last_poll_status, connection.last_poll_error = 'ok', ''
        connection.save(update_fields=['last_poll_attempt_at', 'last_poll_at', 'last_poll_status',
                                       'last_poll_error'])
    _record_health(connection, now, window_start=since_window, retrieved=len(runs), committed=len(runs) - rejected,
                   rejected=rejected, times=[r.finished_at or r.started_at for r in runs])
    return {'ok': True, 'message': 'ok', 'runs': created}


def _record_health(connection, now, *, error=None, diagnostic='', window_start=None, retrieved=0, committed=0,
                   rejected=0, times=()):
    """The poll as a monitoring collection (roadmap 82.7). Listing the
    repositories and jobs in the same poll is the bounded probe that makes an
    empty run window a verified quiet one. Run times are validated, never
    taken from list order."""
    try:
        from events import source_health as sh
        from events.source_health_store import record_collection
        from .models import BackupAlert
        open_alerts = None if error else BackupAlert.objects.filter(
            connection=connection, status__in=('open', 'acknowledged')).count()
        record_collection(connection, 'backup', sh.CollectionResult(
            attempted_at=now, window_start=window_start, window_end=now, retrieved=retrieved, processed=retrieved,
            committed=committed, rejected=rejected, error=error, diagnostic=diagnostic,
            verification='' if error else sh.V_PROBE, event_times=list(times), open_alerts=open_alerts,
            duration_ms=int((timezone.now() - now).total_seconds() * 1000)))
    except Exception:
        logger.exception('could not record backup source health for %s', connection.pk)
