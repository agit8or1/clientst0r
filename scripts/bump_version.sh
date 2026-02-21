#!/bin/bash
#
# Version Bumping Script
#
# Usage:
#   ./scripts/bump_version.sh patch "Bug fixes and improvements"
#   ./scripts/bump_version.sh minor "New features added"
#   ./scripts/bump_version.sh major "Breaking changes"
#

set -e

BUMP_TYPE=${1:-patch}
COMMIT_MSG=${2:-"Version bump"}

# Get current version
CURRENT_VERSION=$(python3 -c "from config.version import VERSION; print(VERSION)")
echo "Current version: $CURRENT_VERSION"

# Parse version
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# Bump version based on type
case "$BUMP_TYPE" in
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    patch)
        PATCH=$((PATCH + 1))
        ;;
    *)
        echo "Error: Invalid bump type. Use 'major', 'minor', or 'patch'"
        exit 1
        ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
echo "New version: $NEW_VERSION"

# Update config/version.py
cat > config/version.py <<EOF
"""
Version information for Client St0r
"""

VERSION = '$NEW_VERSION'
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

echo "✓ Updated config/version.py"

# Git operations
echo ""
echo "Committing changes..."
git add config/version.py
git commit -m "Bump version to $NEW_VERSION

$COMMIT_MSG

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

echo "✓ Committed version bump"
echo ""

# Tag is automatically created by post-commit hook
echo "✓ Tag v$NEW_VERSION will be created by post-commit hook"
echo ""

# Remind to push
echo "⚠️  Remember to push changes and tags:"
echo "   git push origin main"
echo ""
echo "   (Tags will be pushed automatically by pre-push hook)"
echo ""
