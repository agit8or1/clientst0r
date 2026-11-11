"""Binary revision storage: the only code that changes an Office file.

Public API (used by views and by the provider connectors):

    current(target) -> FileRevision | None
    ensure_current(target, user=None) -> FileRevision | None
        Seeds revision 1 from the target's existing file on first use, and
        records a file replaced outside Office (e.g. a re-upload) as a new
        revision. Call before opening a session or listing history.
    save_new_revision(target, data, *, user, source, expected_base_revision=None,
                      session=None, original_name=None) -> FileRevision
        Atomic and durable. Raises StaleRevision, SessionRevoked,
        PermissionRevoked, RevisionRejected or StorageError. The returned
        revision has ``.duplicate = True`` when the call repeated an
        already-stored save (same content, same session) and nothing new was
        written.
    save_or_quarantine(...) -> SaveOutcome
        Same arguments; never raises for the five errors above — the bytes
        are kept as a QuarantinedSave instead. Provider callbacks use this
        and answer the editor "saved" only when ``outcome.ok``.
    restore(target, revision, user) -> FileRevision
        Copies an old revision forward as a new one; history is never
        rewritten.
    open_revision(revision) -> binary file object

Write path of save_new_revision:

  1. Stream the bytes into a temp file under MEDIA_ROOT/office/tmp, hashing
     (SHA-256) and counting as it goes; refuse past the size limit; fsync.
  2. Validate the content against the target's format (office.formats) and
     run the scan hook (office.scanning; no scanner ships by default).
  3. Move the temp file to its final, never-reused name
     office/revisions/<org>/<kind>-<pk>/<uuid>.<ext> (rename on the same
     file system) and fsync the directory.
  4. transaction.atomic(durable=True): lock the target row
     (SELECT ... FOR UPDATE), re-check the session and the user's edit
     permission, detect duplicates, compare the base revision, insert the
     FileRevision row and point the target's file field at the new file.
  5. Return after the commit. On any failure after step 3 the file is moved
     back, so nothing is left half-written.

Stored names are generated here from a uuid and a whitelisted extension; a
user-supplied name is only ever kept as ``original_name`` after
``safe_filename``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import formats
from .scanning import scan_file

from .logging_filters import get_logger

logger = get_logger('office')

CHUNK = 1024 * 1024
DEFAULT_MAX_FILE_MB = 100


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """Base class. ``reason`` maps onto QuarantinedSave.reason."""
    reason = 'storage_error'

    def __init__(self, message='', **kwargs):
        super().__init__(message)
        self.message = message
        for k, v in kwargs.items():
            setattr(self, k, v)


class StaleRevision(StorageError):
    """The save was based on an older revision than the current one.
    Attributes: expected (int), current (int)."""
    reason = 'stale'


class SessionRevoked(StorageError):
    """The edit session is closed, revoked, expired or for another file."""
    reason = 'revoked'


class PermissionRevoked(StorageError):
    """The user may no longer edit this file."""
    reason = 'permission'


class RevisionRejected(StorageError):
    """The content was refused: too large, wrong format, failed scan, or a
    read-only format. ``code`` is one of too_large / invalid / scan / read_only."""
    reason = 'validation'


QUARANTINABLE = (StaleRevision, SessionRevoked, PermissionRevoked, RevisionRejected, StorageError)


@dataclass
class SaveOutcome:
    revision: object = None       # FileRevision when stored
    quarantined: object = None    # QuarantinedSave when kept aside
    error: StorageError | None = None

    @property
    def ok(self):
        return self.revision is not None

    @property
    def duplicate(self):
        return bool(self.revision is not None and getattr(self.revision, 'duplicate', False))


# ---------------------------------------------------------------------------
# Paths and names
# ---------------------------------------------------------------------------

def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def _abs(name) -> Path:
    root = media_root().resolve()
    full = (root / name).resolve()
    full.relative_to(root)  # ValueError if it escapes
    return full


_UNSAFE = re.compile(r'[\x00-\x1f\x7f<>:"|?*]')


def safe_filename(name, *, fallback='document') -> str:
    """A display file name with no path, control characters or reserved
    characters, at most 255 characters, extension kept."""
    name = unicodedata.normalize('NFC', str(name or ''))
    name = name.replace('\\', '/').split('/')[-1]
    name = _UNSAFE.sub('', name).strip().rstrip('. ').strip()
    name = re.sub(r'\s+', ' ', name)
    if not name or name.startswith('.'):
        name = fallback + name
    if len(name) > 255:
        stem, dot, ext = name.rpartition('.')
        name = (stem[:250 - len(ext)] + '.' + ext) if dot and len(ext) <= 10 else name[:255]
    return name


def max_bytes(instance=None) -> int:
    mb = int(getattr(settings, 'OFFICE_MAX_FILE_MB', DEFAULT_MAX_FILE_MB))
    if instance is not None and instance.max_file_mb:
        mb = min(mb, int(instance.max_file_mb))
    return mb * 1024 * 1024


def _revision_name(target, ext) -> str:
    org = target.organization_id or 'global'
    return f'office/revisions/{org}/{target.kind}-{target.pk}/{uuid.uuid4().hex}.{ext}'


def _fsync_dir(path: Path):
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class _Spool:
    """Bytes written to a temp file under MEDIA_ROOT/office/tmp, hashed."""

    def __init__(self, data, limit):
        tmp_dir = media_root() / 'office' / 'tmp'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=str(tmp_dir), prefix='rev-', suffix='.part')
        self.path = Path(path)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, 'wb') as out:
                for chunk in _chunks(data):
                    size += len(chunk)
                    if size > limit:
                        raise RevisionRejected(
                            f'The file is larger than the {limit // (1024 * 1024)} MB limit.',
                            code='too_large')
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            self.cleanup()
            raise
        self.sha256 = digest.hexdigest()
        self.size = size

    def cleanup(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _chunks(data):
    if isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data)
        for i in range(0, len(data), CHUNK):
            yield data[i:i + CHUNK]
        return
    if hasattr(data, 'chunks') and callable(data.chunks):   # Django File / UploadedFile
        if hasattr(data, 'seek'):
            try:
                data.seek(0)
            except Exception:
                pass
        yield from data.chunks(CHUNK)
        return
    if hasattr(data, 'read'):
        while True:
            chunk = data.read(CHUNK)
            if not chunk:
                return
            yield chunk
        return
    # any iterable of bytes (e.g. requests' iter_content)
    for chunk in data:
        if chunk:
            yield chunk


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def revisions(target):
    from .models import FileRevision
    return FileRevision.objects.filter(**target.fk_id()).order_by('-revision_number')


def current(target):
    return revisions(target).first()


def open_revision(revision):
    return open(_abs(revision.file.name), 'rb')


def _revision_number(rev):
    if rev is None:
        return 0
    return rev if isinstance(rev, int) else rev.revision_number


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _durable():
    # durable=True refuses to run nested inside another transaction, which is
    # what guarantees "committed" really means committed. Django's TestCase
    # transactions are exempt.
    return transaction.atomic(durable=True)


def _group_base(session, cur):
    """For an editor save without an explicit base: the newest revision saved
    by any session sharing this session's document_key (one co-editing
    group), else the revision the session opened on."""
    from .models import FileRevision
    latest = (FileRevision.objects
              .filter(editor_session__document_key=session.document_key,
                      **{f'{k}_id': v for k, v in _session_target_ids(session).items()})
              .order_by('-revision_number').first())
    if latest is not None:
        return latest.revision_number
    return _revision_number(session.base_revision) if session.base_revision_id else 0


def _session_target_ids(session):
    from .models import TARGET_FIELDS
    return {f: getattr(session, f'{f}_id') for f in TARGET_FIELDS if getattr(session, f'{f}_id')}


def _check_session(session, target):
    from .models import EditSession
    fresh = EditSession.objects.select_for_update().filter(pk=session.pk).first()
    if fresh is None:
        raise SessionRevoked('The edit session no longer exists.')
    if fresh.state not in EditSession.LIVE_STATES:
        raise SessionRevoked(f'The edit session is {fresh.state}.')
    if fresh.expires_at <= timezone.now():
        raise SessionRevoked('The edit session has expired.')
    if fresh.mode != 'edit':
        raise SessionRevoked('The session is read-only.')
    if getattr(fresh, f'{target.kind}_id') != target.pk:
        raise SessionRevoked('The session belongs to a different file.')
    return fresh


def _validate(spool, name, target, user, *, skip_format=False):
    if not skip_format:
        try:
            formats.validate_file(spool.path, name)
        except formats.InvalidOfficeFile as e:
            raise RevisionRejected(str(e), code='invalid')
    verdict = scan_file(spool.path, name=name, target=target, user=user)
    if not verdict.clean:
        raise RevisionRejected(f'Refused by the content scanner: {verdict.detail}'[:400], code='scan',
                               scanner=verdict.scanner)


def _commit(target, spool, *, user, source, expected_base_revision, session, original_name,
            restored_from=None, check_permission=True, skip_format=False):
    from .models import FileRevision

    name = safe_filename(original_name or target.filename)
    ext = formats.extension(name)
    if ext not in formats.ALL_OFFICE and ext not in formats.TEMPLATE:
        raise RevisionRejected(f'.{ext or "?"} files are not handled by Office storage.',
                               code='invalid')
    if source == 'editor_save' and formats.is_read_only_format(name):
        raise RevisionRejected('This format opens read-only; convert it to a new copy to edit.',
                               code='read_only')
    if formats.extension(target.filename) and ext != formats.extension(target.filename):
        raise RevisionRejected('A revision must keep the file\'s format.', code='invalid')

    _validate(spool, name, target, user, skip_format=skip_format)

    final_name = _revision_name(target, ext)
    final = _abs(final_name)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(spool.path, final)
    _fsync_dir(final.parent)
    moved = True
    try:
        with _durable():
            target.lock()
            cur = current(target)
            live_session = _check_session(session, target) if session is not None else None
            if check_permission and user is not None and not target.can_edit(user):
                raise PermissionRevoked('You no longer have permission to edit this file.')

            # Duplicate delivery of a save already stored (e.g. an editor
            # retrying a callback): same bytes, same session, same base.
            if live_session is not None:
                dup = None
                if expected_base_revision is not None:
                    dup = (revisions(target).filter(
                        sha256=spool.sha256, editor_session=live_session,
                        based_on_revision__revision_number=_revision_number(expected_base_revision))
                        .first())
                if dup is None and cur is not None and cur.sha256 == spool.sha256 \
                        and cur.editor_session_id is not None \
                        and cur.editor_session.document_key == live_session.document_key:
                    dup = cur
                if dup is not None:
                    dup.duplicate = True
                    return dup

            if expected_base_revision is None and live_session is not None:
                expected = _group_base(live_session, cur)
            elif expected_base_revision is not None:
                expected = _revision_number(expected_base_revision)
            else:
                expected = None
            cur_no = cur.revision_number if cur else 0
            if expected is not None and expected != cur_no:
                raise StaleRevision(
                    f'This save was based on revision {expected}, but revision {cur_no} '
                    f'is current.', expected=expected, current=cur_no)

            rev = FileRevision.objects.create(
                revision_number=cur_no + 1,
                organization_id=target.organization_id,
                file=final_name, sha256=spool.sha256, size=spool.size,
                mime=formats.mime_for(name), original_name=name,
                created_by=user if (user is not None and user.is_authenticated) else None,
                source=source, editor_session=live_session, based_on_revision=cur,
                restored_from=restored_from,
                **target.fk())
            target.point_at(final_name, spool.size, formats.mime_for(name), rev.created_by)
            moved = False
    finally:
        if moved:
            # Not committed: put the bytes back where the caller can quarantine them.
            try:
                os.replace(final, spool.path)
            except OSError:
                logger.error('Could not move an uncommitted Office revision back to the spool')
    rev.duplicate = False
    return rev


def save_new_revision(target, data, *, user, source, expected_base_revision=None,
                      session=None, original_name=None):
    """Store `data` (bytes, a file object, a Django File or an iterable of
    bytes) as the next revision of `target`. See the module docstring."""
    instance = session.instance if session is not None else None
    spool = _Spool(data, max_bytes(instance))
    try:
        return _commit(target, spool, user=user, source=source,
                       expected_base_revision=expected_base_revision, session=session,
                       original_name=original_name)
    except QUARANTINABLE:
        raise
    except Exception as e:
        logger.exception('Office revision storage failed')
        raise StorageError('The file could not be stored.') from e
    finally:
        spool.cleanup()


def save_or_quarantine(target, data, *, user, source, expected_base_revision=None,
                       session=None, original_name=None) -> SaveOutcome:
    """save_new_revision that keeps refused content as a QuarantinedSave.

    Content over the size limit cannot be kept (it was never fully read) and
    is reported as an error with no quarantine row.
    """
    from . import audit, quarantine
    instance = session.instance if session is not None else None
    try:
        spool = _Spool(data, max_bytes(instance))
    except RevisionRejected as e:
        audit.save_failed(target, user, session=session, reason=e.reason, detail=e.message)
        return SaveOutcome(error=e)
    try:
        try:
            rev = _commit(target, spool, user=user, source=source,
                          expected_base_revision=expected_base_revision, session=session,
                          original_name=original_name)
        except QUARANTINABLE as e:
            error = e
        except Exception as e:
            logger.exception('Office revision storage failed')
            error = StorageError('The file could not be stored.')
        else:
            if not rev.duplicate:
                audit.saved(target, user, rev, session=session)
            return SaveOutcome(revision=rev)
        q = quarantine.keep(target, spool, session=session, user=user, reason=error.reason,
                            detail=error.message, original_name=original_name)
        audit.save_failed(target, user, session=session, reason=error.reason,
                          detail=error.message, quarantined=q)
        return SaveOutcome(quarantined=q, error=error)
    finally:
        spool.cleanup()


def restore(target, revision, user):
    """Make an old revision current again, as a new revision."""
    if getattr(revision, f'{target.kind}_id') != target.pk:
        raise RevisionRejected('That revision belongs to a different file.', code='invalid')
    with open_revision(revision) as fh:
        spool = _Spool(fh, max(max_bytes(), revision.size))
    try:
        return _commit(target, spool, user=user, source='restore', expected_base_revision=None,
                       session=None, original_name=target.filename, restored_from=revision)
    finally:
        spool.cleanup()


def ensure_current(target, user=None):
    """The current revision, creating it from the target's file when needed.

    * No revisions yet and the target has a file: copy it in as revision 1
      (source ``upload``). The original file is left untouched on disk.
    * The target's file was replaced outside Office (its file field no longer
      names the current revision's file): record that file as a new revision.

    Raises RevisionRejected when the existing file is not a valid file of its
    format (it can still be downloaded, just not opened in an editor).
    """
    cur = current(target)
    if not target.has_file():
        return cur
    if cur is not None and cur.file.name == target.file.name:
        return cur
    try:
        src = _abs(target.file.name)
    except ValueError:
        raise RevisionRejected('The stored file is outside the media directory.', code='invalid')
    if not src.is_file():
        raise StorageError('The stored file is missing.')
    with open(src, 'rb') as fh:
        spool = _Spool(fh, max(max_bytes(), src.stat().st_size))
    try:
        return _commit(target, spool, user=None, source='upload',
                       expected_base_revision=cur.revision_number if cur else 0,
                       session=None, original_name=target.filename, check_permission=False)
    except StaleRevision:
        # Another request recorded it first.
        return current(target)
    finally:
        spool.cleanup()


def store_initial(target, data, *, user, source, original_name=None):
    """Revision 1 of a target created a moment ago (blank, copy, template,
    conversion). The caller has already checked the *creation* permission
    (e.g. docs_create), which can differ from edit permission."""
    spool = _Spool(data, max_bytes())
    try:
        return _commit(target, spool, user=user, source=source, expected_base_revision=0,
                       session=None, original_name=original_name, check_permission=False)
    except QUARANTINABLE:
        raise
    except Exception as e:
        logger.exception('Office revision storage failed')
        raise StorageError('The file could not be stored.') from e
    finally:
        spool.cleanup()


def purge_unreferenced_file(name):
    """Delete a stored revision file once no row names it. Revision files are
    under office/; anything else (an original upload) is never deleted here."""
    if not name or not name.startswith('office/'):
        return
    from django.apps import apps
    from .models import FileRevision
    if FileRevision.objects.filter(file=name).exists():
        return
    for label in ('docs.Document', 'files.Attachment', 'psa.TicketAttachment', 'office.OfficeFile'):
        if apps.get_model(label)._base_manager.filter(file=name).exists():
            return
    try:
        _abs(name).unlink()
    except (FileNotFoundError, ValueError):
        pass


def quarantine_expiry():
    from .models import OfficeSettings
    days = OfficeSettings.get().quarantine_retention_days or int(
        getattr(settings, 'OFFICE_QUARANTINE_RETENTION_DAYS', 30))
    return timezone.now() + timedelta(days=days)
