"""
PSA workflow rule engine.

Fires from psa/signals.py on ticket and comment events. Each rule is a
small JSON DSL — evaluate the condition, run the actions in order. Rule
errors are caught and stored on the rule row so a single bad rule never
breaks ticket save flow.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.contrib.auth.models import User
from django.utils import timezone


logger = logging.getLogger('psa.workflow_engine')

# fire_rule chains: the rules currently running on this thread, outermost
# first. A rule that is already in the chain is refused (a loop), and so is
# a chain deeper than MAX_CHAIN_DEPTH. psa.workflow_graph validates the same
# at save time; this is the run-time backstop for rules saved before that.
import threading as _threading

_chain_state = _threading.local()
MAX_CHAIN_DEPTH = 8


def _chain():
    stack = getattr(_chain_state, 'stack', None)
    if stack is None:
        stack = _chain_state.stack = []
    return stack


# ---- Condition evaluator --------------------------------------------------

def _get(ticket, key: str):
    """Pull a comparable scalar from the ticket for condition checking."""
    if key == 'priority':
        return getattr(getattr(ticket, 'priority', None), 'code', None)
    if key == 'queue':
        return getattr(getattr(ticket, 'queue', None), 'name', None)
    if key == 'status':
        return getattr(getattr(ticket, 'status', None), 'slug', None)
    if key == 'ticket_type':
        return getattr(getattr(ticket, 'ticket_type', None), 'slug', None)
    if key == 'is_unassigned':
        return ticket.assigned_to_id is None
    if key == 'is_paused':
        try:
            return bool(ticket.status_id and ticket.status.pauses_sla)
        except Exception:
            return False
    if key == 'subject':
        return ticket.subject or ''
    if key == 'sla_pct_elapsed':
        # Phase 14 v3 (v3.17.286): SLA-driven automation.
        # Returns 0..100+ percent of resolution SLA window elapsed.
        # 0 if no resolution_due_at is set on the ticket.
        return _sla_pct_elapsed(ticket)
    return None


def _sla_pct_elapsed(ticket) -> float:
    """How far through the resolution-SLA window the ticket is."""
    from django.utils import timezone
    if not getattr(ticket, 'resolution_due_at', None):
        return 0
    started = getattr(ticket, 'created_at', None)
    if started is None:
        return 0
    total = (ticket.resolution_due_at - started).total_seconds()
    if total <= 0:
        return 100  # already past due
    elapsed = (timezone.now() - started).total_seconds()
    return max(0, (elapsed / total) * 100)


def matches(ticket, condition: Dict[str, Any]) -> bool:
    """Evaluate a single condition dict against a ticket. Empty = always True."""
    if not condition:
        return True
    if not isinstance(condition, dict):
        return False

    # Boolean combinators
    if 'any' in condition:
        return any(matches(ticket, c) for c in (condition.get('any') or []))
    if 'all' in condition:
        return all(matches(ticket, c) for c in (condition.get('all') or []))

    # Specials
    if 'subject_contains' in condition:
        needle = (condition['subject_contains'] or '').lower()
        if needle and needle not in (ticket.subject or '').lower():
            return False

    # Phase 14 v3 (v3.17.286): SLA-percent threshold. Truthy when the
    # ticket has burned through at least N% of its resolution SLA window.
    if 'sla_pct_at_least' in condition:
        try:
            threshold = float(condition['sla_pct_at_least'])
        except (TypeError, ValueError):
            return False
        if _sla_pct_elapsed(ticket) < threshold:
            return False

    # Generic field comparisons
    for key, val in condition.items():
        if key in ('any', 'all', 'subject_contains', 'sla_pct_at_least'):
            continue
        if key.endswith('__in'):
            base = key[:-4]
            cur = _get(ticket, base)
            if cur not in (val or []):
                return False
        elif key.endswith('__not'):
            base = key[:-5]
            cur = _get(ticket, base)
            if cur == val:
                return False
        else:
            cur = _get(ticket, key)
            if cur != val:
                return False
    return True


# ---- Action runner --------------------------------------------------------

def _resolve_user(username: Optional[str]) -> Optional[User]:
    if not username:
        return None
    return User.objects.filter(username=username, is_active=True).first()


def run_action(ticket, action: Dict[str, Any]) -> None:
    """Run a single action dict against a ticket. Raises on bad input."""
    from .models import (
        Queue, TicketComment, TicketPriority, TicketWatcher,
    )
    atype = (action or {}).get('type', '')

    if atype == 'set_priority':
        code = action.get('code')
        p = TicketPriority.objects.filter(code=code).first()
        if p:
            ticket.priority = p
            ticket.save(update_fields=['priority', 'updated_at'])

    elif atype == 'set_queue':
        name = action.get('name')
        q = Queue.objects.filter(name=name, is_active=True).first()
        if q:
            ticket.queue = q
            ticket.save(update_fields=['queue', 'updated_at'])

    elif atype == 'assign_to':
        u = _resolve_user(action.get('username'))
        if u:
            ticket.assigned_to = u
            ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'add_watcher':
        u = _resolve_user(action.get('username'))
        if u:
            TicketWatcher.objects.get_or_create(ticket=ticket, user=u)

    elif atype == 'add_internal_note':
        body = (action.get('body') or '').strip()
        if body:
            TicketComment.objects.create(
                ticket=ticket, body=body[:5000],
                is_internal=True, is_system=True,
                source='workflow',
            )

    elif atype == 'add_tag':
        tag = (action.get('tag') or '').strip()
        if tag:
            tags = list(ticket.tags or [])
            if tag not in tags:
                tags.append(tag)
                ticket.tags = tags
                ticket.save(update_fields=['tags', 'updated_at'])

    elif atype == 'assign_round_robin':
        # Phase 14 v8 (v3.17.287): pick the active staff user with the
        # oldest "last assigned ticket" (= who hasn't been assigned in
        # the longest). When no one has ever been assigned, falls back
        # to the lowest-pk active staffer for stable behavior.
        from .models import Ticket as _T
        from django.db.models import Max
        candidates = User.objects.filter(is_active=True, is_staff=True)
        # Optional `group` filter: e.g. {"type": "...", "group": "techs"}
        grp = action.get('group')
        if grp:
            candidates = candidates.filter(groups__name=grp)
        if not candidates.exists():
            return
        last_assigned = (_T.objects
                         .filter(assigned_to__in=candidates)
                         .values('assigned_to_id')
                         .annotate(latest=Max('updated_at')))
        latest_by_user = {r['assigned_to_id']: r['latest'] for r in last_assigned}
        chosen = sorted(
            candidates,
            key=lambda u: (
                latest_by_user.get(u.id) is not None,
                latest_by_user.get(u.id),
                u.id,
            ),
        )[0]
        ticket.assigned_to = chosen
        ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'assign_skill_match':
        # Phase 14 v8 (v3.17.287): assign to a user whose Group
        # membership matches the action's `skill_group`. When multiple
        # users match, falls through to load-balanced selection
        # (lowest open-ticket count).
        from .models import Ticket as _T
        from django.db.models import Count, Q as _Q
        skill = (action.get('skill_group') or '').strip()
        if not skill:
            raise ValueError('assign_skill_match requires "skill_group"')
        candidates = User.objects.filter(
            is_active=True, is_staff=True,
            groups__name=skill,
        )
        if not candidates.exists():
            return
        # Tie-break by current open-ticket count (low first)
        ranked = candidates.annotate(
            open_count=Count('psa_assigned_tickets',
                              filter=~_Q(psa_assigned_tickets__status__is_terminal=True)),
        ).order_by('open_count', 'id')
        ticket.assigned_to = ranked.first()
        ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'assign_load_balanced':
        # Phase 14 v8 (v3.17.287): pick the active staff user with the
        # fewest currently-open assigned tickets.
        from django.db.models import Count, Q as _Q
        candidates = User.objects.filter(is_active=True, is_staff=True)
        grp = action.get('group')
        if grp:
            candidates = candidates.filter(groups__name=grp)
        if not candidates.exists():
            return
        ranked = candidates.annotate(
            open_count=Count('psa_assigned_tickets',
                              filter=~_Q(psa_assigned_tickets__status__is_terminal=True)),
        ).order_by('open_count', 'id')
        ticket.assigned_to = ranked.first()
        ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'create_charge':
        # Phase 14 v11 (v3.17.289): cross-module — when a ticket workflow
        # decides to bill the client (e.g. after-hours emergency, expedited
        # part), record a one-off Charge against the ticket's organization.
        from datetime import date as _d
        from decimal import Decimal as _D
        from .models import Charge as _C
        try:
            amount = _D(str(action.get('amount') or '0'))
        except Exception:
            raise ValueError('create_charge: invalid "amount"')
        if amount <= 0:
            raise ValueError('create_charge: "amount" must be positive')
        description = (action.get('description') or
                        f'Auto-charge for ticket {ticket.ticket_number}')[:300]
        is_credit = bool(action.get('is_credit'))
        # The MSP tenant that owns the workflow rule = ticket.organization;
        # the client to bill is the same since tickets are filed against
        # the client_org. Some installs use a separate `organization` for
        # the MSP and `client_org` for the customer; default to ticket.organization
        # for both, which works for single-tenant SaaS.
        client = getattr(ticket, 'client_org', None) or ticket.organization
        _C.objects.create(
            organization=ticket.organization,
            client_org=client,
            description=description,
            amount=amount,
            currency=action.get('currency') or 'USD',
            charge_date=_d.today(),
            is_credit=is_credit,
            recurrence='once',
            notes=f'Auto-created by workflow rule for ticket '
                  f'{ticket.ticket_number}',
        )

    elif atype == 'fire_rule':
        # Phase 14 v4 (v3.17.285): multi-step orchestration. Chain
        # to another WorkflowRule by name within the same org.
        # Loop / depth protection: the per-thread chain (_chain) below.
        from .models import WorkflowRule
        from django.db.models import Q
        name = (action.get('name') or '').strip()
        if not name:
            raise ValueError('fire_rule requires "name"')
        nxt = WorkflowRule.objects.filter(
            Q(organization__isnull=True) | Q(organization_id=ticket.organization_id),
            name=name, is_active=True,
        ).first()
        if nxt is None:
            raise ValueError(f'fire_rule: no active rule named {name!r}')
        chain = _chain()
        if nxt.pk in chain:
            raise ValueError(f'fire_rule: {name!r} is already running in this chain (loop)')
        if len(chain) >= MAX_CHAIN_DEPTH:
            raise ValueError(f'fire_rule: chain deeper than {MAX_CHAIN_DEPTH} rules')
        # Run nested rule's actions inline (skip the cron-like trigger
        # filter — chained execution intentionally bypasses trigger
        # matching since the parent already fired).
        chain.append(nxt.pk)
        try:
            if matches(ticket, nxt.conditions or {}):
                for sub in (nxt.actions or []):
                    run_action(ticket, sub)
            else:
                for sub in (nxt.else_actions or []):
                    run_action(ticket, sub)
        finally:
            chain.pop()

    else:
        raise ValueError(f'Unknown action type: {atype!r}')


# ---- Rule runner ----------------------------------------------------------

def fire(trigger: str, ticket, *, prior_status=None) -> int:
    """
    Run all active rules in the ticket's organization that match `trigger`
    AND whose conditions evaluate true. Returns the number of rules fired.
    Errors per rule are captured to WorkflowRule.last_error.
    """
    from django.db.models import Q
    from .models import WorkflowRule

    if ticket is None or not ticket.organization_id:
        return 0

    # Match MSP-wide rules (organization IS NULL) AND rules scoped to this
    # ticket's client organization.
    rules = WorkflowRule.objects.filter(
        Q(organization__isnull=True) | Q(organization_id=ticket.organization_id),
        trigger=trigger,
        is_active=True,
    ).order_by('sort_order', 'pk')

    from .models import WorkflowRuleFiring

    fired = 0
    for rule in rules:
        try:
            # Phase 14 v3 (v3.17.286): once-per-(rule,ticket) guard for
            # SLA tick rules so cron-driven fires don't spam.
            if (getattr(rule, 'fire_once_per_ticket', False)
                    and ticket.pk
                    and WorkflowRuleFiring.objects.filter(
                        rule=rule, ticket=ticket).exists()):
                continue

            if matches(ticket, rule.conditions or {}):
                branch = rule.actions or []
            elif rule.else_actions:
                # Phase 14 v2 (v3.17.285): conditional routing — when
                # the main condition fails AND else_actions are
                # configured, run them instead. This still counts as
                # a "fire" so the cooldown / fire_count tracks both
                # branches.
                branch = rule.else_actions
            else:
                continue
            chain = _chain()
            chain.append(rule.pk)
            try:
                for action in branch:
                    run_action(ticket, action)
            finally:
                chain.pop()
            rule.last_fired_at = timezone.now()
            rule.fire_count = (rule.fire_count or 0) + 1
            rule.last_error = ''
            rule.save(update_fields=['last_fired_at', 'fire_count', 'last_error'])

            if getattr(rule, 'fire_once_per_ticket', False) and ticket.pk:
                WorkflowRuleFiring.objects.get_or_create(
                    rule=rule, ticket=ticket,
                )
            fired += 1
        except Exception as exc:
            logger.exception('workflow rule %s failed', rule.pk)
            rule.last_error = str(exc)[:1000]
            rule.save(update_fields=['last_error'])
    return fired
