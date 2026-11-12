"""WOPI locks, one per target file (office.models.WopiLock).

    get(target) -> str                        current lock id or ''
    lock(target, lock_id, session) -> LockResult
    unlock(target, lock_id) -> LockResult
    refresh(target, lock_id, session) -> LockResult
    unlock_and_relock(target, old_lock_id, new_lock_id, session) -> LockResult
    check_write(target, lock_id) -> LockResult (PutFile / RenameFile)

Semantics follow the WOPI specification (Lock, Unlock, RefreshLock,
GetLock, UnlockAndRelock): a lock lasts 30 minutes unless refreshed; LOCK
with the id already held refreshes it; any mismatch is a conflict and
reports the current lock id (``''`` when unlocked) for the X-WOPI-Lock
response header. Collabora 26.04 itself only sends LOCK and UNLOCK and
refreshes by re-sending LOCK every 900 s (storage.wopi.locking.refresh).

Every change is a compare-and-set UPDATE on the single row of the target
(or an INSERT guarded by its unique constraint), retried a few times, so
two editors racing for a lock cannot both get it on any database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

LOCK_TTL = timedelta(minutes=30)
MAX_LOCK_LEN = 1024
_RETRIES = 5


@dataclass
class LockResult:
    ok: bool
    current: str = ''        # lock id to report in X-WOPI-Lock on conflict
    reason: str = ''


def valid_lock_id(lock_id) -> bool:
    return (isinstance(lock_id, str) and 0 < len(lock_id) <= MAX_LOCK_LEN
            and all(0x20 <= ord(c) < 0x7f for c in lock_id))


def _row(target):
    from ...models import WopiLock
    return WopiLock.objects.filter(target_kind=target.kind, target_pk=target.pk).first()


def _live(row, now):
    return row is not None and row.lock_id and row.expires_at > now


def get(target) -> str:
    row = _row(target)
    return row.lock_id if _live(row, timezone.now()) else ''


def _set(target, row, new_id, session, now):
    """CAS: replace `row` (as read) with `new_id`. False if someone changed it first."""
    from ...models import WopiLock
    fields = dict(lock_id=new_id, expires_at=now + LOCK_TTL,
                  session_id=getattr(session, 'pk', None), updated_at=now)
    if row is None:
        try:
            with transaction.atomic():
                WopiLock.objects.create(target_kind=target.kind, target_pk=target.pk, **fields)
            return True
        except IntegrityError:
            return False
    return bool(WopiLock.objects.filter(pk=row.pk, lock_id=row.lock_id,
                                        expires_at=row.expires_at).update(**fields))


def _clear(row):
    from ...models import WopiLock
    return bool(WopiLock.objects.filter(pk=row.pk, lock_id=row.lock_id,
                                        expires_at=row.expires_at).update(
        lock_id='', expires_at=timezone.now()))


def lock(target, lock_id, session) -> LockResult:
    if not valid_lock_id(lock_id):
        return LockResult(False, get(target), 'invalid lock id')
    for _ in range(_RETRIES):
        now = timezone.now()
        row = _row(target)
        if _live(row, now) and row.lock_id != lock_id:
            return LockResult(False, row.lock_id, 'locked by another editor')
        if _set(target, row, lock_id, session, now):
            return LockResult(True, lock_id)
    return LockResult(False, get(target), 'lock contention')


def refresh(target, lock_id, session) -> LockResult:
    for _ in range(_RETRIES):
        now = timezone.now()
        row = _row(target)
        if not _live(row, now) or row.lock_id != lock_id:
            return LockResult(False, row.lock_id if _live(row, now) else '', 'lock mismatch')
        if _set(target, row, lock_id, session, now):
            return LockResult(True, lock_id)
    return LockResult(False, get(target), 'lock contention')


def unlock(target, lock_id) -> LockResult:
    for _ in range(_RETRIES):
        now = timezone.now()
        row = _row(target)
        if not _live(row, now) or row.lock_id != lock_id:
            return LockResult(False, row.lock_id if _live(row, now) else '', 'lock mismatch')
        if _clear(row):
            return LockResult(True, '')
    return LockResult(False, get(target), 'lock contention')


def unlock_and_relock(target, old_lock_id, new_lock_id, session) -> LockResult:
    if not valid_lock_id(new_lock_id):
        return LockResult(False, get(target), 'invalid lock id')
    for _ in range(_RETRIES):
        now = timezone.now()
        row = _row(target)
        if not _live(row, now) or row.lock_id != old_lock_id:
            return LockResult(False, row.lock_id if _live(row, now) else '', 'lock mismatch')
        if _set(target, row, new_lock_id, session, now):
            return LockResult(True, new_lock_id)
    return LockResult(False, get(target), 'lock contention')


def check_write(target, lock_id, *, file_size=None) -> LockResult:
    """May a PutFile / RenameFile carrying `lock_id` proceed? WOPI: when the
    file is locked the ids must match; when it is unlocked, only a 0-byte
    file may be written without a lock."""
    current = get(target)
    if current:
        if current == (lock_id or ''):
            return LockResult(True, current)
        return LockResult(False, current, 'locked by another editor')
    if file_size == 0:
        return LockResult(True, '')
    return LockResult(False, '', 'not locked')
