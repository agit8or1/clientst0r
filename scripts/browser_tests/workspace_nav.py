#!/usr/bin/env python3
"""Browser checks for the technician shell: real server, real Chromium, isolated DB.

1. sidebar filter-as-you-type narrows the menu (nested pages included), Enter
   opens the first match, and a filter with no match runs a global search;
2. collapse to the icon rail with the button and with `[`, remembered across
   a reload; group chevrons expand and collapse;
3. keyboard shortcuts: `?` opens the help overlay (focus moves into it, Esc
   closes it), `/` focuses the global search, `g t` goes to Tickets, and
   nothing fires while typing in a field;
4. phone width (390px): no horizontal scroll, the sidebar is a drawer behind
   the bar's menu button, opens with focus in the filter, closes on Escape;
   tablet width (820px) uses the drawer too;
5. My Work renders its panels and a device link opens in context, offering
   the way back to the previous customer.

It never touches production: it refuses to run unless the database is the
isolated demo SQLite file under $DEMO_DIR, and it starts its own `runserver`
on --port against that database. The schema only is needed (no seed):

    export DEMO_DIR=/var/tmp/clientst0r-nav-demo
    export PYTHONPATH=scripts/demo:.:$HOME/.local/lib/python3.12/site-packages
    python manage.py migrate --settings=demo_settings
    DEMO_PORT=8133 python scripts/browser_tests/workspace_nav.py --port 8133

Exit status is the number of failed checks.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts' / 'demo'))
os.chdir(ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.models import Organization, SystemSetting  # noqa: E402

USERNAME = 'nav.browser'
ORG_A, ORG_B = 'NAV Alpha Freight', 'NAV Bravo Dental'


def guard_not_production() -> None:
    db = settings.DATABASES['default']
    demo_dir = os.environ.get('DEMO_DIR', '')
    if 'sqlite' not in db['ENGINE'] or not demo_dir or not str(db['NAME']).startswith(demo_dir):
        raise SystemExit(f"Refusing to run: {db['NAME']!r} is not the demo SQLite database under $DEMO_DIR.")


class Fx:
    def __init__(self):
        from accounts.models import UserProfile, UserType
        from integrations.models import RMMConnection, RMMDevice
        from psa.models import ClientPSASettings, Queue, Ticket, TicketPriority, TicketStatus, TicketType
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.monitoring_enabled = True
        s.scheduling_enabled = True
        s.save()
        User = get_user_model()
        User.objects.filter(username__startswith='nav.').delete()
        Organization.objects.filter(name__in=[ORG_A, ORG_B]).delete()
        self.a = Organization.objects.create(name=ORG_A, slug='nav-alpha-freight')
        self.b = Organization.objects.create(name=ORG_B, slug='nav-bravo-dental')
        for org in (self.a, self.b):
            ClientPSASettings.objects.update_or_create(organization=org, defaults={'enabled': True})
        # A technician (MSP staff by profile), not a superuser: the shell must
        # work for the people who use it all day.
        self.user = User.objects.create_user(USERNAME, 'nav.browser@example.test', 'not-used-nav-browser')
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.user_type = UserType.STAFF
        profile.save()
        common = dict(queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                      ticket_type=TicketType.objects.first(), status=TicketStatus.objects.get(slug='in-progress'))
        t = Ticket.objects.create(organization=self.a, subject='NAV printer jam', assigned_to=self.user, **common)
        Ticket.objects.filter(pk=t.pk).update(first_response_due_at=None,
                                              resolution_due_at=timezone.now() + timedelta(minutes=40))
        conn, _ = RMMConnection.objects.get_or_create(
            organization=self.a, name='NAV RMM', defaults={'provider_type': 'ninjaone',
                                                          'base_url': 'https://rmm.nav.example'})
        RMMDevice.objects.filter(connection=conn).delete()
        self.dev_b = RMMDevice.objects.create(organization=self.b, connection=conn, external_id='nav-b1',
                                              device_name='NAV-BRAVO-SRV', is_online=False)
        RMMDevice.objects.create(organization=self.a, connection=conn, external_id='nav-a1',
                                 device_name='NAV-ALPHA-SRV', is_online=False)

    def session(self, org) -> str:
        store = SessionStore()
        store['_auth_user_id'] = str(self.user.pk)
        store['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        store['_auth_user_hash'] = self.user.get_session_auth_hash()
        store['current_organization_id'] = org.pk
        store['2fa_prompted'] = True
        store.create()
        return store.session_key


class Run:
    def __init__(self, base, fx, browser):
        self.base, self.fx, self.browser = base, fx, browser
        self.results: list[tuple[str, bool, str]] = []

    def context(self, width=1400, height=1000, org=None, **kw):
        ctx = self.browser.new_context(viewport={'width': width, 'height': height}, **kw)
        ctx.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.fx.session(org or self.fx.a),
                          'domain': '127.0.0.1', 'path': '/'}])
        return ctx

    def check(self, name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — every failure is reported, the run goes on
            detail = f'{type(exc).__name__}: {exc}'
            self.results.append((name, False, detail))
            print(f'FAIL  {name}\n      {detail}')
            if os.environ.get('NAV_TRACE'):
                traceback.print_exc()
        else:
            self.results.append((name, True, ''))
            print(f'ok    {name}')


def expect(cond, message):
    if not cond:
        raise AssertionError(message)


def visible_entries(page):
    return page.eval_on_selector_all(
        '#appNav .app-nav__link, #appNav .app-nav__sublink',
        'els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim())')


def waits(page, js, timeout=3000):
    """True once the expression holds (animations settle at their own pace)."""
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:
        return False


# 1. Filter -------------------------------------------------------------------

def filter_narrows_and_enter_opens(run):
    page = run.context().new_page()
    page.goto(f'{run.base}/core/dashboard/')
    page.fill('#appNavFilter', 'canned')
    shown = visible_entries(page)
    # The match, with its parent entry kept for context and nothing else.
    expect('Canned Replies' in shown and set(shown) <= {'Tickets', 'Canned Replies'},
           f'filter "canned" showed {shown}')
    with page.expect_navigation():
        page.press('#appNavFilter', 'Enter')
    expect('/psa/canned' in page.url, f'Enter on "canned" opened {page.url}')
    page.goto(f'{run.base}/core/dashboard/')
    page.fill('#appNavFilter', 'dispatch')
    expect('Dispatch Board' in visible_entries(page), 'dispatch board not found by filter')
    with page.expect_navigation():
        page.press('#appNavFilter', 'Enter')
    expect(page.url.rstrip('/').endswith('/psa/dispatch'), f'Enter opened {page.url}')
    page.fill('#appNavFilter', 'NAV printer')
    expect(page.is_visible('#appNav .app-nav__empty'), 'no-match hint not shown')
    with page.expect_navigation():
        page.press('#appNavFilter', 'Enter')
    expect('/core/search/' in page.url and 'NAV' in page.content(), f'no-match Enter went to {page.url}')
    expect(page.is_visible('#search-tickets'), 'search did not list the ticket')
    page.context.close()


# 2. Collapse -----------------------------------------------------------------

def rail_collapse_is_remembered(run):
    page = run.context().new_page()
    page.goto(f'{run.base}/core/dashboard/')
    width = page.eval_on_selector('#appNav', 'e => e.getBoundingClientRect().width')
    page.click('#appNavCollapse')
    narrow = page.eval_on_selector('#appNav', 'e => e.getBoundingClientRect().width')
    expect(narrow < width / 2, f'rail not narrower: {width} -> {narrow}')
    expect(page.get_attribute('#appNavCollapse', 'aria-pressed') == 'true', 'aria-pressed not set')
    page.reload()
    again = page.eval_on_selector('#appNav', 'e => e.getBoundingClientRect().width')
    expect(again < width / 2, 'rail not remembered across reload')
    page.keyboard.press('[')
    back = page.eval_on_selector('#appNav', 'e => e.getBoundingClientRect().width')
    expect(back > width - 2, f'[ did not expand the rail: {back}')
    # Group chevron
    toggle = page.locator('.app-nav__group[data-group="clients"] .app-nav__toggle')
    toggle.click()
    expect(toggle.get_attribute('aria-expanded') == 'true', 'clients group did not expand')
    expect(page.is_visible('.app-nav__group[data-group="clients"] .app-nav__entries'), 'entries hidden')
    toggle.click()
    expect(toggle.get_attribute('aria-expanded') == 'false', 'clients group did not collapse')
    page.context.close()


# 3. Shortcuts ----------------------------------------------------------------

def shortcuts_and_help(run):
    page = run.context().new_page()
    page.goto(f'{run.base}/core/dashboard/')
    page.keyboard.press('Shift+?')
    page.wait_for_selector('#shortcutHelp.show', timeout=3000)
    expect(waits(page, "document.getElementById('shortcutHelp').contains(document.activeElement)"),
           'focus did not move into the help dialog')
    expect('g' in page.inner_text('#shortcutHelp') and 'Tickets' in page.inner_text('#shortcutHelp'),
           'help does not list the go-to shortcuts')
    page.keyboard.press('Escape')
    page.wait_for_selector('#shortcutHelp', state='hidden', timeout=3000)
    page.keyboard.press('/')
    expect(page.evaluate("document.activeElement && document.activeElement.name") == 'q',
           'slash did not focus the global search')
    # Typing a "g" in the search box must not navigate anywhere.
    page.keyboard.type('gt')
    time.sleep(0.4)
    expect('/core/dashboard' in page.url, 'shortcut fired while typing')
    page.evaluate('document.activeElement.blur()')
    with page.expect_navigation():
        page.keyboard.press('g')
        page.keyboard.press('t')
    expect(page.url.rstrip('/').endswith('/psa'), f'g t went to {page.url}')  # psa:ticket_list
    page.context.close()


# 4. Phone / tablet -------------------------------------------------------------

def phone_layout_and_drawer(run):
    ctx = run.context(width=390, height=844, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    for path in ('/core/dashboard/', '/psa/my-work/', '/psa/'):
        page.goto(f'{run.base}{path}')
        overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        expect(overflow <= 1, f'{path}: horizontal scroll of {overflow}px at 390px')
    expect(not page.is_visible('#appNav .app-nav__group-link'), 'sidebar visible without opening the drawer')
    page.click('#appNavOpen')
    page.wait_for_function("document.body.classList.contains('appnav-open')")
    expect(waits(page, "document.activeElement && document.activeElement.id === 'appNavFilter'"),
           'focus not in the drawer filter (focus on %s)' % page.evaluate(
               "document.activeElement && (document.activeElement.id || document.activeElement.tagName)"))
    expect(page.is_visible('#appNav .app-nav__group-link'), 'drawer did not show the menu')
    expect(page.get_attribute('#appNavOpen', 'aria-expanded') == 'true', 'menu button aria-expanded')
    page.keyboard.press('Escape')
    page.wait_for_function("!document.body.classList.contains('appnav-open')")
    expect(page.evaluate("document.activeElement.id") == 'appNavOpen', 'focus not returned to the menu button')
    ctx.close()
    ctx = run.context(width=820, height=1180, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/my-work/')
    expect(page.is_visible('#appNavOpen'), 'tablet width has no drawer button')
    overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    expect(overflow <= 1, f'tablet: horizontal scroll of {overflow}px')
    ctx.close()


# 5. My Work + open in context ------------------------------------------------

def my_work_open_device_in_context(run):
    page = run.context().new_page()
    page.goto(f'{run.base}/psa/my-work/?scope=all')
    expect(page.is_visible('#mw-sla'), 'SLA panel missing')
    expect(page.is_visible('#mw-devices'), 'devices panel missing')
    row = page.locator('#mw-devices .list-group-item', has_text='NAV-BRAVO-SRV')
    with page.expect_navigation():
        row.locator('a', has_text='Open device').click()
    expect('/integrations/rmm/devices/' in page.url, f'open device went to {page.url}')
    expect(page.is_visible('#workTrail'), 'no way-back trail after switching customer')
    expect(ORG_A in page.inner_text('#workTrail'), 'trail does not name the previous customer')
    with page.expect_navigation():
        page.click('#workTrail button[type="submit"]')
    expect('/psa/my-work/' in page.url, f'back went to {page.url}')
    expect(ORG_A in page.inner_text('#orgDropdown'), 'customer not restored')
    page.context.close()


CHECKS = [
    ('sidebar filter narrows, Enter opens, no match searches', filter_narrows_and_enter_opens),
    ('rail collapse button and [ remembered; group chevrons', rail_collapse_is_remembered),
    ('? help, / search, g t, no shortcuts while typing', shortcuts_and_help),
    ('phone width: no horizontal scroll, drawer, focus; tablet drawer', phone_layout_and_drawer),
    ('My Work device opens in context and returns', my_work_open_device_in_context),
]


def wait_for(url, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit(f'server at {url} did not come up')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--port', type=int, default=8133)
    ap.add_argument('--base', help='use an already-running server at this URL')
    ap.add_argument('--headed', action='store_true')
    ap.add_argument('--only', help='run checks whose name contains this text')
    args = ap.parse_args()
    guard_not_production()

    server = None
    base = args.base
    if not base:
        if args.port in (8000, 8097, 8099):
            raise SystemExit(f'port {args.port} is reserved on this host')
        base = f'http://127.0.0.1:{args.port}'
        env = dict(os.environ, DEMO_PORT=str(args.port))
        server = subprocess.Popen(
            [sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{args.port}', '--noreload',
             '--settings=demo_settings'],
            env=env, stdout=subprocess.DEVNULL,
            stderr=open(pathlib.Path(os.environ['DEMO_DIR']) / 'nav-server.log', 'w'))
    try:
        wait_for(f'{base}/health/')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            run = Run(base, None, browser)
            for name, fn in CHECKS:
                if args.only and args.only not in name:
                    continue
                run.fx = Fx()
                run.check(name, lambda fn=fn: fn(run))
            browser.close()
            failures = sum(1 for _, ok, _ in run.results if not ok)
            print(f'\n{len(run.results) - failures}/{len(run.results)} checks passed')
        return failures
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    sys.exit(main())
