# HuduGlue 🐕

[![Version 2.14.15](https://img.shields.io/badge/version-2.14.15-brightgreen)](https://github.com/agit8or1/huduglue)
[![Production Ready](https://img.shields.io/badge/status-production%20ready-green)](https://github.com/agit8or1/huduglue)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Django 6.0](https://img.shields.io/badge/django-6.0-blue)](https://www.djangoproject.com/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)

A complete, self-hosted IT documentation platform designed for Managed Service Providers (MSPs) and IT departments. Built with Django 6, HuduGlue provides secure asset management, encrypted password vault, knowledge base, PSA integrations, and comprehensive monitoring tools.

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

#### Processes & Workflows
- **Sequential Runbooks** - Step-by-step process documentation
- **Entity Linking** - Link processes to assets, passwords, diagrams, docs
- **Execution Tracking** - Track process runs with timestamps and notes
- **Process Templates** - Reusable templates for common procedures
- **Checklist Mode** - Interactive checklist for executing processes
- **Stage Duration Tracking** - Time tracking for each process step

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
Full implementations for:
- **NinjaOne** - Device management, monitoring, alerts, and software inventory
- **Datto RMM** - Device sync, software inventory, and automated asset mapping
- **ConnectWise Automate** - Device management, scripting, and automation
- **Atera** - Device monitoring, ticketing integration, and remote access
- **Tactical RMM** - Open-source RMM with full API support and agent management
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

## 🆕 What's New in v2.14

### Latest Release - January 2026

**v2.14.5** - ITFlow PSA Integration (Latest Release)
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

**When the installer finishes, your server is RUNNING and ready to use!**

### Smart Detection

The installer automatically detects existing installations and offers:

1. **Upgrade/Update** - Pull latest code, run migrations, restart service (zero downtime)
2. **System Check** - Verify all components are working properly
3. **Clean Install** - Remove everything and reinstall from scratch
4. **Exit** - Leave existing installation untouched

No manual cleanup needed! The installer handles everything.

**System Requirements:**
- Ubuntu 20.04+ or Debian 11+
- 2GB RAM minimum (4GB recommended)
- Internet connection for package installation

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

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

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

- **Version**: 2.11.7
- **Release Date**: January 2026
- **Status**: Production Ready
- **Maintained**: Yes

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

## 📸 Screenshots

**[View Full Screenshot Gallery →](SCREENSHOTS.md)**

<table>
  <tr>
    <td><img src="screenshots/01-dashboard.png" width="300" alt="Dashboard"/><br/><sub><b>Dashboard</b></sub></td>
    <td><img src="screenshots/05-passwords-list.png" width="300" alt="Password Vault"/><br/><sub><b>Password Vault</b></sub></td>
    <td><img src="screenshots/03-assets-list.png" width="300" alt="Assets"/><br/><sub><b>Asset Management</b></sub></td>
  </tr>
  <tr>
    <td><img src="screenshots/08-documents-list.png" width="300" alt="Documents"/><br/><sub><b>Knowledge Base</b></sub></td>
    <td><img src="screenshots/13-website-monitors.png" width="300" alt="Monitoring"/><br/><sub><b>Website Monitoring</b></sub></td>
    <td><img src="screenshots/25-system-status.png" width="300" alt="System Status"/><br/><sub><b>System Status</b></sub></td>
  </tr>
</table>

**[See all 31 screenshots →](SCREENSHOTS.md)**

---

**Made with ❤️ and 🐕 by the HuduGlue Team and Luna the German Shepherd**
