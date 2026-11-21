# Secure HTTPS Quick Connect: increments

Each increment:

- ships as its own release (version bump, CHANGELOG, ROADMAP sub-item annotation);
- stays behind `AGIT8OR_CONNECT_ENABLED` (off by default);
- does not change a v1 wire format or an existing test vector (`python -m agit8or_connect.tools.generate_vectors
  --check` must pass in every increment);
- keeps ticket-rmm-v1 (`integrations/rem0te/`, `scripts/e2e/cross_peer/`) untouched;
- includes its tests in the matching app (`connect/tests/`, `api_access/tests.py`, `core/tests/test_safe_http.py`,
  `agit8or_connect/tests/`).

Every increment has these regression gates:

- `manage.py test connect api_access` passes;
- `core.tests.test_safe_http` passes;
- the SDK unittest suite passes;
- the TypeScript `npm test` passes;
- `generate_vectors --check` passes;
- `connect/tests/test_security.py::TicketRmmV1Untouched` passes;
- `DisabledByDefault` passes.

Order follows the owner's suggestion (A–G). Two changes follow from the audit: the protocol 1.1 specification and
vectors move to the front of C so the wizard is built against a fixed contract, and the security review is an
explicit closing increment (H).

---

## A. Fix the audit findings that do not need the new design (one release, 79.8)

Scope:

- **QC-04:**
  - `connect/transport.py` builds its own `OutboundPolicy(allow_lan=conn.allow_private_network, allow_local=False,
    allowed_ports={443} | {explicit port from base_url})`. It never calls `configured_service_policy()`.
  - The SDK adapter's `allow_private` branch keeps `allow_local=False`.
- **QC-08:** the kill-switch check runs in `approve_inbound`, `approve_local`, `finalize_*`, `_activate` and the
  `app_connection` applier.
- **QC-10:**
  - `AGIT8OR_CONNECT_PUBLIC_URL` is required: the UI refuses to create invitations or start pairing without it,
    with an explicit message.
  - `identity.endpoints()`/`public_base()` never return relative URLs.
- **QC-11:** request review no longer fetches on GET; there is a "Look up the other application" POST button.
- **QC-12:** a warning plus a second-administrator requirement when an inbound request claims an installation id
  that is already connected.
- **QC-03 (partial):** `token.issue` denials for unknown/absent connections and wrong-code rejections are counted
  in the folded `ApiAccessDecision` log and summarised into the chain once a minute. They are no longer one chain
  row per request.
- **QC-09:** the mTLS key goes to a temp file in a private 0700 directory under the app's runtime dir, with a
  startup sweep of leftovers. A pure-memory alternative needs a different TLS client, which is noted as a
  limitation.
- **QC-14:** `client.get_token`/`client.call` refuse unless `state=active` (re-read from the DB).
- QC-02, QC-01, QC-05, QC-06, QC-07, QC-13 and QC-16 are addressed by B–E (listed there).

Acceptance tests:

- With `ALLOW_PRIVATE_IP_INTEGRATIONS=True`:
  - `https://127.0.0.1/`, `https://[::1]/`, `https://169.254.1.1/` and `https://10.0.0.5:8443/` are refused for a
    connection with private network off;
  - `127.0.0.1` and `169.254.1.1` are still refused with private network on;
  - `10.0.0.5:443` is allowed with private network on.
- Port other than 443 or the explicit `base_url` port → `blocked_destination`.
- Kill switch engaged → approving an inbound request, a local approval and applying a protected change each fail.
  After release the connection is not `active`.
- With `AGIT8OR_CONNECT_PUBLIC_URL` unset → the invite and wizard pages show the error; no relative URL appears in
  any outgoing JWS (assert on the reference peer's captured requests).
- GET of request review performs no outbound request (transport factory mock asserts zero calls).
- Duplicate installation id → warning rendered; approval opens a protected change.
- 500 token requests with unknown `client_id` → at most 1 chain row per minute and a folded decision count of 500.
- `client.call` on a suspended connection raises `connection_inactive`.

---

## B. Default-deny inbound layers and approved outbound destinations (two releases, 79.10–79.12, 79.15)

### B1. Inbound source policy

Scope:

- `SURFACE_CONNECT` in `api_access`.
- `connect/source_policy.py` evaluates both layers through `api_access.policy.evaluate`.
- The `SourceRule` and `ConnectChange` (staging, narrow-only rollback) models, plus
  `InstallationIdentity.connect_policy_version`.
- Middleware branch in `ApiAccessMiddleware`, and the binding check after authentication (§5.3 step 11).
- Network page (installation layer) and the connection Network tab.
- Observe mode for pre-existing connections (DESIGN §13.2).
- v1 code flow: an invitation requires the peer's address (temporary pairing rule). This contains QC-02.
- Pairing/token/event rate-limit buckets keyed by address and connection (QC-13 bounded by the allowlist).
- `manage.py connect_source_rules` for server-side recovery.

Acceptance tests:

- Fresh enable, no rules → every Connect route (`/.well-known/agit8or-connect`, `health`, `pairing`, `token`, `jwks`,
  `events`, `capabilities`, `test`) answers `403 source_not_authorised` for IPv4, IPv6 and IPv4-mapped clients,
  **including with a valid DPoP token**.
- REST API in Unrestricted mode, Connect empty → Connect refuses. REST API in Allowlist with the office range,
  Connect rule for the peer → the peer passes Connect and the office range does not.
- Installation layer allows X but the connection layer does not → 403. Both allow → passes. A deny in either layer
  wins over an allow in the other.
- Two connections, peer P1 allowed only for C1: P1 presenting C2's `client_id` → 403 at step 7. P1 with a stolen
  C2 token and its own address in C1's rules → 403 at step 11 (binding mismatch, security event recorded).
- `0.0.0.0/0`, `::/0`, an IPv4 range shorter than /16 and an IPv6 range shorter than /32 are refused at save.
  Private entries need the explicit flag.
- `X-Forwarded-For` from an untrusted peer is ignored. From a trusted proxy, the first untrusted hop is used (reuse
  the `core.client_ip` tests with Connect routes).
- A private-address client is refused when the site firewall's LAN exemption would pass it.
- Policy change in one worker is visible in another (simulate by resetting the process cache and bumping the
  version). With the DB unavailable and the cache older than 60 s → refuse.
- api_access rollback window armed and expiring → Connect `SourceRule` rows unchanged.
- Connect rollback of a widening change → the allow set never contains an entry absent from both versions.
- Observe mode: an existing active connection keeps working; observed sources are listed; enforcement after the
  date refuses unapproved sources.

### B2. Approved outbound destinations

Scope:

- `ApprovedDestination` model; migration from `base_url`/`tls_ca_bundle`.
- `core.safe_http.OutboundPolicy.pinned` (opt-in, other callers unaffected) and the SPKI pin check.
- `connect/transport.py` uses the pin.
- `destination_changed` → `security_blocked` (lifecycle state added here), with evidence and an approve-new-address
  change (protected when widening). Fixes QC-05.

Acceptance tests:

- Resolution to an address outside the pin → refused before any byte is sent (mock `getaddrinfo`); peer recheck
  refuses a connected address outside the pin.
- Redirect → not followed (existing test kept). Proxy env vars → ignored.
- An IP-literal destination with a certificate lacking that IP SAN → `certificate_name_mismatch`; with the IP SAN →
  passes (local TLS server with a test CA, see G).
- SPKI pin mismatch → `spki_mismatch`, Security Blocked, no automatic retry.
- Approving a /24 is allowed; a /23 is refused.
- `core/tests/test_safe_http.py` is unchanged and passes, so other integrations are unaffected.

---

## C. Quick Connect bootstrap (three releases, 79.9, 79.13, 79.14, 79.22)

### C1. Protocol 1.1 specification, vectors and SDK primitives (docs + SDKs only)

Scope:

- `docs/agit8or-connect/PROTOCOL-1.1.md` (extensions `qc-bootstrap/1`, `qc-source-binding/1`, `qc-diagnostics/1`);
  `openapi.yaml` gains the two API paths under a `1.1` tag.
- New vector files `test-vectors/qc-invitation.json`, `qc-exchange.json`, `qc-transcript.json`.
- Python and TypeScript build/verify functions for the invitation, accept and exchange messages and the QC
  transcript/SAS.
- The reference peer learns the 1.1 flow.

Acceptance tests:

- Both SDKs reproduce the new vectors byte for byte.
- Old vector files are byte-identical (`--check`).
- A v1-only reference peer and a 1.1 reference peer still pair over the v1 code flow.
- A 1.1 message presented to a v1 verifier is refused by `typ`, and vice versa.

### C2. Bootstrap in Clientst0r

Scope:

- `QuickConnectInvitation` and `QuickConnectGrant`.
- Initiator wizard steps 1–4, `qc_authorize` and callback pages, `POST /connect/v1/qc/exchange`.
- Temporary pairing rule creation from the reviewed invitation.
- Attempt deadline and reaper (initially in the existing per-minute delivery job; it moves to the monitor in D).
- `InstallationIdentity.egress_addresses` + `qc_enabled` (default False).

Acceptance tests (Django test client ↔ 1.1 reference peer, both roles):

- Happy path ends in `awaiting_local_approval`/`awaiting_remote_approval` with equal SAS on both sides.
- Invitation reused, expired, tampered (one claim changed), with `redirect_uri` on another origin, or with `base`
  pointing at loopback/metadata → each refused with its own code and an audit record.
- Code reused, expired, wrong verifier, exchange signed by another key, exchange from an address outside the
  temporary rule → refused. The last one shows the observed vs approved address and adds nothing.
- Browser-address independence: the callback and authorise requests come from an address different from
  `egress_A`. The rules contain only `egress_A`.
- No password field exists on any Quick Connect page; the flow never posts credentials to the peer (assert the
  captured request bodies).
- Attempt abandoned → after the deadline the temporary rule is `removed`, keys retired, state `failed`, policy
  version bumped.
- `qc_enabled` False → no Quick Connect button, and `qc_authorize`/`qc_exchange` answer 404.

### C3. Two-sided authorisation, network approval, staged commit

Scope:

- Steps 5–8 of the wizard and the B-side review.
- Reverse-direction rules.
- `awaiting_network` and `testing` states.
- `commit_connection()` gated on a passing diagnostic run (first version: the existing 5 checks plus DNS, TCP, TLS,
  certificate and source steps; full 15 in E).
- Elevated scopes and widening network changes through `tech_access` (`app_connection`).
- Fixes QC-07 for both Quick Connect and v1 code-flow connections.

Acceptance tests:

- A connection never shows Connected before a passing run.
- A failing test step leaves `awaiting_network`/`testing` with no active rule and the temporary rule still
  time-limited.
- A protected change approved by the proposer → refused (existing tech_access rule). The fingerprint changes after
  the proposal → refused.
- The reverse direction is not approved → B cannot reach A's token endpoint (403 at A); the one-directional mode
  allows only discovery.
- Commit is atomic: inject a DB error after the rule activation and before the state change → nothing active.

Implementation notes (`connect/activation.py`, `connect/permissions.py`, tests in
`connect/tests/test_increment_c3.py`):

- Approved reverse rules are written as `staged` rows of a `ConnectChange` in status `approved`. Entering `testing`
  turns them `temporary` for a test window of at most 15 minutes (re-armed by each run); the commit makes them
  `active`. A network or local-source failure returns them to `staged` (`awaiting_network`).
- One administrator approves exactly the address(es) already approved for the pairing; another address, a range or
  a newly private address needs a second administrator (`app_connection`).
- After a Quick Connect exchange the responder narrows the 15-minute pairing rule to a `poll` rule (pairing status
  only) until the attempt deadline, so a later approval can still be learnt.
- A refusal by the other side (not approved yet, our source refused, token refused) keeps `testing`: falling back
  to `awaiting_network` would close our window while the other side tests, and two Clientst0r installations would
  never commit.
- A `testing` connection gets tokens and may call `capabilities`, `test` and `health` and send `connect.test`;
  customer endpoints and other events need `active`.
- The automatic retest of `testing` connections and `resume` through `testing` are left to increment D's monitor.

---

## D. Health states, monitor job, auto-reconnect, event-queue recovery (one release, 79.16–79.18)

Scope:

- `health`, `health_dims` and hysteresis counters; `status.display()` used by every page.
- `connect_monitor` scheduled task (1 min, 50 s in-task loop, CAS on `next_check_at`).
- Backoff ladder 10 s → 15 min with ±20 % jitter; circuit breaker; Security Blocked transitions (DESIGN §7.3).
- The resume path goes through `testing`.
- Queue changes: no attempt counting while open, age-based dead letter, requeue action, ordered drain; delivered
  history pruning. Fixes QC-06.

Acceptance tests (time and transport mocked):

- 60 s ± 10 % checks. Two failures → Degraded, three transport failures → Offline, two passes → Connected.
- The ladder sequence is observed: 10, 30, 60, 120, 300, 600, 900, 900 s ± 20 %.
- While Offline, queued events keep `attempts` unchanged. After 9 h offline (more than today's 7–8 h dead-letter
  point) all events are delivered on recovery, in order, once each. The receiver sees no duplicates beyond the
  idempotent re-sends.
- Restart safety: kill the task mid-loop (raise in a check) → the next run resumes; no connection is checked twice
  in one pass.
- No reconnect attempts in `suspended`, `revoked`, `security_blocked` or while the kill switch is on (transport
  mock asserts zero calls).
- Each §7.3 failure (identity changed, certificate invalid, SPKI mismatch, destination changed, peer revoked, key
  revoked, `source_not_authorised` from the peer, scope withdrawn) → Security Blocked at once. Evidence is kept
  after a later successful retest.
- `connect_deliver_events` still works when run alone (compatibility).

---

## E. Alerts and diagnostics (one release, 79.19–79.20)

Scope:

- `events/` adapter for connection status transitions.
- E-mail, bell, system warning; dedupe marker; mute; optional ticket per incident.
- `DiagnosticRun` with the 15 steps; `qc_probe` endpoint.
- Redacted export; diagnostics tab.
- Audit-chain anchoring into `AuditLog` (C-05).

Acceptance tests:

- A flapping connection (pass/fail every check for 2 h) sends at most one alert per status per 30 min, and the
  recovery notice is sent once.
- 1,000 heartbeats while Offline produce one ticket (opt-in) and no new ticket.
- Muted connection: Degraded/Offline e-mail suppressed; Security Blocked still raises a system warning.
- Each of the 15 steps has a test forcing pass, fail and skipped (dependency failed). `not_tested` is produced for
  step 14 against a v1 peer.
- The export contains no token, assertion, DPoP proof, code, signature, private key or pairing secret (regex scan
  as in `SecretLeakage`).
- `qc_probe` requires a valid DPoP token and source authorisation, and returns the observed address.
- Anchor rows appear hourly; truncating `connect_audit` makes `connect_verify_audit_chain` fail.

---

## F. Public standard repository (one release of this repo + the new repository, 79.21–79.22)

Scope:

- Create `github.com/agit8or1/agit8or-connect`. **The owner creates the repository or authorises its creation;
  nothing is pushed there without that.**
- It holds:
  - `SPEC/` (PROTOCOL v1 + 1.1, normative), `openapi/`, JSON Schemas for every message and discovery;
  - `test-vectors/` (copied byte-identical, then authoritative there);
  - `python/` and `typescript/` SDKs (with the TS guarded transport the audit found missing);
  - `conformance/` (a black-box test suite run against any base URL);
  - `reference-peer/` (an HTTP-serving wrapper around the reference peer, see G);
  - `examples/` and `CLAUDE_INTEGRATION_GUIDE.md`.
- In this repo, `docs/agit8or-connect/` becomes a pinned copy with a `PIN.json` (commit hash + file digests, the
  pattern of `integrations/rem0te/contract/PIN.json`), and a test checks the digests.

Acceptance tests:

- The conformance suite passes against the reference peer and against a Clientst0r dev instance.
- Vectors in both repos are identical (digest test).
- No competitor names, secrets or install-specific data in the public repo (pre-publish scan).

---

## G. Real-network interoperability on this host (one release, 79.23)

Scope:

- `scripts/e2e/connect_interop/`:
  - starts the reference peer as a real HTTPS server (stdlib `http.server` + `ssl`) with a throw-away test CA,
    bound to this host's **non-loopback** LAN address (loopback stays forbidden for Connect);
  - starts a second Clientst0r dev process (`runserver` on its own port with its own SQLite DB and
    `AGIT8OR_CONNECT_ENABLED=True`), never the production service;
  - the private CA is set per connection, and the LAN address is approved as an explicit private destination
    entry.
- No changes to host firewalls, DNS, nginx or the production gunicorn.

Acceptance tests (scripted, also runnable from CI on a single host):

- Quick Connect both directions, v1 code flow both directions, SAS equal.
- Tokens, DPoP, signed events, rotation and revoke all work over real sockets.
- DNS/IP change (switch the peer to another local address) → Security Blocked.
- Certificate replaced by one from another CA → `certificate_invalid`.
- Kill the peer process → Offline and backoff, then restart → recovery and an ordered queue drain.
- A source not in the rules (bind the client to another local address) → 403.
- The TypeScript SDK's conformance run against the Clientst0r dev instance passes.

---

## H. Security review and documentation (one release, 79.24)

Scope:

- An independent review: a fresh-context reviewer given the code, not the design.
- A threat-model update in PROTOCOL-1.1.md.
- A LIMITATIONS.md rewrite.
- An updated `docs/API_ACCESS_CONTROL.md` Connect section.
- Owner sign-off before `qc_enabled` is documented as usable on production.
- The Rem0te handoff updated with the 1.1 extensions as **optional**.

Acceptance:

- Every QC-nn finding is closed or explicitly accepted.
- Review findings are fixed or tracked.
- The Rem0te coordination file is updated through the coordination channel only.

---

## Dependency summary

```
A ──► B1 ──► B2 ──► C1 ──► C2 ──► C3 ──► D ──► E ──► G ──► H
                     └──────────────────────────► F (spec/SDK parts can start after C1)
```
