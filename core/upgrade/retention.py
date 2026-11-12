"""Retention for pre-upgrade backups: how many to keep, and for how long.

A snapshot is a full copy of the database and the uploads (about 540 MB on
a mid-sized install), so they must not pile up. The rules:

    keep          the newest N verified snapshots (Settings -> Updates, or
                  UPGRADE_BACKUPS_KEEP; at least 1, default 5)
    max age       optionally, verified snapshots older than this many days
                  go too (blank: no age limit)
    unverified    a snapshot that never verified (an interrupted run, a
                  failed verification, a half-written directory) is kept for
                  UPGRADE_UNVERIFIED_GRACE_DAYS (default 14) so an admin can
                  look at it, then removed

Never removed, by any of the above or by a manual delete:

    * the newest verified snapshot (the one you would restore)
    * the snapshot the upgrade journal points at (the running upgrade's, or
      the one a failed upgrade needs for recovery)
    * a snapshot that is still being written

and nothing at all is removed by a cleanup started outside an upgrade while
an upgrade is running or the last one needs recovery.

Every upgrade run grooms itself (core.upgrade.apply): before it takes its
snapshot (counting the new one, so the space is free first, but never
below one verified backup) and again when it finishes, whether it worked or
not. A daily scheduled task (`upgrade_backup_prune`) covers installs that
rarely update. Settings -> Updates and `manage.py upgrade_backup --prune /
--delete` do the same on request. Each removal is written to the run output
and the audit log.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings

from . import journal, snapshot

NAME_RE = re.compile(r'^snapshot-[A-Za-z0-9][A-Za-z0-9._+-]*$')
DEFAULT_KEEP = 5
DEFAULT_GRACE_DAYS = 14
# An unverified snapshot touched this recently may still be being written.
IN_PROGRESS_SECONDS = 15 * 60


class RetentionRefused(Exception):
    """Nothing was removed; the message says why."""


@dataclass
class Policy:
    keep: int
    max_age_days: int | None
    grace_days: int
    keep_from: str = 'default'

    def as_dict(self):
        return {'keep': self.keep, 'max_age_days': self.max_age_days,
                'grace_days': self.grace_days, 'keep_from': self.keep_from}


def env_keep() -> int:
    try:
        return max(int(getattr(settings, 'UPGRADE_BACKUPS_KEEP', DEFAULT_KEEP) or DEFAULT_KEEP), 1)
    except (TypeError, ValueError):
        return DEFAULT_KEEP


def grace_days() -> int:
    try:
        return max(int(getattr(settings, 'UPGRADE_UNVERIFIED_GRACE_DAYS', DEFAULT_GRACE_DAYS)), 1)
    except (TypeError, ValueError):
        return DEFAULT_GRACE_DAYS


def policy() -> Policy:
    """What Settings -> Updates says, falling back to the environment."""
    keep, max_age, keep_from = None, None, 'environment'
    try:
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        keep, max_age = s.upgrade_backups_keep, s.upgrade_backups_max_age_days
    except Exception:
        pass
    if keep:
        keep_from = 'settings'
    else:
        keep = env_keep()
    return Policy(keep=max(int(keep), 1), max_age_days=int(max_age) if max_age else None,
                  grace_days=grace_days(), keep_from=keep_from)


# ---------------------------------------------------------------------------
# what is on disk
# ---------------------------------------------------------------------------

def _dir_stats(path: Path):
    """(total bytes, newest mtime) of the files directly inside a snapshot.
    A snapshot is flat (a handful of files), so this is a few stat calls."""
    size, newest = 0, 0.0
    try:
        newest = path.lstat().st_mtime
        with os.scandir(path) as it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if e.is_file(follow_symlinks=False):
                    size += st.st_size
                newest = max(newest, st.st_mtime)
    except OSError:
        pass
    return size, newest


def _created_ts(manifest: dict, fallback: float) -> float:
    try:
        return datetime.fromisoformat(str(manifest.get('created_at'))).timestamp()
    except (TypeError, ValueError):
        return fallback


def inventory(quick=True) -> list[dict]:
    """Every snapshot directory under the backup root, newest first,
    including half-written ones without a manifest. `quick` compares file
    sizes instead of re-hashing (see snapshot.is_verified)."""
    root = journal.backup_root()
    if not root.is_dir():
        return []
    now = time.time()
    rows = []
    for p in root.iterdir():
        if not NAME_RE.match(p.name) or p.is_symlink() or not p.is_dir():
            continue
        size, newest = _dir_stats(p)
        manifest, readable = {}, False
        if (p / 'manifest.json').is_file():
            try:
                manifest, readable = snapshot.load_manifest(p), True
            except snapshot.SnapshotError:
                pass
        if readable:
            verified, detail = snapshot.is_verified(p, quick=quick)
        else:
            verified, detail = False, 'incomplete (no readable manifest)'
        created = _created_ts(manifest, newest)
        rows.append({
            'path': str(p), 'name': p.name, 'created_ts': created,
            'created_at': manifest.get('created_at') or datetime.fromtimestamp(created).isoformat(),
            'created_dt': datetime.fromtimestamp(created, tz=dt_timezone.utc),
            'app_version': manifest.get('app_version') or '', 'git_sha': manifest.get('git_sha') or '',
            'reason': manifest.get('reason') or '', 'verified': verified, 'detail': detail,
            'size': size, 'age_days': max(now - created, 0) / 86400,
            'in_progress': (not verified and not (p / 'verification.json').exists()
                            and now - newest < IN_PROGRESS_SECONDS),
        })
    rows.sort(key=lambda r: (r['created_ts'], r['name']), reverse=True)
    return rows


def pinned_path() -> str:
    data = journal.read() or {}
    return str(data.get('backup') or '')


def _same(a, b) -> bool:
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


# ---------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------

def plan(*, reserve=0, pol: Policy | None = None, rows=None, full_check=True) -> dict:
    """Which snapshots retention would remove, and why each one stays.

    reserve: slots to leave for a snapshot about to be taken (an upgrade run
    grooms before its backup, counting the new one); never below one
    verified snapshot. full_check re-hashes the snapshots that are kept as
    the verified ones, so a damaged file cannot make a broken snapshot the
    one that is kept while good ones go.

    Returns {'delete': [(row, why)], 'keep': [(row, why)], 'policy': Policy}.
    """
    pol = pol or policy()
    rows = inventory(quick=True) if rows is None else rows
    pinned = pinned_path()
    slots = max(pol.keep - max(int(reserve), 0), 1)
    delete, keep = [], []
    kept_verified, newest_kept = 0, False
    for row in rows:   # newest first
        if _same(row['path'], pinned):
            keep.append((row, 'used by the upgrade journal'))
            if row['verified']:   # it fills a slot (it is the newest after a run)
                kept_verified += 1
                newest_kept = True
            continue
        verified = row['verified']
        if verified and full_check and (not newest_kept or kept_verified < slots):
            verified, detail = snapshot.is_verified(row['path'], quick=False)
            if not verified:
                row = {**row, 'verified': False, 'detail': detail}
        if verified:
            if not newest_kept:
                kept_verified += 1
                newest_kept = True
                keep.append((row, 'newest verified backup'))
            elif kept_verified >= slots:
                delete.append((row, f'more than {slots} verified backup(s)'
                               + (' (one slot left for the new backup)' if slots < pol.keep else '')))
            elif pol.max_age_days and row['age_days'] > pol.max_age_days:
                delete.append((row, f'older than {pol.max_age_days} day(s)'))
            else:
                kept_verified += 1
                keep.append((row, 'within the retention limit'))
        elif row.get('in_progress'):
            keep.append((row, 'still being written'))
        elif row['age_days'] > pol.grace_days:
            delete.append((row, f'not verified, older than {pol.grace_days} day(s)'))
        else:
            keep.append((row, f'not verified; kept {pol.grace_days} day(s) for inspection'))
    return {'delete': delete, 'keep': keep, 'policy': pol}


def guard(in_run=False):
    """Refuse a cleanup started outside an upgrade while one is running or
    the last one needs recovery."""
    if in_run:
        return
    a = journal.assess()
    if a['state'] in ('running', 'unreadable') or a['needs_recovery']:
        raise RetentionRefused('Backups are not removed while an upgrade is running or the last '
                               f"one needs recovery: {a['message']}")


# ---------------------------------------------------------------------------
# removing
# ---------------------------------------------------------------------------

def resolve_snapshot(path_or_name) -> Path:
    """The snapshot directory a request names, or RetentionRefused.

    Only a directory directly under the backup root, named snapshot-*, and
    not a symlink (the name is checked before anything is resolved)."""
    raw = str(path_or_name or '').strip()
    if not raw:
        raise RetentionRefused('No backup named.')
    root = journal.backup_root()
    p = Path(raw)
    if not p.is_absolute():
        if len(p.parts) != 1:
            raise RetentionRefused('Name a backup directory directly under the backup root.')
        p = root / p
    if not NAME_RE.match(p.name) or p.name in ('.', '..'):
        raise RetentionRefused(f'{p.name!r} is not an upgrade backup directory.')
    try:
        root_real = root.resolve(strict=True)
        parent_real = p.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise RetentionRefused(f'No such backup: {p}')
    if parent_real != root_real:
        raise RetentionRefused(f'{p} is not directly under the backup root {root}.')
    candidate = root_real / p.name
    if candidate.is_symlink():
        raise RetentionRefused(f'{candidate} is a symbolic link, not a backup.')
    if not candidate.is_dir():
        raise RetentionRefused(f'No such backup: {candidate}')
    return candidate


def _audit(row, why, *, user, trigger, ok=True, error=''):
    try:
        from audit.models import AuditLog
        AuditLog.objects.create(
            action='delete', object_type='upgrade_backup', object_repr=row['name'][:255],
            description=(f"Removed upgrade backup {row['name']} ({why})" if ok else
                         f"Could not remove upgrade backup {row['name']}: {error}"),
            user=user if getattr(user, 'pk', None) else None,
            username=getattr(user, 'username', None) or 'system', success=ok,
            extra_data={'path': row['path'], 'reason': why, 'trigger': trigger,
                        'size_bytes': row.get('size'), 'app_version': row.get('app_version'),
                        'created_at': row.get('created_at'), 'verified': row.get('verified'),
                        'error': error or None})
    except Exception:
        import logging
        logging.getLogger('core').exception('could not write the backup removal audit entry')


def _remove(row, why, *, user, trigger, out):
    path = resolve_snapshot(row['path'])
    try:
        shutil.rmtree(path)
    except OSError as e:
        snapshot._out(out, f"Could not remove upgrade backup {path}: {e}")
        _audit(row, why, user=user, trigger=trigger, ok=False, error=str(e))
        return False
    snapshot._out(out, f"Removed upgrade backup {row['name']} ({why}; "
                       f"{human(row.get('size') or 0)} freed)")
    _audit(row, why, user=user, trigger=trigger)
    return True


def _locked(in_run):
    if in_run:   # the run already holds the upgrade lock
        from contextlib import nullcontext
        return nullcontext()
    return journal.upgrade_lock()


def prune(*, trigger='manual', user=None, out=None, reserve=0, in_run=False,
          keep=None) -> list[str]:
    """Apply retention. Returns the removed paths.

    in_run: called by an upgrade run that holds the lock itself (it may groom
    while its own journal entry says running). Anything else takes the lock
    and is refused while an upgrade is running or needs recovery."""
    guard(in_run)
    try:
        with _locked(in_run):
            guard(in_run)   # again, now that no upgrade can start
            pol = policy()
            if keep is not None:
                pol.keep = max(int(keep), 1)
            decision = plan(reserve=reserve, pol=pol)
            removed = []
            for row, why in decision['delete']:
                try:
                    if _remove(row, why, user=user, trigger=trigger, out=out):
                        removed.append(row['path'])
                except RetentionRefused as e:
                    snapshot._out(out, f"Skipped {row['path']}: {e}")
            return removed
    except journal.LockHeld:
        raise RetentionRefused('An upgrade is running; backups are cleaned up when it finishes.')


def delete(path_or_name, *, user=None, out=None, trigger='manual') -> str:
    """Remove one snapshot on request, with the same protections."""
    guard(False)
    try:
        with journal.upgrade_lock():
            guard(False)
            target = resolve_snapshot(path_or_name)
            if _same(target, pinned_path()):
                raise RetentionRefused(f'{target.name} is the backup the upgrade journal points at '
                                       '(needed to recover the last upgrade); it cannot be removed.')
            rows = inventory(quick=True)
            row = next((r for r in rows if _same(r['path'], target)), None)
            if row is None:
                raise RetentionRefused(f'No such backup: {target}')
            if row['in_progress']:
                raise RetentionRefused(f'{target.name} is still being written.')
            if row['verified']:
                newest = next((r for r in rows if r['verified']), None)
                if newest and _same(newest['path'], target):
                    raise RetentionRefused(f'{target.name} is the newest verified backup; it is '
                                           'always kept.')
            _remove(row, 'removed by request', user=user, trigger=trigger, out=out)
            return str(target)
    except journal.LockHeld:
        raise RetentionRefused('An upgrade is running; try again when it has finished.')


# ---------------------------------------------------------------------------
# for the Updates page
# ---------------------------------------------------------------------------

def human(n) -> str:
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def free_space(path: Path | None = None):
    probe = Path(path or journal.backup_root())
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def summary() -> dict:
    """Backups with size / version / date / verified state and what
    retention would do, without re-hashing anything (quick checks)."""
    pol = policy()
    rows = inventory(quick=True)
    decision = plan(pol=pol, rows=rows, full_check=False)
    why = {r['path']: (w, False) for r, w in decision['keep']}
    why.update({r['path']: (w, True) for r, w in decision['delete']})
    pinned = pinned_path()
    newest_verified = next((r['path'] for r in rows if r['verified']), None)
    for r in rows:
        r['retention'], r['would_remove'] = why.get(r['path'], ('', False))
        r['size_human'] = human(r['size'])
        r['protected'] = (_same(r['path'], pinned) or r['path'] == newest_verified
                          or r['in_progress'])
    total = sum(r['size'] for r in rows)
    free = free_space()
    return {'backups': rows, 'total_bytes': total, 'total_human': human(total),
            'free_bytes': free, 'free_human': human(free) if free is not None else 'unknown',
            'policy': pol, 'env_keep': env_keep(),
            'would_remove': sum(1 for r in rows if r['would_remove'])}
