# Sales tax

Clientst0r works out the sales tax on quotes and invoices. It can use the
rate typed on each document, its own table of jurisdiction rates, or an
external tax provider (Avalara AvaTax or TaxJar). This page covers which system
calculates, reports and records each tax amount, how to avoid two systems
taxing the same invoice, and what happens when a provider cannot be reached.

Settings: **Administration → Integrations → Sales Tax** (`/tax/settings/`).
You need the `manage_tax_settings` role permission, which only MSP staff can
hold. Owner and Billing / Finance have it by default.

Each install serves one MSP, and every Organization is one of that MSP's
customers. Tax settings, manual rates and tax categories therefore apply to the
whole MSP and cover every customer, whichever customer is selected; they are
the rows with no organization. Exemptions belong to one customer. The tax
jurisdiction comes from that customer's billing address (street, city, state,
postal code and country on the client record).

## Modes

| Mode | Who calculates | Notes |
|---|---|---|
| **No sales tax** (`none`) | nobody | Draft quotes and invoices carry zero tax. The page says **"Tax not configured"**, so the zero is never silent. Documents already sent are not changed. |
| **Flat rate** (`flat`) | Clientst0r | The rate typed on each document, or the General settings default rate for new ones. Only lines marked taxable are taxed. With a 0% rate the document shows "Tax not configured". If no Tax settings exist, this is the mode in use. |
| **Manual jurisdiction rates** (`manual`) | Clientst0r | Uses the rate table and the customer's billing address. The single most specific matching rate wins (exact zip, then zip prefix, city, county, state, country). Rates do not stack, so each one is a combined rate. |
| **Avalara AvaTax** (`avalara`) | Avalara | REST v2 `transactions/create`. A preview is a `SalesOrder`, which Avalara does not record. A sent invoice is a committed `SalesInvoice`, and a credit memo is a `ReturnInvoice`. |
| **TaxJar** (`taxjar`) | TaxJar | `POST /v2/taxes`. A sent invoice is also reported with `POST /v2/transactions/orders`, and a credit memo with `POST /v2/transactions/refunds`. |

## Which system calculates, reports and records each amount

| Amount | Calculated by | Reported to the tax authority by | Recorded by |
|---|---|---|---|
| Quote tax (any mode) | Clientst0r, or the provider as an uncommitted preview | nobody (a quote is not a sale) | Clientst0r (`TaxCalculation`, quote totals) |
| Invoice tax, flat / manual | Clientst0r | you, from your own filings | Clientst0r. The accounting system records what it is sent. |
| Invoice tax, Avalara / TaxJar | the provider | the provider, once the invoice is committed (sent) | Clientst0r keeps the provider's figure. The accounting system records what it is sent. |
| Credit memo tax | same as the invoice | the provider (Avalara return / TaxJar refund) | same as the invoice |
| Voided invoice | none | the provider transaction is voided (Avalara) or deleted (TaxJar) | the void and any void error are kept on the calculation |

The **Authoritative system** setting records which of these applies to you.
The accounting push reads it from `tax_mapping_for_push()` (see below).

- *Clientst0r calculates*: the accounting system records the amount it is sent.
- *Provider calculates and reports*: Clientst0r and the accounting system both record the provider's amount.
- *Accounting system calculates*: Clientst0r's amount is an estimate, and the push does not send tax.

## Avoiding conflicts with QuickBooks Online / Xero automated tax

QuickBooks Online Automated Sales Tax (AST) and Xero's tax rates can calculate
tax on their own when an invoice reaches them. If Avalara, TaxJar or manual
rates are already calculating tax in Clientst0r, two systems may arrive at
different amounts. The customer would then be billed one figure while the books
record another, and `provider_tax_amount` drift appears on the invoice.

- When Clientst0r or an external provider calculates tax, we recommend
  disabling AST in QuickBooks Online (or using Xero tax rates that only record
  the amount they are sent). The accounting system then records Clientst0r's
  figure and does not calculate its own.
- If you prefer the accounting system to calculate, set the mode to `flat` or
  `none` and set **Authoritative system** to *Accounting system calculates*.
- Map each tax category to the accounting system's codes (QBO TaxCode Id, Xero
  TaxType) on the category page.

## The provider-failure rule

If Avalara or TaxJar fails, whether it returns an error, times out, cannot be
reached or sends a malformed answer:

1. The calculation is recorded with status **Error** and no tax amount. The
   document's tax is left as it was. It is never set to zero.
2. The quote or invoice **cannot be sent**: emailing it, or marking it Sent,
   is refused with the provider's error message. Manual mode does the same
   when no rate matches the customer's address, and every non-flat mode does
   the same when that address has no state or postal code.
3. A user holding `manage_tax_settings` can enter a **manual override** on
   the quote or invoice page. They give an amount and a reason. The override
   is written to the audit log and to the calculation history, and it covers
   the current lines only. Changing a line needs a new calculation.

Saving a draft also recalculates its tax. In provider modes that is a preview,
which the provider does not record. A failure there does not stop the save, but
the document stays blocked from sending until it is resolved.

## Exemptions

Exemptions are managed on the client page (Sales tax exemptions →
`/tax/clients/<id>/exemptions/`). An exemption applies only when all of these
hold:

- it has been **verified** (who verified it is recorded);
- it has a certificate number;
- the document date falls between its valid from and valid to dates;
- the customer's region (`US-CA`) is in its region list, or the list is empty.

The certificate file is stored as a private attachment. In flat and manual
modes an exemption sets tax to zero, and the reason and certificate number are
recorded on the calculation. In provider modes it is sent to the provider:
Avalara receives `exemptionNo` and `entityUseCode`, and TaxJar receives
`exemption_type`. The provider then records the exempt sale.

## Labor and categories

Tax categories give a line its taxability and its provider codes (Avalara tax
code, TaxJar product tax code, QBO TaxCode Id, Xero TaxType). A line gets its
category in this order:

1. the category chosen for it on the document page (Line tax categories);
2. the labor category, if the line came from a time entry;
3. the default category.

Labor is taxable only when **Labor taxable** is on in the settings. A manual
rate can override that for its own jurisdiction. Shipping follows **Shipping
taxable**. A non-taxable line is sent to providers with their non-taxable code
(Avalara `NT`, TaxJar `99999`). A line's own *taxable* checkbox always wins.

## Audit and reconciliation

Each calculation is stored as a `TaxCalculation`. It holds the provider, its
purpose (preview, finalize or override), its status, a hash of the request, a
fingerprint of the lines and address, the per-line and per-jurisdiction
breakdown, the total, whether it was committed and with which transaction code,
any error, any exemption, and who ran it. The newest one is the document's
current calculation. Recent calculations are listed on the settings page.

## For the accounting push

The QBO / Xero push does not send tax yet. When it starts to, it should call:

```python
from tax.accounting import tax_mapping_for_push
mapping = tax_mapping_for_push(invoice, 'quickbooks_online')   # or 'xero'
```

The call returns the following:

- `send_tax`: whether to send tax at all;
- `total_tax`: the total;
- `stale`: whether the lines changed since tax was calculated;
- for each line, the accounting `tax_code`, `taxable` and `tax`.

`tax.accounting.map_line_tax_code(category, provider, taxable)` maps a single
line.

## Sandbox verification

The adapters are tested against mocked HTTP only. Before going live, run a
preview and a send against each provider's sandbox with real sandbox
credentials ("Use the provider sandbox" in settings, then Test connection):

- Avalara: a sandbox account ID, license key and company code
  (`sandbox-rest.avatax.com`).
- TaxJar: a sandbox API token (`api.sandbox.taxjar.com`). Check that the
  refund sign convention (negative amounts) is accepted for credit memos.
