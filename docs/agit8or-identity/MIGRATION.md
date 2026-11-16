# Agit8or Identity — Migration plan

> **Status: plan only. Nothing here is implemented or deployed.**
> Phase A (deploying the IdP) requires explicit approval from the owner.
> No production change happens in any phase without approval; Clientst0r
> releases follow the normal release pattern and the owner clicks Apply.

Principles for every phase:

- **Existing logins keep working.** Local password + TOTP, Azure AD SSO, LDAP
  (Clientst0r) and local password + MFA / existing OIDC providers (Rem0te)
  stay available until an org explicitly opts into enforcement (Phase E).
- **Every phase is behind a setting that defaults to off** and has a
  rollback that does not require a data migration to be reversed.
- **No automatic linking by email**, ever (ARCHITECTURE.md §5.1).
- Mobile tokens, API keys and Connect credentials are untouched.

---

## Phase A — Deploy the IdP (requires explicit approval)

### A.1 Spike (no production impact)

Run the chosen OP (Zitadel; Keycloak as fallback) in a scratch environment on
this server's dev side (not a disposable cloud VM — local testing only) and
check the six gates in ARCHITECTURE.md §3: licence, multi-org users, back-
channel logout, delegated admin isolation, `amr`/`acr` behaviour, footprint.
Record results in this directory before any production deployment.

### A.2 Topology

Two supported topologies (ARCHITECTURE.md §3 "Deployment topologies"):
**T1** one shared Zitadel serving many MSPs (each MSP = one Zitadel
Organization) or **T2** one Zitadel per MSP. Phase A deploys one instance
for the owner's MSP; it is T1-ready (MSPs added later as orgs) and the same
procedure produces a T2 instance for a self-hosting MSP.

### A.2a Sizing

| Host | OP | Postgres | Total budget | Notes |
|---|---|---|---|---|
| **Separate VM (recommended)** | 2 vCPU, 1 GB RSS (Zitadel) / 2 GB (Keycloak) | 1 GB, 20 GB disk | 2 vCPU / 4 GB / 40 GB | Isolates the OP from app outages and app compromise; easiest to back up and to make HA later |
| Shared 4 vCPU / 7 GB host | Zitadel capped at ~768 MB (systemd `MemoryMax`), Keycloak not recommended here (JVM 1–2 GB) | Dedicated small Postgres cluster, `shared_buffers` 128–256 MB, ~512 MB | ~1.3 GB added | Competes with gunicorn, Collabora and SQLite write load (known login-400 issue under long writes); an app compromise on the host reaches the OP — weaker boundary |

Native install (systemd unit + Postgres) is the default; a container is fine
if the owner prefers. TLS via the existing Nginx pattern on a dedicated
hostname (e.g. `id.<domain>`), HSTS, no other vhosts sharing cookies.

### A.3 Baseline configuration

- Instance (platform) admins: two named humans, passkey required.
- One Zitadel Organization per MSP. First org: the owner's MSP (= the
  owner's Clientst0r install + Rem0te tenant).
- One project/app registration per Agit8or app: `clientst0r`, `rem0te`
  (confidential clients, Auth Code + PKCE, exact redirect URIs, post-logout
  URIs, back-channel logout URIs).
- Roles per app (initial keys): Clientst0r `msp_admin`, `technician`,
  `readonly`; Rem0te `operator_admin`, `technician`, `business_owner`.
- Claims action/mapper emitting the `agit8or` v1 claim.
- MFA policy: required for all users of MSP orgs; passkeys + TOTP enabled.
- Backups + restore test (ARCHITECTURE.md §11.2) before any app is pointed
  at it.

### A.4 Rollback

Stop the OP. No app depends on it yet.

---

## Phase B — Clientst0r generic OIDC client (opt-in, alongside existing logins)

### B.1 Library choice: **Authlib**

| | Authlib | mozilla-django-oidc |
|---|---|---|
| PKCE, nonce, state, discovery, JWKS rotation | yes | PKCE in recent versions; discovery limited |
| Multiple providers, config read at runtime | yes — `OAuth().register()` per provider, can be built from DB/`SystemSetting` per request | single provider from Django settings |
| Validate back-channel `logout_token` | yes — `joserfc` / `authlib.jose` JWT verification with the same JWKS | no back-channel logout support; would need a second JOSE lib |
| Licence / maintenance | BSD-3, actively maintained | MPL-2.0, maintained but narrower |

Clientst0r stores integration configuration in the database (Directory
Services / Azure settings are re-read per request), may need more than one
provider (Agit8or Identity plus a customer's own OP later), and must verify
logout tokens. Authlib covers all three with one dependency; we write a thin
Django auth backend around it. `msal` stays only for the existing Azure path
until that path is migrated (B.5).

### B.2 What ships (see CLIENTST0R_TASKS.md for the task list)

- `OIDCProvider` config (issuer, client id, secret/private key, scopes,
  `jit_enabled`, **pinned `msp_org_id`** (exactly one — set in the setup
  wizard, changed only via a second-admin protected change),
  `min_acr_for_2fa`, enabled flag). Tokens without that org are refused.
- Customer mapping UI: each `core.Organization` (customer) can be given its
  identity customer key so per-customer membership claims/groups in the MSP's
  Zitadel org map to `Membership` rows.
- `ExternalIdentity(issuer, subject)` and `OIDCRoleMapping`.
- Login button "Sign in with Agit8or Identity" on `/account/login/` only
  when a provider is enabled. Local, Azure and LDAP forms unchanged.
- Back-channel logout endpoint, session index, web "sign out everywhere".
- `Enforce2FAMiddleware` accepts SSO sessions with `acr` mfa/phr.

### B.3 Linking existing accounts

Existing users are **not** matched by email. Two supported paths:

1. **User-initiated link (default):** a signed-in user (local or Azure or
   LDAP, already 2FA-verified) opens Profile → "Link Agit8or Identity",
   completes an OIDC login with `prompt=login`, and the returned `(iss, sub)`
   is attached to *their* account. Requires a fresh local re-auth
   (`reauthenticate()`) right before. Audited.
2. **Admin pre-link:** an admin enters the user's OP `sub` (copied from the
   OP console) on the user's edit page; takes effect on first SSO login.
   Second-admin approval required for staff with elevated roles. Audited.

An SSO login whose `(iss, sub)` is unknown and whose email matches an
existing account shows: "An account with this email already exists. Sign in
the usual way and link Agit8or Identity from your profile." — no link, no
JIT.

### B.4 Testing before release

Unit tests for validation, mapping, linking, logout token handling, 2FA
acceptance, step-up (CLIENTST0R_TASKS.md CS-ID-12). Live check against the
spike OP on this server.

### B.5 Azure AD

Fix the email-based matching first (CS-ID-01), independent of Identity. Later
options: keep Azure as a direct login, or federate Azure into the OP as an
upstream IdP and retire the direct path (open question in ARCHITECTURE.md).

### B.6 Rollback

Disable the provider (setting). SSO button disappears; linked users sign in
the old way; `ExternalIdentity` rows are inert. Mapped memberships created by
SSO stay as-is (they are normal memberships tagged `source=oidc`); an admin
can bulk-deactivate them by source if needed.

---

## Phase C — Rem0te: harden its existing OIDC client

Rem0te already has an `openid-client` 6.8.9 SSO module with PKCE S256,
state, nonce, `ExternalIdentity(issuer, subject)` and `OidcGroupMapping`
(`src/sso/sso.service.ts`). Work (REM0TE_HANDOFF.md):

- Explicit `aud`/`azp`/`iss` assertions and alg allowlist (do not rely on
  library defaults alone).
- Read `agit8or.orgs[]` via a claim path in `OidcGroupMapping`; tenant
  binding by OP org id.
- Back-channel logout endpoint using `sessionsValidAfter` / a session index
  by `sid`.
- `acr`/`amr` acceptance to skip local MFA; step-up via OIDC.
- Durable lockout counters; split `JWT_SECRET` usages; break-glass.

Rollback: disable the Agit8or Identity `OidcProvider` row; local login and
other providers are unaffected.

---

## Phase D — SSO between Clientst0r and Rem0te

- Both apps registered at the same OP; a user assigned to both apps signs in
  once and reaches the other via `prompt=none` (ARCHITECTURE.md §6.2).
- Existing deep links from Clientst0r to Rem0te (and back) gain an
  `sso=1` hint so the target starts silent auth instead of showing its local
  login form. No token or user identifier travels in the link.
- RP-initiated logout from either app ends the IdP session and the other
  app's session via back-channel logout.
- Interop test plan: REM0TE_HANDOFF.md §3.
- Connect is unaffected: delegation JWS continues to be issued by Clientst0r
  from the technician's local session; add optional `usr_iss`/`usr_sub`/
  `usr_acr`/`usr_auth_time` claims only after the Connect protocol owner
  agrees (coordinate through the Connect docs).

Rollback: remove the `sso=1` hint; each app still supports its own SSO login.

---

## Phase E — Enforcement, per org (optional)

Per OP org (MSP) and per app install, three modes:

| Mode | Behaviour |
|---|---|
| `off` | No SSO (default) |
| `optional` | SSO and local logins both allowed |
| `enforced` | Staff must sign in via SSO; local password login refused for staff except `break_glass` accounts at the separate break-glass URL; Azure/LDAP direct logins disabled for staff |

Preconditions before an org can be switched to `enforced` (checked by the
app and shown in the UI): every active staff user is linked; break-glass
account exists and its drill passed in the last 90 days; back-channel logout
tested; OP backup restore tested.

Additions in this phase: optional `sid` liveness check for high-privilege
sessions; back-channel logout on app unassignment where the OP supports it;
`phr` (passkey) requirement option for admins.

Rollback: set the mode back to `optional`; local logins return immediately.

---

## Phase F — Customer portal users

Decide (owner) whether portal/customer users move to the OP. If yes: portal
users are users of the **MSP's own Zitadel org** (no separate customer orgs),
authorised via a dedicated portal project (or portal role keys on a
sub-project) and tied to their customer by per-customer membership claims;
separate OIDC client for the portal host; `user_type=org_user` guard
unchanged; MSP org managers administer them. MFA policy for
customers set per MSP. Local portal login remains available per customer.

Rollback: disable the portal client; portal users sign in locally.

---

## Phase G — SCIM / provisioning

Only where it earns its keep. Free OPs generally do not ship a full SCIM
*server* for downstream apps; options:

1. Keep JIT + login-time reconciliation (default — already removes access on
   next login and kills sessions via back-channel logout).
2. Apps expose a SCIM 2.0 `/Users` + `/Groups` endpoint (subset: create,
   patch `active`, delete) so a provisioning job can pre-create and
   deprovision users without waiting for a login. Authenticated with a
   Connect-style client credential, **not** a user token.
3. OP event stream (Zitadel events / Keycloak admin events) → small
   provisioning worker → app SCIM endpoints.

Rollback: disable the SCIM endpoint; JIT continues.

---

## Summary of rollbacks

| Phase | Rollback switch | Data left behind |
|---|---|---|
| A | stop OP | none in apps |
| B | disable Clientst0r provider | inert `ExternalIdentity`, tagged memberships |
| C | disable Rem0te provider row | inert rows |
| D | drop `sso=1` hint | none |
| E | mode → `optional` | none |
| F | disable portal client | inert links |
| G | disable SCIM endpoint | none |
