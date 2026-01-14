#!/bin/bash
# Quick Fix Script for KB Article Import Issues

echo "================================================"
echo "KB Article Import Quick Fix"
echo "================================================"
echo ""

# Check if in correct directory
if [ ! -f "manage.py" ]; then
    echo "ERROR: Not in HuduGlue root directory!"
    echo "Please run from: /home/administrator or /var/www/huduglue"
    exit 1
fi

echo "Step 1: Pulling latest code from GitHub..."
git pull origin main
if [ $? -ne 0 ]; then
    echo "ERROR: Git pull failed. Check network or permissions."
    exit 1
fi
echo ""

echo "Step 2: Checking seed file integrity..."
ARTICLE_COUNT=$(grep -c "articles.append({" docs/management/commands/seed_professional_kb.py)
echo "   Found $ARTICLE_COUNT articles in seed file"

if [ "$ARTICLE_COUNT" -lt 13 ]; then
    echo "   ERROR: Seed file has too few articles ($ARTICLE_COUNT < 13)"
    echo "   The git pull may have failed or the file is corrupted."
    exit 1
fi
echo ""

echo "Step 3: Running seed command..."
venv/bin/python manage.py seed_professional_kb
echo ""

echo "Step 4: Fixing missing is_global flags..."
venv/bin/python manage.py shell -c "
from docs.models import Document
missing = Document.objects.filter(organization__isnull=True, is_global=False)
count = missing.count()
if count > 0:
    print(f'Fixing {count} articles with missing is_global flag...')
    missing.update(is_global=True, is_published=True)
    print('Fixed!')
else:
    print('No articles need fixing.')
"
echo ""

echo "Step 5: Verifying final count..."
FINAL_COUNT=$(venv/bin/python manage.py shell -c "
from docs.models import Document
print(Document.objects.filter(is_global=True).count())
" 2>&1 | tail -1)

echo "   Total global articles in database: $FINAL_COUNT"
echo ""

if [ "$FINAL_COUNT" -ge 24 ]; then
    echo "================================================"
    echo "SUCCESS! KB articles imported correctly."
    echo "Expected: 24+, Got: $FINAL_COUNT"
    echo "================================================"
else
    echo "================================================"
    echo "WARNING: Article count is lower than expected"
    echo "Expected: 24+, Got: $FINAL_COUNT"
    echo ""
    echo "Run the diagnostic script for more details:"
    echo "  ./scripts/verify_kb_import.sh"
    echo "================================================"
fi
