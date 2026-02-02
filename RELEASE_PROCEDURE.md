# GitHub Release Procedure

## MANDATORY STEPS - Follow Every Time Code Changes Are Made

### Step 1: Make Code Changes
- Edit files as needed
- Test locally if possible

### Step 2: Update Version Number
**ALWAYS** update the version in `config/version.py` BEFORE committing:

```python
VERSION = 'X.Y.Z'  # Increment appropriately
VERSION_INFO = {
    'major': X,
    'minor': Y,
    'patch': Z,
    'status': 'stable',
}
```

**Version Increment Rules:**
- **Major (X.0.0):** Breaking changes, major new features
- **Minor (X.Y.0):** New features, significant changes (Issues #57, #44 fixes)
- **Patch (X.Y.Z):** Bug fixes, minor improvements, permission changes

### Step 3: Commit Code Changes
```bash
# Add all modified files
git add <files>

# Commit with descriptive message
git commit -m "vX.Y.Z - Description of changes

Detailed explanation...

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

### Step 4: Commit Version Update (if separate)
If version.py wasn't included in Step 3:
```bash
git add config/version.py
git commit -m "Update version to vX.Y.Z"
```

### Step 5: Push to GitHub
```bash
git push origin main
```

### Step 6: Create Git Tag
```bash
git tag -a vX.Y.Z -m "vX.Y.Z - Brief description"
git push origin vX.Y.Z
```

### Step 7: Create GitHub Release
```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z - Descriptive Title" \
  --notes "Release notes with:
  - What changed
  - Why it changed
  - How to upgrade
  - Related issues"
```

### Step 8: Restart Application
```bash
sudo systemctl restart huduglue-gunicorn.service
sudo systemctl status huduglue-gunicorn.service
```

### Step 9: Verify Release
```bash
# Check release is live
gh release list | head -3

# Verify it shows as "Latest"
gh release view vX.Y.Z
```

---

## Common Mistakes to Avoid

❌ **DON'T:** Push code without updating version.py
✅ **DO:** Update version.py as part of every release

❌ **DON'T:** Commit code without creating a GitHub release
✅ **DO:** Always create both a git tag AND a GitHub release

❌ **DON'T:** Forget to restart the application
✅ **DO:** Restart immediately after pushing to load new code

❌ **DON'T:** Create release without testing the workflow passes
✅ **DO:** Wait for GitHub Actions to pass or rerun if needed

---

## Quick Checklist

Before marking work complete, verify:

- [ ] Code changes committed and pushed
- [ ] `config/version.py` updated with new version
- [ ] Git tag created (vX.Y.Z)
- [ ] Git tag pushed to GitHub
- [ ] GitHub release created with release notes
- [ ] Release marked as "Latest" on GitHub
- [ ] Application restarted
- [ ] GitHub Actions workflows passing (or rerun if infrastructure error)
- [ ] User notified if relevant issues exist

---

## Example: Complete Release Flow

```bash
# 1. Make changes (already done)
# 2. Update version
vim config/version.py  # Change to 2.50.0

# 3. Commit everything together
git add .
git commit -m "v2.50.0 - Add new dashboard widget

- Add revenue tracking widget
- Fix dashboard layout issues
- Update documentation

Fixes #123

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 4. Push to GitHub
git push origin main

# 5. Create and push tag
git tag -a v2.50.0 -m "v2.50.0 - Add new dashboard widget"
git push origin v2.50.0

# 6. Create GitHub release
gh release create v2.50.0 \
  --title "v2.50.0 - Add New Dashboard Widget" \
  --notes "## What's New
- Revenue tracking widget on dashboard
- Fixed layout issues
- Updated documentation

Fixes #123"

# 7. Restart application
sudo systemctl restart huduglue-gunicorn.service

# 8. Verify
gh release list | head -1
sudo systemctl status huduglue-gunicorn.service | head -10
```

---

## System Update Detection

The HuduGlue system update checker looks for:
1. **GitHub Releases** (not just commits or tags)
2. **Latest Release** marked on GitHub
3. **Version number** from the release tag

Without all three, the system will show "Up to Date" even when code has changed.

---

## RULE: Never Skip Steps

**Every code change must go through ALL steps 1-9.**
No exceptions. No shortcuts.

This ensures:
- Users see available updates
- Version numbers are accurate
- Release notes are documented
- System can be rolled back if needed
- Proper audit trail exists
