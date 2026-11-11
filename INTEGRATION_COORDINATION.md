# ClientSt0r ↔ Rem0te integration coordination

A living document, maintained jointly by the ClientSt0r session and the Rem0te session. Each side edits
its own sections and leaves the other side's claims alone, except to mark them confirmed or disputed with
a file:line reference. Nothing here is a release note: nothing in it is shipped until a release says so.

| | |
|---|---|
| Last audited | 2026-11-11 (ClientSt0r session) |
| ClientSt0r tree audited | branch `dev/rmm-coordination`, based on `47c30b72` (tip of `dev/program-2026-11`, unreleased; `config/version.py` still says 3.17.660) |
| Rem0te tree audited | `4b2b9f5cbe093b99563b9332ba3bdf9dded88720` (v0.30.1 "Plumbline"), read-only checkout |
| Previous tested peer | `1bff01a4a3b52fd745e001352e0c417909199aeb` (v0.29.0) |

Paths prefixed `cs:` are in this repository; `r0:` are in the Rem0te repository.

---

## 1. Contract, revision and versions

| | ClientSt0r (implements) | Rem0te (publishes) |
|---|---|---|
| Contract name | `ticket-rmm-v1` (`cs:integrations/rem0te/protocol.py:38`) | `ticket-rmm-v1` (`r0:apps/api/src/integration/contract.ts:13`) |
| Revision | **1** (implicitly: vendored schemas from 0.29.0, no `contract_revision` handling anywhere in `cs:integrations/rem0te/`) | **2** (`r0:apps/api/src/integration/contract.ts:21`, `CONTRACT_REVISION = 2`) |
| Pinned peer | rem0te 0.29.0 @ `1bff01a4` (`cs:integrations/rem0te/contract/PIN.json`) | — |
| Oldest accepted peer | 0.26.0; alerts from 0.29.0 (`cs:integrations/rem0te/pairing.py:42-43`) | — |
| Newer peer handling | warning only when major.minor differs (`cs:integrations/rem0te/pairing.py:317-320`) | "Revisions only add fields; a peer uses nothing newer than it implements" (`r0:docs/contracts/ticket-rmm-v1/README.md`, *Revisions*) |

Revision 2 (rem0te 0.30.0) adds, per `r0:docs/contracts/ticket-rmm-v1/README.md` and confirmed in code:

- `contract_revision` (required integer) in `/capabilities` (`r0:…/contract.ts:283`, emitted at `r0:…/integration.controller.ts:64, 68`);
- `organizations[]` (required) in `/capabilities`: `{organization_id, business_id, business_name, paused[]}`, `paused ⊆ {actions, remote, updates, integration}` (`r0:…/contract.ts:273-287`; built from `integrationOrgMapping` + `activePause` at `r0:…/integration.controller.ts:51-61`);
- `alert.patch_summary` (required key, `PatchSummary | null`) on every alert, non-null only for `REBOOT_PENDING` computer alerts (`r0:…/contract.ts:383-422`; `r0:apps/api/src/monitoring/alert-events.service.ts:22-39, 99-102`). Present in pushed and polled alert events, `GET /alerts/{id}` and the ticket-link response.

0.30.1 is security hardening (Connect step-up, insert-only audit, update signing). It does **not** change the
integration controller, guard, signer or any contract schema: `git diff 1bff01a..4b2b9f5 --stat` touches no file
under `r0:apps/api/src/integration/` other than `contract.ts` and `integration.controller.ts` (both 0.30.0).

### Note on Rem0te's own interop measurement

`r0:docs/contracts/ticket-rmm-v1/CLIENTST0R.md` and `clientst0r-interop.json` record that "ClientSt0r 3.17.659
does not interoperate" (HMAC signing, flat capabilities, legacy job shape). That measurement is accurate for
**released** ClientSt0r (`a5f83826`, `main`), whose only ticket-RMM code is the HMAC module
`cs:integrations/ticket_rmm.py`. It does not describe the integration branch: `r0:scripts/clientst0r-interop/drive.py:23-24`
imports `integrations.ticket_rmm` and `psa_ai.services.processor`, never `integrations.rem0te`, so it cannot
exercise ClientSt0r's Ed25519 implementation. See the requests in §7.

Of the four gaps that document lists, the integration branch already addresses three in code (Ed25519 request
signing, Ed25519 event verification, the `job-request` shape) and half of the fourth (it reads `features`, not a
flat list; it does not read `organizations`). All of it was built against revision 1.

---

## 2. Endpoints

All Rem0te routes are under `/api/integration/v1/`, `@Public()` behind `IntegrationAuthGuard`
(`r0:apps/api/src/integration/integration.controller.ts`, `r0:…/integration-auth.guard.ts`). All ClientSt0r routes
are under `/api/integration/v1/` (`cs:config/urls.py:96` → `cs:psa_ai/integration_api.py:237-238`).

Errors on both sides are `{"error": {"code", "message"}}` (`r0:…/errors.ts:5-43`; `cs:psa_ai/integration_api.py:61`).

### 2.1 ClientSt0r → Rem0te (ClientSt0r client: `cs:integrations/rem0te/client.py:76`)

| Method, path | Auth | Request → response (schema) | Idempotency | ClientSt0r caller |
|---|---|---|---|---|
| `GET /capabilities` | signed request, no delegation | — → `capabilities` | read | `cs:integrations/rem0te/pairing.py:395` (Check pairing) |
| `POST /jobs` | signed + delegation `ticket_analysis:submit`, `req_sha256` = sha256(canonical body) | `job-request` → 202 `job`; replay 200 + `idempotent-replayed: true` | `idempotency_key` in the body; same key, other body → 409 `IDEMPOTENCY_CONFLICT` | `cs:integrations/rem0te/jobs.py:168-169` (body built once, stored, re-sent byte-identical: `jobs.py:157-166`) |
| `GET /jobs/{job_id}` | signed + delegation `ticket_analysis:read` | → `job` | read | not called (ClientSt0r polls events instead) |
| `GET /jobs/{job_id}/events?after=n` | signed + delegation `ticket_analysis:read` | → `{events: [signed-event]}` | read | `cs:integrations/rem0te/jobs.py:236-238` |
| `POST /action-proposals` | signed + delegation `actions:propose` (+ `req_sha256`) | `action-proposal-request` → `action-proposal` | `idempotency_key` in body (`r0:…/action-proposals.service.ts:59`) | `cs:integrations/rem0te/actions.py:130` |
| `GET /action-proposals/{job_id}` | signed + delegation `actions:read` | → `action-proposal` | read | `cs:integrations/rem0te/actions.py:158` |
| `GET /alerts/events?organization_id=&after=n` | signed, service-level (no delegation) | → `{events: [signed-alert-event]}` | read; 403 for an unmapped organization | `cs:integrations/rem0te/alerts.py:226` (poll), `pairing.py:418` (mapping probe) |
| `GET /alerts/{alert_id}?organization_id=` | signed, service-level | → `alert` | read | not called |
| `POST /alerts/{alert_id}/ticket` | signed, service-level | `alert-ticket-link` → 201 `alert`; same ticket again 200 + `idempotent-replayed`; other ticket 409 `TICKET_ALREADY_LINKED` | natural (alert id + ticket id) | `cs:integrations/rem0te/alerts.py:175-201` |

Rem0te error codes ClientSt0r can receive: `NOT_CONFIGURED` 404, `UNAUTHENTICATED` 401, `REPLAYED` 401,
`DELEGATION_INVALID` 401, `FORBIDDEN` 403, `NOT_FOUND` 404, `INVALID_REQUEST` 400, `IDEMPOTENCY_CONFLICT` 409,
`TOO_LARGE` 413, `RATE_LIMITED` 429, `INTERNAL` 500 (`r0:…/errors.ts:16-43`); plus `CONTAINED` 423 on jobs
(`r0:…/jobs.service.ts:79-81`), `IDENTITY_PAUSED` / `THRESHOLD_TRIPPED` 403 (`r0:…/jobs.service.ts:103-104`),
`ACTION_NOT_IN_CATALOG` 400 (`r0:…/action-proposals.service.ts:68`), `TICKET_ALREADY_LINKED` 409
(`r0:…/alert-events.service.ts`, `linkTicket`). ClientSt0r maps them in `cs:integrations/rem0te/pairing.py:232-286`
(Check pairing) and `cs:integrations/rem0te/jobs.py:188-215` (jobs; `CONTAINED` and 5xx/429 are retried).

Inventory is **not** in this contract. ClientSt0r reads Rem0te computers through Rem0te's Public API
(`GET /api/v1/pub/v1/whoami`, `/computers`, Bearer API key, scope `computers:read`;
`cs:integrations/providers/rmm/rem0te.py:25, 72-143`; `r0:apps/api/src/public-api/public-api.controller.ts:91,146,159`).
`RMMDevice.external_id` is Rem0te's endpoint id, which is the `rem0te_endpoint_id` the contract uses.

### 2.2 Rem0te → ClientSt0r

| Method, path | Auth | Request → response | Idempotency | ClientSt0r handler |
|---|---|---|---|---|
| `POST /inference` | Rem0te-signed request (`rem0te-key-id: rem0te/{kid}`, ClientSt0r's audience); response signed `rem0te-http-resp-v1` over the request nonce | `inference-request` → `inference-response` | at most one model call per (job, profile); a retried run is answered from the stored run (`cs:integrations/rem0te/jobs.py` `handle_inference`, ~line 455) | `cs:psa_ai/integration_api.py:65-91` |
| `POST /events` | Rem0te-signed request, then the event's own signature | `signed-event` or `signed-alert-event` → 200 `{status}` | dedup by `event_id` (`ProcessorEvent`, `Rem0teAlertEvent` unique rows); ordering by `sequence` | `cs:psa_ai/integration_api.py:93-122` → `cs:integrations/rem0te/jobs.py:255` / `alerts.py:55` |

ClientSt0r answers: 400 `INVALID_REQUEST` (schema), 401 `UNAUTHENTICATED` / `REPLAYED`, 404 `NOT_FOUND` /
`NOT_CONFIGURED`, 413 `TOO_LARGE`, 503 `UNAVAILABLE` (PSA not ready; nothing recorded so the retry applies it,
`cs:integrations/rem0te/alerts.py:46-48, 82-84`), 500 `INTERNAL`. Rem0te treats any non-2xx as "retry with backoff,
then give up and leave it to polling" (`r0:apps/api/src/integration/worker.service.ts:232-263, 272-293`).

---

## 3. Event payloads

| Payload | Schema (`r0:docs/contracts/ticket-rmm-v1/schemas/`) | Signed as | Changed in rev 2 | ClientSt0r consumer |
|---|---|---|---|---|
| Job event `job.accepted / running / succeeded / partial / failed / expired` | `event`, `signed-event` | `rem0te-event-v1\n` + canonical JSON of `event` | no | `cs:integrations/rem0te/jobs.py:255-331` (terminal map `jobs.py:48-49`) |
| Job snapshot / analysis result | `job`, `analysis-result` | inside the event | no | `jobs.py:312` stores `result`; staff view `jobs.py` `staff_view` |
| Alert event `alert.raised / updated / resolved` | `alert-event`, `signed-alert-event`, `alert` | `rem0te-alert-event-v1\n` + canonical JSON of `alert_event` | **yes: `alert.patch_summary` required (nullable)** | `cs:integrations/rem0te/alerts.py:55-116` |
| Patch summary | `patch-summary` (**new**) | inside the alert | **new** | none |
| Action proposal status (`awaiting_approval … succeeded / failed / refused_by_endpoint / not_executed / unknown`) | `action-proposal` | not signed as an event; read with a signed, delegated GET | no | `cs:integrations/rem0te/actions.py:33-60, 95-121` (status map) |
| Capabilities | `capabilities` | response to a signed request (not separately signed) | **yes: `contract_revision`, `organizations` required** | `cs:integrations/rem0te/pairing.py:296-345` |
| Inference request / response | `inference-request`, `inference-response`, `analysis-output` | request signed by Rem0te; response signed by ClientSt0r | no | `cs:integrations/rem0te/jobs.py` (`handle_inference`), `cs:integrations/rem0te/inbound.py:100-106` |

There is no job "approval" or "execution" callback for analysis jobs: analysis never executes anything
(`next_steps[].executable` is the literal `false`, `r0:…/contract.ts:193`). Action proposals have no push channel;
ClientSt0r polls them (`cs:psa_ai/management/commands/poll_analysis_jobs.py:73` → `actions.poll_open`).

---

## 4. Authentication and authorization

### 4.1 Signatures (identical on both sides; confirmed)

| String | Rem0te | ClientSt0r |
|---|---|---|
| `rem0te-http-req-v1\n{audience}\n{METHOD}\n{path?query}\n{ts}\n{nonce}\n{sha256(body)}` | `r0:…/crypto.ts:86-89`; verified over `req.originalUrl` (`r0:…/integration-auth.guard.ts:62`) | `cs:integrations/rem0te/protocol.py:245-247`; inbound verified over `request.get_full_path()` (`cs:integrations/rem0te/inbound.py:71`) |
| `rem0te-http-resp-v1\n{request nonce}\n{sha256(body)}` | `r0:…/crypto.ts:93-94` | `cs:…/protocol.py:250-251, 277-278` |
| `rem0te-event-v1\n{canonical event}` | `r0:…/crypto.ts:97-98` | `cs:…/protocol.py:254-255` |
| `rem0te-alert-event-v1\n{canonical alert_event}` | `r0:…/signer.ts:17` (`signAlertEvent`) | `cs:…/protocol.py:258-259` |
| Clock skew ±120 s; nonce kept 2×(120+60) s | `r0:…/integration-auth.guard.ts:9-10, 57` | `cs:…/protocol.py:40`; `cs:…/inbound.py:36, 66, 83-87` (nonce recorded only after the signature verifies) |
| Canonical JSON (sorted UTF-16 keys, JS number/string formatting) | `r0:…/crypto.ts:22` | `cs:…/protocol.py:71-146` |

### 4.2 Delegation (technician identity)

- EdDSA compact JWS, `typ: rem0te-delegation+jwt`, separate delegation key, claims `iss`=peer id, `aud`=Rem0te
  audience, `sub`=technician id, `org`=organization id, one `scope`, `exp − iat ≤ 300`, single-use `jti`,
  `req_sha256` on submit/propose (`r0:…/contract.ts:75-92`, `r0:…/delegation.service.ts:72-81`;
  `cs:…/protocol.py:313-334`, minted per request in `cs:…/client.py:101-107`, TTL 120 s `protocol.py:42`).
- Identifiers: organization `org-<ClientSt0r organization pk>` (`cs:integrations/rem0te/pairing.py:67-68`),
  technician `tech-<user pk>` (`pairing.py:71-72`). Rem0te matches nothing by name; a Platform Admin maps each
  organization to a business and each technician to a Rem0te user, with step-up, in Rem0te.

### 4.3 Who decides what

| Decision | Decided by | Where |
|---|---|---|
| Whether a ClientSt0r user may request analysis / see drafts / propose a catalog action / launch remote / run diagnostics | ClientSt0r, per customer, from a live technician-access assignment | `cs:psa_ai/permissions.py:36-69` → `cs:tech_access/resolver.py` |
| Whether that technician id may act at that business at all, and with which Rem0te capability | Rem0te, from its technician mapping and roles, on every delegated call | `r0:…/delegation.service.ts:126` (`FORBIDDEN`); re-checked before each run, `ACTOR_REVOKED` (`r0:…/worker.service.ts:102, 149`) |
| Whether a business is paused (integration, actions, remote, updates) | Rem0te (containment) | `r0:apps/api/src/containment/pause.ts`, `r0:…/jobs.service.ts:76-81` |
| Whether a proposed action runs | Rem0te's approval signer: roster approvers with passkeys on the signer's own origin; the agent verifies the signature and device binding | `r0:docs/approved-actions.md`; `r0:…/contract.ts:307-363` (no command/script/path fields; no approve route) |
| Which AI provider and model, provider keys, customer communication | ClientSt0r only (Rem0te holds no provider key and has no route that messages a customer) | `r0:docs/contracts/ticket-rmm-v1/CLIENTST0R.md`, *Responsibilities*; `cs:psa_ai/services/gateway.py` |

**Rule both sides keep: a ClientSt0r permission never authorizes anything Rem0te refuses.** ClientSt0r checks first
so it does not send what it would not allow; Rem0te checks again and its answer wins. ClientSt0r has no approve or
execute route for Rem0te actions (`cs:integrations/rem0te/actions.py:12`: it "never marks anything approved").

### 4.4 Keys and rotation

- ClientSt0r's request and delegation private keys live encrypted in `Rem0teIdentity` (one identity for the whole
  instance, all organizations) (`cs:integrations/rem0te/identity.py:31-75`). Rem0te's peers file accepts up to 4
  request keys and 4 delegation keys per peer (`r0:apps/api/src/integration/peers.ts:39-40`).
- **ClientSt0r rotation today is a hard cut-over:** `generate_keys(rotate=True)` replaces both private keys at once
  (`cs:…/identity.py:50-75`) and `peer_entry()` lists only the new public keys (`identity.py:182-183`). Requests fail
  with `KEY_UNKNOWN` until Rem0te's operator edits the peers file and restarts. Gap G9.
- Rem0te's signing keys are entered by a ClientSt0r administrator (at most 4, `cs:…/pairing.py:137-138`) and compared
  with `/capabilities.signing_keys` at Check pairing (`pairing.py:328-340`). ClientSt0r never learns a key from
  Rem0te automatically (by design: the trust anchor is set by a person). Rem0te keeps `self.previousKeys`
  (`r0:…/peers.ts:62, 106`).

---

## 5. Revision-2 gaps in ClientSt0r (ranked)

Verified 2026-11-11 by validating Rem0te 0.30's fixtures with ClientSt0r's own validator
(`cs:integrations/rem0te/schema.py` `errors()` against the vendored schemas):
`capabilities.lab.json` → `contract_revision: unknown field; organizations: unknown field`;
`alert-event.raised.json` → `alert.patch_summary: unknown field`.

| # | Gap | Effect against rem0te 0.30.x | File(s) to change |
|---|---|---|---|
| **G1** | Vendored `capabilities` schema has `additionalProperties: false` and no `contract_revision` / `organizations` | **Check pairing fails** with `CONTRACT_MISMATCH` ("capabilities do not match the pinned schema"), so `is_processor()` is false and every Rem0te feature is off | `cs:integrations/rem0te/contract/` (re-vendor from `4b2b9f5`, update `PIN.json`); `cs:integrations/rem0te/pairing.py:304-307` |
| **G2** | Vendored `alert` schema rejects `patch_summary` | **Every alert event is refused 400** (Rem0te emits the key on every alert, null or not). Push is retried then abandoned; polling re-fetches the same refused events because `cursor()` never advances past an unrecorded sequence (`cs:integrations/rem0te/alerts.py:204-214, 233-239`): a head-of-line block, no alert tickets at all | same re-vendor; `cs:integrations/rem0te/alerts.py:57-59` |
| G3 | `contract_revision` not read; no negotiation | Cannot tell rev 1 from rev 2; cannot refuse a future rev it does not know (or accept it safely) | `cs:integrations/rem0te/pairing.py:296-345` (record it in the check doc; accept `1 ≤ rev ≤ implemented`; decide the policy for newer revisions with Rem0te, §7 R2) |
| G4 | `organizations[]` not consumed | Organization mapping is inferred from a 403 on `/alerts/events` (`pairing.py:414-429`), and only when alerts are enabled; business name and pause state are never shown | `cs:integrations/rem0te/pairing.py` (`check()`, `status()`); `cs:templates/integrations/_rem0te_pairing.html` |
| G5 | `paused` kinds not surfaced | A paused business looks like a generic failure; jobs keep retrying `CONTAINED` until they expire (`cs:integrations/rem0te/jobs.py:188-194`); proposals refused by a pause become `rejected` (`actions.py:144`) | `cs:integrations/rem0te/pairing.py` (state → "Degraded: paused at Rem0te: actions, integration"); `jobs.py:188-194` (stop retrying while the capability says `integration` is paused); `actions.py:138-146` (disable "Propose" when `actions` is paused) |
| G6 | `alert.patch_summary` not stored or shown | REBOOT_PENDING tickets carry no patch evidence | `cs:psa_ai/models.py` (`Rem0teAlertTicket`: a JSON field + migration), `cs:integrations/rem0te/alerts.py:92-155` (store; add a staff-only summary to the ticket body or panel), ticket template |
| G7 | Business cross-check | The Public-API key's business (`rem0te_business_id`, `cs:integrations/providers/rmm/rem0te.py:92-116`) is never compared with `organizations[].business_id` for this connection's `org-<pk>`. A mismatch would file inventory from one business against alerts from another | `cs:integrations/rem0te/pairing.py` `check()`; read `BUSINESS_PIN` from `field_mappings` |
| G8 | Test vectors | `FixtureVectorTests.test_alert_event_fixture_verifies_with_its_key_only` uses `fixtures/signed-alert-event.raised.json` + `fixture-alert-signing-key.pub.pem`, both **removed** in 0.30.0; the new byte-for-byte vectors are `examples/*.json` + `examples/keys/` | `cs:integrations/tests_rem0te.py:35-117` (port to `examples/`: request headers, delegation `req_sha256`, response signature, alert event with patch summary, replayed submit, 423 CONTAINED); `pin` assertion at `tests_rem0te.py:116` |
| G9 | Key rotation has no overlap | Rotation causes an outage until the peers file is edited (see §4.4) | `cs:integrations/rem0te/identity.py:50-75, 168-189` (stage a next key, list current + next in `peer_entry`, switch on operator confirmation, retire later) |
| G10 | Cross-peer E2E pinned to 0.29.0 | CI checks out `1bff01a4` (`cs:.github/workflows/cross-peer-e2e.yml:70`, reads `PIN.json`) | follows from G1's pin bump; add scenarios for G4–G7 to `cs:scripts/e2e/cross_peer/run.py` |
| G11 | Capabilities stored per connection include every organization of the peer | Once G4 is done, the stored check doc would hold every customer's `business_name` on each customer's connection (`pairing.py:382-384`) | store only this connection's own `organizations[]` entry (plus a count), never the list |

Not gaps (confirmed unchanged between `1bff01a` and `4b2b9f5`): `job-request`, `job`, `event`, `signed-event`,
`delegation-claims`, `inference-*`, `analysis-*`, `action-proposal*`, `alert-ticket-link`, `error` schemas, signing
strings, header names, skew window.

---

## 6. Legacy HMAC path (other RMM providers)

`cs:integrations/ticket_rmm.py` and `cs:psa_ai/services/integration_auth.py` keep the HMAC flavour of the contract
for providers other than Rem0te (handoffs, read-only diagnostics, remote launch, fix referral; v3.17.646–658).
A Rem0te connection never uses it: migration `integrations/0037_rem0te_hmac_needs_repair` switches HMAC Rem0te
pairings off and marks them *Needs re-pairing* (`cs:docs/contracts/ticket-rmm-v1/README.md`, *Upgrading*), and
`pairing.advertised()` never advertises handoff/diagnostics/remote launch for Rem0te (`cs:integrations/rem0te/pairing.py:193-207`).
Rem0te's contract has no handoff, diagnostics or remote-launch routes (`r0:…/CLIENTST0R.md`, second table).

---

## 7. Requests to the Rem0te session

Each is a request with its reason; the Rem0te session decides the shape. Nothing here assumes an API exists.

| # | Request | Why ClientSt0r needs it |
|---|---|---|
| R1 | **Re-run `interop-clientst0r.mjs` against the ClientSt0r Ed25519 implementation** (`integrations/rem0te/`, branch `dev/program-2026-11` @ `47c30b72` or later), and update `CLIENTST0R.md` / `clientst0r-interop.json` to say which ClientSt0r code was measured. | `drive.py` imports only the HMAC module (`r0:scripts/clientst0r-interop/drive.py:23-24`), so "does not interoperate" is measured against code a Rem0te pairing no longer uses. ClientSt0r will fix G1/G2 first so the run is meaningful. |
| R2 | **Say how a peer at revision N should treat fields from revision N+1.** Either guarantee per-revision schemas a peer can pin, or document that peers must accept unknown fields in Rem0te→peer documents (capabilities, alerts, events), or let a peer declare the revision it implements so Rem0te sends nothing newer. | "Revisions only add fields" is stated, but the generated schemas are `additionalProperties: false` (from zod `.strict()`), so a peer that validates with them — as `schemas/` invites — breaks on every revision (that is G1/G2). ClientSt0r prefers strict validation of inbound data and will not silently drop fields from signed documents. |
| R3 | **A side-effect-free way to learn whether a technician id is mapped and enabled** for an organization (e.g. in capabilities, a probe, or a documented error on an existing read). | Today ClientSt0r learns of an unmapped or revoked technician only when a real job or proposal is refused (`FORBIDDEN` / `ACTOR_REVOKED`). The setup wizard (program phase 1) needs to say "these technicians are not mapped in Rem0te" before anyone tries. |
| R4 | **Pause reason in `CONTAINED` errors:** confirm whether `pauseMessage()`'s `Reason: …` text (`r0:apps/api/src/containment/pause.ts:26-33`, returned by `r0:…/jobs.service.ts:81`) is meant for peers. | `/capabilities` deliberately omits reasons ("never the reason"), but the 423 body carries it (`r0:docs/contracts/ticket-rmm-v1/examples/error.paused-business.json`: "Reason: TW: suspected compromise, under review"). ClientSt0r stores Rem0te's message on the job (`cs:integrations/rem0te/jobs.py:191-193`) where technicians see it. ClientSt0r will treat it as staff-only either way. |
| R5 | **An endpoint health / last-seen signal over the signed contract** (or confirm the Public API is the supported path for it). | Program phases 3–4 (device workspace, ticket RMM panel) need online state, last seen and patch freshness per `rem0te_endpoint_id`. The contract carries these only inside alerts; the Public API (`/computers`) carries online/last-seen via a separate API-key credential. ClientSt0r would rather not hold two credentials per business if one channel can serve. |
| R6 | **Remote-session state that ClientSt0r can show without claiming a session started** — at minimum, whether a technician-initiated Connect from a ticket resulted in a session. | The program requires "never claim a session started until confirmed". Today ClientSt0r can only deep-link to the computer's page in Rem0te (`cs:integrations/providers/rmm/rem0te.py:204-221`); 0.30.1 made Connect need step-up in Rem0te, which is right, and leaves ClientSt0r with no confirmation at all. |
| R7 | **A push (or a signed event) for action-proposal status changes**, like alert events. | ClientSt0r polls every open proposal (`cs:integrations/rem0te/actions.py:170-182`). A signed `approved / dispatched / succeeded / failed` event would let the ticket show progress promptly and reduce delegated reads. |
| R8 | **More catalog actions, and their parameter schemas in capabilities.** | `features.actions` lists `id@version` only; ClientSt0r hard-codes the one it knows (`cs:integrations/rem0te/pairing.py:48-51`). The one-click workflows (program phase 7: service stopped, disk full, pending reboot, Windows Update failure…) need catalog actions to propose, and ClientSt0r should not guess their params. |
| R9 | **Ticket state back to Rem0te** (resolved / closed), or confirm it is out of scope. | Linking is the only write today and "grants nothing". The alert→ticket program (phase 6) wants recovery updates on the ticket (ClientSt0r side) and, possibly, Rem0te to know the ticket was closed. ClientSt0r will not ask to acknowledge or resolve alerts in Rem0te. |
| R10 | **Keep `examples/` regenerated with each revision and list the Rem0te version correctly.** | `examples/index.json` says `rem0te_version: "0.29.1"` while `contract_revision: 2` and the README says revision 2 is 0.30. ClientSt0r will pin tests to these files byte for byte (G8). |

---

## 8. Integration tasks

### Completed (ClientSt0r, unreleased, on `dev/program-2026-11`)

- Ed25519 identity, request signing, delegation JWS, inbound verification with DB nonces, signed inference
  responses (`cs:integrations/rem0te/{protocol,identity,client,inbound}.py`).
- Check pairing with specific, secret-free failure reasons (`cs:integrations/rem0te/pairing.py:232-345`).
- Analysis jobs: idempotent submit, lost-response binding by signed event, event push + polling (`jobs.py`).
- Alerts → exactly one staff-only ticket per alert, asset only via verified device link, link-back with retry and
  conflict kept (`alerts.py`).
- Catalog action proposals by L2+; status read back; no approve route (`actions.py`).
- HMAC Rem0te pairings switched off by migration 0037.

### Outstanding

| Priority | Task | Owner |
|---|---|---|
| P0 | G1 + G2: re-vendor contract at `4b2b9f5`, bump `PIN.json`, fix tests (G8) | ClientSt0r |
| P0 | G3: read and record `contract_revision`; policy agreed under R2 | ClientSt0r + Rem0te |
| P0 | Re-run cross-peer E2E against 0.30.1 (G10) and Rem0te's interop run against Ed25519 ClientSt0r (R1) | both |
| P1 | G4, G5, G7, G11: organization mapping, pause state, business cross-check, store own org only | ClientSt0r |
| P1 | Connection states Connected / Degraded / Disconnected / Authentication Problem / Configuration Required, derived from `pairing.status()` codes | ClientSt0r |
| P1 | G6: patch summary on REBOOT_PENDING tickets | ClientSt0r |
| P1 | G9: overlapping key rotation | ClientSt0r |
| P2 | R3, R5–R9 as Rem0te decides | Rem0te |

---

## 9. Integration test results

| Date | What | ClientSt0r | Peer | Result | Status |
|---|---|---|---|---|---|
| 2026-11-10 | Cross-peer E2E (`cs:scripts/e2e/cross_peer/run.py`, scenarios s1 pairing … s10 failure reasons) | integration branch (Ed25519) | rem0te `1bff01a4` (0.29.0, revision 1) | 71/71 checks passed (as reported to this session; the result file is not committed) | **STALE** against revision 2. Not re-run on 2026-11-11. By G1/G2 above, s1 (pairing) and s4 (alert → ticket) are expected to fail against 0.30.x until ClientSt0r re-vendors. |
| 2026-11-10 | Rem0te's `interop-clientst0r.mjs` | 3.17.659 `a5f83826` (HMAC module only) | rem0te 0.29.1 | "does not interoperate", 4 gaps | Accurate for released ClientSt0r; does not cover the Ed25519 branch (§1 note, R1) |
| 2026-11-10 | Rem0te's `e2e-ticket-workflow.mjs` | reference peer (not ClientSt0r) | rem0te 0.30.0 | pass, per `r0:docs/contracts/ticket-rmm-v1/README.md` | not verified by this session |
| 2026-11-11 | Schema check: Rem0te 0.30 fixtures through ClientSt0r's validator | `dev/rmm-coordination` @ `47c30b72` | `4b2b9f5` fixtures | capabilities and alert-event **rejected** (unknown fields) | current — the basis of G1/G2 |

Unit/fixture tests on the ClientSt0r side: `cs:integrations/tests_rem0te.py` (fixture vectors, key parsing,
identity, Check pairing, inbound auth, migration, connection page) and `cs:psa_ai/tests_rem0te.py` (jobs, inference
refusals, revoked technician, lost response, alerts incl. same computer name in two customers, gap recovery, link
conflict, proposals, L1 limits). They run against a fake Rem0te built from the **0.29.0** fixtures, so they do not
detect G1/G2. Not run on 2026-11-11.

---

## 10. Breaking changes

| When | Change | Who breaks |
|---|---|---|
| rem0te 0.30.0 (revision 2) | `capabilities.contract_revision` and `capabilities.organizations` are required; `alert.patch_summary` is a required key | Any peer validating with the revision-1 schemas — **ClientSt0r's integration branch today** (G1, G2). Rem0te documents this as additive; in practice it is breaking for strict validators (R2). |
| rem0te 0.30.0 | `fixtures/signed-alert-event.raised.json` and `fixtures/fixture-alert-signing-key.pub.pem` removed (replaced by `examples/`) | ClientSt0r's vendored copy and `FixtureVectorTests` once re-vendored (G8) |
| rem0te 0.30.1 | Connect from Rem0te's portal needs step-up; the password is no longer in the Connect response | No contract change. ClientSt0r only deep-links to Rem0te; no effect on ClientSt0r code |
| ClientSt0r (unreleased) | Rem0te pairings are Ed25519 only; HMAC Rem0te pairings are switched off by migration 0037 and must be re-paired | Existing HMAC Rem0te pairings on released ClientSt0r (none interoperated with Rem0te, per Rem0te's own measurement) |

## 11. 2026-11-11 — Phase 1: Rem0te revision 2 on ClientSt0r

Folded in from `docs/plans/coordination/phase1-integration.md` (the file is kept).

Branch `dev/rmm-p1-integration` (from `47c30b72`). Peer: Rem0te `4b2b9f5cbe093b99563b9332ba3bdf9dded88720`
(v0.30.1, contract `ticket-rmm-v1` revision 2). Nothing was released, tagged, pushed or deployed.

### Contract revision implemented

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

### Gaps closed

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

### Rem0te requests

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

### E2E results

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

## 12. 2026-11-11 — Phase 8: RMM permission API

Folded in from `docs/plans/coordination/phase8-permissions.md` (the file is kept).

Branch `dev/rmm-p8-roles`. App: `rmm_permissions`. For agents building the Rem0te protocol, the device
workspace and ticket panel, alert workflows and AI: **call this API for every RMM action**.

### What existed before Phase 8

| Area | State before | Phase 8 |
|---|---|---|
| `tech_access` presets L1/L2/L3 (per-customer assignments, explicit denies, customer restrictions, containment, two-admin protected changes, "why" page) | Shipped. Gated the ticket RMM panel (handoff, diagnostics, remote, fix referral) through `tech_access.resolver.decide` | Kept, unchanged. One input to the new decision: grants, blocks and the customer scope |
| `RoleTemplate` flags | Shipped, but nothing about RMM tiers | `rmm_tier` added (default `''`). Four new built-in templates |
| Platform administrator role | Missing. Superuser stood in | Built-in **Platform Administrator** template (tier `platform_admin`) |
| High-impact RMM work (scripts, patches, device administration, automation) | Missing | Actions in the catalog. They need second-person approval |
| Per-org / per-action allow, deny and require-approval overrides | Missing. `tech_access` had per-capability denies and restrictions only | `RMMPermissionOverride` |
| Second-person approval of RMM operations | Missing in ClientSt0r. Rem0te has its own | `RMMApproval` |
| Audit of every allow and deny | Partial: only requests that were created | `rmm_action()` audits every allow and deny |
| Composition with a Rem0te refusal | Partial: each path handled it by hand | `record_remote_refusal()` |

### The API

```python
from rmm_permissions import can, rmm_action, require, record_remote_refusal, RMMPermissionDenied
from rmm_permissions.approvals import request_approval, approve, reject

d = can(user, organization, 'patch.deploy', device=rmm_device, ticket=None)   # pure, no audit: for rendering
d = rmm_action(user, organization, 'patch.deploy', device=rmm_device, digest=op_digest, request=request)
if d.permitted_now:            # same as bool(d)
    ...do it...
elif d.allowed and d.needs_approval:
    request_approval(user, organization, 'patch.deploy', device=rmm_device, digest=op_digest, summary='...')
else:
    refuse(d.reason)
# after the paired RMM answers:
if rem0te_refused:
    d = record_remote_refusal(d, user, organization, code=r.code, message=r.message, request=request)
```

The `Decision` fields:

- `allowed`: the actor may do this, or may ask for it.
- `needs_approval` and `approval_level`: a second person must approve before it runs. Levels: `peer`, `l3` or `platform_admin`.
- `permitted_now`: allowed and, if needed, approved. `rmm_action` consumed a matching approval and set `approval_id`.
- `grant`: `allowed`, or `request` (the paired RMM grants the session itself, as for remote view and control).
- `reason`: the human answer.
- `source`: what decided it: `tier:l2`, `tech_access`, `legacy:<flag>`, `override:<pk>`, `tenant`, `rem0te` and so on.
- `rem0te_scope`: the ticket-rmm-v1 delegation scope used for this action. `''` means synced data with no delegation. `None` means Rem0te has no route for it.
- `steps`: the chain behind the decision (layer, effect, detail, decisive). The effective-permissions pages render it.
- `as_dict()`: the same, as a dict.

Rules for callers:

- Use `can()` to show or hide buttons. Call `rmm_action()` (or `require()`) **immediately before acting**, on the server, every time. It re-reads every row, so demotion, revocation and new denies apply to the next call, queued jobs included.
- Pass the `device` (an `integrations.RMMDevice`, or an `assets.Asset`) and the `ticket` whenever there is one. That is how the tenant checks, the workstation-only limits, the own-ticket limits and the Rem0te-route checks happen.
- Pass a `digest` of the exact operation (for example sha256 of the canonical payload) both to `request_approval` and to `rmm_action`. An approval only matches the same requester, customer, action, device and digest, and it is used once.
- After Rem0te or another RMM refuses, call `record_remote_refusal`. **Its refusal always wins**: do not retry around it.
- When you refuse for a reason of your own (for example, the RMM doesn't advertise the feature), call `audit_denial(user, organization, action, reason, device=..., request=...)`. That way every denied RMM action is in the audit log.

### Action keys

The catalog is `rmm_permissions/catalog.py`. `tech_access` capability = the preset capability also consulted. Rem0te = the ticket-rmm-v1 scope, `''` = no delegation needed, none = no Rem0te route (refused on Rem0te-managed devices).

| Key | L1 | L2 | L3 | tech_access | Rem0te |
|---|---|---|---|---|---|
| device.view, alert.view | yes | yes | yes | — | `''` |
| diagnostics.view | yes | yes | yes | — | none |
| remote.request_support | request | request | request | remote_view | none |
| remediation.request_low | yes | yes | yes | fix_request_low | actions:propose |
| rmm.handoff | — | yes | yes | rmm_handoff | none |
| diagnostics.run | — | workstations | yes | diagnostics_readonly | none |
| workflow.run_approved | — | yes | yes | — | none |
| remote.request_control | — | request | request | remote_control | none |
| script.run_scoped | — | only by an approved allow override; approval l3 | approval peer | — | none |
| patch.deploy | — | workstations, approval l3 | approval peer | — | none |
| diagnostics.run_advanced | — | — | yes | diagnostics_advanced | none |
| remediation.request_high, remediation.refer | — | — | yes | fix_request_high / fix_refer | actions:propose |
| remote.request_elevation | — | — | request | elevation | none |
| device.administer, automation.deploy | — | — | approval peer | — | none |
| credential.reveal | only with the vault reveal permission at that customer; no tier or override grants it | | | — | none |
| integration.configure, policy.manage, security.settings, audit.review | Platform Administrator only (legacy: integrations_configure, superuser, audit_view) | | | — | — |

Locked (never available): `shell.unrestricted`, `tenant.all_access`, `approval.self`, `endpoint.approve`.

ClientSt0r invents no Rem0te scopes. The only ones it uses are Rem0te's own `ticket_analysis:submit`, `ticket_analysis:read`, `actions:propose` and `actions:read` (`integrations/rem0te/protocol.py SCOPES`). A test checks this. Rem0te's approval roster, passkeys and signer still apply on top of any ClientSt0r approval.

### How a decision is made

The order is in the docstring of `rmm_permissions/decision.py`. In short:

1. **Blocks come first**: locked actions, the user not being a technician, containment, the customer boundary, deny overrides, tech_access denies and restrictions, an unavailable integration, and no Rem0te route.
2. **Then grants**:
   - the role tier, read only from the technician's *global* role, and only at customers where they hold a live tech_access assignment;
   - the tech_access preset;
   - the legacy flags;
   - approved allow overrides.
3. **Then approval.** A deny always wins.

**Upgrade.** Existing templates have no tier and there are no override rows. The preset and legacy-flag grants are exactly the checks used before, so existing users get the same answers. Tests cover this.

### Overrides and approvals

- **Deny and require-approval** apply at once. They can target one action or `*`, one customer or every customer, and one technician, one global role or everyone.
- **Allow** names one action at one customer. It stays pending until a *different* Platform Administrator approves it, after a fresh password check. The person it grants to cannot approve it. High-impact actions also need a tier that lists them. An allow never covers credential reveal.
- **Lifting a deny or a require-approval** also needs a second administrator.
- **RMMApproval approvers.** Nobody approves their own request. The approver re-authenticates, and must qualify now: *peer* = may do the same action there; *l3* = L3 tier or an L3 preset at that customer; *platform_admin* = holds policy.manage. The requester is re-checked when the approval is given and again when it runs. Approvals expire after 24 hours.

### Pages

These are under Settings → Security → **RMM Permissions** (`/settings/security/rmm-permissions/`):

| Page | Shows | Who |
|---|---|---|
| Index | Overrides and their reviews | policy.manage to change; audit.review to read |
| `technician/<id>/?organization=` | Effective permissions and approval requirements, with the chain for each, linked to tech_access's "why" for mapped capabilities | policy.manage or audit.review |
| `customer/<id>/` | Every assigned technician × every action | policy.manage or audit.review |
| `approvals/` | Approvals waiting for a second person | Technicians |

### Wiring

`psa_ai/services/rmm_actions.py` calls the API for the existing ticket panel actions (handoff, diagnostic, remote view and control, fix referrals). The panel uses `can()`. Each operation calls `rmm_action()` before it acts, and Rem0te proposal refusals are recorded with `record_remote_refusal()`.

## 13. 2026-11-11 — ClientSt0r response to Rem0te revision 3

Folded in from `docs/plans/coordination/clientst0r-response-2026-11-11.md` (the file is kept).

From the ClientSt0r session, for rem0te's `INTEGRATION_COORDINATION.md` (rem0te's copy is authoritative for
the contract). This file only reports and acknowledges. It changes nothing in rem0te.

### 1. Correction: ClientSt0r's development branch already implements revision 2

The status in rem0te's sections 2, 4C and 6 is correct for **released** ClientSt0r 3.17.660/3.17.661, which
still uses HMAC. The development branch `dev/program-2026-11` is not yet released and has not been pushed. It
implements rem0te's protocol in `integrations/rem0te/`:

| rem0te item | ClientSt0r dev branch |
|---|---|
| CS-1 Ed25519 request key and separate delegation key | Done. Overlapping rotation: stage → switch → discard, each step audited. The peers-file entry lists the staged keys next to the current ones |
| CS-2 Sign outbound requests and reproduce `examples/` byte for byte | Done. Tests use rem0te's `examples/` with the TEST-ONLY keys |
| CS-3 Delegation JWS per technician action (`sub`, scope, `req_sha256`, short `exp`) | Done |
| CS-4 Verify rem0te requests and events with `/capabilities.signing_keys`; sign `/inference` responses over the nonce | Done |
| CS-5 Read `organizations` and `features` | Done. Only this organization's own `organizations[]` entry is kept (plus a count), and `business_id` is checked against the connection's business pin (`BUSINESS_MISMATCH` stops pairing) |
| CS-6 Build `job-request` bodies and validate against `schemas/` | Done. Contract pinned at rem0te `4b2b9f5c` (revision 2); revision 1 is kept for older peers |
| CS-7 Event names `job.succeeded/partial/failed/expired` | Done for rem0te connections (`integrations/rem0te/jobs.py`) |
| CS-8 Acknowledge revision 3 | Section 2 below |

Also built on the same branch:
- Containment: pause shown as Degraded; a `CONTAINED` job fails once and isn't retried; a proposal under a pause is `unavailable`. The pause reason is never stored.
- Alerts: events ClientSt0r can't apply are recorded and acknowledged (skip and record) and re-applied later.
- `patch_summary` is stored and shown.
- A reconciliation job with backoff.
- A setup wizard with Test connection.
- One connection status: Connected / Degraded / Disconnected / Authentication Problem / Configuration Required.

**Real-app test, both sides running:** ClientSt0r's `scripts/e2e/cross_peer/` against a locally built rem0te
`4b2b9f5cbe093b99563b9332ba3bdf9dded88720` (0.30.1, own Postgres and Redis), with ClientSt0r running from the
branch: **99 passed, 3 failed.**

The 3 failures are all scenario s5: an analysis job submitted while ClientSt0r restarts. rem0te's worker gives
up after 3 `GATEWAY_UNREACHABLE` attempts (~13 s), and the loaded test host took longer to restart. See request
R11.

ClientSt0r does not claim interoperability for that case. Proposals during a pause are unit-tested only. Before
this is released, ClientSt0r will run the test again against rem0te 0.31.0 (`915cb58`); its contract schemas are
unchanged from 0.30.1.

ClientSt0r would welcome rem0te running its own `e2e-ticket-workflow` with this branch in place of the
reference peer once it is pushed.

### 2. Acknowledgement of revision 3 (P1–P10)

ClientSt0r **acknowledges P1–P10 as proposed**, with these notes. None of them changes rem0te's authentication.

| ID | Response |
|---|---|
| P1 | Agreed, including `remote_view` only when view-only is actually enforced. ClientSt0r never shows view-only as a restriction unless it is advertised. The `diagnostics` catalog with `device_classes` matches what ClientSt0r's ticket panel and Device Workspace already read |
| P2 | Agreed. ClientSt0r will send only catalog keys; results are shown as untrusted device output and never fed to AI as instructions |
| P3 | Agreed; these match ClientSt0r's transitions |
| P4 | Agreed. ClientSt0r already uses `action-proposals` for catalog actions; `/fixes` for referrals with `fix.received` when nothing fits is what ClientSt0r wants. Free text never becomes a command on either side |
| P5 | Agreed. ClientSt0r treats `fix.succeeded` as "verifying" until monitoring confirms recovery |
| P6 | Agreed (no credentials; `view` refused until enforceable). Request: a signed `remote.session_started` / `remote.session_ended` event carrying `request_id` and ticket ref, so ClientSt0r can show "session started" only after rem0te confirms it (until then ClientSt0r shows "link issued — session not confirmed") |
| P7 | **Yes: a staff note on the computer, in its History, with the ticket ref, is the intended effect** of a handoff. Nothing else should happen |
| P8 | Already done for rem0te connections on the development branch |
| P9 | Agreed |
| P10 | Agreed. ClientSt0r would use it for the Device Workspace and the ticket panel instead of relying only on synced data. Please include agent version and data freshness (`observed_at`) per field group |

Suggested section 9 row:
`2026-11-11 | ClientSt0r | Revision 3 P1–P10 acknowledged as proposed, with the notes in ClientSt0r's response (P6 session events, P7 = staff note, P10 freshness)`.

### 3. Requests from ClientSt0r (proposals; not implemented on either side)

ClientSt0r's development work needs these. Each is a request: rem0te decides the shape. Nothing here was built
against an invented API; on ClientSt0r's side each one shows as "not supported by the connected rem0te" until it
is advertised.

| ID | Request | Why |
|---|---|---|
| R2 | State how a peer implementing revision N handles fields from N+1: per-revision schemas, or a declared peer revision | The generated schemas reject unknown fields, which is what broke pairing and every alert when 0.30.0 shipped. Interim: ClientSt0r accepts unknown fields only when `contract_revision` is newer than it implements, and logs them |
| R3 | A documented technician-mapping probe | Today ClientSt0r infers it from a delegated `GET /jobs/{nil uuid}` (404 = mapped, 403 = not), which spends a delegation id |
| R4 | Leave the pause reason out of 423/403 `CONTAINED` bodies, as `/capabilities` already does | ClientSt0r shows a fixed message and never stores it, but the reason crosses the wire |
| R6 | Remote-session confirmation events | See P6 |
| R7 | Push action-proposal status changes as signed events | ClientSt0r polls proposals today |
| R8 | More catalog actions, with parameter schemas in capabilities, proposable from a ticket: disk cleanup (temp files, Windows Update cache, Recycle Bin), reboot (for pending-reboot), `windows.update.install@1` from a ticket, not only through staged patching | ClientSt0r's one-click workflows can only offer manual steps for these today. Only `windows.service.start@1` (Spooler) is remediable |
| R9 | Accept ticket state back (opened, resolved, closed), or confirm it is out of scope | — |
| R10 | `examples/index.json` says 0.29.1 although it is labelled revision 2 | Cosmetic |
| R11 | Keep retrying a transient `GATEWAY_UNREACHABLE` model run until the job expires, or for a configurable window (as alert delivery already does) | A ClientSt0r restart longer than ~13 s ends every job queued during it as `ALL_PROFILES_FAILED` (s5 above) |
| R12 | Structured metrics on alerts: disk free % and GB per volume, CPU %, memory % | ClientSt0r currently parses alert titles |
| R13 | Read-only evidence and diagnostics that don't need `model_profiles` (jobs are AI-only today) | Read-only diagnostics must work with AI disabled |
| R14 | A route listing active maintenance windows per organization | So ClientSt0r can show which alerts rem0te itself is holding |
| R15 | Read access to local and endpoint user accounts per computer | ClientSt0r's offboarding check can verify removal in Microsoft 365 and ClientSt0r but must mark rem0te "not verifiable" |
| R16 | Services, processes, event-log excerpts and installed software via `computers/{id}/summary` or a read-only diagnostic | The Device Workspace shows them as unsupported for rem0te |

### 4. Breaking changes on ClientSt0r's side

Replacing HMAC with Ed25519 for rem0te connections is ClientSt0r's migration. The development branch keeps
revision-1 peers and the generic HMAC "any RMM" path for other providers. Pairing records for rem0te move to
`Rem0teIdentity` and `Rem0teReplayGuard` (migrations `integrations 0036–0038`). No change is needed in rem0te.
