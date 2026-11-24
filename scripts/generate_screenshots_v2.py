#!/usr/bin/env python3
"""
Screenshot Generator v2 for Clientst0r.

Captures full-page documentation screenshots of the running app via headless
Chromium + Selenium. Differences from v1:

* Authenticates by injecting a Django session cookie (no login form).
  This avoids 2FA issues entirely.
* Uses Chromium + chromedriver (snap build at /usr/bin/chromium-browser).
* Talks to the running gunicorn on http://localhost:8000 but spoofs
  X-Forwarded-Proto: https via Chrome DevTools Protocol so SECURE_SSL_REDIRECT
  is satisfied.
* Targets the v3.17.113 - 3.17.122 feature surface (PSA, workflows,
  organizations list view, system updates, etc.).
* Each page failure is logged but does not abort the whole run.

Run end-to-end:
    cd /home/administrator/.dev-worktree
    /home/administrator/venv/bin/python scripts/generate_screenshots_v2.py

Note: the production DB lives at /home/administrator/db.sqlite3 (not the
worktree's empty copy), so this script forces sys.path to the production
checkout for Django setup. Output PNGs are written to the worktree's
docs/screenshots/ directory.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

# --- Django setup against the running production checkout -------------------
# The worktree's db.sqlite3 is empty. We import models from the live
# /home/administrator checkout so user / ticket / organization lookups hit
# the same data the gunicorn process is serving.
PROD_CHECKOUT = Path('/home/administrator')
WORKTREE_ROOT = Path('/home/administrator/.dev-worktree')

sys.path.insert(0, str(PROD_CHECKOUT))
os.chdir(PROD_CHECKOUT)  # so BASE_DIR / 'db.sqlite3' resolves correctly
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.options import Options  # noqa: E402
from selenium.webdriver.chrome.service import Service  # noqa: E402

# --- Constants --------------------------------------------------------------
BASE_URL = 'http://localhost:8000'  # gunicorn HTTP; CDP injects X-Forwarded-Proto
OUTPUT_DIR = WORKTREE_ROOT / 'docs' / 'screenshots'
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080
MAX_FULL_PAGE_HEIGHT = 4000
PAGE_SETTLE_SECONDS = 2

CHROMIUM_BIN = '/usr/bin/chromium-browser'
CHROMEDRIVER_BIN = '/usr/bin/chromedriver'


class ScreenshotGenerator:
    """Drive a headless Chromium browser to capture documentation screenshots.

    Auth is performed by creating a Django Session row server-side and
    injecting the session_id cookie into the browser. SECURE_SSL_REDIRECT is
    bypassed by sending an X-Forwarded-Proto: https header on every request
    (production trusts this header per SECURE_PROXY_SSL_HEADER setting).
    """

    def __init__(self, base_url: str = BASE_URL, output_dir: Path = OUTPUT_DIR):
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.driver: webdriver.Chrome | None = None
        self.results: list[tuple[str, str, str]] = []  # (name, status, msg)

    # -- Setup --------------------------------------------------------------
    def setup_driver(self) -> None:
        opts = Options()
        opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--ignore-certificate-errors')
        opts.add_argument(f'--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}')
        opts.binary_location = CHROMIUM_BIN

        service = Service(CHROMEDRIVER_BIN)
        self.driver = webdriver.Chrome(service=service, options=opts)
        self.driver.set_page_load_timeout(45)

        # Spoof X-Forwarded-Proto so Django (with
        # SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')) considers
        # the request secure and does NOT redirect to https://localhost/.
        self.driver.execute_cdp_cmd('Network.enable', {})
        self.driver.execute_cdp_cmd(
            'Network.setExtraHTTPHeaders',
            {'headers': {'X-Forwarded-Proto': 'https'}},
        )

    def authenticate(self) -> None:
        """Create a Django session for a superuser and inject the cookie."""
        User = get_user_model()
        user = (
            User.objects.filter(username='admin', is_superuser=True).first()
            or User.objects.filter(is_superuser=True, is_active=True).first()
        )
        if user is None:
            raise RuntimeError('No superuser found - cannot authenticate')

        session = SessionStore()
        session['_auth_user_id'] = str(user.pk)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session['_auth_user_hash'] = user.get_session_auth_hash()
        session.save()
        session_key = session.session_key
        cookie_name = settings.SESSION_COOKIE_NAME

        # Visit any page first so the cookie domain is established.
        self.driver.get(f'{self.base_url}/account/login/')
        time.sleep(1)
        # Clear the previous AnonymousUser cookies just in case
        self.driver.delete_all_cookies()
        self.driver.add_cookie({
            'name': cookie_name,
            'value': session_key,
            'path': '/',
        })
        # Trigger a page load with the new cookie attached.
        self.driver.get(f'{self.base_url}/core/dashboard/')
        time.sleep(PAGE_SETTLE_SECONDS)
        print(f'[auth] logged in as {user.username} (pk={user.pk}); '
              f'session={session_key[:8]}... title="{self.driver.title}"')

    # -- Capture ------------------------------------------------------------
    def capture(self, name: str, path: str) -> None:
        """Navigate to `path` and save a full-page PNG named `<name>.png`.

        Failures are logged in self.results but never raised — we want the
        whole run to keep going even if one page 404s or times out.
        """
        target = f'{self.base_url}{path}'
        out_file = self.output_dir / f'{name}.png'
        try:
            self.driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
            self.driver.get(target)
            time.sleep(PAGE_SETTLE_SECONDS)

            # If we landed on the login page something went wrong with auth.
            cur = self.driver.current_url
            if '/account/login' in cur and '/account/login' not in path:
                msg = f'redirected to login ({cur})'
                self.results.append((name, 'failed', msg))
                print(f'  [FAIL] {name}: {msg}')
                return

            # Resize viewport to the full body height for a long screenshot.
            try:
                height = self.driver.execute_script(
                    'return Math.max('
                    'document.body.scrollHeight,'
                    'document.documentElement.scrollHeight,'
                    'document.body.offsetHeight,'
                    'document.documentElement.offsetHeight'
                    ');'
                ) or WINDOW_HEIGHT
            except Exception:
                height = WINDOW_HEIGHT
            height = max(WINDOW_HEIGHT, min(int(height) + 40, MAX_FULL_PAGE_HEIGHT))
            self.driver.set_window_size(WINDOW_WIDTH, height)
            time.sleep(0.5)

            ok = self.driver.save_screenshot(str(out_file))
            if not ok:
                self.results.append((name, 'failed', 'save_screenshot returned False'))
                print(f'  [FAIL] {name}: save_screenshot returned False')
                return

            self.results.append((name, 'ok', str(out_file)))
            print(f'  [OK]   {name} -> {out_file}')
        except Exception as exc:  # noqa: BLE001 - keep going past one bad page
            self.results.append((name, 'failed', f'{type(exc).__name__}: {exc}'))
            print(f'  [FAIL] {name}: {type(exc).__name__}: {exc}')

    # -- Lookups ------------------------------------------------------------
    @staticmethod
    def find_first_ticket_number() -> str | None:
        """Prefer a ticket with a workflow attached (process_executions)."""
        from psa.models import Ticket
        t = Ticket.objects.filter(process_executions__isnull=False).first()
        if t is None:
            t = Ticket.objects.first()
        return getattr(t, 'ticket_number', None) if t else None

    @staticmethod
    def find_first_org_id() -> int | None:
        from core.models import Organization
        org = Organization.objects.filter(is_active=True).first()
        return org.pk if org else None

    @staticmethod
    def _find_compliance_framework_slug(org_id: int) -> str | None:
        """Return a framework slug to capture for the given org.

        Prefers a framework the org is already enrolled in (so the
        screenshot shows real attestation rows). Falls back to the first
        active framework so we still capture the catalog if the org
        hasn't enrolled yet.
        """
        try:
            from compliance.models import (
                ComplianceFramework,
                OrganizationCompliance,
            )
        except Exception:
            return None
        enrolled = (
            OrganizationCompliance.objects
            .filter(organization_id=org_id)
            .select_related('framework')
            .first()
        )
        if enrolled:
            return enrolled.framework.slug
        fw = ComplianceFramework.objects.filter(active=True).first()
        return fw.slug if fw else None

    # -- Orchestration ------------------------------------------------------
    def run(self) -> None:
        ticket_number = self.find_first_ticket_number()
        org_id = self.find_first_org_id()
        print(f'[lookup] ticket_number={ticket_number} org_id={org_id}')

        pages: list[tuple[str, str]] = [
            ('dashboard', '/core/dashboard/'),
            ('psa-tickets', '/psa/'),
            ('psa-new-ticket', '/psa/new/'),
            ('psa-aging', '/psa/aging/'),
            ('psa-recurring', '/psa/recurring/'),
            ('psa-workflow-rules', '/psa/rules/'),
            ('psa-dispatch', '/psa/dispatch/'),
            ('psa-quotes', '/psa/quotes/'),
            ('psa-invoices', '/psa/invoices/'),
            ('psa-contracts', '/psa/contracts/'),
            ('organizations', '/accounts/organizations/?view=list'),
            ('organizations-grid', '/accounts/organizations/?view=grid'),
            ('processes', '/processes/'),
            ('system-updates', '/core/settings/updates/'),

            # Phase 9 (v3.17.168) — Security alert ingestion + auto-ticket
            # rules. Forms polished in v3.17.182.
            ('security-alerts-list', '/security/alerts/'),
            ('security-alerts-connections', '/security/connections/'),
            ('security-alerts-connection-new', '/security/connections/new/'),
            ('security-alerts-rules', '/security/rules/'),
            ('security-alerts-rule-new', '/security/rules/new/'),

            # Integrations forms polished in v3.17.183.
            ('integrations-unifi-new', '/integrations/unifi/create/'),
            ('integrations-m365-new', '/integrations/m365/create/'),

            # Roadmap surfaces (in-app + JSON). Annotated through v3.17.185.
            ('roadmap', '/core/roadmap/'),

            # Phase 11.3 — Dispatch heatmap (v3.17.209) and the Phase 3
            # follow-up Configurable wallboards (v3.17.211 / v3.17.212).
            ('dispatch-heatmap', '/psa/dispatch/heatmap/'),
            ('wallboards-list', '/reports/wallboards/'),
            ('wallboards-new', '/reports/wallboards/new/'),
        ]
        # Phase 41 — Compliance Frameworks & Recertification (v3.17.435–444).
        # The dashboard + checklist live under /compliance/organizations/<id>/.
        if org_id:
            pages.append((
                'compliance-org-dashboard',
                f'/compliance/organizations/{org_id}/',
            ))
            # Pick the first framework slug the org is enrolled in (or the
            # first available framework so we capture the empty-state if
            # the org isn't enrolled yet).
            fw_slug = self._find_compliance_framework_slug(org_id)
            if fw_slug:
                pages.append((
                    'compliance-checklist',
                    f'/compliance/organizations/{org_id}/{fw_slug}/',
                ))
        if ticket_number:
            pages.append(('psa-ticket-detail', f'/psa/t/{ticket_number}/'))
        else:
            self.results.append(('psa-ticket-detail', 'failed', 'no Ticket found in DB'))
            print('  [SKIP] psa-ticket-detail: no Ticket in DB')
        if org_id:
            pages.append(('psa-client-account', f'/psa/clients/{org_id}/account/'))
        else:
            self.results.append(('psa-client-account', 'failed', 'no Organization found'))
            print('  [SKIP] psa-client-account: no Organization in DB')

        for name, path in pages:
            self.capture(name, path)

    def teardown(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass

    def report(self) -> None:
        print('\n=== Screenshot results ===')
        ok = sum(1 for _, status, _ in self.results if status == 'ok')
        fail = len(self.results) - ok
        for name, status, msg in self.results:
            mark = 'OK  ' if status == 'ok' else 'FAIL'
            print(f'  [{mark}] {name}: {msg}')
        print(f'\n{ok} captured, {fail} failed, total {len(self.results)}')


def main() -> int:
    gen = ScreenshotGenerator()
    try:
        gen.setup_driver()
        gen.authenticate()
        gen.run()
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        gen.report()
        gen.teardown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
