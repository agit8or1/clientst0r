# Implementing agit8or-connect/1 in another application

This guide is for teams adding Agit8or Connect to an application (Rem0te, Office Unbound, …). The protocol
itself is in [PROTOCOL.md](PROTOCOL.md). The HTTP surface is in [openapi.yaml](openapi.yaml).

## 1. Use an SDK, or match the vectors

| Language | Package | Notes |
|---|---|---|
| Python ≥ 3.10 | `agit8or_connect/` (this repo; `pyproject.toml`) | `cryptography` + `PyJWT` only |
| TypeScript / Node ≥ 22 | `sdk/typescript/agit8or-connect/` | `node:crypto` only, no dependencies |

If you write your own implementation, it MUST reproduce every file in
[`test-vectors/`](test-vectors/) byte for byte: canonical JSON, thumbprints, JWS, tokens, DPoP proofs, the
pairing transcript and SAS, webhook signatures, the audit chain and the endorsed JWKS. The seeds there are
**test-only** and must never be used in production. Run the SDK checks:

```bash
python -m unittest discover -s agit8or_connect/tests -t .     # Python SDK
python -m agit8or_connect.tools.generate_vectors --check     # vectors unchanged
cd sdk/typescript/agit8or-connect && npm test                  # TypeScript SDK
```

### Protocol revision 1.1 (optional)

[PROTOCOL-1.1.md](PROTOCOL-1.1.md) adds Quick Connect: browser-mediated pairing with a signed single-use
invitation, an authorisation code bound with PKCE and DPoP, signed egress-address declarations and a diagnostics
probe. It is optional and negotiated through discovery `extensions`; implement version 1 first. The SDK functions
are in `agit8or_connect/quick_connect.py` and the "Protocol revision 1.1" section of the TypeScript SDK; the
vectors are `test-vectors/qc-*.json`; `agit8or_connect/reference_peer.py` (`quick_connect=True`) is a complete
worked example of both roles. Its §13 is a checklist. A 1.1 implementation still pairs with a 1.0 peer over the
v1 code flow (PROTOCOL-1.1.md §2).

## 2. What your application stores

| Model | Fields (minimum) |
|---|---|
| Installation identity | `installation_id` (UUID, generated once), display name, kill-switch flag |
| Connection | your UUID; remote installation id, app type, display name; base URL; remote endpoints; remote connection id (= your `client_id` at the peer); state; inbound scopes (what the peer may do with you); outbound scopes (what you may do with the peer); per-connection TLS options; `tokens_not_before`; rotation schedule |
| Connection key | kid (thumbprint), state (`staged`/`active`/`retiring`/`retired`/`failed`), public JWK, **encrypted** private key |
| Remote keys | the peer's endorsed JWKS and when it was fetched |
| Pairing invitation | HMAC of the code, expiry, attempts, used/burned |
| Pairing request | public request id, connection, status, the result JWS once decided |
| Tenant grant | connection, your tenant, the peer's tenant id, scopes, active, revoked by/at |
| Replay record | namespace + key, unique, expiry |
| Outbound event / attempt | envelope, status, attempts, next attempt |
| Inbound event | (connection, event id) unique, data |
| Audit event | hash-chained record (PROTOCOL.md §14) |

## 3. Endpoints to serve

Serve every route in openapi.yaml, under any prefix, as long as discovery lists it and it is on the same origin
as discovery. Rules that are easy to get wrong:

1. Gate the whole surface behind a setting that is **off by default**.
2. Don't fetch anything from a pairing request's `discovery_url` until your administrator acts on the request
   with a deliberate action (a POST, never on opening the review page).
3. Count wrong pairing codes **in the database**, not only in a cache, and burn every open invitation at 5.
4. Store replay ids (assertion `jti`, DPoP `jti`, poll `jti`, pairing `jti`, event ids) with an expiry, and use a
   unique constraint as the check.
5. Resolve `Agit8or-Tenant` only through **this connection's** active grants. Never accept your own tenant id
   directly.
6. Check `tokens_not_before` and connection state on every request, not only at token issue.
7. Never put tokens, assertions, codes, signatures or keys in logs, audit detail, error messages or admin pages.
8. Outbound HTTP: HTTPS, TLS ≥ 1.2, verification always on, no redirects, no proxies, IP check at connect time,
   metadata, loopback and link-local addresses always blocked (whatever general "allow private IPs" switch
   your application has), private ranges only when the administrator allowed them for that connection, and only
   port 443 or the explicit port of the peer's address. Keep TLS keys out of plaintext files.
9. Put only absolute https URLs in what you send (`discovery_url`, `endpoints`): make the public base URL a
   required setting rather than deriving it from a request.
10. Don't let an approval or activation happen while your kill switch is engaged.
11. Warn, and require a second administrator, when an inbound request claims the installation id of a peer that
    is already connected.
12. Don't write a permanent audit record for every unauthenticated refusal: count them and summarise.
13. Refuse every source address by default on all Connect endpoints, before authentication (discovery, health and
    pairing included), with an installation-wide list and a per-connection list that must both allow, deny
    winning. Read the client address only through your trusted-proxy logic; give private addresses no special
    trust. After authentication, check that the connection the credentials prove is the one whose rule matched
    the address. Answer `403` with code `source_not_authorised`.
14. Ask for the other application's source address with an invitation code (and when you start a pairing), and
    let only that address use the code.
15. Store an approved destination per connection (host, port, approved addresses, trust anchor, optional SPKI
    pin, expected installation id) and pin every outbound request to it: check every resolved address and the
    connected address against the approved set, verify the certificate against the host (or the IP for an
    IP-literal destination), never follow redirects or use proxies. On a changed address or key, send nothing,
    block the connection and show the evidence; resume only after an administrator approves the new address and
    a retest passes. Never treat loopback, link-local or metadata addresses as approvable.

## 4. Pairing UI checklist

- An application catalog that is honest about status.
- A wizard with these steps: Select application → Connect application (URL) → Verify identity (show the
  installation id) → Pair (code, or QR) → Approve permissions (grouped by risk) → Select customers → Test
  connection → Complete. Keep TLS, CA bundle, private network and rotation under **Advanced**.
- An inbound flow: create a code (shown once, plus a QR), review requests, show the **SAS** prominently, and
  approve or reject.
- `high_risk`/`admin` scopes go through your second-administrator approval.
- A credential dashboard: key fingerprints and states, last rotation and next rotation, last contact, auth
  failures, the test report, recent activity.
- Actions: test, rotate now, suspend/resume, disconnect (notify, then revoke), revoke, per-customer revoke,
  kill switch.
- Error messages say what to do. For example, "The other application did not accept the pairing code. Check
  it, or ask for a new one." Never show a stack trace or a raw code.

## 5. Multi-installation receivers

If your application can be connected to several Clientst0r installations (several MSPs), every lookup must
include the connection. Two MSPs will reuse the same tenant ids (`org-1`). Test with two peers that use
identical ids (see `connect/tests/test_security.py::TenantIsolation`).

## 6. Interop testing

The in-repo reference peer (`agit8or_connect/reference_peer.py`) is a complete in-memory implementation. It
speaks to any transport callable `(method, url, headers, body) → Response`, so you can point it at your
application's test client. `connect/tests/base.py` shows how Clientst0r's Django test client is wired to it.
