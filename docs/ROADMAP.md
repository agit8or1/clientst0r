# Client St0r — Roadmap

> Living plan. Phases 1–7 + 9 + 10 + 11 + 31 (Vault Access Rules) complete. Update as phases complete.

## Phasing principle

Foundations first — engines that *enable* downstream features. Then revenue-relevant features. Then ITIL + ecosystem + polish. Each phase is self-contained, ships incrementally via the Apply flow, and unblocks the next.

---

## Phase 1 — Contract / agreement engine deepening **(M · foundation)** [complete]

Mature contract engine — beyond the basics. Required for accurate profitability reporting (Phase 3).

- Per-contract **overage rules** — different rate for billable hours past allowance *(1.1 — shipped v3.17.126)*
- **Role-based inclusion/exclusion** — e.g. "T1 work included, T3 work billable at $X" *(1.1 — shipped v3.17.126)*
- **Prepaid block hours with rollover** — % rollover, expiry dates *(1.1 — shipped v3.17.126)*
- **Auto-renewal** — N days before end_date, auto-create next period via `psa_auto_renew_contracts` cron *(1.2 — shipped v3.17.130)*
- **Proration** — mid-month start/cancel *(1.1 — shipped v3.17.126)*
- **Bundled services** — line items per agreement via `ContractBundleItem` model with dynamic editor *(1.2 — shipped v3.17.130)*
- Agreement **profitability snapshot** — revenue vs. cost-of-delivery this period, surfaced on contract detail page *(1.2 — shipped v3.17.130)*

## Phase 2 — Resource management foundation **(M · foundation)** [complete]

Required by capacity planning, profitability-by-tech, and scheduling improvements.

- `UserSkill`, `UserCertification` models
- `WorkingHours` (per user, per weekday + per-org override)
- `Holiday` / `LeaveRequest` (PTO booking with approval)
- `BillableTarget` (hours/week per tech, used for utilization KPI)
- **Capacity report** — forecast vs. scheduled vs. actual hours per week per tech
- **Skill matching** on the dispatch board — when assigning, surface techs ranked by skill+availability

## Phase 3 — Financial reporting + BI **(L · keystone)** [complete]

Most-requested feature class. Big surface, but builds entirely on Phase 1+2 foundations.

- Canonical reporting query layer (`reports/queries.py`) — single source of truth for revenue, hours, costs *(3.1 — shipped v3.17.139)*
- **Profitability by**: client *(3.1 — shipped v3.17.139)* / contract / project / tech *(3.2 — shipped v3.17.140)* / agreement / ticket-type / closure-category
- **Effective hourly rate** report (revenue ÷ billable hours) *(3.3 — shipped v3.17.141)*
- **Revenue-leakage report** (unbilled time ≥ N days old + expired blocks + un-pushed invoices) *(3.3 — shipped v3.17.141)*
- **SLA trend report** — breach rate per client, per priority, over time *(3.4 — shipped v3.17.143)*
- **Margin analytics** by service line *(3.4 — shipped v3.17.143)*
- **Custom dashboards** — drag-and-drop widgets sourced from the canonical query layer *(3.5 — shipped v3.17.142)*
- **Scheduled reports** — cron-style, email PDF/CSV *(3.6 wave B — shipped v3.17.147)*
- **Wallboard view** — TV-ready big-number display (active tickets, breaches, MTTR, queue depth) *(3.6 wave A — shipped v3.17.146; basic 6-tile fixed layout)*
- **Configurable wallboards with widgets** *(shipped v3.17.211)* — multiple named `Wallboard` rows per org via `reports.Wallboard` + `reports.WallboardWidget`, widgets sourced from the v3.17.142 `widget_sources.REGISTRY`, per-wallboard `refresh_seconds`, per-widget refresh override, "rotate through wallboards" mode at `/reports/wallboards/<pk>/rotate/` using meta-refresh redirects (no JS required — works on any TV browser). Drag-to-reorder UI deferred — admins set the `order` field via the admin interface for now
- **Executive scorecard** — single page rolling 30-day MSP KPIs *(3.6 wave A — shipped v3.17.146)*
- **Client-health score** — composite of SLA hits, ticket velocity, NPS proxy, billing aging *(3.6 wave B — shipped v3.17.147)*

## Phase 4 — Procurement workflow **(L)** **— shipped**

Builds on existing distributor integrations (Ingram/Pax8/Synnex). Adds the workflow above the catalog.

- `PurchaseRequisition` → approval → `PurchaseOrder` *(4.1 — shipped v3.17.148)*
- POs auto-numbered + branded PDF + email-to-vendor (mirror Quote/Invoice pattern) *(4.1 — shipped v3.17.148)*
- **Receiving** — partial receive, back-orders, serial-number capture into Asset records *(4.2 — shipped v3.17.149)*
- **Vendor relationship** model — lead times, payment terms, contact preferences *(4.3 — shipped v3.17.150)*
- **Stock minimums + auto-replenish** suggestion *(4.3 — shipped v3.17.150)*
- **Drop-ship handling** — direct-to-customer flag with shipping address override *(4.1 — shipped v3.17.148)*
- **Fulfillment tracking** — link POs to tickets/projects, status pipeline *(4.1 — shipped v3.17.148)*
- **One-click PO from accepted quote** — converts quote line items to a draft PO *(4.4 — shipped v3.17.151)*

## Phase 5 — CRM / sales pipeline **(L)** **— complete**

A mature PSA covers sales-pipeline-to-invoice. Currently we have quotes; we need everything *before* the quote.

- `Lead`, `Opportunity`, `Campaign`, `Commission` models *(5.1 — shipped v3.17.152; 5.2 — shipped v3.17.153)*
- Lead scoring + conversion funnel report *(5.2 — shipped v3.17.153)*
- Pipeline Kanban view (Discovery → Qualified → Proposal → Closed Won/Lost) *(5.1 — shipped v3.17.152)*
- **Quote-to-project automation** — one click on accepted quote spins a Project with tasks pre-populated from quote line items *(5.1 — opportunity → quote shipped v3.17.152; quote → project shipped v3.17.213)*
- **Configurable wallboards.** Multi-named per-org boards, widget grid sourced from the v3.17.142 widget registry, per-wallboard refresh + per-widget override, NOC-TV rotation mode *(shipped v3.17.211; Chart.js + nav + screenshots v3.17.212; drag-to-reorder widgets v3.17.215; global / cross-tenant overview boards v3.17.216; selectable category dropdown on widgets v3.17.217; categories on tickets/revenue/at-risk sources v3.17.218; in-form widget add/delete + starter templates v3.17.220; 9 new operations / monitoring widget sources + Monitoring template v3.17.224)*
- Sales-activity timeline per org/lead (calls, emails, meetings logged) *(5.3 — shipped v3.17.155)*
- Commission rules engine + per-tech commission report *(5.2 — shipped v3.17.153)*
- Lead capture from web form / IMAP / API *(5.3 — web + API shipped v3.17.155; IMAP poller stubbed, full implementation deferred to 5.4 follow-up)*

## Phase 6 — ITIL maturity **— complete**

Extends existing tickets + approvals; doesn't fork into a separate model layer.

- **Change requests** as a `Ticket.ticket_type='change'` extension with required CAB approval before status moves to "Implementing" *(6.1 — shipped v3.17.158)*
- **CAB workflow** — multi-approver gate (extends existing single-approval) *(6.1 — shipped v3.17.158)*
- **Problem records** — link N related tickets, root-cause analysis field, status pipeline *(6.2 — shipped v3.17.160)*
- **Release management** — group changes into release windows, freeze flags, rollback documentation *(6.3 — shipped v3.17.165)*
- **Service-catalog governance** — approval gate on catalog item changes *(6.3 — shipped v3.17.165)*
- MSP-named sample role templates seeded by `RoleTemplate.get_or_create_system_templates()`: Client, Client Admin, Technician, Tech Manager, Office Manager, Full Admin (in addition to the existing Owner/Administrator/Editor/Help Desk/IT Manager/Documentation Writer/Read-Only) *(shipped v3.17.164)*

## Phase 7 — Outsourcing, integrations, polish **(continuous track)** [complete]

Not a single phase — runs alongside 1-6.

- **Outsourcing**: subcontractor org type, share-ticket-to-partner endpoint with HMAC, two-way sync of comments + status, optional billing markup *(shipped v3.17.166)*
- **Integration SDK**: clean provider plugin interface *(skeleton shipped v3.17.166)*; then steady drops — Datto Backup, ITGlue v2 import, Hudu sync, BackupRadar, ScreenConnect, Acronis, Liongard. Target: 5-10 new providers per quarter.
- **Polish backlog** — test coverage gaps, permission edge cases, audit improvements, mobile UI fixes, onboarding docs, import-tool maturity, API stability, third-party trust signals *(continuous track)*
  - Tenant-isolation security-test suite restored from rotted state; latent `/api/passwords/<id>/` audit-log crash fixed *(shipped v3.17.171)*
  - Removed deprecated `datetime.utcnow()` / `datetime.now()` from core views; bug-report timestamp no longer mislabels server-local time as UTC *(shipped v3.17.173)*
  - Codebase-wide sweep of deprecated datetime calls; fixes tz-naive query bug in audit-log cleanup + expired-session cleanup on non-UTC servers *(shipped v3.17.174)*
  - Auto-apply-gunicorn-fix migration silenced on test runners + fresh dev installs (no longer spams "Fix script exited with code 1" banners) *(shipped v3.17.175)*
  - Defender adapter flagged as a reference stub in label + test-connection message + module docstring so operators don't pick it expecting live alert flow *(shipped v3.17.179)*
  - Silent `except Exception: pass` swallowers in `core/views.py` audit-log fallback + `core/security_views.py` scan handler tightened to log real exceptions; package-scanner JSON endpoints use a `_staff_or_superuser_api` decorator instead of inline checks *(shipped v3.17.180)*
  - Vault password mutation audit logging — `password_edit` + `password_delete` now write per-action AuditLog rows on success and on every failure mode (form validation, EncryptionError); 2 new tests in `vault.tests.PasswordMutationAuditTests` *(shipped v3.17.181)*
  - Phase 9 forms (Auto-Ticket Rule + Vendor Connection) rewritten with proper card-section layout, Bootstrap widget classes, copy-to-clipboard webhook helpers, "ALL must match" semantic hint on rule clauses *(shipped v3.17.182)*
  - UniFi + M365 connection forms rewritten with the same card-section layout (the only other forms using the sloppy generic field-loop pattern; audit confirmed the rest of the integration forms were already clean) *(shipped v3.17.183)*
  - Bare `except:` clauses replaced with `except Exception:` across 24 sites in 12 modules — no more accidental `SystemExit`/`KeyboardInterrupt` swallowing *(shipped v3.17.184)*
  - `core/security_views.py` inline staff-check sweep finished — all 9 endpoints now use `@_staff_or_superuser_view` (HTML) or `@_staff_or_superuser_api` (JSON) decorators; latent silent `except Exception` in `run_python_scan` also logged *(shipped v3.17.185)*
  - Documentation refresh: 8 new screenshots for Phase 9 + integration forms + the roadmap page; README updated with annotated captions; screenshot script extended with the new pages *(shipped v3.17.186)*
  - Baseline test coverage for `imports/` app — 34 tests across org-matcher fuzzy logic, ImportJob lifecycle, rollback flow (matched orgs preserved, created orgs deleted), unique-together constraints on mapping models, CSV preview helper *(shipped v3.17.187)*

  ➡ **Wave 1 closed (v3.17.171 → v3.17.187)** — every item from the original Phase 7 polish survey has been delivered or explicitly deferred (reCAPTCHA needs Google credentials; scheduler email-send is a feature gap not polish; welcome-email on member-add *was* a feature gap, **shipped v3.17.214**). Phase 7 stays `[in progress]` by design (continuous track) — the next wave will be triggered by user-reported issues + the next bug-bash audit.

  ### Wave 2 — going-from-zero baselines (v3.17.192 → ongoing)

  The audit punch-list flagged 16 apps with no test coverage. Wave 2 is a sustained pass through them. Each app gets baseline tests (model behavior, view tenant-isolation, key happy-path flows) — not feature-complete, but enough to surface latent crashes and lock down the contract going forward.

  **The pattern is paying off.** Three of the first six baselines surfaced real production bugs that had been latent for months — usually a wrong kwarg name, a stale field reference, or a `hasattr` check that doesn't catch `None`. Bugs caught:

  - `psa/tests.py` (5,465 lines / 220+ cases) split into 5 topical shards under `psa/tests/` so CI can run them under the 540s timeout. 271 tests across 5 shards, max shard 147s *(shipped v3.17.192)*
  - **`api/` baseline (11 tests across 6 classes)** — caught two real bugs: `AssetViewSet.filterset_fields` and `AssetSerializer.Meta.fields` both referenced `is_active` and `location` columns that don't exist on the Asset model. Every `/api/assets/` list and detail request 500'd. Fixed in same release *(shipped v3.17.193)*
  - **`audit/` baseline (30 tests across 7 classes)** — caught `AuditLoggingMiddleware._is_update()` crashing on POST to unresolved URLs (`hasattr(req, 'resolver_match')` returns True for None values; `None.kwargs` then raised `AttributeError`). Fixed in same release *(shipped v3.17.195)*
  - `assets/` baseline (16 tests across 6 classes) — model behavior, OrganizationManager filtering, view tenant-isolation, EquipmentModel back-reference. No production bugs surfaced *(shipped v3.17.196)*
  - `monitoring/` baseline (22 tests across 5 classes) — WebsiteMonitor + Expiration property logic, IPAM `(subnet, ip_address)` unique-together dedupe contract, `for_organization()` filtering. No production bugs surfaced *(shipped v3.17.197)*
  - `processes/` baseline (19 tests across 4 classes) — workflow engine slug auto-gen, ProcessExecution lifecycle, completion-percentage math (incl. zero-stages safety), `(execution, stage)` unique-together. No production bugs surfaced *(shipped v3.17.199)*
  - `files/` baseline (9 tests across 2 classes) — `attachment_upload_path()` enforces per-org / per-entity directory structure with UUID filenames (filesystem tenant-isolation contract). No production bugs surfaced *(shipped v3.17.200)*
  - `scheduling/` baseline (20 tests across 5 classes) — recurrence math for every cadence, `check_completion` any-of vs all-of sign-off, `spawn_next_occurrence` clones assignments + tags. No production bugs surfaced *(shipped v3.17.201)*
  - `locations/` baseline (20 tests across 3 classes) — HQ-uniqueness invariant, shared-location ACL, `full_address` formatting, WAN bandwidth display. No production bugs surfaced *(shipped v3.17.202)*
  - `docs/` baseline (13 tests across 5 classes) — Document slug auto-gen, version-snapshot lifecycle (no row on first save, increments on edit), Diagram slug, `is_global` cross-tenant KB. No production bugs surfaced *(shipped v3.17.203)*
  - `inventory/` baseline (15 tests across 5 classes) — InventoryItem QR-code auto-gen, low-stock boundary, total_value math, transaction signed-quantity formatting. No production bugs surfaced *(shipped v3.17.204)*
  - `vehicles/` baseline (18 tests across 3 classes) — ServiceVehicle expiry warnings, `has_location` flag, `update_location()` setter, fleet inventory low-stock + needs-restock + total-value. No production bugs surfaced *(shipped v3.17.205)*

  ➡ **Wave 2 closed (v3.17.192 → v3.17.205)** — every one of the 16 originally-untested apps now has baseline coverage. **Final ratio: 3 of 11 baseline efforts surfaced real production bugs that had been latent for months** (api/, audit/, the v3.17.171 tenant-isolation rebuild before the wave formally started). All bugs caught were stale-attribute / wrong-kwarg / hasattr-vs-None patterns — the same family the next wave should look for first.

  Wave 2 totals: ~280 new tests across 11 modules in 14 commits. Combined with the v3.17.192 psa-tests shard split, the project's test runtime now fits comfortably under any reasonable CI ceiling: each shard ≤ 147s, smaller apps ≤ 7s.

  ✅ **Phase 7 marked complete at v3.17.207.** All three pillars have shipped: outsourcing (v3.17.166), Integration SDK skeleton (v3.17.166) + first reference adapter (v3.17.168), and the polish-backlog test-coverage push (Waves 1 + 2). Ongoing polish continues as routine maintenance — bug fixes, deprecation sweeps, new vendor adapters in the SDK — but it's no longer tracked as an active phase. Future polish lands as standalone releases under whatever phase the change applies to (e.g. a vault-side improvement = Phase 31 polish).

## Phase 9 — Security alert ingestion: EDR / AV / Firewall on the dashboard **(M)** [shipped — v3.17.168]

MSPs run a stack of security tools that all alert independently — SentinelOne, CrowdStrike, Defender, Sophos, Bitdefender, Webroot, Fortinet, Palo Alto, Sonicwall, etc. The PSA dashboard should aggregate alerts from all of them, surface critical issues per client, and let techs triage from one screen.

### Sub-phase 9.1 — Connection framework *(shipped v3.17.168)*

- Generic `SecurityVendorConnection` model: provider type (edr/av/firewall), org-scoped credentials (encrypted), poll interval, last_sync_at, last_error
- Provider type enums covering EDR (CrowdStrike Falcon, SentinelOne Singularity, Microsoft Defender for Endpoint, Sophos Central, Huntress, ThreatLocker), AV (Bitdefender GravityZone, Webroot, Malwarebytes, ESET), Firewall (Fortinet FortiGate, Palo Alto, Sonicwall, Cisco Meraki MX, Sophos XG, pfSense)
- Two-way mapping: each connection optionally pinned to a client `Organization` (multi-tenant alert routing)
- Reuses existing integration patterns (status pill from v3.17.135)

### Sub-phase 9.2 — Alert model + poller *(shipped v3.17.168)*

- `SecurityAlert` model: connection FK, external_id (dedupe key), severity (info/low/medium/high/critical), title, description, asset hint, raw_payload (JSON), seen_at, acknowledged_by, acknowledged_at, status (new/acknowledged/dismissed/resolved), auto_ticket FK (optional)
- Per-vendor poller adapters returning normalized alert dicts; one mgmt cmd `poll_security_alerts` runs every 5 min via cron
- Idempotent dedupe by (connection_id, external_id)
- Alert webhook receiver endpoint `/security/webhook/<token>/` for vendors that push (HMAC-verified)

### Sub-phase 9.3 — Dashboard + auto-ticketing *(shipped v3.17.168)*

- New "Security alerts" card on the global dashboard + per-org dashboard: count by severity in the last 24h, drill-down to filtered list, color-coded
- New page `/security/alerts/` — full triage UI; filter by severity / vendor / client / status
- Per-vendor or per-severity rule: auto-create a PSA ticket from an alert (priority mapped from severity, queue configurable, assignee from a default rule). Mirrors workflow rules engine (v3.17.111).
- Bulk "ack / dismiss / convert to ticket" actions

### Sub-phase 9.4 — Reporting *(shipped v3.17.168)*

- "Mean time to acknowledge" metric per client / per vendor
- Suppression rules (don't auto-ticket from this vendor between 22:00–06:00 etc.)
- Weekly digest email to client of unresolved alerts (opt-in) *(deferred — pending email subscription mgmt; framework + MTTA shipped)*

**Sizing:** **M** — 9.1+9.2 = 2 weeks (one reference adapter + the framework), 9.3 = 2 weeks, 9.4 = 1 week. Each new vendor adapter beyond the first is ~2-4 days. Ship the framework + 1-2 reference adapters first, then add vendors as customer demand arrives.

**Dependencies:** none. Can run alongside Phase 2 / 3 / 8.

---

# Long-term roadmap — Phases 10-23

The following are **planned / in-progress** items focused on MSP workflow consolidation and operational visibility. None are positioned as fully implemented. Items overlapping with already-shipped phases are noted as "Extends X" so the deltas are explicit. AI-assisted features are clearly marked **OPTIONAL AI**.

## Phase 10 — Advanced Email-to-Ticket Engine **(M)** [complete]

**Roadmap item:** Advanced Email Processing & Ticket Intelligence. Extends the basic IMAP poller already shipped (v3.17.83+).

Planned capabilities:
- Advanced inbound email parsing (HTML + plain-text fallback) *(10.2 — shipped v3.17.177)*
- Thread reconstruction across replies + forwards *(10.1 — shipped v3.17.176)*
- Reply correlation by Message-ID + In-Reply-To headers (more reliable than current subject-regex match) *(10.1 — shipped v3.17.176)*
- Signature stripping *(10.2 — shipped v3.17.177)*
- Loop detection (ignore auto-responders) *(10.3 — shipped v3.17.188)*
- Spam scoring before ticket creation *(10.3 — shipped v3.17.188)*
- Attachment extraction with MIME-type allowlist *(10.2 — shipped v3.17.177)*
- Automatic contact association (match sender email → existing contact / membership) *(planned — Phase 10.3.1)*
- Per-client parsing rules *(10.3 — shipped v3.17.188 via EmailRoutingRule)*
- Ticket categorization (rule-based) *(10.3 — shipped v3.17.188 via routing rule queue/priority overrides)*
- Ticket tagging
- Email security validation (SPF / DKIM / DMARC inspection) *(10.3 — shipped v3.17.188; opt-in via enforce_dmarc)*
- Outbound threading + per-ticket conversation panel *(10.4 — shipped v3.17.189)*
- Microsoft 365 mailbox source via Graph API (alternative to IMAP for tenants that can't enable IMAP) *(10.5 — shipped v3.17.506 — `EmailIngestionConfig.source='graph'` reuses an existing M365 connection's app registration (needs `Mail.Read`); the poller fetches each unread message's MIME via Graph and runs the identical threading/quarantine/attachment pipeline, then marks it read — issue #142)*
- Microsoft 365 **outbound** via Graph (optional transport; SMTP remains default) *(10.6 — shipped v3.17.507 — `EmailIngestionConfig.outbound_method='graph'` sends staff replies via Graph `sendMail`/`reply`/`replyAll` on the same mailbox (needs `Mail.Send`, scoped via Exchange Online RBAC for Applications). Durable `EmailOutboundJob` with idempotent claim-lock, 202-accepted tracking, Retry-After-aware retries for 429/5xx, fail-fast on auth/validation, and an 'uncertain' state for post-submit timeouts (never auto-resent). Immutable Graph message ids stored on inbound so replies preserve the M365 conversation. Readiness check + labeled test-send in the mailbox form — issue #142)*
- Reply-to-requester from the ticket form *(10.7 — shipped v3.17.508 — an opt-in "Email this reply to …" checkbox on the ticket reply box sends the comment to the requester through whichever transport the originating mailbox is configured for (SMTP or Graph), closing the round trip so outbound replies are captured in the conversation panel and, on Graph, in the mailbox's Sent Items. Off by default; internal notes are never emailed; a send failure reports but never discards the saved comment — issue #142)*
- Ticket summarization (**OPTIONAL AI**)
- Intent detection (**OPTIONAL AI**)

### Sub-phase 10.1 — Threading + Message-ID correlation *(shipped v3.17.176)*

- New `EmailMessage` model captures every inbound (and later, outbound) email's Message-ID, In-Reply-To, References, headers, and bodies. Unique per `(organization, message_id)` so cross-tenant Message-ID collisions never thread incorrectly.
- New `Ticket.last_inbound_message_id` cache feeds outbound threading in 10.4.
- Poller correlation order is now: (a) In-Reply-To against `EmailMessage.message_id` in the same org, (b) walk the References chain right-to-left, (c) subject-regex fallback (legacy tickets keep working), (d) create new ticket. Whichever path matches, the inbound message is persisted as an `EmailMessage` row so the next reply has something to chain against.
- Tests cover header-threading, References-chain walking, subject-regex fallback for legacy replies, cross-org isolation, and new-ticket creation.

### Sub-phase 10.2 — Body cleanup + attachment ingestion *(shipped v3.17.177)*

- New `psa/email_parsing.py` helper module: `sanitize_html` (bleach with tight allowlist; strips scripts, styles, iframes, inline event handlers, remote images / tracking pixels; rewrites links with `rel="noopener noreferrer" target="_blank"`), `strip_signature` (RFC 3676 `\n-- \n` sentinel + mobile/marketing prefaces), `strip_quoted_reply` (Apple/Gmail "On … wrote:", Outlook `-----Original Message-----` / From-Sent-To-Subject block, trailing `>`-prefix block).
- Reply comments to existing tickets get sig + quoted history stripped so only the new content shows. Full original body still preserved on `EmailMessage.body_text` for the Phase 10.4 conversation panel. New tickets keep the full body so context isn't lost.
- Attachment ingestion via `_ingest_attachments`: walks parts for `Content-Disposition: attachment`, validates against `PSA_EMAIL_ATTACHMENT_MIME_ALLOWLIST` (default: images, PDF, text, Office, ZIP) + `PSA_EMAIL_ATTACHMENT_MAX_BYTES` (default 25 MB), writes accepted files as `TicketAttachment` rows linked to the new comment. Rejected files logged at WARNING level. Filenames sanitized.
- Inbound HTML bodies are sanitized at write time before landing on `EmailMessage.body_html`.

### Sub-phase 10.3 — Routing rules + auto-responder & spam gating *(shipped v3.17.188)*

- New `EmailRoutingRule` model with sender-domain glob matching (exact `acme.com`, subdomain `*.acme.com`, full-email `noreply@acme.com`); MSP's generic `help@msp.com` mailbox now fans inbound mail to the right client tenant + queue + priority. First match wins, ordered by `order` (lower fires first).
- Auto-responder detection via `detect_auto_responder()` — `Auto-Submitted`, `X-Autoreply`, `Precedence: bulk/list/junk`, NDR `multipart/report`, plus subject heuristics for "Out of Office" / "Vacation Auto-Reply" / "Undeliverable".
- DMARC verdict gate — opt-in per-config (`enforce_dmarc`); reads upstream MTA's `Authentication-Results` header; no inline crypto / DNS.
- Spam-keyword scorer — opt-in per-config (`spam_keyword_threshold > 0`); conservative pattern list (claim-your-prize, congratulations-winner, nigerian-prince, etc.).
- Quarantined inbound persists with `was_quarantined=True` + reason but NEVER creates a ticket; admins triage via Django admin.
- 16 new tests across 6 classes covering all four gates plus routing rule end-to-end.

### Sub-phase 10.4 — Outbound threading + conversation panel *(shipped v3.17.189)*

- New `psa/email_outbound.py::send_threaded_reply()` helper — generates Message-ID, sets `In-Reply-To` + `References` from `Ticket.last_inbound_message_id`, sends via Django email backend with optional HTML alternative, persists `EmailMessage(direction='out')` row so future replies thread back via 10.1's `_thread_target` (closing the round-trip).
- New per-ticket conversation view at `/psa/t/<ticket_number>/conversation/` — chronological inbound + outbound rows, HTML bodies rendered in `<iframe sandbox="">` (most-restrictive sandbox), quarantined-inbound shown with reason banner, raw headers/body collapse into `<details>`.
- 9 new tests covering threading headers, round-trip closure, HTML alternative, missing recipients, conversation view ACL.

**Goal:** Reduce dispatcher and technician overhead while improving ticket workflow accuracy.

## Phase 11 — Advanced Dispatch & Technician Scheduling **(M)** [complete]

**Roadmap item:** Dispatch Optimization & Technician Coordination. Extends Phase 2 (resourcing) + the dispatch board (v3.17.112) + skill ranking (v3.17.138).

Planned capabilities:
- Drag/drop dispatch board *(shipped — v3.17.112)*
- Technician scheduling *(partial — Phase 2 WorkingHours shipped)*
- Shift management
- PTO conflict awareness *(11.2 — shipped v3.17.208; extends Phase 2.2 LeaveRequest)*
- Calendar conflict detection *(11.2 — shipped v3.17.208)*
- Recurring onsite scheduling *(deferred — handled by `scheduling.ScheduledTask` recurrence; not a separate dispatch surface)*
- Dispatch prioritization (auto-rank queue by SLA + priority) *(11.1 — shipped v3.17.194)*
- SLA-aware dispatching — SLA-burn panel for tickets due ≤ 4h *(11.1 — shipped v3.17.194)*
- Technician utilization metrics *(shipped — Phase 2.3 capacity report)*
- Geo-aware technician routing *(deferred — needs GPS data on User + Ticket which Phase 8 mobile timeclock will provide; revisit then)*
- Travel time estimation *(deferred — pending Phase 8 GPS data)*
- Dispatch heatmaps *(11.3 — shipped v3.17.209)*
- **Home-dashboard Schedule + Tasks panels** — the main dashboard now leads with a 7-day agenda (scheduled tasks + ticket resolution deadlines, grouped by day, empty days omitted) and an open-work Tasks list ordered most-urgent-first with undated items last. Expiring passwords, tracked expirations and SSL certificates are folded into Tasks rather than sitting in their own panel — an expiry is something somebody has to act on. Replaces the "My Recent", "Recent Activity" and "Expiring Soon" panels, which showed what had already happened. Same shapes as the mobile agenda (v3.17.478), so both surfaces agree on what "upcoming" means *(shipped v3.17.524)*

### Sub-phase 11.1 — Dispatch prioritization + SLA-burn panel *(shipped v3.17.194)*

- New `_dispatch_priority_key(ticket)` returns `(priority.sort_order, no_due_flag, due)` — every lane on the dispatch board (overdue, SLA-burn, unassigned-by-day, assigned-tech cells) now sorts most-urgent first.
- New "SLA at risk" panel above the grid: open tickets due in the next 4 hours but not yet overdue, surfaced with a yellow fire icon. Already-overdue stays in the existing red panel — no duplication. Closed tickets excluded.
- 9 new tests across 3 classes covering sort-key contract, panel filtering, and end-to-end lane ordering.

### Sub-phase 11.2 — PTO + calendar conflict awareness *(shipped v3.17.208)*

- New `_dispatch_conflicts(tech, ticket)` helper returns advisory warnings: **PTO conflict** (approved `resourcing.LeaveRequest` covering the ticket's due date) + **calendar overlap** (another open ticket assigned to the same tech with a due date inside a ±2-hour window).
- `/psa/dispatch/assign/` JSON response now carries a `conflict_warnings` array. Advisory, not blocking — dispatchers made an explicit decision; the warning surfaces as a chip for review. AuditLog includes the conflict list so post-hoc trails capture "they assigned despite the warning".
- 9 new tests across 2 classes covering pure-function conflict detection + end-to-end JSON response shape.

### Sub-phase 11.3 — Dispatch heatmap *(shipped v3.17.209)*

- New `/psa/dispatch/heatmap/` — per-tech, per-day open-ticket load over a ±7-day window (15 columns), rendered as a color-intensity grid so dispatchers see lopsided assignments at a glance.
- 5-step intensity scale (0..4) bucketized against the busiest cell in the visible window; today's column has a blue inset border.
- Counts open assigned tickets with due dates in window; tenant-isolated.
- Geo-aware routing + travel-time estimation **deferred** — they need GPS data the Phase 8 mobile timeclock will collect; revisit then.
- 8 new tests in `DispatchHeatmapTests` covering the view, window calculation, what's counted vs filtered, max-count math, and tenant isolation.

✅ **Phase 11 marked complete at v3.17.210.** All three planned sub-phases shipped (11.1 dispatch prioritization + SLA-burn, 11.2 PTO + calendar conflict awareness, 11.3 heatmap). 27 dispatch tests across the three sub-phases. Two listed capabilities — geo-aware technician routing and travel time estimation — were deferred to Phase 8 because they depend on GPS data the mobile timeclock will collect; revisit them in that phase rather than blocking Phase 11 closure on infrastructure that doesn't exist yet.

**Goal:** Improve technician coordination and service workflow efficiency.

## Phase 12 — Customer Communication Workflows **(M)** [complete]

**Roadmap item:** Enhanced Client Communication & Portal Workflows. Extends the existing customer portal.

Planned capabilities:
- Customer satisfaction (CSAT) surveys post-ticket-close *(shipped v3.17.231 — token-based 1-5 star rating + optional comment, gated by `psa_csat_enabled` SystemSetting flag)*
- Branded client portals *(extends Phase v3.17.112 per-org branding)* *(shipped v3.17.233 — `Organization.portal_primary_color` consumed by portal `base.html` overriding `--bs-primary` + button/link CSS)*
- Portal announcements *(shipped v3.17.232 — per-org banners on the portal home with severity, expiry, dismissable flag + per-session dismissal endpoint; managed via Django admin in v1)*
- Customer approval workflows *(shipped v3.17.239 — `PSAApproval.is_client_approval` flag + `/portal/approvals/` list + decide endpoint; staff route an approval to the client side and the portal user can Approve / Deny with an optional comment)*
- Threaded customer communication *(shipped v3.17.237 — `TicketComment.parent_comment` self-FK + portal "Reply to this comment" button + indented thread render)*
- SMS ticket communication (using existing SMS provider plumbing) *(shipped v3.17.238 — opt-in `portal_notify_sms_status_change` flag + `notify_portal_status_change` helper hooked into the status-change signal; phone field on portal preferences page)*
- Customer escalation workflows *(shipped v3.17.236 — `Ticket.escalated_at/by/reason` fields + portal endpoint that stamps fields and creates a `[Escalated by client]` public comment)*
- Customer-facing knowledge base *(`Document.is_client_visible` shipped earlier; portal KB search shipped; featured + view counts shipped v3.17.234)*
- Customer ticket voting / prioritization *(shipped v3.17.235 — `psa.TicketVote` model + portal toggle endpoint + thumbs-up button on ticket detail)*
- Secure customer messaging *(deferred — would need an encrypted message-thread model + key management distinct from the existing AES-GCM vault; substantial scope and lower priority than other planned phases. Re-evaluated when there's customer demand)*
- Customer notification preferences *(shipped v3.17.233 — three opt-in/out switches at `/portal/preferences/` for ticket replies, status changes, CSAT survey invitations; CSAT helper now honors the flag)*

**Goal:** Improve client interaction visibility and communication consistency.

## Phase 13 — Procurement & Lifecycle Management **(M)** [shipped — v3.17.272]

**Roadmap item:** Advanced Procurement & Asset Lifecycle Management. Extends Phase 4 (Procurement) + the asset lifespan tracking already shipped.

Planned capabilities:
- Serial lifecycle tracking *(partial — serial capture shipped v3.17.149)*
- Warranty expiration tracking *(shipped v3.17.254 — `assets_warranty_alerts` management command emails per-org digests with 7-day per-asset cooldown; configurable warning window via `--days N`)*
- Vendor inventory checks (live stock from distributor APIs) *(shipped v3.17.272 — `/integrations/distributors/stock-check/` fans out `?sku=` to every active DistributorConnection's `check_stock()` + `get_pricing()` so a buyer can compare live qty + unit price across Ingram / Pax8 / SYNNEX in one shot)*
- Procurement approval workflows *(shipped — Phase 4.1 PR/PO)*
- Purchase receiving workflows *(shipped — Phase 4.2)*
- Margin analytics on resold hardware *(shipped v3.17.271 — `/reports/hardware-margin/` joins POs and Invoices by `source_quote_id` to compute resale margin = revenue − cost; per-quote rows + blended summary; CSV export; staff-only)*
- RMA tracking (return / replace lifecycle) *(shipped v3.17.261 — `RMAReturn` model with explicit state machine: open → sent → received_by_vendor → replaced/refunded/closed; views at `/assets/rma/`; tenant-scoped)*
- Asset lifecycle scoring (composite age × usage × warranty) *(shipped v3.17.263 — `Asset.lifecycle_score()` returns 0-100 breakdown {age, warranty, firmware}; report at `/reports/asset-lifecycle/` with `?threshold=` filter and CSV export)*
- Procurement forecasting from historical PR/PO data *(shipped v3.17.268 — `/reports/procurement-forecasting/` projects per-vendor spend over the next 3 months using a 3-month moving average over the last 12 months of committed POs; CSV export; staff-only)*
- Recurring purchasing templates *(shipped v3.17.266 — `RecurringPurchaseTemplate` with JSON line snapshot + recurrence (weekly/biweekly/monthly/quarterly/yearly); `spawn_pr()` creates a draft PR; daily `psa_run_recurring_purchases` cron with catch-up cap)*
- Vendor cost history (price-at-time-of-PO trend) *(shipped v3.17.262 — `/reports/vendor-cost-history/` aggregates POLine items over last 730 days per `(vendor, sku, description)` with min/avg/max/last unit price; CSV export; staff-only)*
- Procurement reporting *(shipped v3.17.258 — `/reports/procurement-summary/` per-vendor + per-month spend over last 365 days; CSV export; staff-only)*

**Goal:** Improve operational procurement visibility and hardware lifecycle management.
- Spreadsheet import for Shop + VAN inventory *(shipped v3.17.523 — the CSV import pipeline now reads .xlsx as well as .csv, and gains `shop_inventory` / `vehicle_inventory` targets so stock levels can be loaded from a spreadsheet with the existing column-mapping, preview and rollback machinery. Vehicles match on name, licence plate or VIN; an unmatched van skips the row with a log line naming the value, rather than failing the batch. Legacy .xls is refused with a re-save instruction instead of a silent half-parse)*

## Phase 14 — Visual Workflow Automation Engine **(L)** [shipped — v3.17.290]

**Roadmap item:** Visual Workflow & Operational Automation Engine. Extends the workflow rules engine (v3.17.111) + visual rule builder (v3.17.112).

Planned capabilities:
- Visual workflow builder *(partial — visual rule builder shipped v3.17.112)*
- Conditional workflow routing (branching based on ticket fields) *(shipped v3.17.285 — `WorkflowRule.else_actions` JSONField runs when `conditions` evaluate false; engine picks branch and counts both as fires)*
- SLA-driven automation *(shipped v3.17.286 — `sla_threshold_crossed` trigger + `sla_pct_at_least` condition + `WorkflowRule.fire_once_per_ticket` guard via `WorkflowRuleFiring` join table; `psa_sla_workflow_tick` cron evaluates open tickets every 5 min)*
- Ticket orchestration (multi-step automated sequences) *(shipped v3.17.285 — new `fire_rule` action type chains by name within the same org / MSP-wide scope; sub-rule's else_actions also honored)*
- Approval chains (extends Phase 6.1 CAB pattern)
- Trigger / action workflows
- Escalation logic (auto-escalate after N hours unanswered)
- Scheduled automations
- State-based workflows *(shipped — already covered by `status_changed` trigger + `status` condition; v3.17.289 confirmation)*
- Dynamic technician assignment (round-robin, skill-match, load-balanced) *(shipped v3.17.287 — 3 new action types: `assign_round_robin` (oldest-assigned wins), `assign_skill_match` (Django Group lookup, load-tiebreak), `assign_load_balanced` (lowest open-ticket count); all skip inactive users)*
- Workflow templates *(shipped v3.17.288 — `WorkflowRuleTemplate` model + `instantiate(organization, name_override)` clone method; UI at `/psa/rules/templates/` with per-template "Use Template" button)*
- Cross-module workflow integration (PSA ↔ procurement ↔ CRM) *(shipped v3.17.289 — `create_charge` action type lets workflow rules add billing rows; future actions for procurement/CRM cross-module land as the need arises)*
- AI-assisted workflow suggestions (**OPTIONAL AI**) *(shipped v3.17.290 — `WorkflowSuggestion` model + `psa_generate_workflow_suggestions` heuristic command (LLM-swap-in later) gated by `psa_ai_enabled`; review/accept/dismiss UI at `/psa/rules/suggestions/`)*

**Goal:** Reduce repetitive operational tasks while improving workflow consistency.

## Phase 15 — Recurring Billing & Contract Management **(M)** [shipped — v3.17.299]

**Roadmap item:** Recurring Billing & Financial Workflow Automation. Extends Phase 1 (contract engine) + invoicing.

Planned capabilities:
- Recurring invoices (auto-generated from contract bundles) *(shipped v3.17.291 — `Contract.billing_frequency` (monthly/quarterly/yearly) + `next_billing_date` + `recurring_amount`; `Contract.generate_invoice()` method; daily `psa_generate_recurring_invoices` cron with catch-up cap + dry-run)*
- Usage-based billing (per-seat / per-device / per-GB metered) *(shipped v3.17.292 — `ContractMeter` model with unit/unit_price/current_quantity + atomic `increment()` helper; `Contract.generate_invoice()` adds one line item per active meter alongside the base recurring amount; meter resets to 0 after billing)*
- Contract renewals *(shipped v3.17.299 — Phase 1.2 auto-renewal cron + Phase 15 v13 pause/resume/cancel-at-period-end complete the lifecycle picture)*
- Proration handling *(shipped v3.17.293 — `Contract._proration_factor()` method computes days-active fraction; `generate_invoice()` applies it to the base amount only (usage line items not prorated); description suffix shows the proration % to the customer)*
- Service bundles *(shipped — Phase 1.2 ContractBundleItem)*
- Billing reconciliation *(shipped v3.17.295 — `/reports/billing-reconciliation/` per-client invoiced-vs-paid over `?days=N` window with collection % coloring; CSV export; tenant-scoped)*
- Late fee automation *(shipped v3.17.294 — `SystemSetting.late_fee_pct` + `late_fee_min_days_overdue`; daily `psa_apply_late_fees` cron creates a `Charge` row for each overdue invoice; idempotent)*
- ACH / payment integrations (Stripe ACH, GoCardless, etc.) *(shipped v3.17.296 — `PaymentConnection` model + `BasePaymentProvider` interface + Stripe & GoCardless adapter stubs; live `charge()` implementation lands when an MSP connects a real account)*
- MRR forecasting *(shipped v3.17.295 — `/reports/mrr-forecast/` reads active recurring contracts; normalizes monthly/quarterly/yearly to monthly equivalents; per-contract table + 12-month projection; staff-only)*
- Contract profitability tracking *(shipped v3.17.299 — Phase 3 profitability-by-contract analytics + Phase 15 v9 MRR forecasting cover both revenue and cost sides)*
- Invoice automation *(shipped v3.17.299 — `SystemSetting.psa_auto_push_recurring_invoices` toggles auto-push of recurring-cron-generated invoices to the configured `AccountingConnection`; failures captured for review on the existing accounting reconciliation report)*
- Tax handling support (Avalara / TaxJar integrations) *(shipped v3.17.297 — `TaxConnection` model + `BaseTaxProvider` interface + Avalara & TaxJar adapter stubs; live `compute_tax()` lands when an MSP connects a real account)*
- Subscription lifecycle management *(shipped v3.17.298 — `Contract.paused_at` / `paused_until` / `cancel_at_period_end` fields + `pause()` / `resume()` / `cancel_at_end_of_period()` methods; daily `psa_advance_subscription_lifecycle` cron auto-resumes + cancels)*

**Goal:** Improve recurring service management and operational billing visibility.

## Phase 16 — Documentation Relationship Mapping **(M)** [shipped — v3.17.303]

**Roadmap item:** Infrastructure Relationship Mapping & Dependency Visualization.

Planned capabilities:
- Asset relationship mapping (parent / child / depends-on) *(shipped — `assets.Relationship` model with parent/child/depends/related/documents choices; v3.17.300 confirmation)*
- Visual dependency graphs (DAG renders) *(shipped — `relationship_map` view emits nodes + edges; v3.17.300 confirmation)*
- Topology visualization *(shipped v3.17.303 — `/assets/relationships/topology.json` returns full org graph as nodes + edges; consumable by Cytoscape / vis-network / D3)*
- Nested organization mapping (extends Phase 17 multi-location) *(shipped — Phase 18 v1, v3.17.240)*
- Shared infrastructure relationships *(shipped — Phase 18 v3, v3.17.252 — `Asset.is_shared_with_descendants` + `visible_to_org()`)*
- Automatic asset linking (heuristic — same subnet, same rack, etc.) *(shipped v3.17.301 — `assets_auto_link` management command buckets by /24 subnet; creates pairwise `related` among peers + `depends` toward a single gateway when one is detected; idempotent; `--dry-run` + `--organization=<slug>` flags)*
- Infrastructure dependency chains *(shipped v3.17.300 — `Asset.dependency_chain(direction='downstream'|'upstream', max_depth=10)` BFS walker; cycle-safe)*
- Rack relationship visualization *(shipped v3.17.303 — racks already shipped; topology JSON includes rack-type assets and their relationships)*
- Service relationship tracking ("Email service depends on Exchange Online + DNS X + Connector Y") *(shipped v3.17.302 — `assets.Service` model with status (operational/degraded/down/maintenance) + criticality + owner; `set_status()` stamps last_status_change; `asset_dependencies()` walks `Relationship(source_type='service')` rows)*
- Documentation inheritance (child sites inherit parent SOPs) *(shipped — `OrganizationManager.for_organization()` walks the parent chain so child orgs see parent KB articles / docs / contacts; v3.17.303 confirmation)*

**Goal:** Improve infrastructure visibility and operational context awareness.

## Phase 17 — Advanced Asset Intelligence **(L)** [shipped — v3.17.310]

**Roadmap item:** Asset Intelligence & Infrastructure Visibility.

Planned capabilities:
- Asset drift detection (compare current state vs. last-known baseline) *(shipped v3.17.304 — `Asset.detect_drift()` field-by-field comparison vs. latest `AssetBaseline`; returns list of `{field, baseline, current}` dicts)*
- Baseline comparison *(shipped v3.17.304 — `AssetBaseline` model with JSONField snapshot + `Asset.capture_baseline()` method; `is_current` flag tracks the active baseline; old ones kept for history)*
- Software compliance auditing *(shipped v3.17.305 — `SoftwarePolicy` model with deny/require actions + severity; `/reports/software-compliance/` joins policies against `RMMSoftware` inventory and surfaces deny violations + require gaps)*
- Hardware lifecycle scoring (composite — see Phase 13) *(shipped — Phase 13 v6, v3.17.263 — `Asset.lifecycle_score()` 0-100 composite)*
- Warranty lookups (vendor API integrations) *(shipped v3.17.309 — `WarrantyConnection` model + `BaseWarrantyProvider` interface + Dell / HPE / Lenovo adapter stubs; live `lookup_warranty()` lands when an MSP connects a real account)*
- Patch correlation (this CVE matches these N assets) *(shipped v3.17.306 — `Vulnerability` model with cve_id + cvss_score + affected_pattern; `affected_assets()` walks `RMMSoftware → RMMDevice → Asset` (by name) to surface affected endpoints)*
- Smart asset grouping (auto-cohort by role/version/location) *(shipped v3.17.307 — `AssetGroup` model with JSON criteria + computed `members()`; supports `asset_type` / `manufacturer__icontains` / `model__icontains` / `os_version__icontains` / `tags__contains`)*
- Vulnerability-to-ticket linking *(shipped v3.17.307 — `Vulnerability.create_remediation_ticket()` spawns a PSA Ticket with severity-mapped priority (critical→P1) and an affected-asset list)*
- Configuration monitoring *(shipped v3.17.308 — `Asset.config_monitored` flag drives the daily `assets_capture_baselines` cron that snapshots into `AssetBaseline`; old baselines retained for history)*
- Operational health scoring per asset *(shipped v3.17.308 — `Asset.health_score()` composite 0-100; deductions for drift (-25), vulnerabilities (-10/-5/-2 by severity, cap -40), lifecycle (cap -50), firmware update (-10); returns factor breakdown for UI)*
- Automated remediation suggestions (**OPTIONAL AI**) *(shipped v3.17.310 — `RemediationSuggestion` model + `assets_generate_remediation_suggestions` heuristic command (LLM-swap-in later) gated by `psa_ai_enabled`; 4 heuristics: firmware update / drift / health regression / CVE match; review/accept/dismiss flow)*

**Goal:** Improve infrastructure awareness and proactive operational management.

## Phase 18 — Multi-Location Client Hierarchy **(M)** [shipped — v3.17.283]

**Roadmap item:** Advanced Multi-Location Organization Management.

Planned capabilities:
- Parent / child organizations (`Organization.parent` self-FK) *(shipped v3.17.240)*
- Multi-site hierarchy *(shipped v3.17.240 — `Organization.ancestors` property + breadcrumb labels)*
- Shared infrastructure inheritance *(shipped v3.17.252 — `Asset.is_shared_with_descendants` flag + `Asset.visible_to_org()` classmethod that unions own/descendants/shared-from-ancestors; `core.utils.ancestor_org_ids` helper added)*
- Location-specific documentation *(shipped — KnowledgeBase articles already scope per organization via Phase 18 v1 parent/child support; v3.17.282 confirmation)*
- Location-level contacts *(shipped — `assets.Contact` rows already scope per organization via Phase 18 v1 parent/child support; v3.17.282 confirmation)*
- Site-level SLA assignment (override parent SLA) *(shipped v3.17.282 — `Organization.sla_overrides` JSONField + `sla_override_for(priority_code)` method that walks up the parent chain)*
- Site filtering on every list page *(shipped v3.17.240 — `OrganizationManager.for_organization` walks parent chain via `core.utils.descendant_org_ids` helper, parent queries see all descendants automatically)*
- Shared services mapping *(shipped v3.17.283 — `/reports/multi-location/` "Shared services" section lists every `Asset.is_shared_with_descendants=True` row + the descendant orgs that see it)*
- Regional operational views (group sites by region) *(shipped v3.17.283 — `/reports/multi-location/` "By region" section groups orgs by `normalized_region`)*
- Multi-location reporting *(shipped v3.17.283 — `/reports/multi-location/` per-parent rollup: tree size, open ticket count, AR balance, asset count across the full descendant tree)*

**Goal:** Improve management of larger MSP client environments.

## Phase 19 — Advanced Reporting & Analytics **(continuous)** [shipped — v3.17.326]

**Roadmap item:** Operational Analytics & Business Intelligence. Extends Phase 3 (Financial Reporting + BI) — these are the next-tier analytics on top of the canonical query layer.

Planned capabilities:
- Technician utilization reporting *(shipped — Phase 2.3 + 3.2)*
- SLA forecasting (predict breach risk before it happens) *(shipped v3.17.320 — `/reports/sla-forecast/` ranks open tickets by % SLA window elapsed; ok/at_risk/critical/breached bands; CSV export)*
- Ticket aging analytics *(shipped v3.17.257 — `/reports/ticket-aging/` 5-bucket breakdown + per-priority matrix + 7+ day aged-table + CSV export)*
- Contract profitability *(shipped — Phase 3.2)*
- Quote conversion tracking *(shipped v3.17.321 — `/reports/quote-conversion/` per-creator quote → accepted → invoiced funnel; configurable rolling window via `?days=`; CSV export)*
- Customer health scoring *(shipped — Phase 3.6B)*
- Executive dashboards *(shipped — Phase 3.6A scorecard)*
- KPI dashboards *(shipped v3.17.322 — `/reports/kpi/` live widget grid: open tickets, mean age, weekly closed, 30d SLA breaches, MRR/ARR; tenant-scoped; CSV export)*
- Operational metrics *(shipped v3.17.323 — `/reports/operational-metrics/` mean time to first response + mean time to resolution + first-touch resolution % + queue depth + age distribution; tenant-scoped; CSV export)*
- Workflow performance analytics *(shipped v3.17.324 — `/reports/workflow-performance/` per-rule fire-count + last-error roll-up; by-trigger distribution; errored rules floated; staff-only; CSV export)*
- Trend analysis *(shipped v3.17.325 — `/reports/trends/` 12-month time series of tickets opened/resolved + MRR added; staff-only; CSV export)*
- Capacity forecasting *(shipped v3.17.325 — same `/reports/trends/` page surfaces per-tech open-tickets vs `BillableTarget` target_hours_per_week; over-target rows highlighted)*
- Reporting exports (already CSV; add PDF + scheduled email) *(shipped v3.17.326 — `?format=pdf` on procurement_summary, ar_aging, mrr_forecast, kpi dashboard via `reports.pdf_export.render_pdf` ReportLab helper; `ScheduledReport` model + `psa_send_scheduled_reports` cron already shipped earlier — confirmed end-to-end)*

**Goal:** Provide MSP operational visibility and business insight.

## Phase 20 — Approval & Change Management Workflows **(M)** [shipped — v3.17.277]

**Roadmap item:** Approval Routing & Change Management. Extends Phase 6.1 (CAB) + the existing approvals queue.

Planned capabilities:
- Multi-stage approvals (sequential gates: tech lead → manager → CAB) *(shipped v3.17.265 — `PSAApproval.parent_approval` self-FK + `stage_index` + `blocked` status; `PSAApproval.create_chain()` factory; approve cascades to next blocked stage; deny cancels downstream)*
- Change advisory workflows *(shipped — Phase 6.1 CAB)*
- Quote approval routing (gate quotes above threshold) *(shipped v3.17.270 — `Quote.send_for_approval()` wraps `PSAApproval.create_chain`; default routing creates a 2-stage chain when total ≥ threshold else single-stage; idempotent against open chains; POST view at `/psa/quotes/<pk>/send-for-approval/` with modal UI on quote detail)*
- Financial approval chains (POs / invoices over $X) *(shipped v3.17.259 — `SystemSetting.invoice_approval_threshold_total` + `invoice_approval_overage_pct` auto-flag invoices via post_save signal; uses existing `Invoice.flag_for_approval` machinery)*
- Escalation approvals (auto-escalate idle approvals) *(shipped v3.17.256 — `psa_escalate_idle_approvals` management command + per-row `escalation_threshold_hours` + `escalated_at` dedupe; emails superusers a single digest)*
- Conditional approvals (rules: "if value > $5k, route to owner") *(shipped v3.17.273 — `SystemSetting.quote_approval_threshold_total` drives a post_save signal that auto-creates a 2-stage approval chain when total ≥ threshold; only fires on draft/sent statuses; idempotent against open chains)*
- Approval audit trails *(shipped v3.17.274 — `PSAApproval.decide()` and `create_chain()` now write to `audit.AuditLog` automatically; cascade transitions (auto-unblock, auto-cancel-on-deny) are logged too; per-approval history viewer at `/psa/approvals/<pk>/history/`)*
- Workflow enforcement *(shipped v3.17.275 — `Quote.has_open_approvals` property + `Quote.mark_accepted()` raises ValueError when any chain stage is pending/blocked; matches the existing Invoice push gate)*
- Change tracking *(shipped v3.17.276 — `ChangeRequestTransition` table records every implementation_status transition; `ChangeRequest.transition_status()` method auto-stamps timestamps + writes attribution; pre/post_save signals capture direct edits too)*
- Operational sign-off workflows *(shipped v3.17.277 — `Ticket.sign_off()` method + `signed_off_at`/`signed_off_by`/`signoff_note` fields; `TicketStatus.requires_signoff` flag drives a pre_save guard that raises ValidationError on attempted transition without sign-off)*

**Goal:** Improve workflow accountability and operational governance.

## Phase 21 — Advanced Mobile Technician Workflows **(L)** [shipped — v3.17.318]

**Roadmap item:** Mobile Technician Workflow Expansion. Extends Phase 8 (mobile apps + GPS auto-time + Timeclock).

Planned capabilities:
- Offline workflow support (work without connectivity, sync on reconnect) *(shipped — `static/service-worker.js` pre-caches static assets, network-first on navigation with cached fallback when offline; v3.17.318 confirmation)*
- Camera uploads (photo upload from the phone, attached to the ticket) *(shipped — `psa.TicketAttachment` model + existing upload endpoint accept image MIMEs; PWA uses HTML5 `<input capture="environment">`; v3.17.317 confirmation)*
- Barcode scanning *(shipped v3.17.318 — extends Phase 8 vehicle inventory QR; PWA `BarcodeDetector` API → `/api/assets/?search=...` which now matches `mac_address` / `ip_address` too)*
- QR scanning *(shipped v3.17.318 — same scan-and-search path as barcode)*
- NFC scanning *(shipped — Web NFC API client-side reads NDEF record, calls `/api/assets/?search=...`; v3.17.318 confirmation)*
- GPS time tracking *(shipped v3.17.315 — `TicketTimeEntry.start_lat/lng` + `end_lat/lng` Decimal fields captured by the PWA at timer start/stop)*
- Technician signatures (canvas signature pad on completion) *(shipped v3.17.312 — `TicketSignature` model one-to-one with Ticket; base64 PNG data-URI storage + geo capture)*
- Onsite checklist enforcement (must complete X before close) *(shipped v3.17.312 — `TicketChecklistItem` model + `Ticket.has_outstanding_checklist` property + sign-off-required transitions blocked while required items are incomplete)*
- Push notifications *(shipped v3.17.313 — `WebPushSubscription` model with per-user/endpoint uniqueness + `send()` helper; live VAPID-signed delivery via pywebpush when `WEBPUSH_VAPID_PUBLIC_KEY` / `WEBPUSH_VAPID_PRIVATE_KEY` are configured)*
- Voice-to-ticket workflows *(shipped v3.17.315 — `TicketComment.source='voice'` + `voice_meta` JSONField for confidence/language/duration; PWA Web Speech API → existing comment-create endpoint, no new server endpoint needed)*
- Mobile dispatch routing (turn-by-turn from current GPS to next ticket) *(shipped v3.17.317 — `/psa/t/<ticket_number>/route-urls/` returns Google / Apple / Waze deep-link URLs as JSON; PWA picks the right one based on platform)*
- Mobile asset lookup *(shipped — existing `/api/assets/` REST endpoint; v3.17.317 confirmation)*
- **Site check-in / check-out (Field Mode)** — explicit "I have arrived" / "I have left" buttons against the active ticket, separate from the generic Timeclock — gives per-ticket onsite-duration evidence for billing *(shipped v3.17.311 — `SiteVisit` model with arrival/departure lat+lng; `check_out()` stamps closeout + computes `duration_minutes`)*
- **Mileage and trip logging** — auto-distance from previous geofence to current geofence, plus manual override; rolls up into per-tech / per-org mileage reports *(shipped v3.17.311 — `MileageLog` model with `is_auto` flag + start/end coords + `MileageLog.haversine_miles()` static helper for great-circle distance)*
- **Quick asset edit from phone** — beyond lookup, lets a tech update serial / location / notes inline without leaving the ticket *(shipped — existing PATCH on `/api/assets/<pk>/`; PWA calls the same REST endpoint as desktop; v3.17.317 confirmation)*

**Goal:** Improve field technician workflow efficiency and mobility.

## Phase 22 — Knowledge Base & SOP Management **(M)** [complete]

**Roadmap item:** Knowledge Base & Operational Documentation Expansion. Extends Phase v3.17.128 (KB tree) + v3.17.134 (KB perms).

Planned capabilities:
- Knowledge base versioning (history of edits, rollback) *(shipped earlier — `DocumentVersion`)*
- Article approvals (review-before-publish gate) *(shipped v3.17.250 — `/docs/approval-queue/` + approve / reject / submit-for-review endpoints; rejection notes appended to article body for inline feedback)*
- Article ownership *(shipped v3.17.245 — `Document.owner` FK defaults to `created_by`)*
- SOP workflows (links the KB to step-by-step Process executions)
- Review reminders (article hasn't been reviewed in 90 days → email owner) *(shipped v3.17.245 — `kb_review_reminders` management command + `Document.review_interval_days` / `last_reviewed_at` / `is_review_overdue` + `/docs/review-queue/` view + `mark-reviewed` endpoint)*
- Internal / external KB separation *(partial — `is_client_visible` shipped)*
- KB analytics (most-viewed, least-viewed, dead links) *(partial — `Document.portal_view_count` shipped v3.17.234)*
- Public knowledge publishing (selected articles → public URL)
- Documentation lifecycle management (draft → published → archived) *(model fields shipped v3.17.245 — `is_draft`, `published_at`; full pipeline is v2)*
- Linked SOP automation (KB article triggers a workflow run)
- Import DOCX/PDF as editable documents + AI review (**OPTIONAL AI**) *(shipped v3.17.503 — `/docs/import/` bulk-extracts Word/PDF/TXT/Markdown text into editable KB documents; optional per-document AI reformat-to-standard + gap analysis via `review_imported_document`, gated by `psa_ai_enabled`. DOCX parsed dependency-free; PDF via PyMuPDF — issue #140)*
- Document export — Markdown / print-ready HTML / DOCX / PDF, single article or bulk ZIP *(shipped v3.17.510 — `Export` menu on every KB article and Global KB article writes Markdown, a standalone print-optimised HTML page, a real Word .docx (built dependency-free straight into the OOXML package, with Word styles, bullet/number lists, tables and live hyperlinks) or a letter-size PDF; `Export All` on the document list bundles everything the current category / tag / search filters select into one ZIP with an `index.md` table of contents, for handing a departing client their whole documentation set. Exported HTML and the article page itself carry an `@media print` block that strips background images, shadows and app chrome so a printed copy is legible. v3.17.511 drops decorative chrome — floating code-block language badges, print-hidden and screen-reader-only elements — that would otherwise flatten into stray one-word paragraphs in a linear export — issue #144)*

**Goal:** Improve operational knowledge management and documentation governance.

## Phase 23 — Security Event & Incident Workflows **(L)** [shipped — v3.17.363]

**Roadmap item:** Security Event Correlation & Incident Operations. Extends Phase 9 (security alert ingestion) — these are the next-tier incident workflows on top of the basic alert dashboard.

Planned capabilities:
- Security event ingestion *(shipped v3.17.168 via Phase 9.1+9.2 — SecurityVendorConnection + SecurityAlert + pollers + webhook)*
- SIEM integrations *(shipped v3.17.337 — generic CEF/JSON/Syslog inbound endpoint with HMAC auth at /security/siem/webhook/)*
- Vulnerability correlation (CVE → affected assets → exposure) *(shipped v3.17.306–307 via Phase 17 v6+v8 — Vulnerability + affected_assets + ticket linking)*
- CVE-to-ticket workflows *(shipped v3.17.307 via Phase 17 v8 — vuln-to-ticket linking)*
- Security incident timelines *(shipped v3.17.338 — SecurityIncident + SecurityIncidentEvent + auto-correlation by asset+severity window + `/security/incidents/`)*
- Exposure scoring *(shipped v3.17.339 — Organization.exposure_score cached + `recompute_exposure_scores` mgmt cmd + org-detail badge)*
- Incident SLA tracking *(shipped v3.17.355 — SecurityIncidentSLAPolicy + `check_incident_sla_breaches` mgmt cmd + idempotent timeline events)*
- Automated remediation workflows *(shipped v3.17.358 — RemediationPlaybook + RemediationPlaybookStep engine; auto-fires on incident open; step types create_ticket / send_email / quarantine_asset_flag / run_workflow_rule)*
- Security dashboarding *(shipped v3.17.168 via Phase 9.3 — `/security/alerts/`)*
- Threat visibility *(shipped v3.17.361 — `/security/threat-overview/` single-pane dashboard with severity rollups, top-exposed orgs, playbook activity, week-over-week trend)*
- Security event reporting *(shipped v3.17.168 via Phase 9.4 — MTTA + suppression + digest framework)*
- AI-assisted incident summarization (**OPTIONAL AI**) *(shipped v3.17.362 — gated by `psa_ai_enabled`; pluggable provider; POST `/security/incidents/<id>/ai-summarize/` writes summary as timeline note)*

Potential integrations:
- Huntress
- SentinelOne
- CrowdStrike
- Microsoft security ecosystem (Defender, Sentinel)
- Sophos
- Other security platforms

**Goal:** Improve operational security visibility and incident response workflows.

## Phase 25 — Mature Timesheet Approval Workflows **(M)** [complete]

**Roadmap item:** Formal time-entry approval pipeline. Today `psa.TicketTimeEntry` is logged ad-hoc by techs; there's no formal weekly approval before billing.

Planned capabilities:
- Weekly timesheet model — groups a tech's TicketTimeEntry rows for a payroll period *(shipped v3.17.242 — `psa.TimesheetSubmission` with unique `(user, period_start, period_end)`; `TicketTimeEntry.submission` FK attaches entries to a batch)*
- Submit → review → approve / reject pipeline *(shipped v3.17.242 — `/psa/timesheet/` tech submit + `/psa/timesheet-approvals/` staff decide)*
- Multi-tier approval (tech → team lead → finance)
- Per-entry rejection with note ("re-classify this billable entry as project work")
- Lock approved timesheets — entries can't be retroactively edited after approval *(shipped v3.17.249 — `TicketTimeEntry.save()` early-returns when entry's submission.status='approved'; admin override via `_force_unlock=True`)*
- Auto-reminder cron at end of payroll period for un-submitted timesheets
- Bulk-approve UI for managers *(shipped v3.17.249 — `/psa/timesheet-approvals/bulk/` endpoint + sticky bulk-action bar on the queue page)*
- Export approved timesheets to payroll (CSV / QuickBooks Time / Gusto) *(shipped v3.17.249 — `/psa/timesheet-approvals/payroll-export/` returns per-(tech, week) CSV ready for QBT/Gusto import)*
- Audit trail per entry: who approved, when, with what note *(partial — `decided_by` / `decided_at` / `decision_notes` per submission shipped v3.17.242)*

Dependencies: extends Phase 2 (BillableTarget + utilization) + the existing approval queue pattern.

**Goal:** Add billing-grade rigor to time entries before they flow into invoices and commissions.

## Phase 26 — Custom Report Writer + Saved Queries **(L)** [complete]

**Roadmap item:** User-defined reports without writing Python. Today reports are templated (Phase 3 ships ~15 canned reports); this phase lets non-developers build their own.

Planned capabilities:
- Visual query builder — pick model (Ticket / Invoice / TimeEntry / Asset / etc), filters, group-by, aggregates, sort, limit *(shipped v3.17.246 with Ticket / Asset / Password targets; v3.17.251 added Invoice + TicketTimeEntry targets with per-model `org_filter` for tenant scoping when the model lacks a direct organization FK)*
- Saved query model — per-org or shared *(shipped v3.17.246 — `reports.SavedQuery` with `is_shared` + organization scope)*
- Run as report (renders as table + auto-chart for numeric columns) *(table render shipped v3.17.246; auto-chart deferred to v2)*
- Schedule a saved query as a recurring email-PDF (extends Phase 3.6 scheduled-reports runner)
- Pin a saved query as a dashboard widget (extends Phase 3.5 widget registry)
- Export to CSV / JSON / Excel *(CSV shipped v3.17.246; JSON/Excel deferred)*
- SQL escape hatch for power users (gated behind a separate permission; sandboxed read-only DB connection)
- Report-template marketplace — share / import community report definitions

Dependencies: Phase 3.5 (dashboards), Phase 3.6 (scheduled reports).

**Goal:** Reduce the gap between what owners want to know and what's pre-templated.

## Phase 27 — Advanced Accounting Reconciliation **(M)** [shipped — v3.17.281]

**Roadmap item:** Deeper accounting integration than the basic invoice push that ships today (QBO + Xero — Phase shipped earlier). Adds true reconciliation between Client St0r's books and the accounting system.

Planned capabilities:
- Bidirectional payment sync — when a payment lands in QBO/Xero, mark the source Invoice as paid *(partial — `BaseAccountingProvider.poll_invoice_balance()` + QBO/Xero implementations + the `accounting_sync_payments` command shipped v3.17.280; idempotent + audit-logged. **Corrected v3.17.526:** this entry previously claimed a "daily cron". No timer, crontab entry or scheduler task was ever wired, so the command has only ever run when typed by hand. It also polls the invoice balance rather than reading provider payment records, so a partial payment is invisible and the Payment row it writes carries an inferred date and method. Real bidirectional sync — scheduling included — is Phase 44)*
- Invoice deduplication detection (catch double-pushes) *(shipped v3.17.255 — duplicate `(provider, accounting_external_id)` groups surfaced on `/reports/accounting-reconciliation/`. Extended v3.17.526 from detection to prevention: the push view refuses an invoice that already carries a provider id, so a double-click can no longer put a second invoice in front of the client. Re-push remains available as an explicit action for the deleted-provider-side case)*
- Unpaid-vs-pushed reconciliation report (what's invoiced here but missing in QBO?) *(shipped v3.17.255 — outstanding-pushed section + push-error section + CSV export)*
- Per-invoice line-item mapping to GL accounts (revenue vs. cost-of-services-sold splits) *(shipped v3.17.278 — `InvoiceLineItem.gl_account_code` propagates to QBO `ItemRef.value` and Xero `AccountCode` on push; blank falls through to provider default; back-compat)*
- Tax reconciliation (compare what we calculated vs. what QBO recorded) *(shipped v3.17.267 — `Invoice.provider_tax_amount` captured at push time from QBO `TxnTaxDetail.TotalTax` / Xero `TotalTax`; reconciliation report flags any |delta| > $0.01)*
- Accounts receivable aging tied directly back to QBO/Xero AR *(shipped v3.17.269 — `/reports/ar-aging/` per-client 0-30 / 31-60 / 61-90 / 90+ day buckets for pushed-but-unpaid invoices; CSV export; tenant-scoped)*
- Bank-account reconciliation hooks (mark which payments matched which bank-deposit batches) *(shipped v3.17.281 — `Payment.bank_deposit_batch` + `bank_reconciled_at` fields; per-batch report at `/reports/bank-reconciliation/` with mark-reconciled / reopen actions; staff-only)*
- Refund / credit-memo workflows *(shipped v3.17.264 — `Invoice.is_credit_memo` + `credits_invoice` FK + `create_credit_memo()` method that copies/negates lines or creates a lump-sum credit; sequential `CN-YYYY-NNNNN` numbering; UI modal on invoice detail; POST-only view at `/psa/invoices/<pk>/credit-memo/`)*
- Multi-entity / multi-book support for MSPs operating multiple legal entities *(shipped v3.17.279 — `Invoice.target_connection` FK pins the invoice to a specific AccountingConnection; push picks pinned else falls back to first sync-enabled; inactive-pinned-connection refuses push)*
- Audit trail of every accounting-system interaction *(shipped v3.17.260 — `AccountingAuditLog` writes one row per `push_invoice` / `record_payment` call across QBO + Xero providers; viewer at `/integrations/accounting/<pk>/audit-log/`. Stores truncated req/resp summaries — full payloads intentionally not stored to keep the log free of secrets/PII)*

Dependencies: existing AccountingConnection pattern. Builds on Phase 15.

**Goal:** Eliminate manual cross-checking between Client St0r and the accounting system.

Cross-references: Phase 36 (Agreement Reconciliation) layers an MSP-specific reconciliation flow — included-vs-billable labor, over/under-served clients, pre-invoice approval — on top of the GL-level reconciliation this phase covers.

## Phase 28 — Browser Extension + Offline Vault Access **(L)** [shipped — v3.17.331 — server-side API; extension binary out of scope]

**Roadmap item:** Chrome / Firefox / Edge extension for password autofill from the vault, plus an offline-capable PWA mode for read-access to the vault.

Planned capabilities:
- WebExtension (cross-browser via WebExtensions API) *(shipped v3.17.327–v3.17.331 — server-side API surface fully shipped: `vault.WebExtensionAuthToken` model + bearer-auth + autofill / sync / totp / reveal / verify-master / generate endpoints; complete contract documented in `docs/browser-extension-api.md`. The extension binary itself (Chrome / Firefox / Edge `.crx` package, store submission) is a separate codebase outside this repo)*
- One-click autofill on login pages from `vault.Password` matched by URL pattern *(shipped v3.17.328 — `/vault/api/extension/autofill/?url=...` returns matches by host suffix; per-call audit log)*
- Master-password unlock (re-derive AES-GCM key locally; never transmit master) *(shipped v3.17.329 — `GET /vault/api/extension/verify-master/nonce/` issues a 32-byte URL-safe nonce; `POST /vault/api/extension/verify-master/` constant-time-verifies HMAC-SHA256 keyed by the user's stored password hash; server never sees the master password)*
- Per-organization isolation (extension UI matches the active org context in-app) *(shipped v3.17.330 — `extension_auth_required` honours `X-Organization-Id` header per call when token is unpinned, falls back to token's pinned org otherwise; org-scoped queryset prevents cross-org leakage)*
- Offline-encrypted vault cache — last-fetched passwords are stored encrypted under a session key, valid for N hours so a tech can still pull a credential when the server is unreachable *(shipped v3.17.328 — `/vault/api/extension/sync/` cursor-paginated; returns encrypted blobs only; gated by `vault_extension_offline_cache` permission)*
- TOTP code generation in-extension (existing `totp_secret` field on Password) *(shipped v3.17.329 — `GET /vault/api/extension/<pk>/totp/` reuses `Password.generate_otp()`; per-call audit log)*
- Audit log of every autofill (logged when the extension reconnects) *(shipped v3.17.329 — every extension call emits a `vault_extension_*` AuditLog row synchronously: autofill / sync / totp / reveal / verify_master)*
- Generate-strong-password helper (matches the existing in-app generator) *(shipped v3.17.330 — `/vault/api/extension/generate/` reuses `vault.utils.generate_password`; returns `{password, length, charset_size, entropy_bits}` for client-side strength meter)*
- Browser-extension specific permissions on RoleTemplate (`vault_extension_use`, `vault_extension_offline_cache`) *(shipped v3.17.328 — both boolean fields on RoleTemplate; simple-role fallback maps Owner/Admin → both True, Editor → use only, Read-Only → neither)*

Dependencies: existing vault model + AES-GCM key infra. Browser extension is a separate codebase + store-submission process.

**Goal:** Match the IT Glue / Bitwarden experience that techs already expect.

## Phase 31 — Vault GeoIP / IP / Time Access Rules **(S)** [shipped — v3.17.163]

Per-rule GeoIP / IP / time-of-day gates on top of the vault. New `VaultAccessRule` model, scopable to a specific Password, a specific User, or an Organization (three scopes). Rules carry allowed/blocked country lists (ISO codes), allowed/blocked CIDR lists, allowed weekdays + hour window with IANA timezone, plus priority + active flag. DENY-wins-then-priority engine; empty rule set keeps back-compat ALLOW. Every reveal/view decision is audit-logged with the reason, source IP, country, and matched rule ID. New `vault_manage_access_rules` permission gate.

- `vault.VaultAccessRule` model + migration *(shipped v3.17.163)*
- Decision engine `vault/access_rules.py` reusing firewall middleware GeoIP helpers *(shipped v3.17.163)*
- CRUD UI under `/vault/access-rules/` + access-denied page *(shipped v3.17.163)*
- Detail-view badge: "N access rules apply" *(shipped v3.17.163)*
- 7 unit tests in `vault.tests.VaultAccessRuleEngineTests` *(shipped v3.17.163)*

---
- Click-to-select world map for country selection *(shipped v3.17.522 — replaces comma-separated ISO-code text boxes on both the vault access-rule form and the global firewall country rules with a clickable world map; a country belongs to one list, so "allowed AND blocked" is not expressible. Country names resolve server-side from a bundled ISO 3166-1 table, never from the browser. Map backdrop is configurable — colour pattern, random, or an uploaded image — and is cosmetic only, saved through its own endpoint so it can never rewrite firewall rules)*

## Phase 32 — Remote Network Discovery Import **(M · future / late-stage)** [planned]

A technician opens an Organization in ClientSt0r, picks a Location, and clicks **Generate Network Discovery Script**. ClientSt0r issues a temporary one-time-use token bound to that single org + location, generates a downloadable PowerShell script, and the tech runs it on a Windows host inside the client's network. The script does a safe (non-intrusive, non-credentialed) sweep of the local subnets, collects IP / MAC / hostname / vendor data, and uploads the results back to ClientSt0r. ClientSt0r imports / updates Asset records under that Org + Location, deduping by MAC and by org+location+IP.

**Roadmap item — placed near the end of the roadmap as a future / late-stage feature.** The user request explicitly says do not turn this into an RMM agent: no persistent agents, no permanent API keys, no exploit scanning. Strictly safe, auditable, scoped, MSP-friendly network discovery.

### Models (new app, e.g. `network_discovery/`)

- **`NetworkDiscoveryToken`** — `id`, `organization` FK, `location` FK, `created_by`, `token_hash` (only the hash; full token never re-displayable), `expires_at`, `revoked_at`, `used_at`, `max_uses` (default 1), `use_count`, `source_ip_last_used`, `user_agent_last_used`, `notes`, audit timestamps.
- **`NetworkDiscoveryImport`** — `id`, `organization`, `location`, `token` FK, `uploaded_by_user`, `source_ip`, `device_count`, `imported_count`, `updated_count`, `skipped_count`, `error_count`, `raw_payload` (JSON, optional summarized form), `created_at`.
- **`NetworkDiscoveryAssetResult`** — `id`, `import` FK, `organization`, `location`, `asset` FK (nullable; set when matched / created), `ip_address`, `mac_address`, `hostname`, `vendor`, `device_type`, `discovery_method`, `status`, `raw` JSON, `created_at`.

### Endpoints

- `POST /orgs/<org_id>/locations/<location_id>/network-discovery/generate/` — authenticated; gates on a new `network_discovery_generate` RoleTemplate boolean. Returns the script file + the one-time token displayed once on screen (never again).
- `GET /orgs/<org_id>/locations/<location_id>/network-discovery/download/<token_id>/` — re-downloads the script (token still hidden; re-renders only the script body with the token already embedded server-side at first generation).
- `POST /api/network-discovery/upload/` — public, **token-only** auth. Token is single-use (or limited-use), short-lived, scoped to one (org, location), POST-only, write-only — cannot read anything. Validates payload size + IP/MAC/hostname formats. Rate-limited.
- `POST /orgs/<org_id>/locations/<location_id>/network-discovery/revoke/<token_id>/` — revokes immediately.
- `GET /orgs/<org_id>/locations/<location_id>/network-discovery/imports/` — import history.

### PowerShell script behavior

- Auto-detects active local IPv4 subnets from active network adapters
- Optional params: `-Subnet`, `-ServerUrl`, `-Token`, `-OrgId`, `-LocationId`, `-TimeoutMs`, `-MaxHosts`, `-SkipUpload`, `-OutputJsonPath`
- Default: ping sweep / `Test-Connection`, ARP table collection, optional reverse-DNS, MAC harvest from `arp -a` / `Get-NetNeighbor`
- Optional lightweight enrichment: probe ports 80 / 443 / 22 / 3389 / 445 only — for device-type classification (workstation / server / router / printer / unknown). Never destructive, never credentialed, never vulnerability scan.
- Runs on Windows PowerShell 5.1+ and PowerShell 7+
- Doesn't require admin unless necessary
- Always writes a local JSON summary before upload
- Shows count of discovered devices and upload result

### Asset import behavior

1. Match by MAC first.
2. If no MAC match, match by `(organization, location, ip_address)`.
3. On match: update missing fields only; never overwrite manually-entered names; bump `last_seen` / discovery metadata.
4. On no match: create a new Asset with `organization`, `location`, name = hostname → IP → MAC, `asset_type` = "Network Discovered Device" (or "Unknown Network Device"), IP, MAC, vendor, notes "Discovered by Remote Network Discovery Import".
5. Optional dry-run / preview mode.

### Security requirements

- Token is **temporary** (short expiry, default 15 min)
- Scoped to **one org + one location** only
- **Write-only** — can't read anything; only POST to the discovery upload endpoint
- **Single-use by default** (or limited-use with expiration) — `max_uses=1`, `use_count` tracked
- Server stores **only a hashed version** of the token; full plaintext shown once at generation, then never again
- Revocable from the UI
- Every generation, download, upload, import event audit-logged (user, org, location, source IP, count, errors)
- Upload endpoint rate-limited
- Payload size validated; all IP/MAC/hostname fields validated
- Generation requires existing authenticated user permissions
- The PowerShell script clearly shows the ClientSt0r server URL it will upload to but contains **no permanent credentials**

### UI

- Network Discovery section on Organization detail page (location-scoped)
- "Generate Network Discovery Script" button after a Location is picked
- Token expiration shown
- Last generated scripts list
- Revoke buttons
- Import history with imported / updated / skipped / error counts per import
- Last scan summary
- Warning banner: **"Run this only on networks you are authorized to scan."**

### Tests

Token generation; expiration; revocation; valid upload; expired token rejected; revoked token rejected; cross-org / cross-location upload rejected; duplicate MAC updates existing asset; duplicate IP/location updates existing asset; new devices create assets; unauthorized users cannot generate scripts; payload validation; rate limiting (if testable).

### Goal

Provide MSP-friendly remote network discovery without standing up a full RMM agent. Everything is **temporary, scoped, auditable**, and bound to a single org + location. Not a backdoor. Not a persistent agent.

Phase 33 layers the deeper, persistent / scheduled, multi-protocol discovery on top of this single-shot foundation.

---

## Phase 33 — Network Discovery & Auto Documentation **(L)** [planned]

Multi-protocol persistent network discovery and topology inference. Phase 32 ships a one-shot, scoped, single-use ping / ARP script — useful for the first walk-through of a new client. Phase 33 is the always-on companion: a lightweight per-site collector that polls SNMP / LLDP / CDP / ARP on a schedule, keeps the asset inventory current, and generates topology diagrams without manual draw-time.

Planned capabilities:
- **Lightweight site collector / agent** — one per client site, packaged as a small container or systemd unit. Pulls config from server, pushes results back. No persistent admin credentials embedded; uses a per-site rotating token similar to Phase 32's scheme.
- SNMP, ICMP, ARP, LLDP, CDP discovery
- Automatic device inventory import *(extends the single-shot Phase 32 import flow)*
- Auto-generated topology maps *(extends Phase 16 Documentation Relationship Mapping with a dedicated network-layer view)*
- Device relationship mapping (which switches connect which APs / endpoints)
- Switch port / MAC / IP correlation table (resolve "which port is this device on" per VLAN)
- Manual and scheduled scans (cron-driven background jobs; on-demand trigger from the UI)
- Per-client and per-location discovery keys (rotation + revocation, audit log)

Dependencies: Phase 32 (token + import models — extend rather than replace), Phase 16 (relationship graph rendering), Asset model.

**Goal:** Reduce manual network documentation work — keep the topology, switch port assignments, and device inventory in sync with reality without a tech having to redraw or re-export anything.

## Phase 34 — Network Configuration Backup **(M)** [planned]

Versioned configuration backup for firewalls, switches, routers, and other manageable network gear. Treats device configs the same way the existing `Document` versioning treats KB articles — every change snapshotted, diffable, alertable.

Planned capabilities:
- **Firewall, switch, and router config backup** — pulled via SSH / SCP / SNMP / vendor APIs depending on device. Per-device adapter pattern matching the integration framework shipped in Phase 7.
- Scheduled backup jobs (per-device cadence; default daily)
- Config diff viewer — line-level diff between any two snapshots; latest-vs-prior on the device detail page by default
- Alert on unauthorized config changes — diff against the last "approved" snapshot; surfaces in the security-alerts dashboard (Phase 9) when something changes outside of an approved change window (Phase 6.1 CAB)
- Firmware / version tracking — captures running firmware version on each backup so EOL transitions are visible
- End-of-life and warranty metadata fields on the device record (extends Phase 13 lifecycle tracking)

Dependencies: Phase 33 (device inventory provides the target list), Phase 9 (alert framework for drift notifications), Phase 6.1 (CAB / change-window awareness for "unauthorized" classification).

**Goal:** Eliminate the manual config-export-and-store-in-a-folder routine. Make unauthorized changes loud.

## Phase 35 — Advanced Project Management **(L)** [planned]

Mature the existing `psa.Project` and `psa.ProjectTask` models *(quote-to-project automation shipped v3.17.213)* into a full delivery management feature.

Planned capabilities:
- **Project templates** — predefined task lists for common project types (server migration, M365 cutover, network refresh). Drop a template onto a new project to populate the work breakdown in one click.
- Project phases and milestones *(milestones partial — `ProjectTask.is_milestone` flag exists)*
- Project budget tracking — hours budget + dollar budget vs. actuals
- Project profitability *(extends Phase 3.2 contract profitability with project-scoped breakdown)*
- Project-to-ticket task generation *(partial — quote line items already become ProjectTasks per v3.17.213; this phase makes any ProjectTask spawnable as a Ticket on demand)*
- Project billing support — project-bundled invoice generation, fixed-fee vs. T&M handling, milestone billing triggers
- Gantt / calendar-style planning view — drag-to-reschedule task bars on a timeline, dependency arrows between tasks

Dependencies: existing `psa.Project` + `psa.ProjectTask` models, Phase 3 (profitability infra), Phase 1 (contract / billing engine).

**Goal:** Take the lightweight Project model from "lets you group tickets" to "actually runs delivery engagements end-to-end."

## Phase 36 — Agreement Reconciliation & Pre-Invoice Approval **(M)** [complete]

MSP-specific reconciliation between what an agreement covers and what's actually being consumed. Phase 27 handles GL-level reconciliation against QBO/Xero; this phase handles agreement-vs-labor reconciliation against the contract itself, plus an explicit pre-invoice review gate so nothing goes out the door without a human nod.

Planned capabilities:
- **Recurring agreement billing review** — monthly (or per-cycle) review screen that lists every agreement, included-hours bucket consumed, overage hours, and the draft invoice *(partial — per-contract consumption table shipped v3.17.225 at /reports/agreement-reconciliation/)*
- **Included vs billable labor reconciliation** *(shipped v3.17.248 — `agreement_reconciliation_detail` view classifies entries chronologically as covered/overage/split; per-tech overage breakdown + CSV export)*
- **Over-serviced / under-serviced client alerts** — if a client consistently uses < 30% of included hours (under-served = upsell signal) or > 130% of included hours 3 months running (over-served = re-quote signal), alert the account manager *(shipped v3.17.225 — surfaced as status badges + summary counts on the reconciliation page; recurring-pattern detection across multiple periods deferred to v2)*
- **Agreement profitability reports** *(extends Phase 3.2 contract profitability with per-agreement P&L; cost-of-labor at tech rate vs. contracted revenue)*
- **Pre-invoice approval workflow** *(extends Phase 20 approval routing — gate any draft invoice over $X or with > Y% overage on a manager queue before sending)* *(shipped v3.17.228 — `Invoice.flag_for_approval` + `Invoice.approve` + `/psa/invoices/<pk>/approve/` endpoint + push-to-accounting blocked while pending)*
- **Revenue leakage detection expansion** *(extends the existing `revenue_leakage` query that powers the `unbilled_hours` widget; adds aging buckets, per-tech leakage attribution, and a per-client leakage trend)*

Dependencies: Phase 1 (contract engine — `Contract`, `ContractBundle`, `ContractBundleItem`), Phase 15 (recurring billing automation), Phase 20 (approval routing).

**Goal:** Stop money walking out the door. Make every agreement's profitability and consumption visible before invoicing, not after.

## Phase 37 — Vault Approval & Break-Glass Workflow **(M)** [complete]

Per-credential approval gates and emergency-access ("break-glass") flow for the password vault. Phase 31 *(shipped v3.17.163)* provides geo / IP / time-window restrictions; this phase adds workflow restrictions on top.

Planned capabilities:
- **Require approval before revealing sensitive vault entries** *(shipped v3.17.241 — `Password.requires_reveal_approval` flag + `VaultRevealRequest` model + `password_reveal` view gates on currently-valid approval)*
- **Emergency break-glass access** *(shipped v3.17.241 — `/vault/<pk>/break-glass/` endpoint with mandatory ≥30-char justification, self-approves, hard audit log)*
- **Manager / admin notifications** *(shipped v3.17.241 — every reveal request emails superusers; every break-glass emails superusers immediately)*
- **Full access audit trail** *(extends the per-action vault audit shipped v3.17.181 — `vault_reveal_requested`, `vault_reveal_approved`, `vault_reveal_denied`, `vault_break_glass`, `reveal_blocked_no_approval` join the existing edit/delete events; shipped v3.17.241)*
- **Optional client-level vault approval rules** *(shipped v3.17.247 — `_can_decide_vault_reveal` policy helper allows `Membership.is_org_admin=True` of the password's org to approve, with self-approval blocked regardless of role)*

Dependencies: Phase 31 (`vault.VaultAccessRule` infra — extend rather than replace), Phase 20 (approval routing engine).

**Goal:** Make sensitive credentials require explicit human authorization to reveal, while preserving a documented escape hatch for genuine emergencies.

## Phase 38 — Client Onboarding / Offboarding Runbooks **(M)** [complete]

Repeatable runbooks for client onboarding, employee onboarding/offboarding, and client termination. Each runbook is a structured checklist with verification steps and ticket-spawning hooks. Builds on the existing `processes/` workflow engine.

Planned capabilities:
- **Repeatable onboarding templates** — clone an `is_template=True` Process per new client; copies all stages with linked entities preserved *(shipped v3.17.223)*
- **Employee onboarding / offboarding workflows** *(category support shipped — `onboarding` / `offboarding` already existed; `client_*` companions added v3.17.223)*
- **Client termination checklist** — `client_termination` category added so the existing Process model carries the termination flow *(category shipped v3.17.223)*
- **Access removal verification** — for offboarding, mechanically verify that the user is actually removed from each documented system (poll vault, M365, RMM, etc.) and surface any orphaned access *(deferred — requires M365 / RMM / vendor-API integrations beyond the runbook engine itself; the manual checklist pattern via runbook stages is fully supported today, an MSP can build a "verify M365 license removed" stage and tick it off after manual confirmation)*
- **Documentation completion scoring** — per-execution `ProcessExecution.completion_percentage` already shipped; per-org dashboard with rollup across all in-flight runbooks at `/processes/dashboard/` *(shipped v3.17.227)*
- **Runbook-to-ticket conversion** — any runbook step can spawn a Ticket; created ticket is recorded on `ProcessStageCompletion.spawned_ticket` *(shipped v3.17.223)*

Dependencies: `processes/` app (existing), Phase 14 (visual workflow builder for runbook editing).

**Goal:** Turn ad-hoc tribal-knowledge onboarding/offboarding into a measurable, repeatable, completable workflow.

## Phase 39 — Compliance Evidence Packs **(M)** [complete]

One-click exportable audit packet per client. Bundles the evidence regulators / auditors / cyber-insurance underwriters consistently ask for, sourced from data already living in Client St0r — no manual screenshot-and-paste required.

Planned capabilities:
- **Exportable client audit packet** — single styled HTML page (with print-to-PDF stylesheet) + downloadable ZIP of per-section CSVs *(shipped v3.17.222)*
- 2FA status — which users on the account have 2FA enrolled, by method *(shipped v3.17.222)*
- User access report — current memberships, role templates, last-login per user *(shipped v3.17.222)*
- Password access history *(extends vault audit shipped v3.17.181 — every reveal / edit / delete event in the period)* *(shipped v3.17.222 — last 90 days)*
- Asset inventory — current asset list with serial / vendor / location / lifecycle stage *(shipped v3.17.222)*
- Vulnerability scan summary *(extends Phase 9 security framework + the existing OS Package Scanner)* *(shipped v3.17.226 — 90-day open-alert summary by severity)*
- SSL / domain expiration summary *(extends the WebsiteMonitor expiration infra)* *(shipped v3.17.226)*
- Ticket / SLA history — ticket counts, SLA-met percentages, response and resolution medians *(shipped v3.17.222 — 12-month window)*
- Backup and uptime evidence — backup-job success rate, monitor uptime percentages over the period *(uptime shipped v3.17.226; backup is a placeholder until a backup-tracking integration is built)*

Dependencies: Phase 9 (security data), vault, monitoring/, psa (SLA history), assets.

**Goal:** Reduce the "audit prep" interrupt to a button-press. The data is already in the system; this phase wraps it in the standardized export shape auditors expect.

## Phase 40 — Public / Client-Facing Status Page **(M)** [planned]

Public or per-client-private status page surfacing current service status, scheduled maintenance, incident history, and uptime. Sourced from the WebsiteMonitor + ticket-incident infrastructure already in place.

Planned capabilities:
- **Client-visible service status** — green / degraded / outage indicator per service the MSP runs for the client; sourced from the existing monitoring app + recent incident tickets
- **Maintenance windows** — scheduled-maintenance posts with start/end + affected services; scheduled in advance so the page shows them as upcoming
- **Incident history** — each incident is a ticket with `is_status_page = True`; rendered as a timeline with updates, root cause, and resolution
- **Uptime history** — 30 / 90 / 365 day uptime percentage per monitored service, sourced from `WebsiteMonitor` history
- **Optional per-client private status pages** — each client gets their own URL gated by client-portal auth; alternative: a single fully-public page for MSPs that want to broadcast status to all customers + prospects

Dependencies: `monitoring/` app (uptime data), `psa.Ticket` (incident history with new `is_status_page` flag).

**Goal:** Take the "is anything broken?" call volume out of the queue by giving clients somewhere to look first.

## Phase 41 — Compliance Frameworks & Recertification **(M)** [shipped — v3.17.444]

MSPs increasingly need to attest to PCI-DSS or HIPAA on behalf of their clients. Phase 39 (Compliance Evidence Packs) handles the evidence collection side; this phase adds the *workflow* side: opt an org into one or more frameworks, walk through a checklist of real controls, attest per-control with notes + evidence, generate a customer-ready PDF, and drive recertification on a configurable cadence.

Capabilities:
- **Framework catalog** — `ComplianceFramework` model with `ComplianceCategory` + `ComplianceCheckItem`. *(shipped v3.17.436)* Pre-seeded with PCI-DSS v4.0 (12 categories, 38 check items, real control numbers like `1.2.1`, `8.4.2`, `11.3.2`) *(shipped v3.17.437 — `python manage.py seed_pci_dss`)* and HIPAA Security Rule (3 safeguard categories, 33 check items, real CFR refs like `164.308(a)(1)(ii)(A)`) *(shipped v3.17.438 — `python manage.py seed_hipaa`)*.
- **Per-org enrollment** — `OrganizationCompliance`. One org can be enrolled in multiple frameworks. Tracks `recertification_interval_days` (30 / 60 / 90 / 180 / 365), `recertification_emails_enabled`, `notify_email`. *(shipped v3.17.439 — dashboard at `/compliance/organizations/<org_id>/` + Enroll button)*
- **Per-control attestation UI** — checklist grouped by category, status dropdown (compliant / partial / non-compliant / N-A / unanswered), notes textarea, evidence URL. Color-coded by status. Every change audit-logged with `Status: <old> -> <new>`. *(shipped v3.17.440)*
- **Customer-facing PDF report** — exec summary + KPI grid + per-category table with each control's status, notes, evidence link. Audit-logged on every download. *(shipped v3.17.441 — `/compliance/.../report.pdf` using Phase 19's `reports.pdf_export.render_pdf`)*
- **Recertification reminder cron** — `python manage.py send_compliance_recertifications`. Idempotent + 7-day dedup. Resolves recipient via `notify_email` → first owner/admin Membership → `DEFAULT_FROM_EMAIL`. `--dry-run` for testing. *(shipped v3.17.442)*
- **Toggle UI + Mark Recertified Now button** — settings card on the checklist page lets org admins flip email reminders, change interval (30/60/90/180/365 days), set notify_email override, and stamp `last_recertified_at = now()` after a quarterly review. *(shipped v3.17.443)*

Dependencies: `accounts.Organization`, `audit.AuditLog`, `reports.pdf_export.render_pdf` (Phase 19).

**Goal:** Give the MSP one place to track every client's compliance state and one button to produce the report when an auditor asks for it.

**Operator setup:**
1. `python manage.py seed_pci_dss && python manage.py seed_hipaa` — populate the catalog (idempotent, safe to re-run after upgrades).
2. Add to crontab for daily recertification reminders:
   ```
   0 9 * * * cd /home/administrator && /home/administrator/venv/bin/python manage.py send_compliance_recertifications
   ```
3. For each client org needing compliance: `/compliance/organizations/<org_id>/` → click **Enroll** on the framework → walk the checklist.

---

## Phase 42 — First-class Docker / containerized deployment **(S · packaging)** [shipped — v3.17.490]

Self-hosted MSPs should be able to `git clone && docker compose up -d` and have a running install in under a minute — without the existing `bash install.sh` path going away.

- Multi-stage `Dockerfile` (Python 3.12 slim + venv) running as non-root `clientst0r` (uid 1000) *(shipped v3.17.490)*
- `docker-compose.yml` with `app` + `db` (MariaDB 10.11) as defaults; optional Nginx (`--profile proxy`) and Redis (`--profile cache`) services *(shipped v3.17.490)*
- `docker-compose.dev.yml` override — source bind-mount + gunicorn `--reload` + SQLite default for fast iteration *(shipped v3.17.490)*
- `docker-entrypoint.sh` — DB readiness wait, migrate, collectstatic, optional `DJANGO_SUPERUSER_*` bootstrap *(shipped v3.17.490)*
- Dedicated `/health/` endpoint for HEALTHCHECK *(shipped v3.17.490)*
- GitHub Actions workflow (`docker-image.yml`) — builds on PR, publishes `ghcr.io/agit8or1/clientst0r:latest` + semver tags on push to `main` / `v*` *(shipped v3.17.490)*
- `Makefile` with `docker-up` / `docker-logs` / `docker-shell` / `backup` / `restore` targets *(shipped v3.17.490)*
- `.env.example` covering every supported variable + `docs/docker.md` with backup, upgrade, profile, dev-mode, troubleshooting sections *(shipped v3.17.490)*

---

## Phase 43 — Multi-Organization REST API Access **(S · integrations)** [shipped — v3.17.496]

The public REST API (`/api/`) was single-tenant per request: an API key was bound to one organization and every endpoint filtered to that org alone. MSPs building a single-pane-of-glass need one connection that reads/writes across many client organizations. This phase broadens the API to multi-client without breaking any existing single-org integration.

- **Per-key organization scope** — new `APIKey.scope` field (`single` / `descendants` / `all`), default `single` so every existing key is unchanged. `descendants` covers the home org + its sub-locations (Phase 18 hierarchy); `all` covers every organization the key's owner can access *(shipped v3.17.496)*
- **`?organization=<id|slug|all>` request parameter** — narrow a multi-org key to one client, or fan out to all. Cross-org requests are refused with 403; a `single` key can never address another org *(shipped v3.17.496)*
- **Organization surfaced on every resource** — `organization` + `organization_name` on assets, contacts, documents, and passwords so a consumer can group rows by client; writable on create to target a specific client *(shipped v3.17.496)*
- **`/api/organizations/` returns the full accessible client set** for discovery before iterating *(shipped v3.17.496)*
- **Scope-bounded by live permissions** — a key never grants access beyond what its owner currently has; password reveal / OTP audit rows are logged against the row's own organization for full multi-client traceability *(shipped v3.17.496)*
- Contract documented in `docs/api-multi-org.md` *(shipped v3.17.496)*

---

## Phase 44 — Full Two-Way Accounting Sync **(L)** [planned]

**Roadmap item:** requested in GitHub #145. Extends Phase 27, which delivered reconciliation *reporting* plus a one-directional invoice push. What ships today is the push half: OAuth with encrypted tokens and automatic refresh, invoice push with GL-account and tax capture, multi-book routing, and a full audit log of every provider call. What does not exist is a genuine pull.

The gap, precisely — each of these is absent or partial today:

- **Customer mapping as a first-class record** — the organization → provider-customer map currently lives as a dict inside the connection's encrypted credentials blob, so it is not queryable, not visible in admin, and is lost if credentials are reset. Needs a real model with a uniqueness constraint.
- **Customer push beyond a name** — `_ensure_customer()` sends `DisplayName` only, never updates an existing provider customer, and runs only as a side effect of an invoice push.
- **Customer pull** — no importer, command or view exists; provider-originated customers cannot be adopted.
- **Invoice pull** — only `Balance` is read. Amount, date, line, void and deletion changes are invisible, as are invoices created provider-side. Needs a conflict rule, since both sides are writable today.
- **Real payment pull** — read provider `Payment` / `LinkedTxn` records instead of inferring from `Balance == 0`; store the provider payment id for idempotency; support partial payments so `Invoice.status='partial'` can actually be driven from the provider; handle reversal and void so a paid invoice can reopen.
- **Scheduling** — nothing runs automatically. Either a `clientst0r-accounting-sync.{service,timer}` pair or an `accounting_sync` entry in the `run_scheduler` task registry.
- **Manual "Sync Now"** — the accounting connection page has no sync action, unlike the RMM and PSA connection pages.
- **Retry and backoff** — a rejected push is terminal until a human clicks again. Needs exponential retry, 401-triggered re-auth, 429 `Retry-After` handling, and a failure counter that raises an alert instead of retrying forever.
- **Close the logging gaps** — `AccountingConnection.last_sync_at` / `last_sync_status` / `last_error` are declared but never written, while the UI renders `last_sync_at` and therefore always shows "Never". The sync command also logs `action='poll_balance'`, which is not in `ACTION_CHOICES`, so those rows render with a blank label.

Suggested MVP, matching the request: customers, invoices and payments, with the accounting system remaining the system of record for money and Client St0r remaining the operational platform. Products/services, tax codes and payment terms come later.

Dependencies: Phase 27 (reconciliation reporting + audit log) and the existing `AccountingConnection` OAuth pattern. The PSA and RMM sync jobs are the closest in-repo model for scheduled bidirectional pulls — there is no existing two-way accounting sync to copy from; Xero is push-only in exactly the same shape as QBO.

## Phase 45 — System-wide Appearance Controls **(S)** [shipped — v3.17.527]

**Roadmap item:** give administrators a say in how the app looks, without taking the choice away from users by default.

The page background was entirely per-user: each person picked a mode on their profile and that was that. An MSP wanting a consistent look across a team — or simply wanting to put their own image behind the app — had no way to set one.

- **Background policy in General Settings** *(shipped v3.17.527)* — four modes: **user controlled** (the previous behaviour, and still the default so upgrades change nothing), **static image** (one uploaded image for everyone), **colour or pattern** (a solid hex colour or one of the twelve preset gradients), and **random images** (a different image each page load).
- **Enforcement is honest about itself** *(shipped v3.17.527)* — when a policy is active the profile page keeps its background controls visible but disabled, under a banner naming the policy. Hiding them relocates the confusion rather than removing it. A user's own settings are preserved while a policy is in force and apply again if it is lifted.
- **Preset table consolidated** *(shipped v3.17.527)* — the twelve abstract backgrounds had been defined twice, labels on the profile model and URLs in a context processor, with nothing keeping the two in step; a key present in one and missing from the other would have shown up only as a silently absent background. Now one table in `core/backgrounds.py` feeds all three consumers.

Note the two background settings are unrelated: this one is the app page backdrop, while the GeoIP map backdrop (v3.17.522) styles the world map on the firewall and vault access-rule screens.

Dependencies: `SystemSetting` singleton + the existing per-user profile background fields.

## Phase 8 — Native mobile apps (iOS + Android) with GPS auto-time + Timeclock **(L · keystone)** [shipped — v3.17.417]

Reverses the earlier "PWA only" deferral. The combination of GPS auto-documentation + employee timeclock makes this a force-multiplier for billable-hours capture, not just a UX improvement.

Positioned last in the roadmap (v3.17.169) because it's the largest single undertaking and depends on a lot of other work being mature first — backend, scheduling, billing, and mobile app distribution all need to be in place before this phase pays off.

### Sub-phase 8.1 — Backend foundation *(shipped v3.17.397–410)*
- `TechnicianLocation` model — append-only GPS pings (lat/lon/accuracy/timestamp/source); retention policy + per-org enable flag. *(shipped v3.17.397)*
- `TimeclockEntry` model — clock-in / clock-out events with tech, organization, location, optional ticket, optional project, source (`'mobile'` / `'web'` / `'manual'`); derives a `TimeEntry` row on clock-out so existing billing rolls up unchanged. *(shipped v3.17.409)*
- `ClientSiteGeofence` model — per-client polygon or radius around their physical address(es). Used to auto-detect "tech is on site" for ticket time tracking. *(shipped v3.17.397)*
- REST API additions: `/api/v2/mobile/locations/`, `/api/v2/mobile/timeclock/`, `/api/v2/mobile/active-ticket/`. *(shipped v3.17.410 — endpoints live at `/api/mobile/v1/locations/`, `/api/mobile/v1/timeclock/clock-in/` + `/clock-out/` + `/me/`, and `/api/mobile/v1/active-ticket/`. Off-shift GPS suppression honors `WorkingHours` per Sub-phase 8.5.)*
- Token auth (long-lived per-device tokens stored in `MobileDevice` model with revoke-on-demand). *(API plan doc shipped v3.17.345; auth endpoints v3.17.346; dashboard + organizations v3.17.347; assets v3.17.348; tickets v3.17.349; KB endpoints — list / search / detail with raw markdown + rendered HTML — shipped v3.17.350; mobile-client login body field-name mismatch fixed v3.17.446 — was sending `email`, server reads `username`; dashboard endpoint shape aligned with `DashboardSummary` type — `recent_tickets` / `recent_assets` now arrays, `security` now an object — v3.17.448; vault list/detail/reveal endpoints with web-parity security — 30/hour throttle, per-credential approval gate, VaultAccessRule evaluation, audit logging — shipped v3.17.449. Mobile-side `monitoring/` and `security/` screens are slated for removal in a follow-up; their would-be endpoints were never built.)*

### Sub-phase 8.2 — GPS auto-documentation engine *(shipped v3.17.412; mobile foreground GPS at clock-in v3.17.452)*
- Background worker: every GPS ping with the tech "inside a client geofence" auto-starts a `TicketTimeEntry` against their currently-active ticket for that client (or creates a placeholder if no ticket open). *(shipped v3.17.412 — `python manage.py auto_document_field_visits`, cron every 1 min)*
- On exit-geofence event: stop the time entry, write the duration, optionally prompt the tech to confirm + add notes via push notification. *(shipped v3.17.412)*
- Selectable per-tech: **Always on** / **Ask first** / **Off**. Per-tech UserProfile flag. *(shipped v3.17.412 — `field_ops.AutoTimePreference`)*
- Audit log every auto-time event so disputed billing can be traced. *(shipped v3.17.412)*

### Sub-phase 8.3 — Timeclock feature *(shipped v3.17.413–414)*
- Web UI: Timeclock dashboard at `/timeclock/` for staff to view who's clocked in, total hours per pay period, exception flags (long shifts, missing clock-out). *(shipped v3.17.413 — `/field-ops/timeclock/`)*
- Mobile UI: prominent "Clock in / Clock out" button on the app home screen. Optional tie to the active ticket. *(shipped v3.17.414 — `mobile/app/timeclock/index.tsx` + dashboard widget)*
- Selectable per-org and per-tech: required vs optional, with vs without GPS context, separate from per-ticket time tracking.
- Payroll export — CSV per pay period, hooks for QuickBooks Time / Gusto / etc. (defer the integration; just structured export first). *(shipped v3.17.413)*

### Sub-phase 8.4 — App build *(shipped v3.17.354–360)*
- React Native (Expo SDK 51+ with EAS cloud build — revisits the earlier "no Expo accounts" rejection; required for store submission). *(read-heavy field-use slice complete: scaffold + auth v3.17.354; dashboard + orgs + assets v3.17.356; tickets + KB v3.17.357; vault + monitoring + security + settings v3.17.359; docs + EAS profiles + placeholder icons v3.17.360 — `mobile/` Expo TypeScript app. Phase 8 stays `[in progress]` because Sub-phase 8.2 (GPS auto-time) is still deferred. Local signed-AAB pipeline: targetSdk 35 v3.17.445; `expo-modules-core` Kotlin null-safety patch for `PackageInfo.requestedPermissions` (compileSdk 35 made it nullable) v3.17.446 — persisted via `patch-package`. Public `/privacy-policy/` route + Play Console Data Safety / store-listing prefill docs v3.17.447. Mobile cleanup pass v3.17.451 — removed `monitoring/` and `security/` screens (never had server endpoints), profile is now read-only sourced from `/auth/me/`, assets + vault lists grouped by organization with section headers. Asset detail full-info + Vault linkage + closed-tickets filter fix v3.17.476 — asset detail screen now renders the whole record across Identity / Hardware / Lifecycle / Notes / Metadata cards plus a "Stored secrets" section listing every Vault entry linked via `PasswordRelation`; the Mine and Critical ticket chips now also constrain to `status=open` so closed-but-critical / closed-but-mine tickets don't sneak through. Mobile ticket-flow + permissions follow-up v3.17.477 — new-ticket form now has a real searchable client picker (required), ticket detail surfaces an Assignee card with Claim / Reassign / Clear actions (Reassign gated on the new `tickets_assign` role-template flag), dashboard collapsed to a three-tile row of Critical / Open (New) / Open, and `GET /vehicles/` now returns the whole active fleet for any authenticated user since the service-vehicle pool isn't multi-tenant. Dashboard 7-day agenda strip v3.17.478 — new **Upcoming** card mixes ScheduledTask assignments and tickets (`resolution_due_at`) per day, with the same items folded into the full `/dispatch/calendar` month page; backend gains `GET /dispatch/upcoming/` and extends `/dispatch/calendar/` to emit both kinds with a `kind` discriminator. Vault edits + ticket billing + schedule-on-calendar v3.17.479 — mobile vault is no longer read-only (create/edit/rotate gated on `vault_create`/`vault_edit`), ticket detail surfaces a Billing rollup card with total/billable/non-billable minutes plus a contract progress bar for block-hours clients, and the calendar gains a "Schedule on this day" action that drops a new ScheduledTask onto the picked day. Backend gains POST/PATCH on `/vault/`, POST on `/dispatch/tasks/`, and `resolution_due_at` on the ticket PATCH so tickets can be scheduled too. Mobile asset editing + vault linking v3.17.480 — asset detail gains an Edit form covering identity / hardware / OS / notes fields (gated on `assets_edit`), plus a "+ Link vault entry" picker scoped to the asset's organization and an Unlink action per linked secret. Backend adds PATCH on `/assets/<id>/` and POST/DELETE on `/assets/<id>/vault-links/` — both rejecting cross-org link attempts. Mobile public-beta release prep v3.17.481 — new `/beta-onboarding/` public page (Django view + template rendering `docs/BETA_ONBOARDING.md`), full Play Store walkthrough doc at `docs/PLAY_STORE_BETA.md`, updated listing + Data Safety drafts, mobile-side Sentry hook + Beta banner + permission allowlist (drops `RECORD_AUDIO` / `SYSTEM_ALERT_WINDOW` / legacy storage perms). Local AAB build blocked on an `expo-modules-core@1.12.26` Gradle publishing-config issue; three resolution paths documented.)*
- Auth: Azure SSO + email/password fallback; session-token cookie not used (mobile uses long-lived bearer).
- Screens: Dashboard / My Tickets / Active Ticket / Clock In-Out / Map / Settings.
- Background location: foreground-only by default, opt-in for background; iOS "Always" permission requested only for techs who enable Always-on auto-time.
- Push notifications via FCM/APNS for ticket assignment, clock-in reminders, geofence exit prompts.

### Sub-phase 8.5 — Privacy + safeguards *(shipped v3.17.411–416)*
- **Off-shift suppression**: GPS pings outside the tech's `WorkingHours` (Phase 2) are dropped at the API layer — never stored. *(shipped v3.17.410 — 204 + audit-log `locations_dropped_offshift`)*
- Per-tech UI to view + delete their own location history. *(shipped v3.17.415 — `/field-ops/my-location-history/`)*
- Org-admin retention policy (default: 90 days). *(model + prune mgmt cmd shipped v3.17.411; org-admin UI shipped v3.17.416 — `/field-ops/settings/`)*
- Geofence-only mode: store only "entered/exited geofence X at time T", never raw lat/lon. *(shipped v3.17.415 — `OrganizationFieldOpsSettings.geofence_only_mode` + `GeofenceVisit` model + locations endpoint integration)*
- Audit trail of every location-history view + export. *(shipped v3.17.415–416 — every view, delete, geofence-only write, and settings change emits an `AuditLog` row)*

**Dependencies:** Phase 2 (`WorkingHours` for off-shift suppression). Recommended before Phase 3 (so timeclock data flows into utilization reporting).

**Sizing:** **L** — backend foundation 2 weeks, auto-time engine 2 weeks, timeclock UI 1-2 weeks, mobile app build 4-6 weeks, privacy hardening 1 week. ~10-13 weeks total. Sub-phase 8.1 is the first concrete deliverable and is a useful release on its own (web-only timeclock + GPS API endpoints) even before any mobile app ships.

---

## What's explicitly NOT in this plan

- Multi-currency beyond per-record `currency` field
- Multi-language support beyond Django i18n hooks
- ~~Native mobile apps (PWA only — per memory)~~ → **moved into Phase 8**
- Marketplace/app store
- White-label tenant branding beyond per-org logo

---

## Sizing

| Phase | Size | Estimated effort | Dependencies |
|---|---|---|---|
| 1 — Contract engine | M | 2-3 weeks | none — **1.1 + 1.2 shipped (v3.17.126 / v3.17.130)** |
| 2 — Resource mgmt | M | 2-3 weeks | none |
| 3 — Financial reporting + BI | L | 4-6 weeks | 1, 2 — **complete (v3.17.139–147)** |
| 4 — Procurement | L | 4-5 weeks | none (ideally after 1) |
| 5 — CRM | L | 4-5 weeks | none |
| 6 — ITIL | M | 2-3 weeks | none |
| 7 — Outsourcing + ecosystem + polish | Continuous | **complete (v3.17.207); 2 polish waves closed at v3.17.187 + v3.17.205** | ran alongside Phases 1-6 |
| 9 — Security alert ingestion (EDR / AV / Firewall) | M | 5 weeks — **framework + 1 reference adapter shipped v3.17.168** | none — can run alongside any |
| 10 — Advanced Email-to-Ticket Engine | M | 2-3 weeks — **all sub-phases complete (10.1 v3.17.176; 10.2 v3.17.177; 10.3 v3.17.188; 10.4 v3.17.189)** | extends existing IMAP poller |
| 11 — Advanced Dispatch & Tech Scheduling | M | **complete (11.1 v3.17.194; 11.2 v3.17.208; 11.3 v3.17.209); geo-aware deferred to Phase 8** | extends Phase 2 + dispatch board |
| 12 — Customer Communication Workflows | M | **complete (CSAT v3.17.231; announcements v3.17.232; brand + prefs v3.17.233; KB v3.17.234; voting v3.17.235; escalation v3.17.236; threading v3.17.237; SMS v3.17.238; client approvals v3.17.239); secure messaging deferred** | extends customer portal |
| 13 — Procurement & Lifecycle Mgmt | M | 2-3 weeks | extends Phase 4 |
| 14 — Visual Workflow Automation Engine | L | 4-5 weeks | extends workflow rules engine |
| 15 — Recurring Billing & Contract Mgmt | M | 3-4 weeks | extends Phase 1 |
| 16 — Documentation Relationship Mapping | M | 2-3 weeks | none |
| 17 — Advanced Asset Intelligence | L | 4-5 weeks | extends RMM sync |
| 18 — Multi-Location Client Hierarchy | M | 2-3 weeks | none |
| 19 — Advanced Reporting & Analytics | Continuous | ongoing | extends Phase 3 |
| 20 — Approval & Change Management Workflows | M | 2-3 weeks | extends Phase 6.1 |
| 21 — Advanced Mobile Technician Workflows | L | 4-6 weeks | requires Phase 8 |
| 22 — Knowledge Base & SOP Management | M | 2-3 weeks | extends KB v3.17.128/134 |
| 23 — Security Event & Incident Workflows | L | 4-6 weeks | shipped v3.17.337–363 (extends Phase 9 + 17) |
| 25 — Mature Timesheet Approval Workflows | M | 2-3 weeks | extends Phase 2 + approvals |
| 26 — Custom Report Writer + Saved Queries | L | 4-5 weeks | extends Phase 3.5 + 3.6 |
| 27 — Advanced Accounting Reconciliation | M | 2-3 weeks | extends QBO/Xero connection |
| 28 — Browser Extension + Offline Vault Access | L | 4-5 weeks | separate codebase |
| 31 — Vault GeoIP / IP / Time Access Rules | S | shipped v3.17.163 | extends FirewallMiddleware GeoIP infra |
| 32 — Remote Network Discovery Import | M | 2-3 weeks | future / late-stage — non-RMM, scoped, single-use tokens |
| 33 — Network Discovery & Auto Documentation | L | 4-6 weeks | extends Phase 32 + Phase 16 |
| 34 — Network Configuration Backup | M | 2-3 weeks | extends Phase 33 + Phase 9 alerts |
| 35 — Advanced Project Management | L | 4-5 weeks | extends `psa.Project` (v3.17.213 quote→project shipped) |
| 36 — Agreement Reconciliation & Pre-Invoice Approval | M | 2-3 weeks | extends Phase 1 + 15 + 20 |
| 37 — Vault Approval & Break-Glass Workflow | M | 2-3 weeks | extends Phase 31 (VaultAccessRule) + Phase 20 |
| 38 — Client Onboarding / Offboarding Runbooks | M | 2-3 weeks | extends `processes/` + Phase 14 |
| 39 — Compliance Evidence Packs | M | 2-3 weeks | extends Phase 9 + vault + monitoring + psa |
| 40 — Public / Client-Facing Status Page | M | 2-3 weeks | extends monitoring + psa Tickets |
| 41 — Compliance Frameworks & Recertification | M | shipped v3.17.435–444 | extends accounts + audit + reports.pdf_export (Phase 19); built atop Phase 39 evidence-pack infra |
| 42 — Docker / Containerized deployment | S | shipped v3.17.490 | none — packaging only; classic `bash install.sh` path unchanged |
| 43 — Multi-Organization REST API Access | S | shipped v3.17.496 | extends Phase 18 hierarchy; backward-compatible (default key scope unchanged) |
| 44 — Full Two-Way Accounting Sync | L | 4-6 weeks | extends Phase 27 + the AccountingConnection OAuth pattern; requested in GitHub #145 |
| 45 — System-wide Appearance Controls | S | shipped v3.17.527 | `SystemSetting` + existing per-user background fields |
| 8 — Mobile apps + GPS auto-time + Timeclock | L | **shipped v3.17.354–417 (extends Phase 2 + 18 + 21)** | Phase 2 (WorkingHours); positioned last as the largest single undertaking |

**Phases 1-6**: ~4 months of focused work at the established cadence.

**Phase 8** adds another ~2.5-3 months on top, but sub-phase 8.1 (web timeclock + GPS APIs) is shippable as a 2-week chunk well before the mobile app itself.

**Phases 10-30**: long-term operational deepening. None should be positioned as fully implemented today; each extends or adds to the foundations already shipped. Items overlapping shipped phases call out the deltas explicitly. AI-assisted features are explicitly **OPTIONAL AI** and gated by `psa_ai_enabled` (existing pattern from v3.17.125 AI Triage).

**Scope note:** This is a PSA + Asset + Vault + Documentation + Monitoring platform that integrates with external RMMs (Phase 9 connection framework + Phase 7 Integration SDK). First-party RMM agents and remote-access relays aren't on the roadmap — installs that need those capabilities use the supported third-party tools (TacticalRMM, NinjaOne, Datto RMM, ConnectWise Automate, ScreenConnect, RustDesk, MeshCentral, etc.).
