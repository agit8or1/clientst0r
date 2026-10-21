"""
Apply an approved AISuggestion(kind='action') to the underlying ticket.

Defence-in-depth — ALL action_payload values are re-validated server-
side at apply time. The model's output is treated as untrusted hint.

Each handler returns a `diff` dict (before/after for changed fields)
that lands in AIActionLog. Failures are caught and logged; the
suggestion is left at its previous state so the caller can retry or
mark `failed`.
"""
from __future__ import annotations

import logging

from django.utils import timezone


logger = logging.getLogger('psa_ai.action_applier')


# Risk-level → which handler keys are considered low/high.
LOW_RISK = {'set_status', 'set_priority', 'assign_to', 'link_kb', 'add_internal_note'}
HIGH_RISK = {'start_workflow', 'run_rmm_script', 'escalate'}


class UnknownAction(Exception):
    pass


class InvalidPayload(Exception):
    pass


def apply_suggestion(suggestion, *, actor):
    """Dispatch on suggestion.action_type. Returns AIActionLog row."""
    from psa_ai.models import AIActionLog
    handler = _HANDLERS.get(suggestion.action_type)
    if handler is None:
        return AIActionLog.objects.create(
            suggestion=suggestion, organization=suggestion.organization,
            actor=actor, success=False,
            error=f'Unknown action_type: {suggestion.action_type!r}',
        )
    try:
        diff = handler(suggestion, actor)
        return AIActionLog.objects.create(
            suggestion=suggestion, organization=suggestion.organization,
            actor=actor, success=True, diff=diff or {},
        )
    except InvalidPayload as e:
        return AIActionLog.objects.create(
            suggestion=suggestion, organization=suggestion.organization,
            actor=actor, success=False, error=f'Invalid payload: {e}'[:500],
        )
    except Exception as e:
        logger.exception('Failed to apply suggestion %s', suggestion.pk)
        return AIActionLog.objects.create(
            suggestion=suggestion, organization=suggestion.organization,
            actor=actor, success=False, error=str(e)[:500],
        )


def _ticket(suggestion):
    """Resolve the underlying ticket. For Phase 10b we only operate on
    native psa.Ticket — synced PSATicket support comes when we wire the
    push path through integrations."""
    if suggestion.native_ticket_id:
        return suggestion.native_ticket
    raise InvalidPayload('Action only supported on native PSA tickets in Phase 10b')


# -- Low-risk handlers ------------------------------------------------------

def _set_status(suggestion, actor):
    from psa.models import TicketStatus, TicketComment
    ticket = _ticket(suggestion)
    target_slug = (suggestion.action_payload or {}).get('target_slug') or ''
    if not target_slug:
        raise InvalidPayload('target_slug required')
    target = TicketStatus.objects.filter(slug=target_slug).first()
    if target is None:
        raise InvalidPayload(f'Unknown status slug: {target_slug!r}')
    if target.is_terminal:
        # Closing goes through the same closeout rules as the Close button;
        # the AI can't supply a resolution, so the ticket must already have one.
        from psa.closeout import closeout_errors
        errors = closeout_errors(ticket, target, ticket.resolution_summary,
                                 ticket.closure_category)
        if errors:
            raise InvalidPayload('Close the ticket from its page: ' + ' '.join(errors))
    prev = ticket.status.name if ticket.status_id else '—'
    ticket.status = target
    ticket.updated_by = actor
    update_fields = ['status', 'updated_by', 'updated_at']
    if target.is_terminal and not ticket.resolved_at:
        ticket.resolved_at = timezone.now()
        update_fields.append('resolved_at')
    ticket.save(update_fields=update_fields)
    TicketComment.objects.create(
        ticket=ticket, author=actor,
        body=f'[AI-suggested, applied by {actor.username}] Status: {prev} → {target.name}',
        is_internal=True, is_system=True,
    )
    return {'status': {'from': prev, 'to': target.name}}


def _set_priority(suggestion, actor):
    from psa.models import TicketPriority, TicketComment
    ticket = _ticket(suggestion)
    target_code = (suggestion.action_payload or {}).get('target_code') or ''
    if not target_code:
        raise InvalidPayload('target_code required')
    target = TicketPriority.objects.filter(code=target_code).first()
    if target is None:
        raise InvalidPayload(f'Unknown priority code: {target_code!r}')
    prev = ticket.priority.code if ticket.priority_id else '—'
    ticket.priority = target
    ticket.updated_by = actor
    ticket.save(update_fields=['priority', 'updated_by', 'updated_at'])
    TicketComment.objects.create(
        ticket=ticket, author=actor,
        body=f'[AI-suggested, applied by {actor.username}] Priority: {prev} → {target.code}',
        is_internal=True, is_system=True,
    )
    return {'priority': {'from': prev, 'to': target.code}}


def _assign_to(suggestion, actor):
    from django.contrib.auth import get_user_model
    from accounts.models import Membership
    from psa.models import TicketComment
    User = get_user_model()
    ticket = _ticket(suggestion)
    username = (suggestion.action_payload or {}).get('username') or ''
    if not username:
        raise InvalidPayload('username required')
    target = User.objects.filter(username=username, is_active=True).first()
    if target is None:
        raise InvalidPayload(f'Unknown user: {username!r}')
    # Defence-in-depth: assigned user must be a member of the ticket's org.
    is_member = Membership.objects.filter(
        user=target, organization=ticket.organization, is_active=True,
    ).exists()
    if not (target.is_superuser or is_member):
        raise InvalidPayload(f'User {username!r} has no membership in this org')
    prev = ticket.assigned_to.username if ticket.assigned_to_id else '—'
    ticket.assigned_to = target
    ticket.updated_by = actor
    ticket.save(update_fields=['assigned_to', 'updated_by', 'updated_at'])
    TicketComment.objects.create(
        ticket=ticket, author=actor,
        body=f'[AI-suggested, applied by {actor.username}] Assigned: {prev} → {target.username}',
        is_internal=True, is_system=True,
    )
    return {'assigned_to': {'from': prev, 'to': target.username}}


def _link_kb(suggestion, actor):
    from docs.models import Document
    from django.db.models import Q
    from psa.models import TicketComment
    ticket = _ticket(suggestion)
    slug = (suggestion.action_payload or {}).get('document_slug') or ''
    if not slug:
        raise InvalidPayload('document_slug required')
    # Tenant-scoped lookup: org docs OR global KB.
    doc = Document.objects.filter(
        Q(slug=slug) & (Q(organization=ticket.organization) | Q(is_global=True))
    ).first()
    if doc is None:
        raise InvalidPayload(f'Unknown / inaccessible doc: {slug!r}')
    prev_id = ticket.related_kb_article_id or ticket.related_documentation_id
    # Prefer the kb-article slot for global docs; documentation slot for org-scoped.
    field = 'related_kb_article' if getattr(doc, 'is_global', False) else 'related_documentation'
    setattr(ticket, field, doc)
    ticket.updated_by = actor
    ticket.save(update_fields=[field, 'updated_by', 'updated_at'])
    TicketComment.objects.create(
        ticket=ticket, author=actor,
        body=f'[AI-suggested, applied by {actor.username}] Linked KB: {doc.title} (#{doc.id})',
        is_internal=True, is_system=True,
    )
    return {field: {'from': prev_id, 'to': doc.id, 'doc_title': doc.title}}


def _add_internal_note(suggestion, actor):
    from psa.models import TicketComment
    ticket = _ticket(suggestion)
    body = (suggestion.action_payload or {}).get('body') or ''
    body = body.strip()[:2000]
    if not body:
        raise InvalidPayload('body required')
    c = TicketComment.objects.create(
        ticket=ticket, author=actor,
        body=f'[AI-suggested, applied by {actor.username}]\n{body}',
        is_internal=True, is_system=False,
    )
    return {'comment_id': c.id, 'length': len(body)}


# -- High-risk handlers (Phase 10c — gated by stricter permissions) ---------

def _start_workflow(suggestion, actor):
    """Spawn a processes.ProcessExecution from a process template name.
    Wraps the existing engine — does not invent new workflow primitives."""
    try:
        from processes.models import Process, ProcessExecution
    except Exception:
        raise InvalidPayload('processes app not available')
    ticket = _ticket(suggestion)
    payload = suggestion.action_payload or {}
    template_name = payload.get('process_template') or ''
    if not template_name:
        raise InvalidPayload('process_template required')
    proc = Process.objects.filter(name=template_name).first()
    if proc is None:
        raise InvalidPayload(f'Unknown process template: {template_name!r}')
    exec_kwargs = {'process': proc}
    if hasattr(ProcessExecution, 'organization_id'):
        exec_kwargs['organization'] = ticket.organization
    if hasattr(ProcessExecution, 'started_by_id'):
        exec_kwargs['started_by'] = actor
    pe = ProcessExecution.objects.create(**exec_kwargs)
    return {'process_execution_id': pe.id, 'process_template': template_name}


def _escalate(suggestion, actor):
    """Mark the ticket as escalated by setting status (best-effort) and
    writing an internal note. Does not page anyone in 10c."""
    from psa.models import TicketStatus, TicketComment
    ticket = _ticket(suggestion)
    payload = suggestion.action_payload or {}
    target = (
        TicketStatus.objects.filter(slug='escalated').first()
        or TicketStatus.objects.filter(name__iexact='Escalated').first()
    )
    if target is not None and ticket.status_id != target.id:
        ticket.status = target
        ticket.updated_by = actor
        ticket.save(update_fields=['status', 'updated_by', 'updated_at'])
    note = f"[AI-suggested, applied by {actor.username}] Escalation requested. Reason: {payload.get('reason', 'not specified')}"
    if payload.get('to_team'):
        note += f"\nTo team: {payload['to_team']}"
    TicketComment.objects.create(
        ticket=ticket, author=actor, body=note,
        is_internal=True, is_system=True,
    )
    return {'escalated': True, 'reason': payload.get('reason', '')}


# -- Dispatcher table --------------------------------------------------------

_HANDLERS = {
    'set_status':        _set_status,
    'set_priority':      _set_priority,
    'assign_to':         _assign_to,
    'link_kb':           _link_kb,
    'add_internal_note': _add_internal_note,
    'start_workflow':    _start_workflow,   # 10c
    'escalate':          _escalate,         # 10c
    # 'run_rmm_script' deliberately not implemented in this commit —
    # needs the integrations.RMM script-run plumbing wired first.
}
