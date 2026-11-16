# MSP commercial operations — Phase 0 audit

Feature matrix for the commercial operations program (roadmap Phases 68–75). Static code audit of
`dev-work` at v3.17.687; no provider was contacted and no tests were run for this document.
Paths are relative to the repository root.

**Status legend:** Fully implemented / Partial / Stub only / Planned / Missing / Requires real-provider
testing (code exists, but only mocked or fixture coverage).

Naming traps to keep in mind: `psa.Contract` is the billing contract, `contracts.ContractDocument` is the
legal document; `psa.ServiceCatalogItem` is a ticket-request template, not a price catalog;
`hardware.CatalogSource` is a spec-import source.

## 1. Price book and service plans

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Price book / product / SKU model | Missing | no model; `psa/models.py:1049` is a ticket template | Phase 1a in progress on `dev/price-book` |
| Service plans / entitlements | Missing | proxy only: `psa/models.py:2236` Contract, `:2871` ContractMeter, `:2929` ContractBundleItem | Plans are derived from contract data today |
| Catalog link on quote / invoice / contract lines | Missing | `QuoteLineItem` `psa/models.py:3441`, `InvoiceLineItem` `:4782`, no catalog FK | Extension points for the price book |
| Cost and markup on quote lines | Missing | `QuoteLineItem` has only `unit_price` | No per-line margin anywhere |
| Distributor price into quotes | Missing | pricing is looked up live and never persisted | See section 9 |

## 2. Labor rates and cost rates

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Tech cost rates, effective-dated | Fully implemented | `resourcing/models.py:288` TechCostRate, `rate_for` `:318` | Falls back to a flat loaded rate |
| Billable targets | Partial | `resourcing/models.py:265` | One row per tech, not effective-dated |
| Labor rate card (role / client / ticket type) | Missing | only `Contract.hourly_rate` `psa/models.py:2284`, `Project.billing_rate` `:1571` | Planned on `dev/price-book` |
| Rate snapshot on time entries | Missing | `TicketTimeEntry` `psa/models.py:901` has no bill/cost rate columns | Rate is resolved at invoice time, so history drifts |
| Role code on time entries | Partial | free text, used only for gating | |

## 3. Contracts and recurring billing

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Billing contract types and lifecycle | Fully implemented | `psa/models.py:2236`; lifecycle `:2618-2645` | Pause, resume, cancel at period end, rollover, proration |
| Recurring invoice generation | Fully implemented | `psa/models.py:2488`; `psa/management/commands/psa_generate_recurring_invoices.py` | Dedup is an application-level lookup (`:2531-2536`), not a database constraint |
| Lifecycle crons | Fully implemented | `psa_auto_renew_contracts`, `psa_advance_subscription_lifecycle`, `psa_recompute_contract_hours` | |
| Meter lines (seat / device / GB) | Fully implemented | `psa/models.py:2871` | Billed and reset by `generate_invoice` |
| Bundle items on invoices | Partial | `psa/models.py:2929` | Display and profitability only; not billed by `generate_invoice` |
| Recurring one-off charges | Stub only | `psa/models.py:5029` Charge | No generator command found |
| Legal contract documents and e-signing | Fully implemented | `contracts/models.py:316`, `:482`, `:710` | Separate app (Phase 65) |
| Signed document to billing contract | Partial | `contracts/services.py:725` | Draft only, always managed services; ignores line items, hours and rates; no next billing date |
| Invoices, credit memos, late fees | Fully implemented | `psa/models.py:4290`; `core/tests/test_billing_credit_memos.py` | |
| Billing review and approval gate | Fully implemented | `psa/billing_review.py` | |

## 4. Quotes

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Quote model, lines, totals | Fully implemented | `psa/models.py:3116`, `:3441` | No optional lines, discounts or recurring flag |
| Approval chain | Fully implemented | `psa/models.py:3362`, `:2011` | |
| E-signature | Fully implemented | `psa/models.py:4939`; portal sign page | Token link, not a portal-login view |
| Quote to contract | Missing | `mark_accepted` `psa/models.py:3322` creates a ticket or project only | |
| Quote to invoice | Missing | `Invoice.source_quote` `:4339` and source `quote_line` `:4787` exist but nothing sets them | Dead scaffolding |
| Quote to purchase order | Partial | `PurchaseOrder.source_quote`; `psa/views.py:7954` | |
| CRM opportunity to quote | Partial | `crm/models.py:145`, quote FK `:190` | |

## 5. Time entries

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Time entry, approval, audit trail | Fully implemented | `psa/models.py:901`, `:3516`, `:3635` | |
| Contract consumption from time | Fully implemented | `psa/models.py:2739`, `:2802`; `psa/signals.py` | |
| Immutable bill and cost rate | Missing | see section 2 | Phase 69 |
| Invoiced flag on entries | Partial | derived from `InvoiceLineItem.billed_source_ids` (`psa/models.py:4813`) | |

## 6. Accounting providers

| Capability | QuickBooks Online | Xero | Others |
|---|---|---|---|
| OAuth and token refresh | Fully implemented (`integrations/providers/accounting/qbo.py:46-120`); requires real-provider testing | Fully implemented (`xero.py:49-135`); requires real-provider testing | n/a |
| Customer push / pull | Fully implemented (`qbo.py:196-309`) | Fully implemented (`xero.py:195`, `:481`) | n/a |
| Invoice create | Fully implemented (`qbo.py:369-450`) | Fully implemented (`xero.py:231-312`) | n/a |
| Invoice update | Missing | Missing | n/a |
| Payment pull (including partials) | Fully implemented (`qbo.py:498`, `services/accounting_sync.py`) | Fully implemented (`xero.py:380-450`) | n/a |
| Payment push | Stub only: `record_payment` `qbo.py:452` has no caller | Stub only: `xero.py:315`, bank account placeholder | n/a |
| Credit memos / refunds | Missing | Missing | n/a |
| Void push | Missing (pull-only detection) | Missing (pull-only detection) | n/a |
| Tax code mapping | Missing | Missing | n/a |
| Item / account mapping | Partial, mislabelled (`qbo.py:386-395`) | Partial (`xero.py:255`) | n/a |
| Webhooks and signature checks | Missing | Missing | n/a |
| Idempotency on retry | Partial: writes are not retried, but no idempotency key or lookup before create | Partial: IdempotencyKey header unused | n/a |
| Sync history and errors | Partial: audit log row per call, no retry or dead-letter queue | Partial | n/a |
| Multiple connections | Partial: several per organization, no legal-entity model | Partial | n/a |
| FreshBooks, Wave, Zoho Books, Sage Business Cloud | Missing: enum choices only (`integrations/models.py:1457-1460`); selecting one reports "Provider class not registered" (`psa/views.py:6079`) | | |
| Intacct, Business Central | Missing: no choice, no adapter | | |

Registry: `integrations/providers/accounting/__init__.py:6-9` (QBO and Xero only). Vendor bills (AP) are Missing.

## 7. Payment providers

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Stripe | Stub only | `integrations/providers/payment/stripe.py:21-41` | `charge()` reports not implemented; no HTTP, webhooks, refunds or customer sync. In progress on `dev/payments` |
| GoCardless | Stub only | `payment/gocardless.py:20-35` | Same; in progress on `dev/payments` |
| Square, PayPal | Missing | no choice, no adapter | |
| Production caller of payment providers | Missing | only `integrations/tests.py:854-904` | Tests assert the stub behaviour |

## 8. Tax providers

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Avalara | Stub only | `integrations/providers/tax/avalara.py:16-33` | Returns failure and zero tax |
| TaxJar | Stub only | `tax/taxjar.py:18-32` | Same |
| Production caller | Missing | only `integrations/tests.py:929-972` | A caller that ignores `success` would read zero tax |
| Local tax on invoices / quotes | Fully implemented | `psa/tests/test_invoice_tax.py`, `test_tax_audit.py` | Quote default can be zero, see known issues |
| `AccountingConnection.default_tax_rate` | Stub only | never read | |

## 9. Distributors and procurement

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Adapters: Ingram Xvantage, Pax8, TD SYNNEX | Requires real-provider testing | `integrations/providers/distributors/` | Mocked / signature tests only |
| D&H, ScanSource, QBS, Westcoast | Missing | enum choices at `integrations/models.py:1311-1317`, no adapter | |
| TD SYNNEX catalog search | Stub only | `synnex.py` `list_products` returns an empty list | |
| Ingram production endpoints | Partial | hard-coded `/sandbox/` paths (`ingram_xvantage.py:14-16`, `:40`) | |
| Order placement | Stub only | adapters have `place_order`; no view or workflow calls it | |
| Order status / ASN | Missing | not in `base.py:60-93` | |
| Distributor webhooks | Partial | HMAC verify and `DistributorWebhookEvent` log; nothing updates PO state | |
| Requisitions, POs, PDF and email | Fully implemented | `psa/models.py:5183`, `:5313`; `psa/views.py:7489`, `:7512` | PO approval exists at requisition level only |
| Receiving, partial shipments, back-orders | Fully implemented | `psa/models.py:5457`, `:5516` | |
| Serial capture to assets | Partial | `psa/views.py:7576` | Bare asset; failures swallowed |
| Receipt to inventory stock | Missing | `po_receive` does not touch `inventory` | |
| RMA | Partial | `assets/models.py:1936` | Not linked to distributor RMA |
| Vendor bills / three-way match | Missing | | |
| Recurring purchases, replenishment suggestions | Fully implemented / Partial | `psa/models.py:6416`; `psa_auto_replenish_suggestions` | |

## 10. Licensing

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| License / subscription / seat model | Missing | none | In progress on `dev/licensing` |
| Microsoft 365 SKU and assignment visibility | Partial | `integrations/providers/m365.py:161`; `integrations/views.py:3285` | Live read only; no persistence, renewal dates or cost. Requires real-provider testing |
| Google Workspace licensing | Missing | | |
| Pax8 subscriptions | Missing | adapter covers products and orders only | |

## 11. Warranty and asset lifecycle

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Warranty lookup, in-app service | Requires real-provider testing | `assets/health.py:187` (Dell, HP, Lenovo) | Scheduled; no tests; credentials in `SystemSetting` |
| Warranty lookup, provider adapters | Stub only | `integrations/providers/warranty/*` | Duplicates the service above; nothing calls it; separate credential store |
| Expiry alerts | Fully implemented | `assets/management/commands/assets_warranty_alerts.py` | |
| Lifecycle fields and scoring | Fully implemented | `assets/models.py:197-233`, `:609` | |
| Purchase price / depreciation on assets | Missing | no field | |
| Asset to purchase order link | Partial | `SerialEvent` only (`assets/models.py:2027`) | No `Asset.purchase_order` |
| Replacement chain | Partial | RMA replacement serial only | |
| Serial lifecycle history | Fully implemented | `assets/serial_lifecycle.py` | |
| Hardware catalog (specs) | Fully implemented | `hardware/models.py:43-440` | No price or SKU; overlaps legacy `assets.EquipmentModel` |

## 12. RMM providers

| Provider | Status | Evidence | Notes |
|---|---|---|---|
| Tactical RMM | Requires real-provider testing | `integrations/providers/rmm/tactical_rmm.py` | Most complete: devices, alerts, software, services |
| NinjaOne, Datto RMM, Atera, ConnectWise Automate | Partial | `rmm/ninjaone.py`, `datto.py`, `atera.py`, `connectwise_automate.py` | Fact gaps per `rmm_fields.py`; mocked tests only |
| Rem0te | Fully implemented for devices and alerts | `integrations/providers/rmm/rem0te.py` | No software or health facts |
| N-central, N-sight, Pulseway, SuperOps, Action1, Kaseya VSA | Missing | registry `rmm/__init__.py:12-19` | |
| Remote actions for non-Rem0te providers | Missing | `rmm_permissions/catalog.py` | |
| Device workspace | Partial | `assets/device_workspace.py` | No events, processes, backup or security panels |
| Alert-to-ticket policy and dedup | Fully implemented for Rem0te; requires real-provider testing for synced alerts | `psa/routing/alert_policy.py` | |

## 13. Rem0te contract (ticket-rmm-v1, revision 2)

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Request signing, response and event verification, replay guard | Fully implemented | `integrations/rem0te/protocol.py`, `inbound.py` | Tested against a real Rem0te 0.30.1 (99 of 102 end-to-end checks) |
| Technician delegation tokens | Fully implemented | `protocol.py:313-337` | |
| Alert to one staff-only ticket | Fully implemented | `integrations/rem0te/alerts.py` | |
| Job survives restart | Partial | one end-to-end case failing | |
| Technician-mapped probe | Partial | relies on observed behaviour | |
| Remote session state, action status, ticket state, endpoint health | Missing | requests to Rem0te | Needed by Phase 74 |

## 14. Backup monitoring

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Customer backup job / status models | Missing | the `backups/` directory is the platform's own pre-upgrade backups | In progress on `dev/backup-monitoring` |
| Providers: Proxmox Backup Server, Veeam, Acronis, Cove, Datto, restic, borg, kopia | Missing | none | |
| Backup evidence in compliance packs | Stub only | `compliance/views.py:285` hard-coded to zero | |
| Backup alert classification | Partial | keyword in `psa/routing/alert_policy.py` | |

## 15. Security products

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Alert, incident and SIEM webhook framework | Fully implemented | `security_alerts/models.py:13-903` | |
| Microsoft Defender adapter | Stub only | `security_alerts/adapters/defender.py:1-45` | Reports success without calling the API |
| CrowdStrike, SentinelOne, Sophos, Huntress, Bitdefender | Missing | enum labels only | Generic webhook ingestion possible |
| Device-level security posture | Missing | | |
| Security alert ticketing and dedup | Partial | `security_alerts/adapters/base.py:71-127` | No join-to-existing-ticket or recovery |

## 16. Customer portal

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Tickets, KB, status, approvals, requests, agreements, pulse, sign-in | Fully implemented | `portal/urls.py:18-71` | |
| Quote view and signing | Fully implemented | `portal/views.py:579-731` | Token link |
| Invoices and balances | Missing | no portal view or template | `dev/payments` covers portal billing |
| Online payments | Missing | providers unwired | `dev/payments` |
| Device health, patch status, backup status, security posture, service plan view | Missing | | Phase 75 |

## 17. Profitability reporting

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Contract profitability snapshot | Stub only | `psa/models.py:2837` | Placeholder cost rate |
| Reports by client / contract / project / tech | Partial | `reports/queries.py:338-606` | Hard-coded fallback rates |
| Margin by service line | Partial | `reports/queries.py:1117` | Fallback bill rate |
| Project profitability | Partial | `psa/models.py:1681` | Margin empty without a rate |
| Executive dashboard | Planned | | Phase 75 |

## 18. Permissions

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Role flag registry and helpers | Fully implemented | `accounts/permission_registry.py:136-410`; `accounts/permission_utils.py` | Add a key with model field, registry entry, seed, enforcement and tests |
| RMM action permissions | Fully implemented | `rmm_permissions/` | |
| Commercial permissions (price book, rates, cost visibility, payments, procurement approval) | Planned | no keys yet | Cost and margin data must be sensitive and staff only |
| Backup, security-product and portal billing permissions | Missing | | |

## Known correctness issues

1. **Placeholder labor cost.** `Contract.profitability_snapshot` assumes cost is 60% of the hourly rate
   (`psa/models.py:2856`) instead of using tech cost rates.
2. **Hard-coded bill rate.** `DEFAULT_BILL_RATE` of $150 is applied when no rate is known
   (`reports/queries.py:876` and `:1117`).
3. **Hard-coded cost rate.** `DEFAULT_LOADED_RATE` of $60 (`reports/queries.py:335`) is also used as a
   stand-in retail rate in `profitability_by_tech` (`:652-664`).
4. **Duplicate invoice on push timeout.** A timeout or 5xx on invoice create saves no external id; a second
   push creates another invoice. No idempotency key and no lookup before create (`qbo.py:422`, `xero.py:270`);
   the guard at `psa/views.py:6041` is check-then-act without a row lock. Fix in progress on
   `dev/invoice-push-safety`.
5. **Recurring invoice dedup race.** Uniqueness of (contract, billing period) is an application check
   (`psa/models.py:2531-2536`) with no database constraint.
6. **QuickBooks ItemRef misuse.** `ItemRef.value` is filled from the GL account code (`qbo.py:386-395`), but
   QuickBooks expects an item id.
7. **Xero bank placeholder.** Payment push uses a reference fragment or the literal `'090'` as the bank
   account code (`xero.py:315`).
8. **Zero-tax fallback on quotes.** The quote tax rate defaults to zero when the system default is unset
   (`psa/views.py:4215`).
9. **Duplicated and stubbed adapters.** Warranty lookup exists twice (`assets/health.py:187` and the stubbed
   `integrations/providers/warranty/*`); the payment, tax and warranty adapters are never called; choices
   exist for providers with no adapter.
10. **Ingram sandbox only.** Hard-coded `/sandbox/` paths (`ingram_xvantage.py:14-16`, `:40`).
11. **Serial-to-asset errors swallowed.** `_maybe_create_assets_from_serials` ignores exceptions
    (`psa/views.py:7576`), so receiving can silently create no assets.
12. **Phase 44 overstated.** It is real for QuickBooks Online and (since v3.17.664) Xero customer sync, invoice
    create and payment pull. Invoice update, credit memos, refunds, tax mapping, webhooks and payment posting
    are not implemented (tracked in Phase 71).
13. **Smaller items.** Quote-to-invoice scaffolding is dead; bundle items are not billed; the legal-contract
    conversion ignores line items; `AccountingConnection.default_tax_rate` is never read; time entries carry no
    rate snapshot, so historical margin drifts when rates change.

## Work in progress

| Branch | Scope | Roadmap phase |
|---|---|---|
| `dev/price-book` | Phase 1a: price book, service plans, rate cards, rate snapshots | 68, 69 |
| `dev/invoice-push-safety` | Duplicate-invoice fixes for accounting push | 71 |
| `dev/backup-monitoring` | Customer backup monitoring | 74 |
| `dev/licensing` | Software license tracking | 73 |
| `dev/payments` | Stripe and GoCardless, and portal billing | 72 |

None of these is released. Features are marked shipped in `docs/ROADMAP.md` only when a release includes them.
