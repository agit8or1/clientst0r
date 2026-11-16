# Business Overview metrics (executive dashboard)

Roadmap Phase 75 (executive dashboard). Page: **Dashboard → Business Overview**
(`/reports/business-overview/`, app `executive`). This file lists every card, the
data it reads and what still has to land for it to be live.

## How a card works

* Each card is a provider class in `executive/providers.py` (`key`, `title`,
  `permission`, `supported_filters`, `columns`, `collect()`). `collect()` returns the
  value **and** the rows behind it in one call, so a card's drill-down
  (`/reports/business-overview/metric/<key>/records/`, HTML or `?format=json`) is
  exactly the records that make up the number.
* A card is one of: `ok` (a value, possibly flagged **incomplete** with a reason),
  `not_configured` (the app or integration is not installed or not set up — no value,
  never a zero), `forbidden` (the role does not cover it) or `error` (logged).
* Unknown stays unknown: a margin with unpriced hours, an unbilled total with no
  priced entry and a utilization with no available-hours basis show "—" and an
  **Incomplete** badge with the reason ("12 hours without a cost rate"), never 0.
* Calculations are the reports' own (one source of truth); the dashboard does not
  re-derive revenue, cost, MRR, churn, utilization, unbilled time, renewals, SLA or
  aging.
* Scope: one MSP per install, Organization = customer. Each card needs its
  permission MSP-wide (`reports.access.has_msp_wide_perm`) and is computed over the
  technician's client scope (`reports.access.viewer_client_scope`), the rule the
  profitability reports use. A customer filter only narrows that scope. Customer users
  never reach the page (`/reports/` is staff-only, and each view checks again).
* Each card loads from its own JSON endpoint (`/metric/<key>/`), cached for five
  minutes per (metric, permission, client scope, filters), so one slow source does
  not hold up the page.
* Filters: date range, customer, service line (contract type), location. Each card
  declares which it uses; the others are greyed out on the card, and one the viewer
  set but the card ignores is shown struck through.

## Metrics

| Card | Key | Source (calculation reused) | Permission | Filters | Status |
|---|---|---|---|---|---|
| MRR & ARR (12-month trend, MoM growth) | `mrr_arr` | `reports.queries.recurring_revenue`, `mrr_trend` | `reports_view_financial` | date (as-of end), customer | Live (dev/profitability, merged in batch-692) |
| Invoiced revenue by month, by service line | `revenue_trend` | `reports.queries.revenue_by_client`, `revenue_by_service_line`; rows: the same invoices | `reports_view_financial` | date, customer, service line | Live |
| Gross margin (operational estimate, not accounting results) | `gross_margin` | `reports.queries.profitability_by_client` + `reports.costing.summarize` | `view_profitability` | date, customer | Live (dev/profitability). Incomplete while hours lack a cost rate |
| Customer profitability, top / bottom 5 | `customer_profitability` | same as gross margin | `view_profitability` | date, customer | Live; customers with unknown margin are listed but not ranked |
| Customers: growth & churn | `customer_growth` | `reports.queries._contracts_running_on`, `contract_churn` | `reports_view_financial` | date, customer, service line (churn covers every line) | Live |
| Contract renewals 30 / 60 / 90 days, MRR at stake | `contract_renewals` | `reports.queries.contracts_expiring` | `reports_view_financial` | customer | Live |
| Outstanding quotes, count / value / aging | `outstanding_quotes` | `psa.Quote` (status sent) | `reports_view_financial` | customer | Live |
| Unbilled work (billable time not invoiced) | `unbilled_work` | `reports.queries.unbilled_time` (bill rates from `reports.costing`) | `reports_view_financial` | date, customer | Live; rows are per customer (the function's grain). Rate snapshots (dev/price-book, merged) improve pricing |
| Accounts receivable, aging | `accounts_receivable` | `psa.models.get_psa_balance` per customer (the aging report's rule); source says when invoices carry synced accounting status (`provider_synced_at`) | `billing_view_aging` | customer | Live. Note: like the aging report, any non-void invoice with a balance counts, drafts included |
| Payments needing attention (failed payments, autopay failures, open disputes, collected online) | `payment_collection` | `payments.PaymentAttempt`, `payments.Dispute` | `billing_view_invoices` | date, customer | Live once a payment gateway connection exists (dev/payments, merged); otherwise not configured |
| Technician utilization | `technician_utilization` | `reports.queries.utilization_summary` | `reports_view_capacity` | date, customer | Live; incomplete for technicians without shifts, working hours or a billable target |
| SLA attainment (resolution) and response SLA met | `sla_attainment` | `reports.queries.sla_trend_by_priority`; rows: the same tickets with breach flags | `reports_view_sla` | date, customer | Live |
| Ticket backlog and age | `ticket_backlog` | open `psa.Ticket` (status not terminal) | `reports_view_sla` | customer, location | Live |
| Critical customer issues (open P1s, high / critical security incidents) | `critical_issues` | `psa.Ticket`, `security_alerts.SecurityIncident` | `tickets_view` (+ `security_alerts_view` for incidents; incomplete without it) | customer, location (tickets only) | Live |
| Security alerts (open, by severity) | `security_issues` | `security_alerts.SecurityAlert` | `security_alerts_view` | customer | Live when a vendor connection, SIEM endpoint or alert exists |
| Backup failures | `backup_failures` | open `backup_monitoring.BackupAlert` | `view_backup_status` (falls back to `monitoring_view` until that key exists) | customer | Pending: `dev/backup-monitoring` (not installed here → not configured) |
| Procurement (requisitions awaiting approval, open POs, back-orders) | `procurement_status` | `psa.PurchaseRequisition`, `PurchaseOrder`, `POBackOrder` | `procurement_view` | customer | Live |
| License renewals, 90-day exposure | `licensing_renewals` | `licensing.LicenseSubscription` (renewal date, customer price × seats) | `reports_view_financial` | customer | Pending: `dev/licensing` (not installed here → not configured) |

## Not on this page by design

* No raw audit-log or activity feed.
* No costs or margins for anyone without `view_profitability`; never for customer users.
* Price book, plans and rate cards (`pricing`) and sales tax (`tax`) feed the reports
  above (bill rates, snapshots); they have no card of their own.
