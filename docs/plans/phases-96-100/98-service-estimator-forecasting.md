# Phase 98 — Service estimator and forecast accuracy

**Priority:** P1 · **Size:** L · **Status:** planned · Roadmap: [Phase 98](../../ROADMAP.md) ·
Index: [Phases 96–100](README.md)

The shared compatibility and safety requirements in the [index](README.md) apply. This spec lists only what
is specific to Phase 98.

## 1. Goals and business value

- Estimate monthly support effort, labor cost and a price range for a target margin from a prospect's
  assessment, before the MSP commits to a price.
- The calculation engine is **deterministic and explainable**: every number shows its formula, inputs and
  assumptions, and the same inputs always give the same result. AI explains; it never produces a financial
  number.
- Unknown costs stay unknown. The estimator never invents licensing, vendor or labor costs.
- After conversion, compare forecast with actual hours, labor cost and profitability at 30, 60 and 90 days and
  beyond, separate onboarding effort from steady state, and recommend assumption changes that a person approves.
- Over time the MSP's own history tightens its estimates.

## 2. Existing components to reuse

| Need | Reuse | Notes |
|---|---|---|
| Prices, plans, tiers | `pricing/models.py` (`PriceBook`, `PriceBookItem`, `PriceTier`, `ServicePlan` with `minimum_users/devices/servers`, `included_support_hours`, `sla_matrix`; `ServicePlanItem`, `ServicePlanEntitlement`), `pricing/services.py` (`resolve_price`, `tier_total`, `coverage_for`) | Unset prices are NULL by design ("no guessed prices"). The pricing app has **no staff UI**: management is through Django admin (`pricing/admin.py`). |
| Labor rates and costs | `pricing/services.py` (`resolve_labor_rate`, `resolve_cost_rate`), `pricing.LaborRole`, `RateCard`, `resourcing.TechCostRate` (effective-dated, loaded cost), `reports/costing.py` (`RateBook`, unknown is `None`, never zero) | |
| Transparent calculations | `advisor/recommend.py` (`inp(label, value, unit, basis)`, `work(formula, steps, inputs, assumptions, unknown)`, `price_for_margin`, `required_monthly_for_target`) | `basis` already distinguishes verified, estimate and unknown. |
| Draft quote / contract with approval | `advisor/actions.py` (`accept`, `_draft_quote`, `_draft_contract`, `sync_implemented`), `crm/views.py` `opportunity_to_quote` | Never edits an active contract; drafts go through existing approval. |
| Actuals | `reports/queries.py` (`profitability_by_client` `:479`, `profitability_by_contract` `:500`, `technician_utilization` `:589`, `effective_hourly_rate_*`, `unbilled_time`), `psa.TicketTimeEntry` cost and bill-rate snapshots, `psa.Project.estimated_hours` / `budget_hours` | |
| Metrics surfaces | `executive/metrics.py` provider framework, `advisor` findings (`advisor/detectors.py` registry), `health_score/registry.py` signals | Forecast accuracy is a new executive provider and a new advisor detector, not a new dashboard. |
| AI explanations (OPTIONAL AI) | `advisor/ai.py` (`build_payload`, `_redact`, `MONEY_RE`, `PCT_RE`, `allowed_numbers`, `validate`, deterministic fallback, `Narrative` cache), `psa_ai/services/policy_call.py`, `core/ai_gate.py` | The figure validator is private to `advisor/ai.py`; 98.4 extracts it to a shared module with no behavior change for the advisor. |
| Assessment input | Phase 97 `crm.assessments.inputs_for(revision)` | Each input arrives with its state (answered, unknown) and verification. |

## 3. New functionality

### 3.1 Estimation models and rules (98.1)

An **estimation model** is a versioned, approved set of rules. No universal hours-per-device assumption is
built in; the MSP defines its own coefficients, and a starter model is shipped as a clearly labelled draft
with every coefficient marked "example — review before use".

- **Drivers:** per user, per endpoint (by class: desktop, laptop, Mac, mobile), per server (physical, virtual,
  by role), per location, per network device, per line-of-business application, per cloud tenant, and
  service-based rules (backup management, security stack, after-hours coverage, onsite visits).
- **Each rule** has low, expected and high hours per unit per month; one-time onboarding hours per unit; an
  optional link to a `PriceBookItem` or `ServicePlanItem`; a labor role for costing; and a condition over
  assessment inputs (the request-form condition format).
- **Allowances:** complexity and risk multipliers driven by assessment answers (for example technical-debt
  score, turnover rate, SLA tier, after-hours requirement), each bounded and listed in the explanation.
- **Margin targets:** install default and per service plan.
- **Versioning and approval:** editing creates a new draft version; a user with `estimator_approve_models`
  activates it. Estimates record the model version they used. Active versions are immutable.

### 3.2 Deterministic calculation engine (98.2)

A pure function `estimates.engine.calculate(inputs, model_version, rates)` with no database writes and no
randomness. For each rule it computes units × coefficients and applies allowances, then aggregates.

Outputs:

| Output | How |
|---|---|
| Monthly hours low / expected / high | Sum of rule ranges after allowances |
| One-time onboarding and remediation hours | Onboarding coefficients plus remediation items flagged in the assessment |
| Labor cost (monthly, one-time) | Hours × loaded cost rate per labor role (`resolve_cost_rate`, `TechCostRate`); unknown rate → cost unknown |
| Licensing and vendor expenses | Only from price book items with a known cost; anything else is listed as "unknown — needs a quote" with no number |
| Recommended monthly price range | `price_for_margin(cost, target)` for low / expected / high cost; shown alongside the plan's own price when a plan is chosen |
| Target and projected gross margin, projected gross profit | From price and known costs; flagged "incomplete" while any cost is unknown |
| Confidence | High / Medium / Low from a published formula: share of estimated hours that rest on verified inputs, minus penalties for unknown inputs and for rules without history |
| Assumptions and missing-data warnings | Every default used, every unknown input, every unknown cost |

Each figure carries a `work(...)` record (formula, steps, inputs with basis verified / estimate / unknown,
assumptions, unknowns), which is what the UI and any AI explanation display.

### 3.3 Estimates on the opportunity (98.3)

- "Create estimate" on an assessment revision (Phase 97) or on an opportunity with manual inputs.
- The estimate stores an input snapshot, the model version, rates used and all outputs, so it can be re-read
  later exactly as it was. Re-running creates a new estimate; earlier ones are kept.
- An estimate is **frozen** when a quote created from it is sent; frozen estimates are the baseline for
  forecast accuracy.

### 3.4 OPTIONAL AI explanations (98.4)

Gated by `psa_ai_enabled` and the MSP organization's AI policy. The AI receives the computed `work(...)`
records and assessment facts with names replaced by placeholders, and may:

- explain the estimate, its risks, missing information and suggested questions for the prospect;
- point out unprofitable or marginal prospects, plan fit, possible remediation projects, margin concerns and
  contract structure options;
- draft a summary, a customer-facing assessment summary or an executive proposal text.

Every figure in the AI's text must appear in the input (the extracted `advisor/ai.py` validator); otherwise the
deterministic summary is shown. AI never approves pricing, edits contracts or quotes, sends proposals, changes
models or coefficients, or commits anything.

### 3.5 Plan comparison and draft proposal (98.5)

- Compare up to three MSP-defined `ServicePlan`s (for example the MSP's own Basic, Standard and Premium) against
  the estimate: inclusions, exclusions, included hours versus estimated hours, plan price (from the price book),
  cost, margin and assumptions. Plans and prices come only from the MSP's data; a missing price is shown as
  missing.
- "Create draft quote" uses the advisor's draft pattern (`advisor/actions.py`): it creates a **draft** `psa.Quote`
  with lines from the chosen plan and one-time onboarding items, and never sends it. Because `psa.Quote.client_org`
  is required, this is available after `lead_convert` (the existing order: convert lead → opportunity with a
  client organization → quote). Before conversion, the output is an estimate summary PDF, not a quote.
- A draft proposal document (summary, plan, assumptions, exclusions) can be generated from a template;
  OPTIONAL AI can draft its narrative. Sending is the existing quote and contract flow, done by a person.

### 3.6 Forecast-versus-actual reviews (98.6)

- When a converted customer's agreement starts, a review schedule is created at 30, 60 and 90 days, then
  quarterly.
- Each review compares the frozen estimate with actuals from `reports/queries.py` and time entries:
  hours (total and by labor role), labor cost from time-entry cost snapshots, revenue, gross margin, and ticket
  volume by category.
- **Onboarding spikes are separated:** time on the onboarding project and remediation tickets created by the
  Phase 97 conversion is classed as onboarding. Where nothing is linked, entries in the first N days
  (configurable, proposed 60) are classed as onboarding with a visible note. Steady-state comparison excludes them;
  the onboarding estimate is compared separately.
- Variance is shown per driver where attributable (for example endpoint tickets versus server tickets) and
  overall, with the estimate's own low/high range as the tolerance band.
- Results surface where people already look: an executive provider "Forecast accuracy", an advisor detector
  "Underpriced against estimate" or "Utilization above estimate" for the customer, and a tab on the customer's
  profitability view.

### 3.7 Assumption-change recommendations (98.7)

- Across completed reviews, the system computes for each rule the ratio of actual to estimated hours (with
  minimum sample sizes) and proposes coefficient changes with the evidence (which customers, which periods).
- Proposals are records with status `proposed`, `accepted`, `rejected`. Accepting one creates a **new draft model
  version**; it still needs activation by a user with `estimator_approve_models`. Nothing is ever applied
  silently, and existing estimates are never recalculated.

### 3.8 Prospect intelligence (98.8)

From the assessment and estimate: missing services (for example no backup management in the chosen plan while
the assessment shows no offsite backups), upsell and revenue opportunities, a service readiness report, follow-up
questions and tasks. All deterministic rules; OPTIONAL AI may phrase them and draft meeting notes.

## 4. UI and workflows

- **No new sidebar entries.** The estimate is a tab next to the Assessment tab on the opportunity (and lead) in
  **Business → CRM**. Estimation models and coefficients are a tab in the CRM section (or in pricing settings once
  Phase 68 has a staff UI). Forecast accuracy appears in existing **Reports** (executive overview provider,
  profitability pages) and on the customer's profitability tab.
- Estimate page: a summary band (hours range, price range, margin, confidence), then per-driver rows that expand to
  show the `work(...)` steps, then warnings and unknowns, then plan comparison.
- Pricing UI: the estimator needs service plans with prices. If Phase 68's staff pages have not shipped, 98 ships
  a minimal read and edit page for `ServicePlan` and `PriceBookItem` behind the existing `pricing_*` permissions,
  or links to Django admin for superusers (open decision).

## 5. Proposed data model changes

New app `estimates` (keeps estimating separate from `pricing`, which stays the source of prices):

| Model | Key fields |
|---|---|
| `EstimationModel` | `organization` (MSP), `name`, `version`, `parent` FK null, `status` (draft, pending_approval, active, retired), `margin_target_pct`, `onboarding_window_days`, `created_by`, `approved_by` null, `approved_at` null |
| `EstimationRule` | `model` FK, `driver`, `unit_filter` JSON, `condition` JSON, `hours_low`, `hours_expected`, `hours_high`, `onboarding_hours`, `labor_role` FK null, `price_book_item` FK null, `service_plan_item` FK null, `note` |
| `EstimationAllowance` | `model` FK, `key`, `condition` JSON, `multiplier_low`, `multiplier_expected`, `multiplier_high`, `cap`, `note` |
| `Estimate` | `organization` (MSP), `opportunity` FK null, `lead` FK null, `assessment_revision` FK null, `client_org` FK null, `model` FK, `inputs` JSON, `rates` JSON, `outputs` JSON, `work` JSON, `confidence`, `status` (draft, frozen, superseded), `quote` FK null, `frozen_at` null, `created_by` |
| `ForecastReview` | `estimate` FK, `client_org` FK, `period_label` (30d, 60d, 90d, quarter), `period_start`, `period_end`, `actuals` JSON, `variance` JSON, `onboarding_split` JSON, `status`, `computed_at` |
| `AssumptionChangeProposal` | `model` FK, `rule` FK null, `allowance` FK null, `field`, `current_value`, `proposed_value`, `evidence` JSON, `status`, `decided_by` null, `decided_at` null, `resulting_version` FK null |

Existing models: none changed except `accounts.RoleTemplate` booleans. Monetary fields use `Decimal` and the
currency of the price book; unknowns are NULL, never zero.

Scheduler: one task `estimates_reviews` registered in the three required places (`ScheduledTask` choice,
`get_or_create_defaults`, `run_scheduler.py` mapping), daily, idempotent per (estimate, period).

## 6. API and integration requirements

- Read-only REST endpoints for estimates and reviews (DRF, `api/scoping.py`), permission-checked; cost and margin
  fields omitted without `pricing_view_internal_cost_rates`.
- Internal service functions only: `estimates.engine.calculate`, `estimates.services.freeze_for_quote(quote)`
  (called from the quote send path, fail-safe like `pricing.services.snapshot_time_entry`).
- No external integrations.

## 7. Roles and permissions

New keys, module `pricing` unless noted, all `staff_only=True`:

| Key | Action | Sensitivity | Seeded on |
|---|---|---|---|
| `estimator_view` (module `sales`) | view | Elevated | Owner, Org Admin, Sales Manager, Sales Rep, Service Manager |
| `estimator_create` (module `sales`) | create | Elevated | Owner, Org Admin, Sales Manager, Sales Rep |
| `estimator_manage_models` | edit | Sensitive | Owner, Org Admin |
| `estimator_approve_models` | approve | Sensitive | Owner |
| `estimator_view_accuracy` (module `reports`) | view | Sensitive | Owner, Org Admin, Service Manager, Billing / Finance |

- Cost, margin and profit figures additionally require the existing `pricing_view_internal_cost_rates`; without it
  the estimate shows hours and price ranges only.
- Creating a draft quote requires the existing quote permissions; accepting an assumption proposal requires
  `estimator_manage_models`, and activation requires `estimator_approve_models`. The same user may not propose and
  activate in one step when two-person approval is turned on (setting, default off).

## 8. Security

- Internal costs and margins never reach customer-facing outputs, exports or AI payloads unless the user may see
  them; customer-facing summaries are generated from a separate, filtered view model.
- AI payloads contain placeholders, no customer names, and only figures the user may see.
- Every model activation, proposal decision, estimate freeze and draft quote creation writes an `AuditLog` row.

## 9. Backward compatibility

- Pricing, quotes, contracts and the advisor behave as today. Extracting the figure validator from `advisor/ai.py`
  keeps its tests passing unchanged.
- The quote-send hook that freezes an estimate is a no-op when no estimate is linked.

## 10. Migration strategy

1. New `estimates` app migration (additive).
2. `accounts` migration for permission booleans with derived grants (for example `estimator_view` where
   `crm_view_forecast` is on); seed versions bumped.
3. Data migration creating the starter model as an unapproved draft only when the module is enabled for the first
   time (done by the enable action, not by the migration, so upgrades create nothing).

## 11. Feature flags and module defaults

| Switch | Field | Fresh | Upgrade | Notes |
|---|---|---|---|---|
| Service estimator | `SystemSetting.estimator_enabled` | off | off | `core/modules.py`, `requires=('crm',)`, works better with assessments |
| Forecast reviews | `estimates.EstimatorSettings.reviews_enabled` | on when the estimator is on | — | |
| AI explanations | `psa_ai_enabled` | — | — | OPTIONAL AI |

## 12. Testing strategy

- **Unit (engine):** table-driven tests: same input → same output; each driver; allowances and caps; unknown cost →
  unknown price components and "incomplete" margin; confidence formula; `work(...)` steps add up to the totals.
- **Unit (reviews):** onboarding split with a linked project and with the window fallback; variance per driver;
  minimum sample sizes before proposals.
- **View:** estimate pages hide costs without `pricing_view_internal_cost_rates`; model edit creates a draft; only
  approvers activate; draft quote creation uses the advisor pattern and never sends.
- **Tenant isolation:** reviews and accuracy figures scoped with `reports/access.py` (`viewer_client_scope`); a user
  scoped to some customers never sees others' actuals; copies of `reports/tests_authz.py` cases.
- **AI:** off → no AI endpoint; on → figure validation rejects invented numbers and falls back.
- **Upgrade/migration:** upgraded install has no models, no estimates and the module off.
- **E2E:** assessment revision → estimate → plan comparison → convert → draft quote → send (freeze) → simulated time
  entries → 30-day review with onboarding split.

## 13. Definition of Done

- Versioned, approved estimation models with MSP-defined coefficients; starter model clearly marked as example.
- Deterministic engine with low/expected/high hours, onboarding estimate, labor cost, known and unknown vendor costs,
  price range, margin, profit, confidence, assumptions and warnings, each explainable.
- Plan comparison from MSP plans; draft quote through the advisor pattern; estimate summary PDF.
- Forecast reviews at 30/60/90 days with onboarding separation, surfaced in reports, executive overview and advisor.
- Assumption proposals that need approval and create new draft versions.
- OPTIONAL AI explanations with figure validation. Tests above pass; docs and roadmap updated.

## 14. Dependencies and sequence

Depends on Phase 97 (assessment inputs), Phases 68 and 69 (pricing and rates), Phase 70 (quote conversion), Phase 75
and 76 (profitability, advisor); Phase 92 improves actual endpoint counts. Order: 98.1 models and rules → 98.2 engine →
98.3 estimates on opportunities → 98.5 plan comparison and draft quote → 98.4 OPTIONAL AI → 98.6 reviews →
98.7 assumption proposals → 98.8 prospect intelligence.

## 15. Limitations and open decisions

- Estimates are only as good as the coefficients; the first months on any install rely on the MSP's judgment until
  reviews accumulate.
- Actual labor cost depends on time entries carrying cost snapshots; installs without cost rates get hours-only
  accuracy.
- Open decisions: pricing UI (index item 9), onboarding window default (item 10), whether two-person approval of
  model changes should default on.
