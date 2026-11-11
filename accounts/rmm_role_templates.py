"""
Built-in RMM role templates (Phase 8): L1, L2, L3 and Platform administrator.

These are ordinary system RoleTemplates with `rmm_tier` set. The tier is what
rmm_permissions reads; the boolean flags below are the rest of the role
(tickets, assets, monitoring...) and follow the usual RoleTemplate rules.

  - Added as new templates. Existing templates keep rmm_tier = '' and so
    keep exactly the access they had: rmm_permissions falls back to
    technician access (tech_access) and the existing flags for them.
  - A tier is read from a technician's *global* role template only, never
    from a customer membership (a customer's member manager can assign
    system templates to memberships; that must not widen RMM access).
  - A tier says what; where comes from a live technician-access assignment
    at the customer. No tier grants all-tenant device access.
  - No template grants credential reveal (vault_view_password stays off);
    reveal needs the vault permission, granted separately.

accounts/migrations/0040 carries a frozen copy of this list so an upgrade
creates the four rows without importing this module.
"""
from __future__ import annotations

TIER_L1, TIER_L2, TIER_L3, TIER_PLATFORM_ADMIN = 'l1', 'l2', 'l3', 'platform_admin'

TIER_CHOICES = [
    ('', 'None (technician access and role flags only)'),
    (TIER_L1, 'RMM L1 — Help Desk'),
    (TIER_L2, 'RMM L2 — Technician'),
    (TIER_L3, 'RMM L3 — Senior Technician'),
    (TIER_PLATFORM_ADMIN, 'Platform Administrator'),
]

_L1_FLAGS = dict(
    vault_view=True, assets_view=True, docs_view=True, files_view=True, monitoring_view=True,
    org_view_members=True, kb_view_articles=True, reports_view_dashboards=True, procurement_view=True,
    change_view=True, change_create=True, problem_view=True, problem_create=True, release_view=True,
    security_alerts_view=True, psa_ai_view=True, psa_ai_request_triage=True,
    tickets_view=True, tickets_create=True, tickets_edit=True, tickets_close=True,
)
_L2_FLAGS = dict(
    _L1_FLAGS, assets_edit=True, docs_create=True, docs_edit=True, files_upload=True, monitoring_trigger=True,
    kb_edit_articles=True, security_alerts_acknowledge=True, catalog_propose_change=True,
)
_L3_FLAGS = dict(
    _L2_FLAGS, assets_create=True, monitoring_create=True, monitoring_edit=True, kb_move_articles=True,
    change_implement=True, problem_assign=True, problem_resolve=True, integrations_view=True,
    integrations_sync=True, tickets_assign=True,
)
_PLATFORM_FLAGS = dict(
    vault_view=True, assets_view=True, docs_view=True, files_view=True, monitoring_view=True,
    integrations_view=True, integrations_configure=True, integrations_sync=True,
    audit_view=True, audit_export=True, org_view_members=True, org_manage_settings=True,
    security_alerts_view=True, security_alerts_manage_connections=True, kb_view_articles=True,
    reports_view_dashboards=True, tickets_view=True,
)

BUILTIN_RMM_TEMPLATES = [
    ('RMM L1 — Help Desk', TIER_L1,
     'Reads permitted devices and alerts, views approved diagnostics, requests remote support and submits '
     'remediation requests. No unrestricted shell or scripts; no credential reveal without the vault '
     'permission.', _L1_FLAGS),
    ('RMM L2 — Technician', TIER_L2,
     'L1 plus approved diagnostics and workflows, private RMM handoffs, scoped script execution only where '
     'specifically granted, and restricted patch deployment (standard workstations, second-person approval).',
     _L2_FLAGS),
    ('RMM L3 — Senior Technician', TIER_L3,
     "L2 plus expanded device administration and remediation, advanced diagnostics, automation and "
     "deployment (high-impact work needs a second person). Never automatic all-tenant access or security "
     "administration.", _L3_FLAGS),
    ('Platform Administrator', TIER_PLATFORM_ADMIN,
     'Integration configuration, RMM policy and role management, security settings and audit review. Grants '
     'no device work by itself.', _PLATFORM_FLAGS),
]


def template_rows(boolean_field_names):
    """(name, defaults) for each built-in, every other boolean False."""
    out = []
    for name, tier, description, flags in BUILTIN_RMM_TEMPLATES:
        data = {f: False for f in boolean_field_names if f != 'is_system_template'}
        data.update(flags)
        data.update(is_system_template=True, description=description, rmm_tier=tier)
        out.append((name, data))
    return out
