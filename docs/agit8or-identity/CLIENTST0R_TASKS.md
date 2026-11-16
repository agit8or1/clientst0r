# Agit8or Identity — Clientst0r task list

> **Status: planned. None of these tasks is implemented.** Pointers were
> checked against `dev-work` v3.17.687 (in the `.wt-connect` worktree) on
> 2026-11-16; re-check before starting. Each task ships with tests in the
> matching app's tests module and follows the normal release pattern
> (version bump, CHANGELOG, ROADMAP entry as a planned/in-progress item).

Ordering: CS-ID-01 and CS-ID-03 are useful on their own and can ship before
any IdP exists. The rest belong to MIGRATION.md Phase B unless noted.

---

### CS-ID-01 — Fix Azure AD account matching (security, independent)

- **Where:** `accounts/azure_auth.py` `AzureADBackend.get_or_create_user()`
  (:124); lookup `User.objects.get(email__iexact=email)` at :138; auto-create
  at :163; auto-assign to the *first active organisation* as `viewer` (just
  after :180).
- **Problem:** an Azure sign-in is linked to whichever local user has the same
  email, and new users are auto-created and auto-added to an org. Email is a
  mutable, tenant-controlled attribute → account takeover / unintended
  access risk.
- **Change:**
  - Link by `(tid, oid)` from the validated ID token claims (not Graph
    `/me` `id` alone). Store `azure_ad_tid` next to the existing
    `UserProfile.azure_ad_oid`; enforce uniqueness of `(tid, oid)`.
  - Pin allowed `tid` values in the Azure config (single-tenant by default).
  - Existing users without a stored `(tid, oid)`: one-time link only via the
    user-initiated flow (sign in the usual way → link Microsoft account), or
    an admin-approved backfill command that matches by email **and** shows
    the list for confirmation before writing. No silent email linking.
  - Auto-create default **off**; when on, require `email_verified`-equivalent
    (`xms_edov` / verified domain) and do **not** auto-add to any org (land
    on a "pending access" page; admin assigns).
- **Tests:** email collision does not link; `(tid, oid)` match links; wrong
  `tid` refused; auto-create off by default; no auto org membership.

### CS-ID-02 — Generic OIDC backend (Authlib)

- **New:** `accounts/oidc/` package — `client.py` (Authlib registry built
  from DB config), `backend.py` (`OIDCBackend.authenticate(request,
  oidc_claims=…)`), `views.py` (login, callback, link, back-channel logout),
  `mapping.py`, `adapter.py` (Keycloak `organization` + `resource_access.<client>.roles` → `agit8or` v1 per ARCHITECTURE.md §4.4; `acr` mapping).
- **Models:** `OIDCProvider` (issuer, client_id, encrypted secret or private
  key via existing `EncryptedTextField`, scopes, enabled, `jit_enabled`,
  pinned Keycloak issuer (realm URL) + MSP Organization id/alias
  (`msp_org_id`, `msp_org_alias`; exactly one; protected change), `min_acr_for_2fa`, token endpoint auth method),
  `ExternalIdentity(provider, issuer, subject, user, created_at,
  last_login_at)` unique `(issuer, subject)`.
- **Settings:** add `accounts.oidc.backend.OIDCBackend` to
  `AUTHENTICATION_BACKENDS` (`config/settings.py:294`) after Axes; dependency
  `Authlib` pinned in `requirements.txt` (exclude `venv/` from any repo-wide
  edits).
- **URLs:** `accounts/urls.py` next to the Azure routes (:24-27):
  `auth/oidc/<slug>/login/`, `auth/oidc/<slug>/callback/`,
  `auth/oidc/<slug>/backchannel-logout/`, `profile/identity/link/`.
- **Validation:** PKCE S256, state + nonce in server session, `iss` exact,
  `aud`/`azp`, alg allowlist, `iat` skew, `agit8or.v`/`app` check; no tokens
  persisted; `code` scrubbed from logs; callback sets
  `Referrer-Policy: no-referrer`.
- **Login page:** button only when a provider is enabled
  (`two_factor:login` template, `LOGIN_URL` `config/settings.py:566`).
- **Tests:** happy path, bad `aud`, bad `iss`, `alg=none`/HS256 rejected,
  replayed state, missing nonce, unknown contract version.

### CS-ID-03 — Web "sign out everywhere" (independent)

- **Gap:** only mobile sessions can be revoked
  (`accounts/urls.py:45,70` `mobile_sessions_revoke`, `api_mobile/models.py:26`
  `MobileAuthToken.revoked_at`). Django DB sessions are not indexed by user.
- **Change:**
  - `UserProfile.sessions_valid_after` (datetime); `SessionIdleTimeoutMiddleware`
    (`accounts/middleware.py:13`) or a new small middleware logs out any
    session whose login timestamp (stored in the session at login) is older.
  - `UserSession` index (user, session_key, created_at, ip, ua, `oidc_iss`,
    `oidc_sid`) written on `user_logged_in`, removed on `user_logged_out`;
    used to list and delete sessions and for back-channel logout by `sid`.
    Keep writes to login/logout only (SQLite prod).
  - UI: Profile → "Sign out all other sessions"; admin user page → "Sign out
    everywhere" (also revokes mobile tokens optionally); audited
    `auth.sessions.revoked`.
- **Tests:** other sessions die, current survives (self-service); admin kill
  ends all; mobile tokens revoked only when chosen.

### CS-ID-04 — Back-channel logout endpoint

- `auth/oidc/<slug>/backchannel-logout/` — CSRF-exempt POST only; validate
  `logout_token` per ARCHITECTURE.md §6.3 with Authlib JOSE; `jti` replay
  store (new `OIDCLogoutReplay` unique `jti`, TTL cleanup in the existing
  scheduler); kill sessions by `(iss, sid)` via `UserSession`, or all
  sessions of the linked user by `(iss, sub)` (sets `sessions_valid_after`).
- **Tests:** valid token kills matching sessions only; token with `nonce`
  rejected; wrong `aud`/`events` rejected; replay rejected; sub-only token
  kills all of that user's sessions; 400 on garbage; no redirect.

### CS-ID-05 — RP-initiated logout

- `accounts` logout view: if the session came from OIDC, log out locally then
  redirect to the provider's `end_session_endpoint` with `client_id`,
  `post_logout_redirect_uri`, `state` (and `id_token_hint` only if the OP
  requires it — then store the ID token server-side in the session, never in
  a cookie). Local logout for non-SSO sessions unchanged.

### CS-ID-06 — Claim → membership mapping

- **Model:** `OIDCRoleMapping(provider, idp_org_id, role_key, target:
  staff-global | organization, global_role_template, client_scope,
  organization, role_template, is_active)`; modelled on `LDAPGroupMapping`
  (`accounts/models.py:2379`) and its sync (`accounts/ldap_group_sync.py`,
  `accounts/ldap_mapping.py`, UI `accounts/ldap_mapping_views.py`).
- **Membership tagging:** add `Membership.oidc_mapping` FK (parallel to
  `Membership.ldap_group_mapping`) so reconciliation touches only SSO-made
  memberships.
- **Staff vs org user:** mappings targeting staff set `UserProfile.user_type
  = staff` + `global_role_template` + `client_scope` (`accounts/models.py:462-497`);
  mappings targeting a client org create `Membership(role_template=…)`.
  `orgs[].customers` intersects with local scope; never widens.
- **Never:** set `is_superuser`, `is_staff` (Django admin) or bypass the
  Superuser Approval flow.
- **Reconcile** on every SSO login and on back-channel logout; invalidate
  `accounts/authz_cache.py`; audit via `accounts/role_audit.py`.
- **Customer key:** `core.Organization.identity_customer_key` (unique, nullable)
  so per-customer membership claims map to the right customer.
- **Tests:** mapping creates membership; removed role deactivates only the
  tagged membership; manual membership untouched; unbound org ignored;
  `platform_admin` not mapped; customers ceiling.

### CS-ID-07 — JIT provisioning

- Only when `jit_enabled`, `email_verified=true`, at least one bound org with
  `assigned=true`, and mapping yields at least one role. Username derived
  from email local part with collision suffix (as Azure code does) but
  **never** matches an existing user by email — an email collision blocks
  JIT and shows the linking message (MIGRATION.md §B.3).
- **Tests:** each precondition refused individually; collision refuses.

### CS-ID-08 — Linking flows

- User-initiated link (`profile/identity/link/`) after `reauthenticate()`
  (`tech_access/protected.py:77`) and an OIDC round trip with `prompt=login`;
  unlink requires fresh auth and is refused if it would leave an
  `enforced`-mode staff user with no login method.
- Admin pre-link field on user edit (`accounts/urls.py:67` `user_edit`) with
  second-admin approval for elevated staff.
- **Tests:** link binds to the signed-in user only; cannot link an
  `(iss, sub)` already linked elsewhere; audit rows.

### CS-ID-09 — 2FA acceptance via `acr`/`amr`

- `Enforce2FAMiddleware` (`accounts/middleware.py:79-210`) currently trusts
  `azure_sso_counts_as_2fa()` (`accounts/azure_auth.py`). Generalise to
  `sso_counts_as_2fa(request)`: session flag set at OIDC login when `acr` ≥
  provider `min_acr_for_2fa` (default `urn:agit8or:acr:mfa`) and `amr`
  consistent; keep the Azure branch as one implementation.
- Make the user `is_verified()` for django-otp purposes only through this
  explicit flag (do not fake an OTP device).
- **Tests:** `acr=pwd` SSO session is forced through 2FA; `acr=mfa` passes;
  inconsistent `amr` rejected; `core.security_policy.require_2fa()` still
  honoured.

### CS-ID-10 — Step-up via OIDC

- `tech_access/protected.py` `reauthenticate()` (:77) / `has_fresh_auth()`
  (:84), `FRESH_AUTH_SECONDS = 300` (:43): add an OIDC path — for SSO users,
  "Confirm it's you" redirects to authorize with `max_age=300`,
  `acr_values` (per-action, default mfa), `prompt=login` when required; on
  return verify `auth_time` and `acr` and write the same session key
  `has_fresh_auth()` reads. Local users keep password + OTP.
- Apply to existing reauth call sites (vault reveal, technician access,
  protected changes, role changes).
- **Tests:** stale `auth_time` refused; lower `acr` refused; success sets
  fresh-auth window; local path unchanged.

### CS-ID-11 — App-assignment and tenant checks

- Refuse login unless `orgs[]` contains the pinned `msp_org_id` with
  `assigned=true` (one MSP per install); discard all other org entries; refuse if `agit8or.app != "clientst0r"`; refuse
  `status != active`. Per-request authorisation remains local (no claims in
  the request path).
- **Tests:** unassigned user refused; other-org-only token refused; app
  mismatch refused.

### CS-ID-12 — Tests, fixtures, docs

- `accounts/tests_oidc.py`: a fake OP fixture (local RSA/EC JWKS, token
  minting helper) — no network. Use `@override_settings(MIDDLEWARE=TEST_MIDDLEWARE,
  SECURE_SSL_REDIRECT=False)` for view tests; staff users via `_make_msp_tech`.
- Admin docs page (Settings → Directory Services → Agit8or Identity) and a
  ROADMAP phase entry marked `[planned]`.

### CS-ID-13 — Break-glass account

- `UserProfile.break_glass` flag + `manage.py breakglass enable|disable
  --user … --ttl 4h` (shell only); scheduler job auto-disables at TTL and
  kills sessions; separate login URL usable when SSO is `enforced`;
  mandatory local TOTP; high-severity audit + notification to superusers on
  enable and each login. Creation goes through Superuser Approval.
- **Tests:** disabled by default; cannot be enabled via web; auto-expiry;
  login alerts; refused at the normal login page when enforced.

### CS-ID-14 — Enforcement mode (Phase E)

- Provider setting `mode: off|optional|enforced`; enforcement refuses local
  password, Azure and LDAP logins for staff (not portal, not break-glass);
  preconditions checklist UI (MIGRATION.md Phase E).

---

## Not in scope for Clientst0r here

Portal users (`portal/auth_views.py`) — Phase F. Mobile tokens — unchanged.
Connect delegation claims — coordinated through the Connect docs.
