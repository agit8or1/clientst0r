#!/bin/bash
# Bootstrap script for Ubuntu
# Installs system dependencies, creates database, sets up venv, runs migrations

set -e

echo "========================================="
echo "HuduGlue - Bootstrap"
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

echo "Step 4: Installing Python packages..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Step 5: Creating upload directory..."
sudo mkdir -p ${UPLOAD_ROOT}
sudo chown -R $(whoami):$(whoami) ${UPLOAD_ROOT}

echo "Step 6: Creating log directory..."
sudo mkdir -p /var/log/itdocs
sudo chown -R $(whoami):$(whoami) /var/log/itdocs

echo "Step 7: Running migrations..."
python manage.py migrate

echo "Step 8: Collecting static files..."
python manage.py collectstatic --noinput

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

echo ""
echo "========================================="
echo "Bootstrap completed successfully!"
echo "========================================="
echo ""
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
echo ""
