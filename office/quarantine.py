"""Quarantine: editor saves that could not become a revision, kept for recovery.

A save is quarantined when it is stale (based on an older revision), arrives
on a revoked/expired session, comes from a user who lost edit rights, fails
validation/scanning, or cannot be stored. The bytes are kept under
MEDIA_ROOT/office/quarantine/ until ``expires_at`` (Settings → Office
Documents → quarantine retention, default 30 days) and are then removed by
the ``office_purge_quarantine`` scheduled task.

Recovery: users who may edit the file see its quarantined saves on the file's
version-history page and can download one or restore it as a new revision;
superusers see all of them under Settings → Office Documents.
"""
from __future__ import annotations

import logging
import os
import uuid

from django.utils import timezone

from .logging_filters import get_logger

logger = get_logger('office')


def keep(target, spool, *, session=None, user=None, reason='storage_error', detail='',
         original_name=None):
    """Move a spooled save into quarantine. Returns the QuarantinedSave."""
    from .models import QuarantinedSave
    from .storage import _abs, _fsync_dir, quarantine_expiry, safe_filename

    name = f'office/quarantine/{timezone.now():%Y/%m}/{uuid.uuid4().hex}'
    dest = _abs(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(spool.path, dest)
    _fsync_dir(dest.parent)
    fk = {}
    org_id = None
    label = ''
    if target is not None:
        fk = target.fk_id()
        org_id = target.organization_id
        label = target.label()
    elif session is not None:
        org_id = session.organization_id
        label = session.target_label
    acting = user if (user is not None and getattr(user, 'is_authenticated', False)) else None
    return QuarantinedSave.objects.create(
        organization_id=org_id, target_label=label, session=session, user=acting,
        file=name, sha256=spool.sha256, size=spool.size,
        original_name=safe_filename(original_name or (target.filename if target else 'unsaved')),
        reason=reason if reason in dict(QuarantinedSave.REASONS) else 'storage_error',
        detail=(detail or '')[:500], expires_at=quarantine_expiry(), **fk)


def keep_bytes(target, data, **kwargs):
    """`keep` for callers holding raw bytes / a stream (e.g. a session whose
    target no longer exists). Pass target=None with session=... then."""
    from .storage import _Spool, max_bytes
    spool = _Spool(data, max_bytes())
    try:
        return keep(target, spool, **kwargs)
    finally:
        spool.cleanup()


def purge_expired(now=None) -> dict:
    """Delete expired quarantined saves and expired diagnostics files."""
    from .models import EditSession, OfficeFile, QuarantinedSave
    from .storage import _abs, purge_unreferenced_file
    now = now or timezone.now()
    removed = 0
    for q in QuarantinedSave.objects.filter(expires_at__lte=now).iterator():
        name = q.file.name
        q.delete()
        try:
            _abs(name).unlink()
        except (FileNotFoundError, ValueError):
            pass
        removed += 1
    diag = 0
    for f in OfficeFile.objects.filter(purpose='diagnostic', expires_at__lte=now):
        names = list(f.revisions.values_list('file', flat=True))
        EditSession.objects.filter(office_file=f, state__in=EditSession.LIVE_STATES).update(
            state='closed', closed_at=now, end_reason='diagnostics file purged')
        f.delete()
        for name in names:
            purge_unreferenced_file(name)
        diag += 1
    # Sessions nobody closed: mark them closed once they expired.
    stale = EditSession.objects.filter(state__in=EditSession.LIVE_STATES,
                                       expires_at__lte=now).update(
        state='closed', closed_at=now, end_reason='expired')
    return {'quarantine_removed': removed, 'diagnostic_files_removed': diag,
            'sessions_expired': stale}
