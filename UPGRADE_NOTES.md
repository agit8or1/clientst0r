# HuduGlue Upgrade Notes

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
