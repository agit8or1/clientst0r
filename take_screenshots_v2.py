#!/usr/bin/env python3
"""
Screenshot tool for HuduGlue v2
Takes screenshots of key pages with random backgrounds enabled
Uses proper form-based login
"""
import os
import sys
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Django setup
sys.path.insert(0, '/home/administrator')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth import get_user_model

# Configuration
BASE_URL = 'http://localhost:8000'
SCREENSHOT_DIR = '/home/administrator/screenshots'
WINDOW_SIZE = '1920,1080'

# Temporary password for screenshots
TEMP_PASSWORD = 'ScreenshotTemp123!'

# Pages to screenshot
PAGES = [
    ('login', '/', 'login-page.png', False),  # Don't login for this one
    ('dashboard', '/dashboard/', 'dashboard.png', True),
    ('about', '/about/', 'about-page.png', True),
    ('assets', '/assets/', 'assets-list.png', True),
    ('vault', '/vault/', 'password-vault.png', True),
    ('docs', '/docs/', 'knowledge-base.png', True),
    ('integrations', '/integrations/', 'integrations.png', True),
    ('system_status', '/settings/system-status/', 'system-status.png', True),
]

def setup_driver():
    """Setup headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument(f'--window-size={WINDOW_SIZE}')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--hide-scrollbars')
    chrome_options.binary_location = '/usr/bin/chromium-browser'

    service = Service('/usr/bin/chromedriver')
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def login(driver, username, password):
    """Login to HuduGlue via form"""
    print(f"\nLogging in as {username}...")
    driver.get(f'{BASE_URL}/accounts/login/')

    # Wait for login form
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'username'))
        )

        # Fill login form
        driver.find_element(By.NAME, 'username').send_keys(username)
        driver.find_element(By.NAME, 'password').send_keys(password)

        # Submit form
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()

        # Wait for redirect to dashboard
        WebDriverWait(driver, 10).until(
            EC.url_contains('/dashboard')
        )

        print("✅ Logged in successfully")
        return True

    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False

def take_screenshot(driver, page_name, url, filename):
    """Navigate to page and take screenshot"""
    print(f"\nTaking screenshot: {page_name}...")

    driver.get(f'{BASE_URL}{url}')

    # Wait for page load
    time.sleep(3)

    # Check for 404 or error
    page_source = driver.page_source.lower()
    if 'page not found' in page_source or '404' in driver.title.lower():
        print(f"⚠️  WARNING: Page appears to be 404 - {url}")
        return False

    # Scroll to top
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

    # Take screenshot
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    driver.save_screenshot(filepath)

    # Verify screenshot exists and has reasonable size
    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        if size < 5000:  # Less than 5KB is suspicious
            print(f"⚠️  WARNING: Screenshot is very small ({size} bytes)")
            return False
        print(f"✅ Saved: {filepath} ({size // 1024}KB)")
        return True
    else:
        print(f"❌ Failed to save screenshot")
        return False

def set_temp_password(username, password):
    """Set temporary password for admin user"""
    User = get_user_model()
    admin = User.objects.get(username=username)
    admin.set_password(password)
    admin.save()
    print(f"✅ Set temporary password for {username}")

def main():
    """Main screenshot workflow"""
    print("=" * 60)
    print("HuduGlue Screenshot Tool v2")
    print("=" * 60)

    # Create screenshots directory
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Get admin credentials
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()

    if not admin:
        print("❌ No admin user found!")
        return 1

    admin_username = admin.username

    # Set temporary password
    set_temp_password(admin_username, TEMP_PASSWORD)

    # Setup driver
    driver = None
    try:
        driver = setup_driver()
        print(f"✅ Chrome driver initialized")

        # Take login page screenshot first (before login)
        print("\n" + "=" * 60)
        print("Taking login page screenshot...")
        print("=" * 60)

        driver.get(f'{BASE_URL}/')
        time.sleep(2)
        login_path = os.path.join(SCREENSHOT_DIR, 'login-page.png')
        driver.save_screenshot(login_path)
        print(f"✅ Saved: {login_path}")

        # Login
        print("\n" + "=" * 60)
        print("Authenticating...")
        print("=" * 60)

        if not login(driver, admin_username, TEMP_PASSWORD):
            print("❌ Failed to login!")
            return 1

        # Take remaining screenshots
        print("\n" + "=" * 60)
        print("Taking page screenshots...")
        print("=" * 60)

        failed = []
        for page_name, url, filename, needs_login in PAGES[1:]:  # Skip login page
            success = take_screenshot(driver, page_name, url, filename)
            if not success:
                failed.append((page_name, filename))
            time.sleep(1)

        print("\n" + "=" * 60)
        if failed:
            print(f"⚠️  {len(failed)} screenshots had issues:")
            for page_name, filename in failed:
                print(f"   - {page_name} ({filename})")
        else:
            print(f"✅ All screenshots saved to: {SCREENSHOT_DIR}")
        print("=" * 60)

        return 0 if not failed else 1

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        if driver:
            driver.quit()

        # Reset admin password to original (remove temp password)
        print("\n⚠️  IMPORTANT: Reset admin password manually after reviewing screenshots!")

if __name__ == '__main__':
    sys.exit(main())
