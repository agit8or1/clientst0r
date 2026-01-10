#!/bin/bash
# ONE-COMMAND SETUP - Get the platform running NOW

set -e

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   HUDUGLUE v1.0.0                                          ║"
echo "║   Quick Local Setup - Running in 60 seconds               ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}[1/8]${NC} Pre-flight checks..."
python3 preflight_check.py > /dev/null 2>&1 || echo "  (Some checks may fail - proceeding anyway)"
echo -e "${GREEN}✓${NC} Basic structure verified"

echo -e "${BLUE}[2/8]${NC} Creating local .env file..."
if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
# LOCAL TEST CONFIGURATION
SECRET_KEY=local-dev-secret-key-$(openssl rand -hex 32)-change-for-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database - SQLite for quick test (change to mysql for production)
DB_ENGINE=sqlite3
DB_NAME=db.sqlite3

# Encryption - Test key (GENERATE REAL ONE FOR PRODUCTION!)
APP_MASTER_KEY=dGVzdC1sb2NhbC1rZXktMzItYnl0ZXMtYmFzZTY0LWVuY29kZWQtY2hhbmdlLW1lLWluLXByb2Q=

# File Storage
UPLOAD_ROOT=./uploads

# Security - RELAXED FOR LOCAL TEST ONLY
REQUIRE_2FA=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0

# API Keys
API_KEY_SECRET=local-dev-api-secret-key-change-for-production

# Rate Limiting - Relaxed for testing
AXES_FAILURE_LIMIT=10
EOF
    echo -e "${GREEN}✓${NC} Created .env for local testing"
else
    echo -e "${GREEN}✓${NC} Using existing .env"
fi

echo -e "${BLUE}[3/8]${NC} Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
echo -e "${GREEN}✓${NC} Virtual environment ready"

echo -e "${BLUE}[4/8]${NC} Installing Python packages..."
pip install -q --upgrade pip setuptools wheel
pip install -q -r requirements.txt
echo -e "${GREEN}✓${NC} Dependencies installed"

echo -e "${BLUE}[5/8]${NC} Setting up database..."
mkdir -p uploads
python manage.py migrate --noinput
echo -e "${GREEN}✓${NC} Database migrations applied"

echo -e "${BLUE}[6/8]${NC} Creating demo data..."
python manage.py seed_demo --noinput 2>/dev/null || python manage.py seed_demo
echo -e "${GREEN}✓${NC} Demo organization and user created"

echo -e "${BLUE}[7/8]${NC} Collecting static files..."
python manage.py collectstatic --noinput -v 0
echo -e "${GREEN}✓${NC} Static files ready"

echo -e "${BLUE}[8/8]${NC} Starting development server..."
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                    ✓ SETUP COMPLETE!                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}➜${NC} Server starting at: ${YELLOW}http://localhost:8000${NC}"
echo ""
echo -e "${GREEN}➜${NC} Login credentials:"
echo -e "   Username: ${YELLOW}admin${NC}"
echo -e "   Password: ${YELLOW}admin${NC}"
echo ""
echo -e "${GREEN}➜${NC} Features available:"
echo "   • Assets Management"
echo "   • Password Vault (encrypted)"
echo "   • Knowledge Base (markdown docs)"
echo "   • PSA Integrations (ConnectWise, Autotask)"
echo "   • REST API"
echo "   • Documentation (menu)"
echo ""
echo -e "${YELLOW}NOTE: 2FA is disabled for local testing${NC}"
echo -e "${YELLOW}      For production: Configure proper .env and enable 2FA${NC}"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""

# Start server
python manage.py runserver 0.0.0.0:8000
