"""
Ticket → paired RMM: handoff, read-only diagnostics, remote launch and fix
referrals (Phase 56.5 / 56.6; services/rmm_actions.py has the rules).

  GET  /psa/rmm/<ticket>/handoff/?device=<id>   preview what a handoff sends
  POST /psa/rmm/<ticket>/handoff/               send it
  POST /psa/rmm/<ticket>/diagnostic/            request a read-only diagnostic
  POST /psa/rmm/<ticket>/launch/                remote view / control → redirect
  POST /psa/rmm/<ticket>/fix/                   refer a fix for the RMM to approve

Not AI features: none of this checks `psa_ai_enabled`. Every route needs
PSA (globally and for the ticket's customer), an MSP technician, the ticket
through the same scoped queryset as the ticket page, and the technician-
access capability for the action at the ticket's customer. Anything else
gets 404, the same as a ticket that doesn't exist.
"""
from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_http_methods, require_POST

from psa.feature_flags import is_psa_enabled_for_client, require_psa_enabled
from psa.views import _scoped_ticket_qs

from .services import rmm_actions
from .services.rmm_actions import ActionRefused


def _ticket(request, ticket_number):
    from tech_access.resolver import is_technician
    if not is_technician(request.user):
        raise Http404()
    ticket = get_object_or_404(_scoped_ticket_qs(request).select_related('related_asset'),
                               ticket_number=ticket_number)
    if not is_psa_enabled_for_client(ticket.organization):
        raise Http404()
    # No technician access at this customer at all: the ticket doesn't exist
    # as far as these routes are concerned. Within an assignment, a missing
    # capability is explained instead (services/rmm_actions.action_state).
    from tech_access.resolver import has_any_assignment
    if not has_any_assignment(request.user, ticket.organization):
        raise Http404()
    return ticket


def _back(ticket):
    return redirect(reverse('psa:ticket_detail', args=[ticket.ticket_number]) + '#ticket-rmm-panel')


def _refused(request, ticket, e: ActionRefused):
    messages.error(request, e.message)
    return _back(ticket)


@login_required
@require_psa_enabled
@require_http_methods(['GET', 'POST'])
def handoff(request, ticket_number):
    ticket = _ticket(request, ticket_number)
    device_pk = request.GET.get('device') if request.method == 'GET' else request.POST.get('device')
    try:
        target = rmm_actions.find_target(ticket, device_pk)
    except ActionRefused as e:
        if request.method == 'GET':
            raise Http404()
        return _refused(request, ticket, e)
    ok, reason, _ = rmm_actions.action_state(request.user, ticket, target, 'handoff')
    if request.method == 'GET':
        if not ok:
            messages.error(request, reason)
            return _back(ticket)
        context = rmm_actions.handoff_context(ticket)
        from .services.evidence import digest
        from integrations.ticket_rmm import settings
        return render(request, 'psa/rmm_handoff_preview.html', {
            'ticket': ticket, 'target': target, 'context': context, 'context_digest': digest(context),
            'site': settings(target.connection)['site'], 'idempotency_key': uuid.uuid4().hex,
            'max_note': rmm_actions.MAX_NOTE_CHARS,
        })
    try:
        req, repeat = rmm_actions.handoff(request.user, ticket, device_pk, request.POST.get('idempotency_key', ''),
                                          request.POST.get('context_digest', ''), request.POST.get('note', ''),
                                          request=request)
    except ActionRefused as e:
        return _refused(request, ticket, e)
    _report(request, req, repeat, 'Handoff')
    return _back(ticket)


def _report(request, req, repeat, what):
    if req.status == 'pending':
        messages.info(request, f'{what} accepted by {req.connection.name}; waiting for it to confirm receipt.'
                      if req.kind == 'handoff' else f'{what} accepted by {req.connection.name}.')
    elif req.status in ('unavailable', 'failed'):
        messages.error(request, f'{what} not delivered: {req.error}')
    elif repeat:
        messages.info(request, f'{what} was already sent ({req.get_status_display().lower()}).')


@login_required
@require_psa_enabled
@require_POST
def diagnostic(request, ticket_number):
    ticket = _ticket(request, ticket_number)
    try:
        req, repeat = rmm_actions.diagnostic(request.user, ticket, request.POST.get('device'),
                                             request.POST.get('diagnostic', ''),
                                             request.POST.get('idempotency_key', ''), request=request)
    except ActionRefused as e:
        return _refused(request, ticket, e)
    _report(request, req, repeat, f'Diagnostic "{req.diagnostic_label}"')
    return _back(ticket)


@login_required
@require_psa_enabled
@require_POST
def launch(request, ticket_number):
    ticket = _ticket(request, ticket_number)
    try:
        url = rmm_actions.launch(request.user, ticket, request.POST.get('device'), request.POST.get('mode', 'view'),
                                 request=request)
    except ActionRefused as e:
        return _refused(request, ticket, e)
    # The URL is the RMM's short-lived launch address: handed to the browser
    # once, never stored, logged, cached or sent on as a referrer.
    response = HttpResponseRedirect(url)
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@login_required
@require_psa_enabled
@require_POST
def fix(request, ticket_number):
    ticket = _ticket(request, ticket_number)
    try:
        req, repeat = rmm_actions.refer_fix(
            request.user, ticket, request.POST.get('device'), request.POST.get('idempotency_key', ''),
            risk=request.POST.get('risk', 'low'), title=request.POST.get('title', ''),
            description=request.POST.get('description', ''), suggestion_ref=request.POST.get('suggestion', ''),
            request=request)
    except ActionRefused as e:
        return _refused(request, ticket, e)
    _report(request, req, repeat, 'Fix referral')
    return _back(ticket)


app_name = 'ticket_rmm'
urlpatterns = [
    path('<str:ticket_number>/handoff/', handoff, name='handoff'),
    path('<str:ticket_number>/diagnostic/', diagnostic, name='diagnostic'),
    path('<str:ticket_number>/launch/', launch, name='launch'),
    path('<str:ticket_number>/fix/', fix, name='fix'),
]
