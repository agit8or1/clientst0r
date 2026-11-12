# Roles and access

How Client St0r decides who may do what, for MSP staff and for customer users. Everything here is enforced on the
server; hiding a button is never the check.

## Concepts

- **Permission**: one named capability, such as `tickets_edit` or `contracts_countersign`. Every permission is listed
  in the permission registry (`accounts/permission_registry.py`) with its module, kind of action, sensitivity, whether
  a customer role may hold it, and a description. New sensitive permissions are always off by default.
- **Role**: a set of permissions (a role template). Built-in roles ship with the product. Custom roles belong to one
  organization. Roles can be created, cloned, renamed and archived. Archiving keeps a role on the people who hold it
  but stops anyone assigning it again.
- **Membership**: a person's access to one organization. It has a primary role, optional *additional roles*, and a
  *record scope*.
- **Global role** (MSP staff only): the role a technician holds across clients. Its *client scope* decides which
  clients it reaches: all of them, the clients where the technician has a live technician access assignment, or a
  selected list (with their subsidiaries).
- **Record scope**: within an organization, a membership or global role covers the whole organization, only the
  records assigned to the person, or only the records they created.

## How roles combine

- Roles add up **within one membership**: the primary role plus the additional roles, evaluated at that organization.
- Each grant keeps its own scope. A permission from one organization never applies in another. A wide view in one
  grant never widens a narrow edit right in another. Example: *edit own tickets* at Customer A plus *view all
  tickets* at Customer B does not let you edit someone else's ticket anywhere.
- A parent organization's membership covers its subsidiaries.
- Customer users are evaluated for the organization they have selected. A permission from one customer's membership
  does not open a page while another customer is selected. `user_has_perm_any_org` is the explicit cross-organization
  helper for the few places (background jobs, menus) that need "anywhere".
- *Staff only* permissions (internal notes, quotes, CRM, resourcing team data, AI and similar) never
  take effect for a customer user, whatever their role says.

## Helpers for application code

| Question | Helper |
|---|---|
| May this user do X at this organization? | `accounts.permission_utils.user_has_org_perm(user, org, perm)` |
| May this user do X at the selected organization? | `user_has_perm(user, perm)` (in a request) |
| Anywhere at all (explicitly cross-organization)? | `user_has_perm_any_org(user, perm)` |
| Which rows of a queryset may this user act on? | `accounts.scope.scoped_queryset(qs, user, perm, ...)` |
| This one record? | `accounts.scope.can_access_object(user, perm, obj, ...)` |
| Which portal tickets may a customer user see? | `accounts.scope.portal_ticket_queryset(qs, membership, user)` |
| Contract actions | `accounts.contract_access.can_contract(user, contract_org, action, contract=None)` |
| Should this person receive an alert about X? | `accounts.alert_access.may_receive_alert(user, perm, organization, obj)` |
| Why does someone have access? | `explain_access(user, org, perm)`, also the **Why?** page |

Check alert recipients both when the alert is generated and again when it is delivered, so someone whose access was
revoked in between gets nothing.

## Contracts

Provider actions need `contracts_view` plus the action's own permission for that customer: view pricing, edit drafts,
submit for approval, approve, send, manage signing links, countersign, void, download signed copies, view the audit
trail. Templates and contract settings are provider-wide. Nobody approves a contract version they wrote or submitted.

Customer actions come from the customer membership: **Contract Reviewer** reads contracts sent to the customer,
**Authorized Contract Signer** signs them (only through a membership in the contract's own customer, not a parent's),
and **Billing Contact** sees pricing and invoices. A **Customer Administrator is not a signer** unless the Authorized
Contract Signer role is added. External signers without an account are handled by the contracts app's signing link,
which opens exactly one contract version and nothing else.

## Delegation and escalation protection

1. Superusers may assign anything; it is still audited.
2. Nobody changes their own role, scope or membership status.
3. Managing ordinary members needs `org_manage_members` at **that** organization: the one in the URL, not the one
   selected in the session. Assigning or removing a *privileged* role needs `org_manage_privileged` as well. A role
   is privileged when it holds a critical permission (user, role, settings, security or platform administration, an
   RMM tier, or ownership).
4. **Subset rule**: you can only hand out a role whose permissions you hold yourself at that organization, including
   additional roles.
5. **Ownership** is never assigned through member or role forms. It moves only through **Transfer ownership**, which
   asks for your password and the organization's name and is recorded.
6. Customer administrators assign customer roles only. They never assign roles to MSP staff or superusers, and never
   platform roles.
7. Organization settings never confer platform access. Superuser, staff type, global roles and client scope are
   changed by superusers only.
8. You can not edit, suspend or remove a member whose access exceeds yours.
9. The **last active owner** of an organization can not be removed, suspended, demoted or deactivated. Transfer
   ownership first.
10. Moving an organization under another parent needs settings rights at both. Creating organizations is for MSP
    staff and superusers.

There is no impersonation ("log in as") feature. If one is added, it needs its own permission and audit trail.

Every refusal of a privileged action is written to the audit log (`delegation.denied` / `access.denied`).

## Audit trail

Role, membership, additional-role, scope, global-role, account-status, invitation and ownership changes are written to
the audit log with before and after values. Values are reduced to safe forms: permission booleans, role names and ids,
scope names. Passwords, secrets, tokens and signing links are never recorded.

## Role management pages

| Page | URL |
|---|---|
| Roles (list, built-in / customized badges, unused roles) | `/accounts/roles/` |
| Role detail (holders, permissions by module) | `/accounts/roles/<id>/` |
| Create / edit with preview before saving | `/accounts/roles/create/`, `/accounts/roles/<id>/edit/` |
| Clone / archive | `/accounts/roles/<id>/clone/`, `/accounts/roles/<id>/archive/` (POST) |
| Compare roles | `/accounts/roles/compare/` |
| Why does someone have access? | `/accounts/roles/why/` |
| Permission catalog (and unassigned permissions) | `/accounts/roles/catalog/` |
| Customer portal access settings | `/accounts/roles/portal-access/` |
| Assign a member's roles and record scope | `/accounts/members/<user_id>/assign-role/` |
| Assignments to review (superuser) | `/accounts/roles/review/` |
| Transfer ownership | `/accounts/organizations/<id>/transfer-ownership/` |

## Upgrading from earlier releases

The upgrade never infers authority from a username, email address or job title, never removes an owner and never
silently grants a powerful role.

- Existing custom roles keep what they could do. New permissions that split an old one are switched on where the old
  permission was: role management and privileged member management where the role managed settings (and members),
  quotes where the role could edit anything, and internal ticket notes, which every staff member could see before.
  Portal behaviour everyone had (organization-wide shared tickets, filing and replying, deciding client approvals,
  coworkers' agreement signatures) stays on. Invoice approval, credit memos and charges follow
  `billing_send_invoices`, commissions follow `crm_view_forecast`, timesheet approval follows
  `resourcing_approve_leave`, the wallboard and workflow rules follow `org_manage_settings`, fleet management follows
  any write permission, password reveal approval and stored device configurations follow `vault_view_password`,
  synced PSA data follows `integrations_view`, and report export and fleet viewing stay on. Internal documentation for
  customer users (`docs_view_internal`) is never granted automatically. Contract permissions, ownership and payroll go
  only to Owner and Full Administrator style system roles. Billing contact, contract reviewer and signer are never
  granted automatically. Memberships on a simple role (Owner, Admin, Editor, Read-only) follow the same rules.
- The existing **Owner** template and the **RMM L1/L2/L3** templates are adopted as the built-in Owner and Level 1–3
  Technician roles. Adoption only adds permissions. New built-in roles are created next to them. An existing role
  with the same name as a new built-in is left alone and listed for review.
- Built-in roles carry a version and checksum. A later release upgrades a built-in role only if nobody changed it.
  A customized one is kept and listed for review.
- Whatever needs a person's decision goes on the review list (the **Review** page and
  `manage.py roles_migration_report`):
  - MSP staff without a global role;
  - customer users still on a simple Owner, Admin or Editor role;
  - customer users holding a role with internal permissions;
  - memberships where a template overrides an Owner or Admin simple role;
  - owner memberships of deactivated accounts;
  - organizations with no active owner.

  Listing an item changes nothing.

Commands:

    manage.py seed_roles                  create / adopt / upgrade the built-in roles (idempotent)
    manage.py roles_migration_report      list the review items (--refresh, --json, --all)
    manage.py roles_matrix                regenerate the tables below (--check in CI)

## Technician access, RMM tiers and OPTIONAL AI

Ticket AI (OPTIONAL AI, gated by `psa_ai_enabled`), RMM and remote-access capabilities are not role permissions.
They are decided per customer by technician access assignments (one customer each, with expiry) and the RMM tier of
the technician's global role. See [TECHNICIAN_ACCESS.md](TECHNICIAN_ACCESS.md).

<!-- BEGIN GENERATED: manage.py roles_matrix -->
## Default role matrix

Generated from `accounts/role_seeds.py`. A blank cell means the role does not hold the permission. Roles adopted from earlier releases (Owner, RMM L1/L2/L3) keep the permissions they already had; the columns show their built-in definition.

### Internal roles

| Permission | Organization Owner | Organization Administrator | Service Manager | Level 1 Technician | Level 2 Technician | Level 3 Technician | Sales Representative | Sales Manager | Billing / Finance | Internal Read-Only / Auditor |
|---|---|---|---|---|---|---|---|---|---|---|
| **Organization & users** | | | | | | | | | | |
| `org_view_members` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `org_invite_members` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `org_manage_members` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `org_manage_privileged` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `roles_manage` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `org_manage_settings` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `org_owner` | ✔ |  |  |  |  |  |  |  |  |  |
| **Tickets & queues** | | | | | | | | | | |
| `tickets_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `tickets_create` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |
| `tickets_edit` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `tickets_assign` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `tickets_view_all` | ✔ | ✔ | ✔ |  |  |  |  |  |  | ✔ |
| `tickets_close` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `tickets_delete` | ✔ |  |  |  |  |  |  |  |  |  |
| `tickets_view_internal` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `outsourcing_share_tickets` | ✔ |  | ✔ |  |  |  |  |  |  |  |
| `routing_manage_rules` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `routing_test` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `routing_override` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| **Service management** | | | | | | | | | | |
| `change_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `change_create` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `change_approve_cab` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `change_implement` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `problem_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `problem_create` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `problem_assign` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `problem_resolve` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `release_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `release_manage` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `release_freeze` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `catalog_propose_change` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| `catalog_approve_change` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| **Assets & inventory** | | | | | | | | | | |
| `assets_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `assets_create` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `assets_edit` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| `assets_delete` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `netconfig_view_configs` | ✔ |  |  |  |  |  |  |  |  |  |
| **Documentation** | | | | | | | | | | |
| `docs_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `docs_create` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| `docs_edit` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| `docs_delete` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `docs_publish` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| **Knowledge base** | | | | | | | | | | |
| `kb_view_articles` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `kb_edit_articles` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| `kb_move_articles` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `kb_manage_categories` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `kb_publish_articles` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| **Files & attachments** | | | | | | | | | | |
| `files_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |
| `files_upload` | ✔ | ✔ | ✔ |  | ✔ | ✔ | ✔ | ✔ |  |  |
| `files_delete` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| **Passwords & secrets** | | | | | | | | | | |
| `vault_view` | ✔ |  |  | ✔ | ✔ | ✔ |  |  |  |  |
| `vault_create` | ✔ |  |  |  |  |  |  |  |  |  |
| `vault_edit` | ✔ |  |  |  |  |  |  |  |  |  |
| `vault_delete` | ✔ |  |  |  |  |  |  |  |  |  |
| `vault_export` | ✔ |  |  |  |  |  |  |  |  |  |
| `vault_view_password` | ✔ |  |  |  |  |  |  |  |  |  |
| `vault_approve_reveal` | ✔ |  |  |  |  |  |  |  |  |  |
| `vault_manage_access_rules` | ✔ |  |  |  |  |  |  |  |  |  |
| **Monitoring & alerts** | | | | | | | | | | |
| `monitoring_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `monitoring_create` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `monitoring_edit` | ✔ | ✔ | ✔ |  |  | ✔ |  |  |  |  |
| `monitoring_delete` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `monitoring_trigger` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| **Security alerts** | | | | | | | | | | |
| `security_alerts_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `security_alerts_manage_connections` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `security_alerts_acknowledge` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  |  |  |  |
| `security_alerts_create_rules` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| **Integrations & RMM** | | | | | | | | | | |
| `integrations_view` | ✔ | ✔ | ✔ |  |  |  |  |  |  | ✔ |
| `integrations_view_synced_psa` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `integrations_configure` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `integrations_sync` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| **Sales, quotes & CRM** | | | | | | | | | | |
| `crm_view` | ✔ | ✔ |  |  |  |  | ✔ | ✔ |  | ✔ |
| `crm_create_lead` | ✔ |  |  |  |  |  | ✔ | ✔ |  |  |
| `crm_manage_pipeline` | ✔ |  |  |  |  |  | ✔ | ✔ |  |  |
| `crm_manage_campaigns` | ✔ |  |  |  |  |  |  | ✔ |  |  |
| `crm_view_forecast` | ✔ |  |  |  |  |  |  | ✔ |  |  |
| `crm_approve_commissions` | ✔ |  |  |  |  |  |  | ✔ |  |  |
| `quotes_view` | ✔ | ✔ |  |  |  |  | ✔ | ✔ | ✔ | ✔ |
| `quotes_edit` | ✔ |  |  |  |  |  | ✔ | ✔ |  |  |
| `quotes_send` | ✔ |  |  |  |  |  |  | ✔ |  |  |
| `quotes_approve_discount` | ✔ |  |  |  |  |  |  | ✔ |  |  |
| **Contracts & signing** | | | | | | | | | | |
| `contracts_view` | ✔ | ✔ |  |  |  |  | ✔ | ✔ | ✔ | ✔ |
| `contracts_view_pricing` | ✔ |  |  |  |  |  | ✔ | ✔ | ✔ |  |
| `contracts_edit_draft` | ✔ |  |  |  |  |  | ✔ | ✔ |  |  |
| `contracts_manage_templates` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_submit_approval` | ✔ |  |  |  |  |  | ✔ | ✔ |  |  |
| `contracts_approve` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_send` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_manage_links` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_countersign` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_void` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_download_signed` | ✔ |  |  |  |  |  |  | ✔ | ✔ |  |
| `contracts_view_audit` | ✔ |  |  |  |  |  |  |  |  |  |
| `contracts_settings` | ✔ |  |  |  |  |  |  |  |  |  |
| **Billing & finance** | | | | | | | | | | |
| `billing_view_invoices` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `billing_send_invoices` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `billing_record_payments` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `billing_view_aging` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `billing_approve_invoices` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `billing_issue_credit` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `billing_manage_charges` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| **Procurement** | | | | | | | | | | |
| `procurement_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  | ✔ | ✔ |
| `procurement_create_pr` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `procurement_approve_pr` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `procurement_create_po` | ✔ |  |  |  |  |  |  |  |  |  |
| `procurement_send_po` | ✔ |  |  |  |  |  |  |  |  |  |
| **Reports & dashboards** | | | | | | | | | | |
| `reports_view_dashboards` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `reports_view_financial` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `reports_view_sla` | ✔ | ✔ | ✔ |  |  |  |  |  |  | ✔ |
| `reports_view_capacity` | ✔ | ✔ | ✔ |  |  |  |  |  |  | ✔ |
| `reports_manage_dashboards` | ✔ | ✔ | ✔ |  |  |  |  | ✔ |  |  |
| `reports_manage_scheduled` | ✔ |  |  |  |  |  |  |  | ✔ |  |
| `reports_export` | ✔ | ✔ | ✔ |  | ✔ | ✔ |  | ✔ | ✔ |  |
| **Resourcing** | | | | | | | | | | |
| `resourcing_view_team` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `resourcing_manage_cost_rates` | ✔ |  |  |  |  |  |  |  |  |  |
| `resourcing_approve_leave` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `resourcing_manage_holidays` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| **API & automation** | | | | | | | | | | |
| `api_access` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| `api_keys_manage` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| **Audit logs** | | | | | | | | | | |
| `audit_view` | ✔ | ✔ |  |  |  |  |  |  |  | ✔ |
| `audit_export` | ✔ |  |  |  |  |  |  |  |  |  |
| **AI assistance (OPTIONAL AI)** | | | | | | | | | | |
| `psa_ai_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `psa_ai_request_triage` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `psa_ai_send_low_risk` | ✔ |  | ✔ |  |  |  |  |  |  |  |
| `psa_ai_send_high_risk` | ✔ |  |  |  |  |  |  |  |  |  |
| `psa_ai_approve_reply` | ✔ |  | ✔ |  |  |  |  |  |  |  |
| `psa_ai_apply_low_risk` | ✔ |  | ✔ |  |  |  |  |  |  |  |
| `psa_ai_apply_high_risk` | ✔ |  |  |  |  |  |  |  |  |  |
| `psa_ai_approve_action` | ✔ |  | ✔ |  |  |  |  |  |  |  |
| `psa_ai_run_script` | ✔ |  |  |  |  |  |  |  |  |  |
| `psa_ai_create_workflow` | ✔ |  |  |  |  |  |  |  |  |  |
| `psa_ai_billing` | ✔ |  |  |  |  |  |  |  |  |  |
| `psa_ai_admin` | ✔ | ✔ |  |  |  |  |  |  |  |  |
| **Operations** | | | | | | | | | | |
| `vehicles_view` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |  |  |  | ✔ |
| `vehicles_manage` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `scheduling_manage_wallboard` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `psa_manage_workflow_rules` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `timesheets_approve` | ✔ | ✔ | ✔ |  |  |  |  |  |  |  |
| `resourcing_view_payroll` | ✔ | ✔ |  |  |  |  |  |  | ✔ |  |
| **Customer portal** | | | | | | | | | | |
| `portal_tickets_view_org` | ✔ |  |  |  |  |  |  |  |  |  |
| `portal_tickets_create` | ✔ |  |  |  |  |  |  |  |  |  |
| `portal_tickets_reply` | ✔ |  |  |  |  |  |  |  |  |  |
| `portal_approve_requests` | ✔ |  |  |  |  |  |  |  |  |  |
| `portal_agreements_view_org` | ✔ |  |  |  |  |  |  |  |  |  |

### Customer roles and add-ons

| Permission | Customer Administrator | Customer Manager | Customer Standard User | Customer Read-Only | Billing Contact | Contract Reviewer | Authorized Contract Signer | Request Approver |
|---|---|---|---|---|---|---|---|---|
| **Organization & users** | | | | | | | | |
| `org_view_members` | ✔ | ✔ |  |  |  |  |  |  |
| `org_invite_members` | ✔ |  |  |  |  |  |  |  |
| `org_manage_members` | ✔ |  |  |  |  |  |  |  |
| **Tickets & queues** | | | | | | | | |
| `tickets_view` | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `tickets_create` | ✔ | ✔ | ✔ |  |  |  |  |  |
| `tickets_edit` | ✔ | ✔ | ✔ |  |  |  |  |  |
| `tickets_close` | ✔ | ✔ |  |  |  |  |  |  |
| **Service management** | | | | | | | | |
| `change_view` | ✔ | ✔ |  |  |  |  |  |  |
| `release_view` | ✔ | ✔ |  |  |  |  |  |  |
| **Assets & inventory** | | | | | | | | |
| `assets_view` | ✔ | ✔ |  |  |  |  |  |  |
| **Documentation** | | | | | | | | |
| `docs_view` | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| **Knowledge base** | | | | | | | | |
| `kb_view_articles` | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| **Files & attachments** | | | | | | | | |
| `files_view` | ✔ | ✔ | ✔ | ✔ |  |  |  |  |
| `files_upload` | ✔ |  |  |  |  |  |  |  |
| **Procurement** | | | | | | | | |
| `procurement_view` | ✔ |  |  |  |  |  |  |  |
| **Reports & dashboards** | | | | | | | | |
| `reports_view_dashboards` | ✔ | ✔ |  |  |  |  |  |  |
| **Customer portal** | | | | | | | | |
| `portal_tickets_view_org` | ✔ | ✔ |  |  |  |  |  |  |
| `portal_tickets_create` | ✔ | ✔ | ✔ |  |  |  |  |  |
| `portal_tickets_reply` | ✔ | ✔ | ✔ |  |  |  |  |  |
| `portal_approve_requests` | ✔ | ✔ |  |  |  |  |  | ✔ |
| `portal_agreements_view_org` | ✔ | ✔ |  |  |  | ✔ | ✔ |  |
| `portal_billing_contact` |  |  |  |  | ✔ |  |  |  |
| `portal_contract_review` |  |  |  |  |  | ✔ | ✔ |  |
| `portal_contract_sign` |  |  |  |  |  |  | ✔ |  |

## Built-in role mapping

| Requirement name | Template in the product | Key | Notes |
|---|---|---|---|
| Organization Owner | Owner | `org_owner` | adopted existing template |
| Organization Administrator | Organization Administrator | `org_admin` | new template |
| Service Manager | Service Manager | `service_manager` | new template |
| Level 1 Technician | RMM L1 — Help Desk | `tech_l1` | adopted existing template, RMM tier l1 |
| Level 2 Technician | RMM L2 — Technician | `tech_l2` | adopted existing template, RMM tier l2 |
| Level 3 Technician | RMM L3 — Senior Technician | `tech_l3` | adopted existing template, RMM tier l3 |
| Sales Representative | Sales Representative | `sales_rep` | new template |
| Sales Manager | Sales Manager | `sales_manager` | new template |
| Billing / Finance | Billing / Finance | `billing_finance` | new template |
| Internal Read-Only / Auditor | Internal Read-Only / Auditor | `auditor` | new template |
| Customer Administrator | Customer Administrator | `customer_admin` | new template |
| Customer Manager | Customer Manager | `customer_manager` | new template |
| Customer Standard User | Customer Standard User | `customer_user` | new template |
| Customer Read-Only | Customer Read-Only | `customer_readonly` | new template |
| Billing Contact | Billing Contact | `customer_billing_contact` | new template |
| Contract Reviewer | Contract Reviewer | `customer_contract_reviewer` | new template |
| Authorized Contract Signer | Authorized Contract Signer | `customer_contract_signer` | new template |
| Request Approver | Request Approver | `customer_request_approver` | new template |

## Permission catalog

Sensitivity: `critical` permissions make a role privileged (assigning it needs `org_manage_privileged`). "Customer" = a customer role may hold it. "Staff only" = never effective for a customer user. Status `pending` = defined, enforcement being wired up; `unimplemented` = the feature does not exist yet.

### Organization & users

Members, invitations, roles, ownership and organization settings.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `org_view_members` | View / list | standard | yes | enforced | View organization members |
| `org_invite_members` | Manage users | elevated | yes | enforced | Invite new members |
| `org_manage_members` | Manage users | elevated | yes | enforced | Manage ordinary members: edit, suspend, remove, assign non-privileged roles |
| `org_manage_privileged` | Manage roles | critical | no | enforced | Assign or remove privileged roles (roles holding user, role, security or platform administration) |
| `roles_manage` | Manage roles | critical | no | enforced | Create, clone, edit and archive custom roles |
| `org_manage_settings` | Manage settings | critical | no | enforced | Change organization settings |
| `org_owner` | Manage roles | critical | no | enforced | Organization owner: ownership transfer, owner-only operations, billing and security policy. Only granted through ownership transfer. |

### Tickets & queues

PSA tickets, internal notes, assignment, routing and sharing.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `tickets_view` | View / list | standard | yes | enforced | View tickets in the PSA / mobile surfaces |
| `tickets_create` | Create | standard | yes | enforced | File new tickets |
| `tickets_edit` | Edit | standard | yes | enforced | Edit ticket subject / description / status / priority |
| `tickets_assign` | Assign / reassign | elevated | no | enforced | Assign a ticket to another user (re-assignment) |
| `tickets_view_all` | View / list | elevated | no | enforced | View tickets across all organizations (not just those the user is a member of) |
| `tickets_close` | Edit | standard | yes | enforced | Move a ticket to a terminal status (resolved / closed) |
| `tickets_delete` | Delete | sensitive | no | enforced | Hard-delete a ticket |
| `tickets_view_internal` | View / list | elevated | staff only | pending | See internal ticket notes and internal-only attachments (MSP staff only) |
| `outsourcing_share_tickets` | Send / publish | sensitive | no | enforced | Share a ticket with an outsourcing partner via signed webhook |
| `routing_manage_rules` | Manage settings | elevated | staff only | enforced | Ticket routing: change settings, customer overrides, rules and on-call shifts |
| `routing_test` | View / list | standard | staff only | enforced | Ticket routing: use Test routing (read-only dry run) |
| `routing_override` | Approve | elevated | staff only | enforced | Ticket routing: accept or reject routing suggestions |

### Service management

Change, problem, release and service catalog governance.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `change_view` | View / list | standard | yes | enforced | View change requests |
| `change_create` | Create | standard | no | enforced | Submit a change request for CAB review |
| `change_approve_cab` | Approve | elevated | no | enforced | Sit on the CAB and vote on changes |
| `change_implement` | Execute scripts / actions | elevated | no | enforced | Move an approved change into Implementing |
| `problem_view` | View / list | standard | no | enforced | View problems |
| `problem_create` | Create | standard | no | enforced | Create problems |
| `problem_assign` | Assign / reassign | elevated | no | enforced | Assign problems to investigators / reassign owners |
| `problem_resolve` | Edit | elevated | no | enforced | Move a problem to resolved / closed |
| `release_view` | View / list | standard | yes | enforced | View release windows |
| `release_manage` | Edit | elevated | no | enforced | Create / edit release windows and bundle changes |
| `release_freeze` | Approve | elevated | no | enforced | Flip a release to frozen / completed / rolled back |
| `catalog_propose_change` | Create | standard | no | enforced | Propose edits to a service catalog item |
| `catalog_approve_change` | Approve | elevated | no | enforced | Approve / reject service catalog change proposals |

### Assets & inventory

Assets, hardware and network discovery.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `assets_view` | View / list | standard | yes | enforced | View assets |
| `assets_create` | Create | standard | no | enforced | Create assets |
| `assets_edit` | Edit | standard | no | enforced | Edit assets |
| `assets_delete` | Delete | elevated | no | enforced | Delete assets |
| `network_discovery_generate` | Execute scripts / actions | sensitive | no | enforced | Generate remote network discovery scripts and tokens |
| `netconfig_view_configs` | Reveal / copy secrets | sensitive | no | pending | Read stored device configurations (may contain secrets) |

### Documentation

Documents, diagrams and their publication.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `docs_view` | View / list | standard | yes | enforced | View documents |
| `docs_create` | Create | standard | yes | enforced | Create documents |
| `docs_edit` | Edit | standard | yes | enforced | Edit documents |
| `docs_delete` | Delete | elevated | no | enforced | Delete documents |
| `docs_publish` | Send / publish | elevated | no | enforced | Publish / unpublish documents |
| `docs_view_internal` | View / list | sensitive | yes | pending | Customer users: see internal documentation (internal blocks, MSP-written source and versions) |

### Knowledge base

KB articles and categories.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `kb_view_articles` | View / list | standard | yes | enforced | View KB articles |
| `kb_edit_articles` | Edit | standard | no | enforced | Create / edit / delete KB articles |
| `kb_move_articles` | Edit | standard | no | enforced | Move KB articles between categories |
| `kb_manage_categories` | Manage settings | elevated | no | enforced | Create / edit / delete KB categories |
| `kb_publish_articles` | Send / publish | elevated | no | enforced | Publish / unpublish KB articles |

### Files & attachments

Uploaded files, photos and attachments.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `files_view` | Download | standard | yes | enforced | View and download files |
| `files_upload` | Create | standard | yes | enforced | Upload files |
| `files_delete` | Delete | elevated | no | enforced | Delete files |

### Passwords & secrets

The password vault and the browser extension.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `vault_view` | View / list | elevated | yes | enforced | List vault entries (titles and metadata, not values) |
| `vault_create` | Create | sensitive | yes | enforced | Create passwords and secrets |
| `vault_edit` | Edit | sensitive | yes | enforced | Edit passwords and secrets |
| `vault_delete` | Delete | sensitive | no | enforced | Delete passwords and secrets |
| `vault_export` | Export / bulk export | sensitive | no | unimplemented | Export passwords (no bulk export exists yet) |
| `vault_view_password` | Reveal / copy secrets | sensitive | yes | enforced | Reveal / copy password values |
| `vault_approve_reveal` | Approve | sensitive | no | pending | Approve another technician's password reveal request |
| `vault_manage_access_rules` | Manage settings | critical | no | enforced | Manage vault GeoIP / IP / time access rules |
| `vault_extension_use` | Reveal / copy secrets | sensitive | no | enforced | Use the browser extension (autofill / TOTP / reveal) |
| `vault_extension_offline_cache` | Export / bulk export | sensitive | no | enforced | Let the browser extension bulk-sync the visible vault for offline use |

### Monitoring & alerts

Website / WAN monitors, expirations, racks, IPAM.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `monitoring_view` | View / list | standard | yes | enforced | View monitors |
| `monitoring_create` | Create | standard | no | enforced | Create monitors |
| `monitoring_edit` | Edit | standard | no | enforced | Edit monitors |
| `monitoring_delete` | Delete | elevated | no | enforced | Delete monitors |
| `monitoring_trigger` | Execute scripts / actions | standard | no | enforced | Manually trigger checks |

### Security alerts

EDR / AV / firewall alert ingestion and rules.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `security_alerts_view` | View / list | standard | staff only | enforced | View the security alert triage list |
| `security_alerts_manage_connections` | Manage settings | critical | staff only | enforced | Create / edit / delete EDR / AV / firewall connections |
| `security_alerts_acknowledge` | Edit | elevated | staff only | enforced | Acknowledge / dismiss / resolve alerts, convert to tickets |
| `security_alerts_create_rules` | Manage settings | elevated | staff only | enforced | Create / edit / delete auto-ticket rules and suppression windows |

### Integrations & RMM

PSA / RMM / M365 and other connections and syncs.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `integrations_view` | View / list | standard | no | enforced | View integrations |
| `integrations_view_synced_psa` | View / list | elevated | staff only | pending | View synced PSA companies, contacts and tickets (raw provider data) |
| `integrations_configure` | Manage settings | critical | no | enforced | Configure integrations |
| `integrations_sync` | Execute scripts / actions | elevated | no | enforced | Trigger sync operations |

### Sales, quotes & CRM

Leads, pipeline, campaigns, forecast and quotes.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `crm_view` | View / list | standard | staff only | enforced | View leads, opportunities, campaigns and the pipeline |
| `crm_create_lead` | Create | standard | staff only | enforced | Create / edit leads |
| `crm_manage_pipeline` | Edit | elevated | staff only | enforced | Move opportunities through stages, convert leads |
| `crm_manage_campaigns` | Edit | elevated | staff only | enforced | Create / edit marketing campaigns and view ROI |
| `crm_view_forecast` | View / list | sensitive | staff only | enforced | See the weighted pipeline forecast |
| `crm_approve_commissions` | Approve | sensitive | staff only | pending | Decide and pay out sales commissions |
| `quotes_view` | View / list | standard | staff only | pending | View quotes and the priced service catalog |
| `quotes_edit` | Edit | elevated | staff only | pending | Create and edit draft quotes |
| `quotes_send` | Send / publish | elevated | staff only | pending | Send quotes to customers for acceptance |
| `quotes_approve_discount` | Approve | sensitive | staff only | pending | Approve discounts and pricing exceptions on quotes |

### Contracts & signing

Contract generator: drafts, approval, signing and evidence.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `contracts_view` | View / list | elevated | staff only | pending | View contracts |
| `contracts_view_pricing` | View / list | sensitive | staff only | pending | View commercial terms and pricing in contracts |
| `contracts_edit_draft` | Edit | elevated | staff only | pending | Create and edit contract drafts |
| `contracts_manage_templates` | Manage settings | sensitive | staff only | pending | Manage contract templates and reusable clauses |
| `contracts_submit_approval` | Send / publish | elevated | staff only | pending | Submit a contract for internal approval |
| `contracts_approve` | Approve | sensitive | staff only | pending | Approve a specific contract version |
| `contracts_send` | Send / publish | sensitive | staff only | pending | Send / resend signing invitations |
| `contracts_manage_links` | Send / publish | sensitive | staff only | pending | Generate / revoke signing links |
| `contracts_countersign` | Sign / countersign | sensitive | staff only | pending | Countersign contracts for the provider |
| `contracts_void` | Delete | sensitive | staff only | pending | Void or supersede a contract |
| `contracts_download_signed` | Download | sensitive | staff only | pending | Download signed agreements |
| `contracts_view_audit` | View audit history | sensitive | staff only | pending | View detailed signing audit evidence |
| `contracts_settings` | Manage settings | critical | staff only | pending | Configure signing and contract notification settings |

### Billing & finance

Invoices, payments, aging.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `billing_view_invoices` | View / list | sensitive | no | enforced | View invoices |
| `billing_send_invoices` | Send / publish | sensitive | no | enforced | Send invoices |
| `billing_record_payments` | Edit | sensitive | no | enforced | Record payments |
| `billing_view_aging` | View / list | sensitive | staff only | enforced | See the cross-client aging report |
| `billing_approve_invoices` | Approve | sensitive | staff only | pending | Approve invoices through the approval gate |
| `billing_issue_credit` | Edit | sensitive | staff only | pending | Issue credit memos |
| `billing_manage_charges` | Edit | sensitive | staff only | pending | Add charges, invoice tickets / projects and push invoices to accounting |

### Procurement

Purchase requisitions and purchase orders.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `procurement_view` | View / list | standard | yes | enforced | View purchase requisitions and orders |
| `procurement_create_pr` | Create | standard | no | enforced | Create / edit purchase requisitions |
| `procurement_approve_pr` | Approve | elevated | no | enforced | Approve / reject purchase requisitions |
| `procurement_create_po` | Create | elevated | no | enforced | Create / edit purchase orders |
| `procurement_send_po` | Send / publish | elevated | no | enforced | Email purchase orders to vendors |

### Reports & dashboards

Dashboards, financial / SLA / capacity reports, schedules.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `reports_view_dashboards` | View / list | standard | yes | enforced | View dashboards |
| `reports_view_financial` | View / list | sensitive | no | enforced | Profitability, effective rate, revenue leakage, margin analytics |
| `reports_view_sla` | View / list | elevated | staff only | enforced | SLA trend report |
| `reports_view_capacity` | View / list | elevated | staff only | enforced | Capacity / utilization report |
| `reports_manage_dashboards` | Edit | elevated | no | enforced | Create / edit / delete dashboards and widgets |
| `reports_manage_scheduled` | Export / bulk export | sensitive | no | enforced | Configure scheduled reports |
| `reports_export` | Export / bulk export | sensitive | staff only | pending | Export reports (CSV / PDF), saved-query results and generated report files |

### Resourcing

Team roster, cost rates, leave and holidays.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `resourcing_view_team` | View / list | elevated | staff only | enforced | See the staff roster and cost rates |
| `resourcing_manage_cost_rates` | Edit | sensitive | staff only | enforced | Edit per-tech loaded cost rates |
| `resourcing_approve_leave` | Approve | elevated | staff only | enforced | Approve / deny leave requests |
| `resourcing_manage_holidays` | Manage settings | elevated | no | enforced | Manage holidays (an organization's own business-hours calendar) |

### API & automation

API access and API keys.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `api_access` | View / list | elevated | no | enforced | Access API endpoints |
| `api_keys_manage` | Manage settings | critical | no | enforced | Create / manage API keys |

### Audit logs

Audit trail viewing and export.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `audit_view` | View audit history | elevated | no | enforced | View audit logs |
| `audit_export` | Export / bulk export | sensitive | no | enforced | Export audit logs |

### AI assistance (OPTIONAL AI)

AI suggestions, replies and actions; gated by psa_ai_enabled.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `psa_ai_view` | View / list | standard | staff only | enforced | View AI suggestions and the AI inbox |
| `psa_ai_request_triage` | View / list | standard | staff only | enforced | Request read-only AI triage guidance |
| `psa_ai_send_low_risk` | Send / publish | elevated | staff only | enforced | Send low-risk AI replies as public comments |
| `psa_ai_send_high_risk` | Send / publish | sensitive | staff only | enforced | Send medium- or high-risk AI replies |
| `psa_ai_approve_reply` | Approve | elevated | staff only | enforced | Approve another user's pending AI reply |
| `psa_ai_apply_low_risk` | Edit | elevated | staff only | enforced | Apply low-risk AI actions |
| `psa_ai_apply_high_risk` | Edit | sensitive | staff only | enforced | Apply medium- or high-risk AI actions |
| `psa_ai_approve_action` | Approve | elevated | staff only | enforced | Approve another user's pending AI action |
| `psa_ai_run_script` | Execute scripts / actions | sensitive | staff only | enforced | Run an AI-suggested RMM script against an asset |
| `psa_ai_create_workflow` | Create | elevated | staff only | enforced | Create or assign a workflow from an AI suggestion |
| `psa_ai_billing` | Edit | sensitive | staff only | enforced | Modify financial fields via AI |
| `psa_ai_admin` | Manage settings | critical | staff only | enforced | Configure AI (model, threshold, allow/blocklist, voice) |

### Operations

Fleet vehicles, scheduling wallboard, workflow rules, timesheets, payroll.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `vehicles_view` | View / list | standard | staff only | pending | View fleet vehicles, receipts and vehicle inventory |
| `vehicles_manage` | Edit | elevated | staff only | pending | Create, edit and delete vehicles, receipts and vehicle inventory |
| `scheduling_manage_wallboard` | Manage settings | elevated | staff only | pending | Configure the public scheduling wallboard |
| `psa_manage_workflow_rules` | Manage settings | elevated | staff only | pending | Manage ticket workflow rules and workflow templates |
| `timesheets_approve` | Approve | elevated | staff only | pending | Review and approve timesheets |
| `resourcing_view_payroll` | Export / bulk export | sensitive | staff only | pending | Timeclock dashboard and payroll export |

### Customer portal

What a customer user may do in the portal beyond the basics.

| Key | Action | Sensitivity | Customer | Status | Description |
|---|---|---|---|---|---|
| `portal_tickets_view_org` | View / list | standard | yes | enforced | See every shared ticket of the customer, not only the user's own |
| `portal_tickets_create` | Create | standard | yes | enforced | File tickets and service requests in the portal |
| `portal_tickets_reply` | Edit | standard | yes | enforced | Reply, send secure replies, escalate and vote on tickets the user can see |
| `portal_approve_requests` | Approve | elevated | yes | enforced | Request approver: decide client approvals for the customer |
| `portal_agreements_view_org` | View / list | sensitive | yes | enforced | See coworkers' agreement signatures and their evidence (not only the user's own) |
| `portal_billing_contact` | View / list | sensitive | yes | pending | Billing contact: see invoices and billing notices for the customer |
| `portal_contract_review` | View / list | elevated | yes | pending | Contract reviewer: read contracts sent to the customer |
| `portal_contract_sign` | Sign / countersign | sensitive | yes | pending | Authorized contract signer: sign contracts for the customer |

## Module coverage

| Application | Governed by |
|---|---|
| `accounts` | org_* / roles_manage / org_owner; accounts.delegation for every assignment path |
| `core` | organization switcher + client scope (accounts.scope); settings are superuser-only |
| `vault` | vault_* per customer (accounts.permission_utils.user_has_org_perm, vault.permissions) |
| `assets` | assets_* (section gate /assets/, /hardware/) + per-customer lookups |
| `hardware` | assets_* (hardware.access) |
| `docs` | docs_* and kb_* (section gate /docs/) |
| `readiness` | MSP staff only + per-customer lookups |
| `files` | files_* per customer |
| `audit` | audit_view / audit_export |
| `api` | api_access / api_keys_manage; API key level caps the owner (api.permissions) |
| `api_mobile` | tickets_* / assets_* per customer, mobile session tokens |
| `integrations` | integrations_* (section gate /integrations/), RMM via rmm_permissions + tech_access |
| `monitoring` | monitoring_* (section gate /monitoring/) |
| `processes` | membership write role (require_write) per customer |
| `locations` | membership write role per customer |
| `imports` | superuser / org_manage_settings |
| `reports` | reports_* (MSP staff only section) |
| `vehicles` | membership write role per customer |
| `inventory` | membership write / admin role per customer |
| `scheduling` | membership write / admin role per customer |
| `psa` | tickets_*, billing_*, procurement_*, change_* / problem_* / release_* / catalog_*, quotes_* |
| `psa.routing` | routing_* |
| `psa.support_workflows` | MSP staff + tickets_* |
| `psa_ai` | psa_ai_* (OPTIONAL AI, gated by psa_ai_enabled) + technician access ai_* capabilities |
| `tech_access` | technician access assignments (capability x customer x expiry); protected changes |
| `rmm_permissions` | RMM tier from the global role x technician access assignment |
| `portal` | customer membership + portal_* permissions; never internal notes or other customers |
| `resourcing` | resourcing_* (MSP staff) |
| `crm` | crm_* (MSP staff only section) |
| `security_alerts` | security_alerts_* (MSP staff only section) |
| `compliance` | membership role per customer |
| `field_ops` | MSP staff + tickets_* |
| `statuspage` | membership admin role |
| `netconfig` | MSP staff + per-customer lookups |
| `network_discovery` | network_discovery_generate + assets_* |
| `office` | docs_* / files_* per customer |
| `contracts` | contracts_* (staff) and portal_contract_* (customer) via accounts.contract_access |

<!-- END GENERATED: manage.py roles_matrix -->
