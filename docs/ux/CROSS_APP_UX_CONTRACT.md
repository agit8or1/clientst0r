# Cross-application UX contract

Version **0.1.0 (draft)**, 2026-11-25. Owner: Clientst0r. Audience: Clientst0r developers, Rem0te and any other
MSPZero application that pairs with Clientst0r.

This contract describes how paired applications present each other to users: the application switcher, customer
context, deep links, capability discovery, integration health, stale data and shared terms. It is built **only** on
what the existing protocols already define:

- Agit8or Connect `agit8or-connect/1` ([PROTOCOL.md](../agit8or-connect/PROTOCOL.md)) and revision 1.1
  ([PROTOCOL-1.1.md](../agit8or-connect/PROTOCOL-1.1.md)), implemented in `agit8or_connect/` (SDK 1.1.0) and `connect/`;
- the transitional ticket-rmm-v1 contract, revision 2, implemented in `integrations/rem0te/` and
  `integrations/ticket_rmm.py`, coordinated in `INTEGRATION_COORDINATION.md`;
- optional OIDC SSO ([OIDC_SSO.md](../OIDC_SSO.md), `oidc_sso/`).

Every item is marked:

- **existing** — implemented today; the `path:line` says where;
- **local rule** — Clientst0r-side presentation that needs nothing from a peer;
- **proposed — needs Rem0te agreement via INTEGRATION_COORDINATION.md** — not implemented on either side; requires the
  peer to change. Clientst0r does not ship these until both sides agree. No protocol code changed for this document.

Standalone rules (S1–S9, F1–F12 …) are in [STANDALONE_REQUIREMENTS.md](STANDALONE_REQUIREMENTS.md). Visual tokens are in
[SHARED_DESIGN_SYSTEM.md](SHARED_DESIGN_SYSTEM.md) and [design-tokens.json](design-tokens.json).

## 1. Principles

1. Each application is complete alone. Integration adds; its absence removes nothing local.
2. Each application authenticates and authorizes its own users. A link from a peer is a *hint*, never a grant.
3. A capability is shown only when both installed versions support it and the last check said so.
4. Everything that crosses applications is keyed by **(connection, tenant)** (`PROTOCOL.md` §8.3).
5. Presentation follows facts from stored state; pages never call a peer while rendering (rule F3).

## 2. Terminology

Use these words in UI text, docs and both applications. "Avoid" lists terms that today mean different things in
different places.

| Term | Meaning | Avoid / notes |
|---|---|---|
| **Application** | Another installed product (Rem0te, st0r …) | "app" in UI text; "peer" is fine in docs only |
| **Connected application** | An application paired through Agit8or Connect (`connect.Connection`) | |
| **RMM connection** | An `integrations.RMMConnection`, any provider | "integration" alone when the type matters |
| **Ticket integration pairing** | A ticket-rmm-v1 pairing on an RMM connection (`integrations/ticket_rmm.py`) | "Rem0te integration" for the generic thing |
| **Customer** | A Clientst0r customer organization (`core.Organization`); Connect tenant id `org-<n>` | "client" and "organization" are used in older pages; new text says customer |
| **Customer mapping** | A Connect tenant grant (`connect.TenantGrant`), or the pinned tenant of a ticket integration pairing | "tenant" in UI text |
| **Technician mapping** | ticket-rmm-v1 delegation subject `tech-<id>` (`INTEGRATION_COORDINATION.md` §4.2); Connect actor claim is planned (`PROTOCOL.md` §17) | |
| **Capability** | Something a connection can do now: a granted Connect scope, or a ticket-rmm-v1 feature from the last compatible check | "feature" |
| **Connected / Degraded / Offline** | Health states (§7) | "Disconnected" — today it means *revoked* in `connect/models.py:84` and *unreachable* in `integrations/rem0te/health.py:52`. New text: **Offline** for unreachable, **Revoked** for ended by an administrator. |
| **Revoked** | Ended by an administrator; records kept (`PROTOCOL.md` §12) | |
| **Security Blocked** | Stopped because a key, certificate, identity or destination did not match (`connect/status.py`) | "error" |
| **Last successful sync** / **as of** | When external data was last refreshed successfully | "last sync" when it may have failed |
| **Request** (to an RMM) | Something Clientst0r asked the RMM to do; the RMM decides (`psa_ai.RMMRequest`) | "run", "execute" for Clientst0r's side |
| **Approval page** | The RMM's own page where its approvers decide | |
| **Open in <application>** | A link that opens the other application in a new tab | "Open in RMM" for a link to a local page |

## 3. Application switcher

Status: **local rule** for Clientst0r's presentation; the entries other applications show for Clientst0r are
**proposed — needs Rem0te agreement via INTEGRATION_COORDINATION.md**. No switcher exists in Clientst0r today.

### 3.1 When it appears

The switcher is rendered only when the current user has at least one usable entry. Otherwise there is no control, no
placeholder and no reserved space (S1, S8).

An entry is usable when **all** hold:

1. The source is configured and live:
   - Connect: `Connection.state == active` and its displayed status is not Security Blocked, Suspended or Revoked
     (`connect/status.py`), with `AGIT8OR_CONNECT_ENABLED` on; or
   - RMM: an active `RMMConnection` whose provider has a console link mode other than `none`
     (`integrations/providers/rmm/console.py`).
2. The user may use it here: MSP staff (`psa.visibility.is_msp_staff`) and, for Connect, `view_app_connections` or a
   per-connection grant once one exists. Customer and portal users never see a switcher.
3. In a customer context, the customer is mapped on that connection (active `TenantGrant`, or the RMM connection belongs
   to that customer / is platform-owned and maps it). Without a mapping the entry is shown disabled with the reason
   (§6.3), not hidden, so a technician learns why.

Offline or Degraded entries stay listed with their status badge; the link still opens (the other application may be
reachable from the browser even when the server-to-server check fails).

### 3.2 What an entry shows

Application display name (`Connection.remote_display_name` or the provider display name), application type icon from
the shared icon map, status badge (§7), and the customer it will open for, if any. No version numbers to technicians.

### 3.3 What an entry links to

Only an origin Clientst0r already approved:

- Connect: the origin of `Connection.base_url` (the discovery address approved at pairing; endpoints must be
  same-origin, `PROTOCOL.md` §4).
- RMM: `validated_console_url()` against `console_hosts()` (`integrations/providers/rmm/console.py:22-34`): https only,
  no user info, host in the connection's allowed set.

The landing path is the application's root, or a deep link from §5. Opens in a new tab with
`rel="noopener noreferrer"`.

### 3.4 Placement

Appearance and position are specified in [SHARED_DESIGN_SYSTEM.md](SHARED_DESIGN_SYSTEM.md) §10 (top bar, right of
the app identity, current application first). Keyboard reachable; the Ctrl+K palette lists the same entries under
"Applications" with the same gates.

## 4. Customer context

Status: **existing** for the mapping model; the browser hand-off is **proposed — needs Rem0te agreement via
INTEGRATION_COORDINATION.md**.

### 4.1 Existing mapping model

- **Connect** (`PROTOCOL.md` §8, `connect/models.py:342-367`): a `TenantGrant` maps one local customer to the peer's
  tenant id per connection, with scopes; unique per (connection, remote tenant) and (connection, customer). A request
  names the tenant with `Agit8or-Tenant` in the caller's namespace; the receiver resolves it only through its own active
  grants for that connection; unknown or revoked ids get `403 tenant_not_granted`; an id that happens to equal a local
  id is never accepted as-is (§8.1).
- **ticket-rmm-v1** (`integrations/ticket_rmm.py:1-40`, `INTEGRATION_COORDINATION.md` §1): one pairing = one remote
  tenant = one Clientst0r customer; the tenant is pinned from the first signed capabilities response and a later
  response naming another tenant stops the pairing (`tenant_mismatch`). Rem0te devices must belong to the pinned
  business to be targets (`psa_ai/services/rmm_actions.py:153-155`).
- Mapping changes are protected changes approved by a second administrator where the protocols say so.

### 4.2 Rules for carrying context between applications (local rules)

1. The receiving application decides the customer. It resolves what it receives through **its own** mapping for the
   connection the link came from. A customer id, role, permission or user in a link is never trusted.
2. If the receiving application cannot resolve the context (no mapping, revoked grant, user not allowed there), it
   opens its own neutral landing page with the explanation from §6.3. It never falls back to "all customers" or to the
   user's last customer.
3. The user is always authenticated by the receiving application: its own session, its own 2FA, or optional SSO
   (§9). No cookie, session or token is copied between applications.
4. Switching never changes the source application's selected customer.

### 4.3 Return to the original context (local rule + proposed)

Clientst0r keeps the user's place locally: the outbound link is opened in a new tab, so the original ticket or asset
tab stays open (P4). A "back to Clientst0r" link from the other application is **proposed**: it uses only the deep-link
form of §5 pointing at Clientst0r's own origin as known to the other application from pairing, never a URL passed in
the link.

## 5. Deep links

Status: one form **existing**; the general form is **proposed — needs Rem0te agreement via INTEGRATION_COORDINATION.md**.

### 5.1 Existing: device console links

Rem0te provider: `{site root}/endpoints/{external_id}` (`integrations/providers/rmm/rem0te.py:204-221`), opened with the
technician's own Rem0te sign-in; carries no key or credential. Other providers use static or on-demand vendor links,
always passed through `validated_console_url()`. On-demand links are fetched on the server in a POST or an explicit
click, never on page render (`integrations/views.py:1238-1262`).

### 5.2 Proposed general form

```
https://{approved origin}{path from the target's advertised template}
   ?ctx_conn={target's connection id for the source}
   &ctx_tenant={source's tenant id, as in Agit8or-Tenant}
   &ctx_type={ticket|asset|device|customer}
   &ctx_ref={source object id}
```

- **Templates come from the target**, not the source: a proposed `ui_links` object in the discovery document, e.g.
  `{"device": "/endpoints/{ref}", "customer": "/customers/{tenant}"}`. Same-origin rule as for endpoints
  (`PROTOCOL.md` §4); unknown keys ignored (§3). Absent `ui_links` → only the application root is linked.
- The target resolves `ctx_conn` + `ctx_tenant` through its own grant (rule 4.2.1) and `ctx_ref` through its own data;
  any mismatch → neutral page with the reason.
- **Never in a link:** tokens, codes, assertions, keys, passwords, session ids, signed JWS, user ids or roles (X4).
  Note: Quick Connect's browser leg carries a single-use 43-character code and signed JWS in the callback query
  (`PROTOCOL-1.1.md` §5.4). That is a bounded bootstrap step bound to the administrator's session and `state`; it is not
  a pattern for navigation links.
- **No redirect parameter.** No `next`, `return_to` or `redirect_uri` with a free URL (X3). Returning is done by the
  same template mechanism in the other direction.
- Links are built on the server from stored, validated values; the browser never assembles them.
- Link length ≤ 2,000 characters; all values URL-safe (`[A-Za-z0-9_.:-]`, the `TENANT_RE` of
  `integrations/ticket_rmm.py:72`), at most 100 characters each.

## 6. Capability discovery and what the UI offers

### 6.1 Sources (existing)

| Protocol | Where capabilities come from | Stored |
|---|---|---|
| Connect | discovery `capabilities[]` with `available`, `PROTOCOL.md` §4, §7.2; effective permission = token scope ∩ grant scopes (§8.2); `GET {capabilities}` per connection (§10) | `Connection.remote_catalog`, `outbound_scopes`, `TenantGrant.scopes` |
| Connect 1.1 | `extensions` negotiation (`PROTOCOL-1.1.md` §3), downgrade check | negotiated on pairing |
| ticket-rmm-v1 | signed `/capabilities` (contract revision, features, organizations[], paused[]) | `field_mappings['ticket_rmm_capabilities']`, Rem0te `pairing.last_check()`; `KNOWN_CAPABILITIES` (`integrations/ticket_rmm.py:65-69`) |

### 6.2 UI rules (local rules)

1. An action is shown enabled only if the capability is in the last *compatible* check **and** the user holds the local
   permission for this customer (technician access assignment, RMM permission policy).
2. Unknown capabilities are ignored, never shown (`PROTOCOL.md` §3).
3. If the capability exists but the user may not use it, show the control disabled with the reason
   (`psa_ai/services/rmm_actions.py:256-285` already returns per-action `reason`).
4. If no connection offers it for this customer, show one sentence, not a row of dead buttons (existing
   `no_target_reason`).
5. A Rem0te containment pause (`paused[]`) disables the matching actions with Rem0te's reason category, never its
   free text (`integrations/rem0te/actions.py:160-166`).

### 6.3 Explanations (local rule; wording for both applications)

| Situation | Text pattern |
|---|---|
| No customer mapping | "{Customer} is not mapped on the {Application} connection. An administrator can add it under Settings → Integrations → {connection}." |
| Mapping revoked | "Access to {Customer} through {Application} was removed on {date}." |
| Permission denied | "You don't have {permission} for {Customer}. Ask an administrator for the {role} assignment." |
| Missing technician mapping | "Your Clientst0r user is not linked to a {Application} technician, so {Application} cannot check your access." |
| Capability not offered | "{Application} {version} does not offer {capability}." |
| Paused by peer | "{Application} has paused {area} for this customer." |

## 7. Integration health and errors

### 7.1 Existing state models

| Source | States | Where |
|---|---|---|
| Connect | Pending Setup, Awaiting Approval, Awaiting Network Authorization, Testing, Connected, Degraded, Offline, Security Blocked, Suspended, Revoked, Setup failed | `connect/status.py` (one `display()` used everywhere) |
| Rem0te ticket-rmm-v1 | Connected, Degraded, Disconnected, Authentication Problem, Configuration Required | `integrations/rem0te/health.py:43-57` |
| Sync health (all integrations) | success, partial, error, never; last successful sync kept separately | `integrations/health.py:28-31` |
| Monitoring sources | verified / stale / unverified / failed | `events/source_health.py` |

### 7.2 Presentation rules (local rules)

1. **Technicians** see one badge per connection, from the shared vocabulary: Connected (success), Degraded (warning),
   Offline (danger), Action needed (secondary: configuration or approval pending), Security Blocked (danger),
   Revoked (neutral). Mapping: Rem0te "Disconnected" → Offline, "Authentication Problem" → Security Blocked, "Configuration
   Required" → Action needed. Labels in admin pages keep their detailed names.
2. **Administrators** get the reason and next step (existing: Connect diagnostics, Rem0te health reasons, sync-health
   issues with `action`). Errors are redacted (`integrations/health.py` `redact()`).
3. One message per connection and state, not one per failed request (rule F8; existing 30-minute dedup in
   `connect/alerts.py`).
4. A peer problem is shown where the peer's data is shown (panel, tab), never as a site-wide banner for technicians.
   Site-wide system warnings stay for administrators and only for configured connections (S5).
5. Colour is never the only signal: badge text always present (WCAG; see SHARED_DESIGN_SYSTEM.md).

## 8. Stale data

Local rules, extending what `_rmm_device_summary.html` and `events/source_health.py` already do:

1. Every panel of external data shows "as of {time}" (last *successful* refresh), with the exact time in a tooltip.
2. Data older than its source's expected interval is labelled **Stale** and its live-sounding values are qualified
   ("Online as of 3 h ago", not "Online").
3. No data from a configured source is "Not received yet", never "0", "none" or a green check.
4. No source configured: the panel is hidden (S3/S8); if a user added it by hand, it says "not connected" (F6).
5. Actions that depend on fresh state (remote launch, fix referral) are still allowed on stale data, but the RMM is the
   authority: Clientst0r never claims a session started or a fix ran until the RMM reports it (existing:
   `templates/psa/_ticket_rmm_panel.html` "Link issued — session not confirmed").

## 9. Optional identity

Existing (`docs/OIDC_SSO.md`, `oidc_sso/`): OIDC is optional per installation; local login, TOTP and the superuser
break-glass at `/account/login/` always remain; IdP claims never grant superuser; back-channel logout ends local SSO
sessions. Rules for paired applications:

- Each application is its own OIDC client with its own session. A shared IdP gives single sign-on, not a shared session.
- Application roles and customer access are decided locally after sign-in. Group-to-role mapping is local
  configuration on each side.
- Coordinated logout across applications is **proposed — needs Rem0te agreement via INTEGRATION_COORDINATION.md**: via
  each application's own back-channel logout endpoint at the IdP, not via calls between the applications.

## 10. Security constraints (summary)

X1 no shared cookies, sessions or tokens across applications; X2 peer customer ids, roles and users are resolved
through local mappings only; X3 no arbitrary redirect URLs; X4 no secrets in URLs; X5 protocol changes only through
`INTEGRATION_COORDINATION.md`; plus the existing protocol guarantees: Ed25519 only, replay stores, immutable
organization mappings (pinned tenants), second-administrator approval for high-risk and admin scopes and for mapping
changes, default-deny source addresses, optional mTLS, append-only hash-chained audit (`PROTOCOL.md` §2, §7.3, §14, §16;
`docs/CONNECTED_APPLICATIONS.md`). Clientst0r requests; the RMM authorizes, approves and executes (P3).

## 11. Compatibility matrix

Versions that this contract has been checked against. "UX contract" is this document; "design spec" is
`design-tokens.json` `meta.version`.

| Clientst0r | UX contract | Design spec | Connect protocol | Connect SDK | ticket-rmm-v1 | Rem0te |
|---|---|---|---|---|---|---|
| 3.17.776 | 0.1.0 (draft) | 1.0.0 | `agit8or-connect/1` + revision 1.1 extensions `qc-bootstrap/1`, `qc-source-binding/1`, `qc-diagnostics/1` | 1.1.0 (`agit8or_connect/__init__.py:35`) | revision 2 (`integrations/rem0te/schema.py:44`) | pinned 0.68.0 @ `5a43f023` (`integrations/rem0te/contract/PIN.json`); oldest accepted 0.26.0, alerts from 0.29.0 (`integrations/rem0te/pairing.py:60-61`) |

Rules:

- The UX contract and the design spec are **development-time** specifications. They never gate runtime compatibility:
  two installations on different design-spec versions interoperate fully. Mismatch only affects how consistent the two
  look.
- A UX-contract item marked **proposed** that needs a protocol change takes effect only when both sides advertise it
  through the protocol's own negotiation (discovery `versions`/`extensions`, ticket-rmm-v1 `contract_revision`).
  Unknown fields are ignored (`PROTOCOL.md` §3), so a newer peer never breaks an older one.
- Semver: patch = wording; minor = new optional rule or proposed item; major = a rule that changes existing behaviour.

## 12. Proposed contract changes

None is implemented. Each needs agreement through `INTEGRATION_COORDINATION.md` before code changes on either side.

| ID | Proposal | Protocol touched | Why |
|---|---|---|---|
| CX-1 | Discovery `ui_links` object: target-owned deep-link path templates (§5.2), same-origin, optional | Connect discovery (additive, ignored by older peers) | Deep links without trusting the source's URLs |
| CX-2 | Context query parameters `ctx_conn`, `ctx_tenant`, `ctx_type`, `ctx_ref` resolved by the receiver through its grant (§5.2) | None on the wire between servers; browser URL convention | Tenant-aware deep links |
| CX-3 | Discovery `app.icon` key from the shared icon map and `app.ui_base` (origin of the user-facing UI if it differs from the API origin, same registrable domain, approved at pairing) | Connect discovery (additive) | Switcher entries with the right icon and address |
| CX-4 | Shared health vocabulary (§7.2) used in both applications' technician-facing UI | None | Same words in both products |
| CX-5 | Rem0te renames its "Disconnected" (unreachable) display state to "Offline" where Clientst0r shows it, matching Connect | None | Terminology clash (§2) |
| CX-6 | Coordinated logout through each app's IdP back-channel endpoint (§9) | None between apps | Optional SSO logout |
| CX-7 | A remote-session confirmation event so a launch can be shown as started (open request R6, `INTEGRATION_COORDINATION.md:221`) | ticket-rmm-v1 / Connect events | Never claim a session started without confirmation |
| CX-8 | Technician-mapping status in capabilities ("this technician is / is not mapped") for the §6.3 explanation | ticket-rmm-v1 `/capabilities`, later Connect actor claims | Missing-mapping explanations |
