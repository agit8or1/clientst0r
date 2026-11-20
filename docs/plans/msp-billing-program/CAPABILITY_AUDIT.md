# Billing / quoting / CRM capability matrix (code audit)

Read-only static audit of `/home/administrator` (main, v3.17.732, 2026-11-20). No tests were run and no provider was contacted.
Paths are relative to the repo root. Line numbers are at HEAD.

**Status legend:** **Working** = code plus tests that exercise it. **Partial** = exists, with the gaps named. **Missing** = no code found.
**Needs improvement** = exists but buggy or unsafe (reason given).
"Adapter exists" means provider code that is only tested against mocked HTTP. "Verified" means a real or sandbox provider test. No billing provider has a verified test.

Background facts that most rows depend on:
- There is **no prepaid-block or hours ledger model**. `psa.Contract` (`psa/models.py:2279`) has one allowance (`total_hours`) and a *derived* counter `hours_used_minutes`. The counter is recomputed from time entries on every save or delete (`psa/models.py:1023-1093`, `Contract.recompute_for_time_entry_scopes` `:2859`).
- Consumption is decided by **client org + date window**, not by the entry's own `contract` FK (`qualifying_time_entries` `psa/models.py:2796-2831`).
- The **`pricing` app has no views or urls**. Price books, rate cards, billing rules and service plans can only be edited in Django admin (`pricing/admin.py:174-362`). `resolve_price` / `apply_price_to_line` (`pricing/services.py:182,266`) have no production caller.
- Ticket invoicing (`Ticket.uninvoiced_billing_lines`, `psa/models.py:449-590`) prices time at `contract.hourly_rate`, or at **0 when there is no contract**. It does not use the rate-card snapshot stored on each time entry (`bill_rate_snapshot` is read only by reports and the advisor: `reports/costing.py:155`, `advisor/inputs.py:143`).

---

## A. Billing models

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Prepaid block: balance | Partial | `Contract.total_hours` / `hours_used_minutes` / `effective_hours_remaining` `psa/models.py:2333-2350,2770`; tests `psa/tests/test_contract_billing_integrity.py:199-272` | Phase 1 ("Prepaid block hours with rollover") | The balance is derived, with no ledger. The allowance spans the whole contract window and does not reset per billing cycle (`billing_review.py:10-14` "consumed chronologically from the contract's start"). |
| Multiple blocks per customer | Missing | One allowance per `Contract`. `Contract.for_ticket` `psa/models.py:2724` uses an unordered `.first()`; `pricing.services.contract_for_client` `:124` orders by `-start_date` | no phase — gap | With two overlapping contracts, **both** count the same time (client-scoped query `:2816`). Ticket invoicing and the rate snapshot can also pick different contracts. |
| Earliest-expiry consumption | Missing | `effective_total_minutes` `psa/models.py:2739` just adds rolled-over minutes to the base | no phase — gap | The help text says rollover is "consumed before total_hours" (`:2345`), but there is no ordering logic. |
| Expiry / rollover | Partial | `rollover_percent/expiry_days/rolled_over_minutes/rollover_expires_at` `psa/models.py:2333-2360`; `psa_auto_renew_contracts.py:48-66`; renewal tests `test_contract_billing_integrity.py:81-155` | Phase 1 | Works only when the contract auto-renews. There is no expiry of the base block itself. |
| Low-balance alerts | Missing | No alert code. The ticket shows a "Depleted" badge only at 0 (`templates/psa/ticket_detail.html:426`). Over/under-use badges are on the reconciliation report (`reports/views.py:2376`) | Phase 36 (over/under-serviced alerts — report badges only) | No notification at a threshold. |
| Overage rate | Working | `Contract.overage_rate` `:2328`; split in `uninvoiced_billing_lines` `psa/models.py:497-546`; tests `test_invoice_billing_integrity.py:145-195` | Phase 1 | |
| Negative-balance policy | Missing | Overage is the only behaviour | no phase — gap | |
| Manual adjustments with audit | Missing | `hours_used_minutes` is "do not edit by hand" (`:2290`); no adjustment model | no phase — gap | |
| Transaction ledger | Missing | None. `psa_recompute_contract_hours` rebuilds the counter | no phase — gap | |
| Unlimited / managed coverage | Partial | `FLAT_FEE_TYPES` `psa/models.py:2749`; flat-fee branch `:520-528`; test `test_invoice_billing_integrity.py:197` | Phase 1 / Phase 15 | All billable time is covered, with no exclusions. |
| Coverage exclusions (remote/onsite, after-hours, service category) | Missing (role gates only) | `billable_role_codes` / `excluded_role_codes` `:2410-2425`; `coverage_for` `pricing/services.py:441` ignores `rate_type` and category | no phase — gap | Only role codes gate coverage. |
| T&M rate cards (remote/onsite/after-hours/holiday/emergency) | Partial | `RateCardLine.RATE_TYPES` `pricing/models.py:827-840`; `resolve_labor_rate` `pricing/services.py:341`; tests `pricing/tests.py:69` | Phase 69.1 | Modelled and resolved, but: (1) time entry UI never sets `rate_type` (always `standard`, `pricing/services.py:470`; `psa/views.py:2550-2570`); (2) **invoicing ignores the snapshot** and bills `contract.hourly_rate`, or $0 with no contract (`psa/models.py:510,537-543`); (3) admin only. |
| Minimum time / rounding increments | Partial (model only) | `BillingRule.minimum_billable_minutes/increment_minutes/rounding_mode` `pricing/models.py:894-940`; tests `pricing/tests.py:525` | Phase 69 (not listed as a bullet) | `resolve_billing_rule` has no caller outside tests, so it is never applied to time or invoices. |
| Trip / dispatch charges | Partial (model only) | `BillingRule.travel_fee/dispatch_fee` `pricing/models.py:908-909` | no phase — gap | Never applied. A `TicketExpense` category is the manual workaround. |
| Retainer: included hours + overage | Partial | `contract_type='retainer'` `:2291`; overage logic as above; test `test_invoice_billing_integrity.py:214` | Phase 1 / 15 | The allowance is per contract window, not per month (see block balance). |
| Retainer rollover | Partial | Same as rollover: auto-renew only | Phase 1 | |
| Proration | Partial | `_proration_factor` `psa/models.py:2501` (first invoice after a mid-period start only) | Phase 1 ("mid-month start/cancel") / 15 | **No proration on cancel**: `cancel_at_period_end` bills the full period. No proration on quantity changes. |
| Per-user/per-device quantity billing | Partial | `ContractMeter` + `increment()` `psa/models.py:2939-2995`, billed and zeroed in `generate_invoice` `:2620-2658`; plan per-unit prices and minimums `pricing/models.py:529-560` | Phase 15 v2 / Phase 92 (planned) | Meters are counters typed in by hand. No snapshots, tiers, minimums or verified counts, and nothing feeds meters automatically. `ServicePlan` minimums and per-unit prices are never billed. |
| Hybrid agreements with coverage precedence | Missing | No precedence resolver. Overlapping contracts double-count (above) | no phase — gap | |
| Project fixed fee / milestones | Working | `Project.BILLING_TYPES` `psa/models.py:1556`; `billable_milestones` `:1785`; `generate_invoice` `:1839`; `psa/tests/test_project_billing.py` | Phase 35 | |
| Project deposits / change orders | Missing | `ChangeRequest` (`psa/models.py:5726`) is ITIL change management, not a commercial change order | no phase — gap | |

## B. Ticket billing

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| In-ticket timer | Working | `timer_start/stop` `psa/views.py:2478,2514`; UI `ticket_detail.html:860` | Phase 1/25 era | |
| Time entry classification | Partial | `is_billable` plus a snapshot `included_vs_overage` (`psa/models.py:971-994`); tests `psa/tests/test_time_entry_rate_snapshots.py:60-119` | Phase 69.2 | No warranty or "covered" choice made by the tech. Coverage is computed once at creation and never refreshed. The ticket page does not show it (`ticket_detail.html:886` shows billable/non-billable only). |
| Agreement selection on entry | Missing (UI) | The `TicketTimeEntry.contract` FK exists (`:989`) and is auto-filled; no form field (`psa/views.py:2550-2570`) | no phase — gap | The FK is also ignored by consumption and invoicing. |
| Billing treatment shown on ticket | Partial | Contract banner with hours used/remaining `ticket_detail.html:416-431` | Phase 1 | Uses `hours_remaining`, not `effective_hours_remaining`, so rollover is ignored. No per-entry treatment or price preview. |
| "Add item" charges on ticket | Partial | `TicketExpense` (description, amount, billable) `psa/models.py:3887`; UI `ticket_detail.html:1132` | no phase — gap | No catalog search, no cost vs sale price, no permission gate on cost. `TicketKitItem` (`:6702`) is a packing list and never bills. `Charge` has no ticket FK. |
| Ticket billing summary | Partial | `invoice_from_ticket` reports covered vs overage hours afterwards (`psa/views.py:5800-5806`) | — | No pre-invoice summary on the ticket. |
| Unbilled items survive close | Working | Unbilled detection is independent of ticket status (`InvoiceLineItem.billed_source_ids` `psa/models.py:4990`); `test_invoice_billing_integrity.py:73-130` | — | |

## C. Billing engine

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Central coverage resolver | Partial | Logic is split: `pricing.services.coverage_for` (snapshot) `:441`, `Ticket.uninvoiced_billing_lines` (invoice) `psa/models.py:449`, `billing_review.build_rows` `psa/billing_review.py:116`, `agreement_reconciliation_detail` `reports/views.py:2672` | no phase — gap (implied by 71.10) | Four implementations that can disagree. |
| Hours consumed on approval | Needs improvement | Consumed on **every save**, regardless of timesheet status (`psa/models.py:1084-1093`) | no phase — gap | Unapproved and draft time already uses up the block. |
| Partial split block / overage | Working | `uninvoiced_billing_lines` `:497-546`; test `test_invoice_billing_integrity.py:145-195` | Phase 1 | |
| Reversal on rejection | Needs improvement | `TimesheetSubmission.return_entries` `psa/models.py:3701-3720` sets `rejected_at` only; `qualifying_time_entries` and `uninvoiced_billing_lines` do not filter rejected entries | no phase — gap | Rejected time still consumes the block and is still invoiceable. |
| Ledger immutability | Missing | No ledger. The counter is recomputed, so history is not preserved | no phase — gap | |
| Idempotency / locking vs double deduction | Partial | Recompute model avoids double counting (`test_resave_does_not_double_count` `test_contract_billing_integrity.py:245`); ticket invoice uses `select_for_update` (`psa/views.py:5762`) | Phase 71.10 (partial) | Overlapping contracts double-count (A). |
| Invoice does not re-consume hours | Working | Recurring invoice never bills time (`psa/models.py:463-466`); overage billed once via `overage_minutes_invoiced` `:2751`; test `:169` | Phase 15 / 36 | |

## D. Invoicing

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Ready-for-billing queue | Partial | `/psa/billing-review/` (contracts per month, approve/hold) `psa/views.py:5899`, `psa/billing_review.py`; tests `psa/tests/test_billing_review.py` | Phase 36 | Covers only recurring agreement invoices. No cross-ticket unbilled-work queue; ticket time is invoiced one ticket at a time (`invoice_from_ticket` `psa/views.py:5738`). The client-account "Unbilled work" list does **not** exclude billed entries (`psa/views.py:6442-6448`, despite its comment). |
| Pre-invoice approval | Working | `Invoice.flag_for_approval/approve` `psa/models.py:4697`; `psa/signals.py:403`; tests `test_invoice_billing_integrity.py:267-330` | Phase 36 | Thresholds have no settings UI (O). |
| Consolidated invoices | Partial | `charge_invoice` bundles account charges per client `psa/views.py:6518`; no multi-ticket or ticket+contract consolidation | no phase — gap | |
| Line source references | Working | `InvoiceLineItem.source/source_id` `psa/models.py:4941-4960`, `billed_source_ids` `:4990` | Phase 27/36 | Charges bundled as `source='manual'`, so voiding the invoice does not release them (`charged.invoiced` stays True). |
| Double-billing prevention on retries | Partial | Recurring: unique `contract_period_key` + IntegrityError handling `psa/models.py:2572-2610,4489`; tests `psa/tests/test_invoice_duplicates.py`. Ticket: row lock `psa/views.py:5762` | Phase 70.5 / 71.10 | **`charge_invoice` has no transaction or lock** (`psa/views.py:6518-6556`). Two concurrent POSTs both read `invoiced=False` and bill the same charges twice. |
| Finalized-invoice immutability | Working | `_invoice_form_locked_post` `psa/views.py:5454`; tests `test_invoice_billing_integrity.py:359-401` | Phase 27 | |
| Credit notes | Working | `Invoice.create_credit_memo` `psa/models.py:4823`; view `psa/views.py:6006`; `core/tests/test_billing_credit_memos.py` | Phase 27 v3 | Local only (see L). |
| Presentation options | Missing | Single layout in `psa/pdf.py` | no phase — gap | No grouping, summary/detail or hide-zero-lines options. |
| PDF | Working | `invoice_pdf` `psa/views.py:6210` | — | |
| Email | Working | `invoice_email` `psa/views.py:6283`; tests `test_invoice_billing_integrity.py:305-320` | — | |
| Portal invoices | Working (mocked pay) | `payments/portal_views.py:73-176`; `portal/urls.py:73-82` | Phase 72.3 | |

## E. Recurring billing

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Cycles (monthly/quarterly/yearly) | Working | `BILLING_FREQUENCY_CHOICES` `psa/models.py:2366`; `psa_generate_recurring_invoices.py`; tests `core/tests/test_expired_contract_billing.py` | Phase 15 | |
| Advance vs arrears | Partial | Advance only (bills the period starting `on_date`, `psa/models.py:2531`) | no phase — gap | Arrears and usage-in-arrears are not modelled, though meters are effectively billed in arrears. |
| Proration | Partial | See A | Phase 15 v4 | |
| Price effective dates | Partial | `ScheduledPriceChange` on price-book items `pricing/models.py:415`; contracts use a static `recurring_amount` | Phase 68 / 70 | Not linked to contracts. |
| Idempotent runs | Working | `psa/models.py:2572-2610`; `test_invoice_duplicates.py:108-129` | Phase 70.5 | |
| Dry-run preview | Partial | `--dry-run` CLI flag `psa_generate_recurring_invoices.py:64` | Phase 15 | CLI only, no UI preview. |
| Failed-billing alerts | Partial | Errors go to stdout and the scheduler `last_error` (`psa_generate_recurring_invoices.py:218-240`) | no phase — gap | No notification to billing staff. |
| Bundle items / recurring charges billed | Missing | `ContractBundleItem` `psa/models.py:2997` is not in `generate_invoice`. `Charge.recurrence/next_run_at` (`:5227-5230`) has no generator | Phase 70.4 / 92.1 (planned) | Phase 1 says "Bundled services shipped" — modelled only. |

## F. Quotes (`psa.Quote` `psa/models.py:3198`)

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Line items | Working | `QuoteLineItem` `:3530`; editor `psa/views.py:4220` | Phase 5/20 | |
| Recurring vs one-time totals | Missing (quotes) / Working (contract docs) | No recurring flag on `QuoteLineItem`. `contracts/content.py:22,132` splits one-time and recurring | Phase 65 (docs) — quotes: gap | |
| Templates | Missing (quotes) / Working (contract docs) | No `QuoteTemplate`; `contracts.ContractTemplate` `contracts/models.py:235` | Phase 65.2 | |
| Price-book selection in editor | Missing | Line FKs exist (`price_book_item`, `unit_cost` `psa/models.py:3542-3555`) but nothing sets them | Phase 68.3 (planned part) | |
| Good/better/best, optional items, mutually exclusive choices | Missing | — | no phase — gap | Contract docs have optional *sections* only (`contracts/content.py:99`). |
| Internal approvals | Working | `send_for_approval` `psa/models.py:3451`; `mark_accepted` guard `:3411` | Phase 20 | |
| Versions / revisions | Missing (quotes) | Quote is locked after signing (`_refuse_signed_content_change`); contract docs have `ContractVersion` `contracts/models.py:482` | Phase 65.6 (docs) | |
| E-signature bound to content hash | Working | `QuoteSignature.content_hash/pdf_hash/evidence_hash` `psa/models.py:5112-5200`; portal check `portal/views.py:673`; `psa/tests/test_quote_signature_binding.py` | Phase 65-adjacent | One signer per quote (OneToOne). |
| Evidence download | Working | `quote_signature_evidence` `psa/views.py:6367` | — | |
| Multiple signers / countersign / reminders / decline | Missing (quotes) / Working (contract docs) | Quotes: single signer, no decline in `portal/views.py:619`. Docs: `ContractSigner.role`, `signing_order`, reminders, decline `contracts/models.py:148-157,401,442` | Phase 65.3/65.5 | |
| Expiration / follow-up | Partial | `valid_until` field; stale flag on dashboard `core/dashboard_widgets.py:1074` | no phase — gap | No job moves quotes to `expired` and no follow-up. |
| Margin guardrails | Missing | `minimum_price` / `target_margin_pct` are never checked on quote lines | no phase — gap | |
| Deposits / payment schedules | Missing | — | no phase — gap | |
| Change orders | Missing | — | no phase — gap | |

## G. Conversion

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Quote → billing contract | Missing | — | Phase 70.1 (planned) | |
| Quote → invoice | Missing | `Invoice.source_quote` exists `psa/models.py:4462`, no conversion path | Phase 70.2 (planned) | Quote → PO exists (`psa/views.py:8049`). |
| Quote → project / ticket | Working | `convert_to_project` (idempotent) `:3495`; ticket in `mark_accepted` `:3411` | Phase 20/35 | Creates tasks, not billing (project `billing_type` is not set from the quote). |
| Contract doc → PSA billing contract | Partial | `contracts/services.py:725-745` (idempotent; draft `managed_services`, recurring_total, frequency, dates); test `contracts/tests/test_flow.py:336` | Phase 70.3 (planned — **already partly shipped**) | Does not carry line items, hours, rates or next billing date. `client_org=contract.organization` — the doc's organization is the customer. |

## H. Ticket estimate / out-of-scope approval

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Ticket estimate + customer approval | Missing | No ticket→quote link (quote has only `converted_ticket`). Portal customer approvals cover service requests (`core/models.py:1032`). `PSAApproval.kind='change'` is internal (`psa/models.py:2060`) | no phase — gap | |

## I. Price book / catalog

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Price book UI (not admin) | Missing | `pricing/` has no `views.py`/`urls.py`; admin `pricing/admin.py:174-362` | Phase 68.1 ("shipped") | The roadmap says shipped. Only the models and admin are. |
| Customer-specific pricing | Partial | `CustomerPriceOverride` `pricing/models.py:350`; `resolve_price` `pricing/services.py:182`; tests `pricing/tests.py:232` | Phase 68 | No production caller. |
| Effective dates | Partial | `ScheduledPriceChange.apply_due` `pricing/models.py:464`; rate card windows | Phase 68/69 | `apply_due` has no caller outside tests, so scheduled price changes are only applied when resolved for a date (and resolution itself has no production caller). |
| Distributor price freshness | Missing | No price timestamp or freshness field; distributor adapters in `integrations/providers/distributors/` | Phase 68.4 (planned) | |
| Inventory reservation vs consumption on ticket parts | Missing | `TicketKitItem.stock_shortfall` only reads stock (`psa/models.py:6803`); `InventoryTransaction` has no reservation type (`inventory/models.py:136-145`) | Phase 73.4 (partial overlap) | |

## J. CRM

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Leads / opportunities / pipeline | Working | `crm/models.py:55,145`; `crm/urls.py`; `crm/tests.py`, `crm/tests_authz.py` | Phase 5 | |
| Lead → customer + opportunity | Working | `lead_convert` `crm/views.py:242` | Phase 5 | |
| Opportunity → quote | Partial | `opportunity_to_quote` `crm/views.py:483` (idempotent, **empty draft quote**) | Phase 5 | No lines are carried over. |
| Won conversion | Partial | `closed_won` only creates a commission (`crm/views.py:446`) | Phase 97 (planned) | No onboarding or contract hand-off. |
| IT discovery / assessment questionnaire | Missing | None in `crm/`. Spec only: `docs/plans/phases-96-100/97-prospect-assessment-crm.md` | Phase 97 (planned) | |
| Workload / service estimator | Missing | Spec only: `98-service-estimator-forecasting.md` | Phase 98 (planned) | |
| Proposal generation | Partial | Contract-document builder and templates (Phase 65) | Phase 65 | Not linked to opportunities. |

## K. Optional AI

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| AI provider abstraction | Working | `psa_ai/services/policy_call.py` (`prepare_for_org`, `complete_for_org`); `psa_ai/tests*.py` | Phase 76.5 / AI phases | |
| `psa_ai_enabled` gating | Working | `core/ai_gate.py:29`; `advisor/permissions.py:65` | Phase 76.5 | |
| Pricing advisor (deterministic + AI narrative) | Working | `advisor/detectors.py`, `advisor/ai.py:1-20,135-165` (figure validation), drafts only via `advisor/actions.py:77-128`; `advisor/tests.py` | Phase 76 | |
| Web market research with cited sources | Missing | No web search or citation code in `advisor/` or `psa_ai/` | no phase — gap | |
| AI spend limits / budgets | Working | `AIBudgetDay/Month/InstallMonth` `psa_ai/models.py:346,739,901` | AI phases | |
| Redaction | Partial | `advisor/ai._redact` replaces names with placeholders (`advisor/ai.py:63`) | Phase 76.5 | Name placeholders only; no PII scanner on this path. |

## L. Accounting and payments

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| QBO: customer sync, invoice push (idempotent), payment pull | Partial — adapter, mocked | `integrations/providers/accounting/quickbooks_online.py:251,442,537,658`; `integrations/services/invoice_push.py`; `psa/tests/test_invoice_push_safety.py`; `integrations/tests.py:638` ("Without a real QBO sandbox, mock…") | Phase 44 / 71.1-71.2 | Not verified against a real provider. |
| Xero: same | Partial — adapter, mocked | `integrations/providers/accounting/xero.py:196,247,344,471` | Phase 44 / 71.3 | Not verified. |
| Payment posting to accounting | Partial — adapter, not wired | `record_payment` QBO `:602`, Xero `:378`; **no caller**; `payments/accounting.py:1-23` leaves rows `pending` | Phase 71.6 (planned) | The adapter exists but nothing calls it. |
| Credit memos / voids / invoice update to provider | Missing | No credit-memo or void call in the providers. Local credit memos are not pushed specifically | Phase 71.4 (planned) | |
| Accounting webhooks | Missing | No QBO/Xero webhook receiver | Phase 71.7 (planned) | |
| Stripe | Partial — adapter, mocked | `integrations/providers/payment/stripe.py:103`; webhook signature check `payments/webhooks.py:135`; `payments/tests.py:1` ("All provider HTTP is mocked") | Phase 72.1 | Not verified in test mode. |
| GoCardless | Partial — adapter, mocked | `integrations/providers/payment/gocardless.py:26-48`; `payments/webhooks.py:204` | Phase 72.2 | Sandbox URL is asserted, never called. |
| Refunds / chargebacks | Partial — mocked | `payments/services.py:496-600`; `Dispute` `payments/models.py:366` | Phase 72.4 | |
| Tax providers (Avalara, TaxJar) | Partial — adapter, mocked | `integrations/providers/tax/avalara.py:33`, `taxjar.py:32`; `tax/tests/test_providers.py:1-3` (mocked) | Phase 72.5 | Manual rates and exemptions are tested (`tax/tests/test_services.py`). |

## M. Reports

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Customer / contract profitability | Needs improvement | `reports/queries.py:479-518`; `Contract.profitability_snapshot` `psa/models.py:2894`; `reports/tests_profitability.py` | Phase 75.1 / 3 | Revenue definitions disagree (see below). |
| Unbilled time | Partial | `reports/queries.py:1699` | Phase 36 | Covered contract time is valued at the bill rate as if billable. The client-account list is wrong (D). |
| Block-hour consumption | Working | `reports/views.py:2376,2672`; `psa/billing_review.py` | Phase 36 | |
| MRR / ARR | Working | `recurring_revenue` / `mrr_trend` `reports/queries.py:1485,1532`; `executive/metrics.py` | Phase 75.4 | Based on contract terms, not invoices. |
| AR aging | Working | `aging_report` `psa/views.py:6565`; `get_psa_balance` `psa/models.py:5264` | Phase 27 | |
| Utilization | Working | `technician_utilization` `reports/queries.py:589` | Phase 2/3 | |
| Consistent revenue / cost definitions | Needs improvement | `revenue_by_client` = invoice `total` **including tax** (`reports/queries.py:183-210`). `revenue_by_contract` = invoiced + `bundled_subtotal()`, and bundles are never billed (`:221-286`). `profitability_snapshot` = contract terms (`psa/models.py:2894-2920`). `DEFAULT_LOADED_RATE=60` is still used by `resourcing` (`reports/queries.py:342`, `resourcing/models.py:365`) | Phase 69.3 / 75.1 | Three revenue definitions. Tax is counted as revenue, and unbilled bundles are counted as revenue. |

## N. Customer portal billing

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Agreements (PSA contract terms) | Missing | `portal/agreement_views.py` serves signed *documents*, not billing contracts | Phase 75.2 / 77 (planned) | |
| Block balance / usage | Missing | No contract data in `portal/` or `templates/portal` | Phase 75.2 / 77 | |
| Invoices + pay links | Working (mocked providers) | `payments/portal_views.py:73-176` | Phase 72.3 | |
| Customer disputes | Missing | `payments.Dispute` is a provider chargeback | no phase — gap | |
| Cost/margin never exposed | Working | `payments/portal_views.py:12-14`; `pricing/serializers.py:1-8`; no cost fields in portal templates | Phase 75.5 | |

## O. Settings → Billing

| Capability | Status | Evidence | Roadmap phase | Notes |
|---|---|---|---|---|
| Billing settings page | Missing | `invoice_approval_threshold_total`, `invoice_approval_overage_pct`, `late_fee_pct`, `late_fee_min_days_overdue`, `psa_auto_push_recurring_invoices` (`core/models.py:1047-1085`) appear in no form, template or admin | no phase — gap | Configurable only from a shell. |
| Payment gateway settings | Working | `/payments/` connections `payments/urls.py:10-15` | Phase 72 | |
| Tax settings | Working | `/tax/settings/` `tax/urls.py:8-21` | Phase 72 | |
| Accounting connection | Working | integrations views (OAuth in providers) | Phase 44 | |
| Price book / rate cards / billing rules | Admin only | `pricing/admin.py` | Phase 68/69 | |

---

## Genuine gaps (no phase covers them)

1. Prepaid-hours **ledger**: transactions, manual adjustments with audit, immutability, earliest-expiry consumption, multiple blocks per customer, negative-balance policy, low-balance alerts.
2. Per-billing-cycle allowance reset for retainers. Today the allowance spans the whole contract window.
3. A **single coverage resolver** with explicit precedence for hybrid or overlapping agreements. Consumption should follow the entry's `contract` FK instead of client + date.
4. Consumption tied to **time approval**, with reversal when an entry is rejected.
5. Coverage exclusions by onsite/remote, after-hours and service category. Automatic `rate_type` (after-hours, holiday) from time of day and calendar.
6. Applying `BillingRule` (minimums, increments, trip/dispatch fees) and rate-card snapshots in **invoicing**. T&M time with no contract invoices at $0 today.
7. Ticket "Add item" from the catalog with cost vs sale price and a permission gate. Ticket billing preview. Agreement picker on time entries.
8. Cross-ticket ready-to-bill queue and consolidated invoices (tickets + charges + contract).
9. Invoice presentation options (grouping, detail level).
10. Recurring billing in arrears, failed-billing notifications and a UI dry-run.
11. Quote options (good/better/best, optional or exclusive items), recurring vs one-time quote totals, quote templates, versions, multi-signer, decline, expiry job, margin guardrails, deposits and payment schedules, change orders.
12. Ticket estimate and out-of-scope customer approval.
13. Customer billing disputes in the portal.
14. Web market research with cited sources for the pricing advisor (OPTIONAL AI).
15. A Settings → Billing page for the existing billing `SystemSetting` fields.
16. Project deposits and commercial change orders.

## Roadmap statuses that look wrong

- **Phase 68.1 "Price book and products *(shipped)*"**: only models and Django admin exist. There is no staff UI and no production caller of `resolve_price`. It should read "partial — models/admin shipped; UI planned".
- **Phase 68.2 "Service plans *(shipped)* … that a contract can reference"**: `psa.Contract` has no service-plan FK, and plan per-unit prices and minimums are never billed. Only onboarding draft lines read them.
- **Phase 69.1 / 69.2 *(shipped)***: rate cards and snapshots exist, but **invoicing ignores them** (`uninvoiced_billing_lines` uses `contract.hourly_rate` or 0). The time UI never sets `rate_type`. Shipped for reporting only.
- **Phase 69.3 "Remove placeholder rates *(shipped)*"**: `DEFAULT_LOADED_RATE = 60` is still used by `resourcing.TechCostRate.rate_for` and resourcing views (`resourcing/models.py:365`, `resourcing/views.py:812-855`).
- **Phase 70 [planned] / 70.3 *(planned)***: signed document → draft billing contract already exists (`contracts/services.py:725`, tested). 70.3 should be "partial".
- **Phase 71.6 "Payment posting *(planned)*"**: `record_payment` adapters exist for QBO and Xero but are not wired. Better as "partial — adapters exist, not wired".
- **Phase 1 [complete]**: "Bundled services" are modelled but never billed (that is 70.4). "Proration — mid-month start/cancel" covers the start only. "Prepaid block hours" has no ledger, and the allowance does not reset per cycle. Annotate as partial or move the remainder to Phase 70/92.
- **Phase 36 [complete]**: the bullets "Agreement profitability reports" and "Revenue leakage detection expansion" (aging buckets, per-tech attribution, trend) carry no shipped marker. The client-account unbilled list is also inaccurate.
- **Phase 15 [shipped]**: "recurring" `Charge` rows are never generated. Phase 92.1 already admits this, but the Phase 15 header implies it works.
- **Phase 72.1 / 72.2 / 72.5**: correctly flagged "needs verification". All payment and tax tests are mocked. The QBO/Xero items under Phase 44 / 71 carry no such flag but are equally mock-only.
- **Phase 75.1 Profitability analytics *(shipped)***: works, but revenue definitions are inconsistent: tax is included, unbilled bundles are counted, and contract revenue comes from terms rather than invoices.
