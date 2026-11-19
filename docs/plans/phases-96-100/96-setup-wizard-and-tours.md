# Phase 96 — First-install setup wizard and interactive onboarding

**Priority:** P0 · **Size:** L · **Status:** planned · Roadmap: [Phase 96](../../ROADMAP.md) ·
Index: [Phases 96–100](README.md)

The shared compatibility and safety requirements in the [index](README.md) apply. This spec lists only what
is specific to Phase 96.

## 1. Goals and business value

- A new administrator reaches a working, secured install without reading a manual: MSP details, security,
  modules, team, first customer or prospect, service desk mail, integrations, backups, optional sample data.
- The wizard writes the settings that already exist. It is a guided path through them, not a second settings
  system, and it can be reopened later without losing or overwriting anything.
- Existing installs are never pushed into it on upgrade.
- Guided tours of the live interface (not screenshots) shorten the time for owners, managers, sales staff,
  technicians and portal users to find their way, and respect permissions and enabled modules.
- Closes two gaps every new install has today: the default administrator password `ChangeMe123!`
  (`install.sh:815-825`) is never flagged, and there is no combined "is this install ready" check.

## 2. Existing components to reuse

| Need | Reuse | Notes |
|---|---|---|
| Wizard engine: steps, skip, resume, reopen, audit | `onboarding/engine.py`, `onboarding/registry.py` (`Step`, `StepForm`, `register_step`, `set_kind_steps`, `requires_apps`, `extra_available()`, `permission_denial()`), `onboarding/models.py` (`OnboardingSession`, `OnboardingStepState`), `docs/plans/ONBOARDING_STEPS.md` | `OnboardingSession.organization` is required today (`onboarding/models.py:53`); see §5. Apps contribute steps from `AppConfig.ready()`. |
| Wizard UI patterns | `templates/connect/_steps.html` (step header), `templates/integrations/rem0te_setup.html` with `integrations/rem0te/setup.py` (test connection with "what is missing"), `templates/two_factor/core/setup.html` | Reuse markup and CSS classes, no new UI framework. |
| MSP details, branding, preferences | `core:settings_general` (`SystemSetting` fields: site name, URL, time zone, logo) | The wizard step posts to the same form class or calls the same save helper. |
| Security | `SystemSetting.require_2fa` (`core/models.py:841`, default on), `core/security_policy.py`, `accounts/middleware.py` `Enforce2FAMiddleware`, `core/security_features.py`, `core:security_dashboard` | Readiness reads these; it never changes enforcement. |
| Module choice | `core/modules.py` (`MODULES`, `describe(settings)`, `set_enabled(module, settings, enabled, user)`), `core:settings_modules` | Dependency checks and `AuditLog` rows already exist. |
| Technicians, teams, roles | `accounts` role templates and seeds (`accounts/role_seeds.py`: Owner, Organization Administrator, Service Manager, Level 1/2/3 Technician, Sales, Billing, Auditor), existing user invite and team pages | The wizard links to or embeds the existing forms. |
| First customer | `onboarding` `new_customer` kind (`onboarding/steps/core.py`, `CustomerStep`) | Starts a normal customer onboarding session. |
| First prospect | `crm:lead_create`; Phase 97 Quick Assessment when enabled | |
| Service desk, mail, routing, notifications | PSA settings (`core:settings_psa`), mail settings, email-to-ticket (Phase 10), routing (Phase 60) | Links with status, plus "send test" where a test exists. |
| Integrations | Settings → Integrations section (`core/navigation.py` `settings_integrations`), Rem0te setup page, RMM connections, accounting, AI configuration (`settings_ai`) | Each shows configured or not configured, with a link. |
| Backup and health readiness | `core/upgrade/preflight.py` (`check_disk`, `check_database`, `check_pending_migrations`, …), `core/system_warnings.collect_system_warnings()`, `core:system_status` | Their check and warning dicts already carry severity, detail and action links. |
| Sample data | `manage.py seed_module_samples` (`core/demo_samples/`, additive, demo slugs only, unusable passwords for demo technicians) | `seed_demo_data` creates users with the fixed password `demo123` and is not used by the wizard. |
| Tour anchors and targets | `core/navigation.py` (`destinations_for(ctx)`, section and tab gates), sidebar `data-shortcut-key` attributes (`static/js/app_nav.js`), `static/js/command_palette.js`, `templates/core/_shortcut_help.html` | Tours resolve pages by URL name and skip what the user cannot open. |
| Help content | `core/help_views.py` (`HELP_INDEX`), `core/templates/core/help/` | The getting-started page is stale ("42 granular permissions") and is rewritten, not reused as is. |
| Front-end stack | Bootstrap 5.3.0 vendored under `static/vendor/bootstrap/5.3.0`, first-party scripts in `static/js/` loaded with `defer`, CSP with `script-src-attr 'none'` | No inline handlers; configuration passed with `json_script`. |

## 3. New functionality

### 3.1 Setup Assistant (the wizard)

Ten steps, each marked **Required** or **Optional**, each with Back, Next and (for optional steps) Skip, inline
help and a progress indicator. Progress is saved after every step; leaving and returning resumes at the last
step.

| # | Step | Required | Writes to |
|---|---|---|---|
| 1 | Welcome, MSP information, organization name, logo, time zone and date preferences | Yes (name, URL) | `SystemSetting` general fields; the MSP `Organization` record if none exists |
| 2 | Administrator security: password change if the default is still in use, 2FA status, recovery codes, security readiness summary | Yes (password change when default) | Existing account and 2FA pages; read-only summary of `core/security_features.py` |
| 3 | Modules: recommended sets (Service desk only; Service desk + CRM; Full) and individual switches with dependencies | Optional | `core/modules.set_enabled()` |
| 4 | Technicians, teams, roles and Level 1/2/3 assignment | Optional | Existing invite, team and role assignment code |
| 5 | First customer (starts `new_customer` onboarding) or first prospect (lead plus Quick Assessment when Phase 97 is on) | Optional | `onboarding`, `crm` |
| 6 | Service desk: support mailbox, email-to-ticket, routing defaults, notification settings, test message | Optional | PSA and mail settings |
| 7 | Integrations: Rem0te, RMM, accounting, AI, security providers, PBX (Phase 99) — each with status and "Set up" | Optional | Links into existing setup pages; each integration's own test |
| 8 | Backups and health: preflight checks, backup destination, scheduler running, site URL, mail configured | Optional (warnings stay visible) | Read-only checks with fix links |
| 9 | Sample data: create a clearly marked demo customer | Optional, off by default | `seed_module_samples` wrapper (§3.4) |
| 10 | Review and launch: what was configured, what was skipped, what still needs attention | — | Marks the wizard complete |

Rules:

- **No duplicate settings.** Every step saves through the same form or service function the existing settings
  page uses. A step that needs a field the existing page does not expose adds it to that page first.
- **Never overwrite silently.** When a step would change a value that is already set, it shows the current
  value, and the change is applied only when the administrator edits it. Reopening the wizard on a configured
  install shows every step as "already configured" with the current values.
- **Never require unused services.** Mail, integrations, backups and AI are optional. Required steps are only
  the MSP name and URL and (when the default password is in use) the password change.
- **No secrets in summaries or logs.** API keys and passwords are entered on the existing integration pages or
  in write-only fields, shown masked, never stored in `OnboardingSession.data`, never written to `AuditLog`
  descriptions. The review step lists "configured / not configured", never values.
- **Connection tests** call the existing test functions (Rem0te setup diagnostics, RMM test connection, SMTP
  test send, AI provider test) where they exist. Where none exists, the step says so instead of pretending.

### 3.2 First-install detection

The wizard is offered automatically only on a fresh install. It never appears by itself on an upgraded one.

- New field `SystemSetting.setup_assistant_state` with values `not_offered` (default), `offered`,
  `in_progress`, `completed`, `dismissed`.
- **Data migration (runs on every install once):** if any `User` row exists when the migration runs, the
  install already existed, and the state is set to `not_offered` (the `SystemSetting` row is created if
  missing). If no users exist (a fresh database, where migrations run before `createsuperuser` in
  `install.sh` and before the Docker entrypoint's optional superuser bootstrap), the state is set to
  `offered`.
- **Runtime guard:** the automatic redirect also requires that the install has no tickets and no non-demo
  customer organizations. If the guard fails, the state moves to `not_offered` and stays there. This catches
  a restored backup or a database created some other way.
- **Who sees it:** the first superuser (or a user with the new `setup_assistant_run` permission) after sign-in,
  once per session, as a full-page start screen with "Start setup" and "Not now". "Not now" sets `dismissed`.
- Administrators on any install can open it from **Administration → General → Setup Assistant** at any time.
  Reopening never resets saved settings.

### 3.3 Ordering with 2FA enforcement

`Enforce2FAMiddleware` redirects a user without a device to `two_factor:setup` on every request when 2FA is
required (the default). The wizard is **not** added to `ALLOWED_PATHS`: the wizard changes settings, and an
administrator who has only passed a password must not reach it. The order is therefore:

1. Sign in with the installer's credentials.
2. 2FA enrolment (existing pages, unchanged). When `require_2fa` is off, the existing once-per-session prompt
   stays as it is.
3. The start screen of the wizard (the first page after enrolment completes, via the post-login redirect).
4. Step 2 shows 2FA as already done and offers recovery codes.

### 3.4 Default administrator password warning

- A readiness check `default_admin_password` runs `check_password('ChangeMe123!', user.password)` for active
  superusers. It runs on demand (wizard step 2, the readiness card, the security dashboard), not on every
  request, because password hashing is deliberately slow. The result is stored on the readiness record with
  its time.
- When the check is positive: a persistent banner for superusers ("The default administrator password is still
  in use — change it now"), a high-severity item in `collect_system_warnings()`, and wizard step 2 requires the
  change before step 10 can complete.
- `install.sh` keeps creating `admin` as it does today. Whether new installs should get a random first password
  printed once is an open decision (§13). The Docker path already requires explicit credentials.

### 3.5 Install readiness check

One composite check, reused by wizard step 8, a card on the settings home and the security dashboard:
default password in use, 2FA enrolled for each superuser, site URL set, outbound mail configured and tested,
backup destination configured (`check_backup_destination`), last successful backup age, scheduler heartbeat,
pending migrations, disk space, app version behind. Results are a list of `Check` dicts (severity, detail,
`action_url`, `action_label`) built from `core/upgrade/preflight.py` and `core/system_warnings.py`, plus the new
checks. Results are stored in a small `core.ReadinessResult` row (latest only, with timestamp) so the settings
home does not re-run slow checks on every page view.

### 3.6 Guided tours

Real tours over the live interface: a highlighted element, a step prompt next to it, Next and Back, "End tour".

- **Engine:** a first-party module `static/js/tours.js` (target size a few hundred lines) built on the vendored
  Bootstrap 5.3 popover component plus a CSS spotlight overlay. No new framework. It reads the tour definition
  from a `json_script` block, attaches listeners with `addEventListener` (CSP forbids inline handlers), and works
  with keyboard (Esc ends, arrow keys move) and screen readers (`aria-live` step text, focus moved to the popover).
  Evaluated alternatives: vendoring a small MIT-licensed tour library under `static/vendor/` is acceptable if the
  first-party module proves insufficient; libraries with AGPL or commercial terms are excluded.
- **Definitions:** a Python registry `core/tours.py` with `Tour(key, version, audience, title, steps)` and
  `TourStep(url_name, anchor, title, body, gate)`. Anchors are stable `data-tour="…"` attributes added to
  templates (plus the existing `data-shortcut-key` on sidebar links), never CSS classes or text.
- **Respecting access:** before a tour is offered, each step's `url_name` is resolved through
  `core/navigation.py` (`destinations_for(ctx)`) and its `gate`. Steps on pages the user cannot open, or in
  modules that are off, are dropped. A tour whose remaining steps fall below a minimum is not offered. On page
  load, a step whose anchor is missing is skipped rather than shown in the wrong place.
- **Multi-page tours:** the tour state (tour key, step index) is held in the per-user progress row (§5), so a
  step on the next page continues after navigation.
- **Audiences and first tours:** owner/administrator (settings home, modules, roles, readiness); manager
  (service desk dashboard, assignment, reports); sales representative (create a lead, pipeline, prospect
  assessment when Phase 97 is on); Level 1 technician (create and work a ticket, time entry, documentation);
  Level 2/3 technician (assets, ports, network diagrams, runbooks); portal user (raise a ticket, see status,
  approvals). Further tours: contracts and profitability reports, AI features and their permission controls
  (shown only when `psa_ai_enabled` is on).
- **Discovery:** a "Tours" entry in the existing Help account menu (`account_help` section), a "Take the tour"
  link on pages that have one, and a one-time suggestion on first sign-in for each audience. Completion,
  dismissal and replay are tracked per user.
- **Contextual help:** each page with a help topic gets a small help icon in the page header linking to the
  matching `HELP_INDEX` entry. The stale getting-started page is rewritten as part of this phase.

### 3.7 Demo data isolation

- New field `Organization.is_demo` (default `False`).
- The wizard's sample-data step creates one synthetic customer with an unmistakable name ("Sample Customer
  (demo)"), a demo badge everywhere its name appears, and records created only through `seed_module_samples`
  logic, which never edits or deletes and creates demo technicians with unusable passwords.
- Before seeding, the step refuses if a real (non-demo) organization already uses one of the demo slugs the
  seeder targets (`core/demo_samples/__init__.py`), instead of seeding into it.
- **Never mixed into real figures:** MSP-wide aggregates exclude `is_demo` organizations by default — reports
  in `reports/queries.py`, the executive overview providers, advisor runs, health-score computation, billing
  exports, accounting sync, outbound webhooks, scheduled report mail and the dashboard KPIs. Implementation
  goes through one helper (for example `core.demo.real_orgs(qs)`) so the exclusion is in one place and testable.
  Outbound mail and SMS to demo contacts is suppressed.
- **One-click removal:** "Remove sample data" deletes the demo organization (cascade) and the demo users the
  seeder created (tracked in a small `core.DemoRecord` ledger of content type and object id), after a
  confirmation that lists counts. It refuses to touch any organization without `is_demo`.

## 4. UI and workflows

- **No new sidebar entries.** The Setup Assistant is a tab in the existing **Administration → General**
  settings section (`core/navigation.py` `settings_general`), with keywords so the command palette finds it.
  The readiness card goes on the settings home (`core:settings_home`). Tours live under the existing **Help**
  account menu.
- The wizard is a full-width page in the existing layout with a left step list (collapses to a top progress bar
  on phones), required/optional badges, and Back / Skip / Save and continue buttons. It works in all existing
  themes.
- `core/tests/test_nav_reachability.py` must pass: every new page is reachable from a nav entry.

## 5. Proposed data model changes

All additive.

| Model | Change | Notes |
|---|---|---|
| `core.SystemSetting` | `setup_assistant_state` CharField, default `not_offered`; `setup_assistant_completed_at` DateTime null; `setup_assistant_completed_by` FK User null | Data migration sets `offered` only on an empty user table (§3.2). |
| `onboarding.OnboardingSession` | New kind `install` in `KINDS`; `organization` relaxed to `null=True` with a `CheckConstraint` (`organization IS NOT NULL OR kind = 'install'`) | Not purely additive (relaxes NOT NULL); existing rows unaffected. All existing customer-onboarding queries add `kind != 'install'` through the default queryset helper, with tests. Alternative: a separate `InstallSetupSession` model (open decision). |
| `core.ReadinessResult` | New: `checks` JSON, `ran_at`, `ran_by` | Latest row only; older rows pruned. |
| `accounts.TourProgress` | New: `user` FK, `tour_key`, `tour_version`, `status` (offered, in_progress, completed, dismissed), `step_index`, `started_at`, `completed_at`, `dismissed_at`; unique (`user`, `tour_key`) | A model rather than a `UserProfile` JSON field so completion can be reported and a new tour version re-offered. |
| `core.Organization` | `is_demo` BooleanField, default `False`, indexed | |
| `core.DemoRecord` | New: `content_type`, `object_id`, `created_at` | Ledger for one-click removal of demo objects that live outside the demo organization (users). |
| `accounts.RoleTemplate` | `setup_assistant_run`, `tours_manage` booleans | See §7. |

The wizard's own answers are saved in `OnboardingSession.data` keyed by step, minus secrets.

## 6. API and integration requirements

- No public API. Wizard and tour progress endpoints are session-authenticated JSON views under existing URL
  prefixes (`/settings/setup/…`, `/account/tours/…`) with CSRF.
- Steps that test integrations call the existing test functions; none adds outbound calls of its own.
- The Docker entrypoint and `install.sh` need no change for detection. An optional `install.sh` change (random
  first password) is an open decision.

## 7. Roles and permissions

New keys in `accounts/permission_registry.py`:

| Key | Module | Action | Sensitivity | Staff only | Seeded on |
|---|---|---|---|---|---|
| `setup_assistant_run` | `org` | `settings` | Critical | Yes | Owner, Organization Administrator |
| `tours_manage` | `org` | `settings` | Elevated | Yes | Owner, Organization Administrator |

- Superusers can always run the wizard. Each step additionally requires the permission of what it changes
  (the onboarding engine's `permission_denial()` contract), so a delegated administrator without user-management
  rights sees step 4 as "needs permission", not as an error.
- Tours need no permission to take; `tours_manage` covers enabling or disabling tours install-wide and
  resetting progress for a user.
- Portal tours run inside the portal with portal permissions only.

## 8. Security

- 2FA enforcement is unchanged; the wizard runs after enrolment (§3.3).
- The wizard never displays or logs secrets; masked inputs; integration secrets stay in their existing
  encrypted fields (`vault/secret_fields.py`).
- Demo users have unusable passwords and cannot sign in. Demo data never receives outbound mail, SMS or
  webhooks.
- Tour definitions contain no user data; the `json_script` payload is rendered server-side per user after gate
  checks, so a tour cannot reveal the existence of a page the user cannot open.
- All wizard saves write `AuditLog` rows through the existing settings code paths.

## 9. Backward compatibility

- Upgraded installs: `setup_assistant_state = not_offered`; nothing appears unless an administrator opens it.
- Module defaults are unchanged on upgrade. The wizard's recommended module sets apply only when the
  administrator chooses one.
- Existing onboarding sessions and pages are unchanged; the `install` kind never appears in customer onboarding
  lists.
- `seed_demo_data`, `seed_module_samples` and `setup_initial_data` keep their current behavior when run from
  the command line.

## 10. Migration strategy

1. `core`: add `SystemSetting` fields, `Organization.is_demo`, `ReadinessResult`, `DemoRecord`; data migration
   for `setup_assistant_state` (reversible: reverse is a no-op).
2. `onboarding`: add the `install` kind, relax `organization` with the check constraint. Reverse: deletes
   `install` sessions, then restores `NOT NULL`.
3. `accounts`: `TourProgress`; the two permission booleans with an additive grant migration modelled on
   `0064_roletemplate_events_permissions.py` (grant `setup_assistant_run` and `tours_manage` where
   `org_manage_settings` is on); bump the Owner and Organization Administrator seed versions.

## 11. Feature flags and module defaults

| Switch | Field | Default fresh | Default upgrade | Registered in |
|---|---|---|---|---|
| Setup Assistant | none (always available to administrators; automatic offer controlled by `setup_assistant_state`) | offered | not offered | — |
| Guided tours | `SystemSetting.tours_enabled` | on | **off** (administrators can turn it on) | `core/modules.py` as `tours`, group "General" |
| Contextual help icons | part of `tours` | on | off | — |

Sample data is never created without an explicit choice in the wizard.

## 12. Testing strategy

- **Unit:** detection logic (users present vs empty; runtime guard with tickets or real organizations);
  readiness checks each in isolation, including `default_admin_password` positive and negative; tour gate
  filtering (module off, missing permission, customer user); demo exclusion helper.
- **View** (`@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)` for most, plus one test
  with the real middleware stack): every wizard step renders, saves through the existing settings path, refuses
  without permission, never writes secrets to `OnboardingSession.data` or `AuditLog`; reopening on a configured
  install changes nothing until edited.
- **2FA ordering:** with real middleware, a fresh superuser without a device is redirected to `two_factor:setup`
  before any wizard URL responds.
- **Tenant isolation:** customer onboarding lists never show `install` sessions; tours never list pages a
  customer user cannot open; demo organizations absent from every MSP-wide report and export in a parametrized
  test over the listed aggregates.
- **Upgrade/migration:** migration tests on a database with users (state `not_offered`) and an empty one
  (`offered`); the upgrade rehearsal in `install-upgrade.yml` confirms an upgraded install never redirects to the
  wizard; reverse migrations.
- **Front end:** a browser test (the existing screenshot tooling or a headless run) that walks one tour across
  two pages, confirms keyboard control and that a missing anchor is skipped; no CSP violations in the console.
- **Demo removal:** removal deletes exactly the ledger and the demo organization and refuses on a non-demo
  organization.

## 13. Definition of Done

- A fresh install (both `install.sh` and Docker) offers the wizard after 2FA enrolment; an upgraded install
  does not.
- All ten steps work, save through existing settings code, resume after leaving, and can be reopened without
  changes.
- The default password is detected and must be changed before the wizard completes; the warning appears in the
  security dashboard.
- Readiness card on the settings home with fix links.
- At least the six audience tours ship, respect permissions and modules, and track completion, dismissal and
  replay.
- Sample data can be created and removed in one action and never appears in MSP-wide reports, exports or
  outbound messages.
- Help text for getting started rewritten; docs and roadmap updated; tests above pass.

## 14. Dependencies and sequence

Depends on Phase 64 (roles), Phase 67 (navigation and settings home) and Phase 59 (preflight). Sub-phase order:

1. **96.1** Default-password detection and readiness check (independently useful; ships first).
2. **96.2** First-install detection and `install` session kind.
3. **96.3** Wizard steps 1–4 and 10.
4. **96.4** Wizard steps 5–8 (5 offers the prospect path only when Phase 97 is on; 7 lists the PBX step only
   when Phase 99 is on).
5. **96.5** Demo data isolation and wizard step 9.
6. **96.6** Tour engine, progress model and the first audience tours.
7. **96.7** Remaining tours and contextual help.

## 15. Limitations and open decisions

- Tours cannot cover pages that render most of their content client-side without stable anchors; those pages get
  `data-tour` attributes as part of the tour work.
- The CRM module's routes are not gated today (`crm/urls.py` has no `gate_patterns`), so turning CRM off in step
  3 only hides navigation. Whether to gate them is an open decision (index item 3).
- Open decisions: wizard session storage (index item 1), random first password (item 2), CRM gating (item 3),
  tour engine (item 4), demo marker and the `demo123` seeder (item 5).
