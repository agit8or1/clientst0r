"""Onboarding wizard pages. All rules live in onboarding.engine / access."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import access, engine, registry
from .models import OnboardingSession as S
from .registry import StepError


def _require_wizard_user(request):
    if not access.can_use_anywhere(request.user):
        raise PermissionDenied('Running customer onboarding needs the "manage_customer_onboarding" permission.')


def _session(request, pk):
    _require_wizard_user(request)
    return access.session_for_user(request.user, pk)


@login_required
def start(request):
    _require_wizard_user(request)
    clients = access.reachable_clients(request.user).filter(is_active=True).order_by('name')
    if request.method == 'POST':
        kind = request.POST.get('kind', '')
        client = None
        if kind != S.NEW_CUSTOMER:
            client = get_object_or_404(clients, pk=request.POST.get('client') or 0)
        tenant = access.tenant_for(request.user, request) or client
        try:
            if tenant is None:
                raise StepError('Select an organization first.')
            session = engine.create_session(request.user, kind, tenant, client)
        except StepError as exc:
            messages.error(request, str(exc))
        else:
            return redirect('onboarding:step', pk=session.pk, key=session.current_step)
    sessions = access.sessions_for(request.user).filter(status__in=S.OPEN_STATUSES)
    recent = access.sessions_for(request.user).filter(status__in=(S.COMPLETED, S.CANCELLED))[:10]
    lifecycle = [(k, label) for k, label in S.KINDS if k != S.NEW_CUSTOMER]
    return render(request, 'onboarding/start.html', {
        'sessions': sessions, 'recent': recent, 'clients': clients, 'lifecycle_kinds': lifecycle,
        'preselect_client': request.GET.get('client', ''),
    })


@login_required
def session_detail(request, pk):
    session = _session(request, pk)
    engine.refresh_status(session)
    return render(request, 'onboarding/session.html', {
        'session': session, 'rows': engine.progress(session), 'counts': engine.counts(session),
    })


def _step_page(request, session, step, form, summary=None):
    rows = engine.progress(session)
    row = next(r for r in rows if r['step'].key == step.key)
    return render(request, 'onboarding/step.html', {
        'session': session, 'step': step, 'form': form, 'row': row, 'rows': rows,
        'counts': engine.counts(session), 'ctx': step.context(session, request.user),
        'denial': engine.step_denial(session, step, request.user),
        'saved': session.step_data(step.key),
    })


@login_required
def step_view(request, pk, key):
    session = _session(request, pk)
    step = engine.get_step_for(session, key)
    if step is None:
        return redirect('onboarding:session', pk=session.pk)
    if request.method == 'POST':
        try:
            form, summary = engine.apply_step(session, key, request.POST, request.user, request)
        except StepError as exc:
            messages.error(request, str(exc))
            return redirect('onboarding:step', pk=session.pk, key=key)
        if summary is not None:
            messages.success(request, summary)
            session.refresh_from_db()
            if not session.is_open or request.POST.get('save_and_exit'):
                return redirect('onboarding:session', pk=session.pk)
            if request.POST.get('stay'):
                return redirect('onboarding:step', pk=session.pk, key=key)
            return redirect('onboarding:step', pk=session.pk, key=session.current_step or key)
        return _step_page(request, session, step, form)
    form = step.get_form(session, None, request.user) if step.is_available() else None
    return _step_page(request, session, step, form)


@login_required
@require_POST
def step_skip(request, pk, key):
    session = _session(request, pk)
    try:
        engine.skip_step(session, key, request.user, request.POST.get('note', ''), request)
        messages.info(request, 'Step skipped. You can come back to it any time.')
    except StepError as exc:
        messages.error(request, str(exc))
        return redirect('onboarding:step', pk=session.pk, key=key)
    session.refresh_from_db()
    return redirect('onboarding:step', pk=session.pk, key=session.current_step or key)


@login_required
@require_POST
def step_reopen(request, pk, key):
    session = _session(request, pk)
    try:
        engine.reopen_step(session, key, request.user)
    except StepError as exc:
        messages.error(request, str(exc))
    return redirect('onboarding:step', pk=session.pk, key=key)


@login_required
@require_POST
def session_cancel(request, pk):
    session = _session(request, pk)
    try:
        engine.cancel_session(session, request.user, request)
        messages.info(request, 'Session cancelled. Drafts and records already created were kept.')
    except StepError as exc:
        messages.error(request, str(exc))
    return redirect('onboarding:start')
