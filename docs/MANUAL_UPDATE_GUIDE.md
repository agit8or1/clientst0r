# 🔄 How to Manually Update Client St0r from CLI

This guide explains how to manually update your Client St0r installation when automatic updates fail or when you need to pull specific commits.

---

## Table of Contents

- [Quick Update](#quick-update)
- [Troubleshooting Version Mismatch](#troubleshooting-version-mismatch)
- [Full Manual Update Process](#full-manual-update-process)
- [Common Issues](#common-issues)
- [Verifying the Update](#verifying-the-update)

---

## Quick Update

For most cases, these commands will update your installation:

```bash
cd /home/administrator  # Or your Client St0r directory
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart clientst0r-gunicorn.service
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
```

**Verify the update:**
```bash
python manage.py shell -c "from config.version import VERSION; print(f'Version: {VERSION}')"
```

---

## Troubleshooting Version Mismatch

### Symptom: UI shows old version after update

**Example:** You updated to v2.21.0 but the UI still shows v2.14.29

### Diagnosis Steps

1. **Check what version is in the code:**
   ```bash
   cd /home/administrator
   grep "VERSION =" config/version.py
   ```

2. **Check if Gunicorn is running the updated code:**
   ```bash
   sudo systemctl status clientst0r-gunicorn.service
   ps aux | grep gunicorn
   ```

3. **Check browser cache:**
   - Hard refresh: `Ctrl + Shift + R` (Chrome/Firefox) or `Cmd + Shift + R` (Mac)
   - Clear browser cache entirely

4. **Check Django cache:**
   ```bash
   python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared')"
   ```

### Solution: Force Full Reload

```bash
# 1. Stop services
sudo systemctl stop clientst0r-gunicorn.service
sudo systemctl stop nginx

# 2. Pull latest code
cd /home/administrator
git fetch --all
git reset --hard origin/main

# 3. Update dependencies
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 4. Run migrations
python manage.py migrate

# 5. Collect static files
python manage.py collectstatic --noinput --clear

# 6. Clear cache
python manage.py shell -c "from django.core.cache import cache; cache.clear()"

# 7. Restart services
sudo systemctl start nginx
sudo systemctl start clientst0r-gunicorn.service

# 8. Verify
sleep 3
python manage.py shell -c "from config.version import VERSION; print(f'Version: {VERSION}')"
curl -I http://localhost:8000 2>&1 | grep "HTTP"
```

---

## Full Manual Update Process

### Step 1: Backup First! 🛡️

Always backup before updating:

```bash
# Backup database
sudo mysqldump -u clientst0r -p clientst0r > ~/clientst0r_backup_$(date +%Y%m%d).sql

# Backup media files
tar -czf ~/clientst0r_media_backup_$(date +%Y%m%d).tar.gz /home/administrator/media/

# Backup configuration
cp /home/administrator/config/settings.py ~/settings_backup_$(date +%Y%m%d).py
cp /home/administrator/.env ~/env_backup_$(date +%Y%m%d)
```

### Step 2: Check Current State

```bash
cd /home/administrator

# Check current version
python manage.py shell -c "from config.version import VERSION; print(f'Current: {VERSION}')"

# Check git status
git status
git log -1 --oneline

# Check for uncommitted changes
git diff
```

### Step 3: Stash Local Changes (if any)

If you have local modifications:

```bash
git stash
# After update, restore with: git stash pop
```

### Step 4: Pull Updates

```bash
# Fetch latest
git fetch origin main

# See what's new
git log HEAD..origin/main --oneline

# Pull updates
git pull origin main
```

**If pull fails:**
```bash
# Reset to remote version (⚠️ DESTROYS local changes)
git reset --hard origin/main
```

### Step 5: Update Dependencies

```bash
source venv/bin/activate

# Upgrade pip first
pip install --upgrade pip

# Install/update requirements
pip install -r requirements.txt --upgrade
```

### Step 6: Run Migrations

```bash
# Check for pending migrations
python manage.py showmigrations | grep "\\[ \\]"

# Run migrations
python manage.py migrate

# Verify
python manage.py showmigrations | tail -20
```

### Step 7: Collect Static Files

```bash
# Clear old static files
rm -rf /home/administrator/static_collected/*

# Collect new ones
python manage.py collectstatic --noinput

# Verify
ls -la /home/administrator/static_collected/css/themes.css
```

### Step 8: Clear Caches

```bash
# Django cache
python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('✓ Django cache cleared')"

# Browser cache (tell users to do this)
# Ctrl + Shift + R (or Cmd + Shift + R on Mac)
```

### Step 9: Restart Services

```bash
# Restart Gunicorn
sudo systemctl restart clientst0r-gunicorn.service

# Check status
sudo systemctl status clientst0r-gunicorn.service

# Restart Nginx (if needed)
sudo systemctl restart nginx
```

### Step 10: Verify Update

```bash
# Check version
python manage.py shell -c "from config.version import VERSION; print(f'Updated to: {VERSION}')"

# Test web server
curl -I http://localhost:8000 2>&1 | grep "HTTP"

# Check logs for errors
sudo journalctl -u clientst0r-gunicorn.service -n 50 --no-pager
tail -f /home/administrator/logs/django.log
```

---

## Common Issues

### Issue 1: "Already up to date" but version is old

**Cause:** You're on a different branch or have local commits

```bash
# Check current branch
git branch

# Check if local is behind remote
git fetch origin
git log HEAD..origin/main --oneline

# If behind, pull
git pull origin main

# If on wrong branch
git checkout main
git pull origin main
```

---

### Issue 2: Merge conflicts during pull

**Symptoms:**
```
error: Your local changes to the following files would be overwritten by merge
```

**Solution:**
```bash
# Option A: Stash changes
git stash
git pull origin main
git stash pop  # Reapply your changes

# Option B: Discard local changes (⚠️ DESTRUCTIVE)
git reset --hard origin/main
```

---

### Issue 3: Static files not updating

**Symptoms:** CSS/JS changes don't appear in browser

**Solution:**
```bash
# Clear and recollect
rm -rf /home/administrator/static_collected/*
python manage.py collectstatic --noinput --clear

# Restart Gunicorn
sudo systemctl restart clientst0r-gunicorn.service

# Check file timestamps
ls -lt /home/administrator/static_collected/css/ | head -10

# Force browser hard refresh
# Ctrl + Shift + R
```

---

### Issue 4: Database migrations fail

**Symptoms:**
```
django.db.utils.OperationalError: (1054, "Unknown column...")
```

**Solution:**
```bash
# Check migration status
python manage.py showmigrations

# Try fake migration (if schema already correct)
python manage.py migrate --fake appname migration_name

# OR rollback and re-run
python manage.py migrate appname zero
python manage.py migrate appname

# Last resort: Check manual schema fix
mysql -u clientst0r -p clientst0r
# Run manual ALTER TABLE commands if needed
```

---

### Issue 5: Gunicorn won't start after update

**Symptoms:**
```
sudo systemctl status clientst0r-gunicorn.service
● clientst0r-gunicorn.service - Client St0r Gunicorn
   Active: failed (Result: exit-code)
```

**Diagnosis:**
```bash
# Check logs
sudo journalctl -u clientst0r-gunicorn.service -n 100 --no-pager

# Try running Gunicorn manually
cd /home/administrator
source venv/bin/activate
gunicorn config.wsgi:application --bind 0.0.0.0:8000

# Common causes:
# - Missing dependency: pip install -r requirements.txt
# - Syntax error: python manage.py check
# - Permission issue: check file ownership
```

**Fix:**
```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Check syntax
python manage.py check

# Fix permissions
sudo chown -R administrator:administrator /home/administrator
sudo chmod -R 755 /home/administrator

# Restart
sudo systemctl restart clientst0r-gunicorn.service
```

---

### Issue 6: 502 Bad Gateway after update

**Cause:** Gunicorn socket/port mismatch with Nginx

**Solution:**
```bash
# Check Gunicorn binding
ps aux | grep gunicorn
# Should show: --bind unix:/home/administrator/gunicorn.sock --bind 0.0.0.0:8000

# Check Nginx config
sudo nginx -t
sudo cat /etc/nginx/sites-enabled/clientst0r | grep "upstream"

# Ensure www-data can access socket
sudo usermod -a -G administrator www-data
sudo chmod 755 /home/administrator

# Restart both
sudo systemctl restart clientst0r-gunicorn.service
sudo systemctl restart nginx
```

---

## Verifying the Update

### Check Version in Multiple Places

```bash
# 1. Python code
python manage.py shell -c "from config.version import VERSION; print(f'Code version: {VERSION}')"

# 2. Web UI (after logging in)
# Navigate to: Settings → About or Profile
# Should show: "Client St0r v2.XX.X"

# 3. Git commit
git log -1 --oneline

# 4. CHANGELOG
grep "##" CHANGELOG.md | head -5
```

### Check Services Status

```bash
# Gunicorn
sudo systemctl status clientst0r-gunicorn.service | grep "Active"

# Nginx
sudo systemctl status nginx | grep "Active"

# Database
sudo systemctl status mariadb | grep "Active"
```

### Check Recent Logs

```bash
# Gunicorn logs (last 50 lines)
sudo journalctl -u clientst0r-gunicorn.service -n 50 --no-pager

# Django logs
tail -50 /home/administrator/logs/django.log

# Nginx error logs
sudo tail -50 /var/log/nginx/error.log
```

### Test Key Features

After updating, test:
- ✅ Login works
- ✅ Dashboard loads
- ✅ Assets page loads (check dark mode!)
- ✅ Create a test item (asset/password/doc)
- ✅ Theme switcher works (Profile → Preferences)
- ✅ Search works
- ✅ No JavaScript errors in browser console (F12)

---

## Update Checklist

Use this checklist for updates:

```
[ ] Backup database
[ ] Backup media files
[ ] Check current version: python manage.py shell -c "from config.version import VERSION; print(VERSION)"
[ ] Pull updates: git pull origin main
[ ] Update dependencies: pip install -r requirements.txt --upgrade
[ ] Run migrations: python manage.py migrate
[ ] Collect static files: python manage.py collectstatic --noinput
[ ] Clear Django cache
[ ] Restart Gunicorn: sudo systemctl restart clientst0r-gunicorn.service
[ ] Hard refresh browser: Ctrl + Shift + R
[ ] Verify version matches in UI
[ ] Test key features
[ ] Check logs for errors
```

---

## Automated Update Script

Save this as `~/update_clientst0r.sh`:

```bash
#!/bin/bash
set -e

echo "🔄 Client St0r Update Script"
echo "=========================="

# Variables
INSTALL_DIR="/home/administrator"
VENV_DIR="$INSTALL_DIR/venv"
BACKUP_DIR="$HOME/clientst0r_backups"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# 1. Backup
echo "📦 Creating backup..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mysqldump -u clientst0r -p clientst0r > "$BACKUP_DIR/db_$TIMESTAMP.sql"
echo "✓ Database backed up"

# 2. Pull updates
echo "⬇️  Pulling updates..."
cd "$INSTALL_DIR"
git fetch origin
git pull origin main
echo "✓ Code updated"

# 3. Update dependencies
echo "📦 Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install -r requirements.txt --upgrade --quiet
echo "✓ Dependencies updated"

# 4. Run migrations
echo "🗄️  Running migrations..."
python manage.py migrate
echo "✓ Migrations complete"

# 5. Collect static files
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput --clear
echo "✓ Static files collected"

# 6. Clear cache
echo "🧹 Clearing cache..."
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
echo "✓ Cache cleared"

# 7. Restart services
echo "🔄 Restarting services..."
sudo systemctl restart clientst0r-gunicorn.service
sudo systemctl restart nginx
sleep 2
echo "✓ Services restarted"

# 8. Verify
echo ""
echo "✅ Update complete!"
echo "📌 New version:"
python manage.py shell -c "from config.version import VERSION; print(f'  {VERSION}')"
echo ""
echo "📋 Next steps:"
echo "  1. Hard refresh your browser (Ctrl + Shift + R)"
echo "  2. Check /admin for any errors"
echo "  3. Test key features"
echo ""
echo "💾 Backup saved to: $BACKUP_DIR/db_$TIMESTAMP.sql"
```

Make it executable:
```bash
chmod +x ~/update_clientst0r.sh
```

Run it:
```bash
~/update_clientst0r.sh
```

---

## Need Help?

If you're still having issues after following this guide:

1. **Check the logs:**
   ```bash
   sudo journalctl -u clientst0r-gunicorn.service -n 100
   tail -100 /home/administrator/logs/django.log
   ```

2. **Ask for help:**
   - 💬 [GitHub Discussions → Q&A](https://github.com/agit8or1/clientst0r/discussions/categories/q-a)
   - 🐛 [Report a Bug](https://github.com/agit8or1/clientst0r/issues/new?template=bug_report.yml)
   - 📧 Email: [your-support-email]

3. **Emergency rollback:**
   ```bash
   # Restore database from backup
   mysql -u clientst0r -p clientst0r < ~/clientst0r_backup_YYYYMMDD.sql

   # Revert code to previous version
   cd /home/administrator
   git log --oneline | head -10  # Find previous commit
   git checkout <commit-hash>
   sudo systemctl restart clientst0r-gunicorn.service
   ```

---

**Remember:** Always backup before updating! 💾
