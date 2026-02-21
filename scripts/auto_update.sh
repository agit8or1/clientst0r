#!/bin/bash
# client st0r Auto-Update Script
# Automatically pulls latest code, runs migrations, and restarts services

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get project directory (where this script is)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Auto-detect venv location (try multiple common paths)
if [ -d "$PROJECT_DIR/venv" ]; then
    VENV_DIR="$PROJECT_DIR/venv"
elif [ -d "$PROJECT_DIR/clientst0r/venv" ]; then
    VENV_DIR="$PROJECT_DIR/clientst0r/venv"
elif [ -d "$(dirname "$PROJECT_DIR")/venv" ]; then
    VENV_DIR="$(dirname "$PROJECT_DIR")/venv"
else
    # Try to find it
    VENV_DIR=$(find "$PROJECT_DIR" -maxdepth 2 -type d -name "venv" 2>/dev/null | head -1)
fi

LOG_FILE="/var/log/clientst0r/auto-update.log"

# Ensure log directory exists
sudo mkdir -p /var/log/clientst0r
sudo chown -R $(whoami):$(whoami) /var/log/clientst0r

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}✗${NC} $1" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${BLUE}ℹ${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1" | tee -a "$LOG_FILE"
}

# Check if running as correct user
if [ "$EUID" -eq 0 ]; then
    log_error "Do not run this script as root. Run as the user who owns the client st0r installation."
    exit 1
fi

log_info "=========================================="
log_info "client st0r Auto-Update Script"
log_info "=========================================="
log_info "Project directory: $PROJECT_DIR"

cd "$PROJECT_DIR"

# Step 1: Check current version
log_info "Step 1/8: Checking current version..."
CURRENT_VERSION=$(grep "VERSION = " config/version.py | cut -d"'" -f2)
log_info "Current version: $CURRENT_VERSION"

# Step 2: Fetch latest from GitHub
log_info "Step 2/8: Fetching latest code from GitHub..."
git fetch origin main
if [ $? -eq 0 ]; then
    log_success "Fetched latest code"
else
    log_error "Failed to fetch from GitHub"
    exit 1
fi

# Step 3: Check if updates available
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" = "$REMOTE" ]; then
    log_success "Already up to date!"
    log_info "Will still restart services to ensure fresh Python imports..."
    # Don't exit - continue to restart services to clear any cached imports
fi

log_info "Updates available!"
log_info "Local:  $LOCAL"
log_info "Remote: $REMOTE"

# Step 4: Stash any local changes
log_info "Step 3/8: Checking for local changes..."
if ! git diff-index --quiet HEAD --; then
    log_warning "Local changes detected, stashing..."
    git stash push -m "Auto-stash before update $(date '+%Y-%m-%d %H:%M:%S')"
    log_success "Local changes stashed"
fi

# Step 5: Pull latest code
log_info "Step 4/8: Pulling latest code..."
git pull origin main
if [ $? -eq 0 ]; then
    log_success "Code updated successfully"
else
    log_error "Failed to pull latest code"
    exit 1
fi

# Step 6: Check new version
NEW_VERSION=$(grep "VERSION = " config/version.py | cut -d"'" -f2)
log_info "New version: $NEW_VERSION"

# Step 7: Activate virtual environment and run migrations
log_info "Step 5/8: Activating virtual environment..."
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    log_error "Virtual environment not found at $VENV_DIR"
    exit 1
fi

source "$VENV_DIR/bin/activate"
log_success "Virtual environment activated"

# Step 8: Install/update dependencies
log_info "Step 6/8: Checking for dependency updates..."
pip install -q -r requirements.txt
if [ $? -eq 0 ]; then
    log_success "Dependencies up to date"
else
    log_warning "Some dependency updates failed (non-critical)"
fi

# Step 9: Run migrations
log_info "Step 7/8: Running database migrations..."
python manage.py migrate --noinput
if [ $? -eq 0 ]; then
    log_success "Migrations completed successfully"
else
    log_error "Migration failed!"
    exit 1
fi

# Step 10: Collect static files (if needed)
log_info "Collecting static files..."
python manage.py collectstatic --noinput --clear > /dev/null 2>&1
if [ $? -eq 0 ]; then
    log_success "Static files collected"
else
    log_warning "Static file collection failed (non-critical)"
fi

# Step 11: Restart services with enhanced cleanup
log_info "Step 8/8: Restarting services with full cleanup..."

# Detect which gunicorn service exists
GUNICORN_SERVICE=""
for service in clientst0r-gunicorn.service clientst0r-gunicorn.service itdocs-gunicorn.service; do
    if systemctl list-unit-files | grep -q "^$service"; then
        GUNICORN_SERVICE="$service"
        break
    fi
done

if [ -z "$GUNICORN_SERVICE" ]; then
    log_error "No gunicorn service found!"
    exit 1
fi

log_info "Using service: $GUNICORN_SERVICE"

# ENHANCED RESTART: Stop, kill processes, clear cache, start fresh
log_info "Stopping service..."
echo "[DEBUG] About to stop service at $(date)" >> "$LOG_FILE"
timeout 30 sudo systemctl stop "$GUNICORN_SERVICE" 2>/dev/null || true
echo "[DEBUG] Service stopped at $(date)" >> "$LOG_FILE"

log_info "Killing any lingering gunicorn processes..."
echo "[DEBUG] About to kill processes at $(date)" >> "$LOG_FILE"
# Only kill python gunicorn workers, not this bash script
sudo pkill -9 -f "python.*gunicorn" 2>/dev/null || true
echo "[DEBUG] Processes killed at $(date)" >> "$LOG_FILE"
sleep 2

log_info "Starting service fresh..."
echo "[DEBUG] About to start service at $(date)" >> "$LOG_FILE"
sudo systemctl start "$GUNICORN_SERVICE"
echo "[DEBUG] Start command issued at $(date)" >> "$LOG_FILE"
sleep 5
echo "[DEBUG] Finished waiting after start at $(date)" >> "$LOG_FILE"

# Clear bytecode cache in background (non-blocking)
log_info "Clearing Python bytecode cache (background)..."
(find "$PROJECT_DIR" -type d -name __pycache__ -not -path "*/venv/*" -exec rm -rf {} + 2>/dev/null || true) &
(find "$PROJECT_DIR" -name "*.pyc" -not -path "*/venv/*" -delete 2>/dev/null || true) &

if sudo systemctl is-active --quiet "$GUNICORN_SERVICE"; then
    log_success "Gunicorn restarted successfully with clean cache"
else
    log_error "Gunicorn failed to restart!"
    sudo systemctl status "$GUNICORN_SERVICE"
    exit 1
fi

# Restart Scheduler (if exists)
if sudo systemctl is-active --quiet clientst0r-scheduler.service; then
    sudo systemctl restart clientst0r-scheduler.service
    log_success "Scheduler restarted"
fi

# Restart PSA Sync (if exists)
if sudo systemctl is-active --quiet clientst0r-psa-sync.service; then
    sudo systemctl restart clientst0r-psa-sync.service
    log_success "PSA Sync restarted"
fi

# Restart RMM Sync (if exists)
if sudo systemctl is-active --quiet clientst0r-rmm-sync.service; then
    sudo systemctl restart clientst0r-rmm-sync.service
    log_success "RMM Sync restarted"
fi

# Restart Monitor (if exists)
if sudo systemctl is-active --quiet clientst0r-monitor.service; then
    sudo systemctl restart clientst0r-monitor.service
    log_success "Monitor restarted"
fi

# Clear Django cache to ensure fresh version display
log_info "Clearing Django cache..."
"$VENV_DIR/bin/python" "$PROJECT_DIR/manage.py" shell -c "from django.core.cache import cache; cache.delete('system_update_check'); print('Cache cleared')" > /dev/null 2>&1 || true
log_success "Cache cleared"

# Auto-setup cron job for web GUI updates (one-time setup)
log_info "Checking cron job for web GUI updates..."
CRON_JOB="* * * * * $PROJECT_DIR/scripts/check_update_trigger.sh"
if ! crontab -l 2>/dev/null | grep -q "check_update_trigger.sh"; then
    log_info "Adding cron job for web GUI updates..."
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    log_success "Cron job added - web GUI updates now enabled!"
else
    log_info "Cron job already exists"
fi

log_info "=========================================="
log_success "Update completed successfully!"
log_info "Version: $CURRENT_VERSION → $NEW_VERSION"
log_info "=========================================="

# Send notification (optional - if configured)
if command -v notify-send &> /dev/null; then
    notify-send "client st0r Updated" "Updated from $CURRENT_VERSION to $NEW_VERSION"
fi

exit 0
