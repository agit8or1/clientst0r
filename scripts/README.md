# Client St0r Scripts

## Version Management

### Automated Version Tagging

**Git Hooks** (installed in `.git/hooks/`):

- **post-commit**: Automatically creates a git tag when `config/version.py` is modified
- **pre-push**: Automatically pushes unpushed version tags to GitHub before pushing commits

These hooks prevent the issue where version is bumped but the corresponding git tag is not created, which breaks the system update checker.

### Manual Version Bumping

Use the `bump_version.sh` script to bump the version and create a tag in one command:

```bash
# Bump patch version (3.9.3 → 3.9.4)
./scripts/bump_version.sh patch "Bug fixes and improvements"

# Bump minor version (3.9.3 → 3.10.0)
./scripts/bump_version.sh minor "New features: Service Vehicles module"

# Bump major version (3.9.3 → 4.0.0)
./scripts/bump_version.sh major "Breaking changes: New architecture"
```

The script will:
1. Update `config/version.py` with the new version
2. Commit the change with the provided message
3. Automatically create a tag (via post-commit hook)
4. Remind you to push (tags will be auto-pushed via pre-push hook)

Then simply:
```bash
git push origin main
```

The pre-push hook will automatically push any unpushed tags along with your commits.

## Other Scripts

### System Package Updates

Update OS packages with security patches:

```bash
# Update all packages
python manage.py update_system_packages --auto-approve

# Security updates only
python manage.py update_system_packages --auto-approve --security-only

# Dry run (preview updates)
python manage.py update_system_packages --dry-run
```

See `core/management/commands/update_system_packages.py` for details.
