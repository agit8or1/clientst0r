# Wallboards, NOC/SOC, security monitoring and automation — Phase 0 audit and plan

Feature-gap analysis for the program in roadmap Phases 81–90. Static code audit of `main` at
v3.17.712 (2026-11-18); no vendor was contacted and no tests were run for this document. Paths are relative
to the repository root.

**Status legend:** Fully implemented / Partial / Stub only / Missing / Requires real-vendor testing (code
exists, but only mocked or fixture coverage).

**Ground rules for the whole program**

- Extend what exists; no second alert engine, dashboard stack, AI configuration or permission system.
- No vendor connector is called complete until authentication, ingestion, normalization and error handling
  have been run against a real instance or the vendor's own test environment. Until then it is listed as
  *requires real-vendor testing*.
- Sample data is shown only where real data is missing, and is labelled as sample data on screen.
- Unknown or stale data is shown as unknown, never as healthy or compliant (the Phase 78 rule).
- Automated remediation is off by default, needs explicit permission and approval, and is audited.
- Event payloads, tickets and logs are data, never instructions — for automation and for AI alike.
- Correlation, incidents and wallboards never mix two customers' data.
- No new distributed infrastructure (message brokers, WebSocket servers) unless the database and the
  existing scheduler are shown to be insufficient by measurement.

## 1. Platform facts that shape the design

| Fact | Evidence | Consequence |
|---|---|---|
| No Celery / RQ / Redis; work runs from systemd timers and the one-minute DB-backed scheduler | `core/management/commands/run_scheduler.py` `COMMAND_TASKS`; `deploy/clientst0r-scheduler.timer` | Ingestion and correlation run as scheduler tasks and bounded DB queues, with a dead-letter table |
| No Channels, WebSocket or SSE code; gunicorn sync workers | `config/asgi.py` standard; nginx only maps the Upgrade header | Wallboards use one batched, cached snapshot request per board at a bounded interval (ETag / 304); SSE only if measurements show it is needed |
| No JS build step; CDN libraries with nonce CSP | `core/csp_middleware.py`; Chart.js 4.4.1, SortableJS 1.15.2 already used | Charts stay on Chart.js; the grid editor uses SortableJS plus CSS grid; no new framework |
| Prod database is SQLite | deployment notes | Event retention, quotas and indexes are mandatory from day one; raw events are size-capped |
| Permission registry with role templates | `accounts/permission_registry.py`, `accounts/role_seeds.py` | New permission keys and seeded roles (L1–L3, Security Analyst, Security Administrator) — configurable, not hard-coded |
| Navigation has ten fixed sections and tab budgets (9 tabs, 6 Configure items) | `core/navigation.py`, `core/tests/test_navbar_sections.py` | New pages go under Security & Monitoring; Reports is already at its 9-tab limit |

## 2. Security alerts, SIEM and incidents

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Security alert model and queue | Partial | `security_alerts/models.py:134` `SecurityAlert`; `alerts/` views with decide / bulk decide | Statuses new / acknowledged / dismissed / resolved; Investigating, Contained, False Positive and Suppressed missing |
| Vendor connection model | Partial | `security_alerts/models.py:13` `SecurityVendorConnection`; encrypted credentials, hashed webhook tokens | 16 vendor choices are dropdown entries only |
| Vendor adapters | Stub only | `security_alerts/adapters/defender.py` returns `[]` by design; base `adapters/base.py:15` on `integrations/sdk` | No working vendor connector exists |
| Generic SIEM webhook (CEF / JSON / syslog text) | Partial | `security_alerts/models.py:275` `SIEMWebhookEndpoint`; `security_alerts/siem.py` | URL token plus optional HMAC; no timestamp, nonce or replay protection; no LEEF; no network syslog listener |
| Incidents with timeline, SLA and playbooks | Partial | `SecurityIncident` `:390`, `SecurityIncidentEvent` `:478`, SLA policy `:521`, playbooks `:640` | Correlation is one fixed rule (same customer, asset hint and severity within 60 minutes, `:846`); no ticket FK on the incident |
| Alert rules | Partial | `SecurityAlertRule` `:221` | Only "create ticket", with an hourly suppression window |
| Security overview, threat overview, exposure scores, digests | Fully implemented | `overview.py`, `exposure.py`, `digest.py` | Reused by the Operations Center and SOC wallboard |
| Optional AI incident summary | Fully implemented | `security_alerts/ai_summarizer.py`, gated by `psa_ai_enabled` | Starting point for the AI Operations Analyst |
| Normalized event store (raw events, MITRE, IOC, dedup key, correlation group) | Missing | — | Phase 82 |
| Wazuh, Sentinel, OPNsense, Splunk, Elastic, Graylog, QRadar, Okta, Duo, AWS, Tenable, Qualys, Greenbone, ExploitHound, MailThreatZero connectors | Missing | names appear only in help text | Phase 84 batches |

## 3. Other alert sources

| Source | Model | Status | Notes |
|---|---|---|---|
| RMM sync | `integrations/models.py:669` `RMMAlert` | Fully implemented | Feeds the alert policy when `include_rmm_sync` is on |
| Rem0te signed events | `psa_ai/models.py:615` `Rem0teAlertEvent`, `:641` `Rem0teAlertTicket` | Fully implemented | Ed25519-signed, replay-protected; contract `ticket-rmm-v1` |
| Backup monitoring | `backup_monitoring/models.py:297` `BackupAlert` | Fully implemented | Own dedup key, occurrence count and ticket link |
| Website, SSL, domain and WAN monitors | `monitoring/models.py:16` `WebsiteMonitor`, `:296` `MonitorCheck` | Fully implemented | Own email notifications |
| Alert policy (grouping, site outages, maintenance, holds) | `psa/routing/alert_policy.py`, `models.py:388–563` | Fully implemented, off by default | Covers Rem0te and RMM alerts only, not security or backup alerts |
| Shared alert / event model and generic alert↔ticket link | — | Missing | Five separate alert models and five separate ticket links today |

**Decision:** keep each source model (they hold source-specific detail and existing data) and add a thin
shared layer: a normalized `OperationalEvent` / alert envelope with source adapters, one alert↔incident↔ticket
link table, and the alert policy extended to every source. Wallboards, the Operations Center, correlation,
notifications and reports read the shared layer.

## 4. Wallboards and dashboards

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Custom wallboards (12-column grid, rotation, per-board refresh) | Partial | `reports/models.py:269` `Wallboard`, `:361` `WallboardWidget`; SortableJS reorder | Full-page meta refresh; per-widget refresh documented as not yet live; reorder only, no resize |
| Widget data sources with fail-closed permissions | Fully implemented | `reports/widget_sources.py` `WIDGET_SPECS`, `DEFAULT_SPEC`, `viewer_for()` | About 30 sources; the catalog to extend |
| Wallboard templates | Partial | `WALLBOARD_TEMPLATES`: operations, tickets, alerts, monitoring, sales, health | Service Desk, Technician, NOC, SOC, Executive, MSP Operations and Customer presets missing |
| Token display (read-only, encrypted token, off by default, rotation) | Fully implemented for the schedule board only | `scheduling/models.py:300` `SchedulerWallboard`, `scheduling/views.py:401` | Pattern for kiosk pairing; reports wallboards need a login today |
| Main dashboard widget registry and role presets | Fully implemented | `core/dashboard_widgets.py` (about 62 widgets), `DashboardRoleDefault` | Separate stack; KPI builders reused, not duplicated |
| Executive overview with drill-down | Fully implemented | `executive/` app, `executive/providers.py` | Executive wallboard reads these providers |
| Dark theme tokens and contrast test | Fully implemented | `static/css/themes.css` (Professional Dark), `core/tests/test_theme_contrast.py` | Wallboard presentation mode adds a dedicated token set on top |
| Draft / published versions, import / export, kiosk pairing, density, transitions, audible alerts | Missing | — | Phase 83 |

## 5. NOC/SOC operations, automation and on-call

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Remediation playbooks | Partial | `RemediationPlaybook` `:640`, `execute_playbook` `:739` | Four actions (ticket, email, quarantine flag, workflow rule); no dry run, approval gate, versioning or emergency stop |
| Support workflows (evidence → causes → Rem0te action → verified outcome) | Fully implemented | `psa/support_workflows/engine.py` | Approval happens in Rem0te; model for SOAR approvals |
| Rem0te actions | Partial | `integrations/rem0te/actions.py`; catalog has one remediable action (`windows.service.start@1`) | Isolation, process kill, diagnostics catalog, remote sessions and endpoint detail need Rem0te contract additions |
| On-call | Partial | `psa/routing/models.py:293` `OnCallShift` | Used by ticket routing; no rotations, escalation chains or acknowledgement deadlines |
| Notification channels | Partial | `core/mailer.py`, `core/sms.py`, `api_mobile/push.py`, `core/webhook_sender.py` | No notification hub, delivery history, retries or storm grouping; push used only for ticket assignment |
| Maintenance windows | Partial | `AlertMaintenanceWindow` `psa/routing/models.py:488` | Applies to Rem0te / RMM alerts only |
| Service dependencies | Partial | `assets/models.py:779` `Relationship`, `relationship_views.py` topology graph, `network_discovery.NetworkLink` | No verified/inferred flag, impact analysis or maintenance preview |

## 6. Reporting, scoring and AI

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Scheduled reports with email delivery | Partial | `reports/models.py:52` `ScheduledReport`, `run_scheduled_reports` | Report types are inventory-oriented; brand colour hard-coded; ReportLab only |
| Customer health score with explanations | Fully implemented | `health_score/` (Phase 78) | Security posture scorecard extends its security dimension rather than adding a parallel score |
| AI gateway, budgets, per-customer AI policy, redaction, injection envelope | Fully implemented | `psa_ai/services/gateway.py`, `AIBusinessPolicy`, `guardrails.py` | Analysis jobs are ticket-bound today; the analyst needs alert / incident evidence bundles through the same gateway |
| Customer portal dashboards | Missing | `portal/` has tickets, KB, approvals, billing | Customer wallboard and scorecards follow Phase 77 permissions |

## 7. API access control and network restrictions

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Trusted-proxy client IP resolution | Fully implemented, settings-file only | `core/client_ip.py` walks `X-Forwarded-For` from the nearest hop; only `TRUSTED_PROXY_CIDRS` may forward; unix-socket peer = local proxy | Needs an admin view of the trusted proxies and a diagnostic page; already used by `api/authentication.py` and `api_mobile/auth_utils.py` |
| Site-wide IP and country firewall | Fully implemented (web) | `core/models.py:2209` `FirewallSettings`, `:2314` `FirewallIPRule`, `:2374` `FirewallCountryRule`, `core/firewall_middleware.py` | Global allow / deny for the web app; no API-key, integration, customer or endpoint scope; no expiry |
| API keys | Partial | `api/models.py:62` `APIKey` — hashed key, prefix, role, scope, `last_used_ip` | No expiry, rotation, network restriction, per-key rate limit or read-only / write split beyond role |
| Inbound webhook protection | Partial | Rem0te and Connect have signatures and replay records; SIEM / security webhooks have a URL token plus optional HMAC only | No per-webhook source rules, timestamp window, body cap or rate limit across all receivers |
| Rate limiting by client address | Defect | `connect/ratelimit.py:32` uses `REMOTE_ADDR` directly, which is empty behind the local nginx socket | All Connect clients share one bucket; switch to `core.client_ip.get_client_ip` |
| Policy decision log and denied-request dashboard | Missing | `FirewallLog` covers web firewall blocks only | Phase 81; denials also feed the shared event layer (Phase 82) |

**Decision:** one policy-evaluation function (`allow / deny + matched rule + policy version`) called by every
API authentication path and every webhook receiver, before the protected operation runs. Precedence: an
explicit deny anywhere wins; then, at each scope that has an allowlist (global → customer → integration →
credential → endpoint group), the request must match it — default deny once any applicable allowlist is on.
Private addresses get no implicit trust. Existing installs start Unrestricted, so nothing changes until an
administrator tightens a policy; recovery is a server-side management command, never an HTTP bypass.

## 8. Security concerns to design for

- SIEM webhook replay: add a signed timestamp and nonce window before any new vendor uses webhooks.
- Ingestion denial of service: per-connection rate limits, payload size caps, bounded queues and storage
  quotas; a failing connector must not slow ticket pages (separate scheduler tasks, time budgets).
- Kiosk displays: a display credential is not a user session; it can read only its assigned boards, cannot
  call any write endpoint, and is revocable at once.
- SOAR and AI: actions come only from an allow-listed catalog with typed parameters; nothing in an event
  payload or model output is executed; every state change needs a permission, an approval record and an
  audit entry.
- Correlation and dashboards are tenant-scoped in the query layer, with negative tests per surface.
- Secrets reuse `vault/secret_fields.py`; saved secrets are never shown again.

## 9. Phases (dependency order)

| Phase | Title | Depends on |
|---|---|---|
| 81 | API access control and network restrictions | — (ships before any new vendor API or webhook endpoint) |
| 82 | Shared operational event and alert foundation | 81 for new ingestion endpoints |
| 83 | NOC/SOC wallboards and secure display pairing | 82 (security and NOC widgets); earlier presets use existing data |
| 84 | Security connector framework and vendor integrations | 81, 82 |
| 85 | Operations Center, alert triage and correlation | 82, 84 |
| 86 | SOAR Lite — approval-driven security automation | 85; Rem0te contract additions for endpoint actions |
| 87 | Alert routing, on-call and escalation | 82, 85 |
| 88 | Service dependency and impact mapping | 82 |
| 89 | Security posture scorecards and customer service reviews | 82, 84, Phase 78 |
| 90 | AI Operations Analyst (OPTIONAL AI) | 85, Phase 56 gateway |

Each phase ships in release-sized slices with tests, a changelog entry and a roadmap annotation; vendor
connectors ship in batches as each one is verified.

## 10. Monitoring health: zero alerts is not healthy (added 2026-11-21)

Community feedback on Phase 82 (GitHub Discussion #161, Dijar Vrella) pointed out that a single "0 alerts"
counter cannot tell a quiet customer from a collector that could not read its source. Every NOC/SOC surface
follows the [Monitoring Health Standard 1.0.0](../standards/MONITORING_HEALTH_STANDARD.md):

- **One contract, no new framework.** `events/source_health.py` (pure, deterministic) decides health from a
  collection result; `events/source_health_store.py` writes it onto the existing
  `integrations.IntegrationSyncHealth` row of the connection (new contract fields, migration
  `integrations 0044`), sweeps freshness from `events_tick`, notifies and rolls up per customer.
- **Writers today:** `SecurityProvider.sync()` (all polled security connectors), `RMMSync`, backup
  `poll_connection()`. **Derived (no storage):** website monitors, webhook-only security connections and SIEM
  endpoints (push only: never "quiet"), the shared event pipeline (82.5).
- **Readers today:** Monitoring reliability page and JSON feed (`/security/events/sources/`, `sources.json`,
  `events_view`, customer-scoped), Security Overview alert card, Business Overview security and backup cards
  (`is_complete`), customer security digest (all-clear only when verified), AI incident summaries (context and
  output guard), system warnings.
- **Next readers:** wallboards (83.1 acceptance), connector SDK (84.1), on-call routing (87), posture scorecards
  (89.1), AI Operations Analyst (90.4), and reports from other products over Connect (82.13).
