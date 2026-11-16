# Agit8or Identity — Adopting it in an Agit8or app

> **Status: design guidance. Agit8or Identity is not deployed yet; this is
> the checklist a future app (Office Unbound, ExploitHound, MailThreatZero,
> Roots-HQ, m0nitor, MyAppDone, …) will follow.** Clientst0r and Rem0te are
> the first adopters (CLIENTST0R_TASKS.md, REM0TE_HANDOFF.md).

The app is an OIDC Relying Party against **any certified OP**; do not code
against Zitadel- or Keycloak-specific APIs outside a small adapter module.

## 1. Registration

- [ ] Request a client at the OP: confidential client (server-side web) or
      public client with PKCE (native/SPA backed by a BFF — tokens must still
      stay server-side).
- [ ] App key (`agit8or.app` value) agreed, e.g. `exploithound`.
- [ ] Exact redirect URI(s), post-logout redirect URI(s), back-channel logout
      URI registered. No wildcards.
- [ ] Role keys for the app defined at the OP (coarse; e.g. `admin`,
      `analyst`, `readonly`).
- [ ] Token endpoint auth: `private_key_jwt` preferred, `client_secret_basic`
      acceptable. Secret/key stored encrypted, never in the repo.

## 2. Login

- [ ] Use a maintained OIDC library (Python: Authlib; Node: openid-client;
      Go: coreos/go-oidc + x/oauth2). Discovery from the issuer URL.
- [ ] Authorization Code + PKCE S256 only; `state` and `nonce` stored
      server-side; scopes `openid email profile agit8or`.
- [ ] Validate ID token: signature (JWKS, refresh on unknown `kid`,
      rate-limited), `iss` exact, `aud`/`azp`, alg allowlist (no `none`, no
      `HS*`), `exp`, `iat` skew ≤ 120 s, `nonce`.
- [ ] Validate `agit8or` claim: known `v`, `app` = own key, `status=active`,
      at least one bound org with `assigned=true`.
- [ ] No tokens in URLs, `localStorage` or `sessionStorage`; session cookie
      HttpOnly + Secure + SameSite; rotate session id at login;
      `Referrer-Policy: no-referrer` on the callback; scrub `code`/tokens
      from logs.

## 3. Accounts and authorisation

- [ ] Identity key is `(iss, sub)`; store in an external-identity table with a
      unique constraint. **Never link or match by email.**
- [ ] JIT only with `email_verified=true` + explicit assignment + at least
      one mapped role; email collision → refuse and point to the linking
      flow.
- [ ] Mapping table `(provider, org_id, role_key) → local role`; unmapped
      keys grant nothing; mapped grants tagged by source and reconciled on
      every login; manual grants untouched.
- [ ] `orgs[].customers` is a ceiling, never a grant.
- [ ] `platform_admin` is not mapped to any app super-admin.
- [ ] Authorisation stays local and is re-checked on every request from the
      app's DB — claims are not consulted after login.
- [ ] Install/tenant bound to explicit OP org ids; other orgs ignored.

## 4. MFA and step-up

- [ ] Treat a session as MFA only when `acr ∈ {urn:agit8or:acr:mfa,
      urn:agit8or:acr:phr}` and `amr` is consistent.
- [ ] Sensitive actions: redirect with `max_age` (default 300) and
      `acr_values`; verify `auth_time` and `acr` on return.

## 5. Sessions and logout

- [ ] Store `sid`, `auth_time`, `acr` with the local session; index sessions
      by user and by `(iss, sid)`.
- [ ] App session never exceeds 8 h absolute; renew with `prompt=none`.
- [ ] RP-initiated logout: kill local session, then redirect to
      `end_session_endpoint`.
- [ ] Back-channel logout endpoint: validate `logout_token` (signature,
      `iss`, `aud`, `events`, no `nonce`, `sid`/`sub`, `jti` replay), kill
      sessions, return 200, no redirect, CSRF-exempt for that route only.
- [ ] Admin "sign out everywhere" for a user (per-user `sessions_valid_after`).

## 6. Separation from Agit8or Connect

- [ ] Never accept an Identity ID/access/logout token on any app-to-app
      endpoint; reject Identity issuers and non-Connect `typ` there.
- [ ] Never forward a user's tokens to another app. Acting for a user uses a
      Connect delegation assertion issued from the user's live local session
      (ARCHITECTURE.md §9).
- [ ] Separate keys, stores, audit event names (`auth.sso.*` vs
      `integration.*`) and admin permissions for Identity settings vs
      Connect settings.

## 7. Break-glass and resilience

- [ ] One sealed local emergency admin: shell-only enable with TTL, local MFA
      mandatory, never SSO-linked, alerts on enable and login, separate
      login route that works when SSO is enforced.
- [ ] OP outage: existing sessions continue; clear error on SSO login;
      fallback paths per the app's enforcement mode.
- [ ] Enforcement mode per org: `off | optional | enforced`.

## 8. Audit

- [ ] Events: `auth.sso.login`, `auth.sso.login_refused` (with reason),
      `auth.sso.link`, `auth.sso.unlink`, `auth.sso.jit_created`,
      `auth.sso.stepup`, `auth.sso.backchannel_logout`,
      `auth.sessions.revoked`, `auth.breakglass.enabled`,
      `auth.breakglass.login`. Include `iss`, `sub`, `sid`, `acr`, IP, user
      agent; never tokens.

## 9. Conformance tests (must pass before an app is registered in production)

Run with a fake OP (locally minted JWKS/tokens) in unit tests, then against
the staging OP.

| ID | Test | Pass condition |
|---|---|---|
| C01 | Valid login | Session created, `(iss, sub)` linked |
| C02 | `aud` = another app | Refused |
| C03 | `iss` differs (incl. trailing slash) | Refused |
| C04 | `alg=none` / `HS256` signed with client secret | Refused |
| C05 | Wrong / missing `nonce`; replayed `state` | Refused |
| C06 | Missing PKCE verifier at token exchange | OP refuses; app shows error |
| C07 | Email equals an existing user, new `sub` | Not linked, no JIT |
| C08 | `email_verified=false` | No JIT |
| C09 | No `assigned` bound org | Refused |
| C10 | Only unbound-org entries | Refused |
| C11 | Unknown `agit8or.v` / wrong `app` / `status≠active` | Refused |
| C12 | Role removed between logins | Mapped grant removed, manual grant kept |
| C13 | `customers` narrower than local scope | Effective scope is the intersection |
| C14 | `platform_admin=true` | No app super-admin |
| C15 | `acr=pwd` | Not treated as MFA |
| C16 | `acr=mfa`, `amr=["pwd"]` | Rejected as inconsistent |
| C17 | Step-up with stale `auth_time` / lower `acr` | Action refused |
| C18 | Back-channel logout by `sid` | Only matching sessions killed |
| C19 | Back-channel logout by `sub` only | All user sessions killed |
| C20 | Logout token with `nonce` / wrong `events` / replayed `jti` | 400, nothing killed |
| C21 | RP-initiated logout | Local session gone, redirect to OP end-session |
| C22 | Tokens in URL / web storage | None found (grep test of templates + HTTP capture) |
| C23 | Identity token on a Connect endpoint | Refused |
| C24 | Break-glass: web enable attempt; TTL expiry; login alert | Refused; disabled; alert sent |
| C25 | OP unreachable | Existing sessions OK; clear error; fallback per mode |
