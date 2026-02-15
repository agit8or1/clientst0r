#!/bin/bash
# Install Auto-Update System for client st0r

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "client st0r Auto-Update Installer"
echo -e "==========================================${NC}"

# Get current user
CURRENT_USER=$(whoami)
PROJECT_DIR=$(pwd)

echo "Installing auto-update system..."
echo "User: $CURRENT_USER"
echo "Project: $PROJECT_DIR"

# Create dynamic service file with actual user
cat > /tmp/clientst0r-auto-update.service << EOF
[Unit]
Description=client st0r Auto-Update Service
After=network.target

[Service]
Type=oneshot
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/scripts/auto_update.sh
StandardOutput=append:/var/log/clientst0r/auto-update.log
StandardError=append:/var/log/clientst0r/auto-update.log

# Environment
Environment="PATH=$PROJECT_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Security
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

# Copy service files
echo "Installing systemd service and timer..."
sudo cp /tmp/clientst0r-auto-update.service /etc/systemd/system/
sudo cp deploy/clientst0r-auto-update.timer /etc/systemd/system/

# Set permissions
sudo chmod 644 /etc/systemd/system/clientst0r-auto-update.service
sudo chmod 644 /etc/systemd/system/clientst0r-auto-update.timer

# Add sudo permissions for the update script
echo "Adding sudo permissions for auto-update..."
SUDOERS_FILE="/etc/sudoers.d/clientst0r-auto-update"
cat > /tmp/clientst0r-auto-update-sudoers << EOF
# Allow $CURRENT_USER to restart client st0r services without password
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-gunicorn.service
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-scheduler.service
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-psa-sync.service
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-rmm-sync.service
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-monitor.service
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl is-active clientst0r-*.service
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl status clientst0r-*.service
EOF

sudo cp /tmp/clientst0r-auto-update-sudoers "$SUDOERS_FILE"
sudo chmod 440 "$SUDOERS_FILE"
sudo visudo -c -f "$SUDOERS_FILE"

if [ $? -ne 0 ]; then
    echo "Error: Sudoers file has syntax errors. Removing..."
    sudo rm "$SUDOERS_FILE"
    exit 1
fi

# Reload systemd
echo "Reloading systemd..."
sudo systemctl daemon-reload

# Enable and start timer
echo "Enabling auto-update timer..."
sudo systemctl enable clientst0r-auto-update.timer
sudo systemctl start clientst0r-auto-update.timer

echo ""
echo -e "${GREEN}=========================================="
echo "✓ Auto-Update System Installed!"
echo -e "==========================================${NC}"
echo ""
echo "Configuration:"
echo "  • Updates check: Daily at 2 AM"
echo "  • Runs on boot: After 10 minutes"
echo "  • Log file: /var/log/clientst0r/auto-update.log"
echo ""
echo "Management Commands:"
echo "  • Check status:  sudo systemctl status clientst0r-auto-update.timer"
echo "  • View schedule: sudo systemctl list-timers clientst0r-auto-update.timer"
echo "  • Run now:       sudo systemctl start clientst0r-auto-update.service"
echo "  • View logs:     tail -f /var/log/clientst0r/auto-update.log"
echo "  • Disable:       sudo systemctl disable clientst0r-auto-update.timer"
echo ""
echo "To test the update system now:"
echo "  sudo systemctl start clientst0r-auto-update.service"
echo ""
