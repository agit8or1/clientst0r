#!/bin/bash
# Client St0r Docker entrypoint
#
# Order of operations:
#   1. Wait for the database to accept connections (only for the
#      MariaDB / MySQL path; skipped when DB_ENGINE=sqlite3 since
#      SQLite has no readiness wait).
#   2. If this image brings migrations the database does not have yet and
#      the database already holds data (an upgrade, not a first start):
#      take and verify a pre-upgrade backup (database, uploads, keys) in
#      the backups volume. No verified backup, no migration -- the
#      container stops with the reason instead (set
#      CLIENTST0R_SKIP_PRE_MIGRATE_BACKUP=1 to override).
#   3. Apply migrations.
#   4. Collect static files into the shared volume.
#   5. Bootstrap a superuser if env vars are provided (idempotent).
#   6. Exec the CMD (gunicorn by default).
#
# With CLIENTST0R_SKIP_SETUP=1 (the `scheduler` service) steps 2-5 are
# skipped: the `app` container owns them.
#
# Values from the environment are read by Python from os.environ, never
# pasted into code: a password containing a quote must not break (or
# inject into) the commands below.

set -e

echo "Client St0r container starting..."

if [ "${DB_ENGINE:-mysql}" != "sqlite3" ]; then
    echo "Waiting for database at ${DB_HOST}:${DB_PORT:-3306}..."
    until python - <<'PY' 2>/dev/null
import os, MySQLdb
MySQLdb.connect(host=os.environ.get('DB_HOST', 'localhost'),
                port=int(os.environ.get('DB_PORT') or 3306),
                user=os.environ.get('DB_USER', ''), passwd=os.environ.get('DB_PASSWORD', ''),
                db=os.environ.get('DB_NAME', '')).close()
PY
    do
        echo "  DB unavailable — sleeping 2s"
        sleep 2
    done
    echo "Database is up."
fi

# The `scheduler` service in docker-compose.yml shares this image and starts
# after `app` is healthy; it sets CLIENTST0R_SKIP_SETUP=1 so two containers
# never race each other through migrate/collectstatic.
if [ "${CLIENTST0R_SKIP_SETUP:-0}" = "1" ]; then
    echo "Skipping migrations/static/superuser setup (CLIENTST0R_SKIP_SETUP=1)"
    echo "Starting: $*"
    exec "$@"
fi

if ! python manage.py migrate --check >/dev/null 2>&1; then
    APPLIED=$(python manage.py shell -c "
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
print(len(MigrationRecorder(connection).applied_migrations()) if MigrationRecorder(connection).has_table() else 0)
" 2>/dev/null | tail -1)
    if [ "${APPLIED:-0}" -gt 0 ] 2>/dev/null; then
        echo "This image brings database migrations: an upgrade."
        if python manage.py upgrade_status >/dev/null 2>&1; then :; else
            echo "An earlier upgrade did not finish:"
            python manage.py upgrade_status || true
        fi
        if [ "${CLIENTST0R_SKIP_PRE_MIGRATE_BACKUP:-0}" = "1" ]; then
            echo "WARNING: CLIENTST0R_SKIP_PRE_MIGRATE_BACKUP=1 -- migrating without a backup."
        else
            echo "Taking and verifying a pre-upgrade backup (database, uploads, keys)..."
            if ! python manage.py upgrade_backup --reason "before migrating to the image's version"; then
                echo "ERROR: could not take a verified backup, so the database was NOT migrated."
                echo "ERROR: fix the problem above (backup volume writable? disk space?) and restart,"
                echo "ERROR: or set CLIENTST0R_SKIP_PRE_MIGRATE_BACKUP=1 if you have your own backup."
                echo "ERROR: See docs/UPGRADE_AND_RECOVERY.md."
                exit 1
            fi
        fi
    fi
fi

echo "Running migrations..."
if ! python manage.py migrate --noinput; then
    echo "ERROR: database migration failed. Diagnosis:"
    python manage.py migration_doctor || true
    echo "Recovery: docs/UPGRADE_AND_RECOVERY.md (restore the backup listed by"
    echo "  docker compose run --rm app python manage.py upgrade_backup --list )"
    exit 1
fi

echo "Collecting static files..."
python manage.py collectstatic --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && \
   [ -n "$DJANGO_SUPERUSER_PASSWORD" ] && \
   [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
    echo "Bootstrapping superuser '$DJANGO_SUPERUSER_USERNAME'..."
    python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
User = get_user_model()
name = os.environ['DJANGO_SUPERUSER_USERNAME']
if not User.objects.filter(username=name).exists():
    User.objects.create_superuser(name, os.environ['DJANGO_SUPERUSER_EMAIL'],
                                  os.environ['DJANGO_SUPERUSER_PASSWORD'])
    print('  superuser created')
else:
    print('  superuser already exists — skipping')
" || echo "  (superuser bootstrap failed; non-fatal)"
fi

echo "Starting: $*"
exec "$@"
