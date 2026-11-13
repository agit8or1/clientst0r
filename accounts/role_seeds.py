"""
Built-in role templates of the roles & access program, and the seeder that
creates them without ever overwriting a customized role.

Each definition has a stable `key` (RoleTemplate.seed_key), a `version` and
the full permission map. The seeder, for each definition:

  * no template with that seed_key yet:
      - an existing system template listed in `adopt` (e.g. "Owner", the RMM
        tier templates) is adopted: it gets the seed_key, and only the
        permissions introduced by this program (NEW_FLAG_KEYS) are set from
        the definition. Its existing permissions are left exactly as they are;
      - otherwise the template is created from the definition. If a
        different role already uses the name, nothing is created and the
        clash is listed for review;
  * a template with that seed_key on an older version:
      - permissions still equal to what was seeded (checksum match): the new
        definition is applied;
      - customized since (checksum differs): left alone, listed for review;
  * same version: nothing.

So reseeding (migrations, `manage.py init_role_templates`, `manage.py
seed_roles`) is idempotent and never undoes an administrator's edits.

Mapping to roles that already existed (docs/ROLES_AND_ACCESS.md):

  Organization Owner        -> existing "Owner" (adopted)
  Organization Administrator-> new. The existing "Administrator" template is
                               a different role (content admin with secret
                               reveal, no user management) and stays as is.
  Level 1/2/3 Technician    -> existing "RMM L1 — Help Desk", "RMM L2 —
                               Technician", "RMM L3 — Senior Technician"
                               (adopted; their RMM tier is unchanged)
  Service Manager, Sales Representative, Sales Manager, Billing / Finance,
  Internal Read-Only / Auditor, Customer Administrator, Customer Manager,
  Customer Standard User, Customer Read-Only, and the customer add-on roles
  Billing Contact, Contract Reviewer, Authorized Contract Signer, Request
  Approver -> new.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .permission_registry import ALL_KEYS

# Permissions introduced by the roles & access program (accounts 0045).
NEW_FLAG_KEYS = (
    'org_manage_privileged', 'roles_manage', 'org_owner', 'tickets_view_internal',
    'quotes_view', 'quotes_edit', 'quotes_send', 'quotes_approve_discount',
    'contracts_view', 'contracts_view_pricing', 'contracts_edit_draft', 'contracts_manage_templates',
    'contracts_submit_approval', 'contracts_approve', 'contracts_send', 'contracts_manage_links',
    'contracts_countersign', 'contracts_void', 'contracts_download_signed', 'contracts_view_audit',
    'contracts_settings',
    'portal_tickets_view_org', 'portal_approve_requests', 'portal_billing_contact',
    'portal_contract_review', 'portal_contract_sign',
    'portal_tickets_create', 'portal_tickets_reply', 'portal_agreements_view_org',
    'crm_approve_commissions', 'billing_approve_invoices', 'billing_issue_credit', 'billing_manage_charges',
    'reports_export', 'vehicles_view', 'vehicles_manage', 'scheduling_manage_wallboard',
    'psa_manage_workflow_rules', 'timesheets_approve', 'resourcing_view_payroll',
    'docs_view_internal', 'vault_approve_reveal', 'integrations_view_synced_psa', 'netconfig_view_configs',
)
CONTRACT_KEYS = tuple(k for k in NEW_FLAG_KEYS if k.startswith('contracts_'))


def checksum(values: Dict[str, bool], rmm_tier: str = '') -> str:
    body = ';'.join(f'{k}={int(bool(v))}' for k, v in sorted(values.items()))
    return hashlib.sha256(f'{body}|tier={rmm_tier or ""}'.encode()).hexdigest()


@dataclass
class RoleDef:
    key: str
    name: str
    audience: str
    description: str
    flags: Dict[str, bool]
    version: int = 1
    adopt: Tuple[str, ...] = ()
    rmm_tier: str = ''
    spec_name: str = ''           # the name the requirement uses, when different

    def full_flags(self, field_names) -> Dict[str, bool]:
        data = {f: False for f in field_names}
        data.update({k: bool(v) for k, v in self.flags.items() if k in data})
        return data


def _on(*keys, **extra) -> Dict[str, bool]:
    d = {k: True for k in keys}
    d.update(extra)
    return d


VIEW_BASICS = ('org_view_members', 'kb_view_articles', 'reports_view_dashboards')

# --- internal ------------------------------------------------------------------

_OWNER = {k: True for k in ALL_KEYS}
_OWNER.update(network_discovery_generate=False, vault_extension_use=False, vault_extension_offline_cache=False,
              portal_billing_contact=False, portal_contract_review=False, docs_view_internal=False,
              portal_contract_sign=False, office_edit_in_m365=False)

_ORG_ADMIN = _on(
    *VIEW_BASICS, 'org_invite_members', 'org_manage_members', 'org_manage_privileged', 'roles_manage',
    'org_manage_settings', 'integrations_view', 'integrations_configure', 'integrations_sync',
    'api_access', 'api_keys_manage', 'audit_view',
    'tickets_view', 'tickets_create', 'tickets_edit', 'tickets_assign', 'tickets_view_all', 'tickets_close',
    'tickets_view_internal', 'routing_manage_rules', 'routing_test', 'routing_override',
    'assets_view', 'assets_create', 'assets_edit', 'assets_delete',
    'docs_view', 'docs_create', 'docs_edit', 'docs_delete', 'docs_publish',
    'kb_edit_articles', 'kb_move_articles', 'kb_manage_categories', 'kb_publish_articles',
    'files_view', 'files_upload', 'files_delete',
    'monitoring_view', 'monitoring_create', 'monitoring_edit', 'monitoring_delete', 'monitoring_trigger',
    'security_alerts_view', 'security_alerts_manage_connections', 'security_alerts_acknowledge',
    'security_alerts_create_rules',
    'change_view', 'change_create', 'change_approve_cab', 'change_implement',
    'problem_view', 'problem_create', 'problem_assign', 'problem_resolve',
    'release_view', 'release_manage', 'release_freeze', 'catalog_propose_change', 'catalog_approve_change',
    'procurement_view', 'procurement_create_pr', 'procurement_approve_pr',
    'reports_view_sla', 'reports_view_capacity', 'reports_manage_dashboards',
    'resourcing_view_team', 'resourcing_approve_leave', 'resourcing_manage_holidays',
    'crm_view', 'quotes_view', 'contracts_view',
    'psa_ai_view', 'psa_ai_request_triage', 'psa_ai_admin',
    'reports_export', 'vehicles_view', 'vehicles_manage', 'scheduling_manage_wallboard',
    'psa_manage_workflow_rules', 'timesheets_approve', 'resourcing_view_payroll',
    'integrations_view_synced_psa',
)

_SERVICE_MANAGER = _on(
    *VIEW_BASICS, 'tickets_view', 'tickets_create', 'tickets_edit', 'tickets_assign', 'tickets_view_all',
    'tickets_close', 'tickets_view_internal', 'outsourcing_share_tickets',
    'routing_manage_rules', 'routing_test', 'routing_override',
    'change_view', 'change_create', 'change_approve_cab', 'change_implement',
    'problem_view', 'problem_create', 'problem_assign', 'problem_resolve',
    'release_view', 'release_manage', 'release_freeze', 'catalog_propose_change', 'catalog_approve_change',
    'assets_view', 'assets_create', 'assets_edit', 'docs_view', 'docs_create', 'docs_edit', 'docs_publish',
    'kb_edit_articles', 'kb_move_articles', 'kb_publish_articles', 'files_view', 'files_upload',
    'monitoring_view', 'monitoring_create', 'monitoring_edit', 'monitoring_trigger', 'integrations_view',
    'security_alerts_view', 'security_alerts_acknowledge',
    'reports_view_sla', 'reports_view_capacity', 'reports_manage_dashboards',
    'resourcing_view_team', 'resourcing_approve_leave',
    'procurement_view', 'procurement_create_pr', 'procurement_approve_pr',
    'psa_ai_view', 'psa_ai_request_triage', 'psa_ai_send_low_risk', 'psa_ai_apply_low_risk',
    'psa_ai_approve_reply', 'psa_ai_approve_action',
    'reports_export', 'vehicles_view', 'vehicles_manage', 'scheduling_manage_wallboard',
    'psa_manage_workflow_rules', 'timesheets_approve',
)

_SALES_REP = _on(
    *VIEW_BASICS, 'crm_view', 'crm_create_lead', 'crm_manage_pipeline',
    'quotes_view', 'quotes_edit', 'contracts_view', 'contracts_view_pricing', 'contracts_edit_draft',
    'contracts_submit_approval', 'tickets_view', 'tickets_create', 'files_view', 'files_upload',
)

_SALES_MANAGER = dict(_SALES_REP, **_on(
    'crm_manage_campaigns', 'crm_view_forecast', 'quotes_send', 'quotes_approve_discount',
    'contracts_download_signed', 'reports_manage_dashboards', 'crm_approve_commissions', 'reports_export',
))

_BILLING = _on(
    *VIEW_BASICS, 'billing_view_invoices', 'billing_send_invoices', 'billing_record_payments',
    'billing_view_aging', 'reports_view_financial', 'reports_manage_scheduled',
    'procurement_view', 'quotes_view', 'contracts_view', 'contracts_view_pricing', 'contracts_download_signed',
    'tickets_view', 'files_view', 'billing_approve_invoices', 'billing_issue_credit', 'billing_manage_charges',
    'reports_export', 'resourcing_view_payroll',
)

_AUDITOR = _on(
    *VIEW_BASICS, 'audit_view', 'tickets_view', 'tickets_view_all', 'tickets_view_internal',
    'assets_view', 'docs_view', 'monitoring_view', 'integrations_view', 'security_alerts_view',
    'change_view', 'problem_view', 'release_view', 'procurement_view', 'crm_view', 'quotes_view',
    'contracts_view', 'reports_view_sla', 'reports_view_capacity', 'vehicles_view',
)


def _rmm_flags():
    from .rmm_role_templates import BUILTIN_RMM_TEMPLATES
    return {tier: (name, flags) for name, tier, _d, flags in BUILTIN_RMM_TEMPLATES}


def _tech(tier):
    name, flags = _rmm_flags()[tier]
    extra = dict(tickets_view_internal=True, vehicles_view=True)
    if tier != 'l1':
        extra['reports_export'] = True
    return name, dict(flags, **extra)


# --- customer -------------------------------------------------------------------

_CUSTOMER_USER = _on('tickets_view', 'tickets_create', 'tickets_edit', 'kb_view_articles', 'docs_view',
                     'files_view', 'portal_tickets_create', 'portal_tickets_reply')
_CUSTOMER_READONLY = _on('tickets_view', 'kb_view_articles', 'docs_view', 'files_view')
_CUSTOMER_MANAGER = dict(_CUSTOMER_USER, **_on(
    'tickets_close', 'portal_tickets_view_org', 'assets_view', 'reports_view_dashboards', 'change_view',
    'release_view', 'org_view_members', 'portal_approve_requests', 'portal_agreements_view_org'))
_CUSTOMER_ADMIN = dict(_CUSTOMER_MANAGER, **_on(
    'org_invite_members', 'org_manage_members', 'files_upload', 'procurement_view'))


def definitions() -> List[RoleDef]:
    l1_name, l1 = _tech('l1')
    l2_name, l2 = _tech('l2')
    l3_name, l3 = _tech('l3')
    return [
        RoleDef('org_owner', 'Owner', 'internal',
                'Organization owner: full business administration, users and administrators, billing, '
                'security policy and ownership transfer. Not a platform superuser.',
                _OWNER, adopt=('Owner',), spec_name='Organization Owner'),
        RoleDef('org_admin', 'Organization Administrator', 'internal',
                'Manages users, roles, configuration and authorized integrations. No ownership transfer or '
                'owner-only operations; stored secrets need explicit vault permissions.', _ORG_ADMIN),
        RoleDef('service_manager', 'Service Manager', 'internal',
                'Service operations: queues, assignment, escalation, change / problem / release and service '
                'reports for authorized clients. No billing administration, secrets or security settings.',
                _SERVICE_MANAGER),
        RoleDef('tech_l1', l1_name, 'internal',
                'Level 1 Technician: assigned tickets and authorized client records, approved documentation '
                'and basic asset information. No stored passwords, remote shell, scripts, exports, '
                'integrations, user administration or destructive operations.',
                l1, adopt=(l1_name,), rmm_tier='l1', spec_name='Level 1 Technician'),
        RoleDef('tech_l2', l2_name, 'internal',
                'Level 2 Technician: Level 1 plus troubleshooting and asset-management actions. Remote '
                'access and credentials stay separate permissions.',
                l2, adopt=(l2_name,), rmm_tier='l2', spec_name='Level 2 Technician'),
        RoleDef('tech_l3', l3_name, 'internal',
                'Level 3 Technician: advanced technical work for authorized clients. Scripts, remote shell, '
                'credentials and destructive actions stay explicit permissions; no organization '
                'administration.',
                l3, adopt=(l3_name,), rmm_tier='l3', spec_name='Level 3 Technician'),
        RoleDef('sales_rep', 'Sales Representative', 'internal',
                'Leads, opportunities, quotes and contract drafts. No technical credentials, remote access, '
                'internal technical notes or security administration; sending contracts, approving '
                'discounts and countersigning are separate.', _SALES_REP),
        RoleDef('sales_manager', 'Sales Manager', 'internal',
                "The sales team's pipeline, quotes, pricing exceptions and forecast. Approving or sending "
                'contracts only when explicitly added.', _SALES_MANAGER),
        RoleDef('billing_finance', 'Billing / Finance', 'internal',
                'Billing records, invoices, payment status and financial reports; reads commercial '
                'agreements. No credentials, remote tools or security settings.', _BILLING),
        RoleDef('auditor', 'Internal Read-Only / Auditor', 'internal',
                'Reads authorized records, reports and the audit log. No editing or operational actions; '
                'secret reveal, file downloads and exports stay separate.', _AUDITOR),
        RoleDef('customer_admin', 'Customer Administrator', 'customer',
                "Manages the customer's portal users and contacts with approved customer roles; sees the "
                "organization's tickets and customer-visible documents and assets. Not a contract signer "
                'unless the Authorized Contract Signer role is added.', _CUSTOMER_ADMIN),
        RoleDef('customer_manager', 'Customer Manager', 'customer',
                "Views and coordinates the organization's tickets, submits requests, sees customer-visible "
                'reports and documents. No user administration.', _CUSTOMER_MANAGER),
        RoleDef('customer_user', 'Customer Standard User', 'customer',
                'Creates tickets and follows their own; sees what is shared with them. Not coworkers\' '
                'tickets, contracts or invoices.', _CUSTOMER_USER),
        RoleDef('customer_readonly', 'Customer Read-Only', 'customer',
                'Views specifically shared customer-facing information. No creating, editing, approvals or '
                'administration.', _CUSTOMER_READONLY),
        RoleDef('customer_billing_contact', 'Billing Contact', 'customer',
                'Add-on customer role: invoices and billing notices.', _on('portal_billing_contact')),
        RoleDef('customer_contract_reviewer', 'Contract Reviewer', 'customer',
                'Add-on customer role: reads contracts sent to the customer.',
                _on('portal_contract_review', 'portal_agreements_view_org')),
        RoleDef('customer_contract_signer', 'Authorized Contract Signer', 'customer',
                'Add-on customer role: signs contracts for the customer.',
                _on('portal_contract_sign', 'portal_contract_review', 'portal_agreements_view_org')),
        RoleDef('customer_request_approver', 'Request Approver', 'customer',
                'Add-on customer role: approves eligible service requests.', _on('portal_approve_requests')),
    ]


def as_frozen() -> List[dict]:
    """Plain-data copy of `definitions()` (what migrations freeze)."""
    out = []
    for d in definitions():
        out.append({'key': d.key, 'name': d.name, 'audience': d.audience, 'description': d.description,
                    'flags': {k: True for k, v in sorted(d.flags.items()) if v}, 'version': d.version,
                    'adopt': list(d.adopt), 'rmm_tier': d.rmm_tier})
    return out


def _field_names(RoleTemplate):
    from django.db import models
    skip = {'is_system_template', 'is_archived'}
    return [f.name for f in RoleTemplate._meta.get_fields()
            if isinstance(f, models.BooleanField) and f.name not in skip]


def _values(row, names):
    return {n: bool(getattr(row, n)) for n in names}


def seed_builtin_roles(RoleTemplate, defs=None, RoleReviewItem=None, source='seed', new_flag_keys=NEW_FLAG_KEYS):
    """Create / adopt / upgrade the built-in roles. Works on the live model
    and on a migration's historical model (pass `defs` as frozen dicts).

    Returns {'created': [...], 'adopted': [...], 'upgraded': [...],
             'kept_customized': [...], 'unchanged': [...], 'skipped': [...]}.
    """
    if RoleReviewItem is None:
        try:
            from .models import RoleReviewItem as RoleReviewItem  # noqa: N806
        except Exception:  # pragma: no cover
            RoleReviewItem = None
    if defs is None:
        defs = as_frozen()
    names = _field_names(RoleTemplate)
    summary = {k: [] for k in ('created', 'adopted', 'upgraded', 'kept_customized', 'unchanged', 'skipped')}

    def review(reason, row, detail):
        if RoleReviewItem is None:
            return
        RoleReviewItem.objects.get_or_create(reason=reason, role_template=row, status='open',
                                             defaults={'detail': detail, 'source': source})

    for d in defs:
        flags = {f: False for f in names}
        flags.update({k: bool(v) for k, v in d['flags'].items() if k in flags})
        tier = d.get('rmm_tier', '') or ''
        row = RoleTemplate.objects.filter(seed_key=d['key'], organization__isnull=True).first()
        if row is None:
            adopt = None
            for adopt_name in d.get('adopt') or ():
                adopt = RoleTemplate.objects.filter(name=adopt_name, organization__isnull=True,
                                                    seed_key='').first()
                if adopt is not None:
                    break
            if adopt is not None:
                # Adoption only adds: a permission the existing role already
                # holds (accounts 0046 preserved it) is never taken away.
                for k in new_flag_keys:
                    if k in flags:
                        setattr(adopt, k, bool(flags[k]) or bool(getattr(adopt, k)))
                adopt.seed_key = d['key']
                adopt.seed_version = d['version']
                if adopt.audience == 'any':
                    adopt.audience = d['audience']
                adopt.seed_checksum = checksum(_values(adopt, names), adopt.rmm_tier)
                adopt.save()
                summary['adopted'].append(adopt.name)
                continue
            if RoleTemplate.objects.filter(name=d['name'], organization__isnull=True).exists():
                clash = RoleTemplate.objects.filter(name=d['name'], organization__isnull=True).first()
                summary['skipped'].append(d['name'])
                review('other', clash, f"A role named '{d['name']}' already exists, so the built-in "
                                       f"'{d['key']}' role was not created. Rename one of them and reseed.")
                continue
            row = RoleTemplate.objects.create(
                name=d['name'], organization=None, is_system_template=True, description=d['description'],
                audience=d['audience'], rmm_tier=tier, seed_key=d['key'], seed_version=d['version'],
                seed_checksum=checksum(flags, tier), **flags)
            summary['created'].append(row.name)
            continue
        if row.seed_version >= d['version']:
            summary['unchanged'].append(row.name)
            continue
        if checksum(_values(row, names), row.rmm_tier) == row.seed_checksum:
            for k, v in flags.items():
                setattr(row, k, v)
            row.description = d['description']
            row.seed_version = d['version']
            row.seed_checksum = checksum(flags, row.rmm_tier)
            row.save()
            summary['upgraded'].append(row.name)
        else:
            summary['kept_customized'].append(row.name)
            review('builtin_customized', row,
                   f"'{row.name}' was customized, so version {d['version']} of the built-in definition was "
                   'not applied. Compare it with the built-in and update it by hand if wanted.')
    return summary
