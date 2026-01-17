#!/bin/bash
# Fix Gunicorn service to load .env file with APP_MASTER_KEY
# This fixes the "Encryption failed: Invalid APP_MASTER_KEY format" error
# when importing demo data or creating passwords from the web UI.

set -e

SERVICE_FILE="/etc/systemd/system/huduglue-gunicorn.service"
ENV_FILE="/home/administrator/.env"

echo "🔧 Checking Gunicorn service configuration..."

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Error: $SERVICE_FILE not found"
    exit 1
fi

# Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: $ENV_FILE not found"
    echo "Please create the .env file with APP_MASTER_KEY first."
    exit 1
fi

# Check if EnvironmentFile is already configured
if grep -q "EnvironmentFile=$ENV_FILE" "$SERVICE_FILE"; then
    echo "✅ Gunicorn service already configured to load .env file"
    exit 0
fi

echo "📝 Adding EnvironmentFile to Gunicorn service..."

# Backup the service file
sudo cp "$SERVICE_FILE" "${SERVICE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
echo "✅ Backed up service file"

# Add EnvironmentFile after the PATH environment variable
sudo sed -i '/Environment="PATH=/a EnvironmentFile=/home/administrator/.env' "$SERVICE_FILE"
echo "✅ Added EnvironmentFile to service configuration"

# Reload systemd and restart Gunicorn
echo "🔄 Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "🔄 Restarting Gunicorn service..."
sudo systemctl restart huduglue-gunicorn.service

# Check if service is running
if sudo systemctl is-active --quiet huduglue-gunicorn.service; then
    echo "✅ Gunicorn service restarted successfully"
    echo ""
    echo "🎉 Fix applied! Demo data import and password encryption should now work from the web UI."
else
    echo "❌ Error: Gunicorn service failed to start"
    echo "Check logs: sudo journalctl -u huduglue-gunicorn.service -n 50"
    exit 1
fi
