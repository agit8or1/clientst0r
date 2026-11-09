# ticket-rmm-v1 — ClientSt0r ↔ rem0te ticket integration contract

Status: **ClientSt0r side implemented (v3.17.646); rem0te side not yet implemented.** Everything ClientSt0r does
here has been tested against a test processor (a fixture that plays rem0te), not against a real rem0te.

## Who owns what

| ClientSt0r | rem0te |
|---|---|
| Ticket UI, visibility, AI settings, provider credentials | Processing analysis jobs |
| The inference gateway (the only thing that calls a model) | Collecting approved device evidence (later milestone) |
| Customer replies and ticket history | Independent approval and execution of endpoint work |

A draft, a model vote, a remote launch or a callback can never approve a fix, send a customer reply or close a
ticket. ClientSt0r sends no endpoint commands.

## Pairing

A ClientSt0r *Rem0te* RMM connection becomes a processor when it has (Integrations → RMM → edit):

- an integration **key ID**, quoted by both sides;
- an **outbound secret** — ClientSt0r signs its requests to rem0te with it;
- an **inbound secret** — rem0te signs its requests to ClientSt0r with it (≥32 chars, different from outbound);
- a processing location: `hosted` or `local` (on-premises);
- a pinned rem0te business (recorded by the inventory sync). One pairing = one rem0te business = one ClientSt0r
  customer.

Turning the pairing on, or marking it on-premises, is a protected change that a second administrator approves.
Changing a secret, key ID or address on a live pairing switches it off until it is approved again.

## Signing (both directions)

```
X-Integration-Key-Id:     <key id>
X-Integration-Timestamp:  <unix seconds>          ±300 s accepted
X-Integration-Nonce:      <16–64 chars [A-Za-z0-9_-]>  never reused (stored per pairing)
X-Integration-Signature:  hex(HMAC-SHA256(secret, canonical))

canonical = METHOD "\n" PATH "\n" TIMESTAMP "\n" NONCE "\n" hex(SHA-256(body))
```

`PATH` excludes the query string. Transport must be HTTPS (plain HTTP only for an on-premises pairing on the LAN).

## rem0te routes (called by ClientSt0r)

### `GET /api/integration/v1/capabilities`

```json
{"contract": "ticket-rmm-v1", "capabilities": ["analysis.jobs", "rmm_handoff", "diagnostics_readonly",
 "remote_view", "remote_control", "fix_request_low", "signed_actions"]}
```

ClientSt0r caches the list on the connection. Technician-access capabilities in the *RMM*, *Remote access* and
*Fixes* groups show **Unavailable** until rem0te advertises them. `signed_actions` gates fix review.

### `POST /api/integration/v1/jobs`

Headers add `Idempotency-Key: <job idempotency key>`. Body:

```json
{
  "contract": "ticket-rmm-v1",
  "job_id": "uuid", "kind": "analyze|compare", "correlation_id": "uuid", "idempotency_key": "hex",
  "organization_id": 12, "business_id": "<pinned rem0te business>",
  "ticket": {"id": 345, "ref": "PSA-2026-000123", "revision": "<sha256>"},
  "actor": {"id": 7, "delegation": "<short-lived signed token>"},
  "endpoint": null,
  "profiles": [{"id": 3, "name": "Economy", "provider": "anthropic", "location": "cloud"}],
  "evidence_digest": "<sha256 of the redacted evidence>",
  "processing_location": "hosted|local",
  "expires_at": "ISO-8601",
  "inference_url": "https://…/api/integration/v1/inference",
  "events_url": "https://…/api/integration/v1/events"
}
```

No ticket text is sent. Response `200/201/202 {"processor_job_id": "…", "status": "accepted"}`.

- The **same idempotency key with an identical payload** must return the original job.
- The **same key with a different payload** must return **409**.

### `GET /api/integration/v1/jobs/{job_id}`

`{"status": "accepted|queued|running|completed|failed|cancelled", "sequence": <int>}`. ClientSt0r polls this to
recover missed events. If rem0te is unreachable, the job is marked *unavailable* and nothing else changes —
manual ticket work carries on.

## ClientSt0r routes (called by rem0te)

### `POST /api/integration/v1/inference`

```json
{"contract": "ticket-rmm-v1", "job_id": "uuid", "profile_id": 3,
 "delegation": "<the token from the job>", "evidence_digest": "<from the job>"}
```

Before any provider is called, the gateway re-checks against current data:

- **Pairing:** the job belongs to the calling pairing, and the pairing is enabled.
- **Job:** not expired and not finished.
- **Delegation:** names this job, actor, customer and ticket, and is less than 15 minutes old.
- **Actor:** still an active technician with the capability on this ticket (technician access, re-read).
- **Tenant binding:** job, ticket and pairing are one customer, and the business pin matches.
- **Ticket:** its revision is unchanged since the preview.
- **Evidence:** the digest matches, and the stored evidence still hashes to it.
- **Profile:** in the job and still usable.
- **Budget:** the reservation succeeds atomically.

The run is claimed with a conditional update. A retry returns the existing run's status; the model is never
called twice. The prompt is built from ClientSt0r's stored evidence only.

| Response | Body |
|---|---|
| `200` | `{"job_id", "profile_id", "status": "succeeded\|failed\|refused", "input_tokens", "output_tokens", "error"}` |
| `202` | `{… "status": "dispatched\|executing", "retry_after": 5}` — repeat the same request |
| `401` | Bad or missing signature, or nonce reused |
| `403` | `{"error": "actor_not_permitted\|profile_refused\|tenant_mismatch\|business_mismatch\|delegation_mismatch"}` |
| `404` | `job_unknown`, `profile_not_in_job` |
| `409` | `ticket_changed`, `evidence_mismatch`, `job_closed` |
| `410` | `job_expired` |
| `429` | `budget_exhausted` |

The analysis text is **not** returned to rem0te, and provider keys never are.

### `POST /api/integration/v1/events`

```json
{"job_id": "uuid", "event_id": "unique-per-job", "sequence": 3,
 "type": "job.accepted|job.running|job.completed|job.failed|job.cancelled"}
```

- A duplicate `event_id` returns `{"status": "duplicate"}`.
- A sequence that isn't higher than the last one seen is recorded but not applied (`"recorded"`).
- Events only move the job's own status. `job.completed` / `job.failed` / `job.cancelled` mark any model run that
  never happened as refused.

## Later milestones (not implemented)

Planned, in order:

1. Private RMM handoffs.
2. Bounded read-only diagnostics.
3. Remote session launch through rem0te's own authorization.
4. Fix review — only when rem0te advertises `signed_actions`. ClientSt0r only refers a fix; rem0te approves and
   runs it.

Targets will come only from verified same-business device associations (`integrations.rmm_association`), never from
a hostname or model output.
