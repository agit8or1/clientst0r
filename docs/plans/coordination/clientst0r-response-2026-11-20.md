
---

## 2026-11-20 (b) — Platform roadmap, Stage 8 backlog, MDM and backup coordination

From Clientst0r v3.17.734 (`f09abd92`). This entry is documentation only and asks for no code change.

- **Order.** The owner's directive sequences the work: Clientst0r is finished first, then Rem0te's major
  expansion follows as Stage 8. Before Stage 8, Rem0te gets only narrow compatibility, integration or critical
  security changes.
- **Stage 8 backlog.** Clientst0r keeps a record of what it needs from Rem0te in
  `docs/plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md`. It covers:
  - full Linux management (APT, DNF, Zypper, systemd, journal)
  - full macOS management (launchd, unified log, MDM-dependent features left to MDM)
  - cross-platform scripting and patching
  - alert-triggered remediation under signer policy
  - MDM coordination and backup-related device workflows
- **The backlog does not set Rem0te's priorities.** Where it differs from your `docs/rmm-expansion-audit.md`
  (PR #182) or `docs/readiness.md`, your documents decide Rem0te's order. Please point out anything we have
  recorded wrongly.
- **Contract items Clientst0r would consume before Stage 8.** All are already agreed or proposed, and none
  touches the signer, the agent checks or the catalog:
  - P10, the device summary
  - P2 and P3, read-only diagnostics, together with R13
  - R7, signed proposal-status events
  - R2, revision declaration, which the newer alert kinds need
  - P6, a launch deep link that carries no credential
  - P7, the handoff note
  - CR-1 and CR-2
- **Avoiding duplicate integrations.**
  - Clientst0r is planning MDM integrations (its Phase 106: Intune/Entra, Jamf Pro, Kandji, Apple Business
    Manager, Android Enterprise) and backup integrations (Phase 74.7–74.12: St0r/UrBackup and Comet Backup,
    besides PBS, restic, Borg and Kopia).
  - To avoid two integrations with the same provider, we suggest Rem0te reads MDM and backup state through
    Clientst0r, or links to it.
  - The exception is endpoint-level state that only the agent sees, such as whether the backup client service
    is running or the MDM enrollment state read on the device.
- **Capability flags for each endpoint.** Clientst0r 63.18 needs a capability set per endpoint, so it can
  display Linux and macOS endpoints at their real level and offer only supported actions. If
  `/capabilities` or the device summary (P10) could carry this, please say which. A proposal will follow as a
  contract item, not as a silent change.
