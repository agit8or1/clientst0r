#!/bin/bash
# Auto-setup script for HuduGlue mobile app building
# This configures passwordless sudo for automatic dependency installation

set -e

echo "=========================================="
echo "HuduGlue Mobile App Build Setup"
echo "=========================================="
echo ""

# Get the current user
CURRENT_USER=$(whoami)
echo "Setting up for user: $CURRENT_USER"

# Copy sudoers file
echo "Configuring passwordless sudo for mobile app builds..."
sudo cp "$(dirname "$0")/huduglue-mobile-build-sudoers" /etc/sudoers.d/huduglue-mobile-build

# Update user in sudoers file
sudo sed -i "s/administrator/$CURRENT_USER/g" /etc/sudoers.d/huduglue-mobile-build

# Set correct permissions
sudo chmod 0440 /etc/sudoers.d/huduglue-mobile-build

# Validate sudoers syntax
if sudo visudo -c -f /etc/sudoers.d/huduglue-mobile-build; then
    echo "✓ Sudoers configuration installed successfully"
else
    echo "✗ Sudoers configuration invalid, removing..."
    sudo rm /etc/sudoers.d/huduglue-mobile-build
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
