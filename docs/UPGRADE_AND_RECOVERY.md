# Upgrading Client St0r, and recovering from a failed upgrade

This guide covers native installs (`bash install.sh`) and Docker installs
(`docker compose up -d`). Native installs upgrade from the web UI first; the
command line is the fallback.

- [Release channels: Stable and Preview](#release-channels-stable-and-preview)
- [Upgrade from the web UI](#upgrade-from-the-web-ui)
- [What Apply does](#what-apply-does)
- [Upgrade from the command line](#upgrade-from-the-command-line)
- [Docker](#docker)
- [Pre-upgrade backups](#pre-upgrade-backups)
- [If an upgrade fails or is interrupted](#if-an-upgrade-fails-or-is-interrupted)
- [Half-applied migrations on MySQL/MariaDB](#half-applied-migrations-on-mysqlmariadb)
- [Restoring a backup](#restoring-a-backup)
- [Moving a backup off the host](#moving-a-backup-off-the-host)

---

## Release channels: Stable and Preview

| Channel | What Apply installs | Verified by |
|---|---|---|
| **Stable** (default) | The latest *published* GitHub release, a `vX.Y.Z` tag | The tag's SSH signature, checked against the trusted release key, and the commit the tag points at |
| **Preview** (opt-in) | The newest commit on `main`: **unreleased**, may include work in progress | The exact commit sha you reviewed (main commits are not signed) |

Pick the channel in **Settings → Updates** (`/core/settings/updates/`).
The page always shows all three:

- **Installed**: version, commit, branch, and whether the checkout has local
  edits. If you run a build newer than the latest release (for example after
  following main), it says so.
- **Recommended release (Stable)**: the tag, its commit, when it was
  published, and whether GitHub reports a signature.
- **Newer on main (not a release)**: how many commits main is ahead of the
  stable release, and the most recent of them.

Underneath, **Apply would install** names exactly one revision: the kind,
the ref (tag or `main`), the version, and the full commit sha.

**There is no LTS channel.** A long-term-support channel needs a published
support window and a backport policy for security fixes; neither exists, so
there is none to offer. It is listed on the roadmap as planned.

If GitHub cannot be reached (offline host, firewall, API rate limit) the page
says so. It shows the last good answer, marked as stale, or nothing, and it
never fails to load. Set `GITHUB_TOKEN` in `.env` if you hit the
unauthenticated rate limit often.

## Upgrade from the web UI

1. **Settings → Updates** → *Check for Updates*.
2. Read what *Apply would install*. If it's a Preview build, it is unreleased.
3. Optional: *Run preflight checks* shows what Apply will check first, with
   the reason and a hint for anything that would stop it.
4. *Apply*. The progress view and live log show each step. The service keeps
   serving the old version until the new one is installed, migrated and
   reloaded.

The browser sends the revision it showed you. If the channel offers something
else by the time you click Apply (for example, a new release appeared), the
server refuses. Reload the page and review again.

## What Apply does

1. **Verify the revision.** It checks that origin still points the reviewed
   ref at the reviewed sha (otherwise it refuses and changes nothing). It
   fetches that commit, checks the sha again and, for a release, verifies the
   tag signature. The trusted key comes from `/etc/clientst0r/allowed_signers`
   (installed by the root helper), or else from the *installed* revision's
   `deploy/root-helper/allowed_signers`. A downgrade is refused.
2. **Preflight checks.** These cover:
   - disk space for a backup plus the new release
   - the database answers
   - the list of migrations that will run
   - media is writable
   - `SECRET_KEY`, `APP_MASTER_KEY` and `API_KEY_SECRET` are present and valid
   - the backup destination is writable and the dump tools exist
   - the target's Python requirements resolve (`pip install --dry-run`)

   Any failure stops here, and nothing is changed.
3. **Verified backup.** The database, uploaded files and keys go to a private
   directory, which is then verified (see
   [Pre-upgrade backups](#pre-upgrade-backups)). A backup that does not
   verify stops the upgrade, and nothing is changed.
4. **Install.** Apply runs `deploy/update_instructions.sh` *from the target
   revision* (not from main): check out the sha, install the requirements,
   re-check the backup, migrate, collect static files, update the root
   helper's system config, then reload the service.
   - If dependencies fail to install, the old code is put back. The database
     was not touched.
   - If the migration fails, the script prints the
     [migration diagnosis](#half-applied-migrations-on-mysqlmariadb) and the
     recovery commands. The service is not reloaded, so it keeps running the
     old code. See [If an upgrade fails](#if-an-upgrade-fails-or-is-interrupted).

Every stage is recorded in `backups/upgrades/journal.json`, so an interrupted
upgrade is recognised afterwards. Each run is also written to the audit log
(`system_update` / `system_update_failed`, with the output tail).

## Upgrade from the command line

Use this when the web UI is unavailable. It runs the same pipeline:

```bash
cd /path/to/clientst0r
venv/bin/python manage.py upgrade_apply          # shows installed / stable / preview, asks first
venv/bin/python manage.py upgrade_preflight      # only the checks
```

`./update.sh` and `bash install.sh` (option 1) both run `upgrade_apply`.
The nightly `clientst0r-auto-update.timer` runs `upgrade_apply --auto`, which
follows the instance's channel.

To install a specific reviewed revision:

```bash
venv/bin/python manage.py upgrade_apply --ref v3.17.640 --sha <full commit sha>
```

An install older than this pipeline downloads `deploy/update_instructions.sh`
from main when you click Apply. The script detects that ("legacy mode"), so
the first upgrade from an older release also takes and verifies a backup
before migrating.

## Docker

A container has no git checkout, so **Settings → Updates** cannot apply an
upgrade in Docker. To upgrade:

```bash
cd clientst0r
git pull                 # new docker-compose.yml / docker files
docker compose pull      # or: docker compose build
docker compose up -d
```

When a new image brings migrations and the database already holds data, the
entrypoint takes and verifies a backup in the `clientst0r-backups` volume
first. If the backup does not verify, the container stops instead of
migrating. Its log gives the reason. `CLIENTST0R_SKIP_PRE_MIGRATE_BACKUP=1`
overrides this, if you keep your own backups.

The restore test needs a scratch database, `<DB_NAME>_verify`. New stacks
grant it on first start (`docker/mariadb/initdb/`). For a stack created
before that, run once:

```bash
docker compose exec db mariadb -uroot -p \
  -e "GRANT ALL PRIVILEGES ON \`clientst0r_verify\`.* TO 'clientst0r'@'%';"
```

Without the grant, the backup is still taken but only checked structurally.

To list backups, or to restore one (stop the scheduler first):

```bash
docker compose exec app python manage.py upgrade_backup --list
docker compose stop scheduler
docker compose exec app python manage.py upgrade_restore /app/backups/upgrades/snapshot-... --no-code --yes
docker compose up -d
```

Use `--no-code` because the image *is* the code. Run the image tag that
matches the backup (`CLIENTST0R_IMAGE=ghcr.io/agit8or1/clientst0r:<version>`).
The backup's manifest records the version.

## Pre-upgrade backups

Pre-upgrade backups go to `backups/upgrades/` in the install directory, or to
`CLIENTST0R_BACKUP_DIR`. Each backup is a directory, `snapshot-<time>-v<version>/`.
The directory is mode 700 and every file in it is mode 600:

| File | Contents |
|---|---|
| `database.sqlite3` / `database.sql` | SQLite online copy, or `mysqldump --single-transaction` |
| `media.tar` | every uploaded file (attachments, pictures, documents) |
| `keys.env` | `SECRET_KEY`, `APP_MASTER_KEY` (and previous keys), `API_KEY_SECRET`, `DB_*` |
| `env.file` | a copy of `.env` (native installs) |
| `manifest.json` | code revision, versions, row counts, applied migrations, checksums, key fingerprints |
| `verification.json` | the result of the verification |

**The keys are in the backup on purpose.** Vault entries, secure notes, TOTP
secrets and integration credentials are encrypted with `APP_MASTER_KEY`. A
database restored without that key is unreadable.

**Verification** checks each of these:

- every file's checksum
- the permissions
- the keys are present and valid
- the media archive reads to the end

Then it restores the database into a scratch copy and checks it:

- SQLite: `PRAGMA integrity_check`
- MySQL/MariaDB: a restore into `<DB_NAME>_verify`

It compares the tables, row counts and applied migrations with the manifest,
and decrypts sample vault entries using only the key stored in the backup.
On MySQL without a scratch database, the check is structural instead: a
complete dump, every table, and the migration history.

To take one by hand, or to list them:

```bash
venv/bin/python manage.py upgrade_backup --reason "before maintenance"
venv/bin/python manage.py upgrade_backup --list
venv/bin/python manage.py upgrade_backup --verify backups/upgrades/snapshot-...
```

Old backups are not deleted automatically. Remove the ones you no longer need.

## If an upgrade fails or is interrupted

Start here:

```bash
venv/bin/python manage.py upgrade_status
```

It reads the journal and says what happened: the stage, the backup, and
whether the database was touched. It exits with 2 when something needs doing.
While an upgrade needs recovery, Apply is disabled, and **Settings → Updates**
shows a recovery panel with the same information.

| Stopped at | Database | What to do |
|---|---|---|
| before the code changed (revision, preflight, backup) | untouched | Nothing to recover; fix the reported cause and apply again. |
| after checkout, before migrating | untouched | `upgrade_apply --resume` to finish, or `upgrade_restore <backup>` to put the old code back. |
| during or after migrating | changed | Run `migration_doctor` first. Then either `upgrade_apply --resume` once the cause is fixed, or `upgrade_restore <backup>` to go back. |

`upgrade_apply --resume` continues the same reviewed revision with the same
verified backup. It does not take a new one, because the database may already
be partly migrated.

Before it backs up or migrates, every upgrade (resumed or not) runs
`migration_doctor --check`. If a pending migration is already partly in the
schema, the upgrade stops without migrating and without backing up the
damaged database, and prints the diagnosis. See the next section.

## Half-applied migrations on MySQL/MariaDB

MySQL and MariaDB commit every `ALTER TABLE` / `CREATE TABLE` on its own; a
migration cannot be rolled back. If a migration with several operations dies
partway (a crash, a killed process, an error in a later statement), its first
operations stay applied but the migration is not recorded. The next `migrate`
fails with *Duplicate column name*, *Table ... already exists* or *Can't DROP*
(issues #128, #129, #86). SQLite and PostgreSQL run each migration in a
transaction, so they are not affected.

**Detect it:**

```bash
venv/bin/python manage.py migration_doctor
```

For the first unapplied migration of each app, it compares every operation
with the live schema and reports one of:

- **not started**: nothing of it is in the database. Re-running the upgrade
  continues.
- **applied, unrecorded**: every schema change is present, but the record is
  missing.
- **partial**: some operations are present and some are not.
- **unknown**: only data steps, which the schema cannot show.

**Recover. The safe way is always to restore the verified backup:**

```bash
venv/bin/python manage.py upgrade_status            # shows the backup path
sudo systemctl stop clientst0r-gunicorn.service clientst0r-scheduler.timer
venv/bin/python manage.py upgrade_restore backups/upgrades/snapshot-...
sudo systemctl start clientst0r-gunicorn.service clientst0r-scheduler.timer
```

Then fix the cause and apply again.

**Faking is only safe in one case:** the doctor says *applied, unrecorded*
and the migration has no data step (the doctor says when it does). Then:

```bash
venv/bin/python manage.py migrate <app> <migration> --fake
venv/bin/python manage.py migrate
```

Never `--fake` a **partial** migration. Its remaining operations would never
run, and the schema would silently differ from what the code expects. Never
run `makemigrations` on an install, either: locally generated migration files
conflict with the ones the next release ships (#91, #110).

## Restoring a backup

```bash
venv/bin/python manage.py upgrade_restore [backup-dir] [--no-code] [--restore-keys] [--yes]
```

With no path, `upgrade_restore` uses the backup recorded in the journal. It
then does the following:

- Refuses an unverified backup, or a backup whose `APP_MASTER_KEY` differs
  from the instance's, because the vault would not decrypt. If you want the
  backup's `.env` back, pass `--restore-keys`.
- Puts back the code revision recorded in the backup (`git reset --hard` plus
  its requirements), unless you pass `--no-code`.
- Restores the database. On MySQL it drops every table first, including any
  that a partial migration created. On SQLite it keeps the current file as
  `db.sqlite3.before-restore-<time>`.
- Restores the uploaded files. The current ones are moved to
  `media.before-restore-<time>`.
- Runs `migrate --check`, and tells you to restart the service.

Stop the web service and the scheduler while restoring. On a native install,
start them again afterwards.

## Moving a backup off the host

A backup sits next to `.env` and is protected the same way, by owner-only
permissions. To keep a copy elsewhere, export it as one passphrase-encrypted
file (scrypt + AES-GCM):

```bash
venv/bin/python manage.py upgrade_backup --export backups/upgrades/snapshot-... \
    --to /secure/place/clientst0r-backup.cs0r --passphrase-file /root/backup-passphrase
venv/bin/python manage.py upgrade_backup --import /secure/place/clientst0r-backup.cs0r \
    --passphrase-file /root/backup-passphrase      # unpacks and verifies it
```

The encrypted `manage.py backup` archive (see [AUTO_UPDATE.md](../AUTO_UPDATE.md))
is still available for routine backups. It is encrypted *with*
`APP_MASTER_KEY`, so store that key separately.
