"""
PSA AI Assist — views (Phase 10a: read-only generate-and-view).

Approve / send / apply flows land in 10b/10c. For 10a we expose:
  * POST /psa/ai/generate-reply/<ticket_number>/
  * GET  /psa/ai/suggestion/<id>/  (detail)
  * POST /psa/ai/suggestion/<id>/reject/  (record rejection + feedback)
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from core.decorators import require_write
from psa.feature_flags import require_psa_enabled
from psa.views import _scoped_ticket_qs

from .models import AISuggestion
from .permissions import (
    can_apply_action, can_approve_others, can_view_suggestion, has_capability,
)
from .services.action_applier import apply_suggestion as apply_suggestion_dispatch
from .services.action_generator import generate_actions_for_ticket
from .services.reply_generator import SafetyFailure, generate_reply_for_ticket
from .services.triage_generator import generate_triage_for_ticket


def _client_ip(request):
    from core.client_ip import get_client_ip
    return get_client_ip(request)


def _ai_on(request):
    """Check both the master PSA flag (decorator handles that) AND the AI
    sub-flag. The decorator stack already enforces psa_enabled."""
    from core.ai_gate import ai_features_enabled
    return ai_features_enabled()


def _user_can_view_suggestion(user, suggestion: AISuggestion, request=None) -> bool:
    return can_view_suggestion(user, suggestion, request=request)


def _ticket_for(request, ticket_number, capability):
    """The ticket, if this technician may use `capability` on it; else 404.
    Customer users never pass (permissions.has_capability)."""
    ticket = get_object_or_404(_scoped_ticket_qs(request), ticket_number=ticket_number)
    if not has_capability(request.user, ticket.organization, capability, ticket=ticket):
        raise Http404()
    return ticket


def _suggestion_for(request, pk):
    """A suggestion by ID, only through a ticket this user can see and only
    with view permission for its organization. Synced-ticket suggestions have
    no native ticket to scope by and are reachable by technicians only."""
    suggestion = get_object_or_404(AISuggestion.objects.select_related('organization', 'native_ticket'), pk=pk)
    if not _user_can_view_suggestion(request.user, suggestion, request=request):
        raise Http404()
    if suggestion.native_ticket_id and not _scoped_ticket_qs(request).filter(
            pk=suggestion.native_ticket_id, organization_id=suggestion.organization_id).exists():
        raise Http404()
    return suggestion


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def generate_reply(request, ticket_number):
    """Generate a fresh AI reply suggestion for the ticket."""
    if not _ai_on(request):
        raise Http404('AI Assist is not enabled.')

    ticket = _ticket_for(request, ticket_number, 'draft')

    try:
        suggestion = generate_reply_for_ticket(
            ticket, user=request.user, request_path=request.path,
        )
    except SafetyFailure as exc:
        messages.warning(request, f'AI generation skipped: {exc}')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    if suggestion.review_state == 'blocked':
        messages.warning(request, 'AI generated a draft but it was blocked by the safety filter — see the suggestion log for details.')
    elif suggestion.review_state == 'failed':
        messages.error(request, 'AI generation failed (see audit log). Try again in a moment.')
    else:
        messages.success(
            request,
            f'AI reply drafted (confidence {suggestion.confidence:.0%}, risk: {suggestion.risk_level}). Review it before sending.'
        )
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def generate_triage(request, ticket_number):
    """
    Generate read-only AI triage guidance for the ticket.

    Triage is advisory only (the AI does NOT act on the ticket), so
    we deliberately do NOT require @require_write — read-only techs
    can still request investigation hints. Permission is gated at the
    service layer via `can_request_triage`.
    """
    if not _ai_on(request):
        raise Http404('AI Assist is not enabled.')

    ticket = _ticket_for(request, ticket_number, 'analyze')

    try:
        suggestion = generate_triage_for_ticket(
            ticket, requested_by=request.user, request=request,
        )
    except SafetyFailure as exc:
        messages.warning(request, f'AI triage skipped: {exc}')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))

    if suggestion.review_state == 'blocked':
        messages.warning(
            request,
            'AI triage was blocked by the safety filter — see the suggestion log for details.',
        )
    elif suggestion.review_state == 'failed':
        messages.error(
            request,
            'AI triage generation failed (see audit log). Try again in a moment.',
        )
    else:
        messages.success(
            request,
            'AI triage suggestion generated. Review below — verify against vendor docs before acting.',
        )
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


@login_required
@require_psa_enabled
def suggestion_detail(request, pk):
    """View a single AI suggestion."""
    if not _ai_on(request):
        raise Http404()
    suggestion = _suggestion_for(request, pk)
    return JsonResponse({
        'id': suggestion.pk,
        'kind': suggestion.kind,
        'review_state': suggestion.review_state,
        'risk_level': suggestion.risk_level,
        'model_name': suggestion.model_name,
        'confidence': float(suggestion.confidence),
        'suggested_body': suggestion.suggested_body,
        'context_snapshot': suggestion.context_snapshot,
        'created_at': suggestion.created_at.isoformat(),
        'reviewer_note': suggestion.reviewer_note,
    })


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def suggestion_reject(request, pk):
    """Record a rejection + feedback. Phase 10a: rejection is the only
    "act on a suggestion" path; approve+send lands in 10b."""
    if not _ai_on(request):
        raise Http404()
    suggestion = _suggestion_for(request, pk)
    if suggestion.review_state not in ('draft', 'pending_review'):
        messages.info(request, 'This suggestion is already in a terminal state.')
        return _back(request, suggestion)

    note = (request.POST.get('reviewer_note') or '').strip()[:2000]
    suggestion.review_state = 'rejected'
    suggestion.reviewer = request.user
    suggestion.reviewed_at = timezone.now()
    suggestion.reviewer_note = note
    suggestion.save(update_fields=[
        'review_state', 'reviewer', 'reviewed_at', 'reviewer_note',
    ])

    AuditLog.log(
        user=request.user, action='update', organization=suggestion.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'rejected suggestion {suggestion.pk}',
        description=f'Rejected AI suggestion {suggestion.pk}: {note[:120]}',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'note_length': len(note)},
    )
    messages.success(request, 'Rejected. The feedback is logged for prompt tuning.')
    return _back(request, suggestion)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def triage_feedback(request, pk):
    """
    Tech feedback on an AI triage suggestion. Triage is advisory-only,
    so the "verdict" just records whether the tech found it useful:
      verdict=helpful  → review_state='approved' + AIActionLog(success=True)
      verdict=reject   → review_state='rejected' + AIActionLog(success=False)

    Read-only techs CAN submit triage feedback (no @require_write) —
    triage is read-only output, so giving feedback on it doesn't grant
    write capability anywhere.
    """
    if not _ai_on(request):
        raise Http404()
    suggestion = _suggestion_for(request, pk)
    if suggestion.kind != 'triage':
        messages.info(request, 'This action is for triage suggestions only.')
        return _back(request, suggestion)
    if suggestion.review_state in ('approved', 'rejected', 'expired', 'superseded', 'failed', 'blocked'):
        messages.info(request, f'Already in terminal state ({suggestion.review_state}).')
        return _back(request, suggestion)

    verdict = (request.POST.get('verdict') or '').strip().lower()
    note = (request.POST.get('reviewer_note') or '').strip()[:2000]
    if verdict not in ('helpful', 'reject'):
        messages.error(request, 'Invalid feedback verdict.')
        return _back(request, suggestion)

    if verdict == 'helpful':
        suggestion.review_state = 'approved'
    else:
        suggestion.review_state = 'rejected'
    suggestion.reviewer = request.user
    suggestion.reviewed_at = timezone.now()
    suggestion.reviewer_note = note
    suggestion.save(update_fields=[
        'review_state', 'reviewer', 'reviewed_at', 'reviewer_note',
    ])

    from .models import AIActionLog
    AIActionLog.objects.create(
        suggestion=suggestion,
        organization=suggestion.organization,
        actor=request.user,
        success=(verdict == 'helpful'),
        error=('' if verdict == 'helpful' else (note[:200] or 'rejected without note')),
        diff={'feedback': verdict},
    )
    AuditLog.log(
        user=request.user, action='update', organization=suggestion.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'triage feedback ({verdict}) on suggestion {suggestion.pk}',
        description=f'AI triage marked {verdict} by tech.',
        ip_address=_client_ip(request), path=request.path,
        extra_data={'verdict': verdict, 'note_length': len(note)},
    )
    if verdict == 'helpful':
        messages.success(request, 'Marked as helpful — feedback recorded for prompt tuning.')
    else:
        messages.success(request, 'Rejected — feedback recorded for prompt tuning.')
    return _back(request, suggestion)


def _back(request, suggestion: AISuggestion):
    nt = suggestion.native_ticket
    if nt is not None:
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': nt.ticket_number}))
    return redirect('psa:ticket_list')


# ---------------------------------------------------------------------------
# Phase 10b — action generation, request approval, approve+apply, send reply
# ---------------------------------------------------------------------------

@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def generate_actions(request, ticket_number):
    """Generate AI Suggested Actions for the ticket."""
    if not _ai_on(request):
        raise Http404()
    ticket = _ticket_for(request, ticket_number, 'apply_change')
    try:
        results = generate_actions_for_ticket(ticket, user=request.user, request_path=request.path)
    except SafetyFailure as exc:
        messages.warning(request, f'AI action generation skipped: {exc}')
        return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
    if not results:
        messages.info(request, 'AI did not propose any actions for this ticket.')
    else:
        usable = [s for s in results if s.review_state == 'draft']
        messages.success(
            request,
            f'AI proposed {len(usable)} action{"s" if len(usable) != 1 else ""} '
            f'(plus {len(results) - len(usable)} blocked).'
        )
    return redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))


def _resolve_suggestion_for_write(request, pk):
    return _suggestion_for(request, pk)


@login_required
@require_psa_enabled
@require_http_methods(['POST'])
def suggestion_request_approval(request, pk):
    """Lower-tier user asks a higher-tier reviewer to approve the suggestion.
    State: draft → pending_review."""
    if not _ai_on(request):
        raise Http404()
    suggestion = _resolve_suggestion_for_write(request, pk)
    if suggestion.review_state != 'draft':
        messages.info(request, 'Already submitted or in a terminal state.')
        return _back(request, suggestion)
    suggestion.review_state = 'pending_review'
    suggestion.requested_review_at = timezone.now()
    suggestion.requested_review_by = request.user
    suggestion.save(update_fields=['review_state', 'requested_review_at', 'requested_review_by'])
    AuditLog.log(
        user=request.user, action='update', organization=suggestion.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'requested approval for suggestion {suggestion.pk}',
        description=f'Requested approval for {suggestion.kind} suggestion #{suggestion.pk}',
        ip_address=_client_ip(request), path=request.path,
    )
    messages.success(request, 'Approval requested. A senior tech / lead will review this shortly.')
    return _back(request, suggestion)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def suggestion_approve_and_apply(request, pk):
    """
    For action-suggestions: re-checks permission, dispatches to the
    action_applier, marks approved.

    Reply-suggestions are refused: since v3.17.646 an AI draft is only ever
    inserted into the composer, and the technician's normal Send publishes it.
    """
    if not _ai_on(request):
        raise Http404()
    suggestion = _resolve_suggestion_for_write(request, pk)
    if suggestion.review_state in ('approved', 'rejected', 'expired', 'superseded', 'failed', 'blocked'):
        messages.info(request, f'Suggestion is in terminal state ({suggestion.review_state}).')
        return _back(request, suggestion)

    # v3.17.646: an AI reply is never published from here. It goes into the
    # composer, and only the technician's own Send posts it.
    if suggestion.kind == 'reply':
        messages.info(request, 'AI replies are not sent from here. Use "Insert into reply box", '
                               'edit it, and send it with the normal Post reply button.')
        return _back(request, suggestion)
    if suggestion.kind == 'action':
        if not can_apply_action(request.user, suggestion, request=request):
            messages.error(request, "You don't have permission to apply this AI-suggested action. Use 'Request approval' instead.")
            return _back(request, suggestion)

    # If this was pending_review, the approver must have approve permission.
    if suggestion.review_state == 'pending_review' and suggestion.requested_review_by_id != request.user.id:
        if not can_approve_others(request.user, suggestion, request=request):
            messages.error(request, "You don't have permission to approve someone else's request.")
            return _back(request, suggestion)

    if suggestion.kind != 'action':
        messages.info(request, 'This suggestion has nothing to apply.')
        return _back(request, suggestion)
    return _approve_and_apply_action(request, suggestion)


def _approve_and_apply_action(request, suggestion):
    """Dispatch to action_applier and persist outcome."""
    log = apply_suggestion_dispatch(suggestion, actor=request.user)
    if log.success:
        suggestion.review_state = 'approved'
        suggestion.reviewer = request.user
        suggestion.reviewed_at = timezone.now()
        suggestion.save(update_fields=['review_state', 'reviewer', 'reviewed_at'])
        messages.success(request, f'Applied: {suggestion.action_type}')
    else:
        messages.error(request, f'Action failed: {log.error[:200]}')
    AuditLog.log(
        user=request.user, action='update', organization=suggestion.organization,
        object_type='psa_ai.AISuggestion', object_id=suggestion.pk,
        object_repr=f'apply suggestion {suggestion.pk} ({suggestion.action_type})',
        description=f'Applied {suggestion.action_type} (success={log.success})',
        ip_address=_client_ip(request), path=request.path,
        success=log.success,
        extra_data={'diff': log.diff or {}, 'error': log.error or ''},
    )
    return _back(request, suggestion)


@login_required
@require_psa_enabled
def ai_inbox(request):
    """List of AI suggestions awaiting review across all tickets the user
    can see. Default filter: pending my approval."""
    if not _ai_on(request):
        raise Http404()
    from psa.visibility import is_msp_staff
    if not is_msp_staff(request.user):
        raise Http404()
    qs = AISuggestion.objects.select_related('organization', 'native_ticket', 'requested_review_by', 'requested_by').filter(
        review_state__in=['draft', 'pending_review'],
    )

    filter_state = request.GET.get('state') or 'pending_review'
    if filter_state in ('draft', 'pending_review', 'all'):
        if filter_state != 'all':
            qs = qs.filter(review_state=filter_state)

    pending = [s for s in qs.order_by('-created_at')[:200]
               if can_view_suggestion(request.user, s, request=request)]
    return render(request, 'psa_ai/inbox.html', {
        'suggestions': pending,
        'filter_state': filter_state,
    })
