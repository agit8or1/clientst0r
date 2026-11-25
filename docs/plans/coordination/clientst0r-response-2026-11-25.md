---

## 2026-11-25 — Clientst0r proposals CX-1 to CX-8 (cross-application UX) and design-spec handoff

From the Clientst0r session (roadmap 113.10, branch `dev/ux-113-10`, based on v3.17.779). This entry is a
**proposal only**. It changes nothing in Rem0te. Clientst0r changed no protocol, signing, token or pairing code
for it. Each item takes effect only after both sides agree here and each side advertises it through the
protocol's own negotiation (Connect discovery and `extensions`, or ticket-rmm-v1 `contract_revision`). Unknown
fields are ignored on both sides (`PROTOCOL.md` §3), so an older peer is never broken.

Source of the items: `cs:docs/ux/CROSS_APP_UX_CONTRACT.md` §12 (contract 0.1.0 draft). Rem0te's answer in
its own coordination copy decides. Please accept, change or refuse each item by ID.

### 0. Handoff pointer: shared design specification

- The design specification **1.0.0** shipped in Clientst0r **v3.17.779**: `cs:docs/ux/SHARED_DESIGN_SYSTEM.md`,
  `cs:docs/ux/design-tokens.json` (`meta.version` 1.0.0), the icon map (§6) and the switcher appearance (§10).
- Handoff checklist and acceptance criteria: `cs:docs/ux/REM0TE_HANDOFF.md` (handoff 1.0.0-draft).
- It is a development-time specification. Rem0te bundles its own CSS, fonts and icons; nothing is loaded
  from Clientst0r at runtime and differing spec versions never affect interoperability.

### 1. What Clientst0r ships now without any of these (113.10)

- **Application switcher** in Clientst0r's top bar (`cs:core/app_switcher.py`, `cs:templates/core/_app_switcher.html`).
  It lists only:
  - Connect connections in state `active` (not Security Blocked, Suspended or Revoked), with Connect enabled
    and the kill switch off, for users holding `view_app_connections`;
  - active RMM connections whose console address passes the existing console-link check
    (`validated_console_url` against the provider's `console_hosts`), for users holding `integrations_view` and
    reach to the connection's customer.
- With no usable entry there is no markup at all (standalone rule S1).
- **Link target**: the https origin of the address approved at pairing (`Connection.base_url`) or of the RMM
  console address. Path, query and fragment are dropped, and the target is never taken from the request.
  Opens in a new tab with `rel="noopener noreferrer"`. No customer, user, token or role is in the link.
- **Status** comes from the last stored result and is shown with its time: Connect health (`last_check_at`),
  RMM sync health. An old result is shown as "Status unknown", never as Connected. Rendering never calls the
  other application.
- **Customer context**: when a customer is selected in Clientst0r, an entry is enabled only if that customer
  is mapped on the connection (active `TenantGrant`, the RMM connection's own customer, or a customer the
  connection's devices are settled under). Otherwise the entry is disabled and shows the contract §6.3
  explanation. Even when mapped, the link opens the other application's **home page**. Clientst0r
  passes no context, because no agreed link format exists.
- **Behind a flag (off)**: `APP_SWITCHER_CUSTOMER_LINKS` (setting, default False) plus a peer-advertised
  template (CX-1). Today nothing advertises or stores a template, so the flag has no effect. Clientst0r does
  not invent a format.
- Device console links (`{site root}/endpoints/{external_id}`) are unchanged. They remain the only deep links.

### 2. Proposals

#### CX-1 — Discovery `ui_links`: target-owned deep-link templates

- **Proposal.** Add an optional top-level object `ui_links` to the Connect discovery document
  (`GET {base}/.well-known/agit8or-connect`). Each key is an object type and each value is an absolute path
  template on the discovery origin:

  ```json
  "ui_links": {
    "home": "/",
    "customer": "/customers/{tenant}",
    "device": "/endpoints/{ref}",
    "ticket": "/tickets/{ref}"
  }
  ```

- **Why.** The target decides where its own pages are. The source never builds or trusts a URL it was given
  by the peer, and never guesses the target's routes.
- **Format.**
  - The keys are `home`, `customer`, `device`, `ticket` and `asset`. Unknown keys are ignored.
  - Placeholders are `{tenant}` (the tenant id **in the target's namespace**, as in the `Agit8or-Tenant`
    header the source already sends) and `{ref}` (the target's own object id as stored by the source, for
    example a Rem0te endpoint id).
  - A value starts with a single `/` and contains no scheme, host, `//`, `\`, `?` or `#`. At most 200
    characters.
  - The source substitutes values only after checking them against `[A-Za-z0-9_.:-]{1,100}` (`TENANT_RE`),
    URL-encodes them, and refuses the result unless its origin equals the approved discovery origin.
- **Storage.** The source stores `ui_links` with the connection at pairing and on each discovery refresh,
  through the same same-origin check as `endpoints` (§4). Clientst0r would add a field for this. That
  change is not made yet.
- **Security.** Templates are discovery data: they are fetched over the verified TLS channel and are subject
  to the same-origin rule. They carry no secrets. An absent key means "home page only".
- **Backward compatibility.** Additive. Older peers ignore the key. Without it, Clientst0r keeps linking to
  the origin (what 113.10 does).

#### CX-2 — Context parameters on a deep link

- **Proposal.** When the source opens a template from CX-1 it may append:
  `?ctx_conn={target's connection id for the source}&ctx_tenant={tenant id}&ctx_type={customer|device|ticket|asset}&ctx_ref={source object id}`.
- **Why.** These parameters let the target show "opened from Clientst0r, customer X" after resolving the
  values **through its own grant for that connection**, and refuse anything that does not resolve.
- **Rules.**
  - The target ignores the parameters unless `ctx_conn` names an active connection and `ctx_tenant` resolves
    through its own active grant on it. Otherwise it shows its neutral page with the contract §6.3 reason.
  - The target never falls back to "all customers" or to the user's last customer.
  - The user is always authenticated by the target: its own session, 2FA or optional SSO.
- **Never in the link.** Tokens, codes, assertions, keys, passwords, session ids, JWS, user ids, roles, or
  `next`/`return_to`/`redirect_uri` with a free URL. The link is at most 2,000 characters.
- **Backward compatibility.** These are browser query parameters only, with no server-to-server change.
  Targets that do not know them ignore them.
- **Question for Rem0te.** Is `ctx_conn` useful to you, or is the tenant id enough? Rem0te may already know
  the connection from its own grant lookup.

#### CX-3 — Discovery `app.icon` and `app.ui_base`

- **Proposal.** Add two optional keys to the existing `app` object:
  - `app.icon`: a concept key from the shared icon map (for example `"integration"` or `"remote-session"`).
    It names an icon. It is not a URL, and no image is fetched.
  - `app.ui_base`: the https origin of the user-facing web UI, if it differs from the discovery/API origin.
- **Why.** The switcher shows the right icon, and the link goes to the UI rather than the API host. Today
  Clientst0r links to the discovery origin, which is correct for Clientst0r and is believed correct for
  Rem0te (the site root serves both). Please confirm.
- **Security.** `ui_base` must have the same registrable domain as the discovery origin. It is shown to the
  administrator at pairing and approved together with the connection. A later change is a protected change
  (second administrator), like a destination change. It is never a redirect target.
- **Backward compatibility.** Additive. Without it, the discovery origin and a generic icon are used.

#### CX-4 — Shared health vocabulary for technicians

- **Proposal.** Both applications use one badge per connection in technician-facing UI: **Connected**,
  **Degraded**, **Offline**, **Action needed**, **Security Blocked** and **Revoked**. Stale results read
  "Status unknown — last checked {time}". Admin pages keep their detailed labels.
- **Why.** Technicians see the same words in both products.
- **Protocol.** None. This is a wording rule.
- **Clientst0r now.** The switcher uses these labels: Connected, Degraded, Offline, Status unknown and
  Not checked yet. Revoked connections are hidden, not listed.

#### CX-5 — Rem0te "Disconnected" (unreachable) shown as "Offline"

- **Proposal.** Where Rem0te shows a peer as unreachable, it says **Offline**. "Disconnected" or "Revoked" is
  kept for a connection an administrator ended.
- **Why.** "Disconnected" means *revoked* in Connect and *unreachable* in the Rem0te ticket pairing.
- **Clientst0r side.** Clientst0r already maps its Rem0te health "Disconnected" to Offline in new UI. Its
  own Rem0te pairing label (`integrations/rem0te/health.py`) will follow once agreed.
- **Backward compatibility.** Display only.

#### CX-6 — Coordinated logout through the IdP

- **Proposal.** When both applications use the same OIDC IdP (optional), each registers its own back-channel
  logout endpoint at the IdP. Logging out at the IdP ends both sessions. The applications never call each
  other to log out.
- **Why.** Single sign-out without a shared session (X1).
- **Clientst0r now.** Back-channel logout exists (`oidc_sso/`). Nothing is needed from Rem0te beyond
  supporting the same IdP feature on its side.
- **Backward compatibility.** Optional per installation. Local login and break-glass stay.

#### CX-7 — Remote-session confirmation event (open request R6 / P6)

- **Proposal.** Rem0te sends a signed `remote.session_started` / `remote.session_ended` event with
  `request_id`, the endpoint `external_id` and an optional ticket reference. It goes over the existing
  ticket-rmm-v1 event channel (or Connect events later).
- **Why.** Clientst0r shows "Link issued — session not confirmed" today and must never claim a session
  started without the RMM saying so.
- **Security.** The event uses the existing event signature and replay rules. It contains no recording,
  keystrokes or screen content.
- **Backward compatibility.** Advertised as a feature in `/capabilities`. Until it is advertised, Clientst0r
  keeps the current wording.

#### CX-8 — Technician-mapping status in capabilities

- **Proposal.** The signed `/capabilities` response for a delegated technician (`sub: tech-<id>`) carries
  `technician: {"mapped": true|false}`. It contains no Rem0te user id, name or role.
- **Why.** Clientst0r can then explain "Your Clientst0r user is not linked to a Rem0te technician" (§6.3)
  before a technician tries an action, instead of after a refusal.
- **Security.** The response is boolean only and is answered for the delegated subject of that request.
  Rem0te still decides every action.
- **Backward compatibility.** Additive field. When it is absent, Clientst0r shows no mapping hint.
- **Later.** The same fact could come from Connect actor claims (`PROTOCOL.md` §17, planned).

### 3. Order Clientst0r suggests

1. CX-4 and CX-5 (wording only).
2. CX-1 and CX-3 (additive discovery keys).
3. CX-2.
4. CX-8 and CX-7 (contract features).
5. CX-6 (independent).

Once Rem0te agrees to CX-1, Clientst0r will:

- store `ui_links` with the connection;
- fill `advertised_ui_links()` in `cs:core/app_switcher.py`;
- review whether to turn on `APP_SWITCHER_CUSTOMER_LINKS` by default.

### 4. Breaking changes

None on either side.
