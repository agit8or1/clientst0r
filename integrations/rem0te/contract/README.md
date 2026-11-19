# Contract ticket-rmm-v1

The canonical interface between **ClientSt0r** and **rem0te**. rem0te owns it.

| Owner | Owns |
|---|---|
| ClientSt0r | Tickets, customer communication, AI configuration, model choice, **every provider key**, the inference gateway |
| rem0te | Mapping organizations/technicians to businesses/users, endpoint evidence, job orchestration, signed results — and, in later milestones, independently approved catalog actions |

| File | What |
|---|---|
| `openapi.yaml` | Routes on both sides |
| `schemas/*.schema.json` | **Generated** from `apps/api/src/integration/contract.ts`. Do not edit — run `node scripts/gen-integration-contracts.mjs` |
| `proposed/*.schema.json` | **Proposals, not contract** (0.34): `peer-capabilities`, `timeline-inference-request`, `timeline-inference-response`, `timeline-summary-output` — items P11/P12 of revision 4 in [`INTEGRATION_COORDINATION.md`](../../../INTEGRATION_COORDINATION.md) §5A. Generated from `PROPOSED_SCHEMAS` in `contract.ts`, checked for drift like the rest, and **not** part of any `contract_revision` until ClientSt0r acknowledges them |
| `fixtures/*.json` | Example messages, produced by rem0te's own code paths. `<schema>.invalid-*.json` must be rejected. CI validates all of them |
| `fixtures/fixture-signing-key.pub.pem` | Verifies `signed-event.job-succeeded.json`. Test-only key; its private half was discarded |
| `examples/*.json` | **Real exchanges** (0.30), recorded by `apps/api/scripts/e2e-ticket-workflow.mjs --write-examples`: method, path, every signing header, body, and the response. Signed with the TEST-ONLY keys in `examples/keys/` (fixed seeds; the private halves are published on purpose so a peer can reproduce the signatures). `gen-integration-contracts.mjs --check` verifies every signature, delegation binding and schema in CI |
| `CLIENTST0R.md` | What ClientSt0r should consume, and the measured gaps between it and this contract |
| `clientst0r-interop.json` | The last run of ClientSt0r's own code against rem0te (`apps/api/scripts/interop-clientst0r.mjs`) |

## Revisions

`/capabilities` returns `contract_revision`. Revisions only add fields; a peer uses nothing newer than it
implements.

| Revision | rem0te | Adds |
|---|---|---|
| 1 | 0.25–0.29 | Jobs, events, action proposals (0.26), alerts and ticket links (0.29) |
| 2 | 0.30 | `contract_revision`; `organizations` in `/capabilities` (each organization's `business_id`, `business_name` and `paused` kinds — the binding made explicit); `alert.patch_summary` on REBOOT_PENDING alerts (schema `patch-summary`) |
| *3 (agreed, not built)* | *—* | *P1–P10 of [`INTEGRATION_COORDINATION.md`](../../../INTEGRATION_COORDINATION.md) §5: capabilities list and diagnostic catalog, diagnostic requests and events, fix referrals and events, remote launch, handoff notes, `Idempotency-Key`, device health summary. Acknowledged by ClientSt0r on 2026-11-11 as proposed (§9). No schema here yet: `contract_revision` stays 2 until rem0te ships them* |
| *4 (proposed)* | *0.34, rem0te side only* | *P11: inference task `device_timeline_v1` (the device page's AI summary). P12: ClientSt0r's own capabilities document at the peers file's `capabilitiesUrl`. Not agreed; see `proposed/`* |

## Milestone status

| Capability | State |
|---|---|
| Ticket-only analysis, optional device evidence, model comparison | **Fixture-tested** (`apps/api/scripts/e2e-integration.mjs`, simulated ClientSt0r) |
| Full workflow (pair, analyse, alert → ticket → resolve, restart without duplicates, identical PC names, revoked technician, offline endpoint, paused business, suggestions authorize nothing) | **Proved against a contract-conformant reference peer**, with the real API, worker and approval signer (`apps/api/scripts/e2e-ticket-workflow.mjs`) |
| Paired with a real ClientSt0r | **Measured: does not interoperate.** ClientSt0r 3.17.659 signs with HMAC and expects a different capabilities and job shape — four gaps, in `CLIENTST0R.md` (`apps/api/scripts/interop-clientst0r.mjs`) |
| Alert events and ticket links (`features.alerts`, `/alerts/*`, rem0te ≥ 0.29) | **Fixture-tested** (`apps/api/scripts/e2e-monitoring.mjs`, simulated ClientSt0r events endpoint). Not yet run against a real ClientSt0r |
| Action proposals (`features.actions`, `/action-proposals`, rem0te ≥ 0.26) | **Fixture-tested** (`apps/api/scripts/e2e-approved-action.mjs`, simulated ClientSt0r and agent). ClientSt0r proposes; it cannot approve or execute. Lists `windows.service.start@1` (Print Spooler) only while an approval signer is configured, otherwise empty |

## Trust

- **Peers live in a root-owned file** (`INTEGRATION_PEERS_FILE`), not the database: keys, audiences, the two
  ClientSt0r URLs, allowed model profiles, optional mTLS pins, and rem0te's own Ed25519 key. A database or
  portal-admin compromise cannot add a peer, swap a key or redirect the worker.
- **Two ClientSt0r keys.** A *request* key signs service-to-service calls; a separate *delegation* key mints
  technician tokens. A stolen service credential alone cannot act as a technician.
- **Explicit mapping.** `(peer, organization_id) → business` and `(peer, organization_id, technician_id) → user`
  are rows a Platform Admin creates (step-up required). Nothing is matched by name, e-mail or hostname.
- **Live access, every time.** Intake, every poll and the worker before every model call rebuild the user's
  access from the database. The business must be the user's own or a current technician assignment, and
  `integration:ticket_analysis` must be held there. The integration never acts as Platform Admin.
- **Inventory API keys (`rk_…`) are not signatures** and get 401 on every route here.

## Request signatures

Both directions. Headers:

```
rem0te-key-id:    {peer-id}/{kid}        (rem0te → ClientSt0r: rem0te/{kid})
rem0te-timestamp: unix seconds            (±120 s)
rem0te-nonce:     16–128 base64url chars  (single use, persisted, survives restart)
rem0te-signature: base64url Ed25519 over
  rem0te-http-req-v1\n{audience}\n{METHOD}\n{path?query}\n{timestamp}\n{nonce}\n{sha256-hex(raw body)}
```

`audience` names the receiver (`peers[].audience` for rem0te, `peers[].peerAudience` for ClientSt0r), so a
request signed for one instance is refused by every other.

Inference responses are signed over `rem0te-http-resp-v1\n{the request's nonce}\n{sha256-hex(body)}` and must
echo `request_id`, `job_id`, `organization_id` and `model_profile`, so a result for another tenant or a replayed
result is rejected.

Events are signed over `rem0te-event-v1\n{canonical JSON of the event}` (object keys sorted, no whitespace),
independent of transport, so a polled event and a pushed event verify the same way.

## Delegation token

Compact JWS, `alg: EdDSA`, `typ: rem0te-delegation+jwt`, `kid` = a delegation key id.

| Claim | Rule |
|---|---|
| `iss` | peer id |
| `aud` | `peers[].audience` |
| `sub` / `org` | ClientSt0r technician / organization; must equal the body's `technician_id` / `organization_id` |
| `scope` | `ticket_analysis:submit` or `ticket_analysis:read` |
| `iat`, `exp` | `exp − iat ≤ 300` |
| `jti` | single use, persisted |
| `req_sha256` | submit only: sha256 of the canonical job request **after defaults** — binds the token to that payload |

## Idempotency

`(peer, idempotency_key)` is unique. Same key + same canonical payload → **200** with the original job and
`idempotent-replayed: true`, still only to a technician with access now. Same key + different payload →
**409 `IDEMPOTENCY_CONFLICT`**. A new ticket revision is a new key.

## Results

Staff-only. Each result separates:

- `facts`: model claims citing evidence rem0te can resolve (`model_cited`), and `rem0te_observed` facts
  rem0te derived itself (heartbeat freshness, inventory age, patch posture).
- `hypotheses`, with the most cautious confidence any model gave.
- `unsupported_claims`: "facts" whose evidence references do not resolve.
- `disagreements`: different categories, or top hypotheses that do not overlap.
- `draft_replies`: `staff_only`, `requires_human_review`, with `link_hosts` surfaced.
- `next_steps`: text, `executable: false`, `requires_human_approval: true`; `blocked_category` marks
  credential extraction, disabling defenses, removing backups, admin grants, disk wipes and arbitrary commands.
- `untrusted_input_flags`: prompt-injection patterns found in the ticket.
- `partial_failures`: per profile.

## Action proposals (0.26)

A proposal is a request, made as the delegated technician (scope `actions:propose`), for one catalog action on
one mapped computer named by its immutable rem0te id. rem0te runs it through the same path as the portal's
Request button — the catalog, that technician's live access to that computer, the approval signer — and returns
an `approval_url`.

- **Proposing authorizes nothing.** The plan is approved on rem0te's approval signer, a separate process on its
  own origin, by people on its roster, each with a user-verified passkey; never by the proposer, and in the number
  the catalog sets (one for a standard workstation, two for anything else) plus customer sign-off where that
  business's policy requires it. The agent on the computer verifies the signer's signature with a key it gets
  from the offline-rooted update chain, so neither ClientSt0r nor rem0te's portal can substitute one.
- **`origin: ai_suggestion`** is shown to the approvers as an AI suggestion and gets no shortcut.
- **The vocabulary is the catalog.** There is no command, script, path or URL field. Anything not in the catalog
  is `ACTION_NOT_IN_CATALOG`, and credential extraction, removing backups, disabling defenses, admin grants, disk
  wipes and arbitrary commands are never in it.
- **Results say what was observed.** `observed` carries the agent's service-state readings; a started Print
  Spooler is not evidence that any document printed.
- Poll `GET /action-proposals/{job_id}` (scope `actions:read`).

## Alert events (0.29)

rem0te tells ClientSt0r about monitoring alerts so it can open a ticket, and ClientSt0r says which ticket it
opened. `features.alerts` is `true` from 0.29.

- **Which alerts.** Only in a business whose notification policy has *Offer alerts to ClientSt0r* on, and at or
  above that policy's severity floor. The first event for an alert is always `alert.raised`; `alert.updated`
  (acknowledged, escalated, ticket linked) and `alert.resolved` follow only for alerts the peer was sent a
  raise for. Every route below is limited to those alerts, in organizations mapped to the calling peer.
- **Signed, sequenced, pushed.** Each event is signed with rem0te's key over
  `rem0te-alert-event-v1\n{canonical alert_event}` — a different prefix from job events, so neither signature
  can stand in for the other — sequenced per (peer, organization) from 1 with no gaps, and POSTed as
  `{alert_event, signature}` to the same `eventsUrl` as job events, with the same retry. Schema:
  `signed-alert-event`; example: `examples/alert-event.raised-with-patch-summary.json`, verifiable with
  `examples/keys/rem0te-self.pub.pem`.
- **Patch summary (revision 2).** A REBOOT_PENDING alert for a computer carries `patch_summary`: evidence source
  (`signed_agent_scan` / `standard_agent_scan` / `none`), its time, age and freshness, last boot, who manages
  patching (`managed_by` plus manager labels), whether a restart is pending, the pending KB numbers, and which KBs
  were confirmed by a later scan, failed, or await confirmation. No update titles, error text, computer
  identifiers, user names, addresses or registry values. Every other alert carries `null`.
- **Recovering a gap.** `GET /api/integration/v1/alerts/events?organization_id=…&after={last sequence}`
  returns up to 100 signed events, oldest first. `GET /api/integration/v1/alerts/{alert_id}?organization_id=…`
  is the alert now.
- **Linking a ticket.** `POST /api/integration/v1/alerts/{alert_id}/ticket` with
  `{contract, organization_id, ticket_id, ticket_url}` (schema `alert-ticket-link`; `ticket_url` https only).
  The same ticket again is `200` with `idempotent-replayed: true`; a different one is `409
  TICKET_ALREADY_LINKED`. Linking grants nothing and does not acknowledge or resolve the alert.
- **No delegation token.** These are service-level: nothing here acts for a technician or reaches a computer.
- Computer and site names in `title`, `computer_name` and `site_name` are device- or customer-supplied text.
  Display them as text.

## Error codes

`NOT_CONFIGURED` 404 · `UNAUTHENTICATED` 401 · `REPLAYED` 401 · `DELEGATION_INVALID` 401 · `FORBIDDEN` 403 ·
`NOT_FOUND` 404 · `INVALID_REQUEST` 400 · `IDEMPOTENCY_CONFLICT` 409 · `TOO_LARGE` 413 · `CONTAINED` 423 ·
`RATE_LIMITED` 429 · `INTERNAL` 500.

`CONTAINED` (rem0te 0.28+) means the operator has paused this kind of work for the organization's business, or for
every business, during an incident. It is not a client error: retry later. A job already queued when the pause is set
ends `failed` with `CONTAINED`.

Action proposals add rem0te's own refusal codes (400/403/409): `ACTION_NOT_IN_CATALOG`, `PARAMS_NOT_ALLOWED`,
`ACTION_NOT_GRANTED`, `PROTECTED_DEVICE_CLASS`, `ENDPOINT_NOT_READY`, `ACTION_PENDING`, `ACTION_UNRECONCILED`,
`APPROVAL_SIGNER_ERROR`, `APPROVAL_SIGNER_REFUSED`.

Alert routes add `TICKET_ALREADY_LINKED` 409.

Job / run error codes: `ACTOR_REVOKED`, `PEER_REMOVED`, `EXPIRED`, `ENDPOINT_NOT_AVAILABLE`,
`ALL_PROFILES_FAILED`, `GATEWAY_UNREACHABLE`, `GATEWAY_UNAVAILABLE`, `GATEWAY_REFUSED`,
`RESPONSE_SIGNATURE_INVALID`, `RESPONSE_INVALID`, `RESPONSE_MISMATCH`, `MODEL_REFUSED`, `OUTPUT_SCHEMA_INVALID`.

## Recovering a lost callback

Events are retried with backoff for up to 7 days. ClientSt0r can always recover: `GET /jobs/{id}` for status
and result, `GET /jobs/{id}/events?after={last sequence seen}` for anything missed.
