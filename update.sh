#!/bin/bash
#################################################
# Client St0r Update Script
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
echo -e "${BLUE}Client St0r Update Script${NC}"
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

# Check if venv exists (try multiple common locations)
info "Checking for virtual environment..."
VENV_DIR=""
if [ -d "venv" ]; then
    VENV_DIR="venv"
elif [ -d "ENV" ]; then
    VENV_DIR="ENV"
elif [ -d "env" ]; then
    VENV_DIR="env"
elif [ -d ".venv" ]; then
    VENV_DIR=".venv"
else
    # Try to find it in parent or common locations
    if [ -d "../venv" ]; then
        VENV_DIR="../venv"
    elif [ -d "/home/administrator/venv" ]; then
        VENV_DIR="/home/administrator/venv"
    elif [ -d "$HOME/venv" ]; then
        VENV_DIR="$HOME/venv"
    fi
fi

if [ -z "$VENV_DIR" ]; then
    error_exit "Virtual environment not found. Checked: venv, ENV, env, .venv, ../venv, /home/administrator/venv"
fi
success "Found virtual environment at: $VENV_DIR"

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
    source "$VENV_DIR/bin/activate" || error_exit "Failed to activate virtual environment"
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
git fetch origin || error_exit "Git fetch failed"

# Check if branches are divergent (happens after force push to remote)
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    # Updates available - check if it's a force push (for informational message)
    git merge-base --is-ancestor HEAD origin/main
    IS_ANCESTOR=$?

    if [ $IS_ANCESTOR -ne 0 ]; then
        # Branches are divergent (remote was force-pushed)
        warning "Remote repository history has changed (force push detected)"
        echo ""
        echo "This typically happens after repository maintenance."
        echo "Your local changes were already checked in Step 1."
        echo ""
    else
        # Regular update
        info "Update available..."
        echo ""
    fi

    # Always use reset --hard for reliability (avoids git pull configuration issues)
    read -p "Apply update to latest version? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Updating to latest version..."
        git reset --hard origin/main || error_exit "Git reset failed"
        success "Updated to latest version successfully"
    else
        error_exit "Update cancelled by user"
    fi
else
    success "Already up to date"
fi

echo ""
echo -e "${YELLOW}Step 3: Installing Dependencies${NC}"
echo "-----------------------------------"

info "Installing/updating Python packages..."
pip install -r requirements.txt || error_exit "pip install failed"
success "Core dependencies installed"

# Install optional dependencies if they exist
if [ -f "requirements-graphql.txt" ]; then
    info "Installing GraphQL API dependencies..."
    pip install -r requirements-graphql.txt || warning "GraphQL dependencies failed (non-critical)"
    success "GraphQL dependencies installed"
fi

if [ -f "requirements-optional.txt" ]; then
    info "Checking for LDAP/optional dependencies..."
    # Only attempt if build-essential is available
    if dpkg -l | grep -q build-essential; then
        pip install -r requirements-optional.txt || warning "Optional dependencies failed (LDAP requires system packages)"
        success "Optional dependencies installed"
    else
        warning "Skipping LDAP dependencies (build-essential not installed)"
    fi
fi

# Migrate from old system-wide Snyk to nvm-based installation
info "Checking for old system-wide Snyk installation..."
if [ -d "/usr/local/lib/node_modules/snyk" ] && [ -d "$HOME/.nvm" ]; then
    warning "Found old system-wide Snyk installation - migrating to nvm-based installation..."

    # Remove system-wide symlink if exists
    if [ -L "/usr/local/bin/snyk" ]; then
        info "Removing old Snyk symlink..."
        sudo rm -f /usr/local/bin/snyk || warning "Failed to remove symlink (non-critical)"
    fi

    # Uninstall system-wide Snyk
    info "Removing old system-wide Snyk installation..."
    sudo npm uninstall -g snyk 2>/dev/null || warning "Failed to uninstall system Snyk (non-critical)"

    # Remove directory if it still exists
    if [ -d "/usr/local/lib/node_modules/snyk" ]; then
        sudo rm -rf /usr/local/lib/node_modules/snyk 2>/dev/null || warning "Failed to remove Snyk directory (non-critical)"
    fi

    success "Old Snyk installation cleaned up - will use nvm-based installation"
elif [ -d "/usr/local/lib/node_modules/snyk" ] && [ ! -d "$HOME/.nvm" ]; then
    info "Found system-wide Snyk installation (kept - no nvm detected)"
else
    success "No migration needed"
fi

# Check and install Snyk CLI if missing (now managed via web interface)
info "Checking for Snyk CLI..."
if command -v snyk &> /dev/null; then
    SNYK_VERSION=$(snyk --version 2>/dev/null || echo "unknown")
    success "Snyk CLI installed (version: $SNYK_VERSION)"
    info "  • Manage Snyk via Settings → Snyk Security in the web interface"
    info "  • Use 'Install All Dependencies' button for automatic setup"
elif [ -d "$HOME/.nvm" ]; then
    # Check if snyk exists in nvm but isn't in PATH
    SNYK_NVM_PATH=$(find "$HOME/.nvm/versions/node/" -name snyk -type f 2>/dev/null | head -1)
    if [ -n "$SNYK_NVM_PATH" ]; then
        success "Snyk CLI found in nvm (available in web interface)"
        info "  • Snyk CLI will be available when running via web interface"
    else
        warning "Snyk CLI not installed"
        info "  • Install via Settings → Snyk Security → 'Install All Dependencies'"
    fi
else
    warning "Snyk CLI not available"
    info "  • Install Node.js and Snyk via Settings → Snyk Security"
    info "  • Click 'Install All Dependencies' for automatic setup"
fi

echo ""
echo -e "${YELLOW}Step 3.5: Regenerating Sudoers Files${NC}"
echo "-----------------------------------"

info "Generating sudoers files with correct paths..."

# Get current user and install directory
CURRENT_USER="$USER"
INSTALL_DIR="$(pwd)"

# Create deploy directory if it doesn't exist
mkdir -p "$INSTALL_DIR/deploy"

# Generate clientst0r-install-sudoers
cat > "$INSTALL_DIR/deploy/clientst0r-install-sudoers" <<SUDOEOF
# Sudoers configuration for Client St0r automatic fail2ban installation
# Install: sudo cp $INSTALL_DIR/deploy/clientst0r-install-sudoers /etc/sudoers.d/clientst0r-install
# Permissions: sudo chmod 0440 /etc/sudoers.d/clientst0r-install

# Allow $CURRENT_USER user to install and configure fail2ban without password
$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/bin/apt-get install -y fail2ban
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl enable fail2ban
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl start fail2ban
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl status fail2ban
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/cp $INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/chmod 0440 /etc/sudoers.d/clientst0r-fail2ban
SUDOEOF

# Generate clientst0r-fail2ban-sudoers
cat > "$INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers" <<FBSUDOEOF
# Sudoers configuration for Client St0r fail2ban integration
# Install: sudo cp $INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban
# Permissions: sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban

# Allow $CURRENT_USER user to run fail2ban-client without password
$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/bin/fail2ban-client
FBSUDOEOF

success "Sudoers files regenerated for user: $CURRENT_USER"
info "  • $INSTALL_DIR/deploy/clientst0r-install-sudoers"
info "  • $INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers"

# Automatically install sudoers files if they don't exist or have changed
info "Checking sudoers installation..."
INSTALL_SUDOERS=false
FB_SUDOERS=false

# Check clientst0r-install sudoers
if [ ! -f "/etc/sudoers.d/clientst0r-install" ]; then
    INSTALL_SUDOERS=true
    info "  • clientst0r-install not found - will install"
elif ! sudo diff -q "$INSTALL_DIR/deploy/clientst0r-install-sudoers" "/etc/sudoers.d/clientst0r-install" &>/dev/null; then
    INSTALL_SUDOERS=true
    info "  • clientst0r-install has changed - will update"
else
    success "  • clientst0r-install already up to date"
fi

# Check clientst0r-fail2ban sudoers
if [ ! -f "/etc/sudoers.d/clientst0r-fail2ban" ]; then
    FB_SUDOERS=true
    info "  • clientst0r-fail2ban not found - will install"
elif ! sudo diff -q "$INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers" "/etc/sudoers.d/clientst0r-fail2ban" &>/dev/null; then
    FB_SUDOERS=true
    info "  • clientst0r-fail2ban has changed - will update"
else
    success "  • clientst0r-fail2ban already up to date"
fi

# Install/update sudoers files if needed
if [ "$INSTALL_SUDOERS" = true ] || [ "$FB_SUDOERS" = true ]; then
    echo ""
    info "Installing sudoers files (requires sudo access)..."
    echo ""
    warning "NOTE: You may be prompted for your sudo password to install sudoers files."
    info "These files enable passwordless sudo for specific Client St0r operations."
    echo ""

    INSTALL_SUCCESS=true

    if [ "$INSTALL_SUDOERS" = true ]; then
        echo -n "Installing clientst0r-install sudoers... "
        # Store output and check return code properly
        if OUTPUT=$(sudo cp "$INSTALL_DIR/deploy/clientst0r-install-sudoers" /etc/sudoers.d/clientst0r-install 2>&1) && \
           sudo chmod 0440 /etc/sudoers.d/clientst0r-install 2>&1; then
            success "✓ Installed"
        else
            INSTALL_SUCCESS=false
            echo -e "${RED}✗ FAILED${NC}"
            warning "Error: $OUTPUT"
            warning "Manual installation required. Run this command:"
            echo -e "${YELLOW}    sudo cp $INSTALL_DIR/deploy/clientst0r-install-sudoers /etc/sudoers.d/clientst0r-install && sudo chmod 0440 /etc/sudoers.d/clientst0r-install${NC}"
        fi
    fi

    if [ "$FB_SUDOERS" = true ]; then
        echo -n "Installing clientst0r-fail2ban sudoers... "
        # Store output and check return code properly
        if OUTPUT=$(sudo cp "$INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers" /etc/sudoers.d/clientst0r-fail2ban 2>&1) && \
           sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban 2>&1; then
            success "✓ Installed"
        else
            INSTALL_SUCCESS=false
            echo -e "${RED}✗ FAILED${NC}"
            warning "Error: $OUTPUT"
            warning "Manual installation required. Run this command:"
            echo -e "${YELLOW}    sudo cp $INSTALL_DIR/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban && sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban${NC}"
        fi
    fi

    if [ "$INSTALL_SUCCESS" = false ]; then
        echo ""
        error "⚠ SUDOERS INSTALLATION INCOMPLETE"
        warning "Some features like automatic fail2ban setup will require manual sudo password entry."
        warning "To fix this, run the manual installation commands shown above."
        echo ""
        read -p "Continue with update anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error_exit "Update cancelled - please install sudoers files manually first"
        fi
    fi
fi

echo ""
echo -e "${YELLOW}Step 4: Database Migrations${NC}"
echo "-----------------------------------"

info "Running database migrations..."
python manage.py migrate || error_exit "Database migration failed"
success "Database updated"

# Create default report templates if they don't exist
info "Creating default report templates..."
python manage.py create_default_reports 2>&1 | grep -E "(Created|Already exists)" || true
success "Default templates verified"

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
    info "Detecting Gunicorn service name..."

    # Auto-detect service name (supports both clientst0r-gunicorn and clientst0r-gunicorn)
    SERVICE_NAME=""
    if systemctl list-units --type=service --all | grep -q "clientst0r-gunicorn.service"; then
        SERVICE_NAME="clientst0r-gunicorn.service"
        info "Found service: clientst0r-gunicorn.service"
    elif systemctl list-units --type=service --all | grep -q "clientst0r-gunicorn.service"; then
        SERVICE_NAME="clientst0r-gunicorn.service"
        info "Found service: clientst0r-gunicorn.service"
    else
        warning "Could not find gunicorn service. Trying clientst0r-gunicorn.service..."
        SERVICE_NAME="clientst0r-gunicorn.service"
    fi

    info "Restarting $SERVICE_NAME..."
    sudo systemctl restart "$SERVICE_NAME" || warning "Service restart failed - you may need to restart manually"

    # Wait a moment for service to start
    sleep 2

    # Check service status
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Service restarted successfully"
    else
        warning "Service may not have restarted correctly. Check with: sudo systemctl status $SERVICE_NAME"
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
    python -c "from config.version import get_version; print(f'  Client St0r v{get_version()}')" 2>/dev/null || true
fi

echo ""
info "Check the application in your browser to verify the update."
echo ""
