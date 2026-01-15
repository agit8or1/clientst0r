#!/usr/bin/env python3
"""
Screenshot tool for HuduGlue
Takes screenshots of key pages with random backgrounds enabled
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

# Pages to screenshot
PAGES = [
    ('login', '/', 'login-page.png'),
    ('dashboard', '/dashboard/', 'dashboard.png'),
    ('about', '/about/', 'about-page.png'),
    ('assets', '/assets/', 'assets-list.png'),
    ('vault', '/vault/', 'password-vault.png'),
    ('docs', '/docs/', 'knowledge-base.png'),
    ('integrations', '/integrations/', 'integrations.png'),
    ('system_status', '/settings/system-status/', 'system-status.png'),
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
    """Login to HuduGlue"""
    print(f"Logging in as {username}...")
    driver.get(f'{BASE_URL}/')

    # Wait for login form
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.NAME, 'username'))
    )

    # Fill login form
    driver.find_element(By.NAME, 'username').send_keys(username)
    driver.find_element(By.NAME, 'password').send_keys(password)
    driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()

    # Wait for redirect
    time.sleep(3)
    print("✅ Logged in successfully")

def take_screenshot(driver, page_name, url, filename):
    """Navigate to page and take screenshot"""
    print(f"Taking screenshot: {page_name}...")

    driver.get(f'{BASE_URL}{url}')
    time.sleep(2)  # Wait for page load and background to load

    # Scroll to top
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

    # Take screenshot
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    driver.save_screenshot(filepath)
    print(f"✅ Saved: {filepath}")

def main():
    """Main screenshot workflow"""
    print("=" * 60)
    print("HuduGlue Screenshot Tool")
    print("=" * 60)

    # Get admin credentials
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first()

    if not admin:
        print("❌ No admin user found!")
        return 1

    # Note: In production, use environment variables for password
    # For demo/screenshots, using Django's password from database
    admin_username = admin.username

    # Setup driver
    driver = None
    try:
        driver = setup_driver()
        print(f"✅ Chrome driver initialized")

        # Take login page screenshot first (before login)
        print("\nTaking login page screenshot...")
        driver.get(f'{BASE_URL}/')
        time.sleep(2)
        login_path = os.path.join(SCREENSHOT_DIR, 'login-page.png')
        driver.save_screenshot(login_path)
        print(f"✅ Saved: {login_path}")

        # Login - using session token instead of password
        print("\n" + "=" * 60)
        print("Authenticating with session...")

        # Use Django session authentication
        from django.contrib.sessions.models import Session
        from django.contrib.auth.models import AnonymousUser

        # Create a session for the admin user
        driver.get(f'{BASE_URL}/accounts/login/')

        # Add Django session cookie
        from django.contrib.sessions.backends.db import SessionStore
        session = SessionStore()
        session['_auth_user_id'] = str(admin.pk)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session['_auth_user_hash'] = admin.get_session_auth_hash()
        session.create()

        # Set cookie
        driver.add_cookie({
            'name': 'sessionid',
            'value': session.session_key,
            'path': '/',
            'domain': 'localhost'
        })

        print("✅ Session authenticated")

        # Take remaining screenshots
        print("\n" + "=" * 60)
        print("Taking page screenshots...")
        print("=" * 60 + "\n")

        for page_name, url, filename in PAGES[1:]:  # Skip login page
            take_screenshot(driver, page_name, url, filename)
            time.sleep(1)

        print("\n" + "=" * 60)
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

if __name__ == '__main__':
    sys.exit(main())
