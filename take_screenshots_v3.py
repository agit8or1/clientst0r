#!/usr/bin/env python3
"""
Screenshot tool for HuduGlue v3
Takes screenshots of key pages with random backgrounds enabled
Uses simple approach with longer waits
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
from selenium.common.exceptions import TimeoutException

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
TEMP_PASSWORD = 'ScreenshotTemp123!'

# Pages to screenshot
PAGES = [
    ('dashboard', '/dashboard/', 'dashboard.png'),
    ('about', '/about/', 'about-page.png'),
    ('assets', '/assets/', 'assets-list.png'),
    ('vault', '/vault/', 'password-vault.png'),
    ('docs', '/docs/', 'knowledge-base.png'),
    ('integrations', '/integrations/', 'integrations.png'),
    ('system_status', '/settings/system-status/', 'system-status.png'),
]

def setup_driver():
    """Setup headless Chrome driver with better options"""
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')  # Use new headless mode
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument(f'--window-size={WINDOW_SIZE}')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--hide-scrollbars')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')
    chrome_options.binary_location = '/usr/bin/chromium-browser'

    service = Service('/usr/bin/chromedriver')
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(30)
    return driver

def login(driver, username, password):
    """Login to HuduGlue via form with better error handling"""
    print(f"\nLogging in as {username}...")

    try:
        driver.get(f'{BASE_URL}/account/login/')
        time.sleep(2)

        # Wait for and fill username
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'username'))
        )
        username_field.clear()
        username_field.send_keys(username)
        time.sleep(0.5)

        # Fill password
        password_field = driver.find_element(By.NAME, 'password')
        password_field.clear()
        password_field.send_keys(password)
        time.sleep(0.5)

        # Find and click submit button using JavaScript
        print("Submitting login form...")
        submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        driver.execute_script("arguments[0].click();", submit_button)

        # Wait for either dashboard or error
        time.sleep(5)

        current_url = driver.current_url
        print(f"Current URL after login: {current_url}")

        if '/dashboard' in current_url or '/accounts/setup' in current_url:
            print("✅ Logged in successfully")
            return True
        else:
            print(f"⚠️  Unexpected URL: {current_url}")
            # Check page source for error messages
            page_source = driver.page_source
            if 'invalid' in page_source.lower() or 'incorrect' in page_source.lower():
                print("❌ Invalid credentials")
            return False

    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False

def take_screenshot(driver, page_name, url, filename):
    """Navigate to page and take screenshot"""
    print(f"\nTaking screenshot: {page_name}...")

    try:
        driver.get(f'{BASE_URL}{url}')
        time.sleep(4)  # Wait longer for page to fully load

        # Check for 404 or error
        page_title = driver.title
        page_source = driver.page_source.lower()

        if 'page not found' in page_source or '404' in page_title.lower():
            print(f"⚠️  WARNING: Page appears to be 404 - {url}")
            return False

        if 'error' in page_title.lower() and 'server error' in page_source:
            print(f"⚠️  WARNING: Server error on page - {url}")
            return False

        # Scroll to top
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        # Take screenshot
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        driver.save_screenshot(filepath)

        # Verify screenshot
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            if size < 5000:
                print(f"⚠️  WARNING: Screenshot is very small ({size} bytes)")
                return False
            print(f"✅ Saved: {filepath} ({size // 1024}KB)")
            return True
        else:
            print(f"❌ Failed to save screenshot")
            return False

    except Exception as e:
        print(f"❌ Error taking screenshot: {e}")
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
    print("HuduGlue Screenshot Tool v3")
    print("=" * 60)

    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Get admin credentials
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()

    if not admin:
        print("❌ No admin user found!")
        return 1

    admin_username = admin.username
    set_temp_password(admin_username, TEMP_PASSWORD)

    driver = None
    try:
        driver = setup_driver()
        print(f"✅ Chrome driver initialized")

        # Take login page screenshot
        print("\n" + "=" * 60)
        print("Taking login page screenshot...")
        print("=" * 60)

        driver.get(f'{BASE_URL}/')
        time.sleep(3)
        login_path = os.path.join(SCREENSHOT_DIR, 'login-page.png')
        driver.save_screenshot(login_path)
        size = os.path.getsize(login_path)
        print(f"✅ Saved: {login_path} ({size // 1024}KB)")

        # Login
        print("\n" + "=" * 60)
        print("Authenticating...")
        print("=" * 60)

        if not login(driver, admin_username, TEMP_PASSWORD):
            print("❌ Failed to login!")
            print("\nDumping page source for debugging:")
            print(driver.page_source[:500])
            return 1

        # Take remaining screenshots
        print("\n" + "=" * 60)
        print("Taking page screenshots...")
        print("=" * 60)

        failed = []
        for page_name, url, filename in PAGES:
            success = take_screenshot(driver, page_name, url, filename)
            if not success:
                failed.append((page_name, filename))
            time.sleep(2)

        print("\n" + "=" * 60)
        if failed:
            print(f"⚠️  {len(failed)} screenshots had issues:")
            for page_name, filename in failed:
                print(f"   - {page_name} ({filename})")
            return 1
        else:
            print(f"✅ All screenshots saved to: {SCREENSHOT_DIR}")
            print("=" * 60)
            return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        if driver:
            driver.quit()
        print("\n⚠️  IMPORTANT: Reset admin password manually!")

if __name__ == '__main__':
    sys.exit(main())
