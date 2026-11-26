"""Setup Assistant pages (core/setup_assistant.py has the rules).

/core/settings/setup/              start screen and overview (GET); start, path, later (POST)
/core/settings/setup/<step>/       one step: GET shows it, POST saves, skips or re-runs

Superusers only (403 for everyone else). Saving goes through the onboarding
engine (onboarding.engine.apply_step / skip_step), which runs the step's save
helper inside one transaction and writes one audit row with the step's
one-line summary (field names only, never values).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from onboarding import engine
from onboarding.registry import StepError

from . import setup_assistant as sa
from . import setup_assistant_steps as steps


def _require_admin(request):
    if not sa.can_run(request.user):
        raise PermissionDenied('The Setup Assistant is for administrators.')


def _rows(session, current_key=None):
    """The step list for the sidebar and the overview, in path order."""
    states = {s.step_key: s for s in session.step_states.all()} if session else {}
    path = sa.session_path(session) if session else sa.BASIC
    out = []
    n = 0
    for step in steps.ordered():
        st = states.get(step.key)
        in_path = path == sa.ADVANCED or step.basic
        if in_path:
            n += 1
        out.append({
            'step': step, 'n': n if in_path else None, 'in_path': in_path,
            'status': st.status if st else 'not_started', 'note': st.notes if st else '',
            'current': step.key == current_key,
        })
    return out


def _progress(rows):
    visible = [r for r in rows if r['in_path']]
    done = sum(1 for r in visible if r['status'] in ('done', 'skipped'))
    return {'done': done, 'total': len(visible),
            'percent': int(100 * done / len(visible)) if visible else 0}


@login_required
def setup_assistant(request):
    _require_admin(request)
    ss = sa.get_settings()
    session = sa.open_session()
    last = session or sa.last_session()
    rows = _rows(session) if session else []
    return render(request, 'core/setup_assistant/start.html', {
        'ss': ss,
        'session': session,
        'last': last,
        'rows': rows,
        'progress': _progress(rows) if session else None,
        'path': sa.session_path(session) if session else sa.BASIC,
        'offer': request.GET.get('offer') == '1',
        'all_steps': steps.ordered(),
        'next_key': sa.next_open_key(session) if session else None,
        'current_tab': 'setup_assistant',
    })


@login_required
@require_POST
def setup_assistant_action(request):
    """start (with path), path (switch), later (dismiss the automatic offer)."""
    _require_admin(request)
    action = request.POST.get('action')
    if action == 'later':
        sa.dismiss(request.user)
        messages.info(request, 'The Setup Assistant will not open by itself again. You can run it any time '
                               'from Administration → General → Setup assistant.')
        return redirect('core:dashboard')
    if action in ('start', 'path'):
        path = request.POST.get('path') or sa.BASIC
        try:
            session = sa.start(request.user, path)
        except StepError as exc:
            messages.error(request, str(exc))
            return redirect('core:setup_assistant')
        return redirect('core:setup_assistant_step', key=sa.next_open_key(session))
    messages.error(request, 'Nothing was changed: unknown action.')
    return redirect('core:setup_assistant')


def _step_page(request, session, step, form, status=200):
    rows = _rows(session, step.key)
    row = next(r for r in rows if r['step'].key == step.key)
    previous, nxt = sa.neighbours(session, step.key)
    ctx = step.context(session, request.user)
    return render(request, 'core/setup_assistant/step.html', {
        'session': session, 'step': step, 'form': form, 'row': row, 'rows': rows,
        'progress': _progress(rows), 'ctx': ctx, 'previous': previous, 'next': nxt,
        'denial': engine.step_denial(session, step, request.user),
        'configured': step.configured(request.user),
        'path': sa.session_path(session),
        'current_tab': 'setup_assistant',
    }, status=status)


@login_required
def setup_assistant_step(request, key):
    _require_admin(request)
    session = sa.open_session()
    if session is None:
        return redirect('core:setup_assistant')
    step = engine.get_step_for(session, key)
    if step is None:
        raise Http404
    if request.method == 'POST':
        action = request.POST.get('action') or 'save'
        if action == 'skip':
            try:
                engine.skip_step(session, key, request.user, request.POST.get('note', ''), request)
            except StepError as exc:
                messages.error(request, str(exc))
                return redirect('core:setup_assistant_step', key=key)
            messages.info(request, f'{step.title}: skipped. Nothing was changed; you can come back to it.')
            session.refresh_from_db()
            return redirect('core:setup_assistant_step', key=sa.next_open_key(session))
        if action != 'save':
            messages.error(request, 'Nothing was changed: unknown action.')
            return redirect('core:setup_assistant_step', key=key)
        try:
            form, summary = engine.apply_step(session, key, request.POST, request.user, request)
        except StepError as exc:
            messages.error(request, str(exc))
            return redirect('core:setup_assistant_step', key=key)
        if summary is None:
            return _step_page(request, session, step, form, status=400)
        messages.success(request, f'{step.title}: {summary}.')
        session.refresh_from_db()
        if not session.is_open:
            return redirect('core:setup_assistant')
        if request.POST.get('stay'):
            return redirect('core:setup_assistant_step', key=key)
        _prev, nxt = sa.neighbours(session, key)
        return redirect('core:setup_assistant_step', key=nxt or sa.next_open_key(session))
    form = step.get_form(session, None, request.user)
    return _step_page(request, session, step, form)
