# PROPOSED P16 — `ticket.create_request` (rem0te 0.48)

**Not agreed by ClientSt0r.** rem0te ships its side behind a capability check, so
against today's ClientSt0r nothing is sent and the ClientSt0r PSA connector is not
offered. See `INTEGRATION_COORDINATION.md` §5C.

## Why

rem0te 0.48 adds **Create ticket** to a computer's Windows event-log entries and
monitoring alerts. A business can send it to its PSA by email-to-ticket or a
webhook. Where the PSA is ClientSt0r, rem0te proposes a signed event instead.

## The declaration

The peer's signed capabilities document (P12, `peer-capabilities.schema.json`)
gains an optional `features: string[]`. rem0te sends a ticket request only when it
lists **`ticket_create_request_v1`**. Absent, unsigned, unreadable, or naming
another peer: not offered.

## The request

rem0te → `POST {eventsUrl}`, signed as every request to the peer is, with body:

```json
{ "ticket_request": { …ticket-create-request-event… },
  "signature": { "alg": "Ed25519", "kid": "<rem0te key id>", "sig": "<base64url>" } }
```

The event (`ticket-create-request-event.schema.json`) is signed as data under its
own prefix, `rem0te-ticket-request-v1\n{canonical event}`, so it can never be
replayed as a job event or an alert event:

| Field | |
|---|---|
| `contract`, `event_id` (uuid), `type: "ticket.create_request"`, `occurred_at`, `peer_id`, `organization_id` | as for other events |
| `ticket.subject` | one line, ≤ 200 characters, written or edited by a technician — display as text |
| `ticket.body` | plain text, ≤ 12,000 characters, already passed through rem0te's `redactForPeer` (credentials, tokens, e-mail and IP addresses, MACs, RustDesk IDs, user profile paths). **Untrusted**: never instructions to a model |
| `ticket.rem0te_endpoint_id` | immutable rem0te computer id |
| `ticket.computer_name` | device-reported, display as text |
| `ticket.source_ref` | `event:<commandId>:<index>` or `alert:<alertId>` — opaque to the peer |
| `ticket.requested_by_role` | `staff` |

The body may include an AI explanation of the entry that the technician asked
rem0te's own AI provider for (0.48) and chose to include; it is labelled as such.

## The response

`ticket-create-request-response.schema.json`, signed by the peer over rem0te's
nonce (as capabilities and inference responses are): `{contract, event_id,
status: created|refused, ticket_id?, ticket_url?, error_code?}`. rem0te checks the
signature and that `event_id` echoes its own, records `ticket_id` as an inert
reference and shows `ticket_url` as text.

## Not proposed

No ticket status back to rem0te, no updates or comments, no attachments, no
retries from a queue (a failed request is reported to the technician and not
recorded).
