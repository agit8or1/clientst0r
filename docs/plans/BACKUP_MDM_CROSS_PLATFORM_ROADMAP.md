# Backup, MDM, macOS and Linux integrations — roadmap specification

**Status:** Planned. This document defines future scope; it is not an implementation claim.
**Priority:** Finish Clientst0r first. Build Clientst0r's provider-facing, read-only workflows before undertaking a broad rem0te agent expansion.
> **Phase numbers reconciled 2026-11-20 with `docs/ROADMAP.md`:** backup management is an extension of Phase 74
> (74.7–74.12, portal 77.8, billing 92.6), MDM is Phase 106, and the Clientst0r side of macOS/Linux coordination
> is 63.18 plus 106.6. Detailed specifications: `docs/plans/backup-integrations/README.md`, `docs/plans/mdm/README.md`,
> `docs/plans/platform-program/CROSS_PLATFORM_REQUIREMENTS.md`. The headings below keep this document's own
> numbering only as section labels.

**Related phases:** 63 (RMM), 74 (backup monitoring), 75/77 (customer portal and reports), 79 (Agit8or Connect), 82 (events), 86 (approval-driven automation), 92 (verified usage), 96 (setup wizard).
**Future rem0te work:** `docs/plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md` (Clientst0r's record of the Stage 8 backlog), reconciled with Rem0te's own `docs/rmm-expansion-audit.md` (rem0te PR #182, open at the time of writing) and `docs/readiness.md`.

## Design boundary and common rules

Clientst0r is the multi-customer **control, workflow and reporting plane**. Backup engines, MDM providers and rem0te stay separate products; no replacement backup engine or second RMM is to be written into Clientst0r.

- Preserve existing deployment behavior, schemas, API compatibility, backups and customer records. Extend existing `backups`, assets, integrations, alerts, tickets, customer portal, pricing and permission components; audit first.
- No implied support from a vendor name or a sample adapter. Distinguish **available**, **limited**, **planned**, and exact provider capabilities.
- One canonical external identity mapping per connection/customer/device/backup item. Use immutable provider identifiers; never match solely by hostname, email or display name. Conflicts and unknown mappings go to a review queue.
- Separation of duties: read-only connection by default, explicit opt-in and role/tenant checks for management actions; restores and destructive operations need fresh step-up and appropriate approvals.
- External events are authenticated, timestamped, replay-checked, rate-limited and idempotent where provider facilities permit. Polling includes cursor/overlap handling, stale-data indicators, backoff and reconciliation.
- Keep credentials encrypted and scoped per integration, never expose sensitive restore data or provider tokens to AI or customer portal. HTTPS/TLS verification is mandatory; no direct cross-host access to vendor application databases.
- Treat backup *success*, replication *success*, restore *verification*, and *recoverability* as different states; never infer one from another.
- Provider integrations are independently optional and can coexist per customer/site.

## Unified backup management: St0r/UrBackup + Comet Backup (roadmap Phase 74.7–74.12; P1)

### St0r (UrBackup management interface) connector — roadmap 74.7, P1

Repo: [agit8or1/St0r](https://github.com/agit8or1/St0r). **St0r manages UrBackup**, which performs backups; St0r is not a separate backup engine. St0r currently operates alongside *one* local UrBackup server. A Clientst0r integration must support *multiple independent St0r installations* serving different customers or sites.

1. Audit St0r's existing API and authentication. If there is no stable least-privileged service integration API, plan and coordinate a narrow, versioned **read-only API extension in St0r** before attempting integration. Do not access St0r or UrBackup SQLite/MariaDB from Clientst0r, and do not expose raw backup files.
2. Support a secure St0r connection per installation: configured URL, scoped service identity/token, TLS verification, capabilities/version handshake, health and last sync. Support securely rotating credentials.
3. Ingest customer/site/endpoint mappings, file/image backup status and dates, failed/in-progress jobs, storage quota/usage, backup history, replication state/lag and recovery-verification/drill results where the source supplies them.
4. Show backup status in customer, asset, ticket, operations, backup and portal views. Map only identities that have been explicitly approved; no cross-customer leakage.
5. Create deduplicated alerts and optional tickets for failures, overdue backups, replication lag, disconnected protected endpoints and failed recovery verification, with maintenance windows and recovery state.
6. Follow St0r source links; enable authorized run-backup, review configuration and request-restore workflows **only after** capabilities, approvals and API authorization are designed. Do not proxy restored backup contents through Clientst0r by default.
7. Include reporting: protected asset coverage, RPO evidence and latest restore drill, source-age warnings, service-level exceptions, customer summaries and optional billing quantities backed by verified data.

### Comet Backup integration — roadmap 74.8, P1

Comet is a **distinct provider**, not part of St0r and not UrBackup. Start with a direct Clientst0r Comet Management Console adapter; do not assume St0r manages Comet. If a future St0r Comet connector is evaluated, keep it optional, explicit and nonduplicating.

Official reference: https://docs.cometbackup.com/latest/api/api-guide/

- Distinguish **Comet Management Console API** authentication from the separate **Comet Account Portal API**; credentials and tokens are not interchangeable. Follow official API semantics and the source server's permissions.
- Connection wizard: console URL, service credentials with minimum usable roles, auth/TOTP or supported token flow, TLS, capability detection, test, rate control, key rotation and error messages. Support multiple consoles/installations.
- Discover and map Comet users, devices, Protected Items, Storage Vaults and customer groups; use stable provider IDs and an explicit matching/approval queue.
- Synchronize jobs, outcomes, backup ages, storage/quota or retention facts, policies, online state where available, and restore points or recovery-test evidence only when actually exposed.
- Normalize all Comet events into the same Clientst0r backup state model. Prefer authenticated event hooks where appropriately available and reconcile via periodic polling so missed events recover.
- Add console deep links for devices, protected items, backup history and permitted actions. See https://docs.cometbackup.com/latest/guides/deep-linking-to-the-management-console/.
- Make the initial connection **read-only**. Later allow permissioned, approval-gated launch-backup, policy changes, protected-item provisioning and **restore requests**, only where the official API supports them, with strong audit, scope and safety checks.
- Model licensing/seat quantities and cost only from verified API facts or explicit configured data; reuse Clientst0r licensing/contract/billing rules to avoid duplicate metering.
- Provide consolidated per-customer Comet and St0r reporting without implying a Comet restore is equivalent to a St0r/UrBackup restore.

### Unified backup view — roadmap 74.9–74.10, P1

Add **Clientst0r → Backups** integrating current PBS/restic/Borg/Kopia monitoring and the new St0r/UrBackup and Comet providers.

- Per-customer and cross-MSP views by provider, endpoint, site, protected workload, last successful job, latest verified restore, replication, next expected protection window, quota/usage, stale or unknown data and SLA.
- Coverage discovery: compare assets and verified provider mappings; distinguish missing protection from unknown mappings.
- Event → alert → ticket → assigned technician → provider deep link/action request → verification → closure, with source record preserved.
- Show configured backup protection and billing quantities to customer portal users only with appropriate permissions.
- Do not create a generic `healthy` status from merely "last job succeeded"; include RPO and recovery-verification evidence separately.

Acceptance: two St0r installations and two Comet consoles mapped to distinct customers, identical endpoint hostnames across customers, expired tokens, event retries, lost events, stale sync, one missing backup, one failed restoration test, and exact read-only/approval behavior. No duplicate ticket or invoice under retry.

## MDM/UEM provider integration (roadmap Phase 106; P2)

**Start with provider integrations in Clientst0r; do not create a native MDM server.** Evaluate available APIs, licensing and permissions for Microsoft Intune/Entra, Apple Business Manager and Apple device-management providers (Jamf, Mosyle, Kandji), Android Enterprise via a supported UEM/EMM provider, and other MSP demand.

1. Provider setup with scoped organization/tenant mapping, version/capability discovery, auth/token refresh and offboarding.
2. Import device identities, ownership, enrollment, OS version, last check-in, compliance state, encryption state, assigned user, policies and app inventory when available. Never conflate an MDM device identity with a rem0te device without verified mapping.
3. Integrate information into Clientst0r assets, user onboarding/offboarding, ticket device view, health dashboards, events and customer reports.
4. Offer governed request workflows for enrollment, group/policy assignment, managed app deployment, device lock, retire, wipe and lost-device workflows only where supported by the provider. Sensitive destructive actions require fresh step-up, review, clear target confirmation and audit.
5. Use least-privilege delegated scopes; no global admin credentials by default; separate read from write permissions and show exactly which scopes an integration requests.
6. Add configuration and security posture reporting with clear source timestamps; avoid promising OS behaviors that require different MDM enrollment types or device ownership.

Acceptance: users cannot see or operate other customers' devices; unsupported actions are hidden/refused at API layer; no automated wipe; stale compliance is unknown rather than passing; reconciliation after reconnect.

## macOS/Linux device management coordination (roadmap 63.18 and 106.6 on the Clientst0r side, P2; Rem0te agent expansion deferred to Stage 8)

Rem0te already offers Linux/macOS enrollment, basic inventory, metrics, monitoring, read-only patch reports and RustDesk access. The missing work is **active, appropriately authorized management** on those operating systems.

**Clientst0r now:** prepare/extend OS-neutral device schema, support-ticket device panel, inventories, job/evidence envelopes, versioned capability negotiation, approval and audit request flows, monitoring and reporting. Render missing capabilities accurately; do not offer a Windows-only action on Linux/macOS.

**rem0te later:** scoped signed agents and explicit platform-specific policies for:

- Linux: Debian/Ubuntu `apt`, RHEL-family `dnf`, SUSE `zypper`; approved updates, package inventory/install, service/systemd actions, logs/journal, disk/network diagnostics, scripts, restart scheduling and verification.
- macOS: Apple software-update visibility and permitted updates, package inventory and managed deployments (where supported), launchd/service status, logs/diagnostics, supervised/MDM-dependent operations via MDM integrations, scripts and restart workflows.
- Both: signed/pinned releases, tamper-resistant agent action validation, version/capability advertisements, safe script catalogs, maintenance windows, offline queue expiry, rollback/recovery policy, consent where applicable, tenant isolation and audit events.

Prioritize Clientst0r first. **Do not implement rem0te cross-platform execution in this phase** unless a small security/interop correction is necessary to finish a Clientst0r workflow.

Acceptance: the Clientst0r UI and API properly distinguish read-only from actionable endpoints, never issue an unsupported command, preserve platform/tenant identity, and handle device drift/offline state. Later rem0te milestones get separate acceptance tests.

## Sequence and rollout

1. **Roadmap/docs first:** audit actual code; update GitHub roadmaps, dependencies, feature matrix and accurate statuses; no application changes in this planning milestone.
2. **Clientst0r P1:** St0r/Comet read-only connectors, unified backup views, alerts, ticket integration and source-aware reporting.
3. **Clientst0r P2:** optional approved backup actions and provider-supported MDM imports/workflows, plus OS-neutral RMM integration UI.
4. **After Clientst0r completion:** rem0te's Linux/macOS action agents, stronger cross-platform patching, scripting and remediations.
5. Update public feature listings only when the specific capability is implemented.

## Documentation and API references

- St0r: https://github.com/agit8or1/St0r
- Comet API guide: https://docs.cometbackup.com/latest/api/api-guide/
- Comet API methods: https://docs.cometbackup.com/latest/api/api-methods/
- Comet console deep linking: https://docs.cometbackup.com/latest/guides/deep-linking-to-the-management-console/
- rem0te capabilities: https://github.com/agit8or1/rem0te/blob/main/docs/capabilities.md
