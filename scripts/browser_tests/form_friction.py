#!/usr/bin/env python3
"""Browser checks for form friction: real server, real Chromium, isolated DB.

Covers the paths behind issue #147 and its relatives:

1. contract edit with bundled services — the bundle survives an unrelated
   save, adding/removing rows works, a submission that bypasses the submit
   event still carries the edited bundle, removing every row clears it;
2. invoice draft edit — line edits, totals and a status change persist;
3. Settings → Security → Technician Access — preset, group-member and
   customer-policy changes save, and untouched settings stay;
4. client switcher with unsaved edits — asks first, cancelling keeps the
   edits, nothing is saved under the other client when another tab switched.

It never touches production: it refuses to run unless the database is the
isolated demo SQLite file under $DEMO_DIR (scripts/demo/), and it starts its
own `runserver` on --port against that database.

Run (from the repository root):

    export DEMO_DIR=/var/tmp/clientst0r-ff-demo        # built by scripts/demo/setup_demo.py
    PYTHONPATH=scripts/demo:.:$HOME/.local/lib/python3.12/site-packages \\
      python scripts/browser_tests/form_friction.py --port 8131

`--base http://127.0.0.1:PORT` uses a server you started yourself instead
(it must use the same demo settings and database). `--headed` shows the
browser. Exit status is the number of failed checks.
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
from datetime import date
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts' / 'demo'))
os.chdir(ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
# Playwright's sync API runs the browser from a greenlet; the fixtures and
# assertions below are plain synchronous ORM calls against the demo SQLite file.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402

from core.models import Organization, SystemSetting  # noqa: E402

USERNAME = 'ff.browser'
ORG_A, ORG_B = 'FF Alpha Freight', 'FF Bravo Dental'


def guard_not_production() -> None:
    db = settings.DATABASES['default']
    demo_dir = os.environ.get('DEMO_DIR', '')
    if 'sqlite' not in db['ENGINE'] or not demo_dir or not str(db['NAME']).startswith(demo_dir):
        raise SystemExit(f"Refusing to run: {db['NAME']!r} is not the demo SQLite database under $DEMO_DIR.")


# ---------------------------------------------------------------- fixtures

class Fx:
    """Fresh fixtures for one run, created through the ORM."""

    def __init__(self):
        from psa.models import Contract, ContractBundleItem, Invoice, InvoiceLineItem
        from tech_access import catalog
        from tech_access.models import AccessPreset, CustomerAccessPolicy, TechnicianGroup
        from tech_access.services import seed_presets
        from tech_access.testing import make_tech

        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.stay_on_page_after_org_switch = True
        s.invoice_approval_threshold_total = 0  # the status check needs an invoice that is not held
        s.invoice_approval_overage_pct = 0
        s.save()
        User = get_user_model()
        User.objects.filter(username__startswith='ff.').delete()
        self.user = User.objects.create_superuser(USERNAME, 'ff.browser@example.test', 'not-used-ff-browser')
        self.tech = make_tech('ff.tech')
        Organization.objects.filter(name__in=[ORG_A, ORG_B]).delete()
        self.a = Organization.objects.create(name=ORG_A, slug='ff-alpha-freight')
        self.b = Organization.objects.create(name=ORG_B, slug='ff-bravo-dental')

        self.contract = Contract.objects.create(
            organization=self.a, client_org=self.a, name='FF Managed Gold', contract_type='managed_services',
            status='active', start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            total_hours=Decimal('40'), hourly_rate=Decimal('150'), notes='Original notes',
            auto_renew=True, billable_role_codes=['T1'])
        self.b1 = ContractBundleItem.objects.create(contract=self.contract, name='Backup per server',
                                                    quantity=Decimal('10'), unit_label='server',
                                                    unit_price=Decimal('12'), sort_order=0)
        self.b2 = ContractBundleItem.objects.create(contract=self.contract, name='AV per seat',
                                                    quantity=Decimal('25'), unit_label='seat',
                                                    unit_price=Decimal('3'), sort_order=1)

        self.invoice = Invoice.objects.create(
            organization=self.a, client_org=self.a, title='FF October services', invoice_date=date(2026, 10, 1),
            due_date=date(2026, 10, 31), currency='EUR', tax_rate=Decimal('0.1000'), notes='Net 30')
        self.l1 = InvoiceLineItem.objects.create(invoice=self.invoice, description='Labour', quantity=Decimal('2'),
                                                 unit_price=Decimal('50'), sort_order=0, source='time_entry')
        self.l2 = InvoiceLineItem.objects.create(invoice=self.invoice, description='Licence',
                                                 quantity=Decimal('1'), unit_price=Decimal('20'), sort_order=1)
        self.invoice.recompute_totals()

        seed_presets()
        AccessPreset.objects.filter(name__startswith='FF ').delete()
        caps = {k: catalog.OFF for k in catalog.OPTIONAL}
        caps.update(ai_analyze=catalog.ALLOWED, ai_draft=catalog.ALLOWED)
        self.preset = AccessPreset.objects.create(name='FF Desk', capabilities=caps)
        TechnicianGroup.objects.filter(name__startswith='FF ').delete()
        self.group = TechnicianGroup.objects.create(name='FF Night shift')
        self.group.members.add(self.tech)
        self.keep_group = TechnicianGroup.objects.create(name='FF Day shift')
        self.keep_group.members.add(self.tech)
        CustomerAccessPolicy.objects.filter(organization=self.a).delete()
        self.policy = CustomerAccessPolicy.objects.create(organization=self.a, default_preset=self.preset,
                                                          restricted=[])

    def session(self, org) -> str:
        store = SessionStore()
        store['_auth_user_id'] = str(self.user.pk)
        store['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        store['_auth_user_hash'] = self.user.get_session_auth_hash()
        store['current_organization_id'] = org.pk
        store['2fa_prompted'] = True
        store.create()
        return store.session_key


# ------------------------------------------------------------------ checks

class Run:
    def __init__(self, base, fx, browser):
        self.base, self.fx, self.browser = base, fx, browser
        self.results: list[tuple[str, bool, str]] = []

    def context(self, org=None):
        ctx = self.browser.new_context(viewport={'width': 1400, 'height': 1000})
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
            if os.environ.get('FF_TRACE'):
                traceback.print_exc()
        else:
            self.results.append((name, True, ''))
            print(f'ok    {name}')


def expect(cond, message):
    if not cond:
        raise AssertionError(message)


def save_button(page, form_selector='main form:has(input[name="bundle_items_json"])'):
    return page.locator(f'{form_selector} button[type="submit"]').first


def watch_dialogs(page, accept=True):
    seen = []

    def on_dialog(d):
        seen.append((d.type, d.message))
        d.accept() if accept else d.dismiss()
    page.on('dialog', on_dialog)
    return seen


# 1. Contract with bundled services ------------------------------------------

def contract_unrelated_save_keeps_bundle(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    dialogs = watch_dialogs(page)
    page.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    page.fill('main input[name="name"]', 'FF Managed Gold (renamed)')
    with page.expect_navigation():
        save_button(page).click()
    expect(f'/psa/contracts/{fx.contract.pk}/' in page.url, f'did not land on the contract: {page.url}')
    expect(not dialogs, f'saving raised a dialog: {dialogs}')
    fx.contract.refresh_from_db()
    expect(fx.contract.name == 'FF Managed Gold (renamed)', 'name not saved')
    names = sorted(fx.contract.bundle_items.values_list('name', flat=True))
    expect(names == ['AV per seat', 'Backup per server'], f'bundle changed by an unrelated save: {names}')
    expect(fx.contract.notes == 'Original notes' and fx.contract.auto_renew, 'other fields changed')
    ctx.close()


def contract_add_and_remove_rows(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    page.locator(f'tr.bundle-row[data-bundle-pk="{fx.b2.pk}"] .bundle-delete').click()
    page.click('#bundle-add')
    row = page.locator('tr.bundle-row').last
    row.locator('.bundle-name').fill('Firewall subscription')
    row.locator('.bundle-qty').fill('1')
    row.locator('.bundle-price').fill('80')
    row.locator('.bundle-period').select_option('yearly')
    page.locator(f'tr.bundle-row[data-bundle-pk="{fx.b1.pk}"] .bundle-qty').fill('12')
    subtotal = page.text_content('#bundle-subtotal').strip()
    expect(subtotal == '224.00', f'subtotal shown {subtotal!r}, expected 224.00')
    with page.expect_navigation():
        save_button(page).click()
    rows = {b.name: (b.quantity, b.unit_price, b.recurring_period) for b in fx.contract.bundle_items.all()}
    expect(set(rows) == {'Backup per server', 'Firewall subscription'}, f'rows after save: {rows}')
    expect(rows['Backup per server'][0] == Decimal('12'), f'quantity edit lost: {rows}')
    expect(rows['Firewall subscription'] == (Decimal('1'), Decimal('80'), 'yearly'), f'new row: {rows}')
    expect(fx.contract.bundle_items.filter(pk=fx.b1.pk).exists(), 'existing row was recreated, not updated')
    ctx.close()


def contract_submit_bypassing_the_submit_event(run):
    """form.submit() fires no submit event; the bundle field is kept current
    on every edit, so the edit still arrives."""
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    page.locator(f'tr.bundle-row[data-bundle-pk="{fx.b1.pk}"] .bundle-qty').fill('15')
    with page.expect_navigation():
        page.evaluate("document.getElementById('bundle-items-json').closest('form').submit()")
    qty = fx.contract.bundle_items.get(pk=fx.b1.pk).quantity
    expect(qty == Decimal('15'), f'quantity after form.submit(): {qty}')
    expect(fx.contract.bundle_items.count() == 2, 'row count changed')
    ctx.close()


def contract_remove_every_row(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    while page.locator('tr.bundle-row .bundle-delete').count():
        page.locator('tr.bundle-row .bundle-delete').first.click()
    with page.expect_navigation():
        save_button(page).click()
    expect(fx.contract.bundle_items.count() == 0, 'removing every row did not clear the bundle')
    ctx.close()


# 2. Invoice ------------------------------------------------------------------

def invoice_lines_and_totals(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/invoices/{fx.invoice.pk}/edit/')
    page.locator('tr.li-row').nth(0).locator('input[name="li_quantity"]').fill('3')
    page.click('#add-line')
    new = page.locator('tr.li-row').last
    new.locator('input[name="li_description"]').fill('Travel')
    new.locator('input[name="li_quantity"]').fill('1')
    new.locator('input[name="li_unit_price"]').fill('30')
    shown = page.text_content('#invoice-total').strip()
    expect(shown == '220.00', f'page total {shown!r}, expected 220.00 (200 + 10% tax)')
    with page.expect_navigation():
        page.locator('main form.invoice-form button[type="submit"]').click()
    inv = type(fx.invoice).objects.get(pk=fx.invoice.pk)
    lines = {li.description: (li.quantity, li.unit_price, li.source) for li in inv.line_items.all()}
    expect(set(lines) == {'Labour', 'Licence', 'Travel'}, f'lines: {lines}')
    expect(lines['Labour'] == (Decimal('3'), Decimal('50'), 'time_entry'), f'edited line: {lines["Labour"]}')
    expect((inv.subtotal, inv.total) == (Decimal('200'), Decimal('220')), f'totals {inv.subtotal}/{inv.total}')
    expect((inv.currency, inv.notes, inv.due_date) == ('EUR', 'Net 30', date(2026, 10, 31)),
           f'header fields changed: {inv.currency} {inv.notes!r} {inv.due_date}')
    ctx.close()


def invoice_status_change_keeps_lines_and_totals(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    before = type(fx.invoice).objects.get(pk=fx.invoice.pk)
    lines_before = sorted(before.line_items.values_list('pk', 'quantity', 'unit_price'))
    page.goto(f'{run.base}/psa/invoices/{fx.invoice.pk}/edit/')
    page.select_option('main form.invoice-form select[name="status"]', 'sent')
    with page.expect_navigation():
        page.locator('main form.invoice-form button[type="submit"]').click()
    inv = type(fx.invoice).objects.get(pk=fx.invoice.pk)
    expect(inv.status == 'sent', f'status {inv.status} (requires_approval={inv.requires_approval})')
    expect(inv.total == before.total, f'total moved {before.total} -> {inv.total}')
    expect(sorted(inv.line_items.values_list('pk', 'quantity', 'unit_price')) == lines_before, 'lines changed')
    # A sent invoice's form only accepts status and notes; saving it unchanged keeps everything.
    page.goto(f'{run.base}/psa/invoices/{fx.invoice.pk}/edit/')
    with page.expect_navigation():
        page.locator('main form.invoice-form button[type="submit"]').click()
    after = type(fx.invoice).objects.get(pk=fx.invoice.pk)
    expect((after.status, after.total) == (inv.status, inv.total), 'resaving a locked invoice changed it')
    ctx.close()


# 3. Technician Access ---------------------------------------------------------

TA = '/settings/security/technician-access/'


def tech_access_preset_change(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}{TA}#presets')
    form_sel = f'form:has(input[name="preset"][value="{fx.preset.pk}"]):has(select[name="cap_ai_draft"])'
    form = page.locator(f'main {form_sel}')
    page.locator('main details', has=page.locator(form_sel)).locator('summary').first.click()  # the editor is collapsed
    form.locator('select[name="cap_ai_draft"]').select_option('off')
    with page.expect_navigation():
        form.locator('button[value="preview_preset"]').click()
    form = page.locator(f'main form:has(input[name="preset"][value="{fx.preset.pk}"]):has(select[name="cap_ai_draft"])')
    expect(form.locator('select[name="cap_ai_draft"]').input_value() == 'off', 'preview lost the choice')
    with page.expect_navigation():
        form.locator('button[value="save_preset"]').click()
    fx.preset.refresh_from_db()
    expect(fx.preset.capabilities['ai_draft'] == 'off', f"ai_draft {fx.preset.capabilities['ai_draft']}")
    expect(fx.preset.capabilities['ai_analyze'] == 'allowed', 'an untouched capability changed')
    ctx.close()


def tech_access_group_members_cleared(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}{TA}#groups')
    form = page.locator(f'main form:has(input[name="action"][value="group_members"]):has(input[name="group"][value="{fx.group.pk}"])')
    form.locator('select[name="members"]').select_option([])
    with page.expect_navigation():
        form.locator('button').click()
    expect(fx.group.members.count() == 0, 'emptying the member list did not remove the member')
    expect(fx.keep_group.members.count() == 1, 'another group lost its members')
    ctx.close()


def tech_access_customer_restriction(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}{TA}#customers')
    form_sel = f'form:has(input[name="action"][value="customer_policy"]):has(input[name="organization"][value="{fx.a.pk}"])'
    form = page.locator(f'main {form_sel}')
    page.locator('main details', has=page.locator(form_sel)).locator('summary').first.click()  # one collapsed panel per customer
    form.locator('input[name="restricted"][value="ai_send"]').check()
    with page.expect_navigation():
        form.locator('button').first.click()
    fx.policy.refresh_from_db()
    expect('ai_send' in (fx.policy.restricted or []), f'restriction not saved: {fx.policy.restricted}')
    expect(fx.policy.default_preset_id == fx.preset.pk, 'default preset changed')
    ctx.close()


# 4. Client switcher with unsaved edits ---------------------------------------

def _switch_link(page, org):
    """The switcher's link to `org`, opening the menu first. Lists longer
    than the inline limit show only recents, so fall back to adding the
    same link the search results would render."""
    page.click('#orgDropdown')
    sel = f'.client-switcher-menu a[href$="/accounts/switch/{org.pk}/"]'
    if not page.locator(sel).count():
        page.evaluate("""([url, name]) => {
            const a = document.createElement('a');
            a.className = 'dropdown-item'; a.href = url; a.title = name; a.textContent = name;
            document.querySelector('.client-switcher-menu').appendChild(a);
        }""", [f'/accounts/switch/{org.pk}/', org.name])
    return page.locator(sel).first


def switch_with_unsaved_edits_asks_first(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    url = f'{run.base}/psa/contracts/{fx.contract.pk}/edit/'
    page.goto(url)
    page.fill('main textarea[name="notes"]', 'Typed but not saved')
    dialogs = watch_dialogs(page, accept=False)
    _switch_link(page, fx.b).click()
    page.wait_for_timeout(500)
    expect(dialogs and 'unsaved changes' in dialogs[0][1], f'no confirm before switching: {dialogs}')
    expect(ORG_B in dialogs[0][1], f'confirm does not name the client: {dialogs[0][1]!r}')
    expect(page.url == url, f'navigated despite cancel: {page.url}')
    expect(page.input_value('main textarea[name="notes"]') == 'Typed but not saved', 'edits lost on cancel')
    expect(page.get_attribute('body', 'data-org-context') == str(fx.a.pk), 'client changed on cancel')
    ctx.close()


def switch_with_unsaved_edits_confirmed(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    page.fill('main textarea[name="notes"]', 'Discard me')
    dialogs = watch_dialogs(page, accept=True)
    with page.expect_navigation():
        _switch_link(page, fx.b).click()
    page.wait_for_load_state()
    expect(len(dialogs) == 1 and dialogs[0][0] == 'confirm',
           f'expected exactly one confirm (no extra beforeunload): {dialogs}')
    expect(page.get_attribute('body', 'data-org-context') == str(fx.b.pk), 'did not switch client')
    fx.contract.refresh_from_db()
    expect(fx.contract.notes == 'Original notes', 'discarded edits were saved')
    ctx.close()


def switch_without_edits_does_not_ask(run):
    fx = run.fx
    ctx = run.context()
    page = ctx.new_page()
    page.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    dialogs = watch_dialogs(page, accept=True)
    with page.expect_navigation():
        _switch_link(page, fx.b).click()
    expect(not dialogs, f'asked although nothing was edited: {dialogs}')
    ctx.close()


def other_tab_switch_blocks_cross_client_save(run):
    fx = run.fx
    ctx = run.context()
    tab1 = ctx.new_page()
    tab1.goto(f'{run.base}/psa/contracts/{fx.contract.pk}/edit/')
    tab1.fill('main textarea[name="notes"]', 'Written for Alpha')
    tab2 = ctx.new_page()
    tab2.goto(f'{run.base}/accounts/switch/{fx.b.pk}/')
    expect(tab2.get_attribute('body', 'data-org-context') == str(fx.b.pk), 'tab 2 did not switch')
    with tab1.expect_navigation():
        save_button(tab1).click()
    body = tab1.text_content('main') or ''
    expect('Nothing was saved' in body and ORG_A in body and ORG_B in body, f'no refusal page: {body[:300]!r}')
    fx.contract.refresh_from_db()
    expect(fx.contract.notes == 'Original notes', 'saved under the other client')
    # Going back restores the typed text; switching back lets the save through.
    tab1.go_back()
    expect(tab1.input_value('main textarea[name="notes"]') == 'Written for Alpha', 'back lost the edits')
    tab2.goto(f'{run.base}/accounts/switch/{fx.a.pk}/')
    tab1.reload()
    tab1.fill('main textarea[name="notes"]', 'Written for Alpha')
    with tab1.expect_navigation():
        save_button(tab1).click()
    fx.contract.refresh_from_db()
    expect(fx.contract.notes == 'Written for Alpha', 'save after switching back did not go through')
    ctx.close()


CHECKS = [
    ('contract: unrelated save keeps bundled services', contract_unrelated_save_keeps_bundle),
    ('contract: add one bundled service, remove one, edit one', contract_add_and_remove_rows),
    ('contract: form.submit() (no submit event) still carries the bundle', contract_submit_bypassing_the_submit_event),
    ('contract: removing every row clears the bundle', contract_remove_every_row),
    ('invoice: line edits, new line and totals persist', invoice_lines_and_totals),
    ('invoice: status change keeps lines and totals', invoice_status_change_keeps_lines_and_totals),
    ('technician access: preset preview + save', tech_access_preset_change),
    ('technician access: empty a group, others untouched', tech_access_group_members_cleared),
    ('technician access: customer restriction saved, default kept', tech_access_customer_restriction),
    ('switcher: unsaved edits ask first; cancel keeps them', switch_with_unsaved_edits_asks_first),
    ('switcher: confirming switches and saves nothing', switch_with_unsaved_edits_confirmed),
    ('switcher: no edits, no prompt', switch_without_edits_does_not_ask),
    ('switcher: other tab switched -> save refused, nothing written', other_tab_switch_blocks_cross_client_save),
]


def wait_for(url, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit(f'server at {url} did not come up')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--port', type=int, default=8131)
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
        env = dict(os.environ)
        server = subprocess.Popen(
            [sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{args.port}', '--noreload',
             '--settings=demo_settings'],
            env=env, stdout=subprocess.DEVNULL, stderr=open(pathlib.Path(os.environ['DEMO_DIR']) / 'ff-server.log', 'w'))
    try:
        wait_for(f'{base}/health/')
        from playwright.sync_api import sync_playwright
        failures = 0
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            run = Run(base, None, browser)
            for name, fn in CHECKS:
                if args.only and args.only not in name:
                    continue
                run.fx = Fx()  # fresh fixtures: every check stands alone
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
