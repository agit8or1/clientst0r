# Agit8or Connect — protocol revision `1.1` (Quick Connect extensions)

Status: **draft.** Clientst0r implements `qc-bootstrap/1` and `qc-source-binding/1` in both roles (increment C2 of
[`docs/plans/quick-connect/INCREMENTS.md`](../plans/quick-connect/INCREMENTS.md), `connect/quick_connect.py`), off by
default behind `AGIT8OR_CONNECT_ENABLED` and the installation's Quick Connect switch. It does not serve
`qc-diagnostics/1` (`qc_probe`) yet and does not advertise it. The reference SDKs implement
every message: `agit8or_connect/quick_connect.py` (Python) and the "Protocol revision 1.1" section of
`sdk/typescript/agit8or-connect/src/index.ts`. Byte-exact examples: `test-vectors/qc-*.json`. HTTP surface:
the `1.1` tag in [`openapi.yaml`](openapi.yaml).

This document only **adds** to [PROTOCOL.md](PROTOCOL.md) (`agit8or-connect/1`). Every term, rule and message of
PROTOCOL.md applies unchanged unless a section below says otherwise. The key words MUST, MUST NOT, SHOULD and MAY
are used as in RFC 2119.

Revision 1.1 is three optional, independently negotiated **extensions**:

| Extension | What it adds |
|---|---|
| `qc-bootstrap/1` | Browser-mediated pairing. The administrator authorises the connection in the *other application's own admin UI*, with that application's own sign-in. A signed single-use invitation, an authorisation code bound with PKCE (S256), a DPoP-bound server-to-server exchange, then the unchanged v1 ack, poll, result, tokens and events. |
| `qc-source-binding/1` | Signed declarations of each installation's egress (source) addresses, and the error code `source_not_authorised` (HTTP 403). |
| `qc-diagnostics/1` | `POST qc_probe`: an authenticated call that answers the source address the peer observed, for connectivity diagnostics. |

There is no password grant (OAuth ROPC) anywhere in 1.1, and no message field that could carry a password. An
administrator signs in only to their own application.

---

## 1. Terms

| Term | Meaning |
|---|---|
| A, initiator | The installation whose administrator starts Quick Connect. |
| B, responder | The installation being connected to. Its administrator authorises in B's own UI. |
| Attempt | One Quick Connect run. A identifies it by its new connection id (`attempt`). |
| K_A, K_B | The new per-connection Ed25519 keys of A and B for this connection. K_A signs the invitation and the exchange and becomes A's connection key (as in a v1 pairing request); K_B signs the accept and the v1 ack and becomes B's connection key. |
| Egress | The source address(es) an installation's outbound requests come from, **as the peer sees them** (after NAT). Declared by each side's administrator, never derived from a browser address. |
| Temporary rule | B's source-address rule admitting A's declared egress to B's `qc_exchange` (and `pairing_status`) for this attempt only, for at most 15 minutes. |
| Origin | `https://host[:port]` in the canonical form of §4.3. |

---

## 2. Compatibility with `agit8or-connect/1` (1.0 peers)

These guarantees are normative and covered by tests (`agit8or_connect/tests/test_qc_reference_peer.py::Compatibility`,
`test_qc_vectors.py::V1Untouched`, `qc-discovery.json`):

1. **Nothing in v1 changes.** No v1 message, claim, header, signing string, endpoint, error code or vector changes
   bytes or meaning. The seven v1 vector files are byte-identical (their SHA-256 digests are pinned in
   `test_qc_vectors.py`), and `python -m agit8or_connect.tools.generate_vectors --check` passes.
2. **The major version stays `1`.** Discovery keeps `"versions": ["1"]`. Version negotiation (PROTOCOL.md §3) is
   unchanged. `revision` and `extensions` are new discovery members which v1 receivers already ignore
   (PROTOCOL.md §3: unknown members MUST be ignored).
3. **Extensions are used only when both sides advertise them** (§3). A peer that advertises nothing is a 1.0 peer.
4. **Fallback is the v1 code flow**, unchanged. A 1.1 initiator that finds no `qc-bootstrap/1` at the responder
   uses the v1 code flow (PROTOCOL.md §5). A 1.0 initiator talking to a 1.1 responder uses the v1 code flow without
   knowing 1.1 exists. Two 1.1 installations MAY still use the code flow.
5. **No cross-protocol confusion.** Every 1.1 message has its own JWS `typ` (§4.2) and `protocol` claim
   `"agit8or-connect/1.1"`. A v1 verifier refuses a 1.1 message (the invitation by `typ` with `invalid_request`;
   the exchange, whose header has no `jwk`, with `invalid_signature`), and a 1.1 verifier refuses every v1 message
   by `typ` (`invalid_request`). A 1.1-typed message whose `protocol` claim says `agit8or-connect/1` is refused
   with `unsupported_version`.
6. **After the exchange everything is v1.** The exchange is answered with the v1 ack
   (`agit8or-pairing-ack+jwt`, bytes as PROTOCOL.md §5.2). Status polling, the result JWS, tokens, DPoP, JWKS,
   rotation, events, suspension and revocation are v1, unchanged. A connection created by Quick Connect is an
   ordinary v1 connection.
7. **`source_not_authorised` is an ordinary error to a 1.0 peer.** A responder that enforces source policy
   answers `403 {"error": {"code": "source_not_authorised", …}}` to any caller, 1.0 or 1.1; PROTOCOL.md §3/§13
   already make unknown codes opaque failures.
8. **Rem0te's ticket-rmm-v1 (revision 2) is untouched.** It uses different routes (`/api/integration/v1/`),
   models and keys; 1.1 neither reads nor changes it. A Rem0te build implementing the v1 handoff contract pairs
   with a 1.1 Clientst0r exactly as with a 1.0 one.

| A (initiator) | B (responder) | Flow |
|---|---|---|
| 1.0 | 1.0 | v1 code flow |
| 1.0 | 1.1 | v1 code flow (B's extra discovery members ignored) |
| 1.1 | 1.0 | v1 code flow (A sees no `qc-bootstrap`; or B's entry point answers 404 and A's attempt expires) |
| 1.1 | 1.1 | Quick Connect, or the v1 code flow if either administrator chooses it |

---

## 3. Discovery additions and negotiation

A 1.1 installation adds to its discovery document (PROTOCOL.md §4):

```json
{
  "versions": ["1"],
  "revision": "1.1",
  "extensions": {"qc-bootstrap": 1, "qc-source-binding": 1, "qc-diagnostics": 1},
  "endpoints": {
    "…every v1 endpoint, unchanged…": "…",
    "qc_authorize": "https://b.example/agit8or-connect/qc-authorize",
    "qc_exchange": "https://b.example/connect/v1/qc/exchange",
    "qc_probe": "https://b.example/connect/v1/qc/probe"
  }
}
```

- `revision` is informative (`"1.1"`). Behaviour follows `extensions` only.
- An `extensions` value is a positive integer or an array of positive integers (< 1000): the extension versions the
  installation implements. Any other value (string, boolean, 0, object) makes that member **not advertised**.
  Names longer than 64 characters are ignored. Unknown names are ignored.
- Required endpoints: `qc-bootstrap` needs `qc_authorize` and `qc_exchange`; `qc-diagnostics` needs `qc_probe`;
  `qc-source-binding` needs none. An extension whose required endpoint is missing, not a string, or not on the
  discovery document's origin (PROTOCOL.md §4 same-origin rule, compared as `scheme://host:port` with the default
  port filled in) is **not advertised**. Unlike a v1 endpoint, a bad 1.1 endpoint does not invalidate the whole
  document; it only removes that extension.
- `qc_authorize` is a browser page in B's admin UI. `qc_exchange` and `qc_probe` are Connect API routes.

**Negotiation algorithm** (`negotiate_extensions` / `negotiateExtensions`):

1. `advertised` = the peer's extensions after the rules above, as `{name: sorted unique versions}`.
2. For each extension this side implements: `common` = our versions ∩ advertised versions; if non-empty, select
   `max(common)`.
3. Drop any selected extension whose prerequisite was not selected. `qc-bootstrap/1` requires
   `qc-source-binding/1`.
4. The pairing flow is `qc-bootstrap/1` if `qc-bootstrap` was selected at version 1, otherwise `code` (v1).

A v1 document yields `{}` and the `code` flow. Vectors: `qc-discovery.json` → `negotiation` (8 cases).

**Signed extension sets and downgrade protection.** The invitation and the accept each carry the signer's own
`extensions` in the normalised form `{name: [versions…]}`. After the callback A reads B's discovery (§5.9) and MUST
check `check_no_downgrade(accept.extensions, advertised(B's document))`: for every extension name this side
implements, every version B signed that this side also implements MUST be in B's advertised set; otherwise
`downgrade_detected` (403). Names this side does not implement are ignored. Vectors: `qc-discovery.json` →
`downgrade`.

---

## 4. Common rules

### 4.1 Cryptography, encoding, time

- As PROTOCOL.md §2: Ed25519 (`alg` `EdDSA`) only, SHA-256, RFC 7638 thumbprints as key ids, canonical JSON for
  every JWS header and payload produced, compact JWS, `crit` refused. `sha256_hex(x)` is the lower-case hex
  SHA-256 of the UTF-8 bytes of `x`; `b64url` is unpadded base64url.
- Time checks are those of v1 (`check_times`): `exp`/`iat`/`nbf` are integers; the message is expired when
  `now >= exp + 120`; `iat > now + 120` is refused; `exp - iat` above the message's maximum lifetime is refused
  with `invalid_request`; `exp <= iat` is refused.
- JWS size: at most 8192 characters (v1). The invitation: at most **4096** characters, so it fits in a URL.

### 4.2 Message types

| Message | JWS `typ` | Header | Signed by | Max lifetime |
|---|---|---|---|---|
| Invitation | `agit8or-qc-invitation+jwt` | `alg`, `typ`, `kid`, `jwk` (= K_A, public) | K_A | 600 s |
| Accept | `agit8or-qc-accept+jwt` | `alg`, `typ`, `kid`, `jwk` (= K_B, public) | K_B | 600 s |
| Exchange | `agit8or-qc-exchange+jwt` | `alg`, `typ`, `kid` (= thumbprint(K_A)); **no** `jwk` | K_A | 120 s (builders use 60 s) |
| Exchange DPoP proof | `dpop+jwt` (v1, unchanged) | v1 | K_A | v1 (±120 s) |
| Ack | `agit8or-pairing-ack+jwt` (v1, unchanged) | v1 | K_B | v1 |

The header `kid`, when present with a `jwk`, MUST equal the thumbprint of that `jwk` (else `invalid_signature`).
Every 1.1 JWS payload has `protocol: "agit8or-connect/1.1"` and `ext: "qc-bootstrap/1"`.

### 4.3 Canonical URLs

`base`, `redirect_uri` and every origin in a 1.1 message MUST match this grammar exactly (no normalisation is
applied by verifiers; a URL that is not already canonical is refused):

```
url      = "https://" host [ ":" port ] path
host     = dns-name / ipv4 / "[" ipv6 "]"
dns-name = label *( "." label )                 ; total ≤ 253
label    = [a-z0-9] [ *61[a-z0-9-] [a-z0-9] ]   ; lower case only
ipv4     = dotted decimal, each octet 0–255 without leading zeros
ipv6     = RFC 5952 text (lower case, longest run of ≥2 zero groups compressed, leftmost on a tie);
           IPv4-mapped (::ffff:0:0/96) refused
port     = 1–65535 without leading zeros, and not 443 (the default port is always omitted)
path     = *( "/" segment )                     ; segment = 1*( ALPHA / DIGIT / "." / "_" / "~" / "-" ), not "." or ".."
```

No user info, query, fragment, percent-encoding or trailing slash. Length ≤ 512, printable ASCII only.
`origin(url)` = `"https://" host [":" port]` of such a URL.

- **`base`** (an installation's public base, `AGIT8OR_CONNECT_PUBLIC_URL` on Clientst0r): canonical URL; port in the
  verifier's allowed set (default `{443}`; a responder MAY allow an administrator-approved port); host not
  `localhost` or `*.localhost`; an IP-literal host not inside any refused network of §4.4. Failure: `invalid_base`.
  Nothing is fetched to check a `base`.
- **`redirect_uri`**: canonical URL with at least one path segment, and `origin(redirect_uri) == origin(base)`.
  Failure: `invalid_redirect_uri`. The callback path itself is the initiator's choice; the responder redirects to the
  exact signed value.

Vectors: `qc-invitation.json` → `base_valid` (5), `base_invalid` (18), `redirect_checks` (6).

### 4.4 Addresses (`qc-source-binding/1`)

An egress entry is `{"net": <canonical network>, "note": <string>}`.

- Accepted input text: `^(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9A-Fa-f:.]{2,45})(?:/(?:0|[1-9][0-9]{0,2}))?$`, then
  parsed as an IPv4 or IPv6 address/network with **host bits zero**. No netmask form, no zone id (`%`), no
  whitespace, no IPv4 octet with a leading zero, no IPv4-mapped IPv6 address. Anything else: `invalid_egress`.
- **Canonical form**: an exact address carries `/32` or `/128`; IPv4 dotted decimal; IPv6 per RFC 5952 (embedded
  IPv4 notation is written as hex groups: `64:ff9b::1.2.3.4` → `64:ff9b::102:304/128`). Builders normalise;
  **verifiers require the canonical form** and refuse anything else.
- Prefix limits: IPv4 `/16`–`/32`, IPv6 `/32`–`/128` (so `0.0.0.0/0` and `::/0` are always refused). A receiver
  MAY apply a narrower local limit.
- Refused when the network **overlaps** any of: `0.0.0.0/8`, `127.0.0.0/8`, `169.254.0.0/16`, `224.0.0.0/4`,
  `240.0.0.0/4`, `100.100.100.200/32`, `192.0.0.192/32`, `::/128`, `::1/128`, `::ffff:0:0/96`, `fe80::/10`,
  `ff00::/8`, `fd00:ec2::254/128`.
- Private (flagged to the administrator, never trusted implicitly): overlaps `10.0.0.0/8`, `172.16.0.0/12`,
  `192.168.0.0/16`, `100.64.0.0/10` or `fc00::/7`. The flag is computed by the receiver; it is not a claim.
- `egress` lists 1–8 entries with distinct `net`s. `note` is a string of at most 100 Unicode code points (builders
  emit `""` when there is none).
- A source address matches an entry when the address is inside the entry's network.

Vectors: `qc-invitation.json` → `net_normalization` (17), `net_malformed` (20), `net_refused` (15),
`net_private` (8).

### 4.5 Random values

| Value | Form | Rule |
|---|---|---|
| PKCE `code_verifier` | 32 random bytes, b64url (43 chars) | RFC 7636 §4.1 charset, 43–128 chars |
| `code_challenge` | `b64url(SHA-256(ASCII(code_verifier)))` (S256) | exactly 43 chars; only `S256` |
| Authorisation `code` | 32 random bytes, b64url (43 chars) | single use, 120 s |
| `state` | 32 random bytes, b64url | 22–128 b64url chars; bound to the administrator's session and the attempt |
| `nonce` | 32 random bytes, b64url | 22–128 b64url chars |
| Invitation / exchange `jti` | ≥ 16 random bytes, b64url | 16–128 chars of `[A-Za-z0-9_-]` |

All from a CSPRNG. The vectors use fixed, published, TEST-ONLY values (`qc_value(name)` in the generator).

---

## 5. `qc-bootstrap/1`

### 5.1 Sequence

```
Admin A ─▶ A: Quick Connect to b.example (destination approved first; DNS+TLS preview only, no HTTP)
A: new attempt (connection id), K_A, PKCE verifier v, state s, nonce
A ─▶ browser: 303 {qc_authorize}?invitation=<invitation JWS>&state=s
browser ─▶ B (admin UI): B's own sign-in + 2FA; B verifies the invitation (§5.3), shows the review
Admin B: approve → B creates the temporary rule for egress_A (§7.2), K_B, code c, accept JWS
B ─▶ browser: 303 redirect_uri?accept=<accept JWS>&code=c&state=s
browser ─▶ A (callback, A's admin session): A checks state, verifies the accept (§5.5)
A ─▶ B: GET discovery (now admitted from egress_A); identity + downgrade check (§5.9)
A ─▶ B: POST qc_exchange {exchange JWS} + DPoP (K_A)              [from egress_A]
B: verifies (§5.6) → consumes code, records the request → 202 {request_id, ack (v1, K_B)}
A: verifies the v1 ack, ack key == accept key; both compute the transcript and SAS (§5.8)
── from here on v1: pairing_status poll (K_A) → result (K_B); both administrators compare the SAS and approve ──
```

### 5.2 Authorisation request (browser leg 1)

`GET {qc_authorize}?invitation=<JWS>&state=<state>` — the parameters in this order, unencoded (both values are
URL-safe). `qc_authorize` is taken from B's discovery when A can read it. Because B's Connect endpoints are
default-deny by source address, A usually cannot read B's discovery before B authorises it; A then uses the
**conventional entry point** `{B base}/agit8or-connect/qc-authorize`. A responder that implements `qc-bootstrap/1`
MUST serve that path as a browser page, or as a `303` to its real authorisation page on the same origin. It is a web
page (B's login, 2FA and site firewall apply), not a Connect API route. A 1.0 responder answers it with 404: the
administrator then uses the code flow, and A's attempt expires (§6).

If A *can* read B's discovery and negotiation yields the `code` flow, A MUST NOT send the invitation
(`extension_not_negotiated`) and offers the v1 code flow.

### 5.3 Invitation

Claims (all required unless marked optional):

| Claim | Value |
|---|---|
| `protocol` | `"agit8or-connect/1.1"` |
| `ext` | `"qc-bootstrap/1"` |
| `extensions` | A's implemented extensions `{name: [versions]}`; MUST include `qc-bootstrap` 1 and `qc-source-binding` 1 |
| `iss` | A's `installation_id` (UUID, lower case) |
| `aud` | `origin(B)` as approved by A's administrator (the approved destination), canonical (§4.3) |
| `responder_installation` | optional: B's `installation_id` when A already knows it; B MUST then check it equals its own |
| `iat`, `exp` | integers; `exp - iat` ≤ 600 |
| `jti` | invitation id (§4.5); single use at B |
| `attempt` | A's connection id for this attempt (UUID). Becomes `connection_id` in the exchange. |
| `app` | `{type, version, display_name, installation_id}`; `installation_id` MUST equal `iss` |
| `base` | A's public base (§4.3) |
| `redirect_uri` | A's callback (§4.3) |
| `egress` | A's declared egress (§4.4) |
| `requested_scopes` | sorted unique scope names A asks for at B (shown to B's administrator; v1 rules apply at approval) |
| `code_challenge`, `code_challenge_method` | S256 challenge of A's verifier; method `"S256"` |
| `nonce` | §4.5 |

Header `jwk` = K_A public, `kid` = thumbprint(K_A). Signed with K_A (self-contained, like the v1 pairing request).

**Verification by B (normative order; first failure wins):**

1. length > 4096 → `too_large`.
2. `typ` ≠ `agit8or-qc-invitation+jwt` → `invalid_request`. Header `jwk` not a valid public Ed25519 JWK, or `kid`
   ≠ its thumbprint → `invalid_signature`.
3. Signature with the header key → `invalid_signature`. Required claims present → else `invalid_request`.
   Times (§4.1, max lifetime 600): expired → **`invitation_expired`**; other time failures → `invalid_request`.
4. `protocol`/`ext` → `unsupported_version`.
5. `aud` ≠ origin(B's own public base) → `wrong_audience`. `responder_installation` present and ≠ B's id →
   `wrong_audience`.
6. `iss` UUID, `jti` format, `attempt` UUID → `invalid_request`. `app.installation_id` ≠ `iss` → `invalid_request`.
7. `code_challenge_method` ≠ `S256`, `code_challenge` not 43 b64url chars, `nonce` malformed, `requested_scopes`
   not a list of strings → `invalid_request`.
8. `base` (§4.3, B's allowed ports) → `invalid_base`. `redirect_uri` → `invalid_redirect_uri`.
9. `egress` (§4.4) → `invalid_egress`.
10. `extensions` lacks `qc-bootstrap` 1 or `qc-source-binding` 1 → `invalid_request`.
11. Replay store namespace `qc-inv`, key `"{iss}:{jti}"`, kept until `exp + 120`. Already present →
    **`invitation_used`**. Record only after steps 1–10 pass.

B MUST NOT fetch anything from `base` at this point. B's host application then applies its local checks (DESIGN.md
§6.4 items 3–8): `base` against its outbound policy, private egress flagged, a claimed installation id that is
already connected needs a second administrator, unknown scopes listed and never granted, the administrator's
permission and fresh re-authentication, rate limits on reviews. A host SHOULD bind re-display of the same review to
the administrator's session instead of re-verifying the JWS (step 11 would refuse it).

**Error redirect.** If, and only if, steps 2–10 passed (so `redirect_uri` is authentic), B MAY redirect a refusal
back as `redirect_uri?error=<code>&state=<state>`. For a failure in steps 1–10 B MUST NOT redirect (open-redirect
protection) and shows its own error page.

### 5.4 Authorisation response (browser leg 2)

On approval B redirects (303) to `redirect_uri?accept=<accept JWS>&code=<code>&state=<state>` (this parameter
order). On denial: `redirect_uri?error=access_denied&state=<state>`. A parses the query (a repeated parameter →
`invalid_request`), compares `state` with the value bound to the administrator's session and this attempt in
constant time (mismatch or missing → `state_mismatch`), surfaces `error` as the refusal code, and requires a
43-character b64url `code` and a non-empty `accept` (else `invalid_request`). A callback is processed at most once
per attempt.

### 5.5 Accept

| Claim | Value |
|---|---|
| `protocol`, `ext` | as the invitation |
| `extensions` | B's implemented extensions (signed; used for the downgrade check, §3) |
| `iss` | B's `installation_id` |
| `aud` | A's `installation_id` (= invitation `iss`) |
| `iat`, `exp` | `exp - iat` ≤ 600 |
| `attempt` | invitation `attempt` |
| `invitation` | invitation `jti` |
| `invitation_sha256` | `sha256_hex(invitation JWS as received)` |
| `connection_id` | B's connection id for this attempt (UUID) |
| `app` | B's `{type, version, display_name, installation_id}`; `installation_id` = `iss` |
| `base` | B's public base; `origin(base)` MUST equal the invitation `aud` |
| `egress` | B's declared egress (§4.4), for the reverse direction |
| `code_sha256` | `sha256_hex(code)` — binds this accept to this code |

Header `jwk` = K_B, `kid` = thumbprint(K_B). K_B MUST be the key that later signs the v1 ack.

**Verification by A (order):** `typ`/header key (as §5.3 step 2) → signature, required claims, times (max 600;
expired → `expired`) → `protocol`/`ext` (`unsupported_version`) → `aud` ≠ A's id → `wrong_audience` → `invitation`,
`attempt` or `invitation_sha256` differ → `wrong_attempt` → `code_sha256` ≠ `sha256_hex(code)` (constant time) →
`invalid_grant` → `iss`/`connection_id` UUIDs, `app.installation_id` = `iss` → `invalid_request` → `base` canonical
and allowed → `invalid_base`; `origin(base)` ≠ invitation `aud` → `destination_mismatch` → `egress` →
`invalid_egress` → `extensions` must include `qc-bootstrap` 1 and `qc-source-binding` 1 → `invalid_request`.

### 5.6 Exchange

```
POST {qc_exchange}
Content-Type: application/json
DPoP: <v1 DPoP proof signed with K_A: htm "POST", htu = qc_exchange URL (normalised as v1), iat, jti; no ath>

{"exchange": "<exchange JWS>"}
```

Exchange claims — every v1 pairing-request claim except `pairing_code`, plus the binding claims:

| Claim | Value |
|---|---|
| `protocol`, `ext` | as the invitation |
| `iss` / `aud` | A's / B's `installation_id` (B's from the accept) |
| `iat`, `exp`, `jti` | `exp - iat` ≤ 120; `jti` per §4.5, single use |
| `code`, `code_verifier` | the code from the redirect; the PKCE verifier |
| `invitation` | invitation `jti` |
| `accept_sha256` | `sha256_hex(accept JWS as received)` |
| `app`, `connection_id`, `discovery_url`, `connection_key`, `requested_scopes`, `proposed_tenants` | as the v1 pairing request (PROTOCOL.md §5.2); `connection_id` = invitation `attempt`; `connection_key` = K_A public JWK |

Header: `alg`, `typ`, `kid` = thumbprint(K_A). No `jwk`: B already holds K_A from the invitation.

**Order of checks at B.** The source-address layer runs first (§7): the request MUST come from an address inside
the temporary rule of the attempt whose grant the `code` names; B finds the grant by `sha256_hex(code)` read from
the *unverified* payload (`exchange_code_sha256`). Unknown code, expired rule or address outside it → `403
source_not_authorised`, and nothing else is evaluated or recorded. Then (`verify_exchange`):

1. `typ` ≠ `agit8or-qc-exchange+jwt` → `invalid_request`.
2. header `kid` ≠ thumbprint(invitation key) → `key_mismatch`.
3. Signature with the invitation key → `invalid_signature`; required claims → `invalid_request`; times (max 120;
   expired → `expired`).
4. `protocol`/`ext` → `unsupported_version`.
5. `aud` ≠ B's id → `wrong_audience`.
6. `iss` ≠ invitation `iss`, `invitation` ≠ invitation `jti`, `connection_id` ≠ invitation `attempt`, or
   `accept_sha256` ≠ `sha256_hex(the accept B issued)` → `wrong_attempt`.
7. thumbprint(`connection_key`) ≠ thumbprint(invitation key) → `key_mismatch`.
8. `app.installation_id` ≠ `iss`, `jti` format, `requested_scopes` not a list → `invalid_request`.
9. `sha256_hex(code)` ≠ the grant's code hash (constant time) → `invalid_grant`.
10. `now >= code_expires_at` (issue time + 120 s, B's clock, no skew) → `code_expired`.
11. `code_verifier` format → `invalid_request`; `S256(code_verifier)` ≠ invitation `code_challenge` →
    `pkce_mismatch`.
12. DPoP proof (v1 `verify_dpop_proof`, method `POST`, the `qc_exchange` URL, `expected_jkt` = thumbprint(K_A)) →
    `invalid_dpop_proof`, or `replayed` for a reused proof `jti`.
13. Replay namespace `qc-exchange`, key `"{iss}:{jti}"`, until `exp + 120` → `replayed`.
14. Replay namespace `qc-code`, key = code hash, until `code_expires_at + 120` → `code_used`.

Steps 13–14 and the host's own state change (grant used, request recorded, observed source recorded on the attempt)
MUST happen in one transaction. A host MUST also fetch A's discovery (from `invitation.base`, through its outbound
policy) when its administrator acts, and check that its `installation_id` equals `iss`
(`identity_mismatch`).

### 5.7 Answer and what follows (v1)

`202 {"status": "pending_approval", "request_id": "<B's request id>", "ack": "<v1 ack JWS>"}` exactly as a v1
`POST pairing` answer. The ack has `request_jti` = exchange `jti` and `connection_id` = accept `connection_id`, and is
signed by K_B. A verifies it with the v1 `verify_ack` and additionally checks that the ack key equals the accept key
(`check_ack_key`, else `key_mismatch`). From here on A polls `pairing_status` with v1 poll proofs, B answers with the
v1 result JWS (`request_jti` = exchange `jti`), and both administrators approve as in PROTOCOL.md §5.3.

Errors from `qc_exchange` use the v1 error body (PROTOCOL.md §13) with the codes of §9.

### 5.8 Transcript and SAS

Both sides compute, from the three messages exactly as sent:

```
qc_transcript = sha256_hex(canonical({
  "v": "agit8or-connect/1.1 qc-transcript",
  "invitation_sha256": sha256_hex(<invitation JWS>),
  "accept_sha256":     sha256_hex(<accept JWS>),
  "exchange_sha256":   sha256_hex(<exchange JWS>),
  "initiator": {"installation_id": <invitation iss>, "jkt": thumbprint(K_A), "egress": [<invitation egress nets, in order>]},
  "responder": {"installation_id": <accept iss>,     "jkt": thumbprint(K_B), "egress": [<accept egress nets, in order>]},
  "destination": {"host": <host of invitation aud, without brackets>, "port": <port of invitation aud, 443 if omitted>}
}))
SAS = the v1 function (PROTOCOL.md §5.2) applied to qc_transcript:
      first 8 bytes of sha256("agit8or-connect/1 sas\n" + qc_transcript), big-endian, mod 10^8, as NNNN-NNNN
```

The SAS function is v1's; domain separation comes from the transcript's `v`. A substituted key on either side, a
changed egress declaration, a different destination host or port, or any altered message changes the SAS
(`qc-transcript.json` → `mutations`, 6 cases, all distinct SAS values). Both UIs show the SAS; administrators
approve only when they match.

### 5.9 Discovery check at A after the callback

Once the temporary rule exists A reads B's discovery (through the approved destination) and MUST check
(`check_discovered_identity`): `app.installation_id` = accept `iss` (else `identity_mismatch`), no downgrade (§3,
`downgrade_detected`), and negotiation yields `qc-bootstrap/1` (else `downgrade_detected`). Only then does A send the
exchange.

---

## 6. State machine (protocol level)

Attempt at **A**:

```
started ──(invitation sent)──▶ awaiting_authorisation
awaiting_authorisation ──(callback: state ok, accept ok, discovery ok)──▶ exchanging
awaiting_authorisation ──(error redirect | attempt deadline)──▶ failed
exchanging ──(202 + ack ok)──▶ awaiting_remote_approval   (v1 from here: poll → result)
exchanging ──(any refusal)──▶ failed
```

Attempt at **B**:

```
(invitation verified) ──▶ under_review
under_review ──(administrator approves)──▶ authorised   [temporary rule active ≤ 15 min; code valid 120 s]
under_review ──(denied)──▶ failed                        [error redirect]
authorised ──(exchange ok)──▶ awaiting_local_approval     (v1 from here)
authorised ──(code expired | rule expired | attempt deadline)──▶ failed   [rule removed, K_B wiped]
```

Timers: invitation ≤ 600 s; code 120 s; temporary rule ≤ 900 s (`TEMPORARY_RULE_TTL`); exchange JWS ≤ 120 s.
A host MAY set an overall attempt deadline (Clientst0r: 30 min, DESIGN.md §6.5). Any failure before both
administrators approve MUST remove the temporary rule and retire the attempt keys (v1: a rejected or expired
pairing wipes its keys). Rollback only removes access. The host's lifecycle after this point (Clientst0r's
`awaiting_network` → `testing` → `active`, DESIGN.md §4) is local and not part of the wire protocol.

---

## 7. `qc-source-binding/1`

### 7.1 Declarations

Each side's administrator declares its own egress; it is signed into the invitation (A) or the accept (B), bound into
the transcript and SAS, and shown to the other side's administrator. A declaration is a **claim**, never trust:

- it is accepted only in canonical form and within §4.4 limits;
- it is never derived from the address of a browser request;
- it only ever narrows: the receiver turns it into a rule only after its administrator approves.

### 7.2 Temporary rule

On approval B creates a rule admitting exactly the invitation's `egress` networks, for this attempt only, for the
pairing endpoints (`qc_exchange`, and `pairing_status` for this request), expiring after at most 900 s. A request
from any other address is refused with `source_not_authorised` **before** authentication, and adds nothing. The
observed source of a successful exchange SHOULD be recorded and shown next to the declaration.

### 7.3 Error

```
HTTP/1.1 403
{"error": {"code": "source_not_authorised", "message": "<no secrets>", "correlation_id": "<uuid>"}}
```

Any Connect endpoint of an installation enforcing source policy MAY answer it, to 1.0 and 1.1 callers alike.
Naming an unknown attempt, connection or code gives the same answer as an address outside the rules, so the
refusal reveals nothing. Vector: `qc-diagnostics.json` → `source_not_authorised_error`.

---

## 8. `qc-diagnostics/1`

```
POST {qc_probe}
Authorization: DPoP <v1 access token, any granted scope>
DPoP: <v1 proof: htm POST, htu = qc_probe URL, ath = hash of the token>
Content-Type: application/json

{"nonce": "<optional, b64url>"}
```

Authentication is exactly the v1 resource rule (PROTOCOL.md §6.3): `invalid_token`, `invalid_dpop_proof`,
`replayed`. Answer `200`:

```json
{"protocol": "agit8or-connect/1.1", "observed_source": "203.0.113.10", "server_time": 1767225600,
 "connection_state": "active", "checks": {"source": "ok", "token": "ok"},
 "peer_reached_at": 1767225540, "nonce": "<echoed when sent>"}
```

- `observed_source`: the caller's address as the server sees it after its trusted-proxy logic, in canonical address
  text (§4.4 without the prefix).
- `checks.source`: `ok` (inside the connection's rules), `not_authorised`, or `not_enforced`.
- `peer_reached_at`: when this server last completed an authorised call **to** the caller (unix seconds), or
  `null`. It supports the reverse-connectivity step of a diagnostic run.
- The caller validates the shape (`validate_probe_response`), requires its nonce to be echoed, and treats the
  answer as information only: an observed address is shown to an administrator as a *suggestion* and never becomes
  a rule by itself.

Vectors: `qc-diagnostics.json` → `verify` (1 valid, 5 refused), `response`, `response_invalid` (5).

---

## 9. Error codes (additions)

All are in the v1 error body. HTTP status applies where the code is answered on the wire; codes raised in a browser
leg are shown in the receiving UI or carried as `error=` on a verified redirect.

| Code | HTTP | Where | Meaning |
|---|---|---|---|
| `source_not_authorised` | 403 | any Connect endpoint | source address not admitted (before authentication) |
| `invitation_expired` | — | B, invitation | `now >= exp + 120` |
| `invitation_used` | — | B, invitation | `jti` already recorded |
| `wrong_audience` | 400/401 | B invitation, A accept, B exchange | message for another origin/installation |
| `wrong_attempt` | 401 | A accept, B exchange | message bound to another attempt, invitation or accept |
| `invalid_base` | — | both | `base` not canonical, port not allowed, refused host |
| `invalid_redirect_uri` | — | B, invitation | not canonical, no path, or another origin |
| `invalid_egress` | — | both | §4.4 |
| `destination_mismatch` | 401 | A, accept | accept `base` is not the destination A approved |
| `identity_mismatch` | 403 | A after callback; B on discovery of A | discovery `installation_id` differs from the signed identity |
| `key_mismatch` | 401 | B exchange; A ack | not signed by the invitation key / ack key ≠ accept key |
| `invalid_grant` | 400 | B exchange; A accept | unknown code / code not bound to this accept |
| `code_expired` | 400 | B, exchange | code older than 120 s |
| `code_used` | 400 | B, exchange | code already exchanged |
| `pkce_mismatch` | 400 | B, exchange | `S256(code_verifier)` ≠ `code_challenge` |
| `downgrade_detected` | 403 | A after callback | discovery advertises less than B signed, or no `qc-bootstrap/1` |
| `extension_not_negotiated` | — | A, before the invitation | peer does not offer Quick Connect: use the code flow |
| `access_denied` | — | A, callback | B's administrator denied |
| `state_mismatch` | 400 | A, callback | `state` missing or not this session's attempt |
| `invalid_dpop_proof`, `replayed`, `expired`, `invalid_signature`, `invalid_request`, `unsupported_version`, `too_large` | v1 | | v1 meanings |

---

## 10. Storage and replay

Replay-store namespaces added to v1's: `qc-inv` (`"{iss}:{jti}"`, until `exp + 120`), `qc-exchange`
(`"{iss}:{jti}"`, until `exp + 120`), `qc-code` (code SHA-256 hex, until expiry + 120). Use the v1 rule: a unique
constraint is the check, recorded only after verification.

| Side | Stores (minimum) |
|---|---|
| A | attempt: connection id, K_A (encrypted at rest, row-bound AAD as v1), PKCE verifier, `state` bound to the administrator's session, invitation JWS, approved destination, deadline |
| B | verified invitation + K_A public key; grant: code SHA-256 (never the code), code expiry, accept JWS, K_B (encrypted), attempt connection; temporary rule (networks, expiry, purpose `pairing`); observed source of the exchange |

Never store or log the code, the verifier, a JWS signature, a DPoP proof or a private key in audit detail, error
messages or admin pages (PROTOCOL.md §14 rules apply).

---

## 11. Security considerations and threat model

Additions to PROTOCOL.md §16. Design rationale: [DESIGN.md](../plans/quick-connect/DESIGN.md) §6 and §15; audit
findings QC-01…QC-16 in [AUDIT.md](../plans/quick-connect/AUDIT.md) §4.

| Threat | Mitigation in 1.1 |
|---|---|
| Password phishing / credential relay between applications | No ROPC, no password field: each administrator signs in only to their own application (code + PKCE). |
| Forged invitation shown to a phished B administrator | The invitation is only a *request to review*; it grants nothing. B shows A's host, claimed id, egress and scopes; the temporary rule reaches only pairing endpoints for ≤ 15 min; final approval is v1 (both administrators, SAS) and B reads A's discovery over TLS for A's name. |
| Stolen redirect / authorisation code | Useless alone: PKCE verifier (only A's server has it), exchange signed by K_A (the invitation key), DPoP proof by K_A, request admitted only from A's declared egress; 120 s, single use; `code_sha256` binds code ↔ accept. |
| Invitation replay | `jti` single use (`qc-inv`), ≤ 10 min, `aud` = B's origin. |
| Mix-and-match across attempts | `invitation_sha256`, `accept_sha256`, `attempt`, `invitation` jti and `code_sha256` chain every message to one attempt. |
| Man in the middle substituting keys or addresses | Transcript binds K_A, K_B, both egress lists and the destination; administrators compare the SAS. |
| Downgrade to the code flow or to fewer extensions | Signed `extensions` in invitation and accept, checked against discovery after the callback (`downgrade_detected`); `typ` + `protocol` claim refuse cross-protocol use; a 1.1 typ carrying `agit8or-connect/1` is refused. |
| Open redirect via `redirect_uri` | Signed by K_A; same origin as `base`; canonical grammar; B redirects only after the invitation verified. |
| SSRF via `base` | Canonical grammar, refused literals, allowed ports; nothing fetched before an administrator acts; outbound fetches go through the approved-destination policy (v1 §4 rules plus pinning). |
| Spoofed or shared source address | The address is a second factor, never the only one: the exchange still needs K_A + PKCE; TCP spoofing cannot complete TLS; two installations behind one NAT are separated by their keys. |
| Unauthenticated audit/log growth | Source refusals happen before verification and are not chain-audited per request (AUDIT.md QC-03). |
| Browser address used as trust | Never: egress comes only from administrator declarations and signed messages. |

Out of scope, as v1: a compromised administrator account (mitigated by two-person approval for elevated scopes and
by the SAS), compromise of a host's master key.

---

## 12. Test vectors

Generated by `python -m agit8or_connect.tools.generate_vectors` from the published TEST-ONLY seeds A, B, C of
`keys.json` and fixed TEST-ONLY nonces (`qc_value(name)` = b64url(SHA-256(`"agit8or-connect/1.1 TEST-ONLY " + name`))).
Both SDKs rebuild every positive message byte for byte and reproduce every expected error code.

| File | Contents |
|---|---|
| `qc-invitation.json` | invitation, PKCE pair, authorisation URL; 20 verification cases (2 valid, 18 refused: expired, replayed, wrong audience ×2, bad signature, substituted header key, lifetime, v1 protocol claim, stripped extensions, redirect ×2, loopback base, egress ×4, `plain` PKCE, v1 request presented); the v1 verifier refusing the invitation; address and URL tables |
| `qc-exchange.json` | accept and its 10 cases (1 valid, 9 refused); authorisation response and error URLs; exchange + DPoP and 17 cases (valid, DPoP replay, code reuse sequence, code expired, exchange expired, wrong audience, wrong verifier, unknown code, other key, bad signature, accept hash, substituted connection key, v1 protocol claim, DPoP by another key, DPoP for another URL, no DPoP, v1 request presented); the v1 verifier refusing the exchange; the v1 ack |
| `qc-transcript.json` | canonical transcript input, hash, SAS, 6 mutations with their distinct SAS |
| `qc-discovery.json` | 8 negotiation cases (3 Quick Connect, 5 fall back to the code flow) and 4 downgrade cases |
| `qc-diagnostics.json` | probe token + DPoP (1 valid, 5 refused), response, 5 invalid responses, the `source_not_authorised` body |

---

## 13. Implementer checklist

1. Implement 1.0 first; pass every v1 vector.
2. Add the discovery members only for extensions you implement; keep `versions: ["1"]`.
3. Serve `/agit8or-connect/qc-authorize` (browser) if you implement `qc-bootstrap/1` as a responder.
4. Verify in the order given; return the listed code for each failure; record single-use values last, in one
   transaction with your state change.
5. Put the source-address check before anything else on `qc_exchange`.
6. Show the SAS on both sides and require both administrators' approval (v1).
7. Fall back to the v1 code flow whenever negotiation does not yield `qc-bootstrap/1`.
8. Reproduce `test-vectors/qc-*.json` byte for byte.
