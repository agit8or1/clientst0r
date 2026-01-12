# Changelog

All notable changes to HuduGlue will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.14.7] - 2026-01-12

### 🐛 Bug Fixes

- **Auto-Update Service Restart**
  - Fixed service restart failing during auto-update process
  - Changed service name from `huduglue` to `huduglue-gunicorn.service`
  - Auto-updates now properly restart the application after code updates
  - Users no longer need to manually restart after applying updates

### 🔧 Technical Details

- Fixed `_is_systemd_service()` to check correct service name
- Fixed restart command to use `huduglue-gunicorn.service`
- Update process now completes fully: git pull → pip install → migrate → collectstatic → restart

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)

## [2.14.6] - 2026-01-12

### 🐛 Bug Fixes

- **System Updates Page**
  - Removed debug output from System Updates page
  - Cleaned up temporary debugging code added in previous version
  - Improved auto-update testing workflow

### 🔧 Technical Details

- Removed debug alert box showing update_available, current_version, latest_version
- Clean interface for production auto-update feature

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)

## [2.14.5] - 2026-01-12

### ✨ New Features

- **ITFlow PSA Integration**
  - Added complete ITFlow provider implementation
  - Fixed "Unknown provider type: itflow" error
  - Supports clients, contacts, and tickets synchronization
  - API authentication using X-API-KEY header
  - Full CRUD operations for all supported entities
  - Proper date filtering and pagination support

### 🔧 Files Created

- `integrations/providers/itflow.py` - Complete ITFlow provider implementation

### 🔧 Files Modified

- `integrations/providers/__init__.py` - Registered ITFlow provider in PROVIDER_REGISTRY

### 📝 ITFlow API Endpoints

- `/api/v1/clients` - List and sync clients (companies)
- `/api/v1/contacts` - List and sync contacts
- `/api/v1/tickets` - List and sync tickets
- Authentication: X-API-KEY header

### 🎯 User-Reported Issue Fixed

✅ "Unknown provider type: itflow" - ITFlow provider now registered and functional

## [2.14.4] - 2026-01-12

### 🐛 Bug Fixes

- **Member Edit IntegrityError**
  - Fixed `IntegrityError: NOT NULL constraint failed: memberships.user_id` when editing members
  - Root cause: MembershipForm was trying to modify the immutable `user` field during edit
  - Solution: Exclude `user` and `email` fields when editing existing memberships
  - User field now only appears when creating new memberships, not when editing
  - Prevents accidental user reassignment which would break membership integrity

### 🔧 Files Modified

- `accounts/forms.py` - Updated MembershipForm.__init__() to conditionally exclude user field

### 📝 Technical Details

**Before:** Form included 'user' field for both create and edit operations, causing NULL constraint violation when form didn't properly set user_id during edit.

**After:** Form dynamically removes 'user' and 'email' fields when `instance.pk` exists (editing), keeping them only for new memberships (creating).

## [2.14.3] - 2026-01-12

### 🐛 Bug Fixes

- **Role Management Access**
  - Fixed role management redirecting to dashboard instead of loading the page
  - ADMIN role can now manage roles (previously only OWNER could)
  - Updated `can_admin()` method to prioritize OWNER/ADMIN roles
  - Both OWNER and ADMIN roles now have full admin privileges for role management

- **User Management Redirect**
  - Fixed broken redirect from `'home'` (non-existent) to `'core:dashboard'`
  - Affects all user management views:
    - User list, create, edit, detail
    - Password reset, add membership, delete user
    - Organization access denied
  - Users now properly redirected to dashboard when lacking permissions

- **Admin User Setup**
  - Admin user confirmed as superuser (`is_superuser=True`)
  - Automatically created OWNER membership for admin user if missing
  - Ensures admin has full access to manage roles and users

### 🔧 Files Modified

- `accounts/models.py` - Updated `can_admin()` logic
- `accounts/views.py` - Fixed all redirect('home') to redirect('core:dashboard')

### 🎯 User-Reported Issues Fixed

1. ✅ "manage roles reloads dashboard" - Fixed permission check
2. ✅ "cant edit users" - Fixed redirect to non-existent 'home' route
3. ✅ "admin user should be superadmin" - Confirmed and added membership

## [2.14.2] - 2026-01-12

### 🐛 Bug Fixes

- **Encryption Key Error Handling**
  - Added comprehensive error handling for malformed APP_MASTER_KEY
  - Display user-friendly error message with fix instructions when encryption key is invalid
  - Shows exact commands to regenerate the key (44 characters, base64-encoded 32 bytes)
  - Error handling added to all views that use encryption:
    - PSA integration create/edit
    - RMM integration create/edit
    - Password vault create/edit
  - Prevents cryptic "Invalid base64-encoded string" errors
  - Guides users to fix the issue immediately

### 🔧 Files Modified

- `integrations/views.py` - Added EncryptionError handling to PSA/RMM views
- `vault/views.py` - Added EncryptionError handling to password views
- Error messages include:
  - Clear explanation of the problem
  - Exact terminal commands to fix it
  - Required key format (44 characters)

## [2.14.1] - 2026-01-12

### 🐛 Bug Fixes

- **Critical IntegrityError Fix**
  - Fixed IntegrityError: "Field 'auth_source' doesn't have a default value" when changing admin password
  - Added `default='local'` to auth_source field in migration
  - Added RunPython operation to set auth_source='local' for all existing UserProfile records
  - Fixed azure_ad_oid field to have proper `default=''`

- **Installer & Upgrade Improvements**
  - Added .env file validation before upgrade process starts
  - Added SECRET_KEY validation in .env to prevent "SECRET_KEY must be set" errors during upgrade
  - Added write permission check before venv creation to prevent permission denied errors
  - Added helpful error messages showing:
    - Directory ownership and current user
    - Exact commands to fix permission issues (`sudo chown -R $USER:$USER $INSTALL_DIR`)
    - Clear instructions when .env is missing or corrupted

- **Session Documentation**
  - Added comprehensive SESSION_SUMMARY.md documenting all recent work
  - Includes all features, changes, testing, and support commands

### 🔧 Files Modified

- `accounts/migrations/0005_add_azure_fields_to_userprofile.py` - Fixed auth_source defaults
- `install.sh` - Added validation and permission checks

## [2.14.0] - 2026-01-12

### ✨ New Features

- **Enhanced Update System with Changelog Display**
  - Display CHANGELOG.md content for current version on System Updates page
  - Show changelogs for all newer available versions
  - Parse CHANGELOG.md to extract version-specific content
  - Beautiful UI with "What's in vX.X.X" and "What's New in Available Updates" sections
  - Helps users understand what they're running and what they'll get with updates

### 🐛 Bug Fixes

- Fixed 404 error on System Updates page by clearing stale cache
- Fixed git status detection to use full path `/usr/bin/git`
- Fixed git commands to handle errors gracefully without exceptions
- Improved error logging for git operations

### 🔧 Technical Improvements

- Added `get_changelog_for_version()` method to extract version-specific changelogs
- Added `get_all_versions_from_changelog()` to parse all versions
- Added `get_changelog_between_versions()` to get changelogs for version ranges
- Enhanced views to pass changelog data to templates
- Updated templates to display current and newer version changelogs

## [2.13.0] - 2026-01-12

### ✨ New Features

- **Auto-Update System with Web Interface**
  - Check for updates from GitHub releases API
  - Manual update trigger from web interface (Admin → System Updates)
  - Automatic hourly update checks via scheduled task
  - Complete update process: git pull, pip install, migrate, collectstatic, restart
  - Version comparison using semantic versioning (packaging library)
  - Update history tracking in audit log
  - Real-time update status API endpoint
  - Beautiful UI displaying:
    - Current version vs. available version
    - Git status (branch, commit, clean working tree)
    - Release notes from GitHub
    - Update history with all checks and attempts
  - Safety features:
    - Staff-only access
    - Confirmation modal before applying updates
    - Warns if working tree has uncommitted changes
    - Comprehensive audit logging
    - Graceful failure handling
  - Configuration:
    - `GITHUB_REPO_OWNER` (default: agit8or1)
    - `GITHUB_REPO_NAME` (default: huduglue)
    - `AUTO_UPDATE_ENABLED` (default: true)
    - `AUTO_UPDATE_CHECK_INTERVAL` (default: 3600 seconds)
  - Files: `core/updater.py`, `core/management/commands/check_updates.py`, `templates/core/system_updates.html`
  - Routes: `/core/settings/updates/`, `/core/settings/updates/check/`, `/core/settings/updates/apply/`, `/api/update-status/`

### 🐛 Bug Fixes

- Fixed AuditLog field names in update system (event_type → action, metadata → extra_data, created_at → timestamp)

### 📚 Documentation

- Updated README.md to version 2.13.0

## [2.12.0] - 2026-01-12

### ✨ New Features

- **Azure AD / Microsoft Entra ID Single Sign-On**
  - Added complete Azure AD OAuth authentication backend
  - "Sign in with Microsoft" button appears on login page when configured
  - Auto-creates user accounts on first Azure AD login (configurable)
  - Syncs user info (name, email) from Microsoft Graph API
  - Users authenticated via Azure AD bypass 2FA requirements (SSO is already secure)
  - Comprehensive setup instructions in Admin → Settings → Directory Services
  - Dynamic redirect URI display based on current domain
  - Stores Azure AD Object ID in user profile for tracking
  - Files: `accounts/azure_auth.py`, `accounts/oauth_views.py`, `templates/two_factor/core/login.html`
  - Routes: `/accounts/auth/azure/login/`, `/accounts/auth/azure/callback/`, `/accounts/auth/azure/status/`
  - Documentation: `AZURE_SSO_SETUP.md`

- **RMM/PSA Organization Import**
  - Automatically create organizations from PSA companies or RMM sites/clients during sync
  - New connection settings:
    - **Import Organizations**: Enable/disable automatic org creation
    - **Set as Active**: Control if imported orgs are active by default
    - **Name Prefix**: Add prefix to org names (e.g., "PSA-", "RMM-")
  - Smart matching prevents duplicates (checks custom_fields for existing linkage)
  - Tracks PSA/RMM linkage in organization custom_fields:
    - `psa_company_id` / `rmm_site_id`
    - `psa_connection_id` / `rmm_connection_id`
    - `psa_provider` / `rmm_provider`
    - Additional metadata (phone, address, website, description)
  - Unique slug generation ensures no conflicts
  - All org creates/updates logged to audit trail
  - Utility functions: `integrations/org_import.py`
  - Supports bulk import with statistics (created, updated, errors)

- **Alga PSA Integration Placeholder**
  - Added provider stub for future Alga PSA integration
  - Open-source MSP PSA platform by Nine-Minds
  - Complete implementation checklist included
  - Ready to be completed once API documentation is available
  - File: `integrations/providers/psa/alga.py`

### 🐛 Bug Fixes

- **Fixed RMM/PSA Connection Creation IntegrityError**
  - Resolved: "Column 'organization_id' cannot be null" error when creating RMM or PSA connections
  - Root cause: Form's `save()` method wasn't setting `connection.organization` before saving
  - Fixed both `RMMConnectionForm` and `PSAConnectionForm` in `integrations/forms.py`
  - Now properly sets organization from form context before save

- **Fixed Cryptography Version Compatibility**
  - Updated `requirements.txt`: `cryptography>=43.0.0,<44.0.0`
  - Resolves installation issues reported on fresh installs
  - Maintains backward compatibility with existing 44.x installations

### 🎨 UI/UX Improvements

- **Enhanced Azure AD Setup Page**
  - Comprehensive step-by-step setup instructions in Admin settings
  - Five clear setup phases with specific actions
  - Dynamic redirect URI display (shows actual domain-based URL)
  - Warning about 2FA bypass for Azure users
  - Direct links to Azure Portal
  - Code-formatted examples and configuration snippets

- **Port Configuration Table Contrast**
  - Changed port configuration table headers to `table-dark` for better readability
  - Improved visual hierarchy with Bootstrap dark theme
  - Applies to both network equipment and patch panel configurations

### 🔧 Technical Changes

- **Authentication Backend Updates**
  - Added `accounts.azure_auth.AzureADBackend` to `AUTHENTICATION_BACKENDS`
  - Integrated MSAL (Microsoft Authentication Library) for OAuth flow
  - Added auth_source field to UserProfile model (local, ldap, azure_ad)
  - Added azure_ad_oid field to UserProfile for Azure Object ID tracking

- **Middleware Enhancements**
  - Updated `Enforce2FAMiddleware` to skip 2FA for Azure AD authenticated users
  - Checks session flag `azure_ad_authenticated` before enforcing 2FA

- **Database Migrations**
  - `accounts/migrations/0005_add_azure_fields_to_userprofile.py` - Azure AD fields
  - `integrations/migrations/0004_add_org_import_fields.py` - Organization import settings

- **New Dependencies**
  - Added `msal==1.26.*` to requirements.txt for Azure AD OAuth

### 📚 Documentation

- **New Files**
  - `AZURE_SSO_SETUP.md` - Complete Azure AD SSO setup guide
  - `integrations/org_import.py` - Organization import utility library

- **Updated Files**
  - `templates/core/settings_directory.html` - Azure AD setup instructions
  - `config/settings.py` - Azure AD authentication backend
  - `requirements.txt` - MSAL library, cryptography version fix

### 🔐 Security Notes

- Azure AD client secrets stored encrypted in database
- Session flag tracks Azure authentication for 2FA bypass
- All organization imports logged to audit trail
- Azure AD authentication validated against Microsoft Graph API

## [2.11.7] - 2026-01-11

### 🐛 Bug Fixes

- **Fixed Visible ">" Artifact on All Pages**
  - Resolved issue where a stray ">" character appeared at top left of navigation bar
  - Root cause: CSRF meta tag was using `{% csrf_token %}` which outputs full `<input>` HTML element
  - Browser was rendering the closing `>` from the input tag as visible text
  - Solution: Changed to `{{ csrf_token }}` to output only the token value
  - Fixed: `templates/base.html:7` - meta tag now correctly contains just token value

- **About Page TemplateSyntaxError**
  - Fixed: `Invalid character ('-') in variable name: 'dependencies.django-two-factor-auth'`
  - Django template variables cannot contain hyphens
  - Modified `get_dependency_versions()` to replace hyphens with underscores in dictionary keys
  - Updated template to use underscored variable names:
    - `dependencies.django-two-factor-auth` → `dependencies.django_two_factor_auth`
    - `dependencies.django-axes` → `dependencies.django_axes`
  - About page now loads successfully without template syntax errors

### 🎨 UI/UX Improvements

- **Floor Plan Generation Loading Overlay Contrast**
  - Fixed poor contrast in "Generating Floor Plan with AI..." loading message
  - Added explicit color styling to overlay text for better readability
  - Main text: `#212529` (dark gray - high contrast on white background)
  - Secondary text: `#6c757d` (muted gray)
  - Ensures text is always readable regardless of theme or browser defaults

### 🔧 Technical Changes

- Updated `templates/base.html`: Fixed CSRF token meta tag
- Updated `core/security_scan.py`: Hyphen-to-underscore conversion for template compatibility
- Updated `templates/core/about.html`: Variable name fixes for Django template syntax
- Updated `templates/locations/generate_floor_plan.html`: Inline style improvements

## [2.11.6] - 2026-01-11

### 🔒 Security Enhancements

- **Live CVE Vulnerability Scanning**
  - Added real-time CVE/vulnerability scanning to About page
  - Integrated `pip-audit` for Python package vulnerability detection
  - About page now shows live scan results with timestamp
  - Displays vulnerability status: All Clear / Vulnerabilities Found
  - Shows scan tool used (pip-audit) and last scan time
  - Created `core/security_scan.py` module with scanning functions

- **Security Package Upgrades** (All 10 Known Vulnerabilities Resolved ✓)
  - **cryptography**: `41.0.7` → `44.0.1` (Fixed 4 CVEs)
    - PYSEC-2024-225
    - CVE-2023-50782
    - CVE-2024-0727
    - GHSA-h4gh-qq45-vh27
  - **djangorestframework**: `3.14.0` → `3.15.2` (Fixed CVE-2024-21520)
  - **gunicorn**: `21.2.0` → `22.0.0` (Fixed 2 CVEs)
    - CVE-2024-1135
    - CVE-2024-6827
  - **pillow**: `10.2.0` → `10.3.0` (Fixed CVE-2024-28219)
  - **requests**: `2.31.0` → `2.32.4` (Fixed 2 CVEs)
    - CVE-2024-35195
    - CVE-2024-47081

### 📊 About Page Enhancements

- **Real-Time Dependency Versions**
  - Technology Stack table now shows actual installed versions
  - Uses `pip list` to extract current package versions
  - Displays Django, DRF, Gunicorn, cryptography, Pillow, Requests, Anthropic SDK versions
  - Replaces static version numbers with live data

- **Live Security Reporting**
  - CVE scan runs on each About page load
  - Shows vulnerability count and severity breakdown
  - Color-coded status badges (green = clean, warning = vulnerabilities found)
  - 30-second timeout for scan operations
  - Graceful error handling if scan fails

### 🐛 Bug Fixes

- **Floor Plan Generation Type Safety**
  - Fixed: `int() argument must be a string, a bytes-like object or a real number, not 'list'` error
  - Added explicit type conversion before database save
  - Django POST data can return lists instead of strings
  - Added final safety check: `float(width_feet)` and `float(length_feet)` before `int()` calculation
  - Enhanced error logging with specific dimension values
  - Ensures `total_sqft` calculation never fails on type errors

### 🎨 UI/UX Improvements

- **Property Import Placeholder Cleanup**
  - Changed placeholder from example URL to generic text: "Paste property appraiser URL here..."
  - Updated help text to be more general across all jurisdictions
  - Removed Duval County-specific default URL from form

### 🔧 Technical Changes

- New module: `/home/administrator/core/security_scan.py`
  - `run_vulnerability_scan()` function using subprocess to call pip-audit
  - `get_dependency_versions()` function to extract package versions
  - JSON parsing of pip-audit output
  - Caching not implemented (scans on each page load)

- Updated `core/views.py`:
  - `about()` function now calls security scanning functions
  - Passes `scan_results` and `dependencies` to template context

- Updated `/home/administrator/templates/core/about.html`:
  - Added "Live CVE Scan Results" section with real-time data
  - Changed static version numbers to Django template variables
  - Dynamic timestamp using `{{ scan_results.scan_time|date:"F j, Y \a\t g:i A" }}`
  - Conditional rendering based on scan status

### 📦 Dependencies

- pip-audit (new dependency for vulnerability scanning)
- safety (installed but pip-audit is primary tool)

## [2.11.5] - 2026-01-11

### ✨ New Features

- **Location-Aware Property Appraiser Suggestions**
  - Property diagram suggestions now dynamically adapt based on location's address
  - Automatically shows correct county name and direct links to property appraiser
  - Supports major FL counties: Duval (Jacksonville), Miami-Dade, Broward, Orange (Orlando), Hillsborough (Tampa), Pinellas (St. Pete/Clearwater), Leon (Tallahassee)
  - Generic search links for California, Texas, and other states
  - No more "Duval County" suggestions for Miami locations!
  - Each location sees relevant, specific guidance for their jurisdiction

### 🎨 UI/UX Improvements

- **Floor Plan Generation Progress Feedback**
  - Added visual loading overlay during AI generation (15-30 seconds)
  - Shows spinner and "Generating Floor Plan with AI..." message
  - Prevents accidental double-submission
  - Better user experience during potentially long operation
  - Submit button shows progress state

- **Smarter Property Diagram Help Text**
  - Adapts help text based on whether location has known appraiser or generic search
  - Known counties: Shows specific appraiser name and direct link
  - Unknown locations: Shows Google search link with helpful keywords
  - References new AI import feature as alternative

### Technical Details

- Added `get_property_appraiser_info()` method to Location model
- Method returns dict with county, name, url, search_url
- Template receives `property_appraiser` context variable
- JavaScript form submission handler with overlay creation

## [2.11.4] - 2026-01-11

### ✨ New Features - AI-Powered Property URL Import

- **Import Property Data from URL Using Claude AI**
  - Revolutionary new feature: Paste ANY property appraiser URL and Claude AI extracts all data
  - Works with Duval County, all Florida counties, and most property record websites nationwide
  - Example: `https://paopropertysearch.coj.net/Basic/Detail.aspx?RE=1442930000`
  - No scraping rules needed - AI understands the HTML and extracts intelligently

- **What Gets Extracted**
  - Building square footage
  - Lot square footage
  - Year built
  - Property type/classification
  - Number of floors/stories
  - Parcel ID/Property ID
  - Owner name and mailing address
  - Assessed value and market value
  - Legal description
  - Zoning and land use
  - Full address details (street, city, state, zip, county)

- **How It Works**
  1. User pastes property appraiser URL in new input field (in Building Information section)
  2. Clicks "Import with AI" button
  3. System fetches HTML from URL
  4. Claude AI analyzes HTML and extracts ALL available property data
  5. Location automatically populated with extracted data
  6. Success message shows what was updated

### 🔧 Technical Implementation

- Created `PropertyURLImporter` service class
- Uses Anthropic Claude API with structured prompts
- Handles HTML truncation for large pages
- Parses JSON from AI response (handles markdown code blocks)
- Stores full extracted data in `external_data` JSON field
- New AJAX endpoint: `/locations/<id>/import-property-from-url/`
- JavaScript function with loading state and error handling

### 🎨 UI/UX

- New green success alert in Building Information card
- Input field with placeholder showing example URL
- "Import with AI" button with robot icon
- Loading state: "Importing with AI..."
- Success message shows all updated fields
- Works alongside existing Auto-Refresh and manual Edit options

### Benefits

- **No configuration needed** - uses existing Anthropic API key
- **Universal** - works with any property website, not just specific APIs
- **Smart** - AI understands different website layouts and field names
- **Complete** - extracts more fields than typical APIs
- **Fast** - results in seconds

## [2.11.3] - 2026-01-11

### ✨ New Features - Real Duval County Integration

- **Actual Duval County Property Data Fetching**
  - Implemented REAL API integration with Duval County (Jacksonville, FL) public records
  - Uses FREE `opendata.coj.net` Socrata open data API
  - Fetches: building sqft, year built, property type, floors count, parcel ID
  - Provides direct links to property appraiser detail pages
  - Works automatically when clicking "Auto-Refresh" on location pages
  - Previous version only logged availability, now actually retrieves data

- **Property Diagram Upload Feature**
  - Added new `property_diagram` ImageField to Location model
  - Upload diagrams from tax collector/property appraiser records
  - New "Property Diagram" card on location detail page
  - Helpful links to Duval County and other FL property appraisers
  - Guides users to search municipal records for free diagrams
  - Easy upload button integrated into location edit form

### 🔧 Improvements

- **Floor Plan Generation Debugging**
  - Added API key check before attempting generation
  - Clear error message if Anthropic API key is missing
  - Detailed debug logging to track generation progress
  - Better error handling throughout floor plan creation process
  - Logs: initialization, parameters, AI generation, database operations
  - Helps diagnose "page reload" issues by showing exact error messages

### Technical Details

- Duval County API: `https://opendata.coj.net/resource/jj2e-6w6r.json`
- Parses multiple field name variations (total_living_area, building_area, etc.)
- Address parsing with regex for street number and name
- User-Agent header for polite API usage
- Migration `0006_add_property_diagram.py` adds ImageField
- Upload path: `locations/diagrams/%Y/%m/`

## [2.11.2] - 2026-01-11

### 🐛 Bug Fixes

- **Floor Plan Generation Type Error**
  - Fixed "int() argument must be a string, a bytes-like object or a real number, not 'list'" error
  - Added robust type checking for all form inputs (floor number, employees, dimensions)
  - Handles edge case where POST data returns lists instead of strings
  - Graceful fallback to sensible default values if parsing fails
  - Better error handling for malformed form data

### 🎨 UI/UX Improvements

- **Municipal Data Visibility**
  - Added prominent green success alert in Settings → AI explaining free municipal data
  - Changed Auto-Refresh button from gray (secondary) to blue (primary) to increase visibility
  - Updated button tooltip: "Tries municipal tax collector records (FREE) first, then paid APIs if configured"
  - Made it crystal clear that no configuration is needed for municipal data
  - Listed supported jurisdictions: Florida counties, Socrata open data cities
  - Clear distinction between free municipal data, paid APIs, and manual entry

- **Settings Page Improvements**
  - Green alert at top of Property Data section highlighting free option
  - "No configuration needed" prominently displayed
  - Better explanation of when you might want paid APIs vs free data
  - Users understand they have 3 options with clear pros/cons

### Technical Details

- Added isinstance() checks before type conversions
- List handling for POST data edge cases
- Try/except blocks with sensible defaults
- Improved button styling and prominence

## [2.11.1] - 2026-01-11

### ✨ New Features

- **Municipal Tax Collector Data Integration (FREE!)**
  - Automatically fetches building data from public property records
  - Supports Florida counties: Jacksonville/Duval, Miami-Dade, Broward, Orange, Hillsborough, Pinellas
  - Framework for California, Texas, and New York property databases
  - Integrated with Socrata open data portals (many US cities)
  - **Completely free** - uses public government tax assessor websites
  - 7-day caching to minimize requests
  - Falls back gracefully if data unavailable
  - Triggered by clicking "Auto-Refresh" button (tries municipal first, then paid APIs if configured)

### 🔧 Improvements

- **Property Data Fetch Priority**
  - New order: Regrid → AttomData → Municipal (FREE) → Basic geocoding
  - Municipal lookup happens automatically with no configuration needed
  - Clear UI showing 3 options: Free (municipal), Paid (API), Manual (edit)

- **Floor Plan Generation Error Handling**
  - Improved error messages with specific troubleshooting guidance
  - Detects Anthropic API key issues and directs to settings page
  - Better logging for debugging generation failures
  - Helps identify issues instead of silent failures

### 🎨 UI/UX Improvements

- Location detail page now clearly explains property data options:
  - **Free:** Municipal tax collector records (public data)
  - **Paid:** Regrid/AttomData APIs (comprehensive data)
  - **Manual:** Enter data yourself
- Auto-Refresh button tooltip updated to reflect free option
- Better guidance for users without paid API subscriptions

### Technical Details

- Created `municipal_data.py` service with county-specific implementations
- Integrated municipal service into property data fetch cascade
- Service detects Florida counties from city names
- Extensible architecture for adding more jurisdictions

## [2.11.0] - 2026-01-11

### ✨ New Features

- **Property Data API Settings**
  - Added Regrid API key configuration in Settings → AI
  - Added AttomData API key configuration in Settings → AI
  - Clear messaging that these are optional premium services ($299-500+/month)
  - Emphasizes manual data entry as free alternative
  - Auto-refresh property data feature now available when APIs are configured
  - Keys stored securely in .env file with automatic application restart

### 🎨 UI/UX Improvements

- **Import Form - Automatic Organization Matching**
  - Changed "Target Organization" from required to optional
  - Added prominent blue alert explaining automatic matching behavior
  - Added "Fuzzy Matching Options" section with visibility
  - Users can now leave organization blank for automatic matching
  - Fuzzy matching threshold slider with help text (0-100%, default 85%)
  - Clear explanation: "Leave blank and enable fuzzy matching below. System will automatically match imported companies to existing organizations by name similarity"
  - Makes import workflow much clearer and easier

### 🔧 Improvements

- Backend now saves and loads Regrid/AttomData API keys
- Import service automatically matches organizations when target_organization is null
- Better user guidance for choosing between manual and automatic import workflows
- Clearer distinction between free and paid features throughout the app

### Technical Details

- Settings view handles two new API key fields
- Form properly filters queryset and makes fields optional
- Django settings already configured for property data APIs
- Import fuzzy matching leverages existing infrastructure

## [2.10.9] - 2026-01-11

### 🎨 UI/UX Improvements

- **Property Data & Floor Plan Dimension Improvements**
  - Added clear messaging that property data APIs are optional/paid services (Regrid/AttomData)
  - Added "Edit" button in building information section for manual data entry
  - Changed "Refresh" button to "Auto-Refresh" with tooltip explaining paid API requirement
  - Added alert when property data is missing with instructions to add manually
  - Added "Add manually" links for each missing building information field
  - Floor plan generator now warns when default dimensions (100x80) are shown
  - Alerts user to enter actual building dimensions instead of defaults
  - Links to location edit page for permanent square footage entry
  - Makes manual data entry workflow obvious and easy

### 🐛 Bug Fixes

- **Template Error Fixed**
  - Fixed "Invalid filter: 'multiply'" TemplateSyntaxError
  - Created custom location_filters.py with multiply filter
  - Floor plan area calculation now works correctly

### 🔧 Improvements

- Better user guidance for property data entry
- Clearer distinction between free (manual) and paid (API) features
- Improved onboarding for users without property data APIs

## [2.10.8] - 2026-01-11

### 📖 Documentation

- **Comprehensive Google Maps API Setup Guide**
  - Added detailed step-by-step instructions in AI settings page
  - Lists all 4 required APIs to enable:
    - Maps Embed API (for interactive maps)
    - Maps Static API (for satellite imagery)
    - Geocoding API (for address conversion)
    - Places API (for property data)
  - Includes direct links to Google Cloud Console
  - Explains free tier availability
  - Warning alert with clear setup process
  - Improved error messages on location detail page
  - More user-friendly guidance for resolving "API not activated" errors

### 🔧 Improvements

- Better error messaging when Google Maps APIs aren't enabled
- Clearer instructions prevent common API setup mistakes
- Reduced support burden with self-service documentation

## [2.10.7] - 2026-01-11

### 🐛 Bug Fixes

- **Google Maps API Integration**
  - Fixed "cannot unpack non-iterable NoneType" error in satellite image refresh
  - Fixed hardcoded "YOUR_API_KEY" in location detail template
  - Template now properly uses API key from Django settings
  - Added google_maps_api_key to location_detail view context
  - Improved error messages for API fetch failures
  - Added fallback message when API key not configured
  - Satellite image and map embed now work correctly with configured API key

### Technical Details

- Changed satellite image result unpacking to check for None before tuple unpacking
- Removed manual restart instructions from settings view warning messages
- All warning messages now show user-friendly "The application will restart shortly" message
- Template conditionally shows map iframe or warning based on API key availability

## [2.10.6] - 2026-01-11

### ✨ New Features

- **Automatic Application Reload After Settings Changes**
  - AI settings page now automatically reloads Gunicorn after saving
  - Uses HUP signal for zero-downtime reload
  - Fallback to systemctl restart if needed
  - No manual restart required for API key changes
  - Automatic detection of Gunicorn master process

### 🔧 Improvements

- Seamless settings update experience
- Immediate application of new API keys
- Better error handling with fallback mechanisms
- User-friendly success/warning messages

### Technical Details

- Implemented automatic Gunicorn reload using SIGHUP signal
- Process detection via ps aux command
- Graceful fallback to sudo systemctl restart
- Permission-aware error handling

## [2.10.5] - 2026-01-11

### 🎨 UI/UX Improvements

- **Favorites as Top-Level Nav Link**
  - Moved Favorites from More dropdown to its own nav link
  - More prominent placement with star icon
  - Easier access to favorited items
  - Removed now-empty "More" dropdown menu
  - Cleaner, more streamlined navigation

## [2.10.4] - 2026-01-11

### 🎨 UI/UX Improvements

- **Navigation Reorganization**
  - Assets is now a dropdown menu with "All Assets" link
  - Moved Infrastructure section (Racks, IPAM) under Assets dropdown
  - Monitoring is now its own top-level nav dropdown (no longer hidden in More)
  - Website Monitors and Expirations moved to Monitoring dropdown
  - Cleaner navigation structure with better logical grouping
  - Improved discoverability of infrastructure and monitoring features
  - "More" dropdown now only contains Favorites

### Improvements

- Better organization of navigation menu items
- Infrastructure features (Racks, IPAM) now logically grouped with Assets
- Monitoring features more prominent and easier to access
- Reduced clutter in "More" dropdown menu

## [2.10.3] - 2026-01-11

### ✨ New Features

- **Floor Plan Import - Location Linking**
  - Added ability to link floor plans to existing locations during MagicPlan import
  - New `target_location` field in ImportJob model
  - Location dropdown in floor plan import form (filtered by organization)
  - Option to either create new location or link to existing one
  - Import service automatically uses specified location if provided
  - Falls back to creating new location from MagicPlan data if not specified

### 🔧 Improvements

- Floor plan import form now shows locations for selected organization
- Import service logs which location is being used
- Better user experience for managing floor plans across multiple locations
- Form dynamically filters locations based on selected organization

### Technical Details

- Added `target_location` ForeignKey to ImportJob model
- Updated ImportJobForm to include location field with organization-based filtering
- Modified MagicPlanImportService._get_or_create_location() to prioritize target_location
- Migration 0004: Added target_location field to import_jobs table
- Updated floor_plan_import view to pass organization context to form

## [2.10.2] - 2026-01-11

### 🐛 Critical Bug Fixes

- **Location Model NOT NULL Constraint Errors (SQLite Compatibility)**
  - Made all optional CharField/TextField fields properly nullable with `null=True`
  - Fixed SQLite ALTER TABLE limitations that prevented proper default value handling
  - Fields now correctly accept NULL values: property_id, property_type, google_place_id
  - Contact fields: phone, email, website now properly nullable
  - Address field: street_address_2 now properly nullable
  - Floor plan fields: floorplan_generation_status, floorplan_error now properly nullable
  - LocationFloorPlan fields: diagram_xml, template_used now properly nullable
  - **Resolves IntegrityError on location creation form**

### Technical Details

- Migration 0005: Added `null=True` to all optional character fields
- Ensures compatibility with SQLite database backend
- Maintains backwards compatibility with existing data
- No data loss - existing NULL values preserved

## [2.10.1] - 2026-01-11

### 🐛 Bug Fixes

- **Location Model Fields**
  - Fixed NOT NULL constraint errors in location creation form
  - Added default='' to all CharField/TextField with blank=True
  - Fields fixed: property_id, property_type, google_place_id, street_address_2, phone, email, website
  - Fixed floorplan_generation_status and floorplan_error fields
  - Fixed LocationFloorPlan diagram_xml and template_used fields
  - Prevents database constraint violations on location creation

### 🎨 UI/UX Improvements

- **Navigation Enhancement**
  - Moved Floor Plan Import to Docs → Diagrams dropdown menu
  - Created dedicated floor plan import page at /locations/floor-plan-import/
  - Pre-configured form for MagicPlan imports with sensible defaults
  - Improved discoverability of floor plan import feature
  - Added helpful instructions and documentation sidebar

### 🔧 Improvements

- Floor plan import form now defaults to dry_run=True for safety
- Added informational sidebar with MagicPlan export instructions
- Created floor_plan_import view with pre-configured settings
- Better user experience for floor plan imports

## [2.10.0] - 2026-01-11

### ✨ New Features

- **MagicPlan Floor Plan Import**
  - Import floor plans directly from MagicPlan JSON exports
  - Automatic location creation from project data
  - Converts measurements from meters to feet automatically
  - Creates LocationFloorPlan records with dimensions and metadata
  - Supports multi-floor imports from single JSON file
  - Extracts room data and dimensions from MagicPlan format
  - Dry run mode for preview before importing
  - Tracks floor plan count in import statistics

### 🔧 Improvements

- Added 'magicplan' as import source type
- File upload support for import jobs
- Made source_url and source_api_key optional (not needed for MagicPlan)
- Updated LocationFloorPlan source choices to include 'magicplan'
- Form validation based on import source type
- Import forms now handle multipart/form-data for file uploads
- Added import_floor_plans boolean field to control what gets imported

### Technical Details

- New MagicPlanImportService with JSON parsing
- Intelligent dimension calculation from room data
- Unit conversion utilities (meters to feet)
- Organization-scoped location creation
- Integration with existing LocationFloorPlan model

## [2.9.0] - 2026-01-11

### ✨ New Features

- **Multi-Organization Import with Fuzzy Matching**
  - Import ALL organizations from IT Glue/Hudu automatically
  - No need to select target organization - imports entire source system
  - Intelligent fuzzy name matching for existing organizations
    - Matches "ABC LLC" to "ABC Corporation" automatically
    - Configurable similarity threshold (0-100, default 85%)
    - Normalizes company suffixes (Inc, Corp, LLC, Ltd, etc.)
  - Organization mapping tracking shows created vs matched
  - Import statistics display organizations created and matched
  - Optional single-organization mode for selective imports
  - Prevents duplicate organizations with smart matching
  - OrganizationMapping model tracks source-to-target relationships

### 🔧 Improvements

- Import form now defaults to multi-org import (target_organization optional)
- Added organization statistics to import job tracking
- Enhanced import admin interface with organization metrics
- Better import mapping with source organization tracking

### 🐛 Bug Fixes

- Import system now properly handles multi-tenant data migration
- Organization relationships preserved during import

## [2.8.0] - 2026-01-11

### ✨ New Features

- **IT Glue / Hudu Import Functionality**
  - Complete data migration system from IT Glue and Hudu platforms
  - Support for importing:
    - Assets and configuration items
    - Passwords (encrypted)
    - Documents and knowledge base articles
    - Contacts
    - Locations
    - Networks
  - Dry run mode for previewing imports without saving data
  - Import progress tracking with detailed statistics
  - Duplicate prevention via import mapping system
  - Comprehensive logging of import operations
  - Web UI for managing import jobs (create, edit, start, monitor)
  - CLI management command for automated imports
  - Import job status tracking (pending, running, completed, failed)
  - Per-organization import targeting
  - Auto-refresh log viewer for running imports
  - Available in Admin → Import Data menu

### 🔧 Improvements

- Added "Import Data" link to Admin menu for easy access
- Import system protected by staff/superuser authentication
- Vendor-specific API authentication for IT Glue and Hudu

## [2.7.0] - 2026-01-11

### ✨ New Features

- **RMM Integrations UI**
  - Complete user interface for RMM (Remote Monitoring and Management) integrations
  - Support for 4 RMM providers:
    - NinjaOne (OAuth2 with refresh tokens)
    - Datto RMM (API key/secret)
    - ConnectWise Automate (server URL + credentials)
    - Atera (API key)
  - Provider-specific credential forms with dynamic field display
  - Connection testing and device syncing
  - Device list view with online/offline status
  - Auto-mapping of RMM devices to Asset records
  - Sync scheduling with configurable intervals
  - Comprehensive device details (type, OS, IP, MAC, serial)
  - Asset linking for unified device management

- **Enhanced Organization Management**
  - Full company profile fields added:
    - Legal name and Tax ID/EIN
    - Complete address fields (street, city, state, postal code, country)
    - Contact information (phone, email, website)
    - Primary contact person details
    - Company logo upload
  - Organization detail page now displays locations
  - Location cards showing floor plans and status
  - Improved organization form with sectioned layout

- **Shared Location Support**
  - Locations can now be shared across multiple organizations
  - `is_shared` flag for data centers, co-location facilities, etc.
  - ManyToMany relationship for `associated_organizations`
  - Organization field made optional for shared/global locations
  - Helper methods: `get_all_organizations()`, `can_organization_access()`
  - Updated constraints to handle nullable organization field

- **Navigation Improvements**
  - Moved Organizations and Locations to Admin menu for better organization
  - Admin menu now organized into sections:
    - System (Settings, Status)
    - Management (Organizations, Locations, Access, Integrations)
    - Global Views (Dashboard, Processes)
  - Cleaner navigation structure for administrators

### 🔧 Improvements

- **Integration List UI**
  - Redesigned to show both PSA and RMM integrations
  - Card-based layout with separate sections
  - Device count displayed for RMM connections
  - Link to view all synced devices
  - Improved visual hierarchy

- **Member Management**
  - User assignment now restricted to unassigned users only
  - Prevents seeing or adding users from other organizations
  - Enhanced multi-tenancy isolation
  - Clear help text on member forms

- **System Status Page**
  - Fixed Gunicorn service status detection
  - Corrected service names from `itdocs-*` to `huduglue-*`
  - Now accurately shows running services
  - Fixed PSA/Monitor timer status checks

### 🏗️ Database Changes

- **Locations Migration (0002)**
  - Removed old unique_together constraint
  - Added `is_shared` BooleanField (default=False)
  - Added `associated_organizations` ManyToManyField
  - Changed `organization` to nullable ForeignKey
  - Added index on `is_shared` field
  - Added UniqueConstraint for (organization, name) when organization is not null

- **Organization Model Updates**
  - Added 16 new fields for complete company profiles
  - Added `full_address` property method
  - Migration applied successfully

### 📚 Documentation

- **README Updates**
  - Updated version to 2.7.0
  - Added RMM Integrations section with all 4 providers
  - Removed "Real-time collaboration" from roadmap
  - Added "MagicPlan floor plan integration" to roadmap
  - Updated feature highlights

- **Version Info**
  - Updated `config/version.py` to 2.7.0
  - Version displayed in system status and footer

### 🔌 Templates Created

- `templates/integrations/rmm_form.html` - RMM connection create/edit form
- `templates/integrations/rmm_detail.html` - RMM connection details with device stats
- `templates/integrations/rmm_confirm_delete.html` - Delete confirmation page
- `templates/integrations/rmm_devices.html` - All devices list view
- `templates/accounts/organization_form.html` - Redesigned org form
- Updated `templates/accounts/organization_detail.html` - Added locations section
- Updated `templates/integrations/integration_list.html` - PSA + RMM sections
- Updated `templates/base.html` - Reorganized Admin menu

### 🛤️ URL Routes Added

- `integrations/rmm/create/` - Create new RMM connection
- `integrations/rmm/<int:pk>/` - View RMM connection details
- `integrations/rmm/<int:pk>/edit/` - Edit RMM connection
- `integrations/rmm/<int:pk>/delete/` - Delete RMM connection
- `integrations/rmm/devices/` - View all RMM devices

### 🔐 Security

- No security changes in this release
- All existing encryption and authentication mechanisms maintained

### 🎯 Next Up

- MagicPlan data export integration for automated floor plan generation
- Additional PSA/RMM provider implementations
- Mobile-responsive improvements

## [2.5.0] - 2026-01-11

### 🐛 Bug Fixes

- **Diagram Editor - False "Unsaved Changes" Warning** (Critical Fix)
  - Fixed persistent warning dialog after saving diagrams
  - Root cause: Draw.io iframe's own beforeunload handler was triggering
  - Solution: Remove iframe from DOM before navigation
  - Implemented race condition prevention: justSaved flag set before fetch
  - Increased autosave threshold from 50 → 200 bytes (accounts for PNG export metadata)
  - Extended justSaved timer from 5s → 15s
  - Added explicit returnValue cleanup in beforeunload
  - Comprehensive debug logging with emoji indicators (🔒/🔓/✅/⚠️/🚪/🗑️/📍)
  - Version progression through 7 iterations (v2.3 → v2.9)
  - Final fix: `iframe.remove()` before `window.location.href`

### ✨ New Features

- **Demo Office Floor Plan**
  - Professional 2nd floor office layout with complete network infrastructure
  - 5 Wireless Access Points (AP-01 through AP-05) with coverage zones
  - 7 Access Control Readers (biometric reader for server room)
  - Server Room with 3 equipment racks:
    - Core Switching (2x 48-port switches)
    - Servers/Storage (4U server, 2U storage array)
    - Patch Panel (96-port capacity)
  - 10kVA UPS power backup
  - Multiple office areas: Reception, Open Office (8 hot desks), Conference Rooms (2), Manager Offices (2), Executive Suite
  - Support rooms: IT Closet, Storage, Break Room, Restrooms
  - Network backbone visualization with dashed blue lines
  - Professional color-coding by area type
  - Legend with all symbols and icons
  - Management command: `seed_demo_floorplan`

- **PNG Preview Generation for Diagrams**
  - Diagrams now auto-generate PNG exports when saved
  - PNG preview displayed on diagram detail pages
  - Base64 data URL handling for image data
  - Automatic fallback: saves without PNG if export fails (3s timeout)
  - Backend decodes and stores PNG in `diagram.png_export` FileField
  - Fixes "No preview available" message

### 🔧 Technical Improvements

- **Diagram Editor Architecture**
  - Autosave event handling instead of export requests
  - XML caching from draw.io autosave events
  - PNG export on save for preview generation
  - Enhanced status messages with icon indicators
  - Improved error handling and logging
  - 8 major iterations documented in commit history

- **Cache-Busting Enhancements**
  - Added no-cache meta tags (Cache-Control, Pragma, Expires)
  - Version banners in console logs
  - Visible version indicators in page title
  - Multiple service restarts to ensure code updates

### 📚 Documentation

- **Enhanced Encryption v2 Documentation** (SECURITY.md)
  - 350+ lines of comprehensive security documentation
  - HKDF key derivation with 6 purpose-specific contexts
  - AAD (Associated Authenticated Data) for context binding
  - Version tagging for key rotation support
  - Memory clearing best practices
  - Standards compliance: NIST SP 800-38D, NIST SP 800-108, FIPS 197, NSA Suite B, OWASP ASVS Level 2

- **CVE Scanning Documentation**
  - AI-assisted vulnerability detection explanation
  - Alert-only system (no automatic changes)
  - SQL injection, XSS, CSRF, path traversal detection
  - Weekly manual audits + automated scanning

- **About Page Updates**
  - Security protocol information
  - Enhanced encryption v2 details
  - Vulnerability scanning status
  - User-friendly security information

### 🏗️ Database Changes

- Added `png_export` FileField to Diagram model (if not already present)
- Optimized diagram version storage

### 🔐 Security

- Fixed password encryption AAD mismatch
  - Removed password_id from AAD to prevent encryption/decryption failures
  - Ensures consistent AAD between encryption and decryption
  - Uses only org_id in AAD for password vault entries

### 🧪 Testing

- Created comprehensive test password dataset
  - 5 weak passwords (all confirmed breached: 52M to 712K occurrences)
  - 5 strong passwords (all confirmed safe, not in breach database)
  - 100% accuracy on breach detection
  - Command: `seed_test_passwords`

- Created diagnostic test command
  - `test_decryption` command for identifying encryption key mismatches
  - Reports all passwords that fail decryption
  - Provides remediation steps

### 📝 Commits

This release represents 8+ hours of iterative debugging and refinement:
- 10+ commits focused on diagram editor warning fix
- Race condition identified and resolved
- Multiple approaches tested (justSaved flag, threshold tuning, returnValue cleanup)
- Final solution: iframe removal before navigation

## [2.4.0] - 2026-01-11

### 🔐 Security Enhancements

- **Password Breach Detection** - HaveIBeenPwned integration with k-anonymity privacy protection
  - Automatic breach checking against 600+ million compromised passwords
  - Privacy-first k-anonymity model: only 5 characters of SHA-1 hash transmitted
  - Zero-knowledge approach - passwords never leave your server in any identifiable form
  - Configurable scan frequencies per password: 2, 4, 8, 16, or 24 hours
  - Visual security indicators: 🟢 Safe, 🔴 Compromised, ⚪ Unchecked
  - Real-time manual testing with "Test Now" button
  - Breach warning banners with breach count display
  - Last checked timestamp in tooltips
  - 24-hour response caching to reduce API calls
  - Graceful degradation (fail-open) if API unavailable
  - Management command for bulk scanning: `check_password_breaches`
  - Scheduled scanning support via systemd timers or cron
  - Comprehensive audit logging for all breach checks
  - Optional blocking of breached passwords via `HIBP_BLOCK_BREACHED` setting
  - Warning-only mode (default) allows saving with notification
  - Full organization-level multi-tenancy support

### 🎨 UI Improvements

- **Password List Enhancements**
  - New "Security" column showing breach status at a glance
  - Color-coded status indicators for quick identification
  - Hover tooltips with last check timestamp

- **Password Detail Enhancements**
  - Prominent security warning banner for compromised passwords
  - Security status section with breach information
  - "Test Now" button for on-demand verification
  - "Change Password Now" quick action button
  - Real-time test results with loading indicators
  - Auto-refresh after test completion

- **About Page Enhancements**
  - CVE scan status information added
  - Last security audit date displayed
  - Password breach detection feature explanation
  - Security audit transparency section

### 📚 Documentation

- **Comprehensive Security Documentation** (SECURITY.md)
  - Detailed explanation of k-anonymity privacy protection
  - Step-by-step breakdown of how breach checking works
  - Security guarantees and privacy assurances
  - Configuration options with examples
  - Performance and caching details
  - Scheduled scanning setup instructions
  - Management command documentation
  - Best practices guide
  - Comparison with Chrome, Firefox, 1Password, Bitwarden implementations
  - "Why breached passwords matter" educational section

- **README Updates**
  - Password breach detection added to security features
  - Feature list updated with breach detection

- **Configuration Examples**
  - `HIBP_ENABLED` - Enable/disable breach checking
  - `HIBP_CHECK_ON_SAVE` - Check passwords when saved
  - `HIBP_BLOCK_BREACHED` - Block compromised passwords
  - `HIBP_SCAN_FREQUENCY` - Default scan interval
  - `HIBP_API_KEY` - Optional API key for increased rate limits

### 🔧 Technical Details

- **New Models**
  - `PasswordBreachCheck` - Tracks breach check results with timestamps
  - Foreign key relationship to `Password` model
  - Stores breach status, count, source, and check timestamp
  - Indexed for performance (password + checked_at, is_breached)

- **New Services**
  - `PasswordBreachChecker` - Core breach checking service
  - SHA-1 hashing with prefix extraction
  - API communication with HaveIBeenPwned
  - Response caching with 24-hour TTL
  - Suffix matching logic

- **New Views & Endpoints**
  - `password_test_breach` - AJAX endpoint for manual breach testing
  - Returns breach status, count, and timestamp
  - Creates breach check record and audit log

- **Form Integration**
  - Breach checking integrated into `PasswordForm` clean() method
  - Configurable warning vs. blocking behavior
  - Scan frequency selection field
  - Per-password frequency storage in custom_fields

- **Management Commands**
  - `check_password_breaches` - Bulk password scanning
  - `--force` - Ignore last check time
  - `--password-id` - Check specific password
  - `--organization-id` - Check organization passwords
  - Respects individual password scan frequency settings
  - Summary output with color-coded results

### 🏗️ Database Changes

- Migration 0006: Create `password_breach_checks` table
- Added indexes for query optimization
- Organization-scoped with automatic filtering

### 🎯 Security Audit

- CVE scan completed: January 11, 2026
- Status: All Clear
- 0 Critical, 0 High, 0 Medium vulnerabilities
- Regular security auditing with Luna the GSD

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
