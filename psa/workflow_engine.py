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
# Actions one top-level ticket event may run in total, across every rule it
# sets off (rules reacting to other rules' saves included). A backstop: the
# chain check below already stops a rule re-entering itself.
MAX_ACTIONS_PER_EVENT = 50


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


class ActionSkipped(Exception):
    """An action that was not carried out; the rule's other actions still run
    and the reason is kept on the rule's last error."""


class BudgetExceeded(ValueError):
    """More than MAX_ACTIONS_PER_EVENT actions for one ticket event (a
    ValueError, as before; the subclass lets the run log tell it apart)."""


class LoopRefused(ValueError):
    """fire_rule refused: the target is already running, or the chain is too
    deep (a ValueError, as before)."""


def _assignable(ticket, users):
    """Users from ``users`` who may be given this ticket (SR-03)."""
    from .routing.engine import assignment_problem
    return [u for u in users if assignment_problem(u, ticket) is None]


def _check_assignee(ticket, user, action):
    from .routing.engine import assignment_problem
    problem = assignment_problem(user, ticket)
    if problem:
        raise ActionSkipped(f'{action}: {user.username} was not assigned ({problem})')


def _check_watcher(ticket, user):
    """Staff pass the assignment check; a customer user may only watch their
    own organization's tickets."""
    from .visibility import is_msp_staff
    if is_msp_staff(user):
        from .routing.engine import assignment_problem
        problem = assignment_problem(user, ticket)
    else:
        from accounts.models import Membership
        own = Membership.objects.filter(user=user, organization_id=ticket.organization_id, is_active=True).exists()
        problem = None if own else 'not a member of this customer'
    if problem:
        raise ActionSkipped(f'add_watcher: {user.username} was not added ({problem})')


def _create_charge_row(Charge, ticket, client, description, amount, action, is_credit, date_cls):
    return Charge.objects.create(
        organization=ticket.organization,
        client_org=client,
        description=description,
        amount=amount,
        currency=action.get('currency') or 'USD',
        charge_date=date_cls.today(),
        is_credit=is_credit,
        recurrence='once',
        notes=f'Auto-created by workflow rule for ticket {ticket.ticket_number}',
    )


# ---- Pool assignment pickers (read-only; shared with the dry run) -----------

def pick_round_robin(ticket, action) -> User:
    """The active staff user (optionally in `group`) who may be given this
    ticket and was assigned least recently; never-assigned users first, then
    lowest pk. Raises ActionSkipped when nobody qualifies. Reads only."""
    from .models import Ticket as _T
    from django.db.models import Max
    candidates = User.objects.filter(is_active=True, is_staff=True)
    grp = action.get('group')
    if grp:
        candidates = candidates.filter(groups__name=grp)
    candidates = _assignable(ticket, candidates)
    if not candidates:
        raise ActionSkipped('assign_round_robin: no technician in the pool may be given this customer\'s tickets')
    last_assigned = (_T.objects
                     .filter(assigned_to__in=candidates)
                     .values('assigned_to_id')
                     .annotate(latest=Max('updated_at')))
    latest_by_user = {r['assigned_to_id']: r['latest'] for r in last_assigned}
    return sorted(
        candidates,
        key=lambda u: (
            latest_by_user.get(u.id) is not None,
            latest_by_user.get(u.id),
            u.id,
        ),
    )[0]


def _least_loaded(candidates, allowed):
    from django.db.models import Count, Q as _Q
    return candidates.filter(pk__in=allowed).annotate(
        open_count=Count('psa_assigned_tickets',
                         filter=~_Q(psa_assigned_tickets__status__is_terminal=True)),
    ).order_by('open_count', 'id').first()


def pick_skill_match(ticket, action) -> User:
    """A member of the action's `skill_group` who may be given this ticket,
    fewest open tickets first. Reads only."""
    skill = (action.get('skill_group') or '').strip()
    if not skill:
        raise ValueError('assign_skill_match requires "skill_group"')
    candidates = User.objects.filter(is_active=True, is_staff=True, groups__name=skill)
    allowed = [u.pk for u in _assignable(ticket, candidates)]
    if not allowed:
        raise ActionSkipped('assign_skill_match: no technician in the group may be given this customer\'s tickets')
    return _least_loaded(candidates, allowed)


def pick_load_balanced(ticket, action) -> User:
    """The active staff user (optionally in `group`) with the fewest open
    tickets who may be given this ticket. Reads only."""
    candidates = User.objects.filter(is_active=True, is_staff=True)
    grp = action.get('group')
    if grp:
        candidates = candidates.filter(groups__name=grp)
    allowed = [u.pk for u in _assignable(ticket, candidates)]
    if not allowed:
        raise ActionSkipped('assign_load_balanced: no technician in the pool may be given this customer\'s tickets')
    return _least_loaded(candidates, allowed)


def parse_charge_amount(action):
    """The create_charge amount as a positive Decimal (ValueError otherwise)."""
    from decimal import Decimal as _D
    try:
        amount = _D(str(action.get('amount') or '0'))
    except Exception:
        raise ValueError('create_charge: invalid "amount"')
    if amount <= 0:
        raise ValueError('create_charge: "amount" must be positive')
    return amount


def find_chained_rule(ticket, name):
    """The active rule `name` a fire_rule step on this ticket runs: MSP-wide
    or the ticket's own customer's (None when there is none)."""
    from .models import WorkflowRule
    from django.db.models import Q
    return WorkflowRule.objects.filter(
        Q(organization__isnull=True) | Q(organization_id=ticket.organization_id),
        name=name, is_active=True,
    ).first()


def in_dry_run() -> bool:
    """True while psa.workflow_dry_run is planning on this thread."""
    return bool(getattr(_chain_state, 'dry_run', False))


class DryRunViolation(RuntimeError):
    """Something tried to run a workflow action during a dry run."""


def run_action(ticket, action: Dict[str, Any]) -> None:
    """Run a single action dict against a ticket. Raises on bad input.
    Inside a rule firing, the step and its result go to the run log
    (psa.workflow_runs, roadmap 91.2)."""
    if in_dry_run():
        raise DryRunViolation('workflow actions cannot run during a dry run')
    from . import workflow_runs
    entry = workflow_runs.action_started(action, len(_chain()))
    try:
        _run_action(ticket, action)
    except ActionSkipped as exc:
        workflow_runs.action_done(entry, 'refused', exc)
        raise
    except Exception as exc:
        workflow_runs.action_done(entry, 'error', exc)
        raise
    workflow_runs.action_done(entry, 'ok')


def _run_action(ticket, action: Dict[str, Any]) -> None:
    if in_dry_run():
        # Roadmap 91.3: a dry run plans actions, it never carries them out.
        raise DryRunViolation('workflow actions cannot run during a dry run')
    used = 0
    if _chain():  # inside a rule firing: count against the event's budget
        used = getattr(_chain_state, 'actions', 0) + 1
        _chain_state.actions = used
    if used > MAX_ACTIONS_PER_EVENT:
        raise BudgetExceeded(f'more than {MAX_ACTIONS_PER_EVENT} workflow actions for one ticket '
                             'event; the remaining actions were not run')
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
            _check_assignee(ticket, u, 'assign_to')
            ticket.assigned_to = u
            ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'add_watcher':
        u = _resolve_user(action.get('username'))
        if u:
            _check_watcher(ticket, u)
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
        # Phase 14 v8 (v3.17.287): the pool member assigned least recently.
        ticket.assigned_to = pick_round_robin(ticket, action)
        ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'assign_skill_match':
        # Phase 14 v8 (v3.17.287): a member of `skill_group`, fewest open
        # tickets first.
        ticket.assigned_to = pick_skill_match(ticket, action)
        ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'assign_load_balanced':
        # Phase 14 v8 (v3.17.287): fewest currently-open assigned tickets.
        ticket.assigned_to = pick_load_balanced(ticket, action)
        ticket.save(update_fields=['assigned_to', 'updated_at'])

    elif atype == 'create_charge':
        # Phase 14 v11 (v3.17.289): cross-module — when a ticket workflow
        # decides to bill the client (e.g. after-hours emergency, expedited
        # part), record a one-off Charge against the ticket's organization.
        from datetime import date as _d
        from .models import Charge as _C
        amount = parse_charge_amount(action)
        description = (action.get('description') or
                        f'Auto-charge for ticket {ticket.ticket_number}')[:300]
        is_credit = bool(action.get('is_credit'))
        # The MSP tenant that owns the workflow rule = ticket.organization;
        # the client to bill is the same since tickets are filed against
        # the client_org. Some installs use a separate `organization` for
        # the MSP and `client_org` for the customer; default to ticket.organization
        # for both, which works for single-tenant SaaS.
        client = getattr(ticket, 'client_org', None) or ticket.organization
        # Billing once per (rule, ticket), whatever re-fires the rule
        # (security review SR-01). The key row is claimed first, inside the
        # same transaction as the charge, so two concurrent firings cannot
        # both bill.
        from django.db import IntegrityError, transaction
        from .models import WorkflowCharge as _WC
        chain = _chain()
        if not chain or not ticket.pk:
            raise ActionSkipped('create_charge: only a saved workflow rule can create a charge')
        rule_pk = chain[-1]
        if _WC.objects.filter(rule_id=rule_pk, ticket_id=ticket.pk).exists():
            raise ActionSkipped(f'create_charge: ticket {ticket.ticket_number} was already charged by this rule')
        try:
            with transaction.atomic():
                key = _WC.objects.create(rule_id=rule_pk, ticket_id=ticket.pk)
                key.charge = _create_charge_row(_C, ticket, client, description, amount,
                                                action, is_credit, _d)
                key.save(update_fields=['charge'])
        except IntegrityError:
            raise ActionSkipped(f'create_charge: ticket {ticket.ticket_number} was already charged by this rule')
        logger.info('workflow rule %s charged ticket %s (%s %s)', rule_pk, ticket.pk,
                    amount, action.get('currency') or 'USD')

    elif atype == 'fire_rule':
        # Phase 14 v4 (v3.17.285): multi-step orchestration. Chain
        # to another WorkflowRule by name within the same org.
        # Loop / depth protection: the per-thread chain (_chain) below.
        name = (action.get('name') or '').strip()
        if not name:
            raise ValueError('fire_rule requires "name"')
        nxt = find_chained_rule(ticket, name)
        if nxt is None:
            raise ValueError(f'fire_rule: no active rule named {name!r}')
        chain = _chain()
        if nxt.pk in chain:
            raise LoopRefused(f'fire_rule: {name!r} is already running in this chain (loop)')
        if len(chain) >= MAX_CHAIN_DEPTH:
            raise LoopRefused(f'fire_rule: chain deeper than {MAX_CHAIN_DEPTH} rules')
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
    if in_dry_run():
        return 0

    chain = _chain()
    if not chain:
        # A new top-level event: a fresh action budget.
        _chain_state.actions = 0
    elif len(chain) >= MAX_CHAIN_DEPTH:
        logger.warning('workflow: %s for ticket %s not run, %d rules already running',
                       trigger, ticket.pk, len(chain))
        return 0

    # Match MSP-wide rules (organization IS NULL) AND rules scoped to this
    # ticket's client organization.
    rules = WorkflowRule.objects.filter(
        Q(organization__isnull=True) | Q(organization_id=ticket.organization_id),
        trigger=trigger,
        is_active=True,
    ).order_by('sort_order', 'pk')

    from .models import WorkflowRuleFiring
    from . import workflow_runs

    fired = 0
    for rule in rules:
        if rule.pk in chain:
            # The rule's own action saved the ticket, which fires the
            # trigger again: running it now would re-enter it (SR-01).
            workflow_runs.note_reentry(rule.pk)
            continue
        run = None
        try:
            # Phase 14 v3 (v3.17.286): once-per-(rule,ticket) guard for
            # SLA tick rules so cron-driven fires don't spam.
            if (getattr(rule, 'fire_once_per_ticket', False)
                    and ticket.pk
                    and WorkflowRuleFiring.objects.filter(
                        rule=rule, ticket=ticket).exists()):
                continue

            branch_name = 'then'
            if matches(ticket, rule.conditions or {}):
                branch = rule.actions or []
            elif rule.else_actions:
                # Phase 14 v2 (v3.17.285): conditional routing — when
                # the main condition fails AND else_actions are
                # configured, run them instead. This still counts as
                # a "fire" so the cooldown / fire_count tracks both
                # branches.
                branch = rule.else_actions
                branch_name = 'else'
            else:
                continue
            run = workflow_runs.begin(rule, ticket, trigger, branch, chain, branch_name)
            chain.append(rule.pk)
            skipped = []
            try:
                for action in branch:
                    try:
                        run_action(ticket, action)
                    except ActionSkipped as exc:
                        skipped.append(str(exc))
            finally:
                chain.pop()
            rule.last_fired_at = timezone.now()
            rule.fire_count = (rule.fire_count or 0) + 1
            rule.last_error = '; '.join(skipped)[:1000]
            rule.save(update_fields=['last_fired_at', 'fire_count', 'last_error'])

            if getattr(rule, 'fire_once_per_ticket', False) and ticket.pk:
                WorkflowRuleFiring.objects.get_or_create(
                    rule=rule, ticket=ticket,
                )
            fired += 1
            workflow_runs.finish(run)
        except Exception as exc:
            workflow_runs.finish(run, error=exc)
            logger.exception('workflow rule %s failed', rule.pk)
            rule.last_error = str(exc)[:1000]
            rule.save(update_fields=['last_error'])
    return fired
