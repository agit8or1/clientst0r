#!/bin/bash
# Data and HTTP checks against the running compose stack (CI only).
#
#   ci_docker_checks.sh seed     seed representative records, then check
#   ci_docker_checks.sh verify   check records seeded earlier (after an upgrade)
#
# The rehearsal scripts are piped into the container, so this also works
# against images of older releases that do not ship them. The state file
# (test secrets) stays in $RUNNER_TEMP on the runner and /tmp in the container.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${RUNNER_TEMP:-/tmp}/docker-state.json"
put() { docker exec -i clientst0r-app sh -c "umask 077; cat > $2" < "$1"; }
inside() { docker exec -e REHEARSAL_STATE=/tmp/state.json clientst0r-app "$@"; }

put "$HERE/verify_data.py" /tmp/verify_data.py
if [ "${1:-verify}" = "seed" ]; then
    put "$HERE/seed.py" /tmp/seed.py
    inside python manage.py shell -c "exec(open('/tmp/seed.py').read())"
    docker exec clientst0r-app cat /tmp/state.json > "$STATE"
    chmod 600 "$STATE"
else
    put "$STATE" /tmp/state.json
fi

inside python manage.py migrate --check
if inside python manage.py showmigrations --plan | grep -q '^\[ \]'; then
    echo "unapplied migrations"; exit 1
fi
echo "  ok    migrate --check / showmigrations: nothing unapplied"
inside python manage.py shell -c "exec(open('/tmp/verify_data.py').read())"
VERSION=$(docker exec clientst0r-app python -c "from config.version import VERSION; print(VERSION)")
python3 -m pip install -q requests
python3 "$HERE/http_smoke.py" --base http://127.0.0.1:8000 --state "$STATE" \
    --expect-version "$VERSION" --require-2fa
