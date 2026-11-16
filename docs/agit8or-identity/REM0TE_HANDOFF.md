# Agit8or Identity — Rem0te handoff (proposal, NOT sent)

> **Status: proposal draft for the Rem0te session. Not sent, not agreed,
> not implemented.** Pointers come from a read-only audit of Rem0te
> (reboot-remote v0.54.0) on 2026-11-16 and must be verified by the Rem0te
> session. When the owner approves, this goes through the agreed
> coordination file only (`INTEGRATION_COORDINATION.clientst0r-response.md`
> on the Rem0te side) — not by editing Rem0te directly.

Context for the Rem0te session: see `ARCHITECTURE.md` (claims contract §4,
mapping §5.3, flows §6, revocation §7, Connect separation §9) and
`MIGRATION.md` Phase C/D.

## 1. What Rem0te already has (from audit)

- OIDC client: `src/sso/sso.service.ts` on `openid-client` 6.8.9, PKCE S256,
  state, nonce (≈ :255-288); `OidcProvider` table with `groupsClaim`;
  `OidcGroupMapping`; `ExternalIdentity(issuer, subject)` unique — never
  links by email; JIT per provider with verified email.
- Local auth: `auth.controller.ts:34,63` password + MFA partial token;
  `mfa.service.ts` TOTP (otplib, replay-protected, recovery codes);
  `passkeys.service.ts` (@simplewebauthn/server 14.0.3, second factor).
- Session: HS256 JWT cookie `access_token`, 8 h (`cookies.ts:7`); revocation
  via `User.sessionsValidAfter` vs `iat` (`session-revocation.ts`).
- Step-up: `step-up.service.ts` HMAC cookie, 10 min, bound to `iat`;
  `ConfirmPolicy`.

## 2. Proposed tasks

### RR-ID-01 — Explicit `iss` / `aud` / `azp` validation

Assert `iss` equals the provider's configured issuer exactly, `aud` contains
the client id, `azp` equals it when `aud` has several values, signing alg in
an allowlist (`RS256`, `ES256`, `EdDSA`), `iat` skew ≤ 120 s. Do not rely on
library defaults alone; add tests that hand-craft bad tokens.

### RR-ID-02 — Back-channel logout endpoint

`POST /sso/:provider/backchannel-logout` (CSRF-exempt, form
`logout_token`). Validate per ARCHITECTURE.md §6.3 (signature, `iss`, `aud`,
`events`, no `nonce`, `sid`/`sub`, `jti` replay via the existing
`IntegrationReplayGuard` INSERT ON CONFLICT pattern but in a **separate
table/namespace** from integration nonces). Kill sessions: record `sid` per
issued session (new `UserSession` or `sid` in the JWT + a server-side
`revokedSids` table checked in the auth guard) or, for sub-only tokens, bump
`sessionsValidAfter`. Register the URI at the OP.

### RR-ID-03 — RP-initiated logout

On sign-out of an SSO session: clear cookie, then redirect to the OP
`end_session_endpoint` with `client_id`, `post_logout_redirect_uri`,
`state`.

### RR-ID-04 — Durable lockout counters

Replace the in-memory `Map` in `auth.service.ts:49` with a Postgres-backed
counter (per account + per IP, sliding window, INSERT … ON CONFLICT
increment), so lockouts survive restarts and work across processes.
Applies to local login (still needed for fallback and break-glass).

### RR-ID-05 — Split `JWT_SECRET` usages

One symmetric secret currently signs session JWTs and (per audit) other
artefacts. Derive or configure separate keys per purpose — at least:
web session JWT, MFA partial token, step-up cookie, SSO state/transaction
cookie — with HKDF from a master or separate env vars, and support a
`*_PREVIOUS` key for rotation. Add `aud`/`typ` per purpose so one token type
cannot be replayed as another. None of these keys may be shared with
Connect/integration keys or with the OP.

### RR-ID-06 — Org and app-assignment claim mapping

- `OidcProvider`: add `claimsContract = "agit8or-v1"` mode reading
  `agit8or.orgs[]` (instead of a flat `groupsClaim`); refuse unknown `v`,
  `app != "rem0te"`, `status != active`.
- Tenant binding: `Tenant.identityOrgId` (or provider-level allowlist of org
  ids per tenant); entries for unbound orgs ignored.
- `OidcGroupMapping` keyed by `(provider, orgId, roleKey)` → `Role` +
  capability set; `orgs[].customers` as a ceiling on
  `Membership.customerId` / `TechnicianAssignment`; tag mapped memberships
  with their mapping id and reconcile only those.
- `platform_admin` claim is **not** mapped to `isPlatformAdmin`.
- Refuse login when no bound org has `assigned=true`.

### RR-ID-07 — MFA acceptance and step-up via OIDC

- SSO login with `acr ∈ {mfa, phr}` and consistent `amr` skips the local MFA
  partial-token step; `acr=pwd` is sent through local MFA (or refused when
  the tenant requires SSO MFA).
- Step-up: for SSO users, `step-up.service.ts` issues its cookie only after
  an OIDC round trip with `max_age=300` / `acr_values`; verify `auth_time`.
  Approval-signer passkey quorum unchanged.

### RR-ID-08 — Break-glass

Local emergency admin per install: sealed (enable only via host CLI, TTL
default 4 h), mandatory local MFA, never SSO-linked, high-severity audit +
alert on enable and every login, separate login route that still works when
SSO is enforced. `isPlatformAdmin` stays a local designation.

### RR-ID-09 — Session lifetime cap

Never issue a Rem0te session longer than 8 h; at expiry use `prompt=none` to
renew while the IdP session lives.

### RR-ID-10 — Tests

Unit tests for every validation rule (bad `iss`, `aud`, `azp`, alg, skew,
nonce, state), logout token cases (valid, nonce present, wrong events,
replay, sub-only), mapping (bound/unbound org, unassigned, customers ceiling,
platform_admin ignored), lockout persistence across restart, key separation
(session JWT rejected as step-up cookie and vice versa), break-glass expiry.
Wire them into `scripts/check-security-invariants.mjs` where applicable.

## 3. Interop test plan (Clientst0r ⇄ Rem0te via the OP)

Run against the Phase A spike OP; both apps on test configs; no production.

| # | Scenario | Expected |
|---|---|---|
| I1 | User assigned to both apps logs into Clientst0r, opens Rem0te | Rem0te signs in silently (`prompt=none`), no credential prompt |
| I2 | User assigned to Clientst0r only opens Rem0te | Rem0te shows "not assigned"; no session created |
| I3 | User with `acr=mfa` session opens a Rem0te action needing `phr` | OP prompts for passkey; Rem0te accepts only after `acr=phr` |
| I4 | Sign out in Clientst0r | Rem0te session ends within seconds (back-channel logout by `sid`) |
| I5 | Sign out in Rem0te | Clientst0r session ends (back-channel) |
| I6 | MSP admin suspends user at OP | Both app sessions end; new logins refused |
| I7 | Admin "terminate sessions" (no suspension) | Both sessions end; user can log in again |
| I8 | Rem0te down during logout | Clientst0r logs out; Rem0te session ends at its next silent re-auth / absolute expiry (documented bound) |
| I9 | Replay a captured `logout_token` | Rejected by both (`jti`) |
| I10 | Token for MSP A presented to a Rem0te tenant bound to MSP B | Refused |
| I11 | Clientst0r ID token sent to Rem0te callback / API / Connect endpoint | Refused (`aud`, and Connect rejects Identity issuers) |
| I12 | Delegated ticket action after the user is suspended | Clientst0r refuses to mint a delegation (no live session); Rem0te refuses any replay |
| I13 | Role removed at OP, user logs in again | Mapped membership deactivated in both apps; manual memberships untouched |
| I14 | OP unreachable | Existing sessions continue; SSO login shows a clear error; local and break-glass logins work |
| I15 | Break-glass enable + login on each app | Works with local MFA; alerts fire; auto-disables at TTL |

## 4. Questions for the Rem0te session

1. Is `JWT_SECRET` used for anything beyond the session cookie, MFA partial
   token and step-up cookie?
2. Preferred session index for `sid` revocation: DB table, or `sid` in the
   JWT + revocation list?
3. Should one Rem0te deployment bind several MSP orgs (one per `Tenant`)?
4. Any objection to the `agit8or` v1 claim shape, especially `customers` as
   a ceiling rather than a grant?
