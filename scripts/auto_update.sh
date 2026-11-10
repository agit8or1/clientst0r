#!/bin/bash
# Client St0r Auto-Update Script
# Thin wrapper: downloads and executes update_instructions.sh from GitHub

# Get project directory (where this script lives)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

LOG_FILE="/var/log/clientst0r/auto-update.log"

# Ensure log directory exists
sudo mkdir -p /var/log/clientst0r
sudo chown -R "$(whoami):$(whoami)" /var/log/clientst0r

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    log "ERROR: Do not run this script as root. Run as the user who owns the installation."
    exit 1
fi

log "=========================================="
log "Client St0r Auto-Update Script"
log "=========================================="
log "Project directory: $PROJECT_DIR"

# Since the install/upgrade hardening the nightly run goes through the same
# pipeline as Settings -> Updates -> Apply: it follows this instance's release
# channel (Stable by default: signed, published releases only), pins the
# revision by commit, runs the preflight checks and refuses to migrate without
# a verified backup. Only an older checkout without that command falls back to
# downloading the update script from main.
PY="$PROJECT_DIR/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
if "$PY" "$PROJECT_DIR/manage.py" help upgrade_apply >/dev/null 2>&1; then
    log "Running the verified upgrade pipeline (manage.py upgrade_apply --auto)"
    "$PY" "$PROJECT_DIR/manage.py" upgrade_apply --auto 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}
    if [ "$EXIT_CODE" -eq 0 ]; then
        log "Auto-update finished (nothing to do, or upgraded)."
    else
        log "Auto-update did NOT complete (exit $EXIT_CODE); see the log above and manage.py upgrade_status."
    fi
    exit "$EXIT_CODE"
fi

# Detect GitHub repo from git remote
REPO_URL=$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || echo "")
if echo "$REPO_URL" | grep -q "github.com"; then
    REPO_PATH=$(echo "$REPO_URL" \
        | sed 's|.*github\.com[:/]\(.*\)|\1|' \
        | sed 's|\.git$||')
else
    REPO_PATH="agit8or1/clientst0r"
fi

INSTRUCTIONS_URL="https://raw.githubusercontent.com/$REPO_PATH/main/deploy/update_instructions.sh"
log "Downloading update instructions from: $INSTRUCTIONS_URL"

# Download to a temp file
TEMP_SCRIPT=$(mktemp /tmp/clientst0r_update_XXXXXXXX.sh)

DOWNLOAD_OK=0
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$INSTRUCTIONS_URL" -o "$TEMP_SCRIPT" 2>/dev/null && DOWNLOAD_OK=1
fi
if [ "$DOWNLOAD_OK" -eq 0 ] && command -v wget >/dev/null 2>&1; then
    wget -q "$INSTRUCTIONS_URL" -O "$TEMP_SCRIPT" 2>/dev/null && DOWNLOAD_OK=1
fi

if [ "$DOWNLOAD_OK" -eq 0 ]; then
    log "ERROR: Failed to download update instructions (tried curl and wget)"
    rm -f "$TEMP_SCRIPT"
    exit 1
fi

# Validate it's a shell script
if ! head -1 "$TEMP_SCRIPT" | grep -q "^#!"; then
    log "ERROR: Downloaded content is not a valid shell script"
    rm -f "$TEMP_SCRIPT"
    exit 1
fi

chmod 700 "$TEMP_SCRIPT"
log "Update instructions downloaded and validated"

# Auto-detect gunicorn service name
GUNICORN_SERVICE=""
for svc in clientst0r-gunicorn.service; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^$svc"; then
        GUNICORN_SERVICE="$svc"
        break
    fi
done

# Execute the update instructions
export CLIENTST0R_BASE_DIR="$PROJECT_DIR"
export CLIENTST0R_SERVICE_NAME="$GUNICORN_SERVICE"

log "Executing update instructions..."
/bin/bash "$TEMP_SCRIPT"
EXIT_CODE=$?

# Cleanup
rm -f "$TEMP_SCRIPT"

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=========================================="
    log "Update completed successfully!"
    log "=========================================="
else
    log "=========================================="
    log "Update FAILED (exit code: $EXIT_CODE)"
    log "=========================================="
fi

exit "$EXIT_CODE"
