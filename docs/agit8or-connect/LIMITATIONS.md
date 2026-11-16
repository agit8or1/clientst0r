# Agit8or Connect — known limitations (Phase 1)

What is **not** done or not proven yet. Keep this list current. Don't describe anything here as shipped.

## Not implemented

- **No peer application implements the protocol yet.** Rem0te support is a proposal
  (`docs/plans/coordination/agit8or-connect-rem0te-handoff.md`). The catalog shows Rem0te as
  "Available — needs a Rem0te release with Agit8or Connect support (not yet released)". Every other app is "Planned".
- **Off by default.** `AGIT8OR_CONNECT_ENABLED=False` makes every Connect route and page answer 404.
  `AGIT8OR_CONNECT_PUBLIC_URL` should be set to the externally reachable https address before turning it on.
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
  encrypted) and passed to the transport, but it is **not covered by an end-to-end test**.
- **Rate limits use the Django cache.** With the default local-memory cache they are per gunicorn worker. The
  brute-force limit on pairing codes is durable (database) and does not depend on it.
- **Event delivery is scheduled** (every minute through `connect_deliver_events`), apart from the connection
  test and disconnect notices, which are sent immediately.
- **QR scanning** is not implemented on Clientst0r's side (it only shows a QR). The SDKs parse the QR payload.
- **Phases 3–5** (other applications' catalogs, event forwarding between more than two apps, shared rate-limit
  store, signed audit exports, health alerting) are design notes only.

## Operational notes

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
