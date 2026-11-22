# Clientst0r — Development Roadmap

**Clientst0r** is a self-hosted platform for managed service providers: PSA (tickets, contracts, billing, quotes),
IT documentation and assets, a password vault, monitoring, a customer portal and integrations. Endpoint management
(RMM) lives in the separate **Rem0te** application; Clientst0r requests and records, Rem0te approves and executes.

[Overview](#overview) · [Current priorities](#current-priorities) · [Active development](#now) ·
[Next priorities](#next) · [Feature matrix](#feature-matrix) · [Blockers & dependencies](#blockers) ·
[Completed features](#completed) · [Future roadmap](#later) · [Technical details](#technical-details) ·
[Release history](#release-history) · [Related planning documents](#related-documents) ·
[How to update this roadmap](#maintaining)

<a id="overview"></a>

## Overview

<!-- generated:counts -->

| | |
|---|---|
| Latest release | ![Latest release](https://img.shields.io/github/v/release/agit8or1/clientst0r?label=release) — see the [changelog](../CHANGELOG.md) |
| Last roadmap audit | 2026-11-20 |
| Active stage | Stage 1 — core completion (P0) |
| Phases | **108** in total |
| ✅ Complete | 52 (of which 2 marked for verification) |
| 🔵 In progress | 28 |
| 🟡 Partial | 4 |
| ⬜ Planned | 23 |
| 🔴 Blocked | 0 (plus blocked items inside other phases — see [Blockers](#blockers)) |
| ⏸️ Deferred | 1 |

<!-- /generated:counts -->

**Strategy — finish Clientst0r first.** Rem0te receives only compatibility, integration and critical security
work until the [Clientst0r completion checklist](#before-rem0te) is met; its larger backlog is kept in the
[Rem0te feature expansion roadmap](plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md).

**Status legend:** ✅ Complete · 🔵 In progress · 🟡 Partial (some parts work; what is missing is named) ·
⬜ Planned · 🔴 Blocked (waiting on a decision or another product) · ⏸️ Deferred. A ✅ phase means the whole phase is
done; finished items inside open phases are marked *(shipped vX)* in that phase's details.

<a id="current-priorities"></a>

## Current priorities

The P0 sequence, in order:

1. Audit-log integrity and playbook approval security — [94.1](#phase-94), [51.20](#phase-51)
2. Ticket Time & Charges and the prepaid-hour ledger — [Phase 101](#phase-101)
3. Ready for Billing and invoice correctness — [Phase 102](#phase-102)
4. Quote-to-contract and quote-to-invoice — [70.1, 70.2](#phase-70)
5. Remaining PSA/RMM integration work — [63.11–63.17](#phase-63)
6. Ticket automation and workflow safety — [Phase 91](#phase-91)

Then, in this order: backup management (P1, [Phase 74](#phase-74)), device management (P2,
[Phase 106](#phase-106)), then CRM and discovery, reporting, customer portal, advanced integrations and optional AI
(P3).

| Priority | Meaning |
|---|---|
| **P0 — Critical** | Core completion, financial correctness or critical security |
| **P1 — High** | Important next-stage capabilities |
| **P2 — Medium** | Planned platform expansion |
| **P3 — Future** | Enhancements and advanced integrations |
| **P4 — Deferred / exploratory** | Needs a later decision |

A priority marked `*` is taken from the [stage table](#later) because the phase header carries none.

<details>
<summary>Priority notes for review</summary>

- Phases 52, 91 and 111 are in Stage 1 (P0) but their headers say P1. Both are kept as written; the header value is shown.
- Billing prerequisites 68, 69, 92 and 93 carry no priority of their own although P0 Phases 101 and 102 depend on
  them; the dependency is shown in each row.
- Open phases with no priority and no stage:

<!-- generated:unprioritized -->

- 9 — [Security alert ingestion: EDR / AV / Firewall on the dashboard](#phase-9) (🟡 Partial)
- 14 — [Visual Workflow Automation Engine](#phase-14) (🟡 Partial)
- 23 — [Security Event & Incident Workflows](#phase-23) (🟡 Partial)
- 33 — [Network Discovery & Auto Documentation](#phase-33) (🟡 Partial)
- 56 — [Ticket AI Assist and RMM handoff](#phase-56) (🔵 In progress)
- 57 — [Technician security levels and abuse prevention](#phase-57) (🔵 In progress)
- 59 — [Verified installs and upgrades](#phase-59) (🔵 In progress)
- 62 — [Pluggable document editors](#phase-62) (🔵 In progress)
- 65 — [Contract documents and digital signing](#phase-65) (🔵 In progress)
- 66 — [Client pulse checks](#phase-66) (🔵 In progress)
- 67 — [Interface, navigation and dashboard redesign](#phase-67) (🔵 In progress)
- 68 — [Commercial price book and service plans](#phase-68) (🔵 In progress)
- 69 — [Labor rate cards and cost rates](#phase-69) (🔵 In progress)
- 71 — [Accounting sync completion](#phase-71) (🔵 In progress)
- 72 — [Payment processing and sales tax](#phase-72) (🔵 In progress)
- 73 — [Procurement, distributors, licensing and warranty lifecycle](#phase-73) (🔵 In progress)
- 79 — [Agit8or Connect: secure application-to-application integration](#phase-79) (🔵 In progress)
- 80 — [Agit8or Identity: single sign-on for people](#phase-80) (🔵 In progress)
- 82 — [Shared operational event and alert foundation](#phase-82) (🔵 In progress)
- 92 — [Verified usage and recurring billing](#phase-92) (⬜ Planned)
- 93 — [Business-hours SLA calendars](#phase-93) (⬜ Planned)
- 95 — [PSA migration importers](#phase-95) (⬜ Planned)

<!-- /generated:unprioritized -->

</details>

<a id="now"></a>

## Active development — NOW

Work being implemented now or approved as the next P0 task.

<!-- generated:now -->

| # | Phase | Priority | Status | Next step | Depends on |
|---|---|---|---|---|---|
| 1 | 94 — [Evidence integrity and routine backups](#phase-94) | P0\* | 🔵 In progress | External append-only audit shipping (94.1); protected-change approval for audit pruning (94.2); S3 destination (94.3) | — |
| 2 | 51 — [Reliability and customer-boundary hardening](#phase-51) | P0\* | 🔵 In progress | Per-customer integration ownership (remaining part of the platform-integrations item) | — |

<!-- /generated:now -->

<a id="next"></a>

## Next priorities — NEXT

Approved, in priority order, not started (or started only in parts already listed above).

<!-- generated:next -->

| # | Phase | Priority | Status | Next step | Depends on |
|---|---|---|---|---|---|
| 1 | 102 — [Ready for Billing queue and invoice integrity](#phase-102) | P0 | 🔵 In progress | 102.5 invoice presentation; 102.6 recurring billing gaps; 102.7 one set of financial definitions | 15, 36, 75, 92, 101 |
| 2 | 70 — [Contracts, recurring billing and quote conversion](#phase-70) | P0 | 🔵 In progress | 70.1 quote to contract, 70.2 quote to invoice | 65, 68, 69 |
| 3 | 63 — [RMM integration and technician workspace](#phase-63) | P0 | 🔵 In progress | 63.17 contract hygiene now; 63.11–63.16 as Rem0te ships each item | 52, 56, 57; Rem0te contract |
| 4 | 91 — [Workflow automation safety](#phase-91) | P1 | 🔵 In progress | 91.6–91.9; approval or cap on charge amounts (91.4) | 14 |
| 5 | 52 — [Technician workspace](#phase-52) | P1 | 🔵 In progress | 52.22 OPTIONAL AI wording | 51 |
| 6 | 111 — [Identity lifecycle and access reviews](#phase-111) | P1 | 🔵 In progress | 111.1 passkeys; 111.3 one-action offboarding | 57, 64, 80 |
| 7 | 74 — [Backup monitoring, backup management and endpoint health](#phase-74) | P1 | 🔵 In progress | 74.8 Comet read-only provider; 74.9 overview; 74.7 when the St0r API lands | 63, 82; St0r API (74.7) |
| 8 | 106 — [Device management (MDM) integrations](#phase-106) | P2 | ⬜ Planned | 106.1 provider connections | 64, 74.9, 82, 92 |
| 9 | 79 — [Agit8or Connect: secure application-to-application integration](#phase-79) | — | 🔵 In progress | 79.21 public Agit8or Connect repository (needs the owner to create agit8or1/agit8or-connect); then interoperability tests between two installations and the security review (Quick Connect increments F, G, H) | Rem0te contract |

<!-- /generated:next -->

<a id="feature-matrix"></a>

## Feature matrix

Every phase appears once, under one workstream. Workstreams are presentation groups; stages and phase numbers are
unchanged. Click a feature for its details.

<!-- generated:matrix -->

### A. Core PSA & Ticketing

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 14 | [Visual Workflow Automation Engine](#phase-14) | — | 🟡 Partial | — | Time-based triggers, delays and escalation logic (91.6) |
| 52 | [Technician workspace](#phase-52) | P1 | 🔵 In progress | 51 | 52.22 OPTIONAL AI wording |
| 91 | [Workflow automation safety](#phase-91) | P1 | 🔵 In progress | 14 | 91.6–91.9; approval or cap on charge amounts (91.4) |
| 93 | [Business-hours SLA calendars](#phase-93) | — | ⬜ Planned | — | 93.1 calendars |

<details markdown="1">
<summary>14 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 2 | [Resource management foundation](#phase-2) | ✅ Complete | — | — |
| 6 | [ITIL maturity](#phase-6) | ✅ Complete | — | — |
| 8 | [Native mobile apps (iOS + Android) with GPS auto-time + Timeclock](#phase-8) | ✅ Complete | v3.17.417 | — |
| 10 | [Advanced Email-to-Ticket Engine](#phase-10) | ✅ Complete | — | — |
| 11 | [Advanced Dispatch & Technician Scheduling](#phase-11) | ✅ Complete | — | Geo-aware routing and travel time deferred (needs Phase 8 GPS data) |
| 20 | [Approval & Change Management Workflows](#phase-20) | ✅ Complete | v3.17.277 | — |
| 21 | [Advanced Mobile Technician Workflows](#phase-21) | ✅ Complete | v3.17.318 | — |
| 25 | [Mature Timesheet Approval Workflows](#phase-25) | ✅ Complete | — | — |
| 35 | [Advanced Project Management](#phase-35) | ✅ Complete | — | — |
| 38 | [Client Onboarding / Offboarding Runbooks](#phase-38) | ✅ Complete | — | — |
| 46 | [Job Kit: tools and materials on a ticket](#phase-46) | ✅ Complete | v3.17.533 | — |
| 47 | [Public scheduler wallboard](#phase-47) | ✅ Complete | v3.17.533 | — |
| 48 | [Task warning windows](#phase-48) | ✅ Complete | v3.17.535 | — |
| 60 | [Optional ticket routing](#phase-60) | ✅ Complete | v3.17.664 | — |

</details>

### B. Billing & Financial Management

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 65 | [Contract documents and digital signing](#phase-65) | — | 🔵 In progress | 15, 64 | 65.10 reviewed legal wording |
| 68 | [Commercial price book and service plans](#phase-68) | — | 🔵 In progress | 15 | 68.1 staff screens; 68.2 plans on contracts; 68.4 distributor price |
| 69 | [Labor rate cards and cost rates](#phase-69) | — | 🔵 In progress | 2, 68 | 69.1–69.3 rates used by invoicing (with 101.4); 69.4 |
| 70 | [Contracts, recurring billing and quote conversion](#phase-70) | P0 | 🔵 In progress | 65, 68, 69 | 70.1 quote to contract, 70.2 quote to invoice |
| 71 | [Accounting sync completion](#phase-71) | — | 🔵 In progress | 44 | 71.4–71.8 accounting completion; 71.11 sandbox verification |
| 72 | [Payment processing and sales tax](#phase-72) | — | 🔵 In progress | 71 | Provider verification; payment posting to accounting |
| 92 | [Verified usage and recurring billing](#phase-92) | — | ⬜ Planned | 70; Rem0te counts (92.4) | 92.1 recurring charge generation |
| 102 | [Ready for Billing queue and invoice integrity](#phase-102) | P0 | 🔵 In progress | 15, 36, 75, 92, 101 | 102.5 invoice presentation; 102.6 recurring billing gaps; 102.7 one set of financial definitions |
| 104 | [Customer approvals, deposits, change orders and portal billing](#phase-104) | P1 | ⬜ Planned | 72, 101, 103 | 104.1 out-of-scope approval |

<details markdown="1">
<summary>6 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 1 | [Contract / agreement engine deepening](#phase-1) | ✅ Complete | — | — |
| 15 | [Recurring Billing & Contract Management](#phase-15) | ✅ Complete | v3.17.299 | — |
| 27 | [Advanced Accounting Reconciliation](#phase-27) | ✅ Complete | v3.17.281 | — |
| 36 | [Agreement Reconciliation & Pre-Invoice Approval](#phase-36) | ✅ Complete — verify | — | Agreement profitability reports and revenue-leakage expansion have no shipped marker (audit 2026-11-20) |
| 44 | [Full Two-Way Accounting Sync](#phase-44) | ✅ Complete | v3.17.531 | — |
| 101 | [Ticket Time & Charges and prepaid-hour ledger](#phase-101) | ✅ Complete | v3.17.751 | — |

</details>

### C. Asset Management & Documentation

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 33 | [Network Discovery & Auto Documentation](#phase-33) | — | 🟡 Partial | 32, 16 | Decide SNMP/LLDP/CDP (108.4); label topology pages meanwhile |
| 62 | [Pluggable document editors](#phase-62) | — | 🔵 In progress | documents | 62.5 Google Docs connector; 62.6 portal editing permissions |
| 73 | [Procurement, distributors, licensing and warranty lifecycle](#phase-73) | — | 🔵 In progress | 4, 13, 68 | 73.2–73.6 ordering, receiving, warranty |
| 95 | [PSA migration importers](#phase-95) | — | ⬜ Planned | 61, 94.3 | 95.1 importer guarantees |
| 107 | [Documentation search, attachments, sharing and asset history](#phase-107) | P3 | ⬜ Planned | 16, 53 | 107.1 ranked search |
| 108 | [Discovery scope approval and suggested-device staging](#phase-108) | P3 | ⬜ Planned | 32, 33 | 108.1 approved scan ranges |

<details markdown="1">
<summary>11 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 4 | [Procurement workflow](#phase-4) | ✅ Complete | — | — |
| 13 | [Procurement & Lifecycle Management](#phase-13) | ✅ Complete | v3.17.272 | — |
| 16 | [Documentation Relationship Mapping](#phase-16) | ✅ Complete | v3.17.303 | — |
| 17 | [Advanced Asset Intelligence](#phase-17) | ✅ Complete | v3.17.310 | — |
| 18 | [Multi-Location Client Hierarchy](#phase-18) | ✅ Complete | v3.17.283 | — |
| 22 | [Knowledge Base & SOP Management](#phase-22) | ✅ Complete | — | — |
| 32 | [Remote Network Discovery Import](#phase-32) | ✅ Complete | — | — |
| 34 | [Network Configuration Backup](#phase-34) | ✅ Complete | — | — |
| 53 | [Documentation readiness and lifecycle](#phase-53) | ✅ Complete | v3.17.656 | — |
| 55 | [Hardware catalog and visual inventory](#phase-55) | ✅ Complete | v3.17.630 | — |
| 61 | [One-customer migration rehearsals (IT Glue, Hudu)](#phase-61) | ✅ Complete | v3.17.664 | — |

</details>

### D. RMM & Platform Integrations

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 9 | [Security alert ingestion: EDR / AV / Firewall on the dashboard](#phase-9) | — | 🟡 Partial | — | Real vendor API connectors (Phase 84); today every vendor is webhook-only |
| 23 | [Security Event & Incident Workflows](#phase-23) | — | 🟡 Partial | — | Approval-driven security automation (Phase 86); playbooks run only after approval since v3.17.737 |
| 56 | [Ticket AI Assist and RMM handoff](#phase-56) | — | 🔵 In progress | 57; Rem0te ticket-rmm-v1 | Remaining Rem0te-side items move with 63.11–63.16 |
| 63 | [RMM integration and technician workspace](#phase-63) | P0 | 🔵 In progress | 52, 56, 57; Rem0te contract | 63.17 contract hygiene now; 63.11–63.16 as Rem0te ships each item |
| 74 | [Backup monitoring, backup management and endpoint health](#phase-74) | P1 | 🔵 In progress | 63, 82; St0r API (74.7) | 74.8 Comet read-only provider; 74.9 overview; 74.7 when the St0r API lands |
| 79 | [Agit8or Connect: secure application-to-application integration](#phase-79) | — | 🔵 In progress | Rem0te contract | 79.21 public Agit8or Connect repository (needs the owner to create agit8or1/agit8or-connect); then interoperability tests between two installations and the security review (Quick Connect increments F, G, H) |
| 82 | [Shared operational event and alert foundation](#phase-82) | — | 🔵 In progress | 81 | 82.13 health reports over Connect; 82.3 per-connection rate limits; first consumers |
| 84 | [Security connector framework and vendor integrations](#phase-84) | P3\* | ⬜ Planned | 81, 82 | 84.1 connector SDK; vendor batches |
| 85 | [Operations Center, alert triage and correlation](#phase-85) | P3\* | ⬜ Planned | 82, 84 | 85.1 Operations Center |
| 86 | [SOAR Lite: approval-driven security automation](#phase-86) | P3\* | ⬜ Planned | 85, 51.20; Rem0te contract | 86.1 builder on the Phase 91 engine |
| 87 | [Alert routing, on-call and escalation](#phase-87) | P3\* | ⬜ Planned | 82, 85 | 87.1 notification routing |
| 88 | [Service dependency and impact mapping](#phase-88) | P3\* | ⬜ Planned | 16, 82 | 88.2 impact analysis |
| 106 | [Device management (MDM) integrations](#phase-106) | P2 | ⬜ Planned | 64, 74.9, 82, 92 | 106.1 provider connections |
| 109 | [Microsoft 365 administration](#phase-109) | P3 | ⬜ Planned | 64, 82 | 109.1 structured tenant models |

<details markdown="1">
<summary>1 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 7 | [Outsourcing, integrations, polish](#phase-7) | ✅ Complete | — | — |

</details>

### E. Sales & CRM

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 97 | [Prospect IT assessment and CRM enhancements](#phase-97) | P1 | ⬜ Planned | 5, 64, 75.3 | 97.1 assessment templates |
| 98 | [Service estimator and forecast accuracy](#phase-98) | P1 | ⬜ Planned | 97, 68–70, 75, 76, 92 | 98.1 estimation models |
| 103 | [Quote builder, options and price-book selection](#phase-103) | P1 | ⬜ Planned | 65, 68, 70 | 103.1 price book in the editors |
| 105 | [Market pricing research and AI proposals](#phase-105) | P3 | ⬜ Planned | 76, 97, 98, 103, 56 | 105.1 research provider |

<details markdown="1">
<summary>2 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 5 | [CRM / sales pipeline](#phase-5) | ✅ Complete — verify | — | 5.3 IMAP lead poller was stubbed and deferred to a 5.4 follow-up; confirm whether it now works |
| 76 | [Profitability and pricing advisor](#phase-76) | ✅ Complete | v3.17.696 | — |

</details>

### F. Security & Administration

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 51 | [Reliability and customer-boundary hardening](#phase-51) | P0\* | 🔵 In progress | — | Per-customer integration ownership (remaining part of the platform-integrations item) |
| 57 | [Technician security levels and abuse prevention](#phase-57) | — | 🔵 In progress | — | Confirm remaining items against 64 roles |
| 64 | [Roles, permission groups and access settings](#phase-64) | P0\* | 🔵 In progress | 57, 63 | 64.8 remaining enforcement call sites |
| 80 | [Agit8or Identity: single sign-on for people](#phase-80) | — | 🔵 In progress | Keycloak | 80.4 Keycloak deployment; 80.5; 80.6 |
| 94 | [Evidence integrity and routine backups](#phase-94) | P0\* | 🔵 In progress | — | External append-only audit shipping (94.1); protected-change approval for audit pruning (94.2); S3 destination (94.3) |
| 111 | [Identity lifecycle and access reviews](#phase-111) | P1 | 🔵 In progress | 57, 64, 80 | 111.1 passkeys; 111.3 one-action offboarding |

<details markdown="1">
<summary>8 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 28 | [Browser Extension + Offline Vault Access](#phase-28) | ✅ Complete | v3.17.331 | Server-side API shipped; the browser extension binary is out of scope |
| 31 | [Vault GeoIP / IP / Time Access Rules](#phase-31) | ✅ Complete | v3.17.163 | — |
| 37 | [Vault Approval & Break-Glass Workflow](#phase-37) | ✅ Complete | — | — |
| 39 | [Compliance Evidence Packs](#phase-39) | ✅ Complete | — | — |
| 41 | [Compliance Frameworks & Recertification](#phase-41) | ✅ Complete | v3.17.444 | — |
| 43 | [Multi-Organization REST API Access](#phase-43) | ✅ Complete | v3.17.496 | — |
| 49 | [Interface consistency and tenant-boundary hardening](#phase-49) | ✅ Complete | — | — |
| 81 | [API access control and network restrictions](#phase-81) | ✅ Complete | v3.17.718 | — |

</details>

### G. Customer Portal & Communications

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 66 | [Client pulse checks](#phase-66) | — | 🔵 In progress | portal, scheduler | 66.5 export and reminders |
| 77 | [Customer command center portal](#phase-77) | P3\* | ⬜ Planned | 72, 73, 74 | 77.1 unified customer dashboard |
| 99 | [Phone system integration and call-to-ticket](#phase-99) | P2 | ⬜ Planned | 64, 81, 82 | 99.1 adapter framework |
| 100 | [Optional simple PBX appliance](#phase-100) | P4 | ⏸️ Deferred | 99 | Go/no-go review after Phase 99 ships |

<details markdown="1">
<summary>3 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 12 | [Customer Communication Workflows](#phase-12) | ✅ Complete | — | — |
| 40 | [Public / Client-Facing Status Page](#phase-40) | ✅ Complete | — | — |
| 54 | [Guided customer service requests](#phase-54) | ✅ Complete | v3.17.669 | — |

</details>

### H. Reporting, Analytics & Optional AI

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 75 | [Profitability analytics, customer commercial portal, onboarding wizard and executive dashboard](#phase-75) | P3\* | 🔵 In progress | 68–74 | 75.2 customer commercial portal; 75.5 permissions |
| 78 | [Customer health score](#phase-78) | P3\* | 🔵 In progress | 66, 74, 75 | 78.6 portal display |
| 83 | [NOC/SOC wallboards and secure display pairing](#phase-83) | P3\* | ⬜ Planned | 82 | 83.1 presentation mode |
| 89 | [Security posture scorecards and customer service reviews](#phase-89) | P3\* | ⬜ Planned | 78, 82, 84 | 89.1 posture scorecard |
| 90 | [AI Operations Analyst](#phase-90) | P3\* | ⬜ Planned | 85, 56 | 90.1 alert analysis |
| 110 | [Service-delivery reporting and one set of definitions](#phase-110) | P3 | ⬜ Planned | 3, 75, 102 | 110.1 one calculation layer |

<details markdown="1">
<summary>3 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 3 | [Financial reporting + BI](#phase-3) | ✅ Complete | — | — |
| 19 | [Advanced Reporting & Analytics](#phase-19) | ✅ Complete | v3.17.326 | — |
| 26 | [Custom Report Writer + Saved Queries](#phase-26) | ✅ Complete | — | JSON and Excel export deferred; auto-chart status to confirm |

</details>

### I. Deployment, Updates & Reliability

| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |
|---|---|---|---|---|---|
| 59 | [Verified installs and upgrades](#phase-59) | — | 🔵 In progress | updater, root helper | 59.7 LTS channel |
| 67 | [Interface, navigation and dashboard redesign](#phase-67) | — | 🔵 In progress | 64 | 67.8 validation and 67.16 follow-ups |
| 96 | [First-install setup wizard and interactive onboarding](#phase-96) | P0 | 🔵 In progress | 59, 64, 67 | 96.2 first-install detection; 96.3–96.4 assistant |

<details markdown="1">
<summary>4 completed phases</summary>

| ID | Feature | Status | Released | Note |
|---|---|---|---|---|
| 42 | [First-class Docker / containerized deployment](#phase-42) | ✅ Complete | v3.17.490 | — |
| 45 | [System-wide Appearance Controls](#phase-45) | ✅ Complete | v3.17.527 | — |
| 50 | ["Help Us Grow" call to action](#phase-50) | ✅ Complete | v3.17.586 | — |
| 58 | [Condensed navigation](#phase-58) | ✅ Complete | v3.17.647 | — |

</details>

<!-- /generated:matrix -->

<a id="blockers"></a>

## Blockers & dependencies

Only blockers that stop current or next work are listed; ordinary prerequisites are in the matrix.

<!-- generated:blockers -->

| Phase | Blocker | Depends on | Decision / action needed | State |
|---|---|---|---|---|
| 33 — [Network Discovery & Auto Documentation](#phase-33) | Topology and port maps need link-layer data nothing collects | 32, 16 | Owner decision on SNMP/LLDP/CDP collection (previously declined) | 🟡 Partial |
| 59 — [Verified installs and upgrades](#phase-59) | LTS channel needs a published support policy | updater, root helper | Owner publishes a support policy | 🔵 In progress |
| 63 — [RMM integration and technician workspace](#phase-63) | 63.11–63.16 need Rem0te contract items (P2/P3, R13, P10, P6, R7/P5, P7, R2) | 52, 56, 57; Rem0te contract | Rem0te ships the items; two-application tests pass | 🔵 In progress |
| 65 — [Contract documents and digital signing](#phase-65) | Starter contract wording is sample text | 15, 64 | Legal review of the wording | 🔵 In progress |
| 71 — [Accounting sync completion](#phase-71) | Provider capabilities verified only against mocks | 44 | QuickBooks Online and Xero sandbox accounts | 🔵 In progress |
| 72 — [Payment processing and sales tax](#phase-72) | Payment providers verified only against mocks | 71 | Payment provider sandbox accounts | 🔵 In progress |
| 74 — [Backup monitoring, backup management and endpoint health](#phase-74) | 74.7 needs St0r’s integration API (in development, St0r PR #54) | 63, 82; St0r API (74.7) | St0r ships /api/v1 with scoped tokens | 🔵 In progress |
| 79 — [Agit8or Connect: secure application-to-application integration](#phase-79) | 79.6 is Rem0te work; 79.7 would duplicate Phase 63 over a second channel | Rem0te contract | Decision on one Rem0te channel; Rem0te Stage 8 | 🔵 In progress |
| 80 — [Agit8or Identity: single sign-on for people](#phase-80) | 80.4 Keycloak deployment requires approval | Keycloak | Owner approves a Keycloak deployment | 🔵 In progress |
| 100 — [Optional simple PBX appliance](#phase-100) | Exploratory; not built until Phase 99 is proven | 99 | Go decision against the recorded criteria | ⏸️ Deferred |
| 106 — [Device management (MDM) integrations](#phase-106) | Mosyle has no official API documentation found | 64, 74.9, 82, 92 | Obtain official Mosyle API documentation (other providers unaffected) | ⬜ Planned |
| 108 — [Discovery scope approval and suggested-device staging](#phase-108) | 108.4 SNMP/LLDP/CDP collection | 32, 33 | Owner decision (previously declined) | ⬜ Planned |

<!-- /generated:blockers -->

**Cross-product dependencies**

| Product | What Clientst0r needs | Where it is tracked |
|---|---|---|
| Rem0te | Contract items P2/P3, R13, P10, P6, R7/P5, P7, R2 for 63.11–63.16; per-endpoint capability flags for 63.18; signed counts for 92.4 | [Rem0te backlog](plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md) Priority 9; coordination file |
| St0r | Versioned `/api/v1` with scoped tokens (in development) for 74.7 | St0r PR #54 (`docs/ROADMAP.md` in St0r) |
| Comet Backup | Read-only administrator account; separate account for actions | [Comet API notes](plans/backup-integrations/COMET_API_NOTES.md) |
| MDM providers | Per-provider credentials and consent; Mosyle documentation | [MDM specification](plans/mdm/README.md) |
| Accounting and payment providers | Sandbox accounts for verification (71.11, 72) | Phases 71, 72 |

<a id="completed"></a>

## Completed features

Each workstream in the [feature matrix](#feature-matrix) lists its completed phases in a collapsed table. The full
original descriptions, sub-items and release versions of completed phases are in
[ROADMAP_HISTORY.md](ROADMAP_HISTORY.md); release notes are in the [changelog](../CHANGELOG.md).

<a id="verify"></a>

**Statuses to verify** — completed phases whose wording and the code may disagree:

<!-- generated:verify -->

| Phase | What to verify |
|---|---|
| 5 — [CRM / sales pipeline](#phase-5) | 5.3 IMAP lead poller was stubbed and deferred to a 5.4 follow-up; confirm whether it now works |
| 36 — [Agreement Reconciliation & Pre-Invoice Approval](#phase-36) | Agreement profitability reports and revenue-leakage expansion have no shipped marker (audit 2026-11-20) |
| 57 — [Technician security levels and abuse prevention](#phase-57) | Confirm remaining items against 64 roles |

<!-- /generated:verify -->

<a id="later"></a>

## Future roadmap — LATER

Planned and partly built phases not in NOW or NEXT, by workstream:

<!-- generated:later -->

- **A. Core PSA & Ticketing:** 93 [Business-hours SLA calendars](#phase-93) (—)
- **B. Billing & Financial Management:** 65 [Contract documents and digital signing](#phase-65) (—), 68 [Commercial price book and service plans](#phase-68) (—), 69 [Labor rate cards and cost rates](#phase-69) (—), 71 [Accounting sync completion](#phase-71) (—), 72 [Payment processing and sales tax](#phase-72) (—), 92 [Verified usage and recurring billing](#phase-92) (—), 104 [Customer approvals, deposits, change orders and portal billing](#phase-104) (P1)
- **C. Asset Management & Documentation:** 33 [Network Discovery & Auto Documentation](#phase-33) (—), 62 [Pluggable document editors](#phase-62) (—), 73 [Procurement, distributors, licensing and warranty lifecycle](#phase-73) (—), 95 [PSA migration importers](#phase-95) (—), 107 [Documentation search, attachments, sharing and asset history](#phase-107) (P3), 108 [Discovery scope approval and suggested-device staging](#phase-108) (P3)
- **D. RMM & Platform Integrations:** 56 [Ticket AI Assist and RMM handoff](#phase-56) (—), 82 [Shared operational event and alert foundation](#phase-82) (—), 84 [Security connector framework and vendor integrations](#phase-84) (P3\*), 85 [Operations Center, alert triage and correlation](#phase-85) (P3\*), 86 [SOAR Lite: approval-driven security automation](#phase-86) (P3\*), 87 [Alert routing, on-call and escalation](#phase-87) (P3\*), 88 [Service dependency and impact mapping](#phase-88) (P3\*), 109 [Microsoft 365 administration](#phase-109) (P3)
- **E. Sales & CRM:** 97 [Prospect IT assessment and CRM enhancements](#phase-97) (P1), 98 [Service estimator and forecast accuracy](#phase-98) (P1), 103 [Quote builder, options and price-book selection](#phase-103) (P1), 105 [Market pricing research and AI proposals](#phase-105) (P3)
- **F. Security & Administration:** 57 [Technician security levels and abuse prevention](#phase-57) (—), 64 [Roles, permission groups and access settings](#phase-64) (P0\*), 80 [Agit8or Identity: single sign-on for people](#phase-80) (—)
- **G. Customer Portal & Communications:** 66 [Client pulse checks](#phase-66) (—), 77 [Customer command center portal](#phase-77) (P3\*), 99 [Phone system integration and call-to-ticket](#phase-99) (P2), 100 [Optional simple PBX appliance](#phase-100) (P4)
- **H. Reporting, Analytics & Optional AI:** 75 [Profitability analytics, customer commercial portal, onboarding wizard and executive dashboard](#phase-75) (P3\*), 78 [Customer health score](#phase-78) (P3\*), 83 [NOC/SOC wallboards and secure display pairing](#phase-83) (P3\*), 89 [Security posture scorecards and customer service reviews](#phase-89) (P3\*), 90 [AI Operations Analyst](#phase-90) (P3\*), 110 [Service-delivery reporting and one set of definitions](#phase-110) (P3)
- **I. Deployment, Updates & Reliability:** 59 [Verified installs and upgrades](#phase-59) (—), 67 [Interface, navigation and dashboard redesign](#phase-67) (—), 96 [First-install setup wizard and interactive onboarding](#phase-96) (P0)

<!-- /generated:later -->

**Stages**

<!-- generated:stages -->

| Stage | Content | Priority | Phases |
|---|---|---|---|
| 1 | Core completion: PSA/RMM workflow, quote conversion, billing correctness, security, ticket workflow, setup | P0 | [51](#phase-51), [52](#phase-52), [63](#phase-63), [64](#phase-64), [70](#phase-70), [91](#phase-91), [94](#phase-94), [96](#phase-96), [101](#phase-101), [102](#phase-102), [111](#phase-111) |
| 2 | Backup management: St0r/UrBackup, Comet, one overview, alerts, reports, billing | P1 | [74](#phase-74) |
| 3 | Device management: MDM, compliance, Linux/macOS visibility, one device record | P2 | [106](#phase-106) |
| 4 | Sales and documentation: CRM discovery, estimator, quotes, documentation, discovery staging | P3 | [97](#phase-97), [98](#phase-98), [103](#phase-103), [104](#phase-104), [107](#phase-107), [108](#phase-108) |
| 5 | Reporting and customer portal | P3 | [75](#phase-75), [77](#phase-77), [78](#phase-78), [89](#phase-89), [110](#phase-110) |
| 6 | Advanced integrations and optional AI | P3 | [83](#phase-83), [84](#phase-84), [85](#phase-85), [86](#phase-86), [87](#phase-87), [88](#phase-88), [90](#phase-90), [99](#phase-99), [105](#phase-105), [109](#phase-109) |
| 7 | Polish, regression coverage, documentation, completion checklist | — | [59](#phase-59), [67](#phase-67) |
| 8 | Rem0te functional expansion (separate backlog) | after Stage 7 | [Rem0te backlog](plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md) |

<!-- /generated:stages -->

<a id="before-rem0te"></a>

**Before Rem0te expansion resumes** — the Clientst0r completion checklist
([full text](plans/platform-program/README.md#clientst0r-completion-checklist-stage-7-exit)):

1. The platform workflows run end to end on a test install with both applications' real code, each with an
   automated test.
2. Every P0 and P1 item is complete or explicitly deferred by the owner.
3. No open security-review finding rated Medium or above.
4. Every listed integration is verified against the real service or labelled by its actual level.
5. Billing acceptance tests pass, with one set of financial definitions.
6. A fresh install reaches a secured state through the setup wizard; upgrades keep all data.
7. The pinned Rem0te contract matches Rem0te's release and the cross-application suite passes.
8. Documentation describes only what items 1–7 verified.

**Out of scope**

- Multi-currency beyond per-record `currency` field
- Multi-language support beyond Django i18n hooks
- ~~Native mobile apps (PWA only — per memory)~~ → **moved into Phase 8**
- Marketplace/app store
- White-label tenant branding beyond per-org logo
- An endpoint agent or remote-access relay inside Clientst0r — RMM functions come from Rem0te (a separate
  application) or a supported third-party RMM.
- A backup engine or an MDM server inside Clientst0r — backup and MDM come from the providers it integrates.

<a id="technical-details"></a>

## Technical details

One section per phase, in numeric order. Open phases keep their full detail (expand *Details*); completed phases
link to [ROADMAP_HISTORY.md](ROADMAP_HISTORY.md).

<a id="phase-1"></a>

## Phase 1 — Contract / agreement engine deepening **(M · foundation)** [complete]
<!-- phase: ws=B -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** B. Billing & Financial Management

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 1](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-1).

---

<a id="phase-2"></a>

## Phase 2 — Resource management foundation **(M · foundation)** [complete]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 2](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-2).

---

<a id="phase-3"></a>

## Phase 3 — Financial reporting + BI **(L · keystone)** [complete]
<!-- phase: ws=H -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** H. Reporting, Analytics & Optional AI

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 3](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-3).

---

<a id="phase-4"></a>

## Phase 4 — Procurement workflow **(L)** **— shipped**
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 4](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-4).

---

<a id="phase-5"></a>

## Phase 5 — CRM / sales pipeline **(L)** **— complete**
<!-- phase: ws=E state=verify note="5.3 IMAP lead poller was stubbed and deferred to a 5.4 follow-up; confirm whether it now works" -->
**Status:** ✅ Complete — verify · **Priority:** — · **Workstream:** E. Sales & CRM  
**Note:** 5.3 IMAP lead poller was stubbed and deferred to a 5.4 follow-up; confirm whether it now works

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 5](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-5).

---

<a id="phase-6"></a>

## Phase 6 — ITIL maturity **— complete**
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 6](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-6).

---

<a id="phase-7"></a>

## Phase 7 — Outsourcing, integrations, polish **(continuous track)** [complete]
<!-- phase: ws=D -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** D. RMM & Platform Integrations

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 7](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-7).

---

<a id="phase-8"></a>

## Phase 8 — Native mobile apps (iOS + Android) with GPS auto-time + Timeclock **(L · keystone)** [shipped — v3.17.417]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 8](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-8).

---

<a id="phase-9"></a>

## Phase 9 — Security alert ingestion: EDR / AV / Firewall on the dashboard **(M)** [in progress]
<!-- phase: ws=D state=partial next="Real vendor API connectors (Phase 84); today every vendor is webhook-only" -->
**Status:** 🟡 Partial · **Priority:** — · **Workstream:** D. RMM & Platform Integrations  
**Next:** Real vendor API connectors (Phase 84); today every vendor is webhook-only

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

> Header changed from *shipped — v3.17.168* to *in progress* on 2026-11-20: what shipped in v3.17.168 stays below; the phase is not finished (see the status line).

MSPs run a stack of security tools that all alert independently — SentinelOne, CrowdStrike, Defender, Sophos, Bitdefender, Webroot, Fortinet, Palo Alto, Sonicwall, etc. The PSA dashboard should aggregate alerts from all of them, surface critical issues per client, and let techs triage from one screen.

### Sub-phase 9.1 — Connection framework *(shipped v3.17.168)*

- Generic `SecurityVendorConnection` model: provider type (edr/av/firewall), org-scoped credentials (encrypted), poll interval, last_sync_at, last_error
- Provider type enums covering EDR (CrowdStrike Falcon, SentinelOne Singularity, Microsoft Defender for Endpoint, Sophos Central, Huntress, ThreatLocker), AV (Bitdefender GravityZone, Webroot, Malwarebytes, ESET), Firewall (Fortinet FortiGate, Palo Alto, Sonicwall, Cisco Meraki MX, Sophos XG, pfSense)
- Two-way mapping: each connection optionally pinned to a client `Organization` (multi-tenant alert routing)
- Reuses existing integration patterns (status pill from v3.17.135)

### Sub-phase 9.2 — Alert model + poller *(shipped v3.17.168)*

- `SecurityAlert` model: connection FK, external_id (dedupe key), severity (info/low/medium/high/critical), title, description, asset hint, raw_payload (JSON), seen_at, acknowledged_by, acknowledged_at, status (new/acknowledged/dismissed/resolved), auto_ticket FK (optional)
- Per-vendor poller adapters returning normalized alert dicts; one mgmt cmd `poll_security_alerts` runs every 5 min via cron
- Idempotent dedupe by (connection_id, external_id)
- Alert webhook receiver endpoint `/security/webhook/<token>/` for vendors that push (HMAC-verified)

### Sub-phase 9.3 — Dashboard + auto-ticketing *(shipped v3.17.168)*

- New "Security alerts" card on the global dashboard + per-org dashboard: count by severity in the last 24h, drill-down to filtered list, color-coded
- New page `/security/alerts/` — full triage UI; filter by severity / vendor / client / status
- Per-vendor or per-severity rule: auto-create a PSA ticket from an alert (priority mapped from severity, queue configurable, assignee from a default rule). Mirrors workflow rules engine (v3.17.111).
- Bulk "ack / dismiss / convert to ticket" actions

### Sub-phase 9.4 — Reporting *(shipped v3.17.168)*

- "Mean time to acknowledge" metric per client / per vendor
- Suppression rules (don't auto-ticket from this vendor between 22:00–06:00 etc.)
- Weekly digest email to client of unresolved alerts (opt-in) *(shipped v3.17.664)* — `security_alerts.SecurityDigestSubscription` holds a per-contact opt-in per customer (off by default). Portal users switch it on or off in portal preferences; staff add customer contacts and switch them at `/security/digest/`, with a preview of this week's digest. `send_security_digests` runs weekly from the in-app scheduler, mails only customers with unresolved (new / acknowledged) alerts, and lists severity, title, device, first-seen date and open / being-investigated only — no description, vendor payload, connection, rule, ticket or acknowledger. Each digest carries a signed unsubscribe link (GET confirms, POST unsubscribes, RFC 8058 one-click supported) that works without signing in; a contact mailed in the last six days is skipped. Optional per-customer "all clear" e-mail *(shipped v3.17.664)*: off by default; when switched on at `/security/digest/`, opted-in contacts get a short "no unresolved alerts" note in weeks with nothing open

> **Status note (audit 2026-11-20):** ingestion, normalization and the dashboard shipped as described, but
> no vendor has a working API connector: every vendor listed above reaches Clientst0r as a signed or token
> webhook only, and the product labels them that way since v3.17.723. Real vendor connectors are Phase 84.

**Sizing:** **M** — 9.1+9.2 = 2 weeks (one reference adapter + the framework), 9.3 = 2 weeks, 9.4 = 1 week. Each new vendor adapter beyond the first is ~2-4 days. Ship the framework + 1-2 reference adapters first, then add vendors as customer demand arrives.

**Dependencies:** none. Can run alongside Phase 2 / 3 / 8.

</details>

---

<a id="phase-10"></a>

## Phase 10 — Advanced Email-to-Ticket Engine **(M)** [complete]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 10](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-10).

---

<a id="phase-11"></a>

## Phase 11 — Advanced Dispatch & Technician Scheduling **(M)** [complete]
<!-- phase: ws=A note="Geo-aware routing and travel time deferred (needs Phase 8 GPS data)" -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing  
**Note:** Geo-aware routing and travel time deferred (needs Phase 8 GPS data)

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 11](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-11).

---

<a id="phase-12"></a>

## Phase 12 — Customer Communication Workflows **(M)** [complete]
<!-- phase: ws=G -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** G. Customer Portal & Communications

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 12](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-12).

---

<a id="phase-13"></a>

## Phase 13 — Procurement & Lifecycle Management **(M)** [shipped — v3.17.272]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 13](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-13).

---

<a id="phase-14"></a>

## Phase 14 — Visual Workflow Automation Engine **(L)** [in progress]
<!-- phase: ws=A state=partial next="Time-based triggers, delays and escalation logic (91.6)" -->
**Status:** 🟡 Partial · **Priority:** — · **Workstream:** A. Core PSA & Ticketing  
**Next:** Time-based triggers, delays and escalation logic (91.6)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

> Header changed from *shipped — v3.17.290* to *in progress* on 2026-11-20: what shipped in v3.17.290 stays below; the phase is not finished (see the status line).

**Roadmap item:** Visual Workflow & Operational Automation Engine. Extends the workflow rules engine (v3.17.111) + visual rule builder (v3.17.112).

Planned capabilities:
- Visual workflow builder *(partial — visual rule builder shipped v3.17.112)* *(shipped v3.17.664: the builder edits both branches of a rule (then / otherwise), chains rules with "Run another rule" steps and sets the once-per-ticket guard; a flow view per rule and a flow map of every rule draw trigger → condition → branches with chained rules inline; definitions are checked before saving (action types, required settings, missing chained rules, loops) and the engine refuses chain loops at run time; raw JSON editing stays available and the stored shape is unchanged)*
- Conditional workflow routing (branching based on ticket fields) *(shipped v3.17.285 — `WorkflowRule.else_actions` JSONField runs when `conditions` evaluate false; engine picks branch and counts both as fires)*
- SLA-driven automation *(shipped v3.17.286 — `sla_threshold_crossed` trigger + `sla_pct_at_least` condition + `WorkflowRule.fire_once_per_ticket` guard via `WorkflowRuleFiring` join table; `psa_sla_workflow_tick` cron evaluates open tickets every 5 min)*
- Ticket orchestration (multi-step automated sequences) *(shipped v3.17.285 — new `fire_rule` action type chains by name within the same org / MSP-wide scope; sub-rule's else_actions also honored)*
- Approval chains (extends Phase 6.1 CAB pattern)
- Trigger / action workflows
- Escalation logic (auto-escalate after N hours unanswered)
- Scheduled automations
- State-based workflows *(shipped — already covered by `status_changed` trigger + `status` condition; v3.17.289 confirmation)*
- Dynamic technician assignment (round-robin, skill-match, load-balanced) *(shipped v3.17.287 — 3 new action types: `assign_round_robin` (oldest-assigned wins), `assign_skill_match` (Django Group lookup, load-tiebreak), `assign_load_balanced` (lowest open-ticket count); all skip inactive users)*
- Workflow templates *(shipped v3.17.288 — `WorkflowRuleTemplate` model + `instantiate(organization, name_override)` clone method; UI at `/psa/rules/templates/` with per-template "Use Template" button)*
- Cross-module workflow integration (PSA ↔ procurement ↔ CRM) *(shipped v3.17.289 — `create_charge` action type lets workflow rules add billing rows; future actions for procurement/CRM cross-module land as the need arises)*
- AI-assisted workflow suggestions (**OPTIONAL AI**) *(shipped v3.17.290 — `WorkflowSuggestion` model + `psa_generate_workflow_suggestions` heuristic command (LLM-swap-in later) gated by `psa_ai_enabled`; review/accept/dismiss UI at `/psa/rules/suggestions/`)*

**Goal:** Reduce repetitive operational tasks while improving workflow consistency.

</details>

---

<a id="phase-15"></a>

## Phase 15 — Recurring Billing & Contract Management **(M)** [shipped — v3.17.299]
<!-- phase: ws=B -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** B. Billing & Financial Management

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 15](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-15).

---

<a id="phase-16"></a>

## Phase 16 — Documentation Relationship Mapping **(M)** [shipped — v3.17.303]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 16](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-16).

---

<a id="phase-17"></a>

## Phase 17 — Advanced Asset Intelligence **(L)** [shipped — v3.17.310]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 17](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-17).

---

<a id="phase-18"></a>

## Phase 18 — Multi-Location Client Hierarchy **(M)** [shipped — v3.17.283]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 18](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-18).

---

<a id="phase-19"></a>

## Phase 19 — Advanced Reporting & Analytics **(continuous)** [shipped — v3.17.326]
<!-- phase: ws=H -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** H. Reporting, Analytics & Optional AI

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 19](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-19).

---

<a id="phase-20"></a>

## Phase 20 — Approval & Change Management Workflows **(M)** [shipped — v3.17.277]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 20](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-20).

---

<a id="phase-21"></a>

## Phase 21 — Advanced Mobile Technician Workflows **(L)** [shipped — v3.17.318]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 21](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-21).

---

<a id="phase-22"></a>

## Phase 22 — Knowledge Base & SOP Management **(M)** [complete]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 22](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-22).

---

<a id="phase-23"></a>

## Phase 23 — Security Event & Incident Workflows **(L)** [in progress]
<!-- phase: ws=D state=partial next="Approval-driven security automation (Phase 86); playbooks run only after approval since v3.17.737" -->
**Status:** 🟡 Partial · **Priority:** — · **Workstream:** D. RMM & Platform Integrations  
**Next:** Approval-driven security automation (Phase 86); playbooks run only after approval since v3.17.737

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

> Header changed from *shipped — v3.17.363* to *in progress* on 2026-11-20: what shipped in v3.17.363 stays below; the phase is not finished (see the status line).

**Roadmap item:** Security Event Correlation & Incident Operations. Extends Phase 9 (security alert ingestion) — these are the next-tier incident workflows on top of the basic alert dashboard.

Planned capabilities:
- Security event ingestion *(shipped v3.17.168 via Phase 9.1+9.2 — SecurityVendorConnection + SecurityAlert + pollers + webhook)*
- SIEM integrations *(shipped v3.17.337 — generic CEF/JSON/Syslog inbound endpoint with HMAC auth at /security/siem/webhook/)*
- Vulnerability correlation (CVE → affected assets → exposure) *(shipped v3.17.306–307 via Phase 17 v6+v8 — Vulnerability + affected_assets + ticket linking)*
- CVE-to-ticket workflows *(shipped v3.17.307 via Phase 17 v8 — vuln-to-ticket linking)*
- Security incident timelines *(shipped v3.17.338 — SecurityIncident + SecurityIncidentEvent + auto-correlation by asset+severity window + `/security/incidents/`)*
- Exposure scoring *(shipped v3.17.339 — Organization.exposure_score cached + `recompute_exposure_scores` mgmt cmd + org-detail badge)*
- Incident SLA tracking *(shipped v3.17.355 — SecurityIncidentSLAPolicy + `check_incident_sla_breaches` mgmt cmd + idempotent timeline events)*
- Automated remediation workflows *(shipped v3.17.358 — RemediationPlaybook + RemediationPlaybookStep engine; auto-fires on incident open; step types create_ticket / send_email / quarantine_asset_flag / run_workflow_rule)*
- Security dashboarding *(shipped v3.17.168 via Phase 9.3 — `/security/alerts/`)*
- Threat visibility *(shipped v3.17.361 — `/security/threat-overview/` single-pane dashboard with severity rollups, top-exposed orgs, playbook activity, week-over-week trend)*
- Security event reporting *(shipped v3.17.168 via Phase 9.4 — MTTA + suppression + digest framework)*
- AI-assisted incident summarization (**OPTIONAL AI**) *(shipped v3.17.362 — gated by `psa_ai_enabled`; pluggable provider; POST `/security/incidents/<id>/ai-summarize/` writes summary as timeline note)*

Potential integrations:
- Huntress
- SentinelOne
- CrowdStrike
- Microsoft security ecosystem (Defender, Sentinel)
- Sophos
- Other security platforms

**Goal:** Improve operational security visibility and incident response workflows.
> **Status note (audit 2026-11-20, SR-37):** remediation playbooks run automatically when an incident opens,
> with no approval step; the `run_workflow_rule` step reports success without running anything and looks up
> the rule without a customer check. Fix planned in 51.20 (approval or off by default, real-or-removed step,
> customer check); approval-driven playbooks are Phase 86.

</details>

---

<a id="phase-25"></a>

## Phase 25 — Mature Timesheet Approval Workflows **(M)** [complete]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 25](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-25).

---

<a id="phase-26"></a>

## Phase 26 — Custom Report Writer + Saved Queries **(L)** [complete]
<!-- phase: ws=H note="JSON and Excel export deferred; auto-chart status to confirm" -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** H. Reporting, Analytics & Optional AI  
**Note:** JSON and Excel export deferred; auto-chart status to confirm

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 26](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-26).

---

<a id="phase-27"></a>

## Phase 27 — Advanced Accounting Reconciliation **(M)** [shipped — v3.17.281]
<!-- phase: ws=B -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** B. Billing & Financial Management

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 27](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-27).

---

<a id="phase-28"></a>

## Phase 28 — Browser Extension + Offline Vault Access **(L)** [shipped — v3.17.331 — server-side API; extension binary out of scope]
<!-- phase: ws=F note="Server-side API shipped; the browser extension binary is out of scope" -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration  
**Note:** Server-side API shipped; the browser extension binary is out of scope

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 28](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-28).

---

<a id="phase-31"></a>

## Phase 31 — Vault GeoIP / IP / Time Access Rules **(S)** [shipped — v3.17.163]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 31](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-31).

---

<a id="phase-32"></a>

## Phase 32 — Remote Network Discovery Import **(M · future / late-stage)** [complete]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 32](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-32).

---

<a id="phase-33"></a>

## Phase 33 — Network Discovery & Auto Documentation **(L)** [in progress]
<!-- phase: ws=C state=partial view=later deps="32, 16" next="Decide SNMP/LLDP/CDP (108.4); label topology pages meanwhile" blocker="Topology and port maps need link-layer data nothing collects" unblock="Owner decision on SNMP/LLDP/CDP collection (previously declined)" -->
**Status:** 🟡 Partial · **Priority:** — · **Workstream:** C. Asset Management & Documentation · **Depends on:** 32, 16  
**Next:** Decide SNMP/LLDP/CDP (108.4); label topology pages meanwhile  
**Blocked:** Topology and port maps need link-layer data nothing collects — *unblocks when:* Owner decision on SNMP/LLDP/CDP collection (previously declined)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Multi-protocol persistent network discovery and topology inference. Phase 32 ships a one-shot, scoped, single-use ping / ARP script — useful for the first walk-through of a new client. Phase 33 is the always-on companion: a lightweight per-site collector that sweeps ICMP / ARP on a schedule, keeps the asset inventory current, and generates topology diagrams without manual draw-time.

Planned capabilities:
- **Lightweight site collector / agent** — one per client site, packaged as a small container or systemd unit. Pulls config from server, pushes results back. No persistent admin credentials embedded; uses a per-site rotating token similar to Phase 32's scheme.
- ICMP and ARP discovery *(SNMP / LLDP / CDP collection is not in scope — stubs removed v3.17.594)*
- Automatic device inventory import *(extends the single-shot Phase 32 import flow)*
- Auto-generated topology maps *(extends Phase 16 Documentation Relationship Mapping with a dedicated network-layer view)*
- Device relationship mapping (which switches connect which APs / endpoints)
- Switch port / MAC / IP correlation table (resolve "which port is this device on" per VLAN)
- Manual and scheduled scans (cron-driven background jobs; on-demand trigger from the UI)
- Per-client and per-location discovery keys (rotation + revocation, audit log)

Dependencies: Phase 32 (token + import models — extend rather than replace), Phase 16 (relationship graph rendering), Asset model.

**Goal:** Reduce manual network documentation work — keep the topology, switch port assignments, and device inventory in sync with reality without a tech having to redraw or re-export anything.

✅ **Phase 33 complete at v3.17.557.** Built on Phase 32's models rather than replacing them, as the dependency note asked.

- **`DiscoverySite`** — a per-site collector with a rotating, revocable key. It is a standing credential, which Phase 32's token deliberately is not, and the boundary that makes that acceptable is enforced and tested: it reads **only its own scan settings** (no assets, no credentials, no other site) and writes **only** discovery results into one organization and one location.
- **`NetworkLink`** — LLDP/CDP adjacencies, idempotent on re-report. A neighbour we do not manage is kept as an unresolved node rather than dropped, because "there is something on port 12 we don't manage" is exactly what a topology map should show. A link not seen for a month is flagged stale rather than deleted.
- **`SwitchPortEntry`** — the port / VLAN / MAC / IP correlation table that answers "which port is this device on". One row per (port, VLAN, MAC), so an uplink carrying many MACs is a fact to display rather than a conflict to resolve.
- **Topology map** — force-directed SVG rendered from a seeded layout, so the same network draws the same way twice.
- **Scheduled and on-demand scans** — cadence lives on the site; "scan now" is a flag the collector picks up on its next check-in, because it polls and we never connect inbound to a client network.

**Scope note, stated plainly:** the server side is complete and tested (112 tests). `deploy/network-collector/collector.py` is a reference implementation that ping-sweeps and reads ARP with only the standard library. It does not collect SNMP, LLDP or CDP data; the unused SNMP stubs and per-site SNMP settings were removed in v3.17.594. The topology and port-map views show whatever neighbour and port records the results endpoint receives.
> **Status note (audit 2026-11-20):** server side complete (scan jobs, import, review, asset creation). The
> topology map and port map need LLDP/CDP/bridge-table data that nothing produces: the collector sends ICMP
> and ARP results only, and `classify_enabled` is not honoured. SNMP/LLDP/CDP collection is **blocked**
> pending an owner decision (an SNMP collector was previously declined). Discovery scope approval and
> staging are Phase 108.

</details>

---

<a id="phase-34"></a>

## Phase 34 — Network Configuration Backup **(M)** [complete]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 34](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-34).

---

<a id="phase-35"></a>

## Phase 35 — Advanced Project Management **(L)** [complete]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 35](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-35).

---

<a id="phase-36"></a>

## Phase 36 — Agreement Reconciliation & Pre-Invoice Approval **(M)** [complete]
<!-- phase: ws=B state=verify note="Agreement profitability reports and revenue-leakage expansion have no shipped marker (audit 2026-11-20)" -->
**Status:** ✅ Complete — verify · **Priority:** — · **Workstream:** B. Billing & Financial Management  
**Note:** Agreement profitability reports and revenue-leakage expansion have no shipped marker (audit 2026-11-20)

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 36](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-36).

---

<a id="phase-37"></a>

## Phase 37 — Vault Approval & Break-Glass Workflow **(M)** [complete]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 37](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-37).

---

<a id="phase-38"></a>

## Phase 38 — Client Onboarding / Offboarding Runbooks **(M)** [complete]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 38](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-38).

---

<a id="phase-39"></a>

## Phase 39 — Compliance Evidence Packs **(M)** [complete]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 39](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-39).

---

<a id="phase-40"></a>

## Phase 40 — Public / Client-Facing Status Page **(M)** [complete]
<!-- phase: ws=G -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** G. Customer Portal & Communications

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 40](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-40).

---

<a id="phase-41"></a>

## Phase 41 — Compliance Frameworks & Recertification **(M)** [shipped — v3.17.444]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 41](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-41).

---

<a id="phase-42"></a>

## Phase 42 — First-class Docker / containerized deployment **(S · packaging)** [shipped — v3.17.490]
<!-- phase: ws=I -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** I. Deployment, Updates & Reliability

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 42](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-42).

---

<a id="phase-43"></a>

## Phase 43 — Multi-Organization REST API Access **(S · integrations)** [shipped — v3.17.496]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 43](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-43).

---

<a id="phase-44"></a>

## Phase 44 — Full Two-Way Accounting Sync **(L)** [shipped — v3.17.531]
<!-- phase: ws=B -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** B. Billing & Financial Management

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 44](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-44).

---

<a id="phase-45"></a>

## Phase 45 — System-wide Appearance Controls **(S)** [shipped — v3.17.527]
<!-- phase: ws=I -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** I. Deployment, Updates & Reliability

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 45](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-45).

---

<a id="phase-46"></a>

## Phase 46 — Job Kit: tools and materials on a ticket **(M)** [shipped — v3.17.533]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 46](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-46).

---

<a id="phase-47"></a>

## Phase 47 — Public scheduler wallboard **(S)** [shipped — v3.17.533]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 47](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-47).

---

<a id="phase-48"></a>

## Phase 48 — Task warning windows **(S)** [shipped — v3.17.535]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 48](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-48).

---

<a id="phase-49"></a>

## Phase 49 — Interface consistency and tenant-boundary hardening **(M · quality)** [complete]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 49](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-49).

---

<a id="phase-50"></a>

## Phase 50 — "Help Us Grow" call to action **(S · growth)** [shipped — v3.17.586]
<!-- phase: ws=I -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** I. Deployment, Updates & Reliability

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 50](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-50).

---

<a id="phase-51"></a>

## Phase 51 — Reliability and customer-boundary hardening **(M · quality)** [in progress]
<!-- phase: ws=F stage=1 view=now order=2 deps="—" next="Per-customer integration ownership (remaining part of the platform-integrations item)" -->
**Status:** 🔵 In progress · **Priority:** P0\* · **Workstream:** F. Security & Administration · **Depends on:** —  
**Next:** Per-customer integration ownership (remaining part of the platform-integrations item)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

A code audit in October 2026 found work that the product described as finished
but that did not hold up in use: periodic jobs that nothing ran, edit forms that
let a customer's own users reach other customers' records, and role switches
that were stored but never checked. This phase fixes those before new features
are built on top of them.

- **Customer boundaries on PSA forms** *(shipped v3.17.599)* — customer users
  can no longer open, edit or create contracts, invoices, projects, quotes,
  recurring schedules, requisitions, purchase orders, email configs or canned
  replies for a customer they don't belong to, by URL or by form field. The
  client account, charge and portal-invite pages are scoped the same way. MSP
  staff still work across every customer.
- **Shared templates and roles** *(shipped v3.17.599)* — only MSP staff can edit
  or delete global document templates; role assignment accepts only system
  roles or the customer's own custom roles.
- **Access ends with the account** *(shipped v3.17.599)* — API keys and browser
  extension tokens stop working when their user is deactivated, a customer
  user's key stops working when they leave that customer, and an extension
  token pinned to a customer can't be pointed at another one.
- **Every periodic job runs from the scheduler** *(shipped v3.17.599)* —
  recurring invoices, SLA workflow ticks, KB review reminders, approval
  escalation and more than twenty other jobs that no timer or cron entry ran
  are now scheduler tasks, visible with their last result on Settings →
  Scheduler. The crontab lines older updates added are removed. Scheduled
  invoicing bills only the current period: a contract more than one period
  behind is reported, never back-billed. Late fees are scheduled but off by
  default.
- **Role view permissions enforced** *(shipped v3.17.600)* — `vault_view`,
  `docs_view` and `assets_view` are checked on every page, in search, the REST
  and GraphQL APIs, the mobile API and the browser extension; the ticket
  sidebar's credential card follows the same rule. `files_view`,
  `monitoring_view` and `integrations_view` are enforced the same way on
  `/files/`, `/monitoring/` and `/integrations/`, in search, dashboards,
  GraphQL, the mobile API and the navbar; upgrading switches the monitoring
  and integrations flags on for every existing role so nobody loses access
  *(shipped v3.17.664)*. `files_upload`
  and `files_delete` are checked on photo/attachment upload and delete (web
  and mobile), vehicle photo lists follow `files_view`, and RMM data on asset
  and ticket pages follows `integrations_view` (or RMM device access);
  upgrading switches upload and delete on for every role that has `files_view`
  *(shipped v3.17.664)*.
- **Protected file downloads** *(shipped v3.17.600)* — every uploaded file is
  served through an authenticated view that checks the record it belongs to,
  so native installs can download attachments and Docker installs no longer
  serve uploads publicly.
- **Import correctness** *(shipped v3.17.603)* — imports land in the right
  customer, report real outcomes, never write during dry runs, roll back
  safely and don't duplicate CSV rows on re-run.
- **Secrets encrypted at rest, key rotation** *(shipped v3.17.607)* — every
  stored secret encrypted or hashed, forms never echo secrets,
  `rotate_encryption_key` and `check_secrets_storage` commands.
- **LDAP / Active Directory sign-in** *(shipped v3.17.608)* — optional, with
  test connection, required and staff groups; mapping directory groups to
  customer memberships, applied at sign-in and re-checked by a throttled
  background sync (removal without signing in again, sessions trimmed, skips
  and reports when the directory is unreachable) *(shipped v3.17.664)*.
- **Website-down alerts, complete webhook events, receipt AI gate**
  *(shipped v3.17.609)*; ticket, contact and invoice webhook events
  (`ticket.created` / `ticket.updated` / `ticket.status_changed`,
  `contact.created` / `contact.updated`, `invoice.created` (issued) /
  `invoice.updated` / `invoice.status_changed`) use the same signing and
  delivery, send metadata only (no descriptions, comments or line items) and
  go only to the record's own customer; tickets only when shared with the
  customer, invoices only once issued *(shipped v3.17.664)*.
- **Monitoring docs match the product** *(shipped v3.17.616)* — the
  monitoring guide and help page rewritten from the code; the Monitor Uptime
  report computes uptime from check history.
- **Scheduled WAN connection checks with alerts** *(shipped v3.17.617)* — each
  monitored WAN is pinged at its own interval; down after 2 failed checks in a
  row and recovery send one email each and `wan.down` / `wan.up` webhooks
  (`wan.check_failed` per failure); check history and 30-day uptime; WANs set
  Inactive, Planned or Under Maintenance are paused; `ping` added to the
  Docker image.
- **Drafts for editors only** *(shipped v3.17.620)* — drafts and documents
  pending review open (web page, export, versions, GraphQL) only for users who
  can edit or publish them; GraphQL `createDocument` saves a draft without the
  publish permission.
- **Internal approvals staff only** *(shipped v3.17.627)* — `/psa/approvals/`
  (list, decide, history) is MSP staff only; customer sign-offs are decided
  only by the customer in the portal.
- **Global KB staff only** *(shipped v3.17.625)* — `/psa/kb/` and the global
  KB edit, move and category permissions limited to MSP staff; drafts listed
  only for KB editors.
- **CRM and Security Alerts staff only** *(shipped v3.17.619)* — `/crm/` and
  `/security/` are MSP staff only (lead capture and vendor/SIEM webhooks
  unaffected); Security Alerts scopes staff by global role; CRM activity
  logging scoped to the current organization.
- **API key permission levels and reports access** *(shipped v3.17.618)* —
  an API key's Read-Only / Editor / Admin / Owner level is enforced (it was
  stored but never checked); REST writes check the create, edit, delete and
  publish permissions; `/reports/` is MSP staff only; report template and
  scheduled-report pages work; scheduled reports use the SMTP settings; API,
  GraphQL and reports guides rewritten from the code.
- **Live security settings and Content-Security-Policy** *(shipped
  v3.17.610)* — saved Security settings apply (environment overrides win); CSP
  with nonces in report-only mode. Inline event handlers removed and blocked
  by `script-src-attr 'none'` *(shipped v3.17.614)*; inline styles remain
  allowed.
- **Accurate documentation and capability labels** *(shipped v3.17.611)* —
  README, FEATURES, SECURITY and guides corrected; screenshot gallery
  recaptured.
- **Tokens, share links and 2FA keys protected at rest** *(shipped v3.17.612)*
  — per-device hashed mobile sign-in tokens with sign-out-everywhere, hashed or
  encrypted share links, encrypted authenticator seeds and hashed backup codes,
  license keys behind the reveal gate, partner secret removed from ticket-share
  requests.
- **Dispatch and assignment limited to MSP technicians** *(shipped v3.17.613)*
  — board rows, heatmap, suggestions and every assignee picker list
  technicians only; leftover assignments to non-technicians are flagged; the
  server rejects non-technician assignees on web and mobile.
- **Staff technicians as first-class users** *(shipped v3.17.602)* — Staff
  user-type techs are assignable on any customer's work, and their global role
  applies to membership-checked permissions.
- **Billing correctness** *(shipped v3.17.601)* — renewed contracts keep
  billing; contract hours are computed from billable, in-window, role-eligible
  time; cancel-at-period-end contracts stop billing and get cancelled; ticket
  invoices never re-bill time and respect prepaid and flat-fee coverage; the
  invoice approval gate can't be bypassed; editing an invoice keeps each
  line's source.
- **Customer users see what the portal shows them** *(shipped v3.17.600)* —
  shared tickets only, no internal comments or attachments, on the staff UI and
  the mobile API; cross-customer ticket reach is an MSP-staff capability.
- **Readable links in the dark themes** *(shipped v3.17.634)* — Dark, Dracula
  and Monokai used their button colour for link text, which fell to about 2:1
  on cards in Dark, and hover went darker. Those themes now have their own link
  colour, at least 4.5:1 on every page and card surface, lighter on hover; a
  test checks the ratios. The light themes followed *(shipped v3.17.635)*:
  Sunset and Gruvbox were about 2.5:1, Solarized and Nord under 4.5:1; every
  theme now passes, and the test covers all of them.
- **Dependency floors that actually take effect** *(shipped v3.17.640)* — the
  update flow never upgrades a package that still meets its range, so installs
  drifted to 115 advisories. Minimum versions are raised for Django, DRF,
  urllib3 and the indirect packages with advisories, so the next update brings
  any install up to date; Authlib and nltk, kept only for an unused scanner,
  are gone.
- **Bootstrap served locally** *(shipped v3.17.642)* — every page loaded
  Bootstrap from a CDN, so a blocked or failing CDN left the app unstyled. The
  unmodified 5.3.0 release now ships in `static/vendor/bootstrap/`, and a test
  fails if a template or view links the CDN copy again.
- **RMM devices stay with their own customer** *(shipped v3.17.643)* — every
  RMM integration (NinjaOne, Datto RMM, Atera, ConnectWise Automate, Tactical
  RMM) settles each device's customer from the RMM's own customer ID before
  anything is linked or shown. Connections are single- or multiple-customer.
  Unplaced or moved devices wait in a staff review queue instead of falling
  back to the connection owner. Asset matching uses a unique serial, or a
  unique hostname inside the customer, and never an IP address. Conflicts go
  to review with the candidates. Technician decisions and edits are kept.
  Alerts and software follow their device's customer. `rmm_reconcile`
  previews and applies the fix-up for existing data.
- **Updates page checks the root helper** *(shipped v3.17.645)* — Settings →
  Updates and the Apply pre-check ask whether the app may run the root helper,
  which every update uses, instead of probing old `sudo systemctl` rules. A
  failed old probe no longer shows a setup banner asking for NOPASSWD rules.
- **Updates page: every version, channel as policy, review before install** *(shipped v3.17.697)* —
  Settings → Updates lists every published stable release and prerelease (all pages of the GitHub
  Releases API, drafts excluded) and the development build from main, whatever the channel. The
  channel (Stable, Prerelease, Preview) only sets what is recommended, notified and auto-installed.
  Installing any eligible version goes through a review (signature, compatibility, preflight) and
  explicit confirmation; older versions need a migration-compatibility check. Restore points are
  listed with the exact restore command. The confirm dialog can no longer be hidden behind the
  app-install banner.
  Compact layout (status strip, collapsed version list and sections) *(shipped v3.17.698)*.
  Two channels only, Official release and Preview / testing *(shipped v3.17.701)*.
- **Customer users on technician pages, reveal defaults, password hashing**
  *(shipped v3.17.650)* — a customer user who opened a shared ticket's staff
  page saw time entries, expenses, kit, workflows, similar tickets and
  contract data, and could post to merge, quick-action, expense, kit, KB-link
  and workflow URLs; those are now technician-only (403), and a customer's
  attachment is always public. The asset page's RMM tab is technician-only.
  New custom roles no longer reveal credential values unless the box is
  ticked. Argon2 is now the active password hasher (the setting had the wrong
  name, so PBKDF2 was used); existing hashes upgrade at next sign-in.
- **Security Features: what ships, and what is on at each customer**
  *(shipped v3.17.651)* — the catalog is grouped into Sign-in, Client access,
  Vault and secrets, Tickets and AI, and Audit, and each entry states what it
  protects, its default, what it needs and where it is configured. The About
  and documentation pages show that description; Settings → Security →
  Security Features (superusers) adds the effective state at a chosen
  customer, read from the settings the code enforces, with environment
  overrides named. Unsupported claims (compliance standards, "immutable" logs,
  a 1-hour lockout, a fixed "2FA enabled" badge) are gone.
  `docs/CLIENT_DATA_PROTECTION.md` explains who sees what, vault reveals,
  ticket AI, RMM enforcement and known limitations.
- **Vault and audit follow-ups** *(shipped v3.17.652)* — browser-extension
  reveals are audited as reveals and share the web vault's 30/hour limit
  (they had none); the extension's offline cache leaves out entries that need
  approval; deleting audit entries (Maintenance clean-up or Django admin) is
  itself recorded.
- **Vault titles inside assigned customers, online-only restricted entries,
  Superuser Approval** *(shipped v3.17.653)* — a technician sees a customer's
  vault entries (titles, usernames, counts, search, APIs, extension, pickers,
  reports) only where a membership or an explicit global role grants "view
  vault"; Admin → Security → Vault Visibility lists staff who lost
  cross-customer visibility, read-only. Entries that need approval or that an
  access rule applies to sync to the extension without their secret, so the
  next sync replaces older local copies. Optional Superuser Approval (off on
  upgrade, needs two eligible administrators, switching it off is a protected
  change) makes a superuser grant wait for a different administrator; grants
  made on the host are recorded and announced.
- **Integrations belong to the platform** *(partial — platform ownership, global-view management and mapping-only data shipped v3.17.667; per-customer docs from platform controllers and multi-customer RMM ticket pairing planned)*: connections are
  platform-owned by default and added from global view, with an optional
  owner of one customer (its own Microsoft 365 tenant or on-site controller).
  Data from a platform connection reaches a customer only through the
  connection's mapping (PSA company, RMM customer, controller site,
  accounting customer); unmapped data stays with platform staff in global
  view. Managing platform connections needs a global role granting
  `integrations_configure` (sync and view have their own flags); a
  customer's admins see only their own connections and a read-only note.
  Existing connections keep their customer until a platform administrator
  uses the audited "Make platform-owned" action (or
  `manage.py integrations_ownership`). Extends integrations from global view
  (shipped v3.17.662). Planned: per-customer documentation from platform
  UniFi and Microsoft 365 connections, and ticket pairing for multi-customer
  platform RMM connections.
- **Pre-upgrade backups that look after themselves** *(shipped v3.17.667)*:
  every update trims old backups before and after it runs, keeping the
  newest verified one and anything a recovery needs; Settings → Updates
  lists them with sizes, retention settings, Delete and Clean up now, and
  the backup step shows its parts, elapsed and expected time.
- **Snyk CLI update alerts** *(shipped v3.17.667)*: a daily check e-mails
  superusers once per new CLI version; upgrading stays a manual,
  exact-version install.
- **Local days everywhere "today" matters** *(shipped v3.17.666)*: reports,
  PSA contracts and invoices, vehicles, resourcing, runbooks, payroll export,
  the mobile calendar, notifications and AI triage limits use the
  installation's time zone, so evening dates no longer roll over to tomorrow.
- **Local days on the wall display and Schedule panel** *(shipped v3.17.665)*:
  both use the installation's time zone for "today", so the evening's tasks
  no longer disappear once the UTC date rolls over.
- **RMM software sync for every provider** *(shipped v3.17.663)*: NinjaOne,
  Datto RMM, Atera and ConnectWise Automate software inventory syncs, Datto
  uses its documented device and software routes, and a failed read keeps
  the stored list instead of clearing it.
- **Integrations from global view** *(shipped v3.17.662)*: in global view the
  Integrations page explains that connections belong to an organization and
  offers an organization picker, so the RMM, UniFi, Microsoft 365, Omada and
  Grandstream Add buttons no longer bounce back.
- **RMM page and invoice scoping** *(shipped v3.17.661)*: RMM pages are
  for MSP technicians only, deleting an RMM device is limited to the selected
  customer, admin-only and audited, and invoices, invoice PDFs and the client
  account page need `billing_view_invoices` for the billed customer, including
  when no customer is selected.
- **Reveal, sign-in and audit-retention hardening** *(shipped v3.17.660)* — the
  customer portal's password reveal honours the approval requirement, access
  rules and the shared reveal rate limit, and shows nothing when its audit
  entry can't be written (mobile reveals and portal access changes likewise).
  A Microsoft sign-in counts as 2FA only when Microsoft confirmed MFA or the
  operator sets `AZURE_SSO_TRUSTED_AS_2FA`; otherwise the user enters their
  authenticator code. Audit clean-up keeps at least 30 days, and new installs
  no longer write `REQUIRE_2FA=False`.
- **Microsoft sign-in matched on identity, not e-mail** *(shipped v3.17.688)* —
  a Microsoft sign-in finds an account only by the verified tenant and object
  ID it is linked to. Existing accounts are linked by their owner after
  re-authenticating, or by an administrator confirming a recorded request;
  only the configured (or allow-listed) tenants are accepted; the flow uses
  PKCE and a nonce; auto-create is off by default and creates accounts with no
  access.
- **Scheduled UniFi asset sync places and types devices correctly**
  *(shipped v3.17.664)* — the scheduled `sync_network_assets` run and the manual
  Import to Assets page share one implementation
  (`integrations/network_assets.py`): device type from the controller's
  product type, features or model (gateway, switch, AP, UPS ...); each
  controller site's devices go to the customer that site maps to, for
  self-hosted and cloud connections alike; repeated runs update the same
  asset (controller + MAC/serial within the customer). Sites with no
  customer, more than one, or a name shared by several sites are skipped and
  listed on the connection page and in the sync result with what to fix.
  A read-only placement report (MSP staff admins) lists assets earlier syncs
  put under the wrong customer, typed wrongly or created twice; correcting
  them is a separate, confirmed action that records each asset's previous
  values in the audit log. Existing assets are left as they are until an
  admin applies a correction.
- **Standard integration sync health** *(shipped v3.17.664)* — PSA, RMM, Microsoft
  365, UniFi, Omada and Grandstream connections record last attempt, last
  successful sync, created / updated / skipped / failed counts, affected
  customers and sites, and a specific next step (re-enter credentials, check
  URL/port, map a site, fix the certificate). A run that dropped records or
  skipped sites shows as Partial, not Success. Errors are stored and shown
  with tokens, keys, passwords and credentials in URLs removed, including
  errors saved before this change. Shown on Integrations and on each
  connection's page. Distributor and accounting connections show their
  existing status fields (redacted) until they adopt the same recorder.
- **Edit forms keep what they don't submit** *(shipped v3.17.664)* — extends the bundled-services fix (shipped v3.17.584, #147).
  Contract, invoice and quote edits keep a field the submission does not carry
  or carries malformed (reported, never a 500); a blank value, an unticked
  checkbox or a removed row still clears. A contract saved before its bundle
  editor ran keeps its bundle. Technician Access keeps capabilities, group
  members, customer restrictions, approvers and detection settings a
  submission leaves out. Switching client with unsaved edits asks first, and a
  form left open while another tab switched client is refused instead of
  being saved under the other client. Browser checks:
  `scripts/browser_tests/form_friction.py`.
- **Separate customer portal sign-in and country policy** *(shipped v3.17.669)* — customers sign in at
  `/portal/login/` with their own password reset, two-factor enrolment and
  lockout pages; the staff sign-in refuses customer portal accounts and the
  portal sign-in refuses staff and superusers. Customer users who open a
  staff page are sent to the portal. Firewall Settings gains a country policy
  for the portal surface (portal pages, the portal sign-in and links sent to
  customers) next to the existing rules, which keep governing the staff
  backend, so the backend can be limited to fewer countries than customers
  sign in from; it inherits the staff rules until changed. An optional portal
  host name (Settings → General or `PORTAL_HOSTNAME`) serves the portal and
  customer links on their own host, with staff pages there returning 404.
  The portal and its sign-in pages have their own look with the customer's
  logo and colour, light and dark.
- **Security review fixes, first wave** *(shipped v3.17.724)* — invoice approval needs MSP staff and,
  while another staff member exists, someone other than the invoice's creator (refusals audited); files
  stored as documents are checked (executable, script and HTML types refused, 50MB limit, content must
  match the extension, stored type taken from the file name); security-vendor webhook severities are mapped
  onto the known levels with unknown values logged; the asset edit endpoint used by rack and closet pages
  no longer skips CSRF protection. Each finding has a reproducing test.
- **Security review fixes, second wave** *(shipped v3.17.725)* — rate limits count each visitor behind the
  trusted proxies instead of one shared bucket (public lead form and every per-address limit); public
  survey and unsubscribe links are throttled per address and per link; a satisfaction survey says when it
  was already answered and limits changes; ticket attachments (uploads and inbound e-mail) take their type
  from the extension, must match it in content and may not hide an executable or HTML in the name.
- **Security review fixes, third wave** *(shipped v3.17.727)* — a re-delivered alert never lowers its
  severity; security auto-tickets join an open ticket for the same customer, device and title and are
  capped per source per hour; unsigned webhooks are listed on the Security Overview; workflow assign and
  watcher actions apply the routing engine's customer authorization; creating from Global View uses the
  picked customer and only reachable ones; website monitors show their customer, are scoped on the detail
  page, and report failed checks in plain words.
- **Technician write access and backup server addresses** *(shipped v3.17.728)* — technicians without the
  administrator staff flag write by their global role within their customer scope (Global View create
  works); backup server requests go through the outbound-address guard, with a staff-only, audited
  per-connection opt-in for private addresses.
- **Security review fixes, fourth wave** *(shipped v3.17.729)* — process detail in Global View and dashboard
  widget changes check the record's customer; the asset API stays in reach without a selected customer;
  the legacy importer's requests are address-guarded; bulk upload logs counts only; CORS limited to the
  API and off in production.
- **Workflow re-entry and charge limits** *(shipped v3.17.732)* — a running rule is not started again by its
  own ticket save, one ticket event runs at most 50 actions, and `create_charge` bills a ticket once per rule.
**Added 2026-11-20 (platform audit; P0 unless noted):**

- **51.20 Security playbooks behind approval (SR-37)** *(shipped v3.17.737 — playbooks run only after approval unless `auto_run` is switched on per playbook; the workflow-rule step reports "not supported" or "refused", never ok)* — remediation playbooks off by default or
  behind an approval, the `run_workflow_rule` step either runs the rule or is removed, and the rule lookup
  checks the incident's customer. Tests: a forged alert sends no mail; a rule from another customer is
  refused.
- **51.21 Remove the dead GraphQL module (SR-20)** *(shipped v3.17.737, with SR-35/SR-36 comments and an unsigned-webhook test)* — with a URL-resolver test.
- **51.22 Throttling on public quote-signing and satisfaction-survey endpoints** *(shipped v3.17.737)*.
- **51.23 Workflow rule visibility by customer scope** *(shipped v3.17.738 — rules and the flow pages follow the technician's customer scope; editing needs `psa_manage_workflow_rules`; rules for every customer are read-only to restricted technicians)* — technicians restricted to some customers
  see and edit only those customers' rules; rule editing checks the roles registry (64.8).

</details>

---

<a id="phase-52"></a>

## Phase 52 — Technician workspace **(L · P1)** [in progress]
<!-- phase: ws=A stage=1 view=next order=6 deps=51 next="52.22 OPTIONAL AI wording" -->
**Status:** 🔵 In progress · **Priority:** P1 · **Workstream:** A. Core PSA & Ticketing · **Depends on:** 51  
**Next:** 52.22 OPTIONAL AI wording

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Day-to-day ticket work in fewer steps, without losing work or replying over
someone else.

- **My Work page** *(shipped v3.17.604)* — assigned tickets by SLA, running
  timers, customer-replied, waiting-on-customer / waiting-on-us queues,
  approvals and appointments.
- **Reply drafts, collision warnings, explicit public/internal composer,
  keyboard shortcuts** *(shipped v3.17.604)*.
- **Unified closeout with checklist and sign-off** *(shipped v3.17.604)*.
- **Draft KB article from a resolution, reviewed before publication**
  *(shipped v3.17.604)*.
- **Closeout checks on every closing path** *(shipped v3.17.626)* — the
  mobile app, AI-suggested status changes, change-request verification and
  ticket merge run the same resolution, checklist, sign-off and time rules
  as the Close button (merge skips the time rule); partner status updates
  no longer close or reopen local tickets.
- **Tickets read as a conversation** *(shipped v3.17.641)* — staff and portal
  pages share one thread: customer messages on the left, technician replies on
  the right, internal notes in amber marked staff only, and system events as
  compact rows. The sender's role comes from how the entry was recorded, not
  from its visibility; the portal never receives internal notes, internal
  attachments or private reply previews.
- **Ticket asset with RMM status** *(shipped v3.17.643)* — pick the
  customer's asset when creating a ticket, or change it on the ticket. The
  list holds that customer's assets only, and the server checks it again. Technicians
  see which RMM manages the asset, its last reported status (stale data is
  marked separately from offline), its last check-in, and an "Open in" link
  where the RMM documents one. RMM alerts open a prefilled ticket. Customers
  see none of the RMM details.
- **Connect with Rem0te from the asset or ticket** *(shipped v3.17.644)* — a
  Rem0te connection (one per customer, since a Rem0te key covers one business)
  syncs that business's computers and links them to the customer's assets by
  the same matching rules as the RMMs. Technicians get a Connect with Rem0te
  button that opens the computer in Rem0te under their own sign-in; no
  remote access credential is stored. A key for a different business stops
  the sync instead of filing its computers under the wrong customer.
- **Cc, secure messages, last activity and "Next"** *(shipped v3.17.654)* —
  a ticket keeps a Cc list (filled from the Cc of the opening e-mail, edited
  on the ticket) that e-mailed replies copy; a reply can carry a secure
  message, encrypted and sent to the requester as a one-time link that opens
  behind a button, with the ticket showing only whether it was opened. The
  ticket list and page show the last activity (reply, note, file, update; who
  and when) and whose move it is: needs reply, waiting on customer, follow up
  after 3 days, waiting on vendor. `psa_seed_sample_conversations` adds demo
  customer people and sample tickets showing all of it.
- **Sample data for every module** *(shipped v3.17.655)* —
  `manage.py seed_module_samples` fills the modules the other demo seeders
  leave empty (CRM, changes, problems, purchasing, inventory, scheduling,
  resourcing, vehicles, field ops, status pages, security incidents and
  playbooks, portal announcements, asset services, groups and
  vulnerabilities), for the demo customers only. It adds three demo
  technicians who can't sign in and is safe to re-run.
- **Customer operations page** *(shipped v3.17.664)* —
  one page per customer (`/core/customers/<id>/operations/`, from the
  customer page and the client switcher) listing SLA risks, uptime
  incidents (down monitors, recent outages, status-page incidents),
  contract renewals, overdue invoices and aging assets, each with a link to
  the page where the work is done (open ticket, renew contract, send
  reminder, open asset, plan replacement). Every section and total follows
  the user's role for that customer; customer users see only their own
  customer and only what their role allows.
  Uptime also lists WAN connections that are down or failed recent checks,
  active RMM alerts on the customer's devices (for roles with integrations
  access) and SSL certificates and domains that have expired or are about
  to; "Send reminder" on an overdue invoice emails the invoice PDF to the
  customer's contact in one click (needs the send-invoices permission for
  that customer; audit-logged; a second click within 10 minutes is
  refused); and MSP technicians can open any customer page instead of being
  sent back to the list.
  *(shipped v3.17.664)*
- **Invoice and client account pages need the view-invoices permission** —
  the invoice page, its PDF and the client account summary are refused to
  roles without it (customer editors and read-only users, technicians whose
  global role leaves billing out); customer users only reach invoices billed
  to their own customers, in every view mode.
  *(shipped v3.17.664)*
- **Optional modules settings page** *(shipped v3.17.664)* — Settings → System → Optional Modules lists every optional
  module with whether it is on, what it needs (Ticket AI, portal, routing
  and CSAT need PSA; status pages need monitoring), what people see when it
  is on and a link to its settings. Turning a module on while what it needs
  is off is refused; turning a dependency off says which modules stop
  working. No default changes. Ticket AI is listed as **OPTIONAL AI**.
  The six PSA settings switches that were saved but never read (client
  portal, anonymous ticket form, email to ticket, SMS to staff, desktop
  alerts, external alert ingest) are removed; the portal, mailboxes and SMS
  keep their own settings. Reports & Analytics and Secure Notes (Settings →
  Features) now switch their module off: menus, pages and scheduled reports
  (secure-note links already sent keep working). Both stay on after an
  upgrade. *(shipped v3.17.664)*
**Added 2026-11-20 (platform audit, area E; planned, P1):**

- **52.20 Drop files on the ticket composer** *(shipped v3.17.737 — several files per upload)* — through the existing upload rules
  (`psa/attachment_rules.py`), rejecting a mismatched type.
- **52.21 Ticket reminders** *(shipped v3.17.739 — private per-ticket reminders, the top-bar bell when due, a Reminders card on My Work)* — per-ticket reminders on the scheduler, shown in My Work.
- **52.22 Technician handoff summary** *(partial — the non-AI summary with a Copy button shipped v3.17.739; the OPTIONAL AI wording planned)* — a non-AI summary (status, last actions, open tasks,
  devices) for shift or technician changes; an AI wording is OPTIONAL AI behind `psa_ai_enabled`.
- **52.23 Knowledge suggestions without AI** *(shipped v3.17.739 — matched by alert kind, ticket tags and asset type with a reason for each; documents have no asset-type or alert-kind field, so matches use tags and category names)* — articles and runbooks matched by category, alert kind
  or asset type.
- **52.24 Customer follow-up and confirm-or-close** *(shipped v3.17.760)* — automatic follow-up when a ticket waits on the
  customer, closing after a configurable silence with a recorded reason.

</details>

---

<a id="phase-53"></a>

## Phase 53 — Documentation readiness and lifecycle **(L)** [shipped — v3.17.656]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 53](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-53).

---

<a id="phase-54"></a>

## Phase 54 — Guided customer service requests **(L)** [shipped — v3.17.669]
<!-- phase: ws=G -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** G. Customer Portal & Communications

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 54](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-54).

---

<a id="phase-55"></a>

## Phase 55 — Hardware catalog and visual inventory **(L)** [shipped — v3.17.630]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 55](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-55).

---

<a id="phase-56"></a>

## Phase 56 — Ticket AI Assist and RMM handoff **(L · OPTIONAL AI)** [in progress]
<!-- phase: ws=D view=later deps="57; Rem0te ticket-rmm-v1" next="Remaining Rem0te-side items move with 63.11–63.16" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 57; Rem0te ticket-rmm-v1  
**Next:** Remaining Rem0te-side items move with 63.11–63.16

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

**OPTIONAL AI** — gated by `psa_ai_enabled`, the customer's PSA switch, a customer
AI policy, an enabled model profile and technician access (Phase 57). ClientSt0r
owns the ticket UI, AI settings, provider credentials, the inference gateway and
customer replies; a paired RMM (any that implements ticket-rmm-v1; rem0te is the
reference implementation) processes jobs and, in later milestones,
collects approved device evidence and independently approves and runs endpoint
work. Contract: `docs/contracts/ticket-rmm-v1/`.

- **56.1 Ticket-only analysis and drafts** — "Analyze ticket" with a preview of
  the redacted evidence, destination and cost; staff-only facts with evidence
  references, causes, missing information, checks, warnings and editable
  replies; works without a device; "Use reply" never overwrites the composer
  and only Send publishes; the old Approve & Send path and the
  `run_rmm_script` AI action removed. *(shipped v3.17.646 — tested against a
  fixture processor; the rem0te side of the contract is not built yet)*
- **56.2 Model profiles, customer policies and the gateway** — Claude, OpenAI
  and approved on-premises Ollama; company, assigned-MSP or (where the customer
  allows) technician-owned keys, write-only and sealed to the gateway key;
  one economical default; atomic daily budgets; local-only for both processor
  and model; the gateway re-checks job, actor, tenant, profile, evidence digest,
  expiry and budget on every call. *(shipped v3.17.646; isolated worker mode is
  opt-in — the default in-process mode is reported as not isolated)*
  Technicians add their own Claude / OpenAI keys under My Profile → My AI keys,
  usable only by them where the customer allows technicians' keys.
  *(shipped v3.17.648)*
- **56.3 Compare models** — separately permissioned, shows every recipient and
  its cost first, labels disagreements, returns partial results.
  *(shipped v3.17.646)*
- **56.4 Signed integration channel** — mutual HMAC signing, DB-backed nonces,
  delegated short-lived identity, idempotent jobs (409 on a changed payload),
  sequenced and de-duplicated events, polling recovery, outage leaves manual
  work untouched. *(shipped v3.17.646 — ClientSt0r side; the recovery poll runs
  every minute from the in-app scheduler since v3.17.648)* Pairing works with
  any RMM provider, the remote tenant is pinned from the RMM's signed
  capabilities answer, and the connection page shows pairing status with a
  Check pairing button. *(shipped v3.17.658)*
- **56.5 Private RMM handoffs, read-only diagnostics and remote launch** —
  targets only from verified same-business associations; "Sent" only on a
  confirmed receipt. *(partial — ClientSt0r side shipped v3.17.658: Send to
  RMM, advertised read-only diagnostics with staff-only results, remote
  view/control launch; works with AI off; tested against a fixture processor —
  the RMM side is still to be built in rem0te)*
- **56.7 Rem0te pairing over Ed25519** — Rem0te's own revision of the contract:
  Ed25519 request, response and event signatures, ClientSt0r request and
  delegation keys (encrypted at rest, shown with the peers-file entry on the
  connection page), technician delegation tokens bound to the request body,
  the contract pinned to a Rem0te revision with incompatible peers refused,
  specific secret-free Check pairing reasons, and a reversible migration that
  marks HMAC Rem0te pairings for re-pairing. HMAC pairing stays for every
  other provider. *(shipped v3.17.664)*
- **56.8 Rem0te alerts, jobs and action proposals** — Rem0te monitoring alerts
  open exactly one staff-only ticket and the ticket is linked back in Rem0te;
  analysis jobs run through Rem0te with signed results; L2+ technicians
  propose Rem0te catalog actions that Rem0te approves and runs. A cross-peer
  end-to-end run against a real Rem0te (`scripts/e2e/cross_peer/`, CI
  workflow `cross-peer-e2e`). *(shipped v3.17.664; refusal reasons for Rem0te 0.31–0.68 codes, direct mode
  shown as unavailable, and the list of Rem0te alert kinds not sent shipped v3.17.721)*
- **56.6 Fix review** — only when the RMM advertises signed actions; ClientSt0r
  refers, the RMM approves and runs. *(partial — ClientSt0r referral and signed
  status shipped v3.17.658; approval and execution happen in Rem0te, proven end to end by the cross-peer
  remediation-chain run against Rem0te 0.68.0 in v3.17.721)*
- **56.9 Ticket AI and automation history** — one staff-only, chronological
  timeline per ticket: model/profile actually run, prompt version (file name +
  content hash) on every draft and run, the human decision on each draft
  (sent unchanged, edited then sent, kept internal, send refused) and
  suggestion (approval requested, approved, rejected), approval requirement
  and expiry for suggested changes, fix referrals and Rem0te proposals,
  Rem0te outcome (job error code, proposal status and observed result),
  alert tickets and routing decisions (marked as never starting a remote
  session or endpoint action). Technicians with access at the customer only;
  AI entries need AI output access and show no AI text while AI is off;
  per-customer retention with a scheduled purge. *(shipped v3.17.664)*

**Sizing:** **L** — 56.1–56.4 shipped; ClientSt0r side of 56.5–56.6 shipped
v3.17.658; the RMM side waits on rem0te.

</details>

---

<a id="phase-57"></a>

## Phase 57 — Technician security levels and abuse prevention **(L · security)** [in progress]
<!-- phase: ws=F state=verify view=later deps="—" next="Confirm remaining items against 64 roles" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** F. Security & Administration · **Depends on:** —  
**Next:** Confirm remaining items against 64 roles

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **57.1 Presets and assignments** — L1 Help Desk / L2 Technician / L3 Senior
  presets seeded idempotently; clone and customise; assign per technician or
  group, per customer, with expiry; customer defaults and restrictions;
  explicit denies; effective-access preview with explanations; diffs before
  saving; reset-to-default preview; audit of every change. Portal users are
  outside presets; staff/admin/superuser flags never imply a level.
  *(shipped v3.17.646)*
- **57.2 One resolver on every path** — ticket page, AI routes (including the
  old inbox/apply/workflow routes), direct IDs, result reads and gateway
  dispatch, re-checked on every request and when a queued job runs.
  *(shipped v3.17.646)*
- **57.3 Vault isolation for AI** — provider keys sealed to an X25519 gateway
  key; a restricted worker without the vault master key; destination allowlist,
  no redirects, metadata and DNS-rebinding blocked. *(partial — shipped
  v3.17.646; worker runs as the same OS user, a separate user is a deployment
  step)* The worker as its own OS user (`clientst0r-ai`) that can't read
  `.env`: set up by `bash install.sh` on MariaDB/MySQL installs and by
  `deploy/setup-ai-gateway-user.sh` on existing ones, the `ai-gateway` compose
  profile on Docker, checked in the native-install CI job.
  *(shipped v3.17.664)*
- **57.4 Protected changes** — widening needs fresh authentication and a
  distinct approver; self-promotion and own-recovery-address approvals refused;
  the previously verified contact is notified. *(shipped v3.17.646)* The e-mail
  address of superusers, approvers and MSP technicians moves the same way, from
  the profile page, the user editor and the Django admin, and the old address
  is told at every step. *(shipped v3.17.648)* Granting superuser from inside
  the app as a protected change, as an optional Superuser Approval policy
  (off on upgrade; host-level grants recorded and announced).
  *(shipped v3.17.653)*
- **57.5 Read-only theft detection** — distinct tickets, customers, exports and
  diagnostic bytes per identity across UI, REST and mobile API, 1 h and 24 h
  windows, on by default, tunable, containment by level, no ticket text in
  alerts. *(shipped v3.17.646; diagnostic bytes counted from RMM diagnostic
  results since v3.17.658)*
- **57.6 Remote actions with live RMM authorization** — view, control and
  elevation as time-limited grants from the RMM. *(partial — view/control
  launch with an allowed or on-request grant shipped v3.17.658; time-limited
  grants are the RMM's to implement; elevation not wired)*
- **57.7 Why a technician can do something** — extends the effective-access
  preview (shipped v3.17.646): for a technician, customer and capability, the
  outcome and the chain of sources at that customer (assignments active,
  expired and revoked, group membership, denies, customer restriction, paired
  RMM, technician standing and Superuser grant, membership role), who granted
  each and when, expiry, links to the assignment record and the approving
  protected change, and audit history with before/after. Assignments record
  their approving change and revoker; role changes are audited.
  *(shipped v3.17.664)*

**Sizing:** **L** — 57.1–57.5 and 57.7 shipped; 57.6 partial with Phase 56.5.

</details>

---

<a id="phase-58"></a>

## Phase 58 — Condensed navigation **(M · UX)** [shipped — v3.17.647]
<!-- phase: ws=I -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** I. Deployment, Updates & Reliability

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 58](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-58).

---

<a id="phase-59"></a>

## Phase 59 — Verified installs and upgrades **(M · reliability)** [in progress]
<!-- phase: ws=I stage=7 view=later deps="updater, root helper" next="59.7 LTS channel" blocker="LTS channel needs a published support policy" unblock="Owner publishes a support policy" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** I. Deployment, Updates & Reliability · **Depends on:** updater, root helper  
**Next:** 59.7 LTS channel  
**Blocked:** LTS channel needs a published support policy — *unblocks when:* Owner publishes a support policy

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

An upgrade installs exactly the revision the administrator reviewed. It
doesn't migrate without a backup that has been proven to restore, and an
upgrade that stops partway can be recognised and recovered.
Guide: `docs/UPGRADE_AND_RECOVERY.md`.

- **59.1 Release channels** *(shipped v3.17.664)*: **Stable** (the
  latest signed published release, the default) and opt-in **Preview** (newer
  commits on main, labelled unreleased). Settings → Updates and the update
  badge show the installed build, the recommended release, and main's
  unreleased commits (count and list). They show which channel the instance
  follows and exactly what Apply would install. If GitHub is unreachable or
  rate-limited, the page shows the last good answer, marked stale.
- **59.2 Pinned, verified Apply** *(shipped v3.17.664)*: Apply carries
  the reviewed commit sha. It refuses if origin moved, fetches that commit,
  and verifies the release tag signature against the trusted release key. It
  then runs the update script from that revision. The same pipeline backs
  `manage.py upgrade_apply`, `update.sh`, `install.sh` option 1 and the
  nightly timer.
- **59.3 Preflight checks** *(shipped v3.17.664)*: disk space, database
  reachable, pending migrations, media writable, required keys, backup
  destination, dependency resolution. Results are shown in the UI before
  Apply and logged.
- **59.4 Verified pre-upgrade backups** *(shipped v3.17.664)*: the
  database, uploaded files and keys, kept in an owner-only directory. Each
  backup is restore-tested into a scratch database, including a vault decrypt
  with the stored key, before any migration. There is restore, plus
  passphrase-encrypted export and import. The Docker entrypoint takes one
  before migrating an existing database.
- **59.5 Interrupted-upgrade recovery** *(shipped v3.17.664)*: an
  upgrade journal, `upgrade_status`, `upgrade_apply --resume`,
  `upgrade_restore`, and `migration_doctor`. The doctor tells a half-applied
  MySQL/MariaDB migration apart from one that ran but wasn't recorded (#128,
  #129). The recovery panel replaces Apply while recovery is needed.
  Repair from the browser *(shipped v3.17.709)*: the panel's **Repair**
  button finishes an unfinished upgrade with a newer build that contains the
  stuck revision (`upgrade_apply --resume --sha`), and **Resume** re-runs the
  same revision, both reusing the verified pre-upgrade backup.
- **59.6 Install and upgrade rehearsals in CI** *(shipped v3.17.664)*:
  fresh native and Docker installs; a multi-release upgrade with
  representative data; a killed upgrade recovered by restore and by resume;
  a half-applied migration on MariaDB. Checks after each step cover login
  with 2FA, tenant isolation, file serving, vault decryption, clean
  migrations and a scheduler tick. Workflow:
  `.github/workflows/install-upgrade.yml`; scripts:
  `scripts/upgrade_rehearsal/`.
- **59.7 LTS channel** *(planned)*: only once there is a published support
  window and a backport policy for security fixes. Until then there is no
  LTS.
- **Security update label for critical fixes only** *(shipped v3.17.726)* — the update badge turns red only for a release explicitly marked as a critical security fix; routine hardening shows as an ordinary update.

</details>

---

<a id="phase-60"></a>

## Phase 60 — Optional ticket routing **(M · PSA)** [shipped — v3.17.664]
<!-- phase: ws=A -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** A. Core PSA & Ticketing

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 60](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-60).

---

<a id="phase-61"></a>

## Phase 61 — One-customer migration rehearsals (IT Glue, Hudu) **(M · imports)** [shipped — v3.17.664]
<!-- phase: ws=C -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** C. Asset Management & Documentation

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 61](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-61).

---

<a id="phase-62"></a>

## Phase 62 — Pluggable document editors **(L · documents)** [in progress]
<!-- phase: ws=C view=later deps=documents next="62.5 Google Docs connector; 62.6 portal editing permissions" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** C. Asset Management & Documentation · **Depends on:** documents  
**Next:** 62.5 Google Docs connector; 62.6 portal editing permissions

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

View, edit and create Word, Excel and PowerPoint files attached to
documentation, tickets and assets, through an editor the MSP chooses: on the
clientst0r server, on a separate VM, or an existing editor service. Local files
stay in clientst0r, which keeps every version. Shipped v3.17.668, built and tested against
protocol-accurate fakes; **not yet verified against a real ONLYOFFICE,
Collabora or Microsoft 365 service**.

- **62.1 Editor framework** *(shipped v3.17.668 — not yet verified against a real service)* — binary
  file versions with checksums, atomic saves, stale-save refusal and a
  quarantine for late or refused saves (30-day retention); edit sessions with
  scoped, expiring, revocable tokens; outbound requests only to approved editor
  hosts (metadata addresses, redirects and DNS rebinding blocked; private CA
  supported, TLS always verified); New Word / Excel / PowerPoint, templates,
  Preview, Edit, Download, Rename, Save a Copy, Version History, Restore,
  Export PDF where the editor supports it; legacy and macro-enabled files kept
  and opened read-only with conversion to a new copy; full-screen editor with
  "changes in editor" vs "saved to clientst0r" status; Settings → Integrations
  → Office Documents (superusers configure instances, organization admins pick
  approved ones), diagnostics and an explicit round-trip test; every action
  audited, tokens redacted from logs. No malware scanner ships; a hook is
  provided.
- **62.2 ONLYOFFICE Docs (self-hosted)** *(shipped v3.17.668 — not yet verified against a real service)* — signed (JWT)
  editor configuration and callbacks, every callback status, force-save,
  per-save document keys, revocation drops the editor, PDF and legacy
  conversion via the conversion service. Requires ONLYOFFICE Docs 10.0 or
  later.
- **62.3 Collabora Online (self-hosted)** *(shipped v3.17.668 — not yet verified against a real service)* — WOPI host
  (CheckFileInfo, GetFile, PutFile, locks, rename), proof-key verification,
  timestamp and lock conflict handling, form-posted tokens with renewal,
  postMessage origin checks. CODE is labelled evaluation / development only;
  licensed Collabora Online is supported for production.
- **62.4 Microsoft 365 documents** *(shipped v3.17.668 — not yet verified against a real service)* — separately enabled
  on the Microsoft 365 connection: per-user delegated sign-in for document
  scopes only, administrator-chosen libraries and folders, link and open
  SharePoint / OneDrive files in Microsoft 365, create in a chosen folder, and
  explicit import / export of copies. Linked files stay in Microsoft 365; no
  sync, no sharing links. Embedding Microsoft's editors directly over
  clientst0r-stored files (WOPI) is not offered (it requires Microsoft's
  partner program).
  - **Edit in Microsoft 365** *(shipped v3.17.671 — not yet verified against a real tenant)* —
    a working-copy round trip for clientst0r Word, Excel and PowerPoint files:
    the current revision (checksum verified) is uploaded as the user to their
    own OneDrive or an approved library / folder and opened in Microsoft 365;
    *Save back to clientst0r* stores the Microsoft copy as a new revision on
    request only (stale-base saves are kept as conflicts, double saves are
    no-ops, permission re-checked); Finish / Discard delete or keep the copy
    per administrator policy. MSP staff can use the platform (MSP) tenant or
    the customer's own; customer users only their own customer's; another
    customer's tenant is never used, and a confirm step names the receiving
    tenant first. Other users and the ONLYOFFICE / Collabora
    editors show who is editing in Microsoft 365. Customer users need the new
    `office_edit_in_m365` permission. A scheduled task reminds about or ends
    idle sessions and never imports. No sharing links.
- **62.5 Google Docs** *(planned)* — optional connector. Open a copy in
  Google Drive, then import the edited file back as a new version; files are
  never left shared in Drive.
- **62.6 Permissions and customer boundaries** *(partial — staff side shipped v3.17.668; customer portal editing planned)* — opening a file follows the same view and edit permissions as
  its document, ticket or asset, rechecked on every save; tokens are limited
  to one file, one user and one session. Customer portal editing is planned.
- **62.7 Installation and operations** *(shipped v3.17.668 — not yet verified against a real service)* — editor installer
  for the same server or a separate VM (preflight, verified signing keys,
  pinned and held versions, secrets never on the command line), drain before
  editor upgrades or provider switches, uninstall that keeps every document,
  and clientst0r updates that never upgrade or restart an editor.
- **62.8 Managed Local ONLYOFFICE** *(shipped v3.17.668 as **untested** — off by default; not yet run against a real container, and the helper refuses to install a release until it passes the live checklist)* —
  an optional, off-by-default mode in which a deployment runs one
  ONLYOFFICE Docs container on its own VM, pinned by image digest, managed
  from the Office settings page through a root-owned helper with a fixed set
  of operations (install, status, start, stop, restart, update, rollback,
  redacted logs, uninstall). Sessions are drained and saves verified before
  any restart, backups are taken before updates, rollback uses a matching
  backup, uninstall keeps documents and editor data, and the app never gets
  Docker access.
- **62.9 Managed Local Collabora (CODE)** *(shipped v3.17.671 — untested against a real container)* —
  a second engine for the managed mode, one engine at a time and chosen only
  from the engines the root configuration allows. Pinned image digests
  (every CODE release untested until the live checklist passes), resource
  limits, loopback-only port, editor traffic limited to clientst0r over
  HTTPS, WOPI allow-list restricted to the deployment, admin secret and proof
  key held by root. The existing Collabora provider is configured
  automatically after install. Switching engines drains sessions and keeps
  every document. Labelled evaluation / development; licensed Collabora
  Online stays supported through the external provider.
- **62.10 Reverse-proxy setup for managed editors** *(shipped v3.17.671 — untested against a real container)* —
  the root helper writes only its own Nginx files for the editor: a
  dedicated host name (TLS on this server, or on a device in front of it), or
  Collabora's opt-in same-host paths as a snippet the administrator includes
  once. `nginx -t` before every reload and the previous files restored on
  failure; clientst0r's own site is detected and never modified. Same-host
  shows the shared-origin warning, needs an explicit, audited acceptance and
  strips cookies and authorization headers on the editor paths. Switching
  between same-host and a dedicated name is a supported operation (drain,
  rewrite, update the provider's address, re-check) without reinstalling.
  Setup checks cover DNS, certificate, the Nginx files and all three
  reachability paths, including a browser probe.
- **62.11 Capacity checks for managed editors** *(shipped v3.17.671 — untested against a real container)* —
  setup checks warn about, or refuse, an editor that would starve
  clientst0r of memory or CPU, with the verdict, limits and a recommendation
  per engine on the settings page.

- **62.12 Live verification harness for managed editors** *(shipped v3.17.671; first run against a real Collabora CODE container on 2026-11-13 found the welcome-dialog problem fixed in v3.17.674)* —
  one command that checks a managed Collabora or ONLYOFFICE editor with a
  real headless browser: create, open, type, save, close and reopen DOCX,
  XLSX and PPTX files and confirm the stored revision and its checksum; a
  read-only user cannot save; two users edit at once; a long session with a
  delayed save; restart, stop/start, update and rollback, and uninstall and
  reinstall through clientst0r's own operations; and, in same-host path
  mode, that clientst0r's session cookie never reaches the editor. Runs
  safely on a live install by default (its own test organization and users,
  removed at the end; refuses while real users have documents open), with an
  optional disposable-VM profile that adds installation and reboot checks.
  Produces a JSON result and a report, and a release is marked tested only
  from a passing result for its exact image digest.
- **62.13 Server setup for managed editors from Settings** *(shipped v3.17.672 — not yet run on a real host)* —
  one form on the Managed page installs Docker (only if absent), the Office
  service helper, the container firewall and the helper's Nginx files, and,
  for the same-host layout, the include line in clientst0r's own site. It
  runs through the root helper from the signed release (never the app
  directory), with every argument checked again and `nginx -t` before any
  reload; the web process only records the request, the scheduler runs it
  in its own process, and the output and result are audited.

**Sizing:** **L** — framework 1–2 weeks, ONLYOFFICE 1 week, Collabora 1 week,
Microsoft 365 and Google Docs 1–2 weeks each.

- **62.14 Front proxy on gunicorn's port** *(shipped v3.17.673 — not yet run on a real host)* —
  for servers where the device in front talks to gunicorn's TCP port directly, the root helper's
  `front-proxy on` moves that port to an Nginx site in front of gunicorn's unix socket (systemd
  drop-in, health compared through the port and the socket, automatic rollback), so the same-host
  editor locations can be added without any change to DNS or the device in front. Server setup
  runs it first when it is needed.
- **62.15 Native Collabora runtime (no Docker)** *(shipped v3.17.687 — not yet run on a real host; both pinned releases marked untested)* —
  the managed Collabora editor can run from Collabora's own packages instead of a container,
  chosen at setup (Settings → Set up this server, or `--runtime native`). The installer adds
  Collabora's CODE apt repository with its signing key pinned by fingerprint; Install puts the
  exact `coolwsd` and `code-brand` versions from the helper's release list in place, pins and
  holds them, and runs the package's systemd service on a loopback port with memory and CPU
  limits, the same editor settings as the container, a root-kept proof key and an nftables
  rule that lets the editor's own user reach only clientst0r over HTTPS. Start, stop, update,
  roll back, uninstall, logs, setup checks, layouts and engine switching work for both
  runtimes. ONLYOFFICE keeps running in Docker.

</details>

---

<a id="phase-63"></a>

## Phase 63 — RMM integration and technician workspace **(XL · P0 · RMM)** [in progress]
<!-- phase: ws=D stage=1 view=next order=4 deps="52, 56, 57; Rem0te contract" next="63.17 contract hygiene now; 63.11–63.16 as Rem0te ships each item" blocker="63.11–63.16 need Rem0te contract items (P2/P3, R13, P10, P6, R7/P5, P7, R2)" unblock="Rem0te ships the items; two-application tests pass" -->
**Status:** 🔵 In progress · **Priority:** P0 · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 52, 56, 57; Rem0te contract  
**Next:** 63.17 contract hygiene now; 63.11–63.16 as Rem0te ships each item  
**Blocked:** 63.11–63.16 need Rem0te contract items (P2/P3, R13, P10, P6, R7/P5, P7, R2) — *unblocks when:* Rem0te ships the items; two-application tests pass

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

One place for a technician to see a customer's devices, alerts and tickets,
act on them within their permission level, and leave a record of what was
done. Builds on Phase 56 (ticket AI and RMM handoff), Phase 57 (technician
security levels) and Phase 52 (technician workspace).

- **63.1 Rem0te contract revision 2** *(shipped v3.17.664)* — Ed25519 request and delegation
  keys with overlapping rotation, the contract revision negotiated per
  connection (revision 1 still accepted), each organization bound to its own
  Rem0te business, containment pauses shown as Degraded, and undeliverable
  events recorded and re-applied later. One connection status everywhere
  (Connected, Degraded, Disconnected, Authentication Problem, Configuration
  Required), a setup wizard with Test connection, and a reconciliation job
  with backoff. Tested against a real Rem0te 0.30.1 (99/102; job-across-restart
  case pending R11). Extends 56.7 and 56.8.
- **63.2 Technician workspace and navigation** *(shipped v3.17.664)* — recent devices, saved
  views with default filters on dense lists (assets, RMM alerts, routing
  triage, invoices, timesheet approvals), open-in-context links and
  setup guidance on empty pages. Extends Phase 52 and Phase 58.
- **63.3 Device Workspace** *(shipped v3.17.664)* — one page per device with stored RMM data,
  each fact's source and age, and an explicit "not supported by this RMM"
  where a provider has no such field. Per-provider field maps, opt-in service
  lists (Tactical RMM) and a rate-limited Refresh from RMM.
- **63.4 Ticket RMM panel** *(shipped v3.17.664; audit 2026-11-20: read-only diagnostics work for synced RMMs but return nothing for Rem0te connections until 63.11)* — affected devices on a ticket (same customer
  only), device health and history, read-only diagnostics, result notes and
  verify-then-close.
- **63.5 AI Troubleshoot** **OPTIONAL AI** *(shipped v3.17.664)* — gated by `psa_ai_enabled` and
  off per customer until switched on. Sharing rules per customer, runbook and
  KB matching, an installation-wide monthly cap and an optional command
  allowlist. Suggested commands are shown as text only and never run.
- **63.6 Alert-to-ticket policy** *(shipped v3.17.664)* — rules, maintenance windows, site
  outage grouping and recovery notes for Rem0te and synced RMM alerts. Off
  (legacy one ticket per alert) until an administrator switches it on.
- **63.7 One-click support workflows** *(shipped v3.17.664)* — guided evidence, likely causes,
  remediation the connected RMM advertises (with approval) or manual steps,
  and recovery confirmed by monitoring. Structured editor, JSON kept as an
  advanced view. Routing a ticket never starts a remote session or authorizes
  an endpoint action.
- **63.8 L1 / L2 / L3 RMM permission levels** *(shipped v3.17.664)* — one server-side decision
  for every RMM action, built-in level templates, per-customer and per-action
  overrides, second-person approvals with approver e-mail, and level changes
  that need a second administrator. Extends Phase 57.
- **63.9 Technician UX and accessibility** *(shipped v3.17.664)* — sidebar entries for the new
  pages, named controls and visible focus on technician pages, checked at
  phone and tablet widths.
- **63.10 Tests and coordination** *(shipped v3.17.664)* — unit and browser tests per part, a
  cross-peer run against a real Rem0te, and a shared coordination record
  (`INTEGRATION_COORDINATION.md`) with the Rem0te project. *(record brought up to date for Rem0te 0.68.0,
  citing the cross-peer CI run, v3.17.723)*

**Added 2026-11-20 — remaining PSA/RMM workflow (P0).** Each item needs the matching Rem0te contract item
(Rem0te backlog Priority 9 in `docs/plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md`); none is
claimed until a two-application test passes against real Rem0te code. Clientst0r requests and records; Rem0te
approves, executes and verifies.

- **63.11 Read-only diagnostics from Rem0te** *(planned — needs Rem0te P2/P3, R13)* — no AI involved; results
  stored on the ticket with their observation time.
- **63.12 Device health summary in the ticket** *(planned — needs Rem0te P10)* — with an age per field group.
- **63.13 Remote session launch from the ticket** *(planned — needs Rem0te P6)* — a deep link only, no
  credential in any response; the session record is written back to the ticket.
- **63.14 Proposal status events and automatic result notes** *(planned — needs Rem0te R7/P5)* — replaces the
  poll and the technician click; results arrive signed.
- **63.15 Handoff note and ticket status to Rem0te** *(planned — needs Rem0te P7)*.
- **63.16 Patch status on demand and newer alert kinds** *(planned — needs Rem0te revision negotiation, R2)* —
  the six newer alert kinds only after both sides declare the revision.
- **63.17 Contract hygiene** *(planned)* — re-vendor the interop file (SR-33), outbound client certificate to
  Rem0te (SR-23), complete the double-ticket guard (SR-27).
- **63.18 Platform-aware device views (P2)** *(planned — needs per-endpoint capability flags from Rem0te)* —
  Windows, Linux and macOS endpoints shown at the capability Rem0te actually reports; read-only agents
  labelled read-only; no Windows-only action offered on Linux or macOS, refused at the API as well as hidden.
  See `docs/plans/platform-program/CROSS_PLATFORM_REQUIREMENTS.md`.

Acceptance: the end-to-end chain alert → ticket → diagnostics → proposal → approval in Rem0te → signed
result → verified recovery → ticket update runs in the cross-peer suite with both applications' real code.

**Sizing:** **XL** — ten parts across integrations, assets, PSA, AI and
permissions; interoperability with Rem0te is claimed only for what both
applications have passed end to end.

</details>

---

<a id="phase-64"></a>

## Phase 64 — Roles, permission groups and access settings **(L · security)** [in progress]
<!-- phase: ws=F stage=1 view=later deps="57, 63" next="64.8 remaining enforcement call sites" -->
**Status:** 🔵 In progress · **Priority:** P0\* · **Workstream:** F. Security & Administration · **Depends on:** 57, 63  
**Next:** 64.8 remaining enforcement call sites

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

One permission model for MSP staff and customer users: every permission
named and described in one registry, built-in roles for the usual jobs,
roles that combine without widening each other, data scope per grant, and
protection against handing out more access than you hold. Extends Phase 57
(technician security levels) and the RMM tiers of Phase 63.

- **64.1 Permission registry** *(shipped v3.17.669)* — every role permission with
  its module, kind of action, sensitivity, whether a customer role may hold
  it and a description; new sensitive permissions default to off. Adds
  quotes, internal ticket notes, privileged member and role management,
  ownership, contract (draft, approve, send, signing links, countersign,
  void, signed copies, audit, settings), portal (organization-wide tickets,
  filing and replying, request approval, coworkers' agreements, billing
  contact, contract reviewer, authorized signer) and operations permissions.
- **64.2 Built-in roles** *(shipped v3.17.669)* — Owner, Organization Administrator,
  Service Manager, Level 1–3 Technician (the RMM tier roles), Sales
  Representative and Manager, Billing / Finance, Internal Read-Only /
  Auditor; Customer Administrator, Manager, Standard User and Read-Only, plus
  add-on Billing Contact, Contract Reviewer, Authorized Contract Signer and
  Request Approver. Seeded idempotently with a version and checksum so a
  customized role is never overwritten.
- **64.3 Scope** *(shipped v3.17.669)* — a technician's global role reaches all
  clients, assigned clients or selected clients; memberships and global
  roles cover the organization, assigned records or own records. Every
  check evaluates one organization; permissions from different grants never
  combine into a wider one.
- **64.4 Delegation protection** *(shipped v3.17.669)* — no self-promotion,
  the subset rule, privileged roles need their own permission, customer
  administrators assign customer roles only, the organization in the URL is
  the one authorized, last-owner protection and an explicit ownership
  transfer with password and name confirmation.
- **64.5 Role management pages** *(shipped v3.17.669)* — create, clone, rename,
  archive, permissions by module with search, preview before saving,
  compare roles, "why does someone have access", permission catalog,
  customer portal access, multiple roles per member and a review list.
- **64.6 Upgrade mapping and review list** *(shipped v3.17.669)* — existing roles
  keep what they could do; anything ambiguous is listed for review, never
  granted. `manage.py roles_migration_report`.
- **64.7 Audit and cache** *(shipped v3.17.669)* — role, membership, scope,
  account and ownership changes audited with safe before / after values;
  authorization decisions cached per request and invalidated on change.
- **64.8 Enforcement across modules** *(partial — enforcement shipped v3.17.669; flags still marked pending in the registry await their call sites)* — PSA, sales,
  reports, portal, assets, documentation, vault, integrations and the API
  read these permissions per organization and per record. Operations
  permissions (fleet, wallboard, workflow rules, timesheets, payroll,
  report export, billing approvals) are defined; their call sites are
  planned.

See [ROLES_AND_ACCESS.md](ROLES_AND_ACCESS.md) for the role matrix.

**Sizing:** **L** — registry, roles and helpers, then enforcement module by
module.

</details>

---

<a id="phase-65"></a>

## Phase 65 — Contract documents and digital signing **(L · sales)** [in progress]
<!-- phase: ws=B view=later deps="15, 64" next="65.10 reviewed legal wording" blocker="Starter contract wording is sample text" unblock="Legal review of the wording" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** B. Billing & Financial Management · **Depends on:** 15, 64  
**Next:** 65.10 reviewed legal wording  
**Blocked:** Starter contract wording is sample text — *unblocks when:* Legal review of the wording

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Write a contract for a client, get internal approval, send it for signature
and keep the signed result with its evidence. Separate from PSA billing
contracts (which a signed contract can start) and from the existing client
agreements and quote acceptance. Items 65.1–65.9 **shipped v3.17.669**.

- **65.1 Builder** *(shipped v3.17.669)* —
  start from a template, a copy of an earlier contract or a blank page;
  client, title, number, type, owner, account manager, dates, duration,
  renewal and notice terms, billing frequency, payment terms, currency, tax,
  one-time and recurring line items, signers and attachments. Rich text with
  headings, lists, tables and page breaks; every section can be renamed,
  reordered, left out or removed; autosave with a visible saved state and a
  conflict warning when the draft changed elsewhere.
- **65.2 Templates and clauses** *(shipped v3.17.669)* —
  seven starter templates (managed IT services, project statement of work,
  recurring support, backup and disaster recovery, security services,
  renewal, amendment or addendum), each marked as sample wording with a review note
  that blocks sending until it is replaced. Customer-only templates,
  template versions (contracts keep the text they were created with), a
  clause library, merge fields and placeholder checks.
- **65.3 Built-in signing** *(shipped v3.17.669)* —
  personal links that need no account, several signers in parallel or in
  order, internal countersignature from the signed-in staff account, typed
  or drawn signatures, consent and intent statements, decline with a
  reason, optional e-mailed 6-digit code, a phone-friendly page with no
  third-party assets, and a downloadable copy. Each signature is bound to
  the exact version and its SHA-256.
- **65.4 Open tracking and alerts** *(shipped v3.17.669)* —
  link requests, likely human views (interaction beacon with a one-use
  nonce) and verified views are kept apart; mail scanners, previewers and
  prefetchers are recognised by a heuristic and never count as views; alerts
  are de-duplicated and repeat-view alerts have a cooldown. Wording never
  claims who opened a link unless the signer verified.
- **65.5 Delivery and reminders** *(shipped v3.17.669)* —
  e-mail with retries ("accepted by the mail server", not "delivered"),
  copy-link, resend, revoke, replace a signer, link expiry, acceptance
  deadline and automatic reminders that stop when the signer signs or the
  contract closes.
- **65.6 Statuses and versions** *(shipped v3.17.669)* —
  draft, pending approval, ready to send, sent, viewed, partially signed,
  signed, declined, expired, voided and superseded, enforced on the server;
  frozen versions, revise, amend, renew, replace and void with a reason;
  approval bound to the exact version and required again after a change.
- **65.7 PDFs and evidence** *(shipped v3.17.669)* —
  an issued PDF per version and a final signed PDF with an audit
  certificate, made without fetching remote resources; an append-only
  timeline; an evidence package with SHA-256 sums.
- **65.8 Dashboard, client record and settings** *(shipped v3.17.669)* —
  search and filters, follow-up, recently viewed, awaiting approval or
  countersignature and upcoming renewals, one-time and recurring values
  shown separately; a Contracts card on the client record; deployment and
  per-customer settings for branding, alerts, reminders, expiry, signing
  rules, e-mail wording and access-log retention.
- **65.9 Permissions** *(shipped v3.17.669)* —
  uses the contract permissions of Phase 64 (64.1) through one helper per
  customer: view, view pricing, edit drafts, manage templates, submit for
  approval, approve (never the version's own author or submitter), send,
  manage signing links, countersign, void, download signed copies, view
  audit evidence and settings. Lists follow the technician's client and
  record scope; alerts are re-checked when they are created and again when
  they are delivered. Internal countersignatures need a signed-in staff
  account with the countersign permission; a customer account signs only as
  an authorized contract signer. External signers use the pages under
  `/sign/`.
- **65.10 Reviewed legal wording** *(planned)* — the starter wording is sample
  text; per-jurisdiction reviewed templates are not included.
- **65.11 Sample contract library** *(shipped v3.17.761)* — twelve starter agreements (month-to-month, 12-month and
  36-month managed services, prepaid block hours, statement of work, time and materials, master services agreement
  with a schedule, and more), each marked as not legal advice; **Use this sample** makes your own editable copy, and
  re-seeding never overwrites your edits.
- **65.12 Contract terms** *(shipped v3.17.761)* — month-to-month, annual, multi-year or custom fixed term with a
  notice period, on contract documents and billing contracts; existing contracts are mapped from their dates and keep
  billing as before.
- **65.13 E-signature before activation, conversion or billing** *(shipped v3.17.761)* — every quote, and every
  contract that is not month-to-month, needs the customer's e-signature before it is accepted, converted, activated
  or billed; changing the signed terms needs a new signature; enforced in models, services, views and scheduled jobs.
  The month-to-month exemption is a setting in Settings → Billing.
- **65.14 Viewed tracking** *(shipped v3.17.761)* — quote, invoice and contract links record first view, last view and
  view count per recipient (staff previews, email scanners and bots are not counted), shown as Sent → Viewed →
  Signed / Accepted / Paid with an audit entry, a webhook and an email to the owner.
- **65.15 Contract follow-ups** *(planned)* — link a signed amendment to an existing billing contract; a no-sign-in
  invoice link for leads; separate links per recipient for quotes; in-app notifications for quote and invoice views.

**Sizing:** **L** — a new app with its own models, background jobs, PDFs and
public signing pages; integrates with PSA billing contracts, the scheduler,
mail settings and roles.

</details>

---

<a id="phase-66"></a>

## Phase 66 — Client pulse checks **(M · client relationship)** [in progress]
<!-- phase: ws=G view=later deps="portal, scheduler" next="66.5 export and reminders" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** G. Customer Portal & Communications · **Depends on:** portal, scheduler  
**Next:** 66.5 export and reminders

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Short, periodic service-feedback surveys the MSP sends to people at its
client organizations, about the relationship as a whole. Separate from the
per-ticket satisfaction survey (Phase 12). An optional module, off by
default (Settings → System → Optional modules → Pulse checks). Setup and use:
[docs/PULSE_CHECKS.md](PULSE_CHECKS.md).

- **66.1 Pulse check templates** *(shipped v3.17.673)* — name, intro text and
  up to twelve questions (1–5 rating, 0–10 likelihood to recommend, yes / no,
  free text), managed by MSP staff; each send keeps a copy of the questions it
  asked.
- **66.2 Audience** *(shipped v3.17.673)* — all active clients or chosen
  organizations; everyone with a portal account (optionally plus contacts
  with an e-mail address), people with chosen roles (owners, managers /
  administrators, editors, read-only, or named roles held as primary or
  additional role), or chosen users and contacts. MSP staff are never
  recipients.
- **66.3 Sending** *(shipped v3.17.673)* — send now with a recipient preview,
  or monthly / quarterly from the scheduler (once per period, safe to rerun);
  one single-use link per person that needs no sign-in and closes after a set
  number of days; portal users can also answer from a Feedback page; opt-out
  from the e-mail or the portal; audit log entries for create, edit and send.
- **66.4 Results** *(shipped v3.17.673)* — response rate, average rating,
  NPS, yes / no share and comments per pulse check and per send, filterable
  by organization; a per-client trend card on the client record for MSP
  staff. Staff limited to some clients see only those clients' answers.
- **66.5 Reports export and reminders** *(planned)* — CSV export of answers
  and a reminder to people who have not answered.

**Sizing:** **M** — a new app (`pulse`) with its own models, staff pages,
portal pages, one scheduled task and an optional-module switch.

</details>

---

<a id="phase-67"></a>

## Phase 67 — Interface, navigation and dashboard redesign **(L · usability)** [in progress]
<!-- phase: ws=I stage=7 view=later deps=64 next="67.8 validation and 67.16 follow-ups" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** I. Deployment, Updates & Reliability · **Depends on:** 64  
**Next:** 67.8 validation and 67.16 follow-ups

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

A cleaner, more compact interface over the same features, URLs and permissions.
Plan and audit: [docs/plans/2026-11-ui-redesign.md](plans/2026-11-ui-redesign.md).
Hiding a link stays presentation only; every page keeps its own server-side check.

- **67.1 One navigation definition** *(shipped v3.17.677)* — the sidebar, the settings
  workspace, top-bar shortcuts and the account menu all come from
  `core/navigation.py`; the separate settings menu is folded in; sidebar
  groups Overview, Operations, Clients & Assets, Business, Tools & Automation,
  Reports & Analytics and Administration.
- **67.2 Every page has a path** *(shipped v3.17.677)* — pages that were reachable only
  by bookmark get a place in the navigation (or are documented as reached from
  their parent page); members and roles reachable for the organization admins
  the pages already admit; a test fails when a new page has no path.
- **67.3 Compact page frame** *(shipped v3.17.677)* — top bar that stays usable on
  1366-px laptops; breadcrumb and section tabs on one row; shortcut pins in
  the sidebar.
- **67.4 Settings workspace** *(shipped v3.17.677)* — nine settings categories (ten since 67.12) with
  secondary navigation, settings search, unsaved-change warnings.
- **67.5 Dashboard that fits the window** *(shipped v3.17.677)* — compact dashboard
  (default) built from permission-checked widgets that fits 1366×768 and up
  without page scrolling; the previous dashboard stays available as Classic.
- **67.6 Dashboard customization** *(shipped v3.17.677)* — show / hide, order and size
  widgets by drag or keyboard, compact or comfortable density, restore
  defaults, built-in role presets and administrator-set role defaults.
- **67.7 Professional Dark theme** *(shipped v3.17.677; every existing profile switched to it v3.17.678)* — default for new profiles,
  wallpaper optional, shared design tokens; existing preferences kept.
- **67.8 Validation** *(partial — per-role navigation and dashboard tests, direct-URL checks and viewport screenshots v3.17.677; customer-role screenshots and a review period before the Classic dashboard is retired planned)* — role matrix with direct-URL denial checks,
  viewport screenshots, regression suite.
- **67.9 Phones and the sign-in page** *(shipped v3.17.679)* — one-row top bar with a
  distinct menu button, wide tables scroll inside their own frame, section tabs scroll
  sideways, phone-sized dashboard panels, ticket list drops secondary columns on small
  screens; sign-in fields stack full width at every size.
- **67.10 Customer Portal settings** *(shipped v3.17.679)* — Settings → General → Customer
  Portal: portal address, branding (name, logo, accent colour, sign-in background and
  welcome message, support contact), layout (top or side navigation, content width,
  default theme), portal features, per-customer portal on/off, country-policy summary.
- **67.11 Ten-section navigation** *(shipped v3.17.680)* — Dashboard, My Work, Service Desk,
  Clients, Assets & Network, Business, Knowledge & Vault, Security & Monitoring, Reports, with
  Administration pinned at the foot; navy sidebar with an icon rail and keyboard-accessible
  flyouts (rail by default on tablets); per-section Configure menus for secondary tools; tab
  strips that never wrap (More menu); breadcrumbs; duplicate labels removed (VLAN Ports vs
  VLANs, one Contracts heading, one Knowledge Base entry). No URL changed.
- **67.12 Settings center** *(shipped v3.17.680)* — Administration opens a searchable page of
  ten categories (General, Users & Access, Security, Integrations, AI Configuration — OPTIONAL
  AI, Automation, Communications, Modules, System, Maintenance), each listing only the pages
  the user may open.
- **67.13 Client workspace** *(shipped v3.17.680)* — the client page becomes a tabbed workspace
  (Overview, Tickets, Assets, RMM, Contacts, Documents, Passwords — names only, Contracts,
  Billing, Projects, Activity, Members) with a KPI row, renewals, open invoices, recent activity
  and permission-aware quick actions; opening it makes the client current, with a way back to
  the MSP-wide view.
- **67.14 Command palette, Favorites and Recent** *(shipped v3.17.680)* — Ctrl+K / Cmd+K
  searches pages, settings, clients, tickets, devices, projects, documents, KB and reports with
  the list pages' own scoping (passwords excluded), plus quick commands; star any page; Recent
  menu; entries vanish when access, the record or the module goes away.
- **67.15 Dashboard KPIs and role layouts** *(shipped v3.17.680)* — compact header with quick
  actions, KPI row (my open, SLA at risk, overdue, unassigned, pending approvals, due today),
  my ticket queue, SLA overview, technician workload, sales pipeline, my time; default layouts
  for admin, manager/dispatcher, L1/L2/L3 technician, sales and customer roles.
- **67.17 Security update alert** *(shipped v3.17.682)* — the update pill, bell and System status
  panel turn red while a release with security fixes (a "Security" section in its notes) is
  newer than the running version.
- **67.16 Follow-ups** *(partial — shipped v3.17.683: sales Quotes/Contracts panels, the
  Escalated ticket view and KPI, ticket-list Unassigned / SLA / Approvals tabs, Security Overview;
  planned: retire the Classic dashboard after the review period — see
  docs/plans/classic-dashboard-retirement.md)*
- **67.18 Ticket workspace tabs** *(shipped v3.17.683)* — Overview, Unassigned, SLA, Escalated and
  Approvals views of the ticket list with filters in the URL; assignment from the Unassigned view
  and the dispatch board; one SLA definition shared with the dashboard.
- **67.19 Security Overview** *(shipped v3.17.683)* — read-only operational page: alerts,
  incidents, RMM security, monitoring and response times, each panel gated by its source page;
  "Not configured" / "No data" instead of zero; alert → incident → device → RMM links.
- **67.20 Global View, sales and manager dashboards, role dashboards** *(shipped v3.17.683)* —
  all-clients widget dashboard scoped to the clients a role reaches; quotes, contracts, pipeline
  and team utilization panels; per-role widgets, quick actions, landing page and sidebar default
  (remove-only).
- **67.21 Workflow polish** *(shipped v3.17.683)* — back-to-ticket links, sidebar-matching
  breadcrumbs, settings search synonyms and "/" shortcut, access-denied page, favorite indicator,
  phone menu as a modal; security review of search, workspace, audit and map data.
- **67.22 Layout and help follow-ups** *(shipped v3.17.684)* — sidebar stays in view on long
  pages, table columns break between words, help diagrams redrawn in the current layout.
- **67.23 Business Overview tile alignment** *(shipped v3.17.739)* — tiles in a row line up: title, figure,
  chart and footer at the same height whatever each card contains.
- **67.24 Dark-theme contrast for category headings** *(shipped v3.17.739)* — knowledge-base category rows
  and count badges no longer show a near-white bar in dark themes.
- **67.25 Faster page loads** *(shipped v3.17.745)* — the sidebar's permission decisions are kept per worker and dropped the moment any access changes; system settings are read once per request; reloading a page no longer writes to the database; Font Awesome, DataTables, Select2, Leaflet and jQuery are served from the app; SQLite installs run in WAL mode with a busy timeout, and every backup and restore goes through SQLite's backup API. Server render time roughly halved (about 55–115 ms per page on the production dataset). Second pass *(shipped v3.17.758)*: the sidebar and settings header HTML is reused when unchanged, the customer tree, memberships and ticket priorities are read once per request, ticket billing lines read prepaid postings and agreements once, and per-page query ceilings are tested — 20–50% less server time per page and 40–60% fewer queries for technicians. The sign-in activity stamp is saved at most once a minute instead of on every page *(shipped v3.17.759)*.

**Sizing:** **L** — navigation and settings, dashboard, visual system, then
validation across roles and viewports.

</details>

---

<a id="phase-68"></a>

## Phase 68 — Commercial price book and service plans **(L · sales)** [in progress]
<!-- phase: ws=B view=later deps=15 next="68.1 staff screens; 68.2 plans on contracts; 68.4 distributor price" note="Prerequisite of 103" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** B. Billing & Financial Management · **Depends on:** 15  
**Next:** 68.1 staff screens; 68.2 plans on contracts; 68.4 distributor price  
**Note:** Prerequisite of 103

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

A single priced catalog and named service plans, so quotes, contracts and invoices stop typing prices by
hand. Audit: [docs/plans/COMMERCIAL_OPS_AUDIT.md](plans/COMMERCIAL_OPS_AUDIT.md). Separate from the ticket
request catalog (`ServiceCatalogItem`).

- **68.1 Price book and products** *(partial — models and Django admin shipped v3.17.692; staff screens and a caller of the price lookup in quotes and invoices planned, Phase 103)* — products and services with SKU,
  unit, cost, list price and markup.
- **68.2 Service plans** *(partial — plans shipped v3.17.692; billing contracts cannot reference a plan yet and plan prices are read only by onboarding drafts)* — named plans (included hours, meters, bundled
  items) that a contract can reference.
- **68.3 Catalog links on quote, invoice and contract lines** *(partial — line fields and price snapshot shipped v3.17.692; picking items in the quote and invoice editors planned)* — optional product reference on
  each line type.
- **68.4 Distributor price into the price book** *(planned)* — copy distributor pricing at quote time.

**Sizing:** **L** — models and admin, then line-level integration across quotes, contracts and invoices.

</details>

---

<a id="phase-69"></a>

## Phase 69 — Labor rate cards and cost rates **(M · billing)** [in progress]
<!-- phase: ws=B view=later deps="2, 68" next="69.1–69.3 rates used by invoicing (with 101.4); 69.4" note="Prerequisite of 101" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** B. Billing & Financial Management · **Depends on:** 2, 68  
**Next:** 69.1–69.3 rates used by invoicing (with 101.4); 69.4  
**Note:** Prerequisite of 101

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **69.1 Rate cards** *(partial — shipped v3.17.692 for reporting; invoicing still prices ticket time at the contract rate, or $0 without a contract — fixed in Phase 101)* — bill rates by role, client and ticket type, with
  effective dates.
- **69.2 Rate snapshots on time entries** *(partial — snapshots stored v3.17.692; not yet used by invoicing, and the time screens never set after-hours or holiday rate types)* — bill and cost rate stored on
  each entry so history does not drift.
- **69.3 Remove placeholder rates** *(partial — profitability and reports v3.17.692; the $60 loaded-rate fallback is still used in resourcing)* — replace the 60% cost assumption and the fixed fallback
  rates in profitability and reports with real rate lookups.
- **69.4 Effective-dated billable targets** *(planned)*.

**Sizing:** **M** — rate models, time-entry snapshot, then report changes.

</details>

---

<a id="phase-70"></a>

## Phase 70 — Contracts, recurring billing and quote conversion **(M · P0 · billing)** [in progress]
<!-- phase: ws=B stage=1 view=next order=3 deps="65, 68, 69" next="70.1 quote to contract, 70.2 quote to invoice" -->
**Status:** 🔵 In progress · **Priority:** P0 · **Workstream:** B. Billing & Financial Management · **Depends on:** 65, 68, 69  
**Next:** 70.1 quote to contract, 70.2 quote to invoice

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **70.1 Quote to contract** *(planned · P0)* — accepting a quote can create a billing contract after a conversion
  review: selected package, inclusions and exclusions, recurring and one-time charges, included and block hours,
  overage rates, quantities, term, frequency, payment terms, effective dates, renewal and SLA carried across;
  idempotent (a retry or reopened quote never creates a second contract, invoice or project); the signed legal
  document (Phase 65) and the billing contract stay distinct and are linked.
- **70.2 Quote to invoice** *(planned · P0)* — one-off lines copied to an invoice using the existing source link;
  never the whole contract value up front unless agreed, no one-time charge for a recurring item, prices frozen at
  acceptance, lines reference the quote and catalog item.
- **70.3 Signed document to billing contract** *(partial — a signed document creates a draft billing contract with the header fields; line items, hours and rates planned)* — carry line items, hours, rates and next billing
  date across.
- **70.4 Bill bundle items and recurring charges** *(planned)*.
- **70.5 Database uniqueness for recurring invoices** *(shipped v3.17.690)* — constraint on contract and billing period.

**Sizing:** **M** — conversions and the recurring-billing hardening.

</details>

---

<a id="phase-71"></a>

## Phase 71 — Accounting sync completion **(L · accounting)** [in progress]
<!-- phase: ws=B view=later deps=44 next="71.4–71.8 accounting completion; 71.11 sandbox verification" blocker="Provider capabilities verified only against mocks" unblock="QuickBooks Online and Xero sandbox accounts" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** B. Billing & Financial Management · **Depends on:** 44  
**Next:** 71.4–71.8 accounting completion; 71.11 sandbox verification  
**Blocked:** Provider capabilities verified only against mocks — *unblocks when:* QuickBooks Online and Xero sandbox accounts

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Builds on Phase 44, which covers customer sync, invoice create and payment pull for QuickBooks Online and Xero.

- **71.1 Invoice push safety** *(shipped v3.17.690)* — no duplicate invoice after a
  timeout, idempotency keys, row lock on push.
- **71.2 QuickBooks Online mapping fixes** *(shipped v3.17.690 — GL code to Item mapping)* — correct item and account references.
- **71.3 Xero payment account setting** *(shipped v3.17.690)* — replace the bank account placeholder.
- **71.4 Invoice update, credit memos, refunds and voids** *(planned)*.
- **71.5 Tax-code mapping** *(planned)*.
- **71.6 Payment posting to the provider** *(partial — QuickBooks Online and Xero adapters exist, nothing calls them yet)*.
- **71.11 Sandbox verification** *(planned)* — every QuickBooks Online and Xero capability exercised against a
  real sandbox company before it is called production ready; today all provider tests use mocked HTTP.
- **71.7 Webhooks with signature checks** *(planned)*.
- **71.8 Retry queue and error review** *(planned)*.
- **71.9 Other providers** *(planned)* — after QuickBooks Online and Xero, additional accounting providers
  as demand and real-provider testing allow.
- **71.10 Billing-event integrity** *(partial — one invoice per contract period shipped v3.17.690)* — stable internal billing-event
  IDs, idempotency keys, durable sync queue, reconciliation and duplicate detection; ambiguous submissions
  are reconciled before any retry; posted invoices changed only via provider amendment, void or credit memo.

**Sizing:** **L** — safety fixes first, then provider capabilities one at a time.

</details>

---

<a id="phase-72"></a>

## Phase 72 — Payment processing and sales tax **(L · payments)** [in progress]
<!-- phase: ws=B view=later deps=71 next="Provider verification; payment posting to accounting" blocker="Payment providers verified only against mocks" unblock="Payment provider sandbox accounts" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** B. Billing & Financial Management · **Depends on:** 71  
**Next:** Provider verification; payment posting to accounting  
**Blocked:** Payment providers verified only against mocks — *unblocks when:* Payment provider sandbox accounts

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **72.1 Stripe** *(shipped v3.17.690 — needs verification with test-mode keys)*.
- **72.2 GoCardless** *(shipped v3.17.690 — needs verification with sandbox keys)*.
- **72.3 Portal billing** *(shipped v3.17.690)* — invoices, balances and online payment for
  customers.
- **72.4 Payment webhooks, refunds and idempotency** *(shipped v3.17.690; posting payments to accounting planned under 71.6)*.
- **72.5 Tax providers** *(shipped v3.17.690 — needs verification with sandbox credentials)* — real Avalara and TaxJar calls, and no silent zero tax on failure.
- **72.6 Quote tax default** *(shipped v3.17.690)* — warn instead of defaulting to zero.

**Sizing:** **L** — provider code needs sandbox testing before release.

</details>

---

<a id="phase-73"></a>

## Phase 73 — Procurement, distributors, licensing and warranty lifecycle **(L · procurement)** [in progress]
<!-- phase: ws=C view=later deps="4, 13, 68" next="73.2–73.6 ordering, receiving, warranty" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** C. Asset Management & Documentation · **Depends on:** 4, 13, 68  
**Next:** 73.2–73.6 ordering, receiving, warranty

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **73.1 Software licensing** *(shipped v3.17.699 — Google Workspace planned)* — license subscriptions,
  seat assignments, renewals and utilization alerts; Microsoft 365 and Pax8 sync; per-customer monthly
  license cost feeds the Pricing Advisor (a subscription without a unit cost leaves the cost unknown).
- **73.2 Distributor ordering** *(planned)* — submit purchase orders to distributors, order status.
- **73.3 Distributor adapters** *(planned)* — production endpoints, TD SYNNEX catalog, further
  distributors.
- **73.4 Receiving to inventory and assets** *(planned)* — stock movements, complete asset records, no
  swallowed errors.
- **73.5 Warranty consolidation** *(planned)* — one warranty lookup path and credential store.
- **73.6 Asset acquisition cost and replacement history** *(planned)*.
- **73.7 Vendor bills** *(planned)*.

**Sizing:** **L** — licensing first, then procurement wiring.

</details>

---

<a id="phase-74"></a>

## Phase 74 — Backup monitoring, backup management and endpoint health **(XL · P1 · backup)** [in progress]
<!-- phase: ws=D stage=2 view=next order=8 deps="63, 82; St0r API (74.7)" next="74.8 Comet read-only provider; 74.9 overview; 74.7 when the St0r API lands" blocker="74.7 needs St0r’s integration API (in development, St0r PR #54)" unblock="St0r ships /api/v1 with scoped tokens" -->
**Status:** 🔵 In progress · **Priority:** P1 · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 63, 82; St0r API (74.7)  
**Next:** 74.8 Comet read-only provider; 74.9 overview; 74.7 when the St0r API lands  
**Blocked:** 74.7 needs St0r’s integration API (in development, St0r PR #54) — *unblocks when:* St0r ships /api/v1 with scoped tokens

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **74.1 Backup monitoring framework** *(shipped v3.17.695)* — jobs, runs, repositories with capacity,
  restore tests, alert policies and alerts (with tickets), customer and device views, MSP-wide connections
  with per-customer mapping. Stale data is shown as stale, never healthy. See `docs/BACKUP_MONITORING.md`.
- **74.2 Standalone backup providers** *(partial — Proxmox Backup Server polling and signed push reports
  for restic, Borg and Kopia shipped v3.17.695; commercial products planned)* — commercial products as they
  can be tested.
- **74.3 Rem0te backup and endpoint health** *(planned)* — needs additions to the Rem0te contract.
- **74.4 Security product adapters** *(moved to 84.5 — one plan for security vendor connectors)* — replace the Defender stub; further vendors.
- **74.5 Device workspace panels** *(partial — backup panel shipped v3.17.695; security and events planned)*.
- **74.6 Compliance backup evidence** *(shipped v3.17.695 — the evidence pack reads backup monitoring data; audit 2026-11-20)* — replace the hard-coded zero.

**Added 2026-11-20 — unified backup management (P1).** Extends the framework above; no second backup module and
no backup engine inside Clientst0r. Every provider is an implementation of the existing provider interface
(`backup_monitoring/providers/base.py`) feeding the same jobs, runs, repositories, restore tests, alerts and
tickets. Several connections per provider are already supported (MSP-wide or per customer); each new provider
keeps that. Specification: `docs/plans/backup-integrations/README.md`.

- **74.7 St0r / UrBackup provider** *(planned — read-only first; needs a versioned service API in St0r)* —
  several St0r installations, each mapped to one or more customers and sites; protected clients, file and
  image backup status, last success and failure, job history, running jobs, storage, retention, replication
  status and lag, restore-test results and server health, as far as St0r's API provides them. Clientst0r never
  reads St0r's database or UrBackup's files. St0r API requirements are recorded in the St0r repository roadmap.
- **74.8 Comet Backup provider** *(planned — read-only first)* — several Comet Management Servers; users,
  devices, protected items, storage vaults, policies, job history, last success, storage use, retention,
  restore activity and licensing counts through the documented admin API, using an administrator account
  limited to the needed permissions. Devices map to existing assets by stable provider identifiers; no
  duplicate inventory records. Deep links to the Comet console for devices, protected items and history.
- **74.9 Backup overview and protection coverage** *(planned)* — one page across all providers: customer, site,
  device, provider, protection status, last success, backup age against the RPO, replication, restore
  verification, storage, open alerts and related tickets, filterable. Coverage compares the asset inventory
  with provider inventories: verified, failed, overdue, not protected, unknown. A device whose backup identity
  is not yet matched is **unknown**, never "unprotected"; uncertain matches wait in a review queue. Backup
  success, replication success, restore verification and recoverability are separate states; none is
  inferred from another.
- **74.10 Backup alerts on the event layer** *(planned)* — failed, missed and overdue-against-RPO backups,
  unprotected devices, storage near capacity, replication failure and lag, failed restore tests, server
  offline; deduplicated by provider event identity so repeated delivery never opens a second ticket; flows
  into the existing alert-to-ticket policy and the Phase 82 event layer. A ticket closes only after a later
  successful backup or a recorded technician decision.
- **74.11 Permissioned backup actions** *(planned — after 74.7–74.10)* — start a backup, view schedules,
  configuration and retention, request a restore and follow its status, where the provider's API supports it
  (checked per connection from the provider's reported capabilities). Restores and anything destructive need
  a permission of their own, step-up authentication and an audit record; ordinary technicians never get
  provider-administrator operations.
- **74.12 Backup reports** *(planned)* — per-customer protection and restore-verification report (PDF/CSV),
  feeding the evidence pack (74.6) and service reviews (89.2).

Customer-portal backup status is 77.8; backup billing from verified counts is 92.6.

**Sizing:** **L** — framework, then providers, then Rem0te contract changes.

</details>

---

<a id="phase-75"></a>

## Phase 75 — Profitability analytics, customer commercial portal, onboarding wizard and executive dashboard **(L · analytics)** [in progress]
<!-- phase: ws=H stage=5 view=later deps="68–74" next="75.2 customer commercial portal; 75.5 permissions" -->
**Status:** 🔵 In progress · **Priority:** P3\* · **Workstream:** H. Reporting, Analytics & Optional AI · **Depends on:** 68–74  
**Next:** 75.2 customer commercial portal; 75.5 permissions

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **75.1 Profitability analytics** *(shipped v3.17.692; audit 2026-11-20: reports use three revenue definitions — one includes tax, one counts unbilled bundles, one uses contract terms — unified in Phase 102.7)* — margin by client, contract, plan and service line from
  rate snapshots.
- **75.2 Customer commercial portal** *(planned)* — plans, invoices, device health and backup status.
- **75.3 Commercial onboarding wizard** *(shipped v3.17.700)* — new-customer onboarding (customer, locations,
  quantities, service plan and add-ons from the price book, contract template, SLA, billing, accounting mapping,
  payment, RMM, backup, warranty, draft quote or agreement, approval, activation) and lifecycle changes (plan
  change, users, devices, locations, renewal, price increase, offboarding). Commercial changes are drafts that go
  through approval; missing prices stay missing.
- **75.4 Executive dashboard** *(shipped v3.17.693 — backup and license cards follow those modules)* — recurring revenue, margin, renewals and receivables.
- **75.5 Commercial permissions** *(partial — pricing, profitability, payments and tax permissions shipped v3.17.690–692)* — roles for rates, cost visibility and payments.
- **75.6 Executive dashboard drill-down** *(shipped v3.17.693)* — drill from every metric to the
  underlying records, with date, customer, service-line and location filters; estimates labelled as not
  accounting-certified.

**Sizing:** **L** — depends on Phases 68–74.

</details>

---

<a id="phase-76"></a>

## Phase 76 — Profitability and pricing advisor **(L · OPTIONAL AI)** [shipped — v3.17.696]
<!-- phase: ws=E -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** E. Sales & CRM

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 76](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-76).

---

<a id="phase-77"></a>

## Phase 77 — Customer command center portal **(XL · portal)** [planned]
<!-- phase: ws=G stage=5 view=later deps="72, 73, 74" next="77.1 unified customer dashboard" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** G. Customer Portal & Communications · **Depends on:** 72, 73, 74  
**Next:** 77.1 unified customer dashboard

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **77.1 Unified customer dashboard** *(planned)* — sections for IT health, backup and recovery, services and
  contracts (plan, allowances, renewals), licensing, service desk, financial (invoices, payments, quotes,
  receipts and provider-hosted payment methods), maintenance and communications.
- **77.2 Customer self-service requests** *(planned)* — new and removed users, licenses, hardware, upgrades,
  services, quote and purchase approvals, contract review, tickets, and invoice download and payment. Anything
  affecting pricing, contracts, security or infrastructure requires MSP approval.
- **77.3 Multi-location views** *(planned)* — tenant and location-level permissions.

Depends on Phases 72, 73 and 74.

**Added 2026-11-20 (planned):**

- **77.8 Backup status for customers** — protected-device counts, backup health, latest backup and restore
  verification, backup-related tickets; never backup contents or internal provider configuration. Needs 74.9.
- **77.9 Maintenance notices and managed assets** — scheduled maintenance from the status page and the
  customer's managed devices (with MDM compliance once Phase 106 lands), filtered by portal permissions.

**Sizing:** **XL** — the largest portal surface; split into release-sized slices by section.

</details>

---

<a id="phase-78"></a>

## Phase 78 — Customer health score **(M)** [in progress]
<!-- phase: ws=H stage=5 view=later deps="66, 74, 75" next="78.6 portal display" -->
**Status:** 🔵 In progress · **Priority:** P3\* · **Workstream:** H. Reporting, Analytics & Optional AI · **Depends on:** 66, 74, 75  
**Next:** 78.6 portal display

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **78.1 Health dimensions** *(shipped v3.17.695)* — technical, security, backup, service delivery, commercial and
  satisfaction. Satisfaction reuses the client pulse checks from Phase 66.
- **78.2 Signals** *(partial — RMM devices, security alerts and incidents, backup jobs, alerts and restore
  tests, SLA, ticket volume, reopen rate, overdue invoices, renewals, payment failures, profitability and
  pulse checks shipped v3.17.695; utilization planned)*.
- **78.3 Configurable weights** *(shipped v3.17.695)* — per-signal weights and status thresholds.
- **78.4 Explanations** *(shipped v3.17.695)* — each change is explained with the contributing records.
- **78.5 Unknown is not healthy** *(shipped v3.17.695)* — unknown or stale data is shown as unknown, never as healthy.

- **78.6 Customer portal display** *(planned)* — staff-only today.

**Sizing:** **M** — scoring model and explanations first, then dashboard and portal display.

</details>

---

<a id="phase-79"></a>

## Phase 79 — Agit8or Connect: secure application-to-application integration **(XL · integrations)** [in progress]
<!-- phase: ws=D view=next order=10 deps="Rem0te contract" next="79.21 public Agit8or Connect repository (needs the owner to create agit8or1/agit8or-connect); then interoperability tests between two installations and the security review (Quick Connect increments F, G, H)" blocker="79.6 is Rem0te work; 79.7 would duplicate Phase 63 over a second channel" unblock="Decision on one Rem0te channel; Rem0te Stage 8" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** D. RMM & Platform Integrations · **Depends on:** Rem0te contract  
**Next:** 79.21 public Agit8or Connect repository (needs the owner to create agit8or1/agit8or-connect); then interoperability tests between two installations and the security review (Quick Connect increments F, G, H)  
**Blocked:** 79.6 is Rem0te work; 79.7 would duplicate Phase 63 over a second channel — *unblocks when:* Decision on one Rem0te channel; Rem0te Stage 8

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

A reusable, self-hosted standard for Agit8or applications to discover, pair, authenticate and exchange
events with each other, starting with Clientst0r and Rem0te. It runs alongside the existing
`ticket-rmm-v1` link, which keeps working unchanged.

- **79.1 Protocol and SDKs** *(shipped v3.17.692)* — versioned protocol and OpenAPI spec;
  Python and TypeScript SDKs checked against shared test vectors.
- **79.2 Pairing and credentials** *(shipped v3.17.692)* — single-use, short-lived pairing
  codes with administrator approval on the receiving side; a key pair per connection; short-lived access
  tokens; no long-lived shared API keys.
- **79.3 Permissions and customer grants** *(partial — framework and three read/publish scopes shipped v3.17.692)* — human-readable scopes in
  risk tiers; explicit per-customer grants; per-grant revocation and an emergency disconnect.
- **79.4 Signed events and webhooks** *(shipped v3.17.692 — incoming events are stored; acting on them is planned)* — signed, replay-protected
  delivery with retries and a failed-delivery queue.
- **79.5 Connection wizard and credential dashboard** *(shipped v3.17.692)* — off by default
  until enabled by an administrator.
- **79.6 Rem0te side** *(planned)* — implemented in the Rem0te repository against the shared contract.
- **79.7 Device sync, alert tickets, ticket-to-device and approved remote actions over Connect** *(planned)*.

**Secure HTTPS Quick Connect** — guided, default-deny connection setup on top of this protocol; audit, design and increment plan in [docs/plans/quick-connect/](plans/quick-connect/AUDIT.md). Connect stays off by default; Quick Connect is not offered on production installations until 79.23 and 79.24 pass.

- **79.8 Connect hardening from the Quick Connect audit** *(shipped v3.17.743 — findings QC-04, 08, 09, 10, 11, 12, 14 fixed and QC-03 in part; the SDK's fallback transport loopback gap moves to 79.12)* — outbound requests never reach loopback or link-local addresses and use only the approved port, approvals respect the kill switch, a public address is required before pairing, unauthenticated refusals no longer grow the audit log, and a request claiming an existing installation needs a second administrator.
- **79.9 Browser-mediated bootstrap** *(shipped v3.17.748 — off by default behind a per-installation Quick Connect switch; serves qc-bootstrap and qc-source-binding, the diagnostics probe follows with 79.18)* — the administrator authorises the connection in the other application's own admin page; a short-lived, single-use, signed invitation and an authorization code with PKCE replace typed codes; no password ever passes between applications.
- **79.10 Default-deny source policy for Connect** *(shipped v3.17.746)* — Connect endpoints refuse every address until one is authorised, with IPv4 and IPv6 addresses and ranges, explicit deny winning, no allow-all and no implicit trust for private addresses, checked before any authentication and independent of the general API settings; reuses the API access policy engine.
- **79.11 Per-connection inbound addresses** *(shipped v3.17.746)* — a second, per-connection allowlist that every request must also pass; a request is bound to the connection whose address rule it matched, so shared NAT addresses stay separated by key; unexpected sources are refused and shown, never added automatically.
- **79.12 Approved outbound destinations** *(shipped v3.17.746 — includes the SDK fallback transport's loopback fix)* — per connection: host, port, approved addresses, trust anchor and expected identity; every resolved and connected address is checked against the approved set; an address change blocks the connection until an administrator approves it and it is retested.
- **79.13 Two-sided authorization** *(shipped v3.17.750)* — each side approves permissions, customers and the other side's source address independently; the reverse direction is its own approval; elevated permissions and widening network changes need a second administrator.
- **79.14 Staged configuration changes** *(shipped — network changes v3.17.746, permission and customer changes v3.17.750)* — network and permission changes are staged with a preview of who gains or loses access, approved, and committed atomically; rollback only ever narrows access; changes reach every worker through a policy version.
- **79.15 Certificate verification and pinning** *(shipped v3.17.746)* — certificates are always verified, an IP address is accepted only when the certificate names it, a private CA can be set per connection, and an optional public-key pin is available; a failure blocks the connection.
- **79.16 Connection health states** *(shipped v3.17.752)* — Pending Setup, Awaiting Approval, Awaiting Network Authorization, Testing, Connected, Degraded, Offline, Security Blocked, Suspended and Revoked, from separate transport, TLS, authentication, authorization and operational checks every 60 seconds with jitter and hysteresis; "Connected" only after every test passed.
- **79.17 Automatic reconnection** *(shipped v3.17.752 — the delay ladder uses ±20% jitter so waits never fall near zero)* — backoff from 10 seconds to 15 minutes with jitter and a circuit breaker, restart-safe on the scheduler; never after a revocation, suspension, identity or certificate change, unauthorised address or other security failure, and the evidence of a security failure is kept.
- **79.18 Event queue recovery** *(shipped v3.17.752)* — events wait while a peer is offline instead of being used up by retries, drain in order on recovery, expire by age, and can be requeued from the failed list.
- **79.19 Connection alerts** *(shipped — email, system warnings and the bell v3.17.752; event layer, webhook, muting and a ticket per incident v3.17.754)* — status changes go through the shared event layer and existing notification channels, with deduplication, rate limits, muting and recovery notices; an optional ticket per incident, never one per check.
- **79.20 Connection diagnostics** *(shipped — fifteen checks v3.17.752; history tab, redacted export, diagnostics in the activation gate and a full run every 15 minutes v3.17.754)* — fifteen independent checks from DNS to reverse connectivity, each with a result, explanation, next step, error code and time, a run history, and a redacted export.
- **79.21 Public Agit8or Connect standard** *(planned)* — a public repository with the specification, OpenAPI, message schemas, test vectors, conformance tests, a reference peer, examples and an integration guide; this repository keeps a pinned copy.
- **79.22 SDK updates for protocol revision 1.1** *(partial — specification, OpenAPI, test vectors and Python/TypeScript SDK support shipped v3.17.747; publishing in the public repository is 79.21)* — Python and TypeScript support for the optional bootstrap, source-binding and diagnostics extensions with new test vectors; version 1 messages and vectors unchanged, so version 1 peers keep working.
- **79.23 Independent interoperability testing** *(planned)* — Clientst0r and the reference peer connect over real HTTPS on one host, covering both pairing flows, address and certificate changes, outages and recovery, without changes to host firewalls, DNS or proxies.
- **79.24 Security review of Quick Connect** *(planned)* — an independent review, an updated threat model and limitations, and owner sign-off before Quick Connect is offered on production installations.
- **79.25 Quick Connect wizard** *(shipped — wizard v3.17.748, connection test before Connected v3.17.750; automatic retests follow with 79.16–79.18)* — enter a host name or address (HTTPS on 443 by default), check the network and certificate, authorise in the other application, compare the code, choose permissions and customers, allow the other side's address, watch the tests, and only then see Connected.

**Sizing:** **XL** — protocol and Clientst0r side first, then the Rem0te side, then integration features.

</details>

---

<a id="phase-80"></a>

## Phase 80 — Agit8or Identity: single sign-on for people **(L · security)** [in progress]
<!-- phase: ws=F view=later deps=Keycloak next="80.4 Keycloak deployment; 80.5; 80.6" blocker="80.4 Keycloak deployment requires approval" unblock="Owner approves a Keycloak deployment" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** F. Security & Administration · **Depends on:** Keycloak  
**Next:** 80.4 Keycloak deployment; 80.5; 80.6  
**Blocked:** 80.4 Keycloak deployment requires approval — *unblocks when:* Owner approves a Keycloak deployment

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Single sign-on across Agit8or applications through a shared, self-hosted Keycloak, using standard OpenID
Connect. Each application keeps making its own authorization decisions; signing in to one application never
grants access to another. Kept separate from Agit8or Connect (separate keys, audiences, revocation and audit).

- **80.1 Architecture and migration plan** *(in progress)* — design documents; nothing is deployed without
  approval.
- **80.2 Web "sign out everywhere"** *(shipped v3.17.689)* — per-user session cut-off; sign out other
  sessions or everywhere; automatic on password and 2FA changes and on deactivation; administrator sign-out.
- **80.3 OpenID Connect sign-in client** *(shipped v3.17.690 — not yet verified against a live Keycloak)* — works with any certified
  provider; off by default; local, Microsoft and LDAP sign-in unchanged.
- **80.4 Keycloak deployment** *(planned)* — requires approval.
- **80.5 Single sign-on between Clientst0r and Rem0te** *(planned)*.
- **80.6 Customer portal users** *(planned)*.

**Sizing:** **L** — client and session work first, then the identity server, then cross-application sign-on.

</details>

---

<a id="phase-81"></a>

## Phase 81 — API access control and network restrictions **(L · security)** [shipped — v3.17.718]
<!-- phase: ws=F -->
**Status:** ✅ Complete · **Priority:** — · **Workstream:** F. Security & Administration

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 81](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-81).

---

<a id="phase-82"></a>

## Phase 82 — Shared operational event and alert foundation **(L · monitoring)** [in progress]
<!-- phase: ws=D view=later deps=81 next="82.13 health reports over Connect; 82.3 per-connection rate limits; first consumers" -->
**Status:** 🔵 In progress · **Priority:** — · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 81  
**Next:** 82.13 health reports over Connect; 82.3 per-connection rate limits; first consumers

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

One normalized layer over the alert sources that exist today — security alerts, RMM and Rem0te alerts,
backup alerts and website / WAN monitors — instead of a new alert engine per feature. Each source keeps its
own model; the shared layer is what the Operations Center, wallboards, correlation, notifications and reports
read.

- **82.1 Normalized event and alert envelope** *(shipped v3.17.719 — security, RMM, Rem0te, backup and website-monitor alerts projected; address, account and IOC fields are filled as connectors supply them, Phase 84)* — customer, source and connection, vendor event ID,
  type, times, severity, confidence, rule, asset and endpoint, addresses, account, MITRE ATT&CK mapping, IOC
  references, deduplication key, correlation group and a size-capped raw-event reference.
- **82.2 One alert ↔ incident ↔ ticket link** *(shipped v3.17.719 — existing source links copied, manual linking per customer)* — replaces the five per-source ticket links for new
  work; alert, incident and ticket lifecycles stay separate, synchronized only on purpose.
- **82.3 Bounded ingestion** *(partial — scheduler queue with time budget, backpressure cap, retries, dead letters and idempotent projection shipped v3.17.719; webhook payload caps since v3.17.716; per-connection rate limits come with the push connectors)* — scheduler-driven queues with backpressure, retries, a dead-letter
  table, idempotency, per-connection rate limits and payload caps; a failing source cannot slow the Service
  Desk.
- **82.4 Retention and storage quotas** *(shipped — install-wide retention, raw-payload pruning and an event quota v3.17.719; per-source and per-customer retention v3.17.720)* — per-customer and per-source retention, raw-event
  pruning and quotas, sized for the SQLite and PostgreSQL deployments.
- **82.5 Ingestion health** *(shipped v3.17.719)* — last successful ingestion, error counts and diagnostics per source;
  monitoring of the monitoring.
- **82.6 Permissions and feature switches** *(partial — ingestion switch v3.17.719; permission keys and the Security Analyst / Security Administrator roles v3.17.720 (Level 1–3 Technician roles extended); the correlation, automation and AI analysis switches arrive with those features in Phases 85, 86 and 90)* — new permission keys and seeded roles (Level 1–3
  technician, Security Analyst, Security Administrator), all editable; module switches for ingestion,
  correlation, automation and AI analysis.

**Monitoring health and reliability** — added 2026-11-21 from community feedback (GitHub Discussion
[#161](https://github.com/agit8or1/clientst0r/discussions/161), credit: **Dijar Vrella**). A dashboard that
shows "0 alerts" might be a quiet, healthy customer — or a collector that could not read the source at all
(expired credentials, a removed API permission, an unreachable endpoint, events that could not be stored). Zero
alerts is not evidence of health unless collection is verified, so a failed, stale or unverified source is never
presented as healthy. These items implement the
[Monitoring Health Standard 1.0.0](https://github.com/agit8or1/clientst0r/blob/main/docs/standards/MONITORING_HEALTH_STANDARD.md),
the shared contract for Clientst0r and later MSPZero products.

- **82.7 Source-health telemetry** *(shipped v3.17.NNN)* — four independent fields per monitoring source
  (operational health, collection outcome, alert status, failure reason) plus last attempt, last success,
  query window, records retrieved / processed / committed / rejected, newest verified event time, duration,
  consecutive failures, completeness, freshness threshold and a redacted diagnostic; stored on the existing
  integration health record and written by polled security connectors, RMM sync and polled backup connections.
- **82.8 Empty-window verification and failure classification** *(shipped v3.17.NNN)* — an HTTP error,
  refused permission or malformed response is never an empty result; an empty window is healthy / quiet only
  after a bounded, read-only probe or an authenticated connection test in the same attempt, otherwise
  unverified; the newest event comes from validated timestamps (never the first record unless the provider
  documents ordering) or is unknown; the collection cursor moves only after a complete window.
- **82.9 Monitoring reliability view and dashboard status** *(shipped v3.17.NNN)* — Security & Monitoring →
  Events → Monitoring reliability: per-customer roll-up with drill-down to each source (icon, text and tooltip,
  last successful collection), a tenant-scoped JSON feed (schema 1.0.0); the Security Overview says whether
  alert collection is verified; the Business Overview security and backup cards are marked incomplete while a
  source behind them is not verified; the customer security digest sends "all clear" only when monitoring is
  verified. Shared RMM connections count against every customer whose devices they serve.
- **82.10 Recovery and alerting** *(shipped v3.17.NNN)* — exponential backoff with jitter that honours
  Retry-After, transient failures Degraded until they persist, per-source freshness thresholds evaluated every
  minute, one technician e-mail when a critical source fails persistently or goes stale and one on recovery,
  system warnings while it lasts, every state change in the audit log; nothing is disabled or suppressed
  automatically.
- **82.11 AI visibility safeguards** **OPTIONAL AI** *(shipped v3.17.NNN for incident summaries)* — health is
  decided by deterministic code; AI incident summaries receive the source-health facts (no credentials, errors
  or event content) and any summary for a customer whose monitoring is not verified leads with the
  deterministic visibility statement, e.g. "Zero threats detected in the successfully monitored sources.
  Monitoring is not verified for Microsoft Defender (source unavailable), so overall security status cannot be
  verified." Phase 90 must use the same context and guard.
- **82.12 Monitoring Health Standard and conformance tests** *(shipped v3.17.NNN — standard 1.0.0, JSON
  Schema, example payloads, validator and conformance cases C1–C13 and C15; C14 waits for 82.13)* —
  acceptance tests A–J from Discussion #161 (verified quiet window, missing permission, failed ingestion,
  endpoint unavailable, stale, unordered results, partial ingestion, AI reporting, tenant isolation, recovery).
- **82.13 Health reports from other products** *(planned — needs a new Connect event type)* — products such as
  Rem0te report schema 1.0.0 records over Agit8or Connect (`events:publish`, granted customers only); a product
  that stops reporting shows stale. Specified in the standard, section 11.
- **82.14 Security vendor probes** *(planned — with the Phase 84 connectors)* — each real vendor connector
  implements its provider-specific bounded probe; until then vendor connections without an API adapter are
  push-only and shown as unverified when quiet.

**Sizing:** **L** — envelope and links first, then queueing, retention and health.

</details>

---

<a id="phase-83"></a>

## Phase 83 — NOC/SOC wallboards and secure display pairing **(XL · monitoring)** [planned]
<!-- phase: ws=H stage=6 view=later deps=82 next="83.1 presentation mode" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** H. Reporting, Analytics & Optional AI · **Depends on:** 82  
**Next:** 83.1 presentation mode

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends the wallboards shipped in the Reports module (12-column boards, rotation and permission-checked
widget sources) into large-screen operations displays.

- **83.1 Presentation mode** *(planned)* — dedicated dark display theme, viewport-fitted grid that scales from
  1080p to 4K without page scrolling, adjustable density, stale-data indicators and labelled sample data
  where real data is missing.
  Acceptance (82.9, Monitoring Health Standard §7): every monitoring widget distinguishes zero verified alerts,
  actual alerts, permission failure, source unavailable, collection failure, ingestion failure, stale and
  unknown with an icon and text, never colour alone, and shows the last successful collection; monitoring
  health is a separate element from security alert severity; a customer with a failed critical source never
  shows as fully healthy.
- **83.2 Preset boards** *(planned)* — Service Desk, Technician, NOC, SOC, Executive (financial permissions
  enforced), MSP Operations and a customer-scoped board. Early presets use data that exists today; security
  and NOC widgets fill in as Phases 82 and 84 land.
- **83.3 Widget catalog** *(planned)* — KPI, line, area, bar, stacked bar, donut, gauge, status, alert list,
  ticket queue, timeline, leaderboards, availability, security feed, incident table, SLA, backup,
  infrastructure health, geographic events (only where location data is reliable, never shown as a definite
  attacker location) and saved-report widgets. No custom SQL or code.
- **83.4 Board editor** *(planned)* — drag-and-drop placement and resizing, duplicate, thresholds, filters
  (customer, team, technician, time range), preview, draft and published versions with history, cloning,
  validated import / export, per-user and team defaults, rotation, refresh interval, transitions and optional
  sound alerts.
- **83.5 Efficient refresh** *(planned)* — one cached snapshot request per board per interval with
  conditional responses, a bounded minimum interval and recovery after disconnects, instead of a query per
  widget.
- **83.6 Secure display pairing** *(planned — extends the token-based schedule board pattern)* — read-only
  display identities paired by an administrator, with expiry, rotation, instant revocation, per-board and
  per-customer scope, optional address restrictions (Phase 81) and an audit trail. A display holds no user
  session and reaches no write or admin function; on expiry it blanks.
- **83.7 Visual validation** *(planned)* — screenshot checks of every preset at 1920×1080, 2560×1440,
  3840×2160, desktop and tablet widths.

**Sizing:** **XL** — presentation mode and presets first, then the editor, then pairing.

</details>

---

<a id="phase-84"></a>

## Phase 84 — Security connector framework and vendor integrations **(XL · security)** [planned]
<!-- phase: ws=D stage=6 view=later deps="81, 82" next="84.1 connector SDK; vendor batches" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 81, 82  
**Next:** 84.1 connector SDK; vendor batches

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends the security alerts module (vendor connections, SIEM webhook endpoints and the integration SDK) into
a connector framework, then real vendor connectors in batches. A connector is listed as shipped only after
authentication, ingestion, normalization and error handling have been run against a real instance or the
vendor's test environment.

- **84.1 Connector SDK** *(planned)* — polling with checkpoints, pagination, rate-limit handling, backoff,
  retries, duplicate suppression, token-expiry warnings, credential rotation, health checks and diagnostics.
  Acceptance: every connector records Monitoring Health Standard 1.0.0 telemetry through the shared contract
  (82.7) — raises on HTTP / permission / malformed responses, implements its provider-specific bounded
  empty-window probe or declares it unsupported, declares whether its API guarantees ordering — and passes the
  conformance cases C1–C13 against a recorded fixture of the real API.
- **84.2 Generic receivers** *(planned)* — signed webhook receiver with replay protection (Phase 81) and a
  TLS syslog collector for CEF, LEEF and JSON, run as its own service and off by default.
- **84.3 Connection administration** *(partial — honest capability labels shipped v3.17.723: vendors without a working API adapter are marked webhook only, their test and sync say "not implemented", and the scheduled poller skips them; the rest planned — extends Vendor Connections)* — vendor picker, credentials
  (never shown again), test connection, customers, categories, severity mapping, polling frequency, routing,
  test ingestion, retention and sync status.
- **84.4 Batch A** *(planned)* — Wazuh, Microsoft Sentinel, OPNsense, pfSense.
- **84.5 Batch B** *(planned)* — Microsoft Defender for Endpoint (replacing the reference stub), CrowdStrike
  Falcon, SentinelOne.
- **84.6 Batch C** *(planned)* — Splunk, Elastic Security, Graylog.
- **84.7 Later batches** *(planned, in order of API availability)* — IBM QRadar; Sophos and Huntress;
  Fortinet, Palo Alto Networks and SonicWall; Microsoft Entra ID, Okta, Duo and Google Workspace; AWS
  Security Hub, GuardDuty and Azure security services; Microsoft Defender for Office 365, Proofpoint and
  Mimecast; Tenable, Qualys and Greenbone / OpenVAS.
- **84.8 ExploitHound and MailThreatZero** *(planned)* — optional native connectors for vulnerability,
  exposure and email-threat findings, mapped to customers and assets where the APIs provide it.

**Sizing:** **XL** — SDK and generic receivers first, then one batch at a time.

</details>

---

<a id="phase-85"></a>

## Phase 85 — Operations Center, alert triage and correlation **(L · security)** [planned]
<!-- phase: ws=D stage=6 view=later deps="82, 84" next="85.1 Operations Center" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 82, 84  
**Next:** 85.1 Operations Center

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **85.1 Operations Center** *(planned)* — one dark operations page under Security & Monitoring combining
  Service Desk incidents, Rem0te and RMM alerts, monitors, backups, security alerts and investigations,
  outages, maintenance and customer impact, with drill-down to the customer, asset, alert, incident or
  ticket.
- **85.2 Alert triage** *(planned — extends the security alert queue)* — Investigating, Contained, False
  Positive and Suppressed statuses; analyst assignment, escalation, grouping, related alerts, notes,
  evidence, closure reasons and history.
- **85.3 Correlation rules** *(planned — replaces the fixed 60-minute grouping)* — configurable rules and
  windows, source reliability weights, rule tests and simulation, explanations, versions, false-positive
  controls and performance limits; never across customers.
- **85.4 Incident timelines and ticket links** *(planned)* — incidents linked explicitly to tickets and
  assets, with one timeline across sources.

**Sizing:** **L** — triage and the Operations Center first, then correlation.

</details>

---

<a id="phase-86"></a>

## Phase 86 — SOAR Lite: approval-driven security automation **(L · security)** [planned]
<!-- phase: ws=D stage=6 view=later deps="85, 51.20; Rem0te contract" next="86.1 builder on the Phase 91 engine" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 85, 51.20; Rem0te contract  
**Next:** 86.1 builder on the Phase 91 engine

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends incident playbooks and the support-workflow approval model. Read-only by default; nothing runs
because an event or a model said so.

- **86.1 Workflow builder** *(planned)* — triggers, enrichment, severity routing, tickets, incidents,
  notifications and IOC lookups, with dry runs, versions, execution history, failure recovery, per-customer
  policies and an emergency stop.
- **86.2 Approval gates and action catalog** *(planned)* — isolation, process termination, service restarts,
  account disabling, firewall and network blocks, quarantine, scripts and reboots each need their own
  permission and an approval record, with scoped action tokens, timeouts and idempotency. Automated
  remediation is off by default.
- **86.3 Rem0te endpoint actions** *(planned — needs Rem0te contract additions)* — endpoint detail and
  monitoring history, diagnostics and evidence collection, approved remediation with tracked results, and
  remote sessions where authorized.

> Prerequisite added 2026-11-20: 51.20 (playbooks behind approval) ships first. Phase 86 then becomes the one
> automation path for security actions; no fifth rule engine — it reuses the workflow engine's safety work
> from Phase 91.

**Sizing:** **L** — dry-run builder first, then approvals, then Rem0te actions as the contract allows.

</details>

---

<a id="phase-87"></a>

## Phase 87 — Alert routing, on-call and escalation **(M · monitoring)** [planned]
<!-- phase: ws=D stage=6 view=later deps="82, 85" next="87.1 notification routing" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 82, 85  
**Next:** 87.1 notification routing

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends on-call shifts, alert policies and maintenance windows to every alert source.

- **87.1 Notification routing** *(planned)* — email, SMS, mobile push, in-app and webhooks per severity,
  customer and technician preference, with delivery history, retries and failed-delivery alerts.
- **87.2 On-call rotations and escalation chains** *(planned)* — rotations, acknowledgement deadlines,
  after-hours policies and escalation steps.
- **87.3 Storm protection** *(planned)* — grouping, likely-root-cause summaries and suppression during wide
  outages and maintenance.
  Acceptance: monitoring-source failures route through the same rules; suppression never hides a persistent
  monitoring failure (82.10).

**Sizing:** **M**.

</details>

---

<a id="phase-88"></a>

## Phase 88 — Service dependency and impact mapping **(M · assets)** [planned]
<!-- phase: ws=D stage=6 view=later deps="16, 82" next="88.2 impact analysis" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 16, 82  
**Next:** 88.2 impact analysis

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends asset relationships and the topology view.

- **88.1 Dependency graph** *(re-scoped 2026-11-20: the relationship graph, services and dependency chains shipped in Phase 16; what remains is impact analysis and provenance on top of them)* — customers, sites, endpoints, servers, VMs, hosts, network, storage,
  applications, services, internet links and backup, from assets, Rem0te inventory and discovery; inferred
  links are marked unverified until confirmed.
- **88.2 Impact analysis** *(planned)* — affected services and customers for an outage, root-cause
  suggestions, related tickets, one ticket per underlying failure, and maintenance impact previews.

**Sizing:** **M**.

</details>

---

<a id="phase-89"></a>

## Phase 89 — Security posture scorecards and customer service reviews **(L · reporting)** [planned]
<!-- phase: ws=H stage=5 view=later deps="78, 82, 84" next="89.1 posture scorecard" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** H. Reporting, Analytics & Optional AI · **Depends on:** 78, 82, 84  
**Next:** 89.1 posture scorecard

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends the customer health score (Phase 78) and scheduled reports.

- **89.1 Security posture scorecard** *(planned)* — MFA, endpoint protection, encryption, patching,
  unsupported systems, backups, vulnerabilities, identity and firewall findings and monitoring coverage; each
  item shows its source, check time, deductions and remediation, and missing data stays missing. Optional
  framework mappings; a score is never presented as a certification. Monitoring coverage uses the
  source-health roll-up (82.9): an unverified or stale source is missing data, never a pass.
- **89.2 Customer review reports** *(planned)* — monthly service review, executive summary, service desk and
  SLA, security posture and incidents, endpoint, patch and backup health, availability, productivity,
  recurring problems and recommendations; MSP and customer branding, scheduling, email, PDF and CSV,
  history, access control and data-freshness notes.

**Sizing:** **L**.

</details>

---

<a id="phase-90"></a>

## Phase 90 — AI Operations Analyst **(L · OPTIONAL AI)** [planned]
<!-- phase: ws=H stage=6 view=later deps="85, 56" next="90.1 alert analysis" -->
**Status:** ⬜ Planned · **Priority:** P3\* · **Workstream:** H. Reporting, Analytics & Optional AI · **Depends on:** 85, 56  
**Next:** 90.1 alert analysis

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends the AI gateway (Phase 56), gated by `psa_ai_enabled` and the per-customer AI policy.

- **90.1 Alert and incident analysis** *(planned)* — summaries, repeated-alert detection, likely causes,
  related events, investigation steps, remediation options, timelines and customer-friendly summaries, using
  only the models an administrator enabled, with multi-model comparison where allowed.
- **90.2 Clear provenance** *(planned)* — raw evidence, verified facts, correlation findings, AI
  interpretation, recommendations and actions needing approval are labelled separately.
- **90.3 Guardrails** *(planned)* — no autonomous or destructive actions, no secrets in prompts, no
  cross-customer data, content from tickets, logs and events treated as data, redacted activity logs,
  budgets, rate limits and timeouts.
- **90.4 Monitoring visibility** *(planned — reuses 82.11)* — every analysis receives the deterministic
  source-health context and identifies material visibility gaps; a model can never report an environment as
  healthy because a collector returned zero alerts (conformance case C15).

**Sizing:** **L**.

</details>

---

<a id="phase-91"></a>

## Phase 91 — Workflow automation safety **(M · P1 · PSA)** [in progress]
<!-- phase: ws=A stage=1 view=next order=5 deps=14 next="91.6–91.9; approval or cap on charge amounts (91.4)" -->
**Status:** 🔵 In progress · **Priority:** P1 · **Workstream:** A. Core PSA & Ticketing · **Depends on:** 14  
**Next:** 91.6–91.9; approval or cap on charge amounts (91.4)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

> Status (audit 2026-11-20): loop prevention within one event and charge-once shipped v3.17.732; customer checks on assignment actions shipped v3.17.727. The items below that are not marked remain planned.

Automation that can be inspected, tested before it runs and cannot run away. Extends the workflow engine
(Phase 14) and ticket routing.

- **91.1 Loop and storm protection** *(partial — loop prevention within one event and the 50-action budget shipped v3.17.732; limits across events planned as 91.9)* — a rule never re-fires inside its own chain; per-rule and
  per-ticket rate limits with a cut-off that is recorded and shown.
- **91.2 Execution log** *(shipped v3.17.739 — runs and per-action results on the rule's flow page, scoped to the viewer's customers; kept 30 days, at most 500 per rule)* — every firing recorded with trigger, rule version, each action and its
  result, actor and duration, visible on the rule page.
- **91.3 Dry run** *(shipped v3.17.741 — conditions with the ticket's values and each planned action, through read-only planners; no writes, messages or calls; audited)* — evaluate rules against a chosen ticket with no side effects.
- **91.4 Permission checks for high-impact actions** *(partial — charge once per rule and ticket shipped v3.17.732, assignment customer checks v3.17.727; approval or cap on charge amounts planned)* — charges behind approval or a cap with
  fire-once protection; assignment and watchers limited to technicians allowed at that customer.

**Added 2026-11-20 (planned, P1):**

- **91.6 Time-based triggers and delayed actions** — "no reply in N hours", scheduled rules and wait steps, run
  by the scheduler.
- **91.7 Retries for transient failures** — mail and PSA pushes retried with backoff; the execution log (91.2)
  records each attempt.
- **91.8 Per-customer overrides** — switch off or adjust an MSP-wide rule for one customer.
- **91.9 Limits across events** — per-rule and per-ticket firing limits over time, with a visible cut-off.

**Sizing:** **M**.

</details>

---

<a id="phase-92"></a>

## Phase 92 — Verified usage and recurring billing **(M · billing)** [planned]
<!-- phase: ws=B view=later deps="70; Rem0te counts (92.4)" next="92.1 recurring charge generation" note="Prerequisite of 102" -->
**Status:** ⬜ Planned · **Priority:** — · **Workstream:** B. Billing & Financial Management · **Depends on:** 70; Rem0te counts (92.4)  
**Next:** 92.1 recurring charge generation  
**Note:** Prerequisite of 102

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Per-device and per-user billing that never bills an unverified count. Extends contracts and billing
(Phase 70).

- **92.1 Recurring charge generation** *(planned)* — a scheduler job creates each next-period charge once,
  with an audit trail; the "recurring" option on charges does this today in name only.
- **92.2 Usage count snapshots** *(planned)* — monthly per-customer device and user counts with source,
  observed time and verification state (verified, stale, unverified); stale or unverified counts never update
  a meter.
- **92.3 Reconciliation** *(planned)* — billed versus observed per agreement; differences become adjustment
  requests that need approval, never automatic invoice changes.
- **92.4 Count sources** *(planned)* — synced RMM devices first, Rem0te through a signed count once the
  contract supports it, Microsoft 365 seats from licensing.

- **92.6 Backup service billing from verified counts** *(planned, added 2026-11-20)* — per protected device,
  server, workstation or licensed user, per GB/TB only where the provider reports a reliable measurement, or
  a fixed monthly service; counts come from 74.7–74.9 and go through the same review step as other verified
  usage — never an automatic invoice change. Reuses contracts, service plans and invoicing; no second billing
  engine.
- **92.7 Device-management billing from verified MDM counts** *(planned, added 2026-11-20)* — same rules, counts
  from Phase 106.

**Sizing:** **M**.

</details>

---

<a id="phase-93"></a>

## Phase 93 — Business-hours SLA calendars **(M · PSA)** [planned]
<!-- phase: ws=A view=later deps="—" next="93.1 calendars" note="Prerequisite of 101" -->
**Status:** ⬜ Planned · **Priority:** — · **Workstream:** A. Core PSA & Ticketing · **Depends on:** —  
**Next:** 93.1 calendars  
**Note:** Prerequisite of 101

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **93.1 Calendars** *(planned)* — working hours, time zone and holidays per install default, customer and
  contract, reusing resourcing holidays.
- **93.2 SLA clocks on calendars** *(planned)* — due dates, pause and resume, and breach flags computed in
  working time; routing business hours read the same calendar; existing due dates unchanged on upgrade unless
  recomputed explicitly.

**Added 2026-11-20 (planned):** several coverage schedules per contract (for example 8×5 for normal work and
24×7 for priority 1), and an at-risk forecast from queue load and remaining working time.

**Sizing:** **M**.

</details>

---

<a id="phase-94"></a>

## Phase 94 — Evidence integrity and routine backups **(M · security)** [in progress]
<!-- phase: ws=F stage=1 view=now order=1 deps="—" next="External append-only audit shipping (94.1); protected-change approval for audit pruning (94.2); S3 destination (94.3)" -->
**Status:** 🔵 In progress · **Priority:** P0\* · **Workstream:** F. Security & Administration · **Depends on:** —  
**Next:** External append-only audit shipping (94.1); protected-change approval for audit pruning (94.2); S3 destination (94.3)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **94.1 Tamper-evident audit log** *(partial — shipped v3.17.736: HMAC hash chain sealed every 5 minutes by the scheduler, `audit_chain verify`/`export` commands, a critical system warning and an audit-page status when verification fails; shipping to an external append-only destination planned)* — hash-chained audit rows with a verification command and
  optional shipping to an external append-only destination.
- **94.2 Audit retention** *(partial — shipped v3.17.736: cleanup prunes only the oldest sealed rows and archives them first, refuses when the archive cannot be written, and the admin site cannot delete audit rows; a protected-change approval for pruning planned)* — retention with export before pruning; deleting audit rows goes
  through a protected change.
- **94.3 Scheduled off-host backups** *(shipped v3.17.744 — SFTP with host-key approval or a mounted directory; AES-256-GCM with a separate backup key shown once; weekly restore verification; S3-compatible storage planned, needs an S3 client library)* — encrypted backups to an off-host destination with
  periodic restore verification and key-escrow guidance.

**Sizing:** **M**.

</details>

---

<a id="phase-95"></a>

## Phase 95 — PSA migration importers **(L · imports)** [planned]
<!-- phase: ws=C view=later deps="61, 94.3" next="95.1 importer guarantees" -->
**Status:** ⬜ Planned · **Priority:** — · **Workstream:** C. Asset Management & Documentation · **Depends on:** 61, 94.3  
**Next:** 95.1 importer guarantees

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Extends the import framework (Phase 61).

- **95.1 Importer guarantees** *(planned)* — every importer offers dry run, field mapping, duplicate
  detection, a per-record error report, rollback and an integrity report; destructive imports need explicit
  confirmation and a verified backup.
- **95.2 First PSA source** *(planned)* — clients, contacts, tickets with comments and attachments,
  contracts, time, invoices, assets and credentials from one source, proven against a real instance.
- **95.3 Further sources** *(planned)* — ITFlow, HaloPSA, ConnectWise Manage, Autotask, Syncro and a
  broader CSV import, each listed as shipped only after a real-instance or sandbox run.

**Sizing:** **L**.

</details>

---

<a id="phase-96"></a>

## Phase 96 — First-install setup wizard and interactive onboarding **(L · P0 · UX)** [in progress]
<!-- phase: ws=I stage=1 view=later deps="59, 64, 67" next="96.2 first-install detection; 96.3–96.4 assistant" -->
**Status:** 🔵 In progress · **Priority:** P0 · **Workstream:** I. Deployment, Updates & Reliability · **Depends on:** 59, 64, 67  
**Next:** 96.2 first-install detection; 96.3–96.4 assistant

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P0. A Setup Assistant for new installs and guided tours of the live interface. The wizard writes the
existing settings; it is not a second settings system. Spec:
[docs/plans/phases-96-100/96-setup-wizard-and-tours.md](plans/phases-96-100/96-setup-wizard-and-tours.md).

- **96.1 Default password and install readiness** *(shipped v3.17.730 — banner, system warning, readiness card; last-backup age follows the scheduled backups work)* — flag the installer's default administrator
  password until it is changed; one readiness check (2FA, site URL, mail, backups, scheduler, disk, pending
  migrations) with fix links, built on the upgrade preflight and system warnings.
- **96.2 First-install detection** *(planned)* — the wizard is offered automatically only on a fresh install,
  after 2FA enrolment; upgraded installs are never redirected; extends the onboarding step engine with an
  install session that needs no customer.
- **96.3 Setup Assistant, core steps** *(planned)* — MSP details and branding, administrator security, modules,
  technicians, teams and roles, review; progress, save and resume, Back / Next / Skip, required and optional
  steps marked; reopen any time under Administration → General without overwriting anything.
- **96.4 Setup Assistant, service steps** *(planned)* — first customer or first prospect, service desk mail,
  routing and notifications, optional integrations with their existing connection tests, backup and health
  readiness. Secrets never appear in summaries or logs.
- **96.5 Isolated sample data** *(planned)* — an optional, clearly marked demo customer that never appears in
  reports, exports, billing or outbound messages, removable in one action.
- **96.6 Guided tours** *(planned)* — real tours over the live interface (highlighted element, step prompt) for
  owner, manager, sales, Level 1 and Level 2/3 technicians and portal users; steps follow permissions, enabled
  modules and current navigation; completion, dismissal and replay per user; no new UI framework.
- **96.7 Contextual help** *(planned)* — help links from the relevant screens and a rewritten getting-started
  guide.

Dependencies: Phases 59 (preflight), 64 (roles), 67 (navigation). Acceptance: fresh installs (script and
Docker) are offered the wizard after 2FA enrolment and upgraded installs are not; every step saves through the
existing settings; sample data never reaches real figures. Testing: detection on empty and populated databases,
2FA ordering with the real middleware, permission and customer-boundary tests for every step and tour, upgrade
rehearsal, a browser run of a multi-page tour.

**Added 2026-11-20 (planned):** one module-health page — for each module: enabled, configured, connection
tested, healthy, documented — linked from the setup wizard and Settings.

**Sizing:** **L** — readiness and detection first, then the wizard, then tours.

</details>

---

<a id="phase-97"></a>

## Phase 97 — Prospect IT assessment and CRM enhancements **(L · P1 · sales)** [planned]
<!-- phase: ws=E stage=4 view=later deps="5, 64, 75.3" next="97.1 assessment templates" -->
**Status:** ⬜ Planned · **Priority:** P1 · **Workstream:** E. Sales & CRM · **Depends on:** 5, 64, 75.3  
**Next:** 97.1 assessment templates

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P1. Extends the CRM (Phase 5) so a salesperson or technician can record a prospect's whole IT
environment during a meeting, then turn approved answers into draft records when the deal is won. Spec:
[docs/plans/phases-96-100/97-prospect-assessment-crm.md](plans/phases-96-100/97-prospect-assessment-crm.md).

- **97.1 Assessment templates** *(planned)* — reusable, versioned templates on the request-form schema engine:
  sections, optional and conditional questions, Yes / No / Unknown, numbers, choices and short text; a starter
  template covering business profile, endpoints, servers, network, applications, security, backup, current IT
  support and business and financial details.
- **97.2 Assessments on leads and opportunities** *(planned)* — Quick and Detailed views of the same answers,
  autosave and resume, notes and attachments per section, tablet and phone layout, several assessments per
  lead over time.
- **97.3 Answer provenance** *(planned)* — who supplied each answer, who recorded it, and whether it is
  verified, unverified or disputed; "Unknown" is an explicit answer.
- **97.4 Revisions and compare** *(planned)* — immutable revisions with side-by-side comparison.
- **97.5 Reports and summaries** *(planned)* — printable and PDF report, customer-facing variant without
  internal notes; **OPTIONAL AI** assessment and meeting summaries with action items, gated by
  `psa_ai_enabled`, drafts only.
- **97.6 Conversion to draft records** *(planned)* — on conversion, verified answers become draft customer,
  location, contact, asset, documentation, plan, quote, contract, onboarding project and remediation records
  through the existing lead conversion and onboarding wizard; unverified answers become "to confirm" items;
  duplicates are linked, not created.
- **97.7 Risk and readiness scores** *(planned)* — deterministic, explained per answer; unknown never counts as
  healthy.
- **97.8 Qualification rules** *(planned)* — MSP-defined qualification and profitability acceptance rules,
  advisory only.
- **97.9 Unified communications history** *(planned)* — sales activities, assessment events and (with Phase 99)
  calls on one timeline.
- **97.10 Imports and reconciliation** *(planned)* — optional spreadsheet import before conversion; discovery
  and RMM counts reconciled after conversion for review, never overwriting answers.

Dependencies: Phases 5 (CRM), 64 (roles), 75.3 (commercial onboarding). Acceptance: one answer set behind both
views; only verified answers create records; prospects stay out of customer lists until conversion. Testing:
schema compatibility with request forms, conversion and rollback, sales versus technical permissions,
customer-boundary tests, AI gating, a tablet-viewport browser run.

**Sizing:** **L** — templates and assessments first, then provenance, revisions and conversion.

Program link (2026-11-20): this phase carries the IT Discovery wizard of the
[MSP billing program](plans/msp-billing-program/README.md) §H. Opportunity → quote today creates an empty quote;
97 and 98 feed Phase 103 proposals.

</details>

---

<a id="phase-98"></a>

## Phase 98 — Service estimator and forecast accuracy **(L · P1 · sales)** [planned]
<!-- phase: ws=E stage=4 view=later deps="97, 68–70, 75, 76, 92" next="98.1 estimation models" -->
**Status:** ⬜ Planned · **Priority:** P1 · **Workstream:** E. Sales & CRM · **Depends on:** 97, 68–70, 75, 76, 92  
**Next:** 98.1 estimation models

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P1. Estimates monthly effort, cost and a price range from the Phase 97 assessment with a
deterministic, explainable engine, then checks the forecast against actual results. Spec:
[docs/plans/phases-96-100/98-service-estimator-forecasting.md](plans/phases-96-100/98-service-estimator-forecasting.md).

- **98.1 Estimation models** *(planned)* — MSP-defined, versioned rules per user, endpoint, server, location,
  application and service, with low / expected / high hours, onboarding hours and bounded complexity
  allowances; changes need approval.
- **98.2 Calculation engine** *(planned)* — deterministic: monthly hours range, onboarding and remediation
  estimate, labor cost from existing cost rates, known vendor costs (unknown stays unknown), price range for the
  target margin, projected gross profit, confidence, assumptions and missing-data warnings, each with its
  working shown.
- **98.3 Estimates on opportunities** *(planned)* — stored with their inputs and model version; frozen when a
  quote is sent.
- **98.4 Explanations** *(planned)* — **OPTIONAL AI**, gated by `psa_ai_enabled`: explains estimates, risks,
  missing information and plan fit, and drafts proposal text; every figure is checked against the computed
  input. AI never approves pricing, edits contracts or sends proposals.
- **98.5 Plan comparison and draft quote** *(planned)* — compare the MSP's own service plans against the
  estimate; create a draft quote through the existing draft-with-approval pattern; never sent automatically.
- **98.6 Forecast-versus-actual reviews** *(planned)* — 30, 60 and 90-day and quarterly reviews of hours, labor
  cost and margin with onboarding effort separated from steady state; surfaced in existing reports, the
  executive overview and the advisor.
- **98.7 Assumption-change recommendations** *(planned)* — proposals based on review history that a person
  accepts into a new draft model version; nothing applied silently.
- **98.8 Prospect intelligence** *(planned)* — missing services, upsell, readiness report and follow-up
  questions.

Dependencies: Phase 97; Phases 68, 69 (pricing, rate cards), 70 (quote conversion), 75 and 76 (profitability,
advisor); Phase 92 improves actual counts. Acceptance: same inputs always give the same results; unknown costs
never shown as numbers; costs and margins visible only with internal-cost permission. Testing: table-driven
engine tests, onboarding split, cost visibility, customer scoping of actuals, AI figure validation, an end-to-end
run from assessment to 30-day review.

**Sizing:** **L** — models and engine first, then plan comparison, then reviews.

Program link (2026-11-20): the rules-based workload estimator, low / expected / high scenarios and standard
proposal generation of the [MSP billing program](plans/msp-billing-program/README.md) §H build on this phase;
all of it works without AI.

</details>

---

<a id="phase-99"></a>

## Phase 99 — Phone system integration and call-to-ticket **(XL · P2 · integrations)** [planned]
<!-- phase: ws=G stage=6 view=later deps="64, 81, 82" next="99.1 adapter framework" -->
**Status:** ⬜ Planned · **Priority:** P2 · **Workstream:** G. Customer Portal & Communications · **Depends on:** 64, 81, 82  
**Next:** 99.1 adapter framework

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P2. Connects ClientSt0r to a PBX the MSP already runs; media and routing stay on the PBX and calls
never transit ClientSt0r. First target: Asterisk 22 LTS and FreePBX 17 through the Asterisk Manager Interface,
via a small bridge on the PBX host. No platform is listed as supported until its integration is verified. Spec:
[docs/plans/phases-96-100/99-pbx-integration.md](plans/phases-96-100/99-pbx-integration.md).

- **99.1 Adapter framework and signed event contract** *(planned)* — vendor-neutral call events with HMAC
  signatures, timestamps, replay protection, ordering and retries on the existing webhook guard; network
  rules from Phase 81.
- **99.2 Asterisk / FreePBX bridge** *(planned)* — a small outbound-only process on the PBX host with an
  on-disk buffer; AMI kept on localhost; continuous integration against a real containerized Asterisk.
- **99.3 Number normalization and matching** *(planned)* — E.164 normalization; matches to contacts,
  customers, leads and users, with ambiguous matches shown as such. A phone number never establishes identity
  or authorization.
- **99.4 Caller popup** *(planned)* — compact slide-out with caller, customer, open tickets and permitted
  contract and SLA facts; quick ticket or new lead.
- **99.5 Click-to-call** *(planned)* — from customer, contact, ticket and lead records through the PBX, with
  permission checks, rate limits and an audit trail.
- **99.6 Call log and timelines** *(planned)* — inbound, outbound and missed calls on ticket, contact,
  customer and lead timelines.
- **99.7 Missed calls, voicemail-to-ticket and callbacks** *(planned)* — voicemail-to-ticket optional and off
  by default; callback due times in business hours.
- **99.8 Queue and agent status** *(planned)* — where the PBX reports them; IVR, trunks and routing stay in the
  PBX.
- **99.9 Health alerts** *(planned)* — bridge offline and signature failures through the event layer
  (Phase 82).
- **99.10 Recording and transcription policy** *(planned)* — off by default; links to PBX-held recordings only,
  behind their own permission; transcription would be **OPTIONAL AI** with consent and retention settings.
- **99.11 Further adapters** *(planned)* — Yeastar P-Series, 3CX, Wazo Platform, FreeSWITCH / FusionPBX,
  Grandstream UCM, one at a time, each after licensing checks and a verified integration.

Dependencies: Phases 81, 82, 64; uses Phase 93 calendars and Phase 97 leads when present. Acceptance: a
disconnected PBX never affects sign-in or ticketing; call state is stored in the database; every call
operation is permission-checked. Testing: signature, replay and ordering tests, customer-boundary tests on
popups and call lists, failure-isolation tests, and a CI job placing real calls against containerized
Asterisk 22.

**Sizing:** **XL** — contract and bridge first, then matching and popup, then click-to-call and call history.

</details>

---

<a id="phase-100"></a>

## Phase 100 — Optional simple PBX appliance **(XL · P4 · exploratory)** [planned]
<!-- phase: ws=G state=deferred view=later deps=99 next="Go/no-go review after Phase 99 ships" blocker="Exploratory; not built until Phase 99 is proven" unblock="Go decision against the recorded criteria" -->
**Status:** ⏸️ Deferred · **Priority:** P4 · **Workstream:** G. Customer Portal & Communications · **Depends on:** 99  
**Next:** Go/no-go review after Phase 99 ships  
**Blocked:** Exploratory; not built until Phase 99 is proven — *unblocks when:* Go decision against the recorded criteria

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P4, exploratory. An optional, separate PBX appliance built on an existing open-source engine (no new
SIP or media stack), isolated from the ClientSt0r application and database so voice keeps working when
ClientSt0r is offline. **Not to be built until Phase 99 is proven with real users and the go/no-go criteria
are met.** Spec:
[docs/plans/phases-96-100/100-simple-pbx-appliance.md](plans/phases-96-100/100-simple-pbx-appliance.md).

- **100.1 Research refresh** *(planned)* — Asterisk versus FreeSWITCH, licensing, measured footprint, trunk and
  NAT compatibility, TLS / SRTP, toll-fraud prevention, call-rate and destination limits, emergency calling
  (Kari's Law and RAY BAUM'S Act dispatchable location), recording consent, updates and support burden.
- **100.2 Go / no-go review** *(planned)* — recorded against the criteria in the spec: shipped Phase 99,
  documented demand, staffed patching, emergency-calling scope, toll-fraud defaults, licensing review and
  measured capacity.
- **100.3 Implementation plan** *(planned — only on a go decision)* — minimum feature set: trunks, DID routing,
  extensions, ring groups, sales and support queues, basic IVR, voicemail, business hours and holidays,
  transfers, call history, softphones, ClientSt0r popups through the Phase 99 bridge, health monitoring, backup,
  restore and updates.

Dependencies: Phase 99 shipped and proven; Phases 59, 93, 94. Acceptance for this phase: a recorded go/no-go
decision. Testing (if built): the Phase 99 Asterisk CI harness, security scans, emergency-calling tests on a
test route, update and restore rehearsals, load tests.

**Sizing:** **XL** if built; the exploratory work itself is **S**.

</details>

---

<a id="phase-101"></a>

## Phase 101 — Ticket Time & Charges and prepaid-hour ledger **(XL · P0 · billing)** [shipped — v3.17.751]
<!-- phase: ws=B stage=1 deps="1, 36, 69, 70, 73, 93" -->
**Status:** ✅ Complete · **Priority:** P0 · **Workstream:** B. Billing & Financial Management · **Depends on:** 1, 36, 69, 70, 73, 93

Full description, sub-items and release history: [ROADMAP_HISTORY.md — Phase 101](https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md#phase-101).

---

<a id="phase-102"></a>

## Phase 102 — Ready for Billing queue and invoice integrity **(L · P0 · billing)** [in progress]
<!-- phase: ws=B stage=1 view=next order=2 deps="15, 36, 75, 92, 101" next="102.5 invoice presentation; 102.6 recurring billing gaps; 102.7 one set of financial definitions" -->
**Status:** 🔵 In progress · **Priority:** P0 · **Workstream:** B. Billing & Financial Management · **Depends on:** 15, 36, 75, 92, 101  
**Next:** 102.5 invoice presentation; 102.6 recurring billing gaps; 102.7 one set of financial definitions

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P0 (§D, §E). Extends Phase 36 pre-invoice approval and the existing invoices.

- **102.1 Account charge bundling under a lock** *(shipped v3.17.753)* — bundling a customer's account charges into an
  invoice runs in one transaction with a row lock; today two quick clicks can bill the same charges twice.
- **102.2 Accurate unbilled list** *(shipped v3.17.753)* — the client-account "Unbilled work" list excludes time already
  invoiced.
- **102.3 Ready for Billing queue** *(partial — time, items, fees, account charges, adjustments and project milestones with approve, hold, exclude and adjust shipped v3.17.753; recurring charges wait for a charge generator (70.4, 92.1), customer-approved work for 102.9)* — approved unbilled time, items, expenses, overages, recurring
  charges, milestones and customer-approved work across tickets; review, approve, hold, exclude, adjust.
- **102.4 Consolidated invoices** *(partial — tickets, account charges and the agreement fee on one draft shipped v3.17.757; project milestones stay on the project page)* — several tickets, charges and the contract fee on one invoice;
  every line keeps its source; retries never double bill; finalized invoices corrected only by credit notes.
- **102.5 Invoice presentation** *(planned)* — itemized, grouped by ticket, monthly summary or summary with a
  service report; MSP branding.
- **102.6 Recurring billing gaps** *(planned)* — billing in arrears, failed-billing alerts, an in-app dry run
  before automatic billing is switched on (extends Phase 15 and 92).
- **102.7 One set of financial definitions** *(planned)* — billed, collected and recognized revenue, direct cost,
  gross profit and margin defined once and used by every report (Phase 75.1 today uses three revenue definitions);
  partial costs labelled as partial.
- **102.8 Settings → Billing** *(shipped v3.17.757)* — a page for the billing settings that exist but cannot be changed
  anywhere (invoice approval threshold, late fees, automatic accounting push), with per-customer and per-contract
  overrides showing where each value comes from.
- **102.9 Ticket billing follow-ups from Phase 101** *(planned)* — out-of-scope work charged under a flat-fee agreement (billable overriding covered), customer approval of extra work and an approval step for item lines from the ticket, an MSP-wide or per-location stock picker for ticket items, and items and the billing summary in the mobile API.

</details>

---

<a id="phase-103"></a>

## Phase 103 — Quote builder, options and price-book selection **(L · P1 · sales)** [planned]
<!-- phase: ws=E stage=4 view=later deps="65, 68, 70" next="103.1 price book in the editors" -->
**Status:** ⬜ Planned · **Priority:** P1 · **Workstream:** E. Sales & CRM · **Depends on:** 65, 68, 70  
**Next:** 103.1 price book in the editors

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P1 (§G). Extends the existing quotes and the Phase 65 signing; no second quote or signing module.

- **103.1 Price book in the editors** *(planned)* — catalog search on quote and invoice lines with price
  snapshots (completes 68.3) and staff screens for the price book outside Django admin (completes 68.1);
  customer-specific, bundle, volume and effective-dated prices; stale distributor price warnings.
- **103.2 Recurring and one-time totals** *(planned)* — monthly recurring, one-time subtotal and contract value
  shown separately, tax separately; payment terms, contract length, effective and expiry dates, assumptions and
  exclusions.
- **103.3 Quote templates** *(planned)* — editable, versioned templates fed by service plans and the price book.
- **103.4 Packages and optional items** *(planned)* — Good / Better / Best options in one proposal, optional,
  mutually exclusive and bundled items with quantity limits and dependencies; the customer chooses, the chosen
  configuration becomes a fixed, approved revision before signing, and the signature evidence covers it; only the
  chosen option is ever activated.
- **103.5 Revisions and signing** *(planned)* — quote versions with immutable accepted revisions; multiple and
  sequential signers, MSP countersignature, decline with reason, reminders, expiry job, reusing the Phase 65
  contract-document signing that already supports these.
- **103.6 Margin guardrails** *(planned)* — revenue, direct cost and expected margin against the target before
  sending; approval thresholds for low margin and large discounts, enforced server-side; never shown to customers.
- **103.7 Quote-to-cash dashboard** *(planned)* — drafts, approvals, sent, awaiting signature, accepted, awaiting
  activation, onboarding, unbilled work, draft and overdue invoices, with blockers and next actions; sales
  analytics kept apart from contracted and recognized revenue.

</details>

---

<a id="phase-104"></a>

## Phase 104 — Customer approvals, deposits, change orders and portal billing **(L · P1 · billing)** [planned]
<!-- phase: ws=B stage=4 view=later deps="72, 101, 103" next="104.1 out-of-scope approval" -->
**Status:** ⬜ Planned · **Priority:** P1 · **Workstream:** B. Billing & Financial Management · **Depends on:** 72, 101, 103  
**Next:** 104.1 out-of-scope approval

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P1 (§B, §G, §J).

- **104.1 Out-of-scope approval from a ticket** *(planned)* — itemized estimate through a secure link; approve,
  decline or ask; approver, time, exact revision and decision recorded; work and invoices link to it; changes past
  the contract threshold need a new approval.
- **104.2 Deposits and payment schedules** *(planned)* — percentage or fixed deposits, milestones, deposit
  invoices, balance due, application to the final invoice, refunds and credits; deposits not counted as earned
  revenue early.
- **104.3 Change orders** *(planned)* — through the quote and signing path; the original agreement is kept, the
  difference, effective date and authorization recorded, with version history.
- **104.4 Portal billing additions** *(planned)* — agreements, block balances and usage history, service
  summaries, disputes and explanation requests; never costs, margins or internal notes.

</details>

---

<a id="phase-105"></a>

## Phase 105 — Market pricing research and AI proposals **(L · P3 · OPTIONAL AI)** [planned]
<!-- phase: ws=E stage=6 view=later deps="76, 97, 98, 103, 56" next="105.1 research provider" -->
**Status:** ⬜ Planned · **Priority:** P3 · **Workstream:** E. Sales & CRM · **Depends on:** 76, 97, 98, 103, 56  
**Next:** 105.1 research provider

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Priority P3 (§I). Extends Phase 76; every switch separate, off by default, gated by `psa_ai_enabled`; billing and
quoting work fully without it.

- **105.1 Research provider and markets (OPTIONAL AI)** *(planned)* — a configurable search provider, geographic
  markets (city to national, several territories), legitimate public sources only, terms and rate limits respected;
  each observation stores source, URL, retrieval date, region, scope, price, unit, terms, confidence and
  comparability; nothing invented, verified prices kept apart from estimates.
- **105.2 Item and package pricing (OPTIONAL AI)** *(planned)* — Analyze Pricing on catalog items, packages and
  custom packages with scope normalization; recommendations combine market evidence with internal cost and never
  override the target margin; prices change only on explicit acceptance.
- **105.3 Prospect proposal (OPTIONAL AI)** *(planned)* — Analyze Prospect & Build Quote: Phase 97 assessment,
  Phase 98 estimate, market evidence, Basic / Standard / Premium, margins, risks and gaps, into an editable Phase
  103 quote; proposal text written only from recorded facts; approval stays human.
- **105.4 Market reports and customer reviews (OPTIONAL AI)** *(planned)* — market and pricing intelligence
  reports with methodology, sources and limitations; renewal reviews; a what-if simulator that separates facts,
  assumptions and AI suggestions.
- **105.5 AI pricing settings (OPTIONAL AI)** *(planned)* — per-feature switches, provider and model, search
  provider, encrypted keys, budgets and request limits, data-sharing rules, research retention; redaction, no
  secrets sent, prompt-injection protection for fetched pages, usage and cost logging.

</details>

---

<a id="phase-106"></a>

## Phase 106 — Device management (MDM) integrations **(XL · P2 · devices)** [planned]
<!-- phase: ws=D stage=3 view=next order=9 deps="64, 74.9, 82, 92" next="106.1 provider connections" blocker="Mosyle has no official API documentation found" unblock="Obtain official Mosyle API documentation (other providers unaffected)" -->
**Status:** ⬜ Planned · **Priority:** P2 · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 64, 74.9, 82, 92  
**Next:** 106.1 provider connections  
**Blocked:** Mosyle has no official API documentation found — *unblocks when:* Obtain official Mosyle API documentation (other providers unaffected)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Inventory, compliance and approved device workflows through established MDM providers — Microsoft Intune with
Entra ID devices, Jamf Pro, Kandji, Mosyle (once its official API documentation is obtained), Apple Business Manager (device assignment and enrollment records) and
Android Enterprise through a supporting provider. No native MDM server. Specification:
`docs/plans/mdm/README.md`.

- **106.1 Provider connections** *(planned)* — several connections per provider, each mapped to customers;
  least-privilege provider credentials (read-only first), sealed storage, rotation, TLS verification, a
  connection test and the provider's reported capabilities.
- **106.2 Device inventory** *(planned)* — Windows, macOS, iPhone, iPad and Android, corporate and (where the
  customer allows) personal devices: identity, customer, assigned user, OS and version, enrollment, last
  check-in, compliance, encryption, policy state, apps where available, ownership. Matched to existing assets
  and RMM devices by stable identifiers; unmatched devices stay "unmatched", never duplicated.
- **106.3 Compliance views and alerts** *(planned)* — non-compliant, unencrypted and stale devices per customer,
  through the Phase 82 event layer into tickets.
- **106.4 Approved device actions** *(planned — after 106.1–106.3)* — enrollment and assignment workflows, policy
  and profile assignment, app deployment, lock, lost mode, retire and wipe, only where the provider supports
  them. Wipe, retire and other destructive actions need their own permission, fresh authentication, typed
  confirmation and an audit record; no AI-initiated destructive action; the provider's own authorization
  stays separate from the Clientst0r approval.
- **106.5 Offboarding and onboarding** *(planned)* — the employee-leaver checklist gains an MDM device review,
  authorized retirement and license recovery steps, each an approved task, ending in a documentation update.
- **106.6 One device record across sources** *(planned)* — asset, RMM (including Linux and macOS devices from
  Rem0te, shown at the level Rem0te actually supports) and MDM facts on one device page, each with its source
  and age; unified device reporting; device counts available to 92.7.

Depends on: Phase 82 (events), 64 (roles), 74.9's matching approach, 92 (billing). Security: least privilege per
provider, customer isolation, step-up for destructive actions, never send device or user secrets to AI.
Acceptance: inventory from a sandbox tenant of each provider built, with a test that a wipe without step-up and
the wipe permission is refused at the API.

</details>

---

<a id="phase-107"></a>

## Phase 107 — Documentation search, attachments, sharing and asset history **(L · P3 · documentation)** [planned]
<!-- phase: ws=C stage=4 view=later deps="16, 53" next="107.1 ranked search" -->
**Status:** ⬜ Planned · **Priority:** P3 · **Workstream:** C. Asset Management & Documentation · **Depends on:** 16, 53  
**Next:** 107.1 ranked search

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **107.1 Ranked full-text search** for documents, assets and the knowledge base *(planned)*.
- **107.2 Document attachments and expiring share links** *(planned)* — share links scoped, logged and revocable.
- **107.3 Per-asset field history and bulk asset editing** *(planned)*.
- **107.4 Retire duplicate graphs** *(planned)* — one relationship view instead of the asset map, topology and
  connectivity diagrams.

Reuses Phase 16 relationships, Phase 53 readiness and the vault's permission model.

</details>

---

<a id="phase-108"></a>

## Phase 108 — Discovery scope approval and suggested-device staging **(M · P3 · network)** [planned]
<!-- phase: ws=C stage=4 view=later deps="32, 33" next="108.1 approved scan ranges" blocker="108.4 SNMP/LLDP/CDP collection" unblock="Owner decision (previously declined)" -->
**Status:** ⬜ Planned · **Priority:** P3 · **Workstream:** C. Asset Management & Documentation · **Depends on:** 32, 33  
**Next:** 108.1 approved scan ranges  
**Blocked:** 108.4 SNMP/LLDP/CDP collection — *unblocks when:* Owner decision (previously declined)

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **108.1 Administrator-approved scan ranges** a collector cannot exceed, scheduled runs for approved ranges and
  rate limits *(planned)*.
- **108.2 Suggested / unverified state** for discovered devices and inferred links, never overwriting approved
  documentation *(planned)*.
- **108.3 Honour `classify_enabled`** in the collector *(planned)*.
- **108.4 SNMP, LLDP/CDP, MAC and ARP tables, switch-port association and SNMP-based network monitoring**
  *(blocked — owner decision pending; an SNMP collector was previously declined)*. Until decided, the topology
  and port-map pages are labelled as needing pushed data.

</details>

---

<a id="phase-109"></a>

## Phase 109 — Microsoft 365 administration **(L · P3 · cloud)** [planned]
<!-- phase: ws=D stage=6 view=later deps="64, 82" next="109.1 structured tenant models" -->
**Status:** ⬜ Planned · **Priority:** P3 · **Workstream:** D. RMM & Platform Integrations · **Depends on:** 64, 82  
**Next:** 109.1 structured tenant models

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

Today: read-only tenant inventory with manual sync, not verified against a real tenant.

- **109.1 Structured tenant models** replacing the single cached JSON row, with history *(planned)*.
- **109.2 Users, licenses, guests, dormant and disabled accounts, MFA registration, security defaults,
  conditional-access visibility, service health and baseline drift** *(planned)*.
- **109.3 Prepared new-user provisioning from a ticket** — user, licenses, groups, mailbox, onboarding tasks;
  approval before anything is written to the tenant; least-privilege delegated access *(planned)*.
- **109.4 Google Workspace inventory** where practical *(planned)*.

</details>

---

<a id="phase-110"></a>

## Phase 110 — Service-delivery reporting and one set of definitions **(L · P3 · reporting)** [planned]
<!-- phase: ws=H stage=5 view=later deps="3, 75, 102" next="110.1 one calculation layer" -->
**Status:** ⬜ Planned · **Priority:** P3 · **Workstream:** H. Reporting, Analytics & Optional AI · **Depends on:** 3, 75, 102  
**Next:** 110.1 one calculation layer

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **110.1 One calculation layer** — executive providers become the only source for revenue, MRR, margin and
  utilization; the duplicate KPI, scorecard, wallboard and health-score pages are retired *(planned)*.
- **110.2 Service delivery** — tickets per customer, device and technician, first response, resolution, reopens,
  escalations, repeat issues, satisfaction, common problems, automation impact *(planned)*.
- **110.3 Sales** — pipeline, win rate, sales cycle, renewals and churn *(planned)*.

</details>

---

<a id="phase-111"></a>

## Phase 111 — Identity lifecycle and access reviews **(L · P1 · security)** [in progress]
<!-- phase: ws=F stage=1 view=next order=7 deps="57, 64, 80" next="111.1 passkeys; 111.3 one-action offboarding" -->
**Status:** 🔵 In progress · **Priority:** P1 · **Workstream:** F. Security & Administration · **Depends on:** 57, 64, 80  
**Next:** 111.1 passkeys; 111.3 one-action offboarding

<details markdown="1">
<summary>Details, completed work and acceptance criteria</summary>

- **111.1 Passkeys (WebAuthn)** as second factor and for step-up *(planned)*.
- **111.2 Periodic access reviews** with attestation per customer *(planned)*.
- **111.3 One-action technician offboarding** — sessions, keys and assignments revoked, tickets reassigned,
  shared vault entries queued for rotation *(planned)*.
- **111.4 Break-glass account** documented, alerting on every use *(planned)*.
- **111.5 Live verification of OIDC sign-in** against a real Keycloak (Phase 80) *(planned)*.
- **111.6 Access groups** *(shipped v3.17.742)* — named groups of staff (L1/L2/L3 Tech, Managers, Sales, Sales
  Managers, Owners, Administrators, Billing, Auditors) that carry a role and a customer scope; adding a person
  gives them that access, removing them revokes it; enforced on the server, audit-logged, owner-level groups
  managed only by owner-level staff. Built-in roles get plain names and the older roles fold under "Legacy roles";
  nobody's existing access changes.

</details>

---

<a id="release-history"></a>

## Release history

- [CHANGELOG.md](../CHANGELOG.md) — every release, newest first.
- [GitHub releases](https://github.com/agit8or1/clientst0r/releases).
- [ROADMAP_HISTORY.md](ROADMAP_HISTORY.md) — completed phases with their original wording and versions, earlier
  planning notes and the superseded sizing table.
- Machine-readable status: `GET /core/roadmap.json` on any install.

<a id="related-documents"></a>

## Related planning documents

| Document | Covers |
|---|---|
| [Platform program](plans/platform-program/README.md) | Stages, areas, development rules, completion checklist |
| [Clientst0r audit](plans/platform-program/CLIENTST0R_AUDIT.md) · [Rem0te audit](plans/platform-program/REM0TE_AUDIT.md) | Code audits of 2026-11-20 behind the statuses |
| [Rem0te feature expansion](plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md) | Stage 8 backlog |
| [Cross-platform requirements](plans/platform-program/CROSS_PLATFORM_REQUIREMENTS.md) | Windows, Linux, macOS, MDM and backup responsibilities |
| [Billing program](plans/msp-billing-program/README.md) | Billing, quoting, CRM discovery specification |
| [Backup integrations](plans/backup-integrations/README.md) | St0r, Comet and unified backup management |
| [Device management](plans/mdm/README.md) | MDM providers and workflows |
| [Backup, MDM and cross-platform overview](plans/BACKUP_MDM_CROSS_PLATFORM_ROADMAP.md) | Combined plan |
| [Platform feature matrix](plans/MSP_PLATFORM_FEATURE_MATRIX.md) | Benchmark comparison (internal) |
| [Security review](plans/competitive/SECURITY_REVIEW.md) | Open findings |

<a id="maintaining"></a>

## How to update this roadmap

The **phase record** is the only place a status is written: the `## Phase N — …` header and the
`<!-- phase: … -->` line under it. Everything else on this page is generated from those records.

1. Header marker: `[planned]`, `[in progress]`, `[shipped — vX.Y.Z]` or `[complete]` — these feed
   `/core/roadmap.json` and the in-app roadmap page, so keep exactly these forms.
2. Record line: `ws` (workstream A–I), `stage`, `state` (`partial`, `blocked`, `deferred`, `verify`), `view`
   (`now`, `next`, `later`), `order`, `deps`, `next`, `blocker`, `unblock`, `note`. Use double quotes for values
   with spaces; no double quotes or double hyphens inside values.
3. When something ships: mark the sub-item in the phase's details `*(shipped vX.Y.Z)*`, update `next`, and when the
   whole phase is done change the header marker and move the phase's details to ROADMAP_HISTORY.md, leaving the
   link.
4. New phase: add the anchor `<a id="phase-N"></a>`, the header, the record line and a `**Status:**` line, plus a
   Details block; new phases are `[planned]`.
5. Run `python3 scripts/roadmap_dashboard.py` (rewrites the generated tables and status lines). The test suite runs
   it with `--check` and fails when the page is out of date.
