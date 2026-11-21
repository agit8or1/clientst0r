"""Run, verify, prune and report off-host backups (Phase 94.3, SR-17).

Called by the scheduler task ``offhost_backup`` (every 15 minutes; it decides
what is due from OffhostBackupConfig) and by ``manage.py offhost_backup``.
Nothing runs until an administrator has configured a destination, generated
and acknowledged the backup key, and switched backups on.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import archive as arc
from . import crypto
from .destinations import DestinationError, NAME_PREFIX, NAME_RE, NAME_SUFFIX, open_destination

logger = logging.getLogger('core')

FAILED_RETRY = timedelta(hours=1)


class NotReady(Exception):
    """Off-host backup is switched on but cannot run (no destination / key)."""


def staging_root() -> Path:
    return Path(getattr(settings, 'OFFHOST_BACKUP_STAGING_DIR', '') or
                Path(settings.BASE_DIR) / 'backups' / 'offhost-staging')


def archive_name(now=None):
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    return f'{NAME_PREFIX}{now:%Y%m%dT%H%M%S}Z{NAME_SUFFIX}'


def _name_time(name):
    m = NAME_RE.match(name)
    return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S').replace(tzinfo=dt_timezone.utc)


def _audit(user, action, description, extra=None, success=True):
    from audit.models import AuditLog
    AuditLog.log(user=user, action=action, object_type='offhost_backup', object_id=1,
                 object_repr='Off-host backup', description=description[:2000],
                 extra_data=extra or {}, success=success)


def readiness_problems(cfg):
    problems = []
    if not cfg.destination_configured():
        problems.append('no destination is configured')
    if cfg.destination_type == cfg.DEST_SFTP and cfg.sftp_host and not cfg.host_key:
        problems.append("the backup server's SSH host key is not approved")
    if not cfg.backup_key:
        problems.append('no backup encryption key has been generated')
    elif not cfg.backup_key_acknowledged_at:
        problems.append('the backup key has not been confirmed as escrowed')
    return problems


# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------

def plan_retention(names, keep_daily, keep_weekly, protect=()):
    """Names to delete. Keeps the newest archive of each of the last
    ``keep_daily`` days and of each of the last ``keep_weekly`` ISO weeks,
    always the newest archive, and every name in ``protect`` (the newest
    verified archive). Unrecognised names are never touched."""
    archives = sorted((n for n in names if NAME_RE.match(n)), reverse=True)
    if not archives:
        return []
    keep = {archives[0]} | {p for p in protect if p}
    days, weeks = [], []
    for n in archives:
        t = _name_time(n)
        d, w = t.date(), t.isocalendar()[:2]
        if d not in days:
            days.append(d)
            if len(days) <= max(0, keep_daily):
                keep.add(n)
        if w not in weeks:
            weeks.append(w)
            if len(weeks) <= max(0, keep_weekly):
                keep.add(n)
    return [n for n in archives if n not in keep]


def prune(dest, cfg):
    names = [r['name'] for r in dest.list()]
    doomed = plan_retention(names, cfg.keep_daily, cfg.keep_weekly, protect=[cfg.last_verified_name])
    removed, errors = [], []
    for n in doomed:
        try:
            dest.delete(n)
            removed.append(n)
        except Exception as e:  # noqa: BLE001
            errors.append(f'{n}: {e.__class__.__name__}')
    return removed, errors


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------

def run_backup(*, trigger='scheduler', user=None, sqlite_source=None, media_root=None, out=None):
    from core.models import OffhostBackupConfig, OffhostBackupRun
    cfg = OffhostBackupConfig.get()
    problems = readiness_problems(cfg)
    if problems:
        raise NotReady('Off-host backup cannot run: ' + '; '.join(problems) + '.')
    key = cfg.backup_key
    fp = crypto.key_fingerprint(key)
    name = archive_name()
    run = OffhostBackupRun.objects.create(kind='backup', trigger=trigger, remote_name=name, key_fingerprint=fp,
                                          destination=cfg.destination_label()[:600], requested_by=user)
    OffhostBackupConfig.objects.filter(pk=1).update(backup_requested_at=None)
    staging = arc.private_dir(staging_root()) / f'run-{run.pk}'
    old_umask = os.umask(0o077)
    try:
        staging.mkdir(mode=0o700)
        enc_path = staging / name
        if out:
            out('Writing the encrypted archive...')
        with open(enc_path, 'wb') as f:
            w = crypto.EncryptingWriter(f, key)
            manifest = arc.write_archive(w, staging, media_root=media_root, sqlite_source=sqlite_source,
                                         backup_key_fingerprint=fp)
            w.close()
        size = enc_path.stat().st_size
        if out:
            out(f'Uploading {size} bytes to {cfg.destination_label()}...')
        with open_destination(cfg) as dest:
            dest.put(enc_path, name)
            listed = {r['name']: r['size'] for r in dest.list()}
            if listed.get(name) != size:
                raise DestinationError(f'Upload check failed: the destination reports '
                                       f'{listed.get(name)} bytes for {name}, expected {size}.')
            removed, prune_errors = prune(dest, cfg)
        detail = (f'{name}: {size} bytes, {manifest["media"]["files"]} uploaded files, '
                  f'database {manifest["db"]["engine"]}.')
        if removed:
            detail += f' Retention removed {len(removed)} older archive(s).'
        if prune_errors:
            detail += ' Could not remove: ' + ', '.join(prune_errors[:5]) + '.'
        now = timezone.now()
        run.status, run.finished_at, run.size_bytes, run.sha256, run.detail = 'success', now, size, w.sha256, detail
        run.save()
        OffhostBackupConfig.objects.filter(pk=1).update(
            last_backup_at=now, last_backup_status='success', last_backup_detail=detail,
            last_success_at=now, last_success_name=name)
        _audit(user, 'export', f'Off-host backup uploaded ({trigger}): {detail}',
               {'event': 'offhost_backup', 'trigger': trigger, 'archive': name, 'size': size, 'sha256': w.sha256,
                'key_fingerprint': fp, 'destination': cfg.destination_label(), 'pruned': removed})
        logger.info('offhost backup ok: %s (%s bytes) -> %s', name, size, cfg.destination_label())
        return run
    except Exception as e:
        msg = _safe_message(e)
        now = timezone.now()
        run.status, run.finished_at, run.detail = 'failed', now, msg
        run.save()
        OffhostBackupConfig.objects.filter(pk=1).update(
            last_backup_at=now, last_backup_status='failed', last_backup_detail=msg)
        _audit(user, 'export', f'Off-host backup FAILED ({trigger}): {msg}',
               {'event': 'offhost_backup', 'trigger': trigger, 'archive': name}, success=False)
        logger.error('offhost backup failed: %s', msg)
        raise
    finally:
        os.umask(old_umask)
        arc.rmtree(staging)


def _safe_message(e):
    """Error text for the page and log. Our own exceptions are written to be
    safe; anything else is reduced to its class and first line, and any stored
    secret that somehow appears in it is masked."""
    from core.models import OffhostBackupConfig
    known = (NotReady, DestinationError, arc.ArchiveError, crypto.BackupCryptoError)
    text = str(e) if isinstance(e, known) else f'{e.__class__.__name__}: {str(e).splitlines()[0] if str(e) else ""}'
    try:
        cfg = OffhostBackupConfig.get()
        secrets = [cfg.backup_key, cfg.sftp_password, cfg.sftp_private_key]
    except Exception:
        secrets = []
    for s in secrets:
        if s and len(s) >= 4 and s in text:
            text = text.replace(s, '[secret]')
    return text[:2000]


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

def verify_file(enc_path, key_text, work: Path, expected_sha256=''):
    """Check one downloaded archive. Returns (ok, checks). Works only inside
    ``work``; never touches the live database or media."""
    checks = []
    h = hashlib.sha256()
    with open(enc_path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    digest = h.hexdigest()
    if expected_sha256:
        if digest != expected_sha256:
            checks.append(('download hash', False, f'sha256 {digest[:16]}… does not match the {expected_sha256[:16]}… '
                                                  'recorded at upload'))
            return False, checks
        checks.append(('download hash', True, f'sha256 matches the upload ({digest[:16]}…)'))
    else:
        checks.append(('download hash', True, f'sha256 {digest[:16]}… (no upload record to compare)'))
    plain = work / 'archive.tar.gz'
    try:
        crypto.decrypt_file(enc_path, plain, key_text)
    except crypto.BackupCryptoError as e:
        checks.append(('decrypt', False, str(e)))
        return False, checks
    checks.append(('decrypt', True, 'every segment authenticated with the backup key'))
    extract = arc.private_dir(work / 'x')
    ok, more, _manifest = arc.check_extracted(plain, extract)
    checks.extend(more)
    return ok, checks


def run_verify(*, trigger='scheduler', user=None, out=None):
    from core.models import OffhostBackupConfig, OffhostBackupRun
    cfg = OffhostBackupConfig.get()
    problems = readiness_problems(cfg)
    if problems:
        raise NotReady('Restore verification cannot run: ' + '; '.join(problems) + '.')
    run = OffhostBackupRun.objects.create(kind='verify', trigger=trigger, destination=cfg.destination_label()[:600],
                                          requested_by=user)
    OffhostBackupConfig.objects.filter(pk=1).update(verify_requested_at=None)
    work = arc.private_dir(staging_root()) / f'verify-{run.pk}'
    old_umask = os.umask(0o077)
    try:
        work.mkdir(mode=0o700)
        with open_destination(cfg) as dest:
            listing = dest.list()
            if not listing:
                raise DestinationError('There is no backup archive at the destination to verify.')
            newest = listing[-1]['name']
            run.remote_name = newest
            if out:
                out(f'Downloading {newest}...')
            enc = work / newest
            dest.get(newest, enc)
        uploaded = (OffhostBackupRun.objects.filter(kind='backup', status='success', remote_name=newest)
                    .exclude(sha256='').values_list('sha256', flat=True).first()) or ''
        run.size_bytes = enc.stat().st_size
        try:
            run.key_fingerprint = crypto.archive_key_fingerprint(enc)
        except crypto.BackupCryptoError:
            pass
        ok, checks = verify_file(enc, cfg.backup_key, work, expected_sha256=uploaded)
        now = timezone.now()
        run.checks = [{'check': c, 'ok': o, 'detail': d} for c, o, d in checks]
        failed = [f'{c}: {d}' for c, o, d in checks if not o]
        run.status = 'success' if ok and not failed else 'failed'
        run.detail = (f'{newest} restores: ' + '; '.join(f'{c} ok' for c, o, d in checks)) if run.status == 'success' \
            else f'{newest} FAILED verification: ' + '; '.join(failed)[:1500]
        run.finished_at = now
        run.save()
        upd = dict(last_verify_at=now, last_verify_status=run.status, last_verify_detail=run.detail)
        if run.status == 'success':
            upd.update(last_verified_name=newest, last_verified_ok_at=now)
        OffhostBackupConfig.objects.filter(pk=1).update(**upd)
        _audit(user, 'read', f'Off-host restore verification {run.status} ({trigger}): {run.detail}',
               {'event': 'offhost_verify', 'trigger': trigger, 'archive': newest, 'checks': run.checks},
               success=run.status == 'success')
        if run.status != 'success':
            raise arc.ArchiveError(run.detail)
        return run
    except Exception as e:
        if run.status == 'failed' and run.finished_at:
            raise
        msg = _safe_message(e)
        now = timezone.now()
        run.status, run.finished_at, run.detail = 'failed', now, msg
        run.save()
        OffhostBackupConfig.objects.filter(pk=1).update(last_verify_at=now, last_verify_status='failed',
                                                        last_verify_detail=msg)
        _audit(user, 'read', f'Off-host restore verification FAILED ({trigger}): {msg}',
               {'event': 'offhost_verify', 'trigger': trigger}, success=False)
        logger.error('offhost verification failed: %s', msg)
        raise
    finally:
        os.umask(old_umask)
        arc.rmtree(work)


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------

def backup_due(cfg, now=None):
    now = now or timezone.now()
    if cfg.backup_requested_at:
        return True
    if not cfg.last_backup_at:
        return True
    interval = timedelta(hours=max(1, cfg.backup_interval_hours))
    if cfg.last_backup_status == 'failed':
        interval = min(interval, FAILED_RETRY)
    return now - cfg.last_backup_at >= interval


def verify_due(cfg, now=None):
    now = now or timezone.now()
    if cfg.verify_requested_at:
        return True
    if not cfg.last_success_at:
        return False
    if not cfg.last_verify_at:
        return True
    interval = timedelta(days=max(1, cfg.verify_interval_days))
    if cfg.last_verify_status == 'failed':
        interval = min(interval, timedelta(days=1))
    return now - cfg.last_verify_at >= interval


def tick(*, out=None, sqlite_source=None, media_root=None):
    """What the scheduler runs. Returns a short status string; raises when a
    run that was due failed, so the Scheduled Tasks page shows it."""
    from core.models import OffhostBackupConfig
    cfg = OffhostBackupConfig.get()
    if not cfg.enabled:
        return 'disabled'
    problems = readiness_problems(cfg)
    if problems:
        raise NotReady('Off-host backup is switched on but cannot run: ' + '; '.join(problems) + '.')
    done, errors = [], []
    if backup_due(cfg):
        try:
            run_backup(out=out, sqlite_source=sqlite_source, media_root=media_root,
                       trigger='manual' if cfg.backup_requested_at else 'scheduler')
            done.append('backup')
        except Exception as e:  # noqa: BLE001 — recorded; verification may still run
            errors.append(f'backup: {_safe_message(e)}')
        cfg = OffhostBackupConfig.get()
    if verify_due(cfg):
        try:
            run_verify(out=out, trigger='manual' if cfg.verify_requested_at else 'scheduler')
            done.append('verify')
        except Exception as e:  # noqa: BLE001
            errors.append(f'verify: {_safe_message(e)}')
    if errors:
        raise RuntimeError(' | '.join(errors))
    return ', '.join(done) or 'nothing due'


def request_now(kind, user):
    """Queue a run for the next scheduler pass (within a minute) instead of
    holding a web request open for a full backup."""
    from core.models import OffhostBackupConfig, ScheduledTask
    now = timezone.now()
    field = 'backup_requested_at' if kind == 'backup' else 'verify_requested_at'
    OffhostBackupConfig.objects.filter(pk=1).update(**{field: now})
    ScheduledTask.objects.filter(task_type='offhost_backup').exclude(last_status='running').update(next_run_at=now)
    _audit(user, 'update', f'Off-host {"backup" if kind == "backup" else "restore verification"} requested now',
           {'event': f'offhost_{kind}_requested'})


# ---------------------------------------------------------------------------
# health (system warnings, readiness)
# ---------------------------------------------------------------------------

def health(now=None):
    """{'state': 'not_configured'|'disabled'|'ok'|'stale'|'failing'|'verify_failed'|'not_ready', ...}"""
    from core.models import OffhostBackupConfig
    now = now or timezone.now()
    cfg = OffhostBackupConfig.objects.filter(pk=1).first()
    if cfg is None or not cfg.destination_configured():
        return {'state': 'not_configured', 'detail': 'No off-host backup destination is configured.'}
    if not cfg.enabled:
        return {'state': 'disabled', 'detail': 'Off-host backups are configured but switched off.'}
    problems = readiness_problems(cfg)
    if problems:
        return {'state': 'not_ready', 'detail': 'Switched on but cannot run: ' + '; '.join(problems) + '.'}
    limit = timedelta(days=max(1, cfg.alert_after_days))
    if cfg.last_verify_status == 'failed':
        return {'state': 'verify_failed', 'since': cfg.last_verify_at,
                'detail': (cfg.last_verify_detail or 'Restore verification failed.')[:300]}
    if not cfg.last_success_at or now - cfg.last_success_at > limit:
        when = cfg.last_success_at.strftime('%Y-%m-%d %H:%M') if cfg.last_success_at else 'never'
        detail = f'Last successful off-host backup: {when}.'
        if cfg.last_backup_status == 'failed':
            detail += f' Last attempt failed: {(cfg.last_backup_detail or "")[:200]}'
        return {'state': 'stale', 'since': cfg.last_success_at, 'detail': detail}
    if cfg.last_verified_ok_at is None or now - cfg.last_verified_ok_at > timedelta(days=cfg.verify_interval_days * 2 + 1):
        return {'state': 'unverified', 'since': cfg.last_verified_ok_at,
                'detail': 'Backups upload, but no archive has passed restore verification recently.'}
    return {'state': 'ok', 'detail': f'Last backup {cfg.last_success_at:%Y-%m-%d %H:%M}, last verified '
                                     f'{cfg.last_verified_ok_at:%Y-%m-%d %H:%M}.'}
