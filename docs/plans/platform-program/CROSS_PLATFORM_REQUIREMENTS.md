# Cross-platform device management — requirements across Clientst0r, Rem0te, MDM and backup

Planning document, 2026-11-20. **Nothing here is built.** It records how Windows, Linux and macOS devices, MDM
providers and backup providers fit together, so that the Clientst0r phases (63, 74, 106) and the future Rem0te
work (Stage 8, [REM0TE_FEATURE_EXPANSION_ROADMAP.md](REM0TE_FEATURE_EXPANSION_ROADMAP.md)) do not contradict each
other.

## Who does what

| Concern | Owner | Clientst0r's role |
|---|---|---|
| Endpoint agent, monitoring, scripts, patching, remote sessions | Rem0te | Shows state, requests and records; never executes |
| Approvals for endpoint actions | Rem0te's approval signer | Sends proposals; a technician's request or an AI suggestion is never an approval |
| Enrollment, supervision, configuration profiles, Apple and Android management protocols, wipe | MDM provider (Intune, Jamf Pro, Mosyle, Kandji, ABM via a provider, Android Enterprise via a provider) | Inventory, compliance and approved requests through the provider's API (Phase 106) |
| Backup engine, schedules, restores | St0r/UrBackup, Comet, PBS, restic/Borg/Kopia | Status, coverage, alerts, reports and permissioned requests (Phase 74) |
| Customers, contracts, tickets, billing, documentation, workflow approvals | Clientst0r | Owner |

The applications stay separate privilege domains; St0r and Comet stay independent backup providers.

## One device, several sources

A Clientst0r asset can be linked to one Rem0te endpoint, one or more MDM records and one or more backup
protected systems. Each link uses the provider's stable identifier and is confirmed once; hostname or serial
matches are suggestions. Every fact on the device page carries its source and age. A device with no link is
"unmatched", which is never shown as "unprotected" or "unmanaged".

## Consistent device page (Rem0te, Stage 8; mirrored in Clientst0r where data exists)

Tabs: Overview, Hardware, Software, Processes, Services, Patches, Scripts, Monitoring, Logs, Network, Remote
Access, Activity, Security — the same on Windows, Linux and macOS, with platform-specific implementations behind
them. A tab or action appears only if the platform **and** the installed agent version support it, and the page
says why when it does not (platform, agent version, missing MDM enrollment, or permission).

## Platform scope (Rem0te, deferred to Stage 8)

**Linux:** Debian/Ubuntu, RHEL-compatible (Rocky, AlmaLinux), Fedora; SUSE/openSUSE where feasible. Hardware and
software inventory, CPU/memory/disk monitoring, processes, systemd services, journal, network diagnostics,
patch detection and deployment through APT, DNF and Zypper, package install and removal, shell scripts and
schedules, restart management, automation, alerts, remote support. Patching uses approval-based policies,
maintenance windows, staged rings, verification and signed instructions, and respects an existing external
package-management policy (e.g. a configuration-management tool already owning the packages).

**macOS:** Apple Silicon and Intel where practical. Inventory, installed software, hardware, monitoring, patch
detection, supported update deployment, software deployment and package management, processes, launchd
services, unified log, diagnostics, approved scripts, schedules, restart workflows, alerts, remote support.
Anything that needs enrollment, supervision or Apple management protocols (configuration profiles, managed
software updates on supervised devices, FileVault escrow, lock and wipe) goes through the MDM integration; an
agent is never presented as a substitute for MDM.

**Both:** no unrestricted privileged shell because a technician can open the RMM; scripts follow the same
library, review, signing and two-approval rules as on Windows. Until the signed Linux/macOS agent exists, those
agents are read-only and are labelled read-only everywhere, including in Clientst0r.

## Security model to preserve (every platform)

Signed agent and update chain; signed action plans verified by the agent; the separate approval signer;
per-customer permissions; tamper-evident audit; containment pauses; device identity verification; least-privilege
provider credentials; customer isolation; credential rotation; TLS verification; replay protection and
idempotent event processing; restricted restore and MDM management permissions; no default destructive
automation; no secrets sent to AI.

## Dependencies

| Need | Depends on |
|---|---|
| Linux/macOS devices shown in Clientst0r at their real capability | Rem0te contract capability flags per endpoint (Priority 9) |
| macOS profile, update and wipe actions | Phase 106 MDM connection for that customer |
| Backup coverage on a Linux/macOS server | Phase 74.9 matching; Rem0te endpoint identity |
| Alert-triggered remediation on any platform | Rem0te Priority 5 and signer policy; Clientst0r Phase 82 events |
| Leaver workflow retiring a device | Phase 106.5, Phase 109 for the account, approvals in Clientst0r and in the provider |
