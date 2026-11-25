# Standalone operation and optional integration: requirements, audit and test matrix

Version 1.0 (2026-11-25), audited against Clientst0r 3.17.776 (`dev/ux-program`, based on `origin/main` 2d26c309).
Program sections covered: §2 (standalone), §6 (identity and integration), §9 (RMM parts of the ticket workspace), §24
(test matrix). The cross-app rules are in [CROSS_APP_UX_CONTRACT.md](CROSS_APP_UX_CONTRACT.md); the handoff to Rem0te is
in [REM0TE_HANDOFF.md](REM0TE_HANDOFF.md).

Standalone operation is a **release-blocking** requirement. Every rule below can be checked in code review or with a
test. A rule ID (S1, F3 …) is cited in tests and in review comments.

Evidence in this document comes from reading the code at the `path:line` shown. Timing figures marked *estimated* are
worked out from the timeouts in the code, not measured on a running server.

## 1. Configurations that must all work

None is the "real" one. The test matrix in §5 exercises each.

| # | Configuration |
|---|---|
| C1 | Clientst0r alone: no RMM, no Connect, no SSO |
| C2 | Paired with Rem0te (ticket-rmm-v1 and/or Agit8or Connect) |
| C3 | One supported third-party RMM (Tactical RMM, NinjaOne, Datto RMM, Atera, ConnectWise Automate, others in `integrations/providers/rmm/`) |
| C4 | Several RMM providers at once, also for the same customer |
| C5 | Next to other MSPZero applications (st0r, OPNManager, m0nitor …) through Agit8or Connect |
| C6 | Next to unrelated software, with no integration at all |

## 2. Rules

### 2.1 Independence (I)

| ID | Rule | How to check |
|---|---|---|
| I1 | Install, setup wizard, migrations and first sign-in complete with no peer, no Connect and no IdP configured. | Fresh-install test with every integration setting at its default. |
| I2 | Every local feature (tickets, billing, documentation, vault, customers, search, reports, backups, updates, health) works with every peer setting at its default. | Standalone smoke test (P0-1). |
| I3 | No setup step, readiness check or banner requires or recommends a peer. | Grep `core/readiness.py`, `onboarding/steps/`; review. |
| I4 | Peer features are off by default (`AGIT8OR_CONNECT_ENABLED=False`, Quick Connect off, no OIDC provider, no RMM). | `config/settings.py:788`; tests per flag. |
| I5 | No standalone feature is restricted to push Rem0te; no other RMM is degraded in its favour. Rem0te is one provider among several. | Review: every capability check goes through provider-neutral code (`integrations/ticket_rmm.py`). |
| I6 | Local upgrades, backup and restore never contact a peer and succeed with the peer missing. | Restore test with Connect / Rem0te rows and no peer (P0-5). |

### 2.2 Standalone interface (S)

| ID | Rule |
|---|---|
| S1 | No application switcher unless at least one other application is configured, active and usable by this user. |
| S2 | No cross-application actions (open in peer, hand off, launch) unless the capability is live for this customer and user. |
| S3 | Peer-specific dashboard widgets are not in any default layout while no matching integration exists. |
| S4 | Peer-specific navigation entries outside Settings → Integrations are hidden while no matching integration exists. |
| S5 | No persistent warning about a missing optional integration. Warnings are about configured integrations that fail. |
| S6 | No advertisement, upsell or persistent recommendation for another product. A one-line pointer in an empty state of an integration-specific page is allowed. |
| S7 | No broken link and no control that cannot work in the current configuration. |
| S8 | No empty space reserved for a missing application (empty cards, empty tabs, "0" figures for data nobody collects). |
| S9 | Optional integrations stay discoverable under Settings → Integrations. |

### 2.3 Paired interface (P)

| ID | Rule |
|---|---|
| P1 | A cross-app capability is offered only when both sides advertise it (Connect scopes and catalog, ticket-rmm-v1 capabilities) and the last check was compatible. |
| P2 | Each action names the provider and connection it goes to. |
| P3 | Clientst0r requests and records; the RMM authorizes, approves and executes. Clientst0r and OPTIONAL AI never execute privileged RMM actions. |
| P4 | The original ticket / asset / customer context is restorable after switching applications and returning. |

### 2.4 Fault isolation (F)

| ID | Rule |
|---|---|
| F1 | Every outbound request has a bounded connect and read timeout. |
| F2 | Retries are limited and back off; non-idempotent requests are not retried automatically by the HTTP layer. |
| F3 | No outbound call to a peer or RMM on the page-render path (GET views, template tags, context processors, dashboard builders). Reads come from stored state; network work runs in scheduled jobs or in an explicit POST the user started. |
| F4 | A failing peer is backed off as a whole (circuit breaker / hysteresis), not retried per page view or per record. |
| F5 | External data shows when it was last successfully refreshed. |
| F6 | Missing or stale external data is never shown as current or healthy ("no alerts" is not "healthy" when nothing is collected). |
| F7 | Administrators see a clear reason and next step for each failure (health page, diagnostics). |
| F8 | Repeated failures do not flood technicians (deduplication, rate limits on alerts and notifications). |
| F9 | A sensitive operation is never silently rerouted to another provider when its provider fails. |
| F10 | Local sign-in and break-glass recovery work when the IdP is down or misconfigured. |
| F11 | A user-started outbound operation completes, fails or is handed to the background within the web worker timeout (300 s, `deploy/clientst0r-gunicorn.service:17`); interactive ones should answer in 30 s or less. |
| F12 | Response size is capped. |

### 2.5 Data retention (D)

| ID | Rule |
|---|---|
| D1 | Disabling, revoking or deleting an integration never deletes local customers, tickets, documentation, billing or audit records. |
| D2 | Historical integration references (which RMM request, alert link or event belonged to which ticket) are kept or kept readable after the integration is removed. |
| D3 | When a removal is refused to protect history, the page says why and offers "disable" instead. |

### 2.6 Cross-app security (X), summary

Details in [CROSS_APP_UX_CONTRACT.md](CROSS_APP_UX_CONTRACT.md) §8. X1 no shared cookies or sessions; X2 a peer's customer
ID, role or user is never trusted without a local mapping; X3 no arbitrary redirect URLs; X4 no secrets in URLs; X5 no
protocol change without the coordination document.

## 3. Audit findings

Status: **meets**, **gap**, **fixed** (fixed in this batch, §4) or **unknown** (not verified). Severity is for the
standalone requirement only: **high** = can block local work, **medium** = misleads or clutters, **low** = polish.

### 3.1 Page-render path and outbound calls

| Where | Rule | Status | Sev. | Finding | Fix |
|---|---|---|---|---|---|
| `psa_ai/services/rmm_actions.py:278` (before this batch), called from `psa/views.py:585` | F3, F4, F11 | **fixed** | high | The ticket page's RMM panel called `integrations.rem0te.actions.refresh()` for up to 20 open fix referrals on every view. For a proposal that could not be sent (`created`, no `remote_id`), `refresh()` re-sent it as a **POST** with no rate limit (`integrations/rem0te/actions.py:187-190` checks `POLL_EVERY` only after the resend branch). Each call can wait `TIMEOUT = (5, 20)` s (`integrations/rem0te/client.py:35`). With Rem0te black-holing traffic: up to 25 s per request, 20 requests, about 500 s *estimated*, past the 300 s worker timeout, so the ticket page fails. The panel's own docstring (`psa/views.py:1412`) already promised "no RMM call while the page renders". | Render-path refresh removed; the scheduler already re-sends and polls every minute (`integrations/rem0te/reconcile.py:75` → `actions.poll_open`). Open requests now show "status as of …". Tests in §4. |
| `core/context_processors.py` (all) | F3 | meets | — | No network call. The update badge reads stored values (`core/context_processors.py:171-204`). | — |
| `integrations/templatetags/integration_health.py:17`, `oidc_sso/templatetags/oidc_sso_tags.py:6` | F3 | meets | — | Read stored rows only. The OIDC button tag survives a missing table. | — |
| `core/dashboard_widgets.py`, `core/dashboard_global.py`, `accounts/client_workspace.py` | F3 | meets | — | RMM figures come from synced rows (`RMMAlert`, `RMMDevice`); no provider call. | — |
| `integrations/views.py:1238` `rmm_device_open` | F3, F11 | meets | low | GET, but only on an explicit click; one vendor call, `timeout=30` default plus up to 3 GET retries (below). | Covered by P0-4. |
| `integrations/providers/base.py:91-108` | F1, F2, F11 | gap | medium | Every provider session retries GET 3 times with `backoff_factor=1` on 429/5xx, at `timeout=30`: about 4 × 30 s + 7 s ≈ 127 s *estimated* for one interactive "Test connection" or console link. | P0-4: shorter interactive budget (e.g. `(5, 15)`, 1 retry) for user-started calls; keep sync budgets for jobs. |
| `integrations/views.py:1443` `rmm_trigger_sync` | F11 | gap | medium | "Sync now" runs a full `RMMSync.sync_all()` inside the POST. A large or slow RMM can hold a web worker past 300 s. | Increment: queue the sync for the scheduler and show progress (pattern exists for upgrades). |
| `integrations/views.py:3800`, `:4289` (`distributor_test`, `accounting_test`) | F3 | gap | low | Outbound test runs on GET (no `require_POST`): a prefetching browser or crawler can trigger it. | Add `@require_POST` (both are AJAX buttons). |
| `integrations/rem0te/client.py:35,108-140` | F1, F2, F12 | meets | — | `(5, 20)` timeout, no redirects, `trust_env=False`, SSRF guard, 4 MiB response cap (`MAX_RESPONSE`, `:36`). | — |
| `connect/transport.py:28`, `agit8or_connect/adapters/safe_http.py:212-247` | F1, F2, F12 | meets | — | `(5, 15)` s, `max_retries=0`, no redirects, size cap, connect-time IP checks. | — |
| `oidc_sso/http.py:27-28,100` | F1, F10 | meets | — | `(5, 10)` s, no redirects. Superusers keep `/account/login/` as break-glass (`oidc_sso/views.py:5`). | — |
| `integrations/rem0te/reconcile.py:33-48`, `connect/health.py:19` | F4 | meets | — | Rem0te: capability re-check backs off 1, 2, 4 … min up to 1 h. Connect: hysteresis (2 failures → Degraded, 3 → Offline), events wait without spending attempts while Offline. | — |
| `integrations/rem0te/pairing.py:470-476` | F9 | meets | — | An unreachable check keeps the last `compatible` result, so `processor_for()` (`integrations/ticket_rmm.py:178`, first paired connection by pk) does not switch an analysis job to a second processor during an outage. Device actions always use the device's own connection (`psa_ai/services/rmm_actions.py:132-157`). | Increment (low): let an admin choose the processor when a customer has two. |
| `connect/alerts.py:1-30`, `connect/tests/test_increment_e.py:115` | F8 | meets | — | One alert per connection and status per 30 min; mute; "thousand heartbeats while offline, one ticket" is tested. | — |

### 3.2 What a standalone installation shows

| Where | Rule | Status | Sev. | Finding | Fix |
|---|---|---|---|---|---|
| `core/navigation.py:51-59,926` Connected Applications | S4, S9 | meets | — | Shown only with `AGIT8OR_CONNECT_ENABLED` and `view_app_connections`; all Connect routes 404 while off (`connect/urls_api.py:1`). | — |
| `core/navigation.py:901` Single sign-on | S9 | meets | — | Settings → Security, for SSO managers only. Login buttons only for enabled providers (`oidc_sso/tests.py:840`). | — |
| `core/navigation.py:1387` RMM Devices, `:1457` RMM Alerts | S4, S8 | gap | medium | Shown to every MSP technician with no RMM connection. The pages themselves have good empty states (`templates/integrations/rmm_alerts.html:137`). | P0-3: gate on "an RMM connection exists" through the nav decision cache (`core/nav_cache.py:93` already keys on the Connect flag). |
| `core/navigation.py:1389` Device Workspace | S4 | meets (low) | low | Works on local assets; says "No RMM manages this asset" (`templates/assets/device_workspace.html:89`). | Optional: hide with P0-3. |
| `core/navigation.py:924` "RMM · Rem0te" tab | S9, I5 | gap | low | A Rem0te-only settings tab next to the provider-neutral Integrations page; other providers have none. Inside Settings, so not a standalone breach, but it gives one provider extra prominence. | Fold into the Integrations page as the Rem0te provider's detail page (needs owner decision). |
| `core/dashboard_widgets.py:1771,1781,1785` role presets | S3, S8 | gap | medium | `kpi_rmm_alerts` / `rmm_alerts` are in the Admin, L3 and L2 default layouts and `g_kpi_rmm` / `g_rmm_alerts` in the global layout (`:1810`) with no RMM. | P0-3: drop peer widgets from built-in layouts while no RMM exists (saved user layouts untouched). |
| `templates/core/dashboard/_w_rmm_alerts.html`, `_w_g_rmm_alerts.html` | F6 | **fixed** | medium | With no RMM the panel showed a green check and "No active RMM alerts", which reads as healthy. | Now "No RMM is connected, so no RMM alerts are collected." (`core/dashboard_widgets.py` `rmm_configured()`). Test `core/tests/test_standalone_panels.py`. |
| `core/dashboard_widgets.py:369` KPI "RMM alerts" | F6, S8 | gap | low | Shows `0` with no RMM. | P0-3 removes it from default layouts; when added by hand, show "—" and "not connected". |
| `accounts/client_workspace.py:59,217,481-486` client workspace | S8, F6 | gap | medium | RMM tab and the "RMM offline 0" KPI appear for staff with no RMM connection; "0 offline" reads as healthy. The tab's button says "Open in RMM" but opens Clientst0r's own list (`templates/accounts/workspace/_tab_lists.html:50`). | P0-3: tab and KPI only when the customer has RMM devices or an RMM connection; rename the button "All RMM devices". |
| `templates/psa/ticket_detail.html:695` | S8 | gap | low | "No RMM reports this asset." on every ticket with an asset, also with no RMM at all. | Show only when an RMM connection exists. |
| `psa_ai/services/rmm_actions.py:271-276` panel reason | S7 | meets | — | Panel shown only to assigned technicians; with no paired RMM it says why actions are unavailable instead of showing dead buttons. | — |
| `templates/assets/asset_detail.html:127,491` | S8 | meets | — | RMM tab only when devices exist. | — |
| `security_alerts/overview.py:246-249` | F6 | meets | — | "Not configured" state with no RMM connection; tested (`security_alerts/tests_overview.py:182`). | — |
| `templates/assets/asset_list.html:124`, `templates/integrations/rmm_devices.html:150` | S6 | meets | — | Empty-state pointer "Connect an RMM" (provider-neutral, only when the list is empty). No product advertising found (grep for Rem0te/"install"/"try" phrases in `templates/`). | — |
| `core/readiness.py:213`, `onboarding/steps/` | I3 | meets | — | No readiness check or onboarding step mentions a peer. | — |
| Application switcher | S1 | meets (absent) | — | No switcher exists today (no template or nav code). Specified in the contract before one is built. | — |

### 3.3 Stale data

| Where | Rule | Status | Sev. | Finding |
|---|---|---|---|---|
| `templates/integrations/_rmm_device_summary.html:13-27` (asset, ticket) | F5, F6 | meets | — | Online / Offline / **Stale data** / Status unknown, "Last check-in" and "Data refreshed". |
| `integrations/health.py`, `templates/integrations/_sync_health.html` | F5, F7 | meets | — | Last *successful* sync kept separately from the last attempt; redacted errors; suggested action. |
| `events/source_health.py:365-508` | F5, F6 | meets | — | Freshness per source, "verified healthy" only on evidence. |
| `templates/accounts/workspace/_tab_lists.html:56-58` | F5 | gap | low | Online/Offline badges without the connection's last sync time; a device from a dead connection still says Online. | Reuse the `_rmm_device_summary` status rule (stale after the sync interval). |
| `templates/psa/_ticket_rmm_panel.html` request list | F5 | **fixed** | low | Open requests had no freshness. Now "status as of <time>". |

### 3.4 Removing or disabling an integration

| Where | Rule | Status | Sev. | Finding | Fix |
|---|---|---|---|---|---|
| `connect/models.py:59-245`, `PROTOCOL.md` §12 | D1, D2 | meets | — | Connections are revoked, never deleted from the UI; audit is append-only (`connect/models.py:441-496`); "Revoke … customer records, events and audit history are kept"; tested (`connect/tests/test_security.py:462`). | — |
| `integrations/models.py:558,690,728,767` | D1 | meets | — | Deleting an RMM connection deletes its mirrored devices, alerts, software and snapshots (peer data). Assets survive (`RMMDevice.linked_asset` is `SET_NULL`, `:632`). | — |
| `psa_ai/models.py:535` `RMMRequest.connection` `PROTECT` | D2, D3 | gap | medium | History is protected, but deleting such a connection ends in "Database integrity error. Related records may exist." (`integrations/views.py:883-887`): no reason, no "disable instead". | Catch `ProtectedError`, say how many ticket requests reference it, offer Disable (`is_active=False`). |
| `psa/routing/models.py:570` `AlertTicketLink.connection` `CASCADE`; `psa_ai/models.py:618,648` `Rem0teAlertEvent`, `Rem0teAlertTicket` `CASCADE` | D2 | gap | medium | Deleting the RMM connection deletes the record of which alert opened which ticket. Tickets survive (`Rem0teAlertTicket.ticket` is `SET_NULL`), the link evidence does not. | Increment: `SET_NULL` plus stored connection name / provider on the link rows (migration), or require Disable for connections with links. |
| `psa/routing/models.py:493` `AlertMaintenanceWindow.device` `CASCADE` | D1 | gap | low | A maintenance window for one device disappears when the device goes away in a sync. Configuration, not history. | Review with the routing owner. |
| `integrations/models.py:362` `RMMConnection.is_active` | D1 | meets | — | Disable exists and keeps everything. | — |

### 3.5 Identity (§6)

| Where | Rule | Status | Finding |
|---|---|---|---|
| `oidc_sso/` (`docs/OIDC_SSO.md`) | F10, X1 | meets | Optional, off until a provider is enabled; local login and TOTP unchanged (`oidc_sso/tests.py:400,644,726`); never grants superuser (`:482`); back-channel logout (`:772`). |
| `connect/` tokens | X1 | meets | No cookies or sessions cross apps; DPoP-bound 300 s tokens (`PROTOCOL.md` §6). |
| Technician mapping | §6 | partial | ticket-rmm-v1 delegation carries `tech-<id>` (`INTEGRATION_COORDINATION.md` §4.2); Connect actor claims are planned (`PROTOCOL.md` §17). No UI explains a missing technician mapping yet. |
| Coordinated logout across apps | §6 | not built | Only IdP logout. Proposed in the contract (§5). |

## 4. Fixed in this batch

| Change | Files | Test |
|---|---|---|
| Ticket page no longer calls Rem0te while rendering; the scheduler (every minute) re-sends and polls proposals. Open requests show "status as of". | `psa_ai/services/rmm_actions.py`, `templates/psa/_ticket_rmm_panel.html` | `psa_ai/tests_rem0te.py` `ActionProposalTests.test_ticket_page_never_resends_or_polls_rem0te`, `test_ticket_page_renders_while_rem0te_is_unreachable`, `test_scheduler_resends_what_the_page_no_longer_sends` |
| RMM alert panels (customer and global) say "No RMM is connected …" instead of a green "No active RMM alerts" when no RMM connection exists (one extra `EXISTS` query, only when the list is empty). | `core/dashboard_widgets.py`, `core/dashboard_global.py`, `templates/core/dashboard/_w_rmm_alerts.html`, `templates/core/dashboard/_w_g_rmm_alerts.html` | `core/tests/test_standalone_panels.py` |

Behaviour change to note in the changelog: a fix referral's status in the ticket panel now updates within about a minute
(scheduler) instead of on page load. The explicit **Refresh** on a support workflow run
(`psa/support_workflows/views.py:78-81`, POST) still reads Rem0te at once.

## 5. Test matrix (§24) and existing coverage

"Covered" means an automated test exercises the scenario; "partial" means some of the §24 checks are covered.

| | Scenario | Coverage | Existing tests | Missing |
|---|---|---|---|---|
| A | Clientst0r alone | covered (network and errors); partial (UI) | `core/tests/test_page_budgets.py` (pages render with no integration), `core/tests/test_nav_reachability.py` (static), `security_alerts/tests_overview.py:182`, `assets/tests_device_workspace.py:145`, `connect/tests/test_admin.py:203`, `oidc_sso/tests.py:840`, `core/tests/test_standalone_panels.py`, `core/tests/test_standalone_smoke.py` (every nav landing page as a superuser technician and as a portal user, no peer, `no_network()`: no 5xx, zero outbound attempts; P0-1) | Assert that no response shows a peer control (waits for P0-3). |
| B | With Rem0te | covered | `integrations/tests_rem0te.py`, `integrations/tests_rem0te_rev2.py`, `psa_ai/tests_rem0te.py`, `psa_ai/tests_rem0te_rev2.py`, two-application runs in `INTEGRATION_COORDINATION.md` §14 | — |
| C | Third-party RMMs | covered (adapters) | `integrations/tests_rmm_association.py:187-298` (NinjaOne, Datto, Atera, Automate, Tactical), `integrations/tests_rmm_data.py`, `integrations/tests_rmm_software_sync.py` | Ticket panel with a non-Rem0te ticket-rmm-v1 processor (HMAC) end to end. |
| D | Several providers | partial | `integrations/tests_rmm_association.py:527` (two RMMs share one asset), `connect/tests/test_security.py` (several installations) | Two processors for one customer: actions go to each device's own connection; no rerouting on outage (F9). |
| E | Optional SSO | covered | `oidc_sso/tests.py` `LoginFlowTests`, `MappingTests`, `TokenValidationTests`, `BackChannelLogoutTests` | IdP unreachable at login page render (only discovery on action is tested via `SSRFTests`). |
| F | Local authentication | covered | `oidc_sso/tests.py:400,644,726`, `accounts/tests_*` | — |
| G | Rem0te disconnected | partial | `connect/tests/test_security.py:185,462`, `connect/tests/test_increment_d.py:351` | Ticket and asset pages after a ticket-rmm-v1 pairing is switched off: panel hides actions, history stays. |
| H | Peer unavailable or slow | covered (render path); partial (labelling) | `psa_ai/tests_rem0te_rev2.py:282,316`, `integrations/tests_rem0te.py:272`, `connect/tests/test_increment_d.py:475`, new ticket-page tests (§4), `core/tests/standalone.py` `peer_unreachable()` with `core/tests/test_standalone_peer_unreachable.py` (ticket, asset, device workspace, client workspace, dashboards, RMM and integration pages render 200 with zero outbound attempts, timeout and refused flavours; P0-2) | Stale-data labelling on those pages; the "online" claim for data older than its sync interval. |
| I | Incompatible peer version | covered | `integrations/tests_rem0te.py:246`, `integrations/tests_rem0te_rev2.py:192-276`, `agit8or_connect/tests/test_qc_vectors.py` (downgrade) | UI test: incompatible peer hides capabilities and shows the reason on the ticket panel. |
| J | Integration disabled or removed | partial | `connect/tests/test_security.py:462` | Delete / disable an RMM connection with tickets, requests and alert links: local data and link history kept (D1–D3). |
| K | Revoked technician permissions | covered | `psa_ai/tests_rem0te.py` `L1PermissionTests`, `rmm_permissions/tests.py`, `tech_access/tests.py`, `assets/tests_device_workspace.py:220` | — |
| L | Missing or wrong customer mapping | covered | `connect/tests/test_security.py:351` (`tenant_not_granted`), `integrations/tests_platform_ownership.py:416`, `integrations/tests_rem0te_rev2.py:203`, `psa_ai/tests_rem0te.py` `test_computer_of_another_business_is_not_a_target` | UI wording for a missing mapping (contract §6). |
| M | Clientst0r upgraded alone | partial | `integrations/tests_rem0te.py:371` (migration keeps pairings), `integrations/tests_rem0te_rev2.py:193` (revision-1 peer still pairs) | Connect: a 1.1 installation with a 1.0 peer after upgrade (vectors exist, no Django-level test). |
| N | Peer upgraded alone | partial | `integrations/tests_rem0te_rev2.py:160` (unknown fields from a newer revision), `PROTOCOL.md` §3 rule | Newer Connect peer with unknown capabilities in discovery. |
| O | Backup restore without the peer | partial (SQLite path) | `core/tests/test_backup_restore.py`, `core/tests/test_sqlite_wal_backup.py` (no peer rows), `core/tests/test_restore_without_peer.py` (real `snapshot.create` / `verify` / `restore(code=False)` of a database with an RMM connection, a Rem0te row and a Connect pairing, under `no_network()`; local data and vault metadata intact, pages render, first scheduler pass at most one Rem0te check per connection; P0-5) | Not covered: the `code=True` step (git reset, pip), the MariaDB restore, Connect health `check_one` after restore, the Apply-button wrapper. |

§24 "verify" items and where they stand: install / setup / login without Rem0te (A, partial); ticketing, billing,
documentation, customers, search, reports (A, partial: rendered by page-budget tests, not asserted as a standalone
suite); no broken peer controls (gaps in §3.2); external failures do not block local work (H, partial, one defect fixed);
cross-tenant refusal (L, covered); third-party integrations unaffected (C, covered); disabling keeps history (J, partial).

## 6. Proposed P0 increments

Each is small and shippable alone. None changes a protocol.

**P0-1 Standalone smoke suite.** `core/tests/test_standalone.py`: fresh database, defaults only, sign in as superuser
and as an MSP technician, GET every nav landing page (`core/tests/nav_landing_routes.py`).
*Accept:* every page 200; no response contains `rem0te`, `Connected Applications`, `Open in RMM`, `RMM Devices` or an
application switcher; outbound sockets patched to fail the test if opened.

**P0-2 "Peer unreachable" fixture.** A test mixin that patches `requests.Session.request`, `integrations.rem0te.client.request`
and `connect.transport.for_connection` to record calls and raise a timeout, plus an RMM and Rem0te pairing with stored
data. Apply it to the ticket, asset, device workspace, client workspace, dashboard (all role presets) and RMM pages.
*Accept:* every page 200; zero recorded outbound calls; stale data labelled; no page states "healthy" or "online" for
data older than its sync interval.

**P0-3 Hide peer-only UI when nothing is configured.** One cached flag `rmm_configured` (any `RMMConnection`), part of
the nav decision cache key (`core/nav_cache.py`), invalidated on connection create/delete. Use it to hide RMM Devices and
RMM Alerts nav entries, drop RMM widgets from built-in layouts, hide the client workspace RMM tab and KPI, and the
"No RMM reports this asset" line.
*Accept:* standalone: none of these appear, query budgets unchanged (`core/tests/test_page_budgets.py`); with one RMM
connection: all appear as today; saved user layouts are not modified.

**P0-4 Outbound-request lint and interactive budget** *(shipped in the 113.6 test infrastructure: `core/tests/test_outbound_timeouts.py`; `BaseProvider.interactive()` gives "Test connection" and console links connect 5 s / read 10 s, one retry, 15 s total)*. Original proposal: `core/tests/test_outbound_bounds.py`: AST scan of every
non-test module for `requests.<verb>(`, `Session.request(`, `urlopen(` and `httpx` calls; each must pass `timeout=` or
go through an allow-listed wrapper (`integrations/providers/base.py`, `core/safe_http.py`, `connect/transport.py`,
`integrations/rem0te/client.py`, `oidc_sso/http.py`). Known current hits without a timeout:
`core/management/commands/create_github_releases.py:942,959` (maintainer command). Also flag GET views that reach these
wrappers (the AST scan used for this audit is a starting point). Add an interactive profile to the provider base
(`(5, 15)`, at most one retry) for test / console-link calls.
*Accept:* the test fails on a new unbounded call; "Test connection" against a black-holed host answers in ≤ 30 s.

**P0-5 Restore without peers.** Restore a backup that contains an active Connect connection and a Rem0te pairing into a
test database with no network.
*Accept:* sign-in, tickets, billing, documents, vault work; connections show Offline or "needs check" with the last
success time; the first scheduler pass does not send more than one check per connection.

**P0-6 Safe removal of an RMM connection.** Catch `ProtectedError` in `integrations/views.py:867`, list what references the
connection, offer Disable; open question for the owner whether alert-link rows should survive deletion (migration).
*Accept:* deleting a connection with ticket requests shows the reason and a Disable button; tickets, notes and audit
rows are unchanged in all cases (test J).

Planned, not P0: queue "Sync now" in the background (F11); `@require_POST` on the distributor / accounting test
views; processor choice per customer (F9); freshness on the client workspace RMM table.
