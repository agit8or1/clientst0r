# ClientSt0r and ticket-rmm-v1: what to consume, and what does not match yet

**Rem0te's implementation is canonical.** ClientSt0r should consume contract **ticket-rmm-v1, revision 2**, as
shipped in **rem0te 0.30.0** (the commit tagged `v0.30.0`). This directory is the whole interface:

| File | Use |
|---|---|
| `schemas/*.schema.json` | JSON Schema for every message, generated from rem0te's runtime zod schemas |
| `openapi.yaml` | The routes on both sides |
| `examples/*.json` | Real signed exchanges from `e2e-ticket-workflow.mjs`, with the TEST-ONLY keys that verify them in `examples/keys/`. Reproduce your signer against these byte for byte |
| `clientst0r-interop.json` | The last measured run of ClientSt0r's own code against rem0te (below) |

Read `contract_revision` from `/capabilities` and use nothing newer than you implement. Revisions only add
fields. Revision 2 adds `contract_revision`, `organizations` and `alert.patch_summary`.

## Revision 3: acknowledged 2026-11-11, not built

ClientSt0r acknowledged P1–P10 (`INTEGRATION_COORDINATION.md` §5) as proposed; its notes and its requests R2–R16 are
recorded in §9 and §9A there. rem0te has not built them, so build against revision 2 until `/capabilities` reports
`contract_revision: 3`.

## Proposed for revision 4: the device summary (rem0te 0.34, not agreed)

rem0te no longer calls a model provider for the device page's AI summary; it asks your gateway instead, with a new
inference task `device_timeline_v1` (P11) that it uses only after your own capabilities document lists it (P12).
Shapes, what rem0te sends and three open questions are in `INTEGRATION_COORDINATION.md` §5A; JSON Schemas in
`proposed/`. These are proposals: build them only once they are acknowledged there. Until then rem0te shows
*Needs ClientSt0r support for device_timeline_v1* and sends nothing.

## Proposed for revision 5: agent-silent alerts and tray support requests (rem0te 0.36.1, not agreed)

`AGENT_SILENT` as an alert kind (P13), a signed `support_request.created` event (P14) and an authenticated read for
a request and its attachments (P15). rem0te proposes to send them **only to a peer that declares
`contract_revision` ≥ 5** in its capabilities document, never to an older one, because a strict validator would
refuse them (your R2). Nothing is built on rem0te's side and nothing is sent. Shapes and three questions:
`INTEGRATION_COORDINATION.md` §5B.

## Measured: ClientSt0r 3.17.659 does not interoperate

`apps/api/scripts/interop-clientst0r.mjs` starts a real rem0te API on a scratch database and runs
`scripts/clientst0r-interop/drive.py` inside a disposable ClientSt0r: its own Django, sqlite, and its own
`psa_ai.services.processor` and `integrations.ticket_rmm` code. Last run against ClientSt0r
**3.17.659, commit `a5f83826c059af20a74f100b74045405c93aa02a`**:

| # | Where | ClientSt0r does | rem0te expects | Observed |
|---|---|---|---|---|
| 1 | **Request signing** | HMAC-SHA256 with a shared secret (`integration_outbound_secret`). Headers `X-Integration-Key-Id`, `-Timestamp` (±300 s), `-Nonce`, `-Signature`. Canonical string `METHOD\nPATH\nTS\nNONCE\nsha256(body)`, path without query and without audience | Ed25519, one key pair per direction. Headers `rem0te-key-id` (`{peer}/{kid}`), `rem0te-timestamp` (±120 s), `rem0te-nonce`, `rem0te-signature`. Canonical string `rem0te-http-req-v1\n{audience}\n{METHOD}\n{path?query}\n{ts}\n{nonce}\n{sha256}` | `refresh_capabilities` → *"The RMM answered HTTP 401."* |
| 2 | **Capabilities** | A flat `capabilities` list (`analysis.jobs`, `rmm_handoff`, …) and a pinned `tenant.id`: one pairing is one customer | `features` (an object), `contract_revision`, and `organizations`: one peer serving several businesses, one organization per business | `record_capabilities(rem0te's real document)` → *"did not say which tenant … cannot be paired"*, and no capabilities recognised |
| 3 | **Callbacks** | Events verified with the HMAC inbound secret and `X-Integration-*` headers | Events signed by rem0te's Ed25519 key over `rem0te-event-v1\n{canonical event}` (jobs) or `rem0te-alert-event-v1\n…` (alerts), sent with rem0te-* request headers | rem0te's signed `job.succeeded` → ClientSt0r `/api/integration/v1/events` **401** *"Request signature not accepted."* |
| 4 | **Job request** | `processor.job_payload`: `job_id`, `kind`, `business_id`, `actor{id,delegation}`, `profiles[{id,name,provider,location}]`, `evidence_digest`, `processing_location`, `inference_url`, `events_url`; `ticket{id,ref,revision}` | `job-request`: `technician_id`, `ticket{id,revision,subject,body,comments}`, `model_profiles` (names rem0te's peers file allows), `evidence`; the delegation token in the `rem0te-delegation` header bound to the body by `req_sha256`; no URLs (they live in rem0te's root-owned peers file) | Schema: missing `technician_id`, `ticket.subject`, `ticket.body`, `model_profiles`; unknown `ticket.ref` and nine top-level keys |

Also in ClientSt0r's code, not exercised by the run because pairing fails first:

| ClientSt0r calls | rem0te |
|---|---|
| `GET /jobs/{ClientSt0r's job.id}` | Jobs are rem0te's: `GET /jobs/{job_id}` takes the `job_id` rem0te returned, with a `ticket_analysis:read` delegation token |
| `POST /handoffs`, `/diagnostics/requests`, `/fixes`, `/remote/launch` | **No such routes.** A fix is an *action proposal* (`POST /action-proposals`, catalog only, independently approved on rem0te's signer). Remote launch is a technician in rem0te's portal. Diagnostics are the evidence in a job |
| Event types `job.completed`, `job.cancelled` | `job.succeeded`, `job.partial`, `job.failed`, `job.expired` (plus `job.accepted`, `job.running`) |
| Idempotency in an `Idempotency-Key` header | `idempotency_key` in the body; the same key with another body is `409 IDEMPOTENCY_CONFLICT` |
| JSON with sorted keys | Signatures cover the bytes sent. The *delegation* binding is `sha256(canonical JSON of the parsed body)`: RFC 8785-style, keys sorted |

## Business binding

The binding is `(peer, organization_id) → business`, one to one in both directions, and a Platform Admin creates
it in rem0te with step-up. A ClientSt0r that serves several customers is **one peer with one organization per
customer**: every request names its `organization_id`, and nothing is ever matched by name. Two customers each
with a PC called `FRONTDESK` stay apart because computers are named by `rem0te_endpoint_id`, and an id from
another organization's business is refused (`e2e-ticket-workflow.mjs`, "Two customers, identically named PCs").
`/capabilities` lists the calling peer's organizations, each with its `business_id`, `business_name` and
`paused` (the containment kinds in force, never the reason), so a peer operator can check the mapping. These are
shown, not accepted: no route takes a business id.

ClientSt0r's single-tenant pin (`tenant.id`) maps onto this as one ClientSt0r customer equals one
`organization_id`. ClientSt0r can keep its one-customer-per-pairing rule by checking that `organizations`
contains exactly the organization it pinned.

## What closes the gap (ClientSt0r side)

1. Generate an Ed25519 request key and a separate delegation key. Give rem0te's operator the public halves for
   the peers file. Sign requests and delegation tokens as `examples/` shows, and check your output against them.
2. Verify rem0te's requests to `/inference` and `/events` with rem0te's key from `/capabilities.signing_keys`.
   Sign `/inference` responses over the request nonce.
3. Build `job-request` and `action-proposal-request` bodies, and validate them against `schemas/` before sending.
4. Read `organizations` instead of `tenant.id`, and `features` instead of `capabilities`.
5. Then run `e2e-ticket-workflow.mjs`'s scenarios against the real thing. `interop-clientst0r.mjs` is
   expected to *fail* from that point, and should then be turned into the pass.

## Responsibilities that do not move

- AI provider keys, model choice and customer communication stay in ClientSt0r. Rem0te calls ClientSt0r's
  inference endpoint by profile name and holds no provider key. A draft reply comes back `staff_only` with
  `requires_human_review`, and rem0te has no route that messages a customer.
- An AI suggestion or a ticket referral authorizes nothing. A proposal becomes a plan **awaiting approval** on
  rem0te's approval signer: approvers sign it with passkeys on the signer's own origin, the agent verifies that
  signature and the device binding, and every step is in rem0te's sealed audit log. There is no approve route in
  the portal or the integration.
