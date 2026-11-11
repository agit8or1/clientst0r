# RMM integration and technician UX program: audit

Audited 2026-11-11 on `dev/rmm-coordination` (based on `47c30b72`, unreleased). This is a plan, not a
release note: nothing listed as "missing" or "planned" here is implemented. The Rem0te contract details, the
revision-2 gaps (G1–G11) and the requests to Rem0te (R1–R10) are in `INTEGRATION_COORDINATION.md`. This
document refers to them by number.

Priorities:
- **P0**: blocks the integration or is a security fix.
- **P1**: the core of the program.
- **P2**: depth and polish.

Each phase's build list is in dependency order.

---

## Security findings (fix before feature work)

| # | Finding | Where | Priority |
|---|---|---|---|
| S1 | `rmm_device_delete` checks only `@login_required` and `if org and device.organization != org`. With no current organization (global view), any signed-in user can delete any RMM device. There is no staff, write or admin check. | `integrations/views.py:1030-1057` | P0 |
| S2 | The legacy AI routes `generate-reply/`, `generate-actions/` and `triage/` call Anthropic with the install's `ANTHROPIC_API_KEY`. They never consult `AIBusinessPolicy`: no `local_only`, no daily budget, no evidence redaction. A customer set to "local only" can still have ticket text sent to a cloud provider. | `psa_ai/urls.py:9-11`; `psa_ai/services/reply_generator.py:63-70`, `action_generator.py:154`, `triage_generator.py:200`; linked from `templates/psa/ticket_detail.html:1130-1205` | P0 |
| S3 | `/integrations/rmm/devices/`, `alerts/`, `software/` and `devices/<pk>/` have `@login_required` and organization scoping only. `/integrations/` is not in `STAFF_ONLY_PREFIXES`. `rmm_trigger_sync` has no admin check. Customer members may see their organization's RMM data. | `integrations/views.py:787-890, 1174`; `accounts/middleware.py:250` | P0 (confirm with a test first) |
| S4 | Rem0te alert tickets and security auto-tickets take the first active queue install-wide. Security auto-tickets fall back to the MSP organization when `client_org` is unset. | `integrations/rem0te/alerts.py:132`; `security_alerts/adapters/base.py:99, 113` | P1 |
| S5 | Once G4 is built, a stored capabilities document would hold every customer's Rem0te business name on each customer's connection. | G11 | P1 (with G4) |
| S6 | Technician-access assignments limit only AI/RMM capabilities. Ordinary ticket and asset access for MSP staff is install-wide. Phase 8 must not present per-organization roles as narrowing ordinary work until it does. | `psa/views.py:122`; `assets/views.py:131` | P1 (decision) |
| S7 | `assist_views.job_status` returns AI output without checking the AI master switch. | `psa_ai/assist_views.py:182` | P2 |

The S1 and S2 code was checked in this session. S3, S4, S6 and S7 come from a read-only sweep and need a
failing test before any fix.

---

## Phase 1: Real integration with Rem0te

**Exists:**
- Ed25519 pairing, signed requests and events, delegation, nonces, idempotent jobs, alert→ticket with link-back, and catalog proposals (`integrations/rem0te/`).
- Check pairing with specific failure reasons (`integrations/rem0te/pairing.py:232-345`), shown at `/integrations/rmm/<pk>/` with `templates/integrations/_rem0te_pairing.html` and `rmm/<pk>/pairing/check/`.
- Asset↔endpoint matching by persistent ids: `RMMDevice.external_id` holds Rem0te's endpoint id from the Public API (`integrations/providers/rmm/rem0te.py:118-143`). Association follows the rules in `integrations/rmm_association.py` (serial first, hostname only without conflict, never IP).

**Partial:**
- Status states are off / pending / checking / error / warning / ok (`pairing.py:449-503`). They are not Connected / Degraded / Disconnected / Authentication Problem / Configuration Required.
- Organization mapping is inferred from a 403 probe.
- Technician mapping is not checkable before use (R3).

**Missing:**
- Revision 2 (G1–G7).
- Overlapping key rotation (G9).
- A setup wizard.
- E2E against 0.30.x (G10).

**Build:**
1. **P0** Re-vendor the contract at `4b2b9f5`, bump `PIN.json` and port the test vectors to `examples/` (G1, G2, G8).
2. **P0** Read `contract_revision` (G3). Agree the newer-revision policy with Rem0te (R2).
3. **P0** Re-run `scripts/e2e/cross_peer/` against 0.30.1, and add scenarios for the paused business, the organizations list and the patch summary (G10). Ask Rem0te to re-run its interop against `integrations/rem0te` (R1).
4. **P1** Consume `organizations`: mapped/unmapped, business name, paused kinds. Store only the connection's own organization (G4, G5, G11).
5. **P1** Compare the Public-API business pin with `organizations[].business_id` (G7).
6. **P1** Map the existing `pairing.status()` and `check()` codes onto the five states:
   - Configuration Required = `NOT_CONFIGURED_LOCAL`, `NOT_CONFIGURED`, unmapped organization
   - Authentication Problem = `KEY_UNKNOWN`, `SIGNATURE_REJECTED`, `CLOCK_SKEW`, `PEER_MISMATCH`, `SIGNING_KEY_MISMATCH`
   - Disconnected = `UNREACHABLE`, `BLOCKED`
   - Degraded = ok plus warnings, a paused kind, or a failed check after a good one
   - Connected = otherwise
   Put this in `pairing.py`, not in a new module.
7. **P1** Turn the connection page's existing `steps` list (`pairing.py:491-502`) into a stepwise setup wizard. Test Connection is the existing Check pairing. Each step shows its own failure text.
8. **P1** Overlapping key rotation (G9).
9. **P2** Use push for proposal status (R7) and an endpoint health channel (R5) once Rem0te decides.

---

## Phase 2: Technician workspace and navigation

**Exists:**
- Primary nav in `templates/base.html:77-190`: 8 top-level menus, about 36 dropdown entries, about 9 utility controls. Phase 58 condensed nav, shipped v3.17.647.
- Section tabs in `core/navigation.py` (36 sections).
- Settings sidebar groups in `core/settings_groups.py`.
- Per-user shortcut strip with 3 pins (`core/shortcut_strip.py`).
- **My Work** at `/psa/my-work/` (`psa/views.py:9715`, `psa/my_work.py`, `templates/psa/my_work.html`). It shows:
  - timers
  - my open tickets, soonest SLA first, overdue in red
  - customer replied
  - waiting on us / waiting on customer
  - appointments
  - pending approvals
- Phase 52 is in progress (`docs/ROADMAP.md:1717`).

**Partial:**
- Nav permissions are template conditionals only; each view keeps its own checks (`core/navigation.py:17-19`).

**Missing:**
- The requested top level (My Work / Tickets / Clients / Devices / Alerts / Tools / Reports).
- Nav search and collapse.
- Admin nav configuration in Settings.
- These My Work sections:
  - an SLA near-breach queue
  - unacknowledged alerts
  - unhealthy devices
  - scheduled maintenance
  - recent devices
  - active remote sessions
  - jobs needing review
  - AI suggestions

**Build:**
1. **P1** Restructure `base.html`'s primary nav into the seven groups, keeping today's gating flags.
   - Devices = assets + RMM devices.
   - Alerts = Rem0te/RMM/security alerts.
   - Tools = Ops/Modules.
   - Extend `core/navigation.py` rather than adding a second registry.
2. **P1** Extend `psa/my_work.py` with these sections, each using an existing source and one primary action:
   - SLA near-breach, from `psa/sla.py`
   - unlinked/open Rem0te alerts, from `Rem0teAlertTicket`
   - offline/stale devices for assigned customers, from `rmm_association.device_status`
   - open `AnalysisJob` and `RMMRequest` needing review
3. **P2** Admin nav order and visibility in Settings (`core/settings_groups.py`), plus nav search and collapse.
4. **P2** Remote sessions and maintenance on My Work, after R6 and Phase 6's maintenance model.

---

## Phase 3: Device workspace

**Exists:**
- `/assets/<pk>/` (`assets/views.py:118`). It has Details, Custom Fields, Ports, RMM (staff only) and Images tabs.
- The RMM tab (`templates/assets/asset_detail.html:475-585`, `templates/integrations/_rmm_device_summary.html`) shows:
  - Online / Offline / Stale / Unknown (`integrations/rmm_association.py:652-656`)
  - last check-in and a console link (`:681`)
  - OS, logged-in user, last patched and needs-reboot, read from `raw_data`
  - alerts and software

**Partial:**
- "Active Alerts" counts resolved alerts too (`asset_detail.html:538-542`).
- Patches and reboot exist only as raw JSON.

**Missing:**
- On the asset page: a tickets list, docs/runbook links, vault credential links, services, the Windows event log, remediation history, and the toolbar.
- The `/assets/<pk>/remediation/` route promised in `assets/models.py:895-907` does not exist.

**Build:**
1. **P1** Fix the alert count.
2. **P1** Add a toolbar, **CONNECT | DIAGNOSE | RUN APPROVED ACTION | PATCHES | CREATE TICKET | MORE**, that reuses `psa_ai/services/rmm_actions.py` (`action_state` :163, `panel` :189).
   - Disabled states take their reason from `tech_access.resolver.decide` and from `pairing.advertised()` / `proposable_actions()`. That logic already explains refusals; do not write a second permission path.
   - CREATE TICKET prefills `/psa/new/` with the asset.
3. **P1** Add tickets, docs and vault-link panels from existing relations. Vault through its existing reveal flow, never inline.
4. **P1** Patch panel from G6's stored `patch_summary`, marked fresh/stale as Rem0te reports it.
5. **P2** Services, events and remediation history, once Rem0te exposes them (R5). Until then, "not available from this RMM" is shown explicitly.

---

## Phase 4: Ticket-centric RMM side panel

**Exists:**
- The staff-only asset card and `_ticket_rmm_panel.html` (`templates/psa/ticket_detail.html:624-655`; `psa/views.py:978, 1001`). It offers send to RMM, view/control or request a session, read-only diagnostics, and fix referral or Rem0te proposal, with request history.
- Each action is checked with `tech_access.resolver.decide`.

**Partial:**
- One asset per ticket (`Ticket.related_asset` FK, `psa/models.py:237`).
- Remote launch is a redirect that is never recorded (`psa_ai/rmm_views.py:131-136`). It correctly claims nothing.

**Missing:**
- Recent device alerts on the ticket.
- Multiple devices.
- Confirmed session state (R6).
- Verify-and-close flow tied to RMM results.

**Build:**
1. **P1** Show the linked asset's alerts (`RMMAlert`, `Rem0teAlertTicket`) and the patch summary on the panel.
2. **P1** Multiple devices: add a ticket↔asset many-to-many next to `related_asset`. Keep the FK as "primary" so the existing code keeps working. Every target still goes through `rmm_actions.targets()` boundary checks.
3. **P1** Label remote launch "opened in Rem0te — not confirmed" until R6 exists.
4. **P2** A Verify step: re-read proposal status and alert state, then add a note or time entry with the existing ticket composer.

---

## Phase 5: AI Troubleshoot (OPTIONAL AI, gated by `psa_ai_enabled`)

**Exists:**
- Providers anthropic / openai / ollama (`psa_ai/models.py:195-199`), with sealed keys (`services/gateway_keys.py`).
- Per-customer `AIBusinessPolicy`: allowed profiles, `local_only`, compare, `daily_budget_cents` with atomic `AIBudgetDay` (`models.py:270-282`, `services/budget.py:30`).
- Default-profile selection (`services/profiles.py:101`) and compare with at least 2 profiles (`:146`).
- Redaction (`services/evidence.py:48`). Vault data is locked out of evidence.
- Gate `core/ai_gate.py:28`.
- Rem0te's `analysis-result` already separates `facts` / `hypotheses` / `unsupported_claims`, and every `next_steps[].executable` is `false`.

**Partial:**
- No explicit primary/secondary or failover.
- No routing by task.
- No information-sharing rules beyond redaction plus `local_only`.

**Missing:**
- A troubleshoot flow that keeps observation / inference / approved action / verified result as separate, labelled records.

**Build:**
1. **P0** Route the legacy generators through the gateway and policy, or retire them (S2).
2. **P1** Add a secondary/failover profile to `AIBusinessPolicy`, with a per-task cost cap. Extend `profiles.py`, don't fork it.
3. **P1** A Troubleshoot view over `AnalysisJob` results, with four labelled sections:
   - Observation: Rem0te-observed evidence
   - Inference: hypotheses
   - Proposed action: a catalog proposal, which still needs Rem0te approval
   - Verified result: the proposal outcome as Rem0te reports it
   Nothing executes from this view. A proposal is the only path, and it goes to Rem0te's approval signer.
4. **P2** Additional providers, and per-customer information-sharing rules (which evidence kinds may leave).

---

## Phase 6: Alert → ticket

**Exists:**
- Rem0te alerts: one ticket per (connection, alert id), signed and sequenced, deduplicated on `Rem0teAlertEvent`. Resolved and updated alerts deliberately never touch the ticket (`integrations/rem0te/alerts.py:11-21, 92-116`).
- Security alerts: rule-based auto-tickets with suppression and incident correlation (`security_alerts/adapters/base.py:40-113`).
- Assignment routing (`psa/routing/`): business hours, on-call, round robin, SLA reroute, idempotent decisions.
- SLA (`psa/sla.py`, wall-clock only).
- Escalation via workflow rules.

**Partial:**
- `outage_alert_id` (site outage grouping) is received but ignored.
- Queue selection is install-wide (S4).
- Security suppression uses UTC hours (`base.py:89`).

**Missing:**
- Alert intake policies per client/site/category/severity.
- Correlation by device and issue across alerts.
- Maintenance suppression (`statuspage.MaintenanceWindow` is display only).
- Recovery updates on the ticket.
- Business-hours SLA.
- Storm protection.

**Build:**
1. **P0** G2, or no Rem0te alert reaches ClientSt0r at all.
2. **P1** An alert-intake policy model per customer/site/kind/severity: open a ticket / record only / suppress.
   - Route the opened ticket through `psa/routing` instead of `Queue.objects.first()`.
3. **P1** Correlation:
   - Child alerts with an `outage_alert_id` attach to the outage's ticket.
   - A second alert for the same device and kind while a ticket is open adds a note instead of a ticket.
   - Use the existing `Rem0teAlertTicket` rows as the key.
4. **P1** Recovery: on `alert.resolved`, add a staff note to the alert's own ticket and mark the alert resolved. Never close unrelated tickets. Closing stays a person's decision unless a policy says to auto-resolve that alert's ticket.
5. **P1** Storm guard: a per-customer cap on tickets per window, overflow into a single summary ticket.
6. **P2** Maintenance windows that suppress intake. Extend `statuspage.MaintenanceWindow`, or add a scoped model it references.
7. **P2** Business-hours SLA in `psa/sla.py`, reusing `psa/routing/engine.py:91 in_business_hours`.

---

## Phase 7: One-click workflows

**Exists:**
- Rem0te catalog proposals: only `windows.service.start@1` (Print Spooler) (`integrations/rem0te/pairing.py:48-51`).
- Read-only diagnostics for HMAC providers (`psa_ai/rmm_views.py`).
- Security `RemediationPlaybook` (`security_alerts/models.py:640-720`).
- Process runbooks (`/processes/`).

**Missing:**
- The twelve workflows (offline, disk full, service stopped, …).
- `docs/runbook_models.py` is orphaned: no imports, no migrations.

**Build:**
1. **P1** A workflow definition keyed by alert kind (Rem0te kinds: `OFFLINE`, `DISK_FREE`, `CPU_HIGH`, `MEMORY_HIGH`, `SERVICE_STOPPED`, `EVENT_MATCH`, `REBOOT_PENDING`, `SITE_OUTAGE`). Each workflow:
   - gathers evidence from an analysis job with endpoint evidence
   - shows impact
   - offers only catalog actions Rem0te advertises
   - tracks the proposal through approval and outcome
   - writes notes and status to the ticket
   Build it on `AnalysisJob` + `RMMRequest`. Delete or revive `docs/runbook_models.py`; don't keep both.
2. **P1** Ship the workflows whose evidence and action exist today first: service stopped (the Spooler action), and pending reboot (evidence only, from the patch summary).
3. **P2** The rest, as Rem0te adds catalog actions (R8). Kinds Rem0te does not monitor (backup failure, endpoint security alert, application failure) start as evidence-gathering checklists without an action.

---

## Phase 8: Roles L1 / L2 / L3 / platform admin

**Exists:**
- `tech_access`: presets L1 Help Desk / L2 Technician / L3 Senior (`tech_access/catalog.py:127-146`).
- Per-customer assignments with expiry, customer policies, explicit denies, and protected changes with second-admin approval. Superuser Approval (`/settings/security/technician-access/superusers/`).
- Effective permissions and the "why" view (`tech_access/resolver.py:141, 189`; `/settings/security/technician-access/why/`).
- All server-side.

**Partial:**
- Covers AI/RMM capabilities only (S6).
- Some catalog capabilities are never checked by any view: `export`, `diagnostics_advanced`, `elevation`, `unattended_access`, `clipboard`, `file_transfer`.

**Missing:**
- A "platform admin" preset distinct from superuser.
- Approval requirements shown next to each action.

**Build:**
1. **P1** Show approval requirements on each RMM action: Rem0te's `approvals_required` and `customer_signoff` from the proposal, plus ClientSt0r's own capability decision. Reuse `explain.py`.
2. **P1** Either wire the unchecked capabilities into the views they describe, or mark them "not enforced yet" in the catalog UI. Do not show a toggle that does nothing.
3. **P2** Decide whether assignments should also narrow ordinary ticket and asset access (S6). That is a large change; plan it separately.

---

## Phase 9: UX

**Exists:**
- Global search `/core/search/` (assets, contacts, passwords, documents, PSA companies/contacts; `core/search_views.py:23`).
- Ticket-page shortcuts (`static/js/psa_ticket_workspace.js:347`).
- Favorites, recent clients, client switcher with keyboard navigation.
- Client context persistence with a cross-tab guard (`core/middleware.py:30-84`).
- Breadcrumbs (widely used) and confirmation dialogs.
- My Work empty states.

**Missing:**
- Tickets and RMM devices in global search.
- A global search hotkey.
- Saved views on ticket and asset lists (saved queries exist only in reports).
- Recently viewed devices.
- Progress indicators for long RMM actions.

**Build:**
1. **P1** Add tickets and RMM devices to `core/search_views.py`, with the same scoping tests (`core/tests/test_global_search_scoping.py`).
2. **P1** A global `/` search hotkey and recent devices. Store them per user like recent clients (`core/models.py:2522`).
3. **P1** Ticket → linked device in one click from the ticket header, using the existing asset card link.
4. **P2** Saved views for ticket and asset lists, generalised from `reports/models.py:420`.
5. **P2** A mobile pass on the ticket RMM panel and the device toolbar.

---

## Phase 10: Tests

**Existing tests to extend:**

| Area | Tests |
|---|---|
| Org mapping, duplicate hostnames | `integrations/tests_rmm_association.py` (AssociationTests, Rem0teAdapterTests); `psa_ai/tests_rem0te.py` `test_same_computer_name_in_two_customers_never_mixes`; `psa_ai/tests_assist.py:201` |
| Replay, signatures | `integrations/tests_rem0te.py` InboundAuthTests, FixtureVectorTests |
| Denied access | `psa/tests/test_customer_boundary.py`, `psa_ai/tests_rmm.py` TargetBoundaryTests, `accounts/tests_view_permissions.py` |
| AI boundaries | `psa_ai/tests.py`, `psa_ai/tests_assist.py`, `tech_access/tests.py`, `tech_access/tests_why.py` |
| Ticket dedup | `psa_ai/tests_rem0te.py` AlertTicketTests; `security_alerts/tests.py:273`; `psa/routing/tests.py:308` |

**Missing tests:**
- **P0** S1, S2, S3: customer and global-view users refused on the RMM device, alert, software, delete and sync routes. Legacy AI generation honours `local_only` and the budget.
- **P0** Revision-2 vectors from `examples/`: capabilities with organizations, an alert with `patch_summary` (null and non-null), 423 CONTAINED, the replayed submit.
- **P1** Paused business (each kind), unmapped technician, capability differences (no alerts, no actions), stale or offline device on the panel, failed and expired proposals, outage child alerts on one ticket, storm cap, recovery note.
- **P1** Cross-peer E2E re-run against 0.30.1 (G10), plus scenarios for the items above.
- **P2** Browser and responsive checks of the ticket panel and device toolbar.

---

## P0 list (in order)

1. S1: authorization on `rmm_device_delete`. While there, test S3's routes and fix what the tests show.
2. S2: legacy AI generators through the gateway and the customer AI policy, or retire them.
3. G1 + G2 + G8: re-vendor Rem0te's contract at `4b2b9f5`, bump the pin, port the test vectors. Without this, Check pairing fails and every alert is refused against rem0te 0.30.x.
4. G3: read `contract_revision`, with the policy agreed with Rem0te (R2).
5. Re-run the cross-peer E2E against 0.30.1 (G10). Ask Rem0te to re-measure the Ed25519 implementation (R1).
