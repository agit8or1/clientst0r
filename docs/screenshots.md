# ClientSt0r — visual tour

Every image below is a capture of the running application against an isolated demo
database. All organizations, contacts, hostnames, addresses and credentials are invented;
no secret is ever rendered into a page, so nothing is masked after the fact.

Captured at 1440 × 900, light theme, against the current release.

[← Back to the README](../README.md)

---

## Walkthrough

[![Animated walkthrough: the client dashboard, the service desk queue, a ticket showing its contract, SLA countdown and masked vault context, the runbook behind it, the asset record, the vault, a project timeline and a profitability report](images/github/walkthrough.gif)](images/github/walkthrough.gif)

Twenty-eight seconds through a working day: client dashboard, the queue, a ticket with its
contract and credentials, the runbook behind it, the asset record, the vault, a project
plan, and what the month earned.

---

## Dashboard

[![Client dashboard: quick actions, record counts, a site map with two mapped locations, the next seven days of scheduled work, outstanding tasks and monitor status](images/github/dashboard.png)](images/github/dashboard.png)

The per-client dashboard. Quick actions adapt to which features are enabled — the ticket,
quote and invoice shortcuts appear only once the service desk is switched on. The schedule
panel merges upcoming tickets and scheduled maintenance; the task panel surfaces what is
falling due.

---

## Service desk

### Ticket queue

[![Service desk queue listing nine tickets across four client organizations, filtered by client, status, priority, queue and assignee](images/github/tickets.png)](images/github/tickets.png)

One queue across every client. Filter by client, status, priority, queue or technician, or
search by ticket number and subject. Status and priority sets are yours to define.

### Ticket with customer context

[![Ticket detail showing the client's active contract, SLA countdown, internal and client-visible activity, the linked asset, vault context with secrets masked, and logged billable time](images/github/ticket-detail.png)](images/github/ticket-detail.png)

The reason the documentation and the service desk live in one product. The ticket opens
with:

- the client's **active contract** and hours consumed against it,
- the **SLA countdown**, with pause logic for statuses that stop the clock,
- **activity** separated into client-visible replies and internal-only notes,
- the **linked asset**, documentation and KB article,
- **vault context** — the credentials this job needs, listed by title and username only.
  Secrets are never rendered here; opening one goes through the vault's own permissions and
  is audited,
- **time entries**, billable or not, ready to roll into an invoice.

---

## Client documentation

### Client overview

[![Client overview page for a logistics company showing company information, primary contact details and two mapped sites](images/github/client-overview.png)](images/github/client-overview.png)

Everything for one customer hangs off this page — contacts, addresses, sites, and the
shortcut buttons into that client's VoIP, email, Microsoft 365, web, firewall and procedure
documentation.

### Asset register

[![Asset list for one client showing six devices with type, manufacturer, model and serial number, plus filters for type, manufacturer, status and location](images/github/assets.png)](images/github/assets.png)

### Asset detail

[![Asset detail for a domain controller showing identity, network, operating system, hardware specification, physical rack position, lifecycle dates and tags](images/github/asset-detail.png)](images/github/asset-detail.png)

Identity, network, OS, hardware, rack position, lifecycle and warranty in one record —
with the client contact responsible for it and the tags that drive reporting.

### Knowledge base and runbooks

[![Document list showing per-client documentation and global knowledge base articles](images/github/docs.png)](images/github/docs.png)

[![A runbook article: when to use it, numbered steps, and an escalation note](images/github/kb-article.png)](images/github/kb-article.png)

Documents are either scoped to one client or global to the whole tenant. Runbooks,
network overviews and procedures live beside the assets and credentials they reference,
and link directly from tickets.

---

## Vault

[![Password vault listing nine credentials for one client with usernames and security status shown and every secret hidden](images/github/vault.png)](images/github/vault.png)

AES-GCM encrypted at rest. Entries are organized in folders per client, carry their own
access rules, and support approval and break-glass flows for the credentials that warrant
them. Reveals are audited.

---

## Service desk — the rest of the queue

### Dispatch board

[![Dispatch board showing a week of scheduled work by technician, with an SLA-at-risk banner and unassigned tickets ready to drag onto a tech row](images/github/dispatch.png)](images/github/dispatch.png)

Drag a ticket onto a technician's row to schedule it. The banner at the top calls out
anything about to breach.

### Scheduled maintenance

[![Scheduling page showing tasks needing sign-off and upcoming maintenance for the next seven days, with priority and status](images/github/scheduling.png)](images/github/scheduling.png)

Recurring maintenance with per-task sign-off, separate from the ticket queue.

### Website and certificate monitoring

[![Website monitor list showing two monitored endpoints with status, response time, SSL expiry date and last check time](images/github/monitors.png)](images/github/monitors.png)

---

## Quotes, invoices and contracts

### Quotes

[![Quote list showing three quotes across three clients with status, total and creation date](images/github/quotes.png)](images/github/quotes.png)

[![Quote detail with line items, subtotal, tax and total, plus buttons to view the PDF, email it, copy a customer signing URL, or accept it and spin up a ticket or project](images/github/quote-detail.png)](images/github/quote-detail.png)

Accepting a quote can open a ticket, or spin up a project with one task per line item.
Customers can sign it from a tokenised URL without an account.

### Invoices

[![Invoice list showing three invoices with sent, paid and overdue status, totals and balances](images/github/invoices.png)](images/github/invoices.png)

[![Invoice detail with line items tagged by origin — contract period, time entry and expense — a payment recording form, and a push-to-accounting action](images/github/invoice-detail.png)](images/github/invoice-detail.png)

Every line carries its origin — a contract period, a logged time entry, or an expense —
so an invoice query can be answered without reconstructing it by hand.

### Contracts

[![Contract list showing three agreements with type, status, hours used against allowance and period](images/github/contracts.png)](images/github/contracts.png)

[![Contract detail showing hours consumed, the rollover policy, auto-renewal state and a profitability snapshot with revenue, cost, margin and margin percentage](images/github/contract-detail.png)](images/github/contract-detail.png)

Block hours with rollover rules, managed agreements, auto-renewal, and a profitability
snapshot for the current period.

---

## Projects

[![Project detail showing client, owner, dates, a ready-to-bill panel, profitability, budget consumption, and a task list with milestones, assignees and status](images/github/project-detail.png)](images/github/project-detail.png)

[![Project timeline: a Gantt chart of seven tasks with milestones marked, above a dependency table showing which tasks are blocked and what they wait for](images/github/project-timeline.png)](images/github/project-timeline.png)

Tasks, milestones and dependencies, with the schedule draggable and blocked work flagged.
Billing rolls up from the plan.

---

## Reporting

### Profitability by client

[![Profitability by client report showing revenue, cost, margin and blended margin percentage for the period, with a per-client breakdown](images/github/report-profitability.png)](images/github/report-profitability.png)

Revenue against cost of delivery, drawn from logged time and issued invoices — not
typed in.

### Client health

[![Client health score report ranking five clients by a composite score built from SLA performance, ticket velocity, billing aging, engagement and an NPS proxy](images/github/report-client-health.png)](images/github/report-client-health.png)

### Effective hourly rate

[![Effective hourly rate report showing average, highest, lowest and median rates, with billable and non-billable hours and utilisation per client](images/github/report-hourly-rate.png)](images/github/report-hourly-rate.png)

What an hour actually earned once non-billable time is counted.

---

## Across every client

[![Global dashboard showing counts across all organizations — five clients, assets, documents, passwords, monitors — with a thirty-day health summary and a map of every client site across the United States](images/github/global-dashboard.png)](images/github/global-dashboard.png)

The MSP-wide view: totals across every tenant and a map of every client site.

---

## Older captures

The screenshot set from earlier releases — PSA quotes, invoices, dispatch board, workflow
rules, contracts, compliance frameworks, security alert ingestion, integration setup forms,
monitoring, racks, IPAM, wallboards, fleet inventory and more — is kept at
[`docs/screenshots/`](screenshots/README.md). Those images have not been recaptured for the
current release and may show older styling.
