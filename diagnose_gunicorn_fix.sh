#!/bin/bash
# Diagnostic script to check Gunicorn environment fix status
# Run this on remote servers that are having demo data import issues

echo "=========================================="
echo "client st0r Gunicorn Environment Diagnostic"
echo "=========================================="
echo ""

SERVICE_FILE="/etc/systemd/system/clientst0r-gunicorn.service"
# Detect install directory from this script's location (works for any username/path)
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$APP_DIR/.env"

# Check 1: Does .env file exist and have APP_MASTER_KEY?
echo "Check 1: .env file"
if [ -f "$ENV_FILE" ]; then
    echo "✅ $ENV_FILE exists"
    if grep -q "APP_MASTER_KEY=" "$ENV_FILE" 2>/dev/null; then
        echo "✅ APP_MASTER_KEY found in .env"
    else
        echo "❌ APP_MASTER_KEY NOT found in .env"
    fi
else
    echo "❌ $ENV_FILE does NOT exist"
fi
echo ""

# Check 2: Does service file exist?
echo "Check 2: Gunicorn service file"
if [ -f "$SERVICE_FILE" ]; then
    echo "✅ $SERVICE_FILE exists"
else
    echo "❌ $SERVICE_FILE does NOT exist"
    exit 1
fi
echo ""

# Check 3: Is EnvironmentFile configured?
echo "Check 3: EnvironmentFile configuration"
if sudo grep -q "EnvironmentFile=$ENV_FILE" "$SERVICE_FILE" 2>/dev/null; then
    echo "✅ EnvironmentFile IS configured in service"
    echo "   The fix has been applied!"
    echo ""
    echo "If you're still getting encryption errors, try:"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl restart clientst0r-gunicorn.service"
elif grep -q "EnvironmentFile=$ENV_FILE" "$SERVICE_FILE" 2>/dev/null; then
    echo "✅ EnvironmentFile IS configured in service"
    echo "   The fix has been applied!"
else
    echo "❌ EnvironmentFile NOT configured"
    echo "   This is why demo data import fails!"
    echo ""
    echo "Testing if we can apply the fix..."
    echo ""

    # Check 4: Test sudo permissions
    echo "Check 4: Sudo permissions"

    # Test systemctl
    if sudo -n systemctl status clientst0r-gunicorn.service >/dev/null 2>&1; then
        echo "✅ sudo systemctl works"
    else
        echo "❌ sudo systemctl needs password"
        CURRENT_USER="$(whoami)"
        echo "   Install the root helper once (v3.17.597): Settings → Updates,"
        echo "   or: sudo bash $(pwd)/deploy/root-helper/install-root-helper.sh"
        exit 1
    fi

    # Test tee to /etc/systemd/system/
    if echo "test" | sudo -n tee /etc/systemd/system/.test_permission >/dev/null 2>&1; then
        sudo rm -f /etc/systemd/system/.test_permission 2>/dev/null
        echo "✅ sudo tee to /etc/systemd/system/ works"
        echo ""
        echo "Permissions look good! Run the fix script:"
        echo "   ./scripts/fix_gunicorn_env.sh"
    else
        echo "❌ sudo tee to /etc/systemd/system/ FAILED"
        echo ""
        echo "You need to configure sudo permissions first:"
        echo ""
        CURRENT_USER="$(whoami)"
        # v3.17.597: this used to suggest granting bare systemd-run and tee onto
        # the unit file, either of which is root. Unit changes now go through
        # the root helper.
        echo "Install the root helper once: Settings → Updates,"
        echo "or: sudo bash $(pwd)/deploy/root-helper/install-root-helper.sh"
    fi
fi

echo ""
echo "=========================================="
echo "Diagnostic complete"
echo "=========================================="
