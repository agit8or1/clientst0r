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

DEST=/etc/sudoers.d/clientst0r-mobile-build
EXPECTED=$(sed "s/administrator/$CURRENT_USER/g" "$SRC")

# v3.17.519: this runs on every update, but the content only changes when the
# template does — and re-copying needs `sudo cp` into /etc/sudoers.d, which is
# deliberately NOT in the least-privilege ruleset (v3.17.518). Two consequences
# handled here:
#
#   1. Skip when nothing changed. /etc/sudoers.d is root-only, so the installed
#      file cannot be read (or even stat'ed) to compare against — hence a stamp
#      recording the hash of what was last installed successfully.
#   2. When the copy genuinely cannot be done, say so once and exit 0. The step
#      is optional: it grants only the first-run Node bootstrap, and mobile
#      builds work wherever Node and npm are already present. Failing every
#      update would add noise, not information.
STAMP_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/clientst0r"
STAMP="$STAMP_DIR/mobile-build-sudoers.sha256"
WANT=$(printf '%s' "$EXPECTED" | sha256sum | cut -d' ' -f1)

if [ -f "$STAMP" ] && [ "$WANT" = "$(cat "$STAMP" 2>/dev/null)" ]; then
    echo "✓ Sudoers configuration already current (unchanged since last install)"
    exit 0
fi

echo "Configuring passwordless sudo for mobile app builds..."
if ! sudo -n true 2>/dev/null; then
    echo "Note: cannot write $DEST — passwordless sudo for cp into /etc/sudoers.d"
    echo "is intentionally not granted. To enable the first-run Node bootstrap, run once:"
    echo "    sudo cp $SRC $DEST && sudo chmod 0440 $DEST"
    echo "Mobile builds work regardless wherever Node.js and npm are installed."
    exit 0
fi
sudo cp "$SRC" "$DEST"

# Update user in sudoers file
sudo sed -i "s/administrator/$CURRENT_USER/g" "$DEST"

# Set correct permissions
sudo chmod 0440 "$DEST"

# Validate sudoers syntax
if sudo visudo -c -f "$DEST"; then
    mkdir -p "$STAMP_DIR" 2>/dev/null && printf '%s' "$WANT" > "$STAMP" 2>/dev/null
    echo "✓ Sudoers configuration installed successfully"
else
    echo "✗ Sudoers configuration invalid, removing..."
    sudo rm "$DEST"
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
