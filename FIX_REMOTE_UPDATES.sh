#!/bin/bash
###############################################################################
# FIX Remote System GUI Updates
# Run this script on the remote system to fix the update process
###############################################################################

echo "=========================================="
echo "Fixing Remote System GUI Updates"
echo "=========================================="
echo ""

# Step 1: Ensure we're in the right directory
if [ -d "/home/administrator/huduglue" ]; then
    cd /home/administrator/huduglue
elif [ -d "/home/administrator" ] && [ -f "/home/administrator/manage.py" ]; then
    cd /home/administrator
else
    echo "❌ ERROR: Cannot find Client St0r installation"
    exit 1
fi

echo "Working directory: $(pwd)"
echo ""

# Step 2: Clean up any modified files
echo "Cleaning up modified files..."
sudo git reset --hard HEAD
sudo git clean -fd
echo "✓ Working directory clean"
echo ""

# Step 3: Pull latest code
echo "Pulling latest updates..."
sudo git fetch origin
sudo git reset --hard origin/main
echo "✓ Code updated"
echo ""

# Step 4: Setup GUI update permissions
echo "Setting up GUI update permissions..."
if [ -f "setup_gui_updates.sh" ]; then
    chmod +x setup_gui_updates.sh
    sudo ./setup_gui_updates.sh
    echo "✓ GUI updates configured"
else
    echo "⚠️  setup_gui_updates.sh not found - may need manual configuration"
fi
echo ""

# Step 5: Install dependencies
echo "Installing dependencies..."
if [ -d "venv" ]; then
    source venv/bin/activate
    sudo venv/bin/pip install -r requirements.txt
elif [ -d "ENV" ]; then
    source ENV/bin/activate
    sudo ENV/bin/pip install -r requirements.txt
fi
echo "✓ Dependencies installed"
echo ""

# Step 6: Run migrations
echo "Running database migrations..."
if [ -d "venv" ]; then
    sudo venv/bin/python manage.py migrate --noinput
elif [ -d "ENV" ]; then
    sudo ENV/bin/python manage.py migrate --noinput
fi
echo "✓ Migrations complete"
echo ""

# Step 7: Collect static files
echo "Collecting static files..."
if [ -d "venv" ]; then
    sudo venv/bin/python manage.py collectstatic --noinput
elif [ -d "ENV" ]; then
    sudo ENV/bin/python manage.py collectstatic --noinput
fi
echo "✓ Static files collected"
echo ""

# Step 8: Restart service
echo "Restarting service..."
if systemctl is-active --quiet clientst0r-gunicorn.service; then
    sudo systemctl restart clientst0r-gunicorn.service
    echo "✓ Service restarted"
else
    echo "⚠️  Service not running as systemd - manual restart required"
fi
echo ""

echo "=========================================="
echo "✅ REMOTE SYSTEM FIXED!"
echo "=========================================="
echo ""
echo "Your system is now updated to the latest version."
echo "GUI updates will work from the web interface."
echo ""
echo "Test it:"
echo "1. Go to Settings → System Updates"
echo "2. Click 'Check for Updates'"
echo "3. Click 'Apply Update'"
echo ""
