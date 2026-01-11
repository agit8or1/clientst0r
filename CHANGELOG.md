# Changelog

All notable changes to HuduGlue will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-01-11

### ✨ Added

- **Data Closets & Network Closets** - Enhanced rack management for network infrastructure
  - New rack types: Data Closet, Network Closet, Wall Mount Rack, Open Frame, Half Rack
  - Building/Floor/Room location hierarchy for better organization
  - Network closet specific fields: patch panel count, total port count
  - Closet diagram upload for visual layout documentation
  - Ambient temperature tracking for monitoring environmental conditions
  - PDU count tracking for power distribution management

- **Rack Resources Model** - Comprehensive equipment tracking for racks and closets
  - Track non-rackable equipment: patch panels, switches, routers, firewalls, UPS, PDUs
  - Network equipment specifications: port count, port speed, management IP
  - Power specifications: power draw, input voltage, UPS runtime, VA capacity
  - Rack position tracking (U position for rack-mounted resources)
  - Warranty and support contract tracking
  - Photo documentation for each resource
  - Optional asset linking for integration with asset management
  - Full admin interface with organized fieldsets

- **2FA Enrollment Prompt** - Optional but recommended security
  - Users prompted to enable 2FA on first login
  - "Skip for now" button allows users to defer enrollment
  - Prompts once per session only (not on every page)
  - Info banner explains 2FA benefits
  - Custom template with Bootstrap styling

### 🔧 Fixed

- **Diagram Templates** - Resolved draw.io editor errors
  - Fixed "Error: 1: Self Reference" in diagram XML
  - Simplified diagram templates to use valid mxGraph structure
  - All 5 templates now load and edit correctly without errors
  - Created `fix_diagram_templates` management command for repairs

- **Diagram Previews** - Templates now have visual previews
  - PNG thumbnails generated for all diagram templates
  - Previews displayed in diagram list and template selection
  - Automated preview generation via management command

- **Fresh Installation** - Template seeding now works correctly
  - Fixed migration ordering issue that prevented template creation
  - Templates seed after all schema changes complete
  - No longer requires organization to exist before seeding global templates
  - Installer automatically populates 5 document templates, 5 diagram templates

- **2FA Middleware** - More flexible authentication flow
  - When REQUIRE_2FA=False, shows optional enrollment prompt
  - When REQUIRE_2FA=True, enforces mandatory enrollment (existing behavior)
  - Session tracking prevents repeated redirects
  - Improved user experience for security-conscious but flexible deployments

### 📚 Documentation

- Updated version to 2.3.0
- Enhanced rack management documentation for data closets
- Added rack resource tracking documentation

## [2.2.0] - 2026-01-10

### 🚀 One-Line Installation

**Major improvement:** Complete automated installation with zero manual steps!

```bash
git clone https://github.com/agit8or1/huduglue.git && cd huduglue && bash install.sh
```

The installer now does EVERYTHING:
- Installs all system dependencies (Python, MariaDB, build tools, libraries)
- Creates virtual environment and installs Python packages
- Generates secure encryption keys automatically
- Creates and configures .env file
- Sets up database with proper schema
- Creates log directory with correct permissions
- Runs all database migrations
- Creates superuser account (interactive prompt)
- Collects static files
- **Automatically starts production server with systemd**

**When the installer finishes, the server is RUNNING!** No manual commands needed.

**Smart Detection & Upgrade System:**
The installer now detects existing installations and provides options:
- **Option 1: Upgrade/Update** - Pull latest code, update dependencies, run migrations, restart service (zero downtime)
- **Option 2: System Check** - Comprehensive health check (Python, database, service, port, HTTP response)
- **Option 3: Clean Install** - Automated cleanup and fresh reinstall
- **Option 4: Exit** - Leave installation untouched

Detects: .env file, virtual environment, systemd service, database
Shows: Current status of all components before prompting

### ✨ Added
- **Processes Feature** - Sequential workflow/runbook system for IT operations
  - Process CRUD operations with slug-based URLs
  - Sequential stages with entity linking (Documents, Passwords, Assets, Secure Notes)
  - Global processes (superuser-created) and organization-specific processes
  - Process categories: onboarding, offboarding, deployment, maintenance, incident, backup, security, other
  - Inline formset management for stages with drag-and-drop reordering
  - Confirmation checkpoints per stage
  - Full CRUD operations with list, detail, create, edit, delete views
  - Navigation integration in main navbar

- **Diagrams Feature** - Draw.io integration for network and system diagrams
  - Embedded diagrams.net editor via iframe with postMessage API
  - Store diagrams in .drawio XML format (editable)
  - PNG and SVG export generation via diagrams.net export API
  - Diagram types: network, process flow, architecture, rack layout, floor plan, organizational chart
  - Global diagrams support (superuser-created)
  - Tag-based categorization and organization
  - Full CRUD operations with list, detail, create, edit, delete views
  - Download support for all formats (PNG, SVG, XML)
  - Thumbnail previews in list view

- **Rackmount Asset Tracking** - Enhanced asset management for rack-mounted equipment
  - `is_rackmount` checkbox field on assets
  - `rack_units` field for height tracking (1U, 2U, etc.)
  - Conditional form field display (rack_units shows only when is_rackmount is checked)
  - JavaScript toggle for dynamic field visibility
  - Asset migration to add rackmount fields (assets/migrations/0004)

- **Enhanced Rack Management** - Improved rack-to-asset integration
  - Rack devices now require existing assets (ForeignKey to Asset model)
  - Asset dropdown filtered to show only rackmount assets for organization
  - "Create New Asset" button with smart redirect flow
  - After asset creation from rack page, automatically returns to "Add Asset to Rack" form
  - Updated labels: "Devices" → "Mounted Assets"
  - Improved rack detail layout with asset links

- **Access Management Dashboard** - Consolidated admin interface
  - Single page for Organizations, Users, Members, and Roles management
  - Summary cards showing counts (Organizations, Users, Memberships)
  - Recent data tables (5 recent orgs, 5 recent users, 10 recent memberships)
  - Quick links to all management functions
  - Roles & Permissions section with links to Tags, API Keys, Audit Logs
  - Superuser-only access with permission checks

### 🎨 Improved
- **Admin Navigation** - Condensed dropdown menu from 7 items to 6
  - Replaced separate Orgs/Users/Members/Roles links with single "Access Management" link
  - Cleaner, more organized menu structure
  - Better UX for administrators

- **Asset Form** - Enhanced network fields section
  - Added hostname, IP address, and MAC address fields
  - Responsive 3-column grid layout for network fields
  - Rackmount fields section with 2-column layout
  - Helper text for all new fields
  - Improved validation and placeholder text

- **Monitoring Forms** - Better organization filtering
  - RackDeviceForm filters assets by organization and rackmount capability
  - IPAddressForm properly filters assets by organization
  - Helpful empty labels and help text
  - Required field indicators with asterisks

### 🔧 Changed
- **Rack Device Model** - Changed from generic device to asset-based system
  - Removed RackDevice fields: name, photo, color, power_draw_watts, units
  - Changed asset field from optional to required ForeignKey
  - Asset properties now drive rack device display (name comes from Asset.name)
  - Maintains start_unit and notes fields
  - Migration created to preserve existing data

- **Forms Organization** - Improved __init__ patterns
  - Consistent organization parameter passing
  - Proper queryset filtering in all forms
  - Better parameter extraction (kwargs.pop pattern)

### 📚 Documentation
- Updated README.md to version 2.2.0
- Added Processes and Diagrams features to Core Features list
- Updated Infrastructure description to mention rackmount assets
- Comprehensive CHANGELOG entry for all new features

### 🗄️ Database Migrations
- `assets.0004_add_rackmount_fields` - Added is_rackmount and rack_units to Asset model
- `monitoring.0004_change_asset_id_to_foreignkey` - Changed RackDevice to use Asset ForeignKey
- `processes.0001_initial` - Created Process, ProcessStage, and Diagram models

### 🐕 Contributors
- Luna the GSD - Continued security oversight and code quality review

## [2.1.1] - 2026-01-10

### 🐛 Fixed
- **2FA Inconsistent State Detection** - Added auto-detection and repair for users who enabled 2FA before TOTPDevice integration
  - System now automatically resets inconsistent states (profile.two_factor_enabled=True but no TOTPDevice)
  - Shows warning message prompting users to re-enable 2FA properly
  - Fixes dashboard warning showing incorrectly
- **ModuleNotFoundError in 2FA Setup** - Removed incorrect import statement that caused 500 errors
  - Removed `from two_factor.models import get_available_methods` (module doesn't exist)
  - 2FA verification now works without errors
- **TOTPDevice Key Format Error** - Fixed "Non-hexadecimal digit found" error on login
  - Now properly converts base32 keys from pyotp to hex format expected by django-otp
  - Base32 to hex conversion: `base64.b32decode(secret).hex()`
  - Fixed existing broken TOTPDevice records in database
- **2FA Login Challenge Not Working** - Fixed issue where users with 2FA enabled weren't challenged for codes
  - Login now properly prompts for 6-digit TOTP codes
  - django-two-factor-auth integration working correctly
- **2FA Dashboard Warning Logic** - Dashboard warning now accurately reflects 2FA status
  - Checks for confirmed TOTPDevice existence rather than profile flag alone
  - No more false warnings for users with proper 2FA setup

### 🔧 Technical Details
- TOTPDevice keys stored in hex format (40 chars) instead of base32 (32 chars)
- Conversion: base32 → bytes (20) → hex (40 chars)
- State consistency check added to 2FA setup page load
- Auto-repair runs when users visit Profile > Two-Factor Authentication

## [2.1.0] - 2026-01-10

### ✨ Added
- **Tag Management** - Full CRUD for organization tags in Admin section
  - Create/edit/delete tags with custom colors
  - View tag usage across assets and passwords
  - Live color preview in tag forms
  - Delete warnings when tags are in use
- **Screenshot Gallery** - 31 feature screenshots for documentation
  - Full screenshot gallery page (SCREENSHOTS.md)
  - 2x3 thumbnail grid preview in README
  - Organized by feature category
- **Navigation Improvements**:
  - Tags menu item in Admin → System section
  - Improved navbar layout with truncated long usernames
  - Compact spacing for better single-line fit

### 🔧 Changed
- **Static File Serving** - Switched to WhiteNoise for efficient static file delivery
  - Removed redundant nginx (NPM handles reverse proxy)
  - Gunicorn now serves static files via WhiteNoise
  - Compressed manifest static files storage
- **Deployment Architecture** - Optimized for Nginx Proxy Manager
  - Gunicorn listens on 0.0.0.0:8000 (not unix socket)
  - NPM handles SSL termination and caching
  - Simplified stack: NPM → Gunicorn:8000 → Django
- **Asset Form** - Condensed multi-column layout
  - 2-column and 3-column responsive grid
  - Side-by-side notes and custom fields
  - Scrollable tags container
  - Improved JSON validation for custom fields with examples
- **Documentation** - Updated README with working links
  - Fixed broken documentation references
  - Updated screenshots path
  - Clarified no default credentials (must run createsuperuser)

### 🐛 Fixed
- **System Status** - Fixed systemctl path issue
  - Use /usr/bin/systemctl (full path) for service checks
  - Resolves "No such file or directory" error
- **Navbar Layout** - Fixed text jumbling with long usernames
  - Username truncated with ellipsis (max 150px)
  - Organization name truncated (max 180px)
  - Optimized padding and font sizes
- **Static Files** - Logo and assets now load correctly
  - WhiteNoise middleware properly configured
  - Collected static files with manifest
- **Tag Management** - Fixed FieldError in tag list view
  - Corrected Count() annotations for related fields
- **Asset Form** - Improved JSON field validation
  - Better help text with DNS server examples
  - Client-side validation to catch errors before submission

### 📚 Documentation
- Added SCREENSHOTS.md with all 31 feature screenshots
- Updated README.md with screenshot gallery preview
- Fixed all broken documentation links
- Clarified installation process and credential setup

## [2.0.0] - 2026-01-10

### 🔒 Security Fixes (Critical)
- **Fixed SQL Injection** - Parameterized table name quoting in database optimization (settings_views.py)
- **Fixed SSRF in Website Monitoring** - URL validation with private IP blacklisting, blocks internal networks
- **Fixed SSRF in PSA Integrations** - Base URL validation for external connections
- **Fixed Path Traversal** - Strict file path validation in file downloads using pathlib
- **Fixed IDOR** - Object type and access validation in asset relationships
- **Fixed Insecure File Uploads** - Type whitelist, size limits (25MB), extension validation, dangerous pattern blocking
- **Fixed Hardcoded Secrets** - Environment variable enforcement for SECRET_KEY, API_KEY_SECRET, APP_MASTER_KEY
- **Fixed Weak Encryption** - Proper AES-GCM key management with validation
- **Fixed SMTP Credentials** - Encrypted SMTP password storage with decrypt method
- **Fixed Password Generator** - Input validation and bounds checking (8-128 chars)

### ✨ Added
- **Enhanced Password Types** - 15 specialized password types with type-specific fields:
  - Website Login, Email Account, Windows/Active Directory, Database, SSH Key
  - API Key, OTP/TOTP (2FA), Credit Card, Network Device, Server/VPS
  - FTP/SFTP, VPN, WiFi Network, Software License, Other
  - Type-specific fields: email_server, email_port, domain, database_type, database_host, database_port, database_name, ssh_host, ssh_port, license_key
- **Password Security Features**:
  - Secure password generator with configurable length (8-128 characters)
  - Character type selection (uppercase, lowercase, digits, symbols)
  - Cryptographically secure randomness (crypto.getRandomValues)
  - Real-time strength meter with scoring algorithm
  - Have I Been Pwned integration using k-Anonymity protocol
  - SHA-1 hashing for breach checking (first 5 chars only sent)
- **Document Templates** - Reusable templates for documents and KB articles
  - Template CRUD operations
  - Pre-populate new documents from templates
  - Template selector in document creation
  - Category and content-type inheritance
- **Comprehensive GitHub Documentation**:
  - README.md with Luna the GSD attribution
  - SECURITY.md with vulnerability disclosure policy and security checklist
  - CONTRIBUTING.md with development guidelines
  - FEATURES.md with complete feature documentation
  - LICENSE (MIT)
  - CHANGELOG.md with version history
- **All PSA Providers Complete** - Full implementations:
  - Kaseya BMS (276 lines) - Companies, Contacts, Tickets, Projects, Agreements
  - Syncro (271 lines) - Customers, Contacts, Tickets
  - Freshservice (305 lines) - Departments, Requesters, Tickets, Basic Auth
  - Zendesk (291 lines) - Organizations, Users, Tickets, Basic Auth with API token

### 🎨 Improved
- **Rack Detail Layout** - Improved responsive layout with devices to the right of rack visual
  - Info panel (left column)
  - Visual rack + Device list side-by-side (right columns)
  - Responsive breakpoints for all screen sizes
- **Password Form** - Condensed multi-column layout for better UX
  - 2-3 column grid layouts
  - Reduced vertical spacing
  - Type-specific sections with show/hide logic
  - Password generator modal integration
- **Document Form** - Condensed layout with template selector
  - Template dropdown at top of form
  - Load template button with JavaScript
  - Compact field layouts
- **Navigation** - System Status and Maintenance moved from username dropdown to Admin dropdown
  - Reorganized Admin menu with sections: Settings, System, Integrations
  - User Management moved to Admin menu
- **Security Headers** - Enhanced CSP and security configurations
  - Proper CSP directives
  - HSTS enforcement
  - X-Frame-Options, X-Content-Type-Options

### 🔧 Changed
- **SECRET_KEY Validation** - Now required in production, no default fallback
  - Raises ValueError if not set in production
  - Development fallback: 'django-insecure-dev-key-not-for-production'
- **API_KEY_SECRET** - Must be separate from SECRET_KEY
  - Validates in production
  - Auto-generates separate key in development
- **APP_MASTER_KEY** - Required in production for encryption
  - Must be 32-byte Fernet key
  - No fallback allowed
- **SMTP Passwords** - Now encrypted before database storage
  - Uses vault encryption module
  - Added get_smtp_password_decrypted() method
  - Backward compatible with unencrypted passwords
- **File Upload Limits** - Maximum 25MB with strict validation
  - Whitelist: pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, md, log, jpg, jpeg, png, gif, bmp, svg, webp, zip, 7z, tar, gz, rar, json, xml, yaml, yml
  - Blocks dangerous patterns: .exe, .bat, .cmd, .sh, .php, .jsp, .asp, .aspx, .js, .vbs, .scr
  - Entity type validation
- **Password Types** - Changed default from 'password' to 'website'
  - Updated all 15 types with proper display names
  - Type-specific form sections

### 📝 Documentation
- Complete feature documentation (FEATURES.md) covering:
  - Security features (Authentication, Data Protection, Application Security, File Upload Security, Audit)
  - Multi-tenancy & RBAC
  - Asset Management
  - Password Vault
  - Documentation System
  - Website Monitoring
  - Infrastructure Management
  - PSA Integrations (all 7 providers)
  - Notifications & Alerts
  - Reporting & Analytics
  - Administration
  - API
  - User Interface
  - Developer Features
  - Data Management
  - Performance & Scalability
  - Deployment & Maintenance
- Security policy (SECURITY.md) with:
  - Vulnerability reporting guidelines
  - Supported versions
  - Security measures documentation
  - Disclosure process
  - Security checklist for deployment
  - Luna's security tips
- Contributing guidelines (CONTRIBUTING.md) with:
  - Development setup instructions
  - Code standards
  - Testing requirements
  - Commit message format
  - Pull request process
  - Luna's development tips

### 🐕 Contributors
- Luna the GSD - Security auditing, code review, architecture decisions, and bug hunting

### 🔧 Technical Details
- Upgraded to Django 6.0 and Django REST Framework 3.15
- Python 3.12+ required
- Comprehensive security audit completed
- All critical and high severity vulnerabilities fixed
- 22 security issues addressed

### Database Migrations
- `vault.0005` - Added type-specific fields to Password model:
  - database_host, database_name, database_port, database_type
  - domain (for Windows/AD)
  - email_port, email_server
  - license_key
  - ssh_host, ssh_port
  - Altered password_type field with new choices

---

## [1.0.0] - 2026-01-09

### Added
- **Core Platform**
  - Multi-tenant organization system with complete data isolation
  - Role-based access control (Owner, Admin, Editor, Read-Only)
  - Django 5.0 framework with Django REST Framework 3.14
  - MariaDB database support

- **Security Features**
  - Enforced TOTP two-factor authentication (django-two-factor-auth)
  - Argon2 password hashing
  - AES-GCM encryption for password vault and credentials
  - HMAC-SHA256 hashed API keys
  - Brute-force protection via django-axes (5 attempts, 1-hour lockout)
  - Rate limiting on all API endpoints and login
  - Comprehensive security headers (HSTS, X-Frame-Options, CSP, etc.)
  - Secure session cookies (Secure, HttpOnly, SameSite)

- **Asset Management**
  - Device tracking with flexible custom JSON fields
  - Asset types: Server, Workstation, Laptop, Network, Printer, Phone, Mobile, Other
  - Tag system for categorization
  - Contact associations
  - Relationship mapping between entities
  - Audit trail for all changes

- **Password Vault**
  - AES-GCM encrypted password storage (256-bit)
  - Master key from environment variable
  - Secure reveal with audit logging
  - Tags and categorization
  - URL and username storage
  - Never stores plaintext

- **Knowledge Base**
  - Markdown document support
  - Version history tracking
  - Rich markdown rendering (code blocks, tables, etc.)
  - Tag-based organization
  - Publish/draft status
  - Full-text search ready

- **File Management**
  - Private file attachments
  - Nginx X-Accel-Redirect for secure serving
  - No public media exposure
  - Permission-based access
  - Upload size limits

- **Audit System**
  - Comprehensive activity logging
  - Records: user, action, IP, user-agent, timestamp
  - Immutable logs (admin read-only)
  - Special logging for sensitive actions (password reveals)
  - Tracks: create, read, update, delete, login, logout, API calls, sync events

- **REST API**
  - Full CRUD operations for all entities
  - API key authentication with secure storage
  - Session authentication support
  - Rate limiting (1000/hour per user, 100/hour anonymous)
  - Password reveal endpoint with audit
  - Pagination support (50 items per page)
  - OpenAPI-ready structure

- **PSA Integrations**
  - Extensible provider architecture with BaseProvider abstraction
  - **ConnectWise Manage** - Full implementation
  - **Autotask PSA** - Full implementation
  - Sync engine features
  - PSA data models

- **User Interface**
  - Bootstrap 5 responsive design
  - Server-rendered templates
  - Organization switcher in navigation
  - Documentation and about pages

- **Deployment**
  - Ubuntu bootstrap script
  - Gunicorn systemd service
  - PSA sync systemd timer
  - Nginx reverse proxy configuration
  - SSL/TLS support (Let's Encrypt ready)

- **Management Commands**
  - `seed_demo` - Create demo organization and data
  - `sync_psa` - Manual PSA sync with filtering

### Security
- All sensitive data encrypted at rest
- API keys never stored in plaintext
- Password vault uses AES-GCM with environmental master key
- CSRF protection on all forms
- XSS protection via bleach HTML sanitization
- SQL injection protection via Django ORM

### Technical Details
- Python 3.8+ required
- Django 5.0 with async support ready
- MariaDB 10.5+ with utf8mb4
- Gunicorn WSGI server with 4 workers
- Nginx with security headers
- systemd for process management
- No Docker required
- No Redis required (uses systemd timers)

---

## Version Numbering

This project follows [Semantic Versioning](https://semver.org/):
- **MAJOR** version for incompatible API changes
- **MINOR** version for backwards-compatible functionality additions
- **PATCH** version for backwards-compatible bug fixes

Format: `MAJOR.MINOR.PATCH` (e.g., `2.0.0`)

---

**Changelog maintained by the HuduGlue Team and Luna the GSD 🐕**
