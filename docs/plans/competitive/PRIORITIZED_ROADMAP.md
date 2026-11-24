# Competitive program — prioritized implementation order

Releasable increments in dependency order, derived from `GAP_ANALYSIS.md` (gap rows `n.nn`),
`SECURITY_REVIEW.md` (`SR-nn`) and `INTEGRATION_TEST_MATRIX.md` (rows and scenarios `sNN`). Each increment is
meant to ship as one or more ordinary releases (version bump, CHANGELOG, ROADMAP update in the same commit, per
`CLAUDE.md`).

Ground rules carried from the program brief and existing roadmap phases:

- Clientst0r does not build endpoint RMM functionality. Endpoint execution, approval of endpoint actions and
  agent work stay in Rem0te. Clientst0r proposes, displays and records.
- AI work is **OPTIONAL AI**, gated by `psa_ai_enabled` and the customer AI policy. Clientst0r owns provider
  keys; Rem0te supplies redacted evidence; AI never authorizes endpoint execution; a technician asking for a
  fix is not approval.
- Billing never uses unverified endpoint counts: counts are snapshotted with source and freshness, reconciled,
  and adjustments go through approval.
- No destructive import without explicit confirmation and a verified backup.
- Existing phases are extended, not duplicated. Where a new phase is needed it is listed as "proposed Phase
  9x"; numbers are tentative until the user approves them and they are added to `docs/ROADMAP.md` as
  `[planned]`.
- Roadmap prose stays free of competitor names; this planning directory is internal.

Size key: **S** ≤ 1 week, **M** 1–3 weeks, **L** 3–6 weeks of focused work at the project's usual cadence.

## Increment summary

| # | Increment | Program phase | Roadmap phase | Rem0te coordination | Size | Depends on |
|---|---|---|---|---|---|---|
| R-01 | Reproduce and fix the security findings | 8 | 51 (extends) | n | M | — |
| R-02 | Re-pin and extend the cross-peer E2E | 1 | 63.10, 56.8 (extends) | y | M | — |
| R-03 | Map new Rem0te refusal codes and alert kinds | 1 | 63.1 (extends) | y | S | R-02 |
| R-04 | Integration honesty and coordination record | 1, 9 | 63.10, 84 (extends) | y (read) | S | R-03 |
| R-05 | Workflow automation safety | 4 | proposed Phase 91 | n | M | R-01 |
| R-06 | Answer Rem0te's revision 4–6 proposals; Clientst0r capabilities document (P12) | 1 | 63 (extends), 79 (relates) | y | S–M | R-02 |
| R-07 | Remediation status on the ticket | 2 | 52, 63.4 (extends) | n | M | R-02 (s12 passing) |
| R-08 | Revision-3 consumers behind capability flags | 1 | 56.5, 56.6, 57.6, 63.4 (extends) | y | L | R-06; Rem0te rev 3 |
| R-09 | Recurring charges and data-fed agreements | 5 | 70.4 (extends) | n | M | R-05 |
| R-10 | Endpoint count snapshots and billing reconciliation | 5 | proposed Phase 92 (or 70.6) | y | M | R-09; R-08 for Rem0te counts |
| R-11 | Approval-controlled billing adjustments | 5 | 36, 71.10 (extends) | n | M | R-01 (SR-04) |
| R-12 | Business-hours SLA calendars | 4 | proposed Phase 93 | n | M | — |
| R-13 | Security alert dedup, signature migration, adapter honesty | 6 | 82.2, 84.1, 84.3 (extends) | n | M | R-01 |
| R-14 | Event-layer consumers and wallboard presets | 6 | 83.1–83.3, 85.1 (extends) | n | L | R-13 |
| R-15 | AI service-desk orchestration (OPTIONAL AI) | 3 | 56, 63.5, 90 (extends) | y | L | R-07, R-08 |
| R-16 | Audit-log integrity, retention and routine backups | 8 | proposed Phase 94 (or 51) | n | M | — |
| R-17 | Import framework conformance and the first PSA importer | 7 | proposed Phase 95 (extends 61) | n | L | R-16 (backups) |
| R-18 | Further PSA importers | 7 | proposed Phase 95 | n | L | R-17 |
| R-19 | API key resource scopes and public-endpoint throttles | 8 | 81 (follow-up), 64 | n | M | R-01 |
| R-20 | PSA automation follow-ups (CSAT, recurring tickets, closure) | 4 | 12, 87 (extends) | n | M | R-05 |
| R-21 | UX and reporting: freshness, empty states, review packs | 9 | 67, 83.1, 89 (extends) | n | M | R-14 |

## Increments

### R-01 — Reproduce and fix the security findings

- **Goal.** Turn each audit finding into a failing test, then fix the ones that reproduce.
- **Scope.** First wave: SR-01 (workflow re-entrancy + `create_charge`), SR-02 (PBS SSRF), SR-04 (invoice
  approval SoD), SR-05 (bulk document upload), SR-18 (upload logging). Second wave in the same increment if
  time allows: SR-03, SR-06, SR-11, SR-13, SR-14, SR-15, SR-16, SR-20 (delete dead module). Findings that do
  not reproduce are closed with the test kept as a regression guard and a note in `SECURITY_REVIEW.md`.
- **Dependencies.** None.
- **Roadmap.** Extends Phase 51 (reliability and customer-boundary hardening, in progress).
- **Rem0te coordination.** No.
- **Tests.** One test per finding as listed in `SECURITY_REVIEW.md`, in the owning app's tests module.
- **Acceptance.** Every first-wave finding has a merged test that failed before its fix (or is recorded as
  not reproducible with evidence); `manage.py test psa backup_monitoring docs assets crm` green; no new
  `csrf_exempt` without a justification comment.
- **Size.** M.

### R-02 — Re-pin and extend the cross-peer E2E

- **Goal.** Prove the integration against current Rem0te and run the full remediation chain between two real
  applications.
- **Scope.** Bump `PIN.json` to Rem0te 0.67.0 or the next tag; re-vendor `contract/` (prose, interop file,
  `proposed/` as non-normative); run s1–s11; add s12 (remediation chain), s16 (alert lifecycle), s17
  (second-admin enablement, removing the `run.py:355` bypass), s19 (offline and expiry), s20 (replay), s21
  (AI suggestion → proposal); add a non-blocking leg against Rem0te `main`. Fixtures need a technician with the
  Rem0te action capability and a test signer or Rem0te's simulator.
- **Dependencies.** None in Clientst0r. Needs Rem0te to confirm how a test signer / agent simulator is
  configured in fixtures (request RQ-03).
- **Roadmap.** Extends 63.10 and 56.8.
- **Rem0te coordination.** Yes.
- **Tests.** `INTEGRATION_TEST_MATRIX.md` rows 1–3, 5–8, 11–17, 19, 21–26.
- **Acceptance.** Blocking CI job green at the new pin with s12 asserting: L2 proposal → `awaiting_approval`
  → approval by a distinct Rem0te signer → terminal status polled → staff-only ticket note → `alert.resolved`
  → support-workflow outcome confirmed. Clientst0r exposes no approve route (asserted). Job summary records
  Rem0te version, contract revision and run id.
- **Size.** M.

### R-03 — Map new Rem0te refusal codes and alert kinds

- **Goal.** Correct, specific behaviour for everything Rem0te 0.31–0.67 can return today.
- **Scope.** Add `DIRECT_MODE_PORTAL_ONLY` to `actions.REFUSAL_TEXT`; parse 403s outside the
  `{error:{code}}` envelope as an unknown refusal with the raw code stored; review every proposal-path code in
  Rem0te `errors.ts`; decide `windows.update.install@1` (add to `KNOWN_ACTIONS` with fixed safe parameters, or
  exclude with the reason documented in `pairing.py` and `support_workflows/builtins.py`); keep unknown alert
  kinds fail-closed and show the connection-page notice listing kinds Rem0te does not send (gap 9.01).
  Add s13 (direct mode) and s14 (proposal under containment).
- **Dependencies.** R-02 (the new pin).
- **Roadmap.** Extends 63.1.
- **Rem0te coordination.** Yes: envelope shape for direct mode (RQ-09).
- **Tests.** Unit per code using recorded bodies; s13, s14; template test for the notice.
- **Acceptance.** Matrix rows 20, 27, 29 passing; row 28 shows the notice and fail-closed refusal.
- **Size.** S.
- **User decision.** Whether to support `windows.update.install@1` from Clientst0r.

### R-04 — Integration honesty and coordination record

- **Goal.** No page or document claims more than what has passed.
- **Scope.** Update the Clientst0r sections of `INTEGRATION_COORDINATION.md` (header still says revision 1 /
  3.17.660); fix FEATURES.md:617 ("released versions pair Rem0te over HMAC"); label the 15 security-vendor
  choices without adapters as "not supported yet" and stop the Defender stub's `test_connection` from
  reporting success (gaps 6.02, 9.01). Post the Rem0te-side requests below through the coordination file.
- **Dependencies.** R-03 (so the record cites a current run).
- **Roadmap.** Extends 63.10 and 84 (honesty before 84.4–84.7).
- **Rem0te coordination.** Yes (record only).
- **Tests.** Template tests for the labels; a test that the stub's connection test reports "not implemented".
- **Acceptance.** No UI claims support for a vendor without an adapter; the coordination record cites the
  R-02/R-03 CI run id.
- **Size.** S.

### R-05 — Workflow automation safety (proposed Phase 91)

- **Goal.** Automation that can be inspected, tested before it runs, and cannot run away.
- **Scope.** Per-execution log model (trigger, rule version, each action with result, actor, duration);
  dry-run endpoint evaluating rules against a chosen ticket with no side effects; per-rule and per-ticket rate
  limits with a storm cut-off; permission checks for high-impact actions (`create_charge` behind approval or
  cap + fire-once, assign/watch through the routing engine's authorization); deprecate legacy workflow
  assignment actions in favour of routing. The loop guard itself ships in R-01.
- **Dependencies.** R-01 (SR-01, SR-03 fixed).
- **Roadmap.** Proposed Phase 91 "Workflow automation safety" — Phase 14 (visual workflow engine) is marked
  shipped, so a new phase is cleaner than reopening it.
- **Rem0te coordination.** No.
- **Tests.** Execution-log contents; dry run writes nothing and sends nothing; limit trips and records;
  cross-customer assign/watch refused; `create_charge` idempotent.
- **Acceptance.** Gap rows 4.01–4.05 closed; every rule firing visible on the rule page with its actions.
- **Size.** M.

### R-06 — Answer Rem0te's revision 4–6 proposals; Clientst0r capabilities document (P12)

- **Goal.** Unblock gated Rem0te features with explicit decisions instead of silence.
- **Scope.** Written answers for CS-9/10/11: P11 `device_timeline_v1` (OPTIONAL AI), P12 Clientst0r signed
  capabilities document with `contract_revision` and `features` (also settles R2 and SR-21), P13
  `AGENT_SILENT`, P14/P15 support requests, P16 `ticket.create_request` (requires idempotency and a
  duplicate rule against alert tickets). Build P12 on the Clientst0r side once agreed.
- **Dependencies.** R-02.
- **Roadmap.** Extends Phase 63; relates to Phase 79 (Connect) — decide whether P12 lives in
  `ticket-rmm-v1` or Connect.
- **Rem0te coordination.** Yes.
- **Tests.** P12: schema test against Rem0te's `peer-capabilities` proposal; signature test; unknown-field
  handling per R2.
- **Acceptance.** Every open proposal has an accepted / declined / deferred answer in the coordination file;
  P12 served and verified by Rem0te in a cross-peer run (if accepted).
- **Size.** S (answers) to M (P12 build).
- **User decision.** Which of P11, P13–P16 to accept; whether P12 belongs to `ticket-rmm-v1` or Connect.

### R-07 — Remediation status on the ticket

- **Goal.** One place on the ticket that shows endpoint work honestly.
- **Scope.** A staff-only strip in the ticket RMM panel: proposed → awaiting approval in Rem0te → approved /
  refused / expired / contained → result → verified by monitoring, with times and the Rem0te reference;
  contract coverage label per time entry (gap 2.03). No approve button anywhere.
- **Dependencies.** R-02 (s12 passing) so the states shown are the states proven.
- **Roadmap.** Extends Phase 52 and 63.4.
- **Rem0te coordination.** No (uses rev-2 polling).
- **Tests.** Template test per state; permission test (L1 sees status, cannot propose); browser check at
  phone and tablet widths.
- **Acceptance.** Gap rows 2.01–2.03 closed; s12 screenshot of the strip attached to the release notes.
- **Size.** M.

### R-08 — Revision-3 consumers behind capability flags

- **Goal.** Clientst0r ready for diagnostics, fixes, remote launch, handoff and device summary the day Rem0te
  ships revision 3.
- **Scope.** Rem0te branches in `rmm_actions` for P2 diagnostics, P4 `/fixes`, P6 remote launch and P7
  handoff using the Ed25519 client (not `processor._request`); P3/P5 event handling; P9 `Idempotency-Key`
  header; P10 summary in the Device Workspace; optional client certificate per connection (SR-23). All
  hidden unless capabilities advertise them.
- **Dependencies.** R-06; Rem0te revision 3 for cross-peer acceptance.
- **Roadmap.** Extends 56.5, 56.6, 57.6, 63.4, 74.3.
- **Rem0te coordination.** Yes.
- **Tests.** Unit against Rem0te's revision-3 examples once published; matrix rows 10, 31, 32 cross-peer.
- **Acceptance.** Features stay invisible at revision 2; matrix rows 10, 31, 32 pass cross-peer at a
  revision-3 pin.
- **Size.** L (Clientst0r side), schedule driven by Rem0te.

### R-09 — Recurring charges and data-fed agreements

- **Goal.** What the UI promises about recurrence actually happens.
- **Scope.** Scheduler task generating recurring `Charge` instances with catch-up cap, dry run and
  idempotency (or remove the recurrence fields from the form if the user prefers); `ClientServicePlan` read by
  the invoice generator or explicitly retired; `ContractMeter` fed only from snapshots (R-10) or by hand with
  an audit entry.
- **Dependencies.** R-05 (charge creation rules).
- **Roadmap.** Extends 70.4 ("bill bundle items and recurring charges").
- **Rem0te coordination.** No.
- **Tests.** Generator idempotency, catch-up cap, dry run; plan → invoice lines.
- **Acceptance.** Gap rows 5.01, 5.02 closed.
- **Size.** M.
- **User decision.** Build the generator or remove the recurrence option.

### R-10 — Endpoint count snapshots and billing reconciliation (proposed Phase 92)

- **Goal.** Per-device and per-user billing that never bills an unverified count.
- **Scope.** Monthly per-customer count snapshot (source, observed-at, verification state: verified / stale /
  unverified); stale or unverified snapshots block meter updates; reconciliation report billed vs observed per
  agreement; differences become adjustment requests (R-11), never automatic invoice changes. Sources: synced
  RMM devices first, Rem0te via a signed count or P10 summary once available, M365 seats from licensing.
- **Dependencies.** R-09; R-08 for Rem0te counts.
- **Roadmap.** Proposed Phase 92 "Verified usage billing", or 70.6 under Phase 70 if the user prefers.
- **Rem0te coordination.** Yes (count endpoint with freshness, RQ-11).
- **Tests.** Snapshot immutability; stale-source refusal; reconciliation arithmetic; no invoice change
  without an approved adjustment.
- **Acceptance.** Gap rows 5.03, 5.04 closed for synced RMMs; Rem0te leg when the contract allows.
- **Size.** M.

### R-11 — Approval-controlled billing adjustments

- **Goal.** Every change to what a customer is billed has a requester, an approver and a history.
- **Scope.** Adjustment record for credit memos, line edits after approval and reconciliation differences;
  requester ≠ approver; staff-only; history on the invoice. Builds on the SR-04 fix.
- **Dependencies.** R-01.
- **Roadmap.** Extends Phase 36 and 71.10.
- **Rem0te coordination.** No.
- **Tests.** SoD refusals; history entries; customer-admin refusal.
- **Acceptance.** Gap rows 5.05, 5.06 closed.
- **Size.** M.

### R-12 — Business-hours SLA calendars (proposed Phase 93)

- **Goal.** SLA due dates and breach flags that respect working hours and holidays.
- **Scope.** Calendar model (hours, time zone, holidays) per MSP default, customer and contract; applied in
  `psa/sla.py` due-date computation, pause/resume and breach refresh; reuse `resourcing` holidays where
  possible; routing business hours read the same calendar.
- **Dependencies.** None.
- **Roadmap.** Proposed Phase 93 (Phase 87 covers on-call and escalation, not SLA clocks).
- **Rem0te coordination.** No.
- **Tests.** Arithmetic across weekends, holidays and DST changes; existing tickets keep their due dates
  on upgrade unless recomputed explicitly.
- **Acceptance.** Gap row 4.07 closed; breach reports match a hand-computed fixture.
- **Size.** M.

### R-13 — Security alert dedup, signature migration, adapter honesty

- **Goal.** Security alerts cannot flood the service desk and unsigned endpoints are visible.
- **Scope.** Auto-ticket dedup window and per-connection cap (SR-08); route security auto-tickets through the
  Phase 82.2 link; severity normalization and no silent downgrade (SR-09, SR-10); Security Overview warning
  and one-click migration for unsigned legacy connections.
- **Dependencies.** R-01.
- **Roadmap.** Extends 82.2, 84.1, 84.3.
- **Rem0te coordination.** No.
- **Tests.** Flood test; dedup; downgrade refusal; unsigned-connection warning.
- **Acceptance.** Gap rows 6.03, 6.05, 6.10 closed.
- **Size.** M.

### R-14 — Event-layer consumers and wallboard presets

- **Goal.** Phase 82's event layer is read by something a technician sees.
- **Scope.** As planned in 83.1–83.3 and 85.1, starting with widget sources that read `OperationalEvent`,
  NOC widgets (RMM offline, backup failures, SLA at risk by queue), "as of" on every widget, presets.
- **Dependencies.** R-13.
- **Roadmap.** Extends 83 and 85 (no new phase).
- **Rem0te coordination.** No.
- **Tests.** Per-source permission tests; visual checks per 83.7.
- **Acceptance.** Gap rows 6.01, 6.11–6.13 closed.
- **Size.** L.

### R-15 — AI service-desk orchestration (OPTIONAL AI)

- **Goal.** AI that shortens triage and diagnosis without crossing the execution boundary.
- **Scope.** AI category/priority suggestions into routing Suggest mode (never Auto without a rule); evidence
  request flow: AI proposes read-only diagnostics → technician confirms → Rem0te returns redacted evidence →
  analysis; prompt/response retention export per customer; kill-switch behaviour mid-job. Every AI-originated
  remediation idea becomes, at most, a draft proposal a technician must submit, which Rem0te must approve.
- **Dependencies.** R-07, R-08 (diagnostics); R-06 if P11 is accepted.
- **Roadmap.** Extends 56, 63.5 and 90.
- **Rem0te coordination.** Yes (redaction of evidence; P11 if accepted).
- **Tests.** AI suggestion cannot bypass routing authorization; disabling `psa_ai_enabled` mid-job stops
  dispatch; matrix row 25 cross-peer; no secrets in prompts (redaction test).
- **Acceptance.** Gap rows 3.03–3.07 closed; all paths inert with `psa_ai_enabled` off.
- **Size.** L.

### R-16 — Audit-log integrity, retention and routine backups (proposed Phase 94)

- **Goal.** Evidence the MSP can rely on, and data that survives the host.
- **Scope.** Hash-chained audit rows with a verification command and optional external append-only shipping;
  retention with export-before-prune; admin deletion behind a protected change (SR-07). Scheduled encrypted
  backup to an off-host destination with periodic restore verification; key escrow guidance (SR-17).
- **Dependencies.** None (can run in parallel with R-02–R-04).
- **Roadmap.** Proposed Phase 94 "Evidence integrity and routine backups", or sub-items of Phase 51/59.
- **Rem0te coordination.** No.
- **Tests.** Tamper detection; retention export; scheduler task present; restore verification.
- **Acceptance.** Gap rows 8.03, 8.09 closed.
- **Size.** M.
- **User decision.** External shipping target(s) to support first (syslog, S3-compatible object lock, file).

### R-17 — Import framework conformance and the first PSA importer (proposed Phase 95)

- **Goal.** Every importer offers the same guarantees; one PSA migration source works end to end.
- **Scope.** Conformance suite for `imports/migration/`: dry run, field mapping, duplicate detection,
  per-record error report, rollback, integrity report, refusal of destructive import without explicit
  confirmation and a verified backup (reuse the Phase 59.4 snapshot). Retire or guard the legacy importer
  (SR-16). First PSA source: ITFlow (self-hosted, open API; user to confirm), covering clients, contacts,
  tickets with comments and attachments, contracts, time entries, invoices, assets and credentials.
- **Dependencies.** R-16 (routine backup) for the destructive-import gate.
- **Roadmap.** Proposed Phase 95 "PSA migration importers", extending Phase 61.
- **Rem0te coordination.** No.
- **Tests.** Conformance suite run against IT Glue, Hudu and the new source; recorded-fixture contract tests;
  one real-instance run before the source is called shipped.
- **Acceptance.** Gap rows 7.03 (first source), 7.09, 7.10 closed.
- **Size.** L.
- **User decision.** Source order; whether real instances or trial tenants are available for each source.

### R-18 — Further PSA importers

- **Goal.** Remaining migration sources.
- **Scope.** HaloPSA, ConnectWise Manage, Autotask, Syncro, then CSV coverage of clients, tickets, contracts,
  invoices and time (gap 7.08), each passing the R-17 conformance suite.
- **Dependencies.** R-17.
- **Roadmap.** Proposed Phase 95.
- **Rem0te coordination.** No.
- **Tests.** As R-17 per source.
- **Acceptance.** Each source listed as shipped only after a real-instance or vendor-sandbox run.
- **Size.** L (in batches).

### R-19 — API key resource scopes and public-endpoint throttles

- **Goal.** Least privilege for integrations and bounded public endpoints.
- **Scope.** Per-resource key scopes (tickets, assets, documents, vault none by default) layered on
  organization reach and levels (SR-34); throttles for CSAT respond, unsubscribes and collector endpoints
  (SR-12); CORS restricted to DEBUG or API paths (SR-19).
- **Dependencies.** R-01.
- **Roadmap.** Follow-up to Phase 81; permission keys in Phase 64.
- **Rem0te coordination.** No.
- **Tests.** Scope enforcement per resource; throttle tests; settings test for CORS.
- **Acceptance.** Gap rows 8.04, 8.06, 8.11 closed; existing keys keep current behaviour until edited.
- **Size.** M.

### R-20 — PSA automation follow-ups

- **Goal.** Close smaller automation gaps once R-05 makes them observable.
- **Scope.** CSAT reminders, low-score follow-up and tests (gap 4.12); recurring-ticket tests and
  skip-if-open guard (4.11); offboarding close gate on access-removal checks (4.15); closure confirmation /
  auto-close (4.13); escalation matrix with Phase 87 (4.08).
- **Dependencies.** R-05.
- **Roadmap.** Extends Phase 12 (CSAT) and Phase 87.
- **Rem0te coordination.** No.
- **Tests.** As listed per gap row.
- **Acceptance.** Listed gap rows closed.
- **Size.** M.

### R-21 — UX and reporting

- **Goal.** Freshness and empty states that tell the truth; customer review packs.
- **Scope.** Shared empty-state component; integration last-sync age on dashboards; customer review reports
  per 89.2 once R-14 data exists.
- **Dependencies.** R-14.
- **Roadmap.** Extends 67, 83.1, 89.
- **Rem0te coordination.** No.
- **Tests.** Template snapshots; report permission tests.
- **Acceptance.** Gap rows 6.13, 9.02, 9.04 closed.
- **Size.** M.

## Requests for the Rem0te side

To be posted through `INTEGRATION_COORDINATION.md` (Rem0te's file is edited only by the Rem0te session). Not
written from this plan.

| ID | Request | Needed by |
|---|---|---|
| RQ-01 | Re-measure Clientst0r: update `scripts/clientst0r-interop/drive.py` / `interop-clientst0r.mjs` to drive `integrations.rem0te` (Ed25519) at Clientst0r ≥ 3.17.664; mark G1–G4 resolved in §2, §4C, §6 and §8 | R-04 |
| RQ-02 | Run Rem0te's `e2e-ticket-workflow` against real Clientst0r instead of the reference peer; confirm whether it runs in Rem0te CI | R-02 |
| RQ-03 | Document how fixtures configure a test approval signer and the agent simulator, so Clientst0r's E2E can drive approval and results | R-02 |
| RQ-04 | Ship revision 3 (P1–P10) with schemas, examples and e2e | R-08 |
| RQ-05 | A contract revision adding DRIVE_FREE, UPTIME_LONG, UPDATES_MISSING, UPDATE_FAILED, WARRANTY_EXPIRING, AGENT_SILENT, gated on the peer's declared revision; optional R12 metrics and 0.66 classification/explanation fields | R-03 follow-up |
| RQ-06 | R11: retry `GATEWAY_UNREACHABLE` until job expiry or a configurable window | Matrix row 18 |
| RQ-07 | R7: signed proposal-status events (approved, dispatched, succeeded, failed, with verification evidence) | R-07, R-08 |
| RQ-08 | R8: parameter schemas for integration-proposable actions in capabilities; consider exposing safe maintenance actions (reboot when pending, disk cleanup) with `integration: true` | R-03, R-08 |
| RQ-09 | Return `DIRECT_MODE_PORTAL_ONLY` in the `{error:{code,message}}` envelope and list it in `errors.ts` and the contract docs | R-03 |
| RQ-10 | Suppress or expose automatic PSA tickets (0.55) and P16 for businesses mapped to a Clientst0r peer (double-ticket safety) | Matrix row 9 |
| RQ-11 | A signed endpoint-count or P10 summary with `observed_at` suitable as a billing snapshot source | R-10 |
| RQ-12 | False-positive interop: delegated `POST /alerts/{id}/false-positive` (report only, never creates or approves a rule) and rule-applied info on `alert.updated` | Gap 1.09 |
| RQ-13 | R2/R3/R4: declared-revision mechanism (ties to P12), a documented technician-mapping probe, drop the pause reason from 423/403 bodies | R-06, SR-28, SR-31 |
| RQ-14 | Check whether revoked mapping rows block re-mapping (unique keys include revoked rows); regenerate `examples/index.json` (R10) | Matrix row 4 |
| RQ-15 | R9, R13–R16: ticket state back to Rem0te, AI-free diagnostics, maintenance-window listing, user-account reads, services/processes/software via summary or diagnostics | Later |

## Items needing the user's decision

1. **Phase numbering.** Approve proposed Phases 91 (workflow automation safety), 92 (verified usage billing,
   or fold into Phase 70), 93 (business-hours SLA calendars), 94 (evidence integrity and routine backups, or
   fold into 51/59) and 95 (PSA migration importers) before they are added to `docs/ROADMAP.md` as `[planned]`.
2. **`windows.update.install@1`.** Offer it from Clientst0r (with fixed parameters and Rem0te approval) or
   exclude it with a documented reason (R-03).
3. **Rem0te proposals P11–P16.** Accept, decline or defer each (R-06), and whether the P12 capabilities
   document belongs to `ticket-rmm-v1` or Agit8or Connect (Phase 79).
4. **Recurring charges.** Build the generator or remove the recurrence option from the charge form (R-09).
5. **Importer order and test instances.** Confirm ITFlow first and whether trial tenants exist for HaloPSA,
   ConnectWise, Autotask and Syncro (R-17, R-18). Without a real-instance run a source stays "requires
   real-vendor testing".
6. **Audit shipping target.** Which external append-only target to support first (R-16).
7. **Private-address opt-in for PBS.** Who may allow a backup connection to a private address (R-01, SR-02):
   superusers only, or a dedicated MSP-staff permission.
8. **Rem0te test signer in CI.** Whether Clientst0r's CI may run Rem0te's simulator with a test-only signer
   key committed to fixtures (R-02).
