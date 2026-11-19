# ClientSt0r — screenshot gallery

107 views of the running application — 55 in the light theme (Default Blue), 52 in Professional Dark, the default theme. Every one is a capture of ClientSt0r against an isolated demo database; no mockups, no composites.

All organizations, people, hostnames, addresses and credentials below are invented. Domains use the reserved `.example` TLD and addresses are RFC 1918. Nothing is masked after the fact because nothing needed masking — the application never renders a secret into a list, a ticket or a report.

> Regenerate this set with `scripts/demo/recapture.sh` (it serves the demo, runs `scripts/capture_screenshots.py` and rebuilds this page). See [scripts/demo/README.md](../scripts/demo/README.md) for how the demo instance is built and why it cannot reach production data.

[← Back to the README](../README.md)

## Contents

- [Finding your way](#finding-your-way) — 7 views
- [Overview and dashboards](#overview-and-dashboards) — 8 views
- [Visual insights and monitoring](#visual-insights-and-monitoring) — 19 views
- [Hardware and cabling](#hardware-and-cabling) — 16 views
- [Everyday workflows](#everyday-workflows) — 21 views
- [Tickets and the paired RMM](#tickets-and-the-paired-rmm) — 6 views
- [Management and configuration](#management-and-configuration) — 5 views
- [Access and administration](#access-and-administration) — 6 views
- [Operations and monitoring](#operations-and-monitoring) — 4 views
- [Business operations](#business-operations) — 5 views
- [Security and client data protection](#security-and-client-data-protection) — 10 views

---

## Finding your way

The ten-section sidebar and its icon rail, Go to (Ctrl+K), Favorites and Recent, and the same frame on a phone.

### Ten-section sidebar

**Professional Dark theme**

[![Ticket list in the Professional Dark theme with the navy sidebar expanded: a Jump to filter, the Dashboard, My Work and Service Desk sections with Service Desk open on Tickets, Dispatch Board, Shifts and Locations, Scheduling, Projects, Service Management and Workflows, the remaining sections collapsed and Administration at the foot](images/github/nav-sidebar-dark.png)](images/github/nav-sidebar-dark.png)

Nine work sections — Dashboard, My Work, Service Desk, Clients, Assets & Network, Business, Knowledge & Vault, Security & Monitoring and Reports — with Administration pinned at the foot. Only the current section starts open; its pages carry their own tabs and a Configure menu, and the breadcrumb reads Section › Workspace › Page. The filter at the top also finds tabs, Configure pages and settings.

### Icon rail and flyouts

**Light theme**

[![Asset list in light theme with the sidebar collapsed to a 64-pixel icon rail and the Knowledge and Vault flyout open beside it, listing Documentation, Knowledge Base, Diagrams, Review and Publishing, Documentation Readiness, Password Vault, My Vault and Secure Notes](images/github/nav-rail-flyout-light.png)](images/github/nav-rail-flyout-light.png)

The sidebar collapses to an icon rail (the default on tablets, remembered once you choose). A section's icon opens its pages as a flyout — by click, Enter or Space, with arrow keys inside and Escape to close.

### Go to (Ctrl+K)

**Professional Dark theme**

[![Command palette open over the dashboard in the Professional Dark theme with the query north: grouped results for the Northwind Logistics client, its tickets, devices and documents, with keyboard hints for moving, opening and closing](images/github/command-palette-dark.png)](images/github/command-palette-dark.png)

Ctrl+K or Cmd+K (or the Go to button) opens one box for pages, settings and quick commands, and for clients, tickets, devices, projects, documents, KB articles and reports — each searched with that list page's own permission rules. Passwords are never searched.

### Favorites

**Light theme**

[![Ticket list in light theme with the top bar Favorites menu open: an Add this page button and five starred pages including the dispatch board, the client health report, a switch and the Northwind Logistics client, with a Manage favorites link](images/github/favorites-menu-light.png)](images/github/favorites-menu-light.png)

Star any page from the top bar and it is one click away. A favorite disappears by itself when you lose access, the record is deleted or its module is switched off.

### Phone layout

**Professional Dark theme**

[![Dashboard at 390 pixels wide in the Professional Dark theme: a one-row top bar with the menu button, the dashboard header with its quick actions and the KPI tiles two to a row](images/github/phone-dashboard-dark.png)](images/github/phone-dashboard-dark.png)

At phone width the top bar stays on one row with a menu button, KPI tiles wrap two to a row and panels take phone-sized heights.

### Navigation drawer on a phone

**Professional Dark theme**

[![The navigation drawer open at 390 pixels wide over a dimmed dashboard: the Jump to filter, a close button and the ten sections with Dashboard open](images/github/phone-drawer-dark.png)](images/github/phone-drawer-dark.png)

Below 768 pixels the sidebar becomes a drawer opened from the menu button, with the same sections, filter and Administration link; focus stays inside it until it closes.

### Recently opened

**Professional Dark theme**

[![Dashboard in the Professional Dark theme with the top bar Recent menu open, listing recently opened pages and records such as tickets, an asset, a runbook and the vault](images/github/recent-menu-dark.png)](images/github/recent-menu-dark.png)

The pages and records you opened last, newest first, checked against your access each time the menu opens.

---

## Overview and dashboards

Where a technician starts the day, and where an owner looks at the whole book of business.

### Dashboard

**Light theme**

[![Dashboard in light theme with Northwind Logistics selected: the navy ten-section sidebar, the top bar with Go to, Favorites, Recent and the client switcher, a header with New Ticket, Log Time, Add Client, Create Project and Dispatch Board, seven KPI tiles, My ticket queue with three tickets and their SLA due times, an SLA overview at 67 percent, technician workload, upcoming tasks and system status](images/github/client-dashboard-light.png)](images/github/client-dashboard-light.png)

The dashboard for the client you have selected: quick actions in the header, a KPI row of what needs you (open tickets, SLA at risk, overdue, unassigned, pending approvals, due today, RMM alerts), then your ticket queue, the SLA overview, technician workload, upcoming tasks and system status. The layout follows your role.

### Client dashboard (dark)

**Professional Dark theme**

[![Dashboard in dark theme for Northwind Logistics with KPI tiles, the technician's ticket queue, SLA overview, technician workload, upcoming tasks and system status](images/github/client-dashboard-dark.png)](images/github/client-dashboard-dark.png)

The technician home in the Professional Dark theme: queue, SLA overview, workload, upcoming tasks and system status for the selected customer.

### My Work

**Light theme**

[![My Work page in light theme: a running timer, eleven open tickets sorted by SLA due time, upcoming appointments, and pending approvals for an expense, three timesheets, change votes and invoices on hold](images/github/my-work-light.png)](images/github/my-work-light.png)

Everything waiting on one technician: a running timer with a stop button, open tickets in SLA order, tickets where the customer has replied, the waiting-on-us and waiting-on-customer queues, pending approvals and the week's appointments. Each count matches the list its link opens.

### Every client at once

**Professional Dark theme**

[![Cross-tenant dashboard in the Professional Dark theme with a Quick Actions row and a Customize button, counts for organizations, users, assets, documents and monitors, a thirty-day health summary, and a map of client sites across the United States](images/github/global-dashboard-dark.png)](images/github/global-dashboard-dark.png)

The MSP-wide view: totals across all tenants, thirty-day health, and a map of every client site.

### Client workspace

**Light theme**

[![Northwind Logistics client workspace in light theme on the Overview tab: the client header with Operations, Evidence pack and Edit, a current-client banner, quick actions, the tab bar, a KPI row for open tickets, SLA at risk, managed assets, RMM offline, active contracts, open invoices and active projects, then company information, contact and address, contacts, and the client's open tickets, devices and contracts](images/github/client-overview-light.png)](images/github/client-overview-light.png)

Open a client and it becomes your current client and a workspace: quick actions (create a ticket, add a contact, asset or document, open the RMM, create a project or quote), a KPI row, tabs for Overview, Tickets, Assets, RMM, Contacts, Documents, Passwords (names only), Contracts, Billing, Projects and more, and links back to all clients and the MSP-wide view.

### Dashboard: administrator layout

**Professional Dark theme**

[![Dashboard in the Professional Dark theme for an administrator with Ridgeline Dental Group selected: New Ticket, Log Time, Add Client, Create Project and Dispatch Board, seven KPI tiles, a My ticket queue panel, an SLA overview, technician workload bars, upcoming tasks and a system status panel](images/github/dashboard-admin-dark.png)](images/github/dashboard-admin-dark.png)

An administrator's default layout: New Ticket, Log Time, Add Client, Create Project and Dispatch Board in the header, a KPI row (my open tickets, SLA at risk, overdue, unassigned, pending approvals, due today, RMM alerts), then the ticket queue, SLA overview, technician workload, tasks and system status. Every widget checks its own permission on the server.

### Dashboard: technician layout

**Light theme**

[![Dashboard in light theme for technician Priya Patel with Harbor Point Credit Union selected: KPI tiles for my open tickets, SLA at risk, overdue, due today, unassigned and my open tasks, then My ticket queue, SLA overview, upcoming tasks, RMM alerts and recently updated tickets](images/github/dashboard-technician-light.png)](images/github/dashboard-technician-light.png)

A technician's default layout follows the role: their own queue and SLA warnings first, then tasks, RMM alerts and recently updated tickets. Anyone can rearrange, resize or hide panels; administrators can save a role's default.

### Client workspace: Tickets tab

**Professional Dark theme**

[![Northwind Logistics client workspace in the Professional Dark theme on the Tickets tab: the client header with quick actions, a KPI row, the tab bar from Overview to Members and the client's tickets with status, priority, assignee and age](images/github/client-workspace-tickets-dark.png)](images/github/client-workspace-tickets-dark.png)

Each tab of the client workspace is the client's slice of a list you already know — here its tickets — with the KPI row and quick actions kept above it. Tabs appear only for what you may open; Passwords lists names only.

---

## Visual insights and monitoring

The views that answer a question at a glance — schedules, elevations, address space, margins.

### Project timeline

**Light theme**

[![Project timeline in light theme: a Gantt chart of seven tasks with milestones marked, above a dependency table showing blocked tasks and what each waits for](images/github/project-timeline-light.png)](images/github/project-timeline-light.png)

Drag a bar to reschedule. Dependencies show what is blocked and what it is waiting for.

### Dispatch board

**Professional Dark theme**

[![Dispatch board in the Professional Dark theme showing a week of scheduled work by technician with an SLA-at-risk banner and unassigned tickets](images/github/dispatch-board-dark.png)](images/github/dispatch-board-dark.png)

A week of work per technician. Drag a ticket onto a row to schedule it; the banner flags anything close to breaching.

### Profitability by client

**Light theme**

[![Profitability by client report in light theme showing revenue, cost, margin and blended margin percentage with a per-client breakdown](images/github/report-profitability-light.png)](images/github/report-profitability-light.png)

Revenue against cost of delivery for the period, drawn from logged time and issued invoices — not typed in.

### Client health score

**Professional Dark theme**

[![Client health score report in the Professional Dark theme ranking five clients by a composite score built from SLA, velocity, aging, engagement and an NPS proxy](images/github/report-client-health-dark.png)](images/github/report-client-health-dark.png)

A composite of SLA performance, ticket velocity, billing aging and engagement — so at-risk accounts surface before they churn.

### Effective hourly rate

**Light theme**

[![Effective hourly rate report in light theme showing average, highest, lowest and median rates with billable hours and utilisation per client](images/github/report-hourly-rate-light.png)](images/github/report-hourly-rate-light.png)

What an hour actually earned once non-billable time is counted, per client and per technician.

### Rack elevation

**Professional Dark theme**

[![Rack elevation in the Professional Dark theme drawn from catalog artwork: a FortiGate firewall at U40, an HPE Aruba 6300M core switch at U37, a 2U Panduit patch panel, a legacy KVM console placement with no model shown as a plain face with its saved name, Dell PowerEdge R650 and 2U R750xs servers and a 2U Synology NAS, each named beside the rack with its model and units](images/github/rack-elevation-dark.png)](images/github/rack-elevation-dark.png)

Each device is drawn from the same catalog artwork as its device page, across its real unit span — a 2U server reads as one 2U chassis. Front and rear faces, half-depth rules, and a plain face where no artwork is recorded.

### IP address management

**Light theme**

[![IP address management in light theme listing four subnets with network, VLAN, gateway and location for one client](images/github/ipam-subnets-light.png)](images/github/ipam-subnets-light.png)

Subnets per client with their VLAN, gateway and DNS, and which addresses are allocated, reserved or free.

### Recurring maintenance

**Professional Dark theme**

[![Scheduling page in the Professional Dark theme showing tasks needing sign-off and upcoming maintenance for the next seven days with priority and status](images/github/scheduling-dark.png)](images/github/scheduling-dark.png)

Maintenance that recurs on its own schedule, with per-task sign-off, kept separate from the ticket queue.

### Uptime and certificate expiry

**Light theme**

[![Website monitor list in light theme showing monitored endpoints with status, response time, SSL expiry date and last check time](images/github/monitors-light.png)](images/github/monitors-light.png)

Endpoint checks with response time, and the certificate expiry date you would otherwise find out about at 2am.

### Compliance frameworks per client

**Professional Dark theme**

[![Compliance overview in the Professional Dark theme showing PCI-DSS and HIPAA framework cards for one client with progress bars, status counts and a recertification countdown](images/github/compliance-overview-dark.png)](images/github/compliance-overview-dark.png)

Which frameworks a client is enrolled in, how far through the attestation they are, and when recertification is next due.

### Attestation checklist

**Light theme**

[![PCI-DSS attestation checklist in light theme with per-control status dropdowns, notes, evidence links and last-reviewed stamps, colour-coded by compliance state](images/github/compliance-checklist-light.png)](images/github/compliance-checklist-light.png)

Per-control status, notes and an evidence link, with who last reviewed it and when — the record you hand an auditor.

### Documentation readiness

**Light theme**

[![Documentation readiness overview in light theme listing customers with readiness scores and unmet requirement counts](images/github/readiness-overview-light.png)](images/github/readiness-overview-light.png)

Each customer scored against the documentation standards in force, worst first, with a count of unmet requirements.

### Readiness for one customer

**Professional Dark theme**

[![Readiness page for one customer in the Professional Dark theme showing a Microsoft 365 documentation standard with met and unmet requirements and fix buttons](images/github/readiness-customer-dark.png)](images/github/readiness-customer-dark.png)

Every requirement in a standard, met or unmet, with a plain explanation of what is missing, why it matters, the records that satisfy it and a link to fix it.

### Readiness repair queue

**Light theme**

[![Readiness repair queue in light theme listing unmet requirements per customer with what is missing, the owner and a fix action](images/github/readiness-repair-light.png)](images/github/readiness-repair-light.png)

Everything unmet across customers in one list, filterable by customer, standard and owner. Excepted items are left out.

### KB analytics

**Light theme**

[![KB analytics page in light theme with most viewed, past review date and never viewed tables and a list of top zero-result searches](images/github/kb-analytics-light.png)](images/github/kb-analytics-light.png)

Most viewed and never viewed articles, articles past their review date with their owner, and searches that found nothing. Only zero-result searches are kept, for 90 days, and vault searches are never recorded.

### Custom asset fields as requirements

**Professional Dark theme**

[![Network baseline standard for Northwind Logistics in the Professional Dark theme scoring 81.8 percent: four met requirements, and an unmet one, Servers have a support contract and backup policy, listing NWL-FS01 and NWL-NAS01 as missing Vendor support contract and Backup policy, with a Fill in the asset button](images/github/readiness-custom-fields-dark.png)](images/github/readiness-custom-fields-dark.png)

A requirement can name your own custom asset fields. Here every server must record its vendor support contract and backup policy; the servers missing them are listed and the fix opens the asset's Custom Fields section.

### A readiness fix opens a filled-in form

**Light theme**

[![Create Document form in light theme opened from a readiness fix link, with a banner reading This will be saved in Northwind Logistics and the title already filled in](images/github/readiness-prefill-light.png)](images/github/readiness-prefill-light.png)

A readiness "Create it" link switches to the customer the gap belongs to and opens the form with what the requirement asks for already filled in. The form says which customer it saves in; nothing is saved until you click Save.

### Customer status page

**Light theme**

[![Status page editor in light theme for Northwind Logistics with a warning that the page is live and public, its link with a Rotate link control, two published services marked operational, and an ongoing VPN incident and a resolved website incident with update boxes](images/github/status-page-light.png)](images/github/status-page-light.png)

A public status page per customer: only the services listed here appear, under a public name, and incidents are written for that audience rather than copied from tickets.

### Technician roster

**Light theme**

[![Tech Roster in light theme listing four technicians with on-shift or off-shift badges, skill and certification counts, and one expiring and one expired certification flagged](images/github/tech-roster-light.png)](images/github/tech-roster-light.png)

Who is on shift now, with each technician's skills and certifications, and which certifications are expiring or have expired.

---

## Hardware and cabling

Each client's physical network as panel artwork, cables, racks, diagrams and labels.

### A switch and its ports

**Light theme**

[![Device page in light theme for a 48-port Dell PowerConnect 3448P switch: front and rear panel artwork with ports coloured by VLAN, a verified-front and approximate-rear badge, a VLAN legend and the port table below](images/github/hardware-device-light.png)](images/github/hardware-device-light.png)

A Dell PowerConnect 3448P drawn from its catalog layout, front and rear, with the VLAN overlay on. Click a port to document it; badges say which face was checked against the manufacturer's documentation and which is approximate.

### Port editor

**Professional Dark theme**

[![Switch page in the Professional Dark theme with the port editor open for port 1/e12: description, mode access, VLAN 10 Staff with voice VLAN 20, PoE auto, and cable C-0012 to PP-01 Port 12, with the port highlighted on the panel artwork](images/github/hardware-port-editor-dark.png)](images/github/hardware-port-editor-dark.png)

Click a port on the artwork to edit it: description, technician label, admin state, speed, mode, native, tagged and voice VLANs, LAG and PoE. The cable and its far end are shown in the same panel. Operational state stays "Not observed" because nothing here polls the switch.

### Full cable trace

**Light theme**

[![Cable trace in light theme from switch port 12 through a patch panel, a 34.5 m permanent link and wall jack Office 104 A to workstation XYZ-WS-104, marked complete documented path](images/github/hardware-trace-light.png)](images/github/hardware-trace-light.png)

From one switch port to the workstation it serves: patch cable, panel front and rear, the permanent link in the wall, the jack and the last patch cable, with each cable's ID, type, colour and length.

### Patch panel, front and rear

**Professional Dark theme**

[![Patch panel PP-01 in the Professional Dark theme with front and rear artwork, the connected overlay marking ports 12 and 24 cabled on both faces and port 13 cabled only at the rear](images/github/hardware-panel-device-dark.png)](images/github/hardware-panel-device-dark.png)

A 48-port panel with the connected overlay on. Port 12 and port 24 are cabled at the front and rear, while port 13 has only its permanent link at the rear. The overlay shows documented cables, not link state.

### Front-to-rear port mapping

**Light theme**

[![Patch panel mapping in light theme for PP-01: port 12 from switch port 12 through C-0012 and L-104A to XYZ-WS-104 (complete), port 13 through L-105A to Office 105 jack A (incomplete), port 24 to XYZ-AP-01 (complete)](images/github/hardware-panel-mapping-light.png)](images/github/hardware-panel-mapping-light.png)

Each panel port as one row: what is patched into the front, which rear termination it maps to, the permanent link, and the device at the far end. A path that stops short is marked incomplete. "In use only" hides the empty ports.

### Cable register

**Professional Dark theme**

[![Cable list in the Professional Dark theme with nine cables: patch cables, permanent links and work-area cables with both ends, type, colour, length and installed status](images/github/hardware-cables-dark.png)](images/github/hardware-cables-dark.png)

Every documented cable with both ends, type, colour, length and status. Select several to print their labels in one go.

### A server with a module

**Professional Dark theme**

[![Device page in the Professional Dark theme for a Dell PowerEdge R640 with rear artwork showing an installed two-port SFP NIC, approximate-layout badges and a port table including the module ports](images/github/hardware-server-dark.png)](images/github/hardware-server-dark.png)

A Dell PowerEdge R640 from the community library, with a two-port 10 GbE NIC installed in a PCIe bay. The module's ports join the device's port list and can be cabled like any other.

### Access point, top and bottom

**Light theme**

[![Access point page in light theme for a Ubiquiti U6 Pro with top and bottom artwork, the RJ45 uplink cabled on the bottom face, and the port row showing trunk VLANs 99 native, 10 and 30 tagged](images/github/hardware-ap-light.png)](images/github/hardware-ap-light.png)

A ceiling access point drawn from above and below. The uplink port is on the bottom face and is documented as a trunk with native VLAN 99 and tagged 10 and 30.

### Artwork on the asset record

**Light theme**

[![Asset detail page in light theme for XYZ-SW-01 with an illustration card showing the switch front and rear panels, accuracy badges and a ports and cabling button](images/github/hardware-asset-artwork-light.png)](images/github/hardware-asset-artwork-light.png)

The asset page shows the same generated front and rear artwork, with its accuracy badges and a link to the ports and cabling.

### Rack from catalog artwork

**Professional Dark theme**

[![Rack elevation in the Professional Dark theme with a patch panel, switch and firewall shown on the front and rear faces, the half-depth firewall outlined on the rear, and SVG, PNG and PDF export links](images/github/hardware-rack-dark.png)](images/github/hardware-rack-dark.png)

Front and rear of a rack, drawn from each model's artwork at its U position. A half-depth device mounted at the front is outlined on the rear. Each face exports to SVG, PNG or PDF.

### Connectivity diagram

**Professional Dark theme**

[![Physical connectivity diagram in the Professional Dark theme: firewall, switch, patch panel, server, wall jacks, access point and workstation joined by labelled cables, two nodes flagged with undocumented continuations](images/github/hardware-connectivity-dark.png)](images/github/hardware-connectivity-dark.png)

Drawn only from documented cables. Edges are labelled with the ports at each end, and a device whose path continues without a documented cable is outlined in red. Drag to arrange, save the layout, export it.

### VLAN diagram

**Light theme**

[![VLAN diagram in light theme linking VLANs 10 Staff, 20 Voice, 30 Guest and 99 Management to a firewall, switch, access point and workstation, with untagged, tagged and voice port counts](images/github/hardware-vlan-light.png)](images/github/hardware-vlan-light.png)

Which devices carry which VLANs, from the port configuration: solid lines for native or untagged, dashed for tagged or voice, with untagged/tagged/voice port counts on each line.

### Hardware catalog

**Light theme**

[![Hardware catalog in light theme showing 16,526 models as cards with panel thumbnails, inferred categories and approximate-layout badges, with manufacturer, kind, category and accuracy filters](images/github/hardware-catalog-light.png)](images/github/hardware-catalog-light.png)

About 16,500 device, module and rack models imported from the community device-type library at a pinned revision, each with generated artwork. Filter by manufacturer, kind, category or layout accuracy.

### A catalog model and its sources

**Professional Dark theme**

[![Catalog model page in the Professional Dark theme for the Dell PowerConnect 3448P with front and rear artwork, a component table and a source and provenance panel quoting the manufacturer's guide](images/github/hardware-model-dark.png)](images/github/hardware-model-dark.png)

Every model shows its artwork, its components and where they came from. This switch was entered from Dell's user guide: the page cites the pages used and says what the guide does not state.

### Layout editor

**Professional Dark theme**

[![Layout editor in the Professional Dark theme for the PowerConnect 3448P front face, 48 ports in blocks of six, with arrange, numbering and label-position controls and a source document field](images/github/hardware-layout-editor-dark.png)](images/github/hardware-layout-editor-dark.png)

Place, number and arrange a model's components in millimetres and save a new layout version. A face can only be marked verified with the document it was checked against.

### Labels

**Light theme**

[![Label page in light theme with label kind, a 38 × 19 mm cable-flag template, a list of cables to label and a print calibration link](images/github/hardware-labels-light.png)](images/github/hardware-labels-light.png)

Device, rack, port, panel, wall-jack and cable labels from millimetre templates, printed at true size. Cable labels come in pairs, each end naming where the other goes, and a calibration page checks the printer.

---

## Everyday workflows

Ticket to resolution, quote to invoice, and the documentation that hangs off both.

### Service desk queue

**Professional Dark theme**

[![Service desk queue in the Professional Dark theme with page tabs for All Tickets, Overview, My Queue, Unassigned, SLA and Escalated, saved views (All tickets, My open tickets, Unassigned, Waiting on us, Customer replied), and a list of 36 tickets across five clients with subject and ticket number, client, priority, status, queue, assignee, a Needs reply flag, last activity with who acted, and age](images/github/ticket-queue-dark.png)](images/github/ticket-queue-dark.png)

Every client in one queue. Filter by status, priority, queue or technician; the subject is what you scan, not the badges.

### A ticket that knows the customer

**Light theme**

[![Ticket detail in light theme laid out as a conversation: customer messages in left-hand bubbles labelled Customer, technician replies in blue right-hand bubbles labelled Technician, an amber internal note marked staff only, a status-change row and a composer set to Public reply, beside the Cc list, the active contract, problem link, closeout checklist, details and the asset card](images/github/ticket-detail-light.png)](images/github/ticket-detail-light.png)

The ticket reads as a conversation: the customer on the left, technicians on the right, internal notes in amber marked staff only, and status changes as compact rows. Contract hours, the SLA countdown and the credentials this job needs sit alongside — listed, never revealed.

### Internal note composer

**Professional Dark theme**

[![Ticket reply composer in the Professional Dark theme switched to Internal note, with an amber box labelled staff only and a restored draft](images/github/ticket-composer-dark.png)](images/github/ticket-composer-dark.png)

Public reply and internal note are separate modes. An internal note gets an amber composer that says it is never sent to the client, and an unsent reply is saved as a draft only its author can see.

### Client documentation

**Professional Dark theme**

[![Document list in the Professional Dark theme showing per-client documentation with category, tags and last-updated date](images/github/documents-dark.png)](images/github/documents-dark.png)

Per-client documents and global knowledge base articles, searchable by title and body.

### Runbooks beside the work

**Light theme**

[![Knowledge base runbook in light theme with when-to-use guidance, numbered steps and an escalation note](images/github/kb-runbook-light.png)](images/github/kb-runbook-light.png)

A procedure written for the technician who will actually run it — and linked from the tickets that need it.

### Asset register

**Professional Dark theme**

[![Asset list in the Professional Dark theme showing devices with name, type, manufacturer, model and serial number, with filters above](images/github/assets-dark.png)](images/github/assets-dark.png)

Every device you look after for a client, filterable by type, manufacturer, status and location.

### Asset detail

**Light theme**

[![Asset detail in light theme for a domain controller showing identity, network, operating system, hardware specification, physical position, lifecycle dates and tags](images/github/asset-detail-light.png)](images/github/asset-detail-light.png)

Identity, network, operating system, hardware, rack position, warranty and lifecycle on one record.

### Credential vault

**Professional Dark theme**

[![Password vault in the Professional Dark theme listing nine credentials for one client with title, username and security status, every secret hidden](images/github/vault-dark.png)](images/github/vault-dark.png)

AES-GCM encrypted at rest, organised per client. Secrets are never rendered into a list — opening one is a permissioned, audited act.

### Quote to signature

**Light theme**

[![Quote detail in light theme with line items, subtotal, tax and total, plus actions to view the PDF, email it, copy a signing URL or accept it](images/github/quote-detail-light.png)](images/github/quote-detail-light.png)

Line items, tax and total, a PDF, and a signing link the customer can use without an account. Accepting it can open a ticket or spin up a project.

### Invoices that explain themselves

**Professional Dark theme**

[![Invoice detail in the Professional Dark theme with line items tagged by origin, a payment recording form and a push-to-accounting action](images/github/invoice-detail-dark.png)](images/github/invoice-detail-dark.png)

Every line carries its origin — a contract period, a logged time entry, an expense — so a billing query is answerable without reconstructing it.

### Agreements and hours

**Light theme**

[![Contract detail in light theme showing hours consumed, rollover policy, auto-renewal state and a profitability snapshot](images/github/contract-detail-light.png)](images/github/contract-detail-light.png)

Block hours with rollover rules, auto-renewal, and a profitability snapshot for the current period.

### Project delivery

**Professional Dark theme**

[![Project detail in the Professional Dark theme showing client, owner, dates, a ready-to-bill panel, profitability, budget consumption and a task list with milestones](images/github/project-detail-dark.png)](images/github/project-detail-dark.png)

Tasks, milestones and assignees with budget consumption and profitability rolled up from the work already logged.

### Request a service (customer portal)

**Light theme**

[![Customer portal Employee onboarding request form in light theme with filled-in fields, a conditional laptop type question and a what-to-expect panel](images/github/portal-request-form-light.png)](images/github/portal-request-form-light.png)

A customer fills in a guided form from the service catalog. Questions can appear only when relevant (the laptop type appears once "Needs a laptop" is ticked), and the side panel says how long it usually takes and whether approval is needed.

### Document version compare

**Professional Dark theme**

[![Document version comparison in the Professional Dark theme showing removed and added lines between version 1 and the current runbook, with a restore button](images/github/document-version-diff-dark.png)](images/github/document-version-diff-dark.png)

Compare any stored version of a document with the current one, line by line, and restore it if needed. A restore is audited and keeps the replaced content as a version.

### A ticket conversation with Cc and a secure message

**Professional Dark theme**

[![Resolved ticket in the Professional Dark theme titled Outlook keeps asking for my password: customer bubbles from Dana Whitfield on the left, technician replies from Jordan Reyes on the right with one showing Cc office.manager@northwind.example, an amber internal note marked staff only, status-change rows, and a dashed Secure message box reading opened by the recipient, opens once, its content encrypted and not shown; beside it a Copied on replies (Cc) card, the active contract and a linked known-error problem record](images/github/ticket-conversation-dark.png)](images/github/ticket-conversation-dark.png)

A customer's e-mailed request as a thread: replies quote what they answer, the internal note stays amber and staff-only, and the reply that carried a temporary password shows only the secure message's state — opened by the recipient — never its content. The header says what happened last and the Cc card lists who is copied on e-mailed replies.

### Replying with Cc

**Light theme**

[![Ticket composer in light theme with Email this reply ticked and a Cc field pre-filled with hr@ridgeline.example and it.lead@ridgeline.example, below a technician reply whose dashed Secure message box reads sent by e-mail, not opened yet, opens once, with an expiry date](images/github/ticket-cc-reply-light.png)](images/github/ticket-cc-reply-light.png)

Tick "Email this reply" and the Cc field appears, filled from the people the customer copied. The reply above it carried a first-day password as a secure message: sent by e-mail, not opened yet, opens once, with its expiry.

### Adding a secure message

**Professional Dark theme**

[![Public reply composer in the Professional Dark theme with the Add a secure message section open: a box for the secret that goes only to marcus.bell@northwind.example, an Expires after 3 days selector, a Can be opened once checkbox, the note Can't be combined with Cc, and Email this reply ticked](images/github/ticket-secure-compose-dark.png)](images/github/ticket-secure-compose-dark.png)

A secret such as a temporary password goes in its own box, not the reply. It is stored encrypted as a one-time link that only the requester receives, expires after 1, 3 or 7 days, and cannot be combined with Cc.

### The same ticket in the customer portal

**Light theme**

[![Customer portal ticket page in light theme for Northwind Logistics: a Received, In progress, Resolved progress bar, then the conversation with customer and technician bubbles, the Cc line on a reply, and a Secure message box reading sent to your e-mail address as a separate link that opens once, it has been opened; the internal note is absent](images/github/portal-ticket-light.png)](images/github/portal-ticket-light.png)

The customer sees the shared conversation in the same layout, with no internal note and no technician working data. Where a reply carried a secure message, the portal says it went to their e-mail address as a separate link.

### Approving a request as the named approver

**Light theme**

[![Customer portal Approvals page in light theme: an access request from Dana Whitfield for read and write access to the inventory share, labelled Approver: Aaron Lindqvist, with a comment box and Approve and Deny buttons](images/github/portal-approvals-light.png)](images/github/portal-approvals-light.png)

A request type can name who approves it for each customer. Here Aaron is the named approver for access requests, so Dana's request waits on him and he gets Approve and Deny; other customer admins see who it is waiting on.

### Change request and CAB vote

**Professional Dark theme**

[![Change management page in the Professional Dark theme for a high-risk firewall firmware upgrade marked Approved, ready to implement: implementation and rollback plans, impact assessment, scheduled window, and a CAB approval table with two approvals, a vote box and a Begin Implementation button](images/github/change-cab-dark.png)](images/github/change-cab-dark.png)

A change carries its implementation, rollback and impact plans, its window, and the CAB's votes. It can be implemented only once every required approver has approved and nobody has rejected it.

### Problem records

**Light theme**

[![Problem Records list in light theme with problems such as VPN tunnels dropping on dead-peer-detection timeouts, recurring Outlook credential prompts and print spooler crashes, each with status, priority, assignee, linked tickets and created date](images/github/problems-light.png)](images/github/problems-light.png)

Recurring incidents get a problem record of their own, from investigating to known error to resolved, with the tickets linked to it.

---

## Tickets and the paired RMM

Pairing an RMM for ticket-rmm-v1, then handoffs, read-only diagnostics and fix referrals from a ticket.

### Pairing an RMM for ticket integration

**Light theme**

[![Ticket integration pairing section of the Tactical RMM connection form in light theme, with the pairing switch, integration key ID, outbound and inbound secret fields, processing location and integration address](images/github/rmm-pairing-form-light.png)](images/github/rmm-pairing-form-light.png)

Any RMM that implements the ticket-rmm-v1 contract can be paired from its connection form: an integration key ID, two shared secrets, where requests are processed and an optional integration address. The connection must serve a single customer, and switching pairing on is a protected change that a second administrator approves.

### Pairing status on the connection

**Professional Dark theme**

[![Ticket integration pairing card in the Professional Dark theme marked Paired: contract address, key ID, hosted processing, the pinned tenant beacon-ridgeline, the advertised capabilities, three read-only diagnostics, the time of the last check and a Check pairing button](images/github/rmm-pairing-status-dark.png)](images/github/rmm-pairing-status-dark.png)

The connection page says in plain words whether the pairing is live, which tenant it is pinned to, what the RMM advertised in its last capabilities check and which read-only diagnostics it offers. If the RMM ever answers for a different tenant, the pairing stops.

### The ticket's asset and its paired RMM

**Light theme**

[![Asset card on a ticket in light theme for workstation RDG-OP3-PC: the RMM's online status and last check-in, then a Paired RMM block with Send to RMM, Request view and Request control buttons, a Disk space read-only diagnostic picker, Refer a fix, and three requests already sent: an approved fix referral, a completed diagnostic and a handoff with receipt confirmed](images/github/ticket-rmm-light.png)](images/github/ticket-rmm-light.png)

A ticket names the asset it is about, chosen from that customer's assets only. Technicians see what the RMM last reported and, when the RMM is paired, the actions their Technician Access allows on that device: send the ticket, run a read-only diagnostic, open a view or control session, or refer a fix. Customers see none of it.

### Reviewing a handoff before it is sent

**Professional Dark theme**

[![Send to RMM preview in the Professional Dark theme for ticket PSA-2026-000036, naming Ridgeline — Tactical RMM, its integration address, tenant beacon-ridgeline and device RDG-OP3-PC, the four redacted items that would be sent, what was left out (one internal note), an optional note field and Send to RMM and Cancel buttons](images/github/rmm-handoff-preview-dark.png)](images/github/rmm-handoff-preview-dark.png)

Send to RMM shows exactly what will leave: the destination, its tenant and device, and the redacted ticket context — the same evidence document ticket analysis uses, with what was left out and what was redacted. Nothing is sent until the technician confirms, and it counts as sent only when the RMM confirms receipt.

### What the RMM said back

**Professional Dark theme**

[![Requests to the RMM list on a ticket in the Professional Dark theme: a handoff marked Sent with receipt confirmed, a Disk space diagnostic marked Completed with its staff-only result expanded showing C: at 4% free, and a fix referral to clear the X-ray bridge cache marked Approved in the RMM](images/github/ticket-rmm-requests-dark.png)](images/github/ticket-rmm-requests-dark.png)

Every request keeps the RMM's signed status callbacks: a handoff counts as sent once receipt is confirmed, a read-only diagnostic's sanitised, size-limited result is shown to staff only, and a fix referral shows the RMM's approval. ClientSt0r only refers a fix; the RMM approves and runs it.

### Effective access with a paired RMM

**Light theme**

[![Preview effective access in light theme for demo.tech at Ridgeline Dental Group: ticket AI, Private RMM handoff, read-only diagnostics and low-risk fix requests allowed in scope; view and control sessions by time-limited request; advanced diagnostics, elevation, unattended access, clipboard and file transfer unavailable because the paired RMM does not advertise them; and locked rows such as approving an endpoint fix and running commands from ClientSt0r](images/github/technician-access-rmm-light.png)](images/github/technician-access-rmm-light.png)

The effective-access preview shows, for one technician at one customer, each capability's result and why. RMM, remote-access and fix capabilities stay Unavailable until the customer's paired RMM advertises them; remote sessions on the L2 preset are by request.

---

## Management and configuration

The commercial side: what is quoted, what is billed, and what each client is entitled to.

### Quote pipeline

**Light theme**

[![Quote list in light theme showing three quotes across three clients with status, total and creation date](images/github/quotes-list-light.png)](images/github/quotes-list-light.png)

Draft, sent and accepted quotes across every client, with totals and a one-click PDF.

### Billing at a glance

**Professional Dark theme**

[![Invoice list in the Professional Dark theme showing three invoices with sent, paid and overdue status, totals, balances and accounting push state](images/github/invoices-list-dark.png)](images/github/invoices-list-dark.png)

Sent, paid and overdue invoices with balances, and whether each has been pushed to your accounting system.

### Agreements per client

**Light theme**

[![Contract list in light theme showing three agreements with type, status, hours used against allowance and period](images/github/contracts-list-light.png)](images/github/contracts-list-light.png)

Which clients are on managed agreements, which are on block hours, and how much of the allowance is gone.

### Named approvers per request type

**Professional Dark theme**

[![Named approvers page in the Professional Dark theme for the Access request type: a list of customers with how many approvers each has, and for Northwind Logistics a warning that Grace Holt is no longer an active person there and is ignored, with Aaron Lindqvist ticked among the customer's people and a Save approvers button](images/github/catalog-approvers-dark.png)](images/github/catalog-approvers-dark.png)

For each customer a request type is offered to, staff pick which of that customer's people approve it. With nobody named, the customer's admins approve as before. Someone who has left is flagged and ignored, and nobody approves their own request.

### Sales pipeline

**Professional Dark theme**

[![CRM sales pipeline in the Professional Dark theme with Discovery, Qualified, Proposal, Negotiation, Closed Won and Closed Lost columns holding opportunities such as a managed security add-on and a server room refresh, with values, probabilities and weighted totals](images/github/crm-pipeline-dark.png)](images/github/crm-pipeline-dark.png)

Opportunities by stage, each with its customer, value, probability and owner, and a weighted total per column. Drag a card to move it to another stage.

---

## Access and administration

Tenancy, membership and the switches that decide which modules exist.

### Tenants and access

**Professional Dark theme**

[![Organization list in the Professional Dark theme showing client tenants with member counts, asset counts and status](images/github/organizations-dark.png)](images/github/organizations-dark.png)

Every client is its own tenant. Membership decides who sees what; switching client context is one click.

### Feature toggles

**Light theme**

[![Feature toggle settings in light theme showing switches for optional modules including the native PSA service desk](images/github/feature-toggles-light.png)](images/github/feature-toggles-light.png)

The service desk, AI assistance and other modules are opt-in — off until an administrator turns them on.

### Scheduler

**Professional Dark theme**

[![Task scheduler settings in the Professional Dark theme listing periodic jobs with run history, one failed recurring-invoice job showing its error message, and late fees switched off](images/github/settings-scheduler-dark.png)](images/github/settings-scheduler-dark.png)

The built-in scheduler's periodic jobs with their interval, last and next run, status and run count. A job that reports a problem shows its error here, such as recurring invoicing skipping a contract that is more than one period behind. Late fees are off until you turn them on.

### Security settings

**Light theme**

[![Security settings page in light theme with session, 2FA, password policy and brute-force fields, two of them marked Set by environment](images/github/settings-security-light.png)](images/github/settings-security-light.png)

Session limits, 2FA, password rules and lockout are set here and take effect when saved. A value fixed by an environment variable is marked "Set by environment" and can only be changed on the server.

### Settings center

**Light theme**

[![Settings center in light theme: a search box above ten category cards, each listing its settings pages, from General Settings and Customer Portal to Data Import and Vault Import](images/github/settings-center-light.png)](images/github/settings-center-light.png)

Administration opens the settings center: one compact card per category — General, Users & Access, Security, Integrations, AI Configuration (OPTIONAL AI), Automation, Communications, Modules, System and Maintenance — each listing only the pages you may open, with a search across all of them.

### Customer Portal settings

**Light theme**

[![Customer Portal settings in light theme with sections for the portal address and effective URL, branding fields and colour pickers, layout and theme choices, portal feature switches and per-customer portal switches](images/github/portal-settings-light.png)](images/github/portal-settings-light.png)

One page for the customer portal: its address and sign-in, branding (name, logo, accent colour, sign-in background, welcome message, support contacts), layout and default theme, the portal features, and which customers have a portal at all.

---

## Operations and monitoring

Every alert source in one event list, ingestion health, backup monitoring and the wallboards on the office screen.

### Events

**Professional Dark theme**

[![Events list in dark theme showing website, backup, security and RMM alerts across several customers with severity badges and occurrence counts](images/github/events-dark.png)](images/github/events-dark.png)

One list of alerts from every source — security vendors and SIEM, RMM, Rem0te, backups and website monitors — with severity, customer, status and repeat counts.

### Event ingestion health

**Light theme**

[![Event ingestion health page listing each alert source with last ingestion time, error counts and retention settings](images/github/events-ingestion-light.png)](images/github/events-ingestion-light.png)

Per-source ingestion status, queue depth and dead letters, with retention settings per source and per customer.

### Backup monitoring

**Light theme**

[![Backup monitoring dashboard listing two customers marked stale data, with job counts, newest and oldest successful backups, repository capacity bars, restore test status and open alert counts](images/github/backup-monitoring-light.png)](images/github/backup-monitoring-light.png)

Backup health per customer from Proxmox Backup Server and restic reports: newest and oldest success, repository capacity, restore tests and open alerts. A source that has stopped reporting shows as stale, never as healthy.

### Wallboard

**Professional Dark theme**

[![Service Desk wallboard in dark theme with ticket, monitor and certificate counters, a monitor status pie chart, a 30-day ticket chart and tickets by priority](images/github/wallboard-dark.png)](images/github/wallboard-dark.png)

A configurable wallboard for the office screen: open and overdue tickets, monitors down, certificates expiring, monitor status and ticket trends.

---

## Business operations

The owner's view: business overview, licensing, customer health, pricing findings and onboarding a new customer.

### Business overview

**Professional Dark theme**

[![Business overview in dark theme with MRR and ARR, invoiced revenue, gross margin, customer profitability and contract renewal cards](images/github/business-overview-dark.png)](images/github/business-overview-dark.png)

Revenue, recurring revenue, margin and customer figures for the date range, each card showing its data source and whether the figure is complete.

### Software licensing

**Light theme**

[![Software licensing overview listing renewals, an over-allocated subscription and unused licenses, with purchased, assigned and unused counts per customer](images/github/licensing-light.png)](images/github/licensing-light.png)

What each customer has purchased, what is assigned and when it renews, with unused, over-allocated and renewal items called out.

### Client health

**Professional Dark theme**

[![Client health table in dark theme with overall scores, coverage and per-dimension scores for each customer, some marked unknown](images/github/client-health-dark.png)](images/github/client-health-dark.png)

A score per customer across technical, security, backup, service delivery, commercial and satisfaction dimensions; dimensions without trustworthy data show as unknown.

### Pricing advisor

**Light theme**

[![Pricing advisor listing high-severity findings per customer and the coverage of each detector](images/github/pricing-advisor-light.png)](images/github/pricing-advisor-light.png)

Loss-making customers, underpriced contracts, unbilled work and renewals to review, from contract, invoice and time data. Recommendations only create drafts.

### Customer onboarding

**Light theme**

[![Customer onboarding page with an in-progress list, a button to onboard a new customer and a form to start a change for an existing customer](images/github/onboarding-wizard-light.png)](images/github/onboarding-wizard-light.png)

Start onboarding a new customer (record, locations, plan, agreement, integrations, activation) or a change for an existing one; price and contract changes go through approval as drafts.

---

## Security and client data protection

Which safeguards are in effect for a customer, who may see and widen what, and how secrets reach a customer.

### What the recipient of a secure message sees

**Light theme**

[![Secure message page in light theme reading You have a secure message, it can be opened once, copy what you need before you leave the page, with its expiry time and a Show the message button](images/github/secure-message-reveal-light.png)](images/github/secure-message-reveal-light.png)

A one-time link opens behind a button. Mail scanners and link previews fetch links without pressing it, so they no longer use up the message before the person it was sent to sees it.

### Security Features

**Light theme**

[![Security Features page in light theme with the effective state shown for Northwind Logistics: a Sign-in table listing two-factor sign-in, failed sign-in lockout, password rules and hashing, session time limits, the IP and country firewall and the Content Security Policy, each with a shipped badge, default and prerequisites, and its state at the customer such as Partly, On or Off, then a Client access table](images/github/security-features-light.png)](images/github/security-features-light.png)

Every safeguard with what it protects, its default and what it needs — and, for the customer you pick, whether it is actually in effect there. Values fixed by an environment variable are named; a check that cannot be read shows Unknown, never On.

### Vault visibility report

**Professional Dark theme**

[![Vault Visibility report in the Professional Dark theme explaining that vault titles stay inside the customers a technician is assigned to, with a table of technicians, the customers they still see, the customer they no longer see and the number of entries hidden](images/github/vault-visibility-dark.png)](images/github/vault-visibility-dark.png)

Technicians see a customer's vault entries only where a membership or their global role grants it. This read-only report shows which staff lost cross-customer visibility, what they still see and how many entries are now hidden. It grants nothing.

### Technician Access

**Light theme**

[![Technician Access settings in light theme: the order of evaluation, a password and authenticator confirmation box, protected changes waiting, an effective-access preview, assignments of L1 Help Desk and L2 Technician presets to three technicians at Northwind Logistics, and the preset capability table](images/github/technician-access-light.png)](images/github/technician-access-light.png)

What each MSP technician may do with ticket AI and RMM tools, per customer, from L1, L2 and L3 presets. Narrowing applies at once; anything that widens access is a protected change that a different administrator approves.

### Superuser Approval

**Professional Dark theme**

[![Superuser Approval page in the Professional Dark theme with the policy turned on, two eligible administrators, and a grant of superuser to one account waiting for approval by a different administrator](images/github/superuser-approval-dark.png)](images/github/superuser-approval-dark.png)

Optional and off by default. When on, creating or promoting a superuser is a request that a different administrator must approve; until then the account is not a superuser. Turning the policy off is itself a protected change.

### Ticket AI models (OPTIONAL AI)

**Professional Dark theme**

[![Ticket AI Assist models and customer policies page in the Professional Dark theme marked OPTIONAL AI, listing two model profiles with provider and model, a write-only stored key, MSP ownership for assigned customers only and enabled status, beside a New profile form](images/github/ticket-ai-models-dark.png)](images/github/ticket-ai-models-dark.png)

Optional, off unless PSA AI is enabled. Model profiles name the provider, model and whose key it is; keys are write-only and sealed to the gateway. Each customer's AI policy decides what is allowed there.

### Security Overview

**Professional Dark theme**

[![Security Overview in the Professional Dark theme with four panels: Security Alerts showing 9 active, 3 critical, 3 high and 3 unacknowledged; Incidents showing 6 open with counts by severity and assigned responders; RMM Security with 9 device security alerts; Monitoring with website monitor, WAN, expiration and network integration status; and a Response Performance panel with an 8-minute time to acknowledge, a 26-hour time to resolve, open incident aging and a 14-day alert volume chart](images/github/security-overview-dark.png)](images/github/security-overview-dark.png)

One read-only page for security: alerts, incidents, RMM security and monitoring, each scoped to the customers your role covers, plus response times for the last thirty days. Every figure opens the page where you work it.

### Security incidents

**Professional Dark theme**

[![Security Incidents list in the Professional Dark theme with VPN brute-force attempts, a compromised Microsoft 365 account and blocked ransomware incidents across three clients, each with severity, status, client, asset, opened time and alert count](images/github/security-incidents-dark.png)](images/github/security-incidents-dark.png)

Alerts that need handling become incidents with a severity, a status, the client and asset involved, and the alerts behind them.

### Update available

**Light theme**

[![Top bar in light theme: the ClientSt0r logo with an amber Update Available v3.17.681 pill beside it, then Go to with its Ctrl K hint, Favorites, Recent, the client switcher, the notifications bell, Help, the settings gear and the account menu](images/github/update-badge-light.png)](images/github/update-badge-light.png)

When the scheduled update check finds a newer release, superusers see a glowing amber Update Available pill beside the logo, at every window width, and an entry in the notifications bell; both link to Administration → System → System Updates. Pages never contact GitHub while loading, and other users never see it.

### API access control

**Light theme**

[![API Access Control settings with global mode selectors, per-address limits and a rules table with allow and deny entries](images/github/api-access-light.png)](images/github/api-access-light.png)

Address rules for the inbound API and webhooks: allowlist and denylist modes, per-key and per-integration scopes, rate and size limits, and a trial window that undoes risky changes.

---

## About these captures

- Viewport 1440 px wide (390 px for the phone views) at device pixel ratio 2, so text stays sharp when you open an image full size.
- Themes are switched through the application's own theme control, not by injecting CSS — what you see is the shipped theme.
- Each image is cropped to where the page's content ends, so none of them carry a slab of empty background. Views of an open menu, the palette or a phone show the window as it is.
- Absolute links a page prints (a status page link, the portal address) show the demo's documented host, `desk.beaconmanaged.example`, instead of the local address the capture ran on.
- Route, theme, viewport and the demo data each view needs are recorded in [`scripts/screenshot_manifest.json`](../scripts/screenshot_manifest.json).

Prefer moving pictures? The [4-minute walkthrough](https://github.com/agit8or1/clientst0r/releases/download/v3.17.681/clientst0r-walkthrough.mp4) covers the same ground end to end, in both themes.

Older captures from previous releases are kept in [`docs/screenshots/`](screenshots/README.md).

---

[← Back to the README](../README.md) · [MSP Reboot](https://mspreboot.com) — the MSP consulting practice behind ClientSt0r
