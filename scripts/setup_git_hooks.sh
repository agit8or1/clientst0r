#!/bin/bash
# Setup Git Hooks for client st0r
# This script installs git hooks that automatically restart services after updates

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIR="$REPO_ROOT/.git/hooks"

echo "🔧 Installing client st0r git hooks..."

# Create post-merge hook
cat > "$HOOK_DIR/post-merge" << 'EOF'
#!/bin/bash
# client st0r post-merge hook
# Automatically restart services after git pull

echo "🔄 Post-merge hook: Checking if restart is needed..."

# Check if Python files were changed
if git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD | grep -qE '\.(py|json|txt)$'; then
    echo "📝 Python/config files changed, restarting client st0r services..."

    # Restart the main Gunicorn service
    if systemctl is-active --quiet clientst0r-gunicorn.service; then
        echo "🔄 Restarting clientst0r-gunicorn.service..."
        sudo systemctl restart clientst0r-gunicorn.service

        if [ $? -eq 0 ]; then
            echo "✅ client st0r restarted successfully!"
        else
            echo "❌ Failed to restart client st0r service"
            exit 1
        fi
    else
        echo "⚠️  clientst0r-gunicorn.service is not running"
    fi
else
    echo "ℹ️  No Python files changed, skipping restart"
fi

echo "✅ Post-merge hook completed"
EOF

# Make the hook executable
chmod +x "$HOOK_DIR/post-merge"

echo "✅ Git hooks installed successfully!"
echo ""
echo "The following hook was installed:"
echo "  - post-merge: Automatically restarts client st0r after git pull"
echo ""
echo "Note: Ensure your user has sudo permissions to restart systemd services without password:"
echo "  sudo visudo -f /etc/sudoers.d/clientst0r"
echo "  # Add this line:"
echo "  administrator ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-gunicorn.service"
