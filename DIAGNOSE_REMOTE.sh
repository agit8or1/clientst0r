#!/bin/bash
echo "=== Remote System Diagnostic ==="
echo ""

# Find project dir
if [ -d "/home/administrator/huduglue" ]; then
    cd /home/administrator/huduglue
elif [ -d "/home/administrator" ] && [ -f "/home/administrator/manage.py" ]; then
    cd /home/administrator
else
    echo "ERROR: Project not found"
    exit 1
fi

echo "Working directory: $(pwd)"
echo ""

echo "=== Git Status ==="
git status
echo ""

echo "=== Current Commit ==="
git rev-parse HEAD
echo ""

echo "=== Version in File ==="
cat config/version.py | grep "VERSION = "
echo ""

echo "=== Version from Python ==="
if [ -d "venv" ]; then
    venv/bin/python -c "from config.version import VERSION; print(f'Python reports: {VERSION}')"
elif [ -d "ENV" ]; then
    ENV/bin/python -c "from config.version import VERSION; print(f'Python reports: {VERSION}')"
fi
echo ""

echo "=== Modified Files ==="
git diff --name-only
echo ""

echo "=== Gunicorn Process ==="
ps aux | grep '[g]unicorn' | head -3
echo ""

echo "=== Gunicorn Working Directory ==="
GPID=$(ps aux | grep '[g]unicorn.*master' | awk '{print $2}' | head -1)
if [ -n "$GPID" ]; then
    sudo ls -la /proc/$GPID/cwd 2>/dev/null || ls -la /proc/$GPID/cwd 2>/dev/null
fi
echo ""
