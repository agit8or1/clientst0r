"""The onboarding engine: sessions, step states, applying and skipping.

Views are thin; every rule lives here so tests and other callers use the same
path. Each applied step is atomic (the step's own writes, the saved answers and
the step state commit together) and writes one audit log entry.
"""
from __future__ import annotations

import datetime
import decimal
import logging

from django.db import transaction
from django.utils import timezone

from . import access, registry
from .models import OnboardingSession as S, OnboardingStepState as St
from .registry import StepError

logger = logging.getLogger('onboarding')

DONE_STATES = (St.DONE, St.SKIPPED)


def jsonable(value):
    """JSON-safe copy of form data (Decimals, dates, model instances)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if hasattr(value, 'pk') and hasattr(value, '_meta'):
        return value.pk
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


# --- sessions ----------------------------------------------------------------

def create_session(user, kind, organization, client=None, title=''):
    if kind not in dict(S.KINDS):
        raise StepError('Unknown kind of session.')
    if not access.can_use(user, organization):
        raise StepError('You do not have permission to run onboarding wizards here.')
    if kind != S.NEW_CUSTOMER:
        if client is None:
            raise StepError('Choose the customer this change is for.')
        if not access.can_use(user, client):
            raise StepError('You do not have permission to run onboarding wizards for that customer.')
    with transaction.atomic():
        session = S.objects.create(organization=organization, client=client, kind=kind, title=title[:255],
                                   created_by=user, status=S.DRAFT)
        ensure_states(session)
        if client is not None and kind != S.NEW_CUSTOMER:
            st = session.step_states.filter(step_key='select_client').first()
            if st is not None:
                st.status, st.completed_by, st.completed_at = St.DONE, user, timezone.now()
                st.save()
        session.current_step = next_step_key(session) or ''
        session.save(update_fields=['current_step'])
    _audit(session, user, 'create', f'Started {session.get_kind_display()}', None)
    return session


def ensure_states(session):
    """A state row for every step of the session's kind (steps contributed
    after the session was started get theirs on the next load)."""
    have = set(session.step_states.values_list('step_key', flat=True))
    for step in registry.steps_for(session.kind):
        if step.key not in have:
            St.objects.create(session=session, step_key=step.key)


def _states(session):
    ensure_states(session)
    return {s.step_key: s for s in session.step_states.select_related('completed_by')}


def next_step_key(session):
    states = _states(session)
    for step in registry.steps_for(session.kind):
        st = states.get(step.key)
        if st is None or st.status not in DONE_STATES:
            return step.key
    return None


def progress(session):
    """Rows for the checklist sidebar, in step order."""
    states = _states(session)
    rows = []
    for step in registry.steps_for(session.kind):
        st = states[step.key]
        available = step.is_available()
        rows.append({
            'step': step, 'state': st, 'status': st.status, 'available': available,
            'unavailable_reason': step.unavailable_reason(),
            'blocked_reason': step.blocked_reason(session) if available else '',
            'current': step.key == session.current_step,
            'skippable': step.skippable or not available,
        })
    return rows


def counts(session):
    rows = progress(session)
    done = sum(1 for r in rows if r['status'] == St.DONE)
    skipped = sum(1 for r in rows if r['status'] == St.SKIPPED)
    return {'total': len(rows), 'done': done, 'skipped': skipped,
            'percent': int(100 * (done + skipped) / len(rows)) if rows else 0}


# --- access to one step --------------------------------------------------------

def step_denial(session, step, user):
    """Why `user` cannot apply `step` in `session` ('' = they can)."""
    if not access.can_open(user, session):
        return 'You do not have permission to run this wizard.'
    if not session.is_open:
        return 'This session is closed.'
    if not step.is_available():
        return step.unavailable_reason()
    why = step.blocked_reason(session)
    if why:
        return why
    return step.permission_denial(user, session) or ''


def get_step_for(session, key):
    step = registry.get_step(key)
    if step is None or key not in [s.key for s in registry.steps_for(session.kind)]:
        return None
    return step


# --- applying / skipping --------------------------------------------------------

def apply_step(session, key, data, user, request=None):
    """Validate and apply one step. Returns (form, summary): on a form error
    `summary` is None and the bound form carries the errors."""
    step = get_step_for(session, key)
    if step is None:
        raise StepError('Unknown step.')
    why = step_denial(session, step, user)
    if why:
        raise StepError(why)
    form = step.get_form(session, data, user)
    if form is not None and not form.is_valid():
        return form, None
    cleaned = form.cleaned_data if form is not None else {}
    try:
        with transaction.atomic():
            summary = step.apply(session, cleaned, user, request) or f'{step.title} saved'
            session.refresh_from_db()
            session.set_step_data(step.key, step.saved_data(session, cleaned))
            st = _states(session)[step.key]
            st.status, st.completed_by, st.completed_at = St.DONE, user, timezone.now()
            st.save()
            if session.status in (S.DRAFT,):
                session.status = S.IN_PROGRESS
            session.save()
            session.current_step = next_step_key(session) or step.key
            session.save(update_fields=['current_step'])
    except StepError as exc:
        if form is None:
            raise
        form.add_error(None, str(exc))
        return form, None
    _audit(session, user, 'update', f'{step.title}: {summary}', step, request)
    return form, summary


def skip_step(session, key, user, note='', request=None):
    step = get_step_for(session, key)
    if step is None:
        raise StepError('Unknown step.')
    if not access.can_open(user, session):
        raise StepError('You do not have permission to run this wizard.')
    if not session.is_open:
        raise StepError('This session is closed.')
    if not (step.skippable or not step.is_available()):
        raise StepError(f'"{step.title}" cannot be skipped.')
    with transaction.atomic():
        st = _states(session)[step.key]
        st.status, st.notes = St.SKIPPED, (note or '')[:2000]
        st.completed_by, st.completed_at = user, timezone.now()
        st.save()
        if session.status == S.DRAFT:
            session.status = S.IN_PROGRESS
        session.current_step = next_step_key(session) or step.key
        session.save()
    _audit(session, user, 'update', f'{step.title}: skipped' + (f' ({note})' if note else ''), step, request)


def reopen_step(session, key, user):
    step = get_step_for(session, key)
    if step is None or not access.can_open(user, session) or not session.is_open:
        raise StepError('This step cannot be reopened.')
    st = _states(session)[step.key]
    st.status = St.IN_PROGRESS
    st.save(update_fields=['status', 'updated_at'])
    session.current_step = step.key
    session.save(update_fields=['current_step', 'updated_at'])


def cancel_session(session, user, request=None):
    if not access.can_open(user, session):
        raise StepError('You do not have permission to run this wizard.')
    if not session.is_open:
        raise StepError('This session is already closed.')
    session.status = S.CANCELLED
    session.save(update_fields=['status', 'updated_at'])
    _audit(session, user, 'update', 'Cancelled (drafts and records already created are kept)', None, request)


def complete_session(session, user=None):
    session.status = S.COMPLETED
    session.completed_at = timezone.now()
    session.save(update_fields=['status', 'completed_at', 'updated_at'])


def refresh_status(session):
    """Follow the drafts this session produced: a signed agreement completes a
    change session, an agreement or quote still in an approval or signing state
    moves it to awaiting approval / signature."""
    if not session.is_open:
        return session
    from contracts.models import ContractDocument as D
    ag = session.agreement
    if ag is not None:
        if ag.status == D.SIGNED and session.kind != S.NEW_CUSTOMER:
            complete_session(session)
        elif ag.status in D.OPEN_FOR_SIGNING:
            _set_status(session, S.AWAITING_SIGNATURE)
        elif ag.status in (D.PENDING_APPROVAL,):
            _set_status(session, S.AWAITING_APPROVAL)
    return session


def _set_status(session, status):
    if session.status != status:
        session.status = status
        session.save(update_fields=['status', 'updated_at'])


# --- audit ----------------------------------------------------------------------

def _audit(session, user, action, description, step, request=None):
    from audit.models import AuditLog
    try:
        AuditLog.objects.create(
            user=user, username=getattr(user, 'username', '') or '', action=action,
            object_type='OnboardingSession', object_id=session.pk, object_repr=session.display_title[:255],
            description=description[:2000], organization=session.client or session.organization,
            ip_address=(request.META.get('REMOTE_ADDR') or None) if request is not None else None,
            path=request.path if request is not None else '',
            extra_data={'session': session.pk, 'kind': session.kind, 'step': getattr(step, 'key', ''),
                        'tenant': session.organization_id, 'client': session.client_id})
    except Exception:  # an audit failure must never undo the work
        logger.exception('could not audit onboarding step')
