# ClientSt0r — screenshot gallery

28 views of the running application — 15 in the light theme, 13 in dark. Every one is a capture of ClientSt0r against an isolated demo database; no mockups, no composites.

All organizations, people, hostnames, addresses and credentials below are invented. Domains use the reserved `.example` TLD and addresses are RFC 1918. Nothing is masked after the fact because nothing needed masking — the application never renders a secret into a list, a ticket or a report.

> Regenerate this set with `scripts/capture_screenshots.py`. See [scripts/demo/README.md](../scripts/demo/README.md) for how the demo instance is built and why it cannot reach production data.

[← Back to the README](../README.md)

## Contents

- [Overview and dashboards](#overview-and-dashboards) — 3 views
- [Visual insights and monitoring](#visual-insights-and-monitoring) — 9 views
- [Everyday workflows](#everyday-workflows) — 11 views
- [Management and configuration](#management-and-configuration) — 3 views
- [Access and administration](#access-and-administration) — 2 views

---

## Overview and dashboards

Where a technician starts the day, and where an owner looks at the whole book of business.

### Client dashboard

**Light theme**

[![Client dashboard in light theme with quick actions, record counts, a seven-day schedule, outstanding tasks, monitor status and a site map](images/github/client-dashboard-light.png)](images/github/client-dashboard-light.png)

Open a client and see the week ahead: scheduled tickets, maintenance falling due, monitor status, and where their sites are.

### Every client at once

**Dark theme**

[![Cross-tenant dashboard in dark theme showing counts for organizations, users, assets, documents and monitors, a thirty-day health summary, and a map of client sites across the United States](images/github/global-dashboard-dark.png)](images/github/global-dashboard-dark.png)

The MSP-wide view: totals across all tenants, thirty-day health, and a map of every client site.

### Customer overview

**Light theme**

[![Customer overview page in light theme showing company information, primary contact details and two mapped sites](images/github/client-overview-light.png)](images/github/client-overview-light.png)

Everything about one customer in one place — contacts, sites, and shortcuts into their documentation.

---

## Visual insights and monitoring

The views that answer a question at a glance — schedules, elevations, address space, margins.

### Project timeline

**Light theme**

[![Project timeline in light theme: a Gantt chart of seven tasks with milestones marked, above a dependency table showing blocked tasks and what each waits for](images/github/project-timeline-light.png)](images/github/project-timeline-light.png)

Drag a bar to reschedule. Dependencies show what is blocked and what it is waiting for.

### Dispatch board

**Dark theme**

[![Dispatch board in dark theme showing a week of scheduled work by technician with an SLA-at-risk banner and unassigned tickets](images/github/dispatch-board-dark.png)](images/github/dispatch-board-dark.png)

A week of work per technician. Drag a ticket onto a row to schedule it; the banner flags anything close to breaching.

### Profitability by client

**Light theme**

[![Profitability by client report in light theme showing revenue, cost, margin and blended margin percentage with a per-client breakdown](images/github/report-profitability-light.png)](images/github/report-profitability-light.png)

Revenue against cost of delivery for the period, drawn from logged time and issued invoices — not typed in.

### Client health score

**Dark theme**

[![Client health score report in dark theme ranking five clients by a composite score built from SLA, velocity, aging, engagement and an NPS proxy](images/github/report-client-health-dark.png)](images/github/report-client-health-dark.png)

A composite of SLA performance, ticket velocity, billing aging and engagement — so at-risk accounts surface before they churn.

### Effective hourly rate

**Light theme**

[![Effective hourly rate report in light theme showing average, highest, lowest and median rates with billable hours and utilisation per client](images/github/report-hourly-rate-light.png)](images/github/report-hourly-rate-light.png)

What an hour actually earned once non-billable time is counted, per client and per technician.

### Rack elevation

**Dark theme**

[![Rack elevation view in dark theme showing a 42U rack populated with a firewall, core switch, patch panel, servers, NAS and UPS at their unit positions](images/github/rack-elevation-dark.png)](images/github/rack-elevation-dark.png)

What is in the comms room, at which U, drawing how much power — linked to the asset record for each device.

### IP address management

**Light theme**

[![IP address management in light theme listing four subnets with network, VLAN, gateway and location for one client](images/github/ipam-subnets-light.png)](images/github/ipam-subnets-light.png)

Subnets per client with their VLAN, gateway and DNS, and which addresses are allocated, reserved or free.

### Recurring maintenance

**Dark theme**

[![Scheduling page in dark theme showing tasks needing sign-off and upcoming maintenance for the next seven days with priority and status](images/github/scheduling-dark.png)](images/github/scheduling-dark.png)

Maintenance that recurs on its own schedule, with per-task sign-off, kept separate from the ticket queue.

### Uptime and certificate expiry

**Light theme**

[![Website monitor list in light theme showing monitored endpoints with status, response time, SSL expiry date and last check time](images/github/monitors-light.png)](images/github/monitors-light.png)

Endpoint checks with response time, and the certificate expiry date you would otherwise find out about at 2am.

---

## Everyday workflows

Ticket to resolution, quote to invoice, and the documentation that hangs off both.

### Service desk queue

**Dark theme**

[![Service desk queue in dark theme listing twelve tickets across four clients with subject, client, priority, status, queue, assignee and age](images/github/ticket-queue-dark.png)](images/github/ticket-queue-dark.png)

Every client in one queue. Filter by status, priority, queue or technician; the subject is what you scan, not the badges.

### A ticket that knows the customer

**Light theme**

[![Ticket detail in light theme showing the client's active contract, SLA countdown, internal and client-visible activity, the linked asset, vault context with secrets hidden, and logged time](images/github/ticket-detail-light.png)](images/github/ticket-detail-light.png)

Contract and hours used, the SLA countdown, internal notes kept apart from client replies, the linked asset, and the credentials this job needs — listed, never revealed.

### Client documentation

**Dark theme**

[![Document list in dark theme showing per-client documentation with category, tags and last-updated date](images/github/documents-dark.png)](images/github/documents-dark.png)

Per-client documents and global knowledge base articles, searchable by title and body.

### Runbooks beside the work

**Light theme**

[![Knowledge base runbook in light theme with when-to-use guidance, numbered steps and an escalation note](images/github/kb-runbook-light.png)](images/github/kb-runbook-light.png)

A procedure written for the technician who will actually run it — and linked from the tickets that need it.

### Asset register

**Dark theme**

[![Asset list in dark theme showing devices with name, type, manufacturer, model and serial number, with filters above](images/github/assets-dark.png)](images/github/assets-dark.png)

Every device you look after for a client, filterable by type, manufacturer, status and location.

### Asset detail

**Light theme**

[![Asset detail in light theme for a domain controller showing identity, network, operating system, hardware specification, physical position, lifecycle dates and tags](images/github/asset-detail-light.png)](images/github/asset-detail-light.png)

Identity, network, operating system, hardware, rack position, warranty and lifecycle on one record.

### Credential vault

**Dark theme**

[![Password vault in dark theme listing nine credentials for one client with title, username and security status, every secret hidden](images/github/vault-dark.png)](images/github/vault-dark.png)

AES-GCM encrypted at rest, organised per client. Secrets are never rendered into a list — opening one is a permissioned, audited act.

### Quote to signature

**Light theme**

[![Quote detail in light theme with line items, subtotal, tax and total, plus actions to view the PDF, email it, copy a signing URL or accept it](images/github/quote-detail-light.png)](images/github/quote-detail-light.png)

Line items, tax and total, a PDF, and a signing link the customer can use without an account. Accepting it can open a ticket or spin up a project.

### Invoices that explain themselves

**Dark theme**

[![Invoice detail in dark theme with line items tagged by origin, a payment recording form and a push-to-accounting action](images/github/invoice-detail-dark.png)](images/github/invoice-detail-dark.png)

Every line carries its origin — a contract period, a logged time entry, an expense — so a billing query is answerable without reconstructing it.

### Agreements and hours

**Light theme**

[![Contract detail in light theme showing hours consumed, rollover policy, auto-renewal state and a profitability snapshot](images/github/contract-detail-light.png)](images/github/contract-detail-light.png)

Block hours with rollover rules, auto-renewal, and a profitability snapshot for the current period.

### Project delivery

**Dark theme**

[![Project detail in dark theme showing client, owner, dates, a ready-to-bill panel, profitability, budget consumption and a task list with milestones](images/github/project-detail-dark.png)](images/github/project-detail-dark.png)

Tasks, milestones and assignees with budget consumption and profitability rolled up from the work already logged.

---

## Management and configuration

The commercial side: what is quoted, what is billed, and what each client is entitled to.

### Quote pipeline

**Light theme**

[![Quote list in light theme showing three quotes across three clients with status, total and creation date](images/github/quotes-list-light.png)](images/github/quotes-list-light.png)

Draft, sent and accepted quotes across every client, with totals and a one-click PDF.

### Billing at a glance

**Dark theme**

[![Invoice list in dark theme showing three invoices with sent, paid and overdue status, totals, balances and accounting push state](images/github/invoices-list-dark.png)](images/github/invoices-list-dark.png)

Sent, paid and overdue invoices with balances, and whether each has been pushed to your accounting system.

### Agreements per client

**Light theme**

[![Contract list in light theme showing three agreements with type, status, hours used against allowance and period](images/github/contracts-list-light.png)](images/github/contracts-list-light.png)

Which clients are on managed agreements, which are on block hours, and how much of the allowance is gone.

---

## Access and administration

Tenancy, membership and the switches that decide which modules exist.

### Tenants and access

**Dark theme**

[![Organization list in dark theme showing client tenants with member counts, asset counts and status](images/github/organizations-dark.png)](images/github/organizations-dark.png)

Every client is its own tenant. Membership decides who sees what; switching client context is one click.

### Feature toggles

**Light theme**

[![Feature toggle settings in light theme showing switches for optional modules including the native PSA service desk](images/github/feature-toggles-light.png)](images/github/feature-toggles-light.png)

The service desk, AI assistance and other modules are opt-in — off until an administrator turns them on.

---

## About these captures

- Viewport 1440 px wide at device pixel ratio 2, so text stays sharp when you open an image full size.
- Themes are switched through the application's own theme control, not by injecting CSS — what you see is the shipped theme.
- Each image is cropped to where the page's content ends, so none of them carry a slab of empty background.
- Route, theme, viewport and the demo data each view needs are recorded in [`scripts/screenshot_manifest.json`](../scripts/screenshot_manifest.json).

Older captures from previous releases are kept in [`docs/screenshots/`](screenshots/README.md).

---

[← Back to the README](../README.md) · [MSP Reboot](https://mspreboot.com) — the MSP consulting practice behind ClientSt0r
