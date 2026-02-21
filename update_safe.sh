#!/bin/bash
#
# Self-Healing Update Script for HuduGlue
# Automatically detects and fixes common migration and update issues
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Header
echo "╔════════════════════════════════════════════════════════╗"
echo "║                                                        ║"
echo "║        HuduGlue Self-Healing Update System            ║"
echo "║                                                        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Check we're in the right directory
if [ ! -f "manage.py" ]; then
    log_error "manage.py not found. Are you in the HuduGlue directory?"
    exit 1
fi

if [ ! -d "venv" ]; then
    log_error "Virtual environment not found. Please run installer first."
    exit 1
fi

log_info "Starting self-healing update process..."
echo ""

# Activate virtual environment
log_info "Activating virtual environment..."
source venv/bin/activate

# Step 1: Get current git state
log_info "Checking current git state..."
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)
log_info "Current: $CURRENT_BRANCH @ $CURRENT_COMMIT"

# Step 2: Check for local changes
if ! git diff-index --quiet HEAD --; then
    log_warning "You have uncommitted changes"
    git status --short
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Update cancelled"
        exit 1
    fi
fi

# Step 3: Fetch latest from remote
log_info "Fetching latest updates from GitHub..."
git fetch origin main --tags

# Step 4: Check what migrations exist in remote vs local
log_info "Analyzing migration files..."

# Get list of migration files in remote
REMOTE_MIGRATIONS=$(git ls-tree -r --name-only origin/main | grep -E "migrations/[0-9]+.*\.py$" | grep -v "__pycache__" | sort || true)

# Get list of local migration files
LOCAL_MIGRATIONS=$(find . -path "*/migrations/[0-9]*.py" -not -path "*/venv/*" -not -path "*/__pycache__/*" | sed 's|^\./||' | sort || true)

# Find migrations that exist locally but not in remote (likely user-generated)
log_info "Detecting locally-generated migrations..."
ORPHAN_MIGRATIONS=""
while IFS= read -r local_file; do
    if ! echo "$REMOTE_MIGRATIONS" | grep -q "^$local_file$"; then
        ORPHAN_MIGRATIONS="$ORPHAN_MIGRATIONS$local_file\n"
    fi
done <<< "$LOCAL_MIGRATIONS"

# Step 5: Clean up orphan migrations
if [ -n "$ORPHAN_MIGRATIONS" ]; then
    log_warning "Found locally-generated migrations that don't exist in repository:"
    echo -e "$ORPHAN_MIGRATIONS"
    echo ""
    log_info "These migrations will be removed and fake-applied to prevent conflicts..."

    # Fake-apply each orphan migration before deleting
    while IFS= read -r orphan_file; do
        if [ -n "$orphan_file" ]; then
            # Extract app name and migration name
            APP_NAME=$(echo "$orphan_file" | cut -d'/' -f1)
            MIGRATION_NAME=$(basename "$orphan_file" .py)

            log_info "Fake-applying: $APP_NAME.$MIGRATION_NAME"
            python manage.py migrate --fake "$APP_NAME" "$MIGRATION_NAME" 2>/dev/null || log_warning "Could not fake-apply $MIGRATION_NAME (may not exist in DB)"

            log_info "Removing: $orphan_file"
            rm -f "$orphan_file"
        fi
    done <<< "$(echo -e "$ORPHAN_MIGRATIONS")"

    log_success "Orphan migrations cleaned up"
    echo ""
fi

# Step 6: Pull latest code
log_info "Pulling latest code from GitHub..."
git pull origin main

NEW_COMMIT=$(git rev-parse --short HEAD)
if [ "$CURRENT_COMMIT" != "$NEW_COMMIT" ]; then
    log_success "Updated from $CURRENT_COMMIT to $NEW_COMMIT"
else
    log_info "Already up to date"
fi
echo ""

# Step 7: Update dependencies
log_info "Updating Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
log_success "Dependencies updated"
echo ""

# Step 8: Run migrations with safety checks
log_info "Running database migrations..."

# First, check for migration conflicts
MIGRATION_CONFLICTS=$(python manage.py showmigrations 2>&1 | grep -i "conflicting\|multiple leaf" || true)
if [ -n "$MIGRATION_CONFLICTS" ]; then
    log_warning "Migration conflicts detected:"
    echo "$MIGRATION_CONFLICTS"
    echo ""
    log_info "Attempting automatic resolution..."

    # Try to auto-resolve with merge
    python manage.py makemigrations --merge --noinput 2>/dev/null || log_warning "Could not auto-merge migrations"
fi

# Run migrations
python manage.py migrate
log_success "Migrations applied"
echo ""

# Step 9: Collect static files
log_info "Collecting static files..."
python manage.py collectstatic --noinput --clear
log_success "Static files collected"
echo ""

# Step 10: Restart service
log_info "Restarting Gunicorn service..."
sudo systemctl restart clientst0r-gunicorn.service

# Wait a moment for service to start
sleep 2

# Check service status
if sudo systemctl is-active --quiet clientst0r-gunicorn.service; then
    log_success "Service restarted successfully"
else
    log_error "Service failed to start. Check: sudo systemctl status clientst0r-gunicorn.service"
    exit 1
fi
echo ""

# Step 11: Display current version
log_info "Checking current version..."
CURRENT_VERSION=$(python manage.py shell -c "from config.version import VERSION; print(VERSION)" 2>/dev/null || echo "Unknown")
log_success "HuduGlue is now running version $CURRENT_VERSION"
echo ""

# Summary
echo "╔════════════════════════════════════════════════════════╗"
echo "║                                                        ║"
echo "║              ✅ Update Completed Successfully          ║"
echo "║                                                        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
log_info "What was done:"
echo "  ✓ Cleaned up locally-generated migrations"
echo "  ✓ Pulled latest code from GitHub"
echo "  ✓ Updated Python dependencies"
echo "  ✓ Applied database migrations"
echo "  ✓ Collected static files"
echo "  ✓ Restarted service"
echo ""
log_success "HuduGlue is ready to use!"
