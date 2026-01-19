# HuduGlue 🐕

[![Version 2.24.159](https://img.shields.io/badge/version-2.24.159-brightgreen)](https://github.com/agit8or1/huduglue)
[![Production Ready](https://img.shields.io/badge/status-production%20ready-green)](https://github.com/agit8or1/huduglue)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Django 6.0](https://img.shields.io/badge/django-6.0-blue)](https://www.djangoproject.com/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![Known Vulnerabilities](https://snyk.io/test/github/agit8or1/huduglue/badge.svg)](https://snyk.io/test/github/agit8or1/huduglue)
[![Security Monitoring](https://img.shields.io/badge/security-Snyk%20%7C%20HaveIBeenPwned-blue)](https://github.com/agit8or1/huduglue)

A complete, self-hosted IT documentation platform designed for Managed Service Providers (MSPs) and IT departments. Built with Django 6, HuduGlue provides secure asset management, encrypted password vault, knowledge base, PSA integrations, and comprehensive monitoring tools.

## 📸 Screenshots

*All screenshots include demo data and are watermarked. Random background feature enabled. [View full gallery →](docs/screenshots/)*

<table>
<tr>
<td width="50%">

### 🏠 Dashboard & Quick Access
![Dashboard](docs/screenshots/dashboard.png)
![Quick Add](docs/screenshots/quick-add.png)

</td>
<td width="50%">

### 📦 Asset Management
![Assets](docs/screenshots/assets-list.png)
![Racks](docs/screenshots/racks.png)

</td>
</tr>
<tr>
<td width="50%">

### 🔐 Password Vault & Security
![Password Vault](docs/screenshots/password-vault.png)
![Personal Vault](docs/screenshots/personal-vault.png)

</td>
<td width="50%">

### 📚 Documentation & Knowledge Base
![Knowledge Base](docs/screenshots/knowledge-base.png)
![Diagrams](docs/screenshots/diagrams.png)

</td>
</tr>
<tr>
<td width="50%">

### 🔒 Security Dashboard
![Security Dashboard](docs/screenshots/security-dashboard.png)
![Vulnerability Scans](docs/screenshots/vulnerability-scans.png)

</td>
<td width="50%">

### 🌐 Monitoring
![Website Monitors](docs/screenshots/website-monitors.png)
![Expirations](docs/screenshots/expirations.png)

</td>
</tr>
<tr>
<td width="50%">

### ⚙️ System Management
![System Updates](docs/screenshots/system-updates.png)
![System Status](docs/screenshots/system-status.png)

</td>
<td width="50%">

### 🏢 Multi-Tenancy & Access
![Organizations](docs/screenshots/organizations.png)
![Access Management](docs/screenshots/access-management.png)

</td>
</tr>
</table>

<details>
<summary><strong>📋 View All Screenshots (34 total)</strong></summary>

### Core Features
- [Dashboard](docs/screenshots/dashboard.png) - Main dashboard with random backgrounds
- [Quick Add](docs/screenshots/quick-add.png) - Fast creation menu for assets, passwords, documents
- [About](docs/screenshots/about-page.png) - System information and version details
- [Profile](docs/screenshots/profile.png) - User profile and settings
- [Favorites](docs/screenshots/favorites.png) - Quick access to favorited items

### Asset Management
- [Assets List](docs/screenshots/assets-list.png) - Comprehensive asset tracking
- [Racks](docs/screenshots/racks.png) - Rack management with U-space tracking
- [Network Closets](docs/screenshots/network-closets.png) - Network infrastructure management
- [IPAM/Subnets](docs/screenshots/ipam-subnets.png) - IP address management
- [VLANs](docs/screenshots/vlans.png) - VLAN configuration and tracking
- [Locations](docs/screenshots/locations.png) - Physical location management

### Password Vault
- [Password Vault](docs/screenshots/password-vault.png) - AES-256-GCM encrypted password storage
- [Personal Vault](docs/screenshots/personal-vault.png) - Private user password vault
- [Secure Notes](docs/screenshots/secure-notes.png) - Encrypted ephemeral messaging

### Documentation & Diagrams
- [Knowledge Base](docs/screenshots/knowledge-base.png) - Document management system
- [Diagrams](docs/screenshots/diagrams.png) - Draw.io integrated diagramming
- [Floor Plans Import](docs/screenshots/floor-plans-import.png) - MagicPlan floor plan import

### Workflows & Processes
- [Workflows](docs/screenshots/workflows.png) - Process automation and tracking

### Monitoring & Expirations
- [Website Monitors](docs/screenshots/website-monitors.png) - Uptime monitoring dashboard
- [Expirations](docs/screenshots/expirations.png) - SSL, domain, and credential expiration tracking

### Security & Scanning
- [Security Dashboard](docs/screenshots/security-dashboard.png) - Security overview and vulnerability status
- [Vulnerability Scans](docs/screenshots/vulnerability-scans.png) - Snyk scan history
- [Scan Configuration](docs/screenshots/scan-configuration.png) - Security scan settings

### System Administration
- [Settings](docs/screenshots/settings-general.png) - General system configuration
- [System Status](docs/screenshots/system-status.png) - Health monitoring and scheduled tasks
- [System Updates](docs/screenshots/system-updates.png) - One-click update system
- [Organizations](docs/screenshots/organizations.png) - Multi-tenant organization management
- [Access Management](docs/screenshots/access-management.png) - User and role management
- [Integrations](docs/screenshots/integrations.png) - PSA and external integrations
- [Import Data](docs/screenshots/import-data.png) - Bulk data import tools

### MSP/Global Features (Staff Only)
- [Global Dashboard](docs/screenshots/global-dashboard.png) - Cross-organization overview
- [Global KB](docs/screenshots/global-kb.png) - Internal staff documentation
- [Global Workflows](docs/screenshots/global-workflows.png) - Reusable process templates

</details>

## 🐕 About Luna

This project was developed with the assistance of **Luna**, a brilliant German Shepherd Dog with exceptional problem-solving abilities and a keen eye for security best practices. Luna's contributions to code review, architecture decisions, and bug hunting have been invaluable.

## ✨ Key Features

### 🔐 Security First
- **Azure AD / Microsoft Entra ID SSO** - Single Sign-On with Microsoft accounts (NEW in 2.12.0)
- **LDAP/Active Directory** - Enterprise directory integration
- **Enforced TOTP 2FA** - Two-factor authentication required for all users (bypassed for SSO)
- **AES-GCM Encryption** - Military-grade encryption for all sensitive data
- **Argon2 Password Hashing** - Industry-standard password security
- **Password Breach Detection** - HaveIBeenPwned integration with k-anonymity (your passwords never leave your server)
- **Snyk Security Scanning** - Automated vulnerability scanning for Python and JavaScript dependencies with web UI
- **Automated CVE Scanning** - Continuous vulnerability monitoring and security advisory checks
- **Brute-Force Protection** - Account lockout after failed attempts
- **Rate Limiting** - All endpoints protected
- **Security Headers** - CSP, HSTS, X-Frame-Options, and more
- **SQL Injection Prevention** - Parameterized queries throughout
- **SSRF Protection** - URL validation for external connections
- **Path Traversal Prevention** - Strict file validation
- **IDOR Protection** - Object access validation

### 🏢 Multi-Tenancy & RBAC
- **Organization Isolation** - Complete data separation
- **42 Granular Permissions** - Across 10 categories
- **MSP User Types** - Staff users (global) and Organization users (scoped)
- **Role Templates** - Reusable permission sets
- **Four-Tier Access** - Owner, Admin, Editor, Read-Only

### 📦 Core Features

#### Auto-Update System (NEW in 2.14.21!)
- **One-Click Updates** - Update HuduGlue directly from the web interface
- **Real-Time Progress** - Animated progress modal showing all 5 update steps
- **Automatic Service Restart** - Service restarts automatically after update
- **Zero Downtime** - Updates complete in 20-30 seconds with automatic reload
- **Background Execution** - Updates run in background thread, no browser timeouts
- **Smart Dependency Management** - Only installs missing packages, no unnecessary rebuilds
- **Version Detection** - Automatic detection of new releases from GitHub
- **Safety Features** - Delayed restart using systemd-run to prevent self-termination
- **No SSH Required** - Non-technical users can update without command line access

#### Asset Management
- **Comprehensive Asset Tracking** - Track all IT assets with custom fields, relationships, and lifecycle management
- **Rackmount Tracking** - NetBox-style rack visualization with U-space management
- **Asset Relationships** - Link related assets (server → VM, switch → port, etc.)
- **Custom Fields** - Flexible metadata for any asset type
- **Asset Templates** - Predefined configurations for common asset types
- **Bulk Operations** - Import, export, and update multiple assets at once

#### Password Vault & Security
- **AES-GCM Encrypted Vault** - Military-grade encryption for all passwords
- **Folder Organization** - Organize passwords by category, client, or custom structure
- **Password Breach Detection** - Automatic checking against HaveIBeenPwned database
- **Personal Vault** - Private password storage per user (separate from org passwords)
- **Password Strength Analysis** - Real-time password quality checking
- **Expiration Tracking** - Automatic alerts for expiring credentials
- **Secure Notes** - Encrypted ephemeral messaging system

#### Documentation & Knowledge Base
- **Per-Organization Docs** - Isolated documentation per client/organization
- **Categories & Tags** - Flexible organization with categories and tagging
- **Version Control** - Full document version history with rollback
- **Rich Text Editor** - Markdown support with WYSIWYG editing
- **Global Knowledge Base** - Staff-only internal documentation (MSP KB)
- **Document Templates** - Reusable templates for common documentation types
- **Full-Text Search** - Fast search across all documentation

#### Diagrams & Floor Plans
- **Draw.io Integration** - Full-featured diagramming with Draw.io embedded editor
- **Diagram Templates** - Pre-built templates for network, rack, and flowchart diagrams
- **Version History** - Track diagram changes with automatic versioning
- **Export Formats** - PNG, SVG, XML export options
- **Floor Plan Generation** - AI-powered floor plan creation from building data
- **MagicPlan Import** - Import floor plans directly from MagicPlan mobile app
- **Location Linking** - Link floor plans to specific locations/buildings

#### Locations & Facilities
- **Multi-Location Management** - Track multiple offices, data centers, warehouses
- **Geocoding** - Automatic GPS coordinate lookup from addresses
- **Property Data Integration** - Fetch building information from external sources
- **Satellite Imagery** - Automatic satellite image download via Google Maps API
- **Floor Plan Management** - Multiple floor plans per location with dimensions
- **Location Types** - Office, Warehouse, Data Center, Retail, Branch, etc.
- **Shared Locations** - Co-location facilities shared across multiple organizations

#### Infrastructure Management
- **Rack Visualization** - NetBox-style rack diagrams with U-space allocation
- **IPAM (IP Address Management)** - Subnet tracking, IP allocation, CIDR management
- **Network Documentation** - Switch, router, firewall configuration tracking
- **Cable Management** - Track patch cables, fiber runs, and connections
- **Power Distribution** - PDU tracking and power capacity planning

#### Monitoring & Alerts
- **Website Monitoring** - Uptime checks with configurable intervals
- **SSL Certificate Tracking** - Automatic SSL expiration monitoring and alerts
- **Domain Expiration** - Track domain renewal dates
- **Expiration Dashboard** - Centralized view of all expiring items
- **Custom Alerts** - Configurable notification thresholds
- **Monitoring History** - Track uptime/downtime trends over time

#### Workflows & Process Automation (v2.24.155-159)
- **One-Click Launch** - Prominent "Launch Workflow" button with automatic assignment
- **Complete Audit Logging** - Every action tracked (who, what, when) with timeline view
- **PSA Ticket Integration** - Link workflows to PSA tickets with automatic completion summaries
- **Execution List View** - See all workflow launches across organization with filtering
- **Sequential Runbooks** - Step-by-step process documentation
- **Entity Linking** - Link processes to assets, passwords, diagrams, docs
- **Execution Tracking** - Track process runs with timestamps, notes, and progress bars
- **Process Templates** - Reusable templates for common procedures
- **Interactive Checklist** - Live progress tracking with stage completion
- **Stage Duration Tracking** - Time tracking for each process step
- **Note Visibility Control** - Choose internal/public visibility for PSA ticket notes
- **Auto-Generated Flowcharts** - Convert workflows to Draw.io diagrams

#### Data Import & Migration
- **IT Glue Import** - Full data migration from IT Glue platform
- **Hudu Import** - Complete Hudu data migration support
- **MagicPlan Floor Plans** - Import floor plans from MagicPlan JSON exports
- **Multi-Organization Import** - Import all organizations at once or selectively
- **Fuzzy Matching** - Intelligent organization name matching (e.g., "ABC LLC" → "ABC Corporation")
- **Dry Run Mode** - Preview imports before committing changes
- **Duplicate Prevention** - Automatic detection and prevention of duplicate records
- **Progress Tracking** - Real-time import status with detailed logs
- **Import History** - Track all import jobs with statistics and error logs

#### Contact Management
- **Organization-Specific Contacts** - Contact database per client
- **Contact Types** - Primary, Billing, Technical, Emergency contacts
- **Contact Relationships** - Link contacts to assets, locations, and tickets
- **Communication History** - Track interactions with contacts

#### Audit & Compliance
- **Complete Audit Logging** - Every action tracked with user, timestamp, and details
- **Audit Search** - Search audit logs by user, action, date range
- **Compliance Reports** - Generate reports for compliance requirements
- **Data Retention** - Configurable audit log retention policies

### 🔌 PSA Integrations (8 Providers)
Full implementations for:
- **ConnectWise Manage** - Companies, Contacts, Tickets, Projects, Agreements
- **Autotask PSA** - Companies, Contacts, Tickets, Projects, Agreements
- **HaloPSA** - Companies, Contacts, Tickets, OAuth2
- **Kaseya BMS** - Companies, Contacts, Tickets, Projects, Agreements
- **Syncro** - Customers, Contacts, Tickets
- **Freshservice** - Departments, Requesters, Tickets
- **Zendesk** - Organizations, Users, Tickets
- **ITFlow** - Open-source PSA with full API support
- **Alga PSA** - Placeholder ready (open-source MSP PSA)

**NEW in 2.12.0: Organization Auto-Import**
- Automatically create HuduGlue organizations from PSA companies
- Optional name prefixes (e.g., "PSA-CompanyName")
- Smart duplicate prevention with external ID tracking
- Sync metadata (phone, address, website)

### 🖥️ RMM Integrations (5 Providers)
**Phase 1 Infrastructure Complete (v2.24.x)** - Ready for provider implementations:
- **Base Models & Architecture** - RMMConnection, RMMDevice, RMMAlert, RMMSoftware models with encryption
- **Provider Registry** - Extensible provider system with BaseRMMProvider abstract class
- **Admin Interface** - Full Django admin integration for RMM management
- **Database Schema** - Complete migrations and indexes for optimal performance
- **Tactical RMM** (Fully Implemented) - Device management, alerts, software inventory, WebSocket updates
- **NinjaOne** (Infrastructure Ready) - OAuth 2.0 authentication, device sync, monitoring
- **Datto RMM** (Infrastructure Ready) - API key authentication, device inventory, alerts
- **Atera** (Infrastructure Ready) - Agent management, ticketing integration
- **ConnectWise Automate** (Infrastructure Ready) - Computer management, script execution
- **Auto Asset Mapping** - Automatically link RMM devices to asset records based on serial number and hostname
- **Scheduled Sync** - Automatic device synchronization on configurable intervals
- **Device Monitoring** - Track online/offline status, last seen timestamps

**NEW in 2.12.0: Organization Auto-Import**
- Automatically create HuduGlue organizations from RMM sites/clients
- Optional name prefixes (e.g., "RMM-SiteName")
- Smart duplicate prevention with external ID tracking
- Sync site metadata and contact information
- **Software Inventory** - Sync installed software from RMM platforms
- **Alert Integration** - Pull RMM alerts and monitoring data

## 🆕 What's New in v2.24

### Latest Release - January 2026

**v2.24.159** - 🚀 **Automatic Workflow Assignment** (Latest Release)
- **Simplified Launch** - Removed "Assign To" field from workflow launch form
- **Auto-Assignment** - Workflows automatically assigned to user who launches them
- **Cleaner UX** - Streamlined workflow execution creation process
- **Info Message** - Clear notification that workflow will be assigned to you

**v2.24.158** - 📊 **Workflow Execution List View & Bug Fixes**
- **Complete History** - View all workflow launches across organization in one place
- **Advanced Filtering** - Filter by status, workflow, and assigned user
- **Visual Dashboard** - Color-coded status badges, progress bars, overdue warnings
- **Quick Actions** - Jump to execution details or audit log from list
- **Fixed** ProcessExecutionForm organization filtering errors
- **Fixed** User membership query using correct relationship

**v2.24.157** - 🎨 **Enhanced Workflow Launch Experience**
- **Renamed** "Start Execution" to "Launch Workflow" throughout UI
- **Prominent Button** - Large green "Launch Workflow" button with rocket icon 🚀
- **PSA Integration** - Select PSA ticket and set note visibility directly at launch
- **Better Separation** - Clear distinction between viewing templates and launching executions

**v2.24.156** - 🔐 **PSA Note Visibility Control**
- **Internal/Public Toggle** - Choose whether PSA completion notes are private or customer-visible
- **Default Public** - Notes visible to customers by default
- **Checkbox Control** - Simple checkbox in launch form to make notes internal

**v2.24.155** - 📋 **Complete Workflow Audit Logging & PSA Integration**
- **Comprehensive Audit Log** - Every workflow action tracked with user, timestamp, IP address
- **Timeline View** - Beautiful chronological activity feed grouped by date
- **Color-Coded Events** - Green (completed), yellow (uncompleted), red (failed), blue (other)
- **PSA Ticket Integration** - Link workflows to PSA tickets at launch time
- **Auto-Update PSA** - Completion summary automatically posted to PSA ticket when workflow finishes
- **Change History** - Old/new values stored in JSON for all updates
- **Dual Logging** - Logs to both workflow-specific audit log and system-wide audit log
- **Supported PSAs** - ITFlow, ConnectWise Manage, Syncro (with internal/public note control)
- **PSAManager Class** - Unified interface for all PSA ticket operations with encryption

**v2.24.154** - 🎨 **Diagram Preview Generation Fixes**
- **Fixed** FileField empty detection for diagram previews on remote server
- **Added** --force flag to updater for diagram preview generation
- **Improved** Q object filtering for better SQLite/PostgreSQL compatibility

**v2.24.153** - 📱 **Document Previews & Workflow Flowcharts**
- **Document Card View** - Visual preview cards for all knowledge base documents
- **One-Click Flowcharts** - Generate workflow diagrams directly from process pages
- **Auto-Generate on Update** - Workflow diagrams regenerate during system updates

**v2.24.37** - 📚 **Comprehensive Professional KB Article Library**
- **Windows Administration Articles** - 4 comprehensive guides (1,576 lines of professional content):
  - How to Reset Windows Local Administrator Password (5 methods including Utilman.exe replacement)
  - Optimize Windows 10/11 Performance - Complete optimization guide
  - Create and Manage Group Policy Objects (10 common GPO configurations)
  - Configure and Troubleshoot Windows Updates - Complete guide with error fixes
- **Professional Formatting** - Emoji icons for organization, syntax-highlighted code blocks
- **Step-by-Step Procedures** - Comprehensive troubleshooting and best practices
- **Real-World MSP Content** - Ready-to-use documentation for client support

**v2.24.36** - 🎨 **Enhanced UI Visibility & Navigation**
- **Breadcrumb Backgrounds** - Standalone breadcrumbs now have gradient backgrounds for better readability
- **Dark Mode Support** - Breadcrumb styling adapts to dark theme
- **Improved Contrast** - All UI elements now meet WCAG accessibility standards

**v2.24.35** - 🐛 **UI Color Corrections**
- **Snyk Page Improvements** - Changed alert colors from warning to info for better context
- **Visual Consistency** - Standardized alert usage across all settings pages

**v2.24.34** - 🔧 **Database Compatibility & Menu Standardization**
- **SQLite Support** - Fixed maintenance page database queries for SQLite compatibility
- **Cross-Database Queries** - Added database-agnostic table size queries (MySQL/PostgreSQL/SQLite)
- **Settings Navigation** - Standardized all settings pages to 12-item menu
- **System Updates Header** - Added background card for better visibility

**v2.24.33-25** - 🎨 **Comprehensive UI Polish**
- **Rounded Corners** - Fixed card headers with gradient backgrounds across entire application
- **Enhanced Visibility** - Card headers now have depth with subtle shadows and gradients
- **CSS Refactoring** - Improved specificity and consistency for all Bootstrap components

## 🆕 What's New in v2.14

### Previous Releases - January 2026

**v2.14.21** - 🎉 **Auto-Update System Complete!** (Latest Release)
- **One-Click Web Updates** - Update HuduGlue directly from the web interface without SSH access
- **Real-Time Progress Tracking** - Animated modal shows all 5 steps with live status updates
- **Automatic Service Restart** - Service restarts automatically using systemd-run with 3-second delay
- **Zero Manual Intervention** - Complete end-to-end automation from git pull to service reload
- **Smart Dependency Management** - Only installs missing packages, avoids rebuilding compiled packages
- **Production Ready** - Fully tested and verified working in v2.14.19 → v2.14.20 update
- **Better UX** - Clear messaging about restart timing (may take up to a minute)
- **Total Update Time** - 20-30 seconds from start to finish

**Technical Implementation:**
- Background thread execution prevents browser timeouts
- Full path resolution for all system commands (`/usr/bin/sudo`, `/usr/bin/systemd-run`, `/usr/bin/systemctl`)
- AJAX polling for progress updates every second
- Passwordless sudo permissions configured via `/etc/sudoers.d/huduglue-auto-update`
- Industry-standard delayed restart approach prevents process self-termination

**v2.14.5** - ITFlow PSA Integration
- **New Integration** - Complete ITFlow PSA provider implementation
- **Fixed Error** - "Unknown provider type: itflow" now resolved
- **Full Support** - Clients, contacts, and tickets synchronization

**v2.14.4** - Member Edit IntegrityError Fix
- **Fixed Critical Bug** - IntegrityError when editing organization members
- **User Field Protection** - Prevents accidental user reassignment during edit
- **Cleaner Forms** - User selection only shown when creating new memberships

**v2.14.3** - Role Management & User Edit Fixes
- **Fixed Role Management** - ADMIN role can now manage roles (not just OWNER)
- **Fixed User Editing** - Corrected redirect from non-existent 'home' route
- **Admin User Setup** - Automatically creates OWNER membership if missing

**v2.14.2** - Encryption Error Handling
- **Better Error Messages** for malformed encryption keys
- **User-Friendly Instructions** showing exact commands to fix issues
- **Comprehensive Coverage** across all encryption points (PSA, RMM, Passwords)

**v2.14.1** - Critical Bug Fixes
- **Fixed IntegrityError** when changing admin password (auth_source field)
- **Enhanced Installer** with .env validation and permission checks
- **Better Error Messages** showing exact fix commands for common issues
- Added comprehensive session documentation

**v2.14.0** - Enhanced Update System with Changelog Display
- **Changelog Integration**
  - Display current version's changelog on System Updates page
  - Show changelogs for all available newer versions
  - Helps users understand what they're running and what updates will bring
  - Automatically parses CHANGELOG.md for version-specific content

**v2.13.0** - Auto-Update System
- **Auto-Update System with Web Interface**
  - Check for updates from GitHub releases
  - Manual update trigger from Admin → System Updates
  - Automatic hourly update checks
  - One-click update: git pull, pip install, migrate, collectstatic, restart
  - Version comparison using semantic versioning
  - Beautiful UI showing current vs. available version
  - Git status monitoring (branch, commit, clean working tree)
  - Release notes display from GitHub
  - Update history tracking with audit log
  - Staff-only access with confirmation modal
  - Graceful failure handling

**v2.12.0** - Azure SSO & Organization Auto-Import
- **Azure AD / Microsoft Entra ID SSO** - Complete single sign-on implementation
  - "Sign in with Microsoft" button on login page
  - Auto-create user accounts from Azure AD
  - Bypasses 2FA for SSO users (already authenticated)
  - Full setup guide in Admin settings
- **Organization Auto-Import from PSA/RMM**
  - Automatically create orgs from PSA companies or RMM sites
  - Configurable name prefixes
  - Smart duplicate prevention
  - Tracks external IDs in custom fields
- **Fixed RMM/PSA IntegrityError** - organization_id null error resolved
- **Alga PSA placeholder** - Ready for future integration
- **Cryptography compatibility fix** - Resolved installation issues

## 🆕 What's New in v2.11

### Recent Updates (January 2026)

**v2.11.7** - Bug Fixes & UI Improvements
- Fixed visible ">" artifact on all pages (CSRF token meta tag issue)
- Fixed About page TemplateSyntaxError with hyphenated package names
- Improved floor plan generation loading overlay contrast
- Renamed "Processes" to "Workflows" throughout UI for better clarity
- Fixed template variable mismatch causing workflow list errors
- Added comprehensive demo data documentation to installation guide
- Timezone display now correctly shows Eastern Time (EST/EDT)

**v2.11.6** - Security & CVE Scanning
- **Live CVE vulnerability scanning** on About page with real-time results
- Resolved all 10 known security vulnerabilities through package upgrades:
  - cryptography 41.0.7 → 44.0.1 (4 CVEs fixed)
  - djangorestframework 3.14.0 → 3.15.2 (1 CVE fixed)
  - gunicorn 21.2.0 → 22.0.0 (2 CVEs fixed)
  - pillow 10.2.0 → 10.3.0 (1 CVE fixed)
  - requests 2.31.0 → 2.32.4 (2 CVEs fixed)
- Real-time dependency version display on About page
- Integrated pip-audit for automated vulnerability detection
- **Result: Zero known vulnerabilities** ✓

**v2.11.5** - Location Intelligence & Password Security
- Location-aware property appraiser suggestions (adapts to county/state)
- Password breach detection integration with HaveIBeenPwned
- Scheduled password breach scanning (configurable intervals: 2-24 hours)
- Floor plan generation progress feedback with visual overlay
- Smarter property diagram help text based on location

**Earlier v2.11.x Features:**
- Workflows (formerly Processes) with sequential execution tracking
- Enhanced diagram versioning and template system
- Password strength analysis and expiration tracking
- Website monitoring with SSL certificate tracking
- Multi-location management with geocoding
- Scheduled task system (no Redis required - systemd timers)

## 🚀 Quick Start

### One-Line Installation (Recommended)

The easiest way to install HuduGlue:

```bash
git clone https://github.com/agit8or1/huduglue.git && cd huduglue && bash install.sh
```

This automated installer will:
- ✅ Install all prerequisites (Python 3.12, pip, venv, MariaDB server & client)
- ✅ Create virtual environment and install dependencies
- ✅ Generate secure encryption keys automatically
- ✅ Create `.env` configuration file
- ✅ Setup database and user
- ✅ Create log directory
- ✅ Run migrations
- ✅ Create superuser account
- ✅ Collect static files
- ✅ **Start production server automatically** (Gunicorn with systemd)
- ✅ **Configure auto-update permissions** (sudoers for one-click web updates)

**When the installer finishes, your server is RUNNING and ready to use!**

### Smart Detection

The installer automatically detects existing installations and offers:

1. **Upgrade/Update** - Pull latest code, run migrations, restart service (zero downtime)
2. **System Check** - Verify all components are working properly
3. **Clean Install** - Remove everything and reinstall from scratch
4. **Exit** - Leave existing installation untouched

No manual cleanup needed! The installer handles everything.

### Web-Based Auto-Update (NEW in 2.14.21!)

Once installed, you can update HuduGlue **directly from the web interface**:

1. Navigate to **System Settings → System Updates**
2. Click **"Check for Updates Now"** to detect new versions
3. Click **"Apply Update"** when an update is available
4. Watch real-time progress through all 5 steps:
   - Step 1: Git Pull
   - Step 2: Install Dependencies
   - Step 3: Run Migrations
   - Step 4: Collect Static Files
   - Step 5: Restart Service
5. Page automatically reloads with the new version (20-30 seconds total)

**No SSH access required!** Non-technical users can update safely from the web interface.

**System Requirements:**
- Ubuntu 20.04+ or Debian 11+
- 2GB RAM minimum (4GB recommended)
- Internet connection for package installation

### Optional Features

#### LDAP/Active Directory Integration

By default, HuduGlue installs with Azure AD SSO support but **without** LDAP/Active Directory. This is because LDAP requires C compilation and system libraries.

**If you need LDAP/AD support**, install it after the main installation:

```bash
# Install system build dependencies
sudo apt-get update
sudo apt-get install -y build-essential python3-dev libldap2-dev libsasl2-dev

# Install LDAP Python packages
cd ~/huduglue
source venv/bin/activate
pip install -r requirements-optional.txt
sudo systemctl restart huduglue-gunicorn.service
```

**Note:** Azure AD SSO does **not** require these packages. LDAP is only needed for on-premises Active Directory or other LDAP servers.

### Manual Installation

If you prefer to install manually or need more control:

<details>
<summary>Click to expand manual installation steps</summary>

#### Prerequisites
- Python 3.12+
- MariaDB 10.5+ or MySQL 8.0+
- Nginx (production only)

```bash
# 1. Clone repository
git clone https://github.com/agit8or1/huduglue.git
cd huduglue

# 2. Install system dependencies
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip mariadb-client mariadb-server

# 3. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Generate secrets
python3 -c "from cryptography.fernet import Fernet; print('APP_MASTER_KEY=' + Fernet.generate_key().decode())"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(50))"
python3 -c "import secrets; print('API_KEY_SECRET=' + secrets.token_urlsafe(50))"

# 6. Create .env file
# Copy the generated secrets from step 5 into this file
cat > .env << 'EOF'
DEBUG=True
SECRET_KEY=<paste_secret_key_here>
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=huduglue
DB_USER=huduglue
DB_PASSWORD=your_secure_password
DB_HOST=localhost
DB_PORT=3306

APP_MASTER_KEY=<paste_master_key_here>
API_KEY_SECRET=<paste_api_key_secret_here>

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
SITE_NAME=HuduGlue
SITE_URL=http://localhost:8000
EOF

# 7. Start MariaDB and create database
sudo systemctl start mariadb
sudo mysql << 'EOSQL'
CREATE DATABASE huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'huduglue'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue'@'localhost';
FLUSH PRIVILEGES;
EOSQL

# 8. Run migrations
python3 manage.py migrate

# 9. Create superuser
python3 manage.py createsuperuser

# 10. Collect static files
python3 manage.py collectstatic --noinput

# 11. Run development server
python3 manage.py runserver 0.0.0.0:8000
```

Visit `http://localhost:8000` and log in with the credentials you created in step 9.

</details>

## 📚 Documentation

**Installation:**
- **[INSTALL.md](INSTALL.md)** - Complete installation guide (quick start, upgrade, troubleshooting)

**Core Documentation:**
- **[ORGANIZATIONS.md](ORGANIZATIONS.md)** - Complete guide to organizations, user types, roles, and permissions
- **[SECURITY.md](SECURITY.md)** - Security best practices and vulnerability disclosure
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Development and contribution guidelines
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and release notes
- **[deploy/](deploy/)** - Production deployment configs (Nginx, Gunicorn, systemd services)

## 🏗️ Architecture

### Technology Stack
- **Framework**: Django 6.0
- **API**: Django REST Framework 3.15
- **Database**: MariaDB 10.5+ (MySQL 8.0+ supported)
- **Web Server**: Nginx + Gunicorn
- **Authentication**: django-two-factor-auth (TOTP)
- **Encryption**: Python cryptography (AES-GCM)
- **Password Hashing**: Argon2
- **Frontend**: Bootstrap 5, vanilla JavaScript

### Design Philosophy
- ✅ **No Docker** - Pure systemd deployment
- ✅ **No Redis** - systemd timers for scheduling
- ✅ **Minimal Dependencies** - Only essential packages
- ✅ **Security First** - Built with security in mind
- ✅ **Self-Hosted** - Complete data control

## 🔒 Security

HuduGlue has undergone comprehensive security auditing and continuous vulnerability monitoring:

### Continuous Security Monitoring
- ✅ **Automated CVE Scanning** - Codebase scanned for known vulnerabilities and CVEs
- ✅ **AI-Assisted Detection** - Pattern matching for SQL injection, XSS, CSRF, path traversal
- ✅ **Dependency Monitoring** - Python packages checked against security advisories
- ✅ **Weekly Manual Audits** - Regular security reviews by development team
- ✅ **Alert-Only System** - No automated code changes, human verification required

### Fixed Vulnerabilities
- ✅ SQL Injection - Parameterized queries and identifier quoting
- ✅ SSRF - URL validation with IP blacklisting
- ✅ Path Traversal - Strict file path validation
- ✅ IDOR - Object access verification
- ✅ Insecure File Uploads - Type, size, and extension validation
- ✅ Hardcoded Secrets - Environment variable enforcement
- ✅ Weak Encryption - AES-GCM with validated keys
- ✅ CSRF Protection - Multi-domain support

### Security Features
- All passwords encrypted with AES-GCM
- API keys hashed with HMAC-SHA256
- Rate limiting on all endpoints
- Brute-force protection
- Security headers (CSP, HSTS)
- Private file serving
- Audit logging
- Password breach detection (HaveIBeenPwned integration)

**Security Disclosure**: If you discover a vulnerability, please email agit8or@agit8or.net. See [SECURITY.md](SECURITY.md) for details.

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### 💡 Feature Requests & Ideas

Have an idea for a new feature? We use a community-driven voting system:

1. **Start with a Discussion** → [Share your idea](https://github.com/agit8or1/huduglue/discussions/new?category=ideas)
2. **Vote on existing ideas** → [Browse and upvote](https://github.com/agit8or1/huduglue/discussions/categories/ideas) (👍 reactions)
3. **Track the Roadmap** → [View what's being built](https://github.com/agit8or1/huduglue/projects)

Popular ideas (high votes + alignment with project goals) are promoted to Feature Request issues and added to the Roadmap.

📖 **Read the full guide:** [docs/FEATURE_REQUESTS.md](docs/FEATURE_REQUESTS.md)

### 🐛 Bug Reports

Found a bug? [Report it here](https://github.com/agit8or1/huduglue/issues/new?template=bug_report.yml)

### 🔨 Code Contributions

Ready to contribute code? See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/agit8or1/huduglue.git
cd huduglue

# 2. Create feature branch
git checkout -b feature/amazing-feature

# 3. Make changes and test
python3 manage.py test

# 4. Commit and push
git commit -m 'Add amazing feature'
git push origin feature/amazing-feature

# 5. Open Pull Request
```

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Luna the GSD** - Development assistance, security review, and bug hunting
- **Django & DRF** - Excellent web framework
- **Bootstrap 5** - Beautiful, responsive UI
- **Font Awesome** - Icon library
- **Community** - All contributors and users

## 📊 Project Status

- **Version**: 2.24.159
- **Release Date**: January 2026
- **Status**: Production Ready
- **Maintained**: Yes
- **Security**: Snyk monitored, HaveIBeenPwned integrated

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/agit8or1/huduglue/issues)
- **Discussions**: [GitHub Discussions](https://github.com/agit8or1/huduglue/discussions)
- **Security**: See [SECURITY.md](SECURITY.md) for vulnerability disclosure

## 💝 Supporting This Project

If you find HuduGlue useful for your MSP or IT department, please consider supporting the developer's business: **[MSP Reboot](https://www.mspreboot.com)** - Professional MSP services and consulting.

Your support allows me to continue developing open-source tools like HuduGlue and contribute to the MSP community. Thank you!

## 🗺️ Roadmap

- [ ] Mobile-responsive UI improvements
- [ ] Advanced reporting and analytics
- [ ] Backup/restore functionality
- [ ] Docker deployment option (optional)
- [ ] Additional PSA/RMM integrations
- [ ] API v2 with GraphQL
- [x] MagicPlan floor plan integration
- [ ] Mobile app

## ⚡ Performance

- Handles 1000+ assets per organization
- Sub-second page load times
- Efficient database queries
- Optimized for low-resource environments
- Horizontal scaling support

---

**Made with ❤️ and 🐕 by the HuduGlue Team and Luna the German Shepherd**
