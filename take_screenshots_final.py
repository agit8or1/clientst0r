#!/usr/bin/env python3
"""
Screenshot tool for HuduGlue - Final Version
Uses requests for login, then Selenium for screenshots
"""
import os
import sys
import time
import requests
from selenium import webdriver
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
TEMP_PASSWORD = 'ScreenshotTest2024!'  # Temporary for screenshots

# Pages to screenshot
PAGES = [
    ('login', '/', 'login-page.png', False),
    ('dashboard', '/core/dashboard/', 'dashboard.png', True),
    ('about', '/core/about/', 'about-page.png', True),
    ('assets', '/assets/', 'assets-list.png', True),
    ('vault', '/vault/', 'password-vault.png', True),
    ('docs', '/docs/', 'knowledge-base.png', True),
    ('integrations', '/integrations/', 'integrations.png', True),
    ('system_status', '/core/settings/system-status/', 'system-status.png', True),
]

def setup_driver():
    """Setup headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument(f'--window-size={WINDOW_SIZE}')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--hide-scrollbars')
    chrome_options.binary_location = '/usr/bin/chromium-browser'

    service = Service('/usr/bin/chromedriver')
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(30)
    return driver

def login_with_requests(username, password):
    """Login using requests library to get session cookie"""
    print(f"\nLogging in as {username} using requests...")

    session = requests.Session()

    # Get login page to retrieve CSRF token
    login_url = f'{BASE_URL}/account/login/'
    response = session.get(login_url)

    if response.status_code != 200:
        print(f"❌ Failed to access login page: {response.status_code}")
        return None

    # Extract CSRF token
    csrf_token = None
    for line in response.text.split('\n'):
        if 'csrf' in line.lower() and 'content' in line.lower():
            parts = line.split('"')
            for i, part in enumerate(parts):
                if 'csrf' in part.lower() and i + 2 < len(parts):
                    csrf_token = parts[i + 2]
                    break
            if csrf_token:
                break

    if not csrf_token:
        print("❌ Could not find CSRF token")
        return None

    print(f"Found CSRF token: {csrf_token[:20]}...")

    # Login - using correct field names for two_factor wizard
    login_data = {
        'auth-username': username,
        'auth-password': password,
        'login_view-current_step': 'auth',
        'csrfmiddlewaretoken': csrf_token,
    }

    headers = {
        'Referer': login_url,
    }

    response = session.post(login_url, data=login_data, headers=headers, allow_redirects=True)

    if response.status_code == 200 and ('/dashboard' in response.url or 'two_factor' in response.url):
        print(f"✅ Logged in successfully")
        # Return session cookie
        sessionid = session.cookies.get('sessionid')
        if sessionid:
            print(f"Got session ID: {sessionid[:20]}...")
            return sessionid
        else:
            print("⚠️  No sessionid cookie found")
            return None
    else:
        print(f"❌ Login failed. Status: {response.status_code}, URL: {response.url}")
        return None

def take_screenshot(driver, page_name, url, filename):
    """Navigate to page and take screenshot"""
    print(f"\nTaking screenshot: {page_name}...")

    try:
        driver.get(f'{BASE_URL}{url}')
        time.sleep(4)

        # Check for errors
        page_title = driver.title
        if 'not found' in page_title.lower() or '404' in page_title.lower():
            print(f"⚠️  WARNING: Page appears to be 404 - {url}")
            print(f"   Title: {page_title}")
            return False

        if 'error' in page_title.lower():
            print(f"⚠️  WARNING: Error page - {url}")
            print(f"   Title: {page_title}")
            return False

        # Scroll to top
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        # Take screenshot
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        driver.save_screenshot(filepath)

        # Verify
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            if size < 5000:
                print(f"⚠️  WARNING: Screenshot is very small ({size} bytes)")
                return False
            print(f"✅ Saved: {filepath} ({size // 1024}KB) - Title: {page_title}")
            return True
        else:
            print(f"❌ Failed to save screenshot")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def set_temp_password(username, password):
    """Set temporary password for screenshots"""
    User = get_user_model()
    admin = User.objects.get(username=username)
    admin.set_password(password)
    admin.save()
    print(f"✅ Set temporary password for screenshots")

def main():
    """Main workflow"""
    print("=" * 60)
    print("HuduGlue Screenshot Tool - Final Version")
    print("=" * 60)

    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Get admin
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()

    if not admin:
        print("❌ No admin user found!")
        return 1

    admin_username = admin.username
    set_temp_password(admin_username, TEMP_PASSWORD)

    # Login with requests to get session cookie
    print("\n" + "=" * 60)
    print("Authenticating with requests...")
    print("=" * 60)

    sessionid = login_with_requests(admin_username, TEMP_PASSWORD)

    if not sessionid:
        print("❌ Failed to login!")
        return 1

    # Setup Selenium driver
    driver = None
    try:
        driver = setup_driver()
        print(f"\n✅ Chrome driver initialized")

        # Take screenshots
        print("\n" + "=" * 60)
        print("Taking screenshots...")
        print("=" * 60)

        # Inject session cookie once at the beginning
        driver.get(f'{BASE_URL}/')
        driver.add_cookie({
            'name': 'sessionid',
            'value': sessionid,
            'path': '/',
            'domain': 'localhost',
            'secure': False,
            'httpOnly': True
        })
        print("✅ Injected session cookie")

        failed = []
        for page_name, url, filename, needs_auth in PAGES:
            # For login page, clear cookies temporarily
            if not needs_auth:
                # Save session cookie
                saved_cookies = driver.get_cookies()
                driver.delete_all_cookies()
                success = take_screenshot(driver, page_name, url, filename)
                # Restore cookies
                for cookie in saved_cookies:
                    driver.add_cookie(cookie)
            else:
                # Use existing session cookie
                success = take_screenshot(driver, page_name, url, filename)

            if not success:
                failed.append((page_name, filename))
            time.sleep(1)

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

        # Reset password back
        print("\n" + "=" * 60)
        print("Resetting admin password...")
        print("=" * 60)
        User = get_user_model()
        admin = User.objects.get(username=admin_username)
        admin.set_password('Chin00k2023###')
        admin.save()
        print("✅ Password reset to original")

if __name__ == '__main__':
    sys.exit(main())
