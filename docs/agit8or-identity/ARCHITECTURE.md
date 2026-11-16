# Agit8or Identity — Architecture

> **Status: design / planned. Nothing in this document is implemented.**
> No IdP is deployed, no app has an Agit8or Identity client, and no
> production change is made by this document. Deployment (MIGRATION.md
> Phase A) requires explicit approval from the owner.
>
> Inputs: the Clientst0r + Rem0te authentication audit and IdP evaluation
> (2026-11-16), the Agit8or Connect audits for both apps (2026-11-16), and the
> product brief. File/line pointers for Rem0te come from a read-only audit and
> must be re-checked by the Rem0te session before work starts.

Companion documents in this directory:

| File | Purpose |
|---|---|
| `ARCHITECTURE.md` | This file — components, trust boundaries, IdP decision, claims contract, flows, separation from Connect, break-glass, threat model |
| `MIGRATION.md` | Phased rollout (A–G) with backward compatibility and rollback per phase |
| `CLIENTST0R_TASKS.md` | Concrete Clientst0r task list with file pointers |
| `REM0TE_HANDOFF.md` | Proposed task list for the Rem0te session (not sent) + interop test plan |
| `IMPLEMENTING.md` | Adoption checklist and conformance tests for any future Agit8or app |

---

## 1. What Agit8or Identity is (and is not)

Agit8or Identity is the **human** single sign-on layer for every Agit8or
application: Clientst0r, Rem0te, Office Unbound, ExploitHound,
MailThreatZero, Roots-HQ, m0nitor and MyAppDone. It is built on an existing,
self-hosted, open-source OpenID Connect Provider (OP); we do not write an
authentication engine.

**Centralised in Identity:** users, authentication, MFA (TOTP, WebAuthn /
passkeys), password policy, account recovery, IdP sessions, tenant (MSP)
memberships, groups, application assignments, coarse role/group grants,
suspension, deactivation, login history, authentication security events.

**Distributed (stays in each app):** authorisation. Every app keeps its own
permission model and enforces it on every request. Identity tells an app *who
the user is, how strongly they authenticated, which MSP organisations they
belong to and whether they are assigned to this app*; the app decides *what
they may do*.

**Explicitly not Identity:**

- Not app-to-app authentication. That is **Agit8or Connect** (separate
  issuer, keys, audiences, stores, admin — see §9).
- Not a replacement for mobile app tokens (`api_mobile.MobileAuthToken`),
  Rem0te `rk_` public API keys, agent enrolment, or integration HMAC/JWS
  credentials. Those are untouched.
- Not an "implicit access" system. Signing into one app never grants access
  to another; every app requires an explicit assignment per user per org.

### Standards

OIDC Core 1.0 + Discovery; OAuth 2.1 profile (Authorization Code + PKCE S256
only, no implicit, no ROPC, exact redirect URI match); OIDC RP-Initiated
Logout 1.0; OIDC Back-Channel Logout 1.0; `acr_values` / `max_age` / `amr`
(RFC 8176) for step-up; WebAuthn L2 / passkeys and TOTP (RFC 6238) at the
IdP; SCIM 2.0 (RFC 7643/7644) only in Phase G and only where it earns its
keep.

---

## 2. Components and trust boundaries

```
                         ┌───────────────────────────────────────────────┐
                         │  TRUST BOUNDARY 1 — Agit8or Identity (OP)      │
                         │                                               │
   Browser ──TLS────────►│  OIDC endpoints (authorize, token, jwks,      │
   (user agent;          │  userinfo, end_session)                       │
    holds only IdP       │  Login UI: password + TOTP + passkeys         │
    session cookie,      │  Admin console (platform admins / MSP admins) │
    app session cookies) │  Claims adapter (Actions / protocol mappers)  │
                         │  Session store, signing keys (ID tokens only) │
                         │  Postgres (users, orgs, grants, sessions,     │
                         │  events)  ── encrypted backups ──► offsite    │
                         └────────┬───────────────────────┬──────────────┘
                 ID token (aud=   │  back-channel logout  │  ID token (aud=
                 clientst0r)      │  POST logout_token    │  rem0te)
                                  ▼                       ▼
 ┌──────────────────────────────────────┐   ┌──────────────────────────────────────┐
 │ TRUST BOUNDARY 2 — Clientst0r (RP)    │   │ TRUST BOUNDARY 3 — Rem0te (RP)        │
 │ OIDC client (Authlib) + adapter        │   │ openid-client 6.x SSO module          │
 │ ExternalIdentity(iss, sub) → User      │   │ ExternalIdentity(issuer, subject)     │
 │ Mapping → Membership / RoleTemplate    │   │ OidcGroupMapping → Membership/Role    │
 │ Local authz: permission_registry,      │   │ Local authz: capabilities, Role,      │
 │   rmm_permissions, tech_access         │   │   ConfirmPolicy, approval-signer      │
 │ Django DB sessions + IdP sid index     │   │ JWT cookie + sessionsValidAfter       │
 │ Break-glass local admin (sealed)       │   │ Break-glass local admin (sealed)      │
 │ Local login fallback (password+TOTP,   │   │ Local login fallback (password+MFA)   │
 │   Azure, LDAP) during migration        │   │                                       │
 └──────────────────┬───────────────────┘   └───────────────────┬──────────────────┘
                    │                                           │
                    │   TRUST BOUNDARY 4 — Agit8or Connect       │
                    └──────► signed requests + delegation ◄─────┘
                             assertions (Ed25519, own keys,
                             own audiences, own revocation)
                             — NEVER accepts Identity tokens —
```

```mermaid
flowchart LR
  B[Browser] -->|authorize + PKCE| IDP[(Agit8or Identity OP)]
  IDP -->|code| B
  B -->|code| CS[Clientst0r RP]
  B -->|code| RR[Rem0te RP]
  CS -->|token exchange code+verifier| IDP
  RR -->|token exchange code+verifier| IDP
  IDP -. back-channel logout_token .-> CS
  IDP -. back-channel logout_token .-> RR
  CS <-->|Agit8or Connect: signed requests, delegation JWS| RR
  classDef b fill:#eef,stroke:#447
  class IDP b
```

Trust rules between boundaries:

1. The OP is trusted **only** for authentication facts and coarse grants, and
   only via signed ID tokens validated against the OP's JWKS (pinned issuer).
2. An app never trusts another app's session, cookie or token. SSO between
   apps happens only through the OP session (silent `prompt=none`).
3. An app never forwards a user's ID token or access token to another app.
   App-to-app traffic uses Connect credentials (§9).
4. The browser is never trusted with tokens: no tokens in URLs (other than
   the one-time `code` and `state`), no tokens in `localStorage` /
   `sessionStorage`. Tokens live server-side; the browser holds only
   HttpOnly, Secure, SameSite cookies.

---

## 3. IdP choice — ADR-ID-001

**Status:** accepted by the owner (2026-11-16): **Zitadel**, with Keycloak as
fallback. The Phase A spike gates below still have to pass before production;
a failed gate switches to Keycloak.

### Context

We need a free, self-hostable, certified OIDC OP with: TOTP + passkeys,
native multi-organisation support with delegated (per-org) admin, org-scoped
roles/app assignments, session revocation APIs, back-channel logout, audit
events, Postgres storage, and a footprint that can share a 4 vCPU / 7 GB host
if needed. No paid licensing.

### Options considered

| Option | Fit | Concerns |
|---|---|---|
| **Zitadel** | Organisations are first-class with org managers (delegated admin); projects, roles, project grants (share an app with another org) and user grants (= application assignment); "check for project / check roles on authentication" gate login on assignment; passkeys + TOTP; OpenID-certified; Go binary, light (~0.5–1 GB RAM + Postgres); Actions to shape custom claims | **Licence must be re-verified**: Zitadel announced a move from Apache-2.0 to **AGPL-3.0** for v3+. Unmodified self-hosting is free, but modifications served over a network carry source obligations — acceptable if we never patch it, but the owner must confirm. A Zitadel user has one owning org; "one person, several MSPs with different roles" must be proven in the spike (grants across orgs vs. duplicate accounts). Back-channel logout support and its exact semantics must be confirmed on the chosen version. |
| **Keycloak** (fallback) | Most mature; Apache-2.0; certified; back-channel logout, `acr`/LoA step-up flows, admin REST session logout, Organizations (v26+, users can belong to several orgs), fine-grained admin permissions v2 | JVM, 1–2 GB RAM; realm/org modelling heavier; delegated per-org admin is newer and more manual to lock down |
| Authentik | Good UX, flows | Multi-tenancy is an enterprise feature → fails "no paid licensing" |
| Ory (Hydra/Kratos/Keto) | Very flexible | A toolkit, not a product: we would build login UI, admin, org model — too close to a custom engine |
| Authelia | Light | No multi-tenancy, limited admin; not an IdP for many MSPs |

### Decision

**Zitadel** is the primary OP and **Keycloak** the documented fallback
(the owner confirmed this). Phase A begins with a time-boxed spike that must pass these gates
before Zitadel is accepted; failing any gate switches to Keycloak:

1. Licence re-checked and acceptable to the owner (AGPL-3.0 for v3+ vs. pinning an
   Apache-2.0 release — pinning an old release is **not** acceptable long
   term because it stops security fixes).
2. One human can hold different roles in two MSP orgs without two accounts
   (or the owner accepts per-MSP accounts, see open questions).
3. OIDC Back-Channel Logout delivers a `logout_token` with `sid` and `sub` to
   each RP on IdP session termination and on admin "terminate sessions".
4. Org managers of MSP A cannot see or change anything in MSP B (tested via
   the admin API with an MSP A manager token).
5. `amr` / `acr` values are emitted predictably for password, password+TOTP
   and passkey logins, and `max_age` / `prompt=login` force re-authentication.
6. Footprint fits the chosen host (MIGRATION.md §A.2).

### App-side design is IdP-neutral

Apps integrate with **any certified OIDC OP**. Everything IdP-specific is
isolated in a small **claims/admin adapter** on each side:

| IdP-specific concern | Where it is isolated | Zitadel shape | Keycloak shape |
|---|---|---|---|
| Org / role claim shape | OP side: a claims action/mapper emits the normalised `agit8or` claim (§4). App side: `adapter.normalise(claims)` as fallback when the OP cannot be customised | `urn:zitadel:iam:org:project:{projectId}:roles` → `{role: {orgId: domain}}`, `urn:zitadel:iam:user:resourceowner:id`; Actions v2 add `agit8or` | Organization membership mapper (`organization` claim), group / client-role mappers; script or hardcoded mapper adds `agit8or` |
| Application assignment gate | OP project/client setting + app re-check | Project "check authorization on authentication" + user grants | Client role required via authentication flow condition, or org-scoped client access |
| Session revocation API (admin "kill sessions") | OP admin runbook + adapter `terminate_user_sessions(sub)` | Session API v2 / user sessions endpoints | `POST /admin/realms/{r}/users/{id}/logout` |
| Back-channel logout | Standard on the RP side (§6); only registration differs | Per-app back-channel logout URI (confirm in spike) | Client "Backchannel logout URL", "session required" on |
| Delegated admin | OP admin model; documented in runbook, not in apps | Org managers (ORG_OWNER / ORG_USER_MANAGER), IAM managers for platform | Fine-grained admin permissions v2 / org admins |
| `acr` values | Mapping table in adapter config | Confirm emitted values in spike | LoA mapping (`acr` → level) |

If the OP is replaced, only the adapter and runbooks change; app models,
mapping tables and flows do not.

### Deployment topologies (both supported by the same app-side design)

The basic unit is **one MSP = one Zitadel Organization = one Clientst0r
install (one VM) + that MSP's Rem0te tenant and its businesses**. Clientst0r
always serves exactly one MSP; its `core.Organization` rows are that MSP's
customers.

| Topology | Description | When |
|---|---|---|
| **T1 — Shared Zitadel, many MSPs** | One Zitadel instance (platform operated by Agit8or). Each MSP is a Zitadel Organization with its own org managers. App projects (`clientst0r`, `rem0te`, …) are owned by the platform org and **granted** to each MSP org (project grant); each MSP org assigns its own users (user grants). Each Clientst0r install has its own OIDC client (own redirect URIs) and is pinned to its MSP's org id. | Hosted/managed offering; MSPs that want Agit8or-run SSO |
| **T2 — One Zitadel per MSP** | The MSP runs its own Zitadel (on its own VM or alongside its Clientst0r VM). It still contains one MSP Organization (plus the instance's default org); projects are local. Apps are pinned to that issuer **and** that org id. | Self-hosting MSPs that want full control, separate failure domain, or data-residency isolation |

In both topologies the apps pin **issuer + MSP org id**; nothing else in the
app changes. T1 gives one human (e.g. a contractor working for two MSPs) one
login; T2 gives the strongest isolation (separate keys, DB, admins, outage
domain) at the cost of running one OP per MSP. Rem0te, if it hosts several
MSPs as `Tenant`s, can trust several issuers (T2) or several org ids under one
issuer (T1) — one binding per `Tenant`.

---

## 4. Claims contract (v1)

Apps validate the ID token (signature via JWKS, `iss` exact match, `aud`
contains this app's client_id, `azp` = client_id when multiple audiences,
`exp`, `iat` skew ≤ 120 s, `nonce` matches, `alg` in an allowlist —
`RS256`/`ES256`/`EdDSA`, never `none`, never `HS*`).

### Standard claims used

| Claim | Use | Required |
|---|---|---|
| `iss` | Pinned per configured provider; part of the identity key | yes |
| `sub` | Stable, never-reassigned user id; part of the identity key `(iss, sub)` | yes |
| `aud`, `azp` | Must be this app's client id | yes |
| `email` | Display + JIT username suggestion only. **Never** used to link or match accounts | yes |
| `email_verified` | Must be `true` for JIT provisioning | yes for JIT |
| `name`, `given_name`, `family_name` | Profile display | no |
| `amr` | How the user authenticated (`pwd`, `otp`, `hwk`, `swk`, `user`, `mfa`, …) | yes |
| `acr` | Assurance level achieved (normalised, below) | yes |
| `auth_time` | Time of last interactive authentication; freshness checks for step-up | yes |
| `sid` | IdP session id; stored with the app session; key for back-channel logout | yes |

### Normalised assurance levels (`acr`)

Apps compare against these names; the adapter maps the OP's native values.

| `acr` | Meaning |
|---|---|
| `urn:agit8or:acr:pwd` | Single factor (password or social) — **not accepted by any app for staff in production** |
| `urn:agit8or:acr:mfa` | Two factors (password + TOTP, or password + passkey as second factor) |
| `urn:agit8or:acr:phr` | Phishing-resistant: passkey / hardware key as the authenticator (`amr` contains `hwk` or `swk` with user verification) |

Apps derive MFA from `acr` **and** cross-check `amr` (an `acr` of `mfa`/`phr`
with an `amr` containing only `pwd` is rejected as inconsistent).

### Custom claim `agit8or` (versioned)

Emitted into the ID token (and userinfo) **for the requesting client only** —
a token for Clientst0r never lists the user's Rem0te or ExploitHound
assignments.

```json
{
  "agit8or": {
    "v": 1,
    "app": "clientst0r",
    "status": "active",
    "platform_admin": false,
    "orgs": [
      {
        "id": "312874650912345678",
        "slug": "acme-msp",
        "kind": "msp",
        "assigned": true,
        "roles": ["msp_admin", "technician"],
        "customers": null
      },
      {
        "id": "312874650998765432",
        "slug": "contoso-msp",
        "kind": "msp",
        "assigned": true,
        "roles": ["technician"],
        "customers": [
          {"id": "cust-ext-0193", "roles": ["technician"]},
          {"id": "cust-ext-0207", "roles": ["readonly"]}
        ]
      }
    ]
  }
}
```

Rules:

- `v` — contract version. Apps reject unknown major versions (fail closed to
  "no SSO login", local login still works). Additive fields are allowed
  within a version; apps ignore unknown fields.
- `app` — must equal the app's configured app key (defence in depth on top of
  `aud`).
- `status` — `active` only; anything else is refused (the OP should not issue
  tokens for suspended users anyway).
- `platform_admin` — Identity platform administrator. **Apps must not map
  this to app superuser automatically**; it is informational / for audit
  unless an app's local mapping table explicitly says otherwise.
- `orgs[].id` — OP organisation id (immutable). `slug` is display only.
- `orgs[].assigned` — the user has an explicit application assignment for
  this app in this org. Entries with `assigned: false` are not emitted in v1
  (reserved).
- `orgs[].roles` — coarse, app-scoped role keys granted in that org. Apps map
  them to local roles through a mapping table; unmapped keys grant nothing.
- `orgs[].customers` — per-customer membership inside that MSP for this app:
  `null` = no customer-level statement from the IdP (all customers the
  local role allows); otherwise a list of entries
  `{"id": "<customer ext id>", "roles": ["<role key>", …]}` (v1 also accepts
  a bare id string meaning "no extra roles"). In Zitadel these come from
  role keys / groups inside the MSP's org (e.g. role key
  `customer:<ext-id>:<role>` on the app project, normalised by the claims
  action). The app maps each entry through its mapping table to a local
  customer membership. For staff it is a **ceiling**: the app intersects it
  with local scope and it never widens a staff role's reach beyond what the
  mapping allows.
- Size budget: if the claim would exceed ~4 KB the OP emits
  `"orgs_ref": "userinfo"` and apps fetch it from userinfo during the code
  exchange (server-side; never via the browser).

Clientst0r is pinned to exactly one MSP org id at setup and **rejects any
token whose `agit8or.orgs[]` does not contain that org id with
`assigned=true`**; other org entries are discarded before mapping.

Login is scoped to one org at a time where the app needs it: the app passes
an org hint (`urn:zitadel:iam:org:id:{id}` scope in the Zitadel adapter;
`organization` / `kc_org` hint in Keycloak) and still re-checks the claim.

---

## 5. Claim → local mapping (apps keep authorisation)

### 5.1 Common rules (both apps, every future app)

1. **Account linking is strictly by `(iss, sub)`.** Never by email, username
   or display name. A new `(iss, sub)` with an email equal to an existing
   local user's email is **not** linked automatically; it goes to the linking
   flow (MIGRATION.md §B.3) or is refused.
2. **JIT provisioning** only when all hold: provider has JIT enabled,
   `email_verified=true`, `agit8or.orgs[]` contains at least one org with
   `assigned=true` that is bound to this install/tenant, and the mapping
   table yields at least one local role. Otherwise: no account, audited
   refusal.
3. **Mapped memberships are tagged with their source** (`source=oidc`,
   mapping id). On each login the app reconciles only the memberships it
   created from mappings; manually granted memberships are never removed by
   SSO. (Same pattern as Clientst0r's `Membership.ldap_group_mapping`.)
4. **Removal is immediate on next login and on back-channel logout**: if an
   org/role disappears from the claim, the mapped membership is deactivated.
   Suspension at the IdP + back-channel logout kills current sessions (§7).
5. **Local re-check on every request.** The app's session carries the local
   user id only; membership and permissions are evaluated from the local DB
   per request as today. A cached claim is never an authorisation input after
   login.
6. **Install/tenant binding.** Each app install or app tenant is bound to an
   explicit OP issuer + org id (Clientst0r: exactly one, pinned at setup;
   Rem0te: one per `Tenant`). Tokens without the bound org are refused;
   claims for any other org are ignored even if the token is otherwise
   valid.

### 5.2 Clientst0r

Current model (verified in `.wt-connect`, dev-work v3.17.687):
`accounts/models.py` — `Membership` (:47, unique user+organization, `role`,
`role_template`, `additional_roles`, `record_scope`, `ldap_group_mapping`),
`UserProfile` (:462, `user_type` staff / org_user :469, `global_role_template`
:477, `client_scope` :497, `azure_ad_oid`), `RoleTemplate` (:834),
`LDAPGroupMapping` (:2379). **A Clientst0r install serves exactly one MSP**
(one install per VM); its `core.Organization` rows are that MSP's
**customers**. The install's OIDC provider config pins one issuer and one
Zitadel org id (the MSP) at setup; changing it is a protected change
(second-admin approval).

| Identity input | Clientst0r target |
|---|---|
| `(iss, sub)` | New `accounts.ExternalIdentity(provider, issuer, subject, user, last_login_at, last_sid)`, unique `(issuer, subject)` |
| Token without the pinned MSP org id (assigned) | Refused — no login, audited `auth.sso.login_refused reason=org_mismatch` |
| Pinned MSP org id + role key (e.g. `technician`) | New `OIDCRoleMapping(provider, idp_org_id, role_key, → user_type=staff, global_role_template, client_scope)` — staff users |
| Pinned MSP org id + `customers[]` entries (per-customer membership claims/groups within the MSP's Zitadel org) | `core.Organization` resolved by a stored customer external id (new `Organization.identity_customer_key`, set when the admin maps the customer) → `Membership(role_template from mapping, source=oidc, oidc_mapping=…)` |
| `email`, names | `User.first_name/last_name`, `User.email` (display only; updating email never re-links) |
| `amr`/`acr`/`auth_time`/`sid` | Session keys used by `Enforce2FAMiddleware` and step-up (§8) |
| Org users (`user_type=org_user`) | Via `customers[]` mappings; **customer portal users stay local in Phase B–E**; in Phase F they are users of the same MSP Zitadel org (or of a dedicated portal sub-project) — §10 |

Superuser (`is_superuser`) is **never** granted via SSO mapping. Superuser
remains a local designation and goes through the existing Superuser Approval
flow.

### 5.3 Rem0te

Current model (from audit; verify): `ExternalIdentity(issuer, subject)` unique,
`OidcProvider` with `groupsClaim`, `OidcGroupMapping`; `Tenant` (MSP operator,
schema.prisma:352), `Customer` (business, :592), `User` (:425, `status`,
`isPlatformAdmin`, `platformPermissions`, `sessionsValidAfter`), `Membership`
(:560, unique user+tenant, one `customerId`, capabilities), `Role`
PLATFORM_ADMIN / BUSINESS_OWNER / BUSINESS_USER, `TechnicianAssignment`.

| Identity input | Rem0te target |
|---|---|
| `(iss, sub)` | Existing `ExternalIdentity(issuer, subject)` — already never links by email |
| OP org id | `Tenant` binding (new `Tenant.identityOrgId` or provider-level allowlist) |
| `orgs[].roles` | Extend `OidcGroupMapping` to read `agit8or.orgs[].roles` (claim path) instead of a flat `groupsClaim`; maps to `Role` + capability set |
| `orgs[].customers` | Ceiling on `Membership.customerId` / technician assignments; never widens |
| `platform_admin` | **Not** mapped to `isPlatformAdmin`. Rem0te platform admin stays local + break-glass |
| Capabilities, TechnicianAssignment, ConfirmPolicy, approval-signer quorum | Stay local, unchanged |

---

## 6. SSO, logout and session flows

### 6.1 Login to Clientst0r (first app)

```
User        Browser            Clientst0r              Identity (OP)
 │  open /     │                    │                        │
 │────────────►│  GET /             │                        │
 │             │───────────────────►│ no session             │
 │             │◄── 302 /account/oidc/login/?next=/          │
 │             │───────────────────►│ make state, nonce,     │
 │             │                    │ code_verifier (server- │
 │             │                    │ side session only)     │
 │             │◄── 302 /authorize?response_type=code&client_id=clientst0r
 │             │      &redirect_uri=…&scope=openid email profile agit8or
 │             │      &state=…&nonce=…&code_challenge=S256(…)&acr_values=urn:agit8or:acr:mfa
 │             │────────────────────────────────────────────►│ login UI:
 │             │                                             │ password +
 │◄───────── credentials / passkey / TOTP ─────────────────►│ TOTP/passkey
 │             │◄── 302 redirect_uri?code=…&state=…  (IdP session cookie set)
 │             │───────────────────►│ check state; POST /token
 │             │                    │ (code + code_verifier + client auth)
 │             │                    │───────────────────────►│
 │             │                    │◄── id_token (+access)  │
 │             │                    │ validate (§4); map (§5);│
 │             │                    │ create Django session;  │
 │             │                    │ store sid, auth_time,   │
 │             │                    │ acr, amr; rotate key    │
 │             │◄── 302 /  (Set-Cookie: sessionid; HttpOnly; Secure; SameSite=Lax)
```

Client authentication at the token endpoint: `private_key_jwt` preferred,
`client_secret_basic` acceptable in Phase B. Tokens returned by the token
endpoint are kept server-side (Clientst0r stores none after login except what
is needed for RP-initiated logout — the `id_token` hint can be replaced by
`client_id` + `logout_hint` where the OP supports it).

### 6.2 Silent SSO into Rem0te (second app)

```
Browser (already has IdP session)        Rem0te                 Identity
 │ open rem0te.example/                    │                         │
 │────────────────────────────────────────►│ no Rem0te session        │
 │◄── 302 /authorize?…&prompt=none&state&nonce&PKCE                  │
 │──────────────────────────────────────────────────────────────────►│ valid IdP
 │                                                                   │ session AND
 │                                                                   │ user assigned
 │                                                                   │ to rem0te?
 │◄── 302 /sso/callback?code=…  ─── or ─── ?error=login_required /  │
 │                                          interaction_required /   │
 │                                          access_denied            │
 │────────────────────────────────────────►│ exchange, validate aud=rem0te,
 │                                         │ map, set Rem0te cookie   │
```

- `prompt=none` success requires an existing IdP session **and** an
  assignment for Rem0te. Without the assignment the OP returns an error and
  Rem0te shows "you are not assigned to this application" — logging into
  Clientst0r granted nothing.
- On `login_required` / `interaction_required` Rem0te falls back to an
  interactive authorize (or its local login page during migration).
- If Rem0te requires a stronger `acr` than the existing IdP session holds,
  it sends `acr_values` and the OP prompts for the missing factor.
- Silent auth is a top-level redirect, not an iframe (third-party cookie
  restrictions make iframe-based checks unreliable and we do not depend on
  them).

### 6.3 Logout

**RP-initiated** (user clicks Sign out in any app): the app kills its own
session first, then redirects to the OP `end_session_endpoint` with
`client_id`, `post_logout_redirect_uri` (pre-registered) and `state`. The OP
ends the IdP session and fires back-channel logout to every other RP that has
a session under that `sid`.

**Back-channel** (required for every app): `POST /…/oidc/backchannel-logout/`
with form field `logout_token` (a JWT). The app:

1. Validates signature (OP JWKS), `iss`, `aud` = own client id, `iat` within
   skew, `events` contains `http://schemas.openid.net/event/backchannel-logout`,
   **no** `nonce` claim, at least one of `sid` / `sub`.
2. Rejects replays by `jti` (unique store, TTL ≥ token lifetime).
3. Kills every local session matching `(iss, sid)`; if only `sub` is present,
   kills every session of the user linked to `(iss, sub)`.
4. Returns `200` (or `204`), `Cache-Control: no-store`; `400` on invalid
   tokens. Never redirects; CSRF-exempt but accepts only this POST shape.
5. Audits `auth.sso.backchannel_logout` with sid/sub and sessions killed.

Front-channel logout (iframes) is **not** used.

### 6.4 Session lifetime alignment

| Session | Today | Proposed |
|---|---|---|
| IdP SSO session | n/a | absolute 10 h, idle 2 h (OP config) |
| Clientst0r web | idle 60 min, absolute 480 min (`SessionIdleTimeoutMiddleware`, `config/settings.py:398-404`) | unchanged, **and** never longer than the IdP session: at absolute expiry the user is re-authenticated (silent `prompt=none` keeps it seamless while the IdP session lives) |
| Rem0te web | 8 h JWT cookie (`cookies.ts:7`) | unchanged, capped the same way |
| Step-up freshness | Clientst0r `FRESH_AUTH_SECONDS = 300` (`tech_access/protected.py:43`); Rem0te step-up cookie 10 min | per-action `max_age` (default 300 s), checked against `auth_time` |

App sessions are always killable independently of the IdP (local sign-out,
admin revoke, back-channel logout).

---

## 7. Revocation paths

| Trigger | Path | Result |
|---|---|---|
| User signs out in one app | RP-initiated logout → OP ends IdP session → back-channel logout to other RPs | All app sessions under that `sid` end |
| MSP admin suspends / deactivates a user at the IdP | OP terminates the user's sessions → back-channel logout (`sub`) to every RP | All app sessions end; new logins refused by OP; next app login (if any slipped through) sees no token |
| Platform/MSP admin "terminate sessions" for a user | Same as above without suspension | All sessions end; user can log in again |
| Back-channel delivery fails (app down) | App sessions keep living until local expiry — **mitigation**: apps re-validate at absolute timeout via silent auth; Phase E adds a short app-side `sid` liveness check (OP introspection / session API through the adapter) for high-privilege sessions; OP retries per its policy | Bounded exposure ≤ app absolute timeout (8 h) without mitigation, ≤ check interval with it |
| App-local admin revokes a user | Clientst0r: new **web "sign out everywhere"** (missing today — `CLIENTST0R_TASKS.md` CS-ID-03) using a per-user `sessions_valid_after` + session index; Rem0te: existing `sessionsValidAfter` | That app only; IdP session untouched (admin should also revoke at IdP) |
| User removed from app assignment | OP refuses next login to that app; mapped memberships deactivated on next login; Phase E: OP triggers back-channel logout for that client on unassignment (adapter, if supported) | Access ends on next request after logout or at next login |
| Credential compromise | Revoke at IdP (sessions + passkeys + reset), then per-app "sign out everywhere" as belt-and-braces; Connect credentials are a separate revocation (§9) | |

Mobile tokens (`MobileAuthToken`) and Rem0te `rk_` keys are **not** affected
by IdP revocation in v1 — documented gap; admins revoke them via existing
UIs (`/account/users/<id>/mobile-sessions/revoke/`). Phase E evaluates
linking mobile token revocation to back-channel logout by `sub`.

---

## 8. MFA policy and step-up

- **The IdP enforces MFA.** Org policy at the OP: MFA required for all MSP
  staff; passkeys allowed and encouraged; TOTP allowed; SMS/email OTP not
  allowed for staff.
- **Apps verify, not trust blindly.** An SSO session counts as "2FA verified"
  in an app only when `acr ∈ {mfa, phr}` and `amr` is consistent (§4). This
  replaces Clientst0r's Azure-specific `azure_sso_counts_as_2fa()`
  (`accounts/azure_auth.py`) for the generic provider and is evaluated in
  `Enforce2FAMiddleware` (`accounts/middleware.py:79`). Rem0te applies the
  same to skip its local MFA partial-token step for SSO logins.
- **Step-up for sensitive actions** (vault reveal, technician access grants,
  role changes, Rem0te `technicians.manage`, script approval, remote
  actions): the app redirects to authorize with `max_age=300` (or
  `prompt=login`) and `acr_values` (`mfa` or `phr` per action), then on
  return requires `auth_time` within the window and the requested `acr`.
  - Clientst0r: `tech_access/protected.py` `reauthenticate()` /
    `has_fresh_auth()` gain an OIDC branch; local password+OTP remains for
    local users.
  - Rem0te: `step-up.service.ts` issues its HMAC step-up cookie after a
    successful OIDC step-up instead of (or in addition to) local re-entry.
  - Rem0te approval-signer passkey quorum is **not** replaced — it is an
    approval control (who approves), not authentication strength.
- **Phishing-resistant policy option** per org: require `phr` for
  platform/MSP admins and for selected actions.

---

## 9. Separation from Agit8or Connect

Identity authenticates **humans to apps**. Connect authenticates **apps to
apps** (and carries explicit delegation when an app acts for a user). They
share nothing.

| Aspect | Agit8or Identity | Agit8or Connect |
|---|---|---|
| Purpose | Human SSO into an app | App-to-app requests, events, delegated actions |
| Issuer | OP issuer URL (e.g. `https://id.<domain>`) | Each app's own Connect identity (`iss` = peer id, e.g. ticket-rmm-v1 `iss` peer) |
| Signing keys | OP-managed JWKS (RS256/ES256), rotated by the OP | Per-app Ed25519 keys (today `Rem0teIdentity` / Rem0te `peers.json`; planned per-connection keys), rotated by Connect's stage/promote |
| Audiences | OIDC client ids (`clientst0r`, `rem0te`, …) | Connect audiences (`aud` = peer id / connection id), request-signing domain strings (`rem0te-http-req-v1`, …) |
| Token types | ID tokens (`typ` JWT), logout tokens | Signed HTTP requests, delegation JWS (`typ` `rem0te-delegation+jwt` today; Connect generalisation planned), planned client_credentials access tokens |
| Credential stores | OP Postgres; app stores only `(iss, sub)` links and session index | Clientst0r encrypted fields under `APP_MASTER_KEY`; Rem0te root-owned PEM + peers file / planned DB-backed connections |
| Revocation | OP session kill + back-channel logout | Connect key/connection revocation, replay guards (`Rem0teReplayGuard`, `IntegrationReplayGuard`) |
| Audit | OP auth events + app `auth.*` audit events | `integration.*` / Connect audit events |
| Admin permission | IdP platform admins / MSP org managers; app "Identity provider settings" permission | App integration-admin permission (Clientst0r Settings → Integrations + second-admin protected change; Rem0te `technicians.manage` step-up) |

**Hard rules**

1. A user ID token, access token or logout token from Identity is **never**
   accepted as a credential on any Connect endpoint. Connect verifiers reject
   any token whose `iss` is an Identity issuer or whose `typ` is not a Connect
   type.
2. Identity signing keys never sign Connect material and vice versa.
3. Revoking a Connect connection does not log users out; revoking a user at
   the IdP does not revoke a Connect connection — but it **does** make any
   further delegation on that user's behalf fail (rule 4b below).
4. **Acting on behalf of a user** is an explicit delegated authorisation
   issued by the calling app's Connect boundary:
   a. Keep and generalise the existing **ticket-rmm-v1 delegation JWS**
      (EdDSA, `iss` peer, `aud`, `sub` = mapped local principal e.g.
      `tech-<pk>`, `org`, single `scope`, `iat`/`exp` ≤ 300 s, `jti`,
      `req_sha256` binding to the exact request). It is already implemented
      on both sides, strictly validated, replay-protected and request-bound.
   b. Add optional, informational user-context claims for audit and policy:
      `usr_iss`, `usr_sub` (the Identity `(iss, sub)` of the human), `usr_acr`,
      `usr_auth_time`, `approval` (reference to an approval record). The
      receiver uses them for audit correlation and may **require** a recent
      `usr_auth_time` / `usr_acr` for sensitive scopes, but never treats them
      as authorisation — it still maps `sub`/`org` through its own mapping
      tables (e.g. Rem0te `IntegrationTechnicianMapping`, `checkActor`) and
      enforces its own permissions and approval rules. The calling app only
      issues a delegation while the user has a live, non-revoked local
      session.
   c. **RFC 8693 Token Exchange** is evaluated as a later Connect profile, if
      and when Connect gains an authorisation server (the planned
      client_credentials + `private_key_jwt` token endpoint). If adopted, the
      exchange happens at the **receiving app's Connect AS**, the
      `subject_token` is the caller's Connect delegation assertion (never a
      user ID token), the `actor_token` is the caller's client assertion, and
      the issued token carries `act` (actor) plus the preserved user/tenant/
      approval context. Until then, 4a is the only delegation mechanism.

Connect's own protocol is specified separately in `docs/agit8or-connect/`
(in progress at time of writing; not yet present in this worktree).

---

## 10. Tenant isolation and multi-MSP rules

- **IdP org = MSP** = one Clientst0r install + that MSP's Rem0te tenant and
  businesses. Customers are **not** separate IdP orgs; they are app-local
  records (Clientst0r `core.Organization`, Rem0te `Customer`) referenced
  from the MSP org by per-customer membership claims/groups
  (`orgs[].customers`).
- Clientst0r rejects any token whose org claim is not its pinned MSP org
  (§4, §5.2). In topology T1 (shared Zitadel) this is the control that keeps
  MSP A's users out of MSP B's install; in T2 (one Zitadel per MSP) the
  issuer pin does it as well.
- A token's org claim **never** grants access to another org. Apps ignore
  `orgs[]` entries not bound to the install/tenant (§5.1 rule 6).
- One human, several MSPs: one `sub` with several `orgs[]` entries, each with
  its own roles and assignment. Apps that host several MSPs (Rem0te tenants)
  keep a per-tenant membership; the user picks the active tenant, the app
  re-checks membership on every request (no "current org" from the token).
- MSP org managers administer only their own org at the OP (users,
  assignments, roles, MFA policy within platform minimums, sessions, login
  history). Platform admins are a separate, small group with phishing-
  resistant MFA required, managed only at the OP's instance level.
- Customer-specific app access is expressed by `orgs[].customers` (ceiling)
  plus app-local scoping (Clientst0r `client_scope`, `Membership`; Rem0te
  `Membership.customerId`, `TechnicianAssignment`).
- Login history and security events at the OP are filterable per org and
  visible only to that org's managers and platform admins.

### Portal / customer users

Phase F. Target model: portal/customer users are **users of the MSP's own
Zitadel org** (managed by that MSP's org managers), authorised for the portal
through a dedicated portal project or portal role keys (sub-project), with
their customer given by `orgs[].customers`. They never receive staff role
keys, and the portal OIDC client is separate from the staff client. Until
then Clientst0r customer portal users
(`portal/auth_views.py`, `PortalHostMiddleware`, `PortalUserGuardMiddleware`)
and Rem0te business users keep local login. The portal never accepts the
staff OIDC client's sessions (separate client id, separate redirect URIs on
the portal host, `user_type` guard unchanged).

### Mobile and API tokens

Untouched in v1: Clientst0r `api_mobile.MobileAuthToken`, Rem0te `rk_` keys,
agent enrolment tokens. A future phase may let the mobile app sign in through
the OP with PKCE (native app, RFC 8252) — not in scope here.

---

## 11. Break-glass, DR and HA

### 11.1 Break-glass local emergency admin (per app)

Purpose: recover an app when the OP is down, misconfigured, or an attacker
has locked admins out. It is documented, audited and narrow — never an
undocumented backdoor.

- One (max two) local accounts per app install, flagged `break_glass=true`,
  created by an admin with a second-admin approval (Clientst0r: existing
  Superuser Approval flow; Rem0te: platform admin + step-up).
- **Sealed**: the account is disabled by default. Enabling it requires shell
  access to the app host (Clientst0r: `manage.py breakglass enable --ttl 4h`;
  Rem0te: CLI equivalent) — i.e. it cannot be enabled from the web UI by a
  compromised web admin.
- Strong local password (generated, stored offline by the owner) **plus
  mandatory local MFA** (TOTP or passkey); never SSO-linked.
- **Auto-expiring**: enabled for a TTL (default 4 h), then disabled and its
  sessions killed automatically.
- **Alerting**: enabling and every sign-in raise a high-severity audit event
  and an alert (email/notification to all app superusers and platform
  admins).
- Login path stays available even when "SSO enforced" is on, but only at a
  separate URL and only for `break_glass` accounts while enabled.
- Quarterly drill documented in the runbook.

### 11.2 IdP backup and restore

- Postgres: nightly `pg_dump` (logical) + WAL archiving if HA; encrypted with
  a key held outside the IdP host; retained 30 days; offsite copy.
- OP master key / encryption key (Zitadel `masterkey`; Keycloak realm keys
  are in DB) backed up separately and offline — without it a DB backup is
  useless (Zitadel).
- Restore tested quarterly into a scratch instance; RPO ≤ 24 h (≤ 5 min with
  WAL), RTO ≤ 4 h.
- Configuration as code where possible (OP provisioning scripts/Terraform
  provider) so clients, projects and policies can be rebuilt.

### 11.3 HA options

| Option | Notes |
|---|---|
| Single VM + backups (Phase A default) | Simplest; OP outage = SSO outage, local logins + break-glass still work during migration phases |
| 2 OP nodes behind a load balancer + Postgres primary/replica | Zitadel and Keycloak are stateless-ish against Postgres (Keycloak also needs Infinispan cache config); adds operational load |
| Managed-elsewhere Postgres | Not chosen by default (self-hosted brief) |

Apps must degrade safely when the OP is unreachable: existing app sessions
continue until expiry; new SSO logins fail with a clear message; break-glass
and (until Phase E enforcement) local logins work.

### 11.4 Lockout recovery runbook (summary)

1. Confirm scope: OP down, OP misconfigured, admin accounts compromised, or
   signing key problem.
2. OP down → restore service/DB from backup; apps keep existing sessions.
3. All OP admins locked out → OP's documented instance-admin recovery
   (console/CLI on the OP host), then rotate those admins' credentials.
4. App unreachable via SSO → shell on the app host → enable break-glass with
   TTL → sign in with local MFA → fix provider config or switch the app's
   SSO mode to "optional" → disable break-glass.
5. Suspected OP key compromise → rotate OP signing keys, terminate all OP
   sessions, apps' JWKS cache refresh (forced), per-app "sign out
   everywhere", review login history.
6. Post-incident review; every step is in the audit log.

---

## 12. Threat model (STRIDE summary)

| # | Threat | Mitigation |
|---|---|---|
| T1 | Account takeover via email collision (attacker controls an IdP account with a victim's email) | Link only by `(iss, sub)`; JIT needs verified email **and** explicit assignment; fix existing Clientst0r Azure email matching (`accounts/azure_auth.py:138` `email__iexact`) → link by `tid`+`oid` |
| T2 | Token substitution / mix-up between apps | `aud`/`azp` exact; `iss` pinned per provider; `agit8or.app` check; per-provider redirect URIs; `state` bound to provider |
| T3 | Authorization code interception / injection | PKCE S256 mandatory; `state` + `nonce`; exact redirect URI match; codes single-use |
| T4 | Tokens leaked via URL / browser storage / logs | No tokens in URLs (code only), no web storage, server-side only; scrub `code`, `id_token` from logs and Sentry-like reporters; `Referrer-Policy: no-referrer` on callback |
| T5 | Cross-tenant access (MSP A token used for MSP B) | Install/tenant ↔ org binding; per-request local membership check; org-scoped login hint |
| T6 | Stale sessions after suspension | Back-channel logout; `sessions_valid_after`; silent re-auth at absolute timeout; Phase E sid liveness check |
| T7 | Forged back-channel logout (DoS by logging users out) | Signed `logout_token` validated against OP JWKS, `aud`, `events`, `jti` replay store |
| T8 | MFA bypass via weak SSO login | Apps require `acr` mfa/phr + consistent `amr`; per-action `acr_values`/`max_age`; local MFA kept for local accounts |
| T9 | Compromised MSP org manager escalates to platform or another MSP | OP delegated admin limited to own org; platform admins separate with `phr`; `platform_admin` never auto-maps to app superuser; Phase A gate 4 tests isolation |
| T10 | Using an Identity token against Connect endpoints / confused deputy | §9 hard rules: Connect rejects Identity issuers and types; delegation is explicit, short-lived, request-bound, re-authorised by the receiver |
| T11 | OP outage locks everyone out | Local login fallback until enforcement; break-glass; backups; HA option |
| T12 | Break-glass abuse | Sealed (shell-only enable), TTL, MFA, alerts, second-admin creation |
| T13 | OP signing key compromise | OP key rotation; apps refresh JWKS on unknown `kid` (rate-limited) and on demand; global session kill runbook |
| T14 | Open redirect via `next` / `post_logout_redirect_uri` | Only relative same-site `next` (existing `url_has_allowed_host_and_scheme`); pre-registered post-logout URIs |
| T15 | Brute force / credential stuffing | At the OP (rate limits, lockout policy, passkeys); local fallback keeps Clientst0r Axes; Rem0te moves lockout counters from in-memory Map to durable storage (`auth.service.ts:49`) |
| T16 | Audit gaps / repudiation | OP auth events + app `auth.sso.*` events with `iss`, `sub`, `sid`, `acr`, IP; Clientst0r `AuditLog` is mutable today (Connect audit item) — tamper-evidence tracked separately |
| T17 | SQLite write contention on Clientst0r prod during login bursts (known prod issue) | Keep session index writes minimal; no per-request writes for SSO; flagged for Postgres migration discussion |

---

## 13. Open questions (for the owner)

1. Zitadel is confirmed; please confirm its current licence terms
   (AGPL-3.0 for v3+, to be re-verified in the spike) are acceptable for
   unmodified self-hosting.
2. Host: share the 4 vCPU / 7 GB Clientst0r prod host, or a separate VM
   (recommended)? Which DNS name for the OP?
3. Same human in several MSPs (topology T1): one account with grants in
   several MSP orgs (preferred) or separate per-MSP accounts? In T2 they are
   necessarily separate accounts.
7. Default topology for new MSPs: shared Zitadel (T1) or one per MSP (T2)?
4. Should Identity platform admins ever map to app superuser, or always stay
   separate (recommended: separate)?
5. Should existing Azure AD SSO be kept long-term (federated *into* the OP as
   an upstream IdP) or retired after migration?
6. Portal/customer users at the OP (Phase F): users of the MSP org with a
   portal role, or a dedicated portal project per MSP?
