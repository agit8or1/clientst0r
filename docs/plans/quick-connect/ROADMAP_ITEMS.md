# Proposed Phase 79 sub-items for Secure HTTPS Quick Connect

These are proposals to add to `docs/ROADMAP.md` under Phase 79, after 79.7, the highest existing item. They are all
planned and none is implemented. Increment letters refer to [INCREMENTS.md](INCREMENTS.md).

When they are added, the Phase 79 record line's `next=` should name 79.8 (increment A) as well, and
`python3 scripts/roadmap_dashboard.py` has to be run in the same commit (CLAUDE.md "Roadmap discipline").

```markdown
- **79.8 Connect hardening from the Quick Connect audit** *(planned)* — outbound requests never reach loopback or link-local addresses and use only the approved port, approvals respect the kill switch, a public address is required before pairing, unauthenticated refusals no longer grow the audit log, and a request claiming an existing installation needs a second administrator.
- **79.9 Browser-mediated bootstrap** *(planned)* — the administrator authorises the connection in the other application's own admin page; a short-lived, single-use, signed invitation and an authorization code with PKCE replace typed codes; no password ever passes between applications.
- **79.10 Default-deny source policy for Connect** *(planned)* — Connect endpoints refuse every address until one is authorised, with IPv4 and IPv6 addresses and ranges, explicit deny winning, no allow-all and no implicit trust for private addresses, checked before any authentication and independent of the general API settings; reuses the API access policy engine.
- **79.11 Per-connection inbound addresses** *(planned)* — a second, per-connection allowlist that every request must also pass; a request is bound to the connection whose address rule it matched, so shared NAT addresses stay separated by key; unexpected sources are refused and shown, never added automatically.
- **79.12 Approved outbound destinations** *(planned)* — per connection: host, port, approved addresses, trust anchor and expected identity; every resolved and connected address is checked against the approved set; an address change blocks the connection until an administrator approves it and it is retested.
- **79.13 Two-sided authorization** *(planned)* — each side approves permissions, customers and the other side's source address independently; the reverse direction is its own approval; elevated permissions and widening network changes need a second administrator.
- **79.14 Staged configuration changes** *(planned)* — network and permission changes are staged with a preview of who gains or loses access, approved, and committed atomically; rollback only ever narrows access; changes reach every worker through a policy version.
- **79.15 Certificate verification and pinning** *(planned)* — certificates are always verified, an IP address is accepted only when the certificate names it, a private CA can be set per connection, and an optional public-key pin is available; a failure blocks the connection.
- **79.16 Connection health states** *(planned)* — Pending Setup, Awaiting Approval, Awaiting Network Authorization, Testing, Connected, Degraded, Offline, Security Blocked, Suspended and Revoked, from separate transport, TLS, authentication, authorization and operational checks every 60 seconds with jitter and hysteresis; "Connected" only after every test passed.
- **79.17 Automatic reconnection** *(planned)* — backoff from 10 seconds to 15 minutes with jitter and a circuit breaker, restart-safe on the scheduler; never after a revocation, suspension, identity or certificate change, unauthorised address or other security failure, and the evidence of a security failure is kept.
- **79.18 Event queue recovery** *(planned)* — events wait while a peer is offline instead of being used up by retries, drain in order on recovery, expire by age, and can be requeued from the failed list.
- **79.19 Connection alerts** *(planned)* — status changes go through the shared event layer and existing notification channels, with deduplication, rate limits, muting and recovery notices; an optional ticket per incident, never one per check.
- **79.20 Connection diagnostics** *(planned)* — fifteen independent checks from DNS to reverse connectivity, each with a result, explanation, next step, error code and time, a run history, and a redacted export.
- **79.21 Public Agit8or Connect standard** *(planned)* — a public repository with the specification, OpenAPI, message schemas, test vectors, conformance tests, a reference peer, examples and an integration guide; this repository keeps a pinned copy.
- **79.22 SDK updates for protocol revision 1.1** *(planned)* — Python and TypeScript support for the optional bootstrap, source-binding and diagnostics extensions with new test vectors; version 1 messages and vectors unchanged, so version 1 peers keep working.
- **79.23 Independent interoperability testing** *(planned)* — Clientst0r and the reference peer connect over real HTTPS on one host, covering both pairing flows, address and certificate changes, outages and recovery, without changes to host firewalls, DNS or proxies.
- **79.24 Security review of Quick Connect** *(planned)* — an independent review, an updated threat model and limitations, and owner sign-off before Quick Connect is offered on production installations.
- **79.25 Quick Connect wizard** *(planned)* — enter a host name or address (HTTPS on 443 by default), check the network and certificate, authorise in the other application, compare the code, choose permissions and customers, allow the other side's address, watch the tests, and only then see Connected.
```

| Item | Increment | Owner-listed area |
|---|---|---|
| 79.8 | A | (audit findings) |
| 79.9 | C2 | bootstrap |
| 79.10 | B1 | default-deny source policies |
| 79.11 | B1 | per-connection inbound IP |
| 79.12 | B2 | approved outbound destinations |
| 79.13 | C3 | two-sided authorization |
| 79.14 | B1 (staging model), C3 (commit) | config staging |
| 79.15 | B2 | cert verification |
| 79.16 | C3 (Testing, Connected-only-after-tests), D (health) | health states |
| 79.17 | D | auto-reconnect |
| 79.18 | D | event queue recovery |
| 79.19 | E | alerts |
| 79.20 | E | diagnostics |
| 79.21 | F | public GitHub standard |
| 79.22 | C1, F | SDK updates |
| 79.23 | G | independent interop testing |
| 79.24 | H | security review |
| 79.25 | C2 (steps 1–4), C3 (steps 5–8), E (live test view) | Quick Connect UX |

