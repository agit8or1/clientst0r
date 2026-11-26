#!/usr/bin/env python3
"""Workflow benchmarks for the section 23 usability targets (Playwright).

Drives a running Clientst0r DEMO instance through the headline technician
workflows and records, for each: the number of clicks and keystrokes, the
security steps (counted separately), the measured machine time (median of N
runs) and whether the section 23 target is met.

It only talks to the URL given with --base. Safety rules:

* No shared settings are ever saved; it never opens a settings form.
* Read-only unless --allow-writes is given. With --allow-writes it creates
  records whose names start with "UXBENCH" (tickets, customers, time entries,
  a remediation referral, a draft invoice). Run those against a COPY of the
  demo database (sqlite backup API) served on its own port, never against the
  instance other people are using.
* Refuses a non-loopback host unless --allow-remote is given.

Authentication: --cookie sessionid=<key> (a Django session created for the
demo user; the same approach scripts/capture_screenshots.py uses), or
--username/--password for the staff sign-in form.

    python scripts/ux/workflow_benchmarks.py --base http://127.0.0.1:8123 \\
        --cookie sessionid=XXXX --msp-cookie sessionid=YYYY --runs 5 \\
        --allow-writes --json workflows.json

--msp-cookie is a second session whose current organization is the MSP's own
organization (billing pages live there); without it the billing workflow is
reported as not measured.

What is measured: wall-clock time in the browser from the first user action to
the visible result (typing is instantaneous, so human typing time is NOT in
the number; the report adds an estimate separately, marked as such). Network
is loopback, so the time is server render plus browser work. Note the host
load average (printed at start and end) when quoting numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

TARGETS = {
    'W01': 'Find a customer within 5 s',
    'W02': 'Find a device within 5 s',
    'W03': 'Find a ticket within 5 s',
    'W04': 'Create a basic ticket within 15 s',
    'W05': 'Start / stop a ticket timer in one click',
    'W06': 'Reach an authorized credential in 2-3 clicks',
    'W07': 'Open a linked RMM device in one click',
    'W08': 'Review linked endpoint health in one click',
    'W09': 'Request supported remediation in three clicks (excl. approvals)',
    'W10': 'Create a customer within 2 minutes',
    'W11': 'Generate a customer health report in three clicks',
    'W12': 'Create an invoice draft from approved charges in three clicks',
    'W13': 'Return from a linked page without losing the record context',
    'W14': 'Switch configured applications in one click',
    'W15': 'Pair compatible applications within five minutes',
}
TYPING_S_PER_CHAR = 0.2   # estimate: a typical technician types about 5 characters per second
CLICK_S = 0.8             # estimate: aim + click + visual check per click


class Run:
    """Counts the user actions of one run and times it."""

    def __init__(self, page):
        self.page = page
        self.clicks = 0
        self.keys = 0           # key presses incl. chords (not typed text)
        self.chars = 0          # characters typed into fields
        self.security = 0       # extra steps that exist for security (re-auth, reason, 2FA)
        self.steps = []
        self.t0 = None
        self.marks = {}

    def start(self):
        self.t0 = time.perf_counter()

    def mark(self, name):
        self.marks[name] = round((time.perf_counter() - self.t0) * 1000)

    def click(self, target, label, **kw):
        self.clicks += 1
        self.steps.append(f'click {label}')
        (self.page.locator(target) if isinstance(target, str) else target).first.click(**kw)

    def type(self, target, text, label):
        self.chars += len(text)
        self.steps.append(f'type {len(text)} chars in {label}')
        loc = self.page.locator(target) if isinstance(target, str) else target
        loc.first.fill(text)

    def key(self, chord, label=None):
        self.keys += 1
        self.steps.append(f'key {label or chord}')
        self.page.keyboard.press(chord)

    def elapsed_ms(self):
        return round((time.perf_counter() - self.t0) * 1000)


# --------------------------------------------------------------------------- helpers

def nav_link(r: Run, href: str, label: str):
    """Reach a sidebar link: open its group if it is collapsed, then click it.
    Counts every click it takes."""
    page = r.page
    sel = f'.app-nav a[href="{href}"]'
    link = page.locator(sel).first
    if not link.is_visible():
        group = page.evaluate(
            """sel => { const a = document.querySelector(sel); const ul = a && a.closest('[id^=appNavGroup-]');
                        return ul ? ul.id.replace('appNavGroup-', '') : null }""", sel)
        if group:
            r.click(f'#appNavBtn-{group}', f'sidebar group {group}')
    if not link.is_visible():
        # a sub-link: open the parent entry
        r.click(page.locator(sel).first.locator('xpath=ancestor::li[contains(@class,"app-nav__entry")]//a[contains(@class,"app-nav__link")]').first,
                'parent entry')
    r.click(sel, f'sidebar {href}')


def palette_find(r: Run, query: str, expect_url_part: str, base: str):
    r.page.wait_for_load_state('load')
    r.start()
    r.key('Control+k', 'Ctrl+K')
    r.page.wait_for_selector('#cmdkInput', state='visible')
    r.page.fill('#cmdkInput', query)
    r.chars += len(query)
    r.steps.append(f'type {len(query)} chars in palette')
    # first result row that points at the wanted record, then Enter / click
    r.page.wait_for_selector(f'#cmdkList [href*="{expect_url_part}"], #cmdkList [data-url*="{expect_url_part}"], #cmdkList li', timeout=10000)
    # Enter takes the highlighted (first) row; if the first row is not the wanted one use ArrowDown
    r.key('Enter')
    try:
        r.page.wait_for_url(f'**{expect_url_part}**', timeout=10000)
    except PWTimeout:
        r.steps.append('FAILED: did not reach ' + expect_url_part)
        return False
    r.page.wait_for_load_state('load')
    r.mark('page_loaded')
    return True


# --------------------------------------------------------------------------- workflows

def w01(r, a):
    r.page.goto(a.base + '/core/dashboard/', wait_until='load')
    return palette_find(r, a.customer_query, f'/accounts/organizations/{a.org_id}/', a.base)


def w02(r, a):
    r.page.goto(a.base + '/core/dashboard/', wait_until='load')
    return palette_find(r, a.device_query, f'/assets/{a.asset_id}/', a.base)


def w03(r, a):
    r.page.goto(a.base + '/core/dashboard/', wait_until='load')
    return palette_find(r, a.ticket_query, f'/psa/t/{a.ticket}/', a.base)


def w04(r, a):
    """From the ticket list: New ticket, pick client, subject, Create."""
    p = r.page
    p.goto(a.base + '/psa/', wait_until='load')
    r.start()
    r.click('a[href="/psa/new/"]', 'New ticket')
    p.wait_for_selector('select[name=client]')
    r.steps.append('select client')
    r.clicks += 1
    p.select_option('select[name=client]', label=a.client_label)
    r.click('input[name=subject]', 'Subject field')
    r.type('input[name=subject]', f'UXBENCH ticket {time.time_ns() % 10**8}', 'Subject')
    r.click('button[type=submit]:has-text("Create Ticket")', 'Create Ticket')
    p.wait_for_url('**/psa/t/**')
    p.wait_for_load_state('load')
    r.mark('ticket_page_loaded')
    return '/psa/t/' in p.url


def w04b(r, a):
    """From the client workspace: 'Create ticket' button, client preselected."""
    p = r.page
    p.goto(f'{a.base}/accounts/organizations/{a.org_id}/', wait_until='load')
    r.start()
    r.click('a:has-text("Create ticket")', 'Create ticket (workspace)')
    p.wait_for_selector('input[name=subject]')
    r.click('input[name=subject]', 'Subject field')
    r.type('input[name=subject]', f'UXBENCH ticket {time.time_ns() % 10**8}', 'Subject')
    r.click('button[type=submit]:has-text("Create Ticket")', 'Create Ticket')
    p.wait_for_url('**/psa/t/**')
    p.wait_for_load_state('load')
    r.mark('ticket_page_loaded')
    return '/psa/t/' in p.url


def w05(r, a):
    p = r.page
    p.goto(f'{a.base}/psa/t/{a.ticket}/', wait_until='load')
    inline = p.locator('#ticketTimerInline')     # 113.9: compact control, no reload
    if inline.count():
        # a timer left running by an earlier run is stopped outside the measurement
        if inline.get_attribute('data-running') == '1':
            inline.locator('button').click()
            p.wait_for_selector('#ticketTimerInline[data-running="0"]')
        btn = inline.locator('button')
        box = btn.bounding_box()
        r.steps.append(f"Start timer button sits {round(box['y'])}px down the page (viewport {a.height}px); inline, no reload")
        r.start()
        r.click(btn, 'Start timer')
        p.wait_for_selector('#ticketTimerInline[data-running="1"]')
        r.mark('timer_running_visible')
        r.marks['start_ms'] = r.elapsed_ms()
        t1 = time.perf_counter()
        r.click(btn, 'Stop & log')
        p.wait_for_selector('#ticketTimerInline[data-running="0"]')
        r.marks['stop_ms'] = round((time.perf_counter() - t1) * 1000)
        return True
    # a timer left running by an earlier run is stopped outside the measurement
    if p.locator('button:has-text("Stop & log")').count():
        p.locator('button:has-text("Stop & log")').first.click()
        p.wait_for_load_state('load')
    btn = p.locator('button:has-text("Start timer")').first
    y = btn.evaluate('e => Math.round(e.getBoundingClientRect().top + window.scrollY)')
    r.steps.append(f'Start timer button sits {y}px down the page (viewport 900px)')
    r.start()
    r.click(btn, 'Start timer')
    p.wait_for_selector('text=Running')
    r.mark('timer_running_visible')
    start_ms = r.elapsed_ms()
    stop = p.locator('button:has-text("Stop & log")').first
    t1 = time.perf_counter()
    r.click(stop, 'Stop & log')
    p.wait_for_selector('button:has-text("Start timer")')
    r.marks['stop_ms'] = round((time.perf_counter() - t1) * 1000)
    r.marks['start_ms'] = start_ms
    return True


def w06(r, a):
    p = r.page
    p.goto(f'{a.base}/psa/t/{a.ticket}/', wait_until='load')
    r.start()
    with p.context.expect_page() as pi:
        r.click(f'a[href="/vault/{a.password_id}/"]', 'credential link on ticket (opens a new tab)')
    v = pi.value
    v.wait_for_load_state('load')
    r.page = v
    r.mark('credential_page_loaded')
    r.click('#reveal-btn', 'Reveal')
    v.wait_for_function("() => document.querySelector('#password-field') && document.querySelector('#password-field').type === 'text'", timeout=10000)
    r.mark('secret_visible')
    ok = True
    v.close()
    r.page = p
    return ok


def w07(r, a):
    p = r.page
    p.goto(f'{a.base}/psa/t/{a.ticket}/', wait_until='load')
    seen = []
    p.context.route('**/*', lambda route: (seen.append(route.request.url), route.abort()) if 'example' in urlparse(route.request.url).hostname else route.continue_())
    link = p.locator('a:has-text("Open in "):visible').first
    r.start()
    with p.context.expect_page() as pi:
        r.click(link, 'Open in <RMM> link')
    pg = pi.value
    try:
        pg.wait_for_load_state('commit', timeout=5000)
    except PWTimeout:
        pass
    r.mark('new_tab_requested')
    target = link.get_attribute('href')
    r.steps.append(f'link target {urlparse(target).scheme}://{urlparse(target).hostname} (peer host is an invented .example name; request blocked by the harness)')
    pg.close()
    p.context.unroute('**/*')
    return bool(seen)


def w08(r, a):
    """Endpoint health for the customer: client workspace -> RMM tab."""
    p = r.page
    p.goto(f'{a.base}/accounts/organizations/{a.org_id}/', wait_until='load')
    r.start()
    r.click('a[href$="?tab=rmm"]:has-text("RMM")', 'RMM tab')
    p.wait_for_url('**tab=rmm**')
    p.wait_for_load_state('load')
    r.mark('rmm_tab_loaded')
    r.steps.append('health columns visible: ' + str(p.locator('main :text-matches("stale|online|offline|last seen|check-in", "i")').count()) + ' status mentions')
    return True


def w09(r, a):
    p = r.page
    p.goto(f'{a.base}/psa/t/{a.ticket}/', wait_until='load')
    r.start()
    r.click('summary:has-text("Refer a fix")', 'open "Refer a fix for the RMM to approve"')
    form = 'form:has(select[name=risk])'
    r.click(f'{form} input[name=title]', 'title field')
    r.type(f'{form} input[name=title]', f'UXBENCH clear cache {time.time_ns() % 10**8}', 'title')
    r.key('Tab')   # title -> description (the form refuses an empty description)
    r.type(f'{form} textarea[name=description]', 'UXBENCH: clear the image cache, keep 7 days', 'description')
    sub = p.locator(f'{form} button[data-rmm-action=fix]').first
    r.click(sub, 'submit referral')
    p.wait_for_load_state('load')
    r.mark('result_page_loaded')
    ok = p.locator('text=UXBENCH clear cache').count() > 0
    r.steps.append('referral listed after submit: ' + str(ok) + '; approval happens in the RMM and is excluded')
    return ok


def w10(r, a):
    p = r.page
    p.goto(a.base + '/accounts/organizations/', wait_until='load')
    r.start()
    r.click('a[href="/accounts/organizations/create/"]', 'Create Organization')
    p.wait_for_selector('input[name=name]')
    r.click('input[name=name]', 'Name field')
    n = time.time_ns() % 10**8
    r.type('input[name=name]', f'UXBENCH Customer {n}', 'name')
    r.click('button[type=submit]:has-text("Create Organization")', 'Create Organization')
    p.wait_for_load_state('load')
    r.mark('after_submit')
    return '/create/' not in p.url


def w10b(r, a):
    """The same, with the fields a real onboarding fills in (12 fields)."""
    p = r.page
    p.goto(a.base + '/accounts/organizations/create/', wait_until='load')
    r.start()
    n = time.time_ns() % 10**8
    fields = [('name', f'UXBENCH Customer {n}'), ('legal_name', f'UXBENCH Customer {n} LLC'), ('street_address', '1 Test Way'),
              ('city', 'Testville'), ('state', 'CO'), ('postal_code', '80000'), ('phone', '555 0100'),
              ('email', 'office@uxbench.example'), ('website', 'https://uxbench.example'),
              ('primary_contact_name', 'Pat Example'), ('primary_contact_email', 'pat@uxbench.example'),
              ('primary_contact_phone', '555 0101')]
    for name, val in fields:
        r.click(f'input[name={name}]', name)
        r.type(f'input[name={name}]', val, name)
    p.select_option('select[name=organization_type]', index=1)
    r.clicks += 1
    r.click('button[type=submit]:has-text("Create Organization")', 'Create Organization')
    p.wait_for_load_state('load')
    r.mark('after_submit')
    return '/create/' not in p.url


def w11(r, a):
    p = r.page
    p.goto(a.base + '/core/dashboard/', wait_until='load')
    r.start()
    nav_link(r, '/client-health/', 'Client Health')
    p.wait_for_url('**/client-health/')
    p.wait_for_load_state('load')
    r.mark('health_list_loaded')
    r.click(f'a[href="/client-health/{a.org_id}/"]', 'customer row')
    p.wait_for_url(f'**/client-health/{a.org_id}/')
    p.wait_for_load_state('load')
    r.mark('health_report_loaded')
    return True


def w12(r, a):
    if not a.msp_cookie:
        r.steps.append('needs --msp-cookie')
        return None
    p = r.page
    import re as _re

    def invoice_count():
        html = p.context.request.get(a.base + '/psa/invoices/').text()
        return len(set(_re.findall(r'href="/psa/invoices/(\d+)/"', html)))

    before = invoice_count()
    p.goto(a.base + '/core/dashboard/', wait_until='load')
    confirms = []
    p.on('dialog', lambda d: (confirms.append(d.message[:60]), d.accept()))
    r.start()
    nav_link(r, '/psa/billing-review/', 'Billing Review')
    p.wait_for_url('**/billing-review/**')
    p.wait_for_load_state('load')
    r.mark('billing_review_loaded')
    boxes = p.locator('input[name=ticket]')
    if boxes.count() == 0:
        r.steps.append('no approved charges left to invoice (single-use data)')
        return None
    first = boxes.first
    r.click(first, 'tick one ticket (its time lines are not ticked by this; the server takes the ticket)')
    btn = first.locator('xpath=ancestor::form[1]').locator('button:has-text("Create draft invoices for selected")')
    r.click(btn, 'Create draft invoices for selected')
    p.wait_for_load_state('load')
    r.mark('after_draft')
    r.steps.append(f'confirmation dialog shown {len(confirms)} time(s), accepted (one more click, not counted above): {confirms[:1]}')
    r.steps.append('landed on ' + p.url.replace(a.base, ''))
    after = invoice_count()
    r.steps.append(f'invoices listed before/after: {before}/{after}')
    return after > before


def w13(r, a):
    p = r.page
    p.goto(f'{a.base}/psa/t/{a.ticket}/', wait_until='load')
    r.start()
    r.click(f'a[href^="/assets/{a.device_asset_id}/workspace/?device="]', 'Workspace link on ticket')
    p.wait_for_url('**/workspace/**')
    p.wait_for_load_state('load')
    r.mark('device_workspace_loaded')
    back = p.locator(f'a:has-text("Back to {a.ticket}")').first
    r.click(back, f'Back to {a.ticket}')
    p.wait_for_url(f'**/psa/t/{a.ticket}/**')
    p.wait_for_load_state('load')
    r.mark('back_on_ticket')
    r.steps.append('returned to ' + p.url.replace(a.base, ''))
    return '#ticket-rmm-panel' in p.url


def w14(r, a):
    r.steps.append('no application switcher control found in templates/base.html or the topbar; AGIT8OR_CONNECT_ENABLED is off on the demo')
    return None


def w15(r, a):
    r.steps.append('Connected Applications page returns 404 on the demo (AGIT8OR_CONNECT_ENABLED off) and needs a second application')
    return None


WORKFLOWS = [
    ('W01', 'Find a customer (palette)', w01, False),
    ('W02', 'Find a device (palette)', w02, False),
    ('W03', 'Find a ticket (palette)', w03, False),
    ('W04', 'Create a basic ticket, from the ticket list', w04, True),
    ('W04', 'Create a basic ticket, from the client workspace', w04b, True),
    ('W05', 'Start and stop a ticket timer', w05, True),
    ('W06', 'Reveal a credential from a ticket', w06, False),
    ('W07', 'Open the linked RMM device from a ticket', w07, False),
    ('W08', 'Review endpoint health for a customer', w08, False),
    ('W09', 'Request a remediation referral from a ticket', w09, True),
    ('W11', 'Customer health report from the dashboard', w11, False),
    ('W12', 'Invoice draft from approved charges', w12, True),
    ('W13', 'Return from the device workspace to the ticket', w13, False),
    # Last of the writers: creating a customer makes it the session's current client (observed),
    # which would put later workflows in the wrong client.
    ('W10', 'Create a customer, name only', w10, True),
    ('W10', 'Create a customer, 12 fields', w10b, True),
    ('W14', 'Switch application', w14, False),
    ('W15', 'Pair applications', w15, False),
]


def cookie_dict(base, raw):
    name, _, val = raw.partition('=')
    return {'name': name, 'value': val, 'url': base}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', required=True, help='demo instance URL, e.g. http://127.0.0.1:8123')
    ap.add_argument('--cookie', help='sessionid=<key> for the technician (current client: the customer below)')
    ap.add_argument('--msp-cookie', help='sessionid=<key> for the same user with the MSP organization selected')
    ap.add_argument('--username')
    ap.add_argument('--password')
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--only', help='comma list of workflow ids, e.g. W01,W05')
    ap.add_argument('--allow-writes', action='store_true', help='run workflows that create UXBENCH records')
    ap.add_argument('--allow-remote', action='store_true')
    ap.add_argument('--json')
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--height', type=int, default=900)
    # demo record identifiers (defaults match the seeded demo)
    ap.add_argument('--org-id', type=int, default=3)
    ap.add_argument('--client-label', default='Ridgeline Dental Group')
    ap.add_argument('--customer-query', default='Ridgeline')
    ap.add_argument('--asset-id', type=int, default=17)
    ap.add_argument('--device-query', default='RDG-OP3')
    ap.add_argument('--ticket', default='PSA-2026-000036')
    ap.add_argument('--ticket-query', default='Operatory 3 PC')
    ap.add_argument('--password-id', type=int, default=25)
    ap.add_argument('--device-asset-id', type=int, default=17)
    a = ap.parse_args()

    host = urlparse(a.base).hostname
    if host not in ('127.0.0.1', 'localhost', '::1') and not a.allow_remote:
        sys.exit('Refusing a non-loopback host without --allow-remote.')
    only = set(a.only.split(',')) if a.only else None
    load0 = os.getloadavg()
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for wid, title, fn, writes in WORKFLOWS:
            if only and wid not in only:
                continue
            row = {'id': wid, 'workflow': title, 'target': TARGETS[wid]}
            if writes and not a.allow_writes:
                row['status'] = 'skipped (writes; pass --allow-writes on a copy)'
                results.append(row)
                continue
            use_msp = wid == 'W12'
            a.msp_cookie_present = bool(a.msp_cookie)
            runs = []
            n_runs = 1 if wid == 'W12' else a.runs   # W12 consumes its source charges
            for i in range(n_runs):
                ctx = browser.new_context(viewport={'width': a.width, 'height': a.height})
                ck = a.msp_cookie if use_msp else a.cookie
                if ck:
                    ctx.add_cookies([cookie_dict(a.base, ck)])
                page = ctx.new_page()
                if not ck and a.username:
                    page.goto(a.base + '/account/login/')
                    page.fill('input[name="auth-username"]', a.username)
                    page.fill('input[name="auth-password"]', a.password)
                    page.click('button[type=submit]')
                    page.wait_for_load_state('load')
                r = Run(page)
                r.start()
                try:
                    ok = fn(r, a)
                    ms = r.marks.get('stop_ms') and r.marks.get('start_ms') or r.elapsed_ms()
                    ms = r.elapsed_ms() if wid != 'W05' else r.marks['start_ms']
                except Exception as e:   # record, do not abort the whole benchmark
                    ok, ms = False, r.elapsed_ms()
                    r.steps.append(f'ERROR {type(e).__name__}: {str(e)[:160]}')
                runs.append({'ok': ok, 'ms': ms, 'clicks': r.clicks, 'keys': r.keys, 'chars': r.chars,
                             'marks': r.marks, 'steps': r.steps})
                ctx.close()
                if ok is None:
                    break
            good = [x for x in runs if x['ok']]
            row['runs'] = len(runs)
            row['ok_runs'] = len(good)
            if good:
                row['median_ms'] = round(statistics.median(x['ms'] for x in good))
                row['min_ms'] = min(x['ms'] for x in good)
                row['max_ms'] = max(x['ms'] for x in good)
                row['clicks'] = good[0]['clicks']
                row['keys'] = good[0]['keys']
                row['chars'] = good[0]['chars']
                row['marks_median'] = {k: round(statistics.median(x['marks'].get(k, 0) for x in good)) for k in good[0]['marks']}
                row['est_human_s'] = round(row['median_ms'] / 1000 + row['chars'] * TYPING_S_PER_CHAR + row['clicks'] * CLICK_S, 1)
                row['steps'] = good[0]['steps']
            else:
                row['steps'] = runs[0]['steps'] if runs else []
                row['status'] = 'not measurable' if runs and runs[0]['ok'] is None else 'failed'
            results.append(row)
            print(json.dumps({k: row[k] for k in row if k != 'steps'}), flush=True)
        browser.close()
    out = {'base': a.base, 'runs_requested': a.runs, 'viewport': [a.width, a.height],
           'load_avg_start': load0, 'load_avg_end': os.getloadavg(), 'nproc': os.cpu_count(),
           'typing_estimate_s_per_char': TYPING_S_PER_CHAR, 'click_estimate_s': CLICK_S, 'results': results}
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
