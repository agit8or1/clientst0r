# ClientSt0r Features

What ClientSt0r does as of **v3.17.761**, by area, with what each feature needs and where it stops.
See the [README](README.md) for install steps, [docs/screenshots.md](docs/screenshots.md) for the
visual tour, and the [roadmap](docs/ROADMAP.md) for planned work.

## How to read this page

| Status | Meaning |
|---|---|
| **Available** | Implemented and usable as described. |
| **Limited** | Works with a stated limitation, or is in the code but not yet verified against the real external service. |
| **Planned** | Not built yet (or only partly). Tracked in the [roadmap](docs/ROADMAP.md). |
| **Separate component** | Not part of the web application in this repository. |

**Configuration** names where to switch or set the feature up. "Settings → X → Y" means
**Administration** (or the gear in the top bar) → settings center category X → page Y. Module
switches live in **Settings → Modules → Feature Toggles**; defaults: `psa_enabled`,
`psa_ai_enabled`, `crm_enabled` and `pulse_enabled` are **off**; monitoring, global KB, workflows,
secure notes, reports, webhooks, vehicles, inventory and scheduling are **on**.

**Access model.** Every user is **MSP staff** (superuser, staff flag, or User Type *Staff*) or a
**customer user**. Staff work across customers within their global role. Customer users see only
their own organizations, only tickets shared with them, and never internal notes or internal
attachments, on the web, in the portal and through the APIs and mobile app. See
[docs/ROLES_AND_ACCESS.md](docs/ROLES_AND_ACCESS.md).

Categories:
[1 Navigation](#1-navigation-and-workspace) ·
[2 Service desk](#2-service-desk-psa) ·
[3 Clients](#3-clients-and-contacts) ·
[4 Documentation](#4-documentation-and-knowledge-base) ·
[5 Vault](#5-password-vault) ·
[6 Assets](#6-assets-hardware-and-racks) ·
[7 Network & monitoring](#7-network-and-monitoring) ·
[8 Security alerts](#8-security-alerts-siem-and-events) ·
[9 RMM & Rem0te](#9-rmm-and-rem0te) ·
[10 Projects & dispatch](#10-projects-scheduling-and-dispatch) ·
[11 Billing](#11-billing-contracts-and-invoicing) ·
[12 Quotes, CRM & procurement](#12-quotes-crm-and-procurement) ·
[13 Reporting](#13-reporting-dashboards-and-wallboards) ·
[14 Portal](#14-client-portal) ·
[15 AI](#15-ai-assistance-optional-ai) ·
[16 Identity & access](#16-identity-roles-and-access) ·
[17 API & administration](#17-api-integrations-and-administration)

---

## 1. Navigation and workspace

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Ten-section sidebar (Dashboard, My Work, Service Desk, Clients, Assets & Network, Business, Knowledge & Vault, Security & Monitoring, Reports; Administration at the foot) with icon rail and flyouts | Available | None | Sections hide when their module is off or the user lacks permission | [navigation-map.md](docs/navigation-map.md) |
| Go to palette (Ctrl+K / Cmd+K): pages, settings, quick commands, clients, tickets, devices, projects, documents, reports | Available | None | Passwords are never searched; results follow each list's permissions | — |
| Jump to filter, Favorites, Recent, `g <key>` section shortcuts | Available | None | | — |
| Role dashboards with KPI row (administrator, manager, technician levels, sales, customer) | Available | Settings → Users & Access → Role Dashboards | | — |
| Client workspace: overview, tickets, assets, RMM devices, contacts, documents, passwords (names only), contracts, billing, projects, activity, members | Available | PSA tabs need `psa_enabled` | | — |
| Settings center: ten searchable categories showing only permitted pages | Available | None | | — |
| Global search | Limited | None | Substring match; no ranking or saved searches | — |
| Themes (light, Professional Dark default), phone layout, installable web app (PWA) | Available | None | PWA install needs HTTPS | [INSTALL_APP.md](docs/INSTALL_APP.md) |

## 2. Service desk (PSA)

The native service desk is off until `psa_enabled` is turned on. It is separate from the
third-party PSA sync in [category 17](#17-api-integrations-and-administration).

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Tickets, queues, priorities, types, public replies and internal notes, @mentions, watchers, attachments, merge, canned replies | Available | `psa_enabled` | | — |
| Ticket workspace: conversation layout, Cc, explicit Public reply / Internal note composer, drafts, collision warnings, keyboard shortcuts, closeout checklist | Available | `psa_enabled` | | — |
| Secure messages (one-time reveal link for a secret in a reply) | Available | `psa_enabled` | | — |
| My Work: own tickets in SLA order, running timers, customer replies, waiting queues, approvals, appointments | Available | `psa_enabled` | | — |
| SLAs per priority with per-contract overrides and pause statuses | Limited | Contract form | Calendar time; no business-hours calendar per customer | — |
| Time entries, timers, expenses, timesheets and approval | Available | `psa_enabled` | | — |
| Email-to-ticket (IMAP, Microsoft 365 Graph), reply threading | Available | Service Desk email configs; scheduler (every 5 min) | | — |
| Service catalog with guided request forms, conditional questions, approvers per customer | Available | Service Desk → Service Management | | — |
| Problems, changes with CAB, approvals inbox | Available | `psa_enabled` | Approvals inbox covers quote chains; other flows have their own review | — |
| Workflow rules (created, updated, status, comment, SLA threshold) | Limited | Service Desk → Workflows | No loop guard between chained rules; charges and chaining only in raw JSON | — |
| Process templates (runbooks with stages and sign-off, attached to a ticket) | Limited | `workflows_enabled` | Deleting a stage while editing deletes its sign-offs on existing runs | — |
| Customer follow-up and confirm-or-close: follow-up email, optional second reminder, then automatic close with a recorded reason; per-customer override, pause per ticket | Available | PSA settings → Customer follow-up and confirm-or-close | **Off by default**; never contacts staff, people with email notifications off, or customers opted out of the PSA | [SUPPORT_WORKFLOWS.md](docs/SUPPORT_WORKFLOWS.md#customer-follow-up-and-confirm-or-close) |
| One-click support workflows (twelve built-ins) | Available | `psa_enabled` | Remediation steps only where the paired RMM advertises them | [SUPPORT_WORKFLOWS.md](docs/SUPPORT_WORKFLOWS.md) |
| Ticket routing (Off / Suggest / Automatic rules, test, history); not AI | Limited | Off by default; Service Desk → routing | One MSP-wide business-hours definition | [TICKET_ROUTING.md](docs/TICKET_ROUTING.md) |
| Recurring tickets, CSAT, announcements, voting, escalation | Available | Scheduler; portal switches | | — |
| Partner ticket sharing between installs (signed webhooks) | Available | Ticket partner configuration | Partner must keep sending v2 signatures after the first valid one | — |

## 3. Clients and contacts

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Organizations (customers), unlimited, parent/child, multi-location | Available | None | | — |
| Customer Operations page: SLA risks, uptime incidents, renewals, overdue invoices, aging assets | Available | Sections follow the viewer's role | Rows per section capped (stated on the page) | — |
| Customer onboarding wizard and lifecycle changes (plan change, add users/devices, renewal, price increase, offboarding) | Available | Clients → Onboard Customer; role permission `manage_customer_onboarding` | Outputs are drafts that go through approval; accounting step links an existing provider customer but does not create one | — |
| Contacts | Available | Follows View assets permission | | — |
| Locations, geocoding (Google, OpenStreetMap fallback), navigation links by email/SMS | Available | Geocoding key optional | | — |
| Per-organization branding | Limited | Organization edit page | Portal logo and accent color only; site name and logo are install-wide | — |
| Importers: IT Glue, Hudu, CSV/xlsx, MagicPlan | Limited | Imports; source API key | IT Glue and Hudu: contacts, locations, networks, attachments and relationships are not imported | [importing-from-it-glue.md](docs/importing-from-it-glue.md), [importing-from-hudu.md](docs/importing-from-hudu.md) |

## 4. Documentation and knowledge base

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Documents: WYSIWYG, Markdown or uploaded file; categories; templates | Available | None | No file attachments, favorites or share links on documents | [msp-documentation.md](docs/msp-documentation.md) |
| Versions with view, compare and restore; owners and review dates; drafts; Submit for review → Approve; archive; template drift | Available | Publish permissions per role | | — |
| Global knowledge base shared with all, selected customers or customer groups; bulk audience changes; Make global | Available | `global_kb_enabled` | | — |
| KB analytics (most viewed, never viewed, past review, zero-result searches) | Available | MSP staff | | — |
| Documentation readiness: standards, per-customer score, repair queue, exceptions | Available | Knowledge & Vault → Documentation Readiness | | — |
| Diagrams (draw.io) | Available | None | | — |
| Agreements and policy acknowledgments bound to an exact document version, with evidence download | Available | Document → Agreement | Uploaded-file documents can't be agreements | — |
| Export: Markdown, HTML, DOCX, PDF | Available | None | | — |
| Office document editing: ONLYOFFICE, Collabora, Microsoft 365 (SharePoint/OneDrive) | Limited | Settings → Integrations → Office Documents | Not yet verified against real editor services; customer-portal editing and Google Docs planned | [OFFICE_DOCUMENTS.md](docs/OFFICE_DOCUMENTS.md) |

## 5. Password vault

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Encrypted entries (AES-256-GCM, per-purpose HKDF keys), 15 types, folders, TOTP codes | Available | `APP_MASTER_KEY` | Losing the master key makes vault data unrecoverable | [CLIENT_DATA_PROTECTION.md](docs/CLIENT_DATA_PROTECTION.md) |
| Reveal as its own permission; every reveal audited and rate-limited | Available | Roles | | — |
| Access rules (country, address range, time), reveal approval, break-glass, expiry warnings | Available | Vault → access rules | | — |
| Vault visibility: technicians see a customer's entries only where a membership or global role grants it | Available | Settings → Security → Vault Visibility | | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |
| Breach checks (Have I Been Pwned, k-anonymity) | Limited | Scheduler | Blocking breached passwords only via `HIBP_BLOCK_BREACHED` environment variable | — |
| Personal vault | Limited | None | Encrypted with the server master key, not a per-user key | — |
| Secure notes (ephemeral share links) | Available | `secure_notes_enabled` | | — |
| Bitwarden / Vaultwarden JSON import | Limited | Settings → Maintenance → Vault Import | Superusers only | — |
| Browser extension | Separate component | REST API key (Editor level or higher) | In `clientst0r-extension/`; unsigned, loads in developer mode only | [browser-extension-api.md](docs/browser-extension-api.md) |

## 6. Assets, hardware and racks

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Assets: about 60 built-in types, custom types and custom fields (on the form and the API), relationships, photos, RMA, lifecycle dates | Limited | Settings → General → Custom Fields & Types | No bulk edit; no per-asset change history; status is a custom field | — |
| Hardware catalog (community device-type library) with generated front/rear panel artwork and a layout editor | Available | Catalog import | Catalog size depends on the imported revision | [HARDWARE_INVENTORY.md](docs/HARDWARE_INVENTORY.md) |
| Ports, VLANs, PoE, cables, patch-panel mapping, cable tracing, labels with QR codes, rack/connectivity/VLAN diagrams | Available | None | Documentation only: nothing is pushed to devices; link state shows "Not observed"; hardware REST API is read-only | [HARDWARE_INVENTORY.md](docs/HARDWARE_INVENTORY.md) |
| Rack elevations (drag placement), network closets | Limited | None | Rack power figures are not summed from devices | — |
| Device Workspace (stored RMM facts with source and age) | Available | A synced RMM connection | Refresh once per device every 5 minutes | — |
| Inventory (stock) and service vehicles | Available | `inventory_enabled`, `vehicles_enabled` | Vehicle module switch hides the menu only | [INSTALL_APP.md](docs/INSTALL_APP.md) |
| Warranty lookups (Dell, HPE, Lenovo) | Limited | `warranty_checks_enabled` | Lookup classes are stubs; enter warranty dates by hand | — |

## 7. Network and monitoring

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| IPAM: subnets, VLANs, IP assignments | Available | None | | — |
| Website and SSL monitors; email and webhooks on down (after 2 failed checks) and recovery | Limited | `monitoring_enabled` | Checks at most every 5 minutes | — |
| WAN monitors (server-side ping) | Available | `monitoring_enabled` | Needs `ping` on the server and a reachable target | — |
| Domain and certificate expiry tracking | Limited | `monitoring_enabled` | No WHOIS; domain expiry entered by hand | — |
| Status pages (public token pages, per customer, incident posts) | Available | Monitoring → Status pages | | — |
| Network config backups over SSH (Cisco IOS/ASA, Arista EOS, Juniper Junos, MikroTik, FortiOS, HP ProCurve, generic), diff, approve, drift | Available | Per-device SSH credentials | | — |
| Network discovery import (script run on a Windows host, results imported as assets) | Available | Collector token | No SNMP or LLDP; the topology and port-map pages have no data source until pushed link data exists | — |
| Network controller sync: UniFi, Omada, Grandstream | Limited | Settings → Integrations | Scheduled UniFi sync records every device as an access point; use manual import for correct types | — |
| Backup monitoring: Proxmox Backup Server (polled), restic, Borg, Kopia (signed push reports); alerts, tickets, restore tests | Available | Assets & Network → Backup Monitoring; `view_backup_status` | Commercial backup products planned | [BACKUP_MONITORING.md](docs/BACKUP_MONITORING.md) |
| Service dependency and impact mapping | Planned | | Phase 88 | [ROADMAP.md](docs/ROADMAP.md) |

## 8. Security alerts, SIEM and events

Security Alerts and Incidents need `psa_enabled` and are MSP-staff only.

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Security vendor connections | Limited | Security & Monitoring → Security Alerts | Alerts arrive only by the generic JSON webhook (token URL, optional or required HMAC signature). The vendor names in the list are labels; no vendor API polling works (the Defender adapter is a reference stub) | — |
| SIEM webhook endpoints (CEF, generic JSON, Syslog RFC 5424 over HTTPS POST) | Available | Security Alerts → SIEM endpoints; signatures required by default for new endpoints | No network syslog listener | — |
| Auto-ticket rules, incidents, playbooks, correlation, threat overview, digest, MTTA | Available | `psa_enabled` | Correlation is fixed grouping; configurable rules planned (Phase 85) | — |
| Security Overview (read-only summary) | Available | `psa_enabled` | | — |
| Events: one list of security, RMM, Rem0te, backup and website-monitor alerts; manual ticket/incident links; ingestion health | Available | Security & Monitoring → Events; ingestion switch on by default; permissions `events_view`, `events_link`, `events_manage_ingestion` (seeded Security Analyst and Security Administrator roles); retention per source and per customer on the ingestion health page | Phase 82 in progress: no correlation or automation yet; address/account/IOC fields empty until connectors supply them; WAN monitors not a source | [ROADMAP.md](docs/ROADMAP.md) |
| Firewall: IP and GeoIP rules, blocked-request log; fail2ban management | Available | Settings → Security → Firewall & GeoIP, Fail2ban | Application-level; fail2ban on native installs only | — |
| Vulnerability scans (Snyk, pip-audit, OS packages) | Available | Settings → Security → Vulnerability Scans | Snyk needs a token | [PACKAGE_SCANNER.md](docs/PACKAGE_SCANNER.md) |
| Vendor connectors, Operations Center, SOAR Lite, on-call routing, posture scorecards | Planned | | Phases 84–89 | [ROADMAP.md](docs/ROADMAP.md) |

## 9. RMM and Rem0te

Rem0te is a **separate component**: an RMM application maintained outside this repository.
ClientSt0r never runs anything on a device; any endpoint action is approved in the RMM, never in
ClientSt0r or by AI.

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| RMM sync (devices, alerts, software): Atera, ConnectWise Automate, Datto RMM, NinjaOne, Tactical RMM, Rem0te | Available | Settings → Integrations; scheduler task `rmm_sync` (off by default) | Polling; device map coordinates only from Tactical RMM | [INTEGRATION_SETUP_GUIDE.md](docs/INTEGRATION_SETUP_GUIDE.md) |
| Rem0te pairing over contract ticket-rmm-v1 revision 2 (Ed25519 signatures, replay protection, tenant pinned by immutable IDs) | Available | Settings → Integrations → RMM · Rem0te; turning pairing on is a protected change a second administrator approves | Tested with both real applications in CI | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |
| Pairing other RMMs that implement the contract (HMAC signatures) | Limited | RMM connection page | Rem0te is the only known implementation | — |
| Rem0te alert → ClientSt0r ticket with link back; alert-to-ticket policy and maintenance windows | Available | Security & Monitoring → Alert Policies | One ticket per Rem0te alert until the policy is switched on | — |
| Redacted handoff from a ticket, view/control session launch | Limited | Technician access assignment at the customer | Session grants come from the RMM; the Rem0te handoff and session-launch routes (contract revision 3) are in development on the Rem0te side | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |
| Read-only diagnostics, remediation proposals, approval in Rem0te and results back to the ticket | Limited | | In development: contract routes agreed (revision 3) but not built on the Rem0te side; not yet end-to-end | [ROADMAP.md](docs/ROADMAP.md) |
| Ticket RMM panel, verify-then-close, service lists (Tactical RMM only) | Available | Paired or synced RMM | | — |
| RMM Permissions: action catalog, tier holds, second-person approvals, per-customer overrides | Available | Settings → Security → RMM Permissions | | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |

## 10. Projects, scheduling and dispatch

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Projects: tasks, milestones, dependencies, timeline, templates, invoicing | Available | `psa_enabled` | | — |
| Dispatch board (7-day grid, overdue and unassigned rows) | Limited | `psa_enabled` | Dragging changes the assignee, not the date | — |
| Scheduling: recurring maintenance tasks with sign-off, calendar | Available | `scheduling_enabled` | | — |
| Scheduler wallboard (public token page) | Available | Scheduling → Wallboard settings | | — |
| Resourcing: shifts, leave, holidays, skills, certifications, on-call, capacity, cost rates | Available | MSP staff | | — |
| Timeclock and location sharing (field ops) | Available | Settings → Modules → Field Ops; consent | The native mobile app is a separate component | — |

## 11. Billing, contracts and invoicing

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Billing contracts: block hours, retainer, managed, per-incident; rollover, renewals, SLA overrides | Available | `psa_enabled` | Quote → contract conversion planned (Phase 70) | — |
| Invoices: from tickets, client charges or projects; recurring invoices; aging; late fees (off by default); approval gate | Limited | Scheduler | Recurring client charges store a recurrence but no job creates the next one | — |
| Ticket Time & Charges: time classification, work type, role, agreement choice, per-entry breakdown; Add Item (catalog, stock, one-off, credits); billing summary with Send to billing | Available | `psa_enabled`; Manage charges for agreement choice and credits | Cost and margin only with the internal-cost permission; sending to billing never creates an invoice | [BILLING.md](docs/BILLING.md) |
| Prepaid-hour ledger: immutable postings, earliest-expiry-first, only approved time uses hours, retainer cycles, audited adjustments | Available | Contract → Prepaid-hour ledger | After-hours and weekend rates are not set automatically | [BILLING.md](docs/BILLING.md#prepaid-hour-ledger) |
| Ready for Billing queue on Billing Review: approve, hold, exclude, adjust, draft invoices | Available | Business → Billing → Billing Review | Creates drafts only; nothing is sent | [BILLING.md](docs/BILLING.md#ready-for-billing) |
| Consolidated invoices: one draft per customer from selected tickets, account charges and the agreement fee | Available | Billing Review → Ready for Billing | Draft only; sent invoices change by credit note | [BILLING.md](docs/BILLING.md#consolidated-invoices) |
| Settings → Billing: approval thresholds, late fees, default tax and currency, month-to-month e-signature exemption, with per-customer and per-contract overrides | Available | Settings → General → Billing | Superusers and staff who can approve invoices | [BILLING.md](docs/BILLING.md#settings--billing) |
| Contract documents with digital signing: build, approve, send, sign link with optional e-mail code, countersign, evidence PDF and certificate; term and notice period; e-signature required before a non-month-to-month contract takes effect or bills | Available | Business → Contracts | The twelve sample agreements are starting points, not legal advice | [BILLING.md](docs/BILLING.md#contracts-samples-terms-and-e-signature) |
| Sample contract library (twelve starters) | Available | Business → Contracts → Templates → Use this sample | Not legal advice; review notes block sending until replaced | [BILLING.md](docs/BILLING.md#contracts-samples-terms-and-e-signature) |
| Viewed tracking for quote, invoice and contract links (first view, last view, count, webhook, email to creator) | Available | Automatic | Staff previews, email scanners and bots are not counted | [BILLING.md](docs/BILLING.md#contracts-samples-terms-and-e-signature) |
| Price book, service plans, labor rate cards, cost rates | Limited | Django admin | Admin-managed; picking items in quote/invoice editors planned | — |
| Accounting: QuickBooks Online, Xero (customer sync, duplicate-safe invoice push, payment status pull) | Limited | Settings → Integrations → Accounting | Payments, credit memos, refunds and voids are not pushed; FreshBooks, Wave, Zoho Books and Sage are listed but not implemented | — |
| Payments: Stripe (card/ACH), GoCardless; portal payment, saved methods, autopay, refunds | Limited | Service Desk → Billing → Payments | Not yet verified with live or sandbox keys; payments are not posted to accounting | [PAYMENTS.md](docs/PAYMENTS.md) |
| Sales tax: manual rates, Avalara AvaTax, TaxJar, exemptions | Limited | Settings → Integrations → Sales Tax | Provider calls not yet verified against sandboxes | [TAX.md](docs/TAX.md) |
| Software licensing: subscriptions, seats, renewals; Microsoft 365 and Pax8 sync | Available | Business → Licensing | Google Workspace not implemented | — |

## 12. Quotes, CRM and procurement

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Quotes: line items, tax, PDF, email, approval chains, no-login e-signature (required before a quote can be accepted or converted), Viewed status | Available | `psa_enabled` | Staff cannot accept on the customer's behalf | — |
| CRM: leads, opportunities, campaigns, commissions, quote from opportunity | Available | `crm_enabled` (off by default) | | — |
| Procurement, vendors, purchase orders | Available | `psa_enabled`; MSP staff | | — |
| Distributors: Ingram Micro Xvantage, Pax8, TD Synnex (catalog, price, availability, webhooks) | Limited | Settings → Integrations → Distributors | No ordering from the UI; D&H, ScanSource, QBS and Westcoast are listed but not implemented | — |

## 13. Reporting, dashboards and wallboards

Reports are MSP-staff only and cover every customer; financial reports need the View financial
reports permission.

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Profitability by client, technician, contract, project; effective hourly rate; revenue leakage; SLA trends; margin | Available | `reports_enabled` | Uses technician cost rates; missing rates are reported as incomplete | — |
| Business Overview (MRR/ARR, invoiced revenue, margin, growth, renewals), each card naming its source | Available | Dashboard → Business Overview; `reports_view_dashboards` | | — |
| Custom dashboards, report templates, scheduled reports, report writer | Limited | Scheduler | Template PDFs are plain text of the data | — |
| Wallboards (configurable widget boards with rotation) | Available | Reports → Wallboards | Presentation mode, presets and display pairing planned (Phase 83) | — |
| Client health score (six dimensions, nightly snapshots) | Limited | Business → Client Health | Staff-only; portal display planned | — |
| Pricing Advisor (nightly findings, recommendations) | Available | Reports → Pricing Advisor | Plain-English explanation is OPTIONAL AI (`psa_ai_enabled`) | — |
| Pulse checks (periodic customer feedback) | Available | `pulse_enabled` (off by default) | CSV export planned | [PULSE_CHECKS.md](docs/PULSE_CHECKS.md) |
| Compliance: PCI-DSS v4 and HIPAA catalogs, attestation, PDF report, evidence pack ZIP | Limited | None | No other frameworks seeded | — |
| Audit log with CSV/JSON export | Limited | Owner/Admin | Request-level log; no before/after values for most changes | — |

## 14. Client portal

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Tickets, replies, secure replies, plain-language progress, votes, escalation | Available | `psa_enabled` and the customer's portal enabled | Only tickets shared with the customer | — |
| Request a service (guided catalog forms with KB suggestions) | Available | Catalog item portal visibility | | — |
| Customer approvals | Available | Portal customer-approvals setting | | — |
| Knowledge base, vault entries (per-entry visibility), agreements, pulse feedback, announcements, Service Status | Available | Settings → General → Customer Portal | | — |
| Billing: invoices, online payment, saved methods, autopay | Limited | Payments connection | Payment provider calls not yet verified | [PAYMENTS.md](docs/PAYMENTS.md) |
| Portal address, sign-in and branding | Available | Settings → General → Customer Portal | | — |
| Customer command center (health, backups, contracts, licensing, self-service requests) | Planned | | Phase 77 | [ROADMAP.md](docs/ROADMAP.md) |

## 15. AI assistance (OPTIONAL AI)

Every AI feature is optional and gated by `psa_ai_enabled` (off by default). Nothing calls a
provider until an administrator configures one. Ticket AI additionally needs a per-customer AI
policy, an enabled model profile and a technician access assignment at that customer.

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| Documentation generate, enhance, validate | Available | Settings → AI Configuration → AI & LLM | Providers: Anthropic, OpenAI, Moonshot, MiniMax, Ollama | — |
| Ticket reply drafts, suggested actions, triage (AI Inbox) | Available | Settings → AI Configuration → Ticket AI models; customer AI policy | Providers: Anthropic, OpenAI, Ollama; nothing is sent to a customer until a technician presses Send | [CLIENT_DATA_PROTECTION.md](docs/CLIENT_DATA_PROTECTION.md) |
| Ticket Analyze and Compare models (2–4 profiles) | Limited | As above, plus a paired RMM | Requires a paired RMM as the job processor ("No RMM is paired" otherwise) | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |
| AI Troubleshoot (primary/fallback/local-first/cheapest routing, multi-model) | Available | Customer policy `troubleshoot_enabled` | Text suggestions only; cannot run commands | [AI_TROUBLESHOOT.md](docs/AI_TROUBLESHOOT.md) |
| Redaction: secrets stripped from evidence; network identifiers and contact names replaced when sharing rules say so; vault data, attachments and internal notes never sent; preview of what leaves | Available | Customer AI policy sharing rules | | [CLIENT_DATA_PROTECTION.md](docs/CLIENT_DATA_PROTECTION.md) |
| Budgets, run limits, local-only mode, history with retention | Available | Customer AI policy | | — |
| Optional separate AI gateway service | Available | `AI_GATEWAY_MODE=worker`; compose profile `ai-gateway` | Synchronous features refuse in worker mode and point to Analyze | — |
| Receipt extraction, floor plan generation, pricing advisor explanation, security incident summary | Limited | `psa_ai_enabled` | | — |
| AI Operations Analyst | Planned | | Phase 90 | [ROADMAP.md](docs/ROADMAP.md) |

## 16. Identity, roles and access

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| TOTP 2FA (required by default), Argon2, lockout, session idle and maximum length, password policy | Available | Settings → Security → Security Settings (environment variables override) | | — |
| Sign out everywhere (web, optionally mobile) | Available | Profile | | — |
| Azure AD / Entra ID SSO | Limited | Settings → Users & Access → Directory Services | Counts as 2FA only when Microsoft confirms MFA (or `AZURE_SSO_TRUSTED_AS_2FA`) | — |
| LDAP / Active Directory sign-in | Available | Settings → Users & Access → Directory Services | Needs optional `django-auth-ldap` and `python-ldap` | — |
| OIDC sign-in | Limited | Settings → Security → Single sign-on (OIDC); off by default | Not yet verified against a live identity provider | [OIDC_SSO.md](docs/OIDC_SSO.md) |
| SAML, passkeys | Planned | | | [ROADMAP.md](docs/ROADMAP.md) |
| Roles: built-in and custom, about a hundred switches; View passwords/documents/assets/files/monitors/integrations enforced per customer | Available | Settings → Users & Access → Roles | Vault export permission not implemented | [ROLES_AND_ACCESS.md](docs/ROLES_AND_ACCESS.md) |
| Access groups: named groups of MSP staff (L1/L2/L3 Tech, Managers, Sales, Sales Managers, Owners, Administrators, Billing, Auditors by default) with one role and a customer scope; members hold it in addition to their own access | Available | Settings → Users & Access → Access groups | Staff only; a group never removes access or grants superuser or an RMM tier | [ROLES_AND_ACCESS.md](docs/ROLES_AND_ACCESS.md#access-groups) |
| Technician Access: L1/L2/L3 presets per technician or group per customer, expiry, denies, "why" page, protected changes needing a second administrator | Available | Settings → Security → Technician Access | | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |
| Superuser Approval (second administrator approves superuser grants) | Available | Settings → Security → Superuser Approval; 2+ administrators | Off by default | [TECHNICIAN_ACCESS.md](docs/TECHNICIAN_ACCESS.md) |
| Security Features: per-customer check of which protections are in effect | Available | Settings → Security → Security Features | | [CLIENT_DATA_PROTECTION.md](docs/CLIENT_DATA_PROTECTION.md) |
| Key rotation and secret storage audit (`rotate_encryption_key`, `check_secrets_storage`) | Available | CLI | | [SECURITY.md](SECURITY.md) |
| Content-Security-Policy with nonces | Limited | `CSP_REPORT_ONLY=False` to enforce | Report-only by default | — |

## 17. API, integrations and administration

| Feature | Status | Configuration | Limitations | Docs |
|---|---|---|---|---|
| REST API: assets, contacts, documents, passwords, tags; organizations and hardware read-only | Limited | API key | No tickets, monitors or locations endpoints | [API_V2_GRAPHQL.md](docs/API_V2_GRAPHQL.md) |
| API keys: levels, organization scope, expiry, allowed sources, per-key rate limit, rotation with overlap, required client-certificate fingerprint (mutual TLS) | Available | `/api/keys/` | Mutual TLS needs a reverse proxy that verifies the client certificate | [API_ACCESS_CONTROL.md](docs/API_ACCESS_CONTROL.md) |
| API Access Control: IP/CIDR allow and deny rules for the APIs and inbound webhooks, modes, scopes, test-an-address, refused-request log, rollback window, repeat-source alerts, per-address limits, trusted proxies | Available | Settings → Security → API Access Control (superusers); Unrestricted by default | Concurrency limits not built; web pages are covered by Firewall & GeoIP instead | [API_ACCESS_CONTROL.md](docs/API_ACCESS_CONTROL.md) |
| Inbound webhook protection: signatures, timestamps, replay protection (security vendor, SIEM, distributor, ticket partner) | Available | Per connection | Opt-in for existing security vendor connections | [API_ACCESS_CONTROL.md](docs/API_ACCESS_CONTROL.md) |
| GraphQL | Limited | `requirements-graphql.txt` | Session only (no API keys); not in the Docker image; mostly read-only | [API_V2_GRAPHQL.md](docs/API_V2_GRAPHQL.md) |
| Mobile API; native mobile app | Available / Separate component | `/api/mobile/v1/` | App source is maintained outside this repository | — |
| Outbound webhooks (assets, documents, password metadata, reveals, locations, organizations, workflows, monitors, syncs) | Available | Settings → Integrations → Webhooks | Plain JSON; no Slack/Teams format | — |
| Third-party PSA sync: ConnectWise Manage, Autotask, HaloPSA, Kaseya BMS, Syncro, Freshservice, Zendesk, ITFlow; RangerMSP and Alga PSA (newly added) | Available / Limited | Settings → Integrations; `psa_sync` task (off by default) | Companies, contacts, tickets only; no projects/agreements or field mapping | [INTEGRATION_SETUP_GUIDE.md](docs/INTEGRATION_SETUP_GUIDE.md) |
| Microsoft 365 tenant connection | Limited | Settings → Integrations | Read-only inventory with manual sync; not yet verified against a real tenant | [INTEGRATION_SETUP_GUIDE.md](docs/INTEGRATION_SETUP_GUIDE.md) |
| SMS: Twilio, Plivo, Vonage, Telnyx | Available | Settings → Communications → SMS Provider | AWS SNS and Sinch are listed but not implemented | — |
| Agit8or Connect / Quick Connect (app-to-app pairing, default-deny source and destination addresses, health, automatic reconnection, incidents, diagnostics) | Limited | `AGIT8OR_CONNECT_ENABLED=True` (off); Settings → Integrations → Connected Applications | Early release, not independently reviewed; incoming events are stored, acting on them is planned | [CONNECTED_APPLICATIONS.md](docs/CONNECTED_APPLICATIONS.md) |
| Built-in scheduler (no crontab, Redis or Celery) | Available | Settings → Automation → Task Scheduler | | — |
| Feature toggles and Optional Modules page | Limited | Settings → Modules | Install-wide, not per customer; some switches only hide menus | — |
| Web updates: Official or Preview channel (explained on the page), pinned commit, signed tag check, preflight, verified pre-upgrade backup, one status and stage checklist while updating, resume/repair, restore points | Available | Settings → System → System Updates | Rollback is a manual restore command on the server | [UPGRADE_AND_RECOVERY.md](docs/UPGRADE_AND_RECOVERY.md) |
| Off-host backups: encrypted (AES-256-GCM, separate backup key) database and uploads to SFTP or a mounted directory, retention, weekly restore verification, warnings | Available | Settings → Maintenance → Off-host Backups (superusers); off until set up | No S3 client; use SFTP or mount the bucket. `.env` keys are never in the archive | [BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md) |
| Backup and restore commands (`manage.py backup`, `restore`) | Limited | CLI | No web restore; not scheduled by default; on SQLite never copy `db.sqlite3` while running | [UPGRADE_AND_RECOVERY.md](docs/UPGRADE_AND_RECOVERY.md) |
| Install: Docker Compose (app, scheduler, MariaDB; profiles proxy, cache, ai-gateway) or `install.sh` (MariaDB, Gunicorn on :8000, systemd) | Available | `.env` | `install.sh` does not install Nginx or TLS and creates `admin` / `ChangeMe123!` (change at first login); single server only | [docker.md](docs/docker.md), [INSTALL.md](INSTALL.md) |
| Health endpoint `/health/`, system status page | Available | None | | — |
| Maintenance mode, log rotation | Planned | | Configure logrotate yourself | — |

---

**Architecture:** Django with Django REST Framework, Gunicorn, MariaDB/MySQL (SQLite for local
development), Bootstrap 5 and plain JavaScript with no build step, AES-256-GCM via Python
`cryptography`, and a built-in database-backed scheduler. One server per MSP.
