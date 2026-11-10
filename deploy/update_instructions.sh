#!/bin/bash
# Client St0r Update Instructions
# Downloaded and executed by perform_update() — do not rename or move
#
# Environment variables (passed by caller):
#   CLIENTST0R_BASE_DIR      - absolute path to the project root
#   CLIENTST0R_SERVICE_NAME  - systemd service name (or empty if none)
#
# Pinned mode (core/upgrade/apply.py; Settings -> Updates and
# `manage.py upgrade_apply`):
#   CLIENTST0R_TARGET_SHA      - the exact commit the admin reviewed. The caller
#                                has already fetched it, checked that origin
#                                still points at it and (for a release) verified
#                                the tag signature. This script is the copy from
#                                that very revision (git show <sha>:...).
#   CLIENTST0R_TARGET_REF      - vX.Y.Z or main (for the log)
#   CLIENTST0R_PREV_SHA        - the revision installed before, for rollback
#   CLIENTST0R_VERIFIED_BACKUP - the verified pre-upgrade snapshot directory
#   CLIENTST0R_JOURNAL         - core/upgrade/journal.py's JSON file
#
# Without CLIENTST0R_TARGET_SHA (an older Client St0r downloaded this script
# from main) it runs in legacy mode: fetch main and reset to it, as before, but
# it still takes and verifies a backup before migrating, and records the run
# in the journal.
#
#   CLIENTST0R_UPDATE_SANDBOX=1 - rehearsal/CI only: skip everything that
#                                touches the host outside BASE_DIR (root helper,
#                                crontab, sudoers, systemd, signalling gunicorn).

set -euo pipefail

# Ensure standard system utilities are available regardless of the calling
# process's PATH (gunicorn restricts PATH to venv/bin via EnvironmentFile)
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

BASE_DIR="${CLIENTST0R_BASE_DIR:-$(dirname "$(realpath "$0")")/..}"
SERVICE="${CLIENTST0R_SERVICE_NAME:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# v3.17.595: a systemd unit with NoNewPrivileges=true (the nightly
# clientst0r-auto-update.service shipped with it until this release) makes
# sudo refuse to run and setgid crontab fail. Detect it once so the steps that
# need privilege can take another route or say plainly why they are skipped.
NO_NEW_PRIVS=0
if grep -qE '^NoNewPrivs:[[:space:]]*1' /proc/self/status 2>/dev/null; then
    NO_NEW_PRIVS=1
fi

# v3.17.597: root actions go through this one root-owned program, installed
# once by deploy/root-helper/install-root-helper.sh. See that directory.
ROOT_HELPER=/usr/local/sbin/clientst0r-root-helper

SANDBOX="${CLIENTST0R_UPDATE_SANDBOX:-0}"
TARGET_SHA="${CLIENTST0R_TARGET_SHA:-}"
TARGET_REF="${CLIENTST0R_TARGET_REF:-main}"
VERIFIED_BACKUP="${CLIENTST0R_VERIFIED_BACKUP:-}"

# Trap: log exactly which command failed and on which line
trap 'log "ERROR: command failed at line $LINENO: $BASH_COMMAND (exit $?)"' ERR

log "=================================================="
log "Client St0r Update Instructions"
log "=================================================="
log "Base directory: $BASE_DIR"
log "Service: ${SERVICE:-<none detected>}"

# --- Resolve git binary (path varies by OS / install method) ---
GIT=$(command -v git 2>/dev/null || true)
if [ -z "$GIT" ]; then
    log "ERROR: git not found in PATH. Please install git."
    exit 1
fi
log "Using git: $GIT"

# --- Venv detection (checks common names and locations) ---
VENV_DIR=""
for candidate in \
    "$BASE_DIR/venv" \
    "$BASE_DIR/.venv" \
    "$BASE_DIR/env" \
    "$BASE_DIR/clientst0r/venv" \
    "$BASE_DIR/clientst0r/.venv" \
    "$(dirname "$BASE_DIR")/venv" \
    "$(dirname "$BASE_DIR")/.venv"; do
    if [ -f "$candidate/bin/python" ]; then
        VENV_DIR="$candidate"
        break
    fi
done

if [ -z "$VENV_DIR" ]; then
    VENV_DIR=$(find "$BASE_DIR" -maxdepth 2 -type d \( -name "venv" -o -name ".venv" -o -name "env" \) 2>/dev/null | head -1 || true)
fi

if [ -z "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/python" ]; then
    log "ERROR: Virtual environment not found. Searched in $BASE_DIR and parent."
    exit 1
fi

log "Using virtual environment: $VENV_DIR"
PY="$VENV_DIR/bin/python"

JOURNAL="${CLIENTST0R_JOURNAL:-${CLIENTST0R_BACKUP_DIR:-$BASE_DIR/backups/upgrades}/journal.json}"

# journal key=value ... | key:json=<json>  -- update the upgrade journal
# (core/upgrade/journal.py). stage=X and status=X also append to history.
journal() {
    "$PY" -I - "$JOURNAL" "$@" <<'JOURNAL_EOF' || log "[WARN] could not update the upgrade journal"
import json, os, sys, tempfile, time
path, args = sys.argv[1], sys.argv[2:]
try:
    with open(path) as f:
        d = json.load(f)
except Exception:
    d = {}
for a in args:
    k, _, v = a.partition('=')
    if k.endswith(':json'):
        d[k[:-5]] = json.loads(v)
    elif k in ('stage', 'status'):
        d[k] = v
        d.setdefault('history', []).append({k: v, 'at': time.time()})
        if k == 'stage' and v == 'complete':
            d['status'] = 'complete'
    else:
        d[k] = v
d['updated_at'] = time.time()
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.journal.')
with os.fdopen(fd, 'w') as f:
    json.dump(d, f, indent=2, sort_keys=True)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
JOURNAL_EOF
}

RECOVERY_DOC="docs/UPGRADE_AND_RECOVERY.md"

# Put the code (and its dependencies) back to the revision that was installed
# before. Only used while the database is still untouched.
rollback_code() {
    local reason="$1"
    log "ERROR: $reason"
    if [ -n "${PREV_SHA:-}" ]; then
        log "Rolling the code back to ${PREV_SHA:0:12} (the database was not changed)..."
        if $GIT -C "$BASE_DIR" reset --hard "$PREV_SHA" >/dev/null 2>&1; then
            "$VENV_DIR/bin/pip" install -q -r "$BASE_DIR/requirements.txt" >/dev/null 2>&1 \
                || log "[WARN] reinstalling the previous requirements failed; run: $VENV_DIR/bin/pip install -r $BASE_DIR/requirements.txt"
            journal status=rolled_back "error=$reason"
            log "Rolled back. The running service was never reloaded, so it is unaffected."
        else
            journal status=failed "error=$reason; rollback to $PREV_SHA failed"
            log "ERROR: rollback failed. Recover with: $PY $BASE_DIR/manage.py upgrade_status"
        fi
    else
        journal status=failed "error=$reason"
    fi
    exit 1
}

# --- Service detection (if not provided by caller) ---
if [ -z "$SERVICE" ]; then
    for svc in clientst0r-gunicorn.service; do
        if /usr/bin/systemctl is-active "$svc" >/dev/null 2>&1; then
            SERVICE="$svc"
            break
        fi
    done
fi

# =====================================================================
# Step 1: Git fetch + reset
# =====================================================================
log ""
PREV_SHA="${CLIENTST0R_PREV_SHA:-$($GIT -C "$BASE_DIR" rev-parse HEAD 2>/dev/null || true)}"
if [ -n "$TARGET_SHA" ]; then
    log "Step 1/5: Fetching the reviewed revision $TARGET_REF @ $TARGET_SHA..."
    if ! [[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]]; then
        log "ERROR: CLIENTST0R_TARGET_SHA is not a full commit sha"
        journal status=aborted "error=bad target sha"
        exit 1
    fi
    if ! $GIT -C "$BASE_DIR" cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
        log "ERROR: $TARGET_SHA is not in the repository (the caller fetches it first)"
        journal status=aborted "error=target commit missing"
        exit 1
    fi
    $GIT -C "$BASE_DIR" reset --hard "$TARGET_SHA"
    if [ "$($GIT -C "$BASE_DIR" rev-parse HEAD)" != "$TARGET_SHA" ]; then
        rollback_code "checked-out revision is not $TARGET_SHA"
    fi
else
    log "Step 1/5: Fetching latest code from GitHub..."
    log "[legacy mode] an older Client St0r started this update; installing main as before"
    $GIT -C "$BASE_DIR" fetch origin main
    $GIT -C "$BASE_DIR" reset --hard origin/main
    TARGET_SHA=$($GIT -C "$BASE_DIR" rev-parse HEAD)
    PREV_VERSION=$($GIT -C "$BASE_DIR" show "$PREV_SHA:config/version.py" 2>/dev/null | grep "VERSION = " | cut -d"'" -f2 || true)
    journal status=running stage=started "prev_sha=$PREV_SHA" "prev_version=$PREV_VERSION" \
        "target:json={\"kind\": \"preview\", \"ref\": \"main\", \"sha\": \"$TARGET_SHA\"}" \
        "script_pid:json=$$" "user=legacy-updater"
fi
journal stage=code_checked_out

NEW_VERSION=$(grep "VERSION = " "$BASE_DIR/config/version.py" 2>/dev/null | cut -d"'" -f2 || echo "unknown")
log "Step 1/5: Code updated. New version: $NEW_VERSION (revision ${TARGET_SHA:0:12})"

# =====================================================================
# Step 2: Install Python dependencies
# =====================================================================
log ""
log "Step 2/5: Installing Python dependencies..."
if ! "$VENV_DIR/bin/pip" install -q -r "$BASE_DIR/requirements.txt"; then
    rollback_code "installing the new Python dependencies failed (see the pip output above)"
fi
log "Step 2/5: Core dependencies installed"
journal stage=deps_installed

# Optional requirements (non-critical)
for req_file in requirements-graphql.txt requirements-optional.txt; do
    if [ -f "$BASE_DIR/$req_file" ]; then
        log "Installing optional: $req_file"
        ( "$VENV_DIR/bin/pip" install -q -r "$BASE_DIR/$req_file" ) \
            || log "[WARN] Optional $req_file install failed (non-critical)"
    fi
done

# =====================================================================
# Step 3: Database migrations
# =====================================================================
log ""
# No verified backup, no migration. In pinned mode the caller took and verified
# it; re-check it with the new code. In legacy mode take it now: the database
# is still the old one, untouched.
if [ -n "$VERIFIED_BACKUP" ]; then
    if ! "$PY" "$BASE_DIR/manage.py" upgrade_backup --check-verified "$VERIFIED_BACKUP"; then
        rollback_code "the pre-upgrade backup $VERIFIED_BACKUP is not verified; refusing to migrate"
    fi
else
    log "Taking and verifying a pre-upgrade backup (database, uploads, keys)..."
    if BACKUP_OUT=$("$PY" "$BASE_DIR/manage.py" upgrade_backup --reason "before upgrade to $TARGET_REF" --print-path \
            --code-sha "$PREV_SHA" ${PREV_VERSION:+--code-version "$PREV_VERSION"} 2>&1); then
        VERIFIED_BACKUP=$(printf '%s\n' "$BACKUP_OUT" | tail -1)
        printf '%s\n' "$BACKUP_OUT" | sed '$d' | while IFS= read -r line; do log "$line"; done
        journal stage=backup_verified "backup=$VERIFIED_BACKUP"
        log "Verified backup: $VERIFIED_BACKUP"
    else
        printf '%s\n' "$BACKUP_OUT" | while IFS= read -r line; do log "$line"; done
        rollback_code "could not take a verified backup; refusing to migrate"
    fi
fi

log "Step 3/5: Running database migrations..."
journal stage=migrating
if ! "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" migrate --noinput; then
    log "ERROR: Database migration failed. The code is at ${TARGET_SHA:0:12}; the database may be"
    log "ERROR: partly migrated (MySQL/MariaDB cannot roll back schema changes)."
    log "ERROR: The service was NOT reloaded and still runs the previous code."
    log "Migration diagnosis (manage.py migration_doctor):"
    "$PY" "$BASE_DIR/manage.py" migration_doctor 2>&1 | while IFS= read -r line; do log "  $line"; done || true
    log "Recovery -- see $RECOVERY_DOC:"
    log "  restore the verified backup:  $PY $BASE_DIR/manage.py upgrade_restore $VERIFIED_BACKUP"
    log "  or, once the cause is fixed:  $PY $BASE_DIR/manage.py upgrade_apply --resume"
    journal status=failed "error=database migration failed" "backup=$VERIFIED_BACKUP"
    exit 3
fi
journal stage=migrated
log "Step 3/5: Migrations completed"

# =====================================================================
# Step 4: Collect static files
# =====================================================================
log ""
log "Step 4/5: Collecting static files..."
if ! "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" collectstatic --noinput; then
    log "ERROR: collectstatic failed. The database is already migrated; fix the error and run"
    log "ERROR:   $PY $BASE_DIR/manage.py upgrade_apply --resume"
    journal status=failed "error=collectstatic failed"
    exit 1
fi
journal stage=static_collected
log "Step 4/5: Static files collected"

# v3.17.597: keep the root helper and the root-owned config it manages current.
# self-update installs the helper from this release's tag only if the tag is
# signed by a trusted release key; apply-system-config rewrites the units and
# sudoers rules the helper owns. Neither ever reads files from $BASE_DIR.
log ""
if [ "$SANDBOX" = "1" ]; then
    log "[sandbox] skipping root helper, crontab, sudoers and host configuration"
elif [ -x "$ROOT_HELPER" ]; then
    for helper_step in "self-update v$NEW_VERSION" "apply-system-config"; do
        # shellcheck disable=SC2086
        if HELPER_OUT=$(sudo -n "$ROOT_HELPER" $helper_step 2>&1); then
            while IFS= read -r line; do log "root helper: $line"; done <<< "$HELPER_OUT"
        else
            log "[WARN] root helper $helper_step failed (non-critical):"
            while IFS= read -r line; do log "[WARN]   $line"; done <<< "$HELPER_OUT"
        fi
    done
else
    log "[WARN] One-time setup needed: the root helper is not installed, so this"
    log "[WARN] install still relies on older passwordless sudo rules. Install it from"
    log "[WARN] Settings → Updates, or run: sudo bash $BASE_DIR/deploy/root-helper/install-root-helper.sh"
fi

# =====================================================================
# Optional extras (non-critical — failures are logged but do not abort)
# =====================================================================
log ""
log "Running optional update steps..."

# v3.17.598: local country database for the GeoIP firewall (monthly refresh).
if [ "$SANDBOX" = "1" ]; then
    log "[sandbox] skipping the GeoIP database download"
elif "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" update_geoip_db --max-age-days 25 2>&1 | tail -1 | sed "s/^/[$(date '+%Y-%m-%d %H:%M:%S')] /"; then
    :
fi

# Gunicorn environment fix
FIX_SCRIPT="$BASE_DIR/scripts/fix_gunicorn_env.sh"
if [ "$SANDBOX" != "1" ] && [ -f "$FIX_SCRIPT" ]; then
    log "Applying gunicorn environment fix..."
    ( chmod +x "$FIX_SCRIPT" && "$FIX_SCRIPT" ) \
        || log "[WARN] Gunicorn env fix failed (non-critical)"
fi

# Mobile build setup
MOBILE_SETUP="$BASE_DIR/deploy/setup_mobile_build.sh"
if [ "$SANDBOX" != "1" ] && [ -f "$MOBILE_SETUP" ]; then
    log "Running mobile build setup..."
    ( chmod +x "$MOBILE_SETUP" && "$MOBILE_SETUP" ) \
        || log "[WARN] Mobile build setup failed (non-critical)"
fi

# Diagram previews
( "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" generate_diagram_previews --force 2>&1 \
    && log "Diagram previews generated" ) \
    || log "[WARN] Diagram preview generation failed (non-critical)"

# Workflow diagrams
( "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" generate_workflow_diagrams 2>&1 \
    && log "Workflow diagrams generated" ) \
    || log "[WARN] Workflow diagram generation failed (non-critical)"

# PSA reference data — queues, statuses, priorities, types, service catalog.
# Idempotent: skips rows that already exist.
( "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" psa_seed_defaults 2>&1 \
    && log "PSA defaults seeded (queues, statuses, priorities, types, catalog)" ) \
    || log "[WARN] PSA seed_defaults failed (non-critical)"

# PSA sample workflows — installs starter rules (P1 escalation, sales-inquiry
# follow-up, new-user onboarding, termination security routing, outage keyword
# detection, unassigned triage, client-reply tagging) into every active org.
# Idempotent: matches by (organization, rule name); existing rows skipped.
( "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" psa_seed_sample_workflows 2>&1 \
    && log "PSA sample workflows installed" ) \
    || log "[WARN] PSA sample workflows install failed (non-critical)"

# Default reporting dashboard — "MSP Overview" with revenue / ticket / tech
# KPI widgets. Idempotent (skips if dashboard already has widgets).
( "$VENV_DIR/bin/python" "$BASE_DIR/manage.py" seed_default_dashboard 2>&1 \
    && log "Default dashboard seeded" ) \
    || log "[WARN] Default dashboard seed failed (non-critical)"

# fail2ban sudoers (install if fail2ban present and sudoers not yet configured)
if [ "$SANDBOX" != "1" ] && command -v fail2ban-client >/dev/null 2>&1; then
    FB_SRC="$BASE_DIR/deploy/clientst0r-fail2ban-sudoers"
    FB_DEST="/etc/sudoers.d/clientst0r-fail2ban"
    if [ -f "$FB_SRC" ] && [ ! -f "$FB_DEST" ]; then
        log "Installing fail2ban sudoers configuration..."
        ( sudo /usr/bin/cp "$FB_SRC" "$FB_DEST" && sudo /usr/bin/chmod 0440 "$FB_DEST" \
            && log "fail2ban sudoers installed" ) \
            || log "[WARN] fail2ban sudoers install failed (non-critical)"
    else
        log "fail2ban sudoers already configured"
    fi
fi

if [ "$SANDBOX" = "1" ]; then
    log "[sandbox] crontab left alone"
elif [ "$NO_NEW_PRIVS" -eq 1 ]; then
    log "[WARN] Skipping cron job setup: this process has no_new_privs set, so"
    log "[WARN] crontab cannot run. Existing cron jobs are untouched — including any"
    log "[WARN] legacy manage.py psa_* lines, which now duplicate the in-app scheduler"
    log "[WARN] and should be removed with crontab -e. To fix, reinstall"
    log "[WARN] the auto-update unit: sudo cp $BASE_DIR/deploy/clientst0r-auto-update.service"
    log "[WARN]   /etc/systemd/system/ && sudo systemctl daemon-reload"
else
# Cron job for web GUI updates (one-time setup)
CRON_JOB="* * * * * $BASE_DIR/scripts/check_update_trigger.sh"
if ! crontab -l 2>/dev/null | grep -q "check_update_trigger.sh"; then
    ( (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab - \
        && log "Cron job configured for web GUI updates" ) \
        || log "[WARN] Cron job setup failed (non-critical)"
fi

# v3.17.599: periodic jobs belong to the in-app scheduler (run_scheduler,
# clientst0r-scheduler.timer; Settings > Scheduler), not to cron. Earlier
# releases of this script appended crontab lines for them; remove those, or
# every job would run twice — once from cron, once from the scheduler.
# Idempotent: when none are present the crontab is not rewritten at all, and
# any other line (yours, or check_update_trigger.sh above) is kept as is.
# BEGIN legacy-cron-cleanup
LEGACY_CRON_RE='manage\.py[[:space:]]+(psa_run_recurring_tickets|psa_poll_email|psa_send_outbound|psa_auto_renew_contracts|psa_auto_replenish_suggestions|sync_distributors|run_scheduled_reports|poll_security_alerts)([[:space:]]|$)'
if CURRENT_CRON=$(crontab -l 2>/dev/null); then
    LEGACY_COUNT=$(printf '%s\n' "$CURRENT_CRON" | grep -cE "$LEGACY_CRON_RE" || true)
    if [ "${LEGACY_COUNT:-0}" -gt 0 ]; then
        if printf '%s\n' "$CURRENT_CRON" | { grep -vE "$LEGACY_CRON_RE" || true; } | crontab -; then
            log "Removed $LEGACY_COUNT legacy cron line(s); those jobs now run from the in-app scheduler"
        else
            log "[WARN] Could not remove legacy cron lines — they will run alongside the scheduler."
            log "[WARN] Remove the manage.py psa_* / sync_distributors / run_scheduled_reports /"
            log "[WARN] poll_security_alerts lines by hand: crontab -e"
        fi
    fi
fi
# END legacy-cron-cleanup
fi  # NO_NEW_PRIVS

# =====================================================================
# Step 5: Clear Python bytecode cache + graceful reload
# =====================================================================
log ""
log "Step 5/5: Scheduling service restart..."

# Refresh bytecode for the project's own packages, then pre-compile it.
#
# v3.17.513: this used to `find "$BASE_DIR"` unscoped, which cost twice over.
# BASE_DIR is a home directory, not just the app — on a working host it can
# also hold an android-sdk, an Expo checkout, a snap dir and assorted archives,
# so the walk covered gigabytes to delete a few hundred files. Worse, it wiped
# the venv's bytecode as well, which pip manages perfectly well itself: every
# worker the reload forked then had to recompile the whole of Django before it
# could serve a request, while the old workers were already being retired.
# That window is what cost 2 requests out of 423 in the v3.17.512 measurement.
#
# Now: discover the project's own Python packages (top-level dirs holding an
# __init__.py — ~0.02s, no deep walk), purge only those, then compile them
# ahead of the reload so new workers boot warm. Roughly 2s in total, and it
# happens while the old workers are still serving, so it costs update duration
# rather than downtime.
# Match on the top-level directory NAME (grep -vx = whole line), not on the
# absolute path: a install rooted at, say, /srv/mobile/app must not exclude
# itself just because "mobile" appears somewhere in its path.
PKG_DIRS=$(find "$BASE_DIR" -maxdepth 2 -mindepth 2 -name '__init__.py' -printf '%h\n' 2>/dev/null \
    | sed "s|^$BASE_DIR/||" \
    | grep -vxE "(venv|\.venv|env|node_modules|mobile|mobile-app|android-sdk|snap|local_apps|\.dev-worktree)" \
    | sed "s|^|$BASE_DIR/|" \
    | sort -u || true)

if [ -n "$PKG_DIRS" ]; then
    while IFS= read -r pkg; do
        [ -n "$pkg" ] || continue
        find "$pkg" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    done <<< "$PKG_DIRS"
    log "Bytecode cache cleared for $(echo "$PKG_DIRS" | wc -l) project package(s)"

    # Anything left behind is a __pycache__ this user cannot delete — almost
    # always root-owned, from a manage.py run under sudo. The purge above hides
    # that (2>/dev/null), and it stayed invisible for a long time; say it out
    # loud instead, because those directories also block the pre-compile below.
    STUCK=$(echo "$PKG_DIRS" | while IFS= read -r pkg; do
        [ -n "$pkg" ] && find "$pkg" -type d -name "__pycache__" 2>/dev/null
    done | wc -l)
    if [ "$STUCK" -gt 0 ]; then
        log "[WARN] $STUCK __pycache__ dir(s) could not be removed (likely root-owned)."
        log "[WARN] Fix with: sudo chown -R \$(whoami) \$(find $BASE_DIR -maxdepth 3 -type d -name __pycache__ | tr '\\n' ' ')"
    fi

    # Unquoted on purpose: compileall takes the package dirs as separate args.
    ( "$VENV_DIR/bin/python" -m compileall -q -j 0 $PKG_DIRS >/dev/null 2>&1 \
        && log "Bytecode pre-compiled — reloaded workers boot warm" ) \
        || log "[WARN] Bytecode pre-compile failed (non-critical — workers compile on demand)"
else
    log "[WARN] No project packages discovered — skipping bytecode refresh"
fi

# v3.17.421 — write the "completed" status to the progress JSON file
# DIRECTLY from bash, BEFORE the reload signal is sent. The Python
# worker that's reading our stdout will be SIGHUP'd by `systemctl
# reload` and won't survive long enough to process the "Update
# complete!" line, so the status_completed step would otherwise stay
# stuck at 4/5 forever in the UI. By writing the JSON ourselves we
# decouple the front-end from the Python reader's lifetime.
PROGRESS_FILE="/tmp/clientst0r_update_progress_current.json"
if [ "$SANDBOX" = "1" ]; then
    # A rehearsal must not write the progress file a real install's UI reads.
    PROGRESS_FILE="$BASE_DIR/.update_progress_sandbox.json"
fi
PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -n "$PYTHON_BIN" ] && [ -f "$PROGRESS_FILE" ]; then
    "$PYTHON_BIN" - <<EOF || true
import json, time, os
p = "$PROGRESS_FILE"
try:
    with open(p) as f:
        d = json.load(f)
except Exception:
    d = {}
steps = d.get('steps_completed') or []
for s in ('Git Pull','Install Dependencies','Run Migrations','Collect Static Files','Restart Service'):
    if s not in steps:
        steps.append(s)
d['status'] = 'completed'
d['steps_completed'] = steps
d['current_step'] = ''
d['total_steps'] = max(int(d.get('total_steps') or 5), len(steps))
d['finished_at'] = time.time()
tmp = p + '.tmp'
with open(tmp, 'w') as f:
    json.dump(d, f)
os.replace(tmp, p)
EOF
    log "Step 5/5: Marked progress=completed before reload"
fi

SYSTEMCTL=$(command -v systemctl 2>/dev/null || true)
SYSTEMD_RUN=$(command -v systemd-run 2>/dev/null || true)

# v3.17.515: warn when the installed unit has drifted from the one in the repo.
# `git pull` updates deploy/clientst0r-gunicorn.service but nothing re-installs
# it, so a change to ExecStart ships and then never reaches the running service.
# That is not hypothetical: v3.17.500 raised --timeout 180 -> 300 to stop AI
# generation being SIGKILLed mid-request (issue #138), and this host was still
# running 180 fourteen releases later, with nothing anywhere reporting it.
# Warn only — never overwrite, since an operator may have tuned the unit on
# purpose (worker count, bind address, resource limits).
UNIT_SRC="$BASE_DIR/deploy/${SERVICE:-clientst0r-gunicorn.service}"
UNIT_DEST="/etc/systemd/system/${SERVICE:-clientst0r-gunicorn.service}"
if [ -n "$SERVICE" ] && [ -f "$UNIT_SRC" ] && [ -f "$UNIT_DEST" ]; then
    if ! diff -q <(grep -vE '^\s*(#|$)' "$UNIT_SRC") <(grep -vE '^\s*(#|$)' "$UNIT_DEST") >/dev/null 2>&1; then
        log "[WARN] Installed unit differs from $UNIT_SRC — the running service"
        log "[WARN] is NOT what this release ships. Review with:"
        log "[WARN]   diff $UNIT_SRC $UNIT_DEST"
        log "[WARN] To adopt it: sudo cp $UNIT_SRC $UNIT_DEST && sudo systemctl daemon-reload"
        log "[WARN] (ExecStart changes need a restart, not a reload, to take effect.)"
    fi
fi

journal stage=reloading

# v3.17.595: if nothing below manages a reload or restart, the run must fail.
# Before this, the last fallback backgrounded `sudo systemctl restart` and
# logged it as scheduled; under NoNewPrivileges that sudo always failed
# unseen, so every nightly run since at least 2026-10-03 left gunicorn on the
# old code while reporting "Update completed successfully!".
RELOADED=0
if [ "${SANDBOX:-0}" = "1" ]; then
    log "Step 5/5: [sandbox] not reloading any service"
    RELOADED=1
elif [ -n "$SERVICE" ] && [ -n "$SYSTEMCTL" ]; then
    # Graceful reload: sends SIGHUP to the gunicorn master (ExecReload=kill -HUP $MAINPID).
    # Workers are replaced one-by-one while the master stays alive — zero downtime.
    if [ -x "$ROOT_HELPER" ] && sudo -n "$ROOT_HELPER" reload >/dev/null 2>&1; then
        log "Step 5/5: Graceful reload of '$SERVICE' via root helper completed (zero downtime)"
        RELOADED=1
    elif sudo -n "$SYSTEMCTL" reload "$SERVICE" 2>/dev/null; then
        log "Step 5/5: Graceful reload of '$SERVICE' completed (zero downtime)"
        RELOADED=1
    else
        # sudo unavailable (no_new_privs, no sudoers rule). The unit's
        # ExecReload is only `kill -HUP $MAINPID`, and the master normally runs
        # as this same user, so send that signal ourselves. MainPID is
        # readable without privilege.
        MAIN_PID=$("$SYSTEMCTL" show -p MainPID --value "$SERVICE" 2>/dev/null || echo 0)
        if [ "${MAIN_PID:-0}" -gt 0 ] 2>/dev/null \
                && [ "$(ps -o uid= -p "$MAIN_PID" 2>/dev/null | tr -d ' ')" = "$(id -u)" ] \
                && kill -HUP "$MAIN_PID" 2>/dev/null; then
            log "Step 5/5: Graceful reload of '$SERVICE' via SIGHUP to master PID $MAIN_PID (zero downtime)"
            RELOADED=1
        elif sudo -n true 2>/dev/null; then
            # Service not running or reload unsupported — fall back to a clean restart.
            log "[WARN] reload failed — falling back to restart (brief downtime expected)"
            if [ -n "$SYSTEMD_RUN" ] \
                    && sudo -n "$SYSTEMD_RUN" --on-active=3 --system "$SYSTEMCTL" restart "$SERVICE" 2>/dev/null; then
                log "Step 5/5: Restart of '$SERVICE' scheduled via systemd-run (3-second delay)"
                RELOADED=1
            else
                nohup sudo -n "$SYSTEMCTL" restart "$SERVICE" >/dev/null 2>&1 &
                disown 2>/dev/null || true
                log "Step 5/5: Restart of '$SERVICE' scheduled via nohup"
                RELOADED=1
            fi
        fi
    fi
    if [ "$RELOADED" -eq 0 ]; then
        log "ERROR: could not reload or restart '$SERVICE'. The new code is on disk"
        log "ERROR: but the running server is still serving the old version."
        if [ "$NO_NEW_PRIVS" -eq 1 ]; then
            log "ERROR: this process has no_new_privs set, so sudo cannot run. Reinstall"
            log "ERROR: the auto-update unit without NoNewPrivileges:"
            log "ERROR:   sudo cp $BASE_DIR/deploy/clientst0r-auto-update.service /etc/systemd/system/"
            log "ERROR:   sudo systemctl daemon-reload"
        fi
        log "ERROR: Reload by hand: sudo systemctl reload $SERVICE"
        if [ -n "$PYTHON_BIN" ] && [ -f "$PROGRESS_FILE" ]; then
            "$PYTHON_BIN" - <<EOF || true
import json, os
p = "$PROGRESS_FILE"
try:
    with open(p) as f:
        d = json.load(f)
except Exception:
    d = {}
d['status'] = 'failed'
d['error'] = 'Update installed but the service could not be reloaded; reload it by hand.'
tmp = p + '.tmp'
with open(tmp, 'w') as f:
    json.dump(d, f)
os.replace(tmp, p)
EOF
        fi
        exit 1
    fi
else
    # No systemd service — send SIGHUP to the gunicorn master serving THIS
    # directory. A bare `pkill -f gunicorn` would also reload every other
    # install (or unrelated gunicorn app) this user runs on the host.
    SIGNALLED=0
    for pid in $(pgrep -u "$(id -u)" -f 'gunicorn.*wsgi:application' 2>/dev/null || true); do
        [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$(readlink -f "$BASE_DIR")" ] || continue
        ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
        # Masters only: a worker's parent is a gunicorn process in the same dir.
        if [ -n "$ppid" ] && grep -q gunicorn "/proc/$ppid/cmdline" 2>/dev/null; then
            continue
        fi
        kill -HUP "$pid" 2>/dev/null && SIGNALLED=1
    done
    if [ "$SIGNALLED" -eq 1 ]; then
        log "Step 5/5: Graceful reload signal sent to gunicorn master"
    else
        log "[WARN] No gunicorn master found for $BASE_DIR — restart it by hand to load the new code"
    fi
fi

log ""
log "=================================================="
log "Update complete! Please wait 10 seconds then refresh."
log "=================================================="
journal stage=complete

exit 0
