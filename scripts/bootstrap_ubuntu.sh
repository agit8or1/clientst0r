#!/bin/bash
# Bootstrap script for Ubuntu
# Installs system dependencies, creates database, sets up venv, runs migrations
# Supports both fresh installation and upgrades

set -e

echo "========================================="
echo "client st0r - Bootstrap"
echo "========================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Error: Do not run as root. Run as normal user with sudo access."
    exit 1
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Error: .env file not found. Copy .env.example to .env and configure it first."
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Detect if this is an upgrade or fresh install
INSTALL_TYPE="fresh"
if [ -f "venv/bin/python" ] && [ -d "static_collected" ]; then
    INSTALL_TYPE="upgrade"
    echo "✓ Existing installation detected - running upgrade mode"
    echo ""
fi

if [ "$INSTALL_TYPE" = "upgrade" ]; then
    echo "========================================="
    echo "UPGRADE MODE"
    echo "========================================="
    echo ""
    echo "This will:"
    echo "  - Update Python dependencies"
    echo "  - Run database migrations"
    echo "  - Collect static files"
    echo "  - Restart services (if running)"
    echo ""
    read -p "Continue with upgrade? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Upgrade cancelled."
        exit 0
    fi
    echo ""
fi

if [ "$INSTALL_TYPE" = "fresh" ]; then
    echo "Step 1: Installing system packages..."
    sudo apt-get update
    sudo apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        mariadb-server \
        nginx \
        build-essential \
        libmariadb-dev \
        pkg-config \
        git

    echo "Step 2: Setting up MariaDB..."
    sudo systemctl start mariadb
    sudo systemctl enable mariadb

    # Create database and user
    echo "Creating database and user..."
    sudo mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';"
    sudo mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
    sudo mysql -e "FLUSH PRIVILEGES;"

    echo "Step 3: Creating virtual environment..."
    python3 -m venv venv
else
    echo "Step 1: Backing up current installation..."
    BACKUP_DIR="backups/upgrade-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR"

    # Backup database
    echo "  - Backing up database to $BACKUP_DIR/database.sql"
    mysqldump -u ${DB_USER} -p${DB_PASSWORD} ${DB_NAME} > "$BACKUP_DIR/database.sql"

    # Backup .env
    echo "  - Backing up .env file"
    cp .env "$BACKUP_DIR/.env.backup"

    echo "✓ Backup completed"
    echo ""
fi

STEP_NUM=$( [ "$INSTALL_TYPE" = "fresh" ] && echo "4" || echo "2" )
echo "Step ${STEP_NUM}: Installing Python packages..."
source venv/bin/activate
pip install --upgrade pip

if [ "$INSTALL_TYPE" = "upgrade" ]; then
    echo "  - Upgrading packages from requirements.txt"
    pip install --upgrade -r requirements.txt
else
    pip install -r requirements.txt
fi

if [ "$INSTALL_TYPE" = "fresh" ]; then
    STEP_NUM=5
    echo "Step ${STEP_NUM}: Creating upload directory..."
    sudo mkdir -p ${UPLOAD_ROOT}
    sudo chown -R $(whoami):$(whoami) ${UPLOAD_ROOT}

    STEP_NUM=6
    echo "Step ${STEP_NUM}: Creating log directory..."
    sudo mkdir -p /var/log/itdocs
    sudo chown -R $(whoami):$(whoami) /var/log/itdocs
fi

STEP_NUM=$( [ "$INSTALL_TYPE" = "fresh" ] && echo "7" || echo "3" )
echo "Step ${STEP_NUM}: Running migrations..."
python manage.py migrate

STEP_NUM=$( [ "$INSTALL_TYPE" = "fresh" ] && echo "8" || echo "4" )
echo "Step ${STEP_NUM}: Collecting static files..."
python manage.py collectstatic --noinput

if [ "$INSTALL_TYPE" = "fresh" ]; then
    echo "Step 9: Creating superuser (optional)..."
    echo "You can create a superuser now or run 'python manage.py createsuperuser' later."
    read -p "Create superuser now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python manage.py createsuperuser
    fi

    echo "Step 10: Seeding demo data (optional)..."
    read -p "Seed demo data? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python manage.py seed_demo
    fi
fi

if [ "$INSTALL_TYPE" = "upgrade" ]; then
    echo "Step 5: Restarting services..."

    # Check if gunicorn service exists and is active
    if systemctl is-active --quiet itdocs-gunicorn; then
        echo "  - Restarting itdocs-gunicorn service..."
        sudo systemctl restart itdocs-gunicorn
        echo "  ✓ Service restarted"
    else
        echo "  ℹ itdocs-gunicorn service not running (will need manual start)"
    fi

    # Check if nginx is running
    if systemctl is-active --quiet nginx; then
        echo "  - Reloading nginx configuration..."
        sudo systemctl reload nginx
        echo "  ✓ Nginx reloaded"
    fi
fi

echo ""
echo "========================================="
if [ "$INSTALL_TYPE" = "upgrade" ]; then
    echo "Upgrade completed successfully!"
else
    echo "Bootstrap completed successfully!"
fi
echo "========================================="
echo ""

if [ "$INSTALL_TYPE" = "fresh" ]; then
    echo "Next steps:"
    echo "1. Install systemd service:"
    echo "   sudo cp deploy/itdocs-gunicorn.service /etc/systemd/system/"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl enable itdocs-gunicorn"
    echo "   sudo systemctl start itdocs-gunicorn"
    echo ""
    echo "2. Install PSA sync timer (optional):"
    echo "   sudo cp deploy/itdocs-psa-sync.service /etc/systemd/system/"
    echo "   sudo cp deploy/itdocs-psa-sync.timer /etc/systemd/system/"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl enable itdocs-psa-sync.timer"
    echo "   sudo systemctl start itdocs-psa-sync.timer"
    echo ""
    echo "3. Configure Nginx:"
    echo "   sudo cp deploy/nginx-itdocs.conf /etc/nginx/sites-available/itdocs"
    echo "   sudo ln -s /etc/nginx/sites-available/itdocs /etc/nginx/sites-enabled/"
    echo "   sudo nginx -t"
    echo "   sudo systemctl reload nginx"
    echo ""
    echo "4. Access the platform at http://yourdomain.com"
else
    echo "Upgrade complete! Your services have been restarted."
    echo ""
    echo "Database backup saved to: $BACKUP_DIR/database.sql"
    echo ""
    echo "To verify the installation:"
    echo "  - Check service status: sudo systemctl status itdocs-gunicorn"
    echo "  - View logs: sudo journalctl -u itdocs-gunicorn -f"
    echo "  - Test the web interface at your configured URL"
fi
echo ""
