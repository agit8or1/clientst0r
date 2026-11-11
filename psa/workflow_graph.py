"""Workflow rules as multi-step flows (Phase 14, visual workflow builder).

A workflow in this codebase is a WorkflowRule plus the rules it chains to:

    trigger -> if <conditions> -> then <actions> | otherwise <else_actions>

and a ``fire_rule`` action runs another rule's branch inline (its own
condition decides which of its branches runs). This module turns rules into
that tree for the flow view and the builder, and validates a definition
before it is saved: unknown action types, missing action settings,
``fire_rule`` targets that don't exist, and chains that loop back on
themselves (which the engine refuses at run time as well).

Nothing here changes the stored shape: ``conditions`` / ``actions`` /
``else_actions`` stay the JSON the engine has always read.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

ACTION_LABELS = {
    'set_priority': 'Set priority',
    'set_queue': 'Set queue',
    'assign_to': 'Assign to user',
    'add_watcher': 'Add watcher',
    'add_internal_note': 'Add internal note',
    'add_tag': 'Add tag',
    'assign_round_robin': 'Assign round-robin',
    'assign_skill_match': 'Assign by skill group',
    'assign_load_balanced': 'Assign least-loaded',
    'create_charge': 'Add a charge',
    'fire_rule': 'Run another rule',
}
# action type -> keys that must be present and non-empty
REQUIRED_KEYS = {
    'set_priority': ('code',), 'set_queue': ('name',), 'assign_to': ('username',),
    'add_watcher': ('username',), 'add_internal_note': ('body',), 'add_tag': ('tag',),
    'assign_skill_match': ('skill_group',), 'fire_rule': ('name',), 'create_charge': ('amount',),
}
CONDITION_LABELS = {
    'priority': 'Priority', 'queue': 'Queue', 'status': 'Status', 'ticket_type': 'Ticket type',
    'is_unassigned': 'Is unassigned', 'is_paused': 'SLA paused', 'subject': 'Subject',
    'subject_contains': 'Subject contains', 'sla_pct_at_least': 'SLA elapsed at least (%)',
    'sla_pct_elapsed': 'SLA elapsed (%)',
}
MAX_DEPTH = 8  # same cap the engine enforces on fire_rule chains


def describe_condition(cond) -> List[str]:
    """Human-readable lines for a condition dict (empty = always)."""
    if not cond:
        return ['Always']
    if not isinstance(cond, dict):
        return ['(invalid condition)']
    out = []
    for key, val in cond.items():
        if key in ('any', 'all'):
            parts = [' and '.join(describe_condition(c)) for c in (val or [])]
            joiner = ' OR ' if key == 'any' else ' AND '
            out.append('(' + joiner.join(parts) + ')' if parts else 'Always')
            continue
        op, base = '=', key
        if key.endswith('__in'):
            op, base = 'is one of', key[:-4]
            val = ', '.join(str(v) for v in (val or []))
        elif key.endswith('__not'):
            op, base = 'is not', key[:-5]
        elif key in ('subject_contains', 'sla_pct_at_least'):
            op = ''
        label = CONDITION_LABELS.get(base, base)
        if isinstance(val, bool):
            val = 'yes' if val else 'no'
        out.append(f'{label} {op} {val}'.replace('  ', ' ').strip())
    return out


def describe_action(action) -> str:
    if not isinstance(action, dict):
        return '(invalid action)'
    atype = action.get('type', '')
    label = ACTION_LABELS.get(atype, atype or '(no type)')
    detail = {k: v for k, v in action.items() if k != 'type'}
    if not detail:
        return label
    return f'{label}: ' + ', '.join(f'{v}' if len(detail) == 1 else f'{k}={v}' for k, v in detail.items())


def _rules_visible_to(rule_org_id):
    """Rules a fire_rule in a rule of this scope can reach (same lookup as
    the engine: MSP-wide rules plus the ticket organization's rules)."""
    from django.db.models import Q
    from .models import WorkflowRule
    qs = WorkflowRule.objects.filter(is_active=True)
    if rule_org_id:
        qs = qs.filter(Q(organization__isnull=True) | Q(organization_id=rule_org_id))
    return qs


def resolve_target(name: str, rule_org_id, *, overrides=None):
    """The rule a ``fire_rule`` named ``name`` reaches from a rule scoped to
    ``rule_org_id`` (None = MSP-wide). MSP-wide callers can reach per-client
    rules only on that client's tickets; those are returned with
    ``conditional=True``. ``overrides`` maps pk -> unsaved rule stand-ins."""
    name = (name or '').strip()
    if not name:
        return None, False
    for stand_in in (overrides or {}).values():
        if stand_in.name == name and stand_in.is_active and (
                stand_in.organization_id in (None, rule_org_id) or rule_org_id is None):
            return stand_in, bool(rule_org_id is None and stand_in.organization_id)
    qs = _rules_visible_to(rule_org_id).filter(name=name).order_by('organization_id', 'sort_order', 'pk')
    if overrides:
        qs = qs.exclude(pk__in=[k for k in overrides if k])
    target = qs.filter(organization__isnull=True).first() or qs.first()
    if target is None:
        return None, False
    return target, bool(rule_org_id is None and target.organization_id)


def _branch(rule, actions, path, depth, overrides, scope_org_id):
    steps = []
    for action in actions or []:
        step = {'label': describe_action(action), 'type': (action or {}).get('type', '')
                if isinstance(action, dict) else '', 'problem': '', 'sub': None}
        if not isinstance(action, dict) or step['type'] not in ACTION_LABELS:
            step['problem'] = 'unknown action type'
        elif step['type'] == 'fire_rule':
            target, conditional = resolve_target(action.get('name'), scope_org_id, overrides=overrides)
            if target is None:
                step['problem'] = f'no active rule named "{action.get("name") or ""}"'
            elif (target.pk or id(target)) in path:
                step['problem'] = f'loops back to "{target.name}"'
            elif depth >= MAX_DEPTH:
                step['problem'] = f'chain deeper than {MAX_DEPTH} steps'
            else:
                step['sub'] = _flow(target, path | {target.pk or id(target)}, depth + 1, overrides,
                                    scope_org_id or target.organization_id)
                if conditional:
                    step['note'] = f'only on tickets of {target.organization}'
        steps.append(step)
    return steps


def _flow(rule, path, depth, overrides, scope_org_id):
    return {
        'rule': rule,
        'conditions': describe_condition(rule.conditions or {}),
        'then': _branch(rule, rule.actions, path, depth, overrides, scope_org_id),
        'else': _branch(rule, rule.else_actions, path, depth, overrides, scope_org_id),
    }


def build_flow(rule, *, overrides=None) -> Dict[str, Any]:
    """The rule as a tree: conditions, then-steps, else-steps; fire_rule
    steps carry the chained rule's tree in ``sub``."""
    return _flow(rule, {rule.pk or id(rule)}, 0, overrides or {}, rule.organization_id)


def problems(flow) -> List[str]:
    out = []

    def walk(node, prefix):
        for branch in ('then', 'else'):
            for step in node[branch]:
                if step['problem']:
                    out.append(f'{prefix}{"Then" if branch == "then" else "Otherwise"} → '
                               f'{step["label"]}: {step["problem"]}')
                if step['sub']:
                    walk(step['sub'], f'{prefix}{step["sub"]["rule"].name} › ')
    walk(flow, '')
    return out


def validate(name, conditions, actions, else_actions, *, rule=None, organization=None) -> List[str]:
    """Errors that should stop a save. ``rule`` is the rule being edited
    (None for a new one); its new definition is used in place of the saved
    one, so a loop through the edited rule is caught before saving."""
    from .models import WorkflowRule
    errors = []
    if not isinstance(conditions, dict):
        errors.append('Conditions must be a JSON object.')
    for label, acts in (('Then', actions), ('Otherwise', else_actions)):
        if not isinstance(acts, list):
            errors.append(f'{label} actions must be a JSON list.')
            continue
        for n, a in enumerate(acts, 1):
            if not isinstance(a, dict) or a.get('type') not in ACTION_LABELS:
                errors.append(f'{label} step {n}: unknown action type '
                              f'"{a.get("type") if isinstance(a, dict) else a}".')
                continue
            missing = [k for k in REQUIRED_KEYS.get(a['type'], ()) if a.get(k) in (None, '')]
            if missing:
                errors.append(f'{label} step {n} ({ACTION_LABELS[a["type"]]}) needs {", ".join(missing)}.')
    if errors:
        return errors
    stand_in = WorkflowRule(pk=rule.pk if rule else None, name=name, conditions=conditions,
                            actions=actions, else_actions=else_actions, is_active=True,
                            organization=organization)
    overrides = {stand_in.pk: stand_in} if stand_in.pk else {None: stand_in}
    for p in problems(build_flow(stand_in, overrides=overrides)):
        errors.append(p)
    return errors


def rule_choices(exclude_pk=None) -> Iterable[str]:
    from .models import WorkflowRule
    qs = WorkflowRule.objects.filter(is_active=True)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return sorted(set(qs.values_list('name', flat=True)))


def chained_into(rules) -> set:
    """Names of rules some other rule runs via fire_rule."""
    names = set()
    for r in rules:
        for a in list(r.actions or []) + list(r.else_actions or []):
            if isinstance(a, dict) and a.get('type') == 'fire_rule' and a.get('name'):
                names.add(a['name'])
    return names
