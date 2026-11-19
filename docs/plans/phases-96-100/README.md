# Phases 96–100 — specifications index

These specs support [docs/ROADMAP.md](../../ROADMAP.md), which stays the single source of truth for status
(the in-app roadmap and `/core/roadmap.json` parse it). The specs describe how each phase fits this codebase;
they are not a second roadmap and they carry no dates. Every item here is **planned**. Nothing in these
documents is implemented yet.

| Phase | Spec | Priority | Size | One line |
|---|---|---|---|---|
| 96 | [First-install setup wizard and interactive onboarding](96-setup-wizard-and-tours.md) | P0 | L | A Setup Assistant for fresh installs, readiness checks, and guided tours of the live interface. |
| 97 | [Prospect IT assessment and CRM enhancements](97-prospect-assessment-crm.md) | P1 | L | Structured discovery of a prospect's IT environment on the lead, converted into draft records when the deal is won. |
| 98 | [Service estimator and forecast accuracy](98-service-estimator-forecasting.md) | P1 | L | A deterministic effort and price estimator fed by the assessment, with forecast-versus-actual reviews. |
| 99 | [Phone system integration and call-to-ticket](99-pbx-integration.md) | P2 | XL | Caller identification, popups, click-to-call and call history from an existing PBX, starting with Asterisk 22 LTS and FreePBX. |
| 100 | [Optional simple PBX appliance](100-simple-pbx-appliance.md) | P4 | XL if built | Exploratory. Research and go/no-go criteria only; not to be built until Phase 99 is proven and demand exists. |

## Priority definitions

Priority is independent of status and size. It says how much the phase matters, not when it ships.

- **P0 — essential usability.** The first-time experience and anything that blocks an MSP from getting value
  without a manual.
- **P1 — major business value.** Prospect discovery, estimating, forecasting and profitability.
- **P2 — valuable optional integrations.** Connections to systems MSPs already run, such as an existing PBX.
- **P3 — lower-priority enhancements.** Improvements that can wait behind P0–P2. None of Phases 96–100 is P3;
  individual sub-phases may be deferred to P3 inside a spec.
- **P4 — long-term exploratory.** Research and decision gates. Building is conditional.

## Recommended sequence

1. **Phase 96 first.** It is P0, it is mostly additive UI over settings that already exist, and two of its
   early items (the default-administrator password warning and the readiness check) close real gaps on every
   new install today. Its step registry also gives later phases a place to plug in setup steps (the PBX
   connection step in 99, the estimator defaults in 98) without editing the wizard.
2. **Phase 97 next.** The assessment is the input to the estimator, so 98 cannot produce useful numbers
   without it. 97 also settles the prospect-versus-customer question (an assessment lives on the lead, not
   on an `Organization`) that 98 relies on.
3. **Phase 98 after 97.** The calculation engine reads approved assessment answers and existing pricing and
   cost data. Forecast-accuracy reviews (98.6–98.7) need converted customers with time entries, so they come
   last inside the phase.
4. **Phase 99 can run in parallel with 97/98** once 96's module switches and settings placement are settled.
   It shares only the communications timeline (97.9) and lead creation for unknown callers with 97. If 97 has
   not shipped, 99 still attaches calls to contacts, customers and tickets; lead linking switches on later.
5. **Phase 100 last, and only if its go/no-go criteria hold.** It depends on 99 having shipped with real
   users.

## Cross-phase dependencies

| From | Needs | Why |
|---|---|---|
| 96.5 (first customer or prospect step) | 97 (optional) | The "first prospect" path opens a lead with a Quick Assessment when 97 is enabled; otherwise it offers only "first customer". |
| 96.7 (integrations step) | 99 (optional) | The PBX step registers from the telephony app and shows "Available once Phone integration is enabled" until then (existing `Step.extra_available()` contract). |
| 97.7 (scores) and 97.8 (qualification rules) | 98.3 (estimate outputs) | Profitability acceptance rules read the estimate; without 98 they evaluate only non-financial rules. |
| 98.1–98.3 | 97.1–97.4 | Inputs come from approved assessment answers and their provenance. |
| 98.2 | Phases 68, 69 | Price books, service plans, rate cards and cost rates (`pricing/services.py`, `resourcing.TechCostRate`). |
| 98.5 | Phase 70, `advisor/actions.py` | Draft quote and draft contract creation follow the advisor's draft-with-approval pattern. |
| 98.6–98.7 | Phases 75, 92 | Actuals come from `reports/queries.py` profitability and time entries; verified usage counts (92.2) improve endpoint actuals when available. |
| 99.9 (after-hours routing hints, callback due times) | Phase 93 | Business-hours calendars decide what "after hours" means; until 93 ships, 99 uses `resourcing.WorkingHours` and `Holiday`. |
| 99.10 (PBX health alerts) | Phase 82 | A `pbx` source adapter in `events/sources.py`. Call records never go into the event layer. |
| 97.9 / 99.6 | each other | One communications timeline: `crm.SalesActivity` for sales touches and `telephony.CallRecord` for calls, shown together. |
| 100 | 99 shipped and proven | The appliance would use the same bridge contract as any other PBX. |
| All AI items | Phase 56 gateway, `core/ai_gate.py` | OPTIONAL AI, gated by `psa_ai_enabled`, existing providers, budgets and policies. |

## Shared compatibility and safety requirements

These apply to every phase in this set. Each spec states only its phase-specific additions.

1. **Additive migrations only.** New models and new nullable or defaulted fields. No column drops, renames or
   type narrowing. Any schema change that is not purely additive (for example relaxing a `NOT NULL`) is called
   out in the spec with its reason, a reviewed migration plan and a reversal.
2. **No data loss and no silent rewrites.** Migrations never rewrite existing business records. Data
   migrations only set flags that describe the install (such as "this install existed before the wizard").
3. **Upgrades need no reconfiguration.** An upgraded install behaves exactly as before until an administrator
   turns something on.
4. **New optional features are off by default on upgraded installs.** Module switches are `SystemSetting`
   booleans registered in `core/modules.py` (`MODULES`, `describe`, `set_enabled`), so dependency checks and the
   `AuditLog` row come for free. A fresh install may get a different, wizard-chosen set; an upgrade never
   changes an existing switch.
5. **Existing modules keep working.** No existing view, URL name, template block or API response changes shape
   unless a spec says so explicitly, with tests that pin the old behavior.
6. **Permissions and tenant isolation.** New permission keys are added only in
   `accounts/permission_registry.py` (with the matching `BooleanField` on `RoleTemplate` and a migration in the
   style of `accounts/migrations/0064_roletemplate_events_permissions.py`). Grants are additive: nobody loses
   access, and built-in role definitions in `accounts/role_seeds.py` get a version bump so the seeder updates
   uncustomized roles and lists customized ones for review. Every new view gets customer-boundary tests in the
   style of `crm/tests_authz.py`.
7. **No unexpected security changes.** Enforcement of 2FA, the API access rules of Phase 81, CSP and session
   handling stay as they are. Any spec item that touches them says so and ships behind an explicit setting.
8. **No autonomous AI.** Every AI function is **OPTIONAL AI**, gated by `psa_ai_enabled` through
   `core/ai_gate.py`, uses the existing gateway, policies and budgets, and only drafts or explains. AI never
   approves pricing, edits or signs contracts, sends proposals or messages, changes estimator assumptions or
   acts on a PBX.
9. **No impact on Rem0te or existing RMM integrations.** None of these phases changes the Rem0te contract,
   `integrations/sync.py` or the Connect framework.
10. **Graceful handling of missing external services.** A disconnected PBX, AI provider, mail server or
    discovery tool never breaks sign-in, the Service Desk or any page that does not depend on it. Pages show
    "not configured" or "unavailable" states instead of errors.
11. **Shared-cache caveat.** The cache is a per-process `LocMemCache` (`config/settings.py`) behind four sync
    gunicorn workers. Anything that must be consistent across requests (call state, wizard progress, tour
    progress, rate limits that matter) is stored in the database.
12. **Rollout and rollback.** Each sub-phase ships behind its module switch. Rollback is "turn the switch off":
    data stays, pages return 404 through `core/feature_gates.py`, and the previous release's code ignores the
    new tables. Every schema change has a working reverse migration with a test, and the upgrade path from
    the previous release is covered by the upgrade CI job (`.github/workflows/install-upgrade.yml`).
13. **Honest status.** Nothing is listed as shipped on the roadmap, README or in-app until it is released and,
    for integrations, verified against the real product.

## Open decisions

Recommendations are given in each spec. These need the maintainer's call before or during implementation.

1. **96 — wizard session storage.** Relax `OnboardingSession.organization` to nullable for a new `install`
   kind (recommended, guarded by a check constraint), or add a separate install-session model.
2. **96 — default administrator password.** Keep `ChangeMe123!` in `install.sh` and require a change before
   the wizard completes (recommended minimum), or also generate a random first password on new installs.
3. **96 — CRM route gating.** Put `crm/urls.py` behind `gate_patterns('crm_enabled')`, which changes behavior
   for installs that use `/crm/` with the module off. Recommended only together with a data migration that
   turns `crm_enabled` on where CRM records already exist.
4. **96 — tour engine.** A small first-party module on the vendored Bootstrap 5.3 popovers (recommended) or a
   vendored MIT library.
5. **96 — demo data marker.** Add `Organization.is_demo` (recommended) and retire the `demo123` users created
   by `seed_demo_data`, or keep the current seeders unchanged.
6. **97 — prospect lifecycle.** Keep `lead_convert` as the only place that creates an `Organization`
   (recommended), or add a prospect state to `Organization`.
7. **97 — AI policy for prospect data.** Use the MSP organization's `AIBusinessPolicy` (the lead's
   `organization`) or add an install-level policy for pre-customer data.
8. **97 — attachments and conversion staging.** Store assessment files as `files.Attachment` rows on the MSP
   organization with a new entity type, and stage conversion through the `imports` app's plan and rollback
   machinery or a dedicated conversion plan.
9. **98 — pricing UI.** Wait for the Phase 68 staff pages, or ship a minimal service-plan and price-book UI
   inside 98.
10. **98 — onboarding window.** The default length of the onboarding period excluded from steady-state actuals
    (proposed 60 days, configurable), when no onboarding project is linked.
11. **99 — scope.** The MSP's own PBX only (recommended MVP), or also customers' PBXs that the MSP manages.
12. **99 — second adapter.** Yeastar P-Series or 3CX after Asterisk/FreePBX, pending licensing verification.
13. **99 — browser delivery.** Short polling (recommended MVP) or server-sent events served by a separate
    async worker later.
14. **99 — recordings.** Link to recordings kept on the PBX only (recommended), or ever store them in
    ClientSt0r.
15. **99 — bridge distribution.** A small package in this repository with its own systemd unit and container
    image (recommended), or a separate repository.
16. **100 — go/no-go owner** and the demand threshold that counts as "customers ask for it".
