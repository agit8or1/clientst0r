# Client St0r Features

Complete feature documentation for Client St0r - Self-hosted IT documentation platform.

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

## 🏢 Multi-Tenancy & RBAC

### Organization Management
- **Complete Data Isolation** - Organization-based data separation
- **Unlimited Organizations** - Support for multiple tenants
- **Custom Branding** - Per-organization customization
- **Flexible Structure** - Hierarchical organization support

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
- **Location Tracking** - Manage physical locations for organizations
- **Address Management** - Full address details with geocoding support
- **Coordinates Support** - Latitude/longitude for precise positioning
- **Location Types** - Headquarters, branch office, data center, remote site, customer site
- **Status Tracking** - Active, planned, inactive, closed
- **Primary Location** - Designate headquarters

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

### Vehicle Inventory
- **Per-Vehicle Inventory** - Track tools, cables, connectors, hardware, supplies stored in each vehicle
- **Categories** - Organize by cables, tools, hardware, supplies, etc.
- **Quantity Tracking** - Current quantity with units (ea, ft, box, etc.)
- **Low Stock Alerts** - Set minimum quantity thresholds for automated alerts
- **Value Tracking** - Unit cost and total value calculations
- **Storage Location** - Note where items are stored within vehicle (toolbox, compartment, etc.)

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

## 📱 User Interface
- **Design** - Bootstrap 5, dark mode, mobile responsive, DataTables, tooltips, progress indicators
- **Navigation** - Breadcrumbs, global search, recent items, favorites
- **Accessibility** - Keyboard navigation, ARIA labels, high contrast, semantic HTML

## 🛠️ Developer Features
- **Extensibility** - Django apps, plugin system, custom fields, hooks, customizable templates
- **Development Tools** - Management commands, seed data, test suite, debug toolbar, API docs

## 🔄 Data Management
- **Import/Export** - CSV import, JSON export, backup/restore, migration tools from other platforms
- **Data Integrity** - Comprehensive validation, database constraints, ACID transactions, rollback

## 🚀 Performance & Deployment
- **Optimization** - Database indexing, query optimization, caching, lazy loading, pagination
- **Scalability** - Horizontal scaling, database replication, CDN integration, minified assets
- **Installation** - One-command install, Docker support, systemd integration, Nginx config
- **Maintenance** - Zero-downtime updates, automated backups, log rotation, health checks

---

**All features developed with assistance from Luna the GSD 🐕**
