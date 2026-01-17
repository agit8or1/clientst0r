# HuduGlue Upgrade Notes

## 🚨 v2.24.127 - HOTFIX: Critical Template Syntax Error

### What's Fixed:
**CRITICAL BUG**: Fixed template syntax error that broke all pages in v2.24.126.

### The Problem:
v2.24.126 introduced a Django template syntax error using parentheses in an if statement:
```django
{% if global_kb_enabled and (is_staff_user or user.is_superuser) %}
```

Django templates don't support parentheses for grouping logic, causing:
```
TemplateSyntaxError: Could not parse the remainder: '(is_staff_user' from '(is_staff_user'
```

### The Fix:
Nested the if statements properly:
```django
{% if global_kb_enabled %}
    {% if is_staff_user or user.is_superuser %}
        ...
    {% endif %}
{% endif %}
```

### Impact:
- **v2.24.126**: Broke ALL pages with base.html template
- **v2.24.127**: Fixed - all pages working again

### Upgrade Immediately:
```bash
cd /home/administrator
git pull origin main
sudo systemctl restart huduglue-gunicorn.service
```

**If you're on v2.24.126, upgrade to v2.24.127 immediately!**

---

## 🔧 v2.24.126 - Fixed Organization Dropdown Not Showing All Orgs (BROKEN - DO NOT USE)

### What's Fixed:
Fixed issue where organization dropdown wasn't showing all available organizations for some users.

### Problems Resolved:
1. **Superusers not seeing all organizations** - Superusers were not automatically seeing all orgs unless they were also marked as staff users
2. **Inactive organizations appearing** - Org users could see organizations that were marked as inactive if they had an active membership
3. **Middleware not respecting superuser status** - Organization middleware wasn't checking `is_superuser` flag

### Changes Made:
- **Context Processor**: Added `request.user.is_superuser` check to show all organizations
- **Context Processor**: Added `organization__is_active=True` filter for org users
- **Middleware**: Added `is_superuser` check for organization access
- **Middleware**: Added `organization__is_active=True` filter when auto-selecting organization

### Who This Affects:
- **Superusers**: Now properly see all active organizations in dropdown
- **Org Users**: No longer see inactive organizations even if they have memberships

### Technical Details:
Before: Only staff users (user_type=STAFF) saw all organizations
After: Both superusers AND staff users see all organizations

### Upgrade:
```bash
cd /home/administrator
git pull origin main
sudo systemctl restart huduglue-gunicorn.service
```

---

## 🐛 v2.24.125 - Fixed Document Form Validation Errors

### What's Fixed:
Fixed browser console errors and form validation issues on document creation/editing pages.

### Problems Resolved:
1. **"An invalid form control is not focusable" error** - The body textarea was marked as required but hidden by the WYSIWYG editor, preventing form submission
2. **Autocomplete warning** - GitHub token field in bug report modal was missing autocomplete attribute
3. **Form submission failures** - Users couldn't submit document forms due to hidden field validation

### Changes Made:
- **Document Forms**: Removed HTML5 `required` attribute from hidden textarea when WYSIWYG editor is active
- **Validation**: Added JavaScript validation before form submission to ensure content exists
- **Autocomplete**: Added `autocomplete="off"` to GitHub token password field
- **Consistency**: Applied fixes to all document form templates (documents, global KB, templates)

### Files Updated:
- `docs/forms.py` - Added data-required attribute
- `templates/docs/document_form.html` - Fixed validation
- `templates/docs/global_kb_form.html` - Fixed validation
- `templates/docs/template_form.html` - Fixed validation
- `templates/base.html` - Added autocomplete attribute

### User Experience:
- Forms now submit correctly without browser validation errors
- Clear alert message if content is empty on submission
- No more console warnings about form controls

### Upgrade:
```bash
cd /home/administrator
git pull origin main
sudo systemctl restart huduglue-gunicorn.service
```

---

## 🔧 v2.24.124 - Fixed Error Messages for Encryption Issues (Issue #4)

### What's Fixed:
Updated error handling in RMM and PSA integrations to provide correct guidance when encryption errors occur.

### The Problem:
When users encountered encryption errors (typically during Tactical RMM setup or password operations), the error message incorrectly suggested regenerating the APP_MASTER_KEY. This wasn't the right solution!

### The Real Issue:
Encryption errors usually mean the Gunicorn service isn't loading the `.env` file containing the APP_MASTER_KEY environment variable.

### New Error Message:
Now when encryption errors occur, users see clear instructions:
- Run the fix script: `./scripts/fix_gunicorn_env.sh`
- Or run diagnostic: `./diagnose_gunicorn_fix.sh`
- Link to GitHub Issue #4 for full details

### What Was Updated:
- All RMM integration views (create, edit, sync, test)
- All PSA integration views (create, edit, sync, test)
- Error messages now link to the correct fix scripts
- Added reference to Issue #4 for documentation

### Upgrade:
```bash
cd /home/administrator
git pull origin main
sudo systemctl restart huduglue-gunicorn.service
```

---

## 🎛️ v2.24.123 - Feature Toggles: Enable/Disable Services!

### What's New:
Added Feature Toggles in Admin Settings to enable or disable major system features. When disabled, features won't appear in the navigation menu and will be inaccessible.

### Configurable Features:
- **Monitoring** - Website & Service Monitoring, SSL tracking, expiration tracking
- **Global Knowledge Base** - Staff-only shared knowledge base across organizations
- **Workflows & Automation** - Process definitions and automated execution

### How to Use:
1. **Admin dropdown → System Settings → Feature Toggles**
2. Toggle features on/off with simple switches
3. Changes apply immediately after saving

### Benefits:
- **Simplified UI** - Hide features you don't use to reduce menu clutter
- **Focus on What Matters** - Keep only the tools your team needs visible
- **Flexible Configuration** - Enable/disable features as your needs change

### Technical Details:
- Feature toggles stored in SystemSetting model
- Context processor makes toggles available to all templates
- Navigation menu conditionally hides disabled features
- Backward compatible - all features enabled by default

### Upgrade:
```bash
cd /home/administrator
git pull origin main
python manage.py migrate
sudo systemctl restart huduglue-gunicorn.service
```

---

## 🔍 v2.24.122 - Diagnostic Script to Find the Problem!

### What's New:
Added a diagnostic script that tells you EXACTLY what's wrong and how to fix it!

### Run This on Your Remote Server:

```bash
cd /home/administrator
git pull origin main
./diagnose_gunicorn_fix.sh
```

### What the Diagnostic Does:
1. ✅ Checks if .env file exists and has APP_MASTER_KEY
2. ✅ Checks if Gunicorn service file exists
3. ✅ Checks if EnvironmentFile is configured (THE FIX)
4. ✅ Tests if sudo permissions are configured
5. ✅ Tells you EXACTLY what command to run to fix it

### The Script Will Tell You:
- **If fix is already applied:** Just restart Gunicorn
- **If sudo not configured:** Shows exact command to configure it
- **If fix needs to be applied:** Tells you to run `./scripts/fix_gunicorn_env.sh`

### Why This Helps:
The red alert in the web UI only checks if `systemctl status` works, but the fix needs `sudo tee` permission. This diagnostic checks BOTH!

---

## 🔧 v2.24.121 - FIXED: Gunicorn Fix Script Now Works with Sudo Permissions!

### What Was Fixed:
The Gunicorn fix script was using `sudo sed` and `sudo cp` commands that weren't in the sudoers permissions, causing it to fail silently during web-based updates.

**The fix:** Changed the script to use only `sudo tee`, `sudo systemctl`, and `sudo grep` - commands that ARE in the sudoers permissions!

### How It Works Now:
1. Script reads the service file with `awk` (no sudo needed)
2. Modifies the content in memory
3. **Uses `sudo tee` to write** (which IS allowed in sudoers)
4. Reloads and restarts service

### Update Now:
```bash
# From web UI:
Admin → System Updates → Click "Apply Update"

# The fix script will NOW work correctly!
```

### What Gets Fixed:
- ✅ Demo data import encryption errors
- ✅ Password creation/editing from web UI
- ✅ All environment variable operations

### Technical Details:
- **Old script:** Used `sudo sed -i` and `sudo cp` (not in sudoers)
- **New script:** Uses `sudo tee` (IS in sudoers)
- **Result:** Fix actually applies during web-based updates!

---

## 🧪 v2.24.120 - Test Release for Complete Update Flow

### What's New:
This is a test release to verify the complete one-click update system works end-to-end!

### What to Test:

**On Systems WITHOUT Sudo Configured:**
1. Go to **Admin → System Updates**
2. You should see a **RED ALERT** with the exact sudo command
3. Copy and run the command shown
4. Refresh the page - alert should disappear
5. Click "Check for Updates" - should show v2.24.120 available
6. Click "Apply Update" - should update automatically

**On Systems WITH Sudo Already Configured:**
1. Go to **Admin → System Updates**
2. No red alert (sudo already configured)
3. Click "Check for Updates" - should show v2.24.120 available
4. Click "Apply Update" - should update automatically

**What Happens Automatically:**
- ✅ Pulls v2.24.120 code
- ✅ Runs migrations
- ✅ **Runs Gunicorn fix script (if present)**
- ✅ Installs dependencies
- ✅ Collects static files
- ✅ Restarts Gunicorn service

### Version Changes:
- v2.24.120: Test release (version bump only)
- All functionality from v2.24.119 included

---

## 💡 v2.24.119 - Sudo Setup Alert in Web UI!

### What's New:
The System Updates page now shows a PROMINENT ALERT if passwordless sudo is not configured, with the exact command users need to run!

### Update Process (Same as v2.24.118):

**Web UI (Easiest):**
1. **Admin dropdown → System Updates**
2. If you see a red alert, **copy and run the command shown** (one-time setup)
3. **Refresh the page**
4. **Click "Check for Updates"**
5. **Click "Apply Update"**
6. **Done!**

### What Changed in v2.24.119:
- ✅ Added sudo configuration check to System Updates page
- ✅ Shows prominent red alert if sudo is not configured
- ✅ Displays exact command users need to run
- ✅ Clear instructions: run command → refresh page → click update
- ✅ No more guessing or hidden errors!

### Perfect For:
- Users who don't read documentation
- Clear guidance right in the UI where it's needed
- One-time setup is obvious and easy to follow

---

## 🚀 v2.24.118 - ONE-CLICK UPDATE with Automatic Fix!

### What's New:
Click the **Update** button in the web UI and EVERYTHING happens automatically - including the critical Gunicorn fix!

### Update Process (Web UI - EASIEST):

1. **Admin dropdown → System Updates**
2. **Click "Check for Updates"**
3. **Click "Update Now"**
4. **Done!** The update automatically:
   - ✅ Pulls latest code
   - ✅ Runs migrations
   - ✅ **Applies Gunicorn environment fix**
   - ✅ Installs dependencies
   - ✅ Collects static files
   - ✅ Restarts Gunicorn service

### One-Time Sudo Configuration Required:

For web-based updates to work, configure passwordless sudo ONCE:

```bash
sudo tee /etc/sudoers.d/huduglue-auto-update > /dev/null <<'SUDOERS'
administrator ALL=(ALL) NOPASSWD: /bin/systemctl restart huduglue-gunicorn.service, /bin/systemctl status huduglue-gunicorn.service, /bin/systemctl daemon-reload, /usr/bin/systemd-run, /usr/bin/tee /etc/systemd/system/huduglue-gunicorn.service
SUDOERS

sudo chmod 0440 /etc/sudoers.d/huduglue-auto-update
```

**After this one-time setup, all future updates are ONE CLICK!**

### Alternative: Command Line Update

```bash
cd /home/administrator && ./update.sh
```

### What Gets Fixed Automatically:
- ❌ Demo data import failures
- ❌ Password encryption errors
- ❌ Any environment variable issues

The update process now includes an explicit step to run the Gunicorn environment fix script, ensuring the fix is applied even if the migration doesn't have sudo permissions.

### Perfect for Multiple Servers:
Set up passwordless sudo once on each server, then all future updates are just clicking a button in the web UI!

---

## ✅ v2.24.117 - AUTOMATIC Gunicorn Fix During Migration!

### What's New:
The critical Gunicorn environment fix from v2.24.113/116 now **applies automatically** when you run the update script!

### Update Process (ONE COMMAND):

```bash
cd /home/administrator && ./update.sh
```

**That's it!** The update script automatically:
- ✅ Pulls latest code from GitHub
- ✅ Runs database migrations (which applies the Gunicorn fix)
- ✅ Installs/updates dependencies
- ✅ Collects static files
- ✅ Restarts Gunicorn service
- ✅ Verifies service is running

### What the Migration Fixes (Automatically):
- ❌ Demo data import failures
- ❌ Password encryption errors
- ❌ Any feature requiring environment variables from .env file

The migration automatically:
- Runs the fix_gunicorn_env.sh script
- Adds `EnvironmentFile=/home/administrator/.env` to Gunicorn service
- Reloads systemd daemon
- Restarts Gunicorn

### Perfect for Multiple Servers:
This update is designed for administrators managing multiple HuduGlue servers. Run the same single command on all servers - everything happens automatically!

### Already Applied the Fix Manually?
No problem! The migration detects if the fix is already applied and won't duplicate the configuration.

---

## ⚠️ v2.24.116 - CRITICAL: Apply Environment Fix NOW!

### If You're Seeing Encryption Errors - READ THIS!

**Error you might see:**
```
Error: Demo data import failed: Encryption failed: Invalid APP_MASTER_KEY format: Incorrect padding
```

### Quick Fix (2 commands):

```bash
cd /home/administrator
./scripts/fix_gunicorn_env.sh
```

**That's it!** This fixes:
- ❌ Demo data import failures
- ❌ Password encryption errors
- ❌ Any feature requiring environment variables from .env file

### What This Version Does:
- 📢 **Emphasizes** the critical Gunicorn environment fix
- 📚 Provides clear, simple instructions
- ✅ Includes the fix script (from v2.24.113)

### Already Applied the Fix?
If you've already run `./scripts/fix_gunicorn_env.sh` after v2.24.113, you're good! This version just makes the instructions clearer for others.

---

## v2.24.115 - Bug Reporting Feature

### New Feature: Report Bugs Directly to GitHub

Users can now report bugs from HuduGlue! Click **username dropdown → Report Bug**.

**Features:**
- Submit title, description, steps to reproduce
- Upload screenshots (max 5MB)
- Auto-collect system information
- Use system GitHub PAT or your own credentials

### Upgrade:
```bash
cd /home/administrator
git pull origin main
python manage.py migrate
sudo systemctl restart huduglue-gunicorn.service
```

---

## v2.24.114 - UI Cleanup

### Changes:
- Removed duplicate "System Updates" link from settings sidebar
- System Updates now only in Admin dropdown menu

---

## v2.24.113 - Critical Fix for Demo Data Import & Password Encryption

### Issue
Demo data import was failing with error:
```
Encryption failed: Invalid APP_MASTER_KEY format: Incorrect padding
```

This occurred when:
- Importing demo data from the web UI
- Creating/editing passwords from the web UI
- Any operation requiring encryption through the web interface

**Command line operations worked fine** - only web UI operations failed.

### Root Cause
The Gunicorn systemd service was not configured to load the `.env` file, so the `APP_MASTER_KEY` environment variable was not available to the Django application when running through the web server.

### Fix Required
Add `EnvironmentFile=/home/administrator/.env` to the Gunicorn service configuration.

### Automatic Fix (Recommended)

```bash
cd /home/administrator
./scripts/fix_gunicorn_env.sh
```

This script will:
1. ✅ Check if the service file exists
2. ✅ Verify .env file exists
3. ✅ Backup the service file
4. ✅ Add EnvironmentFile configuration
5. ✅ Reload systemd and restart Gunicorn
6. ✅ Verify the service started successfully

### Manual Fix (If Needed)

1. Edit the service file:
```bash
sudo nano /etc/systemd/system/huduglue-gunicorn.service
```

2. Add this line after the `Environment="PATH=..."` line:
```ini
EnvironmentFile=/home/administrator/.env
```

3. The result should look like:
```ini
[Service]
Type=notify
User=administrator
Group=administrator
WorkingDirectory=/home/administrator
Environment="PATH=/home/administrator/venv/bin"
EnvironmentFile=/home/administrator/.env
ExecStart=/home/administrator/venv/bin/gunicorn \
    ...
```

4. Reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart huduglue-gunicorn.service
```

### Verification

After applying the fix:

1. Go to **Settings → General Settings**
2. Click **"Import Demo Data"**
3. You should see: "✓ Demo data imported successfully!"
4. Refresh the page
5. Switch to "Acme Corporation" organization
6. Verify you see:
   - 5 Documents
   - 3 Diagrams
   - 10 Assets
   - 5 Passwords
   - 5 Workflows

### Note for Fresh Installations

This fix is required for any system where the Gunicorn service was set up before v2.24.113. The fix script is idempotent and safe to run multiple times.

---

## v2.24.112 - Demo Data Import Reliability

### Changes
- Removed background threading from demo data import
- Made import synchronous for better error handling
- Automatic organization switching after import
- Improved success/error messages
- Import completes in 2-3 seconds

### Upgrade
```bash
cd /home/administrator
git pull origin main
sudo systemctl restart huduglue-gunicorn.service
```

---

## Previous Versions

See git commit history for older version notes.
