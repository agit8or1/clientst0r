"""
Management command to create GitHub releases for auto-update system.
Usage: python manage.py create_github_releases --token YOUR_GITHUB_TOKEN
"""
from django.core.management.base import BaseCommand
import requests
import os


class Command(BaseCommand):
    help = 'Create GitHub releases from version tags'

    def add_arguments(self, parser):
        parser.add_argument(
            '--token',
            type=str,
            help='GitHub personal access token',
            required=False
        )
        parser.add_argument(
            '--versions',
            type=str,
            help='Comma-separated versions to release (e.g., 2.14.1,2.14.2)',
            required=False
        )

    def handle(self, *args, **options):
        # Get GitHub token
        token = options.get('token') or os.environ.get('GITHUB_TOKEN')
        if not token:
            self.stdout.write(self.style.ERROR('GitHub token required!'))
            self.stdout.write('')
            self.stdout.write('Usage:')
            self.stdout.write('  python manage.py create_github_releases --token YOUR_GITHUB_TOKEN')
            self.stdout.write('')
            self.stdout.write('Or set environment variable:')
            self.stdout.write('  export GITHUB_TOKEN=your_token_here')
            self.stdout.write('  python manage.py create_github_releases')
            self.stdout.write('')
            self.stdout.write('Get token from: https://github.com/settings/tokens')
            self.stdout.write('Required scope: repo (Full control of private repositories)')
            return

        # Define releases to create
        releases = {
            'v2.14.1': {
                'name': 'v2.14.1 - Critical Bug Fixes',
                'body': '''## 🐛 Critical Bug Fixes

### IntegrityError Fix
- **Fixed:** IntegrityError when changing admin password: "Field 'auth_source' doesn't have a default value"
- Added `default='local'` to auth_source field in UserProfile migration
- Added RunPython operation to set auth_source='local' for all existing records
- Fixed azure_ad_oid field to have proper `default=''`

### Installer & Upgrade Improvements
- **Added:** .env file validation before upgrade process starts
- **Added:** SECRET_KEY validation in .env to prevent "SECRET_KEY must be set" errors during upgrade
- **Added:** Write permission check before venv creation to prevent permission denied errors
- **Improved:** Error messages now show exact commands to fix permission issues

### Documentation
- Added comprehensive SESSION_SUMMARY.md documenting all recent work

## 🎯 What's Fixed
1. ✅ IntegrityError when changing passwords
2. ✅ SECRET_KEY errors during upgrade
3. ✅ Permission denied errors when running installer

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            },
            'v2.14.2': {
                'name': 'v2.14.2 - Encryption Error Handling',
                'body': '''## 🐛 Bug Fixes

### Encryption Key Error Handling
- Added comprehensive error handling for malformed APP_MASTER_KEY
- Display user-friendly error message with fix instructions when encryption key is invalid
- Shows exact commands to regenerate the key (44 characters, base64-encoded 32 bytes)
- Error handling added to all views that use encryption:
  - PSA integration create/edit
  - RMM integration create/edit
  - Password vault create/edit
- Prevents cryptic "Invalid base64-encoded string" errors
- Guides users to fix the issue immediately

## 📝 Error Message Example

When encountering a malformed encryption key, users now see:

```
🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed.
Please regenerate it using the following commands:

cd ~/huduglue
source venv/bin/activate
NEW_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
sed -i "s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|" .env
sudo systemctl restart huduglue-gunicorn.service

The key must be exactly 44 characters (base64-encoded 32 bytes).
```

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            },
            'v2.14.3': {
                'name': 'v2.14.3 - Role Management & User Edit Fixes',
                'body': '''## 🐛 Bug Fixes

### Role Management Access
- Fixed role management redirecting to dashboard instead of loading the page
- ADMIN role can now manage roles (previously only OWNER could)
- Updated `can_admin()` method to prioritize OWNER/ADMIN roles
- Both OWNER and ADMIN roles now have full admin privileges for role management

### User Management Redirect
- Fixed broken redirect from `'home'` (non-existent) to `'core:dashboard'`
- Affects all user management views:
  - User list, create, edit, detail
  - Password reset, add membership, delete user
  - Organization access denied
- Users now properly redirected to dashboard when lacking permissions

### Admin User Setup
- Admin user confirmed as superuser (`is_superuser=True`)
- Automatically created OWNER membership for admin user if missing
- Ensures admin has full access to manage roles and users

## 🎯 User-Reported Issues Fixed

1. ✅ "manage roles reloads dashboard" - Fixed permission check
2. ✅ "cant edit users" - Fixed redirect to non-existent 'home' route
3. ✅ "admin user should be superadmin" - Confirmed and added membership

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            },
            'v2.14.4': {
                'name': 'v2.14.4 - Member Edit IntegrityError Fix',
                'body': '''## 🐛 Bug Fixes

### Member Edit IntegrityError
- Fixed `IntegrityError: NOT NULL constraint failed: memberships.user_id` when editing members
- Root cause: MembershipForm was trying to modify the immutable `user` field during edit
- Solution: Exclude `user` and `email` fields when editing existing memberships
- User field now only appears when creating new memberships, not when editing
- Prevents accidental user reassignment which would break membership integrity

## 📝 Technical Details

**Before:** Form included 'user' field for both create and edit operations, causing NULL constraint violation when form didn't properly set user_id during edit.

**After:** Form dynamically removes 'user' and 'email' fields when `instance.pk` exists (editing), keeping them only for new memberships (creating).

## 🔧 Benefits
- ✅ No more IntegrityError when editing members
- ✅ Cleaner UI - user field only shows when adding new members
- ✅ Data integrity - prevents accidental user reassignment
- ✅ Better UX - form only shows relevant fields for each operation

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            },
            'v2.14.5': {
                'name': 'v2.14.5 - ITFlow PSA Integration',
                'body': '''## ✨ New Features

### ITFlow PSA Integration
- Added complete ITFlow provider implementation
- Fixed "Unknown provider type: itflow" error
- Supports clients, contacts, and tickets synchronization
- API authentication using X-API-KEY header
- Full CRUD operations for all supported entities
- Proper date filtering and pagination support

## 📝 ITFlow API Endpoints

- `GET /api/v1/clients` - List and sync clients (companies)
- `GET /api/v1/contacts` - List and sync contacts
- `GET /api/v1/tickets` - List and sync tickets
- `GET /api/v1/clients/{id}/contacts` - List client contacts
- `GET /api/v1/clients/{id}/tickets` - List client tickets
- Authentication: X-API-KEY header

## 🎯 How to Use

1. Go to **Integrations** → **Create New PSA Integration**
2. Select **ITFlow** from the provider dropdown
3. Enter your ITFlow configuration:
   - **Name:** Your integration name (e.g., "Production ITFlow")
   - **Base URL:** Your ITFlow instance URL (e.g., `https://itflow.yourdomain.com`)
   - **API Key:** Your ITFlow API key (from Settings → API Keys in ITFlow)
4. Configure sync options (companies, contacts, tickets)
5. Click **Create**

## 🎯 User-Reported Issue Fixed

✅ "Unknown provider type: itflow" - ITFlow provider now registered and functional

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            },
            'v2.14.6': {
                'name': 'v2.14.6 - Debug Output Removal',
                'body': '''## 🐛 Bug Fixes

### System Updates Page
- Removed debug output from System Updates page
- Cleaned up temporary debugging code added in previous version
- Improved auto-update testing workflow

## 🔧 Technical Details

- Removed debug alert box showing update_available, current_version, latest_version
- Clean interface for production auto-update feature
- Ensures clean testing of auto-update functionality

## 🎯 What's Fixed

1. ✅ Removed yellow debug warning box from System Updates page
2. ✅ Clean production-ready interface
3. ✅ Proper version bump for testing auto-update from 2.14.5 → 2.14.6

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            },
            'v2.14.7': {
                'name': 'v2.14.7 - Auto-Update Service Restart Fix',
                'body': '''## 🐛 Bug Fixes

### Auto-Update Service Restart
- Fixed service restart failing during auto-update process
- Changed service name from `huduglue` to `huduglue-gunicorn.service`
- Auto-updates now properly restart the application after code updates
- Users no longer need to manually restart after applying updates

## 🔧 Technical Details

- Fixed `_is_systemd_service()` to check correct service name
- Fixed restart command to use `huduglue-gunicorn.service`
- Update process now completes fully: git pull → pip install → migrate → collectstatic → **restart** ✅

## 🎯 What's Fixed

1. ✅ Auto-update now properly restarts Gunicorn service
2. ✅ Version updates immediately visible after update completes
3. ✅ No manual intervention required after clicking "Apply Update"
4. ✅ Complete zero-downtime update flow

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)'''
            }
        }

        # Filter versions if specified
        if options.get('versions'):
            version_list = [f'v{v.strip()}' for v in options['versions'].split(',')]
            releases = {k: v for k, v in releases.items() if k in version_list}

        # Create releases
        repo = 'agit8or1/huduglue'
        api_url = f'https://api.github.com/repos/{repo}/releases'

        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }

        created = 0
        skipped = 0
        failed = 0

        for tag, release_info in releases.items():
            self.stdout.write(f'\nCreating release {tag}...')

            # Check if release already exists
            check_url = f'https://api.github.com/repos/{repo}/releases/tags/{tag}'
            check_response = requests.get(check_url, headers=headers)

            if check_response.status_code == 200:
                self.stdout.write(self.style.WARNING(f'  ⚠ Release {tag} already exists, skipping'))
                skipped += 1
                continue

            # Create release
            data = {
                'tag_name': tag,
                'target_commitish': 'main',
                'name': release_info['name'],
                'body': release_info['body'],
                'draft': False,
                'prerelease': False
            }

            response = requests.post(api_url, json=data, headers=headers)

            if response.status_code == 201:
                release_data = response.json()
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created: {release_data["html_url"]}'))
                created += 1
            else:
                self.stdout.write(self.style.ERROR(f'  ✗ Failed: {response.status_code} - {response.text}'))
                failed += 1

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Created: {created}')
        self.stdout.write(f'Skipped: {skipped}')
        self.stdout.write(f'Failed: {failed}')
        self.stdout.write(self.style.SUCCESS('='*60))

        if created > 0:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✓ Releases created successfully!'))
            self.stdout.write('Auto-update system should now detect new versions.')
