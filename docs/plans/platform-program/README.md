# Clientst0r + Rem0te platform program (directive of 2026-11-20)

Internal planning document. It consolidates the platform directive received on 2026-11-20. Competitor product
names appear only in the feature matrix ([MSP_PLATFORM_FEATURE_MATRIX.md](../MSP_PLATFORM_FEATURE_MATRIX.md)),
never in `docs/ROADMAP.md`, FEATURES.md or marketing prose.

Related programs that this one builds on rather than repeats:

- [Competitive program (2026-11-19)](../competitive/GAP_ANALYSIS.md) — gap analysis, security review, integration
  test matrix and the R-01 … R-21 increments.
- [MSP billing, quote-to-cash and CRM discovery program](../msp-billing-program/README.md) — roadmap Phases 70,
  97, 98, 101–105 and the [billing capability audit](../msp-billing-program/CAPABILITY_AUDIT.md).
- [Phases 96–100](../phases-96-100/README.md) — setup wizard, prospect assessment, estimator, telephony.

Audits for this program: [CLIENTST0R_AUDIT.md](CLIENTST0R_AUDIT.md) and [REM0TE_AUDIT.md](REM0TE_AUDIT.md). The
future RMM backlog is [REM0TE_FEATURE_EXPANSION_ROADMAP.md](REM0TE_FEATURE_EXPANSION_ROADMAP.md).

## Two applications, one platform

- **Clientst0r** — PSA, CRM, ticketing, customers, contracts, billing, documentation, security operations, MSP
  business management.
- **Rem0te** — RMM, endpoint monitoring, remote access, patching, software deployment, scripting, endpoint
  administration.

They stay separate applications with separate security boundaries, joined by explicit, signed, versioned
integration contracts. Clientst0r may request or suggest an endpoint action; Rem0te independently authorizes
it; the endpoint validates the signed authorization. There is never a second execution engine in Clientst0r and
never a shortcut around Rem0te's approval system.

## Competitive aims to preserve

Self-hosting and data ownership; open source; comprehensive MSP features without excess complexity; strong
technician permissions and security; integrated PSA and RMM with separate security boundaries; strong
documentation and physical and network asset management; optional, useful AI; simple setup, administration and
upgrades; low running cost; the full customer lifecycle from prospect to recurring revenue.

## Execution order

**Clientst0r first; Rem0te expansion later.** Rem0te receives only narrowly scoped compatibility, integration or
critical security changes until the Clientst0r completion checklist is met, and those go through the
coordination file (`INTEGRATION_COORDINATION.md`), never as direct edits from this project.

| Stage | Content | Priority |
|---|---|---|
| 0 | Roadmap first: audits, feature matrix, gaps, Clientst0r roadmap update, Rem0te backlog, issues and dependencies | — |
| 1 | Clientst0r core completion: PSA/RMM integration (A), quote-to-contract and quote-to-invoice, billing correctness (B), security and permission gaps (L), ticket workflow and automation safety (E), setup wizard (M, Phase 96) | P0 |
| 2 | Backup management (I): St0r/UrBackup, Comet, one overview, coverage, alerts, ticket workflow, reports, billing | P1 |
| 3 | Device management (N): MDM integrations, inventory, compliance, approved device workflows, Linux/macOS visibility through Rem0te, one device record and reporting | P2 |
| 4 | Sales and documentation: CRM discovery, estimator, discovery-to-quote (C); documentation and discovery improvements (F) | P3 |
| 5 | Business intelligence (J) and customer portal (K) | P3 |
| 6 | Advanced integrations: Microsoft 365 (H), security vendors, event correlation, SOC, approval-driven automation (G); optional AI (D) | P3 |
| 7 | Polish and completion: remaining gaps, UI simplification, installation and configuration, documentation, integration and regression coverage, release preparation; the Clientst0r completion checklist | — |
| 8 | Rem0te functional expansion — only after Stage 7: full Linux, full macOS, cross-platform patching, software deployment, scripting, automated remediation, MDM coordination, backup-related device workflows, further endpoint security | — |

Stage priorities follow the second directive of 2026-11-20 ("Roadmap additions: St0r, Comet Backup, MDM, macOS &
Linux"), which moved backup management to P1 and device management to P2 and placed CRM/discovery, AI pricing,
reporting, portal, advanced integrations and polish in P3. Roadmap phase mapping: `docs/ROADMAP.md` §"Stages".

AI work needed by an approved workflow may proceed alongside it, but AI never blocks or delays the non-AI core.

## Scope by area

### A. PSA/RMM integration (P0)

Technician path: open ticket → customer and device → device health and recent alerts → relevant history →
request a diagnostic → launch an authorized remote session → request an approved remediation → review results →
results on the ticket → verify → close, without copying between applications. Needs: immutable customer and
device IDs; ticket-to-endpoint links; health, alerts, inventory summary, patch and connectivity status in the
ticket; session launch; read-only diagnostic requests; remediation proposals with status and results; ticket
synchronization; failure reporting; technician permission enforcement; cross-application audit references;
actionable errors. Clientst0r side first; only the smallest compatible Rem0te changes, through the contract and
coordination file.

### B. Quoting, contracts and billing (P0)

Covered by the [billing program](../msp-billing-program/README.md) and roadmap Phases 65, 68–72, 92, 101–104.
Adds from this directive: approval chains, procurement drafts and customer service assignments on conversion,
quantity reconciliation, renewals.

### C. CRM, prospect discovery and onboarding (P1)

Covered by roadmap Phases 97 and 98 and billing program §H: guided discovery (business, workstations, servers,
network, applications, security, support needs) with quick and detailed modes, drafts, templates, attachments,
PDF and future asset import; deterministic estimator with low / expected / high; discovery-to-quote into the
existing quote builder; onboarding tasks, documentation checklists, inventory, billing schedules and approved RMM
deployment requests on acceptance.

### D. Optional AI pricing and sales intelligence (P2)

Covered by roadmap Phases 76 and 105: market pricing with sourced evidence and geographic scope, prospect
proposals (Basic / Standard / Premium), customer profitability reviews, market comparison reports; existing AI
infrastructure; research and inference configured separately; tenant isolation, permissions, budgets, approval,
redaction.

### E. Ticketing and technician workflow (P1)

The ticket page as the technician's work area: customer, contact, contract, SLA, assignee, assets, RMM health,
alerts, relevant knowledge, permission-controlled credentials, tasks, time, billable items, action history.
Workflow: drag-and-drop attachments, quick assignment, quick time and timers, one-click internal note and public
reply, canned replies, knowledge insertion, suggested troubleshooting, escalation, merging, related-ticket
detection, approval requests, reminders, customer follow-up, handoff summaries. Automation: visual rule builder
(no JSON for ordinary rules), conditions, triggers, actions, delays, escalations, dry run, execution history, loop
prevention, rate limits, retries, per-customer overrides, approval for sensitive actions. SLAs: customer business
hours, holidays, several coverage schedules, priority targets, after-hours escalation, on-call, breach prediction,
correct pause and resume.

### F. Documentation, inventory and network management (P1)

Authorized discovery jobs without a ticket (administrator-defined scope, scheduled runs for approved ranges, scope
checks, rate limits): ICMP, TCP ports, service detection, printers, access points, firewalls, and — **blocked
pending the owner's confirmation, because an SNMP collector was previously declined** — SNMP, LLDP/CDP, MAC and ARP
tables and switch-port association. Synchronization into assets, ports, patch panels, cables, VLANs, IPs, racks and
maps, keeping manual facts, discovered facts and unverified suggestions apart and never overwriting approved
documentation. Network monitoring (interface utilization, errors, link, PoE, CPU, memory, temperature, firewall,
printer and wireless status, bandwidth history, thresholds) — the SNMP-based parts carry the same block.
Documentation: ranked full-text search, attachments, secure sharing, bulk asset editing, per-asset history, asset
relationships and dependency maps, completeness scoring, reminders, import and export.

### G. Security operations and event management (P1/P2)

Builds on roadmap Phases 82–89: events from RMM, backup, security tools, website and network monitors, Microsoft
365, firewalls, endpoints and customer integrations; normalization, deduplication, correlation, severity,
customer and asset association, evidence, history, ticket and incident links, suppression, maintenance windows.
Vendor integrations (Defender, SentinelOne, CrowdStrike, Huntress, Bitdefender, Sophos, firewalls, backup) built
properly and never shown as working when they are only generic webhooks. SOC views, triage, posture, wallboards,
routing, escalation, customer summaries. Approval-driven playbooks; endpoint execution stays with Rem0te or the
security product.

### H. Microsoft 365 and cloud administration (P2)

Tenant, user, license and utilization inventory; MFA, conditional access and security-defaults visibility;
mailboxes, shared mailboxes, groups, guests, dormant accounts; security alerts, service health, backup coverage,
baseline reporting. From a new-user ticket: prepared user creation, licenses, groups, mailbox and onboarding tasks,
with approval and least-privilege delegated access. Google Workspace where practical.

### I. Backup management (P1 since the second directive)

Extends Phase 74 backup monitoring through provider APIs (Proxmox Backup Server, Veeam, Acronis, Cove, Datto and
others): job and protected-asset inventory, last success, retention, storage, failures, restore verification and
test history, compliance, customer reports; where the provider allows, start, retry, restore and restore status,
permissioned and audited. No backup engine inside Clientst0r. Second directive: St0r (the UrBackup management
interface, several installations) and Comet Backup (several management servers) as first providers, a unified
overview with protection coverage, customer portal status and backup billing from verified counts — roadmap
74.7–74.12, 77.8, 92.6; specification `docs/plans/backup-integrations/README.md`.

### N. Device management — MDM (P2, added by the second directive)

Integrate established MDM/UEM providers rather than building an MDM server: Microsoft Intune and Entra ID,
Jamf Pro, Mosyle, Kandji, Apple Business Manager through supported workflows, Android Enterprise through a
supporting provider. Inventory for Windows, macOS, iPhone, iPad and Android (corporate and permitted BYOD);
compliance; approved actions (enrollment, assignment, policies, profiles, apps, lock, retire, wipe, lost mode)
with fresh authentication, explicit confirmation and authorization for destructive ones and never AI-initiated;
links to assets, employees, onboarding and offboarding, tickets, security events, reporting, portal and service
plans. Provider authorization stays separate from Clientst0r workflow approval. Roadmap Phase 106;
specification `docs/plans/mdm/README.md`.

### J. Reporting and business intelligence (P1/P2)

Business: MRR, ARR, growth, contract and customer profitability, utilization, effective rates, billable vs
non-billable, block utilization, leakage, unbilled tickets, renewals, churn, pipeline, win rate, sales cycle,
project and subscription margins, overdue invoices, acquisition. Service delivery: tickets per customer, device and
technician, SLA, first response, resolution, repeats, reopens, escalations, satisfaction, common problems,
automation impact. Role dashboards with filters; one set of data definitions; CSV and PDF.

### K. Customer portal (P2)

Unified customer dashboard (tickets, requests, contracts, included services, block balances, invoices, payments,
quotes, approvals, managed assets, backup status, maintenance notices, service status, security summaries) and
self-service (tickets, new employees, equipment, software, quote and work approvals, signing, invoices, payments,
published documentation) with configurable forms; never internal costs, private notes, privileged credentials or
other customers' records.

### L. Security across Clientst0r (P0/P1)

Identity: MFA, passkeys/WebAuthn, OIDC SSO, Entra ID, Keycloak, session controls, step-up authentication, emergency
recovery accounts, identity lifecycle and technician offboarding. Access: per-customer roles, L1/L2/L3,
least privilege, customer scope, approvals, temporary access and expiry, access reviews, audit; the same checks in
UI, API, workers, exports and integrations. Credentials: vault, API keys, RMM keys, accounting, payment, AI and SMTP
secrets with separation and rotation; never sent to AI. Audit: tamper evidence, off-host export, independent
verification, permission, credential, integration and financial change tracking. Integration security: signed
messages, replay protection, identity binding, tenant checks, narrow scopes, rotation, expiry, idempotency, rate
limits, validation. Application security: dependency, static and secret scanning, CSRF, XSS, SSRF, uploads, API
authorization, container and worker permissions, backup encryption, restore access, update signing, headers.

### M. Installation, configuration and usability (P1)

First-run wizard (identity, FQDN, reverse proxy and TLS, single-MSP or supported multi-tenant mode, mail,
administrator, MFA, security defaults, modules, portal, billing, optional accounting, optional AI, optional Rem0te
pairing, backups, verification) without inventing unsupported topologies. One searchable settings experience
showing per module: enabled, configuration, connection status, credentials, security needs, dependencies, test,
health, documentation link. UI principles: short menus, shallow navigation, few modals, visible common actions,
consistent labels, clear errors, few reloads, responsive, dark and light themes.

## Platform workflows (end goals)

1. New customer: lead → assessment → estimate → optional market research → packages → quote → signature →
   contract → onboarding → recurring billing.
2. Support: ticket → assignment → device → diagnostics → authorized session → approved remediation →
   verification → time → billing classification → resolution.
3. Monitoring alert: alert → correlation → customer and device → ticket or incident → review → approved action →
   verification → closure.
4. Renewal: utilization → profitability → optional market comparison → suggested pricing → proposal → approval →
   signed agreement → billing update.
5. New employee: request → approval → checklist → authorized Microsoft 365 provisioning → licenses → equipment →
   software → documentation → completion.
6. Hardware replacement: ticket or assessment → hardware → quote → approval → purchase order → receiving →
   inventory → asset assignment → installation → invoice → lifecycle.

Each reuses existing modules; no parallel implementations.

## Development rules (every phase)

Compatibility: no broken installations, data or API contracts; no reset settings; no invalidated signed documents;
no duplicated billing records; no silent permission changes; optional features stay off; AI never required;
compatible migrations and feature flags. Architecture: reuse, modular extensions, Clientst0r/Rem0te separation,
tenant isolation, one canonical record per business object, endpoint execution only in Rem0te, finance decisions
only in authorized PSA workflows, explicit contracts, no hidden coupling. Tests: unit, integration, permission,
tenant isolation, financial integrity, migration, regression, API contract and error handling; never weaken
existing security tests. Documentation: README, FEATURES, ROADMAP, API, configuration, user, integration and
security guides and the showcase, only at the level actually implemented.

## Clientst0r completion checklist (Stage 7 exit)

Clientst0r is complete when every item below is demonstrably true — not when every heading exists:

1. Workflows 1, 2, 3, 4 and 6 run end to end on a test install with real code on both applications (Workflow 5
   needs Phase H), each covered by an automated end-to-end test.
2. Every P0 and P1 roadmap item is Complete, or explicitly Deferred by the owner with a reason.
3. No open finding in `docs/plans/competitive/SECURITY_REVIEW.md` rated Medium or above.
4. Every integration listed in FEATURES.md is either verified against the real service or its sandbox, or labelled
   by its actual level (adapter, mocked, webhook only).
5. Billing acceptance tests of the billing program pass, and one set of financial definitions is used by every
   report.
6. A fresh install (script and Docker) reaches a working, secured state through the setup wizard without manual
   file edits; an upgrade from the previous release keeps all data.
7. Rem0te integration: the pinned contract version matches Rem0te's current release and the cross-peer E2E suite
   passes.
8. Documentation and the showcase describe only what items 1–7 verified.
