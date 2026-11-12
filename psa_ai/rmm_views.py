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

from core.decorators import require_write
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
            request=request, action_key=request.POST.get('action', ''))
    except ActionRefused as e:
        return _refused(request, ticket, e)
    _report(request, req, repeat, 'Fix referral')
    return _back(ticket)


# --- Phase 4: affected devices, notes, verify-then-close ----------------------

def _staff_ticket(request, ticket_number, perm='tickets_view'):
    """A ticket an MSP technician may change (same rule as Set asset): the
    ticket page's scoped queryset, PSA on for the customer. 404 otherwise.

    `perm` is the ticket role flag the action needs at the ticket's customer
    (tickets_edit to change affected devices, tickets_close to close); a
    role without it gets 403 rather than the action."""
    from django.core.exceptions import PermissionDenied
    from accounts.permission_utils import has_perm_for_org
    from psa.visibility import is_msp_staff
    if not is_msp_staff(request.user):
        raise Http404()
    ticket = get_object_or_404(_scoped_ticket_qs(request).select_related('related_asset'),
                               ticket_number=ticket_number)
    if not is_psa_enabled_for_client(ticket.organization):
        raise Http404()
    if not has_perm_for_org(request.user, ticket.organization, 'tickets_view'):
        raise Http404()
    if perm != 'tickets_view' and not has_perm_for_org(request.user, ticket.organization, perm):
        raise PermissionDenied(f"Your role does not include '{perm}' for this customer.")
    return ticket


@login_required
@require_write
@require_psa_enabled
@require_POST
def affected(request, ticket_number):
    """Add or remove an affected device (same customer only)."""
    from psa.affected import AffectedRefused, add, remove
    ticket = _staff_ticket(request, ticket_number, 'tickets_edit')
    try:
        if request.POST.get('op') == 'remove':
            asset = remove(ticket, request.POST.get('asset'), request.user, request)
            messages.success(request, f'{asset.name} is no longer listed on this ticket.')
        else:
            asset, created = add(ticket, request.POST.get('asset'), request.user, request)
            messages.success(request, f'{asset.name} added to this ticket.' if created
                             else f'{asset.name} is already on this ticket.')
    except AffectedRefused as e:
        messages.error(request, str(e))
    return _back(ticket)


@login_required
@require_psa_enabled
@require_POST
def note(request, ticket_number):
    """Attach one request's outcome to the ticket as an internal note."""
    from .services.device_panel import NoteRefused, attach_note
    ticket = _ticket(request, ticket_number)
    try:
        attach_note(request.user, ticket, request.POST.get('request', ''), request)
    except NoteRefused as e:
        messages.error(request, str(e))
        return _back(ticket)
    messages.success(request, 'Result added as an internal note.')
    return _back(ticket)


@login_required
@require_psa_enabled
@require_http_methods(['GET'])
def verify(request, ticket_number):
    from psa.models import Ticket, TicketStatus
    from .services.device_panel import verification
    ticket = _staff_ticket(request, ticket_number)
    return render(request, 'psa/ticket_verify_close.html', {
        'ticket': ticket, 'v': verification(ticket),
        'statuses': TicketStatus.objects.filter(is_terminal=True).order_by('sort_order'),
        'categories': Ticket.CLOSURE_CATEGORIES,
    })


@login_required
@require_write
@require_psa_enabled
@require_POST
def verify_close(request, ticket_number):
    """Close after verification. The checks are re-run here, not trusted from
    the form; failing or unknown checks need `acknowledge`. The Close
    button's own closeout rules (summary, category, sign-off, checklist)
    still apply through the same function."""
    from audit.models import AuditLog
    from django.core.exceptions import ValidationError
    from psa.models import TicketComment, TicketStatus
    from psa.views import _closeout_transition
    from .services.device_panel import verification, verification_text
    ticket = _staff_ticket(request, ticket_number, 'tickets_close')
    v = verification(ticket)
    verify_url = reverse('ticket_rmm:verify', args=[ticket.ticket_number])
    if not v['all_ok'] and request.POST.get('acknowledge') != '1':
        messages.error(request, 'Some checks failed or could not be verified. Tick “Close anyway” to confirm you '
                                'verified the fix another way.')
        return redirect(verify_url)
    status_id = (request.POST.get('status') or '').strip()
    target = (TicketStatus.objects.filter(pk=status_id, is_terminal=True).first() if status_id.isdigit() else
              (TicketStatus.objects.filter(slug='closed').first()
               or TicketStatus.objects.filter(is_terminal=True).order_by('sort_order').first()))
    if target is None:
        messages.error(request, 'Pick a resolved/closed status.')
        return redirect(verify_url)
    try:
        result = _closeout_transition(request, ticket, target, mark_closed=True)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        result = None
    if result is None:
        return redirect(verify_url)
    description, extra = result
    text = verification_text(v)
    if not v['all_ok']:
        text += '\nClosed anyway: the technician confirmed the fix another way.'
    TicketComment.objects.create(ticket=ticket, author=request.user, body=text, is_internal=True, source='rmm')
    AuditLog.log(user=request.user, action='update', organization=ticket.organization, object_type='psa.Ticket',
                 object_id=ticket.pk, object_repr=ticket.ticket_number,
                 description=(description + (' after verification' if v['all_ok'] else
                                             ' with unverified checks acknowledged'))[:1000],
                 path=request.path, extra_data=dict(extra, verified=v['all_ok'], failed=v['failed'],
                                                    unknown=v['unknown']))
    messages.success(request, description)
    return redirect(reverse('psa:ticket_detail', args=[ticket.ticket_number]))


app_name = 'ticket_rmm'
urlpatterns = [
    path('<str:ticket_number>/affected/', affected, name='affected'),
    path('<str:ticket_number>/note/', note, name='note'),
    path('<str:ticket_number>/verify/', verify, name='verify'),
    path('<str:ticket_number>/verify/close/', verify_close, name='verify_close'),
    path('<str:ticket_number>/handoff/', handoff, name='handoff'),
    path('<str:ticket_number>/diagnostic/', diagnostic, name='diagnostic'),
    path('<str:ticket_number>/launch/', launch, name='launch'),
    path('<str:ticket_number>/fix/', fix, name='fix'),
]
