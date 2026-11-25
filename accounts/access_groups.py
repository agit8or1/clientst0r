"""
Access groups: named groups of MSP staff that carry one internal role at a
customer scope (tech_access.TechnicianGroup, shown as "Access groups").

What a group grants
  Each member holds the group's role (`role_template`) and the group's
  per-feature permissions (`feature_permissions`, accounts.group_features)
  at the group's customers - every customer (`all_customers`), or the chosen
  customers and their subsidiaries - in addition to their own access: their
  global role inside their client scope, and their memberships. Effective
  access is the union; a group never takes anything away. A group without a
  role or per-feature permissions, a group with no customers and an empty
  group grant nothing. Per-feature permissions never include critical,
  ownership or customer-portal keys (filtered again here when read).

How it is enforced
  Permissions are resolved in one place, accounts.permission_utils
  (user_has_org_perm, user_has_perm, user_has_perm_any_org, orgs_with_perm,
  explain_access) and accounts.scope.grants_for (row scoping). Each of them
  adds the grants listed here, each grant with its own customer scope - one
  group's role is never combined with another grant's customers.
  Row scope stays per permission: `staff_client_org_ids` and
  core.tenancy.accessible_org_ids / scope_to_request are the technician's
  own client scope and never include group customers (callers apply them as
  the row scope of a permission checked once). Group customers are added
  only where the permission is named: orgs_with_perm / filter_by_org_perm,
  accounts.scope, client_org_ids_for_perm, scope_to_request(..., perm=...),
  psa.workflow_access (psa_manage_workflow_rules). The client switcher uses
  navigable_org_ids (scope + group customers), so a member can select a
  group customer; what they may do there is user_has_org_perm's answer, and
  with a customer selected user_has_perm answers for it. MSP-wide checks (one MSP per install: SSO, payment
  gateways, platform integrations, MSP-wide report figures) count a group
  only when it covers every customer, the same rule as a global role.

  Background jobs call the same helpers with no request bound, so they read
  the current rows; inside a request the answers are memoized and dropped
  whenever a group, its members or its customers change (accounts.signals ->
  accounts.authz_cache), so removing a member or deleting a group revokes the
  access at the next check.

What a group never does
  * hold customer (portal) users - every add is refused for anyone who is not
    MSP staff (accounts.signals, and the pages check first);
  * set superuser or Django staff flags;
  * grant an RMM tier: tiers are read from the global role only, and a global
    role with a tier is a protected change (tech_access). A group whose role
    has a tier grants that role's flags, not the tier.

Who manages groups
  `roles_manage` held MSP-wide (superusers always). A group whose role is
  privileged (ownership, critical permissions, an RMM tier) also needs that
  level: `org_owner` for an owner role, `org_manage_privileged` for the rest.
  Nobody but a superuser may manage a group with a role or per-feature
  permissions holding permissions they do not hold MSP-wide themselves, or
  a group they are a member of. The same rule decides who may change a
  group's per-feature permissions (group_features.refusal).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Set

from . import authz_cache


@dataclass(frozen=True)
class GroupGrant:
    group_id: int
    group_name: str
    role: object                      # accounts.RoleTemplate, or None
    org_ids: Optional[FrozenSet[int]]  # None = every customer
    feature_keys: FrozenSet[str] = frozenset()  # per-feature permissions

    def covers(self, org_id) -> bool:
        if self.org_ids is None:
            return True
        return org_id is not None and org_id in self.org_ids

    def holds(self, perm_name) -> bool:
        return self.holds_by_role(perm_name) or perm_name in self.feature_keys

    def holds_by_role(self, perm_name) -> bool:
        return self.role is not None and bool(getattr(self.role, perm_name, False))

    def via(self, perm_name) -> str:
        """How the group grants `perm_name`: 'role', 'feature', 'both' or ''."""
        r, f = self.holds_by_role(perm_name), perm_name in self.feature_keys
        return 'both' if r and f else 'role' if r else 'feature' if f else ''

    @property
    def scope_label(self) -> str:
        return 'All customers' if self.org_ids is None else f'{len(self.org_ids)} customer(s)'


def _eligible(user) -> bool:
    if user is None or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'is_superuser', False):
        return False  # superusers hold everything already
    from psa.visibility import is_msp_staff
    return is_msp_staff(user)


def group_grants(user) -> List[GroupGrant]:
    """The grants `user` holds through access groups (MSP staff only): one
    per group with a role or per-feature permissions."""
    if not _eligible(user):
        return []

    def compute():
        try:
            from tech_access.models import TechnicianGroup
        except Exception:  # pragma: no cover - app not installed
            return []
        from core.utils import descendant_org_ids
        from .group_features import clean
        out = []
        groups = (TechnicianGroup.objects.filter(members=user)
                  .select_related('role_template').prefetch_related('customers').distinct().order_by('name'))
        for g in groups:
            features = frozenset(clean(g.feature_permissions or ()))
            if g.role_template_id is None and not features:
                continue
            if g.all_customers:
                ids = None
            else:
                ids = set()
                for org in g.customers.all():
                    if org.is_active:
                        ids |= set(descendant_org_ids(org.pk))
                ids = frozenset(ids)
            out.append(GroupGrant(g.pk, g.name, g.role_template, ids, features))
        return out
    return authz_cache.memo(('access_groups', user.pk), compute)


def holds_at(user, org_id, perm_name) -> bool:
    """A group grants `perm_name` at `org_id`. `org_id=None` asks for every
    customer at once (MSP-wide): only groups covering all customers count."""
    return any(g.holds(perm_name) and g.covers(org_id) for g in group_grants(user))


def holds_msp_wide(user, perm_name) -> bool:
    return holds_at(user, None, perm_name)


def holds_anywhere(user, perm_name) -> bool:
    return any(g.holds(perm_name) and (g.org_ids is None or g.org_ids) for g in group_grants(user))


def orgs_with_perm(user, perm_name) -> Optional[Set[int]]:
    """Customers where a group grants `perm_name`: None = every customer."""
    out: Set[int] = set()
    for g in group_grants(user):
        if not g.holds(perm_name):
            continue
        if g.org_ids is None:
            return None
        out |= set(g.org_ids)
    return out


def reach(user) -> Optional[Set[int]]:
    """Customers any of the user's groups covers (None = all); empty set when
    the user has no group with a role."""
    out: Set[int] = set()
    for g in group_grants(user):
        if g.org_ids is None:
            return None
        out |= set(g.org_ids)
    return out


def group_features_summary(keys) -> str:
    """'Tickets & queues: Edit, Assets & inventory: View' for explanations."""
    from .group_features import summary
    return ', '.join(f'{label}: {level}' for label, level in summary(keys).items())


def sources_at(user, org_id, perm_name=None) -> List[dict]:
    """For "why does this person have access": one row per group covering
    `org_id` (and holding `perm_name`, when given)."""
    rows = []
    for g in group_grants(user):
        if not g.covers(org_id):
            continue
        parts = []
        if g.role is not None:
            parts.append(f'role {g.role.name}')
        if g.feature_keys:
            parts.append(f'{len(g.feature_keys)} per-feature permission(s)')
        via = g.via(perm_name) if perm_name else ''
        note = 'Adds to the global role and memberships.'
        if via == 'feature':
            note = "Granted by the group's per-feature permissions. " + note
        elif via == 'both':
            note = "Granted by the group's role and its per-feature permissions. " + note
        elif via == 'role':
            note = "Granted by the group's role. " + note
        rows.append({'label': f'Access group: {g.group_name} ({", ".join(parts)})',
                     'grants': g.holds(perm_name) if perm_name else True,
                     'scope': g.scope_label, 'note': note, 'via': via,
                     'group_id': g.group_id})
    return rows


# --- management ------------------------------------------------------------------------

def _msp_wide(user, perm_name) -> bool:
    from .permission_utils import user_has_org_perm
    return user_has_org_perm(user, None, perm_name)


def can_manage(user) -> bool:
    """May `user` open the access group pages and change groups at all."""
    if user is None or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    from psa.visibility import is_msp_staff
    return is_msp_staff(user) and _msp_wide(user, 'roles_manage')


def role_refusal(user, role) -> str:
    """'' when `user` may manage a group carrying `role`, else the reason."""
    if not can_manage(user):
        return 'Managing access groups needs the roles_manage permission across every customer.'
    if role is None or user.is_superuser:
        return ''
    from . import permission_registry as registry
    if getattr(role, 'audience', '') == 'customer':
        return 'Access groups carry internal roles only; customer roles are assigned per customer.'
    if role.organization_id is not None:
        return "Access groups carry built-in or install-wide roles, not one customer's custom role."
    if getattr(role, 'org_owner', False) and not _msp_wide(user, 'org_owner'):
        return 'Only an owner manages a group whose role is an owner role.'
    if registry.is_privileged_role(role) and not _msp_wide(user, 'org_manage_privileged'):
        return "Groups whose role holds administration permissions need 'org_manage_privileged'."
    missing = sorted(k for k in registry.granted_keys(role) if not _msp_wide(user, k))
    if missing:
        return ('You can only manage groups whose role holds permissions you hold yourself across every '
                'customer. Missing: ' + ', '.join(missing[:8]) + ('...' if len(missing) > 8 else ''))
    return ''


def group_refusal(user, group) -> str:
    """'' when `user` may change `group` (its current role decides)."""
    reason = role_refusal(user, getattr(group, 'role_template', None))
    if reason:
        return reason
    from .group_features import refusal as feature_refusal
    reason = feature_refusal(user, getattr(group, 'feature_permissions', None) or (), check_grantable=False)
    if reason:
        return reason
    if not user.is_superuser and group.pk and group.members.filter(pk=user.pk).exists():
        return 'You can not change a group you are a member of.'
    return ''


def member_refusal(actor, target) -> str:
    """'' when `target` may be added to a staff access group by `actor`."""
    from psa.visibility import is_msp_staff
    if target is None or not target.is_active:
        return 'Only active users can be added.'
    if not is_msp_staff(target):
        return f'{target.get_username()} is a customer user; access groups hold MSP staff only.'
    if actor is not None and not actor.is_superuser and actor.pk == target.pk:
        return 'You can not add yourself to an access group.'
    return ''


def snapshot(group) -> dict:
    """Small before/after representation for the audit trail."""
    return {'name': group.name, 'role': getattr(group.role_template, 'name', None),
            'role_id': group.role_template_id, 'all_customers': bool(group.all_customers),
            'feature_permissions': sorted(group.feature_permissions or []),
            'customers': sorted(group.customers.values_list('pk', flat=True)) if group.pk else [],
            'members': sorted(group.members.values_list('username', flat=True)) if group.pk else []}


# --- default groups ---------------------------------------------------------------------

# (seed_key, name, role seed_key, description). Created once, empty, scope
# "all customers"; never changed or re-created afterwards.
DEFAULT_GROUPS = (
    ('l1_tech', 'L1 Tech', 'tech_l1', 'Level 1 technicians.'),
    ('l2_tech', 'L2 Tech', 'tech_l2', 'Level 2 technicians.'),
    ('l3_tech', 'L3 Tech', 'tech_l3', 'Level 3 technicians.'),
    ('managers', 'Managers', 'service_manager', 'Service managers.'),
    ('sales', 'Sales', 'sales_rep', 'Sales team.'),
    ('sales_managers', 'Sales Managers', 'sales_manager', 'Sales managers.'),
    ('owners', 'Owners', 'org_owner', 'Business owners.'),
    ('administrators', 'Administrators', 'org_admin', 'Administrators of users, roles and settings.'),
    ('billing', 'Billing', 'billing_finance', 'Billing and finance.'),
    ('auditors', 'Auditors', 'auditor', 'Read-only reviewers.'),
)


def seed_default_groups(TechnicianGroup, RoleTemplate, groups=DEFAULT_GROUPS) -> dict:
    """Create the default groups that do not exist yet. A group that already
    exists (by seed key, or a group of the same name) is never touched, so an
    administrator's edits stay. Works on historical (migration) models."""
    summary = {'created': [], 'exists': [], 'no_role': []}
    for key, name, role_key, description in groups:
        if TechnicianGroup.objects.filter(seed_key=key).exists() or TechnicianGroup.objects.filter(
                name=name).exists():
            summary['exists'].append(name)
            continue
        role = RoleTemplate.objects.filter(seed_key=role_key, organization__isnull=True).first()
        if role is None:
            summary['no_role'].append(name)
            continue
        TechnicianGroup.objects.create(name=name, description=description, role_template=role,
                                       all_customers=True, seed_key=key)
        summary['created'].append(name)
    return summary
