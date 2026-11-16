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

## Phase A — Keycloak deployment (requires explicit approval)

**First step: find out where the shared Keycloak runs** (URL, version, realm;
ARCHITECTURE.md §13 Q1). Rem0te plans to use Keycloak, but no configuration
or container exists on the Rem0te repo/host yet. If an instance already
exists, Phase A becomes "validate it against the gates below and add the
Clientst0r client"; if not, deploy one as described here, and Rem0te targets
the same instance.

### A.1 Validation gates (local test instance; no production impact)

Run Keycloak (target version, ≥ 26.2) in a local test environment on this
server's dev side (no disposable cloud VM) with both apps on test configs.
Record results in this directory. All gates must pass before production:

1. **Organizations behaviour.** Organizations enabled on realm `agit8or`;
   the `organization` scope / Organization Membership mapper emits alias
   **and** id; `organization:<alias>` scope limits the token to that org;
   membership is required for the org to appear; removing membership removes
   it from the next token.
2. **Multi-org user.** One user in two Organizations with different
   prefixed client roles in each; each app's token carries only that app's
   client roles (`Full scope allowed` off) and the adapter normalises both
   orgs correctly; Clientst0r pinned to org A ignores org B.
3. **Back-channel logout to both apps.** `logout_token` with `sid` and `sub`
   reaches Clientst0r and Rem0te on: RP-initiated logout from either app,
   admin "sign out" of a user (`POST /admin/realms/agit8or/users/{id}/logout`),
   deleting a single session, and disabling a user (if disabling does not
   trigger it, the runbook is "disable, then logout").
4. **Admin isolation between MSPs.** With fine-grained admin permissions v2,
   an MSP A admin can manage users/members of org A and map only `acme-msp:*`
   client roles, and **cannot** view or change MSP B users, map other
   prefixes or realm roles, edit clients, flows, mappers, keys or realm
   settings, or impersonate. If this cannot be achieved, fall back to
   realm-per-MSP (ARCHITECTURE.md §3 option B) — or a small MSP-admin UI on
   the Admin REST API — before go-live.
5. **Assurance.** ACR-to-LoA mapping emits `urn:agit8or:acr:pwd|mfa|phr`
   for password, password+TOTP/WebAuthn and passkey sign-in; the AMR mapper
   emits consistent `amr`; `acr_values`, `max_age` and `prompt=login` force
   the right step-up.
6. **Assignment gate.** A user without any of a client's roles is denied at
   Keycloak by the per-client flow ("Condition – user role" → "Deny
   access"), and `prompt=none` returns an error instead of a session.
7. **Brute-force detection** locks temporarily per the policy and unlocks;
   login/admin events are recorded with the expected detail.
8. **Footprint, backup, restore.** Memory/CPU on the target host under a
   login burst; `pg_dump` + realm export restore into a scratch instance and
   existing tokens/sessions behave as expected.

### A.2 Tenancy

Single realm `agit8or`, one Organization per MSP (ARCHITECTURE.md §3).
First Organization: the owner's MSP (= the owner's Clientst0r install +
Rem0te tenant). Realm-per-MSP or a separate Keycloak per MSP is the
isolation option for MSPs that require it; the apps need no change.

### A.3 Sizing

Keycloak is a JVM service: plan ~1–1.5 GB heap plus overhead, CPU dominated
by password hashing during login bursts.

| Host | Keycloak | Postgres | Total budget | Notes |
|---|---|---|---|---|
| **Separate VM (recommended)** | 2 vCPU, 2 GB RAM (`-Xmx` ~1.25 GB / `MaxRAMPercentage`) | 1 GB RAM, 20 GB disk | 2 vCPU / 4 GB / 40 GB | Isolates the OP from app outages and app compromise; easiest to back up and to make HA later (add a second node + replica) |
| Shared 4 vCPU / 7 GB Clientst0r host | **Not recommended**: needs ~1.5–2 GB + Postgres ~0.5 GB | | ~2–2.5 GB added | Competes with gunicorn, Collabora and SQLite write load (known login-400 issue under long writes); an app compromise on the host reaches the OP |

Native install (Keycloak distribution as a systemd service, `kc.sh build`
optimised start, Postgres) is the default; the official container image is
fine if the owner prefers. TLS via Nginx on a dedicated hostname (e.g.
`id.<domain>`), `KC_PROXY_HEADERS=xforwarded`, HSTS, admin console reachable
only from the admin network (separate hostname via `KC_HOSTNAME_ADMIN` or
proxy path restriction), no other vhosts sharing cookies.

### A.4 Baseline configuration (as code)

- Master realm: only for instance administration; two named platform admins
  with passkeys; never used by apps.
- Realm `agit8or`: Organizations on; policies per ARCHITECTURE.md §3
  "Keycloak configuration baseline" (MFA, passkeys, TOTP, password policy,
  brute-force detection, session lifetimes, events).
- Clients: `clientst0r-<alias>` per Clientst0r install, `rem0te` (one per
  Rem0te deployment); confidential, Standard Flow + PKCE S256, exact
  redirect/post-logout URIs, back-channel logout URL + session required,
  `Full scope allowed` off, per-client assignment-gate flow.
- Client roles named `<alias>:<role>` (initial: Clientst0r `msp_admin`,
  `technician`, `readonly`; Rem0te `operator_admin`, `technician`,
  `business_owner`) granted through groups per MSP.
- Client scopes `organization` + `agit8or` (AMR + client-roles mappers).
- Provisioning scripted (`kcadm.sh` / Admin REST) and stored in git;
  nightly realm export.
- Backups + restore test (ARCHITECTURE.md §11.2) before any app is pointed
  at it.

### A.5 Rollback

Stop the instance (or remove the Clientst0r client if the instance is shared
with Rem0te). No app depends on it yet.

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

- `OIDCProvider` config (issuer = Keycloak realm URL, client id, secret/private key, scopes,
  `jit_enabled`, **pinned MSP Keycloak Organization id + alias** (exactly one — set in the setup
  wizard, changed only via a second-admin protected change),
  `min_acr_for_2fa`, enabled flag). Tokens without that org are refused.
- Customer mapping UI: each `core.Organization` (customer) can be given its
  identity customer key so client roles `<alias>:customer:<key>:<role>` map
  to `Membership` rows.
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
Phase A local test Keycloak on this server.

### B.5 Azure AD

Fix the email-based matching first (CS-ID-01), independent of Identity. Later
options: keep Azure as a direct login, or broker Azure through Keycloak as an
identity provider (Entra ID as upstream OIDC IdP) and retire the direct path (open question in ARCHITECTURE.md).

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
users are members of the **MSP's own Keycloak Organization** (no separate
customer orgs), authorised via client roles on a dedicated portal client
(`portal-<alias>`, e.g. `<alias>:customer:<key>:portal_user`) on the portal
host; `user_type=org_user` guard unchanged; MSP admins manage them via
FGAP v2. MFA policy for
customers set per MSP. Local portal login remains available per customer.

Rollback: disable the portal client; portal users sign in locally.

---

## Phase G — SCIM / provisioning

Only where it earns its keep. Keycloak does not ship a SCIM client that
pushes to downstream apps; options:

1. Keep JIT + login-time reconciliation (default — already removes access on
   next login and kills sessions via back-channel logout).
2. Apps expose a SCIM 2.0 `/Users` + `/Groups` endpoint (subset: create,
   patch `active`, delete) so a provisioning job can pre-create and
   deprovision users without waiting for a login. Authenticated with a
   Connect-style client credential, **not** a user token.
3. Keycloak admin events (event listener SPI, or polling the Admin REST
   events API) → small provisioning worker → app SCIM endpoints.

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
