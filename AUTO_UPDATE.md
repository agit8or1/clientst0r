# Client St0r Auto-Update System

Optional unattended updates for native (`install.sh`) installs. Docker installs update with
`docker compose pull && docker compose up -d` instead and do not use this.

The auto-update timer is **installed but turned off** by `install.sh`, because applying
releases to a live system unattended is a decision you should make deliberately. The
**Apply** button in **Settings → Updates** (`/core/settings/updates/`) runs exactly the same
update steps on demand, and is the recommended way to update.

## What an update does

`scripts/auto_update.sh` is a thin wrapper. It downloads
`deploy/update_instructions.sh` from the `main` branch on GitHub and runs it. The web UI's
Apply button downloads and runs the same script. The script:

1. **Fetches and resets the code** — `git fetch origin main`, then
   `git reset --hard origin/main`. This installs the latest commit on `main` (not a specific
   release tag), and **discards any local modifications to tracked files**. Nothing is
   stashed. Untracked files you added are left alone.
2. **Installs Python dependencies** from `requirements.txt`. Optional requirement files
   (`requirements-graphql.txt`, `requirements-optional.txt`) are installed if present; a
   failure there is logged and does not stop the update.
3. **Runs database migrations** (`migrate --noinput`).
4. **Collects static files** (`collectstatic --noinput`).
5. **Runs optional maintenance steps.** Failures are logged and do not stop the update.
   These include updating the root helper (if installed), refreshing the local GeoIP
   database, re-seeding PSA reference data and sample workflow rules (existing rows are
   skipped), and removing crontab lines left by older releases for jobs that now run from
   the built-in scheduler.
6. **Reloads the web server gracefully.** Gunicorn receives a reload signal and replaces
   its workers one at a time while the master process keeps serving, so requests are not
   dropped in normal operation. If a reload is not possible, the script falls back to a
   restart (a brief interruption). If it can neither reload nor restart, the update is
   reported as **failed**: the new code is on disk, but the old code is still running.

Only the web service is reloaded. The other `clientst0r-*` units (scheduler, monitor, PSA
and RMM sync, breach scan) are timer-driven one-shot jobs, so they pick up the new code on
their next run.

### What it does not do

- **No automatic backup.** Take one first (see [Backups](#backups-and-recovery)).
- **No rollback.** If a step fails, the steps before it stay applied. For example, if a
  migration fails, the new code is already on disk and the database may be partly
  migrated, while the web service keeps running the previous code until it is reloaded.
  See [If an update fails](#if-an-update-fails).
- **No stash of local changes.** Keep customisations out of tracked files, or they are
  overwritten.

### Release notes that change behaviour on update

Read these before applying an update that crosses them:

- **3.17.610 — saved Security settings become live.** Before updating, open
  **Settings → Security** and check the values. Idle timeout, maximum session length,
  require 2FA, password policy, failed-login limit and lockout duration now come from that
  page unless an environment variable is set (the variable wins and the field shows
  "set by environment"). If `AXES_COOLOFF_TIME` isn't set, the lockout becomes the saved
  value (default 30 minutes) instead of 1 hour; an install with "Require 2FA" unticked and
  no `REQUIRE_2FA` variable stops requiring 2FA. A Content-Security-Policy is added in
  report-only mode (nothing is blocked; set `CSP_REPORT_ONLY=False` to enforce).
- **3.17.608 — LDAP sign-in** needs `django-auth-ldap` and `python-ldap` from
  `requirements-optional.txt`. The update tries to install that file; `python-ldap` needs
  system build packages (listed in the file), so if it fails the update continues and the
  Directory settings page says the packages are missing.
- **3.17.607 — stored secrets are converted** to encrypted or hashed storage by a
  migration. Back up first and keep `APP_MASTER_KEY`. Going back to an earlier release
  afterwards needs the pre-update database backup.
- **3.17.600 — technicians must be Staff.** Users who aren't superusers or User Type
  *Staff* are treated as customer users. See [FEATURES.md](FEATURES.md#access-model-msp-staff-and-customer-users).

## Turning on unattended updates

```bash
cd /path/to/clientst0r
./scripts/install_auto_update.sh
```

This installs and enables:

- `clientst0r-auto-update.service` — runs `scripts/auto_update.sh` as the install user
- `clientst0r-auto-update.timer` — daily at 02:00 local time, 10 minutes after boot, and
  as soon as possible after a missed run (`Persistent=true`)

On installs that have the root helper (`/usr/local/sbin/clientst0r-root-helper`, set up
from **Settings → Updates**), the app's root actions — including the graceful reload — go
through that one program, and each update refreshes the helper's managed configuration.
Installs without the helper fall back to the narrower `sudo` rules written by the
installer.

## Running an update by hand

```bash
# Same steps as the timer
/path/to/clientst0r/scripts/auto_update.sh

# Through systemd
sudo systemctl start clientst0r-auto-update.service

# Through Django
cd /path/to/clientst0r && source venv/bin/activate
python manage.py auto_update
```

### Check for updates only

```bash
python manage.py auto_update --check-only   # exits 1 when updates are available
```

## Status and logs

```bash
sudo systemctl status clientst0r-auto-update.timer
sudo systemctl list-timers clientst0r-auto-update.timer
sudo systemctl status clientst0r-auto-update.service

tail -n 50 /var/log/clientst0r/auto-update.log
sudo journalctl -u clientst0r-auto-update.service -n 50
```

Updates applied from the web UI are also recorded in the audit log. A failed web update
stores the last 200 lines of script output with the audit entry, so you can see which step
failed without SSH.

## Changing the schedule

```bash
sudo systemctl edit clientst0r-auto-update.timer
```

```ini
[Timer]
OnCalendar=
OnCalendar=Sun 03:00
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart clientst0r-auto-update.timer
```

## Turning unattended updates off

```bash
sudo systemctl disable --now clientst0r-auto-update.timer
```

The **Apply** button in Settings → Updates keeps working.

## Backups and recovery

Back up before updating, and keep `APP_MASTER_KEY` (from `.env`) somewhere safe and
separate. Without it, encrypted vault entries and credentials in a restored database cannot
be decrypted. If you have rotated the key since a backup was taken, list the old key in
`APP_MASTER_KEY_PREVIOUS` to restore it (see [SECURITY.md](SECURITY.md#key-rotation)).

```bash
python manage.py backup --output-dir /var/backups/clientst0r --encrypt --retention-days 30
```

## If an update fails

1. Read the log: `tail -n 100 /var/log/clientst0r/auto-update.log`, or the failed update's
   entry in the audit log.
2. Fix the cause (common ones: a dependency that failed to install, a migration error, or
   missing permission to reload the service) and run the update again. Re-running is safe:
   every step is repeatable.
3. If you need to go back to the previous version, there is no one-step rollback. Restore
   the database from the backup you took before updating, check out the previous release
   tag (`git checkout vX.Y.Z`), install its requirements, and reload the service. Restoring
   code without restoring the database only works when the failed release added no
   migrations.

See [docs/MANUAL_UPDATE_GUIDE.md](docs/MANUAL_UPDATE_GUIDE.md) for the manual update path.

## Uninstall

```bash
sudo systemctl disable --now clientst0r-auto-update.timer
sudo rm /etc/systemd/system/clientst0r-auto-update.service \
        /etc/systemd/system/clientst0r-auto-update.timer
sudo systemctl daemon-reload
```

Leave `/etc/sudoers.d/clientst0r-auto-update` in place if you still use the **Apply**
button on an install without the root helper; it carries the rules that button relies on.
