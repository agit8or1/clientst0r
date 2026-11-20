"""Workflow rule dry run (roadmap 91.3).

Shows what one rule would do to a chosen ticket on a chosen event, without
doing any of it: each condition with the ticket's actual value and whether it
passes, then the actions of the branch that would run, in order, with their
settings resolved ("would assign to jdoe", "would add charge 25.00 USD -
skipped: this rule already charged this ticket", chained rules expanded).

How side effects are kept out
  * Nothing here calls psa.workflow_engine.run_action / fire. Every action
    type has a planner function in PLANNERS that only reads; an action type
    without one is reported as "cannot preview" and is never run.
  * While planning, the engine's thread-local dry-run flag is set, so
    run_action and fire refuse to do anything (DryRunViolation / 0 rules)
    should any code path reach them.
  * The planners work on a copy of the ticket whose save() and delete()
    raise, so an in-memory change (a new priority, say, which a chained rule's
    condition then sees) can never be written back. Nothing is saved, so no
    signal, e-mail, webhook, PSA push or scheduler job can be set off.
  * No run log entry (WorkflowRuleRun), firing marker, charge key, fire count
    or last error is written. The caller may audit-log that a dry run took
    place; that is the only write.

What it does not show: other rules on the same event (they may run before
this one), and rules that this rule's changes would set off through the
ticket's save signal ("Ticket updated"). The page says so.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from . import workflow_engine as eng
from .workflow_graph import ACTION_LABELS, CONDITION_LABELS
from .workflow_runs import summarize


# --- results ---------------------------------------------------------------------

WOULD = 'would'          # the action would change something
NOOP = 'noop'            # it would run but change nothing
SKIPPED = 'skipped'      # refused, the rule's other actions still run (ActionSkipped)
ERROR = 'error'          # the engine would raise: the rule stops here
CANNOT = 'cannot'        # no planner: cannot preview, not run
NOT_RUN = 'not_run'      # never reached (budget, an earlier error)


class _Stop(Exception):
    """The engine would abort the rule here (an error that is not ActionSkipped)."""


class _ReadOnlyTicket(Exception):
    pass


def _refuse(*args, **kwargs):
    raise _ReadOnlyTicket('dry run: the ticket is read-only')


def _working_copy(ticket):
    """A copy of the ticket the planners may change in memory; save() and
    delete() raise, so it cannot be written back."""
    sim = copy.copy(ticket)
    sim.tags = list(ticket.tags or [])
    sim.save = _refuse
    sim.delete = _refuse
    sim.refresh_from_db = _refuse
    return sim


@contextmanager
def _dry_run_flag():
    state = eng._chain_state
    previous = getattr(state, 'dry_run', False)
    state.dry_run = True
    try:
        yield
    finally:
        state.dry_run = previous


# --- conditions --------------------------------------------------------------------

def _shown(value):
    if value is None:
        return '(none)'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float):
        return f'{value:.0f}'
    return str(value)


def explain(ticket, condition) -> Dict[str, Any]:
    """The condition as a tree of {label, actual, expected, passed, children},
    following psa.workflow_engine.matches step for step."""
    if not condition:
        return {'label': 'No conditions (always matches)', 'passed': True, 'children': []}
    if not isinstance(condition, dict):
        return {'label': 'Invalid condition (never matches)', 'passed': False, 'children': []}
    # matches(): a combinator key decides on its own, other keys are ignored.
    for key, label in (('any', 'Any of'), ('all', 'All of')):
        if key in condition:
            children = [explain(ticket, c) for c in (condition.get(key) or [])]
            passed = (any if key == 'any' else all)(c['passed'] for c in children)
            return {'label': label, 'passed': passed, 'children': children}

    children = []
    if 'subject_contains' in condition:
        needle = (condition['subject_contains'] or '')
        passed = not needle or needle.lower() in (ticket.subject or '').lower()
        children.append({'label': CONDITION_LABELS['subject_contains'], 'expected': needle,
                         'actual': ticket.subject or '', 'passed': passed})
    if 'sla_pct_at_least' in condition:
        try:
            threshold = float(condition['sla_pct_at_least'])
        except (TypeError, ValueError):
            threshold = None
        pct = eng._sla_pct_elapsed(ticket)
        children.append({'label': CONDITION_LABELS['sla_pct_at_least'],
                         'expected': _shown(condition['sla_pct_at_least']), 'actual': _shown(float(pct)),
                         'passed': threshold is not None and pct >= threshold})
    for key, val in condition.items():
        if key in ('any', 'all', 'subject_contains', 'sla_pct_at_least'):
            continue
        if key.endswith('__in'):
            base, op = key[:-4], 'is one of'
            cur = eng._get(ticket, base)
            passed = cur in (val or [])
            expected = ', '.join(_shown(v) for v in (val or [])) or '(nothing)'
        elif key.endswith('__not'):
            base, op = key[:-5], 'is not'
            cur = eng._get(ticket, base)
            passed = cur != val
            expected = _shown(val)
        else:
            base, op = key, 'is'
            cur = eng._get(ticket, key)
            passed = cur == val
            expected = _shown(val)
        children.append({'label': f'{CONDITION_LABELS.get(base, base)} {op}', 'expected': expected,
                         'actual': _shown(cur), 'passed': passed})
    if len(children) == 1:
        return children[0] | {'children': []}
    return {'label': 'All of', 'passed': all(c['passed'] for c in children), 'children': children}


def _matches(ticket, condition):
    """(passed, tree). The engine's own matches() decides; the tree explains."""
    tree = explain(ticket, condition)
    passed = eng.matches(ticket, condition or {})
    tree['passed'] = passed
    return passed, tree


# --- planning context --------------------------------------------------------------

class _Plan:
    def __init__(self, ticket, user):
        self.ticket = ticket
        self.user = user
        self.chain: List[int] = []
        self.used = 0
        self.steps: List[Dict[str, Any]] = []
        self.stopped: Optional[str] = None
        from .workflow_access import client_scope
        self.scope = client_scope(user) if user is not None else None

    def add(self, action, status, message, depth, **extra):
        atype = (action or {}).get('type', '') if isinstance(action, dict) else ''
        step = {'type': atype or '(none)', 'label': ACTION_LABELS.get(atype, atype or 'Unknown step'),
                'params': summarize(action) if isinstance(action, dict) else '',
                'status': status, 'message': message, 'depth': depth}
        step.update(extra)
        self.steps.append(step)
        return step


# --- planners (read only) ---------------------------------------------------------
# Each takes (plan, sim_ticket, action) and returns (status, message). They may
# change the in-memory working copy so later steps see the new values, raise
# eng.ActionSkipped for a refusal, or raise ValueError where the engine would.

def _name(user):
    full = user.get_full_name() if hasattr(user, 'get_full_name') else ''
    return f'{user.username} ({full})' if full else user.username


def _plan_set_priority(plan, t, action):
    from .models import TicketPriority
    code = action.get('code')
    p = TicketPriority.objects.filter(code=code).first()
    if not p:
        return NOOP, f'no priority with code {code!r}: nothing would change'
    before = eng._get(t, 'priority')
    t.priority = p
    if before == p.code:
        return NOOP, f'priority is already {p.code}'
    return WOULD, f'would set priority to {p.code} (now {_shown(before)})'


def _plan_set_queue(plan, t, action):
    from .models import Queue
    name = action.get('name')
    q = Queue.objects.filter(name=name, is_active=True).first()
    if not q:
        return NOOP, f'no active queue named {name!r}: nothing would change'
    before = eng._get(t, 'queue')
    t.queue = q
    if before == q.name:
        return NOOP, f'queue is already {q.name}'
    return WOULD, f'would move to queue {q.name} (now {_shown(before)})'


def _assign(t, user, verb):
    before = t.assigned_to if t.assigned_to_id else None
    t.assigned_to = user
    if before is not None and before.pk == user.pk:
        return NOOP, f'already assigned to {_name(user)}'
    now = _name(before) if before is not None else 'unassigned'
    return WOULD, f'would assign to {_name(user)}{verb} (now {now})'


def _plan_assign_to(plan, t, action):
    u = eng._resolve_user(action.get('username'))
    if not u:
        return NOOP, f'no active user named {action.get("username")!r}: nothing would change'
    eng._check_assignee(t, u, 'assign_to')
    return _assign(t, u, '')


def _plan_add_watcher(plan, t, action):
    from .models import TicketWatcher
    u = eng._resolve_user(action.get('username'))
    if not u:
        return NOOP, f'no active user named {action.get("username")!r}: nothing would change'
    eng._check_watcher(t, u)
    if t.pk and TicketWatcher.objects.filter(ticket_id=t.pk, user=u).exists():
        return NOOP, f'{_name(u)} is already watching'
    return WOULD, f'would add {_name(u)} as a watcher'


def _plan_add_internal_note(plan, t, action):
    body = (action.get('body') or '').strip()
    if not body:
        return NOOP, 'empty note: nothing would be added'
    shown = body if len(body) <= 120 else body[:117] + '...'
    return WOULD, f'would add an internal note: "{shown}"'


def _plan_add_tag(plan, t, action):
    tag = (action.get('tag') or '').strip()
    if not tag:
        return NOOP, 'empty tag: nothing would change'
    if tag in t.tags:
        return NOOP, f'already tagged {tag!r}'
    t.tags.append(tag)
    return WOULD, f'would add tag {tag!r}'


def _plan_round_robin(plan, t, action):
    return _assign(t, eng.pick_round_robin(t, action), ' (assigned least recently)')


def _plan_skill_match(plan, t, action):
    return _assign(t, eng.pick_skill_match(t, action),
                   f' (group {action.get("skill_group")}, fewest open tickets)')


def _plan_load_balanced(plan, t, action):
    return _assign(t, eng.pick_load_balanced(t, action), ' (fewest open tickets)')


def _plan_create_charge(plan, t, action):
    from .models import WorkflowCharge
    amount = eng.parse_charge_amount(action)
    currency = action.get('currency') or 'USD'
    if not plan.chain or not t.pk:
        raise eng.ActionSkipped('create_charge: only a saved workflow rule can create a charge')
    rule_pk = plan.chain[-1]
    if WorkflowCharge.objects.filter(rule_id=rule_pk, ticket_id=t.pk).exists():
        raise eng.ActionSkipped(f'would add charge {amount} {currency} - skipped: ticket '
                                f'{t.ticket_number} was already charged once by this rule')
    client = getattr(t, 'client_org', None) or t.organization
    description = (action.get('description') or f'Auto-charge for ticket {t.ticket_number}')[:300]
    kind = 'credit' if action.get('is_credit') else 'charge'
    return WOULD, f'would add {kind} {amount} {currency} to {client.name}: "{description}" (once per ticket)'


def _plan_fire_rule(plan, t, action):
    name = (action.get('name') or '').strip()
    if not name:
        raise ValueError('fire_rule requires "name"')
    nxt = eng.find_chained_rule(t, name)
    if nxt is None:
        raise ValueError(f'fire_rule: no active rule named {name!r}')
    if plan.scope is not None and nxt.organization_id is not None and nxt.organization_id not in plan.scope:
        # Cannot happen for a ticket in scope (the lookup is limited to the
        # ticket's customer); kept so a chained rule the viewer may not see is
        # never described.
        return CANNOT, "would run another rule (only on another customer's tickets; not shown)"
    if nxt.pk in plan.chain:
        raise eng.LoopRefused(f'fire_rule: {name!r} is already running in this chain (loop)')
    if len(plan.chain) >= eng.MAX_CHAIN_DEPTH:
        raise eng.LoopRefused(f'fire_rule: chain deeper than {eng.MAX_CHAIN_DEPTH} rules')
    passed, tree = _matches(t, nxt.conditions or {})
    branch = (nxt.actions or []) if passed else (nxt.else_actions or [])
    which = 'conditions match, its actions' if passed else (
        'conditions do not match, its otherwise actions' if branch else 'conditions do not match, nothing')
    return WOULD, f'would run rule "{nxt.name}" ({which})', (nxt, tree, branch)


PLANNERS = {
    'set_priority': _plan_set_priority,
    'set_queue': _plan_set_queue,
    'assign_to': _plan_assign_to,
    'add_watcher': _plan_add_watcher,
    'add_internal_note': _plan_add_internal_note,
    'add_tag': _plan_add_tag,
    'assign_round_robin': _plan_round_robin,
    'assign_skill_match': _plan_skill_match,
    'assign_load_balanced': _plan_load_balanced,
    'create_charge': _plan_create_charge,
    'fire_rule': _plan_fire_rule,
}


def _plan_actions(plan, t, actions, depth):
    for action in actions:
        if plan.stopped:
            plan.add(action, NOT_RUN, 'not reached', depth)
            continue
        plan.used += 1
        if plan.used > eng.MAX_ACTIONS_PER_EVENT:
            plan.stopped = (f'more than {eng.MAX_ACTIONS_PER_EVENT} workflow actions for one ticket event; '
                            'the remaining actions would not run')
            plan.add(action, NOT_RUN, plan.stopped, depth)
            continue
        atype = action.get('type', '') if isinstance(action, dict) else ''
        planner = PLANNERS.get(atype)
        if planner is None:
            plan.add(action, CANNOT,
                     'cannot preview this action: the dry run does not know it, so it was not run. '
                     'The real rule would stop with an error here if the engine does not know it either.',
                     depth)
            continue
        try:
            result = planner(plan, t, action)
        except eng.ActionSkipped as exc:
            plan.add(action, SKIPPED, str(exc), depth)
            continue
        except Exception as exc:  # the engine would raise: the rule stops
            plan.stopped = f'the rule would stop here: {exc}'
            plan.add(action, ERROR, str(exc), depth)
            continue
        status, message = result[0], result[1]
        if len(result) == 3:
            nxt, tree, branch = result[2]
            plan.add(action, status, message, depth, rule=nxt, conditions=tree)
            plan.chain.append(nxt.pk)
            try:
                _plan_actions(plan, t, branch, depth + 1)
            finally:
                plan.chain.pop()
        else:
            plan.add(action, status, message, depth)


# --- entry point ---------------------------------------------------------------

def triggers_for(rule) -> List[str]:
    """The events this rule listens to (one per rule today)."""
    return [rule.trigger] if rule.trigger else []


def dry_run(rule, ticket, trigger, user=None) -> Dict[str, Any]:
    """What `rule` would do to `ticket` on `trigger`. Reads only."""
    from .models import WorkflowRuleFiring
    labels = dict(rule.TRIGGER_CHOICES)
    result: Dict[str, Any] = {
        'rule': rule, 'ticket': ticket, 'trigger': trigger,
        'trigger_label': labels.get(trigger, trigger), 'blockers': [], 'steps': [],
        'stopped': None, 'branch': None,
    }
    with _dry_run_flag():
        sim = _working_copy(ticket)
        if trigger not in triggers_for(rule):
            result['blockers'].append(f'This rule does not listen to "{labels.get(trigger, trigger)}".')
        if not rule.is_active:
            result['blockers'].append('This rule is inactive, so it would not run.')
        if rule.organization_id is not None and rule.organization_id != ticket.organization_id:
            result['blockers'].append(f'This rule only runs on {rule.organization.name} tickets.')
        if (getattr(rule, 'fire_once_per_ticket', False) and ticket.pk
                and WorkflowRuleFiring.objects.filter(rule=rule, ticket_id=ticket.pk).exists()):
            result['blockers'].append('This rule runs once per ticket and has already run on this ticket.')

        passed, tree = _matches(sim, rule.conditions or {})
        result['matched'] = passed
        result['conditions'] = tree
        if passed:
            branch, result['branch'] = rule.actions or [], 'then'
        elif rule.else_actions:
            branch, result['branch'] = rule.else_actions, 'else'
        else:
            branch = []
        plan = _Plan(ticket, user)
        plan.chain.append(rule.pk)
        _plan_actions(plan, sim, branch, 0)
        result['steps'] = plan.steps
        result['stopped'] = plan.stopped
        result['would_run'] = bool(result['branch']) and not result['blockers']
        result['changes'] = sum(1 for s in plan.steps if s['status'] == WOULD)
    return result
