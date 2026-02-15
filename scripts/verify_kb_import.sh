#!/bin/bash
# KB Article Import Diagnostic Script
# Run this on your test box to diagnose import issues

echo "================================================"
echo "KB Article Import Diagnostic Tool"
echo "================================================"
echo ""

# Check if running from correct directory
if [ ! -f "manage.py" ]; then
    echo "ERROR: Not in client st0r root directory!"
    echo "Please run from: /home/administrator or /var/www/clientst0r"
    exit 1
fi

echo "1. Checking Git Status..."
echo "   Current branch: $(git branch --show-current 2>/dev/null || echo 'Not a git repo')"
echo "   Latest commit: $(git log -1 --oneline 2>/dev/null || echo 'No git history')"
echo "   Current version: $(grep "VERSION = " config/version.py | cut -d"'" -f2)"
echo ""

echo "2. Checking Seed File..."
SEED_FILE="docs/management/commands/seed_professional_kb.py"
if [ ! -f "$SEED_FILE" ]; then
    echo "   ERROR: Seed file not found at $SEED_FILE"
    exit 1
fi

ARTICLE_COUNT=$(grep -c "articles.append({" "$SEED_FILE")
TITLE_COUNT=$(grep -c "'title':" "$SEED_FILE")
FILE_SIZE=$(wc -l < "$SEED_FILE")

echo "   Seed file exists: YES"
echo "   File size: $FILE_SIZE lines"
echo "   articles.append() calls: $ARTICLE_COUNT"
echo "   'title' occurrences: $TITLE_COUNT (should be $((ARTICLE_COUNT + 1)))"
echo ""

if [ "$ARTICLE_COUNT" -lt 13 ]; then
    echo "   WARNING: Expected at least 13 articles, found $ARTICLE_COUNT"
    echo "   Your seed file may be outdated. Try: git pull origin main"
fi

echo "3. Listing Articles in Seed File..."
grep "'title':" "$SEED_FILE" | grep -v "article_data" | sed "s/.*'title': '/   - /" | sed "s/',//"
echo ""

echo "4. Testing Seed Command Syntax..."
python3 -m py_compile "$SEED_FILE" 2>&1
if [ $? -eq 0 ]; then
    echo "   Syntax check: PASSED"
else
    echo "   Syntax check: FAILED"
    echo "   Run this to see error: python3 -m py_compile $SEED_FILE"
    exit 1
fi
echo ""

echo "5. Checking Database Articles..."
DB_OUTPUT=$(venv/bin/python manage.py shell -c "
from docs.models import Document
total = Document.objects.all().count()
global_count = Document.objects.filter(is_global=True).count()
org_none = Document.objects.filter(organization__isnull=True).count()
print(f'TOTAL:{total}')
print(f'GLOBAL:{global_count}')
print(f'ORG_NONE:{org_none}')
" 2>&1 | grep -E "TOTAL|GLOBAL|ORG_NONE")

echo "   $DB_OUTPUT" | tr ' ' '\n'
echo ""

GLOBAL_COUNT=$(echo "$DB_OUTPUT" | grep "GLOBAL:" | cut -d: -f2)

if [ -z "$GLOBAL_COUNT" ]; then
    echo "   ERROR: Could not query database"
    exit 1
elif [ "$GLOBAL_COUNT" -lt 24 ]; then
    echo "   WARNING: Expected 24+ global articles, found $GLOBAL_COUNT"
    echo "   Try running: venv/bin/python manage.py seed_professional_kb"
fi

echo "6. Running Seed Command (DRY RUN)..."
venv/bin/python manage.py seed_professional_kb 2>&1 | tail -20
echo ""

echo "7. Detailed Article Breakdown by Category..."
venv/bin/python manage.py shell -c "
from docs.models import Document
from django.db.models import Count

# Count by category
by_category = Document.objects.filter(is_global=True).values('category__name').annotate(count=Count('id')).order_by('category__name')

print('\nArticles by category:')
for item in by_category:
    cat = item['category__name'] or 'No Category'
    count = item['count']
    print(f'  {cat}: {count} articles')

total = Document.objects.filter(is_global=True).count()
print(f'\nTotal: {total} global articles')
" 2>&1 | grep -E "Articles|Total|:" | grep -v "INFO"
echo ""

echo "8. Checking for Missing is_global Flags..."
MISSING_FLAGS=$(venv/bin/python manage.py shell -c "
from docs.models import Document
missing = Document.objects.filter(organization__isnull=True, is_global=False).count()
print(missing)
" 2>&1 | tail -1)

echo "   Documents with organization=None but is_global=False: $MISSING_FLAGS"
if [ "$MISSING_FLAGS" != "0" ]; then
    echo "   WARNING: Found $MISSING_FLAGS articles that need is_global flag set"
    echo "   Run this to fix:"
    echo "   venv/bin/python manage.py shell -c \"from docs.models import Document; Document.objects.filter(organization__isnull=True, is_global=False).update(is_global=True, is_published=True)\""
fi
echo ""

echo "================================================"
echo "Diagnostic Summary"
echo "================================================"
echo "Seed file articles: $ARTICLE_COUNT"
echo "Database articles: $GLOBAL_COUNT"
echo ""

if [ "$GLOBAL_COUNT" -lt 24 ]; then
    echo "STATUS: ISSUE DETECTED"
    echo ""
    echo "Recommended Fix:"
    echo "1. git pull origin main"
    echo "2. venv/bin/python manage.py seed_professional_kb"
    echo "3. Run this script again to verify"
elif [ "$ARTICLE_COUNT" -lt 13 ]; then
    echo "STATUS: SEED FILE OUTDATED"
    echo ""
    echo "Recommended Fix:"
    echo "1. git pull origin main"
    echo "2. venv/bin/python manage.py seed_professional_kb"
else
    echo "STATUS: HEALTHY"
    echo "All checks passed!"
fi

echo "================================================"
