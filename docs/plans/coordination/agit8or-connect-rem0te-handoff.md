# Agit8or Connect — proposal to Rem0te (handoff contract)

**Status: proposal from the Clientst0r side. Not sent, not agreed, and nothing on the Rem0te host has been changed.**
Clientst0r implements agit8or-connect/1 behind `AGIT8OR_CONNECT_ENABLED` (off by default). Rem0te's existing
ticket-rmm-v1 revision 2 integration (`integrations/rem0te/`, peers file, delegation JWS) is **unchanged** and
keeps working. Connect is meant to run alongside it, then replace it gradually.

Normative spec: `docs/agit8or-connect/PROTOCOL.md`. HTTP: `docs/agit8or-connect/openapi.yaml`. Vectors:
`docs/agit8or-connect/test-vectors/*.json`. SDKs: `sdk/typescript/agit8or-connect/` (Node 22, `node:crypto`
only, the natural fit for Rem0te) and `agit8or_connect/` (Python).

## 1. Tenancy: who is who

| | Clientst0r | Rem0te |
|---|---|---|
| Installation | **one MSP** per install (`installation_id` = the MSP) | one Rem0te install, possibly multi-operator |
| Top-level tenant | — (the install *is* the MSP) | **Tenant = operator** (an MSP using Rem0te) |
| Customer | `Organization`, id `org-<n>` | **Customer = business** |
| Connection | one per Rem0te (or other app) it pairs with | one per Clientst0r install, **owned by exactly one Rem0te Tenant (operator)** |
| Tenant grant | Clientst0r `org-<n>` ↔ Rem0te business id | Rem0te business ↔ Clientst0r `org-<n>`, **within that operator** |

Rules Rem0te must enforce:

1. A Connect connection belongs to exactly one Rem0te Tenant (operator), chosen by the operator admin who
   creates the invitation or starts the pairing. Its grants can only name businesses of that operator.
2. One Rem0te may be connected to several Clientst0r installs (several MSPs). Each is its own connection with
   its own keys, tokens, grants, replay records and event ids. **Two MSPs will both use `org-1`, `org-2`, …**
   Every lookup is keyed by (connection, tenant id). Never by tenant id alone, and never by operator alone.
3. `Agit8or-Tenant` on a call **from** Clientst0r carries Clientst0r's id (`org-<n>`). Rem0te resolves it through
   that connection's grants to one business. In the other direction, Rem0te sends **its** business id and
   Clientst0r resolves it through its grants.
4. A business never appears in a capability, customer list or event for a connection that lacks a grant for it.

Clientst0r tests both levels against the reference peer: customer vs customer within one connection, a
Rem0te-like receiver with two MSP installs using the same tenant ids, and two Rem0te installs on one
Clientst0r (`connect/tests/test_security.py::TenantIsolation`).

## 2. Endpoints Rem0te would serve

All on the same origin as discovery; the path prefix is Rem0te's choice (suggested `/api/connect/v1`).

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/agit8or-connect` | discovery (`app.type = "rem0te"`, catalog, events, tenant model `{"name":"business"}`) |
| `POST …/pairing/requests` | receive a pairing request (when Clientst0r initiates) |
| `POST …/pairing/requests/{request_id}/status` | signed poll → result |
| `POST …/token` | client credentials + private_key_jwt + DPoP |
| `GET …/connections/{connection_id}/jwks` | endorsed JWKS for one connection |
| `GET …/health`, `POST …/test`, `GET …/capabilities` | health and the connection test |
| `POST …/events` | signed events from Clientst0r (`connect.test`, `connect.connection.revoked`) |
| `GET …/customers`, `GET …/customers/current` | sample tenant-scoped reads (the reference peer implements these; useful for interop) |

Rem0te also needs to **call** Clientst0r's endpoints (pairing when Rem0te initiates; token; events to send
`alert.*`).

## 3. Formats (summary — PROTOCOL.md is normative)

- **Discovery**: §4. Endpoints MUST share the discovery origin.
- **Pairing request JWS** `typ agit8or-pairing-request+jwt`, header `jwk`, claims `protocol, iss, aud, iat, exp
  (≤600 s), jti, pairing_code, app{type,version,display_name,installation_id}, connection_id, discovery_url,
  connection_key, requested_scopes[], proposed_tenants[{id,label}]`. Answer is `202 {request_id, ack, status}`.
- **SAS**: §5.2. Show `NNNN-NNNN` in the Rem0te admin UI next to the approve button.
- **Client assertion** `typ client-authentication+jwt`, `aud` = exact token URL, ≤60 s, single-use `jti`.
- **Access token** `typ at+jwt`, ≤300 s, `cnf.jkt`, `iss = aud = issuer installation id`, `client_id` = the
  caller's connection id **at the issuer**.
- **DPoP** `typ dpop+jwt`, header `jwk`, `htm, htu, iat (±120 s), jti, ath`.
- **Webhooks**: headers `Agit8or-Connection / -Event-Id / -Timestamp / -Key-Id / -Signature`; signing string
  `agit8or-connect-event-v1\n{connection}\n{event id}\n{ts}\n{sender}\n{receiver}\n{sha256_hex(body)}`;
  Ed25519, b64url. Body is the canonical-JSON envelope. Duplicate `id` → `200 duplicate`.
- **Errors**: `{"error":{"code","message","correlation_id"}}`; OAuth form on the token endpoint.

Vectors to pass, all in `docs/agit8or-connect/test-vectors/`: `keys.json`, `canonical-json.json`,
`tokens.json`, `pairing.json`, `webhooks.json`, `audit-chain.json`, `jwks.json`. The TypeScript SDK's
`test/vectors.test.ts` already checks them.

## 4. Suggested Prisma models

```prisma
model ConnectInstallation {           // one row
  id              String   @id @default(uuid())   // installation_id
  displayName     String
  killSwitch      Boolean  @default(false)
  killSwitchAt    DateTime?
}

model ConnectConnection {
  id                    String   @id @default(uuid())   // Rem0te's connection id = Clientst0r's client_id
  tenantId              String                           // Rem0te operator that owns it (rule 1)
  tenant                Tenant   @relation(fields: [tenantId], references: [id])
  direction             String                           // inbound | outbound
  state                 String                           // pending_pairing | awaiting_* | active | suspended | revoked | failed
  remoteInstallationId  String
  remoteAppType         String
  remoteDisplayName     String
  remoteConnectionId    String?                          // Rem0te's client_id at Clientst0r
  baseUrl               String
  remoteEndpoints       Json
  remoteJwks            Json?
  remoteJwksFetchedAt   DateTime?
  inboundScopes         String[]
  outboundScopes        String[]
  allowPrivateNetwork   Boolean  @default(false)
  tlsCaBundle           String?
  tokensNotBefore       DateTime?
  sas                   String?
  nextRotationAt        DateTime?
  createdAt             DateTime @default(now())
  keys                  ConnectKey[]
  grants                ConnectTenantGrant[]
  @@unique([tenantId, remoteInstallationId])            // one connection per operator per MSP install
}

model ConnectKey {
  id          String   @id @default(uuid())
  connectionId String
  connection  ConnectConnection @relation(fields: [connectionId], references: [id])
  kid         String
  state       String           // staged | active | retiring | retired | failed
  publicJwk   Json
  privateKey  String           // AES-256-GCM, AAD bound to this row id; wiped when retired
  retireAfter DateTime?
  @@unique([connectionId, kid])
}

model ConnectTenantGrant {
  id             String   @id @default(uuid())
  connectionId   String
  connection     ConnectConnection @relation(fields: [connectionId], references: [id])
  customerId     String               // Rem0te business — MUST belong to connection.tenantId
  remoteTenantId String               // Clientst0r's "org-<n>"
  scopes         String[]
  active         Boolean  @default(true)
  revokedAt      DateTime?
  @@unique([connectionId, remoteTenantId])
  @@unique([connectionId, customerId])
}

model ConnectPairingInvitation { id String @id @default(uuid()); tenantId String; codeHmac String @unique;
  expiresAt DateTime; attempts Int @default(0); usedAt DateTime?; burnedAt DateTime? }
model ConnectPairingRequest { id String @id @default(uuid()); connectionId String; status String;
  resultJws String?; expiresAt DateTime }
model ConnectReplay { namespace String; key String; expiresAt DateTime; @@id([namespace, key]) }
model ConnectOutboundEvent { id String @id; connectionId String; envelope Json; status String;
  attempts Int @default(0); nextAttemptAt DateTime }
model ConnectInboundEvent { connectionId String; eventId String; type String; data Json;
  receivedAt DateTime @default(now()); @@id([connectionId, eventId]) }
model ConnectAudit { seq Int @id; record Json; prevHash String; hash String }   // append-only
```

## 5. Keep the rev2 peers.json path working

- Don't change `INTEGRATION_PEERS_FILE`, `rem0te-http-req-v1`, the delegation JWS or the ticket-rmm-v1 routes.
  Clientst0r's `integrations/rem0te/` keeps using them unchanged.
- Connect connections live in new tables. A Rem0te peer can have both at once. They don't share keys.
- Later, a Connect connection can carry the ticket-rmm-v1 flows as the `ticket_analysis:submit` profile
  (PROTOCOL.md §15). Then the peers file is no longer needed for that peer. Migrating is per peer and opt-in.

## 6. Effect on the open audit items

| Item | Effect |
|---|---|
| **R2** (unknown fields) | Resolved for Connect: unknown fields MUST be ignored everywhere (PROTOCOL.md §3). Versions are negotiated in discovery. |
| **R4** (pause reason in 423/403 bodies) | Connect errors carry only `{code, message, correlation_id}`. Suggested Rem0te `code`: `contained`, with a fixed message and no free text. |
| **R6** (remote-session confirmation) | Becomes Rem0te → Clientst0r events `remote_session.started/ended` under `events:publish` (to be added to Clientst0r's inbound event types). |
| **R7** (proposal status push) | Events `action_proposal.updated`, deduplicated by event id, instead of polling. |
| **R9** (ticket state back) | Clientst0r → Rem0te events `ticket.updated` once `tickets:read`/events are available. |
| **R11** (inference retry budget) | Connect's delivery queue retries up to 12 times with backoff over many hours. If Rem0te uses the same queue model for Clientst0r-bound calls, a Clientst0r restart no longer ends jobs. |

## 7. Work list for Rem0te (mapped to tasks)

| # | Task | Notes |
|---|---|---|
| 1 | Prisma models above + migration | `tenantId` on every connection (rule 1) |
| 2 | Discovery route | `app.type = "rem0te"`, catalog with risk tiers |
| 3 | Invitation (operator admin) + code entry for outbound pairing, SAS display, approve/reject | step-up auth; a high-risk scope needs a second admin |
| 4 | Pairing request / status endpoints | DB attempt counter, burn at 5 |
| 5 | Token endpoint + DPoP verification + replay store | use the TS SDK |
| 6 | Endorsed JWKS + rotation job | old key kept active when validation fails |
| 7 | Tenant resolution via grants | always keyed by (connection, tenant id) |
| 8 | Events in and out, queue with backoff, dead letter | send `alert.*` to Clientst0r |
| 9 | Kill switch, suspend, revoke, per-business revoke | keep data |
| 10 | Hash-chained audit | `audit-chain.json` vector |
| 11 | Pass every vector file | CI |
| 12 | Interop run (§8) | |

## 8. Interop test plan

Run against a Clientst0r dev install with `AGIT8OR_CONNECT_ENABLED=True` (never prod), on a private network
with a private CA:

1. Rem0te → Clientst0r pairing (code typed in Rem0te). Both SAS equal, both admins approve, test passes.
2. Clientst0r → Rem0te pairing (Rem0te code typed in Clientst0r). Same checks.
3. Rem0te calls `GET /connect/v1/customers/current` for a granted business, then for an ungranted one (403).
4. **Two MSPs**: a second Clientst0r dev install pairs with the same Rem0te operator, or with another one.
   Both use `org-1`. Each reaches only its own mapped business, and a token from one is refused for the other.
5. **Two operators**: two Rem0te operators each paired with the same Clientst0r. Neither sees the other's businesses.
6. `alert.raised` from Rem0te accepted. The same event id resent gives `duplicate`.
7. Rotation on each side, then a forced failure (block the JWKS route) leaves the old key working.
8. Revoke a single customer grant, then the whole connection. Calls fail at once and data stays.
9. Kill switch on each side. Release it, and connections stay suspended until resumed.
10. Clock skew of 3 minutes produces a clear `expired`. Replayed DPoP and assertion give `replayed`.
11. ticket-rmm-v1 rev2 flows (analysis job, alert to ticket) still pass `scripts/e2e/cross_peer/` throughout.
