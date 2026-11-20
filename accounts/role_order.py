"""
Display order of roles in pickers and lists.

  1. built-in internal roles, in working order: owner, administrator,
     manager, L1 / L2 / L3 tech, sales, sales manager, billing, security,
     auditor;
  2. custom roles (the install's and the selected customer's), by name;
  3. built-in customer roles, primary roles first, then the add-on roles;
  4. legacy roles: the older system templates with no seed key
     (Administrator, Editor, Read-Only, Platform Administrator...). They
     still work and stay assignable; pickers show them in a collapsed
     "Legacy roles" group.

Ordering only; nothing here changes what a role grants.
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

BUILTIN_ORDER = (
    'org_owner', 'org_admin', 'service_manager', 'tech_l1', 'tech_l2', 'tech_l3',
    'sales_rep', 'sales_manager', 'billing_finance', 'security_analyst', 'security_admin', 'auditor',
    'customer_admin', 'customer_manager', 'customer_user', 'customer_readonly',
    'customer_billing_contact', 'customer_contract_reviewer', 'customer_contract_signer',
    'customer_request_approver',
)
_RANK = {k: i for i, k in enumerate(BUILTIN_ORDER)}

BUILTIN, CUSTOM, CUSTOMER, LEGACY = 'builtin', 'custom', 'customer', 'legacy'
GROUP_LABELS = {BUILTIN: 'Built-in roles', CUSTOM: 'Custom roles', CUSTOMER: 'Customer roles',
                LEGACY: 'Legacy roles'}
_BUCKET_RANK = {BUILTIN: 0, CUSTOM: 1, CUSTOMER: 2, LEGACY: 3}


def is_legacy(role) -> bool:
    """An older built-in template without a seed key."""
    return bool(getattr(role, 'is_system_template', False) and not (getattr(role, 'seed_key', '') or '')
                and getattr(role, 'organization_id', None) is None)


def bucket(role) -> str:
    key = getattr(role, 'seed_key', '') or ''
    if key in _RANK:
        return CUSTOMER if key.startswith('customer_') else BUILTIN
    if is_legacy(role):
        return LEGACY
    if getattr(role, 'audience', '') == 'customer':
        return CUSTOMER
    return CUSTOM


def sort_key(role):
    key = getattr(role, 'seed_key', '') or ''
    return (_BUCKET_RANK[bucket(role)], _RANK.get(key, len(_RANK)), (role.name or '').lower())


def ordered(roles: Iterable) -> List:
    return sorted(roles, key=sort_key)


def grouped(roles: Iterable) -> List[Tuple[str, str, list]]:
    """[(bucket, label, [roles])] in display order, empty groups left out."""
    out = []
    rows = ordered(roles)
    for b in (BUILTIN, CUSTOM, CUSTOMER, LEGACY):
        members = [r for r in rows if bucket(r) == b]
        if members:
            out.append((b, GROUP_LABELS[b], members))
    return out


def grouped_choices(roles: Iterable, label=lambda r: r.name) -> list:
    """Choices for a <select>: [(group label, [(pk, label), ...]), ...]."""
    return [(lbl, [(r.pk, label(r)) for r in members]) for _b, lbl, members in grouped(roles)]


class GroupedRoleChoiceIterator:
    """ModelChoiceIterator replacement yielding optgroups in display order."""

    def __init__(self, field):
        self.field = field

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ('', self.field.empty_label)
        for lbl, members in grouped_choices(self.field.queryset):
            yield (lbl, [(self.field.prepare_value(pk), name) for pk, name in members])

    def __len__(self):
        return self.field.queryset.count() + (1 if self.field.empty_label is not None else 0)

    def __bool__(self):
        return self.field.empty_label is not None or self.field.queryset.exists()


def grouped_model_choice_field(field):
    """Make a ModelChoiceField render its roles grouped and ordered."""
    field.iterator = GroupedRoleChoiceIterator
    field.widget.choices = field.choices
    return field
