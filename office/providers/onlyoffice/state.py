"""Per-session ONLYOFFICE state, kept in EditSession.provider_state (no secrets).

Keys used:

    oo_key        the document.key this session's editor uses
    oo_gen        generation number inside the core co-editing group
    oo_spent      True once Docs reported the key's final save (status 2):
                  the next open must use a new key
    oo_user       the anonymised editor user id sent as editorConfig.user.id
    oo_users      user ids Docs last reported in the co-editing session
    oo_users_at   when (ISO time)
    oo_last_callback_at / oo_last_status
                  the last callback Docs delivered for this session
    oo_file_fetched_at
                  the last time Docs downloaded the document URL
    oo_last_error {at, status, message}  last save error Docs or clientst0r hit
    oo_last_saved {at, revision, status}
    oo_drain_save {at, outcome}   a drain's force-save request (office.drain)
    oo_forcesave_nochange_at      the editor answered a force-save with
                                  "no changes" (command error 4)

Editor keys. The core gives every session of one co-editing group the same
``document_key`` (see office.sessions). ONLYOFFICE also needs a new key after
every completed save ("Every time the document is edited and saved, the key
must be generated anew"). The editor key is therefore
``<document_key>.<generation>``: stable for the whole co-editing session,
including force-saves (status 6), and moved to the next generation once a
status-2 save marked the current one spent. Allowed characters
``[0-9a-zA-Z._=-]``, 32 + 1 + digits characters, well under 128.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone


def now_iso():
    return timezone.now().isoformat()


def oo_user_id(user) -> str:
    """Stable, anonymised editor user id (no username or e-mail leaves clientst0r)."""
    from vault.secret_fields import hash_token
    return 'u' + hash_token(str(user.pk), 'office.onlyoffice.user')[:23]


def display_name(user) -> str:
    name = (user.get_full_name() or user.username or '').strip()
    return name[:128] or 'User'


def update(session_pk, **changes):
    """Merge `changes` into one session's provider_state, under a row lock."""
    from office.models import EditSession
    with transaction.atomic():
        row = EditSession.objects.select_for_update().filter(pk=session_pk).first()
        if row is None:
            return None
        ps = dict(row.provider_state or {})
        ps.update(changes)
        row.provider_state = ps
        row.save(update_fields=['provider_state'])
        return row


def group(session):
    """Every ONLYOFFICE session (any state) of the same file and co-editing
    group as `session`."""
    from office.models import EditSession
    from office.storage import _session_target_ids
    ids = _session_target_ids(session)
    if not ids:
        return EditSession.objects.none()
    return EditSession.objects.filter(document_key=session.document_key, provider='onlyoffice',
                                      **{f'{k}_id': v for k, v in ids.items()})


def with_key(session, key):
    return [s for s in group(session).select_related('user') if (s.provider_state or {}).get('oo_key') == key]


def editor_key(session) -> str:
    """The document.key for `session`, assigning one on first use. See the
    module docstring. Runs under the target's row lock so a status-2
    callback marking a key spent and an opener picking a key serialise."""
    from office.models import EditSession
    from office.targets import target_of
    ps = session.provider_state or {}
    if ps.get('oo_key') and not ps.get('oo_spent'):
        return ps['oo_key']
    target = target_of(session)
    with transaction.atomic():
        if target is not None:
            target.lock()
        row = EditSession.objects.select_for_update().get(pk=session.pk)
        ps = dict(row.provider_state or {})
        if ps.get('oo_key') and not ps.get('oo_spent'):
            session.provider_state = ps
            return ps['oo_key']
        gens, spent = [], set()
        for other in group(session).exclude(pk=session.pk):
            ops = other.provider_state or {}
            if 'oo_gen' in ops:
                gens.append(int(ops['oo_gen']))
                if ops.get('oo_spent'):
                    spent.add(int(ops['oo_gen']))
        if ps.get('oo_spent') and 'oo_gen' in ps:
            gens.append(int(ps['oo_gen']))
            spent.add(int(ps['oo_gen']))
        gen = max(gens) if gens else 0
        while gen in spent:
            gen += 1
        key = f'{session.document_key}.{gen}'
        ps.update({'oo_key': key, 'oo_gen': gen, 'oo_spent': False,
                   'oo_user': oo_user_id(session.user)})
        row.provider_state = ps
        row.save(update_fields=['provider_state'])
    session.provider_state = ps
    return key


def mark_spent(session, key):
    """Docs is saving `key` for good (status 2): no new open may reuse it."""
    from office.targets import target_of
    target = target_of(session)
    with transaction.atomic():
        if target is not None:
            target.lock()
        for s in with_key(session, key):
            update(s.pk, oo_spent=True)


def last_callback_evidence(instance, limit=200):
    """(iso time, status) of the newest callback Docs delivered for any
    session on `instance`, or (None, None)."""
    from office.models import EditSession
    best = (None, None)
    for ps in (EditSession.objects.filter(instance=instance, provider='onlyoffice')
               .order_by('-last_activity_at').values_list('provider_state', flat=True)[:limit]):
        at = (ps or {}).get('oo_last_callback_at')
        if at and (best[0] is None or at > best[0]):
            best = (at, ps.get('oo_last_status'))
    return best


def last_value(instance, key, limit=200):
    """Newest ISO-time value of provider_state[key] across `instance`'s sessions."""
    from office.models import EditSession
    best = None
    for ps in (EditSession.objects.filter(instance=instance, provider='onlyoffice')
               .order_by('-last_activity_at').values_list('provider_state', flat=True)[:limit]):
        at = (ps or {}).get(key)
        if at and (best is None or at > best):
            best = at
    return best
