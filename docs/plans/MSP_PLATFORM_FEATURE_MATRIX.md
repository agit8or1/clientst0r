# MSP platform feature matrix — Clientst0r + Rem0te

Internal planning document (2026-11-20). Competitor product names appear here because this is a benchmark; they
must not be carried into `docs/ROADMAP.md`, FEATURES.md or marketing prose. Program:
[platform-program/README.md](platform-program/README.md).

## How to read it

- **Our columns** come from static code audits on 2026-11-20 — Clientst0r v3.17.733 and St0r v3.2.140
  ([platform-program/CLIENTST0R_AUDIT.md](platform-program/CLIENTST0R_AUDIT.md),
  [msp-billing-program/CAPABILITY_AUDIT.md](msp-billing-program/CAPABILITY_AUDIT.md)) and Rem0te 0.73.0
  ([platform-program/REM0TE_AUDIT.md](platform-program/REM0TE_AUDIT.md)); St0r in
  [backup-integrations/ST0R_AUDIT.md](backup-integrations/ST0R_AUDIT.md). Nothing was run for the audits.
  The MDM row's competitor cells were not part of the benchmark research.
- Our status values: **Complete** (code and tests), **Partial** (what is missing is named), **Limited** (works, but
  below what the label suggests, e.g. mocked-only provider tests), **Planned**, **Blocked** (owner decision
  pending), **Missing**. "Integration" means the capability lives in the other application and reaches this one over
  the signed `ticket-rmm-v1` contract.
- **Competitor columns** are from official vendor pages and documentation only, retrieved 2026-11-20
  (sources at the end). **Yes**, **Partial**, **Add-on/Int** (separate product or third-party integration),
  **NF** = not found on the pages reached — not a statement that the feature is absent. Edition and tier gating was
  not mapped. Atera's main site returned HTTP 403 and two other pages 404, so Atera NF cells are weak.
- Stacks: Halo = HaloPSA + NinjaOne; CW = ConnectWise PSA + RMM; AT = Autotask PSA + Datto RMM; Syncro, Atera and
  SuperOps are single-vendor stacks.
- The comparison is of features and workflows only. Planned work is never shown as available.

## Matrix

| Category | Clientst0r | Rem0te | Roadmap | Halo | CW | AT | Syncro | Atera | SuperOps |
|---|---|---|---|---|---|---|---|---|---|
| PSA ticketing | Complete (composer, canned replies, merge, timers, SLA chip, routing) | — | 52, 60 | Yes | Yes | Yes | Yes | Yes | Yes |
| Workflow automation | Partial: visual builder and loop protection; no dry run, execution log, delays, retries, time triggers | Approved automation schedules (time-based) | 14, 91 | Yes | Yes | Yes | Yes | Partial | Yes |
| SLA calendars | Partial: 24×7 clock, MSP-wide routing hours, correct pause/resume | — | 93 | NF | Yes | NF | NF | NF | NF |
| CRM / pipeline | Partial: leads, opportunities, pipeline; no IT discovery; opportunity → empty quote | — | 5, 97 | Yes | Yes | Yes | NF | NF | Partial |
| Prospect assessment and workload estimate | Planned | — | 97, 98 | NF | NF | NF | NF | NF | NF |
| Billing (contracts, block hours, recurring) | Partial: recurring invoices, allowances, overage, accounting push; no hour ledger, time-and-materials without a contract invoiced at $0, rate cards not used by invoicing | — | 1, 15, 36, 69, 70, 92, 101, 102 | Yes | Yes | Yes | Yes | Yes | Yes |
| Quoting | Partial: line items, tax, PDF, approvals, signing; no recurring/one-time split, templates, options or versions | — | 70, 103 | Yes | Yes | Yes | Yes | NF | Yes |
| Electronic signatures | Complete for contract documents (versions, several signers, decline, evidence); quotes single-signer, revision-hash bound | — | 65, 103.5 | NF | Partial | Add-on | NF | NF | NF |
| Quote → contract / invoice conversion | Partial: signed document → draft billing contract (header fields only) | — | 70 | NF | Yes | Yes | Yes | NF | Yes |
| Procurement / purchase orders | Partial: requisitions, POs, distributors | — | 4, 13, 73 | Yes | Yes | Add-on | Yes | NF | Yes |
| Inventory | Partial: stock and job kits; reservation and consumption not separate on ticket parts | — | 46, 73, 101.6 | Yes | Yes | Add-on | Yes | NF | Yes |
| IT documentation | Complete: documents, vault, assets, racks, ports, VLANs, IPAM, diagrams, relationships; search unranked, no per-asset history or document attachments | — | 16, 53, 55, 107 | Partial | NF | Partial | NF | NF | Yes |
| Network discovery | Partial: ICMP/ARP collector and import, controller sync (UniFi, Omada, Grandstream), SSH config backup; SNMP/LLDP/CDP Blocked | — | 32, 33, 34, 108 | NF | NF | NF | NF | NF | NF |
| RMM monitoring | Integration (8 alert kinds; device workspace) | Complete on Windows (13 monitor kinds, escalation, maintenance windows); Linux/macOS read-only | 63, Rem0te P1 | Add-on/Int | Yes | Yes | Yes | Yes | Yes |
| Remote access | Missing: session launch from a ticket | Complete (RustDesk, Fleet); endpoint-enforced controls in Lab only | 63.13, Rem0te P6 | Add-on/Int | Yes | Yes | Yes | Yes | Yes |
| Scripting | Proposals only (by design) | Complete on Windows: signed library, two approvals, parameters, schedules; no PowerShell 7/bash | Rem0te P4 | Add-on/Int | Yes | Yes | Yes | Partial | Yes |
| OS patching | Patch summary on reboot-pending alerts only | Complete in code for Windows Update (rings Sim, one Fleet install); Linux/macOS Missing | 63.16, Rem0te P3 | Add-on/Int | Yes | Yes | Yes | Yes | Yes |
| Third-party app patching | — | Partial: pinned winget allowlist; no automatic updates | Rem0te P3 | Add-on/Int | Yes | Partial | Yes | Yes | Yes |
| Automated remediation | Proposal → approval in Rem0te → result (tested cross-peer) | Missing: alert-triggered actions | 63, Rem0te P5 | NF | Yes | Yes | NF | NF | Yes |
| Backup | Limited: monitoring for Proxmox Backup Server, restic, Borg, Kopia; no provider actions. St0r/UrBackup and Comet planned (74.7, 74.8; St0r needs a versioned API first) | Missing | 74, 77.8, 92.6, Rem0te P8 | Add-on | Add-on | Add-on | Yes | Add-on | Partial |
| Security (EDR/AV) | Limited: alert ingestion and incidents; vendor connectors webhook-only; playbooks auto-run without approval (SR-35) | Missing: endpoint compliance | 82–86, Rem0te P7 | Add-on/Int | Add-on | Yes | Partial | NF | Add-on |
| Event correlation / SOC views | Partial: event layer with no consumers yet, 60-minute incident grouping, security overview | — | 82, 83, 85 | NF | NF | Yes | NF | NF | NF |
| Mobile device management (MDM) | Missing — planned through Intune/Entra, Jamf Pro, Mosyle, Kandji, Apple Business Manager and Android Enterprise providers (no native MDM server) | Intune update-ring detection only; Apple warranty lookups | 106, Rem0te P8 | not researched | not researched | not researched | not researched | not researched | not researched |
| Microsoft 365 management | Limited: read-only tenant inventory, manual sync, not verified against a real tenant | — | 109 | Partial | Add-on | Yes | Yes | NF | NF |
| AI | Complete, OPTIONAL AI: ticket assist, troubleshoot, pricing advisor, AI gateway | Explains only, never acts | 56, 63.5, 76, 90, 105 | Yes | Yes | NF | Yes | Yes | Yes |
| Customer portal | Partial: tickets, service requests, approvals, invoices and payment, KB, signing; no dashboard, contracts, block balances, assets or backup status | — | 72.3, 77, 104.4 | Yes | Yes | Yes | Yes | NF | Yes |
| Reporting / BI | Partial: Business Overview, profitability, many reports; three revenue definitions and duplicate KPI pages | Patch, software and session reports | 75, 89, 102.7, 110 | Yes | Yes | Yes | Yes | Partial | Yes |
| Identity and SSO | Partial: 2FA, Microsoft sign-in, OIDC (not verified on a live provider), step-up, session cut-off; no passkeys or access reviews | Passkeys on the approval signer | 57, 64, 80, 111 | NF | NF | NF | NF | NF | NF |
| Audit trail | In progress: tamper-evident chain built, not yet released | Complete: sealed chain, signed checkpoints, off-host export | 94.1 | NF | NF | NF | NF | NF | NF |
| Self-hosting | Complete: install script, Docker, signed updates | Complete | 42, 59 | NF | NF | NF | NF | NF | NF |

Workflow features the benchmark documents and the platform should match (sources below): alert-to-ticket with
deduplication and status sync [A1][A9][N6]; ticket-to-device remote session with the session record written back to
the ticket [C5][A1]; patch-failure monitors raising tickets [A9]; portal quote approval converting to work [S3][SO4][N4];
time linked to agreements and contract profitability [N4][SO1]; block hours with top-up and remaining balance [H3][A3];
PO receipt into inventory with accounting export and ticket or project link [C3][S2]; SLA timers alerting before breach
[N4][C1]; AI governance with role-based access and a global switch [N1].

## Sources (official vendor pages, retrieved 2026-11-20; `(s)` = reached via a search result on the vendor's own domain)

- H1 https://usehalo.com/ · H2 https://www.usehalo.com/guides/1356 (s) · H3 https://www.usehalo.com/guides/1843,
  https://www.usehalo.com/guides/1975 (s) · H4 https://www.usehalo.com/guides/1990 (s) ·
  H5 https://www.usehalo.com/guides/1189, https://www.usehalo.com/guides/1106 (s) · H6 https://usehalo.com/halopsa/guides/891 (s)
- N1 https://www.ninjaone.com/rmm/ · N2 https://www.ninjaone.com/endpoint-management/ · further N, C, A, S, AT and SO
  sources: see [platform-program/COMPETITOR_SOURCES.md](platform-program/COMPETITOR_SOURCES.md), which keeps the
  full list with the research notes.
