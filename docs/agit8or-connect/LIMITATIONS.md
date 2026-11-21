# Agit8or Connect — known limitations (Phase 1)

What is **not** done or not proven yet. Keep this list current. Don't describe anything here as shipped.

## Not implemented

- **No peer application implements the protocol yet.** Rem0te support is a proposal
  (`docs/plans/coordination/agit8or-connect-rem0te-handoff.md`). The catalog shows Rem0te as
  "Available — needs a Rem0te release with Agit8or Connect support (not yet released)". Every other app is "Planned".
- **Off by default.** `AGIT8OR_CONNECT_ENABLED=False` makes every Connect route and page answer 404.
  `AGIT8OR_CONNECT_PUBLIC_URL` (the externally reachable absolute https address) is **required** for pairing:
  without it the invitation and Connect Application pages show an error, and creating an invitation, starting
  a pairing or approving a request is refused server-side. Connect never sends a relative URL to another
  application.
- **Only superusers by default.** The new role permissions `view_app_connections` and
  `manage_app_connections` (MSP staff only) are off for every role, built-in ones included. Grant them in a role
  to let other staff see or manage connected applications.
- **Only three scopes are available**: `connection:read`, `customers:read`, `events:publish`.
  `assets:read`, `tickets:read`, `tickets:write` and `ticket_analysis:submit` (the transitional ticket-rmm-v1
  profile) are advertised as unavailable. So are `remote_actions:execute` (high risk) and `connection:admin`.
  Approving any of them is refused.
- **Inbound events are stored, not acted on.** `alert.raised` etc. are verified, deduplicated and recorded
  against the granted customer, but no ticket is opened from them yet. The ticket-rmm-v1 path still does that.
- **Per-action approval** for high-risk actions (each remote action approved separately) is designed but not
  built. Granting a high-risk scope already needs a second administrator.
- **Actor (technician) claims** in tokens: planned Phase 2. Connect tokens act as the installation, not as a user.
- **Inbound mTLS** is left to the reverse proxy. An outbound client certificate per connection is stored (key
  encrypted) and loaded into an in-memory TLS context per request: the CA bundle from memory, the client
  certificate and key through an anonymous in-memory file (Linux `memfd_create`) that is never linked into a
  directory and disappears with the process. Python's `ssl` module cannot take a private key from a string, so
  where memfd is unavailable a 0600 file in a private 0700 directory (`AGIT8OR_CONNECT_RUNTIME_DIR`, else the
  temp dir) is used and removed in `finally`; a start-up sweep removes what a killed worker left behind. A
  pure-memory path without any file descriptor would need a different TLS client. The outbound mTLS handshake
  is covered by a local test server (`connect/tests/test_increment_a.py::MtlsKeyNeverOnDisk`), not yet by a
  real peer.
- **Outbound destinations are pinned** (increment B2, QC-05). Every connection reaches the other application only
  at its approved destination (Connected Applications → connection → Destination): host, port, approved addresses
  (exact IPs, or ranges up to IPv4 /24 and IPv6 /48), trust anchor (system CAs, or only the connection's private
  CA), optional SPKI pins, expected installation id. Every address the name resolves to, and the connected peer,
  must be in the approved set, otherwise nothing is sent; loopback, link-local and metadata addresses can never
  be approved, private ones only explicitly. A certificate that does not name the host (or the IP of an
  IP-literal destination) is refused. A changed address, an SPKI mismatch or a certificate name mismatch moves
  an active connection to **Security Blocked** with the evidence; it does not retry. An administrator approves
  the new address (a staged change; a second administrator for a private address or a range) and the
  connection is active again only after a retest passes. Limits:
  - the pairing preview resolves the name and makes one TLS handshake (no HTTP request) before anything is
    approved; discovery during pairing is pinned to the addresses just shown;
  - a peer behind a CDN or round-robin DNS needs its whole range approved (at most /24 or /48), or it will be
    blocked whenever DNS rotates to an unlisted address;
  - connections that existed before B2 get a staged destination from their address with **no approved IP**:
    they send nothing (events stay queued, not counted as attempts) until an administrator approves the
    addresses;
  - SPKI pins are compared after the handshake, so a pin mismatch is detected before any request bytes, but the
    TLS handshake itself happened;
  - the reference transport in the SDK (`MinimalGuardedTransport`) has no approved-destination store; it now
    always refuses loopback, link-local, unspecified and metadata addresses and opens only RFC1918, CGNAT and
    ULA ranges when private networks are allowed (`allow_loopback_http` no longer permits anything).
- **Connect endpoints are default-deny by source address** (increment B1, QC-01). Once
  `AGIT8OR_CONNECT_ENABLED` is on, every Connect endpoint (discovery, health, pairing, token, JWKS, events,
  capabilities, test, customers) refuses every source address with `403 source_not_authorised` until an
  administrator allows it, at **both** the installation layer and the layer of the connection the request is for.
  A valid token never skips this. Rules are managed under Connected Applications → Network (staged, previewed,
  widening needs a second administrator; rollback only narrows) and from the server with
  `manage.py connect_source_rules`. The REST API access policy no longer applies to Connect. Limits:
  - the address is only as trustworthy as the trusted-proxy configuration (`TRUSTED_PROXY_CIDRS` and the managed
    proxies); behind a CDN the CDN must be listed as a trusted proxy;
  - `source_not_authorised` is a new local error code; v1 peers treat it as an opaque refusal (no wire change);
  - two installations behind one NAT address are told apart only by their keys (the binding check after
    authentication refuses a request whose key holder is not the connection the address matched);
  - an invitation code and an outbound pairing need the other application's exact source address; ranges can be
    added afterwards as a reviewed change. The pairing address becomes the connection's rule when the pairing is
    approved by the same administrator (no second administrator for that step);
  - match counters are written at most once a minute per worker.
- **Observe period for connections that existed before B1.** The migration lists the connections that were active
  or suspended at upgrade time and starts a **14-day observe period** only if there are any (no production
  installation had one). During it, authenticated requests of those connections from unlisted addresses are let
  through and the address is recorded on the connection ("Approve observed address", a reviewed change); new
  pairings and other connections are enforced. It cannot be extended, the Network page shows the end date, an
  administrator can end it early (**Enforce now**), and start and end are in the audit chain. Installations that
  had no Connect connection enforce from the start.
- **Connections show Connected as soon as both sides approve**, before a connection test (QC-07, planned).
- **Rate limits use the Django cache.** With the default local-memory cache they are per gunicorn worker. The
  buckets are keyed by source address and connection, and only allowlisted sources reach them (QC-13 is bounded
  by the allowlist, not fixed). The brute-force limit on pairing codes is durable (database).
- **Unauthenticated refusals are aggregated.** A token request for no or an unknown connection, and a wrong
  pairing code, are counted in the API access refusal log (one row per source and reason per minute, endpoint
  group `connect_api`) and summarised into the Connect audit chain as at most one `refusals.summary` record per
  minute (by the `connect_deliver_events` task). The chain therefore shows totals for those, not each request.
  Refusals for a known connection, and the lock-out of open invitations, are still recorded one by one.
- **Wrong pairing codes** count only against the invitations whose address the request came from; strangers
  cannot reach the pairing endpoint at all (QC-02, contained by B1).
- **Event delivery is scheduled** (every minute through `connect_deliver_events`), apart from the connection
  test and disconnect notices, which are sent immediately.
- **Protocol revision 1.1 (Quick Connect) is specified and in the SDKs only.** `PROTOCOL-1.1.md`, the
  `qc-*.json` vectors, the Python and TypeScript functions and the in-memory reference peer implement it;
  Clientst0r does not advertise or serve any 1.1 extension yet (bootstrap pages and `qc_exchange` come with
  increment C2, `qc_probe` with E). The reference peer has no real source-address policy beyond the temporary
  rule on `qc_exchange`, and the TypeScript SDK has no reference peer. Not tested against an independent
  implementation.
- **QR scanning** is not implemented on Clientst0r's side (it only shows a QR). The SDKs parse the QR payload.
- **Phases 3–5** (other applications' catalogs, event forwarding between more than two apps, shared rate-limit
  store, signed audit exports, health alerting) are design notes only.

## Operational notes

- The kill switch also blocks approvals: approving an inbound request, approving at our end, and applying a
  pending second-administrator change for a connected application are all refused while it is engaged.
  Releasing it does not activate anything; approve again afterwards.
- An inbound request claiming the installation id of an application already connected here shows a warning,
  and approving it needs a second administrator (a protected change), whatever permissions it asks for.
- The request review page never contacts the requesting application on its own. Use **Look up the other
  application** to fetch its permissions before approving (approval always looks it up).
- Code that calls the other application (`connect.client.get_token` / `call`) re-reads the connection state
  from the database and refuses with `connection_inactive` unless it is active, so a suspend or revoke in one
  worker applies to all of them at once.

- Rotation needs the peer to reach this installation's JWKS endpoint. If it cannot, the rotation fails safely:
  the old key stays active, the error is shown, and it is retried in 6 hours.
- The kill switch stops Connect only. It does not touch ticket-rmm-v1 pairings, which have their own controls.
- `rotate_encryption_key` re-encrypts Connect private keys with their row-bound AAD.
  A database restore into another installation with a different master key cannot decrypt them. Pair again.
- The audit chain detects changes made outside the application, but it cannot stop them. Run
  `manage.py connect_verify_audit_chain` from monitoring if you need alerts.

## Not tested against

- A real second installation over the network (all end-to-end tests use the in-memory reference peer and the
  Django test client).
- PostgreSQL/MySQL under concurrent load (tests run on SQLite). The audit chain takes a row lock on the
  installation identity to serialise appends.
