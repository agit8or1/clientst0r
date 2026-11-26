"""First-install Setup Assistant (Phase 96.2–96.4).

A guided path through settings that already exist; it is not a second
settings system. The steps (core/setup_assistant_steps.py) are onboarding
engine steps of the install kind (onboarding.models.OnboardingSession.INSTALL:
a session with no tenant and no customer), so progress, skip, resume, reopen
and the audit trail come from the onboarding engine. Pages:
core/setup_assistant_views.py, under Administration → General → Setup assistant.

When it is offered automatically
    Only on a fresh install, only to superusers, once per sign-in, as a start
    screen with "Start setup" and "Later" (Later = dismissed: never offered
    automatically again; it stays one click away in Administration → General).
    "Fresh" means all of:
      * SystemSetting.setup_assistant_state is 'offered' or 'in_progress'.
        Rows that existed before this feature were set to 'not_offered' by
        migration core 0126, so an upgraded install never qualifies;
      * while still 'offered': the install looks new (looks_fresh): no
        tickets, at most one organization that is not internal (install.sh's
        setup.py creates the MSP's own), at most one user account. When that
        fails the state drops to 'not_offered' for good — a restored backup
        or a database created some other way is never redirected.
    The sign-in itself only arms a session flag (note_sign_in); the redirect
    happens on the first dashboard view (offer_redirect), which 2FA
    enforcement (accounts.middleware.Enforce2FAMiddleware) only lets through
    after enrolment when 2FA is required. The assistant's pages are not on the
    middleware's allow list either. Nothing is ever blocked: every page stays
    reachable while the assistant is unfinished.

Secrets
    Step answers are never stored with their values: a step stores only the
    names of the fields it changed (secret fields included only by name), and
    the audit summary does the same.
"""
from __future__ import annotations

import logging

from django.urls import reverse

logger = logging.getLogger('core')

SESSION_DUE_KEY = 'setup_assistant_due'

BASIC = 'basic'
ADVANCED = 'advanced'
PATHS = (BASIC, ADVANCED)
NOT_IN_PATH_NOTE = 'Not in the basic path'


def get_settings():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def set_state(state, user=None):
    """Write the state on the settings row without touching anything else."""
    from django.utils import timezone

    from core.models import SystemSetting
    fields = {'setup_assistant_state': state}
    if state == SystemSetting.SETUP_COMPLETED:
        fields['setup_assistant_completed_at'] = timezone.now()
        fields['setup_assistant_completed_by'] = user
    SystemSetting.get_settings()  # the row exists
    SystemSetting.objects.filter(pk=1).update(**fields)
    SystemSetting.forget_request_copy()


def looks_fresh() -> bool:
    """The runtime guard: this database still looks like a new install."""
    from django.contrib.auth import get_user_model

    from core.models import Organization
    if get_user_model().objects.count() > 1:
        return False
    if Organization.objects.exclude(organization_type=Organization.TYPE_INTERNAL).count() > 1:
        return False
    try:
        from psa.models import Ticket
        if Ticket.objects.exists():
            return False
    except Exception:  # PSA tables missing: nothing to count
        pass
    return True


def can_run(user) -> bool:
    return bool(user is not None and user.is_authenticated and user.is_active and user.is_superuser)


def should_offer(user) -> bool:
    """Offer the start screen to this user now (state + guard + superuser).
    Has one side effect: an 'offered' install that fails the guard is moved
    to 'not_offered' so it is never offered again."""
    from core.models import SystemSetting
    if not can_run(user):
        return False
    state = get_settings().setup_assistant_state
    if state == SystemSetting.SETUP_IN_PROGRESS:
        return True
    if state != SystemSetting.SETUP_OFFERED:
        return False
    if not looks_fresh():
        set_state(SystemSetting.SETUP_NOT_OFFERED)
        return False
    return True


def note_sign_in(sender, request, user, **kwargs):
    """user_logged_in: a superuser signed in through a sign-in page, so the
    next dashboard view may offer the assistant. The test client's
    force_login() logs in with a bare HttpRequest (no path) and is ignored."""
    if request is None or not getattr(request, 'path', '') or not hasattr(request, 'session'):
        return
    if not can_run(user):
        return
    request.session[SESSION_DUE_KEY] = True


def offer_redirect(request) -> str:
    """The start screen URL for the first dashboard view after sign-in, or ''."""
    session = getattr(request, 'session', None)
    if session is None or not session.pop(SESSION_DUE_KEY, False):
        return ''
    try:
        if should_offer(getattr(request, 'user', None)):
            return reverse('core:setup_assistant') + '?offer=1'
    except Exception:
        logger.exception('setup assistant offer check failed')
    return ''


# --- the install session --------------------------------------------------------

def open_session():
    """The newest open install session, or None."""
    from onboarding.models import OnboardingSession as S
    return (S.objects.filter(kind=S.INSTALL, status__in=S.OPEN_STATUSES)
            .order_by('-created_at', '-pk').first())


def last_session():
    from onboarding.models import OnboardingSession as S
    return S.objects.filter(kind=S.INSTALL).order_by('-created_at', '-pk').first()


def start(user, path):
    """Open (or continue) the install session on the chosen path."""
    from core.models import SystemSetting
    from onboarding import engine
    if path not in PATHS:
        path = BASIC
    session = open_session()
    if session is None:
        session = engine.create_install_session(user)
    apply_path(session, path, user)
    # Only an automatic offer moves on to 'in progress' (offered again at the
    # next sign-in until finished or "Later"). Opened by hand on an upgraded,
    # dismissed or completed install, the state stays as it is, so opening it
    # never makes it offer itself.
    if get_settings().setup_assistant_state == SystemSetting.SETUP_OFFERED:
        set_state(SystemSetting.SETUP_IN_PROGRESS)
    return session


def session_path(session):
    return (session.data or {}).get('path') or BASIC


def apply_path(session, path, user):
    """Basic path: steps outside it are skipped with a note (nothing is
    changed by skipping). Advanced: those skips are reopened."""
    from django.utils import timezone

    from onboarding import engine
    from onboarding.models import OnboardingStepState as St
    from . import setup_assistant_steps as steps
    data = dict(session.data or {})
    data['path'] = path
    session.data = data
    session.save(update_fields=['data', 'updated_at'])
    engine.ensure_states(session)
    for st in session.step_states.all():
        step = steps.STEP_BY_KEY.get(st.step_key)
        if step is None or step.basic:
            continue
        if path == BASIC and st.status == St.NOT_STARTED:
            st.status, st.notes = St.SKIPPED, NOT_IN_PATH_NOTE
            st.completed_by, st.completed_at = user, timezone.now()
            st.save()
        elif path == ADVANCED and st.status == St.SKIPPED and st.notes == NOT_IN_PATH_NOTE:
            st.status, st.notes, st.completed_at = St.NOT_STARTED, '', None
            st.save()
    session.current_step = engine.next_step_key(session) or session.current_step
    session.save(update_fields=['current_step', 'updated_at'])


def dismiss(user):
    """'Later': never offered automatically again (reopen from Administration)."""
    from core.models import SystemSetting
    if get_settings().setup_assistant_state != SystemSetting.SETUP_COMPLETED:
        set_state(SystemSetting.SETUP_DISMISSED)


def visible_steps(session):
    """The steps of the session's path, in order."""
    from . import setup_assistant_steps as steps
    path = session_path(session)
    return [s for s in steps.ordered() if path == ADVANCED or s.basic]


def neighbours(session, key):
    keys = [s.key for s in visible_steps(session)]
    if key not in keys:
        return None, (keys[0] if keys else None)
    i = keys.index(key)
    return (keys[i - 1] if i else None), (keys[i + 1] if i + 1 < len(keys) else None)


def next_open_key(session):
    """The first visible step not yet done or skipped."""
    from onboarding.models import OnboardingStepState as St
    states = {s.step_key: s.status for s in session.step_states.all()}
    for step in visible_steps(session):
        if states.get(step.key) not in (St.DONE, St.SKIPPED):
            return step.key
    keys = [s.key for s in visible_steps(session)]
    return keys[-1] if keys else None
