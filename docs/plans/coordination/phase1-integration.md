# Phase 1 — ClientSt0r ↔ Rem0te integration

Branch `dev/rmm-p1-integration` (from `47c30b72`). Peer: Rem0te `4b2b9f5cbe093b99563b9332ba3bdf9dded88720`
(v0.30.1, contract `ticket-rmm-v1` revision 2). Nothing was released, tagged, pushed or deployed.

## Contract revision implemented

- **Revision 2**, pinned in `integrations/rem0te/contract/PIN.json` (`contract_revision: 2`, `rem0te_version:
  0.30.1`, `rem0te_sha: 4b2b9f5c…`; the previous pin, revision 1 at `1bff01a4`, is kept under `previous`).
- `contract/` is Rem0te's `docs/contracts/ticket-rmm-v1` at that SHA, copied verbatim (schemas, fixtures,
  `examples/` with the TEST-ONLY keys, `CLIENTST0R.md`, `clientst0r-interop.json`).
- **Revision 1 stays supported.** Its four schemas that revision 2 changed (capabilities, alert, alert-event,
  signed-alert-event) and the fixtures 0.30.0 removed are kept under `contract/rev1/`.
- **Negotiation.** `/capabilities` is validated against revision 2, then 1 (`schema.errors_from_peer`). A
  `contract_revision` that is not a positive integer, or `organizations` without a revision, is
  `CONTRACT_MISMATCH`. The revision Rem0te declared and the revision it validated against are stored on the
  check.
- **Unknown fields (pending R2).** ClientSt0r accepts unknown fields only when Rem0te declares a revision newer
  than 2, as the contract says ("revisions only add fields"). It logs them, stores their paths on the check
  (`unknown_fields`) and shows a warning. Rem0te documents at revision 1 or 2 must match their schema exactly.
  Alert events follow the same rule.

## Gaps closed

| Gap | What changed |
|---|---|
| G1 | The revision-2 capabilities schema is pinned; revision 1 is kept. Rem0te 0.30.1's capabilities now pair (s1 in the E2E below). |
| G2 | The revision-2 alert schema includes `patch_summary`. An authentic event ClientSt0r cannot apply is recorded as skipped (`Rem0teAlertEvent.applied=False`, with the reason) and acknowledged with 200, so the cursor and Rem0te's push retries move on. It shows on the connection's health, sets a re-check flag, and reconciliation applies it again after the next good check. Events in the feed that name another peer or organization are recorded as foreign and never applied. |
| G3 | `contract_revision` is read and validated. A revision above 2 is accepted with a logged warning (policy above). |
| G4/G5 | Only this organization's own `organizations[]` entry is used. Pause state is shown as **Degraded (containment)**. A job refused with 423 `CONTAINED` fails once, with a fixed message, and is not retried. A proposal refused with `CONTAINED` becomes `unavailable` (`remote_status CONTAINED`), not "rejected". The refusal clears once a check shows the pause lifted. |
| G6 | `patch_summary` is validated against the pinned `patch-summary` schema, stored on `Rem0teAlertTicket.patch_summary`, written into the ticket description and refreshed by update events. |
| G7 | `organizations[].business_id` is compared with the connection's business pin (`rem0te_business_id`, or the inventory key's `ticket_rmm_tenant_id`). A mismatch is `BUSINESS_MISMATCH`: pairing stops and the status is Configuration Required. With no pin yet, the first good check pins it (trust on first use). |
| G8 | The tests use Rem0te's `examples/` byte vectors. Request signatures are reproduced byte for byte with the TEST-ONLY keys. Delegations are checked with `req_sha256` over canonical JSON, event signatures with domain separation, and the inference response signature over the request nonce. Every example validates against the pinned schemas. Tests that used the removed fixtures now read `contract/rev1/`. |
| G9 | Key rotation now overlaps. *Stage* creates the next request and delegation keys and lists them in the peers-file entry alongside the current ones; the current keys keep signing. *Switch* promotes them, and *Discard* drops them. Every step is audited. The one-step hard rotation still exists and clears any staged keys. |
| G10 | The E2E pins the new SHA. s1 checks revision 2 and the binding; s8 checks the health states and backoff; the new s11 covers the technician probe, the containment pause, patch summary and reconciliation. |
| G11 | No other customer's business id, name or organization id is stored; only `organizations_count` is kept. |

Also part of Phase 1:

- **One status everywhere.** Every connection shows one of Connected, Degraded, Disconnected, Authentication
  Problem or Configuration Required (`integrations/rem0te/health.py`). The state comes from the stored check
  plus per-area issues on the connection's `IntegrationSyncHealth` row, `kind='rem0te'`. That row is now
  unique per (object, kind), so the inventory-sync `rmm` row stays separate.
- **Issue areas.** inbound_auth, events, alerts_poll, alerts_gap, ticket_link, jobs, actions and technician.
  Each issue carries a message and what to do, and is cleared by the next success in its area.
- **Where the status appears.** The integration list badge, the RMM detail page, and the wizard.
- **Reconciliation** (`integrations/rem0te/reconcile.py`). The `poll_analysis_jobs` scheduler task runs it
  every minute; `manage.py rem0te_reconcile [--check]` runs it by hand. Capabilities are re-checked hourly.
  After failures the re-check waits 1, 2, 4 … minutes, capped at one hour; with the re-check flag set it runs
  at once. Each run also re-applies skipped events, polls missed alert events and gaps, retries ticket links
  and refreshes open proposals.
- **Expired approvals.** A proposal still `awaiting_approval` 10 minutes past its window, while Rem0te cannot
  be read, is shown as expired.
- **Setup wizard** (Settings → RMM · Rem0te, superusers only). It covers the identity and keys (including
  staged rotation), the peers-file entry, and per connection the status, a checklist and **Test connection**.
  Test connection runs the signed check plus a technician probe and writes an audit entry. The checklist
  covers keys, identity, approval, tested, network, auth, clock, contract, capabilities, organization,
  business, containment, technicians and profiles. Against a revision-1 Rem0te the business row reads "Not
  supported by the connected Rem0te".

## Rem0te requests

R1–R10 from the coordination audit still stand. Two notes from this phase:

- **R2 (unknown fields).** The interim policy above is implemented and covered by tests. ClientSt0r would drop
  the tolerance branch once Rem0te publishes per-revision schemas or lets a peer declare its revision.
- **R3 (technician probe).** The wizard learns whether a technician is mapped from a delegated
  `GET /jobs/00000000-0000-4000-8000-000000000000`. Rem0te checks the actor before the job, so the answer is
  404 when the technician is mapped and 403 with a reason when not. This relies on observed behaviour, not on a
  documented contract. It spends one delegation `jti` and reads nothing. A documented probe is still requested.
- **R4 (pause reason).** ClientSt0r does not store or show the free-text `Reason:` from 423 / 403 `CONTAINED`
  bodies anywhere; it uses a fixed message instead.

- **R11 (new): inference retry budget.** Rem0te 0.30.1's worker retries a `GATEWAY_UNREACHABLE` model run 3
  times (`MAX_RUN_ATTEMPTS = 3`), about 13 seconds in all. It then ends the job `ALL_PROFILES_FAILED`. If a
  ClientSt0r restart takes longer than that, every job queued during the restart fails for good. Request:
  keep retrying a transient gateway failure until the job expires, or for a configurable window (as alert
  delivery already does).

## E2E results

`scripts/e2e/cross_peer/` was run against the real Rem0te: a copy of `4b2b9f5cbe093b99563b9332ba3bdf9dded88720`
(v0.30.1) built locally, on its own scratch Postgres and Redis. ClientSt0r ran from this branch on a
throwaway SQLite database.

- **Baseline** (branch base `47c30b72`, unchanged code): s1 failed with "Check pairing org-1: paired — its
  capabilities do not match the pinned schema (contract_revision: unknown field; organizations: unknown
  field)". That is G1 confirmed; the run was stopped there.
- **This branch, full run: 99 passed, 3 failed** (Rem0te `4b2b9f5c…`; pinned `4b2b9f5c…`).
  - s1: revision 2; each organization bound to its own business by id; the binding matches; nothing about
    the other customer is stored; status Connected.
  - s4, s6: alert tickets, same computer name across customers.
  - s7: revoked mapping.
  - s8: Disconnected with what to do; backoff; recovery through reconciliation.
  - s9, s10: L1 limits, failure reasons.
  - s11, all passed:
    - Test connection and the technician probe, mapped and unmapped.
    - Containment pause: reported for one business only and shown as Degraded. A job fails at once with
      `CONTAINED`, is not resent, and the pause reason is stored nowhere. After the pause is lifted the
      status is Connected.
    - A real REBOOT_PENDING alert: its `patch_summary` was stored, is valid against the pinned schema and
      shows on the ticket, with the asset matched by Rem0te id.
    - Reconciliation ran for both connections.
  - **s5 failed (3 checks):** "the analysis job submitted during the outage completed", "one terminal result"
    and "one model call". Rem0te ended the job `ALL_PROFILES_FAILED` after its 3 `GATEWAY_UNREACHABLE`
    attempts (14:09:28, :32 and :41). ClientSt0r's `runserver` on this loaded shared machine answered again
    only at 14:09:56. Rem0te's worker retry code is the same at `1bff01a4` and `4b2b9f5c`; this is the
    restart-timing dependency described in R11, not a contract difference. The other s5 checks passed:
    exactly one alert ticket after push retries and polling, and every event acknowledged.
- **Partial run (s1, s2, s11): 53 passed, 0 failed.** This was the run in which s11's posture heartbeat was
  corrected to the signed channel; Rem0te ignores `patchPosture` on any other channel.

Interoperability is therefore shown for everything above except the s5 job-across-a-ClientSt0r-restart case.
Action proposals under a pause are covered by unit tests only: the harness's technicians cannot propose
actions in Rem0te.
