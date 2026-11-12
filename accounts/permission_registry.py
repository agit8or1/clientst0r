"""
The permission registry: one described entry for every role permission.

Every boolean permission on `accounts.RoleTemplate` has exactly one entry
here (a test keeps the two in step). The key IS the RoleTemplate field name,
so it is stable: role templates, `user_has_org_perm(user, org, key)`, the
role editor, the generated matrix in docs/ROLES_AND_ACCESS.md and the audit
trail all use the same identifier.

Each entry says:

  key                 RoleTemplate field name
  module              the product area it belongs to (MODULES)
  action              what kind of action it allows (ACTIONS)
  sensitivity         standard / elevated / sensitive / critical
                      - sensitive: secrets, money, remote/script execution,
                        exports, contract signing
                      - critical: user/role/ownership administration,
                        security settings, API keys, platform configuration
                      A role holding any critical permission is a
                      "privileged role": assigning it needs
                      `org_manage_privileged` as well as `org_manage_members`
                      (accounts.delegation).
  customer_assignable whether a customer (portal) role may hold it. A
                      customer administrator can only hand out roles made
                      solely of customer-assignable permissions.
  status              enforced   - the application checks it
                      pending    - defined for a feature or check that is
                                   being wired up; stored, shown in the role
                                   editor as "not enforced yet"
                      unimplemented - the feature does not exist; stored only
  description         one line for the role editor and the matrix

New permissions are added with a model field that defaults to False, an
entry here, and (when existing access must be preserved) a data migration.

Capabilities that are NOT role flags are catalogued here too, read-only, so
the catalog is complete without a second permission system:
  - technician access (tech_access.catalog): ticket AI, RMM, remote access,
    fixes, per customer through access assignments;
  - RMM actions (rmm_permissions.catalog): RMM tier x customer assignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

# --- vocabularies -----------------------------------------------------------

ACTIONS = {
    'view': 'View / list',
    'create': 'Create',
    'edit': 'Edit',
    'delete': 'Delete',
    'assign': 'Assign / reassign',
    'approve': 'Approve',
    'send': 'Send / publish',
    'download': 'Download',
    'export': 'Export / bulk export',
    'reveal': 'Reveal / copy secrets',
    'execute': 'Execute scripts / actions',
    'remote': 'Open remote sessions',
    'settings': 'Manage settings',
    'users': 'Manage users',
    'roles': 'Manage roles',
    'audit': 'View audit history',
    'sign': 'Sign / countersign',
}

STANDARD, ELEVATED, SENSITIVE, CRITICAL = 'standard', 'elevated', 'sensitive', 'critical'
SENSITIVITY_RANK = {STANDARD: 0, ELEVATED: 1, SENSITIVE: 2, CRITICAL: 3}

ENFORCED, PENDING, UNIMPLEMENTED = 'enforced', 'pending', 'unimplemented'

# module key -> (label, description). Order is the role editor's order.
MODULES = {
    'org': ('Organization & users', 'Members, invitations, roles, ownership and organization settings.'),
    'tickets': ('Tickets & queues', 'PSA tickets, internal notes, assignment, routing and sharing.'),
    'service': ('Service management', 'Change, problem, release and service catalog governance.'),
    'assets': ('Assets & inventory', 'Assets, hardware and network discovery.'),
    'docs': ('Documentation', 'Documents, diagrams and their publication.'),
    'kb': ('Knowledge base', 'KB articles and categories.'),
    'files': ('Files & attachments', 'Uploaded files, photos and attachments.'),
    'vault': ('Passwords & secrets', 'The password vault and the browser extension.'),
    'monitoring': ('Monitoring & alerts', 'Website / WAN monitors, expirations, racks, IPAM.'),
    'security': ('Security alerts', 'EDR / AV / firewall alert ingestion and rules.'),
    'integrations': ('Integrations & RMM', 'PSA / RMM / M365 and other connections and syncs.'),
    'sales': ('Sales, quotes & CRM', 'Leads, pipeline, campaigns, forecast and quotes.'),
    'contracts': ('Contracts & signing', 'Contract generator: drafts, approval, signing and evidence.'),
    'billing': ('Billing & finance', 'Invoices, payments, aging.'),
    'procurement': ('Procurement', 'Purchase requisitions and purchase orders.'),
    'reports': ('Reports & dashboards', 'Dashboards, financial / SLA / capacity reports, schedules.'),
    'resourcing': ('Resourcing', 'Team roster, cost rates, leave and holidays.'),
    'api': ('API & automation', 'API access and API keys.'),
    'audit': ('Audit logs', 'Audit trail viewing and export.'),
    'ai': ('AI assistance (OPTIONAL AI)', 'AI suggestions, replies and actions; gated by psa_ai_enabled.'),
    'operations': ('Operations', 'Fleet vehicles, scheduling wallboard, workflow rules, timesheets, payroll.'),
    'portal': ('Customer portal', 'What a customer user may do in the portal beyond the basics.'),
}


@dataclass(frozen=True)
class Permission:
    key: str
    module: str
    action: str
    sensitivity: str
    customer_assignable: bool
    description: str
    status: str = ENFORCED
    staff_only: bool = False      # never effective for a customer user, whatever the role says

    @property
    def label(self) -> str:
        return self.description

    @property
    def module_label(self) -> str:
        return MODULES[self.module][0]

    @property
    def action_label(self) -> str:
        return ACTIONS[self.action]

    @property
    def privileged(self) -> bool:
        return self.sensitivity == CRITICAL


def _p(key, module, action, sensitivity, customer, description, status=ENFORCED, staff_only=False):
    return Permission(key, module, action, sensitivity, customer, description, status, staff_only)


S, E, X, C = STANDARD, ELEVATED, SENSITIVE, CRITICAL

PERMISSIONS: List[Permission] = [
    # --- organization & users ------------------------------------------------
    _p('org_view_members', 'org', 'view', S, True, 'View organization members'),
    _p('org_invite_members', 'org', 'users', E, True, 'Invite new members'),
    _p('org_manage_members', 'org', 'users', E, True,
       'Manage ordinary members: edit, suspend, remove, assign non-privileged roles'),
    _p('org_manage_privileged', 'org', 'roles', C, False,
       'Assign or remove privileged roles (roles holding user, role, security or platform administration)'),
    _p('roles_manage', 'org', 'roles', C, False, 'Create, clone, edit and archive custom roles'),
    _p('org_manage_settings', 'org', 'settings', C, False, 'Change organization settings'),
    _p('org_owner', 'org', 'roles', C, False,
       'Organization owner: ownership transfer, owner-only operations, billing and security policy. '
       'Only granted through ownership transfer.'),

    # --- tickets & queues --------------------------------------------------------
    _p('tickets_view', 'tickets', 'view', S, True, 'View tickets in the PSA / mobile surfaces'),
    _p('tickets_create', 'tickets', 'create', S, True, 'File new tickets'),
    _p('tickets_edit', 'tickets', 'edit', S, True, 'Edit ticket subject / description / status / priority'),
    _p('tickets_assign', 'tickets', 'assign', E, False, 'Assign a ticket to another user (re-assignment)'),
    _p('tickets_view_all', 'tickets', 'view', E, False,
       'View tickets across all organizations (not just those the user is a member of)'),
    _p('tickets_close', 'tickets', 'edit', S, True, 'Move a ticket to a terminal status (resolved / closed)'),
    _p('tickets_delete', 'tickets', 'delete', X, False, 'Hard-delete a ticket'),
    _p('tickets_view_internal', 'tickets', 'view', E, False,
       'See internal ticket notes and internal-only attachments (MSP staff only)', PENDING, staff_only=True),
    _p('outsourcing_share_tickets', 'tickets', 'send', X, False,
       'Share a ticket with an outsourcing partner via signed webhook'),
    _p('routing_manage_rules', 'tickets', 'settings', E, False,
       'Ticket routing: change settings, customer overrides, rules and on-call shifts', staff_only=True),
    _p('routing_test', 'tickets', 'view', S, False, 'Ticket routing: use Test routing (read-only dry run)',
       staff_only=True),
    _p('routing_override', 'tickets', 'approve', E, False, 'Ticket routing: accept or reject routing suggestions',
       staff_only=True),

    # --- service management -----------------------------------------------------
    _p('change_view', 'service', 'view', S, True, 'View change requests'),
    _p('change_create', 'service', 'create', S, False, 'Submit a change request for CAB review'),
    _p('change_approve_cab', 'service', 'approve', E, False, 'Sit on the CAB and vote on changes'),
    _p('change_implement', 'service', 'execute', E, False, 'Move an approved change into Implementing'),
    _p('problem_view', 'service', 'view', S, False, 'View problems'),
    _p('problem_create', 'service', 'create', S, False, 'Create problems'),
    _p('problem_assign', 'service', 'assign', E, False, 'Assign problems to investigators / reassign owners'),
    _p('problem_resolve', 'service', 'edit', E, False, 'Move a problem to resolved / closed'),
    _p('release_view', 'service', 'view', S, True, 'View release windows'),
    _p('release_manage', 'service', 'edit', E, False, 'Create / edit release windows and bundle changes'),
    _p('release_freeze', 'service', 'approve', E, False, 'Flip a release to frozen / completed / rolled back'),
    _p('catalog_propose_change', 'service', 'create', S, False, 'Propose edits to a service catalog item'),
    _p('catalog_approve_change', 'service', 'approve', E, False, 'Approve / reject service catalog change proposals'),

    # --- assets -----------------------------------------------------------------
    _p('assets_view', 'assets', 'view', S, True, 'View assets'),
    _p('assets_create', 'assets', 'create', S, False, 'Create assets'),
    _p('assets_edit', 'assets', 'edit', S, False, 'Edit assets'),
    _p('assets_delete', 'assets', 'delete', E, False, 'Delete assets'),
    _p('network_discovery_generate', 'assets', 'execute', X, False,
       'Generate remote network discovery scripts and tokens'),
    _p('netconfig_view_configs', 'assets', 'reveal', X, False,
       'Read stored device configurations (may contain secrets)', PENDING),

    # --- documentation / KB / files ---------------------------------------------
    _p('docs_view', 'docs', 'view', S, True, 'View documents'),
    _p('docs_create', 'docs', 'create', S, True, 'Create documents'),
    _p('docs_edit', 'docs', 'edit', S, True, 'Edit documents'),
    _p('docs_delete', 'docs', 'delete', E, False, 'Delete documents'),
    _p('docs_publish', 'docs', 'send', E, False, 'Publish / unpublish documents'),
    _p('docs_view_internal', 'docs', 'view', X, True,
       'Customer users: see internal documentation (internal blocks, MSP-written source and versions)',
       PENDING),
    _p('kb_view_articles', 'kb', 'view', S, True, 'View KB articles'),
    _p('kb_edit_articles', 'kb', 'edit', S, False, 'Create / edit / delete KB articles'),
    _p('kb_move_articles', 'kb', 'edit', S, False, 'Move KB articles between categories'),
    _p('kb_manage_categories', 'kb', 'settings', E, False, 'Create / edit / delete KB categories'),
    _p('kb_publish_articles', 'kb', 'send', E, False, 'Publish / unpublish KB articles'),
    _p('files_view', 'files', 'download', S, True, 'View and download files'),
    _p('files_upload', 'files', 'create', S, True, 'Upload files'),
    _p('files_delete', 'files', 'delete', E, False, 'Delete files'),

    # --- vault ------------------------------------------------------------------
    _p('vault_view', 'vault', 'view', E, True, 'List vault entries (titles and metadata, not values)'),
    _p('vault_create', 'vault', 'create', X, True, 'Create passwords and secrets'),
    _p('vault_edit', 'vault', 'edit', X, True, 'Edit passwords and secrets'),
    _p('vault_delete', 'vault', 'delete', X, False, 'Delete passwords and secrets'),
    _p('vault_export', 'vault', 'export', X, False, 'Export passwords (no bulk export exists yet)', UNIMPLEMENTED),
    _p('vault_view_password', 'vault', 'reveal', X, True, 'Reveal / copy password values'),
    _p('vault_approve_reveal', 'vault', 'approve', X, False,
       "Approve another technician's password reveal request", PENDING),
    _p('vault_manage_access_rules', 'vault', 'settings', C, False, 'Manage vault GeoIP / IP / time access rules'),
    _p('vault_extension_use', 'vault', 'reveal', X, False, 'Use the browser extension (autofill / TOTP / reveal)'),
    _p('vault_extension_offline_cache', 'vault', 'export', X, False,
       'Let the browser extension bulk-sync the visible vault for offline use'),

    # --- monitoring / security alerts -------------------------------------------
    _p('monitoring_view', 'monitoring', 'view', S, True, 'View monitors'),
    _p('monitoring_create', 'monitoring', 'create', S, False, 'Create monitors'),
    _p('monitoring_edit', 'monitoring', 'edit', S, False, 'Edit monitors'),
    _p('monitoring_delete', 'monitoring', 'delete', E, False, 'Delete monitors'),
    _p('monitoring_trigger', 'monitoring', 'execute', S, False, 'Manually trigger checks'),
    _p('security_alerts_view', 'security', 'view', S, False, 'View the security alert triage list', staff_only=True),
    _p('security_alerts_manage_connections', 'security', 'settings', C, False,
       'Create / edit / delete EDR / AV / firewall connections', staff_only=True),
    _p('security_alerts_acknowledge', 'security', 'edit', E, False,
       'Acknowledge / dismiss / resolve alerts, convert to tickets', staff_only=True),
    _p('security_alerts_create_rules', 'security', 'settings', E, False,
       'Create / edit / delete auto-ticket rules and suppression windows', staff_only=True),

    # --- integrations -----------------------------------------------------------
    _p('integrations_view', 'integrations', 'view', S, False, 'View integrations'),
    _p('integrations_view_synced_psa', 'integrations', 'view', E, False,
       'View synced PSA companies, contacts and tickets (raw provider data)', PENDING, staff_only=True),
    _p('integrations_configure', 'integrations', 'settings', C, False, 'Configure integrations'),
    _p('integrations_sync', 'integrations', 'execute', E, False, 'Trigger sync operations'),

    # --- sales / quotes / CRM ---------------------------------------------------
    _p('crm_view', 'sales', 'view', S, False, 'View leads, opportunities, campaigns and the pipeline',
       staff_only=True),
    _p('crm_create_lead', 'sales', 'create', S, False, 'Create / edit leads', staff_only=True),
    _p('crm_manage_pipeline', 'sales', 'edit', E, False, 'Move opportunities through stages, convert leads',
       staff_only=True),
    _p('crm_manage_campaigns', 'sales', 'edit', E, False, 'Create / edit marketing campaigns and view ROI',
       staff_only=True),
    _p('crm_view_forecast', 'sales', 'view', X, False, 'See the weighted pipeline forecast', staff_only=True),
    _p('crm_approve_commissions', 'sales', 'approve', X, False, 'Decide and pay out sales commissions',
       PENDING, staff_only=True),
    _p('quotes_view', 'sales', 'view', S, False, 'View quotes and the priced service catalog', PENDING,
       staff_only=True),
    _p('quotes_edit', 'sales', 'edit', E, False, 'Create and edit draft quotes', PENDING, staff_only=True),
    _p('quotes_send', 'sales', 'send', E, False, 'Send quotes to customers for acceptance', PENDING,
       staff_only=True),
    _p('quotes_approve_discount', 'sales', 'approve', X, False,
       'Approve discounts and pricing exceptions on quotes', PENDING, staff_only=True),

    # --- contracts & signing (contract generator) -------------------------------
    _p('contracts_view', 'contracts', 'view', E, False, 'View contracts', ENFORCED, staff_only=True),
    _p('contracts_view_pricing', 'contracts', 'view', X, False,
       'View commercial terms and pricing in contracts', ENFORCED, staff_only=True),
    _p('contracts_edit_draft', 'contracts', 'edit', E, False, 'Create and edit contract drafts', ENFORCED,
       staff_only=True),
    _p('contracts_manage_templates', 'contracts', 'settings', X, False,
       'Manage contract templates and reusable clauses', ENFORCED, staff_only=True),
    _p('contracts_submit_approval', 'contracts', 'send', E, False, 'Submit a contract for internal approval',
       ENFORCED, staff_only=True),
    _p('contracts_approve', 'contracts', 'approve', X, False, 'Approve a specific contract version', ENFORCED,
       staff_only=True),
    _p('contracts_send', 'contracts', 'send', X, False, 'Send / resend signing invitations', ENFORCED,
       staff_only=True),
    _p('contracts_manage_links', 'contracts', 'send', X, False, 'Generate / revoke signing links', ENFORCED,
       staff_only=True),
    _p('contracts_countersign', 'contracts', 'sign', X, False, 'Countersign contracts for the provider', ENFORCED,
       staff_only=True),
    _p('contracts_void', 'contracts', 'delete', X, False, 'Void or supersede a contract', ENFORCED,
       staff_only=True),
    _p('contracts_download_signed', 'contracts', 'download', X, False, 'Download signed agreements', ENFORCED,
       staff_only=True),
    _p('contracts_view_audit', 'contracts', 'audit', X, False, 'View detailed signing audit evidence', ENFORCED,
       staff_only=True),
    _p('contracts_settings', 'contracts', 'settings', C, False,
       'Configure signing and contract notification settings', ENFORCED, staff_only=True),

    # --- billing / procurement --------------------------------------------------
    _p('billing_view_invoices', 'billing', 'view', X, False, 'View invoices'),
    _p('billing_send_invoices', 'billing', 'send', X, False, 'Send invoices'),
    _p('billing_record_payments', 'billing', 'edit', X, False, 'Record payments'),
    _p('billing_view_aging', 'billing', 'view', X, False, 'See the cross-client aging report', staff_only=True),
    _p('billing_approve_invoices', 'billing', 'approve', X, False, 'Approve invoices through the approval gate',
       PENDING, staff_only=True),
    _p('billing_issue_credit', 'billing', 'edit', X, False, 'Issue credit memos', PENDING, staff_only=True),
    _p('billing_manage_charges', 'billing', 'edit', X, False,
       'Add charges, invoice tickets / projects and push invoices to accounting', PENDING, staff_only=True),
    _p('procurement_view', 'procurement', 'view', S, True, 'View purchase requisitions and orders'),
    _p('procurement_create_pr', 'procurement', 'create', S, False, 'Create / edit purchase requisitions'),
    _p('procurement_approve_pr', 'procurement', 'approve', E, False, 'Approve / reject purchase requisitions'),
    _p('procurement_create_po', 'procurement', 'create', E, False, 'Create / edit purchase orders'),
    _p('procurement_send_po', 'procurement', 'send', E, False, 'Email purchase orders to vendors'),

    # --- reports / resourcing ---------------------------------------------------
    _p('reports_view_dashboards', 'reports', 'view', S, True, 'View dashboards'),
    _p('reports_view_financial', 'reports', 'view', X, False,
       'Profitability, effective rate, revenue leakage, margin analytics'),
    _p('reports_view_sla', 'reports', 'view', E, False, 'SLA trend report', staff_only=True),
    _p('reports_view_capacity', 'reports', 'view', E, False, 'Capacity / utilization report', staff_only=True),
    _p('reports_manage_dashboards', 'reports', 'edit', E, False, 'Create / edit / delete dashboards and widgets'),
    _p('reports_manage_scheduled', 'reports', 'export', X, False, 'Configure scheduled reports'),
    _p('reports_export', 'reports', 'export', X, False,
       'Export reports (CSV / PDF), saved-query results and generated report files', PENDING, staff_only=True),
    _p('resourcing_view_team', 'resourcing', 'view', E, False, 'See the staff roster and cost rates',
       staff_only=True),
    _p('resourcing_manage_cost_rates', 'resourcing', 'edit', X, False, 'Edit per-tech loaded cost rates',
       staff_only=True),
    _p('resourcing_approve_leave', 'resourcing', 'approve', E, False, 'Approve / deny leave requests',
       staff_only=True),
    _p('resourcing_manage_holidays', 'resourcing', 'settings', E, False,
       "Manage holidays (an organization's own business-hours calendar)"),

    # --- operations -----------------------------------------------------------------
    _p('vehicles_view', 'operations', 'view', S, False, 'View fleet vehicles, receipts and vehicle inventory',
       PENDING, staff_only=True),
    _p('vehicles_manage', 'operations', 'edit', E, False,
       'Create, edit and delete vehicles, receipts and vehicle inventory', PENDING, staff_only=True),
    _p('scheduling_manage_wallboard', 'operations', 'settings', E, False,
       'Configure the public scheduling wallboard', PENDING, staff_only=True),
    _p('psa_manage_workflow_rules', 'operations', 'settings', E, False,
       'Manage ticket workflow rules and workflow templates', PENDING, staff_only=True),
    _p('timesheets_approve', 'operations', 'approve', E, False, 'Review and approve timesheets', PENDING,
       staff_only=True),
    _p('resourcing_view_payroll', 'operations', 'export', X, False,
       'Timeclock dashboard and payroll export', PENDING, staff_only=True),

    # --- API / audit --------------------------------------------------------------
    _p('api_access', 'api', 'view', E, False, 'Access API endpoints'),
    _p('api_keys_manage', 'api', 'settings', C, False, 'Create / manage API keys'),
    _p('audit_view', 'audit', 'audit', E, False, 'View audit logs'),
    _p('audit_export', 'audit', 'export', X, False, 'Export audit logs'),

    # --- AI (OPTIONAL AI) -------------------------------------------------------
    _p('psa_ai_view', 'ai', 'view', S, False, 'View AI suggestions and the AI inbox', staff_only=True),
    _p('psa_ai_request_triage', 'ai', 'view', S, False, 'Request read-only AI triage guidance', staff_only=True),
    _p('psa_ai_send_low_risk', 'ai', 'send', E, False, 'Send low-risk AI replies as public comments',
       staff_only=True),
    _p('psa_ai_send_high_risk', 'ai', 'send', X, False, 'Send medium- or high-risk AI replies', staff_only=True),
    _p('psa_ai_approve_reply', 'ai', 'approve', E, False, "Approve another user's pending AI reply",
       staff_only=True),
    _p('psa_ai_apply_low_risk', 'ai', 'edit', E, False, 'Apply low-risk AI actions', staff_only=True),
    _p('psa_ai_apply_high_risk', 'ai', 'edit', X, False, 'Apply medium- or high-risk AI actions',
       staff_only=True),
    _p('psa_ai_approve_action', 'ai', 'approve', E, False, "Approve another user's pending AI action",
       staff_only=True),
    _p('psa_ai_run_script', 'ai', 'execute', X, False, 'Run an AI-suggested RMM script against an asset',
       staff_only=True),
    _p('psa_ai_create_workflow', 'ai', 'create', E, False, 'Create or assign a workflow from an AI suggestion',
       staff_only=True),
    _p('psa_ai_billing', 'ai', 'edit', X, False, 'Modify financial fields via AI', staff_only=True),
    _p('psa_ai_admin', 'ai', 'settings', C, False, 'Configure AI (model, threshold, allow/blocklist, voice)',
       staff_only=True),

    # --- customer portal ----------------------------------------------------------
    _p('portal_tickets_view_org', 'portal', 'view', S, True,
       "See every shared ticket of the customer, not only the user's own"),
    _p('portal_tickets_create', 'portal', 'create', S, True,
       'File tickets and service requests in the portal'),
    _p('portal_tickets_reply', 'portal', 'edit', S, True,
       'Reply, send secure replies, escalate and vote on tickets the user can see'),
    _p('portal_approve_requests', 'portal', 'approve', E, True,
       'Request approver: decide client approvals for the customer'),
    _p('portal_agreements_view_org', 'portal', 'view', X, True,
       "See coworkers' agreement signatures and their evidence (not only the user's own)"),
    _p('portal_billing_contact', 'portal', 'view', X, True,
       'Billing contact: see invoices and billing notices for the customer', PENDING),
    _p('portal_contract_review', 'portal', 'view', E, True,
       'Contract reviewer: read contracts sent to the customer', PENDING),
    _p('portal_contract_sign', 'portal', 'sign', X, True,
       'Authorized contract signer: sign contracts for the customer', ENFORCED),
]

REGISTRY: Dict[str, Permission] = {p.key: p for p in PERMISSIONS}
assert len(REGISTRY) == len(PERMISSIONS), 'duplicate permission key'
for _perm in PERMISSIONS:
    assert _perm.module in MODULES, _perm
    assert _perm.action in ACTIONS, _perm
    assert _perm.sensitivity in SENSITIVITY_RANK, _perm
del _perm

ALL_KEYS = tuple(REGISTRY)
PRIVILEGED_KEYS = frozenset(k for k, p in REGISTRY.items() if p.privileged)
SENSITIVE_KEYS = frozenset(k for k, p in REGISTRY.items()
                           if SENSITIVITY_RANK[p.sensitivity] >= SENSITIVITY_RANK[SENSITIVE])
CUSTOMER_ASSIGNABLE_KEYS = frozenset(k for k, p in REGISTRY.items() if p.customer_assignable)
STAFF_ONLY_KEYS = frozenset(k for k, p in REGISTRY.items() if p.staff_only)
# Only the ownership-transfer workflow may give these to a membership.
TRANSFER_ONLY_KEYS = frozenset({'org_owner'})


def get(key: str) -> Optional[Permission]:
    return REGISTRY.get(key)


def is_known(key: str) -> bool:
    return key in REGISTRY


def by_module() -> List[tuple]:
    """[(module_key, label, description, [Permission, ...]), ...] in MODULES order."""
    out = []
    for mkey, (label, desc) in MODULES.items():
        perms = [p for p in PERMISSIONS if p.module == mkey]
        if perms:
            out.append((mkey, label, desc, perms))
    return out


def search(query: str) -> List[Permission]:
    q = (query or '').strip().lower()
    if not q:
        return list(PERMISSIONS)
    return [p for p in PERMISSIONS
            if q in p.key or q in p.description.lower() or q in p.module_label.lower()
            or q in p.action_label.lower()]


def flags_of(perms) -> Dict[str, bool]:
    """{key: bool} for every registry key from a RoleTemplate / permissions object."""
    return {k: bool(getattr(perms, k, False)) for k in ALL_KEYS}


def granted_keys(perms) -> frozenset:
    return frozenset(k for k in ALL_KEYS if getattr(perms, k, False))


def has_platform_tier(role_template) -> bool:
    """The role carries an RMM tier (a platform role; set by the RMM tier
    templates, never by the role editor)."""
    return bool(getattr(role_template, 'rmm_tier', ''))


def is_privileged_role(role_template) -> bool:
    """A role holding any critical permission, an RMM tier or ownership."""
    if role_template is None:
        return False
    if getattr(role_template, 'rmm_tier', ''):
        return True
    return any(getattr(role_template, k, False) for k in PRIVILEGED_KEYS)


def non_customer_keys(perms) -> List[str]:
    """Granted keys a customer role may not hold."""
    return sorted(k for k in granted_keys(perms) if k not in CUSTOMER_ASSIGNABLE_KEYS)


# --- capabilities governed elsewhere (catalogued, not role flags) ------------

def external_catalog() -> List[dict]:
    """Technician-access capabilities and RMM actions, for the catalog page and
    the generated matrix. They are decided by tech_access.resolver.decide and
    rmm_permissions.can(), per customer, never by a role flag alone."""
    rows = []
    try:
        from tech_access import catalog as ta
        for key, (label, group, desc, _states) in ta.OPTIONAL.items():
            rows.append({'source': 'Technician access', 'key': f'tech_access:{key}', 'label': label,
                         'group': group, 'description': desc, 'locked': False})
        for key, (label, desc) in ta.LOCKED.items():
            rows.append({'source': 'Technician access', 'key': f'tech_access:{key}', 'label': label,
                         'group': 'Locked safeguard', 'description': desc, 'locked': True})
    except Exception:  # pragma: no cover - app missing
        pass
    try:
        from rmm_permissions import catalog as rc
        for key, a in rc.ACTIONS.items():
            rows.append({'source': 'RMM actions', 'key': f'rmm:{key}', 'label': a.label, 'group': a.group,
                         'description': a.description, 'locked': False})
        for key, desc in rc.LOCKED.items():
            rows.append({'source': 'RMM actions', 'key': f'rmm:{key}', 'label': key, 'group': 'Locked',
                         'description': desc, 'locked': True})
    except Exception:  # pragma: no cover
        pass
    return rows


# How each installed application is governed, for the coverage section of
# docs/ROLES_AND_ACCESS.md. Apps not listed are infrastructure (no user data).
MODULE_COVERAGE = {
    'accounts': 'org_* / roles_manage / org_owner; accounts.delegation for every assignment path',
    'core': 'organization switcher + client scope (accounts.scope); settings are superuser-only',
    'vault': 'vault_* per customer (accounts.permission_utils.user_has_org_perm, vault.permissions)',
    'assets': 'assets_* (section gate /assets/, /hardware/) + per-customer lookups',
    'hardware': 'assets_* (hardware.access)',
    'docs': 'docs_* and kb_* (section gate /docs/)',
    'readiness': 'MSP staff only + per-customer lookups',
    'files': 'files_* per customer',
    'audit': 'audit_view / audit_export',
    'api': 'api_access / api_keys_manage; API key level caps the owner (api.permissions)',
    'api_mobile': 'tickets_* / assets_* per customer, mobile session tokens',
    'integrations': 'integrations_* (section gate /integrations/), RMM via rmm_permissions + tech_access',
    'monitoring': 'monitoring_* (section gate /monitoring/)',
    'processes': 'membership write role (require_write) per customer',
    'locations': 'membership write role per customer',
    'imports': 'superuser / org_manage_settings',
    'reports': 'reports_* (MSP staff only section)',
    'vehicles': 'membership write role per customer',
    'inventory': 'membership write / admin role per customer',
    'scheduling': 'membership write / admin role per customer',
    'psa': 'tickets_*, billing_*, procurement_*, change_* / problem_* / release_* / catalog_*, quotes_*',
    'psa.routing': 'routing_*',
    'psa.support_workflows': 'MSP staff + tickets_*',
    'psa_ai': 'psa_ai_* (OPTIONAL AI, gated by psa_ai_enabled) + technician access ai_* capabilities',
    'tech_access': 'technician access assignments (capability x customer x expiry); protected changes',
    'rmm_permissions': 'RMM tier from the global role x technician access assignment',
    'portal': 'customer membership + portal_* permissions; never internal notes or other customers',
    'resourcing': 'resourcing_* (MSP staff)',
    'crm': 'crm_* (MSP staff only section)',
    'security_alerts': 'security_alerts_* (MSP staff only section)',
    'compliance': 'membership role per customer',
    'field_ops': 'MSP staff + tickets_*',
    'statuspage': 'membership admin role',
    'netconfig': 'MSP staff + per-customer lookups',
    'network_discovery': 'network_discovery_generate + assets_*',
    'office': 'docs_* / files_* per customer',
    'contracts': 'contracts_* (staff) and portal_contract_* (customer) via accounts.contract_access',
}
