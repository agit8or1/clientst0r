#!/bin/bash
# Automated release script for client st0r
# Usage: ./scripts/release.sh <version> "<title>" "<notes>"
# Example: ./scripts/release.sh 2.50.0 "Add dashboard widget" "Adds revenue tracking widget"

set -e  # Exit on error

# Check arguments
if [ $# -lt 3 ]; then
    echo "Usage: $0 <version> \"<title>\" \"<release notes>\""
    echo "Example: $0 2.50.0 \"Add dashboard widget\" \"Adds new revenue tracking widget to dashboard\""
    exit 1
fi

VERSION="$1"
TITLE="$2"
NOTES="$3"

echo "=========================================="
echo "client st0r Release Process"
echo "=========================================="
echo "Version: v$VERSION"
echo "Title: $TITLE"
echo ""

# Verify we're on main branch
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ]; then
    echo "❌ Error: Must be on main branch (currently on: $BRANCH)"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "⚠️  Warning: You have uncommitted changes"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Step 1/9: Updating version in config/version.py..."
# Extract version parts
IFS='.' read -r MAJOR MINOR PATCH <<< "$VERSION"

# Update version.py
cat > config/version.py << EOF
"""
Version information for client st0r
"""

VERSION = '$VERSION'
VERSION_INFO = {
    'major': $MAJOR,
    'minor': $MINOR,
    'patch': $PATCH,
    'status': 'stable',  # alpha, beta, rc, stable
}

def get_version():
    """Return version string."""
    return VERSION

def get_version_info():
    """Return version info dict."""
    return VERSION_INFO

def get_full_version():
    """Return full version string with status."""
    status = VERSION_INFO['status']
    if status == 'stable':
        return VERSION
    return f"{VERSION}-{status}"
EOF

echo "✓ Version updated to v$VERSION"

echo "Step 2/9: Committing version update..."
git add config/version.py
git commit -m "Update version to v$VERSION" || echo "No changes to commit"
echo "✓ Version committed"

echo "Step 3/9: Pushing to GitHub..."
git push origin main
echo "✓ Pushed to GitHub"

echo "Step 4/9: Creating git tag..."
git tag -a "v$VERSION" -m "v$VERSION - $TITLE"
echo "✓ Git tag created"

echo "Step 5/9: Pushing tag to GitHub..."
git push origin "v$VERSION"
echo "✓ Tag pushed"

echo "Step 6/9: Creating GitHub release..."
gh release create "v$VERSION" \
    --title "v$VERSION - $TITLE" \
    --notes "$NOTES"
echo "✓ GitHub release created"

echo "Step 7/9: Restarting application..."
sudo systemctl restart clientst0r-gunicorn.service
sleep 3
echo "✓ Application restarted"

echo "Step 8/9: Verifying service status..."
if sudo systemctl is-active --quiet clientst0r-gunicorn.service; then
    echo "✓ Service is running"
else
    echo "❌ Service failed to start!"
    sudo systemctl status clientst0r-gunicorn.service
    exit 1
fi

echo "Step 9/9: Verifying GitHub release..."
LATEST=$(gh release list --limit 1 | head -1 | awk '{print $3}')
if [ "$LATEST" = "v$VERSION" ]; then
    echo "✓ Release v$VERSION is now Latest on GitHub"
else
    echo "⚠️  Warning: Latest release on GitHub is $LATEST, not v$VERSION"
fi

echo ""
echo "=========================================="
echo "✅ Release v$VERSION Complete!"
echo "=========================================="
echo ""
echo "Release URL: https://github.com/agit8or1/clientst0r/releases/tag/v$VERSION"
echo ""
echo "Next steps:"
echo "- Verify update appears on System Updates page"
echo "- Update any related GitHub issues"
echo "- Announce release if needed"
