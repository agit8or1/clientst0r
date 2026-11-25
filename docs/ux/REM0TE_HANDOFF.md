# Design and integration UX handoff to Rem0te

| | |
|---|---|
| Handoff version | **1.0.0-draft** (2026-11-25) |
| From | Clientst0r (owner of the shared design specification) |
| To | Rem0te session, and any other MSPZero application adopting the specification |
| Clientst0r version | 3.17.776 (`dev/ux-program`, based on `origin/main` 2d26c309) |
| Commit / tag | *to be filled by the lead at release* |
| Status | Draft for review. Nothing here is a runtime dependency. Protocol changes are proposals only. |

Rem0te consumes this specification independently, in its own repository and on its own schedule. Clientst0r does not
modify the Rem0te repository and does not depend on Rem0te at runtime. Technical protocol changes go through
`INTEGRATION_COORDINATION.md` (the coordination file), not through this handoff.

## 1. What is in the handoff

| # | Item (§26) | Where | Status |
|---|---|---|---|
| 1 | Design-system version | [design-tokens.json](design-tokens.json) `meta.version`; [SHARED_DESIGN_SYSTEM.md](SHARED_DESIGN_SYSTEM.md) header and §12 | 1.0.0 |
| 2 | Design tokens | [design-tokens.json](design-tokens.json) (W3C design-tokens format, `--cs-` CSS prefix in Clientst0r; each app chooses its own prefix) | ready |
| 3 | Typography | SHARED_DESIGN_SYSTEM.md §5 | ready |
| 4 | Icon mapping | SHARED_DESIGN_SYSTEM.md §6 | ready |
| 5 | Theme specification (light, dark) | SHARED_DESIGN_SYSTEM.md §4, design-tokens.json | ready |
| 6 | Component dimensions | SHARED_DESIGN_SYSTEM.md §7–§8 | ready |
| 7 | Layout rules | SHARED_DESIGN_SYSTEM.md §9 | ready |
| 8 | Navigation conventions | SHARED_DESIGN_SYSTEM.md §4.4, §9 | ready |
| 9 | Common terminology | [CROSS_APP_UX_CONTRACT.md](CROSS_APP_UX_CONTRACT.md) §2 | ready (includes proposal CX-5) |
| 10 | Application switcher behaviour | CROSS_APP_UX_CONTRACT.md §3; appearance SHARED_DESIGN_SYSTEM.md §10 | specified, not built |
| 11 | Standalone requirements | [STANDALONE_REQUIREMENTS.md](STANDALONE_REQUIREMENTS.md) §2 (rules I, S, P, F, D) | ready |
| 12 | Customer context contract | CROSS_APP_UX_CONTRACT.md §4 | existing model + proposed browser hand-off |
| 13 | Deep-link specification | CROSS_APP_UX_CONTRACT.md §5 | existing console links + proposed CX-1/CX-2 |
| 14 | Optional identity requirements | CROSS_APP_UX_CONTRACT.md §9; `docs/OIDC_SSO.md` | ready |
| 15 | Capability discovery | CROSS_APP_UX_CONTRACT.md §6; `docs/agit8or-connect/PROTOCOL.md` §4, §7, §10 | existing |
| 16 | Integration error handling | CROSS_APP_UX_CONTRACT.md §6.3, §7 | ready (includes CX-4) |
| 17 | Fault-isolation requirements | STANDALONE_REQUIREMENTS.md §2.4 (F1–F12) | ready |
| 18 | Compatibility requirements | CROSS_APP_UX_CONTRACT.md §11 | ready |
| 19 | Security constraints | CROSS_APP_UX_CONTRACT.md §10; `docs/agit8or-connect/PROTOCOL.md` §16 | existing |
| 20 | Reference screenshots | Current UI: guide images under `docs/images/guides/` (e.g. `guide-connected-apps.png`). Component screenshots in both themes are planned with the component showcase (SHARED_DESIGN_SYSTEM.md §14, I-7) | partial: not yet captured for the new spec |
| 21 | Acceptance criteria | §3 below | ready |
| 22 | Proposed contract changes | §4 below; CROSS_APP_UX_CONTRACT.md §12 | proposals only |

## 2. Version set this handoff describes

| Artifact | Version |
|---|---|
| Design specification (`design-tokens.json` `meta.version`) | 1.0.0 |
| Cross-app UX contract | 0.1.0 (draft) |
| Standalone requirements | 1.0 |
| Agit8or Connect protocol | `agit8or-connect/1`, revision 1.1 extensions (`qc-bootstrap/1`, `qc-source-binding/1`, `qc-diagnostics/1`) |
| Connect SDK (`agit8or_connect`) | 1.1.0 |
| ticket-rmm-v1 | contract revision 2; Rem0te pin 0.68.0 @ `5a43f02318192dda3f2033be20b1fa9dda3578b5` |

The design specification and the UX contract are development-time documents. A Rem0te on another design version
interoperates fully; only visual consistency differs (CROSS_APP_UX_CONTRACT.md §11).

## 3. Acceptance checklist for an adopting application

Tick in the adopting application's own repository. Each line names the rule it checks.

**Standalone (release-blocking)**
- [ ] Installs, sets up, signs in and runs every local feature with no Clientst0r and no other peer configured (I1, I2).
- [ ] No application switcher, peer widget, peer nav entry, upsell or reserved space when nothing is paired (S1–S8).
- [ ] Integrations stay discoverable in its own settings (S9).

**Fault isolation**
- [ ] Every outbound request has connect and read timeouts; retries are limited and back off (F1, F2).
- [ ] No call to a peer while a page renders; network work runs in jobs or explicit user actions (F3).
- [ ] A peer that is down, slow, revoked or incompatible never blocks a local page (F3, F4, F11).
- [ ] External data shows "as of" its last successful refresh and is never shown as current or healthy when stale (F5, F6).
- [ ] One notification per connection and state, not per failed request (F8).
- [ ] Revoking or removing a connection keeps local records and audit history (D1, D2).

**Cross-app behaviour**
- [ ] Switcher entries only for configured, active connections the user may open (contract §3).
- [ ] Incoming deep links are treated as hints: own authentication, own authorization, own customer mapping; no
      fallback to another customer (contract §4.2).
- [ ] No secrets, tokens, codes, user ids or roles in URLs; no free redirect parameters (contract §5.2; X3, X4).
- [ ] Capabilities shown only from the last compatible check and the user's local permission (contract §6.2).
- [ ] Health badges use the shared vocabulary for technicians (contract §7.2).
- [ ] Shared terminology used in UI text (contract §2).
- [ ] The application executes privileged actions only after its own authorization and approval; requests from
      Clientst0r are requests (P3).

**Design**
- [ ] Tokens imported from `design-tokens.json` at build time and bundled; nothing loaded from another app or a CDN.
- [ ] Text and UI colour pairs meet WCAG 2.2 AA in light and dark (SHARED_DESIGN_SYSTEM.md §4.3).
- [ ] The adopting app records which design-spec version it implements, and runs a drift check against it (Clientst0r's
      own check: `scripts/ux/check_design_tokens.py`, `core/tests/test_design_tokens.py`).

## 4. Proposed contract changes (need agreement via INTEGRATION_COORDINATION.md)

Listed in full in CROSS_APP_UX_CONTRACT.md §12. Summary for the coordination file; the lead posts them there, this
document does not:

| ID | Proposal | Needs from Rem0te |
|---|---|---|
| CX-1 | Discovery `ui_links`: target-owned deep-link templates | Publish templates for computer, customer, alert pages |
| CX-2 | Context parameters `ctx_conn`, `ctx_tenant`, `ctx_type`, `ctx_ref`, resolved through the receiver's own mapping | Accept and resolve them; neutral page on mismatch |
| CX-3 | Discovery `app.icon` and `app.ui_base` | Publish them |
| CX-4 | Shared technician-facing health vocabulary | Use the same six labels |
| CX-5 | "Offline" for unreachable, "Revoked" for ended | Rename where it shows Clientst0r's state |
| CX-6 | Coordinated logout through each app's IdP back-channel endpoint | Implement back-channel logout as its own OIDC client |
| CX-7 | Remote-session confirmation event (open item R6) | Emit it |
| CX-8 | Technician-mapping status in capabilities | Report it |

Until agreed, Clientst0r keeps using only what exists today: console deep links (`integrations/providers/rmm/rem0te.py:204-221`),
the ticket-rmm-v1 revision 2 contract and Agit8or Connect 1 / 1.1.

## 5. Changes in Clientst0r relevant to Rem0te in this batch

- The ticket page no longer polls or re-sends Rem0te action proposals while it renders; the minute scheduler
  (`integrations/rem0te/reconcile.py`) does it. On the wire nothing changes: the same `GET /action-proposals/{id}` and
  idempotent `POST /action-proposals` are sent, from the scheduler instead of page views. A Rem0te may see fewer and
  more evenly spaced status reads.

## 6. Change log of this handoff

| Version | Date | Change |
|---|---|---|
| 1.0.0-draft | 2026-11-25 | First handoff: design spec 1.0.0, UX contract 0.1.0, standalone requirements 1.0. |

A token change bumps `design-tokens.json` `meta.version` and adds a row here (CLAUDE.md, "Shared design system").
