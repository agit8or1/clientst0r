# Phase 97 — Prospect IT assessment and CRM enhancements

**Priority:** P1 · **Size:** L · **Status:** planned · Roadmap: [Phase 97](../../ROADMAP.md) ·
Index: [Phases 96–100](README.md)

The shared compatibility and safety requirements in the [index](README.md) apply. This spec lists only what
is specific to Phase 97.

## 1. Goals and business value

- A salesperson, owner or technician documents a prospect's whole IT environment during a real meeting, fast:
  checkboxes, Yes / No / Unknown, dropdowns, numbers, short text, optional notes.
- The record says who supplied each answer and whether it was verified, so a guess never becomes a confirmed
  fact.
- One answer set, two depths: a Quick Assessment for the first meeting and a Detailed Assessment that expands
  the same answers, never a copy.
- When the deal is won, approved answers turn into **draft** records (customer, locations, contacts, assets,
  network documentation, plan and quote, onboarding project, remediation tasks) through the existing lead
  conversion and commercial onboarding, without duplicates.
- Feeds the Phase 98 estimator and gives the MSP risk, readiness and qualification scores before it commits to a
  price.

## 2. Existing components to reuse

| Need | Reuse | Notes |
|---|---|---|
| Prospect record and pipeline | `crm.Lead`, `crm.Opportunity`, `crm.SalesActivity` (`crm/models.py`), `crm:lead_detail`, `crm:pipeline` | `Lead.organization` is the MSP organization, not the prospect. A lead has no customer `Organization` until `lead_convert`. |
| Conversion | `crm/views.py` `lead_convert` (creates the customer `Organization` and a qualified `Opportunity` in one transaction), `opportunity_to_quote`, `onboarding` `new_customer` kind and `CustomerStep` (`onboarding/steps/core.py`) | Today `lead_convert` and the wizard's customer step both create an organization; 97.6 makes the wizard adopt the converted organization. |
| Questionnaire schema, conditions, validation | `psa/service_requests.py` — `FIELD_TYPES`, `normalize_schema` (`:445`), `visibility` (`:695`), `validate_submission` (`:950`), `snapshot_schema` (`:1083`), cycle detection, `SECRET_RE` | These functions do not depend on tickets. `FormContext` lookups (contact, location, asset fields) need an `Organization` and are not used for prospects. |
| Versioning pattern | `psa.ServiceRequestFormVersion` (immutable published schema, `number`, `published_by`), draft vs published on `ServiceCatalogItem` | Mirrored in new assessment template models, not shared tables. |
| Builder UI | `static/js/request_form_builder.js` (drag, move, locked IDs), `request_form.js` | Extended with section, tier and provenance options. |
| Scoring pattern | `readiness/scoring.py` and `readiness/params.py` (weighted scores with exceptions); `health_score/registry.py` principle "unknown is not healthy" | `readiness` checks documents of an existing customer; it is not a questionnaire. |
| Attachments | `files.Attachment` (`files/models.py`, private, served through X-Accel-Redirect, rules in `files/upload_rules.py`) | No lead or assessment entity type yet; `organization` is required (the MSP organization would be used). |
| Discovery evidence | `network_discovery` tokens, collector script and importer | Token and import need a customer `Organization` and `Location`, so they are post-conversion only. |
| Staged import with rollback | `imports` (`MigrationPlan`, `StagedRecord`, `PlanItem`, `imports/rollback.py`) | Candidate for conversion staging (open decision). |
| Report export | `reports/pdf_export.py` | Print and PDF of the assessment report. |
| Prospect-facing pages without an account | `contracts/public_urls.py` (tokenized pages with email-code verification) | Pattern only, for an optional "prospect fills in a section" link later. |
| OPTIONAL AI | `advisor/ai.py` (placeholder redaction `_redact`, figure validation `validate`, deterministic fallback), `psa_ai/services/policy_call.py` (`prepare_for_org`, `complete_for_org`), `core/ai_gate.py`, budgets | `prepare_for_org` needs an organization's `AIBusinessPolicy`; see §8. |
| Audit | `audit.AuditLog.log`, `crm/views.py` `_audit` | |

## 3. New functionality

### 3.1 Assessment templates (97.1)

- Install-wide, versioned templates. A template version is an immutable schema in the `normalize_schema` format
  with additional keys per question: `section`, `tier` (`quick` or `detailed`), `audience` (`business`,
  `technical`, `financial`), `estimator_key` (the input the Phase 98 engine reads, for example
  `endpoints.laptops.count`), `weight` and `risk_rule` for scoring, and `maps_to` for conversion targets.
- 97.1 first checks whether `normalize_schema` preserves unknown keys. If not, it gains an opt-in parameter
  (`extra_keys=…`) and request forms keep byte-identical behavior, pinned by tests.
- Answer state applies to every question type: `answered`, `unknown`, `not_applicable`, `not_asked`. "Unknown"
  is an explicit choice, never the same as blank.
- Sections can be added, removed and reordered; questions can be optional, required for completion, or
  conditional (existing `CONDITION_OPS`).
- A built-in starter template covers the nine categories of the brief: business profile; endpoints; servers and
  infrastructure; network; applications; security; backup and disaster recovery; existing IT support; business
  and financial. It is seeded as a draft the MSP publishes, so nothing is forced on existing installs.

### 3.2 Assessments on leads and opportunities (97.2)

- An `Assessment` belongs to a lead or an opportunity (at least one), carries the MSP organization like every
  CRM record, and is pinned to one template version.
- Several assessments over time per lead (first meeting, site visit, pre-proposal). Each can be revised.
- **Quick vs Detailed** are two filters over the same answers: Quick shows `tier = quick` questions; Detailed
  shows all. Switching never copies data. Completion is tracked separately for the quick set and the full set.
- **Autosave and resume:** each answer saves on change through a small JSON endpoint (debounced), with an
  optimistic version number so two people editing the same assessment get a conflict message instead of lost
  answers.
- **Mobile and tablet:** one question per row, large touch targets, sticky section navigation, works offline
  for the open page only (answers queue in memory and retry; nothing is stored in browser storage).
- Notes per section and per answer; photos and documents attached per section (§5).

### 3.3 Answer provenance (97.3)

Every answer records:

- **Supplied by:** prospect contact (name and role, optionally linked to the lead's contact), MSP staff
  observation, document provided, tool import, or other.
- **Recorded by:** the user who entered it, and when.
- **Verification:** `unverified` (default), `verified` (by whom, when, how: on-site check, document, tool
  import, screenshot), or `disputed`.
- Changing an answer keeps the earlier value in the revision history (§3.4).

### 3.4 Revisions and compare (97.4)

- "Save revision" (and every approval) freezes an immutable `AssessmentRevision` snapshot: answers, states,
  provenance and the template version.
- Compare any two revisions: changed, added and removed answers, verification changes, and score changes, side
  by side. Works across template versions by question ID; questions that no longer exist are shown as removed.

### 3.5 Reports, export and OPTIONAL AI summary (97.5)

- Printable report and PDF (`reports/pdf_export.py`): per section answers with unknowns highlighted, provenance
  markers, scores and open questions. A customer-facing variant omits internal notes, financial answers and
  internal scores.
- **OPTIONAL AI** (gated by `psa_ai_enabled`): a summary of the assessment, gaps and suggested follow-up
  questions, and a discovery-meeting summary with action items from the MSP's typed notes. It follows the
  `advisor/ai.py` pattern: structured facts only, the prospect's company name replaced by a placeholder, figures
  validated against the input, deterministic fallback. AI output is a draft the user edits or discards; it never
  changes answers, verification states or scores.

### 3.6 Conversion of approved answers (97.6)

- An authorized user approves an assessment revision for conversion. Approval lists every answer that would
  become a record and its verification state.
- **Only `verified` answers become records.** Unverified and unknown answers are carried into the onboarding
  checklist as "to confirm" items, never into confirmed infrastructure records.
- Conversion runs through the existing path: `lead_convert` (unchanged: creates the customer `Organization` and
  qualified `Opportunity`), then a `new_customer` onboarding session that **adopts** the converted organization
  instead of creating one (the `CustomerStep` gains an "existing organization" branch).
- A conversion plan lists proposed records: locations, contacts and departments, draft assets (marked as
  "from assessment" and needing confirmation), network documentation pages, service plan selection and quote
  (via Phase 98 when enabled), contract draft, onboarding project, remediation tickets or tasks, documentation
  checklist. The user ticks what to create.
- **No duplicates:** each proposed record is matched against existing records of the converted organization
  (name, serial, address, email) and shown as "exists — link" instead of "create".
- Created records stay drafts where the target model supports drafts (quotes, contracts, projects). Assets are
  created with a `source` marker and appear in the onboarding checklist for confirmation.
- Each created object is recorded on the plan for traceability and rollback (rollback deletes only records the
  plan created and nobody has edited since).

### 3.7 Scores (97.7)

Deterministic, explainable, computed from answers and stored on each revision:

- **Technology risk score** per category and overall (for example: no MFA, no offsite backups, unsupported
  operating systems, no restore testing). Each contributing answer is listed with its weight.
- **Service readiness score:** how ready the environment is for onboarding (documentation, admin access,
  current vendor cooperation).
- **Data completeness:** share of quick and detailed questions answered and verified.
- Unknown answers never count as healthy; they lower completeness and are shown separately, not silently scored
  as good or bad.

### 3.8 Qualification and profitability acceptance rules (97.8)

- MSP-defined rules (for example: minimum seats, required security baseline, maximum technical-debt score,
  minimum projected margin) evaluated against the latest revision and, when Phase 98 is enabled, the latest
  estimate.
- Outcome per rule: pass, fail, unknown (data missing). The overall result is advisory: it informs, it never
  blocks a sale or changes the pipeline stage by itself.

### 3.9 Unified communications history (97.9)

- The lead and opportunity pages show one timeline: `SalesActivity` entries, assessment events (created,
  revised, approved, converted), and phone calls from Phase 99 when enabled.
- The timeline continues on the customer after conversion (activities with `client_org`).

### 3.10 Authorized imports from discovery tools (97.10)

- Before conversion: a spreadsheet or CSV upload mapped to questions (counts of devices, operating systems,
  servers), marked `supplied_by = tool import`, still `unverified` until a user verifies them.
- After conversion: `network_discovery` and RMM data reconcile against the assessment: counts that differ are
  listed for review; nothing overwrites an answer automatically.

## 4. UI and workflows

- **No new sidebar entries.** Everything lives in the existing **Business → CRM** section
  (`core/navigation.py` `mod_crm`):
  - an **Assessment** tab on the lead and opportunity detail pages (list of assessments, start Quick, continue,
    compare, report);
  - a new tab **Assessment Templates** in the CRM section for template managers;
  - optional **Prospect Discovery** tab in the CRM section listing open assessments across leads (filter by
    owner, completion, score).
- Workflow: lead created → Quick Assessment in the meeting → follow-up questions → Detailed Assessment and
  verification → revision approved → qualification rules → (Phase 98) estimate → `lead_convert` → onboarding
  session adopts the organization and shows the conversion plan → drafts created.
- Section-level audience: financial sections are hidden from users without `assessments_view_financial`;
  technical sections can be completed by technicians invited to the assessment.

## 5. Proposed data model changes

New models in the `crm` app (all carry `organization` = MSP organization, following `crm`'s pattern):

| Model | Key fields |
|---|---|
| `AssessmentTemplate` | `name`, `description`, `draft_schema` JSON, `published_version` FK null, `is_active`, `created_by` |
| `AssessmentTemplateVersion` | `template` FK, `number`, `schema` JSON (immutable), `published_by`, `published_at`; unique (`template`, `number`) |
| `Assessment` | `lead` FK null, `opportunity` FK null, `client_org` FK null (set at conversion), `template_version` FK, `title`, `status` (draft, in_review, approved, converted, archived), `quick_completion_pct`, `full_completion_pct`, `lock_version`, `assigned_to`, `created_by`; check constraint: `lead` or `opportunity` set |
| `AssessmentAnswer` | `assessment` FK, `question_id`, `value` JSON null, `state` (answered, unknown, not_applicable, not_asked), `supplied_by_kind`, `supplied_by_name`, `supplied_by_role`, `recorded_by` FK, `recorded_at`, `verification` (unverified, verified, disputed), `verified_by` FK null, `verified_at` null, `verification_method`, `note`; unique (`assessment`, `question_id`) |
| `AssessmentSectionNote` | `assessment` FK, `section_key`, `body`, `author` |
| `AssessmentRevision` | `assessment` FK, `number`, `snapshot` JSON (answers, provenance, template version), `scores` JSON, `created_by`, `created_at`, `approved_by` null, `approved_at` null |
| `QualificationRule` | `name`, `kind`, `params` JSON, `severity`, `is_active`, `version` |
| `AssessmentConversion` | `revision` FK, `client_org` FK, `onboarding_session` FK null, `plan` JSON (proposed items), `created_objects` JSON (content type, id), `status`, `created_by`, `rolled_back_at` null |

Changes to existing models:

| Model | Change |
|---|---|
| `files.Attachment` | New `ENTITY_TYPES` value `assessment` (choices are form-level only, so no data change). |
| `crm.SalesActivity` | `assessment` FK null (timeline linking); later `call` FK null from Phase 99. |
| `onboarding` | `CustomerStep` gains an "adopt existing organization" path; no schema change expected. |
| `accounts.RoleTemplate` | Booleans for the new permission keys (§7). |

## 6. API and integration requirements

- Session-authenticated JSON endpoints for autosave (`PATCH` one answer with `lock_version`), compare and report.
- REST API (DRF) read endpoints for assessments and revisions, scoped with `api/scoping.py` and requiring the new
  permissions; write API deferred.
- Template import and export as JSON (validated with the same normalizer) so MSPs can share templates.
- Phase 98 reads answers through a small service function (`crm.assessments.inputs_for(revision)`) that returns
  `(value, state, verification)` per `estimator_key`, never the raw tables.

## 7. Roles and permissions

New keys in `accounts/permission_registry.py`, module `sales`, all `staff_only=True`, not customer-assignable:

| Key | Action | Sensitivity | Seeded on |
|---|---|---|---|
| `assessments_view` | view | Standard | Owner, Org Admin, Service Manager, Sales Rep, Sales Manager, Level 2, Level 3 |
| `assessments_edit` | edit | Standard | Owner, Org Admin, Service Manager, Sales Rep, Sales Manager, Level 2, Level 3 |
| `assessments_verify` | approve | Elevated | Owner, Org Admin, Service Manager, Level 3 |
| `assessments_approve` | approve | Elevated | Owner, Org Admin, Sales Manager, Service Manager |
| `assessments_convert` | create | Elevated | Owner, Org Admin, Sales Manager (also needs `crm_manage_pipeline` and the permissions of each target) |
| `assessments_view_financial` | view | Sensitive | Owner, Org Admin, Sales Manager |
| `assessments_manage_templates` | settings | Elevated | Owner, Org Admin |

- The grant migration follows `accounts/migrations/0064_roletemplate_events_permissions.py`: a new key is turned
  on only where an existing related key is on (for example `assessments_view` where `crm_view` is on), nobody
  loses access, customized built-in roles go to the review list.
- Sales versus technical: technicians without `crm_view` can open only assessments they are assigned to,
  through an assignment check, not through the CRM list.
- Conversion also requires the existing permissions of what is created (organization, contacts, assets, quotes,
  contracts, projects); missing ones leave that item unticked with a reason.

## 8. Security

- Prospect data is pre-customer data held by the MSP: it is scoped by the MSP organization and by CRM
  permissions, and never shown in the customer portal.
- Financial answers are hidden without `assessments_view_financial`, including in exports and AI payloads.
- Free-text answers are checked with `SECRET_RE`; a likely password or key is refused with a message pointing to
  the vault. Credentials are never collected in an assessment.
- Attachments are private (`files.Attachment`, X-Accel-Redirect) and follow `files/upload_rules.py`.
- OPTIONAL AI uses the MSP organization's `AIBusinessPolicy` (the lead's `organization`) for budget, allowed
  profiles and `local_only`; if the policy excludes AI, the AI buttons are hidden. Prospect names are replaced
  by placeholders before any call.
- Every approval, verification, conversion and rollback writes an `AuditLog` row.

## 9. Backward compatibility

- Leads, opportunities, `lead_convert`, the pipeline and quotes behave as today. `lead_convert` keeps creating
  the organization exactly as now; only the onboarding wizard learns to adopt it.
- Request forms (`psa/service_requests.py`) keep their behavior; any change to the normalizer is opt-in and
  covered by the existing request-form tests plus new pinning tests.
- `files.Attachment` keeps every existing entity type.

## 10. Migration strategy

1. `crm` migration adding the new models (additive).
2. `accounts` migration adding the permission booleans and the derived grants; role seed versions bumped.
3. A data migration seeds the starter template as an unpublished draft (only if no template exists).
4. No data migration touches leads, opportunities or organizations.

## 11. Feature flags and module defaults

| Switch | Field | Fresh default | Upgrade default | Notes |
|---|---|---|---|---|
| Prospect assessments | `SystemSetting.crm_assessments_enabled` | off | off | Registered in `core/modules.py`, `requires=('crm',)`; routes behind `gate_patterns`. |
| Assessment AI summaries | uses `psa_ai_enabled` | — | — | OPTIONAL AI; also needs `assessments_view` and a policy that allows AI. |

The wizard (Phase 96) may turn assessments on for a new install when the administrator picks a CRM module set.

## 12. Testing strategy

- **Unit:** schema extension keeps request-form behavior identical; Quick and Detailed views over one answer set
  (no duplicate rows); answer states; provenance defaults; revision snapshot immutability; compare across
  template versions; scores with unknowns; qualification outcomes pass / fail / unknown.
- **View:** autosave with `lock_version` conflicts; section audience hiding; attachment upload rules; report and
  customer-facing export omit internal and financial data.
- **Conversion:** only verified answers create records; unverified ones become checklist items; duplicates are
  linked, not created; onboarding adopts the converted organization; rollback deletes only untouched created
  records.
- **Tenant isolation and permissions:** copies of `crm/tests_authz.py` cases for every new view and API
  endpoint; technicians reach only assigned assessments; customer users never reach any assessment; financial
  answers absent from responses without `assessments_view_financial`.
- **AI:** with `psa_ai_enabled` off, no AI endpoint responds; with it on, payloads contain placeholders, no
  financial answers without permission, and invalid figures fall back to the deterministic summary.
- **Upgrade/migration:** migrations on a populated CRM database leave leads, opportunities and roles unchanged
  except the additive grants; reverse migrations.
- **E2E:** a browser run on a tablet viewport completing a Quick Assessment, expanding to Detailed, approving and
  converting into an onboarding session.

## 13. Definition of Done

- Templates with versions, a starter template, builder support for sections, tiers and audiences.
- Assessments on leads and opportunities with Quick and Detailed views of one answer set, autosave, notes,
  attachments, provenance and verification.
- Revisions with compare; report and PDF; scores; qualification rules.
- Conversion of verified answers into drafts through `lead_convert` and onboarding, without duplicates, with
  rollback.
- Unified timeline on leads, opportunities and converted customers.
- OPTIONAL AI summaries behind `psa_ai_enabled`.
- Permissions seeded, tests above pass, documentation and roadmap updated.

## 14. Dependencies and sequence

Depends on the CRM module (Phase 5), commercial onboarding (Phase 75.3), roles (Phase 64). Sub-phase order:
97.1 templates → 97.2 assessments and Quick/Detailed → 97.3 provenance → 97.4 revisions and compare →
97.7 scores → 97.5 reports and OPTIONAL AI → 97.6 conversion → 97.8 qualification rules (financial rules
after Phase 98.3) → 97.9 unified timeline → 97.10 imports and reconciliation.

## 15. Limitations and open decisions

- A prospect has no `Organization`, so customer-bound features (network discovery tokens, per-customer AI
  policies, customer price overrides) are available only after conversion.
- A prospect filling in sections through a tokenized link is not in scope; the `contracts` public-page pattern
  makes it possible later.
- Open decisions: prospect lifecycle in `Organization` (index item 6), AI policy for prospect data (item 7),
  attachment storage and conversion staging (item 8).
