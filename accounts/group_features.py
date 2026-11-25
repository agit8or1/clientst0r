"""
Per-feature permissions of an access group (tech_access.TechnicianGroup
`feature_permissions`).

An access group can carry, besides its optional role, a set of individual
permissions picked per feature module on the group page. Members hold them
at the group's customers, exactly like the group's role
(accounts.access_groups): the union of the role and these permissions, with
the group's customer scope, resolved by accounts.permission_utils.

What is stored
  The list of permission keys (registry keys = RoleTemplate field names),
  never a level. A module shown at "Edit" is the set of keys that level maps
  to on the day it was saved; a permission added to the registry later is
  not granted until an administrator picks it, so a code update never widens
  a group by itself.

Levels (one place: LEVELS / ACTION_LEVEL / KEY_LEVEL)
  None  nothing in the module
  View  keys whose action is view or download
  Edit  View + create and edit
  Full  Edit + every other action (assign, delete, approve, send, export,
        reveal, execute, remote, settings, audit history, sign)
  Levels are cumulative. KEY_LEVEL moves a few keys to a higher level than
  their action says (cross-customer ticket view, routing tools, financial /
  margin figures). Keys of the "users" / "roles" actions belong to no level;
  they can only be ticked one by one under Advanced. A module whose keys do
  not match one level exactly is shown as "Custom".

What a group can never grant (GRANTABLE_KEYS leaves them out; saving,
resolving and the defaults all filter through it)
  * critical permissions (PRIVILEGED_KEYS: user / role / ownership
    administration, security and platform settings, API keys) and
    TRANSFER_ONLY_KEYS (ownership) - a group's role is still the only way a
    group hands those out, behind access_groups.role_refusal;
  * permissions that do not exist yet (status unimplemented);
  * customer-portal permissions (the portal module, and the documentation
    keys written for customer users): groups hold MSP staff only.

Defaults (DEFAULT_FEATURES) are set per default group (seed_key). Each is a
subset of what the group's built-in role grants (a test keeps it so), so
giving a default group its defaults never widens what its members hold
while the group still carries its built-in role.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from . import permission_registry as registry

NONE, VIEW, EDIT, FULL, CUSTOM = 'none', 'view', 'edit', 'full', 'custom'
LEVELS = (NONE, VIEW, EDIT, FULL)
LEVEL_LABELS = {NONE: 'None', VIEW: 'View', EDIT: 'Edit', FULL: 'Full', CUSTOM: 'Custom'}
LEVEL_RANK = {NONE: 0, VIEW: 1, EDIT: 2, FULL: 3}

# action -> lowest level that includes it; None = Advanced only.
ACTION_LEVEL = {
    'view': VIEW, 'download': VIEW,
    'create': EDIT, 'edit': EDIT,
    'assign': FULL, 'delete': FULL, 'approve': FULL, 'send': FULL, 'export': FULL, 'reveal': FULL,
    'execute': FULL, 'remote': FULL, 'settings': FULL, 'audit': FULL, 'sign': FULL,
    'users': None, 'roles': None,
}
# Keys whose level differs from their action's.
KEY_LEVEL = {
    'tickets_view_all': FULL,           # tickets across every customer, not only the group's
    'routing_test': FULL,               # routing tools sit with routing settings
    'monitoring_trigger': EDIT,         # run a check now
    'reports_view_financial': FULL,
    'view_profitability': FULL,
    'crm_view_forecast': FULL,
    'pricing_view_internal_cost_rates': FULL,
    'contracts_view_pricing': FULL,
    'integrations_view_synced_psa': FULL,  # raw provider data
    'view_app_connections': FULL,       # connected applications sit with their settings
    'contracts_download_signed': FULL,
    'audit_view': VIEW,                 # reading the audit trail; exporting it stays Full
}

EXCLUDED_MODULES = frozenset({'portal'})
CUSTOMER_ONLY_KEYS = frozenset({'docs_view_internal', 'office_edit_in_m365'})

GRANTABLE_KEYS = frozenset(
    p.key for p in registry.PERMISSIONS
    if p.key not in registry.PRIVILEGED_KEYS and p.key not in registry.TRANSFER_ONLY_KEYS
    and p.status != registry.UNIMPLEMENTED and p.module not in EXCLUDED_MODULES
    and p.key not in CUSTOMER_ONLY_KEYS)


def key_level(key: str) -> Optional[str]:
    """The lowest level that includes `key` (None = Advanced only)."""
    if key in KEY_LEVEL:
        return KEY_LEVEL[key]
    p = registry.get(key)
    return ACTION_LEVEL.get(p.action) if p else None


def module_keys(module: str) -> List[str]:
    """Grantable keys of `module`, in registry order."""
    return [p.key for p in registry.PERMISSIONS if p.module == module and p.key in GRANTABLE_KEYS]


def level_keys(module: str, level: str) -> frozenset:
    """The keys `level` gives in `module`."""
    if level not in LEVEL_RANK or level == NONE:
        return frozenset()
    rank = LEVEL_RANK[level]
    return frozenset(k for k in module_keys(module)
                     if key_level(k) is not None and LEVEL_RANK[key_level(k)] <= rank)


def modules() -> List[Tuple[str, str, str]]:
    """[(module, label, description)] that have grantable keys, MODULES order."""
    return [(m, label, desc) for m, (label, desc) in registry.MODULES.items() if module_keys(m)]


def clean(keys: Iterable[str]) -> List[str]:
    """Only grantable keys, de-duplicated, sorted."""
    return sorted({k for k in (keys or ()) if k in GRANTABLE_KEYS})


def module_level(keys: Iterable[str], module: str) -> str:
    """The level that matches `keys` in `module` exactly, else CUSTOM."""
    held = frozenset(k for k in keys if k in GRANTABLE_KEYS and registry.get(k).module == module)
    if not held:
        return NONE
    for level in (VIEW, EDIT, FULL):
        if held == level_keys(module, level):
            return level
    return CUSTOM


def expand(spec: Dict[str, object]) -> List[str]:
    """{module: level | iterable of keys} -> grantable key list."""
    out = set()
    for module, value in (spec or {}).items():
        if isinstance(value, str):
            out |= level_keys(module, value)
        else:
            out |= set(value)
    return clean(out)


# --- defaults for the default groups (seed_key) -------------------------------------------
# Each spec: module -> level, or a tuple of keys where no level fits the
# group's purpose. Modules left out are None. Every default is a subset of
# the group's built-in role (accounts.role_seeds), checked by a test.

_TECH_BASE = {
    'org': ('org_view_members',),
    'kb': VIEW, 'files': VIEW, 'vault': VIEW, 'monitoring': VIEW, 'backup': VIEW,
    'procurement': VIEW, 'operations': VIEW, 'security': VIEW,
    'reports': ('reports_view_dashboards',),
    'ai': ('psa_ai_view', 'psa_ai_request_triage'),
}

DEFAULT_FEATURES: Dict[str, Dict[str, object]] = {
    'l1_tech': dict(_TECH_BASE, **{
        'tickets': EDIT,
        'service': ('change_view', 'problem_view', 'release_view', 'change_create', 'problem_create'),
        'assets': VIEW, 'docs': VIEW,
    }),
    'l2_tech': dict(_TECH_BASE, **{
        'tickets': EDIT,
        'service': ('change_view', 'problem_view', 'release_view', 'change_create', 'problem_create',
                    'catalog_propose_change'),
        'assets': ('assets_view', 'assets_edit'), 'docs': EDIT, 'kb': ('kb_view_articles', 'kb_edit_articles'),
        'files': EDIT,
        'monitoring': ('monitoring_view', 'monitoring_trigger'),
        'security': ('security_alerts_view', 'events_view', 'security_alerts_acknowledge', 'events_link'),
        'reports': ('reports_view_dashboards', 'reports_export'),
    }),
    'l3_tech': dict(_TECH_BASE, **{
        'tickets': tuple(level_keys('tickets', EDIT) | {'tickets_assign'}),
        'service': ('change_view', 'problem_view', 'release_view', 'change_create', 'problem_create',
                    'catalog_propose_change', 'change_implement', 'problem_assign', 'problem_resolve'),
        'assets': EDIT, 'docs': EDIT, 'kb': ('kb_view_articles', 'kb_edit_articles', 'kb_move_articles'),
        'files': EDIT, 'monitoring': EDIT,
        'security': ('security_alerts_view', 'events_view', 'security_alerts_acknowledge', 'events_link'),
        'reports': ('reports_view_dashboards', 'reports_export'),
    }),
    'managers': {
        'org': ('org_view_members',),
        'tickets': ('tickets_view', 'tickets_view_internal', 'tickets_create', 'tickets_edit', 'tickets_close',
                    'tickets_assign', 'tickets_view_all', 'outsourcing_share_tickets', 'routing_manage_rules',
                    'routing_test', 'routing_override'),
        'service': FULL, 'assets': EDIT,
        'docs': ('docs_view', 'docs_create', 'docs_edit', 'docs_publish'),
        'kb': ('kb_view_articles', 'kb_edit_articles', 'kb_move_articles', 'kb_publish_articles'),
        'files': EDIT, 'monitoring': EDIT, 'backup': VIEW,
        'security': ('security_alerts_view', 'events_view', 'security_alerts_acknowledge', 'events_link'),
        'integrations': ('integrations_view',),
        'procurement': ('procurement_view', 'procurement_create_pr', 'procurement_approve_pr'),
        'reports': ('reports_view_dashboards', 'reports_view_sla', 'reports_view_capacity',
                    'reports_manage_dashboards', 'reports_export'),
        'resourcing': ('resourcing_view_team', 'resourcing_approve_leave'),
        'ai': ('psa_ai_view', 'psa_ai_request_triage', 'psa_ai_send_low_risk', 'psa_ai_apply_low_risk',
               'psa_ai_approve_reply', 'psa_ai_approve_action'),
        'operations': ('vehicles_view', 'vehicles_manage', 'scheduling_manage_wallboard',
                       'psa_manage_workflow_rules', 'timesheets_approve'),
    },
    'sales': {
        'org': ('org_view_members',),
        'tickets': ('tickets_view', 'tickets_create'), 'kb': VIEW, 'files': EDIT,
        'sales': ('crm_view', 'quotes_view', 'crm_create_lead', 'quotes_edit', 'crm_manage_pipeline'),
        'contracts': ('contracts_view', 'contracts_view_pricing', 'contracts_edit_draft',
                      'contracts_submit_approval'),
        'reports': ('reports_view_dashboards',),
    },
    'sales_managers': {
        'org': ('org_view_members',),
        'tickets': ('tickets_view', 'tickets_create'), 'kb': VIEW, 'files': EDIT,
        'sales': ('crm_view', 'quotes_view', 'crm_create_lead', 'quotes_edit', 'crm_manage_pipeline',
                  'crm_manage_campaigns', 'crm_view_forecast', 'quotes_send', 'quotes_approve_discount',
                  'crm_approve_commissions'),
        'contracts': ('contracts_view', 'contracts_view_pricing', 'contracts_edit_draft',
                      'contracts_submit_approval', 'contracts_download_signed'),
        'reports': ('reports_view_dashboards', 'reports_manage_dashboards', 'reports_export'),
        'pricing': ('pricing_approve_discounts',),
    },
    # 'owners': everything the built-in Owner role holds that a group may
    # grant (default_keys); owner-only and other critical permissions stay
    # with the Owner role.
    'owners': {},
    'administrators': {
        'org': ('org_view_members',),
        'tickets': ('tickets_view', 'tickets_view_internal', 'tickets_create', 'tickets_edit', 'tickets_close',
                    'tickets_assign', 'tickets_view_all', 'routing_manage_rules', 'routing_test',
                    'routing_override'),
        'service': FULL, 'assets': ('assets_view', 'assets_create', 'assets_edit', 'assets_delete'),
        'docs': ('docs_view', 'docs_create', 'docs_edit', 'docs_delete', 'docs_publish'),
        'kb': FULL, 'files': FULL, 'monitoring': FULL, 'backup': FULL,
        'security': ('security_alerts_view', 'events_view', 'security_alerts_acknowledge', 'events_link',
                     'security_alerts_create_rules'),
        'integrations': ('integrations_view', 'integrations_sync', 'integrations_view_synced_psa'),
        'sales': ('crm_view', 'quotes_view', 'manage_customer_onboarding'),
        'contracts': ('contracts_view',),
        'procurement': ('procurement_view', 'procurement_create_pr', 'procurement_approve_pr', 'manage_licensing'),
        'reports': ('reports_view_dashboards', 'reports_view_sla', 'reports_view_capacity',
                    'reports_manage_dashboards', 'reports_export', 'manage_health_score_settings'),
        'resourcing': ('resourcing_view_team', 'resourcing_approve_leave', 'resourcing_manage_holidays'),
        'api': ('api_access',), 'audit': ('audit_view',),
        'ai': ('psa_ai_view', 'psa_ai_request_triage'),
        'operations': FULL,
    },
    'billing': {
        'org': ('org_view_members',),
        'tickets': ('tickets_view',), 'kb': VIEW, 'files': VIEW,
        'sales': ('quotes_view',),
        'contracts': ('contracts_view', 'contracts_view_pricing', 'contracts_download_signed'),
        'billing': ('billing_view_invoices', 'billing_view_aging', 'billing_send_invoices',
                    'billing_record_payments', 'billing_approve_invoices', 'billing_issue_credit',
                    'billing_manage_charges', 'manage_tax_settings'),
        'procurement': VIEW,
        'reports': ('reports_view_dashboards', 'reports_view_financial', 'view_profitability',
                    'reports_export', 'reports_manage_scheduled', 'act_on_pricing_recommendations'),
        'pricing': FULL,
        'operations': ('resourcing_view_payroll',),
    },
    'auditors': {
        'org': ('org_view_members',),
        'tickets': ('tickets_view', 'tickets_view_internal', 'tickets_view_all'),
        'service': VIEW, 'assets': VIEW, 'docs': VIEW, 'kb': VIEW, 'monitoring': VIEW, 'backup': VIEW,
        'security': VIEW, 'integrations': ('integrations_view',),
        'sales': ('crm_view', 'quotes_view'), 'contracts': ('contracts_view',),
        'procurement': VIEW,
        'reports': ('reports_view_dashboards', 'reports_view_sla', 'reports_view_capacity'),
        'audit': ('audit_view',), 'operations': VIEW,
    },
}


def default_keys(seed_key: str) -> List[str]:
    """The default per-feature permissions of a default group ([] for others)."""
    if seed_key == 'owners':
        from .role_seeds import definitions
        owner = next(d for d in definitions() if d.key == 'org_owner')
        return clean(k for k, v in owner.flags.items() if v)
    spec = DEFAULT_FEATURES.get(seed_key or '')
    return expand(spec) if spec else []


def has_defaults(group) -> bool:
    return bool(getattr(group, 'seed_key', '') and getattr(group, 'seed_key') in DEFAULT_FEATURES)


# --- editing ------------------------------------------------------------------------------

def from_post(post) -> Tuple[List[str], List[str]]:
    """Read the matrix from a POST: per module `feat_level_<module>` (none /
    view / edit / full / custom) and, for custom, the ticked `feat_key`
    boxes of that module. Returns (keys, errors)."""
    errors = []
    ticked = set(post.getlist('feat_key'))
    unknown = sorted(k for k in ticked if k not in GRANTABLE_KEYS)
    if unknown:
        errors.append('These permissions can not be given through an access group: ' + ', '.join(unknown[:8]))
    out = set()
    for module, _label, _desc in modules():
        level = post.get(f'feat_level_{module}', NONE)
        if level == CUSTOM:
            out |= {k for k in module_keys(module) if k in ticked}
        elif level in LEVEL_RANK:
            out |= level_keys(module, level)
        else:
            errors.append(f'Unknown level for {registry.MODULES[module][0]}.')
    return sorted(out), errors


def refusal(user, keys: Iterable[str], check_grantable=True) -> str:
    """'' when `user` may give a group the per-feature permissions `keys`.
    The same rule as a group's role (access_groups.role_refusal): managing
    access groups needs roles_manage MSP-wide, and nobody but a superuser
    hands out a permission they do not hold themselves across every
    customer."""
    keys = set(keys or ())
    if check_grantable:
        bad = sorted(k for k in keys if k not in GRANTABLE_KEYS)
        if bad:
            return 'These permissions can not be given through an access group: ' + ', '.join(bad[:8])
    from .access_groups import can_manage
    if not can_manage(user):
        return 'Managing access groups needs the roles_manage permission across every customer.'
    if user.is_superuser:
        return ''
    from .permission_utils import user_has_org_perm
    missing = sorted(k for k in keys if not user_has_org_perm(user, None, k))
    if missing:
        return ('You can only manage groups whose per-feature permissions you hold yourself across every '
                'customer. Missing: ' + ', '.join(missing[:8]) + ('...' if len(missing) > 8 else ''))
    return ''


def matrix(group_keys: Iterable[str], role=None) -> List[dict]:
    """Rows for the group page: one per module with its level, its keys
    (ticked / from the role) and the level each key belongs to."""
    keys = set(group_keys or ())
    role_keys = registry.granted_keys(role) if role is not None else frozenset()
    rows = []
    for module, label, desc in modules():
        perms = []
        for k in module_keys(module):
            p = registry.get(k)
            perms.append({'key': k, 'label': p.description, 'level': key_level(k) or '',
                          'level_label': LEVEL_LABELS.get(key_level(k), 'Advanced only'),
                          'checked': k in keys, 'from_role': k in role_keys,
                          'sensitivity': p.sensitivity, 'pending': p.status != registry.ENFORCED})
        rows.append({'module': module, 'label': label, 'description': desc,
                     'level': module_level(keys, module), 'perms': perms,
                     'role_count': sum(1 for x in perms if x['from_role']),
                     'level_keys': {lv: sorted(level_keys(module, lv)) for lv in (VIEW, EDIT, FULL)}})
    return rows


def summary(keys: Iterable[str]) -> Dict[str, str]:
    """{module label: level label} for the modules that hold anything."""
    keys = list(keys or ())
    out = {}
    for module, label, _desc in modules():
        lv = module_level(keys, module)
        if lv != NONE:
            out[label] = LEVEL_LABELS[lv]
    return out
