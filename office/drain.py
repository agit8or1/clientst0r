"""Draining an editor instance before maintenance (stop, restart, update,
rollback, uninstall, provider switch).

Used by ``manage.py office_sessions --drain`` and by the managed-service
jobs (office.managed.jobs). Steps:

    block(instance)              new sessions refused (instance disabled)
    request_saves(instance)      ask the provider to save every open edit
                                 group now (EditorProvider.force_save)
    verify(instance, since)      DrainState: is everything durable?

``verify`` never treats an unknown count as zero:

* every session in a live state counts, *including* ones whose expiry has
  passed (an expired session is only "probably" closed: its browser tab may
  still hold unsaved changes in the editor);
* for ONLYOFFICE, a session group counts as safe only when (a) it is closed,
  or (b) a save requested at or after ``since`` was stored (or the editor
  answered "no changes"), or (c) the editor's command service says it no
  longer knows the group's key (``info`` -> error 1) — an expired session
  whose key the editor has forgotten is then closed here;
* the editor's ``getForgottenList`` must be empty: a non-empty list means
  documents whose final save never reached clientst0r;
* anything the editor could not answer makes the result *unknown*, and the
  caller postpones.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .logging_filters import get_logger

log = get_logger('office.drain')


@dataclass
class DrainState:
    drained: bool = False
    unknown: bool = False
    pending: list = field(default_factory=list)      # human-readable lines
    detail: str = ''


def live_any_expiry(instance):
    """Sessions on `instance` in a live state, expired or not."""
    from .models import EditSession
    return (EditSession.objects.filter(instance=instance, state__in=EditSession.LIVE_STATES)
            .select_related('user', 'instance').order_by('opened_at'))


def block(instance):
    """Refuse new sessions on `instance`. Returns whether it was enabled."""
    from .models import EditorInstance
    was = EditorInstance.objects.filter(pk=instance.pk).values_list('enabled', flat=True).first()
    EditorInstance.objects.filter(pk=instance.pk).update(enabled=False)
    return bool(was)


def unblock(instance):
    from .models import EditorInstance
    EditorInstance.objects.filter(pk=instance.pk).update(enabled=True)


def request_saves(instance):
    """Ask the provider to save each open edit group once. Returns
    [(session, outcome)] with outcome 'requested' | 'refused' |
    'unsupported' | 'error' | 'unconfigured'."""
    from .providers import NotConfigured, NotSupported, get_provider
    from .providers.onlyoffice import state as oo_state
    out = []
    try:
        provider = get_provider(instance.provider)
    except NotConfigured:
        return [(s, 'unconfigured') for s in live_any_expiry(instance) if s.mode == 'edit']
    asked = set()
    for s in live_any_expiry(instance):
        if s.mode != 'edit' or s.document_key in asked:
            continue
        asked.add(s.document_key)
        try:
            ok = provider.force_save(s)
            outcome = 'requested' if ok else 'refused'
        except NotSupported:
            outcome = 'unsupported'
        except NotConfigured:
            outcome = 'unconfigured'
        except Exception as e:     # one failing group must not stop the drain
            log.warning('force-save during drain failed for session %s: %s', s.pk, type(e).__name__)
            outcome = 'error'
        if instance.provider == 'onlyoffice':
            oo_state.update(s.pk, oo_drain_save={'at': oo_state.now_iso(), 'outcome': outcome})
        out.append((s, outcome))
    return out


def _at_or_after(iso, since):
    when = parse_datetime(iso) if isinstance(iso, str) else None
    return when is not None and since is not None and when >= since


def _group_safe(members, since):
    """True when an edit session of the group stored a save, or the editor
    answered "no changes", at or after `since`."""
    for s in members:
        ps = s.provider_state or {}
        if _at_or_after((ps.get('oo_last_saved') or {}).get('at'), since):
            return True
        if _at_or_after(ps.get('oo_forcesave_nochange_at'), since):
            return True
    return False


def verify(instance, since):
    """See the module docstring."""
    from . import sessions as session_api
    st = DrainState()
    live = list(live_any_expiry(instance))
    if instance.provider != 'onlyoffice':
        # No server-side way to ask the editor: only closed sessions count.
        st.pending = [f'{s.user.username}: {s.target_label} ({s.mode})' for s in live]
        st.drained = not live
        st.detail = 'No open sessions.' if st.drained else f'{len(live)} session(s) still open.'
        return st

    from .net import OfficeFetchError
    from .providers.onlyoffice import client
    now = timezone.now()
    groups = {}
    for s in live:
        groups.setdefault(s.document_key, []).append(s)
    for members in groups.values():
        label = members[0].target_label
        edit = [s for s in members if s.mode == 'edit']
        if not edit or _group_safe(edit, since):
            continue          # viewers only, or saved since the drain began
        ps_list = [s.provider_state or {} for s in members]
        oo_key = next((ps.get('oo_key') for ps in ps_list if ps.get('oo_key')), None)
        if not oo_key and not any(ps.get('oo_file_fetched_at') for ps in ps_list):
            # The editor never loaded the file: nothing of it can be unsaved there.
            for s in members:
                if s.expires_at <= now:
                    session_api.close(s, reason='expired; never loaded by the editor (drain)')
            continue
        if not oo_key:
            st.unknown = True
            st.pending.append(f'{label}: loaded by the editor but its editor key is unknown')
            continue
        try:
            client.command(instance, 'info', key=oo_key)
        except client.DocsError as e:
            if e.code == 1:
                # The editor no longer has the document open. Its final save
                # either arrived or is in the forgotten list (checked below).
                for s in members:
                    session_api.close(s, reason='the editor no longer has it open (drain)')
                continue
            st.unknown = True
            st.pending.append(f'{label}: the editor could not report on it ({e})')
            continue
        except OfficeFetchError as e:
            st.unknown = True
            st.pending.append(f'{label}: the editor is unreachable ({str(e)[:120]})')
            continue
        answers = {((s.provider_state or {}).get('oo_drain_save') or {}).get('outcome') for s in edit}
        if answers & {'error', 'unconfigured', 'refused'}:
            st.unknown = True
            st.pending.append(f'{label}: open in the editor, and the save request failed')
        else:
            st.pending.append(f'{label}: open in the editor; waiting for the requested save')

    try:
        forgotten = client.command(instance, 'getForgottenList')
        keys = forgotten.get('keys') or []
        if keys:
            st.unknown = True
            st.pending.append(f'The editor holds {len(keys)} document(s) whose final save never '
                              'reached clientst0r ("forgotten" files). Recover them before maintenance.')
    except client.DocsError as e:
        st.unknown = True
        st.pending.append(f'The editor could not list unsaved ("forgotten") documents: {e}')
    except OfficeFetchError as e:
        if live:
            st.unknown = True
            st.pending.append('The editor is unreachable, so unsaved documents cannot be ruled out '
                              f'({str(e)[:120]}).')

    st.drained = not st.pending and not st.unknown
    st.detail = ('All edits are stored in clientst0r.' if st.drained else
                 f'{len(st.pending)} item(s) not verified' + (' (unknown state)' if st.unknown else ''))
    return st
