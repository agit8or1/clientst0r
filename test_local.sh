#!/bin/bash
# Local development test - Get running in 60 seconds

set -e

echo "========================================="
echo "HuduGlue - Local Test"
echo "========================================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << 'EOF'
# Quick test configuration
SECRET_KEY=test-secret-key-for-local-development-only-change-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (SQLite for quick test)
DB_ENGINE=sqlite3
DB_NAME=db.sqlite3

# Encryption (generate real one for production)
APP_MASTER_KEY=dGVzdC1tYXN0ZXIta2V5LWZvci1sb2NhbC1kZXZlbG9wbWVudC1vbmx5LWNoYW5nZQ==

# File Storage
UPLOAD_ROOT=./uploads

# Security (relaxed for local test)
REQUIRE_2FA=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=False

# API Keys
API_KEY_SECRET=test-api-key-secret-for-local-development
EOF
    echo "✓ Created .env file for local testing"
else
    echo "✓ .env file exists"
fi

# Check for venv
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi

# Activate venv
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✓ Dependencies installed"

# Update settings for SQLite (for quick test)
echo ""
echo "Configuring for local test..."
if ! grep -q "sqlite3" config/settings.py.bak 2>/dev/null; then
    # Backup original settings
    cp config/settings.py config/settings.py.bak

    # Temporarily modify settings for SQLite
    cat > config/settings_local.py << 'EOFPY'
from .settings import *

# Override for local SQLite testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Disable 2FA for quick test
REQUIRE_2FA = False

# Relax security for local test
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
EOFPY
fi

# Use local settings
export DJANGO_SETTINGS_MODULE=config.settings_local

# Create uploads directory
mkdir -p uploads

# Run migrations
echo ""
echo "Running migrations..."
python manage.py migrate --verbosity 0
echo "✓ Migrations complete"

# Seed demo data
echo ""
echo "Creating demo data..."
python manage.py seed_demo
echo "✓ Demo data created"

# Collect static
echo ""
echo "Collecting static files..."
python manage.py collectstatic --noinput --verbosity 0
echo "✓ Static files collected"

echo ""
echo "========================================="
echo "✓ READY TO RUN!"
echo "========================================="
echo ""
echo "Start the server:"
echo "  python manage.py runserver"
echo ""
echo "Then visit:"
echo "  http://localhost:8000"
echo ""
echo "Login with:"
echo "  Username: admin"
echo "  Password: admin"
echo ""
echo "Note: 2FA is disabled for this local test"
echo "      For production, use proper .env and enable 2FA"
echo ""
echo "To clean up:"
echo "  rm -rf venv db.sqlite3 uploads static_collected"
echo "  git checkout config/settings.py"
echo ""
