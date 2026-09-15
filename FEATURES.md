# Client St0r Features

Complete feature documentation for ClientSt0r — self-hosted IT documentation and service desk for MSPs: client assets, runbooks, an encrypted credential vault, native ticketing with SLAs and billing, monitoring and compliance.

See the [README](README.md) for positioning and install steps, and [docs/screenshots.md](docs/screenshots.md) for the visual tour.

## 🔐 Security Features

### Authentication & Access Control
- **Azure AD / Microsoft Entra ID SSO** - Single sign-on with auto-user creation and 2FA bypass
- **LDAP/Active Directory** - Enterprise directory integration
- **Enforced TOTP 2FA** - Two-factor authentication required for all users
- **Argon2 Password Hashing** - Industry-standard password security
- **Session Management** - Secure session handling with configurable timeout
- **Brute-Force Protection** - Account lockout after failed login attempts
- **Password Policies** - Configurable complexity requirements

### Data Protection
- **AES-GCM Encryption** - Military-grade encryption for passwords, credentials, API keys, and tokens
- **HMAC-SHA256 API Keys** - Secure API key hashing
- **Encrypted Storage** - All sensitive data encrypted at rest
- **Private File Serving** - Secure file delivery via X-Accel-Redirect

### Application Security
- **SQL Injection Prevention** - Parameterized queries throughout
- **XSS Protection** - Strict output encoding and auto-escaping
- **CSRF Protection** - Multi-domain CSRF token validation
- **SSRF Protection** - URL validation with private IP blacklisting
- **Path Traversal Prevention** - Strict file path validation
- **IDOR Protection** - Object access verification
- **Rate Limiting** - Per-user and per-endpoint protection
- **Security Headers** - CSP, HSTS, X-Frame-Options, X-Content-Type-Options

### Vulnerability Scanning & Monitoring
- **Snyk Security Integration** - Automated vulnerability scanning for Python and JavaScript dependencies with web UI dashboard
- **OS Package Security Scanner** - System package vulnerability scanning with automated security update detection
  - Multi-platform support (apt, yum/dnf, pacman)
  - Security-specific update detection
  - Scheduled daily scans with configurable frequency
  - Dashboard widget with security status overview
  - Scan history with trend visualization
  - Manual scan triggers via web interface
  - Webhook notifications for critical updates
- **Scheduled Scanning** - Configurable automatic scans (daily, weekly, monthly)
- **Automated Scan with Email Alerts** - Opt-in scheduled security scanning (daily by default) that emails all superusers when vulnerabilities are found; toggle on/off from Security Dashboard; shows next scheduled run and last scan status
- **Remediation Guidance** - Detailed upgrade paths and security advisories
- **Trend Analysis** - Track vulnerabilities over time

### File Upload Security
- **File Type Whitelist** - Only approved file types, dangerous extensions blocked
- **File Size Limits** - Maximum 25MB per file
- **Content-Type Validation** - MIME type verification

### Audit & Monitoring
- **Comprehensive Audit Logging** - All actions logged with user, timestamp, and details
- **Security Event Tracking** - Failed logins, permission changes, credential access
- **Export Capabilities** - CSV/JSON export for compliance

### Firewall & Intrusion Prevention
- **iptables Firewall Management** - Web-based firewall rule management
- **GeoIP Country Blocking** - Block traffic from specific countries
- **IP Whitelist/Blacklist** - Manage allowed and blocked IP addresses
- **Firewall Logging** - Track blocked connection attempts
- **Fail2ban Integration** - Automated intrusion prevention system
  - Ban management (view, unban individual IPs, unban all)
  - Jail status monitoring
  - IP check functionality
  - Auto-installation during updates
  - Sudoers configuration for web management

## 🏢 Multi-Organization Management & RBAC

### Organization Management
- **Complete Data Isolation** - Organization-based data separation for managing multiple client organizations
- **Unlimited Organizations** - MSPs can manage unlimited client organizations
- **Custom Branding** - Per-organization customization
- **Flexible Structure** - Hierarchical organization support
- **Staff Access** - Staff users have global access across all organizations for management

### Role-Based Access Control (RBAC)
- **42 Granular Permissions** - Across 10 permission categories
- **Four-Tier Access Levels**:
  - **Owner** - Full control including user management
  - **Admin** - Manage integrations, settings, and resources
  - **Editor** - Create, edit, delete content
  - **Read-Only** - View-only access
- **Role Templates** - Reusable permission sets
- **Custom Roles** - Create roles with specific permission combinations

### User Types
- **Staff Users** - Global access to all organizations
- **Organization Users** - Scoped access to specific organizations
- **User Type Management** - Easy assignment and modification
- **Bulk User Operations** - Import/export users

## 📦 Asset Management

### Asset Tracking
- **Flexible Asset Types** - Unlimited custom asset types
- **Custom Fields** - Add custom fields to any asset type
- **Rich Metadata** - Name, type, status, location, serial number, etc.
- **Asset Relationships** - Link assets to documents, passwords, contacts
- **Tagging System** - Organize with tags
- **Asset Photos** - Upload and display asset images

### Asset Features
- **Search & Filter** - Full-text search with advanced filters
- **Status Tracking** - Active, Inactive, Maintenance, Retired
- **Bulk Operations** - Edit multiple assets at once
- **Asset History** - Track changes over time
- **Lifespan Tracking** - Track purchase date, expected lifespan (years), and receive reminders before end-of-life
  - Recommended lifespans (Firewall: 5-7 years, Server: 3-5 years, Workstation: 3-4 years, Switch: 5-7 years)
  - Configurable reminder periods (months before end-of-life)
  - Auto-calculated EOL dates and replacement due dates
- **Export** - CSV/JSON export capabilities
- **Import** - Bulk import from CSV

## 🔑 Password Vault

### Password Storage
- **AES-GCM Encryption** - All passwords encrypted before storage
- **15 Password Types** - Website logins, email, Windows/AD, database, SSH, API keys, OTP/TOTP, credit cards, network devices, servers, FTP/SFTP, VPN, WiFi, software licenses, and more
- **Type-Specific Fields** - Relevant fields for each password type
- **Folder Organization** - Hierarchical folder structure
- **Password Reveal** - Secure reveal with audit logging

### Password Features
- **Secure Password Generator** - Configurable length (8-128 characters) with cryptographically secure randomness
- **Password Strength Meter** - Real-time strength calculation
- **Password Breach Detection** - HaveIBeenPwned integration with k-anonymity (passwords never leave your server)
  - Automatic breach checking against 600+ million compromised passwords
  - Configurable scan frequencies (2-24 hours)
  - Visual security indicators and breach warnings
  - Optional blocking of breached passwords
  - Comprehensive audit logging
- **Expiration Tracking** - Set expiration dates with warnings
- **Auto-lock** - Passwords automatically masked
- **Copy to Clipboard** - One-click secure copy
- **TOTP Code Generation** - Built-in 2FA code generator with QR codes

### Bitwarden/Vaultwarden Import
- **Complete Import Support** - Import passwords from Bitwarden/Vaultwarden JSON exports
- **All Item Types** - Supports login items, secure notes, cards, and identity items
- **Folder Preservation** - Imports folders with optional prefix
- **Custom Fields** - Preserves all custom fields from Bitwarden
- **TOTP Secrets** - Imports and encrypts 2FA/TOTP secrets
- **Update Existing** - Option to update existing passwords with matching title/username
- **Detailed Statistics** - Shows created/updated/skipped counts
- **Error Handling** - Comprehensive error reporting with partial import success

### Personal Vault
- **User-Specific Encryption** - Each user has their own private vault
- **Private Storage** - Not accessible by admins
- **Quick Notes** - Store personal credentials securely

## 📚 Documentation System

### Organization Documentation
- **Per-Organization Docs** - Isolated documentation per tenant
- **Categories** - Organize with predefined categories:
  - Company Policies
  - IT Procedures
  - Network Documentation
  - Server Documentation
  - Application Documentation
  - Disaster Recovery
  - Compliance
  - Training Materials
- **Rich Text Editor** - Markdown or WYSIWYG
- **Version Control** - Track document changes
- **Tags** - Flexible tagging system
- **Search** - Full-text search across all docs
- **Templates** - Create reusable document templates

### Global Knowledge Base
- **Staff-Only Access** - Internal knowledge base for staff
- **Separate from Org Docs** - Global articles not tied to organizations
- **Pre-Populated Content** - MSP best practices included
- **Full Markdown Support** - Rich formatting options
- **Categories & Tags** - Organize internal knowledge
- **Search** - Quick access to internal docs

### Document Features
- **Attachments** - Upload files to documents
- **Document Templates** - Pre-fill new documents
- **Favorites** - Mark important documents
- **Export** - PDF/Word export
- **Sharing** - Generate secure share links
- **Access Control** - Permission-based viewing

## 🌐 Website Monitoring

### Uptime Monitoring
- **HTTP/HTTPS Checks** - Automated uptime monitoring
- **Configurable Intervals** - 1, 5, 15, 30, 60 minutes
- **Response Time Tracking** - Monitor performance
- **Status Codes** - Track HTTP response codes
- **Downtime Alerts** - Email/webhook notifications

### SSL Certificate Monitoring
- **Certificate Details**:
  - Subject (Common Name)
  - Issuer
  - Serial Number
  - Valid From/To dates
  - SSL Protocol version (TLS 1.2, 1.3)
- **Expiration Warnings** - Configurable warning periods
- **Days Until Expiration** - Real-time countdown
- **Certificate Chain** - Full chain validation

### Domain Expiration
- **Domain Registration Tracking** - Monitor domain expiration
- **Expiration Warnings** - Configurable warning days
- **Multi-Domain Support** - Track unlimited domains
- **Renewal Reminders** - Automated reminders

## 🏗️ Infrastructure Management

### Rack Visualization
- **NetBox-Style Layout** - Visual rack diagrams
- **U Position Tracking** - Track device placement
- **Color-Coded Devices** - Visual organization
- **Power Tracking**:
  - Power capacity (watts)
  - Allocated power
  - Utilization percentage
  - Power warnings
- **Device Details** - Name, U start/end, power draw
- **Click-to-Edit** - Click devices to edit
- **Available Space** - Visual empty space indicators

### IPAM (IP Address Management)
- **Subnet Management** - Track IP subnets
- **VLAN Support** - Organize by VLANs
- **IP Assignment** - Assign IPs to assets
- **Utilization Tracking** - Subnet usage statistics
- **IP Status** - Active, Reserved, Available
- **Network Planning** - Visual network organization

## 📍 Location Management & Navigation

### Location Features
- **Integrated into Organizations** - Manage multiple physical locations per organization directly from the organization detail page — no separate menu required
- **Multi-Location Support** - Each organization can have unlimited locations (headquarters, branches, data centers, etc.)
- **Address Management** - Full address details with geocoding support
- **Coordinates Support** - Latitude/longitude for precise positioning
- **Location Types** - Headquarters, branch office, data center, remote site, customer site
- **Status Tracking** - Active, planned, inactive, closed (with colored badges)
- **Primary Location** - Designate headquarters
- **Floor Plan Support** - Track whether a floor plan has been generated for each location
- **Role-Based Controls** - Edit and delete buttons visible to owners and admins only

### SMS/Navigation Links
- **Multi-Provider SMS** - Send SMS via Twilio, Plivo, Vonage/Nexmo, Telnyx, or AWS SNS
- **Navigation Services** - Support for Google Maps, Apple Maps, and Waze
- **SMS Configuration** - Web-based provider settings with encrypted credentials
- **E.164 Format** - Automatic phone number validation
- **Delivery Options** - Send via email, SMS, or both
- **Custom Messages** - Add personalized message to navigation links
- **Map Service Selection** - Choose specific service or send all navigation links

## 🚗 Service Vehicles Fleet Management

### Vehicle Tracking
- **Comprehensive Vehicle Details** - Make, model, year, VIN, license plate, color, purchase info
- **Vehicle Types** - Sedan, SUV, truck, van, cargo van, pickup truck
- **Status Management** - Active, inactive, in maintenance, retired
- **Condition Tracking** - Excellent, good, fair, poor, needs repair
- **Mileage Tracking** - Current odometer reading with automatic updates from fuel logs
- **GPS Location** - Store current vehicle coordinates (6 decimal precision), last update timestamp

### Maintenance Management
- **Service History** - Complete maintenance record tracking with service dates and mileage
- **Maintenance Types** - Oil change, tire rotation, brake service, inspection, tune-up, transmission, coolant, battery, repairs
- **Cost Tracking** - Labor costs, parts costs, total cost calculations
- **Recurring Schedules** - Set next due date and/or mileage for scheduled maintenance
- **Overdue Detection** - Automatic alerts for overdue maintenance based on date or mileage
- **Service Provider** - Track mechanic or service center details

### Fuel Tracking & Analytics
- **Fuel Purchases** - Log fuel purchases with date, mileage, gallons, cost per gallon
- **Automatic MPG Calculation** - Calculate miles per gallon based on previous fill-up
- **Cost Analysis** - Track total fuel costs, average cost per gallon
- **Efficiency Trends** - Monitor MPG trends over time (30-day average)
- **Station Tracking** - Record gas station locations for each fill-up

### Damage Reports & Insurance
- **Interactive Vehicle Diagrams** - SVG-based vehicle diagrams with clickable areas for damage reporting
- **Damage Severity** - Minor, moderate, major, total loss classifications
- **Photo Documentation** - Upload damage photos via attachment system
- **Repair Tracking** - Repair status (reported, assessed, in repair, completed, deferred)
- **Cost Estimates** - Track estimated and actual repair costs
- **Insurance Claims** - Claim number, insurance payout tracking
- **Repair Details** - Repair date, shop, notes
- **Condition Changes** - Track before/after condition status

### Inventory Management
- **Unified Inventory Page** - Single page with filter tabs: All, Vehicles (flat), By Vehicle, Shop — no separate menus
- **Per-Vehicle Inventory** - Track tools, cables, connectors, hardware, supplies stored in each vehicle
- **Shop/Warehouse Inventory** - Separate inventory pool for items stored at base location (not vehicle-specific)
- **Categories** - Organize by cables, tools, hardware, supplies, etc.
- **Quantity Tracking** - Current quantity with units (ea, ft, box, etc.)
- **Low Stock Alerts** - Set minimum quantity thresholds with high-contrast row highlighting
- **Value Tracking** - Unit cost and total value calculations
- **Storage Location** - Note where items are stored (vehicle compartment or shop shelf/cabinet)
- **Reorder Links** - Store reorder URLs (Amazon, eBay, etc.) with one-click cart button in all inventory tables
- **Reorder Quantity** - Track how many to order when restocking

### QR Code System
- **Auto-Generated QR Codes** - Every inventory item gets a unique QR code on creation (never changes)
- **Vehicle Items** - QR codes prefixed `INV-` linked to scan interface
- **Shop Items** - QR codes prefixed `SHOP-INV-` linked to shop scan interface
- **Scan-to-Edit** - Scanning a QR code opens a mobile-optimized interface with +/- quantity buttons, set quantity, and Full Edit link
- **QR Image Download** - Download PNG of any QR code from the item edit form
- **Global QR Print Sheet** - Print all inventory QR codes (vehicle + shop) on one page, filterable by vehicle
- **Print-Optimized Layout** - 4-column grid layout when printing for adhesive label sheets

### User Assignments & History
- **Assignment Management** - Assign vehicles to users/technicians
- **Assignment History** - Track full assignment history with dates
- **Mileage Attribution** - Record starting and ending mileage for each assignment
- **Duration Tracking** - Calculate assignment duration in days
- **Miles Driven** - Calculate miles driven during each assignment period
- **Active Status** - Identify currently assigned vehicles

### Insurance & Registration
- **Insurance Details** - Provider, policy number, premium amount
- **Expiration Tracking** - Insurance and registration expiration dates
- **Expiration Warnings** - 30-day advance warnings for expiring insurance/registration
- **Automatic Alerts** - Dashboard and webhook notifications for expiring documents

### Receipt Scanning & Expense Tracking
- **AI-Powered OCR** - Photograph or upload a receipt on any device; Claude vision API automatically extracts vendor, date, total amount, tax, expense category, and odometer reading
- **Mobile Camera Capture** - Receipt upload form opens rear camera directly on Android and iOS (no app required)
- **AI Confidence Indicator** - High / Medium / Low confidence banner prompts users to review uncertain extractions before saving
- **Duplicate Prevention** - SHA-256 image hash blocks the same receipt from being imported twice across any vehicle
- **Expense Categories** - Fuel, Maintenance, Repair, Insurance, Registration, Tolls/Parking, Cleaning/Detailing, Inspection, Other
- **Cost Summary Dashboard** - Per-category totals (Fuel, Maintenance, Repair) plus grand total shown as summary cards on the vehicle detail Receipts tab
- **Receipt Image Storage** - Original receipt image saved alongside the structured data record
- **Odometer Integration** - If receipt shows a mileage reading, it is extracted and stored for service history correlation

### Mobile Home Screen Shortcuts
- **Phone Shortcut button** on every vehicle's Receipts tab — shows a QR code, copyable URL, and Add to Home Screen instructions for Android and iOS
- **Per-vehicle QR code** — scanning opens Add Receipt directly for that vehicle; no navigation needed
- **PWA shortcuts** — long-pressing the Client St0r home screen icon shows "Scan Receipt" and "Vehicles" shortcuts (Android Chrome)
- **Quick Receipt page** (`/vehicles/receipts/quick/`) — vehicle picker landing page; auto-redirects if only one active vehicle

### Dashboard & Analytics
- **Fleet Statistics** - Total vehicles, active count, in maintenance, total mileage
- **Clickable Stats** - Navigate to filtered vehicle lists from dashboard cards
- **Recent Activity** - Recent fuel logs, maintenance, damage reports
- **Fleet Metrics** - Average mileage per vehicle, average MPG, total fuel costs
- **Alert System** - Insurance/registration expiration, maintenance due, low inventory

### Feature Toggle
- **Enable/Disable** - Toggle vehicles module on/off via system settings
- **Menu Integration** - Dynamic navigation menu based on feature status

## 📋 Workflows & Process Automation

### Workflow Management
- **Process Templates** - Create reusable workflow templates with sequential steps
- **Process Categories** - Organize by type (onboarding, offboarding, deployment, maintenance, incident, backup, security, change)
- **Global & Org Processes** - Superuser templates available to all organizations, or org-specific custom workflows
- **Tagging & States** - Tag workflows for organization, control visibility with published/archived states

### Execution & Tracking
- **One-Click Launch** - Prominent "Launch Workflow" button with automatic assignment to launcher
- **Execution Options** - Set due date, notes, PSA ticket linking, and note visibility (internal/public) at launch
- **Status Tracking** - Monitor Not Started, In Progress, Completed, Failed, or Cancelled workflows
- **Execution List View** - Complete history with advanced filtering by status, workflow, and assigned user
- **Visual Dashboard** - Color-coded status badges, progress bars, overdue warnings, and sortable columns
- **Interactive Checklist** - AJAX-powered stage completion with real-time progress updates
- **Stage Management** - Reorder stages, mark as required, add notes, set time estimates

### Audit Logging
- **Complete Activity Timeline** - Every action logged with user, timestamp, and IP address
- **Tracked Events** - Workflow launches, stage completions/uncompletions, status changes, notes, due dates, PSA updates
- **Timeline View** - Chronological activity feed grouped by date with color-coded events
- **Change History** - Old/new values stored in JSON, dual logging to workflow and system-wide audit logs

### PSA Ticket Integration
- **Ticket Linking** - Link workflows to PSA tickets at launch with automatic completion summaries
- **Note Visibility Control** - Choose public (customer-visible) or internal (staff-only) notes
- **Supported Platforms** - ITFlow, ConnectWise Manage, Syncro (more providers framework-ready)
- **Error Handling** - PSA failures don't block workflow completion

### Additional Features
- **Flowchart Generation** - Auto-generate draw.io diagrams with color-coded stages
- **Entity Linking** - Link knowledge base docs, passwords, secure notes, or assets to workflow stages
- **Quick Access** - View all linked entities directly from execution view

## 🌐 Network Hardware Integrations

### Supported Network Platforms

**3 Network Controller Integrations:**
- **UniFi** - Ubiquiti UniFi Network controller: auto-discover switches, APs, gateways, cameras; import as assets; configurable scheduled sync
- **Omada** - TP-Link Omada controller: auto-discover switches, APs, gateways, EAPs; session-based auth with CSRF; site-aware sync
- **Grandstream** - Grandstream UCM/GDMS: Bearer token auth; auto-discover wireless APs; import as assets with MAC/serial deduplication

### Integration Features
- **Asset Auto-Import** - Discovered devices imported as assets with name, type, serial number, MAC address, IP address, firmware version
- **Smart Deduplication** - Match existing assets by MAC address first, then serial number — updates instead of duplicating
- **Scheduled Auto-Sync** - Configurable sync interval (minutes); systemd timer runs sync_network_assets management command
- **On-Demand Sync** - Trigger manual sync from the Integrations page
- **Encrypted Credentials** - All API keys, tokens, and passwords stored with AES-256-GCM encryption
- **Asset Type Mapping** - Device types automatically mapped (switch, wireless_ap, gateway, camera, etc.)
- **Import Preview** - Review discovered devices before importing
- **Connection Testing** - Verify controller connectivity before saving

## 🎫 Native PSA / Service Desk

A complete in-house ticketing system, separate from the PSA *integrations* below (which mirror data from third-party PSAs).

### Ticketing & Service Desk
- **Tickets** - Auto-numbered `PSA-YYYY-NNNNNN`, queues, statuses (with `is_terminal` and `pauses_sla` flags), 5-tier priority (P1–P5), ticket types, impact × urgency
- **Comments** - Public + internal-only with audit; @mention parser auto-adds the user as a watcher and emails them
- **Attachments** - Per-ticket file uploads with internal-only flag
- **Watchers** - Per-user, per-ticket subscriptions for status/comment notifications
- **Canned Replies** - Reusable comment templates with variable substitution; tenant-scoped
- **Ticket merge** - Move comments + attachments to a target ticket and auto-close source as duplicate
- **Similar tickets** - Same-asset + Jaccard token-overlap detection on subject for recurring-issue spotting
- **Vault context** - Ticket detail surfaces the client's vault entries and lets staff jump to passwords inline

### SLA Engine
- **Per-priority response + resolution targets** in minutes from ticket creation
- **Per-contract SLA matrix override** — premium clients get tighter response/resolution targets per priority
- **Pause logic** - Statuses flagged `pauses_sla=True` (Waiting on Client / Vendor) suppress breach badges
- **Hygiene checks** - Pre-close warnings for missing resolution summary, time entries, etc.

### Time & Expenses
- **Timer + manual entries** - Start/stop on a ticket, billable flag, notes, auto-computed duration
- **Per-ticket expenses** - Reimbursable / billable expense rows with category (mileage, parts, software, subcontractor, shipping), receipt file upload, currency, billable total
- **Auto-tracked contract hours** - Time entries automatically increment `Contract.hours_used_minutes` on stop transitions

### Service Catalog
- **Templated tickets** - Pre-defined service requests (Password Reset, MFA Reset, New User, Termination, etc.) with structured fields
- **Field types** - text, email, date, number, textarea, select, checkbox; `{{key}}` substitution into subject/body
- **CRUD UI** - Admins create/edit catalog items inline

### Projects & Tasks
- **Projects** - Group tickets under a delivery effort; status (planning/active/on_hold/completed/cancelled), owner, billable flag, estimated hours, optional client_org
- **Project tasks/milestones** - Task breakdown with status, assignee, due date, milestone flag, parent-task hierarchy

### Recurring Tickets (Preventive Maintenance)
- **Schedules** - Daily/weekly/monthly/quarterly/yearly × interval, template subject + body, default queue/priority/type/assignee
- **Cron runner** - `psa_run_recurring_tickets` creates tickets and rolls `next_run_at` forward; catch-up cap of 50 prevents runaway after downtime

### Knowledge Base
- **Browse + search** - `/psa/kb/` searches `docs.Document` filtered to global KB articles
- **Per-ticket linking** - Many KB articles can be attached to one ticket via `TicketKBLink`

### Approvals
- **Generic manager-approval gate** for time / expense / quote / order / AI-action / change requests
- **Decide UI** - Approve/deny with comment; status + decided_at + decided_by atomically recorded

### Contracts
- **Types** - Block hours, retainer, managed services, per-incident
- **Allowance tracking** - `total_hours`, `hours_used_minutes` (auto-incremented), `hours_remaining`, hourly rate + overage rate
- **SLA matrix override** - Per-priority response/resolution overrides on a per-contract basis
- **Active-contract banner** on ticket detail showing usage + warnings when allowance is depleted

### Quotes / Estimates
- **Auto-numbered** - `Q-YYYY-NNNNN`, draft → sent → accepted/rejected/expired lifecycle
- **Line items** - Compact form: quantity × unit price, tax rate, auto-computed subtotal/tax/total, dynamic add/delete rows, live recompute as you type
- **Convert-to-ticket on accept** - Optionally creates a ticket on the client's organization scoped to the quote
- **Branded PDF** generation (ReportLab) with org logo header, From/Bill-to blocks, line items, totals, page footer with brand mark
- **Email to customer** with the PDF attached and the e-sign URL in the body; auto-flips draft → sent
- **Customer e-signature** at `/portal/quote/<token>/sign/` — no-login canvas signature pad. POST records signer name/email/title, IP, user-agent, base64 PNG, and auto-accepts the quote (creating the converted ticket)

### Invoices & Payments
- **Auto-numbered** - `INV-YYYY-NNNNN`, draft → sent → partial → paid → overdue → void
- **Compact form matching quotes** - Same density, dynamic line-item editor with live recompute, default tax rate + currency from `SystemSetting.psa_default_tax_rate` / `psa_default_currency`
- **Generate from ticket** — one button rolls a ticket's billable time entries (priced at active contract rate) + expenses into a draft invoice
- **Generate from charges** — bundle all uninvoiced charges + credits for a client into a single invoice
- **Payments** - Per-invoice with method (ACH/check/credit_card/wire/cash), reference, notes; auto-recomputes invoice `amount_paid` + status on save
- **Branded PDF** + email-to-customer modal
- **Push to accounting** - One-click push to QuickBooks Online or Xero (see Accounting Integrations)

### Client Account & Billing
- **Per-client account view** at `/psa/clients/<id>/account/` — net balance, outstanding (open invoices), available credits, uninvoiced charges, **0–30 / 31–60 / 61–90 / 90+ aging buckets**, recent invoices, payment history, and unbilled time + expenses ready to invoice
- **Charges** (`psa.Charge`) — direct line entries against a client account, independent of invoices. Supports one-time vs recurring (monthly/quarterly/yearly), `is_credit` (subtracts from balance), inline add form on the account view
- **Aging report** at `/psa/aging/` — cross-client outstanding balances bucketed by age past due_date with column totals
- **`psa.models.get_psa_balance(client_org)`** is the public helper that returns the same dict the views render

### Accounting Integrations (QuickBooks Online + Xero)
- **OAuth2 connections** (`integrations.AccountingConnection`) with encrypted client_id + client_secret + refresh_token + tenant/realm IDs in a single AES-encrypted JSON blob
- **QuickBooks Online provider** - Full OAuth2 with refresh-rotation; customer-by-name lookup with auto-create fallback (mapping cached on the connection); invoice push via `/v3/company/<realm>/invoice`; payment push via `/payment` with LinkedTxn
- **Xero provider** - OAuth2 with `offline_access`; tenant_id discovery via `/connections`; contact upsert; invoice push to `/api.xro/2.0/Invoices`; payment push to `/Payments`
- **Six other providers reserved** - FreshBooks, Wave, Zoho Books, Sage Business Cloud, etc. — provider types ready for future adapters

### Customer Portal
- **Stripped client-facing site** at `/portal/` — clients log in and see only their org's tickets where `client_can_view=True`
- **Per-org branding** *(v3.17.112)* — Portal navbar and login page show the client `Organization.logo` when one is set on the org row, falling back to the life-ring icon + org name. No new model fields required — uses the existing `Organization.logo` ImageField.
- **Submit + reply** - Clients post replies as public comments and can submit new tickets
- **Portal user invite flow** *(v3.17.106)* — Invite contacts to the client portal directly from the org page; Document.is_client_visible field controls which knowledge-base articles surface to portal users.
- **Internal-only filtering** - Internal comments and staff-only attachments are filtered at the queryset layer
- **Per-org opt-in** via `ClientPSASettings.portal_enabled`

### Vault Visibility for Portal Users *(v3.17.107)*
- **`Password.client_visible`** boolean gates whether a vault entry is exposed to the portal at all (default false)
- **Four access modes** via `Password.client_access_mode`:
  - `none` — never shown
  - `all_org` — every active member of the password's org sees it
  - `specific_users` — only users explicitly added to `Password.client_allowed_users`
  - `org_admin_managed` — same logic as `specific_users`, but the client's own org admin manages the list
- **Defence-in-depth** — `Password.visible_to_portal_user(user)` checks `Membership` even if a user is in the allowed-users list. Personal vault entries (`is_personal=True`) are never portal-visible regardless of mode.
- **Test coverage** — 9 unit tests in `psa.tests.PortalVaultRBACTests` cover every mode, the personal-vault carve-out, and the unauthenticated case.

### Process Workflows Embedded in PSA Tickets *(v3.17.105 → v3.17.120)*
Workflows (Process templates) and PSA tickets are now tightly coupled. A workflow is never a "free-floating execution" page — every running workflow has a parent ticket that owns its checklist + sign-off history.

**Three ways to attach a workflow:**
- **At ticket creation** *(v3.17.120)* — the `/psa/new/` form has an "Attach a workflow" picker. Pick a Process template; the new ticket opens with the embedded checklist already populated.
- **From an existing ticket** *(v3.17.105)* — "Launch workflow" button on the ticket detail page picks any active template and embeds it.
- **Run from the workflows page** *(v3.17.117)* — `/processes/` shows the templates list; clicking Run asks for a Client and creates a brand-new ticket titled `Workflow: <Process title>` with the workflow attached.

**On the ticket detail page:**
- **Inline stage checklist** *(v3.17.117)* — every stage shows as a list item with a checkbox toggle, title, description, and any linked entities (KB doc / vault password / asset / secure note).
- **AJAX sign-off** — click the checkbox to mark a stage complete; POSTs to `/processes/completion/<pk>/complete/` (or `/uncomplete/`), updates the icon, the line-through, and the live progress bar — no page reload.
- **Live progress bar** — `<percent>% · N stages` text + Bootstrap progress bar updates in place as stages flip.
- **Sign-off audit history** *(v3.17.118)* — collapsible "Sign-off history" disclosure under each workflow shows the last 25 audit-log events (stage_completed / stage_uncompleted / execution_created / execution_completed / cancelled / failed) with username, stage title, and time-ago. Coloured icons per action.
- **Full audit log** — "View full audit log →" link goes to `/processes/execution/<pk>/audit-log/` for the unabridged history.

**Backend:**
- **`ProcessExecution.native_psa_ticket`** FK to `psa.Ticket` (in addition to the older `psa_ticket` FK for third-party PSAs).
- **Reverse query** — `ticket.process_executions.all()` lists every workflow run against the ticket.
- **`ProcessExecutionAuditLog.log_action(execution, action_type, user, description, stage=None, request=None)`** writes one row per stage event with IP/user-agent metadata and stores the username + stage_title for history (so the audit row survives even if the user or stage is later renamed/deleted).
- **Eager-loaded** — the ticket detail view prefetches `stage_completions` (with stage + linked entities + completed_by) and `audit_logs` (last 25, with user + stage) in two `Prefetch()` calls, no N+1.
- **Legacy `/processes/execution/<pk>/`** — auto-redirects to the linked ticket if `native_psa_ticket_id` is set; superusers can still hit the old page via `?legacy=1`.

### Workflow Templates Page *(v3.17.117)*
- **`/processes/`** — CRUD + Run page for Process templates. List, create, edit, archive, delete.
- **Run button** — opens a form asking for a Client; on submit creates a PSA ticket and a `ProcessExecution` linked to it, then redirects to the ticket.
- **Operations → Workflows** in the top menu is the entry point. Same destination as the dashboard "Run Workflow" Quick Action tile.
- **Audit-log access** — superusers can still hit `/processes/executions/` for orphan/legacy executions; non-superusers don't see the link.

### Email-to-Ticket
- **IMAP poller** - `psa_poll_email` management command (cron every 5 min)
- **Reply threading** - Subject regex captures ticket number (`PSA-YYYY-NNNNNN`); inbound emails on existing tickets append as public comments instead of creating new tickets
- **Encrypted password storage** - Same vault-encryption as RMM/integration credentials
- **Marks UNSEEN as Seen** to avoid double-processing

### Workflow Rules Engine
- **Trigger events** - `ticket_created`, `ticket_updated`, `status_changed`, `comment_added`
- **MSP-wide vs client-scoped** *(v3.17.111)* — `WorkflowRule.organization` is nullable. NULL = applies to every ticket, regardless of client. Set to a specific org = scoped to that client only. Engine queries `Q(organization__isnull=True) | Q(organization=ticket.organization)` so both fire correctly.
- **Visual rule builder** *(v3.17.112)* — Click-to-add condition + action rows in the rule form. Field dropdown (priority / queue / status / ticket_type / is_unassigned / is_paused / subject_contains) renders the matching value picker (priority codes, queue names, status slugs, etc.). Existing rules with combinators (`any`/`all`/`__in`/`__not`) auto-fall-back to a locked raw-JSON mode so complex rules stay editable.
- **Condition DSL** - JSON: `{"priority": "P1"}`, `{"subject_contains": "outage"}`, `{"is_unassigned": true}`, `{"all": [...]}`, `{"any": [...]}`, `__in` / `__not` operators — still available under "Advanced raw JSON" for power users
- **Actions** - `set_priority`, `set_queue`, `assign_to`, `add_watcher`, `add_internal_note`, `add_tag`
- **Per-rule audit** - `last_fired_at`, `fire_count`, `last_error` so misconfigured rules surface visibly without blocking ticket save
- **Sample workflows** - `psa_seed_sample_workflows` installs starter rules (P1 escalation, sales-inquiry follow-up, new-user onboarding, termination security routing, outage keyword detection, unassigned triage, client-reply tagging)

### Dispatch Board
- **7-day grid** - Columns = days, rows = techs; tickets bucketed by their due date
- **Drag-and-drop reassignment** *(v3.17.112)* — Drag a ticket card from one technician's column to another to reassign. Optimistic UI with Bootstrap toast feedback; failed drags roll the card back and reload. Backed by `POST /psa/dispatch/assign/` (JSON, audit-logged exactly like a manual edit).
- **Overdue panel** - Surfaces overdue open tickets at the top regardless of date
- **Unassigned row** - Visible at the top so unassigned work isn't missed

### Distributor Integrations (Workstream 8)
- **Ingram Micro Xvantage** - OAuth2 client-credentials, catalog, price + availability, order placement (gated by `sync_enabled`), HMAC-SHA256 webhook verification (`X-Ingram-Signature`)
- **Pax8** - SaaS / cloud-software distributor; OAuth2, `/v1/products` catalog, product pricing (price bands), order placement, HMAC webhook (`X-Pax8-Signature`)
- **TD Synnex** - Stellr API; OAuth2, price-and-availability, order placement, HMAC webhook (`X-TDS-Signature`)
- **Reserved choices** - D&H, ScanSource, QBS, Westcoast (provider types ready for future adapters)
- **Per-connection encrypted credentials + webhook secret**, opaque webhook URL token, ad-hoc pricing lookup UI, connection test endpoint
- **`sync_distributors`** management command for cron health probes

### AI-Assisted Service Desk (Workstream 10)
- **Suggested replies** - Generates a draft reply, surfaced for human approval
- **Suggested actions** - Risk-tiered actions (low / medium / high) with separate approve-and-apply flow
- **Guardrails** - Subject blocklist, per-user rate limit, daily token quotas, NFKC + control-char/ZWJ input sanitization, prompt-injection envelope, output content filter, action allowlist
- **Granular RoleTemplate permissions** - 11 booleans (view, send_low_risk, send_high_risk, approve_reply, apply_low_risk, apply_high_risk, approve_action, run_script, create_workflow, billing, admin)
- **Tenant isolation** - No vault secrets ever reach the model context; queryset/view/service-layer enforcement; "no-secrets-leak" test plants a sentinel and asserts it never appears in any AI artifact

## 🔌 PSA Integrations

### Supported PSA Platforms
**8 Fully Implemented Providers:**
- **ConnectWise Manage** - Companies, contacts, tickets, projects, agreements
- **Autotask PSA** - Companies, contacts, tickets, projects, agreements
- **HaloPSA** - Companies, contacts, tickets with OAuth2
- **Kaseya BMS** - Companies, contacts, tickets, projects, agreements
- **Syncro** - Customers, contacts, tickets
- **Freshservice** - Departments, requesters, tickets
- **Zendesk** - Organizations, users, tickets
- **ITFlow** - Open-source PSA with full API support

### Integration Features
- **Automated Sync** - Scheduled synchronization via systemd timers
- **Manual Sync** - On-demand sync with force option and test connection
- **Field Mapping** - Flexible field mapping with conflict resolution
- **Error Handling** - Comprehensive error logging and sync history

### Organization Auto-Import
- **Auto-Create Organizations** - Automatically create Client St0r organizations from PSA companies
- **Smart Duplicate Prevention** - Detects existing organizations by external ID
- **Configurable Settings** - Enable/disable per connection, set active/inactive state, add custom name prefixes
- **External ID Tracking** - Links organizations to PSA companies for update sync

## 🖥️ RMM Integrations

### Supported RMM Platforms
**Complete Infrastructure with 5 Provider Frameworks:**
- **Tactical RMM** (Fully Implemented) - Device/site/agent management, real-time monitoring, software inventory, WebSocket updates
- **NinjaOne** (Infrastructure Ready) - OAuth 2.0 authentication, device management endpoints
- **Datto RMM** (Infrastructure Ready) - Device inventory sync, component tracking, alerts
- **Atera** (Infrastructure Ready) - Agent management, ticket integration, monitoring
- **ConnectWise Automate** (Infrastructure Ready) - Computer management, location tracking, script execution

### Integration Features
- **Automated Device Sync** - Scheduled synchronization via systemd timers with configurable intervals
- **Device Location Mapping** - Display RMM devices with location data on interactive map with toggle controls, color-coded status markers, and device details
- **Asset Mapping** - Automatic linking of RMM devices to asset records by serial number/hostname
- **Alert Management** - Import and track RMM alerts with severity levels and status
- **Software Inventory** - Track installed software per device with version tracking
- **Online Status Tracking** - Real-time device connectivity and last-seen timestamps
- **Encrypted Credentials** - All API keys and tokens encrypted with AES-256-GCM
- **Provider Abstraction** - Unified interface across all RMM platforms

### Organization Auto-Import
- **Auto-Create Organizations** - Automatically create Client St0r organizations from RMM sites/clients
- **Smart Duplicate Prevention** - Detects existing organizations by external ID
- **Configurable Settings** - Enable/disable per connection, set active/inactive state, add custom name prefixes
- **External ID Tracking** - Links organizations to RMM sites for update sync

## 🔔 Notifications & Alerts
- **Alert Types** - Website downtime, SSL expiration, domain expiration, password expiration
- **Notification Channels** - Email (SMTP), webhooks, in-app dashboard notifications

## 📊 Reporting & Analytics
- **Audit Reports** - Activity statistics, security events, resource usage with CSV/JSON export
- **System Reports** - Organization statistics, user activity, integration status, system health metrics
- **Feature Toggle** - Enable/disable Reports & Analytics per organization via Feature Toggles

## 🔧 Administration
- **System Settings** - Site configuration, security settings, SMTP with encrypted credentials, maintenance mode
- **Feature Toggles** - Enable/disable features per organization (Reports, Asset Management, Password Vault, Documentation, etc.)
- **Database Management** - Optimize, analyze, backup, and migration tools
- **User Management** - Create users with roles, bulk operations, suspension, password reset, 2FA management

## 🔗 API
- **REST API** - Full CRUD for all resources with API keys (HMAC-SHA256) or session authentication
- **Endpoints** - Organizations, users, assets, passwords, documents, contacts, PSA integrations, monitors, audit logs
- **Features** - Pagination, filtering, sorting, field selection, bulk operations, rate limiting

## 📱 Mobile & Install

### Add to Home Screen / PWA Install
- **Install Page** (`/core/install/`) - Dedicated, shareable page with everything needed to install Client St0r on any device; no login required so you can send the link to staff
- **QR Code** - Automatically generated QR code of your server URL; scan with any phone camera to open the site instantly
- **Downloadable QR PNG** - Download the QR code image to print and stick on a desk, wall, or whiteboard for staff to scan
- **One-tap Install (Android / Desktop)** - Install button appears automatically on Android Chrome and desktop Chrome/Edge when the browser supports PWA install; one tap adds the app icon
- **iPhone / iPad (Safari)** - Step-by-step instructions: Share button → Add to Home Screen; works without any browser prompt since iOS requires manual flow
- **PWA Shortcuts** - On Android, long-pressing the installed Client St0r icon shows shortcuts: **Scan Receipt** and **Vehicles**
- **How to find it** - Profile dropdown (top-right avatar) → *Install App / Add to Home Screen*

### Mobile-Optimised Pages
- **Receipt scanning form** - Camera capture (`capture="environment"`) opens rear camera on mobile; AI Extract button fills fields automatically
- **Vehicle picker** (`/vehicles/receipts/quick/`) - Fast mobile landing page for choosing a vehicle before scanning a receipt; auto-redirects when only one vehicle exists
- **QR scan interfaces** - Inventory scan, shop scan, and receipt capture pages all designed for one-handed mobile use
- **Responsive layout** - Bootstrap 5 grid; all tables, forms, and dashboards adapt to phone screen widths

## 📱 User Interface
- **Design** - Bootstrap 5, dark mode, mobile responsive, DataTables, tooltips, progress indicators
- **Navigation** - Breadcrumbs, global search, recent items, favorites
- **Accessibility** - Keyboard navigation, ARIA labels, high contrast, semantic HTML

## 🛠️ Developer Features
- **Extensibility** - Django apps, plugin system, custom fields, hooks, customizable templates
- **Development Tools** - Management commands, seed data, test suite, debug toolbar, API docs

## 🔄 Data Management

### Data Import
- **Universal CSV Import** - Import any data from CSV or spreadsheet files with a visual field mapper
- **Field Mapper** - Step-by-step import: select target model (Assets, Passwords, Contacts, Documents), then map each CSV column to a destination field
- **Preview** - See the first 5 rows of your data before mapping to identify columns
- **Auto-Suggestion** - Column names are automatically matched to likely target fields
- **Hudu Import** - Direct import from Hudu exports (assets, passwords, contacts, documents)
- **IT Glue Import** - Direct import from IT Glue exports
- **MagicPlan Import** - Floor plan import from MagicPlan exports
- **Import History** - Track all import jobs with status, record counts, and error details
- **Source Tracking** - Each imported record tagged with source platform

### Export & Backup
- **CSV/JSON Export** - Export assets, audit logs, and reports
- **Encrypted Backups** - Automated encrypted backup with configurable retention
- **One-Click Restore** - Restore from backup via web interface
- **Data Integrity** - Comprehensive validation, database constraints, ACID transactions, rollback

## 📊 Financial Reporting + BI *(Phase 3 — v3.17.139→v3.17.143)*

### Canonical query layer
- **`reports/queries.py`** — single source of truth for revenue / hours / costs / margin queries.
- Functions: `revenue_by_client`, `hours_minutes_by_client`, `hours_minutes_by_tech`, `cost_estimate_by_client`, `profitability_by_client / by_tech / by_contract / by_project`, `effective_hourly_rate_by_client / by_tech`, `revenue_leakage`, `sla_trend_by_priority / by_client`, `margin_analytics_by_service_line`, `hours_minutes_by_contract / by_project`, `revenue_by_contract / by_project`.
- All take `(start_date, end_date, organization=None)` and return list-of-dicts (no querysets) so JSON / CSV export and template rendering both work.
- Uses **`resourcing.TechCostRate`** (effective-dated $/hr per tech) for accurate cost rolls — historical reports stay accurate after a raise.

### Profitability reports
- **By client** *(v3.17.139)* — `/reports/psa/profitability-by-client/`. Date-range picker, summary card (revenue / cost / margin / margin %), sortable table, color-coded margin column, CSV export.
- **By tech** *(v3.17.140)* — same shape; adds utilization %.
- **By contract** *(v3.17.140)* — uses `Invoice.source_contract` FK; adds bundled subscriptions.
- **By project** *(v3.17.140)* — uses `Invoice.source_ticket__project` relationship.

### Revenue + leakage analysis
- **Effective hourly rate** *(v3.17.141)* — tabbed By Client / By Tech. Per-tech version shows **realization %** (effective_rate ÷ cost_rate × 100; target ≥ 200%).
- **Revenue leakage** *(v3.17.141)* — three categories on one page:
  1. Stale unbilled time — billable `TicketTimeEntry` rows ≥ N days old not linked to any non-void invoice (strict invoice-link check via `InvoiceLineItem.source='time'`)
  2. Expired contract blocks — paid-for hours never used
  3. Stuck draft invoices — drafts older than 14 days with deep-link "Open invoice" buttons
- Grand total at the top + per-section subtotals + single combined CSV export.

### SLA + margin analytics
- **SLA trend report** *(v3.17.143)* — `/reports/psa/sla-trends/`. Two stacked Chart.js line charts (response + resolution breach % per priority over time), bucketed day/week/month. Top-N worst-clients side panel.
- **Margin analytics by service line** *(v3.17.143)* — tabbed by `ticket_type` / `closure_category` / `queue`. Bar chart + sortable table.

### Custom dashboards with widgets *(v3.17.142)*
- Per-org or global dashboards (`reports.Dashboard`).
- **12 starter widgets** in `reports/widget_sources.py` registry:
  - Metric: revenue this period, open ticket count, SLA-overdue count, unbilled hours at risk, active techs, avg time-to-resolve
  - Table: top clients by revenue, tickets by priority, my assigned tickets
  - Chart: revenue trend bar, tickets-opened line, billable-vs-nonbillable pie
  - Plus: SLA breach trend 30d (chart_line)
- Widget CRUD: per-dashboard "Add widget" button → form with data-source select + title.
- Chart.js 4.4.1 (CDN, conditionally loaded only if a chart widget is present).
- **Seeded "MSP Overview" global dashboard** with all 12 starter widgets — runs on `Apply` via `seed_default_dashboard` mgmt command.
- Bad widgets render an inline error chip — never crash the whole dashboard.

## 🧑‍💼 Resource Management *(Phase 2 — v3.17.132→v3.17.138)*

### Skills, certifications, working hours *(v3.17.132)*
- **`UserSkill`** — proficiency tiers (beginner / intermediate / advanced / expert), years of experience, notes.
- **`UserCertification`** — issuer, credential ID, issued/expires dates, verification URL, attachment upload. `is_expired` and `expires_soon` (within 60 days) flags.
- **`WorkingHours`** — per user, per weekday, multiple windows allowed (split shifts). Times in user's profile timezone.
- **`/resourcing/me/`** — three-card self-service profile page.
- **`/resourcing/roster/`** — staff-only view: every internal user with skill counts, cert counts, "working now" indicator (green/grey dot), expiring-cert warnings.
- **`UserProfile.is_working_now()`** helper — used by capacity reporting + GPS off-shift suppression (Phase 8.5).

### PTO + holidays + billable targets *(v3.17.137)*
- **`Holiday`** — org-scoped or global, recurring-yearly flag, `is_holiday(date, org)` classmethod.
- **`LeaveRequest`** — 8 leave types (vacation / sick / personal / bereavement / jury / parental / unpaid / other); pending → approved/denied workflow with approver, decided_at, decision_note. Half-day flag. `total_days` property. `is_user_on_leave(user, date)` helper.
- **`BillableTarget`** — per-tech weekly hours goal (default 32h/wk).
- Pages: `/resourcing/leave/` (my requests), `/resourcing/leave/approvals/` (staff queue), `/resourcing/holidays/` (admin).
- **`working_days_in_period(user, start, end, org)`** subtracts WorkingHours gaps + holidays + approved leave. Used by capacity reporting and GPS off-shift suppression (Phase 8.5).
- Audit-logged: every leave decision.

### Tech cost rates *(v3.17.140)*
- **`TechCostRate`** — effective-dated loaded $/hr per tech.
- **`rate_for(user, target_date)`** — picks the most-recent `effective_from <= target_date`. Falls back to `DEFAULT_LOADED_RATE = $60/hr`.
- Cost-rate management UI at `/resourcing/cost-rates/`.

### Capacity report + skill ranking *(v3.17.138)*
- **Capacity report** at `/resourcing/capacity/` — staff/superuser. Per-tech target / scheduled / actual hours + utilization %; window: 1 / 2 / 4 / 8 / 12 weeks.
- Color-coded utilization (red <80%, amber 80-95%, green 95-110%, blue >110%).
- **Skill ranking** on the dispatch board — per-card "Suggest" lightbulb popover ranks candidate techs by:
  - +30 per matching `UserSkill` keyword in subject/description
  - +20 client-org membership
  - +15 on-shift now (`UserProfile.is_working_now()`)
  - −50 approved `LeaveRequest` covering today
  - −30 if already 5+ open tickets assigned

## 🔐 AI Suggestions on tickets *(v3.17.125)*

Per-ticket "AI Suggestions" button surfaces handling guidance without acting on the ticket.

- **Read-only advisory output** — not a reply to send, not an action to apply. Renders as markdown with an unmissable amber warning banner.
- **Reuses existing AI guardrails** from `psa_ai/services/guardrails.py`: subject blocklist, per-user rate limit (10/hr), org token quota, NFKC + ZWJ input sanitization, prompt-injection envelope, vault context **excluded** (no-secrets-leak test still green), tenant isolation at queryset + service layer.
- **`AISuggestion(kind='triage')`** with `risk_level='low'` (advisory only — nothing is applied).
- **`RoleTemplate.psa_ai_request_triage`** boolean (default True for all tech roles).
- **Mark as helpful / Reject** buttons write to `AIActionLog` for feedback.
- Confidence indicator + model name + generated time-ago shown on each suggestion.

## 🛡️ Compliance Frameworks & Recertification *(Phase 41 — v3.17.435→v3.17.444)*

Per-organization compliance attestation with seeded control catalogs, branded customer reports, and monthly recertification reminders.

### Frameworks
- **PCI-DSS v4.0** *(seeded v3.17.437)* — 12 categories, 38 control items with real PCI-DSS v4.0 control numbers (1.2.1, 2.2.7, 3.3.1, 4.2.1, 5.2.1, 6.3.3, 7.2.4, 8.4.2, 9.4.7, 10.4.1, 11.3.2, 12.10.1, …).
- **HIPAA Security Rule** *(seeded v3.17.438)* — Administrative / Physical / Technical Safeguards, 33 control items keyed to 45 CFR 164.308 / 164.310 / 164.312 with subsection refs.
- **Idempotent seeders** — `python manage.py seed_pci_dss` and `seed_hipaa` use `update_or_create((framework, slug))` so re-running never duplicates rows.

### Per-organization workflow
- **Org-scoped enrollment** *(v3.17.439)* — `/compliance/organizations/<id>/`. Each framework appears as a card with progress bar, status counts (compliant / partial / non-compliant / N/A / unanswered), and an "Enroll" CTA when not yet active.
- **Attestation checklist** *(v3.17.440)* — `/compliance/organizations/<id>/<framework>/`. Per-control row with status dropdown (5 states), notes textarea, evidence URL field, and a `last_reviewed_at` / reviewer audit stamp. Color-coded left border (green compliant / orange partial / red non-compliant / grey N/A or unanswered).
- **Customer-facing PDF report** *(v3.17.441)* — `/compliance/organizations/<id>/<framework>/report.pdf`. Branded ReportLab output via `reports.pdf_export.render_pdf` with summary card (percent compliant + counts), per-category sections, evidence link footnotes, and last-reviewed timestamps.

### Monthly recertification reminders
- **Cron job** *(v3.17.442)* — `python manage.py send_compliance_recertifications` runs daily; idempotent + 7-day dedup via `RecertificationReminder` table so a flapping cron can't spam.
- **Recipient resolution** — `enrollment.notify_email` (override) → owner/admin Membership email → `DEFAULT_FROM_EMAIL`. `--dry-run` flag for testing.
- **Per-enrollment settings** *(v3.17.443)* — toggle reminders on/off, choose interval (Monthly / Bi-monthly / Quarterly / Semi-annual / Annual), set notify-email override. **Mark Recertified Now** button stamps `last_recertified_at = now` and resets the next reminder window.

### Auth + RBAC
- **`_user_can_access_pack(user, org)`** — superuser OR is_staff OR Membership(owner/admin). Same gate covers the dashboard, checklist, attestation save, PDF download, and recertification settings — no read-only or editor leak.

### Data model
- `ComplianceFramework`, `ComplianceCategory`, `ComplianceCheckItem` — global catalog (seeded once).
- `OrganizationCompliance` — per-org enrollment with recertification settings + computed properties (`recertification_due_at`, `days_until_recertification`, `status_counts()`, `percent_compliant()`).
- `OrganizationComplianceItem` — per-org-per-control attestation row.
- `RecertificationReminder` — audit log of reminder emails sent (used for dedup).

### Evidence packs *(Phase 39 — earlier)*
- **`/compliance/organizations/<id>/evidence-pack/`** — generates a single ZIP with attestations, evidence links, audit history, and a manifest for SOC2 / ISO27001 / customer-due-diligence requests.

## 📱 Native Mobile Apps *(Phase 8 — v3.17.346→v3.17.444)*

Expo + React Native + TypeScript app for iOS + Android, sharing the web app's session token via the dedicated `/api/mobile/v1/` DRF surface.

### Six top-level navigation areas *(v3.17.445)*
The mobile app exposes only six primary screens; everything else is reachable as a sub-route via deep-link or the Operations hub.

| # | Tile | Maps to |
|---|------|---------|
| 1 | **Dashboard** | `/dashboard` — timeclock card, KPI tiles, recent tickets/assets, recent alerts |
| 2 | **Assets** | `/assets` — list + detail with linked org, IP, type |
| 3 | **Vault** | `/vault` — encrypted credential search and reveal |
| 4 | **Docs** | `/kb` — knowledge base browser with markdown rendering |
| 5 | **PSA** | `/tickets` — list + detail + new-ticket flow |
| 6 | **Operations** | `/operations` — Timeclock / Monitoring / Security / Settings hub |

### Backend mobile API
- **`/api/mobile/v1/`** under DRF `TokenAuthentication` with throttle classes per endpoint.
- Endpoints: `auth/login`, `auth/mfa`, `auth/logout`, `auth/me`, `auth/refresh`, `dashboard/`, `organizations/`, `assets/`, `tickets/`, `kb/`, `locations/` (GPS ping), `timeclock/clock-in`, `timeclock/clock-out`, `timeclock/me/`, `active-ticket/`.
- **Tenant scoping** in `api_mobile/scoping.py` — every list endpoint applies the user's org membership filter; superusers see all.

### Build & sign infrastructure
- **`local_apps/play_publish/`** (gitignored, local-only) — admin web UI at `/play_publish/` for keystore generation, AAB build, AAB upload to Play Console, and per-app status tracking.
- **`build-aab.sh`** — enforces canonical package name `com.clientstor.mspreboot` + auto-derives Android `versionCode` from `config/version.py` (`major × 1_000_000 + minor × 10_000 + patch`). Targets **Android API 35** (SDK 35 + build-tools 35.0.0) per Play Console policy. R8 minify + resource-shrink enabled in release builds; `mapping.txt` captured next to the AAB.
- **`upload-aab.py`** — Google Play Developer API v3 (`google-api-python-client`); resumable AAB upload, proguard `mapping.txt` upload via `androidpublisher.deobfuscationfiles.upload`, track assignment, edit commit. Replaces fastlane (no ruby toolchain).

## 🚀 Performance & Deployment
- **Optimization** - Database indexing, query optimization, caching, lazy loading, pagination
- **Scale** - Vertical scale on a single host; database indexing and query optimization keep large asset and ticket sets responsive. Clustered / multi-node deployment is out of scope.
- **Installation** - One-command install (`bash install.sh`), `docker compose up -d` Docker / Compose path (Phase 42 — v3.17.490), systemd integration, Nginx config
- **Maintenance** - Zero-downtime updates, automated backups, log rotation, health checks (dedicated `/health/` endpoint as of v3.17.490)

### Docker / containerized deployment *(Phase 42 — v3.17.490)*
- **`Dockerfile`** — multi-stage Python 3.12 slim build; non-root `clientst0r` user (uid 1000); HEALTHCHECK against `/health/`.
- **`docker-compose.yml`** — `app` + MariaDB 10.11 `db` by default; optional Nginx (`--profile proxy`) and Redis (`--profile cache`). Required env vars enforced with `${VAR:?...}` so misconfiguration fails loudly. Named volumes `clientst0r-db-data` / `clientst0r-media` / `clientst0r-static` / `clientst0r-uploads` survive `docker compose down`.
- **`docker-compose.dev.yml`** — source bind-mount + `gunicorn --reload` + SQLite default for fast local iteration.
- **`docker-entrypoint.sh`** — DB readiness wait (skipped for `DB_ENGINE=sqlite3`), `migrate`, `collectstatic`, optional `DJANGO_SUPERUSER_*` bootstrap.
- **GitHub Container Registry** — `.github/workflows/docker-image.yml` builds on every PR and publishes `ghcr.io/agit8or1/clientst0r:latest` + semver tags on push to `main` / `v*`. Buildx GHA layer cache. `linux/amd64` (ARM line commented in).
- **Operator UX** — `Makefile` wraps `docker compose` with one-word targets: `make docker-up` / `docker-logs` / `docker-shell` / `docker-migrate` / `docker-createsuperuser` / `dev-up` / `backup` / `restore`.
- **Documentation** — `.env.example` covers every supported variable with inline guidance; [`docs/docker.md`](docs/docker.md) covers quick start, profiles, persistent volumes, backups, upgrades, dev mode, and troubleshooting (race conditions, lost `APP_MASTER_KEY`, ARM hosts).

---

## 🏗️ Architecture

### Technology stack

| Layer | What it runs on |
|---|---|
| Framework | Django 6.0 |
| API | Django REST Framework 3.17, optional GraphQL |
| Database | MariaDB 10.11 (the Compose default); MySQL 8.0+ also supported, SQLite for local development |
| Application server | Gunicorn, behind Nginx |
| Authentication | `django-two-factor-auth` (TOTP), optional Azure AD / Entra ID SSO and LDAP |
| Encryption | Python `cryptography` — AES-GCM for secrets at rest |
| Password hashing | Argon2 |
| Frontend | Bootstrap 5 and vanilla JavaScript, no build step |
| Scheduling | systemd timers (no Redis or Celery required) |

### Design decisions

- **Two install paths, both first-class** — native systemd install via `install.sh`, or
  `docker compose up -d`. Neither is a wrapper around the other.
- **No broker, no worker fleet** — recurring work runs on systemd timers. Redis is optional
  and only used if you point `CACHES` at it.
- **Single server by design** — one VM or one container host per MSP. There is no clustered
  or multi-node deployment story.
- **Self-hosted only** — no hosted service, no phone-home. AI-assisted features are gated
  behind `psa_ai_enabled` and call nothing until you enable them and supply a key.
- **API-driven** — REST and GraphQL endpoints back the mobile app, the browser extension
  and third-party integrations.

---

**All features developed with assistance from Luna the GSD 🐕**
