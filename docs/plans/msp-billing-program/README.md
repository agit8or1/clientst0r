# MSP billing, quote-to-cash, CRM discovery and optional AI pricing program

Received 2026-11-20 as three specifications (billing and ticket charges; CRM discovery, workload estimation
and optional AI pricing and quoting; quoting, e-signature, contract conversion and billing enhancements).
This file consolidates them. The capability audit that maps each item to the existing code and roadmap
phases is [CAPABILITY_AUDIT.md](CAPABILITY_AUDIT.md); the roadmap phases that carry the work are listed at
the end.

## Non-negotiable rules

1. Do not break existing installations, APIs, workflows or integrations. Backward-compatible migrations,
   feature flags, staged rollout, reversible configuration.
2. Audit existing functionality before implementing anything. Extend the existing models and modules
   (contracts, block hours, retainers, invoices, time entries, expenses, recurring billing, price book,
   quotes, signing, payments, accounting, CRM, profitability). Never build a second billing engine, a second
   CRM, a second quote or signing module, or competing revenue and cost definitions.
3. Tenant isolation, server-side permissions and historical data are preserved. Single-MSP and multi-tenant
   deployments both work.
4. All billing and quoting works without AI. Every AI feature is individually optional, off by default on
   existing installs, tagged OPTIONAL AI and gated by `psa_ai_enabled`.
5. AI never silently changes invoices, contracts, prices or live financial records, never approves, signs or
   sends anything binding, and never invents prices, sources, customer requirements or commitments.
6. Every billable transaction has an auditable origin. Finalized invoices and signed documents are never
   rewritten; corrections use credit notes, reversals, amendments or new revisions.
7. Financial integrity: atomic transactions, idempotent hour deduction, invoice generation and conversions,
   locking against concurrent workers, decimal-safe money, explicit rounding, effective-dated rates and
   contract versions, timezone-aware billing periods, no hard-coded tax assumptions.
8. Never bill on unverified device or user counts. Never store card data outside approved payment providers.
   Never call a stub, adapter or mocked integration production-ready.
9. Do not mark anything complete until it is independently tested. Statuses used: Available, Limited,
   Planned, In development, Beta, Production ready.
10. Simple for technicians and small MSPs (Quick Quote, Quick Invoice, Add Ticket Charge, Select Plan, Send for
    Signature, Convert to Contract); advanced functions stay available without crowding the simple path.

## A. Billing plans and service contracts

Reusable plan templates (clone, version, assign, customise per customer) for:

- **Prepaid block hours.** Purchased, available, consumed, reserved and expired hours; multiple concurrent
  blocks consumed earliest-expiry first unless terms say otherwise; expiration, rollover, automatic or manual
  replenishment, low-balance alerts, overage rate, negative balance only when configured and audited,
  customer approval before exceeding, authorized manual adjustments, full transaction history, customer-visible
  balance, reconciliation. A block purchase is not counted as revenue again when hours are consumed (cash,
  invoicing and recognized revenue tracked consistently).
- **Unlimited / fully managed.** Fixed recurring fee; unlimited only within defined coverage (service category,
  technician tier, location, asset type, schedule, remote vs onsite, business hours); exclusions billed
  separately with after-hours and emergency surcharges; all labor tracked for profitability; optional
  fair-use review thresholds that never charge covered work.
- **Break/fix time and materials.** Rate cards (remote, onsite, travel, after-hours, weekend, holiday,
  emergency; per technician or service level), minimum billable time, billing increments, trip charges,
  parts and materials, estimates and spending authorization, deposits, approval thresholds before exceeding
  an estimate.
- **Monthly retainer with included hours.** Recurring fee, included hours per period, usage tracking,
  overage, rollover and expiration, mid-cycle proration, multiple labor rates and exclusions.
- **Per user / per device / metered.** Users, workstations, servers, network devices, locations, mailboxes,
  licenses, backup usage; base rate, minimum commitment, tiers, discounts, quantity snapshots per period,
  manual adjustments and reconciliation before invoicing, mid-cycle changes with proration; Rem0te and other
  RMM counts only as verified input.
- **Hybrid.** Several compatible agreement components per customer; every charge resolves to exactly one
  agreement by documented precedence and effective dates; ambiguous overlap needs explicit precedence or an
  authorized selection.
- **Projects.** Fixed fee, milestones, T&M, deposits, progress payments, budgets, materials, change orders,
  remaining budget, profitability; reuse existing projects, quotes and invoices.
- **Contract setup wizard.** Customer → Plan → Pricing → Coverage → Billing schedule → Review → Activate;
  terms, renewal and auto-renewal, cancellation, frequency, payment terms, discounts, inclusions and
  exclusions, SLAs, covered users/sites/equipment, billing contacts, tax exemptions, account manager, signed
  documents; effective-dated amendments that never rewrite past invoices or deductions; each ticket shows
  which agreement covers it and why.
- **Service package builder and profitability calculator.** Expected hours, loaded labor cost, license,
  monitoring, security and backup costs, other direct costs; required price = cost / (1 − target gross
  margin); missing costs are flagged, never treated as zero; gross margin kept separate from net profit.

## B. Billing inside tickets (highest priority)

- **Time & Charges section** on every applicable ticket: start/stop timer, manual time, edit unapproved
  entries, work category, work type (remote, onsite, travel, after-hours), public description and internal
  note, classification (billable, covered, non-billable, warranty, goodwill, awaiting classification),
  agreement selection when permitted, calculated treatment shown: actual time, rounded billable quantity,
  rate, covered hours, remaining block hours, chargeable overage, estimated customer charge. Reuses the
  existing time-entry and timesheet workflows.
- **Add Item**: labor, parts, hardware, software, licenses, materials, travel, shipping, third-party services,
  miscellaneous, credits and discounts (permissioned); catalog search or one-off entry; quantity, unit, cost,
  sale price, markup or margin, discount, tax class, customer visibility, approval status, inventory source,
  asset, serial number, supplier. Technicians see selling prices, not costs or margins, unless permitted.
- **Ticket billing summary** (agreement, hours before, eligible labor, balance after approval, items, unbilled
  total before tax) with Add Time, Add Item, Review Charges, Request Approval, Send to Billing. Closing a
  ticket never hides or discards unbilled items; unreviewed charges are flagged for billing.
- **Customer approval of extra work** from the ticket: itemized estimate sent through a secure link; approve,
  decline or ask for clarification; approver, timestamp, exact estimate revision and decision recorded; work
  and invoices link to the approval; changes beyond contract thresholds need a new approval.

## C. Billing classification engine and hour ledger

On approval of a time entry: resolve customer and agreement, coverage, included/prepaid/chargeable, role and
service class, date and rate, business vs after-hours, remaining allowance, whether customer approval is
needed, resulting covered and billable amounts. Draft time consumes nothing; approved covered time consumes
the allowance; unlimited covered time is tracked, not invoiced; break/fix and overage become invoice
candidates; rejected or reversed entries release their allocation; partial coverage splits (1 h block + 2 h
overage); an invoice can never consume the same hours again. Immutable ledger of postings and adjustments
(source time entry, agreement, date, quantity, status, reversal) with transactions, locking and idempotency
keys against retries, scheduled jobs and concurrent workers.

## D. Ready for Billing queue and invoicing

Queue of approved unbilled time, parts, travel and expenses, overages, recurring charges, milestones,
customer-approved work, items needing review and exceptions; review, modify, approve, hold, exclude, adjust,
consolidate. Invoice from a ticket, several tickets on one invoice, selected charges, monthly consolidated,
project, recurring, one-time and batch invoices; drafts and approval workflow; credits, discounts, tax, PDF,
email, portal. Every line keeps its source reference; retries never double bill; finalized invoices are
corrected only by credit notes or reversals. Presentation choices: itemized labor, grouped by ticket, monthly
summary, full ticket breakdown, summary with service report; MSP branding.

## E. Recurring billing

Monthly, quarterly, annual and custom cycles; advance or arrears; billing day; proration; effective-dated
price changes; renewal reminders; usage reconciliation; grace periods; suspension; cancellation; discounts;
payment status; failed-billing alerts. Each run idempotent with a job audit; preview / dry run before
automatic billing is switched on.

## F. Price book, catalog, inventory and procurement

MSP catalog categories (labor, managed plans, hardware, software and subscriptions, licensing, networking,
cabling and materials, cloud, backup, security, miscellaneous); SKU, vendor, cost, price, markup and margin,
tax class, unit, one-time vs recurring, interval, active flag, preferred supplier, inventory tracking;
customer-specific, bundle, volume and effective-dated pricing; catalog search inside tickets, quotes,
projects, contracts and invoices; managed in the app, not Django admin; stale distributor price warnings and
authorized refresh that never alters a signed quote. Inventory: availability by location, reservation and
consumption as distinct events, stock deducted once, actual cost recorded, links to ticket and asset, serial
numbers, returns, RMAs and credits, purchase for a ticket, non-stock materials, one-off parts.

## G. Quoting, e-signature and conversion (quote-to-cash)

- **Quote builder improvements:** branding, scope, recurring and one-time lines with separate totals (monthly
  recurring, one-time subtotal, contract value shown separately, tax separately), discounts, payment terms,
  contract length, effective and expiry dates, assumptions and exclusions, editable versioned templates fed by
  plans and the price book.
- **Good / Better / Best** options in one proposal; recommended option labelled; the customer selects one; the
  signed record captures exactly which package and options; alternatives never all activate.
- **Optional items:** mandatory, optional, mutually exclusive, quantity limits, dependencies, fixed bundles;
  deterministic totals; customers never edit prices; the chosen configuration becomes a fixed revision
  (internally approved when needed) before signing, and the signature evidence covers options, quantities,
  prices, terms and totals.
- **E-signature (extend what exists):** keep revision hashing, evidence, PDF snapshots, tamper detection and
  locking; add or verify mobile signing, typed/drawn signatures, signer identity and optional email codes,
  multiple and sequential signers, MSP countersignature, expiry, resend, reminders, decline with reason,
  history, customer copy. No claim of universal legal compliance.
- **Quote → contract (critical):** Approval → Sent → Signed → Countersigned → Conversion review → contract,
  one-time invoice, project, onboarding and draft procurement as chosen and authorized; the agreement inherits
  package, inclusions, exclusions, recurring and one-time charges, included and block hours, overage rates,
  quantities, term, frequency, payment terms, effective dates, renewal and SLA; the signed legal document and
  the operational billing contract are distinct and explicitly linked; conversion is idempotent.
- **Quote → invoice:** one-time items, hardware, labor, materials, onboarding, deposits, milestones; never the
  whole contract value up front unless agreed; no duplicate one-time charge for recurring items; prices frozen
  at acceptance; lines reference the quote and catalog item.
- **Deposits and payment schedules:** percentage or fixed deposits, hardware in advance, milestones; deposit
  invoice, balance due, application to final charges, refunds or credits; deposits not recognized as earned
  revenue early.
- **Change orders** through the quote and signing path: original agreement preserved, difference, effective
  date, authorization, resulting contract/project/invoice changes, version history.
- **Customer proposal experience:** branded proposals, package comparison, permitted option selection,
  terms, sign without a portal account through a secure, revision-bound, optionally time-limited link,
  download, status, invoices and verified payment; no costs, margins or internal notes.
- **Guardrails and tracking:** margin and discount approval thresholds before sending; immutable accepted
  revisions and version history; expiry and configurable follow-ups; quote-to-cash dashboard with blockers
  and next actions; sales analytics (win rate, average value, MRR sold, cycle times, lost reasons) kept
  separate from contracted and recognized revenue; customer timeline built only from recorded events;
  renewal and upsell review before expiry.

## H. CRM IT discovery and workload estimation

- **IT Discovery wizard** on leads, opportunities and existing customers (renewals): business, devices,
  servers and infrastructure, network, cloud and applications, security, support requirements, current
  issues, goals, attachments; checkboxes and numbers, optional advanced sections, help, templates by customer
  type, autosave, drafts, duplication, mobile layout, printable summary and PDF; nothing mandatory to save;
  missing or estimated values marked. Optional imports (CSV, existing assets, authorized Rem0te inventory)
  never overwrite verified data. Extends the existing CRM; no second CRM.
- **Rules-based workload and cost estimator** (no AI): configurable coefficients, helpdesk, server, network,
  security, on/offboarding, travel and onsite hours, direct costs, onboarding projects, low / expected / high
  scenarios with margins, packages flagged when unprofitable at high utilization; optional calibration from
  the MSP's own history, tenant-isolated, measurements kept apart from assumptions.
- **Standard proposal generation** from an assessment: services, licenses, labor, direct costs, onboarding,
  plan templates, pricing against target margins, editable options, human review; never auto-sent.
- **Accepted proposal conversion:** quote → signed agreement → contract → onboarding (templates, discovery
  data carried over, checklists, staff, milestones) → recurring billing on agreed dates; opportunity marked
  won; no external provisioning or ordering without separate authorization; idempotent.

## I. Optional AI (each switch separate, off by default)

- **Workload review:** explain drivers, missing information, complexity, coverage suggestions, extra discovery
  questions; the arithmetic stays reproducible without AI.
- **Market Pricing Advisor:** geographic markets (city, ZIP, county, metro, state, region, national, remote);
  configurable research/search provider; legitimate public sources only (published MSP prices, rate cards,
  public procurement, surveys, vendor lists), respecting terms, paywalls and rate limits; every observation
  stores source, URL, retrieval date, region, description, price, currency, unit, terms, confidence and
  comparability; verified prices kept apart from estimates; nothing invented. Item-level "Analyze Pricing",
  package and custom-package pricing with scope normalization; recommendations combine market evidence with
  internal costs and never override profitability; prices change only on explicit acceptance.
- **Prospect proposal:** "Analyze Prospect & Build Quote" (assessment → workload → costs → market evidence →
  Basic/Standard/Premium → margins → risks and gaps → editable proposal → existing quote workflow); opportunity
  scoring with visible factors; AI proposal writing from factual data only, fully editable; quote editor
  assistant buttons. Approval stays human.
- **Reports and customer reviews:** market and pricing intelligence reports with methodology, sources and
  limitations (PDF, CSV, saved, historical); existing-customer profitability reviews and renewal
  recommendations; what-if simulator separating facts, assumptions and AI recommendations.
- **Settings → Billing → AI Pricing & Intelligence:** master and per-feature switches, provider and model,
  search provider, encrypted keys, default market and territories, target margins, monthly budgets and request
  limits, data-sharing rules, research retention, permissions; redaction and minimization, no secrets sent,
  prompt-injection protection for web content, usage and cost logging, spending ceilings. A self-hosted model
  does not by itself provide current market data.

## J. Accounting, payments, portal, reports, settings, permissions

- **Accounting and payments:** audit what is operational; QuickBooks Online and Xero invoice changes, credit
  memos, refunds, voids, payment posting, tax mapping, retries and reconciliation screens, signed webhooks;
  Stripe and GoCardless verified with sandbox credentials before being called production ready; no automatic
  collection without merchant setup and customer authorization. Clientst0r is the operational source of truth
  (tickets, coverage, time, charge origins); accounting is the financial ledger of record; documented
  conflict rules; useful without an accounting provider.
- **Customer portal:** agreements, plans, block balances and usage, service summaries, invoices, payment status
  and links, outstanding charges, renewals, quotes, approvals, disputes and explanation requests; never costs,
  margins, internal notes or another customer's data.
- **Reports:** customer and contract profitability (MRR, one-time revenue, hours, labor cost, parts, third-party
  costs, gross profit and margin, effective hourly revenue; partial costs labelled as partial), unbilled time,
  block consumption and expiring hours, recurring revenue, revenue by technician, utilization, write-offs,
  discounts, overages, unprofitable customers, revenue leakage, aging and collections, labor recovery, product
  margin, project budget vs actual; billed vs collected vs recognized revenue kept distinct; filters and CSV;
  one set of financial definitions across dashboards.
- **Settings → Billing:** general, plans and templates, labor rates, time tracking and rounding, price book,
  block-hour rules, recurring billing, invoices, tax, payments, accounting, approval rules, notifications,
  permissions, AI pricing; global defaults overridable per customer and contract with the source of each value
  shown.
- **Permissions:** technician (time, authorized parts, classification, selling prices when permitted, no
  margins), manager (review, approve, adjust, exceptions), billing administrator (plans, invoices, credits),
  owner / financial administrator (all financials, rates, costs, sensitive adjustments, integrations), customer
  (own authorized data only); all enforced server-side, including APIs and workers.

## Priorities (combined)

- **P0 — financial correctness and the quote-to-billing loop:** ticket Time & Charges, approval-time hour
  deduction ledger, coverage resolution and overage split, ticket parts billing, Ready for Billing queue,
  idempotency and audit; quote → contract and quote → invoice conversion with correct recurring vs one-time
  classification, source links, duplicate prevention, signed-revision integrity, end-to-end tests.
- **P1 — usability:** price-book selection in editors, quote templates, package comparison, optional items,
  deposits, change orders, ticket estimate approvals, margin guardrails, plan templates and contract wizard.
- **P2 — CRM discovery and sales:** discovery wizard, rules-based estimator, Good/Better/Best generation,
  proposal conversion, onboarding automation.
- **P3 — optional AI:** market pricing with sourced evidence, AI proposals and package recommendations,
  profitability analysis, market reports.
- **P4 — integration hardening:** payment sandbox verification, accounting completion, supplier price updates,
  renewal recommendations, quote-to-cash analytics.

Financial correctness and security fixes are never postponed for AI features.

## Required acceptance tests (summary)

Billing: block deduction, partial overage split, unlimited generates no labor charge, break/fix labor and parts
on the invoice, retainer overage, concurrent workers cannot deduct twice, closed tickets keep unbilled items,
consolidated invoicing does not double bill, inventory deducted on the right event, existing contracts and
invoices survive upgrade. Quotes: create and save, price-book snapshots, internal approval and send, customer
signs the exact approved revision, edits require a new signable revision, selected options in the evidence,
one contract per accepted quote, one-time charges become invoice candidates, recurring charges at the agreed
frequency, conversion retries create no duplicates, deposits apply correctly, change orders preserve the
original, ticket charges can require approval, onboarding only when authorized. CRM: assessments complete and
save partially, create a quote, persist through conversion, stay permission-controlled. Estimation: works
without AI, adjustable, three scenarios, missing inputs warned, history tenant-isolated. AI: item and custom
package analysis, cited sources, nothing invented, geographic scope respected, no silent financial changes,
everything works with AI off. Security: technicians cannot see costs or margins, customers cannot see other
tenants, AI requests carry no secrets, approval thresholds cannot be bypassed through APIs, existing installs
run unchanged with the new modules off, payment tests use legitimate sandbox credentials.

## Documentation

ROADMAP.md, FEATURES.md, billing, CRM discovery, service plan, quoting, AI market pricing, calculation
methodology, permissions, integration and upgrade documentation, screenshots and showcase — updated only when
a capability is demonstrated, with implemented code distinguished from tested, production-ready functionality.
