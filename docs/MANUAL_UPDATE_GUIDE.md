# How to Manually Update Client St0r from the CLI

The normal way to update a native install is the web UI: **Settings → Updates**
(`/core/settings/updates/`), *Check for Updates*, then *Apply*. Use this guide when that
path is unavailable or fails, or when you need to pull specific commits.

Docker installs update with `docker compose pull && docker compose up -d`; see
[docker.md](docker.md).

In the commands below, `/path/to/clientst0r` is your install directory (the one holding
`manage.py`) and `clientst0r-gunicorn.service` is the web service installed by
`install.sh`.

---

## Table of Contents

- [Quick Update](#quick-update)
- [Full Manual Update Process](#full-manual-update-process)
- [Troubleshooting Version Mismatch](#troubleshooting-version-mismatch)
- [Common Issues](#common-issues)
- [Verifying the Update](#verifying-the-update)
- [Rolling Back](#rolling-back)

---

## Quick Update

Back up first (see [Step 1](#step-1-back-up-first)), then:

```bash
cd /path/to/clientst0r
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl reload clientst0r-gunicorn.service
```

`reload` replaces the Gunicorn workers gracefully without dropping requests. Use
`sudo systemctl restart clientst0r-gunicorn.service` instead if the service is not running
or the reload has no effect.

**Verify the update:**
```bash
python manage.py shell -c "from config.version import VERSION; print(f'Version: {VERSION}')"
```

> **Updating from a release older than 3.17.599?** Periodic jobs (recurring invoices,
> email-to-ticket polling, recurring tickets, contract renewals and others) now run from the
> built-in scheduler — **Settings → Scheduler** (`/core/settings/scheduler/`) — driven by
> `clientst0r-scheduler.timer`. The web and automatic updaters remove the old crontab lines
> for these jobs. A manual update does not, so remove them yourself or each job runs twice:
>
> ```bash
> crontab -l | grep -E 'manage\.py[[:space:]]+(psa_run_recurring_tickets|psa_poll_email|psa_send_outbound|psa_auto_renew_contracts|psa_auto_replenish_suggestions|sync_distributors|run_scheduled_reports|poll_security_alerts)'
> crontab -e   # delete the lines listed above
> ```
>
> Leave the `check_update_trigger.sh` line in place; the web UI's update button uses it.

---

## Full Manual Update Process

### Step 1: Back Up First

```bash
cd /path/to/clientst0r
source venv/bin/activate

# Database and uploaded files, encrypted, in one archive
python manage.py backup --output-dir /var/backups/clientst0r --encrypt --retention-days 30

# Configuration (holds APP_MASTER_KEY; store it securely and separately)
cp .env ~/clientst0r_env_backup_$(date +%Y%m%d)
```

Keep a copy of `APP_MASTER_KEY` somewhere other than the server. Without it, encrypted
vault entries and stored credentials in a restored database cannot be decrypted.

A plain database dump also works:

```bash
mysqldump -u clientst0r -p clientst0r > ~/clientst0r_backup_$(date +%Y%m%d).sql
```

### Step 2: Check Current State

```bash
python manage.py shell -c "from config.version import VERSION; print(f'Current: {VERSION}')"
git status
git log -1 --oneline
git diff   # local modifications to tracked files
```

### Step 3: Keep Local Changes Aside (if any)

The web and automatic updaters run `git reset --hard origin/main` and **discard** local
changes to tracked files. If you update by hand and have local modifications:

```bash
git stash push -m "local changes before update"
# after updating: git stash pop
```

### Step 4: Pull Updates

```bash
git fetch origin main
git log HEAD..origin/main --oneline   # what's new
git pull origin main
```

To install a specific release instead of the tip of `main`:

```bash
git fetch --tags
git checkout v3.17.NNN
```

### Step 5: Update Dependencies

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Step 6: Run Migrations

```bash
python manage.py showmigrations | grep "\[ \]"   # pending migrations
python manage.py migrate
```

### Step 7: Collect Static Files

```bash
python manage.py collectstatic --noinput
```

### Step 8: Reload the Web Service

```bash
sudo systemctl reload clientst0r-gunicorn.service
sudo systemctl status clientst0r-gunicorn.service
```

The scheduler, monitor and sync units are timer-driven one-shot jobs; they run the new code
on their next run without a restart.

### Step 9: Verify

```bash
python manage.py shell -c "from config.version import VERSION; print(f'Updated to: {VERSION}')"
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health/
sudo journalctl -u clientst0r-gunicorn.service -n 50 --no-pager
```

---

## Troubleshooting Version Mismatch

### Symptom: UI shows the old version after an update

1. **Check the version in the code:**
   ```bash
   grep "VERSION =" config/version.py
   ```
2. **Check Gunicorn picked up the new code:**
   ```bash
   sudo systemctl status clientst0r-gunicorn.service
   ```
   If the code is new but the UI is not, reload or restart the service.
3. **Check the browser cache:** hard refresh with `Ctrl + Shift + R` (`Cmd + Shift + R` on
   Mac).
4. **Clear the Django cache:**
   ```bash
   python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared')"
   ```

### Solution: Force a full reset to `main`

This discards local changes to tracked files.

```bash
cd /path/to/clientst0r
git fetch origin main
git reset --hard origin/main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
sudo systemctl restart clientst0r-gunicorn.service
```

---

## Common Issues

### "Already up to date" but the version is old

You are on a different branch or have local commits.

```bash
git branch
git fetch origin
git log HEAD..origin/main --oneline
git checkout main && git pull origin main
```

### Local changes block the pull

```
error: Your local changes to the following files would be overwritten by merge
```

```bash
# Keep them
git stash push -m "local changes" && git pull origin main && git stash pop

# Or discard them (destructive)
git reset --hard origin/main
```

### Static files not updating

```bash
python manage.py collectstatic --noinput --clear
sudo systemctl reload clientst0r-gunicorn.service
```

Then hard refresh the browser.

### Database migrations fail

```
django.db.utils.OperationalError: (1054, "Unknown column...")
```

1. Read the full error and note which app and migration failed:
   `python manage.py showmigrations <app>`.
2. Fix the cause the error names (missing dependency, database permissions, disk space)
   and run `python manage.py migrate` again.
3. If you cannot resolve it, restore the backup from Step 1 (see
   [Rolling Back](#rolling-back)) and open an issue with the error output.

Do **not** run `migrate <app> zero` to "re-run" migrations: it drops that app's tables and
the data in them. Only use `migrate --fake` if you have confirmed by hand that the schema
already matches the migration.

### Gunicorn won't start after the update

```bash
sudo journalctl -u clientst0r-gunicorn.service -n 100 --no-pager
source venv/bin/activate
python manage.py check          # configuration or import errors
pip install -r requirements.txt # missing dependency
```

If files are owned by the wrong user (for example after running `manage.py` under `sudo`),
fix ownership of the install directory only:

```bash
sudo chown -R "$(whoami)": /path/to/clientst0r
```

Then `sudo systemctl restart clientst0r-gunicorn.service`.

### 502 Bad Gateway after the update

Nginx cannot reach Gunicorn.

```bash
sudo systemctl status clientst0r-gunicorn.service
sudo nginx -t
sudo journalctl -u clientst0r-gunicorn.service -n 50 --no-pager
```

Check the bind address in `/etc/systemd/system/clientst0r-gunicorn.service` matches the
upstream in your Nginx site, then restart both services.

---

## Verifying the Update

```bash
# Code version
python manage.py shell -c "from config.version import VERSION; print(f'Code version: {VERSION}')"
git log -1 --oneline

# Services
sudo systemctl status clientst0r-gunicorn.service | grep Active
sudo systemctl list-timers 'clientst0r-*'
```

In the web UI, **Settings → Updates** shows the running version, and **Settings →
Scheduler** shows each periodic job's last run and last error.

After updating, test:
- Login works
- Dashboard loads
- Assets, vault and documents pages load
- Search works
- No JavaScript errors in the browser console (F12)

---

## Update Checklist

```
[ ] Back up database and media (manage.py backup) and keep APP_MASTER_KEY safe
[ ] Check current version
[ ] Pull updates: git pull origin main
[ ] Update dependencies: pip install -r requirements.txt
[ ] Run migrations: python manage.py migrate
[ ] Collect static files: python manage.py collectstatic --noinput
[ ] Reload Gunicorn: sudo systemctl reload clientst0r-gunicorn.service
[ ] (Upgrading from before 3.17.599) remove legacy psa_* crontab lines
[ ] (Upgrading from before 3.17.610) review Settings → Security first — saved values become live
[ ] (Using LDAP) pip install -r requirements-optional.txt
[ ] Hard refresh browser
[ ] Verify version in Settings → Updates
[ ] Check Settings → Scheduler for job errors
[ ] Check logs for errors
```

---

## Rolling Back

There is no one-step rollback. To return to the previous version:

```bash
cd /path/to/clientst0r
source venv/bin/activate

# 1. Restore the database (and media) taken before the update
python manage.py restore /var/backups/clientst0r/<backup file> --force
#    or, from a SQL dump: mysql -u clientst0r -p clientst0r < ~/clientst0r_backup_YYYYMMDD.sql

# 2. Return the code to the previous release
git fetch --tags
git checkout v3.17.NNN
pip install -r requirements.txt
python manage.py collectstatic --noinput

# 3. Restart
sudo systemctl restart clientst0r-gunicorn.service
```

Restore the database whenever the release you are leaving added migrations: older code
does not run against a newer schema reliably.
Rolling back across 3.17.607 always needs the database backup: that release converted stored
secrets to encrypted or hashed storage, which older code cannot read.

---

## Need Help?

1. **Check the logs:**
   ```bash
   sudo journalctl -u clientst0r-gunicorn.service -n 100
   tail -100 /var/log/clientst0r/auto-update.log
   ```
2. **Ask for help:**
   - [GitHub Discussions → Q&A](https://github.com/agit8or1/clientst0r/discussions/categories/q-a)
   - [Report a Bug](https://github.com/agit8or1/clientst0r/issues/new?template=bug_report.yml)
