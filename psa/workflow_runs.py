"""Workflow rule execution log (roadmap 91.2).

Every time a rule's branch runs, psa.workflow_engine.fire() records one
WorkflowRuleRun: the trigger, a fingerprint of the rule's definition at that
moment, the ticket and customer, who caused the event, how long it took, the
outcome, and one entry per action (type, a short settings summary, result,
message). Chained steps (fire_rule) appear in the same run, indented.

Recording is best-effort: every function here swallows its own errors and the
row is written inside a savepoint, so a logging problem never changes what the
rule does or stops the ticket being saved.

Who sees runs: the rule page shows only runs on tickets of customers in the
viewer's client scope (psa.workflow_access.client_scope), so an MSP-wide rule
lists just the runs on tickets the technician can reach.

Retention: runs older than PSA_WORKFLOW_RUN_RETENTION_DAYS (default 30) are
removed, and each rule keeps at most PSA_WORKFLOW_RUNS_PER_RULE (default 500)
of its newest runs. prune() is called by the psa_sla_workflow_tick scheduled
task (every 5 minutes; the prune itself at most once an hour).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger('psa.workflow_runs')

DEFAULT_RETENTION_DAYS = 30
DEFAULT_RUNS_PER_RULE = 500
MAX_ENTRIES = 120
_SECRET_HINTS = ('secret', 'password', 'passwd', 'token', 'key', 'credential', 'auth')

_state = threading.local()


def _stack():
    stack = getattr(_state, 'stack', None)
    if stack is None:
        stack = _state.stack = []
    return stack


def fingerprint(rule) -> str:
    """Short hash of what the rule does; changes whenever its definition does."""
    try:
        body = json.dumps({
            'trigger': rule.trigger, 'organization': rule.organization_id,
            'conditions': rule.conditions or {}, 'actions': rule.actions or [],
            'else_actions': rule.else_actions or [],
            'fire_once_per_ticket': bool(getattr(rule, 'fire_once_per_ticket', False)),
        }, sort_keys=True, default=str)
        return hashlib.sha256(body.encode()).hexdigest()[:12]
    except Exception:
        return ''


def summarize(action) -> str:
    """'key=value' summary of an action's settings, without anything that looks
    like a secret, each value cut short."""
    if not isinstance(action, dict):
        return ''
    parts = []
    for k, v in action.items():
        if k == 'type':
            continue
        if any(h in str(k).lower() for h in _SECRET_HINTS):
            continue
        text = v if isinstance(v, str) else json.dumps(v, default=str)
        text = ' '.join(str(text).split())
        if len(text) > 60:
            text = text[:57] + '...'
        parts.append(f'{k}={text}')
    return ', '.join(parts)[:240]


class _Recorder:
    def __init__(self, rule, ticket, trigger, branch, chain, branch_name):
        self.rule = rule
        self.ticket = ticket
        self.trigger = trigger
        self.branch_name = branch_name
        self.branch = list(branch or [])
        self.base_depth = len(chain) + 1  # the rule itself is pushed next
        self.via_rule_id = chain[-1] if chain else None
        self.started_at = timezone.now()
        self.t0 = time.monotonic()
        self.entries = []
        self.reentry_blocked = 0
        self.done = False


def begin(rule, ticket, trigger, branch, chain, branch_name='then'):
    try:
        rec = _Recorder(rule, ticket, trigger, branch, chain, branch_name)
        _stack().append(rec)
        return rec
    except Exception:
        logger.exception('workflow run log: could not start a record for rule %s', getattr(rule, 'pk', None))
        return None


def note_reentry(rule_pk):
    """A rule was not re-run because it is already running (its own save
    re-fired the trigger): counted on that rule's open run."""
    try:
        for rec in reversed(_stack()):
            if rec.rule.pk == rule_pk:
                rec.reentry_blocked += 1
                return
    except Exception:
        pass


def action_started(action, chain_len):
    try:
        stack = _stack()
        if not stack:
            return None
        rec = stack[-1]
        if len(rec.entries) >= MAX_ENTRIES:
            return None
        entry = {
            'type': str((action or {}).get('type', '') if isinstance(action, dict) else '')[:40],
            'summary': summarize(action),
            'depth': max(0, chain_len - rec.base_depth),
            'result': 'ok', 'message': '',
        }
        rec.entries.append(entry)
        return entry
    except Exception:
        return None


def action_done(entry, result, message=''):
    if entry is None:
        return
    try:
        entry['result'] = result
        entry['message'] = str(message or '')[:500]
    except Exception:
        pass


def _outcome(rec, error):
    if error is not None:
        from .workflow_engine import BudgetExceeded, LoopRefused
        if isinstance(error, BudgetExceeded):
            return 'budget'
        if isinstance(error, LoopRefused):
            return 'loop_guard'
        return 'error'
    if any(e['result'] in ('refused', 'error') for e in rec.entries):
        return 'partial'
    return 'ok'


def finish(rec, error=None):
    """Close the record and write it. Idempotent; never raises."""
    if rec is None or rec.done:
        return
    rec.done = True
    try:
        stack = _stack()
        if rec in stack:
            # Pop it and anything a failure left open above it.
            while stack:
                if stack.pop() is rec:
                    break
    except Exception:
        pass
    try:
        if error is not None:
            ran = sum(1 for e in rec.entries if e['depth'] == 0)
            for action in rec.branch[ran:]:
                if len(rec.entries) >= MAX_ENTRIES:
                    break
                rec.entries.append({
                    'type': str(action.get('type', '') if isinstance(action, dict) else '')[:40],
                    'summary': summarize(action), 'depth': 0, 'result': 'skip',
                    'message': 'not run: an earlier step failed',
                })
        _write(rec, error)
    except Exception:
        logger.exception('workflow run log: could not record rule %s', getattr(rec.rule, 'pk', None))


def _actor():
    try:
        from accounts.authz_cache import current_context
        ctx = current_context()
        return getattr(ctx, 'user_id', None) if ctx is not None else None
    except Exception:
        return None


def _write(rec, error):
    from django.db import transaction
    from .models import WorkflowRuleRun
    actor_id = _actor()
    if actor_id:
        label = 'user'
    elif rec.trigger == 'sla_threshold_crossed':
        label = 'scheduler'
    else:
        label = 'system'
    via = ''
    if rec.via_rule_id:
        from .models import WorkflowRule
        via = (WorkflowRule.objects.filter(pk=rec.via_rule_id).values_list('name', flat=True).first() or '')
    ticket = rec.ticket
    with transaction.atomic():
        WorkflowRuleRun.objects.create(
            rule=rec.rule,
            rule_name=(rec.rule.name or '')[:200],
            rule_fingerprint=fingerprint(rec.rule),
            branch=rec.branch_name,
            ticket=ticket if getattr(ticket, 'pk', None) else None,
            ticket_number=(getattr(ticket, 'ticket_number', '') or '')[:32],
            organization_id=getattr(ticket, 'organization_id', None),
            trigger=(rec.trigger or '')[:30],
            actor_id=actor_id,
            actor_label=label,
            via_rule_name=via[:200],
            started_at=rec.started_at,
            finished_at=timezone.now(),
            duration_ms=max(0, int((time.monotonic() - rec.t0) * 1000)),
            outcome=_outcome(rec, error),
            message=(str(error) if error is not None else '')[:1000],
            actions=rec.entries,
            reentry_blocked=rec.reentry_blocked,
        )


# --- reading ---------------------------------------------------------------------

def visible_runs(qs, user):
    """`qs` narrowed to runs on tickets of customers `user` may reach."""
    from . import workflow_access
    if not workflow_access._is_staff(user):
        return qs.none()
    scope = workflow_access.client_scope(user)
    if scope is None:
        return qs
    return qs.filter(organization_id__in=scope)


# --- retention -------------------------------------------------------------------

def prune(days=None, per_rule=None) -> int:
    """Delete runs past the retention window and beyond each rule's cap.
    Returns the number of rows removed."""
    from django.conf import settings
    from django.db.models import Count
    from .models import WorkflowRuleRun
    if days is None:
        days = getattr(settings, 'PSA_WORKFLOW_RUN_RETENTION_DAYS', DEFAULT_RETENTION_DAYS)
    if per_rule is None:
        per_rule = getattr(settings, 'PSA_WORKFLOW_RUNS_PER_RULE', DEFAULT_RUNS_PER_RULE)
    removed = 0
    if days and days > 0:
        removed += WorkflowRuleRun.objects.filter(
            started_at__lt=timezone.now() - timedelta(days=days)).delete()[0]
    if per_rule and per_rule > 0:
        heavy = (WorkflowRuleRun.objects.values('rule_id').annotate(n=Count('id'))
                 .filter(n__gt=per_rule).values_list('rule_id', flat=True))
        for rule_id in list(heavy):
            keep = list(WorkflowRuleRun.objects.filter(rule_id=rule_id)
                        .order_by('-started_at', '-id').values_list('id', flat=True)[:per_rule])
            removed += WorkflowRuleRun.objects.filter(rule_id=rule_id).exclude(id__in=keep).delete()[0]
    return removed


def prune_if_due() -> int:
    """prune() at most once an hour (shared cache flag)."""
    try:
        from django.core.cache import cache
        if not cache.add('psa_workflow_runs_prune', 1, 3600):
            return 0
    except Exception:
        pass
    return prune()
