# PSA Roadmap

Living document for the native PSA built into clientst0r. Tracks what
ships now (the foundation), what's queued, and how each workstream
plugs into existing models so we don't duplicate.

## Guiding principles

1. **Off by default.** Both the global `core.SystemSetting.psa_enabled`
   and every per-surface flag default OFF. Auto-detect opts clients with
   an external PSA out completely.
2. **Reuse over rebuild.** Every PSA model FKs into existing infrastructure
   (`core.Organization`, `assets.Contact`, `assets.Asset`, `vault.Password`,
   `docs.Document`, `scheduling.ScheduledTask`, `audit.AuditLog`,
   `accounts.Membership`/`RoleTemplate`, `core.Webhook`, `integrations.*`).
   See `psa/INTEGRATION_MAP.md`.
3. **Permissions everywhere.** All PSA writes go through
   `@require_write` (Editor+); destructive actions through
   `@require_admin`. Per-feature granularity moves to the existing
   `accounts.RoleTemplate` boolean fields as we add them — see the
   "Permissions plan" section at the bottom.
4. **Audit everything.** Every mutation calls `AuditLog.log(...)`.
5. **Tenant scoping is non-negotiable.** All querysets go through
   `_scoped_ticket_qs(request)` (or equivalent for non-Ticket models).
6. **Native PSA only for clients without another PSA.** Active
   `integrations.PSAConnection` is a hard opt-out, no override.

## Status legend

- ✅ shipped
- 🟡 in progress / partial
- 🔵 next up
- ⚪ planned

---

## Workstream 1 — Ticketing / Service Desk

> Multi-channel ticket intake, SLA management, routing, and resolution workflows.

### Shipped
- ✅ **Phase 1 foundation** (v3.17.70) — `psa.Ticket` with the full spec
  field set (auto-numbered `PSA-YYYY-NNNNNN`), `Queue`, `TicketStatus`,
  `TicketPriority`, `TicketType`, `TicketComment`, `TicketAttachment`,
  `ClientPSASettings`. Seed mgmt command (`psa_seed_defaults`) populates
  7 queues, 10 statuses, 5 priorities (P1..P5 with default SLA targets),
  14 ticket types.
- ✅ **Global ticket list with filtering** (v3.17.79) — client / status /
  priority / queue / assignee / search. URL-driven so admins can bookmark
  a view.
- ✅ **Phase 2a service-desk depth** (v3.17.80) — reply / internal note
  posting, attachments (25 MB cap, MIME allowlist, sanitised filenames),
  quick actions (assign-to-me, status change, reopen, close-with-required-
  resolution-summary), closure categories.
- ✅ **Vault context** (v3.17.70) — read-only metadata view of a client's
  vault entries on each ticket; "Open in Vault" deep-links never inline
  secrets, every open is audit-logged.
- ✅ **Phase 2b watchers + canned replies** (this version) — subscribe
  for emails on activity; reusable comment templates with variable
  substitution (`{{ticket.number}}`, `{{ticket.subject}}`,
  `{{ticket.client}}`, `{{user.first_name}}`, etc.).

### Queued
- 🔵 **Multi-channel intake** (Workstream 8 dependency): email-to-ticket,
  alert API ingestion, anonymous portal form. Per-surface flags already
  exist on `core.SystemSetting`.
- ⚪ **Ticket merge / split** — high-risk; reserved for a focused session
  with red-team tests for data-integrity invariants.
- ⚪ **@mentions in comments** — user picker autocomplete + email notify.
- ⚪ **Recurring issue detection** — similarity match by subject/asset/client.
- ⚪ **Hygiene checks** — flag tickets missing asset / no time / no
  resolution / no KB link.
- ⚪ **SLA engine** — business-hours, holidays, pause-on-waiting-client,
  warning + breach thresholds, escalation rules. Defaults already on
  `TicketPriority.response_target_minutes` / `resolution_target_minutes`.
- ⚪ **Approvals workflow** — request approval, manager sign-off, audit chain.

---

## Workstream 2 — Time & Expense Tracking

> Billable vs. non-billable time, mobile capture, approvals.

### Status: ⚪ planned

### Models (planned)
- `psa.TicketTimeEntry(ticket, user, started_at, ended_at, duration_minutes,
  is_billable, rate_override, notes, expense_category, approved_by,
  approved_at)`
- Reuses `auth.User` for the technician. FK to `psa.Ticket` — every entry
  rolls up to a ticket (which already FKs to Organization).
- Mobile capture: PWA already shipped; we add a "start timer" button on
  the ticket detail page that posts to `/psa/t/<num>/timer/start/` and
  `.../stop/`. State stored in browser localStorage so closing the app
  doesn't lose the running timer.

### Approvals path
- New `accounts.RoleTemplate.psa_time_approve` boolean. Manager-role users
  can review/approve via a queue under Settings → PSA → Time Review.
- Audit-logged on every state transition.

---

## Workstream 3 — Project & Task Management

> Onboarding, break-fix, recurring projects, milestones.

### Status: ⚪ planned

### How it plugs in
- The existing `processes/` Django app already has a `ProcessExecution`
  model with `psa_ticket` FK and audit fields. **Do not duplicate.**
  PSA projects = `processes.Process` instances, with a `psa.Project`
  side-car holding the multi-ticket linkage:
  - `psa.Project(name, organization, owner, process, started_at,
    due_at, status, milestone_set, ...)`
  - `psa.ProjectTask(project, ticket, sort_order)` — child tickets
    are first-class `psa.Ticket` rows; the project is the umbrella.
- Recurring projects driven by the existing `scheduling.ScheduledTask`
  (`recurrence` + `recurrence_interval_days` + `spawn_next_occurrence()`)
  — the recurrence kicks the project from a Process template.

---

## Workstream 4 — Resource Scheduling & Utilization

> Technician capacity planning and skills-based assignment.

### Status: ⚪ planned

### How it plugs in
- Reuses `scheduling.ScheduledTask` for the dispatch calendar.
- New `psa.TechnicianProfile(user, skills_json, hours_per_week,
  vacation_calendar_url)` keyed on User. Skills as a JSON array of
  string tags (free-form for v1, taxonomy-driven later).
- Auto-assignment heuristic: when a ticket is created without an
  assignee, we score eligible technicians by skill match + current
  load and suggest top 3 (one-click accept). Manual override always
  wins.

---

## Workstream 5 — Contract & Billing

> Managed services agreements, usage-based billing, recurring invoices,
> automated revenue recognition.

### Status: ⚪ planned (Phase 2c at the earliest)

### Models (planned)
- `psa.Contract(organization, name, type [block_hours|t_and_m|retainer|
  msp_msa], started_at, ended_at, monthly_rate, included_hours,
  emergency_rate, after_hours_rate, currency, billing_cycle, ...)`
- `psa.ContractBalance(contract, period_start, period_end,
  hours_consumed, hours_remaining, dollars_billed, ...)`
- Time entries roll up against contracts at billing-cycle close.
- Invoicing: integration with QuickBooks Online + Xero (Workstream 8).
  Stay out of the actual accounting business — just hand over invoice
  drafts.
- Revenue recognition: ship balance reports, do NOT replace an
  accounting system.

---

## Workstream 6 — Reporting & Dashboards

> Profitability per client/ticket, utilization rates, SLA compliance,
> financial metrics.

### Status: 🔵 next — extends existing `reports/` app

### How it plugs in (verified against the live `reports/` app)
- `reports.generators.REPORT_GENERATORS` is a class-registry dict at
  `reports/generators.py:286-295`. Each report inherits `ReportGenerator`
  and implements `generate()` returning a dict that lands in
  `GeneratedReport.file` (CSV/PDF/Excel/JSON via the existing
  `FORMAT_CHOICES` model field).
- Add a new `psa_*` family of generator classes alongside the existing
  `AssetSummaryReport`, `PasswordAuditReport`, `MonitorUptimeReport` —
  same shape, no new infra.
- Surface link goes on `templates/reports/home.html` quick-actions
  block as a "PSA Reports" tile pointing at a new `reports:psa_list`
  view.
- All proposed PSA reports verified as single-ORM-call feasible
  (Open tickets by client, SLA breaches in N days, avg response/
  resolution time, billable hours by client via TicketTimeEntry
  rollup, recurring issues by asset, tickets by queue/type/priority).
- No chart library is wired in today — first PSA report that needs a
  chart pulls in Chart.js via CDN; later we centralise.
  - Open tickets / SLA warnings / SLA breaches
  - Response time and resolution time distributions
  - Tickets by client / tech / queue / type
  - Recurring issues, noisy assets
  - CSAT (per Workstream 1 — survey-after-close)
  - Billable time and contract utilization
  - Portal usage, SMS-alert usage
  - Calendar-dispatch performance
- Profitability and financial metrics light up after Workstream 5.

---

## Workstream 7 — Client Portal

> Self-service access for clients to submit tickets and view status.

### Status: ⚪ planned (Phase 3)

### Hard constraints
- **Internal notes never reach the portal.** The `is_internal` flag on
  `TicketComment` and `TicketAttachment` is already in place; portal
  querysets MUST filter them out at the queryset layer with a
  red-team test asserting non-leakage.
- **Vault data never reaches the portal.** `vault.Password` is staff-only
  forever. The vault context page (`/psa/t/<num>/context/`) requires
  full staff auth — the portal is a separate Django app with its own
  middleware.
- Per-client opt-in — the client's `ClientPSASettings.portal_enabled`
  (PSA → Settings → Per-customer PSA settings, or sending a portal
  invite) must be on. Default OFF. There is no global portal switch: the
  unused `SystemSetting.psa_portal_enabled` was removed in core 0087.
- There is no anonymous ticket form. Its global and per-client switches
  were never read and were removed (core 0087, psa 0083); a public form
  would need its own design, with rate-limiting via `django-ratelimit`.

### Routes (planned)
- `/portal/login/`, `/portal/tickets/`, `/portal/tickets/new/`,
  `/portal/tickets/<num>/`, `/portal/tickets/<num>/reply/`,
  `/portal/tickets/<num>/close/`, `/portal/service-catalog/`,
  `/portal/kb/`, `/portal/assets/` (filtered to client),
  `/portal/calendar/`, `/portal/announcements/`.

---

## Workstream 8 — Integrations

> Especially with RMM tools, accounting (QuickBooks, Xero), Microsoft
> 365, and distributors.

### Existing — reuse, do NOT duplicate
- ✅ **PSA sync (third-party PSAs)** — `integrations.PSAConnection`
  already supports Alga, Autotask, ConnectWise Manage, Freshservice,
  HaloPSA, ITFlow, Kaseya BMS, RangerMSP, Syncro, Zendesk. Native PSA
  auto-opts-out clients on these.
- ✅ **RMM sync** — Atera, ConnectWise Automate, Datto, NinjaOne, Tactical
  RMM. Live in `integrations/`.
- ✅ **Microsoft 365 / Entra** — `integrations.M365Connection` (msal-based).
- ✅ **Network & cloud** — Unifi, Omada, Grandstream.

### Queued
- 🔵 **Distributor integrations** (under PSA) — pricing + stock + ordering:
  - Ingram Micro (Xvantage API)
  - Synnex/TD Synnex
  - D&H Distributing
  - ScanSource
  - Tech Data (now part of TD Synnex)
  - Pax8 (cloud distributor)
  - QBS Software
  - Westcoast
  - Implementation pattern (verified against existing `integrations/`):
    - **`integrations.DistributorConnection`** model parallel to `PSAConnection`
      — same encrypted-credentials pattern via `vault.encryption.encrypt_dict()`
    - **`integrations/providers/distributors/`** directory with one module per
      distributor (`ingram_xvantage.py`, `synnex.py`, `d_and_h.py`,
      `scansource.py`, `pax8.py`)
    - Each registers in `integrations.providers.PROVIDER_REGISTRY` (dynamic
      lookup via `get_provider(connection)`)
    - **`BaseDistributorProvider`** extends `BaseProvider` with a fresh
      interface — distributors don't share PSA's company/contact/ticket
      shape; they have catalog/pricing/stock/order/webhook:
      - `test_connection() → bool`
      - `list_products(...)`
      - `get_pricing(sku, qty)`
      - `check_stock(sku, location)`
      - `place_order(items, customer, ...)`
      - `handle_webhook(payload)` — for ASN / order-status updates
    - **New management command** `sync_distributor` mirrors `sync_psa`;
      registers as `'distributor_sync'` task type in `core.ScheduledTask`.
    - **Webhook receivers don't exist yet** in `integrations/` — distributors
      will be the first surface to add them. URL pattern:
      `path('webhooks/<provider>/<token>/', views.distributor_webhook, ...)`
      with HMAC signature verification.
    - **Service catalog** (Workstream 1) becomes the consumer: a ticket for
      "new computer" can fetch live pricing from multiple distributors and
      let the tech pick.
    - Confirmed greenfield — `grep -r 'ingram\|synnex' .` returns zero hits
      across the existing codebase.
- 🔵 **Accounting** — QuickBooks Online + Xero. Output-only (push invoice
  drafts, never read GL data); driven by Workstream 5.
- ⚪ **Webhook outbound** — Workstream 9 dependency.

---

## Workstream 9 — Automation & Workflows

> Rules-based actions, approvals, notifications.

### Status: 🟡 partial (the existing `processes/` app already covers a
> chunk of this)

### Existing
- `processes.Process` + `ProcessExecution` already runs templated
  workflows linked to a `psa_ticket`. Audit log fields exist.
- `core.Webhook` + `WebhookDelivery` already power outbound HTTP events.

### Planned for PSA
- **Workflow engine** wired to PSA-native triggers — extend `processes`,
  don't fork:
  - Triggers: `ticket_created`, `ticket_updated`, `status_changed`,
    `priority_changed`, `assignment_changed`, `client_replied`,
    `tech_replied`, `comment_added`, `calendar_event_created`,
    `SLA_warning`, `SLA_breach`, `ticket_idle`, `ticket_closed`,
    `ticket_reopened`, `rmm_alert_received`, `vault_context_opened`.
  - Actions: `assign_user`, `assign_queue`, `set_priority`,
    `set_status`, `send_email`, `send_sms`, `send_desktop_alert`,
    `create_calendar_event`, `create_reminder`, `request_approval`,
    `create_child_ticket`, `add_internal_note`, `link_asset`,
    `suggest_kb`, `escalate_to_manager`, `webhook_outbound`.
- All actions are audit-logged. All triggers respect tenant scoping.

---

## Permissions plan

PSA actions map to `accounts.RoleTemplate` booleans. Existing template
roles: Owner, Administrator, Editor, Help Desk, IT Manager, Documentation
Writer, Read-Only.

| Capability | Boolean field on RoleTemplate | Default by role |
|---|---|---|
| View tickets (own org) | (existing org membership) | every role |
| View all tickets cross-org | `psa_view_all` | Owner, Administrator |
| Create / comment | `psa_write` | Editor and above |
| Quick close / reopen | `psa_resolve` | Help Desk and above |
| Assign others | `psa_assign_others` | IT Manager and above |
| Manage canned replies | `psa_manage_canned` | Administrator |
| Manage SLA / queues / types / priorities | `psa_manage_config` | Administrator |
| Manage time entries (own) | `psa_time_log` | Help Desk and above |
| Approve time entries | `psa_time_approve` | IT Manager and above |
| Manage contracts / billing | `psa_billing` | Administrator |
| Configure global PSA settings | superuser only | superuser only |
| Manage distributor connections | `psa_distributor_admin` | Administrator |
| Run / configure workflows | `psa_workflow_admin` | Administrator |

Flagged the columns on `RoleTemplate` as we ship each workstream.
Existing decorators (`@require_write`, `@require_admin`, `@require_owner`)
gate the foundation; per-feature granularity comes online with the
matching workstream.

---

## Calendar / scheduling integration — already in place

Native PSA reuses `scheduling.ScheduledTask` for dispatch and reminders.
The existing model already carries:
- `recurrence` + `recurrence_interval_days` + `spawn_next_occurrence()` →
  recurring service tickets
- `alert_email` / `alert_sms` / `alert_before_hours` → reminder cadence
- `psa_ticket` FK → existing `integrations.PSATicket` (third-party). New
  native tickets use `Ticket.related_calendar_event` → `ScheduledTask`.

No duplicate calendar model. Workstream 4 schedules technicians on this
existing surface.

---

## Phasing

- **Now (shipped):** Phase 1 foundation, vault context, admin warnings,
  global filtered list, Phase 2a depth, Phase 2b watchers + canned replies.
- **Next session — Phase 2c:** ticket merge / split, recurring detection,
  hygiene scores, @mentions.
- **Phase 3:** SLA engine + workflow engine + email-to-ticket + alert API.
- **Phase 4:** client portal (with red-team isolation tests).
- **Phase 5:** time tracking + contracts + reports.
- **Phase 6:** distributor integrations (Ingram, Synnex, D&H, Pax8, …).
- **Phase 7:** accounting connectors (QBO, Xero) — output-only.
- **Phase 8:** Workstream 10 — AI-assisted ticketing (Suggested Replies + Suggested Actions).

Update this doc whenever scope shifts.

---

## Workstream 10 — AI-assisted ticketing

> AI Suggested Replies + AI Suggested Actions, with strict human-in-the-loop
> guardrails. Optional, enabled in Settings → PSA. No AI-generated reply
> reaches a client and no action is applied without explicit human approval.

### Status: ⚪ planned — full spec below; awaiting go-ahead to implement.

### 1. Feature Overview — business value

For an MSP team running on Client St0r, the bottleneck is rarely the
ticketing system itself; it's the cognitive load on technicians of
context-switching between clients. AI assists with:

- **Suggested Replies** — drafts a client-facing email/portal reply that
  pulls together the ticket history, linked assets, RMM telemetry, and
  relevant KB articles. The technician edits and approves before send.
- **Suggested Actions** — recommends the next step (status / priority /
  assignee change, KB link, RMM script run, follow-up task creation,
  workflow start, escalation, time-entry draft). The technician picks
  what to apply.

Both run on top of `psa.Ticket` (native) AND `integrations.PSATicket`
(third-party-synced) so the same UI works regardless of where the
ticket lives.

### 2. Detailed user flows

| Role | View suggestions | Approve / send / apply |
|---|---|---|
| **L1 Technician** | yes (replies + actions) | view + copy reply text only · request approval for send/apply |
| **L2 Technician** | yes | send low-risk replies (status updates, password resets, basic info); apply non-destructive actions (field updates, KB linking, internal tasks); needs approval for sensitive replies (billing, outages, escalations) and any destructive action |
| **L3 / Senior Engineer** | yes | approve and send most replies; apply most actions including approved RMM scripts and basic workflow starts |
| **Team Lead / Supervisor** | yes | approve high-risk replies and actions; create / assign complex workflows; configure routing rules |
| **Admin / Owner** | yes | full rights; configure thresholds, allowlists/blocklists, model selection, prompt templates, retention windows |

L1 → L2/L3 escalation flow:
1. L1 opens ticket, sees `AISuggestion` cards.
2. Clicks **Request approval** with optional context note.
3. `AISuggestion.review_state` flips to `pending_review`; an in-app
   notification + (optional) SMS ping fires for users with the
   `psa_ai_approve` permission in the same org.
4. Reviewer approves / rejects / edits-and-approves; outcome and final
   text saved in `AIActionLog`.
5. On approve, the system performs the actual action (send the reply via
   the same SMTP path as comment notifications, OR apply the action via
   the existing service layer).

### 3. Data model

Two new Django models in a NEW app `psa_ai/` so all AI-specific code
stays isolated. Both are scoped to `core.Organization` and audit-logged.

```python
# psa_ai/models.py (planning)
from django.conf import settings
from django.db import models


class AISuggestion(models.Model):
    """
    A single AI-generated suggestion attached to a ticket. Either a reply
    (kind='reply') or an action (kind='action'). Stored regardless of
    whether it ever gets applied — the rejected ones are training data.
    """
    KIND_CHOICES = [('reply', 'Reply'), ('action', 'Action')]
    REVIEW_STATES = [
        ('draft', 'Drafted by AI — awaiting tech review'),
        ('pending_review', 'Awaiting senior approval'),
        ('approved', 'Approved (and applied)'),
        ('rejected', 'Rejected by reviewer'),
        ('expired', 'Expired before action'),
        ('superseded', 'Replaced by a newer suggestion'),
    ]
    RISK_LEVELS = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]

    # Tenant + ticket — supports BOTH native and synced PSA tickets via
    # generic FK. (Two FKs is simpler than ContentType + object_id and
    # keeps DB constraints meaningful.)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                    related_name='ai_suggestions')
    native_ticket = models.ForeignKey('psa.Ticket', null=True, blank=True,
                                     on_delete=models.CASCADE,
                                     related_name='ai_suggestions')
    psa_ticket = models.ForeignKey('integrations.PSATicket', null=True, blank=True,
                                  on_delete=models.CASCADE,
                                  related_name='ai_suggestions')

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    risk_level = models.CharField(max_length=20, choices=RISK_LEVELS, default='medium')
    review_state = models.CharField(max_length=20, choices=REVIEW_STATES, default='draft')

    # Generation metadata
    model_name = models.CharField(max_length=100)        # e.g. 'claude-sonnet-4-6'
    model_version = models.CharField(max_length=50, blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=2,  # 0.00 – 1.00
                                    help_text='Model self-rated 0–1 confidence')
    prompt_version = models.CharField(max_length=50, blank=True)

    # Reply content (when kind='reply')
    suggested_body = models.TextField(blank=True)
    final_body = models.TextField(blank=True,
                                 help_text='What was actually sent (after edits)')

    # Action payload (when kind='action')
    action_type = models.CharField(max_length=50, blank=True)
    action_payload = models.JSONField(default=dict, blank=True,
                                     help_text='e.g. {"new_status_id": 5} or '
                                               '{"workflow_id": 12, "assign_to": 7}')

    # Context audit — what we fed the model (so we can replay/diagnose)
    context_snapshot = models.JSONField(default=dict, blank=True,
                                       help_text='Subject, recent comments, '
                                                 'linked assets, RMM data hash, '
                                                 'KB article ids — never secrets')

    # Review trail
    created_at = models.DateTimeField(auto_now_add=True)
    requested_review_at = models.DateTimeField(null=True, blank=True)
    requested_review_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                           blank=True, on_delete=models.SET_NULL,
                                           related_name='+')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True,
                                    help_text='Why approved/rejected/edited')

    class Meta:
        db_table = 'psa_ai_suggestions'
        indexes = [
            models.Index(fields=['organization', 'review_state', '-created_at']),
            models.Index(fields=['native_ticket', '-created_at']),
            models.Index(fields=['psa_ticket', '-created_at']),
        ]

    def ticket_obj(self):
        return self.native_ticket or self.psa_ticket


class AIActionLog(models.Model):
    """
    Append-only record of every AI action applied to a ticket. Distinct
    from AISuggestion (which is the proposal) — this records the OUTCOME.
    """
    suggestion = models.ForeignKey(AISuggestion, on_delete=models.CASCADE,
                                  related_name='action_logs')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                    related_name='ai_action_logs')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name='+')
    applied_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField()
    error = models.TextField(blank=True)
    diff = models.JSONField(default=dict, blank=True,
                           help_text='Before/after for fields that changed')

    class Meta:
        db_table = 'psa_ai_action_logs'
        ordering = ['-applied_at']
```

Existing `audit.AuditLog` ALSO writes one row per suggestion creation,
review, and apply — `AIActionLog` is the structured side-car, `AuditLog`
is the immutable audit trail.

### 4. RBAC matrix

We add **eleven** new boolean fields to `accounts.RoleTemplate`. Existing
four roles stay; technician levels are layered on top via the existing
template system (Help Desk = L1, IT Manager = L3 by default; admins
configure beyond that).

| Capability | RoleTemplate boolean | L1 | L2 | L3 | Lead | Admin |
|---|---|:-:|:-:|:-:|:-:|:-:|
| View AI suggestions | `psa_ai_view` | ✅ | ✅ | ✅ | ✅ | ✅ |
| Send AI reply (low-risk) | `psa_ai_send_low_risk` | — | ✅ | ✅ | ✅ | ✅ |
| Send AI reply (high-risk) | `psa_ai_send_high_risk` | — | — | ✅ | ✅ | ✅ |
| Approve someone else's reply | `psa_ai_approve_reply` | — | — | ✅ | ✅ | ✅ |
| Apply AI action (low-risk) | `psa_ai_apply_low_risk` | — | ✅ | ✅ | ✅ | ✅ |
| Apply AI action (high-risk) | `psa_ai_apply_high_risk` | — | — | ✅ | ✅ | ✅ |
| Approve someone else's action | `psa_ai_approve_action` | — | — | — | ✅ | ✅ |
| Run AI-suggested RMM script | `psa_ai_run_script` | — | — | ✅ | ✅ | ✅ |
| Create / assign workflow from AI | `psa_ai_create_workflow` | — | — | ✅ | ✅ | ✅ |
| Modify financial fields via AI | `psa_ai_billing` | — | — | — | ✅ | ✅ |
| Configure AI (model, threshold, allow/blocklist) | `psa_ai_admin` | — | — | — | — | ✅ |

"Low-risk" / "high-risk" classification is set on the suggestion at
generation time by the model itself, validated server-side against the
admin-configurable allow/blocklist.

### 5. Backend implementation

```
psa_ai/
├── __init__.py
├── apps.py
├── models.py                  ← AISuggestion, AIActionLog
├── views.py                   ← list/detail/approve/reject/apply endpoints
├── urls.py
├── services/
│   ├── __init__.py
│   ├── context_builder.py     ← assembles ticket context (history, assets,
│   │                            RMM, KB) — never includes vault secrets
│   ├── reply_generator.py     ← Anthropic SDK call, prompt cache hits
│   ├── action_generator.py    ← Anthropic SDK call, structured-output
│   ├── action_applier.py      ← dispatches to the right service per
│   │                            action_type (psa, processes, integrations)
│   └── guardrails.py          ← confidence/threshold/blocklist checks
├── prompts/
│   ├── system_reply.md        ← versioned system prompt (file-based for
│   ├── system_action.md         git diff visibility)
│   └── examples/              ← few-shot examples per action_type
├── permissions.py             ← per-action permission resolvers
├── signals.py                 ← optional auto-generate on ticket events
├── admin.py
├── migrations/
└── tests/
```

Service layer pattern (mirrors `core/system_warnings.py`):

```python
# psa_ai/services/action_applier.py
class ActionApplier:
    """Dispatches an approved AISuggestion to the right downstream service.
    Each action_type maps to a small adapter; new actions register here."""

    def apply(self, suggestion: 'AISuggestion', actor: 'User') -> 'AIActionLog':
        handler = self._handlers.get(suggestion.action_type)
        if handler is None:
            raise UnknownAction(suggestion.action_type)
        try:
            diff = handler(suggestion, actor)
            return AIActionLog.objects.create(
                suggestion=suggestion,
                organization=suggestion.organization,
                actor=actor, success=True, diff=diff,
            )
        except Exception as exc:
            return AIActionLog.objects.create(
                suggestion=suggestion,
                organization=suggestion.organization,
                actor=actor, success=False, error=str(exc)[:2000],
            )

    _handlers = {
        'set_status':       _set_status,
        'set_priority':     _set_priority,
        'assign_to':        _assign,
        'link_kb':          _link_kb,
        'create_followup':  _create_followup,
        'start_workflow':   _start_workflow,        # → processes app
        'run_rmm_script':   _run_rmm_script,        # → integrations app
        'add_internal_note':_add_internal_note,
        'draft_time_entry': _draft_time_entry,
        'escalate':         _escalate,
    }
```

Each handler is permission-checked AGAIN at apply time — defence-in-depth
beyond the role check on the approve button.

### 6. Frontend implementation

Bootstrap 5 + vanilla JS (no SPA). On the ticket detail page, a new
**right-rail card** below "Vault Context":

```
┌─ AI Assist ─────────────── ⚙ ──┐
│ ⚡ Suggested reply  conf: 0.84 │
│ ┌───────────────────────────┐  │
│ │ Hi Nina, thanks for the   │  │
│ │ note about the printer …  │  │
│ │              … (AI-Gen.)  │  │
│ └───────────────────────────┘  │
│ [Edit] [Approve & Send]        │
│ [Reject + Feedback]            │
│ ─────────────────────────────  │
│ Suggested actions:             │
│ □ Set status → Waiting Client  │
│ □ Link KB: HP printer offline  │
│ □ Start workflow: Printer Reset│
│ [Apply selected]               │
└────────────────────────────────┘
```

- **AI-Generated** badge on every suggestion card (yellow pill).
- **Confidence** number visible on every card; suggestions below the
  org's threshold are shown collapsed with a "Below threshold" banner.
- **Edit** opens an inline textarea pre-filled with `suggested_body`.
- **Approve & Send** posts to `/psa/ai/suggestion/<id>/approve/`.
- **Reject + Feedback** opens a modal asking *why* — text becomes
  `reviewer_note`, used as RLHF-style training data later.
- **Request approval** button when the user lacks the permission to
  send/apply directly — fires an in-app notification to qualifying
  reviewers and flips the state to `pending_review`.

Settings → PSA gets two new sections (admin only): **AI Assist** and
**AI Allow / Blocklist**.

### 7. Integration points

- **Pulling context** — `services/context_builder.py` pulls:
  - From `psa.Ticket` or `integrations.PSATicket`: subject, description,
    last 20 comments, linked asset, related KB.
  - From `assets.Asset`: model, hostname, last RMM check-in, recent alerts.
  - From `integrations.RMM*`: last 30 alerts/events for the asset (via
    the existing sync layer — no new RMM API calls).
  - From `docs.Document`: top 5 KB matches by similarity (Phase 1
    similarity = simple title/tag match; Phase 2 = pgvector).
  - **NEVER** reads `vault.Password.encrypted_password` or its plaintext.
- **Pushing actions back** — for synced PSA tickets, action handlers call
  the existing `integrations.PSAConnection` push API (same code path as
  the existing webhook outbound).

### 8. Prompt engineering

System prompts live in version-controlled `prompts/*.md` so changes
diff cleanly. A short reply prompt sketch:

```markdown
You are a senior MSP technician drafting a reply to a client ticket.

Voice: {{org.psa_ai_voice|default:"professional, concise, confident"}}
Brand name: {{org.name}}

Rules:
- Never include passwords, API keys, secrets, or internal-only notes.
- Never make up facts about the asset or its history. If you need data
  you don't have, say so explicitly.
- If the ticket is sensitive (billing, outage, escalation), mark the
  suggestion as risk_level=high.
- Output JSON: {body: "...", confidence: 0.0–1.0, risk_level: "low|medium|high"}

Ticket context:
<<<{{context_summary}}>>>

Most-recent client message:
<<<{{latest_client_message}}>>>

Draft a reply.
```

Anthropic SDK calls use **prompt caching** on the system prompt + the
context payload up to the most-recent message — TTL is 5 minutes, which
lines up with how often a tech is on the same ticket.

### 9. Guardrails & safety

- **`SystemSetting.psa_ai_enabled`** — global on/off, default OFF.
- **`SystemSetting.psa_ai_min_confidence`** — default `0.75`. Suggestions
  below this score are still stored but rendered collapsed; cannot be
  one-click approved.
- **Allowlist / blocklist** — JSON-backed config in Settings → PSA → AI:
  - `allowed_action_types` (default: low-risk only)
  - `blocked_clients` (no AI for these orgs)
  - `blocked_subject_keywords` (drop suggestion if subject matches)
- **Sensitive actions always require explicit approval** — even L3+ users
  must click an extra "I confirm this is correct" checkbox in a modal
  before the action runs. Recorded in the audit trail.
- **`AuditLog`** writes happen at: generate, request_review, approve,
  reject, apply, fail. All include `extra_data` with the prompt version,
  model name, and confidence.
- **`AIActionLog.diff`** is the structured before/after of the resulting
  change — used to roll back if something went sideways.
- **No PII to the model unless necessary** — `context_builder` strips
  email/phone fields from contacts unless the ticket type explicitly
  needs them. Vault entries → never sent.
- **Per-org rate limit** — `django-ratelimit` (already a dep) at
  `5/minute` per org by default.

### 10. Workflow integration

`processes.Process` and `processes.ProcessExecution` already exist with
ticket linkage. AI workflow actions:

- `start_workflow` action_type: payload `{process_template_id, assign_to}`.
- The action handler creates a `ProcessExecution` linked to the ticket
  via the existing `psa_ticket` FK (or the new `psa.Ticket` mirror once
  that field is added).
- Audit trail crosses both apps via the existing
  `processes.ProcessExecutionAuditLog`.
- **No new workflow primitives** — AI just CALLS the existing engine.

### 11. UI/UX recommendations

- Right-rail card on ticket detail (described above), collapsible.
- A new "AI Inbox" page at `/psa/ai/inbox/` — list of suggestions across
  all tickets the user can review, sortable by ticket priority and age.
  Default filter: "pending my approval".
- Approval modal has a clear **"AI-Generated — Review Before Sending"**
  banner that does NOT go away even if the tech edited the body.
- Color cues: low-risk = green outline, medium = yellow, high = red.
  Borrows the same hue palette as ticket priorities for muscle memory.
- Reject feedback modal asks one question: *"Why isn't this a good
  suggestion?"* with optional categories (factually wrong, wrong tone,
  too verbose, missing context, …). One click + comment.
- Every visible AI artifact has the **AI-Generated** badge. Always.

### 12. Edge cases, security, testing

- **Race**: two users approve the same suggestion. Use a row-level lock
  (`select_for_update()`) and a state-machine guard
  (`AISuggestion.review_state == 'draft'` required before flip).
- **Stale tickets**: suggestions older than `SystemSetting.
  psa_ai_suggestion_ttl_minutes` (default 60) auto-flip to `expired`.
- **Synced PSA conflict**: if the underlying ticket changed in the third-
  party PSA between generation and apply, the action_applier MUST refetch
  the current state and refuse if a conflict is detected.
- **Tenant isolation tests** — assert L1 in OrgA cannot see/approve a
  suggestion attached to OrgB's ticket. Same red-team test for staff users
  and superusers.
- **No-secrets test** — `context_snapshot` and `suggested_body` MUST NOT
  contain `encrypted_password`, `decrypt(`, the literal string of any
  vault entry's plaintext, or any `Authorization:` header value. Asserted
  by a dedicated fixture that creates a vault entry with a known
  plaintext sentinel and confirms it's nowhere in the suggestion artifacts.
- **Permission downgrade** — if a user's role drops between request and
  approve, the apply step rechecks permissions at execute time.
- **Model failure / timeout** — graceful: suggestion saved with
  `review_state='draft'` and `suggested_body=''`, marked as failed in the
  inbox with a retry button.
- **Cost ceiling** — per-org daily token budget on `SystemSetting.
  psa_ai_daily_token_limit`; over-budget falls back to a "AI assist
  paused for this client today" banner instead of generating.
- **GDPR / right-to-erasure** — `AISuggestion` and `AIActionLog` rows
  cascade with their `organization`. When a User is deleted,
  `actor`/`reviewer` go to `null` (existing pattern).

### Configuration surface (Settings → PSA → AI Assist)

- `psa_ai_enabled` (master switch, default OFF)
- `psa_ai_provider` (default `anthropic`)
- `psa_ai_model_replies` (default `claude-sonnet-4-6`)
- `psa_ai_model_actions` (default `claude-haiku-4-5-20251001` — actions
  are structured-output and cheaper)
- `psa_ai_min_confidence` (default 0.75)
- `psa_ai_suggestion_ttl_minutes` (default 60)
- `psa_ai_daily_token_limit` (default 200_000)
- `psa_ai_allowed_action_types` (default low-risk subset)
- `psa_ai_blocked_clients` (Organization multi-select)
- `psa_ai_blocked_subject_keywords` (newline-separated)
- `psa_ai_voice` (free-form sentence injected into the system prompt)

### LOC estimate / phasing

- **Phase 10a**: data model + suggestion CRUD UI + reply generation
  (read-only — generate, view, copy). ~1500 LOC.
- **Phase 10b**: action generation + low-risk action_applier handlers
  (status, priority, assign, link KB, internal note). ~1200 LOC.
- **Phase 10c**: high-risk handlers (workflow, RMM script, escalation),
  approval flow + AI Inbox. ~1500 LOC.
- **Phase 10d**: edits + reject-with-feedback loop + per-org configuration
  + cost guardrails + tests. ~1000 LOC.

Total: ~5200 LOC across ~3 sessions. Each phase ships independently
behind `psa_ai_enabled` so the existing PSA stays untouched.
