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
