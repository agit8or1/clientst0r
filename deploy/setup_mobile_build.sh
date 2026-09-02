#!/bin/bash
# Auto-setup script for Client St0r mobile app building
# This configures passwordless sudo for automatic dependency installation

set -e

echo "=========================================="
echo "Client St0r Mobile App Build Setup"
echo "=========================================="
echo ""

# Get the current user
CURRENT_USER=$(whoami)
echo "Setting up for user: $CURRENT_USER"

# Copy sudoers file
SRC="$(dirname "$0")/clientst0r-mobile-build-sudoers"
if [ ! -f "$SRC" ]; then
    # v3.17.516: this is exactly how this broke — the template went missing and
    # the only symptom was a bare "cp: cannot stat" behind a generic
    # "[WARN] Mobile build setup failed" in the update log. Say what is wrong.
    echo "✗ Sudoers template not found: $SRC" >&2
    echo "  Mobile builds will still work wherever Node.js and npm are already" >&2
    echo "  installed; this template only grants the first-run Node bootstrap in" >&2
    echo "  core/management/commands/build_mobile_app.py." >&2
    exit 1
fi

echo "Configuring passwordless sudo for mobile app builds..."
sudo cp "$SRC" /etc/sudoers.d/clientst0r-mobile-build

# Update user in sudoers file
sudo sed -i "s/administrator/$CURRENT_USER/g" /etc/sudoers.d/clientst0r-mobile-build

# Set correct permissions
sudo chmod 0440 /etc/sudoers.d/clientst0r-mobile-build

# Validate sudoers syntax
if sudo visudo -c -f /etc/sudoers.d/clientst0r-mobile-build; then
    echo "✓ Sudoers configuration installed successfully"
else
    echo "✗ Sudoers configuration invalid, removing..."
    sudo rm /etc/sudoers.d/clientst0r-mobile-build
    exit 1
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Mobile app builds will now:"
echo "  ✓ Automatically install Node.js/npm if needed"
echo "  ✓ Install Expo CLI automatically"
echo "  ✓ Build APK/IPA files automatically"
echo ""
echo "Users can now click 'Android App' or 'iOS App' and"
echo "everything will be installed and built automatically!"
echo ""
