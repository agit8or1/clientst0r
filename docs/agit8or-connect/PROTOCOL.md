# Agit8or Connect — protocol `agit8or-connect/1`

Status: **draft 1, Phase 1 implemented in Clientst0r** (behind `AGIT8OR_CONNECT_ENABLED`, off by default).
No other application implements it yet. Machine-readable surface: [`openapi.yaml`](openapi.yaml). Byte-exact
examples: [`test-vectors/`](test-vectors/). Reference SDKs: `agit8or_connect/` (Python) and
`sdk/typescript/agit8or-connect/` (TypeScript, `node:crypto` only).

Agit8or Connect is a self-hosted way for two applications to trust each other: no central service, no shared
secret typed into two screens. Each pair of installations creates a **connection** with its own keys. The
administrators on both sides approve what each side may do and which customers it may reach.

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

Protocol revision **1.1** (optional Quick Connect extensions `qc-bootstrap/1`, `qc-source-binding/1`,
`qc-diagnostics/1`) is specified separately in [PROTOCOL-1.1.md](PROTOCOL-1.1.md). It is additive and negotiated:
nothing in this document changes, and a peer that implements only this document keeps working.

## 1. Terms

| Term | Meaning |
|---|---|
| Installation | One running deployment of an application. It has a stable `installation_id` (UUID). |
| Connection | A trust relationship between two installations. Each side stores its own row and its own UUID for it. Each side's id is the *other* side's `client_id`. |
| Initiator / responder | During pairing: the side that enters the code / the side that issued it. After pairing the connection is symmetric. |
| Tenant | A customer scope in one application (Clientst0r: a customer organization, id `org-<n>`). |
| Tenant grant | A mapping, on one side, from a local tenant to the other side's tenant id, with the scopes allowed for it. |
| Scope | A named permission with a risk tier (§7). |

**Clientst0r tenancy.** One Clientst0r installation serves exactly one MSP. Its `installation_id` *is* the MSP
identity. Its tenants are that MSP's customers. A receiving application that connects to several Clientst0r
installations is connected to several MSPs and MUST keep their connections, grants and data fully apart (§8.3).

## 2. Cryptography

Only established primitives, from standard libraries (Python `cryptography` + PyJWT; Node `node:crypto`):

- Signatures: **Ed25519** (JWS `alg` `EdDSA`, RFC 8037). No other algorithm is accepted; `none` and HMAC are refused.
- Hashes: SHA-256.
- Key ids: the RFC 7638 JWK thumbprint (base64url SHA-256 of `{"crv","kty","x"}`).
- Canonical JSON (for anything hashed or signed as JSON): keys sorted by UTF-16 code units, no whitespace,
  JavaScript number and string serialisation (identical to `JSON.stringify` of a key-sorted value). Integers
  beyond ±2^53−1 and non-finite numbers are refused. Vectors: `test-vectors/canonical-json.json`.
- JWS: compact serialisation. Every JWS has `typ`. Header and payload are canonical JSON, so both SDKs produce
  the same bytes for the same input (`test-vectors/tokens.json`).
- Private keys at rest (Clientst0r): AES-256-GCM via the vault envelope, with associated data bound to the table,
  column **and row**: `connect.ConnectionKey.private_key#<row uuid>`. A ciphertext copied to another row does not decrypt.

## 3. Versioning and forward compatibility

- The discovery document lists `versions` (today `["1"]`). The initiator picks the highest common version.
  Without a common version, pairing fails with `unsupported_version`.
- **Unknown fields MUST be ignored**, in JSON bodies, JWS payloads and headers (except `crit`, which is refused),
  discovery documents and events. This resolves the ticket-rmm-v1 audit item R2: a peer on a newer minor
  revision never breaks an older one. Removing or changing the meaning of a field needs a new major version.
- Unknown scopes in a request are reported to the administrator and never granted. Unknown event types are
  answered `403 event_type_not_allowed`.

## 4. Discovery

`GET {base}/.well-known/agit8or-connect` → `200 application/json`:

```json
{
  "protocol": "agit8or-connect",
  "versions": ["1"],
  "app": {"type": "clientst0r", "version": "3.17.690", "display_name": "Example MSP",
          "installation_id": "6b1f…"},
  "endpoints": {
    "pairing": "https://psa.example.com/connect/v1/pairing/requests",
    "pairing_status": "https://psa.example.com/connect/v1/pairing/requests/{request_id}/status",
    "token": "https://psa.example.com/connect/v1/token",
    "jwks": "https://psa.example.com/connect/v1/connections/{connection_id}/jwks",
    "health": "…/connect/v1/health", "capabilities": "…/connect/v1/capabilities",
    "events": "…/connect/v1/events", "test": "…/connect/v1/test", "api_base": "…/connect/v1"
  },
  "capabilities": [{"name": "customers:read", "risk": "read", "description": "…", "available": true}, …],
  "events": ["connect.test", "connect.connection.revoked"],
  "tenant_model": {"name": "organization", "description": "…"},
  "security": {"token_auth": ["private_key_jwt"], "token_type": "DPoP", "alg": ["EdDSA"],
               "access_token_max_lifetime": 300, "webhook_signature": "ed25519"},
  "msp": {"single_msp_installation": true}
}
```

Rules for the fetching side:

- HTTPS only. TLS 1.2 or newer, certificates always verified. A private CA bundle MAY be configured per
  connection. It then **replaces** the system CAs for that connection.
- No redirects, no proxies. Response size capped (2 MiB).
- Every endpoint MUST have the same origin (scheme, host, port) as the discovery URL. A document pointing
  anywhere else is refused as a whole. This stops a discovery document from steering requests to internal addresses.
- The destination IP is checked **at connect time**, after DNS resolution, which defeats DNS rebinding.
  Loopback, link-local, cloud-metadata (169.254.169.254, fd00:ec2::254, …), multicast and unspecified addresses
  are always refused. Private ranges (RFC 1918, ULA, CGNAT) are refused unless an administrator enabled
  "private network" for this connection.

## 5. Pairing

Pairing creates the connection. It proves possession of each side's connection key and gives both
administrators a short code to compare against a man in the middle. Nothing is usable until **both**
administrators have approved.

### 5.1 Invitation code

The responder's administrator creates an invitation:

- Code: 10 Crockford base32 characters shown as `XXXXX-XXXXX` (50 bits). Input is normalised: case-folded,
  `O→0`, `I/L→1`, separators removed.
- Single use. Valid **10 minutes**.
- Stored only as `HMAC-SHA256(pepper, "agit8or-connect/1 pairing-code\n" + normalised)`. The pepper is
  derived from the server secret, so a database dump alone does not allow offline guessing.
- Every wrong code counts against **every open invitation**. After **5** failures they all burn and the
  responder answers `pairing_locked` (HTTP 403) until an administrator creates a new code. With the code space
  at 2^50, an attacker gets at most 5 guesses per code, a success chance of about 5·2^-50.
- Pairing endpoints are also rate-limited per IP and globally.

QR form (optional, for the initiator's own UI): `agit8or-connect:pair?v=1&url=<discovery url>&code=<code>&id=<installation id>`.
The identity is still verified by discovery; the QR only saves typing.

### 5.2 Messages

```
Initiator                                                Responder
  │ GET /.well-known/agit8or-connect ──────────────────────▶ │   (verify identity, show installation id)
  │ POST pairing  {"request": <request JWS>} ─────────────▶ │   code checked, request stored
  │ ◀──────────── 202 {"request_id", "ack": <ack JWS>}       │
  │   both compute transcript hash → SAS NNNN-NNNN          │   admin compares SAS, approves scopes + customers
  │ POST pairing_status {"proof": <poll JWS>} ────────────▶ │
  │ ◀──────────── 200 {"status":"pending"} | {"status", "result": <result JWS>}
  │   admin compares SAS, approves scopes + customers (initiator side)
  │ (connection active on both sides; either side can now obtain tokens)
```

**Request** (`typ agit8or-pairing-request+jwt`). The header carries `jwk` (the initiator's new connection
public key) and is signed with that key:

| claim | |
|---|---|
| `protocol` | `"agit8or-connect/1"` |
| `iss` / `aud` | initiator / responder `installation_id` |
| `iat`, `exp` | lifetime ≤ 600 s |
| `jti` | unique. The responder keeps it to refuse replays. |
| `pairing_code` | the code as typed |
| `app` | `{type, version, display_name, installation_id}`. `installation_id` MUST equal `iss`. |
| `connection_id` | the initiator's UUID for this connection (becomes the responder's `client_id` when it calls the initiator) |
| `discovery_url` | where the responder can look the initiator up |
| `connection_key` | the same JWK as the header. Its thumbprint MUST match the signing key. |
| `requested_scopes` | what the initiator asks to do at the responder |
| `proposed_tenants` | `[{id, label}]`: the initiator's tenants it offers, so the responder's admin can map them |

The responder MUST NOT fetch anything from `discovery_url` when the request arrives, because the request comes
from an unauthenticated code holder. It fetches only when its administrator opens or approves the request.

**Ack** (`typ agit8or-pairing-ack+jwt`, header `jwk` = the responder's new connection key, signed by it):
`iss`, `aud`, `request_id`, `request_jti`, `connection_id` (the responder's UUID), `app`, `connection_key`,
`status: "pending_approval"`.

**Transcript hash and SAS.** Both sides compute these independently:

```
transcript = sha256_hex(canonical({
  "v": "agit8or-connect/1 pairing-transcript",
  "request_sha256": sha256_hex(<request JWS as sent>),
  "request_jti": …,
  "initiator": {"installation_id": …, "jkt": <thumbprint>},
  "responder": {"installation_id": …, "jkt": <thumbprint>}}))
SAS = first 8 bytes of sha256("agit8or-connect/1 sas\n" + transcript) as big-endian integer mod 10^8, shown NNNN-NNNN
```

Both UIs show the SAS. Administrators approve only if the two codes match. A substituted key on either side
changes the SAS.

**Poll proof** (`typ agit8or-pairing-poll+jwt`): signed with the initiator's connection key; `iss`, `aud`,
`iat`, `exp` (≤120 s), `jti` (single use), `request_id`. Only the holder of the initiator key learns the outcome.

**Result** (`typ agit8or-pairing-result+jwt`), signed with the responder's connection key: `status`
(`approved`/`rejected`), `request_id`, `request_jti`, `connection_id`, `granted_scopes` (what the initiator may
do at the responder), `tenant_grants` (`[{remote_tenant, local_tenant, scopes}]` from the responder's point of
view), `requested_scopes` (what the responder asks to do at the initiator), `endpoints`.

### 5.3 Approval on each side

Each administrator approves only scopes that are **in their own catalog, available, and requested by the
peer**. Each administrator also maps every customer explicitly. A customer is reachable only through an active
tenant grant on the side that owns it. `high_risk` and `admin` scopes need a second administrator (§7.3).

### 5.4 Statuses

`pending` → `approved` / `rejected` / `expired`. A connection that never completes stays `pending_pairing` or
`awaiting_*` and is shown as such. A rejected or expired pairing wipes its keys.

## 6. Tokens

### 6.1 Token request (OAuth 2.1 client credentials, `private_key_jwt`, DPoP)

```
POST {token}
Content-Type: application/x-www-form-urlencoded
DPoP: <DPoP proof for POST {token}>

grant_type=client_credentials
&client_id=<the issuer's connection UUID>
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<JWS>
&scope=<space-separated, optional — defaults to everything granted>
```

Client assertion (`typ client-authentication+jwt`, RFC 7523): `iss` = `sub` = `client_id`, `aud` = the exact
token endpoint URL, `iat`, `exp` (lifetime ≤ 60 s), `jti` (single use; replays are refused with `replayed`). It is
signed with the caller's active or retiring connection key, and the header `kid` names that key.

The DPoP proof (RFC 9449) MUST be signed with the same key as the assertion. The token is bound to that key.

Response `200`:

```json
{"access_token": "<JWS>", "token_type": "DPoP", "expires_in": 300, "scope": "connection:read customers:read"}
```

Requesting a scope that is not granted gives `400 invalid_scope`. It is never silently narrowed.

### 6.2 Access token (`typ at+jwt`)

`iss` = `aud` = the issuer's `installation_id`; `sub` = `client_id` = the caller's connection id at the issuer;
`scope`; `iat`, `exp` (≤ 300 s); `jti`; `cnf.jkt` = thumbprint of the caller's key. Tokens are self-contained
but are checked against the live connection on every use. A token issued before a suspension, revocation or
rotation-reset (`tokens_not_before`) is refused.

### 6.3 Calling a resource

```
Authorization: DPoP <access token>
DPoP: <proof: htm, htu (scheme+host+path, no query/fragment), iat ±120 s, jti single-use, ath = b64url(sha256(token))>
Agit8or-Tenant: <tenant id in the CALLER's namespace>     (tenant-scoped routes)
```

`Bearer` tokens are refused. A token presented with a proof from another key is refused, so a stolen token is
useless without the private key.

### 6.4 Key discovery

`GET {jwks}` with `{connection_id}` = the **publisher's** connection UUID returns:

```json
{"keys": [<public JWKs: active, retiring, staged>],
 "endorsement": "<JWS typ agit8or-jwks+jwt: {iss, sub=connection id, keys_sha256, iat, exp}>"}
```

The endorsement is signed by a key the fetcher already trusts for this connection. A JWKS with a missing,
stale or unknown-key endorsement is refused as a whole. A fetcher re-reads it at most once a minute, only when
it sees an unknown `kid`. A JWKS fetched without an endorsement chain never adds trust.

## 7. Scopes, risk tiers and approval

### 7.1 Tiers

| Tier | Meaning | Approval |
|---|---|---|
| `read` | reads data of granted customers | one administrator |
| `write` | creates or changes data | one administrator |
| `high_risk` | affects endpoints or security (e.g. remote actions) | **second administrator** (protected change); never in the default set |
| `admin` | changes the connection or the other installation's settings | **second administrator**; never in the default set |

### 7.2 Clientst0r's catalog (Phase 1)

| Scope | Tier | Available |
|---|---|---|
| `connection:read` | read | yes |
| `customers:read` | read | yes |
| `events:publish` | write | yes (event types `connect.test`, `alert.raised`, `alert.updated`, `alert.resolved`) |
| `assets:read`, `tickets:read` | read | planned |
| `tickets:write` | write | planned |
| `ticket_analysis:submit` | write | planned (transitional ticket-rmm-v1 profile, §13) |
| `remote_actions:execute` | high_risk | planned. Each action will also need its own approval. |
| `connection:admin` | admin | planned |

A scope advertised `available: false` is refused at approval time.

### 7.3 Second-administrator approval

When an approval includes a `high_risk` or `admin` scope, the connection waits in `awaiting_second_approval`.
A protected change (kind `app_connection`) is opened in Settings → Security → Technician Access. The proposer
re-authenticates and confirms. A **different** administrator approves. The approval is refused if the scopes or
grants changed since the proposal (fingerprint check). The peer sees `pending` until then.

## 8. Tenants

### 8.1 Grants

A tenant grant on side A says: "A's tenant T is reachable through this connection, under the peer's tenant id
R, with these scopes." Requests name the tenant with `Agit8or-Tenant: R`, which is the **caller's** id. The
receiver resolves R only through its own active grants **for this connection**. Unknown, revoked or ungranted
ids get `403 tenant_not_granted`. An id that happens to be the receiver's own tenant id is never accepted as-is.

### 8.2 Scope per grant

The effective permission for a tenant-scoped call is `token scope ∩ grant scopes`.

### 8.3 Multiple installations

A receiver connected to several installations MUST key every lookup by (connection, tenant). Two MSPs (two
Clientst0r installations) may use the very same tenant ids (`org-1`, …), and a Rem0te-like receiver connected to
both MUST still resolve each to its own business. Tokens, keys, grants, event ids and replay records are all per
connection. Covered by `connect/tests/test_security.py::TenantIsolation` and
`agit8or_connect/tests/test_reference_peer.py`.

## 9. Events (webhooks)

`POST {events}`, body = canonical JSON envelope (≤ 1 MiB):

```json
{"id": "<uuid>", "type": "alert.raised", "version": 1, "tenant": "<receiver's grant id for the customer>",
 "data": {…}, "sender": "<sender installation>", "origin": "<first sender>", "correlation_id": "…",
 "causation_id": "", "hops": 0, "idempotency_key": "<uuid>", "occurred_at": 1767225600}
```

Headers:

```
Agit8or-Connection: <receiver's connection UUID (the sender's client_id there)>
Agit8or-Event-Id:   <envelope id>
Agit8or-Timestamp:  <unix seconds>                ±120 s
Agit8or-Key-Id:     <sender key thumbprint>
Agit8or-Signature:  b64url(Ed25519(signing string))

signing string = "agit8or-connect-event-v1\n" + connection + "\n" + event id + "\n" + timestamp + "\n"
                 + sender installation + "\n" + receiver installation + "\n" + sha256_hex(body)
```

Receiver rules:

- Verify the signature with the connection's keys. Check the time window, and that `id` and `sender` match
  the headers.
- The sender needs `events:publish`, the event type must be allowed, and the tenant must be granted.
  **Connection-level events** (`connect.test`, `connect.connection.revoked`) have an empty `tenant` and are
  accepted from any active connection without `events:publish`. Receiving `connect.connection.revoked` revokes
  the connection on the receiving side too (records kept).
- A repeated `id` returns `200 {"status": "duplicate"}` and changes nothing (idempotent).
- Loop guard: `origin == receiver` or `hops ≥ 4` returns `200 {"status": "ignored_loop"}`. A forwarder increments `hops`.
- `2xx` means accepted. Statuses the sender treats as permanent (e.g. 400, 403, 404, 410, 413) go to the dead-letter list at once; everything else is retried.

Sender rules: a durable queue; exponential backoff with jitter (30 s base, 1 h cap); dead letter after 12
attempts; nothing is sent while suspended or while the kill switch is on.

These are local sender rules and never appear on the wire. Clientst0r's revision (editorial, no version change):
only attempts that reached the receiver count towards the 12; while the receiver is unreachable (connection
Offline, circuit open) events wait without spending attempts; events also become dead letters by age (default 7
days); the queue drains in creation order once the receiver is back; an administrator can requeue a dead letter
with its original `id`, which the receiver still deduplicates.

## 10. Health and test

- `GET {health}`: unauthenticated `{status, protocol, installation_id, time}`. With a DPoP token it also returns the connection state.
- `POST {test}` (any valid token): `{ok, connection_id, scopes, protocol, time}`. With `Agit8or-Tenant` it
  also reports whether that tenant is granted (`granted` / an error code).
- `GET {capabilities}` (`connection:read`): the scopes granted, the event types and the tenant grants for **this
  connection only**.

Clientst0r's **Test connection** button checks, and reports pass or fail for each:

1. Discovery: identity unchanged and protocol compatible.
2. Authentication: a token obtained.
3. Permissions: everything requested was granted.
4. Customer mapping: capabilities read.
5. Event delivery: a signed `connect.test` accepted.

## 11. Rotation

1. Stage a new key and publish it in the endorsed JWKS (endorsed by the current active key).
2. Validate: obtain a token signed with the new key. The peer must fetch the JWKS and accept the endorsement.
3. On success: new → `active`, old → `retiring` (still accepted for the overlap, default 24 h), then `retired`.
   A retired key's private half is wiped.
4. On failure: new → `failed` (private half wiped), the old key stays active, the error is shown, and a retry is
   scheduled in 6 h.

Scheduled rotation runs every hour (default interval 90 days per connection, configurable 7–365).

## 12. Suspension, revocation, kill switch

| Action | Effect |
|---|---|
| Suspend | No tokens issued, existing tokens refused (`tokens_not_before`), nothing delivered. Resume restores it. |
| Revoke grant | That customer is unreachable at once, in both API calls and events. |
| Disconnect | A best-effort signed `connect.connection.revoked` event to the peer, then revoke. |
| Revoke | Immediately: state `revoked`, keys wiped, grants inactive, queued events cancelled. **Customer records, events and audit history are kept.** |
| Kill switch | Every API call is answered `503 kill_switch` (discovery and health still answer). All active connections are suspended. Releasing it does not resume them. Available in the UI and as `manage.py connect_kill_switch`. |

## 13. Errors

```json
{"error": {"code": "<code>", "message": "<human text, no secrets>", "correlation_id": "<uuid>"}}
```

The token endpoint answers in OAuth form instead: `{"error": "<code>", "error_description": "…"}` with codes
`invalid_client`, `invalid_grant`, `invalid_scope`, `invalid_request`, `replayed`, `rate_limited`. 401 responses on resources carry `WWW-Authenticate: DPoP error="…", algs="EdDSA"`.

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_request` | 400 | malformed |
| `invalid_client` | 401 | assertion bad, connection unknown/inactive |
| `invalid_token` / `invalid_dpop_proof` / `expired` / `replayed` | 401 | |
| `invalid_signature` | 401 | JWS or webhook signature |
| `insufficient_scope` | 403 | |
| `tenant_not_granted` | 403 | |
| `event_type_not_allowed` | 403 | |
| `invalid_pairing_code` | 400 | wrong/expired/used code |
| `pairing_locked` | 403 | too many wrong codes |
| `not_found` | 404 | |
| `too_large` | 413 | |
| `rate_limited` | 429 | with `Retry-After` |
| `kill_switch` | 503 | |
| `unsupported_version` | 400 | |
| `blocked_destination` | — | client-side SSRF refusal (never on the wire) |

## 14. Audit

Every security-relevant operation is recorded: pairing, approval, token issue/deny, resource calls, events,
rotation, revocation, kill switch. Each record holds time, connection, initiating app, tenant, actor, operation,
scopes, result and correlation id. It never holds a token, assertion, code, signature or key. Records form a
hash chain:

```
hash_n = sha256_hex(canonical({"prev": hash_{n-1}, "record": record_n}))     hash_0.prev = "0"*64
```

The table is append-only in the ORM. `manage.py connect_verify_audit_chain` recomputes the chain and reports
the first changed, missing or reordered entry.

## 15. Transitional profile: ticket-rmm-v1

ticket-rmm-v1 (Rem0te revision 2: HMAC or Ed25519 request signatures, `peers.json`, delegation JWS) keeps
working unchanged in `integrations/rem0te/`. Connect runs alongside it. The mapping, for a later migration:

| ticket-rmm-v1 | agit8or-connect/1 |
|---|---|
| peers file entry / `Rem0teIdentity` keys | connection keys from pairing, rotated with §11 |
| `rem0te-http-req-v1` request signature | DPoP-bound access token + proof |
| delegation JWS `sub = tech-<id>` | planned Phase 2 actor claim (`act`) inside the access token; per-action approval for `high_risk` |
| `org = org-<id>` | `Agit8or-Tenant` + tenant grant |
| `rem0te-event-v1`, `rem0te-alert-event-v1` | §9 events (`alert.raised` …) |
| analysis jobs + inference callback | scope `ticket_analysis:submit` (planned) |
| capabilities `signing_keys` | endorsed JWKS |

During the transition, one Rem0te MAY hold both a ticket-rmm-v1 pairing and a Connect connection for the same
Clientst0r. They are independent: revoking one does not affect the other.

## 16. Threat model

| Threat | Mitigation |
|---|---|
| Guessing a pairing code | 50-bit code, 10 min, single use, 5 failures burn all open codes, IP + global rate limits, HMAC-peppered storage |
| Man in the middle at pairing | TLS + discovery identity + the request signed by the announced key + SAS compared by both admins |
| Rogue code holder pairs | Needs both admins' approval; nothing is reachable without explicit grants |
| SSRF via discovery / endpoints | Same-origin endpoints, connect-time IP checks, metadata always blocked, no redirects or proxies, discovery only on admin action |
| Stolen access token | 300 s lifetime, DPoP binding, `tokens_not_before` |
| Replay (assertion, DPoP, poll, pairing request, event) | `jti`/event-id stores with expiry. Events are idempotent. |
| Cross-tenant access within a connection | Grants per connection, resolution in the caller's namespace, scope ∩ grant scope |
| Cross-installation (two MSPs) | Everything keyed by connection; tokens are bound to `client_id` and `cnf.jkt` |
| Key compromise | Rotation, revoke, kill switch; private keys encrypted with row-bound AAD |
| Privilege escalation | High-risk/admin need two admins. Unavailable scopes are refused. Tokens are never broader than grants. |
| Event loops | `origin` and `hops` guard |
| Audit tampering | Hash chain, append-only model, verify command |
| Secret leakage | Audit detail scrubbing; tests scan logs, API responses and admin pages for codes, tokens and keys |
| Disabled TLS | No code path sets `verify=False`, `CERT_NONE` or `check_hostname=False`; a test enforces it |
| Downgrade | Only EdDSA accepted; `typ` checked for every JWS; only version 1 offered |

Out of scope for Phase 1: a compromised administrator account (mitigated by two-person approval for high-risk
grants), and compromise of the host's master key.

## 17. Later phases (design notes, not implemented)

- **Phase 2: Rem0te profile.** Actor claims (`act: {sub: "tech-<id>"}`) in access tokens for delegated technician
  calls. Per-action approval for `remote_actions:execute`. Scopes `assets:read`, `tickets:*`,
  `ticket_analysis:submit` become available. Events for action-proposal status (R7), remote-session
  confirmation (R6) and ticket state back (R9).
- **Phase 3: more applications** (Office Unbound, ExploitHound, MailThreatZero, Roots-HQ, m0nitor, MyAppDone):
  catalogs and event types per app, plus event forwarding with `origin`/`hops`.
- **Phase 4: operations.** Shared rate-limit store, inbound mTLS, signed exports of the audit chain,
  connection health dashboards and alerting on repeated auth failures.
