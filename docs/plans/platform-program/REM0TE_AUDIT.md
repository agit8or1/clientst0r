# Rem0te audit for the Clientst0r + Rem0te platform program

## 1. Header

| | |
|---|---|
| Repository | `https://github.com/agit8or1/rem0te`, shallow clone (depth 50) |
| Commit audited | `35549219b48064bceb20a86714bc3e4b16da10db` (2026-11-20 11:43 -0500) |
| Version | **0.73.0 "Warden"**, channel stable (`r:version.json`) |
| Previous audit baseline | 0.67.0 `2dab9ef` (`/home/administrator/docs/plans/competitive/GAP_ANALYSIS.md`, Area 1) |
| Clientst0r pin compared | `/home/administrator/integrations/rem0te/contract/PIN.json` on Clientst0r `main` |
| Method | Static reading of docs, changelog, `CLAUDE.md`, the contract directory and selected source files. Nothing was run: no scripts, builds, package installs or tests. No host was contacted. This audit used a fresh clone of the GitHub repository. |
| Conventions | `r:` = path in the Rem0te repo; `cs:` = path in Clientst0r. "Complete" only where code and tests exist. Rem0te's own evidence grades (Lab / Fleet / Runner / Sim / pwsh / API / Unit, `r:docs/readiness.md`) are quoted where they matter, because Rem0te's tests are mostly simulator- or API-level. **(unverified)** marks an inference. |

### What changed since 0.67.0 (`2dab9ef`)

Ten releases, 2026-11-19 → 2026-11-20 (`r:CHANGELOG.md` L8–863):

| Release | Change | Relevance to Clientst0r |
|---|---|---|
| 0.68.0 Nametag | First inventory arrives straight after install; rename, aliases and notes on a computer; Health column says Healthy / Warning / Issues / Unknown | Device naming and health wording for a future P10 summary |
| 0.68.1 | **`r:docs/readiness.md`**, an evidence-graded readiness report and Rem0te's current roadmap; **`r:docs/managed-secure-access.md`** design | Canonical roadmap (see §2) |
| 0.68.2 | CI tests every PR against older released signed agents (`r:scripts/compat/supported-agents.json`, `r:scripts/compat-agents.sh`) | Model for Clientst0r cross-peer pinning |
| 0.68.3 | Windows lab workflow (`r:.github/workflows/lab-windows.yml`, `r:docs/lab-testing.md`): agent Windows code (service control, End process, program removal, offline WU scan, `windows.script.run` under PowerShell 5.1) and RustDesk as SYSTEM on GitHub `windows-latest` (Server 2025) | Several "Sim only" capabilities now have Runner/Lab evidence on Windows Server |
| 0.69.0 Preflight | Managed Secure Access (MSA) step 2: read-only RustDesk preflight in the signed agent, per-computer readiness | Remote session security groundwork |
| 0.70.0 / 0.70.1 Slate | Health labels link to monitoring; "Clear" alerts on one computer; truthful signed-agent version display | Clear emits `MONITOR_ALERT_RESOLVED` per alert → `alert.resolved` events reach Clientst0r (unverified that a bulk clear is emitted per alert on the feed) |
| 0.71.0 Tether | MSA step 3: Ed25519 session-grant key (separate from signer keys), long-poll channel, behind `MSA_GRANTS` (off) | — |
| 0.72.0 Helm | MSA step 4: agent enforcement of RustDesk settings, managed test session, cutover/rollback, grant keys delivered only via the signed release | — |
| 0.73.0 Warden | MSA step 5: Connect through grants, signed revocation, session timelines, cutover runs; view-only and consent enforceable on managed computers | Future basis for a secure session launch from a ticket (P6) |

**No contract change.** `r:docs/contracts/ticket-rmm-v1/` is byte-identical between `2dab9ef`, `5a43f02` (0.68.0) and
HEAD; `contract_revision` is still 2. `r:INTEGRATION_COORDINATION.md` was last changed in 0.51.0 and does not record
Clientst0r's 2026-11-19 response (`cs:docs/plans/coordination/clientst0r-response-2026-11-19.md`).

Corrections to GAP_ANALYSIS Area 1 from this read:

- **1.01 resolved on the Clientst0r side:** the pin moved to Rem0te 0.68.0 `5a43f023` (cs commit `a9e90595`, on `main`).
  It is one minor behind normative-wise only in label; the contract files are identical to 0.73.0.
- **1.02 progressed:** Clientst0r reports cross-peer E2E s1–s13 passing (141 checks) at 0.68.0, including s12
  (remediation chain through a test-only signer) and s13 (direct mode).
- **1.16 resolved:** `cs:integrations/rem0te/actions.py:171-176` maps `DIRECT_MODE_PORTAL_ONLY` and treats unknown codes as *failed*.
- **1.13 unchanged:** Rem0te advertises `windows.update.install@1` as proposable when a signer is configured
  (`r:apps/api/src/actions/catalog.ts:192` `integration: true`; `r:apps/api/src/integration/action-proposals.service.ts:36-39`);
  Clientst0r's `KNOWN_ACTIONS` (`cs:integrations/rem0te/pairing.py:67`) still has only `windows.service.start@1`, so it is
  silently filtered out (`pairing.py:245`).
- **1.27 still stale on the Rem0te side:** `r:docs/readiness.md:114`, `r:docs/contracts/ticket-rmm-v1/README.md`
  (Milestone status) and `CLIENTST0R.md` still say "does not interoperate with real Clientst0r (HMAC vs Ed25519)".

## 2. Existing Rem0te roadmap and plan documents

| Path | Covers | State |
|---|---|---|
| **`r:docs/readiness.md`** (0.68.1, "audited at v0.68.0") | Evidence-graded capability matrix per agent type; production-fleet evidence (4 Windows PCs, signed agent); remote-access limits; **"Roadmap, in dependency order"** Phases 1–12: real-endpoint validation, Managed Secure Access, agent reliability, patching/software/scripting evidence, monitoring (Defender/AV, firewall, BitLocker, SMART, battery, baselines, flapping), AI install detector, Clientst0r interop, hardening/scale/UX | **Canonical.** It states it supersedes the three below where they disagree |
| `r:docs/implementation-status.md` | "Expanded RMM programme" tracker (directive 2026-11-16): phase 0 audit of 0.54, plan rows (health telemetry 1a–1d, backup monitoring 5, digest 7, customer health dashboard 6, scheduling 2a, alert-triggered automation 2b, template library 2c, PowerShell 7 + POSIX Go agent 2d, file manager 3, UI 8), owner decisions (POSIX Design A, run-as, file manager Design B) | **The feature-expansion roadmap**, but a 0.54 snapshot (readiness.md L160 says so). Owner decisions there are still the latest recorded |
| `r:docs/rmm-gap-analysis.md` | Gap inventory against the RMM overhaul brief, written at 0.30.1/0.31 | Stale (two-action catalog etc., per readiness.md L153) |
| `r:docs/managed-secure-access.md` | Remote-session audit, design, build order §4, compatibility testing §5 | Current; steps 1–5 built, 3–5 behind `MSA_GRANTS` |
| `r:docs/capabilities.md` | Per-agent-type capability table and test levels | Partly stale; defers to readiness.md |
| `r:docs/security-model.md` §"Roadmap (not in this build)" L175 | Remote-access roadmap | Superseded by MSA doc |
| `r:INTEGRATION_COORDINATION.md` | Contract proposals rev 3–6 (P1–P16), Clientst0r requests R2–R16, task list | Last updated at 0.51; does not include 2026-11-19 response (CR-1..CR-3) |
| `r:docs/contracts/ticket-rmm-v1/proposed/` | Non-normative schemas for P11/P12/P16 | Unchanged |

Answer: **a feature-expansion roadmap already exists** — the canonical one is `r:docs/readiness.md` §"Roadmap, in
dependency order", with `r:docs/implementation-status.md` holding the detailed feature plan and owner decisions. The
program's `REM0TE_FEATURE_EXPANSION_ROADMAP.md` should reference and extend these rather than restate them.

## 3. Capability inventory

Agent types: **Std** = standard Windows agent (PowerShell scheduled tasks); **Sgn** = signed Go agent
`rem0te-agent.exe` (`r:tools/windows-installer/`, Windows only — every OS-specific file is `//go:build windows`);
**Lin/Mac** = read-only POSIX shell agents (`r:apps/api/src/public/posix-agent.ts`, `macos-agent.ts`).

Status key: **Complete** = code + tests (state Rem0te's evidence level); **Partial**; **Missing**.

### P1 — Common RMM functions

| Capability | Status | Evidence |
|---|---|---|
| Hardware/OS inventory, change history | Complete (Win Fleet; Lin API; Mac recorded output) | `r:apps/api/src/endpoint-inventory/`, `r:apps/api/scripts/e2e-system-inventory.mjs`; readiness.md L89 |
| Software inventory + change history | Complete Windows; Missing Lin/Mac | capabilities.md L288; `r:apps/api/src/software/` |
| Health (CPU/mem/disk, history 48 h raw / 90 d hourly), Health labels | Complete (Fleet) | `r:apps/api/src/metrics/`, `e2e-metric-history.mjs`; 0.68 labels |
| Health telemetry beyond basics (temps, SMART, battery, Defender, firewall, BitLocker, TPM, Secure Boot) | Missing (planned Phase 7 / 1a) | implementation-status.md §1; readiness.md L243-248 |
| Alerting: 13 monitor kinds, scope global→business→site→group→computer, dedup, hysteresis, maintenance windows, 4-level escalation, webhooks, email, classification (0.66), quality rules / false-positive (0.67), Clear (0.70) | Complete (Fleet for basic kinds; event classification partly) | `r:apps/api/prisma/schema.prisma:3249-3263` (`MonitorKind`), `r:apps/api/src/monitoring/` (engine, classify, quality-rules, false-positive.service), `unit-monitoring.mjs`, `e2e-monitoring.mjs`, `e2e-alert-quality*.mjs` |
| Trend / predictive alerts, flapping, baselines | Missing | readiness.md L245-248 |
| Process / service management | Complete in code; Lab (Windows Server runner) since 0.68.3; never on fleet | `windows.service.control@1`, `windows.process.stop@1` (`r:apps/api/src/actions/catalog.ts:589,652`), `r:tools/windows-installer/svcproc_windows.go`, `lab_windows_test.go`, `e2e-service-process.mjs` |
| Process/service/network snapshots (read-only tabs) | Complete Std+Sgn (Fleet); Missing Lin/Mac | `r:apps/api/src/diagnostics-catalog/catalog.ts:117-127`, `e2e-auto-snapshots.mjs` |
| Event logs | Complete Windows (Fleet: 2 queries); Missing Lin/Mac (refused "Windows-only") | `EVENT_LOG_QUERY`; capabilities.md L289 |
| Diagnostics catalog (12 read-only keys) | Complete Std+Sgn (Fleet) | `r:apps/api/src/diagnostics-catalog/catalog.ts:72-127`, `unit/e2e-diagnostics-catalog.mjs` |
| Remote admin: RustDesk remote desktop | Complete (Fleet: 109 sessions) | `r:apps/api/src/sessions/`, `r:apps/launcher/` |
| Remote admin: file manager, remote shell, registry editor | Missing (file manager designed, Design B, not built) | implementation-status.md §3, owner decisions |
| Bulk operations: up to 200 devices for group add/remove, refresh inventory, RustDesk update, export; restarts bulk; actions on ≤ 25 per run | Complete (I) | `r:apps/api/src/device-views/`, `r:apps/api/src/actions/restart-bulk.ts`, `e2e-device-views.mjs` |
| Technician tools: Ctrl+K search, saved views, static/rule groups, notes/aliases, chat, tray (support request, self-help), Quick Connect, warranty | Complete in code (search/views/groups I + browser; chat/tray partly Fleet) | `r:apps/api/src/search/`, `chat/`, `tray/`, `quick-connect/`, `notes/`, `warranty/`; readiness.md L107 |
| Unassigned pool, deployment keys, `.msi` | Partial (API only; `.msi` never run on Windows) | `r:apps/api/src/adoption/`, `r:apps/api/src/public/windows-msi.ts`; readiness.md L87,L111 |

### P2 — Cross-platform agents

| Agent | Executes (writes) | Read-only | Evidence |
|---|---|---|---|
| **Sgn (Windows)** | All 12 catalog actions, patch install, software install/uninstall/remove, scripts, service control, End process, restarts, tray self-help as SYSTEM, MSA enforcement (flagged off), signed pause | Inventory, heartbeat, scans, diagnostics, preflight | Fleet for patch install (1), removal (1), self-update, migration; Lab (Server runner) for service/process/remove/script/WU scan; Sim for the rest |
| **Std (Windows)** | None of the catalog; applies portal-staged password rotation, reinstall, RustDesk update | Inventory, software, event logs, diagnostics, WU scan (read-only) | Fleet (before migration) |
| **Linux** | **Nothing** (`LINUX_AGENT_READ_ONLY`; invariant §24) | Heartbeat, inventory (no software list), pending updates from cache | API only; never installed as root under systemd |
| **macOS** | **Nothing** (`MACOS_AGENT_READ_ONLY`; §24/§32 bans `softwareupdate`, `launchctl`, `defaults write`) | Heartbeat, inventory, macOS's own last update list; restart pending unknown | API against recorded output; never on a Mac |
| Signed Go agent for Linux/macOS | Missing — owner-approved (Design A, 2026-11-16), not started | No `GOOS=linux/darwin` build anywhere; `.github/workflows/` has `ci.yml`, `lab-windows.yml` only | implementation-status.md "Owner decisions" |

### P3 — Third-party patching

| Capability | Status | Evidence |
|---|---|---|
| OS patching (Windows Update): scan, KB/severity/class, deploy | Complete in code; Fleet = 1 direct-mode install (restart pending); rings/canary Sim only | `r:apps/api/src/patching/`, `r:tools/windows-installer/patch_windows.go`, `e2e-staged-patching.mjs`; staged-patching.md §"Known limits" says **"Windows only, and Microsoft updates only. No third-party patching"** |
| Third-party app catalog | Partial: winget community-source allowlist per business/global | `r:docs/software-deployment.md` L24-; `r:apps/api/src/software/` |
| Approved packages + version and installer-hash pinning | Complete (Sim; never on real Windows) | software-deployment.md §"Pinning the hash"; Go `internal/winget`; `unit-software.mjs`, `e2e-software-deploy.mjs` |
| Automatic update of third-party apps to new versions | Missing ("Updating an entry in place… a new version is a changed entry and a new deployment"; "automatic remediation … not done") | software-deployment.md L510-525 |
| Other sources (Chocolatey, msstore, private feeds, own installers) | Missing by design (no upload route) | same |
| Scheduling: one-time ≤ 14 d, recurring automation schedules, patch policies (weekly/monthly windows) | Complete (Sim) | `r:docs/automation.md`, `r:apps/api/src/actions/automation-policy.ts`, `patch-policy.ts`, `unit-patch-policy.mjs`, `e2e-patch-policies.mjs`, `e2e-automation-schedule.mjs` |
| Canary / rings (≤ 25), all-at-once (0.62 default) | Complete (Sim) | staged-patching.md §"How a deployment runs", §"All at once" |
| Maintenance windows | Complete (policy windows; monitoring maintenance windows) | staged-patching.md §"Patch policies", §"Monthly windows" |
| Failure thresholds / auto-pause | Complete (Sim) — `too_many_failures` pauses the deployment; ring gate re-run by the signer | staged-patching.md L126, L354-361 |
| Reboots: restart rule, restart windows (business/group/computer), deferral during RustDesk session | Partial — code + Sim; **never restarted a real computer**; no user postponement; console/RDP sessions not detected | `r:apps/api/src/restart-windows/`, `r:docs/restart-windows.md`, readiness.md L96 |
| Compliance: patch compliance report, software version compliance (compliant/outdated/missing/unknown), CSV | Complete (API) | `r:apps/api/src/patching/compliance.ts`, software-deployment.md §"Version compliance", `e2e-reports.mjs` |
| Other manager detection (WSUS, WUfB, Intune, ConfigMgr) → refuse | Complete (Sim; Lab offline-WSUS scan 0.68.3) | `r:apps/api/src/patching/posture.ts:57` |
| Linux/macOS patching | Missing (read-only pending lists) | capabilities.md L294 |

### P4 — Scripting

| Capability | Status | Evidence |
|---|---|---|
| PowerShell (Windows PowerShell 5.1 as SYSTEM) | Complete in code; **Lab on Windows Server runner since 0.68.3**; never on fleet | `windows.script.run@1` (`catalog.ts:330`), `r:apps/api/src/actions/script-run.ts`, Go `internal/action/lab_windows_test.go` (lab-testing.md L147) |
| PowerShell 7, Bash/Zsh, interpreter reporting, run-as unprivileged | Missing (planned A1–A3; run-as decided) | implementation-status.md §2, owner decisions |
| Library, immutable versions, SHA-256, diff, review (author ≠ reviewer, fresh sign-in) | Complete (U/I) | `r:apps/api/src/script-library/`, `unit/e2e-script-library.mjs` |
| Hash pinning on signer allowlist (2 passkey approvals), signed revocation | Complete (U/Sim) | script-library.md §"How a script runs", §"Revocation"; `unit-approval-signer.mjs`, `e2e-revocation.mjs` |
| Typed parameters checked by portal, signer and agent | Complete | script-library.md §"Parameters"; `unit-script-run.mjs`; Go `scriptParamsOK` |
| Bulk (≤ 25 per run), device groups (capped) | Complete | automation.md §"What a schedule names" |
| Schedules (once; hourly/daily/weekly/monthly policies approved once) | Complete (Sim) | automation.md; `e2e-automation-schedule.mjs` |
| Approval policies: two per run, direct mode for single operator | Complete | approved-actions.md §"Direct mode" |
| Output: 64 KB/stream, double redaction, 90 d retention, device history | Complete | script-library.md §"Output and retention"; `r:apps/api/src/actions/script-output.ts` |
| Verification after run | Partial — exit code and result only; no post-condition check | script-library.md (unverified that no verify hook exists beyond exit code) |
| Audit (sealed hash chain) | Complete | `r:apps/api/src/audit/`, `unit-audit-chain.mjs` |
| Static checks (flag only) | Complete | `r:apps/api/src/script-library/static-checks.ts` |
| Predefined reviewed safe scripts | Missing ("Built-in reviewed templates M"; readiness Phases 4–6 "reviewed library of read-only maintenance scripts") | implementation-status.md §2 |
| Linux/macOS scripts | Missing (needs POSIX Go agent) | — |

### P5 — Automated remediation (monitor → condition → approved policy → action → verification → PSA update)

| Link | Status | Evidence |
|---|---|---|
| Monitor → condition | Complete | monitoring engine |
| Condition → action trigger | **Missing** — monitoring never imports the actions service (no `ActionsService` reference in `r:apps/api/src/monitoring/`); plan item 2b "Alert-triggered automation … executes unattended only under a signer-approved automation policy with cooldown, dedup, max-runs" | implementation-status.md §2 and Plan row 2b |
| Approved policy | Partial — signer-approved automation policies exist, but time-triggered only | `r:apps/api/src/actions/automation-policy.ts` |
| Action | Complete (12-action catalog) | `catalog.ts` |
| Verification | Partial — patches "confirmed by a later scan"; alert auto-resolves at next check; no explicit post-action verification step | capabilities.md §"Patch status" |
| PSA update | Partial — alert → PSA ticket (webhook/email/Clientst0r rev 2), `alert.resolved` events; proposal results only by poll (R7 unbuilt); no fix events (P5 unbuilt) | `r:apps/api/src/monitoring/alert-tickets.service.ts`, `alert-events.service.ts`, `r:apps/api/src/psa/` |
| AI in the chain | Never executes or approves (stated invariant) | contract README "Responsibilities that do not move" |

### P6 — Remote session security (RustDesk-based: yes)

| Capability | Legacy (all production computers) | Managed Secure Access (0.69–0.73, `MSA_GRANTS` off; Lab on Windows Server only) | Evidence |
|---|---|---|---|
| Endpoint-enforced view-only | Missing — portal refuses for presets (`ENDPOINT_CANNOT_ENFORCE_VIEW_ONLY`), "not applied" for owners/admins | Partial — agent applies RustDesk options and verifies; Lab only | readiness.md L105, L131; MSA §3.11–3.12; `lab_enforce_windows_test.go` |
| Consent | Missing (same) | Partial (attended consent enforceable on managed computer; not at logon screen) | MSA §3.6, §3.8 |
| Session credentials | Permanent password released after step-up, or 90 s single-use grant for presets; permanent password works outside Rem0te | One-time password per grant, handed once, replaced at session end | security-model.md L37-55; MSA §3.12 |
| Expiry | Advisory only | Grant limit 1–480 min, idle 15 min, enforced by agent | MSA 0.73 notes |
| Revocation | Stops new launches; seen password still works until rotated | Signed revocation (`rem0te-msa-revoke-v1`), agent ends session | `r:apps/api/src/msa/revocation.ts`; Go `internal/msa/grant` |
| Clipboard / file transfer | Technician-client toggles, not enforced | Enforced via ceiling + preset; ceiling = control+clipboard+files+audio, never tunnel/remote restart | `r:apps/api/src/msa/connect-terms.ts` |
| Timelines | Thin ("connection confirmed" = process count) | Requested → … → Connected/Disconnected/Revoked; "Launched is never shown as Connected" | `r:apps/api/src/msa/session-timeline.ts`, `e2e-msa-sessions.mjs` (114 checks) |
| Recording | Missing; MSA cannot stop technician-side recording; endpoint recording would need a modified RustDesk build (not planned) | same | MSA §3.8; MSA §2 table L84 |
| Audit export | Complete for audit chain (off-host export with signed checkpoints, verify CLI); session history report + CSV | same | security-model.md L168; `r:apps/api/src/audit/`, `r:docs/reports.md` |
| Platforms | — | Signed Windows agent only; Lin/Mac/Std are "Unsupported" | readiness.md L106 |

### P7 — Endpoint compliance

| Capability | Status | Evidence |
|---|---|---|
| Security baselines | Missing (baselines planned, Phase 7) | readiness.md L246 |
| Disk encryption (BitLocker/FileVault/LUKS) | Missing | implementation-status.md §1 |
| Firewall state | Missing | same |
| Defender / AV status, definitions | Missing | same |
| Local administrators | Missing (Clientst0r R15 asked for it) | coordination §9A R15 |
| Patch compliance | Complete (report + CSV; Windows evidence-graded) | `r:apps/api/src/patching/compliance.ts` |
| Software version compliance | Complete (API) | software-deployment.md §"Version compliance" |
| Risk score | Missing (health is worst-alert label only) | implementation-status.md §1 "Health score P" |
| AI-software install detector | Missing (planned Phase 8, off by default) | readiness.md L250 |

### P8 — Backup and MDM integrations

| Capability | Status | Evidence |
|---|---|---|
| Backup monitoring (provider adapters, webhook/poll, backup monitor kinds) | Missing (planned Phase 5; "quick win" via SERVICE_STOPPED/EVENT_MATCH templates) | implementation-status.md §5 |
| Intune | Missing as integration; Intune update-ring **detection** and refusal only | `r:apps/api/src/patching/posture.ts:57-59` |
| Apple Business Manager | Partial — warranty lookups only (stand-in tested) | `r:apps/api/src/warranty/vendors.ts`; readiness.md L112 |
| Android Enterprise | Missing | — |
| Deployment via Intune/GPO (`.msi`, multi-use keys) | Partial (never run) | readiness.md L111 |

### P9 — Clientst0r integration (as Rem0te implements it)

| Capability | Status | Evidence |
|---|---|---|
| Ticket ↔ device link | Complete — jobs carry `rem0te_endpoint_id`; alert-ticket link route | `r:docs/contracts/ticket-rmm-v1/schemas/alert-ticket-link.schema.json`, `job-request.schema.json` |
| Diagnostic requests (read-only, no AI) | **Missing** — P2/P3 agreed (rev 3), unbuilt; R13 (no `model_profiles`) unanswered; diagnostics today only as AI-job evidence (`endpoint_evidence: ['inventory','heartbeat']`) | `r:apps/api/src/integration/integration.controller.ts:69-80` |
| Remediation proposals | Partial — `POST /action-proposals`, catalog only, 2 proposable actions (`windows.service.start@1`, `windows.update.install@1`) when signer configured; 10 others `integration: false` | `catalog.ts:93,192` and `integration: false` rows; `action-proposals.service.ts:36-39` |
| Results | Partial — poll `GET /action-proposals/{id}`; no signed status events (R7), no `fix.*` events (P5) | coordination §5, §9A |
| Asset reconciliation | Partial — Path A public API sync by API key per business; not over the signed contract | coordination §4A; `r:docs/PUBLIC-API.md` |
| Alert → ticket | Complete for 8 rev-2 kinds (OFFLINE, DISK_FREE, CPU_HIGH, MEMORY_HIGH, SERVICE_STOPPED, EVENT_MATCH, REBOOT_PENDING, SITE_OUTAGE); the 6 newer kinds (AGENT_SILENT, DRIVE_FREE, UPTIME_LONG, UPDATES_MISSING, UPDATE_FAILED, WARRANTY_EXPIRING) are dropped before signing | `r:apps/api/src/integration/contract.ts:406`; `r:apps/api/src/monitoring/alert-events.service.ts` |
| Patch status in tickets | Partial — `patch_summary` only on REBOOT_PENDING alerts | `schemas/patch-summary.schema.json`; capabilities.md §"In a linked ticket" |
| Customer associations | Complete — `(peer, organization_id) → business`, step-up mapping, `organizations` in `/capabilities` | contract README §"Trust", CLIENTST0R.md §"Business binding" |
| Technician permissions | Complete — `(peer, org, technician_id) → user`, delegation JWS bound to body hash, live access re-check | `r:apps/api/src/integration/delegation.service.ts`, `integration-auth.guard.ts` |
| Audit references | Partial — `requestedBy.via: 'clientst0r'` on actions (`catalog.ts:735`); ticket ref on proposals; no shared cross-application audit id (unverified) | — |
| Secure session launch | Missing — P6 unbuilt; MSA grants could later back it | coordination §5 P6; MSA §3.12 |
| Handoff note | Missing — P7 agreed, unbuilt | coordination §5 P7 |
| Device health summary | Missing — P10 agreed, unbuilt | coordination §5 P10 |
| AI diagnostics | Complete for ticket analysis jobs via Clientst0r's gateway (reference peer + Clientst0r cross-peer s2); device timeline P11 proposed, unagreed | `r:apps/api/src/integration/analysis.ts`, `timeline.*.ts`; `e2e-ticket-workflow.mjs`, `e2e-ai-timeline.mjs` |
| Rem0te's own PSA connectors (email-to-ticket, webhook, Clientst0r P16 gated) and own AI provider key (0.48, §41) | Exists — note for platform separation: Rem0te now also holds an optional AI provider key and creates tickets in other PSAs | `r:apps/api/src/psa/`, `r:apps/api/src/ai/`; `r:CLAUDE.md` L476 |

## 4. Security model to preserve

| Element | What it is | Evidence |
|---|---|---|
| **Signed agent and update chain** | `rem0te-agent.exe` updates only from a signed repository (root in `trustroot/root.json`, written only into build copies); releases signed by a `rem0te-release` user on a 0700 key directory or an offline machine; downgrades refused; reproducible builds; agent verifies its own update chain | `r:docs/update-signing.md`, `r:deploy/release/`, `r:tools/windows-installer/trustroot/`, invariant §56 |
| **Approval signer, separate trust** | Separate install with its own origin; loads no Nest/Prisma/portal module; the portal never imports it or holds its key; **no approve route in the portal or the integration**; approvals are passkey quorums on the signer's own page; requester/author cannot approve; direct mode is a signer-side CLI decision, and refuses Clientst0r proposals (`DIRECT_MODE_PORTAL_ONLY`) | `r:apps/api/src/approval-signer/`, `r:CLAUDE.md` §14 L280-; `r:docs/approved-actions.md` |
| **Endpoint verification** | Agent verifies the signer's signature against `approval/keys.json`, the device binding (RustDesk ID + device-secret hash), the closed catalog and closed params, `notBefore/notAfter` (≤ 24 h), signed pause (containment), signed revocations (monotonic `seq`); journals before executing; signs its results with a per-device key (TOFU) | approved-actions.md; `r:tools/windows-installer/internal/action`, `internal/devsig`; invariants §14, §15, §52 |
| **Closed catalog** | 12 actions, exact ordered list checked by `check-security-invariants.mjs`; adding one is an agent release; "credential extraction, removing backups, disabling defenses, granting admin rights and wiping disks … never will be" | `r:apps/api/src/actions/catalog.ts`; approved-actions.md L27-31 |
| **MSA grant key** | A separate Ed25519 key (sealed under `ENCRYPTION_KEY`, purpose `rem0te-msa-grant-key-v1`); public keys reach agents **only through the signed release**; flag off unless `MSA_GRANTS === 'on'` exactly, not a console setting | 0.71/0.72 changelog; `r:apps/api/src/msa/msa-grants-flag.ts`, `grant-key-commands.ts` |
| **Integration trust** | Peers in a root-owned file (not DB); two Clientst0r keys (request vs delegation); Ed25519 only, HMAC never accepted; ±120 s, nonces, body `idempotency_key`; explicit org/tech mappings with step-up; live access every time; `rk_` API keys refused on integration routes; never acts as Platform Admin | contract README §"Trust"; `r:apps/api/src/integration/peers.ts`, `replay-guard.service.ts` |
| **Tenant isolation** | Business visibility builders reused by search, lists, reports; identically named PCs kept apart by endpoint id | `e2e-business-access.mjs`, `e2e-endpoint-visibility.mjs`; CLIENTST0R.md §"Business binding" |
| **POSIX agents read-only** | Text-checked invariants §24/§32 | capabilities.md L310-316 |
| **Audit** | Sealed hash chain, insert-only, signed checkpoints, off-host export, verify CLI; detects but cannot prevent a superuser rewrite without export | security-model.md L168 |
| **Containment** | Pauses (actions, remote, updates, integration) enforced at portal, signer and agent (signed pause) | `r:docs/containment.md` |
| **AI boundary** | AI explains only; never proposes or approves; suggestions authorize nothing | contract README; implementation-status.md §2 "AI executes: Never" |
| **Invariant checker** | `r:scripts/check-security-invariants.mjs` (7,102 lines, sections to §83) | CI |

Platform-program consequence: Clientst0r must keep "request/suggest only". Any new contract item must leave approval
on the signer and verification on the agent; none of the asks in §6 touch either.

## 5. Contract state

| | Rem0te HEAD 0.73.0 | Clientst0r pin |
|---|---|---|
| Contract | `ticket-rmm-v1`, `contract_revision: 2` | `ticket-rmm-v1`, revision 2 |
| Source | `r:docs/contracts/ticket-rmm-v1/` | Rem0te 0.68.0 `5a43f023` (copied 2026-11-19), plus `rev1/` for 0.26–0.29 peers |
| Diff | Byte-identical (only Clientst0r's `PIN.json` and `rev1/` differ); no contract commit since 0.68.0 | — |
| Known stale artefacts | `examples/index.json` labels rem0te 0.29.1 (R10, confirmed); `clientst0r-interop.json` records 3.17.659; README/CLIENTST0R.md interop statements | — |

Re-pinning to 0.73.0 is a label-only change (no normative difference); worth doing so the pin matches the
"current release" in completion checklist item 7.

### Offered by Rem0te, not consumed by Clientst0r (Phase A inputs)

| Item | Where | Clientst0r status |
|---|---|---|
| `windows.update.install@1` in `features.actions` (when signer configured) | `catalog.ts:192` | Filtered out by `KNOWN_ACTIONS` (`cs:integrations/rem0te/pairing.py:67,245`). Note: Rem0te requests updates only through deployments (`ACTION_NOT_DIRECT`, CLAUDE.md §15); whether a single-endpoint proposal from the integration is accepted is **(unverified)** |
| `features.model_comparison`, multiple `model_profiles` per job | `integration.controller.ts:70-71` | Not checked in this audit (unverified) |
| `limits` block (`max_model_profiles`, `max_job_ttl_seconds`, `max_delegation_ttl_seconds`, `max_request_bytes`) | `integration.controller.ts:82-87` | Not checked (unverified) |
| `signing_keys[]` with previous keys (rotation) | `integration.controller.ts:88-91` | Consumed per CS-4 (2026-11-11 response) |
| `job.partial`, `job.accepted`, `job.running` events | contract | Handled per CS-7 (unverified for `accepted/running` UI) |
| Proposed P11 `device_timeline_v1`, P12 peer capabilities document, P16 `ticket.create_request` | `proposed/` | Vendored, not implemented; unanswered |

### Rem0te capabilities with **no contract surface yet** (would need a new revision)

Read-only diagnostics catalog (12 keys); processes/services/network snapshots; software inventory and compliance;
patch compliance beyond REBOOT_PENDING; 6 newer alert kinds; alert classification/explanation and false-positive
reporting (0.66–0.67); maintenance windows (R14); metric history; device notes/aliases (0.68); support requests
(P14/P15); session history and MSA timelines (R6); software and maintenance actions (`integration: false`).

## 6. Narrow Rem0te changes Clientst0r Phase A would need

Smallest compatible asks, in order, for the coordination file. None changes the signer, the agent's verification,
the catalog's closedness or tenant binding. Items 1–3 are documentation or tooling only.

1. **Record the current state** (doc only): update `r:INTEGRATION_COORDINATION.md` (§2, §4C, §8, §11), `r:docs/readiness.md:114`,
   contract `README.md` milestone table and `CLIENTST0R.md` to say Clientst0r implements revision 2 and passes the
   cross-peer suite s1–s13 at 0.68.0; append the 2026-11-19 response (CR-1..CR-3). Regenerate `examples/index.json` (R10).
2. **Answer R2** — how a peer declares the highest revision it implements (5B proposes `contract_revision` in the
   P12 capabilities document). Every additive item below depends on it; answering it is a decision, not code.
3. **CR-1 / CR-2** test tooling: prebuilt per-release `rem0te-action-sim` and `rem0te-release` artefacts (or a
   documented build target), and a machine-readable approval-page view, so Clientst0r's CI can exercise approvals
   without a Go toolchain or HTML parsing.
4. **P10 device summary** (read-only, `computers:read` delegation): online/last seen, open alerts, patch summary,
   last boot, agent type and version, Health label, each field group with `observed_at`. Unblocks the ticket device
   panel (Phase A "health, alerts, inventory summary, patch and connectivity status").
5. **P2/P3 read-only diagnostics** over the existing 12-key catalog, **without `model_profiles`** (R13), bounded and
   redacted by Rem0te, signed `diagnostic.*` events. No new agent code needed (the catalog already runs on Std+Sgn) (unverified).
6. **R7 signed proposal-status events** (additive event type, sent only to peers declaring the new revision), so
   results reach the ticket without 30 s polling; include verification evidence where it already exists (patch
   "confirmed by later scan", alert resolved).
7. **Alert kinds gated on declared revision** (P13 plus the 0.55/0.56 kinds; CR-3): AGENT_SILENT, DRIVE_FREE,
   UPTIME_LONG, UPDATES_MISSING, UPDATE_FAILED, WARRANTY_EXPIRING, never sent to an older peer.
8. **P6 remote launch as a deep link** returning `{launch_url, expires_at}` to Rem0te's own launch page, ticket ref
   recorded on the session, no credential in the response; `mode: view` refused unless the computer is MSA-managed
   and verified. Later: route through MSA grants once `MSA_GRANTS` is on.
9. **P7 handoff note** (staff note in History with ticket ref) — agreed, small.
10. **R4** omit the pause reason from 423/403 `CONTAINED` bodies; **R3** a documented technician-mapping probe that
    does not spend a delegation `jti`.
11. **R8 clarification** on `windows.update.install@1` from a ticket: whether it is proposable for one endpoint
    from the integration and its parameter schema in capabilities, so Clientst0r can add it to `KNOWN_ACTIONS` or
    stop expecting it.

Deliberately not asked for Phase A: new catalog actions (an agent release), POSIX execution, file manager, MSA
cutover, AI timeline (P11 — OPTIONAL AI on the Clientst0r side, decide separately), ticket state back to Rem0te (R9).
