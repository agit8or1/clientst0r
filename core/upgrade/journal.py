"""Upgrade journal: one JSON file recording the upgrade in progress or the
last one that ran.

Both the Python pipeline (core.upgrade.apply) and the update script it runs
(deploy/update_instructions.sh, which writes the same file with a few lines
of inline Python) record stages here. It lives next to the backups, outside
any process's memory, so it survives the reload at the end of an update, a
killed worker, or a reboot in the middle of a migration. The next Apply, the
Updates page and `manage.py upgrade_status` read it and refuse to start a new
upgrade over one that did not finish.

Stages, in order:

    started, revision_verified, preflight_ok, backup_verified,
    code_checked_out, deps_installed, migrating, migrated, static_collected,
    reloading, complete

Status is one of running, complete, aborted (stopped before anything on
disk changed), rolled_back (code was put back automatically; the database
was never touched), failed (stopped at or after the migration; needs the
recovery steps), recovered (an operator restored or resumed it).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from django.conf import settings

STAGES = (
    'started', 'revision_verified', 'preflight_ok', 'backup_verified',
    'code_checked_out', 'deps_installed', 'migrating', 'migrated',
    'static_collected', 'reloading', 'complete',
)
# From this stage on the database may differ from the pre-upgrade backup.
DB_TOUCHED_FROM = STAGES.index('migrating')
# Before this stage nothing on disk has changed.
CODE_TOUCHED_FROM = STAGES.index('code_checked_out')

FINISHED = ('complete', 'aborted', 'rolled_back', 'recovered')


def backup_root() -> Path:
    return Path(getattr(settings, 'UPGRADE_BACKUP_DIR', None)
                or Path(settings.BASE_DIR) / 'backups' / 'upgrades')


def journal_path() -> Path:
    return backup_root() / 'journal.json'


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def read() -> dict | None:
    try:
        with open(journal_path(), encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {'status': 'unreadable', 'stage': 'unknown',
                'error': f'{journal_path()} exists but cannot be read'}
    return data if isinstance(data, dict) else None


def write(data: dict) -> dict:
    ensure_private_dir(journal_path().parent)
    data = dict(data)
    data['updated_at'] = time.time()
    fd, tmp = tempfile.mkstemp(dir=str(journal_path().parent), prefix='.journal.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, journal_path())
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return data


def begin(**fields) -> dict:
    data = {'status': 'running', 'stage': 'started', 'started_at': time.time(),
            'pid': os.getpid(), 'history': [{'stage': 'started', 'at': time.time()}]}
    data.update(fields)
    return write(data)


def stage(name: str, **fields) -> dict:
    if name not in STAGES:
        raise ValueError(f'unknown upgrade stage {name!r}')
    data = read() or {}
    data['stage'] = name
    data.setdefault('history', []).append({'stage': name, 'at': time.time()})
    if name == 'complete':
        data['status'] = 'complete'
    data.update(fields)
    return write(data)


def finish(status: str, **fields) -> dict:
    data = read() or {}
    data['status'] = status
    data.setdefault('history', []).append({'status': status, 'at': time.time()})
    data.update(fields)
    return write(data)


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stage_index(data: dict) -> int:
    try:
        return STAGES.index(data.get('stage'))
    except ValueError:
        return len(STAGES)   # unknown: assume the worst


def assess(data: dict | None = None) -> dict:
    """What the journal means for the operator.

    Returns {state, needs_recovery, db_touched, message, journal}. state is
    one of none, complete, running, interrupted, failed, aborted, rolled_back,
    recovered, unreadable.
    """
    data = read() if data is None else data
    if not data:
        return {'state': 'none', 'needs_recovery': False, 'db_touched': False,
                'message': 'No upgrade has been recorded.', 'journal': None}
    status = data.get('status')
    idx = stage_index(data)
    db_touched = idx >= DB_TOUCHED_FROM
    if status == 'unreadable':
        return {'state': 'unreadable', 'needs_recovery': True, 'db_touched': True,
                'message': data.get('error'), 'journal': data}
    if status == 'running':
        alive = _pid_alive(data.get('script_pid')) or _pid_alive(data.get('pid'))
        if alive:
            return {'state': 'running', 'needs_recovery': False, 'db_touched': db_touched,
                    'message': f"An upgrade is running (stage: {data.get('stage')}).",
                    'journal': data}
        state = 'interrupted'
    elif status == 'failed':
        state = 'failed'
    else:
        state = status or 'unknown'
    needs = state in ('interrupted', 'failed') and idx >= CODE_TOUCHED_FROM
    if state in ('interrupted', 'failed') and not needs:
        message = ('The last upgrade stopped before anything was changed '
                   f"(stage: {data.get('stage')}). Nothing to recover.")
    elif needs and db_touched:
        message = ('The last upgrade stopped during or after the database migration '
                   f"(stage: {data.get('stage')}). Resume it or restore the verified "
                   'backup before applying anything else: see docs/UPGRADE_AND_RECOVERY.md.')
    elif needs:
        message = ('The last upgrade stopped after the new code was checked out but before '
                   f"the database was migrated (stage: {data.get('stage')}). The database is "
                   'unchanged. Resume it, or restore to put the old code back.')
    else:
        message = f"Last upgrade: {state} (stage: {data.get('stage')})."
    return {'state': state, 'needs_recovery': needs, 'db_touched': db_touched,
            'message': message, 'journal': data}
