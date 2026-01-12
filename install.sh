#!/bin/bash
#
# HuduGlue Installer - Simple automated setup
# Usage: bash install.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║             HuduGlue Automated Installer                  ║"
echo "║                      v2.2.0                               ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Function to print status messages
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root. It will ask for sudo when needed."
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Try to find the actual installation directory
INSTALL_DIR="$SCRIPT_DIR"

# Check if current directory has venv/.env
if [ ! -f "$SCRIPT_DIR/venv/bin/activate" ] && [ ! -f "$SCRIPT_DIR/.env" ]; then
    # Look for installation in common locations
    POSSIBLE_DIRS=(
        "$HOME/huduglue"
        "$(dirname "$SCRIPT_DIR")"
        "/home/administrator/huduglue"
    )

    for dir in "${POSSIBLE_DIRS[@]}"; do
        if [ -f "$dir/venv/bin/activate" ] || [ -f "$dir/.env" ]; then
            INSTALL_DIR="$dir"
            print_warning "Found existing installation at: $INSTALL_DIR"
            break
        fi
    done
fi

cd "$INSTALL_DIR"

print_info "Installing from: $INSTALL_DIR"
echo ""

# Detect existing installation
EXISTING_INSTALL=false
HAS_DATABASE=false
HAS_VENV=false
HAS_SERVICE=false
HAS_ENV=false

# Check for database with data
if sudo mysql -e "USE huduglue; SELECT COUNT(*) FROM auth_user;" 2>/dev/null | grep -q -E "[0-9]+"; then
    HAS_DATABASE=true
    EXISTING_INSTALL=true
fi

# Check for venv
if [ -f "$INSTALL_DIR/venv/bin/activate" ]; then
    HAS_VENV=true
    EXISTING_INSTALL=true
fi

# Check for service
if sudo systemctl list-unit-files | grep -q huduglue-gunicorn.service; then
    HAS_SERVICE=true
    EXISTING_INSTALL=true
fi

# Check for .env
if [ -f "$INSTALL_DIR/.env" ]; then
    HAS_ENV=true
    EXISTING_INSTALL=true
fi

if [ "$EXISTING_INSTALL" = true ]; then
    echo ""
    print_warning "Existing HuduGlue installation detected!"
    echo ""

    # Show what exists
    if [ "$HAS_ENV" = true ]; then
        echo "  • Found: .env configuration file"
    fi
    if [ "$HAS_VENV" = true ]; then
        echo "  • Found: Python virtual environment"
    fi
    if [ "$HAS_SERVICE" = true ]; then
        echo "  • Found: systemd service"
        if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
            echo "    Status: Running ✓"
        else
            echo "    Status: Stopped"
        fi
    fi
    if [ "$HAS_DATABASE" = true ]; then
        USER_COUNT=$(sudo mysql -e "USE huduglue; SELECT COUNT(*) FROM auth_user;" 2>/dev/null | tail -n1)
        echo "  • Found: Database 'huduglue' with $USER_COUNT user(s)"
    fi

    echo ""
    echo "What would you like to do?"
    echo ""
    echo "  1) Upgrade/Update (pull latest code, run migrations, restart service)"
    echo "  2) System Check (verify all components are working)"
    echo "  3) Clean Install (remove everything and reinstall)"
    echo "  4) Exit"
    echo ""
    read -p "Enter choice [1-4]: " choice

    case $choice in
        1)
            print_info "Starting upgrade process..."

            # Stop service and kill any gunicorn processes
            print_info "Stopping service..."
            sudo systemctl stop huduglue-gunicorn.service 2>/dev/null || true
            sudo pkill -9 gunicorn 2>/dev/null || true
            sleep 1

            # Pull latest code
            print_info "Pulling latest code from GitHub..."
            cd "$INSTALL_DIR"
            git pull origin main || print_warning "Git pull failed or not a git repository"

            # Check if venv exists, create if missing
            if [ ! -d "venv" ] || [ ! -f "venv/bin/activate" ]; then
                print_warning "Virtual environment not found, creating..."
                python3.12 -m venv venv
                if [ ! -f "venv/bin/activate" ]; then
                    print_error "Failed to create virtual environment"
                    print_error "Install python3.12-venv: sudo apt-get install python3.12-venv"
                    exit 1
                fi
                print_status "Virtual environment created"
            fi

            # Activate venv and upgrade dependencies
            print_info "Updating Python dependencies..."
            source venv/bin/activate
            pip install --upgrade pip -q
            pip install -r requirements.txt --upgrade --progress-bar on

            # Run migrations
            print_info "Running database migrations..."
            python3 manage.py migrate

            # Collect static files
            print_info "Collecting static files..."
            python3 manage.py collectstatic --noinput

            # Restart service
            print_info "Restarting service..."
            sudo systemctl start huduglue-gunicorn.service

            # Check status
            sleep 2
            if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
                print_status "Upgrade complete! Service is running."
                SERVER_IP=$(hostname -I | awk '{print $1}')
                echo ""
                echo "Access at: http://${SERVER_IP}:8000"
            else
                print_error "Service failed to start. Check logs:"
                echo "  sudo journalctl -u huduglue-gunicorn.service -n 50"
            fi
            exit 0
            ;;
        2)
            print_info "Running system check..."
            echo ""

            # Check Python
            if [ -f "$INSTALL_DIR/venv/bin/python3" ]; then
                PYTHON_VERSION=$($INSTALL_DIR/venv/bin/python3 --version 2>&1)
                print_status "Python: $PYTHON_VERSION"
            else
                print_error "Python virtual environment not found"
            fi

            # Check database
            if sudo mysql -e "SHOW DATABASES LIKE 'huduglue';" 2>/dev/null | grep -q huduglue; then
                print_status "Database: huduglue exists"
                TABLE_COUNT=$(sudo mysql -e "USE huduglue; SHOW TABLES;" 2>/dev/null | wc -l)
                echo "  Tables: $((TABLE_COUNT - 1))"
            else
                print_error "Database: huduglue not found"
            fi

            # Check service
            if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
                print_status "Service: Running"
                echo "  $(sudo systemctl show huduglue-gunicorn.service -p MainPID --value) - $(sudo systemctl show huduglue-gunicorn.service -p ActiveState --value)"
            elif sudo systemctl list-unit-files | grep -q huduglue-gunicorn.service; then
                print_warning "Service: Installed but not running"
                echo "  Start with: sudo systemctl start huduglue-gunicorn.service"
            else
                print_error "Service: Not installed"
            fi

            # Check port
            if ss -tlnp 2>/dev/null | grep -q :8000; then
                print_status "Port 8000: Listening"
            else
                print_warning "Port 8000: Not listening"
            fi

            # Check logs directory
            if [ -d "/var/log/itdocs" ]; then
                print_status "Log directory: /var/log/itdocs"
            else
                print_error "Log directory not found"
            fi

            # Test HTTP response
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null || echo "000")
            if [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "200" ]; then
                print_status "HTTP Response: $HTTP_CODE (OK)"
                SERVER_IP=$(hostname -I | awk '{print $1}')
                echo ""
                echo "Access at: http://${SERVER_IP}:8000"
            else
                print_error "HTTP Response: $HTTP_CODE (Failed)"
            fi

            echo ""
            print_info "System check complete"
            exit 0
            ;;
        3)
            print_warning "This will DELETE all data and reinstall from scratch!"
            read -p "Are you sure? Type 'yes' to confirm: " confirm
            if [ "$confirm" != "yes" ]; then
                echo "Aborted."
                exit 0
            fi

            print_info "Removing existing installation..."

            # Stop and remove service
            sudo systemctl stop huduglue-gunicorn.service 2>/dev/null || true
            sudo systemctl disable huduglue-gunicorn.service 2>/dev/null || true
            sudo rm -f /etc/systemd/system/huduglue-gunicorn.service
            sudo systemctl daemon-reload

            # Drop database
            print_info "Dropping database..."
            sudo mysql << 'EOSQL'
DROP DATABASE IF EXISTS huduglue;
DROP USER IF EXISTS 'huduglue'@'localhost';
FLUSH PRIVILEGES;
EOSQL

            # Remove directories
            cd ~
            rm -rf "$INSTALL_DIR/venv"
            rm -f "$INSTALL_DIR/.env"
            rm -f "$INSTALL_DIR/.env.backup"
            # Also clean up any stale files in home directory that might confuse auto-detection
            rm -rf ~/venv
            rm -f ~/.env ~/.env.backup
            sudo rm -rf /var/log/itdocs/

            print_status "Cleanup complete. Starting fresh installation..."
            echo ""
            # Reset INSTALL_DIR to where the script actually is (ignore auto-detection)
            INSTALL_DIR="$SCRIPT_DIR"
            # Change to the correct install directory
            cd "$INSTALL_DIR"
            print_info "Installing to: $INSTALL_DIR"
            # Continue to normal installation
            ;;
        4)
            echo "Exiting."
            exit 0
            ;;
        *)
            print_error "Invalid choice. Exiting."
            exit 1
            ;;
    esac
fi

# Step 1: Check and install system prerequisites
print_info "Step 1/11: Checking system prerequisites..."

PACKAGES_TO_INSTALL=()

# Check for Python 3.12
if ! command -v python3.12 &> /dev/null; then
    print_warning "Python 3.12 not found"
    PACKAGES_TO_INSTALL+=("python3.12")
fi

# Check for python3-venv
if ! dpkg -l | grep -q python3.12-venv; then
    print_warning "python3-venv not found"
    PACKAGES_TO_INSTALL+=("python3.12-venv")
fi

# Check for pip
if ! command -v pip3 &> /dev/null; then
    print_warning "pip not found"
    PACKAGES_TO_INSTALL+=("python3-pip")
fi

# Check for MySQL/MariaDB server
if ! systemctl list-unit-files | grep -q 'mariadb.service\|mysql.service'; then
    print_warning "MariaDB server not found"
    PACKAGES_TO_INSTALL+=("mariadb-server")
fi

# Check for MySQL/MariaDB client
if ! command -v mysql &> /dev/null; then
    print_warning "MySQL client not found"
    PACKAGES_TO_INSTALL+=("mariadb-client")
fi

# Check for build essentials (needed for Python packages like cryptography, mysqlclient)
if ! dpkg -l | grep -q build-essential; then
    print_warning "build-essential not found (needed for Python packages)"
    PACKAGES_TO_INSTALL+=("build-essential")
fi

if ! dpkg -l | grep -q python3.12-dev; then
    PACKAGES_TO_INSTALL+=("python3.12-dev")
fi

if ! dpkg -l | grep -q libssl-dev; then
    PACKAGES_TO_INSTALL+=("libssl-dev")
fi

if ! dpkg -l | grep -q libffi-dev; then
    PACKAGES_TO_INSTALL+=("libffi-dev")
fi

# Check for pkg-config (needed for mysqlclient)
if ! command -v pkg-config &> /dev/null; then
    print_warning "pkg-config not found (needed for mysqlclient)"
    PACKAGES_TO_INSTALL+=("pkg-config")
fi

# Check for MySQL development headers (needed for mysqlclient Python package)
if ! dpkg -l | grep -q libmysqlclient-dev && ! dpkg -l | grep -q default-libmysqlclient-dev; then
    print_warning "MySQL development headers not found (needed for mysqlclient)"
    PACKAGES_TO_INSTALL+=("default-libmysqlclient-dev")
fi

# Check for LDAP development headers (needed for python-ldap package)
if ! dpkg -l | grep -q libldap2-dev && ! dpkg -l | grep -q libldap-dev; then
    print_warning "LDAP development headers not found (needed for python-ldap)"
    PACKAGES_TO_INSTALL+=("libldap2-dev" "libsasl2-dev")
fi

# Install missing packages
if [ ${#PACKAGES_TO_INSTALL[@]} -gt 0 ]; then
    print_info "Installing missing packages: ${PACKAGES_TO_INSTALL[*]}"
    echo -e "${YELLOW}This requires sudo privileges. You may be prompted for your password.${NC}"

    # Update package list
    print_info "Updating package list..."
    sudo apt-get update -qq

    # Set DEBIAN_FRONTEND to avoid interactive prompts
    print_info "Installing packages (this may take a few minutes)..."
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${PACKAGES_TO_INSTALL[@]}"

    print_status "System prerequisites installed"
else
    print_status "All system prerequisites met"
fi

# Step 2: Create virtual environment
print_info "Step 2/11: Creating Python virtual environment..."

if [ -d "venv" ]; then
    print_warning "Virtual environment already exists, removing old one..."
    rm -rf venv
fi

python3.12 -m venv venv
if [ ! -f "venv/bin/activate" ]; then
    print_error "Failed to create virtual environment"
    print_error "Python venv creation failed. Is python3.12-venv installed?"
    exit 1
fi
print_status "Virtual environment created"

# Step 3: Activate virtual environment and install dependencies
print_info "Step 3/11: Installing Python dependencies (this may take 2-3 minutes)..."
source venv/bin/activate
if [ -z "$VIRTUAL_ENV" ]; then
    print_error "Failed to activate virtual environment"
    exit 1
fi

echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip -q

echo -e "${YELLOW}Installing dependencies from requirements.txt...${NC}"
echo -e "${YELLOW}Please wait, this will take a few minutes...${NC}"
pip install -r requirements.txt --progress-bar on

# Verify critical packages were installed
if [ ! -f "venv/bin/gunicorn" ]; then
    print_error "Failed to install dependencies - gunicorn not found"
    print_error "Check the pip install output above for errors"
    exit 1
fi
print_status "Python dependencies installed"

# Step 4: Generate secrets
print_info "Step 4/11: Generating secure secrets..."

APP_MASTER_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
API_KEY_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
# Generate random secure database password (32 chars, alphanumeric + special chars)
DB_PASSWORD=$(python3 -c "import secrets; import string; chars = string.ascii_letters + string.digits + '!@#$%^&*'; print(''.join(secrets.choice(chars) for _ in range(32)))")

print_status "Secrets generated"

# Step 5: Create .env file
print_info "Step 5/11: Creating environment configuration..."

if [ -f ".env" ]; then
    print_warning ".env file already exists, backing up to .env.backup"
    cp .env .env.backup
fi

cat > .env << EOF
# Django Settings
DEBUG=True
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (MariaDB/MySQL)
DB_NAME=huduglue
DB_USER=huduglue
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=localhost
DB_PORT=3306

# Encryption
APP_MASTER_KEY=${APP_MASTER_KEY}
API_KEY_SECRET=${API_KEY_SECRET}

# Email (Optional - configure later)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# Application
SITE_NAME=HuduGlue
SITE_URL=http://localhost:8000

# Security
REQUIRE_2FA=False
EOF

print_status "Environment file created (.env)"
print_info "Secure random database password generated"

# Step 6: Database setup
echo ""
print_info "Step 6/11: Database setup..."
print_info "We'll now create the database and user."

# Check if MariaDB/MySQL is running
if ! sudo systemctl is-active --quiet mariadb && ! sudo systemctl is-active --quiet mysql; then
    print_warning "MariaDB/MySQL is not running. Attempting to start..."

    if sudo systemctl start mariadb 2>/dev/null || sudo systemctl start mysql 2>/dev/null; then
        print_status "Database server started"
    else
        print_error "Could not start database server. Please install MariaDB:"
        echo "  sudo apt-get install mariadb-server"
        echo "  sudo systemctl start mariadb"
        echo "  sudo mysql_secure_installation"
        exit 1
    fi
fi

print_info "Creating database and user with secure random password..."
print_warning "You may be prompted for the MySQL root password."
echo ""

# Create database and user with the generated password
sudo mysql << EOSQL
CREATE DATABASE IF NOT EXISTS huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'huduglue'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue'@'localhost';
FLUSH PRIVILEGES;
EOSQL

if [ $? -eq 0 ]; then
    print_status "Database created successfully"
    print_info "  Database: huduglue"
    print_info "  User: huduglue"
    print_info "  Password: (stored in .env file)"
else
    print_error "Database creation failed. You may need to create it manually."
    echo ""
    echo "Run these commands in MySQL as root (use the password from .env file):"
    echo "  CREATE DATABASE huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    echo "  CREATE USER 'huduglue'@'localhost' IDENTIFIED BY '<password from .env>';"
    echo "  GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue'@'localhost';"
    echo "  FLUSH PRIVILEGES;"
    echo ""
    read -p "Press Enter once you've created the database manually..."
fi

# Step 7: Create log directory
print_info "Step 7/10: Creating log directory..."
sudo mkdir -p /var/log/itdocs
sudo chown $USER:$USER /var/log/itdocs
sudo chmod 755 /var/log/itdocs
print_status "Log directory created"

# Step 8: Run migrations
print_info "Step 8/10: Running database migrations..."
python3 manage.py migrate
print_status "Database migrations completed"

# Step 8.5: Initial organization setup
echo ""
print_info "Step 8.5/10: Initial organization setup..."
print_info "Running setup.py to create your organization..."
python3 setup.py
print_status "Organization setup completed"

# Step 9: Create superuser
echo ""
print_info "Step 9/10: Creating superuser account..."

# Create superuser non-interactively
# Default credentials: admin / ChangeMe123!
export DJANGO_SUPERUSER_PASSWORD='ChangeMe123!'
python3 manage.py createsuperuser \
    --username admin \
    --email admin@huduglue.local \
    --noinput 2>/dev/null || true

if python3 manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); exit(0 if User.objects.filter(username='admin').exists() else 1)" 2>/dev/null; then
    print_status "Superuser created successfully"
    print_info "  Username: admin"
    print_info "  Password: ChangeMe123!"
    print_warning "  ⚠️  CHANGE THIS PASSWORD after first login!"
else
    print_warning "Superuser creation skipped (may already exist or failed)"
    print_info "  You can create one manually: python3 manage.py createsuperuser"
fi
unset DJANGO_SUPERUSER_PASSWORD

# Step 10: Seed default templates (on fresh install only)
print_info "Step 10/12: Seeding default templates..."
if python3 manage.py shell -c "from docs.models import Document, Diagram; exit(0 if Document.objects.filter(is_template=True).count() == 0 and Diagram.objects.filter(is_template=True).count() == 0 else 1)" 2>/dev/null; then
    # Fresh install - seed templates
    print_info "  Populating document categories..."
    python3 manage.py populate_doc_categories > /dev/null 2>&1 || true

    print_info "  Seeding document templates..."
    python3 manage.py seed_templates > /dev/null 2>&1 || true

    print_info "  Seeding diagram templates..."
    python3 manage.py seed_diagram_templates > /dev/null 2>&1 || true

    print_info "  Populating MSP knowledge base..."
    python3 manage.py populate_msp_kb > /dev/null 2>&1 || true

    print_status "Default templates seeded successfully"
else
    print_info "  Templates already exist, skipping seed"
fi

# Step 11: Collect static files
print_info "Step 11/12: Collecting static files..."
python3 manage.py collectstatic --noinput > /dev/null 2>&1
print_status "Static files collected"

# Step 12: Start the server automatically
echo ""
print_info "Step 12/12: Starting production server..."

# Stop any existing service and kill processes
sudo systemctl stop huduglue-gunicorn.service 2>/dev/null || true
sudo pkill -9 gunicorn 2>/dev/null || true
sleep 2

# Create systemd service file
sudo tee /etc/systemd/system/huduglue-gunicorn.service > /dev/null << 'SVCEOF'
[Unit]
Description=HuduGlue Gunicorn
After=network.target mariadb.service
Wants=mariadb.service

[Service]
Type=notify
User=USER_PLACEHOLDER
Group=USER_PLACEHOLDER
WorkingDirectory=WORKDIR_PLACEHOLDER
Environment="PATH=WORKDIR_PLACEHOLDER/venv/bin"
ExecStart=WORKDIR_PLACEHOLDER/venv/bin/gunicorn \
    --workers 4 \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile /var/log/itdocs/gunicorn-access.log \
    --error-logfile /var/log/itdocs/gunicorn-error.log \
    --log-level info \
    config.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
SVCEOF

# Replace placeholders with actual values
sudo sed -i "s|USER_PLACEHOLDER|$USER|g" /etc/systemd/system/huduglue-gunicorn.service
sudo sed -i "s|WORKDIR_PLACEHOLDER|$INSTALL_DIR|g" /etc/systemd/system/huduglue-gunicorn.service

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable huduglue-gunicorn.service 2>&1 | grep -v "Created symlink" || true
sudo systemctl start huduglue-gunicorn.service

# Wait for service to start (gunicorn takes a moment to initialize workers)
sleep 4

# Check if service started successfully
if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
    print_status "Production server started successfully!"
else
    print_error "Failed to start production server. Checking logs..."
    sudo journalctl -u huduglue-gunicorn.service -n 30 --no-pager
    echo ""
    print_info "Trying to diagnose the issue..."
    sudo ss -tlnp | grep :8000 || echo "Port 8000 is not in use"
    exit 1
fi

# Get server IP address
SERVER_IP=$(hostname -I | awk '{print $1}')

# Print summary
echo ""
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}║        HuduGlue Installation Complete! 🎉 🐕              ║${NC}"
echo -e "${GREEN}║              Server is RUNNING!                           ║${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

print_info "🌐 Access your HuduGlue installation at:"
echo ""
echo -e "  ${GREEN}➜  http://${SERVER_IP}:8000${NC}"
echo -e "  ${GREEN}➜  http://localhost:8000${NC} (if accessing from this server)"
echo ""

print_info "🔐 Login Credentials:"
echo "  • Username: (the username you created)"
echo "  • Password: (the password you entered)"
echo ""

print_info "📊 What's Running:"
echo "  ✅ MariaDB Database: huduglue"
echo "  ✅ Gunicorn Server: 4 workers on port 8000"
echo "  ✅ Auto-start on boot: Enabled"
echo "  ✅ Auto-restart on failure: Enabled"
echo ""

print_info "🔧 Server Management:"
echo "  • Check status:  sudo systemctl status huduglue-gunicorn.service"
echo "  • Restart:       sudo systemctl restart huduglue-gunicorn.service"
echo "  • Stop:          sudo systemctl stop huduglue-gunicorn.service"
echo "  • View logs:     sudo journalctl -u huduglue-gunicorn.service -f"
echo ""

print_warning "⚠️  IMPORTANT SECURITY STEPS:"
echo "  1. Backup your .env file (contains secure database password)"
echo "  2. Set DEBUG=False in .env for production"
echo "  3. Update ALLOWED_HOSTS in .env with your domain/IP"
echo "  4. Enable 2FA after first login (Profile → Two-Factor Authentication)"
echo "  5. Create an Organization (Dashboard → Organizations)"
echo ""

print_info "🔐 Security Notes:"
echo "  ✅ Random secure database password generated (32 characters)"
echo "  ✅ Random Django SECRET_KEY generated (50+ characters)"
echo "  ✅ Random encryption keys generated"
echo "  📄 All credentials stored in: $INSTALL_DIR/.env"
echo ""

print_info "📚 Documentation: https://github.com/agit8or1/huduglue"
echo ""

print_status "Installation files:"
echo "  • Install directory: $INSTALL_DIR"
echo "  • Config file: $INSTALL_DIR/.env"
echo "  • Virtual env: $INSTALL_DIR/venv"
echo "  • Logs: /var/log/itdocs/"
echo ""
