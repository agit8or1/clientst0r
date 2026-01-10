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
cd "$SCRIPT_DIR"

print_info "Installing from: $SCRIPT_DIR"
echo ""

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
print_status "Virtual environment created"

# Step 3: Activate virtual environment and install dependencies
print_info "Step 3/11: Installing Python dependencies (this may take 2-3 minutes)..."
source venv/bin/activate

echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip -q

echo -e "${YELLOW}Installing dependencies from requirements.txt...${NC}"
echo -e "${YELLOW}Please wait, this will take a few minutes...${NC}"
pip install -r requirements.txt --progress-bar on
print_status "Python dependencies installed"

# Step 4: Generate secrets
print_info "Step 4/11: Generating secure secrets..."

APP_MASTER_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
API_KEY_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")

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
DB_PASSWORD=ChangeMe123!
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
EOF

print_status "Environment file created (.env)"
print_warning "Default database password is 'ChangeMe123!' - you should change this!"

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

print_info "Creating database and user..."
print_warning "You'll be prompted for the MySQL root password."
echo ""

# Create database and user
sudo mysql << 'EOSQL'
CREATE DATABASE IF NOT EXISTS huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'huduglue'@'localhost' IDENTIFIED BY 'ChangeMe123!';
GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue'@'localhost';
FLUSH PRIVILEGES;
EOSQL

if [ $? -eq 0 ]; then
    print_status "Database created successfully"
    print_info "  Database: huduglue"
    print_info "  User: huduglue"
    print_info "  Password: ChangeMe123!"
else
    print_error "Database creation failed. You may need to create it manually."
    echo ""
    echo "Run these commands in MySQL as root:"
    echo "  CREATE DATABASE huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    echo "  CREATE USER 'huduglue'@'localhost' IDENTIFIED BY 'ChangeMe123!';"
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

# Step 9: Create superuser
echo ""
print_info "Step 9/10: Creating superuser account..."
print_info "You'll be prompted to create an admin account."
echo ""

python3 manage.py createsuperuser

print_status "Superuser created"

# Step 10: Collect static files
print_info "Step 10/10: Collecting static files..."
python3 manage.py collectstatic --noinput > /dev/null 2>&1
print_status "Static files collected"

# Step 11: Start the server automatically
echo ""
print_info "Step 11/11: Starting production server..."

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
sudo sed -i "s|WORKDIR_PLACEHOLDER|$SCRIPT_DIR|g" /etc/systemd/system/huduglue-gunicorn.service

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable huduglue-gunicorn.service
sudo systemctl start huduglue-gunicorn.service

# Wait a moment for service to start
sleep 2

# Check if service started successfully
if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
    print_status "Production server started successfully!"
else
    print_error "Failed to start production server. Checking logs..."
    sudo journalctl -u huduglue-gunicorn.service -n 20 --no-pager
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
echo "  1. Change database password in .env and MySQL"
echo "  2. Set DEBUG=False in .env for production"
echo "  3. Update ALLOWED_HOSTS in .env with your domain/IP"
echo "  4. Enable 2FA after first login (Profile → Two-Factor Authentication)"
echo "  5. Create an Organization (Dashboard → Organizations)"
echo ""

print_info "📚 Documentation: https://github.com/agit8or1/huduglue"
echo ""

print_status "Installation files:"
echo "  • Install directory: $SCRIPT_DIR"
echo "  • Config file: $SCRIPT_DIR/.env"
echo "  • Virtual env: $SCRIPT_DIR/venv"
echo "  • Logs: /var/log/itdocs/"
echo ""
