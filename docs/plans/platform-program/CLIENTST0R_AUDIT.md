# Clientst0r audit for the platform program (2026-11-20)

Two static read-only audits of Clientst0r main at v3.17.732/733 (nothing run). Part 1 covers program areas A, E, G and L; part 2 covers F, H, I, J, K and M. Billing, quoting and CRM are in [../msp-billing-program/CAPABILITY_AUDIT.md](../msp-billing-program/CAPABILITY_AUDIT.md). Note: the audit-log hash chain mentioned as uncommitted in part 1 is in release testing at the time of writing.

---

## Clientst0r audit 1 — §A, §E, §G, §L of the platform program

Read-only static audit of `main` at v3.17.732 (`74f2b1c7`, `/home/administrator`). v3.17.733 is roadmap-only. Nothing was run:
no tests, server, migration or state-changing git. "Complete" means code plus a test file that covers it was found. It does
**not** mean the tests were run. Claims marked *(unverified)* are inferred from the code and were not traced end to end. This
audit builds on GAP_ANALYSIS.md (GA x.yy) and SECURITY_REVIEW.md (SR-nn) and records only what changed or was not covered
there.

Status key: **C** Complete · **P** Partial · **PI** Existing but poorly integrated · **M** Missing · **D** Duplicated · **S** Superseded

---

## §A — PSA/RMM integration with Rem0te (P0)

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| Immutable customer and device IDs | C | `org-<pk>`/`tech-<pk>` `integrations/rem0te/pairing.py:86-91`; device match by `external_id` `integrations/providers/rmm/rem0te.py:118-147`; tests `integrations/tests_rem0te*.py`, `tests_rmm_association.py` | 63.1, 56.7 | Re-map after revoke (SR-30, Rem0te side) |
| Ticket ↔ endpoint links | C | `TicketAffectedAsset` `psa/models.py:7497`; panel `templates/psa/_ticket_rmm_panel.html`; alert→ticket `integrations/rem0te/alerts.py:381,429` | 63.4, 52 | — |
| Health, alerts, inventory, patch, connectivity in the ticket | P | Panel alerts L60-64; `_rmm_device_summary.html` (`ticket_detail.html:640`); patch summary comes only from alert payloads `alerts.py:288-320`; Rem0te online and last-seen through the Public API only | 63.3/63.4; P10 device summary rev-3 | Device summary P10 (Rem0te-blocked); patch status not a device fact for Rem0te; the 6 alert kinds Rem0te does not send are listed, not consumed (v3.17.721) |
| Remote session launch | P | `psa_ai/services/rmm_actions.py:528` live-authorized launch for HMAC RMMs only; Rem0te gets a static console deep link `providers/rmm/rem0te.py:207-218` | 57.6 (partial), 56.5 | P6 launch and R6 session events (Rem0te); time-limited grants |
| Read-only diagnostic requests | M (for Rem0te) | `integrations/ticket_rmm.py:165-169` returns `[]` for every Ed25519 (Rem0te) connection | 56.5, 86.3 (rev-3 P1–P3) | Rem0te P1–P3; ClientSt0r capability-flagged branch |
| Remediation proposals with status and results | P | `integrations/rem0te/actions.py:83-195`, `STATUS_MAP` L33-45; only `windows.service.start@1` `pairing.py:67-70`; 30 s poll L30; cross-peer s12 `scripts/e2e/cross_peer/remediation_chain.py` (pinned to Rem0te 0.68.0 since v3.17.721) | 56.8, 56.6, 63.7 | Catalog limited to one action; no push status (R7); parameter schemas (R8) |
| Results written to the ticket, then verify and close | P | The result note is written only when a technician POSTs `/psa/rmm/<t>/note/` (`psa_ai/rmm_views.py:206`; E2E L384). Verification comes from `alert.resolved` and the workflow run (s12) | 63.4, 63.7 | Automatic staff-only result note on terminal status; P5 verification evidence |
| Ticket synchronization | P | Alert→ticket link-back only `alerts.py:438,533-540`. No ticket status, notes or closure go to Rem0te | gap (P7 handoff in rev-3; 79.7) | Ticket-state events to Rem0te; P7 handoff note |
| Failure reporting and actionable errors | C | `integrations/rem0te/health.py` (states L75, `note(..., action=)`); refusal text `actions.py:50-80,171-176` incl. `DIRECT_MODE_PORTAL_ONLY` (v3.17.721) | 63.1, 56.8 | — |
| Technician permission enforcement | C | `rmm_permissions/decision.py:147-176`; per-action re-check `ACTOR_REVOKED` (E2E s7); tests `rmm_permissions/tests*.py` | 63.8, 57.2 | — |
| Cross-application audit references | P | `RMMRequest.remote_id`/idempotency key `actions.py:126-135`; `ticket_ext_id` sent to Rem0te (E2E L207) | 63.10 | No single cross-app correlation ID view; audit rows not linked to the Rem0te job ID *(unverified)* |
| Contract pin / interop record current | P | `contract/PIN.json` = 0.68.0 `5a43f02`; but `contract/clientst0r-interop.json` still says Rem0te 0.30.1 / CS 3.17.660 (SR-33 open); `INTEGRATION_COORDINATION.md:10` says 3.17.723 | 63.10 | Re-vendor the interop file; non-blocking leg against Rem0te `main` |
| Double-ticket guard (Rem0te automatic PSA tickets) | P | Conflicting-link detection only `alerts.py:540` (SR-27) | gap | Refuse or merge the second ticket path |
| mTLS client cert to Rem0te | M | `integrations/rem0te/client.py:76-` has no cert option (SR-23). 81.8 is inbound only | gap | Client cert config and rotation |

**Reuse:** `integrations/rem0te/{protocol,client,schema,health,actions,alerts,jobs}.py`, `ticket_rmm.py`, `rmm_permissions`, `psa_ai/services/rmm_actions.py`, ticket RMM panel, cross-peer harness (s1–s13), `AlertMaintenanceWindow`/alert policy (`psa/routing/alert_policy.py`).

**Security considerations:** approval stays in Rem0te only (verified: no approve route, E2E L295-297). Unknown alert kinds and fields fail closed. SR-21 means a peer declaring rev > 2 has unknown fields accepted. Business pin is TOFU (SR-22). Result and explanation text is untrusted (`client.safe_text`). P16 has no idempotency (SR-32).

**Proposed acceptance criteria**
1. Cross-peer run at the current Rem0te release passes s1–s13. A CI check fails when `clientst0r-interop.json` and `PIN.json` disagree.
2. When a proposal reaches a terminal status, the ticket gets one staff-only result note without a technician click, idempotent per `RMMRequest`.
3. A test shows no ClientSt0r URL, worker or AI path can change an `RMMRequest` to `approved`.
4. Diagnostics for Rem0te stay hidden until Rem0te advertises the rev-3 capability. A fixture test shows them appear behind the flag.
5. Closing a ticket that has an open Rem0te proposal warns the technician and records the proposal ID in the closure audit row.

---

## §E — Ticketing, technician workspace, workflow automation, SLAs (P1)

### Ticket page as work area

| Capability | Status | Evidence | Roadmap | Missing |
|---|---|---|---|---|
| Customer, contact, contract, SLA, assignee, assets on ticket | C | `templates/psa/ticket_detail.html` contract banner ~L414-431, SLA chip `psa/sla.py:201`; tests `psa/tests/test_ticket_workspace.py` | 52, 63.4 | Contract-coverage label per time entry (GA 2.03) |
| RMM health and alerts | C | `ticket_detail.html:640-645` | 63.4 | See §A |
| Relevant knowledge | P | `ticket_kb_link` and `ticket_kb_draft` (psa/urls.py); runbook/KB matching only inside OPTIONAL AI 63.5 | 22, 52, 63.5 | Non-AI KB suggestions by category or asset type |
| Permission-controlled credentials | C | Vault Context card `ticket_detail.html:808-815` (no secrets inline); `psa/tests/test_ticket_vault_sidebar.py` | 52 | — |
| Tasks, time, timers, billable items | C | `ticket_checklist_add`, `timer_start/stop`, `time_entry_manual`, `ticket_expense_add`, kit (`TicketKitItem` `psa/models.py:6702`) | 46, 52 | Billing classification is Phase 101 |
| Action history | P | Staff-only AI and automation history (56.9); conversation (`psa/conversation.py`) | 56.9 | Workflow actions are not in the history (no execution log; see below) |
| Drag-and-drop attachments | M | No drop handler in `templates/psa/*ticket*`; only `dispatch_board.html` has one | gap | Drop zone on composer, reusing `psa/attachment_rules.py` |
| Quick assignment | C | `ticket_quick_action` assign_me/set_assignee `psa/views.py:1975-2010` | 52 | — |
| One-click internal note / public reply, canned replies | C | Composer (52); canned picker `ticket_detail.html:264-269` | 52 | — |
| Suggested troubleshooting | P | Support workflows (63.7) and OPTIONAL AI Troubleshoot (63.5) | 63.5, 63.7 | Non-AI suggestion by alert kind or asset type (GA 2.04) |
| Escalation (manual) | P | Set queue or priority only; no escalate action or level model | 87.2 | Escalation levels |
| Merging | C | `ticket_merge` (psa/urls.py); tests in `test_phase1_2_core.py` *(unverified scope)* | 52 | — |
| Related-ticket detection | P | `psa/sla.py:257 find_similar_tickets` (token/asset), problems | 6.2 | Explicit link types (GA 2.04) |
| Approval requests from the ticket | P | `PSAApproval` kinds time/expense/quote/order/action/change `psa/models.py:2059-2067` | 20, 6.1 | Generic "request approval" on a ticket; delegation |
| Reminders | M | No reminder model or action in `psa/` | gap | Per-ticket reminder plus scheduler hook |
| Customer follow-up | P | "Next" label with a 3-day hint `ticket_detail.html:78`; CSAT `psa/csat.py` | 12, 52 | Auto follow-up, confirm-or-auto-close (GA 4.13) |
| Handoff summaries (shift / technician) | M | "handoff" in `psa/views.py:1264` is the RMM handoff, not a technician handoff | gap | Non-AI handoff summary; AI variant behind `psa_ai_enabled` |

### Automation

| Capability | Status | Evidence | Roadmap | Missing |
|---|---|---|---|---|
| Visual rule builder (no JSON for ordinary rules) | C | `psa/workflow_graph.py`, `workflow_rule_form` `psa/views.py:4737`; `test_workflow_builder.py` | 14 | — |
| Conditions, triggers, actions | P | 5 triggers only `psa/models.py:4134-4140` (no schedule, no time-since-last-reply trigger) | 14 | Time-based triggers ("no reply in N h") — 14 bullet "Escalation logic" has no ship marker |
| Delays | M | No delay or wait action in `psa/workflow_engine.py` | gap | Delayed actions on the scheduler |
| Escalations | P | `sla_threshold_crossed` + `fire_once_per_ticket` | 14, 87.2 | Level/time-offset model |
| Dry run | M | None for rules (routing has a Test page; playbooks have `dry_run=` `security_alerts/models.py:751`) | 91.3 | — |
| Execution history | M | Only `last_fired_at`/`fire_count`/`last_error` `psa/models.py:4170-4172` | 91.2 | Per-firing log |
| Loop prevention | C | Skip rule already in chain `psa/workflow_engine.py:441-444`, depth 8 (L27), 50 actions per event (L31,190-197); `psa/tests/test_workflow_reentrancy.py` (v3.17.732) | 91.1 (marked planned) | — |
| Rate limits | P | Per-event 50-action cap only; nothing across events | 91.1 | Per-rule/per-ticket limits over time; storm cut-off |
| Retries | M | Errors are written to `last_error` and dropped (L483-486) | gap | Retry policy for transient failures (mail, PSA push) |
| Per-customer overrides | P | A rule can be scoped to one org (`WorkflowRule.organization`). No "override MSP rule for customer X" | gap | Override/disable per customer |
| Approval for sensitive actions | P | Charge once per rule and ticket (`WorkflowCharge` `psa/models.py:4389`, v3.17.732); assign/watch customer checks (v3.17.727, `test_workflow_assignment_scope.py`) | 91.4 (marked planned) | Approval gate or cap on charge amount; rule edit uses `require_admin`, not a registry permission (64.8) |

### SLAs

| Capability | Status | Evidence | Roadmap | Missing |
|---|---|---|---|---|
| Priority targets, per-contract matrix | C | `psa/sla.py:34-72` (`contract.sla_matrix` JSON); `test_sla_calculation.py` | 15, 2c | Structured editor instead of JSON *(unverified)* |
| Customer business hours, holidays | M (SLA) / P (routing) | SLA clock is 24×7 `psa/sla.py:5-7`; routing has MSP-wide hours only `psa/routing/engine.py:91-102` + `resourcing.Holiday` `resourcing/models.py:143` | 93.1/93.2 | Per-customer calendar |
| Several coverage schedules | M | One MSP schedule in `RoutingSettings` | gap (93 has one calendar per customer/contract) | Several coverage tiers per contract (e.g. 8×5 and 24×7 P1) |
| After-hours escalation, on-call | P | On-call from two sources `psa/routing/engine.py:308-322` (`OnCallShift` + resourcing shifts); alert policy uses `OnCallShift` `alert_policy.py:415` | 87.2 | Acknowledgement deadlines, escalation chain |
| Breach prediction | P | `sla_pct_at_least` condition; My Work sorted by SLA | gap | At-risk forecast (queue load × remaining working time) |
| Correct pause and resume | C | `psa/sla.py:85-125` (v3.17.563) | 2c/51 | Pause in working time once calendars land (93.2) |

**Reuse:** `workflow_engine` + `workflow_graph`, `psa/routing` (engine, Test page, Suggest mode, `max_reroutes`), `resourcing` holidays and shifts, `PSAApproval`, `support_workflows`, `psa/my_work.py`, `attachment_rules.py`.

**Security considerations:** rule list is visible to every staff account, including technicians restricted to some customers (`psa/views.py:4600-4606`). Rules can name customers they cannot see *(unverified impact)*. An execution log must not copy ticket bodies or secrets. Dry run must suppress mail, charges and PSA pushes. Legacy assign actions now share routing checks (v3.17.727).

**Proposed acceptance criteria**
1. Each rule firing writes one execution row (trigger, rule version, action results, duration). A test asserts no ticket body text is stored.
2. A dry run against a ticket returns the would-run actions. A test asserts zero new Ticket/Charge/EmailOutboundJob/TicketComment rows.
3. A per-rule limit over N firings per hour stops the rule and shows the cut-off on the rule page.
4. With a Mon–Fri 09–17 calendar and a holiday, a P2 ticket opened Friday 16:00 gets a due date computed in working time. DST and holiday cases are tested.
5. A file dropped on the ticket composer uploads through `attachment_rules` and rejects a mismatched type.
6. A restricted technician sees only rules for customers in their scope.

---

## §G — Security operations and event management (P1/P2)

| Capability | Status | Evidence | Roadmap | Missing |
|---|---|---|---|---|
| Events from RMM, Rem0te, backup, security, website/WAN monitors | P | `events/sources.py`, `events/projection.py` (82.1); producer hook `integrations/rem0te/alerts.py:258` | 82.1 | Microsoft 365, firewall/syslog, customer integrations (84.2, Phase H) |
| Normalization and severity | P | Envelope `events/models.py:40`; vendor severity mapped (v3.17.724) | 82.1 | — |
| Deduplication | P | Per-source key in events; security auto-ticket joins an open ticket within 24 h, 20 tickets/h cap `security_alerts/adapters/base.py:164-165` (v3.17.727) | 82, 87.3 | Cross-source dedup (GA 6.04) |
| Correlation | PI | Fixed 60-min grouping `security_alerts/models.py:858`; not on the event layer | 85.3 | Configurable rules on `OperationalEvent` |
| Customer and asset association | P | Customer comes from the connection. Asset is `asset_hint` free text on alert and incident (`models.py:440`) | 82.1, 85.4 | IP/hostname → Asset/RMMDevice resolution |
| Evidence, history | P | `SecurityIncidentEvent` timeline `models.py:490`; raw payload capped in events | 85.2/85.4 | Evidence attachments |
| Ticket and incident links | PI | `EventLink` `events/models.py:94` (82.2), but the five per-source links remain the working paths | 82.2 | Make `EventLink` the only write path |
| Event layer consumers | M | Nothing outside `events/` reads `OperationalEvent` (grep: only the `enqueue` producer) | 82→83/85 | Operations Center, wallboard sources, notifications |
| Suppression, maintenance windows | D | `AlertMaintenanceWindow` `psa/routing/models.py:488` (RMM/Rem0te); `statuspage.MaintenanceWindow` `statuspage/models.py:262`; UTC-hour window on security rules | 87.3 | One window model for all sources |
| Vendor integrations | M (labelled honestly) | Webhook-only labels (v3.17.723) `security_alerts/capabilities.py`; Defender stub `adapters/defender.py` | 84.3 (partial), 84.4–84.7, **74.4 duplicates 84.5** | Real adapters, tested against a vendor sandbox |
| SOC views, triage | P | Security Overview `security_alerts/overview.py`; statuses only new/ack/dismissed/resolved `models.py:155-160` | 85.1, 85.2 | Investigating/Contained/False Positive/Suppressed; analyst queue |
| Posture | P | `security_alerts/exposure.py`, `health_score` app | 89.1 | Scorecard with source and age per item |
| Wallboards | P | `reports/widget_sources.py` REGISTRY (no NOC/SOC sources, GA 6.12) | 83 | Presets, TV mode, display pairing |
| Routing, escalation | P | `SecurityIncidentSLAPolicy` `models.py:533`; alert policy on-call | 87 | Unified routing per severity |
| Customer summaries | C | Security digest `security_alerts/digest.py`, `tests_digest.py`; throttled unsubscribe (v3.17.725) | 89.2 (reviews) | Monthly review report |
| Approval-driven playbooks | **PI / misleading** | `RemediationPlaybook` runs automatically when an incident opens, with no approval (`models.py:899-901`). The `run_workflow_rule` step returns "ok … flagged for execution" but runs nothing, and looks up the rule by pk with no org check (`models.py:~844-853`) | 23 (shipped), 86.1/86.2 | Approval gates, real or removed step, org check, off by default |
| Endpoint execution stays in Rem0te | C (invariant) | No execution path in ClientSt0r; proposals only (§A) | 86.3 | — |

**Reuse:** `events` (envelope, queue, retention, health, permissions 82.6), `security_alerts` ingest and SIEM receivers (81.5 signatures), incident timeline, `psa/routing/alert_policy.py`, `reports` wallboards, `health_score`, `support_workflows` approval model.

**Security considerations:** legacy token-only webhooks are still accepted, now listed on Security Overview (SR-08, partly addressed). Playbook auto-execution sends email (`fail_silently=True`) on incident creation, so a forged alert can trigger mail. Correlation and suppression must never cross customers. Analyst roles exclude secrets (v3.17.720).

**Proposed acceptance criteria**
1. An Operations Center (or wallboard) source reads `OperationalEvent` and is customer-scoped by `scoped_events`. A test covers a restricted analyst.
2. One maintenance window suppresses RMM, Rem0te, security and website-monitor tickets for the same asset (test per source).
3. No playbook step runs before an approval when the incident came from an automated source. The `run_workflow_rule` step either executes within the incident's org or is removed. Tests cover both.
4. Each vendor listed as "API" passes a recorded-fixture contract test and one sandbox run. Otherwise it stays "webhook only".
5. A Rem0te alert and a security alert for the same device within the window produce one ticket.

---

## §L — Security across Clientst0r (P0/P1)

| Capability | Status | Evidence | Roadmap | Missing |
|---|---|---|---|---|
| MFA (TOTP, backup tokens) | C | `django-two-factor-auth` (requirements.txt), `accounts/otp_storage.py`, `tests_otp_storage.py`; default-password banner (v3.17.730) | 51 | — |
| Passkeys / WebAuthn sign-in | M | No WebAuthn library; only a comment in `accounts/session_epoch.py:315` | gap | WebAuthn as second factor and as step-up |
| OIDC SSO / Keycloak | P | `oidc_sso/` (80.3), "not verified against a live Keycloak" | 80.3–80.6 | Live verification; portal users (80.6) |
| Entra ID | C | `accounts/azure_auth.py`, identity-matched (v3.17.688), `tests_azure_sso.py` | 51 | — |
| Session controls | C | `accounts/session_epoch.py` (80.2), `tests_session_epoch.py` | 80.2 | — |
| Step-up authentication | C | `tech_access/protected.py:64-85` (57.4) | 57.4 | WebAuthn step-up |
| Emergency recovery accounts | P | Local superuser stays independent of LDAP `accounts/ldap_backend.py:14`; `api_access_recover` command (81.6) | gap | Documented break-glass account with alerting on use |
| Identity lifecycle / technician offboarding | P | Deactivation ends sessions, keys and tokens `session_epoch.py:205-247`; 51 "Access ends with the account" | 51, 80.2 | One offboarding action: revoke assignments, reassign tickets, rotate shared vault entries the technician revealed |
| Per-customer roles, L1/L2/L3, least privilege, customer scope | C | `accounts/permission_registry.py`, `role_seeds.py`, `scope.py`; `tests_roles_access.py`; `rmm_permissions` | 64.1–64.4, 63.8 | — |
| Approvals, temporary access, expiry | C | `tech_access/models.py:82-131` expiry; superuser approval (57.4); vault break-glass (37) | 37, 57 | — |
| Access reviews | M | Only the upgrade "review list" (64.6); `compliance` recertification covers controls, not user access | gap | Periodic access review with attestation |
| Same checks in UI, API, workers, exports, integrations | P | 64.8 partial (operations permissions defined, call sites pending); workflow rule edit uses `require_admin` (`psa/views.py:4737`) | 64.8 | Remaining call sites; worker-side checks *(unverified)* |
| Vault and secret encryption, rotation | C | 51 "Secrets encrypted at rest, key rotation" (v3.17.607); Rem0te Ed25519 rotation (63.1); API key rotation `api/models.py:92-126`, `api/key_lifecycle.py` | 51, 63.1, 81.4 | Separate keys per secret class *(unverified)*; key escrow (SR-17) |
| Secrets never sent to AI | C | 57.3 sealed provider keys, restricted worker; redaction 56.1 | 57.3 | Separate OS user is a deployment step |
| Audit tamper evidence, off-host export, independent verification | M (in progress off main) | `audit/models.py:9` plain table; `.wt-audit` on `dev/audit-chain` has no commits beyond main; admin purge without export `core/settings_views.py:964-972` | 94.1, 94.2 (SR-07) | Chain, verify command, shipping, export-before-prune |
| Permission, credential, integration, financial change tracking | P | Role audit `accounts/role_audit.py` (64.7); `TimeEntryAuditEvent` `psa/models.py:3738`; invoice approval refusals (v3.17.724) | 64.7, 94 | One financial change trail for invoices, charges and contracts *(unverified coverage)* |
| Signed messages, replay, idempotency (integrations) | C | Rem0te Ed25519 + nonces `integrations/rem0te/protocol.py`; webhook signatures and replay (81.5); Connect JWS/replay `agit8or_connect/{jws,replay}.py` | 63.1, 79, 81.5 | Legacy unsigned webhooks (SR-08) |
| Identity binding, tenant checks | P | Business pin TOFU (SR-22); `org-<pk>` binding | 63.1 | Out-of-band pin confirmation |
| Narrow scopes | P | API keys = org reach + 3 levels (SR-34); Connect 3 scopes (79.3 partial) | 79.3, gap for API keys | Per-resource scopes |
| Rotation, expiry, rate limits, validation | C | 81.4, 81.5, schema validation `integrations/rem0te/schema.py` | 81 | Concurrency limits deferred (81.4) |
| Dependency, static, secret scanning | C | `.github/workflows/security.yml` (pip-audit, Semgrep, Gitleaks), `codeql.yml`; Snyk alerts (51) | 51 | Container image scanning (none in `docker-image.yml`) |
| CSRF, XSS, headers | P | CSP (51); headers `config/settings.py:484-498`; dead `api/urls_graphql.py:15,21` with `csrf_exempt` still present (SR-20) | 51 | Delete the dead module |
| SSRF | C | `core/safe_http.py:140-164`; PBS (v3.17.728) and importer (v3.17.729) now guarded | 51 | — |
| Uploads | C | `files/upload_rules.py`, `psa/attachment_rules.py` (v3.17.724/725) | 51 | — |
| API authorization | C | `api/scoping.py`, `tests_authz_tech.py`; asset API scoped (v3.17.729) | 43, 81 | — |
| Container and worker permissions | P | `Dockerfile:83 USER clientst0r`; AI gateway user optional | 42, 57.3 | — |
| Backup encryption, restore access | P | `core/management/commands/backup.py:29-40` encrypts by default; no scheduled task; keys beside data (SR-17 open) | 94.3 | Scheduled off-host backups, restore rehearsal, restore permission |
| Update signing | C | SSH-signed tags (597), `core/updater.py:222` | 59 | — |

**Reuse:** `permission_registry`/`scope`/`delegation`, `tech_access` (resolver, protected, explain), `session_epoch`, `oidc_sso`, `core/safe_http`, `api_access` policy engine, upload rules, Connect SDK (`agit8or_connect`).

**Security considerations (open):** SR-07 (audit), SR-17 (backups and keys), SR-20, SR-22, SR-23, SR-27, SR-33, SR-34 are still open on main. SR-24/25/26 are addressed by v3.17.721. The Phase 23 playbook auto-run (§G) is a new finding.

**Proposed acceptance criteria**
1. `manage.py audit_verify` detects a modified, deleted or reordered row. Pruning refuses to run without a completed export.
2. A WebAuthn credential can be enrolled and used as second factor and for step-up. A test covers an admin with passkey only.
3. "Offboard technician" in one action revokes sessions, keys, assignments and tokens, lists the vault entries they revealed in the last 90 days, and is audited.
4. Every permission flagged "pending" in the registry has a call site and a refusal test (zero pending entries).
5. A scheduled encrypted backup runs from the scheduler to an off-host target. A restore test runs monthly, and a failure raises a system warning.
6. An API key with `tickets:read` only is refused on vault, invoice and asset write endpoints.

---

## Closing findings

### (1) Genuine gaps not covered by any roadmap phase
- Passkey/WebAuthn sign-in and step-up for ClientSt0r users (Phase 80 is OIDC only).
- Periodic access reviews and attestation. One-action technician offboarding.
- Workflow delays, retries and per-customer rule overrides. Time-based triggers ("no reply in N hours") are named in Phase 14 but never shipped.
- Several coverage schedules per contract (Phase 93 has one calendar per customer/contract) and SLA breach prediction.
- Ticket drag-and-drop attachments, ticket reminders, technician handoff summaries.
- Automatic Rem0te result note on terminal status. Ticket-state sync back to Rem0te (outside the P7 proposal).
- Container image scanning. Deletion of the dead GraphQL module (SR-20). Interop file re-vendor (SR-33). Outbound mTLS to Rem0te (SR-23). Double-ticket guard (SR-27). Per-resource API key scopes (SR-34). These are tracked in SECURITY_REVIEW but have no roadmap bullet.
- Phase 23 playbooks: an approval gate and a fix for the no-op `run_workflow_rule` step. Phase 86 plans a new builder but does not cover retiring or fixing the existing auto-run.

### (2) Roadmap statuses that look wrong
| Item | Current | Evidence | Suggested |
|---|---|---|---|
| Phase 91 header + 91.1, 91.4 | `[planned]` | Chain skip and 50-action cap `workflow_engine.py:31,441`; charge once `WorkflowCharge`; assign/watch checks (v3.17.727/732). These are tracked as Phase 51 bullets | `[in progress]`, 91.1/91.4 *(partial — shipped v3.17.727/732)* |
| Phase 14 header | `[shipped — v3.17.290]` | Bullets "Approval chains", "Trigger / action workflows", "Escalation logic (auto-escalate after N hours unanswered)", "Scheduled automations" have no ship marker. No time-based trigger exists (`psa/models.py:4134-4140`) | `[in progress]`, or move the open bullets to 91 |
| Phase 9 header | `[shipped — v3.17.168]` "EDR / AV / Firewall" | v3.17.723: no vendor has a working API integration; Defender stub | Note "webhook ingestion only", or partial |
| Phase 23 (playbooks "automated remediation") | shipped | `run_workflow_rule` step is a no-op that reports ok (`security_alerts/models.py:~844-853`); runs without approval (L899-901) | Annotate partial; fix or label |
| Phase 52 header | `[in progress]` | Every bullet is marked shipped | `[complete]`, or add the §E work items |
| 63.4 "read-only diagnostics" shipped | shipped | Not available for Rem0te `ticket_rmm.py:165-169` | Qualify "HMAC-contract RMMs only" |
| 63.10 / coordination | "record brought up to date" | `clientst0r-interop.json` still at 0.30.1 / 3.17.660 | Partial until re-vendored |

### (3) Duplicated or competing implementations
- **Four rule engines:** `psa/workflow_engine.py` (WorkflowRule), `psa/routing/engine.py` (routing rules), `psa/support_workflows` (WorkflowRun), `security_alerts` RemediationPlaybook. Each has its own conditions, history and loop handling. Phase 86.1 plans a fifth builder.
- **Maintenance windows ×3:** `psa/routing/models.py:488`, `statuspage/models.py:262`, UTC-hour window on security rules.
- **On-call ×2:** `psa/routing.OnCallShift` and resourcing on-call shifts. They are bridged in `engine.py:308-322`, but the alert policy reads only `OnCallShift` (`alert_policy.py:415`).
- **Alert→ticket paths ×5 + `EventLink`:** the per-source links are still the write path, and `EventLink` only copies them.
- **Two Rem0te channels:** `ticket-rmm-v1` (Ed25519, `integrations/rem0te/`) and Agit8or Connect (`connect/`, `agit8or_connect/`). Roadmap 79.7 plans device sync, alert tickets and remote actions over Connect, which duplicates 63/56. Rem0te data also arrives by two paths: Public API device sync (`providers/rmm/rem0te.py`) and contract events.
- **Duplicate roadmap items:** 74.4 duplicates 84.5 (Defender). 74.3 and 86.3 overlap rev-3 work under 56.5/63. 91.1/91.4 are tracked again as Phase 51 bullets. 94.1 duplicates SR-07, which is in progress.
- **Legacy workflow assign actions vs routing destinations:** checks are shared since v3.17.727, but there are still two assignment implementations (GA 4.06).

### (4) Major architectural concerns
- The event layer (Phase 82) has producers but no consumers. Until correlation, routing, wallboards and suppression read `OperationalEvent`, every §G feature risks being built per source again.
- Workflow re-entrancy protection is thread-local state (`_chain_state`, `workflow_engine.py:26`). It is correct for synchronous `post_save` chains. It does not protect against storms across events or workers. Per-rule rate limits need DB-backed counters.
- Security-critical flows depend on manual technician steps (Rem0te result note) or polling (30 s proposal poll, no R7 push). The "no copying between applications" goal in §A is not met yet.
- Two integration frameworks with Rem0te (ticket-rmm-v1 and Connect) carry separate keys, scopes and audit. Pick one canonical path for each capability before 79.7, or the platform ends up with two authorization models.
- The audit trail is mutable and can be purged from the UI without export. Every §L "audit" acceptance item depends on 94.1/94.2 landing first.
- The SLA engine is 24×7 while routing uses MSP business hours. Two time models will disagree on breach and after-hours until Phase 93 provides one calendar to both.

---

## Clientst0r audit 2 — sections F, H, I, J, K, M (code read at HEAD 7fb68e3f, v3.17.733)

Method: read-only. Code, tests and docs were read; nothing was run, so test claims mean "a test file with tests exists" (unverified that it passes). "(unverified)" marks inference.
Status vocabulary: Complete (code + tests) / Partial / Existing but poorly integrated / Missing / Duplicated / Superseded / Blocked (owner decision).
Billing, quoting and CRM are not repeated here; see `docs/plans/msp-billing-program/CAPABILITY_AUDIT.md` (portal billing rows N, report definitions M).
Paths are relative to the repo root.

---

## F. Documentation, inventory and network management

### What network discovery is today (facts)

| Piece | What it does | Evidence |
|---|---|---|
| Phase 32 one-shot script | Technician generates a PowerShell script with a 15-minute, single-use, SHA-256-hashed token bound to one org and one location. It pings, reads ARP, optionally probes ports 80/443/22/3389/445 to guess a type, and uploads. Upload is token-only, write-only, 20 uploads per hour per source IP, with an identical reply for every rejected token | `network_discovery/models.py:75`, `network_discovery/script.py:147-205`, `network_discovery/views.py:41,240-256` |
| Phase 33 site collector | `DiscoverySite` has a rotatable, revocable key, per-site subnets, an interval and a scan-now flag. The collector polls outbound only. The reference collector is stdlib Python: ICMP sweep plus the local ARP table | `network_discovery/models.py:309`, `deploy/network-collector/collector.py:126-149` |
| Import into assets | Match by MAC, then IP+location; fill blank fields only (manual names never overwritten); dry run supported; otherwise creates an Asset | `network_discovery/importer.py:98,140,183` |
| Topology and port map | `NetworkLink` and `SwitchPortEntry` store neighbours and bridge-table rows and draw a map. **Nothing in the repo produces those records**: the collector sends devices only. `collector_results` accepts `neighbours` and `switch_ports` keys from a payload | `network_discovery/models.py:491,559`; `network_discovery/views.py:552-553`; `docs/ROADMAP.md:764` |
| Network config backup | SSH only (7 platform adapters plus a generic one), host-key pinning, drift against an approved baseline, firmware history | `netconfig/adapters.py`, `netconfig/models.py:23,260`, `netconfig/hostkeys.py` |
| Controller sync | UniFi, Omada, Grandstream mirror devices as assets | `integrations/providers/{unifi,omada,grandstream}.py` |
| Legacy nmap CLI | `scripts/network_scanner.py` needs python-nmap; referenced nowhere else. Orphaned | `scripts/network_scanner.py:1-30` |
| SNMP | None. The roadmap says the stubs were removed in v3.17.594. `requirements*.txt` has no pysnmp | `docs/ROADMAP.md:744,764` |

### F capability table

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| Discovery without a ticket, scheduled runs for approved ranges | Partial | `DiscoverySite.subnets` and `scan_interval_minutes` (`network_discovery/models.py:338-352`); collector polls | Phase 33 (marked complete) | The server never checks that the collector's subnets fall inside an administrator-approved scope: the setting is the approval. Rate limiting is per source IP, not per site (sites behind one NAT share a bucket). Only the collector host runs the scan, so there is no server-initiated scan (by design) |
| ICMP discovery | Complete | `collector.py:90-149`, `script.py:198-200`; tests `network_discovery/tests.py` (58 tests), `tests_phase33.py` (54) | 32, 33 | none |
| ARP / MAC harvest | Complete | `collector.py:102`, `script.py:205`; `normalise_mac` in `models.py:50` | 32, 33 | none |
| TCP port probe / service detection | Partial | Phase 32 script probes 5 ports (`script.py:147`). `DiscoverySite.classify_enabled` exists, but `collector.py` has no probe code and never reads it (grep found nothing) | 32 ("optional lightweight enrichment") | The collector must honour `classify_enabled`; there is no banner or service identification; no per-port results are stored on assets |
| Printers, access points, firewalls identified | Partial | Type guessed from ports in the PowerShell script only; UniFi/Omada/Grandstream sync gives APs. No printer-specific path | none | Classification in the collector; vendor OUI lookup is only partly present (`vendor` field is accepted from the payload) |
| SNMP, LLDP/CDP, MAC/ARP tables from switches, switch-port association | **Blocked — needs owner decision** | The server-side tables and map exist (`NetworkLink`, `SwitchPortEntry`) but have no producer. The owner declined an SNMP collector | Phase 33 states "not in scope" | Not recommended. Owner decision needed on whether the topology and port-map pages stay (empty unless data is pushed by hand or via the API) or are hidden |
| Sync into assets, ports, patch panels, cables, VLANs, IPs, racks | Partial | Assets only (`importer.py`). Ports, cables, patch panels, VLANs and racks live in `monitoring/` and `hardware/` and nothing writes to them from discovery. `assets_auto_link` links by /24 and creates `related` and `depends` rows as ordinary relationships (see F-auto-link below) | 33 | IP address records (`monitoring.IPAddress`, `Subnet`) are not populated or reconciled by discovery; VLAN and port records have no discovered source |
| Keep manual, discovered and unverified facts apart | Partial | Fill-blank-only update; discovery metadata in `custom_fields` (`importer.py:217`). New devices become full Assets immediately. No "suggestion" or "unverified" state | 88.1 mentions "inferred links unverified" | A staging state (pending / confirmed / rejected) for discovered devices and inferred relationships; per-field provenance; stale handling for devices not seen. Note `assets_auto_link` writes inferred links with the same standing as human-entered ones |
| Never overwrite approved documentation | Complete for blank-fill rules | `importer.py:183-216`, tests `tests.py` | 32 | Verification that custom_fields stamps do not override manual values (unverified) |
| Network monitoring (interface utilization, errors, link, PoE, CPU, memory, temperature, firewall/printer/wireless status, bandwidth history, thresholds) | **Blocked — needs owner decision** for SNMP-based items | None exists. The only monitors are `WebsiteMonitor` / `MonitorCheck` (HTTP, SSL, WAN ping) in `monitoring/models.py:16,300` | none; COMPARISON.md:143 states it does not do SNMP monitoring | Not recommended. Non-SNMP options (controller APIs for wireless and AP status, vendor APIs) are a separate decision and would extend the controller sync |
| Ranked full-text search | Missing | Documents use `icontains` on title and body (`docs/views.py:1061`); global search is `icontains` per model (`core/search_views.py:84`) | none | Ranked search (database full-text index or relevance scoring), field weights, KB and document highlighting |
| Document attachments | Partial | Documents can *be* an uploaded file (`docs/models.py:149`); FEATURES.md:101 says there are no attachments on documents | none | Attachment model on documents and assets, with `files/upload_rules.py` validation |
| Secure sharing (links) | Missing for documents | FEATURES.md:101 "no share links". Portal and global KB audience controls exist; quote and signature tokens exist | none | Expiring, revocable share links with audit and optional password |
| Bulk asset editing | Missing | FEATURES.md:129; no bulk route in `assets/urls.py` | 55 mentions multi-select bulk edits for hardware (`docs/ROADMAP.md:2078`) | Multi-select edit for assets, with preview, permission check per object, audit |
| Per-asset change history | Missing | FEATURES.md:129. `AuditLog` is request level with no before/after for most changes (FEATURES.md:230). Only serial lifecycle history (`assets/urls.py:60`) | none | Field-level history on Asset (who, when, old, new), restore; shared with document versions where possible |
| Asset relationships and dependency maps | Complete (code) | `assets/models.py:779` `Relationship`, `Service` at `:816`; `assets/relationship_views.py:104` validates org and object type; `dependency_chain` BFS; topology.json | Phase 16 (shipped v3.17.303) | Duplicated by planned 88.1 (see Duplicated) |
| Documentation completeness scoring | Complete | `readiness/` app (standards, score, repair queue, exceptions) | Phase 53 shipped v3.17.656 | Asset-level completeness (e.g. every server has owner, backup, doc) is covered only through the standards (unverified) |
| Review reminders | Complete | Owners and review dates on documents, FEATURES.md:101; KB "past review" analytics | 22, 53 | none |
| Import and export | Complete (documents); Partial (assets) | `imports/` app (IT Glue, Hudu migration, CSV); document export MD/HTML/DOCX/PDF | 61 | Asset export to CSV is not audited here (unverified); full-tenant import still open (`GAP_ANALYSIS.md` 7.01) |
| Network topology views | Duplicated | `assets/relationship_views.py` topology.json, `network_discovery/topology.py:202` `topology_graph`, hardware connectivity diagrams | 16, 33, 55 | One graph model with provenance (see Duplicated) |

F-auto-link: `assets_auto_link` (roadmap line 385) creates inferred relationships and `depends` toward a "detected gateway". Inferred data lands in the same table as manual data, which contradicts the F requirement to keep them apart and the Phase 88.1 wording.

**Existing functionality to reuse**
- `network_discovery/importer.py` `apply_device` for every discovered-device path (one dedup rule).
- DiscoverySite key model (hash, rotation, revoke, audit) for any future collector.
- `Relationship`, `Service`, `dependency_chain` and `topology.json` for dependency mapping; do not build a second graph.
- `readiness/` standards engine for completeness scoring.
- `core.safe_http` for any outbound call; `files/upload_rules.py` for attachments; `netconfig/hostkeys.py` host-key approval pattern.

**Security considerations**
- Collector key travels in the JSON body of POST `/collector/results/` (CSRF-exempt, key-only). Keep it out of access logs and error reports; HTTPS only.
- `collector_results` rate limit is by source IP counted from import rows, so a shared NAT can starve legitimate sites (inferred).
- Discovery must never write outside the key's org and location (tested today); keep that for new record types.
- Config backups carry secrets (enable hashes, communities); `netconfig/views.py:68` already restricts them. Any search index must not include them.
- Share links and attachments are new data-exposure surfaces: need scoping to customer, expiry and audit.

**Proposed acceptance criteria**
1. A discovered device never changes a non-blank manual asset field, and appears as "unverified" until a technician confirms it (test with the same MAC pushed twice).
2. A collector whose configured subnet is outside the organization's approved ranges is refused at registration and at results time.
3. Search for a phrase returns documents ranked by relevance, scoped to the viewer's customers (cross-customer test), with the 90th-percentile query under an agreed bound on a fixture of 5,000 documents.
4. Editing an asset field records user, time, old and new value, visible on the asset page; a technician without access to the customer cannot read it.
5. Bulk edit of 50 assets applies only to those the user may edit and writes one audit row per asset.
6. Dependency impact on one asset returns affected services using the single `Relationship` model, and inferred links are excluded until confirmed.

---

## H. Microsoft 365 and cloud administration (Google Workspace)

What exists: `integrations/providers/m365.py` (741 lines, `M365Provider`) with client-credentials Graph reads, per-customer `M365Connection` (`integrations/models.py:977`), a manual "Sync" view that stores everything in `connection.cached_data` and renders a generated tenant Document (`integrations/views.py:3229-3650`), a license sync into `licensing` (`licensing/sync.py:88`, scheduler task `sync_licenses`), email ingest and outbound mail via Graph (Phase 10.5/10.6), per-user delegated sign-in for Office documents (`integrations/m365docs/`), and an offboarding access verification that reads M365 (`processes/access_verification.py:130`).

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| Tenant connection and test | Partial | `m365.py:111`; views `integrations/views.py:3126-3223`. FEATURES.md:292 says "Available". Tests only mock one 403 case and the document features (`integrations/tests.py:1094`, `tests_m365docs*.py`); no test of `sync()` found | none (inventory is not a phase) | Verification against a real tenant; a unit test of `sync()` and the de-anonymization helper |
| User inventory | Partial | `get_users` filters `accountEnabled eq true` (`m365.py:134`) so disabled users are invisible; fields: name, UPN, mail, title, department, licenses | none | Disabled accounts, guests (`userType`), last sign-in (`signInActivity`), creation dates |
| License and utilization inventory | Complete (read) | `m365.py:162-171`, `licensing/sync.py:97-150` (SKU to `LicenseSubscription`, per-user reconcile); mailbox, OneDrive, SharePoint usage `m365.py:195-475` | Phase 73 (licensing) | License-to-seat price comparison belongs to billing (see audit) |
| MFA, conditional access, security defaults | Partial | Conditional access policies and roles are read (`m365.py:396-421`); secure score (`:423`). No per-user MFA registration (`authenticationMethods` or the registration report). No security-defaults read | none | Per-user MFA state; security defaults flag; admin role holders without MFA |
| Mailboxes, shared mailboxes, groups, guests | Partial | Shared mailboxes `:182`, mailbox usage `:195`, Teams `:347`, SharePoint sites `:387` | none | Groups (non-Teams), guest users, mailbox forwarding rules, delegates |
| Dormant accounts | Missing | no `signInActivity` anywhere | none | Needs Graph `AuditLog.Read.All` and a license for the activity data (inferred) |
| Security alerts | Partial | `get_defender_alerts` (`m365.py:479`) cached only. It does not enter the Events or `security_alerts` pipelines | 84.8 and "Defender" in 84.x (planned); 74.4 | Map to `SecurityAlert` through the connector framework (Phase 84) |
| Service health | Missing | no `/admin/serviceAnnouncement` reads | none | service health and message center feed, linked to portal Service Status |
| Backup coverage for M365 data | Missing | `backup_monitoring` has no M365 provider | Phase 74 | belongs to section I |
| Baseline reporting | Partial | Secure score and CA policies appear in the generated tenant document only | none | Baseline definition, drift across syncs, customer-facing report. Sync is manual (button) with no scheduled run for the inventory beyond licensing (`run_scheduler.py:47`) |
| New-user provisioning from a ticket (create user, licenses, groups, mailbox, onboarding tasks, approval) | Missing | Provider has no create or update calls other than mail send (`m365.py:604-640`). A guided "New employee" request exists (`psa/request_starters.py:26`) and onboarding runbooks exist (`onboarding/`, Phase 38) but no M365 action | none (Workflow 5 depends on H) | Write scope design, delegated or app-only choice, approval via existing approvals, audit, license availability check, rollback notes |
| Least-privilege delegated access | Partial | Documents use per-user delegated sign-in with explicit scopes (`integrations/m365docs/scopes.py`). Inventory uses app-only `.default` (`m365.py:41`) | 62.4 | Document the exact Graph application permissions per feature; split read and write apps; show granted-vs-needed per connection |
| Google Workspace | Missing | `licensing/sync.py:10` says "Google Workspace is not implemented"; only a license source choice (`licensing/models.py:61`). Roadmap lists it as a 84.x security connector only (`docs/ROADMAP.md:3200`) | 84.x (security) only | Everything: users, licenses, MFA, groups. Scope decision needed ("where practical") |
| Offboarding verification | Complete | `processes/access_verification.py:130` `check_m365`, tests `processes/tests_access_verification.py` | Phase 38 | none |

**Existing functionality to reuse**: `M365Provider` HTTP/token layer; `ConnectionOwnership` (customer ownership of connections); `licensing/sync.py` SKU reconcile; `core.safe_http`; approvals (`PSAApproval`); `onboarding/engine.py` step engine; `psa/request_starters.py` New employee form; vault for credentials (`connection.get_credentials()`).

**Security considerations**
- Client secret stored encrypted via `get_credentials`; `cached_data` JSON holds full user and mailbox lists in the database in clear (inferred privacy impact; bound by the same retention as the connection).
- Any write capability needs separate, narrower credentials than the read app, per-action approval, and audit with before/after; never reuse the mail-send permission.
- Application permission `Mail.Send` is tenant-wide unless scoped by Exchange RBAC (`m365.py:599` comments); keep that guidance in the setup text.
- Staff reach and per-customer restriction on every M365 view (connections are customer-owned; `get_connection_or_404(..., 'write')` is used).
- Never send directory data to AI unless explicitly gated.

**Proposed acceptance criteria**
1. With recorded Graph fixtures, `sync()` returns disabled users, guests and last sign-in; a test asserts dormant users (no sign-in for N days) are listed.
2. A tenant with an admin role holder lacking MFA produces a finding on the connection page.
3. A new-employee ticket creates a draft provisioning plan; nothing executes until the existing approval is granted; the action is audited with the approver and the Graph object IDs.
4. A connection lacking a needed Graph permission shows which permission and which feature is affected (not a generic failure).
5. Technician restricted to customer A cannot view or sync customer B's M365 data (permission test).
6. FEATURES.md lists M365 inventory as Limited until verified against a real tenant.

---

## I. Backup management integrations

What exists (Phase 74.1/74.2, `backup_monitoring/`, 94 tests): connections (customer or MSP-wide), jobs, runs, repositories with capacity, restore tests recorded by people, alert policies and alerts, tickets from alerts, health with staleness, Device Workspace panel, scheduler task `poll_backup_monitoring` (`run_scheduler.py:43`). Providers: PBS polled, restic, Borg and Kopia via signed push (`backup_monitoring/models.py:30-38`).

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| Job and protected-asset inventory | Complete | `backup_monitoring/models.py:129,148`; `ingest.py` | 74.1 | none |
| Last success, retention, storage, failures | Complete | models `:175,196`; `health.py`; alerts `alerts.py` | 74.1 | Retention is the provider's text field, not evaluated |
| Restore verification and test history | Complete | `RestoreTest` `models.py:222`, `recording.py`; kept apart from job success | 74.1 | Automated restore verification does not exist (by design; people record) |
| Commercial providers (Veeam, Acronis, Cove, Datto, others) | Missing | `docs/BACKUP_MONITORING.md` table states "Planned, not implemented"; only 4 provider constants | 74.2 "commercial planned" | Adapter per product on `providers/base.py` (`list_jobs`, `list_runs`, `list_repositories`) with recorded fixtures; real-service verification |
| Rem0te backup and endpoint health | Missing | none | 74.3 planned | Contract addition via the coordination file |
| Start, retry, restore, restore status | Missing | `providers/base.py:66-75` is read-only | none | Provider action API, permission (`manage_backup_integrations` today covers config only), approval, audit, per-customer scoping |
| M365 and cloud backup coverage | Missing | see H | none | provider adapters |
| Compliance backup evidence | Complete (code), roadmap and FEATURES wrong | `compliance/views.py:276-312` reads `backup_monitoring`; FEATURES.md:232 says "Evidence pack backups section is empty"; roadmap 74.6 says planned | 74.6 shown "planned" | Update the statuses; add a test if none exists (no test for `_section_backup_evidence` found by grep) |
| Customer backup reports | Partial | Health score uses backup signals (`health_score/providers.py`, 78.2); executive card `backup_failures` (`executive/providers.py:786`) | 74.5, 75.2, 77 | Customer-facing backup report (portal and scheduled PDF); `docs/plans/EXECUTIVE_METRICS.md` still says the card is "Pending: dev/backup-monitoring (not installed here)" and the provider's availability text says the same (`executive/providers.py:806`); the module is installed, so those strings are stale |
| SSRF protection of provider calls | Complete | PBS now uses `guard_session` and `validate_url` (`providers/pbs.py:22,76`); `PBSAddressGuardTests` (`tests.py:1070`) | SR-02 shipped | none |
| Commercial-grade polling at scale | Partial | single-process management command through the scheduler | none | Concurrency or per-connection timeouts need review (unverified) |

**Existing functionality to reuse**: `providers/base.py` interface, signed push ingest, alert policy engine, `core.safe_http`, vault-style credential storage, `backup_monitoring/tickets.py`, `view_backup_status` and `manage_backup_integrations` permissions, the health-score backup signals.

**Security considerations**
- Provider credentials are write-capable for some products (Veeam, Acronis). Store separate read-only and action credentials; refuse action buttons without a distinct permission.
- Restore actions must be approval-gated and audited, never reuse monitoring credentials.
- SSRF-guard every new provider with an explicit private-address opt-in (PBS pattern).
- Push-report secrets are shown once; keep rotation.
- Restore targets must be per-customer; a restore must never write to a location outside the customer's systems.

**Proposed acceptance criteria**
1. A new provider adapter passes the provider-conformance tests (jobs, runs, repositories, staleness) against recorded fixtures and a real-service run is recorded before it is listed as Supported.
2. An unreachable provider shows every job as Stale, never healthy (existing behaviour kept as a regression test).
3. A restore request requires the new action permission and an approval, and writes an audit row naming the approver, source, and target.
4. The compliance evidence pack lists per-customer jobs with state and restore-test dates (test added), and the FEATURES.md row no longer says empty.
5. The executive card reads live data when the module has connections (test added; stale text removed).

---

## J. Reporting and business intelligence

What exists: `reports/` (queries, 1,811 lines; generators; 4,982-line views; wallboards; saved queries; scheduled reports) and `executive/` Business Overview (18 cards with drill-down, defined in `docs/plans/EXECUTIVE_METRICS.md`; 44 tests). Phase 3, 19, 26, 75, 78, 83 and 89 are the roadmap anchors.

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| MRR, ARR, growth, churn, renewals | Complete | `reports/queries.py:1451-1795`; cards `executive/providers.py` (`mrr_arr`, `customer_growth`, `contract_renewals`) | 75.4/75.6 | Churn covers contracts only |
| Customer, contract, project, service-line profitability and margin | Complete (with caveat) | `reports/queries.py:479-1094`; `reports/costing.py`; `reports/tests_profitability.py` (709 lines) | 75.1 | Roadmap 75.1 notes three revenue definitions (one includes tax, one counts unbilled bundles) unified in Phase 102.7 |
| Utilization, effective rate, billable vs non-billable | Complete | `reports/queries.py:535-780,1679` | 19, 75 | Block utilization depends on Phase 101 (billing audit) |
| Leakage, unbilled tickets | Partial | `revenue_leakage` (`:780`), `unbilled_time` (`:1699`) | 75, 76 | Depends on Ticket Time & Charges (Phase 101/102) |
| Pipeline, win rate, sales cycle | Partial | `sales_funnel` (`reports/queries.py:1312`), quote-conversion report (`reports/urls.py:145`) | 5, 97 | Sales-cycle length, acquisition cost, source attribution |
| Overdue invoices / AR aging | Complete | AR card (`executive/providers.py`), `ar-aging/` URL | 75.4 | Draft invoices count, per EXECUTIVE_METRICS note |
| Service delivery: tickets per customer, technician, SLA, first response, resolution | Complete | `reports/generators.py` (`PSAOpenTicketsByClient`, `PSATicketsByAssignee`, `PSAResponseTimeByTech`, `PSAResolutionTimeByClient`, `PSASLABreaches`), `sla_trend_by_priority` (`queries.py:948`), `operational_metrics_report` (`views.py:4583`) | 19, 26 | none for these |
| Tickets per device | Partial | `PSARecurringIssuesReport` (assets with multiple tickets) `generators.py:601` | 19 | Per-device report with drill-down and RMM health overlay |
| Repeats, reopens, escalations | Partial | Reopen is handled by routing signals (`psa/routing/signals.py:57`) but no reopen counter or report; escalation counts not found | none | Reopen/escalation fields and a report |
| Satisfaction | Partial | Pulse checks (`pulse/`), CSAT (`psa/csat.py`), health-score satisfaction dimension | 66, 78 | A CSAT report by technician, customer and period; CSV export of pulse results is planned (FEATURES.md:226) |
| Common problems | Partial | Tickets by dimension (queue, type, priority) only (`generators.py:551-564`) | none | Category / problem-type ranking, KB-article correlation |
| Automation impact | Complete | `workflow_performance_report` (`views.py:4737`) | 19 v6 | none |
| Role dashboards with filters | Complete | Business Overview filters (date, customer, service line, location), role presets (Phase 67.6/67.15), per-card permission | 67, 75 | Filters are per-card; no cross-card saved filter set |
| Executive dashboards: backup and license cards | Partial | `backup_failures` and `licensing_renewals` providers exist; EXECUTIVE_METRICS marks them Pending | 75.4 | Update statuses; test with data present |
| One set of data definitions | Partial / Duplicated | Business Overview reuses `reports.queries`, but `exec_scorecard` (`views.py:1668`), `kpi_dashboard` (`:4437`), `mrr_forecast_report` (`:3389`), `analytics_overview` (`:841`) and `margin-analytics` are separate pages computing overlapping KPIs. `exec_scorecard` counts open tickets and MTTR over all tickets (`views.py:1695-1710`) even though it computes `scope` for revenue (unverified impact; requires `reports_view_financial` MSP-wide) | 102.7 | Retire or point the older pages at the executive providers |
| CSV and PDF | Partial | CSV on PSA reports and several others (`core/csv_safe` used); PDF only on 4 reports through `reports/pdf_export.py`; FEATURES.md:224 says template PDFs are plain text | 26, 89.2 | PDF for Business Overview and for service-delivery reports; customer review pack (89.2 planned) |
| Scheduled reports | Complete (existing) | `run_scheduled_reports`; `reports/access.py` `may_see_report_type` | 26 | Report types in `ReportTemplate.REPORT_TYPES` are documentation-oriented (assets, vault audit); the PSA generators are reachable through the `psa_*` URL |
| Health score | Duplicated | `reports/queries.py:1169-1312` (`client_health_score`) and `health_score/` app (Phase 78, 69 tests). Wallboard widgets and `psa_client_health` (`reports/views.py:1854`, `widget_sources.py:456,474`) still use the legacy calculation | 78 | Two scoring models can disagree on the same customer; migrate widgets to `health_score` |
| Wallboards | Duplicated | legacy `/reports/wallboard/` (`urls.py:77`) next to configurable `/reports/wallboards/` (`:90-105`) | 83 | Retire the legacy wallboard once presets land |
| NOC widgets and staleness | Partial | See `GAP_ANALYSIS.md` 6.11-6.13 | 83.x planned | Not repeated |

**Existing functionality to reuse**: `executive/providers.py` metric provider pattern (value plus rows in one call, incomplete flag, not_configured), `reports/costing.py` rate snapshots, `reports/access.py` (`has_msp_wide_perm`, `viewer_client_scope`), `reports/pdf_export.py`, `core/csv_safe`, `health_score/` for any health display, `reports/saved_query.py` (user-scope check at `:213`).

**Security considerations**
- Every card and report needs both the permission and the viewer's client scope (done on Business Overview; verify the legacy pages `exec_scorecard`, `kpi_dashboard`, `analytics_overview` which each have their own checks).
- Financial and cost data (margins, cost rates) must stay behind `view_profitability` and never reach portal or customer roles.
- CSV and PDF exports must pass through `csv_safe`; scheduled report e-mail recipients must be re-validated against the report's permission at send time.
- Drill-down rows must obey the same scope as the totals.
- Saved queries (`reports/saved_query.py`) can reach any model: keep the model whitelist.

**Proposed acceptance criteria**
1. A technician restricted to customers A and B sees totals on every report and dashboard that equal the sum of only A and B (one test per legacy page).
2. MRR, revenue and margin shown on Business Overview, exec scorecard and KPI dashboard are identical for one fixture; test fails on divergence.
3. A reopen count and escalation count appear in a service-delivery report and match a fixture of known reopened tickets.
4. Business Overview exports to PDF and CSV with the "estimate, not accounting" label preserved.
5. Only one health score value is shown for a customer anywhere in the UI.
6. A scheduled report to a recipient who lost the permission is not delivered and the failure is logged.

---

## K. Customer portal and self-service

What exists (`portal/`, 55 plus authz, guided-request, approval and login tests): tickets with replies, secure replies and votes (`portal/urls.py:20-33`); public quote signing by token (`:35`); knowledge base (`:37-39`); vault entries with per-entry visibility (`:41-45`); approvals (`:49`); guided service request catalog (`:52-56`); agreements (document signing, `:59-64`); pulse feedback (`:68-71`); billing: invoices, payments, receipts, saved methods (`:73-82`); status page `:21`; customer switcher `:84`; configurable portal address, sign-in and branding (Phase 67.10).

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| Unified customer dashboard | Missing | `portal/urls.py` home is the ticket list (`:20`) | Phase 77 planned | Dashboard composed of the sections below |
| Tickets, requests, approvals | Complete | `portal/views.py`, `portal/request_views.py`, `tests_authz.py`, `tests_named_approvers.py` | 54, 77.2 | Ticket merging and customer-visible time are out of scope here |
| Contracts, included services, block balances | Missing | no contract model use in `portal/` (also billing audit N, `CAPABILITY_AUDIT.md:194-195`) | 75.2, 77.1 | Read-only contract and allowance view; needs Phase 101 ledger for balances |
| Invoices, payments | Partial | `portal/urls.py:73-82`; payment providers mocked, not verified (README.md:272) | 72.3 | Verification with real gateways |
| Quotes and work approvals | Partial | Public token signing exists (single signer, no decline: `CAPABILITY_AUDIT.md:110`); no quote list in the logged-in portal; "customer approvals" cover service requests | 104 | Quote inbox, decline, deposit, change orders |
| Managed assets | Missing | no asset view in portal | 77.1 | A customer-safe asset list (name, type, location, warranty) with an explicit per-field allow-list |
| Backup status, security summary, service status | Partial | Service status page exists (`portal/urls.py:21`); no backup or security surfaces | 77.1, 78.6, 89 | Backup and health summary for customers (reuse `health_score`, `backup_monitoring.summary`) |
| Maintenance notices | Missing | none found in `portal/` (grep for maintenance in portal returned test files only) | 77.1 ("maintenance and communications") | Notice model or reuse announcements (`portal/urls.py:23` dismissable announcements exist) |
| New employee, equipment, software requests | Complete | `psa/request_starters.py:26,217,232` | 54 | Provisioning behind the request depends on H |
| Signing | Complete (documents), Partial (quotes) | `portal/agreement_views.py`, `contracts/` | 65, 104 | see Quotes |
| Published documentation | Complete | `portal/views.py` KB; audience controls | 22 | none |
| Configurable forms | Complete | `psa/request_forms.py`, `request_builder_views.py`, `tests_request_forms.py` | 54 | none |
| Never internal costs, private notes, privileged credentials, other customers' records | Complete (tested) | `portal/tests_authz.py`, `payments/portal_views.py:12-14`; membership check per request (`portal/views.py:86-111`); `tests_portal_login.py` | 49, 51 | Re-run with each new section (acceptance criterion) |
| Public token endpoints throttled | Gap | `quote_sign` has no throttle (`portal/views.py:619`) while agreement unsubscribe has one (`agreement_views.py:106` `@throttled`) | `GAP_ANALYSIS.md` 8.06 | `@throttled` on quote signing and CSAT respond |

**Existing functionality to reuse**: `portal_required` and per-customer membership resolver, `psa/request_*` form engine, `PSAApproval` named approvers, `payments/portal_views.py`, `health_score`, `backup_monitoring/summary.py`, `statuspage`, announcements, `core/public_throttle.throttled`.

**Security considerations**
- Every new section needs an explicit field allow-list and a cross-customer test (membership in two customers, switching customers).
- Asset and backup views must not leak IPs, credentials or internal notes; use serializers, not template access to full models.
- Quote token links are bearer capabilities: add throttling, expiry check and audit; consider IP and e-mail verification for large quotes.
- Portal sessions and 2FA behaviour for customer users (Phase 80/64) need to match staff expectations for anything involving approvals and payments.
- Rendering of ticket text and request answers in the portal must stay escaped.

**Proposed acceptance criteria**
1. Portal home shows tickets, open approvals, invoices due, contract summary and service status for the current customer only; a user with two customers sees only the selected one.
2. A customer user cannot retrieve a managed asset's credential, internal note, cost or another customer's asset by ID (404, tested).
3. Backup and health summaries show "unknown" or "stale" instead of healthy when data is old.
4. `quote_sign` returns 429 after the configured number of attempts from one address (test).
5. A customer approval of a quote or request creates the matching audit and ticket/contract link; MSP-only effects remain behind an MSP approval.
6. Block balance shown in the portal equals the ledger used by the invoice (after Phase 101).

---

## M. Installation, first-run setup, settings experience and UI principles

| Capability | Status | Evidence | Roadmap | Missing components |
|---|---|---|---|---|
| Install paths | Complete | `install.sh`, `docker-compose.yml`, `docker-entrypoint.sh`; rehearsals in CI (`.github/workflows/install-upgrade.yml`, per 59.6) | 42, 59 | `install.sh` installs no Nginx or TLS (FEATURES.md:303) |
| Default administrator password | Partial | Still created as `admin` / `ChangeMe123!` (`install.sh:815-816`); banner, system warning and readiness check shipped v3.17.730 (`core/readiness.py`, `core/system_warnings.py:229`, 9 tests) | 96.1 | Optional: random generated password shown once; forced change at first login |
| First-install detection and wizard (identity, FQDN, proxy/TLS, mail, administrator, MFA, modules, portal, billing, accounting, AI, Rem0te pairing, backups, verification) | Missing | No wizard code (grep for setup assistant / first-run found nothing). Onboarding engine (`onboarding/engine.py`, `onboarding/steps/`) is for customers, not installs | 96.2-96.4 planned | Install-session model, detection that leaves upgrades untouched, steps writing through existing settings |
| Install readiness (2FA, site URL, mail, backups, scheduler, disk, migrations) | Partial | `core/readiness.py` checks default password, superuser 2FA, site URL, mail, scheduler, version; built on upgrade preflight | 96.1 | Last-backup age ("follows the scheduled backups work"); no scheduled `manage.py backup` task (FEATURES.md:303) |
| Searchable settings experience | Complete | Settings center with ten categories and search (`core/navigation.py`, `core/settings_home_views.py`, 67.4/67.12); command palette (`core/palette.py`) | 67 | none |
| Per module: enabled, config, connection status, credentials, security needs, dependencies, test, health, docs link | Partial | Optional Modules page shows on/off and dependencies and soft dependencies (`core/modules.py`, `core/modules_views.py:16`); integration status pill (`integrations/status.py`) and sync health (`integrations/health.py`). No single page combines all columns; FEATURES.md:296 says some switches only hide menus | 67.12 | One module health table: enabled, configured?, last test, credential present, required security setting, doc link, "Test" button |
| Guided tours, contextual help | Missing | | 96.6, 96.7 | |
| Sample data isolated | Missing | | 96.5 | Must never reach reports or billing |
| UI principles (short menus, shallow navigation, few modals, consistent labels, themes, responsive) | Partial | Ten-section navigation, compact frame, Professional Dark and light themes, phone layout, "every page has a path" test (`core/tests/test_nav_reachability.py`) | 58, 67 | Customer-role screenshots and Classic dashboard retirement review pending (`docs/plans/classic-dashboard-retirement.md`); roadmap 67.4 says "nine" categories while 67.12 says "ten" |
| Documentation accuracy | Partial | FEATURES.md header says "as of v3.17.719" (current is 733); FEATURES.md:303 predates 96.1 wording | 96.7 | Refresh FEATURES.md with each release |
| Upgrade safety | Complete | Phase 59 (signed tags, pinned apply, preflight, verified backup, resume, rehearsals) | 59 | LTS channel planned only |

**Existing functionality to reuse**: `core/readiness.py` and `upgrade` preflight checks; `core/modules.py` dependency registry; `core/navigation.py` destinations; `onboarding/engine.py` step engine (extend, do not fork); `core/system_warnings.py`; existing connection test buttons in `integrations/`.

**Security considerations**
- The wizard must run only before the first administrator completes 2FA enrolment and must never be reachable on an upgraded install (a world-writable setup endpoint on a live system is a takeover path).
- Secrets entered in the wizard (SMTP, AI keys) must be stored through the same encrypted fields; never echoed in summaries or logs.
- The default password must be flagged even when `DJANGO_SUPERUSER_PASSWORD` is supplied by Docker; check the Docker path (`docker-entrypoint.sh:97-109`).
- A readiness page shows security posture; staff-only.

**Proposed acceptance criteria**
1. On an empty database the first superuser is routed to the wizard after 2FA enrolment; on a populated or upgraded database it is not (two tests).
2. Every wizard step saves through the existing settings model and is audited; an upgrade rehearsal shows settings unchanged.
3. The default-password check clears after the password changes and re-raises if the password is reset to the installer value.
4. Module health page lists every module with enabled / configured / last test / dependency state and links to its guide.
5. A fresh Docker install and a fresh script install both reach "ready" (no red checks) without manual file edits.

---

## Genuine gaps not covered by any roadmap phase

1. Ranked full-text search for documents and assets (only `icontains`).
2. Per-asset field-level change history; bulk asset editing.
3. Document attachments and secure share links (documents cannot carry attachments; no expiring links).
4. Discovery scope approval (administrator-approved ranges that a collector cannot exceed) and a "suggested / unverified" staging state for discovered devices and inferred links.
5. Collector support for `classify_enabled` (the setting exists, nothing honours it).
6. Microsoft 365: disabled and guest users, sign-in activity and dormant accounts, per-user MFA registration, security defaults, service health, baseline drift, user provisioning with approval. Google Workspace as an inventory (not only a security connector).
7. Backup provider actions (start, retry, restore) with permission and approval; customer backup report.
8. Reopen and escalation counters and a service-delivery report for them; CSAT report; per-device ticket report; common-problem ranking.
9. Retirement plan for duplicate dashboards and scoring (`exec_scorecard`, `kpi_dashboard`, legacy `wallboard`, `client_health_score`).
10. Throttling on public quote signing and CSAT response endpoints (`GAP_ANALYSIS.md` 8.06 lists it, no roadmap phase).
11. A single module-health page (enabled, configured, tested, healthy, documented).
12. Hiding or relabelling the topology and port-map pages while no data producer exists (owner decision).
13. Maintenance notices and managed-asset view for the customer portal are inside Phase 77's headline but have no sub-bullet.

## Roadmap or FEATURES.md statuses that look wrong

| Item | Where | Evidence | Suggested correction |
|---|---|---|---|
| Phase 33 "complete" | ROADMAP.md:738 | The topology map and port map need LLDP/CDP/bridge data nothing produces; the collector only sends ICMP and ARP results (`collector.py:126-149`); `classify_enabled` is unused | Mark partial: server side complete, topology data source absent (owner decision) |
| Phase 34 text lists SNMP/SCP/vendor APIs | ROADMAP.md:771 | Implementation is SSH only | Reword capability line to SSH only |
| 74.6 Compliance backup evidence "planned" | ROADMAP.md:2956 | `compliance/views.py:276-312` reads real backup data | Mark shipped (version to be confirmed from git history) |
| FEATURES.md "Evidence pack backups section is empty" | FEATURES.md:232 | same | Remove limitation |
| Executive `backup_failures` and `licensing_renewals` "Pending" | `docs/plans/EXECUTIVE_METRICS.md`, `executive/providers.py:806` | `backup_monitoring` is installed with models and 94 tests; licensing module exists | Update text and add data-present tests |
| FEATURES.md "Microsoft 365 tenant connection — Available" | FEATURES.md:292 | Read-only inventory, manual sync, no tests of `sync()`, no real-tenant verification; README.md:272 lists only M365 documents as unverified | Limited, with limitation text |
| FEATURES.md "Network discovery import — Available, No SNMP or LLDP" | FEATURES.md:147 | Accurate, but does not mention that topology and port-map pages exist without a data source | Add limitation |
| Phase 88.1 "Dependency graph (planned)" | ROADMAP.md:3260 | Phase 16 already shipped relationship graph, `Service`, dependency chains | Re-scope 88 to impact analysis and provenance only |
| FEATURES.md header version | FEATURES.md:3 | says v3.17.719; repo is 733 | Refresh |
| FEATURES.md install row | FEATURES.md:303 | says nothing about the 96.1 warning shipped in 730 | Add |
| Phase 67.4 "nine settings categories" vs 67.12 "ten" | ROADMAP.md:2790,2828 | internal inconsistency | Align |
| FEATURES.md "Warranty lookups: stubs" with README Business tools claims | FEATURES.md:132 | README.md:272 acknowledges it; the Business list in README.md:136 still implies distributor, warranty and payment features | Keep every list at the stated verified level |

## Duplicated implementations

- Health score: `reports/queries.py:1169` plus legacy pages and widgets vs `health_score/` (Phase 78).
- Executive KPI pages: `reports/views.py` `exec_scorecard`, `kpi_dashboard`, `mrr_forecast_report`, `analytics_overview`, `margin_analytics` vs `executive/` Business Overview; MRR has `monthly_amount` as the single rule but the pages still assemble their own totals.
- Wallboards: `/reports/wallboard/` legacy vs `/reports/wallboards/`.
- Network graphs: `assets` relationship map and `topology.json`, `network_discovery/topology.py` topology, hardware connectivity diagrams.
- Dependency mapping: Phase 16 relationships and `Service` vs planned Phase 88.1.
- Network scanning: `scripts/network_scanner.py` (nmap CLI), the PowerShell script and `deploy/network-collector/collector.py` (three scanners, two import formats).
- Discovery import paths: Phase 32 upload and Phase 33 results share `importer.py` (good); the controller syncs (UniFi/Omada) write assets by a separate path (`integrations/network_assets.py`).
- Report systems: `ReportTemplate` generators (documentation-oriented), `psa_*` generators, saved queries, custom dashboards, wallboards.

## Major architectural concerns

1. Generic `Relationship` (type string plus id, no FKs) cannot enforce referential integrity or cascade on delete; orphaned rows are possible (inferred). It is the basis of all dependency work.
2. `M365Connection.cached_data` stores whole-tenant JSON on a single row and regenerates an HTML Document on each sync; no structured models means no history, drift or per-field permissions. Provisioning and baselines need real models.
3. Discovery writes straight into `Asset` with provenance only in `custom_fields`; adding suggestion/verification states later is easier if introduced now.
4. `reports/views.py` is 4,982 lines mixing calculation, permission and rendering; the executive provider pattern is the better design and should become the single calculation layer.
5. Per-source IP rate limits (collector, portal) are fragile behind NAT or proxies; the repo already has a trusted-proxy model (Phase 81) that these paths should use (inferred).
6. The setup wizard (Phase 96) depends on 2FA middleware ordering and install-state detection; a wrong implementation yields an unauthenticated setup surface, so it needs the same review as the signed update flow.
7. Integration honesty: only PBS, restic, Borg and Kopia exist for backup, and M365 inventory is read-only and unverified; marketing and FEATURES text must stay at the verified level (checklist item 4 of the program).
8. SNMP/LLDP/CDP and SNMP-based monitoring: blocked, owner decision pending. The empty topology and port-map pages are the visible consequence and need a decision (hide, label, or keep for pushed data).
