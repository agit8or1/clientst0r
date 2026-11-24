# Competitive program — Rem0te integration test matrix

What must be proven, and how, before the Clientst0r ↔ Rem0te integration (contract `ticket-rmm-v1`) is called
complete. Program Phase 1 is done only when the **remediation chain** passes between two real applications:

> Rem0te alert → Clientst0r ticket → read-only diagnostic → remediation proposal → independent approval in
> Rem0te → execution result → ticket update (and alert recovery confirming the fix).

State at the time of writing (2026-11-19): Clientst0r v3.17.720; cross-peer CI pinned to Rem0te 0.30.1
`4b2b9f5c`, contract revision 2; Rem0te HEAD 0.67.0 `2dab9ef`, still revision 2. Revision 3 (P1–P10) agreed
2026-11-11 and not built by Rem0te. Revisions 4–6 (P11–P16) proposed by Rem0te, unanswered by Clientst0r.

## Legend

- **Existing test.** `E2E sN` = scenario in `scripts/e2e/cross_peer/run.py` (real Clientst0r + real Rem0te,
  deterministic model stub), run by `.github/workflows/cross-peer-e2e.yml`. `Unit` = Clientst0r test against
  Rem0te's byte vectors or the in-process fake (`integrations/rem0te/testing.py`). `None` = no test.
- **Unit files referenced.** `integrations/tests_rem0te.py` (IT-R), `integrations/tests_rem0te_rev2.py`
  (IT-R2), `psa_ai/tests_rem0te.py` (PA-R), `psa_ai/tests_rem0te_rev2.py` (PA-R2), `psa_ai/tests_rmm.py`
  (PA-RMM), `psa/support_workflows/tests.py` (SW), `psa/routing/tests_alerts.py` (RT-A).
- **Rem0te dependency.** Contract revision the step needs, and whether Rem0te HEAD has built it.
- **Status.** *Passing (0.30.1)* = passes in CI against the old pin only; *Unit only*; *Not tested*;
  *Blocked* = cannot be tested until Rem0te ships the named item.
- New scenario numbers (s12+) are proposals for `run.py`; names are suggestions.

## Matrix

| # | Step / property | Existing test | Rem0te dependency | What the test must assert | Status |
|---|---|---|---|---|---|
| 1 | Pairing (capabilities, revision negotiation) | E2E s1; Unit IT-R `CheckPairingTests`, IT-R2 `CapabilityRevisionTests` | Rev 2; built | Clientst0r validates `/capabilities` against rev 2 at the **new pin**; declared and validated revision stored; Rem0te ≥ 0.59 Bearer refusal does not affect pairing (no `Authorization` header sent) | Passing (0.30.1); not run at 0.67 |
| 2 | Second-administrator enablement | None in E2E (bypassed, `run.py:355`); Unit PA-RMM `test_every_provider_needs_a_second_administrator` | None | A pairing stays inactive until a distinct second administrator approves; E2E drives the approval instead of bypassing it | Unit only |
| 3 | Tenant pinning (business binding, TOFU) | E2E s1, s6; Unit PA-RMM `TenantPinTests` | Rev 2; built | Each Clientst0r Organization binds only its own `organizations[]` entry; a changed `business_id` → `BUSINESS_MISMATCH`, Configuration Required, no further calls | Passing (0.30.1) |
| 4 | Re-map after revoke | None | Rev 2; Rem0te unique keys include revoked rows (unverified) | Revoking and re-mapping the same Organization works or fails with a documented, mapped reason | Not tested |
| 5 | Technician mapping and probe | E2E s11 (probe); Unit IT-R2 `TechnicianProbeTests` | R3 (documented probe) not built | Mapped technician → ready; unmapped → mapped reason; probe result does not depend on undocumented 404-vs-403 once R3 exists | Passing (0.30.1); probe undocumented |
| 6 | Asset ↔ endpoint mapping | E2E s1 (device sync), s4/s6 (asset by id); Unit PA-RMM `TargetBoundaryTests` | Path A public API; built | Devices matched by endpoint id never by name; `client_id` must equal the pinned tenant; device sync via the **scheduled** task, not a direct call | Passing (0.30.1); scheduled path untested |
| 7 | Alert sync (push + poll, rev-2 kinds) | E2E s4, s5, s11; Unit PA-R `AlertTicketTests`, PA-R2 `SkippedEventTests` | Rev 2; built | `alert.raised`, `alert.updated`, `alert.resolved` each applied once, in order; cursor advances; skipped events re-applied after next good check | Raised: passing (0.30.1); updated/resolved: not asserted |
| 8 | Alert → ticket | E2E s4, s5, s6; Unit PA-R `AlertTicketTests`, RT-A | Rev 2; built | Exactly one staff-only ticket per alert; link-back visible in Rem0te; alert policy (when on) groups by device+issue and respects maintenance windows | Passing (0.30.1) |
| 9 | Double-ticket guard (Rem0te 0.55 automatic PSA tickets) | None | Rem0te must expose or suppress automatic PSA tickets for contract-paired businesses (not built) | With both paths configured, Clientst0r warns in the wizard and opens one ticket per alert | Blocked |
| 10 | Read-only diagnostics | None for Rem0te; Unit PA-RMM `DiagnosticTests` (fixture processor, HMAC path) | Rev 3 P1–P3; **not built** (catalog exists internally since 0.31) | Only advertised diagnostics offered; request carries delegation; result staff-only, size-capped, sanitised; counted in theft detection; nothing changes on the endpoint | Blocked |
| 11 | Remediation proposal | None end to end; Unit PA-R `ActionProposalTests`, PA-R `L1PermissionTests`; E2E s9 (local L1 refusal only) | Rev 2 action proposals; built. Fixture technician lacks the action capability and no signer is configured (`run.py:327`) | L2 technician proposes `windows.service.start@1` with fixed params; Rem0te returns `awaiting_approval`; idempotent re-send returns the same proposal; changed body → 409 | Not tested end to end |
| 12 | Independent approval in Rem0te | Unit PA-RMM `test_clientst0r_cannot_approve_and_has_no_route_for_it` | Rem0te signer approvals; built. Needs a test signer or Rem0te simulator in the E2E harness | Approval is performed only by the Rem0te test driver as a distinct signer; Clientst0r exposes no approve route; the proposing technician cannot approve | Not tested end to end |
| 13 | Execution result | None end to end; Unit PA-RMM `FixReferralTests` (status from signed events, fixture) | Rev 2 `GET /action-proposals/{id}`; built. R7 push events not built | Clientst0r poll observes each terminal state (`succeeded`, `failed`, `expired`, `refused`) and maps it via `STATUS_MAP`; `observed` stored as data | Not tested end to end |
| 14 | Ticket update from result | None | Rev 2 for poll; P5 verification evidence not built | Ticket gets one staff-only note per terminal state; AI and automation history (56.9) shows proposal → approval → outcome; result never changes ticket status on its own | Not tested |
| 15 | Alert recovery confirms fix | None (support-workflow outcome via `alert.resolved` not exercised); Unit SW | Rev 2 `alert.resolved`; built | After a successful result the agent simulator clears the condition; `alert.resolved` arrives; support-workflow run records outcome "confirmed by monitoring" | Not tested |
| 16 | Offline endpoint | Unit (`agent_offline_reason`, `ENDPOINT_NOT_READY` mapping) | Rev 2; built | Proposal/diagnostic against an offline endpoint is refused with the mapped reason; nothing queued silently | Unit only |
| 17 | Expired job / proposal | Unit PA-R2 `ExpiredApprovalTests` | Rev 2; built (`MAX_JOB_TTL_S` 24 h) | A proposal not approved within its window becomes `expired` in Clientst0r; a late approval in Rem0te cannot execute; job `job.expired` event applied once | Unit only |
| 18 | Retry across Clientst0r outage | E2E s5 (fast restart), s8 (unavailable peer, backoff); Unit PA-R2 `OutageRecoveryTests`, IT-R2 `HealthAndBackoffTests` | R11 (retry until expiry) **not built** | Alert and job delivered exactly once after a 60 s Clientst0r outage (fails today: Rem0te stops after 3 attempts) | Passing for short restart; long restart fails (R11) |
| 19 | Duplicate delivery | E2E s4, s5; Unit (event-id dedup) | Rev 2; built. P9 `Idempotency-Key` header not built | Same `event_id` applied once; same `idempotency_key` + same body → replayed; different body → 409 `IDEMPOTENCY_CONFLICT` | Passing (0.30.1) for events; proposals not cross-peer |
| 20 | Containment pause | E2E s11 (job); Unit PA-R2 `ContainmentTests` (proposal) | Rev 2 `paused[]`; built. R4 (reason in body) open | Job under pause fails once with fixed text, no retry; proposal under pause → `unavailable` (`CONTAINED`), not "rejected"; pause reason not stored or shown; cleared after the pause lifts | Job: passing (0.30.1); proposal: unit only |
| 21 | Revoked permission | E2E s7; Unit PA-RMM | Rev 2; built | Revoked technician refused (`ACTOR_REVOKED`) on next call; **new:** revoke between propose and approve → approval in Rem0te refused or execution blocked, and Clientst0r shows the refusal | Passing (0.30.1) for revoke-before-call; mid-flight not tested |
| 22 | Tenant isolation | E2E s3, s6, s1; Unit PA-RMM `TargetBoundaryTests`, PA-R2 `SkippedEventTests` (foreign events) | Rev 2; built | Same PC name in two Organizations never cross; foreign-organization events recorded and never applied; proposals for another Organization's endpoint refused before sending | Passing (0.30.1) |
| 23 | Replay protection | Unit IT-R `InboundAuthTests`, `FixtureVectorTests` | Rev 2; built | Re-sent signed request outside ±120 s or with a used nonce refused on both sides; delegation `jti` single-use; `req_sha256` binds body | Unit only; add one cross-peer replay case |
| 24 | Key rotation across peers | Unit IT-R2 `KeyRotationOverlapTests` | Rev 2; built | Stage → both keys accepted by Rem0te → switch → old key refused; no failed calls during overlap | Unit only |
| 25 | AI boundary | E2E s2 (analysis job is staff-only, redacted); Unit PA-RMM `test_clientst0r_cannot_approve...`, `test_from_an_analysis_suggestion_uses_the_stored_text` | Rev 2 (`next_steps[].executable` false); built | An analysis suggestion creates no proposal without a technician action; a proposal created from an AI suggestion still lands `awaiting_approval`; no AI path can call approve; with `psa_ai_enabled` off, the chain (steps 8–15) still works without AI | Partially (s2); proposal-from-AI not cross-peer |
| 26 | "Technician asks for a fix" is not approval | Unit PA-RMM | Rem0te signer; built | Proposal created by the requesting technician remains `awaiting_approval` until a distinct Rem0te signer acts; `approval.self` locked | Unit only |
| 27 | Refusal codes (incl. `DIRECT_MODE_PORTAL_ONLY`) | E2E s10 (secret-free reasons); Unit (existing codes) | `DIRECT_MODE_PORTAL_ONLY` built in Rem0te (~0.40, version unverified); envelope shape unverified | With signer direct mode on, a proposal is refused and Clientst0r shows a specific, secret-free reason; a 403 outside the `{error:{code}}` envelope is mapped as unknown refusal, not "rejected by approver"; every code in Rem0te `errors.ts` used on the proposal path has a mapping | Not tested (code not mapped) |
| 28 | Newer alert kinds (DRIVE_FREE, UPTIME_LONG, UPDATES_MISSING, UPDATE_FAILED, WARRANTY_EXPIRING, AGENT_SILENT) | None | New contract revision; **not built** (Rem0te filters them) | Until the revision ships: an unknown kind is refused fail-closed and the connection page lists unsent kinds. After: each kind opens one ticket with the right template, severity and dedup | Blocked |
| 29 | `windows.update.install@1` | None | Proposable in Rem0te 0.67 (`r0:apps/api/src/actions/catalog.ts:93,192`); not in Clientst0r `KNOWN_ACTIONS` | Either proposed with fixed safe params through the full chain (11–15), or refused locally with a documented reason (user decision) | Not tested |
| 30 | Bearer header refusal (Rem0te ≥ 0.59) | None | Built | Clientst0r sends no `Authorization` header on contract calls; Path A public API (Bearer `rk_`) unaffected | Not tested at ≥ 0.59 |
| 31 | Remote launch (P6) and handoff (P7) | Unit PA-RMM `LaunchTests`, `HandoffTests` (fixture, HMAC path) | Rev 3 P6/P7; **not built** | Launch only with live authorization; "Sent" only on confirmed receipt | Blocked |
| 32 | Device summary (P10) | None | Rev 3 P10; **not built** | Summary shown with `observed_at` and agent version; stale shown as stale | Blocked |
| 33 | Rem0te-initiated requests (P11 timeline, P12 capabilities, P16 ticket request) | None (P16 answers 404, fail-closed) | Built in Rem0te, gated; **unanswered** by Clientst0r | Until agreed: unknown envelopes → 404 and nothing stored. After agreement: per accepted proposal; P11 gated by `psa_ai_enabled` | Blocked on Clientst0r decision |

## Scenarios to add to `run.py`

Ordered by dependency. Each must leave `run.py` exit 0 only if it passes.

| Scenario | Covers rows | Needs |
|---|---|---|
| s12 `remediation_chain` | 8, 11, 12, 13, 14, 15, 25 (with AI off), 26 | Fixture technician with the Rem0te action capability; a test signer (or Rem0te simulator) configured in `rem0te_fixtures.mjs`; agent simulator able to report a service start and clear the alert |
| s13 `direct_mode_refusal` | 27 | Rem0te signer direct mode toggled by the fixture |
| s14 `proposal_under_containment` | 20 | Pause applied via Rem0te admin API in the fixture |
| s15 `revoke_mid_flight` | 21 | Revoke technician mapping between propose and approve |
| s16 `alert_lifecycle` | 7, 15 | Assert `alert.updated` and `alert.resolved` handling |
| s17 `second_admin_enablement` | 2 | Remove the `run.py:355` bypass; drive two distinct administrators |
| s18 `long_outage` | 18 | Stop Clientst0r for 60 s; expected to fail until R11 ships (mark as known-failing, non-blocking) |
| s19 `offline_and_expiry` | 16, 17 | Agent simulator offline; short proposal window |
| s20 `replay_cross_peer` | 23 | Capture and re-send one signed request after the window |
| s21 `ai_suggestion_to_proposal` | 25 | AI on with the model stub; suggestion → technician proposes → still `awaiting_approval` |

## CI changes

1. Re-pin `PIN.json` to Rem0te 0.67.0 (or the next tag) and re-vendor `contract/` (prose docs, interop file,
   `proposed/` as non-normative). The blocking job runs at the pin.
2. Add a non-blocking matrix leg against Rem0te `main` that reports drift (schema diff + s1–s11) without
   failing the push.
3. Record the Rem0te version and contract revision in the job summary so the coordination record can cite a
   run id.

## Definition of done for program Phase 1

All rows 1–30 are *Passing* at a pin no older than the Rem0te release current when the phase closes, s12–s17
and s19–s21 pass in the blocking job, and s18 passes once Rem0te ships R11. Rows 31–33 and row 28 are
tracked separately: they do not block Phase 1 completion but each must have a test before its feature is
called shipped.
