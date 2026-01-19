# HuduGlue Features

Complete feature documentation for HuduGlue - Self-hosted IT documentation platform.

## 🔐 Security Features

### Authentication & Access Control
- **Azure AD / Microsoft Entra ID SSO** (NEW in v2.12.0):
  - Single Sign-On with Azure AD / Microsoft Entra ID
  - OAuth 2.0 authentication flow with MSAL
  - Auto-user creation on first login
  - 2FA bypass for Azure authenticated users (SSO is already secure)
  - Microsoft Graph API user sync
  - Tenant restriction support
  - Comprehensive setup instructions in Admin UI
- **Enforced TOTP 2FA** - Two-factor authentication required for all users
- **Argon2 Password Hashing** - Industry-standard password security with configurable work factors
- **Session Management** - Secure session handling with configurable timeout
- **Brute-Force Protection** - Account lockout after failed login attempts (django-axes)
- **Password Policies** - Configurable minimum length and complexity requirements

### Data Protection
- **AES-GCM Encryption** - Military-grade encryption for sensitive data
  - Password vault entries
  - Personal vault items
  - PSA API credentials
  - SMTP passwords
  - OAuth tokens
- **HMAC-SHA256 API Keys** - Secure API key hashing with separate secret
- **Encrypted Storage** - All sensitive data encrypted at rest
- **Private File Serving** - Files served via X-Accel-Redirect (Nginx)

### Application Security
- **SQL Injection Prevention** - Parameterized queries and identifier quoting throughout
- **XSS Protection** - Django auto-escaping enabled, strict output encoding
- **CSRF Protection** - Multi-domain CSRF token validation
- **SSRF Protection** - URL validation with private IP blacklisting
- **Path Traversal Prevention** - Strict file path validation
- **IDOR Protection** - Object access verification for all resources
- **Rate Limiting** - Per-user and per-endpoint rate limiting
- **Security Headers** - CSP, HSTS, X-Frame-Options, X-Content-Type-Options

### Vulnerability Scanning & Monitoring
- **Snyk Security Integration** (NEW in v2.24.x):
  - Automated vulnerability scanning for Python dependencies (requirements.txt)
  - JavaScript dependency scanning (package.json, node_modules)
  - Docker image scanning (if using containerized deployment)
  - Web UI dashboard showing vulnerability counts by severity (critical, high, medium, low)
  - Trend analysis tracking vulnerabilities over time
  - One-click manual scan from Admin → Settings → Snyk Security
  - Scheduled automatic scanning (configurable: daily, weekly, monthly)
  - Detailed remediation advice with upgrade paths
  - Integration with GitHub security advisories
  - API token configuration in Django admin settings
  - Scan history with timestamps and result storage
  - Zero-config setup with optional API token for enhanced features

### File Upload Security
- **File Type Whitelist** - Only approved file types allowed
- **File Size Limits** - Maximum 25MB per file
- **Extension Validation** - Dangerous extensions blocked
- **Dangerous Pattern Detection** - Blocks .exe, .php, .sh, etc.
- **Content-Type Validation** - MIME type verification

### Audit & Monitoring
- **Comprehensive Audit Logging** - All actions logged with user, timestamp, and details
- **Security Event Tracking** - Failed logins, permission changes, credential access
- **Export Capabilities** - CSV/JSON export for compliance
- **Real-time Monitoring** - Track user activity and system events

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
- **Export** - CSV/JSON export capabilities
- **Import** - Bulk import from CSV

## 🔑 Password Vault

### Password Storage
- **AES-GCM Encryption** - All passwords encrypted before storage
- **15 Password Types**:
  - Website Login
  - Email Account
  - Windows/Active Directory
  - Database
  - SSH Key
  - API Key
  - OTP/TOTP (2FA)
  - Credit Card
  - Network Device
  - Server/VPS
  - FTP/SFTP
  - VPN
  - WiFi Network
  - Software License
  - Other
- **Type-Specific Fields** - Relevant fields for each password type
- **Folder Organization** - Hierarchical folder structure
- **Password Reveal** - Secure reveal with audit logging

### Password Features
- **Secure Password Generator**:
  - Configurable length (8-128 characters)
  - Character type selection
  - Cryptographically secure randomness
- **Password Strength Meter** - Real-time strength calculation
- **Password Breach Detection** - HaveIBeenPwned integration with k-anonymity (NEW in v2.4.0):
  - Automatic breach checking against 600+ million compromised passwords
  - Privacy-first k-anonymity model: only 5 characters of SHA-1 hash transmitted
  - Zero-knowledge approach: passwords never leave your server
  - Configurable scan frequencies: 2, 4, 8, 16, or 24 hours per password
  - Visual security indicators: 🟢 Safe, 🔴 Compromised, ⚪ Unchecked
  - Real-time manual testing with "Test Now" button
  - Breach warning banners with detailed breach count display
  - Last checked timestamp tooltips
  - 24-hour response caching for performance
  - Graceful degradation if API unavailable
  - Optional blocking of breached passwords
  - Warning-only mode (default) with user notification
  - Comprehensive audit logging for all breach checks
  - Management command for bulk scanning
  - Scheduled scanning via systemd timers or cron
- **Expiration Tracking** - Set expiration dates with warnings
- **Auto-lock** - Passwords automatically masked
- **Copy to Clipboard** - One-click secure copy
- **TOTP Code Generation** - Built-in 2FA code generator with QR codes

### Personal Vault
- **User-Specific Encryption** - Each user has their own vault
- **Private Storage** - Not accessible by admins
- **Quick Notes** - Store personal credentials securely
- **Favorites** - Mark frequently used items

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

## 📋 Workflows & Process Automation (v2.24.155-159)

### Process/Workflow Management
- **Process Templates** - Create reusable workflow templates
- **Sequential Steps** - Multi-stage workflows with order tracking
- **Process Categories** - Organize by type (onboarding, offboarding, deployment, maintenance, incident, backup, security, change)
- **Global Processes** - Superuser-created templates available to all organizations
- **Organization Processes** - Org-specific custom workflows
- **Tagging System** - Organize workflows with custom tags
- **Published/Archived States** - Control workflow visibility
- **Template Mode** - Mark workflows as reusable templates for cloning

### Workflow Launch & Execution (v2.24.157-159)
- **One-Click Launch** - Prominent "Launch Workflow" button with rocket icon 🚀
- **Automatic Assignment** - Workflows automatically assigned to launcher (v2.24.159)
- **Launch Form** - Simple form with:
  - Due date (optional)
  - Notes (optional)
  - PSA ticket linking (optional)
  - Note visibility control (internal/public)
- **Execution Status** - Not Started, In Progress, Completed, Failed, Cancelled
- **Stage Completion** - Track which steps are complete
- **Due Date Tracking** - Set deadlines with overdue warnings
- **Progress Percentage** - Real-time completion tracking
- **Stage Requirements** - Mark stages as requiring confirmation
- **Estimated Duration** - Set time estimates per stage

### Execution List View (NEW in v2.24.158)
- **Complete Execution History** - View all workflow launches across organization
- **Advanced Filtering**:
  - Filter by status (Not Started, In Progress, Completed, Failed, Cancelled)
  - Filter by workflow
  - Filter by assigned user
- **Visual Dashboard**:
  - Color-coded status badges
  - Progress bars showing completion percentage
  - Overdue warnings for past-due workflows
  - PSA ticket associations displayed
- **Quick Actions**:
  - View execution details
  - View audit log
- **Sortable Columns** - Sort by workflow, status, assignee, start date, due date

### Comprehensive Audit Logging (v2.24.155)
- **Complete Activity Timeline** - Every action logged with timestamp and user
- **Audit Log Events**:
  - Workflow launched (who launched it, when)
  - Stage completed/uncompleted (who, when, with notes)
  - Status changes with before/after values
  - Notes updated
  - Due date changes
  - PSA ticket updates
- **Timeline View** - Chronological activity feed grouped by date
- **Action Details** - User, IP address, timestamp, description
- **Change History** - Old/new values stored in JSON for all updates
- **Color-Coded Events** - Visual indicators (green=completed, yellow=uncompleted, red=failed, blue=other)
- **Stage-Specific Tracking** - Links actions to specific workflow stages
- **Dual Logging** - Logs to both workflow-specific audit log and system-wide audit log

### PSA Ticket Integration (v2.24.155-156)
- **Ticket Linking** - Link workflow executions to PSA tickets at launch time
- **Automatic Updates** - Post completion summary to PSA ticket when workflow finishes
- **Note Visibility Control** (v2.24.156) - Choose whether completion notes are:
  - **Public** - Visible to customer (default)
  - **Internal** - Private, only visible to internal staff
- **Completion Summary** - Automatically posts to PSA ticket:
  - Workflow title and completion status
  - All completed steps with timestamps
  - User who completed each stage
  - Formatted for readability
- **Supported PSA Platforms**:
  - **ITFlow** - Full API integration with ticket comments
  - **ConnectWise Manage** - Service ticket notes with internal/public control
  - **Syncro** - Ticket comments with visibility control
  - (More providers: Autotask, HaloPSA - framework ready)
- **Error Handling** - PSA failures don't block workflow completion
- **Credential Security** - PSA credentials encrypted with AES-256-GCM

### Flowchart Generation
- **Auto-Generate Diagrams** - Convert workflows to draw.io flowcharts
- **Visual Workflow** - Rectangle nodes for steps, diamond nodes for decision points
- **One-Click Generation** - Generate/regenerate from workflow detail page
- **Color-Coded Stages** - Alternating colors for visual clarity
- **Automatic Layout** - Vertical flow with proper spacing

### Interactive Checklist Mode
- **Live Progress Tracking** - Check off stages as you complete them
- **Stage Completion** - AJAX-powered "Mark Complete" buttons
- **Stage Uncomplete** - Uncheck stages if needed (tracked in audit log)
- **Execution Lock** - Cannot modify completed executions
- **Real-Time Updates** - Progress bar updates immediately
- **Stage Notes** - Add notes when completing stages
- **Entity Linking** - Each stage can link to:
  - Knowledge base documents
  - Passwords/credentials
  - Secure notes
  - Assets
- **Quick Access** - View linked entities directly from execution view

### Workflow Features
- **Entity Linking Per Stage** - Link documents, passwords, secure notes, or assets to workflow steps
- **Required Confirmation** - Mark critical stages as requiring explicit confirmation
- **Stage Reordering** - Drag and drop to reorganize workflow steps
- **Bulk Stage Management** - Inline formsets for adding/editing multiple stages
- **Stage Descriptions** - Rich text instructions for each step
- **Progress Visualization** - Bootstrap progress bars with percentage display

## 🔌 PSA Integrations

### Supported PSA Platforms
All integrations fully implemented:

1. **ConnectWise Manage**
   - Companies, Contacts, Tickets
   - Projects, Agreements
   - API key authentication
   - Bidirectional sync

2. **Autotask PSA**
   - Companies, Contacts, Tickets
   - Projects, Agreements
   - API key + Secret authentication
   - Full CRUD operations

3. **HaloPSA**
   - Companies, Contacts, Tickets
   - OAuth2 authentication
   - Token refresh handling

4. **Kaseya BMS**
   - Companies, Contacts, Tickets
   - Projects, Agreements
   - Bearer token authentication

5. **Syncro**
   - Customers, Contacts, Tickets
   - API key authentication

6. **Freshservice**
   - Departments, Requesters, Tickets
   - Basic authentication

7. **Zendesk**
   - Organizations, Users, Tickets
   - Basic authentication with API token

### Integration Features
- **Automated Sync** - Scheduled synchronization via systemd timers
- **Manual Sync** - On-demand sync with force option
- **Field Mapping** - Flexible field mapping
- **Conflict Resolution** - Last-write-wins strategy
- **Error Handling** - Comprehensive error logging
- **Sync History** - Track sync operations
- **Test Connection** - Verify credentials before saving

### Organization Auto-Import (NEW in v2.12.0)
Automatically create and manage organizations from PSA companies during synchronization:
- **Auto-Create Organizations** - Automatically create HuduGlue organizations from PSA companies
- **Smart Duplicate Prevention** - Detects existing organizations by external ID to prevent duplicates
- **Configurable Settings**:
  - Enable/disable auto-import per connection
  - Set imported organizations as active or inactive
  - Add custom name prefix (e.g., "PSA-" or "CW-")
- **External ID Tracking** - Links organizations to PSA companies via custom_fields
- **Bulk Import** - Import all companies with statistics (created/updated/errors)
- **Audit Trail** - Full logging of all organization creates and updates
- **Update Sync** - Updates organization data when PSA company information changes

## 🖥️ RMM Integrations

### Supported RMM Platforms
**Phase 1 Infrastructure Complete (v2.24.x)** - Ready for provider implementations:

**Complete RMM Infrastructure:**
- **Base Models** - RMMConnection, RMMDevice, RMMAlert, RMMSoftware with full encryption
- **Provider Registry** - Extensible BaseRMMProvider abstract class for easy provider additions
- **Admin Interface** - Complete Django admin integration with connection testing
- **Database Schema** - Optimized migrations and indexes for performance
- **Sync Engine** - Scheduled synchronization with systemd timer support
- **Asset Mapping** - Automatic linking of RMM devices to HuduGlue assets

**Provider Implementations:**

1. **Tactical RMM** (Fully Implemented)
   - Complete device, site, and agent management
   - Real-time monitoring checks and alert integration
   - Comprehensive software inventory tracking
   - Token-based authentication with automatic refresh
   - WebSocket support for real-time updates
   - Full CRUD operations for all entity types

2. **NinjaOne** (Infrastructure Ready)
   - OAuth 2.0 authentication framework configured
   - Device management API endpoints mapped
   - Policy assignment structure in place
   - Monitoring and alert models ready
   - Ready for API implementation

3. **Datto RMM** (Infrastructure Ready)
   - API key authentication configured
   - Device inventory sync structure ready
   - Component tracking models in place
   - Alert integration endpoints mapped
   - Ready for API implementation

4. **Atera** (Infrastructure Ready)
   - API key authentication configured
   - Agent management framework ready
   - Ticket integration models in place
   - Alert and monitoring structure ready
   - Ready for API implementation

5. **ConnectWise Automate** (Infrastructure Ready)
   - API authentication configured
   - Computer management structure ready
   - Location tracking models in place
   - Script execution framework prepared
   - Ready for API implementation

### Integration Features
- **Automated Device Sync** - Scheduled synchronization via systemd timers (configurable intervals)
- **Manual Sync** - On-demand sync with force option and real-time feedback
- **Asset Mapping** - Automatic linking of RMM devices to asset records by serial number/hostname
- **Alert Management** - Import and track RMM alerts with severity levels and status
- **Software Inventory** - Track installed software per device with version tracking
- **Online Status Tracking** - Real-time monitoring of device connectivity and last-seen timestamps
- **Error Handling** - Comprehensive error logging with detailed debugging information
- **Sync History** - Complete audit trail of all sync operations with statistics
- **Test Connection** - Pre-save credential validation to ensure connectivity
- **Encrypted Credentials** - All API keys and tokens encrypted with AES-256-GCM
- **Multi-Connection Support** - Multiple RMM connections per organization
- **Provider Abstraction** - Unified interface across all RMM platforms

### Organization Auto-Import (NEW in v2.12.0)
Automatically create and manage organizations from RMM sites/clients during synchronization:
- **Auto-Create Organizations** - Automatically create HuduGlue organizations from RMM sites or clients
- **Smart Duplicate Prevention** - Detects existing organizations by external ID to prevent duplicates
- **Configurable Settings**:
  - Enable/disable auto-import per connection
  - Set imported organizations as active or inactive
  - Add custom name prefix (e.g., "RMM-" or "Tactical-")
- **External ID Tracking** - Links organizations to RMM sites via custom_fields
- **Bulk Import** - Import all sites with statistics (created/updated/errors)
- **Audit Trail** - Full logging of all organization creates and updates
- **Update Sync** - Updates organization data when RMM site information changes

## 🔔 Notifications & Alerts

### Alert Types
- **Website Downtime** - Immediate notifications
- **SSL Expiration** - Configurable warning periods
- **Domain Expiration** - Renewal reminders
- **Password Expiration** - Credential renewal reminders

### Notification Channels
- **Email** - SMTP integration
- **Webhooks** - Custom webhook endpoints
- **In-App** - Dashboard notifications

## 📊 Reporting & Analytics

### Audit Reports
- **Activity Statistics** - User activity metrics
- **Security Events** - Failed logins, unauthorized access
- **Resource Usage** - Asset, password, document counts
- **Export Options** - CSV, JSON formats

### System Reports
- **Organization Statistics** - Per-organization metrics
- **User Activity** - Login history, actions performed
- **Integration Status** - PSA sync status
- **System Health** - Database, disk, performance metrics

## 🔧 Administration

### System Settings
- **Site Configuration** - Site name, URL, timezone
- **Security Settings** - Session timeout, 2FA enforcement, password policies
- **SMTP Settings** - Email configuration with encrypted credentials
- **Maintenance Mode** - Enable maintenance with custom message
- **System Status** - View system health and metrics

### Database Management
- **Optimize Database** - Table optimization
- **Analyze Tables** - Query optimization
- **Backup Management** - Database backup tools
- **Migration Tools** - Version upgrades

### User Management
- **User Creation** - Create users with roles
- **Bulk Operations** - Import/export users
- **User Suspension** - Temporarily disable accounts
- **Password Reset** - Admin-initiated resets
- **2FA Management** - Reset user 2FA

## 🔗 API

### REST API
- **Full CRUD** - All resources via API
- **Authentication Methods**:
  - API Keys (HMAC-SHA256)
  - Session authentication
- **Rate Limiting** - Protect against abuse
- **Versioning** - API version management

### API Endpoints
- Organizations
- Users & Memberships
- Assets & Asset Types
- Passwords (with secure reveal)
- Documents
- Contacts
- PSA Integrations
- Website Monitors
- Audit Logs

### API Features
- **Pagination** - Efficient data retrieval
- **Filtering** - Query parameters
- **Sorting** - Flexible sorting options
- **Field Selection** - Select specific fields
- **Bulk Operations** - Multiple resources at once

## 📱 User Interface

### Design
- **Bootstrap 5** - Modern, responsive design
- **Dark Mode** - Theme toggle with persistence
- **Mobile Responsive** - Works on all devices
- **DataTables** - Sortable, searchable tables
- **Tooltips** - Helpful hints throughout
- **Progress Indicators** - Visual feedback

### Navigation
- **Breadcrumbs** - Easy navigation
- **Quick Search** - Global search
- **Recent Items** - Quick access to recent resources
- **Favorites** - Star important items

### Accessibility
- **Keyboard Navigation** - Full keyboard support
- **ARIA Labels** - Screen reader compatible
- **High Contrast** - Accessible color schemes
- **Semantic HTML** - Proper HTML structure

## 🛠️ Developer Features

### Extensibility
- **Django Apps** - Modular architecture
- **Plugin System** - Extend functionality
- **Custom Fields** - Add fields to models
- **Hooks** - Pre/post action hooks
- **Templates** - Customizable templates

### Development Tools
- **Management Commands** - CLI utilities
- **Seed Data** - Demo data generation
- **Test Suite** - Comprehensive tests
- **Debug Toolbar** - Development debugging
- **API Documentation** - Interactive API docs

## 🔄 Data Management

### Import/Export
- **CSV Import** - Bulk import from CSV
- **JSON Export** - Export data as JSON
- **Backup/Restore** - Full data backup
- **Migration Tools** - Migrate from other platforms

### Data Integrity
- **Validation** - Comprehensive data validation
- **Constraints** - Database-level constraints
- **Transactions** - ACID compliance
- **Rollback** - Error recovery

## 🚀 Performance

### Optimization
- **Database Indexing** - Optimized queries
- **Query Optimization** - Efficient ORM usage
- **Caching** - Strategic caching
- **Lazy Loading** - Load data on demand
- **Pagination** - Efficient data display

### Scalability
- **Horizontal Scaling** - Load balancing support
- **Database Replication** - Read replicas
- **Static File CDN** - CDN integration
- **Asset Optimization** - Minified CSS/JS

## 📦 Deployment

### Installation
- **One-Command Install** - Automated bootstrap script
- **Docker Support** - Containerized deployment
- **systemd Integration** - Service management
- **Nginx Configuration** - Production-ready config

### Maintenance
- **Zero-Downtime Updates** - Rolling updates
- **Automated Backups** - Scheduled backups
- **Log Rotation** - Automated log management
- **Health Checks** - Automated monitoring

---

**All features developed with assistance from Luna the GSD 🐕**
