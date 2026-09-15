# ClientSt0r — visual tour

Every image below is a capture of the running application against an isolated demo
database. All organizations, contacts, hostnames, addresses and credentials are invented;
no secret is ever rendered into a page, so nothing is masked after the fact.

Captured at 1440 × 900, light theme, against the current release.

[← Back to the README](../README.md)

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

## Older captures

The screenshot set from earlier releases — PSA quotes, invoices, dispatch board, workflow
rules, contracts, compliance frameworks, security alert ingestion, integration setup forms,
monitoring, racks, IPAM, wallboards, fleet inventory and more — is kept at
[`docs/screenshots/`](screenshots/README.md). Those images have not been recaptured for the
current release and may show older styling.
