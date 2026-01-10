#!/usr/bin/env python3
"""
Screenshot Generator for HuduGlue
Automat ically captures screenshots of all pages for documentation
"""
import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Django setup
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.contrib.auth import get_user_model
from core.models import Organization
from accounts.models import Membership

User = get_user_model()

class ScreenshotGenerator:
    """Generate screenshots of all HuduGlue pages"""

    def __init__(self, base_url='http://localhost:8000', output_dir='screenshots'):
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.driver = None
        self.screenshots = []

    def setup_driver(self):
        """Initialize Chrome WebDriver"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-gpu')

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(5)

    def login(self, username='screenshot_user', password='Screenshot123!'):
        """Login to the application"""
        print(f"Logging in as {username}...")
        self.driver.get(f'{self.base_url}/accounts/login/')

        # Fill login form
        username_input = self.driver.find_element(By.NAME, 'username')
        password_input = self.driver.find_element(By.NAME, 'password')

        username_input.send_keys(username)
        password_input.send_keys(password)

        # Submit form
        password_input.submit()

        # Wait for redirect
        time.sleep(2)

    def take_screenshot(self, name, url=None, wait_for_element=None, scroll=False):
        """
        Take a screenshot of a page

        Args:
            name: Name for the screenshot file
            url: URL to navigate to (relative to base_url)
            wait_for_element: CSS selector to wait for before screenshot
            scroll: Whether to scroll to bottom before screenshot
        """
        if url:
            full_url = f'{self.base_url}{url}'
            print(f"  Navigating to {url}...")
            self.driver.get(full_url)
            time.sleep(1)

        # Wait for specific element if specified
        if wait_for_element:
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_element))
                )
            except TimeoutException:
                print(f"  Warning: Element '{wait_for_element}' not found, continuing anyway...")

        # Scroll if needed
        if scroll:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)

        # Take screenshot
        filename = f"{name}.png"
        filepath = self.output_dir / filename
        self.driver.save_screenshot(str(filepath))

        # Get page title
        title = self.driver.title

        self.screenshots.append({
            'name': name,
            'filename': filename,
            'url': url or self.driver.current_url.replace(self.base_url, ''),
            'title': title,
            'timestamp': datetime.now().isoformat(),
            'selected': False
        })

        print(f"  ✓ Screenshot saved: {filename}")

    def capture_all(self):
        """Capture screenshots of all pages"""
        print("\n" + "="*60)
        print("HuduGlue Screenshot Generator")
        print("="*60 + "\n")

        self.setup_driver()
        self.login()

        # Dashboard
        print("\n📊 Dashboard & Overview")
        self.take_screenshot('01-dashboard', '/')

        # Organizations
        print("\n🏢 Organizations")
        self.take_screenshot('02-organizations-list', '/accounts/organizations/')

        # Assets
        print("\n📦 Assets")
        self.take_screenshot('03-assets-list', '/assets/')
        self.take_screenshot('04-asset-create', '/assets/create/')

        # Passwords
        print("\n🔐 Password Vault")
        self.take_screenshot('05-passwords-list', '/vault/passwords/')
        self.take_screenshot('06-password-create', '/vault/passwords/create/')
        self.take_screenshot('07-personal-vault', '/vault/personal/')

        # Documents
        print("\n📚 Documentation")
        self.take_screenshot('08-documents-list', '/docs/documents/')
        self.take_screenshot('09-document-create', '/docs/documents/create/')
        self.take_screenshot('10-templates-list', '/docs/templates/')
        self.take_screenshot('11-global-kb', '/docs/global-kb/')

        # Contacts
        print("\n👥 Contacts")
        self.take_screenshot('12-contacts-list', '/assets/contacts/')

        # Monitoring
        print("\n🌐 Monitoring")
        self.take_screenshot('13-website-monitors', '/monitoring/websites/')
        self.take_screenshot('14-racks-list', '/monitoring/racks/')
        self.take_screenshot('15-subnets-list', '/monitoring/subnets/')

        # Integrations
        print("\n🔌 Integrations")
        self.take_screenshot('16-integrations-list', '/integrations/')

        # Users & Security
        print("\n👤 Users & Security")
        self.take_screenshot('17-users-list', '/accounts/users/')
        self.take_screenshot('18-roles-list', '/accounts/roles/')
        self.take_screenshot('19-api-keys', '/api/keys/')

        # Settings
        print("\n⚙️  Settings")
        self.take_screenshot('20-settings-general', '/core/settings/general/')
        self.take_screenshot('21-settings-security', '/core/settings/security/')
        self.take_screenshot('22-settings-smtp', '/core/settings/smtp/')
        self.take_screenshot('23-system-status', '/core/system-status/')

        # Audit
        print("\n📋 Audit Logs")
        self.take_screenshot('24-audit-logs', '/audit/')

        # Search
        print("\n🔍 Search")
        self.take_screenshot('25-search-results', '/core/search/?q=test')

        # Favorites
        print("\n⭐ Favorites")
        self.take_screenshot('26-favorites', '/core/favorites/')

        print("\n" + "="*60)
        print(f"✅ Captured {len(self.screenshots)} screenshots")
        print(f"📁 Saved to: {self.output_dir.absolute()}")
        print("="*60 + "\n")

    def save_manifest(self):
        """Save manifest file with screenshot metadata"""
        manifest_path = self.output_dir / 'manifest.json'
        with open(manifest_path, 'w') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'base_url': self.base_url,
                'total_screenshots': len(self.screenshots),
                'screenshots': self.screenshots
            }, f, indent=2)
        print(f"📄 Manifest saved: {manifest_path}")

    def cleanup(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()

    def run(self):
        """Run the screenshot generation process"""
        try:
            self.capture_all()
            self.save_manifest()
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()


def create_screenshot_user():
    """Create a test user for screenshots"""
    print("Creating screenshot user...")

    # Get or create organization
    org, _ = Organization.objects.get_or_create(
        slug='demo',
        defaults={'name': 'Demo Organization'}
    )

    # Create or get user
    user, created = User.objects.get_or_create(
        username='screenshot_user',
        defaults={
            'email': 'screenshots@huduglue.local',
            'is_active': True,
        }
    )

    if created:
        user.set_password('Screenshot123!')
        user.save()
        print(f"  ✓ Created user: screenshot_user")
    else:
        # Update password
        user.set_password('Screenshot123!')
        user.save()
        print(f"  ✓ Updated user: screenshot_user")

    # Add to organization as Owner
    membership, created = Membership.objects.get_or_create(
        user=user,
        organization=org,
        defaults={'role': 'owner'}
    )

    if created:
        print(f"  ✓ Added to organization: {org.name}")

    return user, org


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate screenshots for HuduGlue documentation')
    parser.add_argument('--url', default='http://localhost:8000', help='Base URL of the application')
    parser.add_argument('--output', default='screenshots', help='Output directory for screenshots')
    parser.add_argument('--create-user', action='store_true', help='Create screenshot user')

    args = parser.parse_args()

    if args.create_user:
        create_screenshot_user()

    generator = ScreenshotGenerator(base_url=args.url, output_dir=args.output)
    generator.run()
