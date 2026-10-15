#!/bin/bash
# Client St0r Docker entrypoint
#
# Order of operations:
#   1. Wait for the database to accept connections (only for the
#      MariaDB / MySQL path; skipped when DB_ENGINE=sqlite3 since
#      SQLite has no readiness wait).
#   2. Apply migrations.
#   3. Collect static files into the shared volume.
#   4. Bootstrap a superuser if env vars are provided (idempotent).
#   5. Exec the CMD (gunicorn by default).
#
# With CLIENTST0R_SKIP_SETUP=1 (the `scheduler` service) steps 2-4 are
# skipped: the `app` container owns them.

set -e

echo "Client St0r container starting..."

if [ "${DB_ENGINE:-mysql}" != "sqlite3" ]; then
    echo "Waiting for database at ${DB_HOST}:${DB_PORT:-3306}..."
    until python -c "import MySQLdb; MySQLdb.connect(host='${DB_HOST}', \
            port=int('${DB_PORT:-3306}'), \
            user='${DB_USER}', passwd='${DB_PASSWORD}', \
            db='${DB_NAME}')" 2>/dev/null; do
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

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && \
   [ -n "$DJANGO_SUPERUSER_PASSWORD" ] && \
   [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
    echo "Bootstrapping superuser '$DJANGO_SUPERUSER_USERNAME'..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists():
    User.objects.create_superuser(
        '$DJANGO_SUPERUSER_USERNAME',
        '$DJANGO_SUPERUSER_EMAIL',
        '$DJANGO_SUPERUSER_PASSWORD',
    )
    print('  superuser created')
else:
    print('  superuser already exists — skipping')
" || echo "  (superuser bootstrap failed; non-fatal)"
fi

echo "Starting: $*"
exec "$@"
