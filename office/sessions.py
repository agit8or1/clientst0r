"""Edit sessions: one user, one file, one editor instance, one mode.

    open_session(target, user, *, mode, instance=None, request=None) -> EditSession
    get_live(session_id, *, user=None) -> EditSession          (Http404 otherwise)
    renew(session) -> EditSession                              (SessionRevoked if over)
    close(session, *, reason='', pending_final_save=False)
    revoke(session, reason)
    revoke_for_target(target, reason)
    recheck_user(user, reason) -> int                          (sessions revoked)
    expected_base(session) -> int

Document keys. Everyone editing the same revision of the same file through
the same instance shares one ``document_key`` (that is how the editor knows to
put them in one co-editing session). The group keeps its key while it stays
open, including across force-saves it makes itself; once a revision is
written that the group did not make, or the group has closed, the next
session gets a new key (ONLYOFFICE requires a new key after every completed
save). Keys use only [A-Za-z0-9_-], within ONLYOFFICE's 128-character
[0-9a-zA-Z._=-] limit. A key is a random 32-character url-safe string,
so it says nothing about the file or the organization, and it is never reused
for another file.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .logging_filters import get_logger

logger = get_logger('office.sessions')


def _settings():
    from .models import OfficeSettings
    return OfficeSettings.get()


def new_document_key() -> str:
    return secrets.token_urlsafe(24)   # 32 chars of [A-Za-z0-9_-]


def shared_key(target, revision, instance):
    """The key of the live co-editing group whose document state is
    `revision`, if any: a group opened on `revision`, or one whose own saves
    (force-saves while still open) produced it. Joining such a group keeps
    everyone in one editing session; any revision written outside the group
    (restore, upload, another group) gives the next opener a new key."""
    from .models import EditSession
    from .storage import _group_base
    if revision is None:
        return None
    live = (EditSession.objects
            .filter(state__in=EditSession.LIVE_STATES, expires_at__gt=timezone.now(),
                    instance=instance, **target.fk_id())
            .select_related('base_revision').order_by('opened_at'))
    seen = set()
    for s in live:
        if s.document_key in seen:
            continue
        seen.add(s.document_key)
        if _group_base(s, None) == revision.revision_number:
            return s.document_key
    return None


def open_session(target, user, *, mode, instance=None, request=None, maintenance=False):
    """Create a session after checking permission, policy and the file.

    Raises PermissionDenied (no right for `mode`), NotConfigured (no usable
    instance), or office.storage errors when the stored file is unusable.

    ``maintenance=True`` skips only the instance's ``enabled`` switch, for
    the managed service's own verification round trip on a disposable file
    while the editor is still closed to users. Permissions are checked as
    always.
    """
    from . import audit, policy, storage
    from .models import EditSession
    from .providers import NotConfigured

    if mode not in ('view', 'edit'):
        raise ValueError('mode must be view or edit')
    if not target.can_view(user) or (mode == 'edit' and not target.can_edit(user)):
        raise PermissionDenied('Not allowed')
    if instance is None:
        instance = policy.instance_for(target.organization_id)
    if instance is None:
        raise NotConfigured('No Office editor is configured for this organization.')
    if not instance.available_to(target.organization_id) or not (instance.enabled or maintenance):
        raise NotConfigured('That editor is not available to this organization.')

    revision = storage.ensure_current(target, user)
    if revision is None:
        raise storage.StorageError('The file has no content yet.')

    cfg = _settings()
    now = timezone.now()
    with transaction.atomic():
        target.lock()
        key = shared_key(target, revision, instance) or new_document_key()
        max_exp = now + timedelta(hours=cfg.session_max_hours or 24)
        session = EditSession.objects.create(
            organization_id=target.organization_id, target_label=target.label(),
            user=user, instance=instance, provider=instance.provider, mode=mode,
            document_key=key, base_revision=revision,
            expires_at=min(now + timedelta(minutes=cfg.session_ttl_minutes or 240), max_exp),
            max_expires_at=max_exp, **target.fk())
    audit.log('session_start', user=user, target=target, request=request,
              description=f'Opened {target.filename} in {instance.name} ({mode})',
              extra={'session': str(session.pk), 'mode': mode, 'instance': instance.pk,
                     'revision': revision.revision_number})
    return session


def get_live(session_id, *, user=None):
    from .models import EditSession
    session = (EditSession.objects.select_related('instance', 'user', 'base_revision')
               .filter(pk=session_id).first())
    if session is None or (user is not None and session.user_id != user.pk):
        raise Http404('Not found')
    if not session.is_live:
        raise Http404('Not found')
    return session


def renew(session):
    from .storage import SessionRevoked
    from .models import EditSession
    with transaction.atomic():
        fresh = EditSession.objects.select_for_update().get(pk=session.pk)
        now = timezone.now()
        if fresh.state not in EditSession.LIVE_STATES or fresh.expires_at <= now:
            raise SessionRevoked('The edit session is over.')
        if fresh.max_expires_at <= now:
            raise SessionRevoked('The edit session reached its maximum length.')
        cfg = _settings()
        fresh.expires_at = min(now + timedelta(minutes=cfg.session_ttl_minutes or 240),
                               fresh.max_expires_at)
        fresh.last_activity_at = now
        fresh.save(update_fields=['expires_at', 'last_activity_at'])
    return fresh


def touch(session):
    from .models import EditSession
    EditSession.objects.filter(pk=session.pk).update(last_activity_at=timezone.now())


def expected_base(session) -> int:
    """Revision number an editor save on `session` is expected to build on
    (the newest revision this co-editing group saved, else the base)."""
    from .storage import _group_base
    return _group_base(session, None)


def _target(session):
    from .targets import target_of
    return target_of(session)


def close(session, *, reason='', pending_final_save=False, request=None):
    """End a session normally. ``pending_final_save=True`` moves it to
    ``closing`` instead, so the editor's final save callback is still accepted
    until the session expires; the provider then calls close() again."""
    from . import audit
    from .models import EditSession
    from .providers import get_provider, NotConfigured
    state = 'closing' if pending_final_save else 'closed'
    updated = EditSession.objects.filter(pk=session.pk, state__in=EditSession.LIVE_STATES).update(
        state=state, closed_at=None if pending_final_save else timezone.now(),
        end_reason=(reason or '')[:255])
    if not updated:
        return False
    if state == 'closed':
        from .tokens import revoke_session_tokens
        revoke_session_tokens(session)
        target = _target(session)
        audit.log('session_end', user=session.user, target=target, request=request,
                  organization_id=session.organization_id,
                  description=f'Closed Office session on {session.target_label}',
                  extra={'session': str(session.pk), 'reason': reason[:100]})

        def notify():
            try:
                get_provider(session.provider).on_session_closed(session)
            except NotConfigured:
                pass
            except Exception:
                logger.exception('Provider on_session_closed failed')
        transaction.on_commit(notify)
    return True


def revoke(session, reason):
    """Revoke a live session and its tokens; later saves on it are quarantined."""
    from . import audit
    from .models import EditSession
    from .providers import get_provider, NotConfigured
    from .tokens import revoke_session_tokens
    updated = EditSession.objects.filter(pk=session.pk, state__in=EditSession.LIVE_STATES).update(
        state='revoked', closed_at=timezone.now(), end_reason=(reason or '')[:255])
    if not updated:
        return False
    revoke_session_tokens(session)
    audit.log('session_revoked', user=None, target=_target(session),
              organization_id=session.organization_id,
              description=f'Revoked Office session of {session.user.username} on '
                          f'{session.target_label}: {reason}'[:2000],
              extra={'session': str(session.pk), 'session_user': session.user_id})

    def notify():
        try:
            get_provider(session.provider).on_session_revoked(session)
        except NotConfigured:
            pass
        except Exception:
            logger.exception('Provider on_session_revoked failed')
    transaction.on_commit(notify)
    return True


def live_sessions():
    from .models import EditSession
    return EditSession.objects.filter(state__in=EditSession.LIVE_STATES,
                                      expires_at__gt=timezone.now())


def revoke_for_target(target, reason):
    n = 0
    for s in live_sessions().filter(**target.fk_id()).select_related('user'):
        n += bool(revoke(s, reason))
    return n


def still_allowed(session) -> bool:
    target = _target(session)
    if target is None:
        return False
    try:
        target.refresh()
    except Exception:
        return False
    user = session.user
    if not target.can_view(user):
        return False
    return session.mode != 'edit' or target.can_edit(user)


def recheck_user(user, reason='permissions changed'):
    """Revoke every live session of `user` that their current rights no
    longer cover. Called from the membership / role / user signals."""
    n = 0
    for s in live_sessions().filter(user_id=getattr(user, 'pk', user)).select_related('user'):
        if not s.user.is_active or not still_allowed(s):
            n += bool(revoke(s, reason))
    return n


def recheck_all(reason='role changed'):
    n = 0
    for s in live_sessions().select_related('user'):
        if not s.user.is_active or not still_allowed(s):
            n += bool(revoke(s, reason))
    return n
