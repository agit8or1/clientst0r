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
VENV_DIR="$PROJECT_DIR/venv"
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

# Safety check: Don't run from web context (prevents suicide)
if [ -n "$REMOTE_ADDR" ] || [ -n "$HTTP_HOST" ]; then
    log_error "This script cannot be run from web context (would cause service suicide)"
    log_error "Use: python manage.py auto_update (from command line only)"
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
for service in huduglue-gunicorn.service clientst0r-gunicorn.service itdocs-gunicorn.service; do
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
sudo systemctl stop "$GUNICORN_SERVICE" 2>/dev/null || true

log_info "Killing any lingering gunicorn processes..."
sudo pkill -9 -f gunicorn 2>/dev/null || true
sleep 2

log_info "Clearing Python bytecode cache..."
find "$PROJECT_DIR" -type d -name __pycache__ -not -path "*/venv/*" -exec rm -rf {} + 2>/dev/null || true
find "$PROJECT_DIR" -name "*.pyc" -not -path "*/venv/*" -delete 2>/dev/null || true

log_info "Starting service fresh..."
sudo systemctl start "$GUNICORN_SERVICE"
sleep 5

if sudo systemctl is-active --quiet "$GUNICORN_SERVICE"; then
    log_success "Gunicorn restarted successfully with clean cache"
else
    log_error "Gunicorn failed to restart!"
    sudo systemctl status "$GUNICORN_SERVICE"
    exit 1
fi

# Restart Scheduler (if exists)
if sudo systemctl is-active --quiet huduglue-scheduler.service; then
    sudo systemctl restart huduglue-scheduler.service
    log_success "Scheduler restarted"
fi

# Restart PSA Sync (if exists)
if sudo systemctl is-active --quiet huduglue-psa-sync.service; then
    sudo systemctl restart huduglue-psa-sync.service
    log_success "PSA Sync restarted"
fi

# Restart RMM Sync (if exists)
if sudo systemctl is-active --quiet huduglue-rmm-sync.service; then
    sudo systemctl restart huduglue-rmm-sync.service
    log_success "RMM Sync restarted"
fi

# Restart Monitor (if exists)
if sudo systemctl is-active --quiet huduglue-monitor.service; then
    sudo systemctl restart huduglue-monitor.service
    log_success "Monitor restarted"
fi

# Clear Django cache to ensure fresh version display
log_info "Clearing Django cache..."
"$VENV_DIR/bin/python" "$PROJECT_DIR/manage.py" shell -c "from django.core.cache import cache; cache.delete('system_update_check'); print('Cache cleared')" > /dev/null 2>&1 || true
log_success "Cache cleared"

log_info "=========================================="
log_success "Update completed successfully!"
log_info "Version: $CURRENT_VERSION → $NEW_VERSION"
log_info "=========================================="

# Send notification (optional - if configured)
if command -v notify-send &> /dev/null; then
    notify-send "client st0r Updated" "Updated from $CURRENT_VERSION to $NEW_VERSION"
fi

exit 0
