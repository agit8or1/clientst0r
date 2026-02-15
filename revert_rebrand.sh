#!/bin/bash
# Quick revert script - undoes all uncommitted changes
# Use this if you want to go back to HuduGlue

echo "========================================="
echo "  REVERTING to HuduGlue"
echo "========================================="
echo ""

# Check for uncommitted changes
if ! git diff --quiet; then
    echo "⚠️  You have uncommitted changes"
    echo ""
    read -p "Discard all changes and revert to HuduGlue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Cancelled."
        exit 0
    fi

    echo ""
    echo "Reverting all changes..."
    git reset --hard HEAD
    git clean -fd

    echo ""
    echo "✓ Reverted to HuduGlue"
    echo ""
else
    echo "No uncommitted changes found."
    echo ""
    echo "If you committed the rebrand, use:"
    echo "  git revert HEAD"
    echo "  # or restore from backup branch"
    echo ""
fi
