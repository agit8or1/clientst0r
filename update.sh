#!/bin/bash
#################################################
# HuduGlue Update Script
# Safely updates the application from GitHub
#################################################

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}HuduGlue Update Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to print error and exit
error_exit() {
    echo -e "${RED}ERROR: $1${NC}" >&2
    exit 1
}

# Function to print success
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print warning
warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print info
info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

echo -e "${YELLOW}Step 1: Pre-flight Checks${NC}"
echo "-----------------------------------"

# Check if we're in the right directory
info "Checking for manage.py..."
if [ ! -f "manage.py" ]; then
    error_exit "manage.py not found in current directory. Please cd to the application directory first."
fi
success "Found manage.py"

# Check if venv exists
info "Checking for virtual environment..."
if [ ! -d "venv" ]; then
    error_exit "venv directory not found. Virtual environment is missing."
fi
success "Found venv/"

# Check if this is a git repository
info "Checking git repository..."
if [ ! -d ".git" ]; then
    error_exit "Not a git repository. Cannot pull updates."
fi
success "Git repository detected"

# Check for uncommitted changes
info "Checking for uncommitted changes..."
if ! git diff-index --quiet HEAD --; then
    warning "You have uncommitted changes in your working directory"
    git status --short
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error_exit "Update cancelled by user"
    fi
else
    success "Working directory is clean"
fi

# Check if venv is activated
info "Checking virtual environment activation..."
if [ -z "$VIRTUAL_ENV" ]; then
    warning "Virtual environment not activated. Activating now..."
    source venv/bin/activate || error_exit "Failed to activate virtual environment"
    success "Virtual environment activated"
else
    success "Virtual environment already active"
fi

# Check Python version
info "Checking Python version..."
PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
success "Python $PYTHON_VERSION"

# Check if systemctl is available (for restart)
info "Checking systemctl availability..."
if ! command -v systemctl &> /dev/null; then
    warning "systemctl not found - you'll need to restart the service manually"
    RESTART_SERVICE=false
else
    success "systemctl available"
    RESTART_SERVICE=true
fi

echo ""
echo -e "${GREEN}All pre-flight checks passed!${NC}"
echo ""
read -p "Proceed with update? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    error_exit "Update cancelled by user"
fi

echo ""
echo -e "${YELLOW}Step 2: Pulling Updates${NC}"
echo "-----------------------------------"

info "Fetching latest code from GitHub..."
git pull origin main || error_exit "Git pull failed"
success "Code updated successfully"

echo ""
echo -e "${YELLOW}Step 3: Installing Dependencies${NC}"
echo "-----------------------------------"

info "Installing/updating Python packages..."
pip install -r requirements.txt || error_exit "pip install failed"
success "Dependencies installed"

echo ""
echo -e "${YELLOW}Step 4: Database Migrations${NC}"
echo "-----------------------------------"

info "Running database migrations..."
python manage.py migrate || error_exit "Database migration failed"
success "Database updated"

echo ""
echo -e "${YELLOW}Step 5: Collecting Static Files${NC}"
echo "-----------------------------------"

info "Collecting static files..."
python manage.py collectstatic --noinput || error_exit "collectstatic failed"
success "Static files collected"

echo ""
echo -e "${YELLOW}Step 6: Restarting Service${NC}"
echo "-----------------------------------"

if [ "$RESTART_SERVICE" = true ]; then
    info "Restarting Gunicorn service..."
    sudo systemctl restart huduglue-gunicorn.service || warning "Service restart failed - you may need to restart manually"

    # Wait a moment for service to start
    sleep 2

    # Check service status
    if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
        success "Service restarted successfully"
    else
        warning "Service may not have restarted correctly. Check with: sudo systemctl status huduglue-gunicorn.service"
    fi
else
    warning "Please restart the Gunicorn service manually"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Update Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Show current version if available
if [ -f "config/version.py" ]; then
    info "Current version:"
    python -c "from config.version import get_version; print(f'  HuduGlue v{get_version()}')" 2>/dev/null || true
fi

echo ""
info "Check the application in your browser to verify the update."
echo ""
