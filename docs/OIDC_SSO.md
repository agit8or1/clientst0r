# Single sign-on with OpenID Connect (OIDC)

Clientst0r can sign MSP staff in through any certified OpenID Connect
provider (OP). The reference OP is Keycloak (the "Agit8or Identity" design),
but nothing in Clientst0r is Keycloak-specific except the default claim
paths, which are configurable.

Status: **in progress** — the client side is built and unit-tested against a
fake OP; it has not yet been verified against a live Keycloak (see
[What still needs a live OP](#what-still-needs-a-live-op)).

- Settings: **Administration → Security → Single sign-on (OIDC)**
  (`/accounts/sso/oidc/settings/`).
- Permission: superusers, or MSP staff whose **global** role has
  `manage_sso_settings` (critical, off for every role by default).
  Customer memberships never grant it.
- Users link their own account at **Profile → Single sign-on**
  (`/accounts/sso/oidc/account/`).

## What it does

| | |
|---|---|
| Flow | Authorization code + PKCE (S256) + `state` + `nonce`. All three live only in the server-side session and are single use. |
| Client authentication | `private_key_jwt` (recommended — Clientst0r generates an RSA key pair, keeps the private key encrypted, and shows the public JWK) or `client_secret_basic` (secret stored encrypted, never shown again). |
| ID token checks | Signature with the OP's JWKS (unknown `kid` → one refetch, throttled); algorithm allowlist `RS256 PS256 ES256 EdDSA` (never `none`, never `HS*`); `iss` exact; `aud` contains the client id; `azp` equals it when present (required with several audiences); `exp`/`iat`/`nbf` with 60 s leeway; `nonce`; `auth_time` vs `max_age` for step-up; `at_hash` when present. |
| Discovery | `<issuer>/.well-known/openid-configuration`; its `issuer` must equal the configured issuer exactly; every endpoint passes the outbound request guard. Cached per worker for an hour. |
| Accounts | Found strictly by `(issuer, sub)`. **Never by e-mail.** An unknown `sub` whose e-mail matches a local account is refused with "sign in the usual way and link from your profile". |
| MSP pin | Tokens must carry the pinned MSP organization (alias, and id when set) in the organization claim. Only roles with the `<alias>:` prefix count; other organizations' roles are discarded. |
| Roles | `<alias>:<role>` → MSP staff global role; `<alias>:customer:<key>:<role>` → membership in the customer mapped to `<key>`. A token with no mapped role cannot sign in. |
| MFA | Off by default: an SSO sign-in is asked for the local authenticator code exactly like a password sign-in. With **Accept the IdP's MFA** on, a token whose `acr` is in the configured list (or whose `amr` has a configured second factor, and is not password-only) stands in for local 2FA. |
| Step-up | "Confirm with <provider>" next to the password confirmation (Technician Access, Superuser Approval, the SSO page) re-authenticates at the OP (`prompt=login`, `max_age=300`, optional `acr_values`) and satisfies the same five-minute "fresh authentication" check. Local password + code keeps working. |
| Logout | Signing out ends the local session, then continues to the OP's `end_session_endpoint` (`id_token_hint`, `client_id`, `post_logout_redirect_uri`). A back-channel logout endpoint ends sessions by `sid` (or all SSO sessions of the `sub`). |
| Audit | `sso_login`, `sso_login_denied` (with a reason code), `sso_link`, `sso_unlink`, `sso_step_up`, `sso_backchannel_logout`, `sso_config_change`, `oidc_sso_2fa_accepted`. No tokens, codes or secrets are logged. |

Local, Microsoft (Azure) and LDAP sign-in are unchanged. The customer portal
is not affected (portal users keep local sign-in; a customer portal account
is refused by the staff SSO).

## Break-glass

**Local superuser sign-in always remains available** at `/account/login/`
(password + local authenticator code). Nothing in this phase can disable
local, Microsoft or LDAP sign-in, and disabling the provider (one checkbox)
removes the button and makes every SSO endpoint return 404. Keep at least one
local superuser with a strong password and TOTP, stored offline.

## Keycloak setup (walkthrough)

Assumes a realm (e.g. `agit8or`) with the **Organizations** feature on and an
organization for the MSP (e.g. alias `acme-msp`). Keycloak 26.x screen names.

1. **Add the provider in Clientst0r first.** Administration → Security →
   Single sign-on (OIDC) → *Add provider* (e.g. name "Agit8or Identity",
   short name `agit8or`). It is created **disabled** with a fresh key pair.
   The page shows the redirect URI, back-channel logout URL, post-logout
   redirect URI, the public JWK and a JWKS URL.

2. **Create the client** (Clients → Create client):
   - Client type **OpenID Connect**, Client ID e.g. `clientst0r-acme-msp`.
   - **Client authentication: On**. Authentication flow: **Standard flow
     only** (no implicit, no direct access grants, no service accounts).
   - Valid redirect URIs: the exact redirect URI shown in Clientst0r
     (`https://<host>/accounts/sso/oidc/<slug>/callback/`).
   - Valid post logout redirect URIs: `https://<host>/account/login/`.
   - Advanced → **Proof Key for Code Exchange Code Challenge Method: S256**.

3. **Client authentication = Signed JWT.** Client → *Credentials* →
   Client Authenticator **Signed JWT**, signature algorithm **RS256**. Then
   *Keys* tab → either **Use JWKS URL** with the JWKS URL shown in Clientst0r
   (served only while the provider is enabled), or *Import key* → JSON Web Key
   Set and paste the JWK shown. (To use a client secret instead, choose
   "Client Id and Secret" and set Clientst0r to `client_secret_basic`.)

4. **Back-channel logout.** Client → *Settings* → Logout settings:
   Front channel logout **Off**; **Backchannel logout URL** = the URL shown
   in Clientst0r (`https://<host>/accounts/sso/oidc/<slug>/backchannel-logout/`);
   **Backchannel logout session required: On** (so tokens carry `sid`).

5. **Organization claim.** Client scopes → ensure the `organization` scope is
   assigned to the client (default or optional) and its *Organization
   Membership* mapper has **Add organization id** on, so the ID token carries
   `"organization": {"acme-msp": {"id": "<uuid>"}}`. In Clientst0r set
   *Org claim* `organization`, *MSP org alias* `acme-msp`, *MSP org id* the
   organization's UUID.

6. **Client roles.** Client → *Roles*: create roles named
   `acme-msp:<role>` for staff (e.g. `acme-msp:technician`,
   `acme-msp:service-manager`) and `acme-msp:customer:<customer-key>:<role>`
   for customer-scoped access (e.g. `acme-msp:customer:cust-0193:technician`).
   Grant them to users or (better) groups. Make sure the client's
   *Dedicated scope* includes the **client roles** mapper adding
   `resource_access.<client_id>.roles` to the **ID token**, and set
   **Full scope allowed: Off** so tokens carry only this client's roles.
   The default Clientst0r *Roles claim* is `resource_access.{client_id}.roles`.

7. **MFA (optional).** If the realm enforces MFA and maps `acr`
   (ACR-to-LoA mapping, e.g. `urn:agit8or:acr:mfa`) and `amr` (AMR protocol
   mapper), list those values in Clientst0r and switch on *Accept the IdP's
   MFA*. Leave it off to keep local TOTP.

8. **Map roles and customers in Clientst0r.** On the provider page add role
   mappings (`technician` → *MSP staff global role* → a global role;
   `technician` → *Customer membership role* → a role) and customer keys
   (`cust-0193` → the customer). Mapping a privileged role needs a superuser.

9. **Test discovery**, then tick **Enabled** and save. The button
   "Sign in with Agit8or Identity" appears on the staff login page.

10. **Link existing accounts.** Either each user goes to Profile → Single
    sign-on, confirms their password (and code) and clicks *Link SSO account*
    (signs in at Keycloak with `prompt=login`), or an administrator pre-links
    them with the Keycloak user id (`sub`, shown on the Keycloak user page).
    Optionally switch on *JIT provisioning* to create accounts for new staff
    with a verified e-mail and a mapped staff role.

## Rules for roles and memberships

- Customer roles create memberships **tagged as SSO-managed**. Only those are
  re-roled, re-activated or deactivated by later sign-ins; when the role
  disappears from the token, the membership is deactivated at the next
  sign-in (even when that sign-in is then refused). Memberships made by hand,
  invite or LDAP are never touched.
- Staff roles change the user type / global role / client scope only of
  accounts **SSO manages**: accounts created by JIT, or ones a superuser
  switched to "SSO manages staff role". Linked existing accounts keep their
  local role; the token's role then only acts as the sign-in gate.
- For SSO-managed staff, customer roles in the token are a **ceiling**: the
  client scope becomes the mapped customers listed in the token, intersected
  with the mapping's own scope ("assigned" = current technician access
  assignments). They never widen access.
- SSO never sets `is_superuser` or Django `is_staff`.
- With JIT on, a new account needs: `email_verified=true` (unless that check
  is switched off), an e-mail, and a mapped **staff** role. An e-mail that
  already exists locally blocks JIT.

## Network and SSRF

All OP traffic goes through `core/safe_http.py`'s guarded session (DNS is
resolved once and pinned; every redirect and connection is re-checked; proxies
are refused). By default only public addresses are reachable (or private ones
when the install-wide `ALLOW_PRIVATE_IP_INTEGRATIONS` is on). The per-provider
**"private network"** switch allows an OP on RFC 1918 / ULA addresses (and
`http://`, for testing only); loopback and link-local still need the global
setting; cloud metadata addresses are refused always. A private CA bundle
(PEM) can be set per provider.

## Generic OP notes

- Any OP that supports discovery, PKCE S256 and RS256/PS256/ES256/EdDSA ID
  tokens works. Set *Roles claim* to wherever the OP puts roles (e.g.
  `groups`, `roles`, `realm_access.roles`) and keep the `<alias>:` naming, or
  leave *MSP org alias* empty to read unprefixed roles.
- An OP / realm dedicated to this MSP may leave *Org claim* empty: the issuer
  pin then separates MSPs. With a shared realm, always pin the organization.
- Back-channel logout needs `sid` (or `sub`) in the logout token; without
  back-channel support, sessions end at the local idle / absolute timeout.
- `end_session_endpoint` is optional; without it sign-out is local only.

## Design deviations (from docs/agit8or-identity)

- **No Authlib.** The design recommended Authlib; this uses PyJWT 2.x (already
  installed) for JWS/JWKS, `cryptography` for the key pair and the standard
  library for PKCE/state/nonce, so no new production dependency was added.
  Only library primitives are used — no custom crypto.
- The app lives in `oidc_sso/` (not `accounts/oidc/`); tables are
  `OIDCProvider`, `OIDCIdentity` (= ExternalIdentity), `OIDCRoleMapping`,
  `OIDCCustomerMapping` (instead of a new `Organization.identity_customer_key`
  column), `OIDCManagedMembership` (instead of a `Membership.oidc_mapping`
  column), `OIDCSession` (sid → session index) and `ReplayRecord`.
- Claims are read in Keycloak's native shape (`organization` +
  `resource_access`) through the configurable adapter; the normalised
  `agit8or` v1 object is not required.
- Protected changes use superuser checks (issuer / MSP pin changes once
  accounts are linked, privileged role mappings, SSO-managed staff roles,
  pre-linking a superuser) instead of the two-administrator ProtectedChange
  flow; admin pre-link of elevated staff has no second-admin approval yet.
- Sub-only back-channel logout ends this OP's SSO sessions of the user; when
  the "sign out everywhere" feature (`UserProfile.sessions_valid_after`) is
  present it is also set, ending every session.
- Break-glass account, enforcement mode and SCIM are later phases.

## What still needs a live OP

- The exact Keycloak `organization` claim shape with "Add organization id",
  and the client-roles mapper output in the ID token.
- `private_key_jwt` acceptance (assertion `aud` = token endpoint) and JWKS-URL
  key fetching by Keycloak.
- Back-channel logout delivery (`sid` present, `events` claim, `typ`) and
  RP-initiated logout with `id_token_hint` + `post_logout_redirect_uri`.
- `acr` / `amr` values Keycloak emits with the realm's ACR-to-LoA and AMR
  mappers, and `max_age` / `prompt=login` behaviour for step-up.
