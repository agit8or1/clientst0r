# Rem0te — future feature expansion backlog (Stage 8)

**Plan now, implement later.** This backlog records the RMM requirements of the 2026-11-20 platform directive so
they are ready when Clientst0r reaches its completion checklist ([README.md](README.md) §"Clientst0r completion
checklist"). Nothing here is to be built before Stage 8, except narrowly scoped compatibility, integration or
critical security changes (see "Allowed before Stage 8").

**Where this lives and why.** Rem0te already has a canonical roadmap: `docs/readiness.md` §"Roadmap, in dependency
order" (Phases 1–12), with the detailed plan and owner decisions in `docs/implementation-status.md`. This file does
not replace them. It is kept in the Clientst0r repository because Clientst0r never edits Rem0te's tracked files;
it reaches Rem0te through the coordination file (`INTEGRATION_COORDINATION.clientst0r-response.md`), and the Rem0te
maintainers decide whether and where to merge it into their roadmap.

Rem0te is also writing its own RMM expansion audit and priorities (`docs/rmm-expansion-audit.md`, rem0te PR #182,
open on 2026-11-20). Where that document and this backlog differ, Rem0te's document decides Rem0te's order; this
file records what Clientst0r needs and the directive's rule that major expansion waits for Stage 8.

Evidence: [REM0TE_AUDIT.md](REM0TE_AUDIT.md) — static read of Rem0te 0.73.0 (`35549219`, 2026-11-20). Status key:
**Complete** (code and tests; the evidence level Rem0te itself records is given — Fleet, Lab, Sim, Unit),
**Partial**, **Missing**. Paths prefixed `r:` are in the Rem0te repository.

## Security model that every item must keep

- The signed Windows agent and its signed update chain; downgrades refused.
- The separate approval signer: passkey quorums on its own page, no approve route in the portal or the integration,
  requester cannot approve, direct mode refuses Clientst0r proposals.
- The agent re-verifies every signed plan (signature, device binding, closed catalog, closed parameters, validity
  window, pause and revocation state) and signs its results.
- A closed action catalog checked by `scripts/check-security-invariants.mjs`; credential extraction, backup
  removal, disabling defenses, granting admin rights and wiping disks are never added.
- POSIX agents stay read-only until a signed Linux/macOS agent exists.
- AI explains only; it never proposes, approves or executes.
- Integration peers in a root-owned file, Ed25519 only, replay windows, explicit organization and technician
  mappings with live access checks.

No backlog item weakens one of these. A capability is never claimed from a disabled UI control alone; it counts
only when the endpoint enforces it.

## Backlog by priority

### Priority 1 — complete common RMM functions

| Item | Today | Missing | Rem0te phase |
|---|---|---|---|
| Inventory and change history | Complete (Windows Fleet; Linux API; macOS recorded) | Software inventory on Linux and macOS | readiness Phase 7 |
| Health telemetry | CPU, memory, disk with history (Fleet) | Temperatures, SMART, battery, Defender/AV, firewall, BitLocker, TPM, Secure Boot | readiness Phase 7; implementation-status 1a–1d |
| Alerting | 13 monitor kinds, scopes, dedup, hysteresis, maintenance windows, escalation | Trend and predictive alerts, flapping, baselines | readiness Phase 7 |
| Process and service management | Complete in code; Lab on Windows Server | Fleet evidence; Linux/macOS (needs signed POSIX agent) | readiness Phase 4 |
| Event logs | Complete Windows | Linux journal, macOS unified log | readiness Phase 7 |
| Remote administration | RustDesk desktop (Fleet) | File manager (Design B decided), remote shell, registry editor | implementation-status 3 |
| Bulk operations and technician tools | Complete | — (keep within the 25-per-run action limit) | — |
| Deployment (`.msi`, deployment keys) | Partial, never run on Windows | Real-Windows validation | readiness Phase 1 |

### Priority 2 — cross-platform agents

| Item | Today | Missing |
|---|---|---|
| Windows signed agent | Executes the 12-action catalog | Fleet evidence for several actions |
| Linux and macOS | Read-only shell agents (`LINUX_AGENT_READ_ONLY`, `MACOS_AGENT_READ_ONLY`) | Signed Go agent for Linux/macOS (owner-approved Design A, 2026-11-16, not started) with capability-specific authorization per platform: patching, software, scripts, schedules, services, processes, logs, monitoring, restarts, policy compliance |

A read-only agent is never presented as able to manage anything.

Platform scope and the consistent device page (tabs, capability display) are specified in
[CROSS_PLATFORM_REQUIREMENTS.md](CROSS_PLATFORM_REQUIREMENTS.md): Linux — Debian/Ubuntu, RHEL-compatible
(Rocky, AlmaLinux), Fedora, SUSE/openSUSE where feasible, with systemd, journal and APT/DNF/Zypper patching under
approval policies, maintenance windows, staged rings, verification and signed instructions, respecting external
package-management policy; macOS — Apple Silicon and Intel, launchd, unified log, supported update and software
deployment, with enrollment-dependent features delegated to MDM.

### Priority 3 — third-party patching

| Item | Today | Missing |
|---|---|---|
| Windows Update | Complete in code; one Fleet install | Fleet evidence for rings |
| Application catalog | Partial: winget allowlist with version and installer-hash pinning (Sim) | Automatic updates of approved apps to new versions; other sources (private feeds, custom packages) by explicit design decision |
| Scheduling, canary/rings, maintenance windows, failure thresholds | Complete (Sim) | Real-fleet evidence |
| Reboots | Partial: rules and windows (Sim), never restarted a real computer | Real-fleet evidence, user postponement, console/RDP session detection |
| Compliance reporting | Complete (patch and software version, CSV) | — |
| Linux/macOS patching | Missing | Needs the signed POSIX agent |

### Priority 4 — scripting and automation

| Item | Today | Missing |
|---|---|---|
| PowerShell 5.1 as SYSTEM | Complete; Lab | PowerShell 7, bash/zsh, interpreter reporting, run-as (decided) |
| Library, versions, hashes, reviews, signer allowlist, parameters, schedules, groups, output redaction, audit | Complete | — |
| Result verification | Partial: exit code only | Post-condition checks |
| Predefined safe scripts | Missing | A reviewed read-only library: flush DNS, collect diagnostics, restart a named service, disk space, Windows Update status, installed software, event-log queries, network information |

Sensitive and destructive scripts stay behind the two-approval signer path.

### Priority 5 — automated remediation

Chain: monitor → condition → approved policy → action → verification → result → PSA update.

| Link | Today | Missing |
|---|---|---|
| Monitor → condition | Complete | — |
| Condition → action | Missing (monitoring never calls the actions service) | Alert-triggered automation under a signer-approved policy with cooldown, deduplication and run limits (implementation-status 2b) |
| Verification | Partial (later scan, alert auto-resolve) | Explicit post-action verification step |
| PSA update | Partial (alert → ticket; proposal results by poll only) | Signed proposal-status and fix events to the PSA |

An alert never authorizes unrestricted execution.

### Priority 6 — remote session security

| Item | Production (legacy) | Managed Secure Access (0.69–0.73, `MSA_GRANTS` off, Lab only) | Missing |
|---|---|---|---|
| Endpoint-enforced view-only and consent | Not enforced | Partial (agent applies and verifies) | Fleet validation; consent at the logon screen |
| Session credentials and expiry | Permanent password; advisory expiry | One-time password per grant, agent-enforced limits | Turning MSA on for the fleet |
| Revocation | Stops new launches only | Signed revocation ends the session | — |
| Clipboard and file transfer | Technician-side toggles | Enforced ceiling and presets | — |
| Timelines and audit export | Thin; audit chain export complete | Full timeline | — |
| Recording | Missing | Missing | Only if feasible without a modified client; not planned today |
| Platforms | — | Signed Windows agent only | Linux/macOS after Priority 2 |

### Priority 7 — endpoint management and compliance

Patch and software-version compliance exist. Missing: security baselines, encryption status, firewall state,
Defender/AV status, local administrators (Clientst0r request R15), risk scoring, device lifecycle and posture
reports. Dedicated EDR functions are integrated, not rebuilt.

### Priority 8 — backup and MDM integrations

Missing: backup monitoring adapters (implementation-status 5), Intune integration (today detection and refusal
only), Apple device management (warranty lookups only), Android Enterprise, compliance and enrollment status.
Prefer established providers over native backup or MDM engines; surface the status in Clientst0r.

**Coordination with Clientst0r (added 2026-11-20):** Clientst0r is planning the MDM integrations (its Phase 106)
and the St0r/UrBackup and Comet backup integrations (its Phase 74.7–74.12) on the Clientst0r side. To avoid two
integrations with the same provider, Rem0te should consume MDM and backup state **through Clientst0r** or link to
it, unless an endpoint-level need (for example, a backup agent's local service state, or MDM enrollment state
read on the device) requires a Rem0te monitor. Backup-related device workflows (restore to a device, verifying a
backup client is installed and running) are Stage 8 items that use the provider's own API for the backup action
and Rem0te only for endpoint state.

### Priority 9 — better Clientst0r integration

| Item | Today | Missing (contract item) |
|---|---|---|
| Ticket ↔ device, customer and technician mappings, alert → ticket (8 kinds) | Complete | The 6 newer alert kinds, sent only to peers that declare a newer revision |
| Diagnostic requests (read-only, no AI) | Missing | P2/P3 (revision 3) and R13 |
| Device health summary in the ticket | Missing | P10, with an observation time per field group |
| Remediation proposals and results | Partial (2 proposable actions; results by poll) | R7 signed status events; P5 fix events; answer on `windows.update.install@1` from a ticket (R8) |
| Patch status in tickets | Partial (only on REBOOT_PENDING) | Patch summary on demand |
| Secure session launch | Missing | P6 as a deep link with no credential in the response; MSA grants behind it later |
| Handoff note | Missing | P7 |
| Asset reconciliation | Partial (public API sync) | Over the signed contract |
| Cross-application audit references | Partial | A shared audit reference on every integration action |
| AI diagnostics | Complete for ticket analysis jobs | Device timeline (P11), unagreed |

The two applications never merge into one privilege domain.

## Allowed before Stage 8

Only through the coordination file, each touching neither the signer, the agent's checks nor the action catalog:

1. Bring Rem0te's coordination and readiness records up to date with Clientst0r's actual state; fix the stale
   `examples/index.json` version label (R10).
2. Answer R2 (how a peer declares its supported revision).
3. Prebuilt cross-peer test tooling and a machine-readable approval page (CR-1, CR-2) for the two-application tests.
4. The Priority 9 contract items Clientst0r roadmap Phase 63 (RMM integration and technician workspace) consumes: P10 device
   summary, read-only diagnostics (P2/P3, R13), R7 status events, newer alert kinds, P6 launch deep link, P7
   handoff note.
5. Refusal bodies without the pause reason (R4) and a documented technician-mapping check (R3).
6. Critical security fixes.

## Order once Stage 8 starts

1. Priority 9 items not already delivered before Stage 8.
2. Priority 2 signed POSIX agent — full Linux management first, then full macOS management (it unblocks the
   Linux/macOS parts of Priorities 1, 3, 4, 6).
3. Priority 6 Managed Secure Access on the fleet.
4. Priority 1 health telemetry and Priority 7 compliance (shared collectors).
5. Priority 4 PowerShell 7, bash, run-as and the safe-script library.
6. Priority 5 alert-triggered remediation (depends on 4 and on Clientst0r's event layer).
7. Priority 3 automatic third-party updates.
8. Priority 8 MDM coordination and backup-related device workflows.
9. Additional endpoint security controls (Priority 7 remainder).
