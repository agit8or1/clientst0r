# Rebranding to "Client St0r" - Testing Guide

## Quick Start

```bash
# 1. Run the rebrand script
./rebrand.sh

# 2. Start dev server
python manage.py runserver

# 3. Test in browser
# Open: http://localhost:8000
```

---

## What Gets Changed

### Text Replacements

| Original | New | Where Used |
|----------|-----|------------|
| `Client St0r` | `Client St0r` | Display names, titles, user-facing text |
| `ClientSt0r` | `ClientSt0r` | Python class names, internal code |
| `clientst0r` | `clientst0r` | URLs, slugs, database references |
| `CLIENTST0R` | `CLIENTST0R` | Constants, environment variables |

### Files Changed

- ✅ All Python files (`.py`)
- ✅ All HTML templates (`.html`)
- ✅ All JavaScript (`.js`)
- ✅ All CSS (`.css`)
- ✅ All Markdown docs (`.md`)
- ✅ Config files
- ❌ Logo images (need manual replacement)

---

## Testing Checklist

After running `./rebrand.sh` and starting dev server:

### Visual Checks
- [ ] Navbar shows "Client St0r" logo/text
- [ ] Page titles show "Client St0r" (browser tab)
- [ ] Footer shows "© 2024-2026 Client St0r"
- [ ] Login page shows correct branding
- [ ] Dashboard header

### Functional Tests
- [ ] Login still works
- [ ] Navigation works
- [ ] Pages load correctly
- [ ] No console errors (F12 → Console)
- [ ] Forms submit correctly

### Text Search
```bash
# Should return NO results (all replaced)
grep -r "Client St0r" . --exclude-dir=venv --exclude-dir=.git --exclude-dir=staticfiles | grep -v ".pyc" | grep -v "__pycache__"
```

---

## Logo Replacement (Optional)

If you want to replace the logo images:

```bash
# Current logo locations
static/images/logo.png              # Main logo (navbar)
static/images/logo-light.png        # Light theme variant
static/images/logo-dark.png         # Dark theme variant
static/images/favicon.ico           # Browser tab icon
static/images/apple-touch-icon.png  # iOS bookmark icon
```

**Recommended Sizes:**
- Main logo: 200x50px (PNG)
- Favicon: 32x32px (ICO)
- Apple touch: 180x180px (PNG)

**Quick Text Logo (Temporary):**

If you don't have logo images yet, the navbar will show "Client St0r" as text, which works fine for testing!

---

## If Everything Looks Good

```bash
# Check what changed
git status
git diff | less

# Commit the rebrand
git add -A
git commit -m "Rebrand to Client St0r

- Changed all Client St0r references to Client St0r
- Updated display names, class names, URLs
- Ready for production deployment"

# DO NOT push to GitHub yet if you want to test more
# git push
```

---

## If You Want to Revert

### Option 1: Quick Revert (Uncommitted)
```bash
./revert_rebrand.sh
```

### Option 2: Manual Revert
```bash
# Discard all uncommitted changes
git reset --hard HEAD
git clean -fd
```

### Option 3: Restore from Backup Branch
```bash
# Find your backup branch
git branch | grep backup-before-rebrand

# Restore from it
git checkout backup-before-rebrand-YYYYMMDD-HHMMSS
git checkout -b main-restored
git branch -D main
git branch -m main
```

---

## Common Issues

### "Client St0r" shows as "Client St0r" (escaped)

Some places might need manual HTML entity fixes:
```html
<!-- If you see this: -->
Client St0r

<!-- Change to: -->
Client St0r
```

### Logo not showing

The logo image files weren't changed - still shows Client St0r logo or broken image. Either:
1. Replace logo files (see above)
2. Or temporarily, the navbar will show text "Client St0r"

### Database references

The database content (documents, assets, etc.) won't change - only the application code changes. This is expected and correct.

---

## Notes About "st0r" (with zero)

The script preserves the "0" (zero) in "st0r". Case variations:
- `Client St0r` (display, with space)
- `clientst0r` (URLs, no space)
- `ClientSt0r` (class names)
- `CLIENTST0R` (constants)

This is intentional for the unique branding!

---

## When You're Ready for Production

1. **Update Production Environment Variables**
   ```bash
   # Update .env file
   PROJECT_NAME="Client St0r"
   ```

2. **Update Systemd Service** (if using)
   ```bash
   sudo systemctl stop clientst0r
   sudo mv /etc/systemd/system/clientst0r.service /etc/systemd/system/clientst0r.service
   sudo nano /etc/systemd/system/clientst0r.service
   # Update all references
   sudo systemctl daemon-reload
   sudo systemctl start clientst0r
   ```

3. **Update Nginx/Apache Config**
   ```bash
   # Update server name, paths, etc.
   sudo nano /etc/nginx/sites-available/clientst0r
   sudo systemctl reload nginx
   ```

4. **Commit and Push**
   ```bash
   git add -A
   git commit -m "Rebrand to Client St0r"
   git push
   ```

5. **Optional: Rename GitHub Repo**
   - Go to GitHub → Settings → Repository name
   - Change to "clientst0r" or "client-st0r"
   - Update local remote:
     ```bash
     git remote set-url origin https://github.com/username/clientst0r.git
     ```

---

## Support

If anything breaks during testing:
1. Check browser console for errors (F12)
2. Check Django console for errors
3. Use `./revert_rebrand.sh` to undo changes
4. The backup branch is always available

Good luck with the rebrand! 🚀
