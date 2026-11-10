#!/bin/bash
# Upgrade rehearsal: install an old release on disposable data, fill it with
# representative records, upgrade it (through several releases if asked) to
# the code under test, and prove everything still works. Also rehearses an
# interrupted upgrade and its recovery.
#
# NEVER point this at a real install. Everything happens under $REHEARSAL_WORK:
# its own git remote, checkout, venv, .env, database and gunicorn on a free
# port. The update script runs with CLIENTST0R_UPDATE_SANDBOX=1, so it does not
# touch crontab, sudoers, systemd, the root helper or any other gunicorn.
#
# Usage:
#   REHEARSAL_WORK=/tmp/x scripts/upgrade_rehearsal/rehearse.sh fresh
#   REHEARSAL_WORK=/tmp/x scripts/upgrade_rehearsal/rehearse.sh upgrade v3.17.558 v3.17.640
#   REHEARSAL_WORK=/tmp/x scripts/upgrade_rehearsal/rehearse.sh interrupt v3.17.640
#
#   fresh                 fresh install of the code under test, seed, all checks
#   upgrade R1 [R2 ...]   install R1, seed, check; upgrade to each later Rn the way
#                         that release's updater did (reset, pip, migrate,
#                         collectstatic), check; then to the code under test the
#                         way an older Client St0r does it (it downloads main's
#                         deploy/update_instructions.sh: "legacy mode"), check; then
#                         a pinned, signed-release upgrade with `upgrade_apply`,
#                         including the refusals (wrong sha, unsigned / untrusted
#                         tag, preview on Stable, moved branch), check
#   interrupt R           install R, seed; start the upgrade to the code under test
#                         and SIGKILL it mid-migration; restore the verified backup,
#                         check (back on R); interrupt again and resume, check; then
#                         a half-applied migration (first statement applied by hand,
#                         as a crash on MySQL leaves it): migration fails, doctor
#                         diagnoses it, restore, upgrade again, check
#
# Environment:
#   REHEARSAL_WORK     scratch directory (required)
#   REHEARSAL_SOURCE   git repository with the refs (default: this checkout)
#   REHEARSAL_HEAD     commit under test (default: HEAD of REHEARSAL_SOURCE)
#   REHEARSAL_PYTHON   interpreter for a new venv (default: python3)
#   REHEARSAL_VENV     use this (scratch!) venv instead of creating one; it is
#                      pip-installed into as the upgrade proceeds
#   REHEARSAL_DB       sqlite (default) or mysql
#   REHEARSAL_MYSQL_HOST/PORT/USER/PASSWORD/DATABASE, REHEARSAL_MYSQL_ROOT_PASSWORD
#   REHEARSAL_PORT     port for gunicorn (default: a free one)
set -euo pipefail

MODE="${1:?mode: fresh | upgrade REF... | interrupt REF}"
shift || true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${REHEARSAL_WORK:?set REHEARSAL_WORK to a scratch directory}"
SOURCE="${REHEARSAL_SOURCE:-$(cd "$HERE/../.." && pwd)}"
PYTHON="${REHEARSAL_PYTHON:-python3}"
DB="${REHEARSAL_DB:-sqlite}"

mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
REMOTE="$WORK/remote.git"
APP="$WORK/app"
STATE="$WORK/state.json"
LOGS="$WORK/logs"
mkdir -p "$LOGS"
GIT() { git -c advice.detachedHead=false "$@"; }

say() { echo "[rehearsal $(date '+%H:%M:%S')] $*"; }
die() { say "FAILED: $*"; exit 1; }

case "$APP" in
    /home/administrator|/home/administrator/*) case "$APP" in */.claude/*|*/tmp/*) ;; *) die "refusing to run inside /home/administrator";; esac ;;
esac

HEAD_SHA="$(GIT -C "$SOURCE" rev-parse "${REHEARSAL_HEAD:-HEAD}^{commit}")"
PORT="${REHEARSAL_PORT:-$("$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')}"
BASE_URL="http://127.0.0.1:$PORT"

# ---------------------------------------------------------------------------
setup_remote() {
    rm -rf "$REMOTE"
    GIT clone -q --bare "$SOURCE" "$REMOTE"
    GIT --git-dir="$REMOTE" fetch -q "$SOURCE" "+$HEAD_SHA:refs/heads/rehearsal-head" 2>/dev/null || true
    GIT --git-dir="$REMOTE" fetch -q --tags "$SOURCE" 2>/dev/null || true
}

set_remote_main() { GIT --git-dir="$REMOTE" update-ref refs/heads/main "$1"; }

sha_of() { GIT --git-dir="$REMOTE" rev-parse "$1^{commit}"; }

venv_python() { echo "$APP/venv/bin/python"; }

manage() { (cd "$APP" && "$(venv_python)" manage.py "$@"); }

write_env() {
    local key secret api
    key=$("$PYTHON" -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())")
    secret=$("$PYTHON" -c "import secrets; print(secrets.token_urlsafe(50))")
    api=$("$PYTHON" -c "import secrets; print(secrets.token_urlsafe(50))")
    umask 077
    {
        echo "DEBUG=False"
        echo "SECRET_KEY=$secret"
        echo "APP_MASTER_KEY=$key"
        echo "API_KEY_SECRET=$api"
        echo "ALLOWED_HOSTS=127.0.0.1,localhost"
        echo "CSRF_TRUSTED_ORIGINS=$BASE_URL"
        echo "SECURE_SSL_REDIRECT=False"
        echo "SESSION_COOKIE_SECURE=False"
        echo "CSRF_COOKIE_SECURE=False"
        echo "SECURE_HSTS_SECONDS=0"
        echo "REQUIRE_2FA=True"
        echo "HIBP_ENABLED=False"
        echo "HIBP_CHECK_ON_SAVE=False"
        echo "EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend"
        echo "AUTO_UPDATE_ENABLED=False"
        if [ "$DB" = "mysql" ]; then
            echo "DB_ENGINE=mysql"
            echo "DB_HOST=${REHEARSAL_MYSQL_HOST:-127.0.0.1}"
            echo "DB_PORT=${REHEARSAL_MYSQL_PORT:-3306}"
            echo "DB_NAME=${REHEARSAL_MYSQL_DATABASE:-clientst0r}"
            echo "DB_USER=${REHEARSAL_MYSQL_USER:-clientst0r}"
            echo "DB_PASSWORD=${REHEARSAL_MYSQL_PASSWORD:?}"
        else
            echo "DB_ENGINE=sqlite3"
        fi
    } > "$APP/.env"
    umask 022
}

reset_mysql() {
    [ "$DB" = "mysql" ] || return 0
    local db="${REHEARSAL_MYSQL_DATABASE:-clientst0r}"
    mysql -h "${REHEARSAL_MYSQL_HOST:-127.0.0.1}" -P "${REHEARSAL_MYSQL_PORT:-3306}" -uroot \
        -p"${REHEARSAL_MYSQL_ROOT_PASSWORD:?}" -e \
        "DROP DATABASE IF EXISTS \`$db\`; CREATE DATABASE \`$db\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
         DROP DATABASE IF EXISTS \`${db}_verify\`;"
}

ensure_venv() {
    if [ -n "${REHEARSAL_VENV:-}" ]; then
        ln -sfn "$REHEARSAL_VENV" "$APP/venv"
    else
        if [ ! -x "$WORK/venv/bin/python" ]; then
            "$PYTHON" -m venv "$WORK/venv"
            "$WORK/venv/bin/pip" install -q --upgrade pip
        fi
        ln -sfn "$WORK/venv" "$APP/venv"
    fi
}

install_ref() {   # fresh install of a ref, the way install.sh does the Python side
    local ref="$1" sha
    sha="$(sha_of "$ref")"
    say "installing $ref ($sha)"
    stop_server
    rm -rf "$APP"
    set_remote_main "$sha"
    GIT clone -q "$REMOTE" "$APP"
    GIT -C "$APP" checkout -q -B main "$sha"
    GIT -C "$APP" branch -q --set-upstream-to=origin/main main
    ensure_venv
    write_env
    reset_mysql
    "$APP/venv/bin/pip" install -q -r "$APP/requirements.txt" > "$LOGS/pip-$ref.log" 2>&1 \
        || die "pip install for $ref (see $LOGS/pip-$ref.log)"
    manage migrate --noinput > "$LOGS/migrate-$ref.log" 2>&1 || die "migrate on $ref (see $LOGS/migrate-$ref.log)"
    manage collectstatic --noinput > /dev/null 2>&1 || die "collectstatic on $ref"
}

old_style_upgrade() {   # what the updater of releases before this one did
    local ref="$1" sha
    sha="$(sha_of "$ref")"
    say "upgrading to $ref the way its own updater does (reset, pip, migrate, collectstatic)"
    stop_server
    set_remote_main "$sha"
    GIT -C "$APP" fetch -q origin main
    GIT -C "$APP" reset -q --hard origin/main
    "$APP/venv/bin/pip" install -q -r "$APP/requirements.txt" > "$LOGS/pip-$ref.log" 2>&1 || die "pip for $ref"
    manage migrate --noinput > "$LOGS/migrate-$ref.log" 2>&1 || die "migrate to $ref (see $LOGS/migrate-$ref.log)"
    manage collectstatic --noinput > /dev/null 2>&1 || die "collectstatic on $ref"
}

legacy_script() {   # the update script an older Client St0r downloads from main
    local out="$WORK/update_instructions.legacy.sh"
    GIT --git-dir="$REMOTE" show "$HEAD_SHA:deploy/update_instructions.sh" > "$out"
    echo "$out"
}

legacy_upgrade_to_head() {
    local log="$LOGS/legacy-upgrade.log"
    say "upgrading to the code under test ($HEAD_SHA) via main's update script (legacy mode)"
    stop_server
    set_remote_main "$HEAD_SHA"
    CLIENTST0R_BASE_DIR="$APP" CLIENTST0R_SERVICE_NAME="" CLIENTST0R_UPDATE_SANDBOX=1 PYTHONUNBUFFERED=1 \
        bash "$(legacy_script)" > "$log" 2>&1 || { tail -40 "$log"; die "legacy-mode upgrade (see $log)"; }
    grep -q "Verified backup" "$log" || die "legacy upgrade did not take a verified backup"
    grep -q "Update complete" "$log" || die "legacy upgrade did not complete"
    say "legacy-mode upgrade complete; backup: $(grep -o 'Verified backup: .*' "$log" | tail -1)"
}

start_server() {
    stop_server
    (cd "$APP" && "$APP/venv/bin/python" -m gunicorn config.wsgi:application -b "127.0.0.1:$PORT" \
        --workers 2 --timeout 120 --daemon --pid "$WORK/gunicorn.pid" \
        --error-logfile "$LOGS/gunicorn.log" --capture-output)
    for _ in $(seq 1 60); do
        if curl -fsS "$BASE_URL/health/" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    tail -30 "$LOGS/gunicorn.log" || true
    die "server did not come up on $BASE_URL"
}

stop_server() {
    if [ -f "$WORK/gunicorn.pid" ]; then
        kill "$(cat "$WORK/gunicorn.pid")" 2>/dev/null || true
        for _ in $(seq 1 20); do kill -0 "$(cat "$WORK/gunicorn.pid")" 2>/dev/null || break; sleep 0.5; done
        rm -f "$WORK/gunicorn.pid"
    fi
}

checks() {   # $1 = label
    local label="$1" version
    version=$(cd "$APP" && "$(venv_python)" -c "from config.version import VERSION; print(VERSION)")
    say "checks [$label] on v$version @ $(GIT -C "$APP" rev-parse --short HEAD)"
    manage migrate --check > "$LOGS/check-$label.log" 2>&1 || { cat "$LOGS/check-$label.log"; die "migrate --check [$label]"; }
    if manage showmigrations --plan 2>/dev/null | grep -q '^\[ \]'; then die "unapplied migrations [$label]"; fi
    say "  ok    migrate --check / showmigrations: nothing unapplied"
    (cd "$APP" && REHEARSAL_STATE="$STATE" "$(venv_python)" manage.py shell -c \
        "exec(open('$HERE/verify_data.py').read())") || die "verify_data [$label]"
    start_server
    "$(venv_python)" "$HERE/http_smoke.py" --base "$BASE_URL" --state "$STATE" \
        --expect-version "$version" --require-2fa || die "http_smoke [$label]"
    stop_server
}

seed() {
    say "seeding representative records"
    (cd "$APP" && REHEARSAL_STATE="$STATE" "$(venv_python)" manage.py shell -c \
        "exec(open('$HERE/seed.py').read())") || die "seed"
}

# --- pinned, signed-release hop ---------------------------------------------
make_signed_release() {   # sets REL_SHA, REL_TAG; also UNSIGNED/UNTRUSTED tags
    local src="$WORK/release-src" keys="$WORK/signing"
    rm -rf "$src" "$keys"
    mkdir -p "$keys"
    ssh-keygen -q -t ed25519 -N '' -C rehearsal-release -f "$keys/release" >/dev/null
    ssh-keygen -q -t ed25519 -N '' -C untrusted -f "$keys/untrusted" >/dev/null
    echo "release@rehearsal namespaces=\"git\" $(cat "$keys/release.pub")" > "$keys/allowed_signers"
    GIT clone -q "$REMOTE" "$src"
    GIT -C "$src" checkout -q -B main "$HEAD_SHA"
    sed -i "s/^VERSION = .*/VERSION = '3.99.0'/" "$src/config/version.py"
    # Marker: proves the update script that runs is the target revision's copy.
    sed -i 's/^log "Client St0r Update Instructions"$/log "Client St0r Update Instructions"\nlog "rehearsal-marker: update script from the v3.99.0 revision"/' \
        "$src/deploy/update_instructions.sh"
    GIT -C "$src" -c user.name=rehearsal -c user.email=rehearsal@example.invalid \
        commit -q -am "rehearsal release 3.99.0 (scratch only)"
    REL_SHA="$(GIT -C "$src" rev-parse HEAD)"
    REL_TAG=v3.99.0
    GIT -C "$src" -c gpg.format=ssh -c user.signingkey="$keys/release.pub" \
        -c user.name=rehearsal -c user.email=rehearsal@example.invalid tag -s -m "v3.99.0" "$REL_TAG"
    GIT -C "$src" -c user.name=rehearsal -c user.email=rehearsal@example.invalid tag -a -m "unsigned" v3.99.1
    GIT -C "$src" -c gpg.format=ssh -c user.signingkey="$keys/untrusted.pub" \
        -c user.name=rehearsal -c user.email=rehearsal@example.invalid tag -s -m "untrusted" v3.99.2
    GIT -C "$src" push -q "$REMOTE" "main:refs/heads/main" "$REL_TAG" v3.99.1 v3.99.2
    export CLIENTST0R_RELEASE_SIGNERS_FILE="$keys/allowed_signers"
}

expect_refusal() {   # $1 label, rest: upgrade_apply args
    local label="$1"; shift
    local before; before="$(GIT -C "$APP" rev-parse HEAD)"
    set +e
    CLIENTST0R_UPDATE_SANDBOX=1 manage upgrade_apply "$@" --skip-deps-check > "$LOGS/refusal-$label.log" 2>&1
    local code=$?
    set -e
    [ "$code" -eq 4 ] || { cat "$LOGS/refusal-$label.log"; die "expected refusal ($label), exit $code"; }
    [ "$(GIT -C "$APP" rev-parse HEAD)" = "$before" ] || die "refusal ($label) changed the checkout"
    say "  ok    refused: $label -- $(grep -m1 'REFUSED' "$LOGS/refusal-$label.log" | cut -c1-160)"
}

pinned_release_upgrade() {
    make_signed_release
    say "pinned upgrade to signed release $REL_TAG @ $REL_SHA (and the refusals)"
    expect_refusal wrong-sha --ref "$REL_TAG" --sha "$HEAD_SHA"
    expect_refusal unsigned-tag --ref v3.99.1 --sha "$REL_SHA"
    expect_refusal untrusted-key --ref v3.99.2 --sha "$REL_SHA"
    expect_refusal preview-on-stable --kind preview --ref main --sha "$REL_SHA"
    expect_refusal main-moved --kind preview --ref main --sha "$HEAD_SHA" --allow-preview
    CLIENTST0R_UPDATE_SANDBOX=1 PYTHONUNBUFFERED=1 manage upgrade_apply --ref "$REL_TAG" --sha "$REL_SHA" \
        > "$LOGS/pinned-upgrade.log" 2>&1 || { tail -60 "$LOGS/pinned-upgrade.log"; die "pinned upgrade"; }
    grep -q "Release tag signature verified" "$LOGS/pinned-upgrade.log" || die "no signature verification logged"
    grep -q "rehearsal-marker: update script from the v3.99.0 revision" "$LOGS/pinned-upgrade.log" \
        || die "the update script that ran was not the target revision's"
    [ "$(GIT -C "$APP" rev-parse HEAD)" = "$REL_SHA" ] || die "checkout is not the reviewed sha"
    say "  ok    installed exactly $REL_SHA; signature verified; target revision's update script ran"
}

# --- interruption ------------------------------------------------------------
interrupt_upgrade() {   # start the legacy-mode upgrade, SIGKILL it during migrate
    local log="$LOGS/interrupted-$1.log"
    set_remote_main "$HEAD_SHA"
    stop_server
    (CLIENTST0R_BASE_DIR="$APP" CLIENTST0R_SERVICE_NAME="" CLIENTST0R_UPDATE_SANDBOX=1 PYTHONUNBUFFERED=1 \
        setsid bash "$(legacy_script)" > "$log" 2>&1) &
    local pid=$! pgid=""
    for _ in $(seq 1 1200); do
        if grep -q "Applying " "$log" 2>/dev/null; then break; fi
        if ! kill -0 "$pid" 2>/dev/null; then tail -30 "$log"; die "upgrade ended before migrating"; fi
        sleep 0.1
    done
    pgid=$(ps -o pgid= -p "$(pgrep -f "update_instructions.legacy.sh" | head -1)" 2>/dev/null | tr -d ' ' || true)
    if [ -n "$pgid" ]; then kill -KILL -- "-$pgid" 2>/dev/null || true; fi
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    say "killed the upgrade mid-migration: $(grep 'Applying ' "$log" | tail -1 | sed 's/^ *//' | cut -c1-100)"
}

partial_migration() {   # apply only the first statement of the first new migration
    local first app name sql
    first=$(cd "$APP" && GIT diff --name-only --diff-filter=A HEAD "$HEAD_SHA" -- '*/migrations/0*.py' | sort | head -1)
    app=$(echo "$first" | cut -d/ -f1); name=$(basename "$first" .py)
    say "simulating a crash inside $app.$name: applying only its first SQL statement"
    GIT -C "$APP" show "$HEAD_SHA:$first" > /dev/null
    # sqlmigrate needs the new code; run it from a throwaway checkout of HEAD.
    rm -rf "$WORK/head-src"; GIT clone -q "$REMOTE" "$WORK/head-src"; GIT -C "$WORK/head-src" checkout -q "$HEAD_SHA"
    cp "$APP/.env" "$WORK/head-src/.env"
    sql=$(cd "$WORK/head-src" && "$(venv_python)" manage.py sqlmigrate "$app" "$name" 2>/dev/null \
          | grep -v '^--' | grep -v '^BEGIN;$' | grep -v '^COMMIT;$' | awk 'BEGIN{RS=";\n"} NR==1{print; exit}')
    [ -n "$sql" ] || die "could not get SQL for $app.$name"
    (cd "$WORK/head-src" && echo "$sql;" | "$(venv_python)" manage.py dbshell >/dev/null 2>&1) || \
    (cd "$WORK/head-src" && "$(venv_python)" -c "
import os, django, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup()
from django.db import connection
with connection.cursor() as c: c.execute(sys.stdin.read())
" <<< "$sql") || die "applying the first statement of $app.$name"
    rm -rf "$WORK/head-src"
    PARTIAL="$app.$name"
}

# ---------------------------------------------------------------------------
setup_remote
case "$MODE" in
    fresh)
        install_ref "$HEAD_SHA"
        seed
        checks fresh
        ;;
    upgrade)
        [ $# -ge 1 ] || die "upgrade needs at least one starting ref"
        first="$1"; shift
        install_ref "$first"
        seed
        checks "$first"
        for ref in "$@"; do
            old_style_upgrade "$ref"
            checks "$ref"
        done
        legacy_upgrade_to_head
        checks head-legacy
        manage upgrade_status > "$LOGS/status-after-legacy.log" || die "journal says the legacy upgrade needs recovery"
        pinned_release_upgrade
        checks release-pinned
        ;;
    interrupt)
        [ $# -eq 1 ] || die "interrupt needs one starting ref"
        start="$1"
        install_ref "$start"
        seed
        checks "$start"

        say "== interruption 1: kill mid-migration, then restore the verified backup"
        interrupt_upgrade 1
        set +e; manage upgrade_status > "$LOGS/status-1.log" 2>&1; code=$?; set -e
        cat "$LOGS/status-1.log"
        [ "$code" -eq 2 ] || die "upgrade_status should report an interrupted upgrade (exit 2), got $code"
        manage migration_doctor | tee "$LOGS/doctor-1.log"
        manage upgrade_restore --yes | tee "$LOGS/restore-1.log"
        checks "restored-$start"
        [ "$(GIT -C "$APP" rev-parse HEAD)" = "$(sha_of "$start")" ] || die "restore did not put the $start code back"

        say "== interruption 2: kill mid-migration, then resume the same revision"
        interrupt_upgrade 2
        set +e; manage upgrade_status > "$LOGS/status-2.log" 2>&1; code=$?; set -e
        [ "$code" -eq 2 ] || die "expected an interrupted upgrade (exit 2), got $code"
        CLIENTST0R_UPDATE_SANDBOX=1 PYTHONUNBUFFERED=1 manage upgrade_apply --resume \
            > "$LOGS/resume.log" 2>&1 || { tail -50 "$LOGS/resume.log"; die "resume"; }
        grep -q "Reusing the pre-upgrade backup" "$LOGS/resume.log" || die "resume did not reuse the verified backup"
        checks resumed-head

        say "== half-applied migration (what a crash leaves on MySQL/MariaDB)"
        manage upgrade_restore --yes > "$LOGS/restore-2.log"
        checks "restored-again-$start"
        partial_migration
        set +e
        CLIENTST0R_BASE_DIR="$APP" CLIENTST0R_SERVICE_NAME="" CLIENTST0R_UPDATE_SANDBOX=1 PYTHONUNBUFFERED=1 \
            bash "$(legacy_script)" > "$LOGS/partial-upgrade.log" 2>&1
        code=$?
        set -e
        [ "$code" -eq 3 ] || { tail -40 "$LOGS/partial-upgrade.log"; die "expected the migration to fail (exit 3), got $code"; }
        grep -A12 "Migration diagnosis" "$LOGS/partial-upgrade.log" | tee "$LOGS/doctor-partial.log"
        grep -q "$PARTIAL" "$LOGS/doctor-partial.log" || die "migration_doctor did not name $PARTIAL"
        grep -Eq "$PARTIAL: (partial|applied unrecorded)" "$LOGS/doctor-partial.log" || die "doctor did not detect the half-applied state"
        manage upgrade_restore --yes > "$LOGS/restore-3.log"
        checks "restored-after-partial-$start"
        legacy_upgrade_to_head
        checks head-after-recovery
        ;;
    *) die "unknown mode $MODE" ;;
esac
stop_server
say "ALL REHEARSAL CHECKS PASSED ($MODE)"
