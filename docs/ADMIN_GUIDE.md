# Administrator guide

Where to switch on the optional features added in v3.17.664. After upgrading, every feature below
is in its default state until an administrator changes it. Feature guides:
[TICKET_ROUTING.md](TICKET_ROUTING.md), [AI_TROUBLESHOOT.md](AI_TROUBLESHOOT.md),
[SUPPORT_WORKFLOWS.md](SUPPORT_WORKFLOWS.md),
[TECHNICIAN_ACCESS.md](TECHNICIAN_ACCESS.md),
[UPGRADE_AND_RECOVERY.md](UPGRADE_AND_RECOVERY.md).

## Where to switch things on

"su" means superuser. Permission names are role-template flags.

| Feature | Setting location | Default | Who can change it |
|---|---|---|---|
| Integration owner (platform or one customer) | Settings → Integrations → Integrations, in global view → Add (Owner); existing connections: "Make platform-owned" or `manage.py integrations_ownership` | New connections in global view are platform-owned; existing ones keep their customer | su, Django staff, or MSP staff whose global role grants `integrations_configure` |
| Rem0te pairing (Ed25519) | Settings → Integrations → RMM · Rem0te (`/integrations/rmm/rem0te/setup/`) | Not paired: no identity keys until created | su |
| RMM service lists (Tactical RMM only) | Settings → Integrations → Integrations → the RMM connection → Edit → "Collect services" | Off | MSP staff who are administrators of the selected customer |
| Refresh from RMM (one device) | Assets & Network → Device Workspace → Refresh from RMM | Available; once per device every 5 minutes | MSP technicians allowed `device.view` for that device |
| RMM permission levels (L1 / L2 / L3) | Settings → Security → RMM Permissions (`/settings/security/rmm-permissions/`); levels are set on the user's global role | No level assigned | `policy.manage`; giving or changing a level also needs a second administrator to approve |
| Ticket routing | Service Desk → Dispatch Board → Configure → Ticket Routing (`/psa/routing/`; MSP default), per customer under Customers | Off; customers inherit the MSP default | PSA on + `routing_manage_rules` |
| Alert-to-ticket policy | Security & Monitoring → Alert Policies (`/psa/routing/alerts/`) | Legacy: one ticket per Rem0te alert, no policy; synced RMM alerts not included | PSA on + `routing_manage_rules` |
| Support workflows | Service Desk → Workflows → Support Workflows (`/psa/workflows/`) | Twelve built-in workflows, active | PSA on + `routing_manage_rules` |
| AI features (master switch) **OPTIONAL AI** | Settings → General → PSA (`/psa/settings/`) → `psa_ai_enabled` | Off | su |
| AI Troubleshoot per customer **OPTIONAL AI** | Settings → AI Configuration → Ticket AI models (`/psa/ai/profiles/`) → the customer's policy | Off; 50 runs a day per customer, 20 per technician; network identifiers and contact names not shared | su |
| Installation-wide AI cap and command allowlist **OPTIONAL AI** | Settings → AI Configuration → Ticket AI models (`/psa/ai/profiles/`) → Installation-wide limits | No cap; no allowlist (built-in denylist always applies) | su |
| Geo-aware dispatch | Service Desk → Shifts & Locations → Configure → Dispatch Locations | Off | su who is MSP staff |
| Sharing my position with dispatch | Service Desk → Shifts & Locations → Location Sharing | Not shared | Each technician, for themselves |
| Shift templates | Service Desk → Shifts & Locations → Configure → Shift Templates | None | Staff with `resourcing_approve_leave` or `routing_manage_rules`, or su |
| LDAP group mappings | Settings → Users & Access → LDAP Group Mappings (`/accounts/ldap/group-mappings/`) | None | su |
| LDAP background sync | Settings → Automation → Task Scheduler → LDAP Group Mapping Sync | On, every 15 minutes; does nothing without LDAP sign-in and mappings | su |
| Weekly security digest | Security & Monitoring → Security Alerts → Configure → Weekly Digest (`/security/digest/`) | No contacts subscribed | `security_alerts_view` to view; `security_alerts_manage_connections` to change |
| "All clear" digest e-mail | Same page, per customer | Off | `security_alerts_manage_connections` for that customer |
| Agreement reminders | Each agreement's settings | On, every 7 days | Staff who manage agreements |
| Portal for a customer | Settings → General → PSA → per-customer settings (`/psa/settings/client/`) | As before | su |
| Requesters' default sites | `/psa/requester-sites/` | None | Staff with `tickets_edit` for that customer |
| Release channel | Settings → System → System Updates | New installs: Stable. Existing installs: Preview (keep following `main`) | su |
| Optional modules overview | Settings → Modules → Optional Modules (`/core/settings/modules/`) | Shows each module's current state | su |
| File upload and delete | Settings → Users & Access → Roles → `files_upload`, `files_delete` | Custom roles with `files_view` get both on upgrade; built-in Editor has no delete, Read-Only neither | Administrators who manage roles |
| Invoice editing and payments | Settings → Users & Access → Roles → `billing_send_invoices`, `billing_record_payments` | Owner and Admin roles | Administrators who manage roles |

## Safety rules that no setting changes

- Routing a ticket never starts a remote session or authorizes an endpoint action.
- Routing, the alert policy and support workflows work with AI switched off.
- AI suggestions, including commands, are shown as text and never run.
- Customer users never see RMM data.
