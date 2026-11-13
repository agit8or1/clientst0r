"""Edit in Microsoft 365: a working-copy round trip for a clientst0r file.

    can_start(user, target, connection) / edit_connections(user, target)
    start(user, target, connection, *, request=None) -> (M365EditSession, created)
    open_url(user, session, *, request=None) -> webUrl
    check_changes(user, session, *, request=None) -> dict
    save_back(user, session, *, request=None) -> SaveBackResult
    finish(user, session, *, discard=False, request=None) -> str (message)
    revoke(session, reason) / recheck_user(user) / recheck_all()
    run_maintenance(now=None) -> dict          (scheduled task m365_edit_sessions)

How it works:

* **Start.** A user who may edit the clientst0r file chooses *Edit in
  Microsoft 365*. clientst0r checks the stored revision against its SHA-256,
  uploads it as the user (delegated token, ``conflictBehavior=fail``, so
  nothing is ever replaced) into the connection's working-copy location (each
  user's own OneDrive, or one allowed library or folder), records the session
  (file, base revision + checksum, user, organization, Graph drive / item id,
  eTag, cTag) and redirects to the item's ``webUrl`` in a new tab.
* **Save back.** On request only: permission is re-checked, the item is read
  again (same drive, same item id, still inside the allowed location), the
  content is downloaded from the tenant's SharePoint host and stored with
  ``office.storage.save_or_quarantine`` with the base revision as the
  expected base. A newer clientst0r revision in the meantime makes the save
  stale: the content is kept as a quarantined save (version history) and the
  user is told. Content identical to what is already stored is not saved
  again, and a second click while a save-back runs is refused, so a double
  click never creates two revisions.
* **Finish / Discard.** Ends the session. Finish refuses while the Microsoft
  copy has changes clientst0r does not hold yet. The working copy is then
  deleted or kept as the connection's policy says (default: delete).
* **Never:** sharing links, invitations or permission changes (m365docs.http
  refuses those endpoints), automatic imports, a token or download URL in a
  URL, log line, audit entry or this table.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from office import formats, storage
from office.logging_filters import get_logger

from . import access, audit, graph, http, oauth, services

logger = get_logger('office.m365')

EDIT_FORMATS = ('docx', 'xlsx', 'pptx')
EDIT_KINDS = ('document', 'attachment', 'ticket_attachment')
WORKING_COPY_KINDS = ('my_onedrive', 'drive', 'folder')
GRAPH_SIMPLE_UPLOAD_LIMIT = 250 * 1024 * 1024
SAVE_CLAIM_TTL = timedelta(minutes=10)
OBJECT_TYPE = 'integrations.m365editsession'


class EditError(services.ServiceError):
    """A user-facing failure (message is safe to show)."""


def _model():
    from integrations.models import M365EditSession
    return M365EditSession


def target_key(target) -> str:
    return f'{target.kind}:{target.pk}'


def max_bytes() -> int:
    return min(storage.max_bytes(), GRAPH_SIMPLE_UPLOAD_LIMIT)


# ---------------------------------------------------------------------------
# Who may
# ---------------------------------------------------------------------------

def _active(user):
    return bool(user is not None and user.is_authenticated and user.is_active)


def user_may_edit(user, target) -> bool:
    """Edit permission on the file, an Office Open XML format, and for a
    customer (non-MSP) user the explicit ``office_edit_in_m365`` permission."""
    if not _active(user) or target is None or target.kind not in EDIT_KINDS:
        return False
    if target.organization_id is None or target.extension not in EDIT_FORMATS:
        return False
    if not target.can_edit(user):
        return False
    from psa.visibility import is_msp_staff
    if is_msp_staff(user):
        return True
    from accounts.permission_utils import has_perm_for_org
    return bool(has_perm_for_org(user, target.organization_id, 'office_edit_in_m365'))


def connection_ready(connection) -> bool:
    loc = connection.docs_edit_location if connection.docs_edit_location_id else None
    return bool(access.writes_allowed(connection) and connection.docs_edit_enabled
                and loc is not None and loc.kind in WORKING_COPY_KINDS
                and loc.connection_id == connection.pk
                and loc.organization_id == connection.organization_id)


def _is_staff(user):
    from psa.visibility import is_msp_staff
    return is_msp_staff(user)


def connection_allowed_for(connection, target, user) -> bool:
    """Tenant isolation. Customer data never goes to another customer's tenant:

    * a customer's own connection is used only for that customer's files;
    * the platform-owned connection (the MSP's own tenant) only by MSP staff,
      for files they may edit at their customer;
    * a connection owned by any other customer is never used.
    """
    if connection.organization_id is None:
        return _is_staff(user)
    return connection.organization_id == target.organization_id


def owner_label(connection) -> str:
    return 'Platform (MSP)' if connection.organization_id is None else connection.organization.name


def edit_connections(user, target):
    """Connections through which `user` may edit `target` in Microsoft 365,
    the preferred one first.

    MSP staff: the file's customer's own connection and the platform
    connection. When both qualify, the customer connection's
    ``docs_edit_staff_tenant`` decides (default: platform). Customer users:
    their own customer's connection only."""
    if not user_may_edit(user, target):
        return []
    from integrations.models import M365Connection
    staff = _is_staff(user)
    q = Q(organization_id=target.organization_id)
    if staff:
        q |= Q(organization__isnull=True)
    rows = (M365Connection.objects.filter(q, is_active=True, docs_enabled=True,
                                          docs_access='readwrite', docs_edit_enabled=True)
            .select_related('docs_edit_location', 'organization').order_by('pk'))
    conns = [c for c in rows if connection_ready(c) and access.can_use(user, c)
             and connection_allowed_for(c, target, user)]
    own = [c for c in conns if c.organization_id is not None]
    platform = [c for c in conns if c.organization_id is None]
    if not staff:
        return own
    prefer_customer = any(c.docs_edit_staff_tenant == 'customer' for c in own)
    return own + platform if prefer_customer else platform + own


def can_start(user, target, connection) -> bool:
    return any(c.pk == connection.pk for c in edit_connections(user, target))


def still_allowed(session) -> bool:
    from office.targets import target_of
    target = target_of(session)
    if target is None:
        return False
    try:
        target.refresh()
    except Exception:
        return False
    conn = session.connection
    return (user_may_edit(session.user, target)
            and connection_allowed_for(conn, target, session.user)
            and access.can_use(session.user, conn) and access.writes_allowed(conn)
            and conn.docs_edit_enabled)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def live_sessions():
    return _model().objects.filter(state__in=_model().LIVE_STATES)


def live_for_target(target):
    return live_sessions().filter(target_key=target_key(target)).select_related('user')


def session_for(user, session_id):
    """The user's own session (Http404 for anyone else's or an unknown id)."""
    from django.http import Http404
    s = (_model().objects.select_related('connection', 'location', 'user', 'base_revision',
                                         'last_saved_revision')
         .filter(pk=session_id, user=user).first())
    if s is None:
        raise Http404('Not found')
    return s


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def _log(event, session, *, user=None, request=None, description='', extra=None, success=True):
    audit.log(event, user=user, organization_id=session.organization_id, request=request,
              object_type=OBJECT_TYPE, object_id=None, object_repr=session.target_label,
              description=description, success=success,
              extra={'session': str(session.pk), 'connection': session.connection_id,
                     'connection_name': session.connection.name,
                     'connection_owner': owner_label(session.connection),
                     'tenant_id': session.connection.tenant_id,
                     'target': session.target_key, 'drive_id': session.drive_id,
                     'item_id': session.item_id, **(extra or {})})


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def _working_copy_name(target, attempt):
    ext = target.extension
    stem = target.filename[:-(len(ext) + 1)] if ext else target.filename
    stem = storage.safe_filename(stem, fallback='Document')
    for ch in '"*:<>?/\\|#%':
        stem = stem.replace(ch, '')
    stem = stem.strip().strip('.').lstrip('~$') or 'Document'
    tag = 'clientst0r edit' if attempt == 0 else f'clientst0r edit {secrets.token_hex(3)}'
    return graph.valid_name(f'{stem[:180]} ({tag}).{ext}')


def _working_folder(client, connection, loc):
    drive_id, root_id = access.location_root(client, loc)
    _loc, root = access.locate_folder(client, connection, drive_id, root_id or 'root',
                                      location=loc)
    folder = root
    name = (connection.docs_edit_folder_name or '').strip()
    if name:
        try:
            name = graph.valid_name(name)
        except ValueError:
            raise EditError('The working-copy folder name set by the administrator cannot be '
                            'used in OneDrive / SharePoint.')
        folder = client.ensure_folder(drive_id, root.get('id') or root_id, name)
        access.locate_folder(client, connection, drive_id, folder['id'], location=loc)
    return drive_id, folder


def start(user, target, connection, *, request=None):
    """Upload a working copy and open a session, or return the user's live
    session on this file. Raises PermissionDenied, EditError, GraphError,
    oauth.NotConnected, access.NotPermitted."""
    Session = _model()
    if not connection_allowed_for(connection, target, user) or \
            not can_start(user, target, connection):
        raise PermissionDenied('Not allowed')
    rev = storage.ensure_current(target, user)
    if rev is None:
        raise EditError('The file has no content yet.')
    if rev.size > max_bytes():
        raise EditError(f'The file is larger than the {max_bytes() // (1024 * 1024)} MB limit '
                        'for editing in Microsoft 365.')
    with storage.open_revision(rev) as fh:
        data = fh.read(max_bytes() + 1)
    if len(data) > max_bytes() or hashlib.sha256(data).hexdigest() != rev.sha256:
        raise EditError('The stored file does not match its recorded checksum, so it was not '
                        'sent to Microsoft 365.')

    with transaction.atomic():
        target.lock()
        existing = live_sessions().filter(user=user, target_key=target_key(target)).first()
        if existing is not None:
            return existing, False
        session = Session.objects.create(
            organization_id=target.organization_id, connection=connection,
            location=connection.docs_edit_location, user=user, target_key=target_key(target),
            target_label=target.label(), base_revision=rev,
            base_revision_number=rev.revision_number, base_sha256=rev.sha256,
            state='starting', **target.fk())

    meta = None
    client = None
    try:
        client = services.client_for(user, connection)
        services.learn_sharepoint_host(client, connection)
        connection.refresh_from_db(fields=['docs_sharepoint_host'])
        drive_id, folder = _working_folder(client, connection, connection.docs_edit_location)
        for attempt in range(3):
            try:
                meta = client.upload_new(drive_id, folder['id'], _working_copy_name(target, attempt),
                                         data, formats.mime_for(target.filename))
                break
            except graph.GraphError as e:
                if e.status != 409 or attempt == 2:
                    raise
        if str((meta.get('parentReference') or {}).get('driveId') or drive_id) != drive_id:
            raise EditError('Microsoft 365 stored the working copy somewhere unexpected.')
        if meta.get('size') is not None and int(meta['size']) != len(data):
            raise EditError('Microsoft 365 reported a different size for the uploaded copy.')
        web_url = services.check_web_url(connection, str(meta.get('webUrl') or ''))
    except Exception as exc:
        if meta and meta.get('id') and client is not None:
            try:
                client.delete_item(drive_id, graph.valid_id(meta['id']))
            except Exception:
                logger.warning('Could not remove a working copy after a failed start')
        Session.objects.filter(pk=session.pk).update(
            state='failed', closed_at=timezone.now(),
            end_reason=f'start failed: {type(exc).__name__}'[:255])
        session.refresh_from_db()
        _log('m365_edit_start', session, user=user, request=request, success=False,
             description=f'Edit in Microsoft 365 of {target.filename} could not start')
        raise

    Session.objects.filter(pk=session.pk).update(
        state='open', drive_id=drive_id, folder_id=str(folder.get('id', ''))[:300],
        item_id=str(meta['id'])[:300], item_name=str(meta.get('name', ''))[:500],
        web_url=web_url[:2000], uploaded_etag=str(meta.get('eTag', ''))[:300],
        synced_ctag=str(meta.get('cTag', ''))[:300], synced_sha256=rev.sha256,
        working_copy='present', last_activity_at=timezone.now())
    session.refresh_from_db()
    _log('m365_edit_start', session, user=user, request=request,
         description=f'Started editing {target.filename} (revision {rev.revision_number}) in '
                     f'Microsoft 365: working copy {session.item_name}',
         extra={'revision': rev.revision_number, 'sha256': rev.sha256,
                'location': session.location_id, 'etag': session.uploaded_etag,
                'conflict_behavior': 'fail'})
    return session, True


# ---------------------------------------------------------------------------
# Session actions (owner only)
# ---------------------------------------------------------------------------

def _require_open(session, user):
    if session.user_id != getattr(user, 'pk', None):
        raise PermissionDenied('Not allowed')
    if session.state == 'starting':
        raise EditError('The working copy is still being prepared. Try again in a moment.')
    if session.state != 'open':
        raise EditError('This Microsoft 365 edit session has ended.')


def _target_checked(session):
    """The session's file, with the user's permission re-checked; a lost
    permission revokes the session."""
    from office.targets import target_of
    if not still_allowed(session):
        revoke(session, 'permission lost' if target_of(session) else 'file deleted')
        raise PermissionDenied('You may no longer edit this file in Microsoft 365. The edit '
                               'session was ended.')
    return target_of(session)


def _locate_item(client, session, select=None):
    loc = session.location if session.location_id else None
    _loc, meta = access.locate(client, session.connection, session.drive_id, session.item_id,
                               location=loc)
    if meta.get('id') != session.item_id or 'file' not in meta:
        raise EditError('The Microsoft 365 item is not the working copy of this session.')
    return meta


def open_url(user, session, *, request=None):
    _require_open(session, user)
    _target_checked(session)
    client = services.client_for(user, session.connection)
    meta = _locate_item(client, session)
    url = services.check_web_url(session.connection, str(meta.get('webUrl') or ''))
    _model().objects.filter(pk=session.pk).update(web_url=url[:2000],
                                                  last_activity_at=timezone.now())
    _log('m365_edit_open', session, user=user, request=request,
         description=f'Opened the Microsoft 365 working copy of {session.target_label}')
    return url


def check_changes(user, session, *, request=None):
    """Whether the Microsoft copy's content changed since clientst0r last held
    it (cTag). Imports nothing."""
    _require_open(session, user)
    _target_checked(session)
    client = services.client_for(user, session.connection)
    _locate_item(client, session)
    meta = client.item_state(session.drive_id, session.item_id)
    if meta.get('id') != session.item_id:
        raise EditError('The Microsoft 365 item is not the working copy of this session.')
    ctag = str(meta.get('cTag', ''))[:300]
    changed = bool(ctag) and ctag != session.synced_ctag
    by = (((meta.get('lastModifiedBy') or {}).get('user') or {}).get('displayName') or '')[:120]
    now = timezone.now()
    _model().objects.filter(pk=session.pk).update(remote_ctag=ctag, remote_changed=changed,
                                                  remote_checked_at=now, last_activity_at=now)
    session.refresh_from_db()
    return {'changed': changed, 'modified_at': meta.get('lastModifiedDateTime'),
            'modified_by': by, 'size': meta.get('size')}


@dataclass
class SaveBackResult:
    status: str                   # saved / duplicate / unchanged / conflict / rejected
    message: str
    revision: object = None
    quarantined: object = None


def _claim(session):
    now = timezone.now()
    return _model().objects.filter(pk=session.pk, state='open').filter(
        Q(saving_since__isnull=True) | Q(saving_since__lt=now - SAVE_CLAIM_TTL)
    ).update(saving_since=now)


def save_back(user, session, *, request=None):
    """Download the working copy and store it as a new revision (see the
    module docstring). Raises PermissionDenied / EditError / Graph errors."""
    _require_open(session, user)
    if not _claim(session):
        session.refresh_from_db()
        if session.state != 'open':
            raise EditError('This Microsoft 365 edit session has ended.')
        raise EditError('A save back to clientst0r is already running for this session.')
    try:
        session.refresh_from_db()
        return _save_back(user, session, request)
    finally:
        _model().objects.filter(pk=session.pk).update(saving_since=None)


def _save_back(user, session, request):
    target = _target_checked(session)
    conn = session.connection
    client = services.client_for(user, conn)
    _locate_item(client, session)
    try:
        meta, data = client.download(session.drive_id, session.item_id, max_bytes(),
                                     http.sharepoint_hosts(conn))
    except (ValueError, http.RefusedURL) as e:
        raise EditError(str(e))
    if meta.get('id') != session.item_id or \
            ((meta.get('parentReference') or {}).get('driveId') or session.drive_id) != session.drive_id:
        raise EditError('The Microsoft 365 item is not the working copy of this session.')
    sha = hashlib.sha256(data).hexdigest()
    ctag = str(meta.get('cTag', ''))[:300]
    etag = str(meta.get('eTag', ''))[:300]
    now = timezone.now()
    Session = _model()

    if session.last_saved_sha256 and sha == session.last_saved_sha256:
        Session.objects.filter(pk=session.pk).update(synced_ctag=ctag, last_activity_at=now,
                                                     remote_changed=False)
        rev = session.last_saved_revision
        return SaveBackResult('duplicate', 'Already saved: clientst0r has this content as '
                              f'revision {rev.revision_number if rev else "?"}.', revision=rev)
    if not session.last_saved_sha256 and sha == session.base_sha256:
        Session.objects.filter(pk=session.pk).update(synced_ctag=ctag, last_activity_at=now,
                                                     remote_changed=False)
        return SaveBackResult('unchanged', 'No changes: the Microsoft 365 copy has the same '
                                           'content as the clientst0r file.')

    expected = (session.last_saved_revision.revision_number if session.last_saved_revision_id
                else session.base_revision_number)
    outcome = storage.save_or_quarantine(target, data, user=user, source='import',
                                         expected_base_revision=expected,
                                         original_name=target.filename)
    extra = {'sha256': sha, 'etag': etag, 'expected_base': expected}
    if outcome.ok:
        rev = outcome.revision
        Session.objects.filter(pk=session.pk).update(
            last_saved_revision=rev, last_saved_sha256=sha, last_saved_at=now,
            save_count=session.save_count + 1, synced_ctag=ctag, synced_sha256=sha,
            remote_changed=False, last_activity_at=now)
        _log('m365_edit_save', session, user=user, request=request,
             description=f'Saved the Microsoft 365 working copy of {target.filename} back as '
                         f'revision {rev.revision_number}',
             extra={**extra, 'revision': rev.revision_number})
        return SaveBackResult('saved', f'Saved back to clientst0r as revision '
                                       f'{rev.revision_number}.', revision=rev)
    err = outcome.error
    q = outcome.quarantined
    if q is not None:
        Session.objects.filter(pk=session.pk).update(last_conflict=q, synced_ctag=ctag,
                                                     synced_sha256=sha, last_activity_at=now)
    reason = getattr(err, 'reason', 'storage_error')
    _log('m365_edit_save', session, user=user, request=request, success=False,
         description=f'Save back of {target.filename} from Microsoft 365 not accepted ({reason})'
                     + ('; kept in quarantine' if q is not None else ''),
         extra={**extra, 'reason': reason, 'quarantine_id': q.pk if q else None})
    if reason == 'stale':
        return SaveBackResult(
            'conflict', 'The clientst0r file changed while you were editing (revision '
                        f'{getattr(err, "current", "?")} is now current, your copy was based on '
                        f'revision {expected}). Your Microsoft 365 version was kept as an '
                        'unaccepted save in the version history, where it can be downloaded or '
                        'restored; nothing was overwritten.', quarantined=q)
    return SaveBackResult('rejected', 'The Microsoft 365 copy was not accepted: '
                          f'{getattr(err, "message", "") or reason}'
                          + (' It was kept in the version history.' if q is not None else ''),
                          quarantined=q)


# ---------------------------------------------------------------------------
# Ending sessions and the working copy
# ---------------------------------------------------------------------------

def _delete_copy(client, session, *, if_match=''):
    """Delete the working copy. Returns the new working_copy state."""
    if not session.item_id:
        return 'none'
    try:
        client.delete_item(session.drive_id, session.item_id, if_match=if_match)
        return 'deleted'
    except graph.GraphError as e:
        if e.status == 412:
            raise EditError('The Microsoft 365 copy changed a moment ago, so it was not '
                            'deleted. Check for changes and try again.')
        logger.warning('Working copy delete refused by Microsoft 365 (%s)', e.status)
        return 'delete_failed'


def _end(session, state, reason, working_copy):
    return _model().objects.filter(pk=session.pk, state__in=_model().LIVE_STATES).update(
        state=state, closed_at=timezone.now(), end_reason=reason[:255],
        working_copy=working_copy, saving_since=None)


def finish(user, session, *, discard=False, request=None):
    if session.user_id != getattr(user, 'pk', None):
        raise PermissionDenied('Not allowed')
    if not session.is_live:
        raise EditError('This Microsoft 365 edit session has ended.')
    policy = session.connection.docs_edit_cleanup
    copy_state = session.working_copy
    try:
        client = graph.GraphClient(services.grant_for(user, session.connection))
    except oauth.NotConnected:
        client = None
    if not discard:
        if session.state != 'open':
            raise EditError('The working copy is still being prepared.')
        if client is None:
            raise oauth.NotConnected('Connect your Microsoft 365 documents first, or discard.')
        state = client.item_state(session.drive_id, session.item_id)
        ctag = str(state.get('cTag', ''))
        if ctag and ctag != session.synced_ctag:
            raise EditError('The Microsoft 365 copy has changes that are not in clientst0r yet. '
                            'Save back to clientst0r first, or discard the session.')
        if_match = str(state.get('eTag', ''))
    else:
        if_match = ''
    if session.working_copy == 'present':
        if policy == 'keep':
            copy_state = 'kept'
        elif client is None:
            copy_state = 'delete_pending'
        else:
            copy_state = _delete_copy(client, session, if_match=if_match)
    state_name = 'discarded' if discard else 'closed'
    if not _end(session, state_name, 'discarded by user' if discard else 'finished by user',
                copy_state):
        raise EditError('This Microsoft 365 edit session has ended.')
    session.refresh_from_db()
    _log('m365_edit_discard' if discard else 'm365_edit_finish', session, user=user,
         request=request,
         description=(f'{"Discarded" if discard else "Finished"} editing {session.target_label} '
                      f'in Microsoft 365; working copy {session.get_working_copy_display().lower()}'),
         extra={'working_copy': copy_state, 'policy': policy, 'saves': session.save_count})
    return {
        'deleted': 'The working copy was deleted from Microsoft 365 (it stays in the recycle '
                   'bin there for the retention Microsoft applies).',
        'kept': 'The working copy was left in Microsoft 365, as the administrator set. It is '
                'no longer connected to clientst0r.',
        'delete_pending': 'The working copy will be deleted once you connect your Microsoft '
                          '365 documents again.',
        'delete_failed': 'Microsoft 365 refused to delete the working copy; delete it there '
                         'yourself.',
        'none': '',
    }.get(copy_state, '')


def revoke(session, reason):
    """End a live session without contacting Microsoft (safe in signals). A
    working copy that policy says to delete is deleted by the cleanup task."""
    copy_state = session.working_copy
    if copy_state == 'present':
        copy_state = 'kept' if session.connection.docs_edit_cleanup == 'keep' else 'delete_pending'
    if not _end(session, 'revoked', reason, copy_state):
        return False
    session.refresh_from_db()
    _log('m365_edit_revoked', session, user=None,
         description=f'Ended the Microsoft 365 edit session of {session.user.username} on '
                     f'{session.target_label}: {reason}'[:2000],
         extra={'session_user': session.user_id, 'working_copy': copy_state})
    return True


def recheck_user(user, reason='permissions changed'):
    n = 0
    uid = getattr(user, 'pk', user)
    for s in live_sessions().filter(user_id=uid).select_related('user', 'connection'):
        if not s.user.is_active or not still_allowed(s):
            n += bool(revoke(s, reason))
    return n


def recheck_all(reason='role changed'):
    n = 0
    for s in live_sessions().select_related('user', 'connection'):
        if not s.user.is_active or not still_allowed(s):
            n += bool(revoke(s, reason))
    return n


def revoke_for_target(target, reason):
    n = 0
    for s in live_for_target(target).select_related('connection'):
        n += bool(revoke(s, reason))
    return n


# ---------------------------------------------------------------------------
# Scheduled task: reminders and cleanup (never imports)
# ---------------------------------------------------------------------------

def _remind(session, now):
    from core.mailer import default_from_email, get_smtp_connection, send_to_recipients
    from core.models import SystemSetting
    _model().objects.filter(pk=session.pk).update(reminded_at=now)
    email = (session.user.email or '').strip()
    _log('m365_edit_reminder', session, user=None,
         description=f'Reminded {session.user.username} of the open Microsoft 365 edit session '
                     f'on {session.target_label}')
    if not email:
        return False
    try:
        system = SystemSetting.get_settings()
        smtp = get_smtp_connection(system)
        if smtp is None:
            return False
        body = (f'You are still editing "{session.target_label}" in Microsoft 365 '
                f'(started {session.opened_at:%Y-%m-%d %H:%M} UTC).\n\n'
                'clientst0r only receives your changes when you choose "Save back to '
                'clientst0r" on the file page. When you are done, save back and choose '
                '"Finish", or "Discard" to drop the working copy.\n')
        return bool(send_to_recipients(smtp, default_from_email(system), [email],
                                       'Open Microsoft 365 edit session', body))
    except Exception:
        logger.warning('Edit-session reminder e-mail failed')
        return False


def run_maintenance(now=None) -> dict:
    now = now or timezone.now()
    out = {'revoked': recheck_all('permission lost'), 'copies_deleted': 0,
           'ended_unchanged': 0, 'reminded': 0, 'errors': 0}
    Session = _model()
    # Starts that never finished (the request died mid-upload).
    Session.objects.filter(state='starting', opened_at__lt=now - timedelta(hours=1)).update(
        state='failed', closed_at=now, end_reason='start did not complete')
    # Working copies policy says to delete, for sessions that ended without it.
    for s in Session.objects.filter(working_copy='delete_pending').select_related(
            'connection', 'user')[:200]:
        try:
            client = graph.GraphClient(services.grant_for(s.user, s.connection))
            state = _delete_copy(client, s)
        except oauth.NotConnected:
            state = 'delete_pending' if s.closed_at and s.closed_at > now - timedelta(days=30) \
                else 'delete_failed'
        except Exception:
            out['errors'] += 1
            continue
        Session.objects.filter(pk=s.pk).update(working_copy=state)
        out['copies_deleted'] += state == 'deleted'
    # Idle sessions: end them when Microsoft holds nothing new, else remind.
    for s in Session.objects.filter(state='open').select_related('connection', 'user')[:500]:
        hours = s.connection.docs_edit_stale_hours or 72
        if s.last_activity_at > now - timedelta(hours=hours):
            continue
        changed = None
        client = None
        try:
            client = graph.GraphClient(services.grant_for(s.user, s.connection))
            meta = client.item_state(s.drive_id, s.item_id)
            ctag = str(meta.get('cTag', ''))
            changed = bool(ctag) and ctag != s.synced_ctag
            if not changed:
                copy_state = s.working_copy
                if copy_state == 'present':
                    copy_state = ('kept' if s.connection.docs_edit_cleanup == 'keep'
                                  else _delete_copy(client, s, if_match=str(meta.get('eTag', ''))))
                if _end(s, 'ended', 'idle with no changes in Microsoft 365', copy_state):
                    s.refresh_from_db()
                    _log('m365_edit_ended', s, user=None,
                         description=f'Ended the idle Microsoft 365 edit session of '
                                     f'{s.user.username} on {s.target_label} (no changes)',
                         extra={'working_copy': copy_state})
                    out['ended_unchanged'] += 1
                continue
        except oauth.NotConnected:
            pass
        except Exception:
            out['errors'] += 1
        if s.reminded_at is None or s.reminded_at < now - timedelta(hours=hours):
            _remind(s, now)
            out['reminded'] += 1
    return out
