# ClientSt0r screenshots — archive

> **This is the archive.** The current visual tour lives at
> [`docs/screenshots.md`](../screenshots.md), captured against the current release.
> The 59 images indexed below span **v2.24.52 to v3.17.475** and show older styling, but
> they cover ground the current tour does not: racks, VLANs and IPAM, floor plan import,
> diagrams, secure notes, security alert ingestion and its auto-ticket rules, UniFi and
> Microsoft 365 connection forms, wallboards, fleet vehicles and inventory with printable
> QR labels, and the system status and update screens.
>
> A further 30 files sit in this directory unindexed — the older PSA quote, invoice,
> contract, dispatch and project captures, plus the compliance framework screens. The
> first group is superseded by the current tour; the compliance screens simply have not
> been recaptured yet.

All screenshots use demo data.

**Read them with that age in mind.** Most of these predate the rename, so the navbar,
footer and watermark still carry the old product name. Several pages were captured in a
state that would not be chosen today — empty network closets, IPAM, expirations, personal
vault, secure notes, global workflows, security alerts and processes all show first-run
empty states, and a number of the later captures have the "add to home screen" prompt open
over the page. The alt text below describes what each image actually shows, empty states
included, rather than what the feature does at its best.

---

## 🏠 Core Features

### Dashboard
![Organization dashboard with quick-action shortcuts, counters for passwords, assets, documents and monitors, an empty location map, and panels for recent items, items expiring in 30 days and monitor status](dashboard.png)

### Quick Add
![Quick Add page offering three shortcut cards — add a new user, add a new PC or laptop asset, and add a new server asset](quick-add.png)

### Profile
![User profile page showing contact details, timezone, language, theme and background preference, a security panel confirming two-factor authentication is enabled, and organization memberships with an owner role](profile.png)

### Favorites
![Favorites page listing one starred vault entry under a Passwords heading](favorites.png)

---

## 📦 Asset Management

### Assets List
![Asset list filtered by type, manufacturer, status and location, showing nine devices with name, type, manufacturer, model and serial number — a Synology backup server, a Cisco core switch, a Dell development server, a Fortinet firewall and a patch panel](assets-list.png)

### Racks
![Rack management page listing one 42U full rack in a datacentre, with width, available units and device count](racks.png)

### Network Closets
![Empty network closets page inviting the first IDF, MDF or wiring closet to be added](network-closets.png)

### IPAM/Subnets
![Empty IP address management page inviting the first subnet to be added](ipam-subnets.png)

### VLANs
![VLAN table listing a single VLAN with its ID, name, description, colour swatch and subnet count](vlans.png)

### Locations
![Locations page with search, status and type filters, a total-locations counter, and one office location marked as headquarters with an action to generate a floor plan](locations.png)

---

## 🔐 Password Vault & Security

### Password Vault
![Password vault listing nine credentials with username, type and a security column — five flagged weak and four flagged as found in a breach. Secret values are never shown in the list](password-vault.png)

### Personal Vault
![Empty personal vault inviting the first encrypted note to be created](personal-vault.png)

### Secure Notes
![Secure notes page with inbox and sent tabs, showing an empty inbox](secure-notes.png)

---

## 📚 Documentation & Knowledge Base

### Knowledge Base
![Document list for one organization showing five documents — incident response plan, development environment setup, server access policy, backup procedures and network architecture overview — with category, tags and last-updated date](knowledge-base.png)

### Diagrams
![Diagram gallery with three thumbnails: an office floor plan, a network topology diagram and a third diagram, each with a type badge and last-edited time](diagrams.png)

### Floor Plans Import
![Floor plan import page: an upload form for a MagicPlan JSON export with target organization, optional location link and a dry-run preview toggle, beside a sidebar explaining what gets imported and how to export from the app](floor-plans-import.png)

---

## 🔄 Workflows & Processes

### Workflows
![Process list showing three multi-stage workflows — monthly security patching, new server deployment and employee offboarding — with stage counts and scope](workflows.png)

---

## 🌐 Monitoring & Expirations

### Website Monitors
![Website monitor list showing two endpoints with status, response time, SSL expiry date and last-check time — one reporting down, one active](website-monitors.png)

### Expirations
![Empty expirations page inviting the first SSL certificate, licence or contract expiry to be tracked](expirations.png)

---

## 🔒 Security & Scanning

### Security Dashboard
![Security dashboard showing current vulnerability counts across critical, high, medium and low — all zero after the most recent scan — with scan statistics and quick actions to run a scan or review configuration](security-dashboard.png)

### Vulnerability Scans
![Dependency scan history: the latest scan reporting zero vulnerabilities, above a table of earlier scans with duration, vulnerability count and a severity breakdown](vulnerability-scans.png)

### Scan Configuration
![Dependency scanning settings with an enable toggle and step-by-step setup instructions for creating an account, generating an API token and finding the organization ID](scan-configuration.png)

---

## ⚙️ System Administration

### General Settings
![General settings page with fields for site name, site base URL used in email links and API callbacks, and default timezone for new users](settings-general.png)

### System Status
![System status page showing version, operating system, Python and Django versions, database engine and size, service states, CPU, memory and disk usage, a capacity score, record counts and the schedule of background tasks with their last and next run](system-status.png)

### System Updates
![System updates page showing the installed version, an up-to-date badge against the latest released version, a check-for-updates action, and the equivalent command-line update instructions](system-updates.png)

### Organizations
![Organization list showing six tenants with type badges — fully managed, internal, co-managed and break-fix — alongside member count, asset count, status and creation date](organizations.png)

### Access Management
![Access management overview with counters for organizations, users and memberships, beside panels listing each organization and each user account with its role](access-management.png)

### Integrations
![Integrations page with separate sections for PSA, RMM and UniFi connections, each showing no connection configured yet and an action to add one](integrations.png)

### Import Data
![Import jobs page showing no import jobs yet, with an action to create the first import](import-data.png)

---

## 🌍 MSP/Global Features (Staff Only)

### Global Dashboard
![Cross-tenant dashboard with totals for organizations, users, assets, documents, passwords, processes, monitors and files, a thirty-day system health summary, process statistics and a ranked list of the largest organizations](global-dashboard.png)

### Global Knowledge Base
![Staff-only global knowledge base listing five articles covering Linux server administration, VMware vSphere, Windows Server performance troubleshooting, enterprise wireless setup and VLAN routing, with category tags and last-updated dates](global-kb.png)

### Global Workflows
![Empty global workflows page — processes defined here would be available to every organization](global-workflows.png)

---

## 📝 Login Page

### Login
![Sign-in form asking for username and password](login-page.png)

---

## 🚗 Service Vehicles & Inventory

### Vehicles Dashboard
![Service vehicle dashboard with counters for total, active and in-maintenance vehicles and total miles, a low-inventory-stock alert, panels for recent fuel logs, maintenance and damage reports, and fleet metrics for average mileage, fuel economy and fuel cost](vehicles-dashboard.png)

### Vehicle List
![Vehicle list showing one van with make and model, year, licence plate, mileage, status, condition and assignment](vehicles-list.png)

### Inventory (Unified View)
![Unified inventory view with an alert that two items are at or below their minimum quantity, listing eight items carried in the van — cabling, connectors, consumables and tools — each with category, quantity and stock status](vehicles-inventory.png)

### Inventory — By Vehicle
![Inventory grouped by vehicle, showing the van's low-stock count and total stock value above eight items with the compartment each is stored in](vehicles-inventory-by-vehicle.png)

### Inventory — Shop
![Shop inventory listing eight stocked items with shelf or bin location, quantity, minimum quantity, value and stock status — one fibre optic cable flagged as low](vehicles-inventory-shop.png)

### Shop Inventory Item Edit (with QR code)
![Shop inventory item edit form with name, category, quantity, minimum quantity, reorder quantity and unit cost, beside an auto-generated QR code that can be downloaded and printed as a label](vehicles-inventory-shop-edit.png)

### Vehicle Inventory Item Edit (with QR code)
![Vehicle inventory item edit form with quantity, unit cost, storage location in the van and a description, beside an auto-generated QR code and a reorder link to the supplier](vehicles-inventory-item-edit.png)

### QR Code Print Sheet
![Printable QR code sheet for inventory labels, with printing guidance above a grid of codes, each labelled with item name, part number, vehicle, minimum quantity, category and storage location](vehicles-inventory-qr-codes.png)

---

## 🛡️ Security Alert Ingestion

Unified triage queue for EDR / AV / firewall alerts from any vendor, plus auto-ticket
rules that fire on matching inbound alerts.

### Alert triage queue
![Security alert triage queue with filters for severity, status, vendor, client and date range, and bulk acknowledge, dismiss and resolve actions — no alerts yet until a vendor connection is configured](security-alerts-list.png)

### Vendor connections
![Security vendor connections page with columns for provider, category, client, sync state and status — no connections configured yet](security-alerts-connections.png)

### New vendor connection
![New security vendor connection form grouped into identity, endpoint and credentials, polling and activity, and notes — with the credential blob encrypted at rest and a poll interval that can be disabled for webhook-only providers](security-alerts-connection-new.png)

### Auto-ticket rules
![Auto-ticket rules page listing rules by priority, match criteria, minimum severity, suppression window and action — no rules created yet](security-alerts-rules.png)

### New auto-ticket rule
![New auto-ticket rule form: identity and priority, match clauses that must all be satisfied — provider, category, minimum severity and client — the action taken when matched, and an optional suppression window](security-alerts-rule-new.png)

---

## 🔌 Integration Connection Forms

### New UniFi connection
![New UniFi connection form with a self-hosted or cloud Site Manager mode toggle, controller endpoint and TLS verification, and API key credentials, beside a sidebar giving the setup steps for both modes](integrations-unifi-new.png)

### New Microsoft 365 connection
![New Microsoft 365 connection form with tenant directory ID and app registration client ID and secret, beside a sidebar listing the exact Graph API permissions the app registration needs](integrations-m365-new.png)

---

## 📺 Wallboards

TV-ready big-number displays, configurable per organization.

### Wallboard list
![Wallboard list showing one global board with its refresh interval, rotation order, active state and widget count](wallboards-list.png)

### New wallboard
![New wallboard form with scope and name, a choice of starter templates — operations overview, service desk, security and alerts, monitoring and infrastructure, sales and revenue, or client health — and refresh and rotation settings for TV display](wallboards-new.png)

---

## 🎫 Service Desk — additional views

### Dispatch heatmap
![Dispatch heatmap covering a fourteen-day window, empty because no assigned tickets currently carry due dates in that range](dispatch-heatmap.png)

### Recurring ticket schedule form
![Recurring ticket schedule form with an internal schedule name, the client it belongs to, subject and body templates for the generated ticket, queue, priority and type, a monthly frequency with interval, and the next run time](psa-recurring-form.png)

### Organizations grid
![Organization list in grid view, showing six tenant cards with type badges, slug, member and asset counts, and shortcuts to details, edit and account](organizations-grid.png)

### Processes
![Process list with search and category filters and a banner explaining that running a workflow attaches it to a new ticket with its checklist embedded — no workflows defined yet](processes.png)

---

## 🧾 Vehicle Receipt Scanning

### Receipt list and cost summary
![Expense receipts tab on a service vehicle record, with no receipts recorded yet and an action to add the first one](vehicle-receipts.png)

### Add receipt
![Add receipt form in two steps: an optional receipt photo captured from a phone camera or chosen from disk, then receipt details — date, vendor, amount, tax, category, odometer reading, description and notes](vehicle-receipt-form.png)

---

## 📱 Install App / Phone Shortcut

### Install App page
![Install page showing a QR code to open the app on a phone alongside the server address, with expandable step-by-step instructions for adding it to the home screen on Android, iPhone or iPad, and desktop](install-app.png)

### Phone shortcut
![Phone shortcut dialog showing a QR code that opens a specific vehicle's receipt page directly, with a copyable link and add-to-home-screen instructions for Android and iOS](pwa-shortcut.png)

---

## 🗺️ Live Roadmap

The roadmap renders in-app from `docs/ROADMAP.md`, and is also published to the About-page
card and a polling-friendly JSON feed at `/core/roadmap.json`.

![In-app roadmap page rendering the repository's roadmap file, with a counter of shipped, in-progress and planned phases, a toggle to hide completed phases, and one phase expanded to show its models, endpoints and scope](roadmap.png)

---

**ClientSt0r** — self-hosted IT documentation and service desk for MSPs
https://github.com/agit8or1/clientst0r
