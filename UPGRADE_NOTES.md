# HuduGlue Upgrade Notes

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
