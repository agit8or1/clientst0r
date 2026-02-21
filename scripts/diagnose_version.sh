#!/bin/bash
# Diagnostic script to debug version display issue

echo "==================== VERSION DIAGNOSTIC ===================="
echo ""

echo "1. GIT INFORMATION:"
echo "   Current commit:"
git log -1 --oneline
echo "   Current branch:"
git branch --show-current
echo ""

echo "2. VERSION.PY FILE:"
echo "   File content:"
cat config/version.py | grep "VERSION = "
echo "   File modification time:"
stat -c "%y" config/version.py
echo ""

echo "3. COMPILED VERSION:"
echo "   Python reports:"
source venv/bin/activate
python -c "from config.version import VERSION; print(f'   VERSION = {VERSION}')"
echo ""

echo "4. CACHED .PYC FILES:"
echo "   Checking for stale __pycache__:"
find config -name "*.pyc" -o -name "__pycache__" 2>/dev/null
echo ""

echo "5. GUNICORN WORKERS:"
echo "   Running processes:"
ps aux | grep gunicorn | grep -v grep | grep -v "diagnose" | head -5
echo ""
echo "   Service status:"
sudo systemctl status clientst0r-gunicorn.service | grep -E "(Active|Main PID)" | head -2
echo ""

echo "6. WORKER VERSION CHECK:"
echo "   What workers see:"
python manage.py shell -c "from core.updater import UpdateService; u = UpdateService(); print(f'   UpdateService reports: {u.current_version}')" 2>/dev/null
echo ""

echo "7. CACHE STATUS:"
echo "   Django cache:"
python manage.py shell -c "from django.core.cache import cache; c = cache.get('system_update_check'); print(f'   Cached version: {c.get(\"current_version\") if c else \"None\"}')  " 2>/dev/null
echo ""

echo "8. SERVICE CONFIGURATION:"
echo "   Service working directory:"
sudo systemctl cat clientst0r-gunicorn.service 2>/dev/null | grep "WorkingDirectory" || echo "   (service not found)"
echo "   Current script directory:"
pwd
echo ""

echo "9. MULTIPLE INSTALLATIONS CHECK:"
echo "   Searching for version.py files:"
find /home -name "version.py" -path "*/config/version.py" 2>/dev/null | while read file; do
    version=$(grep "VERSION = " "$file" | cut -d"'" -f2)
    echo "   $file: $version"
done
echo ""

echo "10. PYTHON MODULE PATH:"
echo "   Where Python finds config.version:"
python -c "import config.version; print(f'   {config.version.__file__}')"
echo ""

echo "==================== END DIAGNOSTIC ===================="
