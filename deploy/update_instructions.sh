#!/bin/bash
# Client St0r Update Instructions
# Downloaded and executed by perform_update() — do not rename or move
#
# Environment variables (passed by caller):
#   CLIENTST0R_BASE_DIR      - absolute path to the project root
#   CLIENTST0R_SERVICE_NAME  - systemd service name (or empty if none)

set -euo pipefail

# Ensure standard system utilities are available regardless of the calling
# process's PATH (gunicorn restricts PATH to venv/bin via EnvironmentFile)
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

BASE_DIR="${CLIENTST0R_BASE_DIR:-$(dirname "$(realpath "$0")")/..}"
SERVICE="${CLIENTST0R_SERVICE_NAME:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

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
log "Step 1/5: Fetching latest code from GitHub..."
$GIT -C "$BASE_DIR" fetch origin main
$GIT -C "$BASE_DIR" reset --hard origin/main

NEW_VERSION=$(grep "VERSION = " "$BASE_DIR/config/version.py" 2>/dev/null | cut -d"'" -f2 || echo "unknown")
log "Step 1/5: Code updated. New version: $NEW_VERSION"

# =====================================================================
# Step 2: Install Python dependencies
# =====================================================================
log ""
log "Step 2/5: Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$BASE_DIR/requirements.txt"
log "Step 2/5: Core dependencies installed"

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
log "Step 3/5: Running database migrations..."
"$VENV_DIR/bin/python" "$BASE_DIR/manage.py" migrate --noinput
log "Step 3/5: Migrations completed"

# =====================================================================
# Step 4: Collect static files
# =====================================================================
log ""
log "Step 4/5: Collecting static files..."
"$VENV_DIR/bin/python" "$BASE_DIR/manage.py" collectstatic --noinput
log "Step 4/5: Static files collected"

# =====================================================================
# Optional extras (non-critical — failures are logged but do not abort)
# =====================================================================
log ""
log "Running optional update steps..."

# Gunicorn environment fix
FIX_SCRIPT="$BASE_DIR/scripts/fix_gunicorn_env.sh"
if [ -f "$FIX_SCRIPT" ]; then
    log "Applying gunicorn environment fix..."
    ( chmod +x "$FIX_SCRIPT" && "$FIX_SCRIPT" ) \
        || log "[WARN] Gunicorn env fix failed (non-critical)"
fi

# Mobile build setup
MOBILE_SETUP="$BASE_DIR/deploy/setup_mobile_build.sh"
if [ -f "$MOBILE_SETUP" ]; then
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
if command -v fail2ban-client >/dev/null 2>&1; then
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

# Cron job for web GUI updates (one-time setup)
CRON_JOB="* * * * * $BASE_DIR/scripts/check_update_trigger.sh"
if ! crontab -l 2>/dev/null | grep -q "check_update_trigger.sh"; then
    ( (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab - \
        && log "Cron job configured for web GUI updates" ) \
        || log "[WARN] Cron job setup failed (non-critical)"
fi

# PSA recurring tickets — every 15 minutes
PSA_RECURRING="*/15 * * * * $VENV_DIR/bin/python $BASE_DIR/manage.py psa_run_recurring_tickets >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "psa_run_recurring_tickets"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_RECURRING") | crontab - \
        && log "Cron job configured for PSA recurring tickets" ) \
        || log "[WARN] PSA recurring-tickets cron setup failed (non-critical)"
fi

# PSA email-to-ticket — every 5 minutes
PSA_EMAIL="*/5 * * * * $VENV_DIR/bin/python $BASE_DIR/manage.py psa_poll_email >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "psa_poll_email"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_EMAIL") | crontab - \
        && log "Cron job configured for PSA email-to-ticket polling" ) \
        || log "[WARN] PSA email-poll cron setup failed (non-critical)"
fi

# PSA Graph outbound retry worker — every 5 minutes (issue #142). Retries any
# outbound Graph sends left queued by a transient failure; inline sends already
# happen at request time, so this is a safety net (jobs are lock-claimed, so no
# double-send).
PSA_OUTBOUND="*/5 * * * * $VENV_DIR/bin/python $BASE_DIR/manage.py psa_send_outbound >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "psa_send_outbound"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_OUTBOUND") | crontab - \
        && log "Cron job configured for PSA Graph outbound worker" ) \
        || log "[WARN] PSA outbound cron setup failed (non-critical)"
fi

# Contract auto-renewal — daily at 02:30
PSA_RENEW="30 2 * * * $VENV_DIR/bin/python $BASE_DIR/manage.py psa_auto_renew_contracts >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "psa_auto_renew_contracts"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_RENEW") | crontab - \
        && log "Cron job configured for PSA contract auto-renewal" ) \
        || log "[WARN] PSA contract auto-renewal cron setup failed (non-critical)"
fi

# Distributors health probe — hourly
PSA_DIST="0 * * * * $VENV_DIR/bin/python $BASE_DIR/manage.py sync_distributors >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "sync_distributors"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_DIST") | crontab - \
        && log "Cron job configured for distributor health probe" ) \
        || log "[WARN] Distributor cron setup failed (non-critical)"
fi

# Scheduled reports — every 15 minutes (v3.17.147 — Phase 3.6 wave B)
PSA_REPORTS="*/15 * * * * $VENV_DIR/bin/python $BASE_DIR/manage.py run_scheduled_reports >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "run_scheduled_reports"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_REPORTS") | crontab - \
        && log "Cron job configured for scheduled reports runner" ) \
        || log "[WARN] Scheduled reports cron setup failed (non-critical)"
fi

# Auto-replenish scan — daily at 06:00, log only (no auto-PR creation)
# (v3.17.150 — Phase 4.3) PR creation via --create-prs is admin-triggered.
PSA_REPLENISH="0 6 * * * $VENV_DIR/bin/python $BASE_DIR/manage.py psa_auto_replenish_suggestions >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "psa_auto_replenish_suggestions"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_REPLENISH") | crontab - \
        && log "Cron job configured for stock-minimum scan" ) \
        || log "[WARN] Stock-minimum scan cron setup failed (non-critical)"
fi

# Security alert polling — every 5 minutes (v3.17.168 — Phase 9.2)
PSA_SEC="*/5 * * * * $VENV_DIR/bin/python $BASE_DIR/manage.py poll_security_alerts >/dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "poll_security_alerts"; then
    ( (crontab -l 2>/dev/null; echo "$PSA_SEC") | crontab - \
        && log "Cron job configured for security alert polling" ) \
        || log "[WARN] Security alert polling cron setup failed (non-critical)"
fi

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
d['total_steps'] = 5
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

if [ -n "$SERVICE" ] && [ -n "$SYSTEMCTL" ]; then
    # Graceful reload: sends SIGHUP to the gunicorn master (ExecReload=kill -HUP $MAINPID).
    # Workers are replaced one-by-one while the master stays alive — zero downtime.
    if sudo "$SYSTEMCTL" reload "$SERVICE" 2>/dev/null; then
        log "Step 5/5: Graceful reload of '$SERVICE' completed (zero downtime)"
    else
        # Service not running or reload unsupported — fall back to a clean restart.
        log "[WARN] reload failed — falling back to restart (brief downtime expected)"
        RESTART_SCHEDULED=0
        if [ -n "$SYSTEMD_RUN" ]; then
            if sudo "$SYSTEMD_RUN" --on-active=3 --system "$SYSTEMCTL" restart "$SERVICE" 2>/dev/null; then
                log "Step 5/5: Restart of '$SERVICE' scheduled via systemd-run (3-second delay)"
                RESTART_SCHEDULED=1
            fi
        fi
        if [ "$RESTART_SCHEDULED" -eq 0 ]; then
            nohup sudo "$SYSTEMCTL" restart "$SERVICE" >/dev/null 2>&1 &
            disown 2>/dev/null || true
            log "Step 5/5: Restart of '$SERVICE' scheduled via nohup"
        fi
    fi
else
    # No systemd service — send SIGHUP to gunicorn master for graceful reload.
    if pkill -HUP -f 'gunicorn.*wsgi:application' 2>/dev/null; then
        log "Step 5/5: Graceful reload signal sent to gunicorn master"
    else
        log "[WARN] Could not send SIGHUP to gunicorn — workers may be stale"
    fi
fi

log ""
log "=================================================="
log "Update complete! Please wait 10 seconds then refresh."
log "=================================================="

exit 0
