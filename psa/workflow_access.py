"""Who may see and change PSA workflow rules (roadmap 51.23).

A WorkflowRule is either scoped to one customer (``organization`` set) or
MSP-wide (``organization`` None, runs on every customer's tickets).

Seeing rules (list, flow map, workflow analytics)
  MSP staff only. A technician whose client scope is narrowed
  (UserProfile.client_scope 'selected' / 'assigned') sees the rules of the
  customers in that scope plus the MSP-wide rules, read-only - the same rule
  ``core.tenancy.scope_to_request(include_global=True)`` applies to other
  shared rows. Other customers' rules are a 404.

Changing rules (create, edit, delete, templates)
  The role permission ``psa_manage_workflow_rules`` (accounts permission
  registry), held at the rule's customer (``user_has_org_perm``, which also
  enforces the client scope). An MSP-wide rule affects every customer, so it
  additionally needs an unrestricted client scope. Superusers hold both.

What a rule refers to
  A restricted technician's rule may only name people who can work that
  customer's tickets (assign_to) or watch them (add_watcher), checked with the
  engine's own SR-03 checks. ``fire_rule`` targets are already limited to the
  customer's and MSP-wide rules by workflow_graph.validate.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable, List, Optional, Set

from django.db.models import Q

PERM = 'psa_manage_workflow_rules'


def _active(user) -> bool:
    return bool(user is not None and getattr(user, 'is_authenticated', False)
                and getattr(user, 'is_active', False))


def _is_staff(user) -> bool:
    from .visibility import is_msp_staff
    return _active(user) and is_msp_staff(user)


def client_scope(user) -> Optional[Set[int]]:
    """None = every customer, else the customer ids the technician may reach."""
    from accounts.permission_utils import staff_client_org_ids
    return staff_client_org_ids(user)


def is_restricted(user) -> bool:
    return client_scope(user) is not None


# --- reading -------------------------------------------------------------------

def _visible_scope(user) -> Optional[Set[int]]:
    """Client scope plus the customers where an access group grants the
    workflow rule permission (a group whose role lacks it shows nothing)."""
    from accounts.permission_utils import client_org_ids_for_perm
    return client_org_ids_for_perm(user, PERM)


def visible_rules(qs, user):
    """`qs` narrowed to the rules `user` may see (in-scope + MSP-wide)."""
    if not _is_staff(user):
        return qs.none()
    scope = _visible_scope(user)
    if scope is None:
        return qs
    return qs.filter(Q(organization__isnull=True) | Q(organization_id__in=scope))


def visible_org_ids(user) -> Optional[Set[int]]:
    return _visible_scope(user)


# --- changing ------------------------------------------------------------------

def can_manage(user) -> bool:
    """Page-level capability: may this user manage workflow rules at all."""
    if not _is_staff(user):
        return False
    if user.is_superuser:
        return True
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, PERM)


def can_edit_org(user, org_id) -> bool:
    """May `user` create / edit / delete a rule scoped to `org_id` (None =
    MSP-wide)."""
    if not can_manage(user):
        return False
    if user.is_superuser:
        return True
    if org_id is None:
        return not is_restricted(user)
    from accounts.permission_utils import user_has_org_perm
    return user_has_org_perm(user, org_id, PERM)


def can_edit_rule(user, rule) -> bool:
    return can_edit_org(user, rule.organization_id)


def editable_organizations(user):
    """Active customers `user` may scope a rule to."""
    from core.models import Organization
    qs = Organization.objects.filter(is_active=True).order_by('name')
    if not can_manage(user):
        return qs.none()
    scope = client_scope(user)
    if scope is None:
        return qs
    return qs.filter(pk__in=[o for o in scope if can_edit_org(user, o)])


def editable_rule_ids(user, rules: Iterable) -> Set[int]:
    return {r.pk for r in rules if can_edit_rule(user, r)}


# --- what a rule refers to -------------------------------------------------------

def reference_problems(user, organization, *action_lists) -> List[str]:
    """Errors for actions of a rule scoped to `organization` that name people
    outside that customer. Applied to restricted technicians (unrestricted
    administrators keep today's behaviour; the engine re-checks at run time).
    The message is the same for unknown and out-of-scope users, so the form
    cannot be used to discover other customers' accounts."""
    if organization is None or not is_restricted(user):
        return []
    from django.contrib.auth.models import User
    from .routing.engine import assignment_problem
    from .workflow_engine import ActionSkipped, _check_watcher
    stand_in = SimpleNamespace(organization=organization, organization_id=organization.pk)
    errors = []
    for actions in action_lists:
        for n, action in enumerate(actions or [], 1):
            if not isinstance(action, dict):
                continue
            atype = action.get('type')
            if atype not in ('assign_to', 'add_watcher'):
                continue
            username = (action.get('username') or '').strip()
            target = User.objects.filter(username=username, is_active=True).first() if username else None
            ok = False
            if target is not None:
                if atype == 'assign_to':
                    ok = assignment_problem(target, stand_in) is None
                else:
                    try:
                        _check_watcher(stand_in, target)
                        ok = True
                    except ActionSkipped:
                        ok = False
            if not ok:
                errors.append(f'Step {n} ({atype}): "{username}" cannot work on {organization.name} tickets.')
    return errors


def redact_flow(flow, user):
    """Drop chained sub-flows of rules `user` may not see (an MSP-wide rule can
    chain to any customer's rule) from a workflow_graph flow tree."""
    scope = client_scope(user)
    if scope is None or flow is None:
        return flow
    for branch in ('then', 'else'):
        for step in flow.get(branch, []):
            sub = step.get('sub')
            if not sub:
                continue
            org_id = getattr(sub['rule'], 'organization_id', None)
            if org_id is not None and org_id not in scope:
                step['sub'] = None
                step['label'] = 'Run another rule'
                step['note'] = "only on another customer's tickets"
            else:
                redact_flow(sub, user)
    return flow


def rule_names_for(user, organization_id, exclude_pk=None) -> List[str]:
    """Names a fire_rule step of this user's rule may offer (the dropdown)."""
    from .models import WorkflowRule
    qs = WorkflowRule.objects.filter(is_active=True)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    scope = client_scope(user)
    if scope is not None:
        qs = qs.filter(Q(organization__isnull=True) | Q(organization_id__in=scope))
    return sorted(set(qs.values_list('name', flat=True)))
