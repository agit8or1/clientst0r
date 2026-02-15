#!/bin/bash
# Rebrand HuduGlue to "client st0r" for local testing
# This script does NOT commit to git - for testing only!

set -e  # Exit on error

echo "========================================="
echo "  Rebranding HuduGlue → client st0r"
echo "  LOCAL TESTING ONLY (no git commits)"
echo "========================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "manage.py" ]; then
    echo -e "${RED}Error: Must run from project root (where manage.py is)${NC}"
    exit 1
fi

# Create backup branch
echo -e "${YELLOW}Creating backup branch...${NC}"
BACKUP_BRANCH="backup-before-rebrand-$(date +%Y%m%d-%H%M%S)"
git branch "$BACKUP_BRANCH"
echo -e "${GREEN}✓ Backup branch created: $BACKUP_BRANCH${NC}"
echo ""

# Function to replace in files
replace_in_files() {
    local pattern=$1
    local replacement=$2
    local description=$3

    echo -e "${YELLOW}Replacing: $description${NC}"

    # Python files
    find . -name "*.py" -type f \
        -not -path "./venv/*" \
        -not -path "./.git/*" \
        -not -path "./staticfiles/*" \
        -not -path "./__pycache__/*" \
        -exec sed -i "s/$pattern/$replacement/g" {} + 2>/dev/null || true

    # HTML templates
    find templates/ -name "*.html" -type f \
        -exec sed -i "s/$pattern/$replacement/g" {} + 2>/dev/null || true

    # JavaScript
    find static/ -name "*.js" -type f \
        -exec sed -i "s/$pattern/$replacement/g" {} + 2>/dev/null || true

    # CSS
    find static/ -name "*.css" -type f \
        -exec sed -i "s/$pattern/$replacement/g" {} + 2>/dev/null || true

    # Markdown docs
    find . -name "*.md" -type f \
        -not -path "./venv/*" \
        -not -path "./.git/*" \
        -exec sed -i "s/$pattern/$replacement/g" {} + 2>/dev/null || true

    # Config files
    find config/ -type f \
        -exec sed -i "s/$pattern/$replacement/g" {} + 2>/dev/null || true
}

echo "Starting rebranding..."
echo ""

# Replace various case combinations
# Display name with space: "client st0r"
replace_in_files "HuduGlue" "client st0r" "Display names (with space)"

# CamelCase for class names: ClientSt0r
replace_in_files "Huduglue" "ClientSt0r" "CamelCase class names"

# lowercase no space for URLs/slugs: clientst0r
replace_in_files "huduglue" "clientst0r" "URLs and slugs (no space)"

# UPPERCASE for constants
replace_in_files "HUDUGLUE" "CLIENTST0R" "Constants (uppercase)"

# Special cases that might have been missed
echo -e "${YELLOW}Handling special cases...${NC}"

# Update base.html title tags
sed -i 's/<title>.*HuduGlue.*<\/title>/<title>client st0r<\/title>/g' templates/base.html 2>/dev/null || true

# Update footer
sed -i 's/© .* HuduGlue/© 2024-2026 client st0r/g' templates/base.html 2>/dev/null || true

# Update README title
sed -i '1s/.*/# client st0r/' README.md 2>/dev/null || true

# Update version.py comments
sed -i 's/Version information for HuduGlue/Version information for client st0r/g' config/version.py 2>/dev/null || true

echo -e "${GREEN}✓ Text replacements complete${NC}"
echo ""

# Summary of changes
echo "========================================="
echo "  REBRANDING COMPLETE"
echo "========================================="
echo ""
echo "Changed:"
echo "  • HuduGlue → client st0r (display name)"
echo "  • Huduglue → ClientSt0r (class names)"
echo "  • huduglue → clientst0r (URLs/slugs)"
echo "  • HUDUGLUE → CLIENTST0R (constants)"
echo ""
echo -e "${YELLOW}⚠️  LOGO FILES NOT CHANGED${NC}"
echo "Logo files still at: static/images/logo*.png"
echo "Replace these manually if needed"
echo ""
echo "========================================="
echo "  NEXT STEPS - LOCAL TESTING"
echo "========================================="
echo ""
echo "1. Check what changed:"
echo "   git status"
echo "   git diff | head -100"
echo ""
echo "2. Start dev server:"
echo "   python manage.py runserver"
echo ""
echo "3. Test in browser:"
echo "   http://localhost:8000"
echo "   • Check navbar/footer branding"
echo "   • Check page titles"
echo "   • Test login/registration"
echo "   • Browse different pages"
echo ""
echo "========================================="
echo "  IF TESTING SUCCEEDS"
echo "========================================="
echo ""
echo "Commit changes:"
echo "  git add -A"
echo "  git commit -m 'Rebrand to client st0r'"
echo "  git push"
echo ""
echo "========================================="
echo "  IF YOU WANT TO REVERT"
echo "========================================="
echo ""
echo "Restore from backup branch:"
echo "  git checkout $BACKUP_BRANCH"
echo "  git checkout -b main-restored"
echo "  git branch -D main"
echo "  git branch -m main"
echo ""
echo "Or use git reset (if not committed):"
echo "  git reset --hard HEAD"
echo "  git clean -fd"
echo ""
echo -e "${GREEN}Backup branch: $BACKUP_BRANCH${NC}"
echo ""
echo "Ready to test! Start dev server and browse to localhost:8000"
echo ""
