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
- **Outbound destinations are not pinned yet.** Connect builds its own destination policy (port 443 or the
  explicit port of the connection's address; private ranges only with the connection's private-network
  setting; loopback, link-local and metadata always refused, whatever `ALLOW_PRIVATE_IP_INTEGRATIONS` says),
  but DNS is still resolved per request and a changed address is not detected (QC-05, planned increment B2).
- **Connect has no network allowlist of its own yet.** Its endpoints follow the general REST API access policy
  (QC-01, planned increment B1).
- **Connections show Connected as soon as both sides approve**, before a connection test (QC-07, planned).
- **Rate limits use the Django cache.** With the default local-memory cache they are per gunicorn worker. The
  brute-force limit on pairing codes is durable (database) and does not depend on it.
- **Unauthenticated refusals are aggregated.** A token request for no or an unknown connection, and a wrong
  pairing code, are counted in the API access refusal log (one row per source and reason per minute, endpoint
  group `connect_api`) and summarised into the Connect audit chain as at most one `refusals.summary` record per
  minute (by the `connect_deliver_events` task). The chain therefore shows totals for those, not each request.
  Refusals for a known connection, and the lock-out of open invitations, are still recorded one by one.
- **A wrong code still counts against every open invitation** (QC-02, planned increment B1).
- **Event delivery is scheduled** (every minute through `connect_deliver_events`), apart from the connection
  test and disconnect notices, which are sent immediately.
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
