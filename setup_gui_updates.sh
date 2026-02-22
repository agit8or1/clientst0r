#!/bin/bash
###############################################################################
# Client St0r - Enable GUI One-Click Updates
# This script configures passwordless sudo for the web interface to apply updates
###############################################################################

set -e

echo "========================================"
echo "Client St0r - GUI Update Setup"
echo "========================================"
echo ""

# Get current user
USERNAME=$(whoami)
echo "Configuring for user: $USERNAME"
echo ""

# Create sudoers file for git and service management
SUDOERS_FILE="/etc/sudoers.d/clientst0r-gui-updates"

echo "Creating sudoers configuration..."
cat > /tmp/clientst0r-gui-updates <<EOF
# Client St0r - GUI Update Permissions
# Allow web user to pull updates and restart services

# Git operations
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git pull
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git pull *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git fetch
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git fetch *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git reset
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git reset *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git rev-parse *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/git merge-base *

# Service management
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart clientst0r-gunicorn.service
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload clientst0r-gunicorn.service
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart clientst0r-gunicorn
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl status clientst0r-gunicorn.service
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/systemd-run *

# Python/pip for package installs
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/pip
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/pip install *
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/pip3
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/pip3 install *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/pip3
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/pip3 install *

# Database migrations and management
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/python
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/python *
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/python3
$USERNAME ALL=(ALL) NOPASSWD: /home/*/venv/bin/python3 *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/python3 */manage.py migrate *
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/python3 */manage.py collectstatic *

# Package scanner (already configured separately)
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
$USERNAME ALL=(ALL) NOPASSWD: /usr/bin/apt-get upgrade -y
EOF

# Validate syntax
echo "Validating sudoers syntax..."
if ! sudo visudo -c -f /tmp/clientst0r-gui-updates; then
    echo "ERROR: Invalid sudoers syntax!"
    rm /tmp/clientst0r-gui-updates
    exit 1
fi

echo "✓ Syntax valid"

# Install sudoers file
echo "Installing sudoers file..."
sudo cp /tmp/clientst0r-gui-updates "$SUDOERS_FILE"
sudo chmod 0440 "$SUDOERS_FILE"
sudo chown root:root "$SUDOERS_FILE"
rm /tmp/clientst0r-gui-updates

echo "✓ Sudoers file installed"
echo ""

# Test sudo access
echo "Testing sudo permissions..."
if sudo -n git --version >/dev/null 2>&1; then
    echo "✓ Git: OK"
else
    echo "⚠ Git: Failed (may need to logout/login)"
fi

if sudo -n systemctl --version >/dev/null 2>&1; then
    echo "✓ Systemctl: OK"
else
    echo "⚠ Systemctl: Failed (may need to logout/login)"
fi

echo ""
echo "========================================"
echo "✓ GUI Update Setup Complete!"
echo "========================================"
echo ""
echo "You can now use the web interface to:"
echo "  • Click 'Apply Update' button"
echo "  • Updates will pull from Git automatically"
echo "  • Services will restart automatically"
echo "  • No SSH/command-line needed!"
echo ""
echo "Go to: Settings → System Updates → Click 'Apply Update'"
echo ""
