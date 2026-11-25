"""Server-side page baseline: wall time and SQL query count per page.

Read-only. Runs the Django test client in-process against a SQLite demo
database, so point DEMO_DIR at a COPY of the demo database (see the usage
below); the script refuses to run against anything but a demo SQLite file.
It creates one session row (in the database it is pointed at) for the user.

    sqlite3-backup copy:  python - <<'PY'
        import sqlite3
        s = sqlite3.connect('file:/var/tmp/clientst0r-demo/demo.sqlite3?mode=ro', uri=True)
        d = sqlite3.connect('/tmp/bench/db/demo.sqlite3'); s.backup(d)
    PY
    DEMO_DIR=/tmp/bench/db DJANGO_SETTINGS_MODULE=demo_settings \\
      PYTHONPATH=scripts/demo:. python scripts/ux/page_baseline.py --user demo.tech --runs 5 --json out.json

Timing is the in-process request/response time (middleware, view, template
render), not network or browser time. The first request per page is a warm-up
and is reported separately (cold). Query counts come from
CaptureQueriesContext and are for the last measured run.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'scripts', 'demo'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.urls import NoReverseMatch, reverse  # noqa: E402


def guard():
    db = settings.DATABASES['default']
    if 'sqlite' not in db['ENGINE'] or 'demo' not in str(db['NAME']).lower():
        sys.exit('Refusing to run: not a demo SQLite database.')


MSP_PAGES = {'Billing review', 'Invoice list', 'Invoice detail', 'Contract list', 'Contract detail',
             'Quote list', 'Quote detail', 'Reports home', 'PSA reports list', 'Client health list', 'Timesheet'}


def pages(org):
    from assets.models import Asset
    from psa.models import Contract, Invoice, Quote, Ticket
    t = Ticket.objects.filter(organization=org).order_by('-id').first() or Ticket.objects.order_by('-id').first()
    a = Asset.objects.filter(organization=org).first() or Asset.objects.first()
    inv = Invoice.objects.first()
    con = Contract.objects.first()
    quo = Quote.objects.first()  # billing records live on the MSP organization
    P = [
        ('Dashboard', 'core:dashboard', {}),
        ('Ticket list', 'psa:ticket_list', {}),
        ('Ticket detail', 'psa:ticket_detail', {'ticket_number': t.ticket_number} if t else None),
        ('Ticket create form', 'psa:ticket_create', {}),
        ('My Work', 'psa:my_work', {}),
        ('Dispatch board', 'psa:dispatch_board', {}),
        ('Client workspace', 'accounts:organization_detail', {'org_id': org.pk}),
        ('Client list', 'accounts:organization_list', {}),
        ('Client operations', 'core:customer_ops', {'org_id': org.pk}),
        ('Asset list', 'assets:asset_list', {}),
        ('Asset detail', 'assets:asset_detail', {'pk': a.pk} if a else None),
        ('Global search (q=server)', 'core:search', {}, '?q=server'),
        ('Palette home JSON', 'core:palette_home', {}),
        ('Palette search JSON (q=ridge)', 'core:palette_search', {}, '?q=ridge'),
        ('Client switcher search JSON', 'core:client_switcher_search', {}, '?q=r'),
        ('Reports home', 'reports:home', {}),
        ('PSA reports list', 'reports:psa_reports_list', {}),
        ('Client health list', 'health_score:list', {}),
        ('Billing review', 'psa:billing_review', {}),
        ('Invoice list', 'psa:invoice_list', {}),
        ('Invoice detail', 'psa:invoice_detail', {'pk': inv.pk} if inv else None),
        ('Contract list', 'psa:contract_list', {}),
        ('Contract detail', 'psa:contract_detail', {'pk': con.pk} if con else None),
        ('Quote list', 'psa:quote_list', {}),
        ('Quote detail', 'psa:quote_detail', {'pk': quo.pk} if quo else None),
        ('Document list (KB/docs)', 'docs:document_list', {}),
        ('Global KB list', 'docs:global_kb_list', {}),
        ('Vault list', 'vault:password_list', {}),
        ('RMM devices', 'integrations:rmm_devices', {}),
        ('Integrations list', 'integrations:integration_list', {}),
        ('Settings home', 'core:settings_home', {}),
        ('Security dashboard', 'core:security_dashboard', {}),
        ('Timesheet', 'psa:my_timesheet', {}),
        ('Wallboard data JSON', 'reports:wallboard_data', {}),
    ]
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--user', default='demo.tech')
    ap.add_argument('--org', default='Ridgeline', help='substring of the organization name to select')
    ap.add_argument('--msp', default='Beacon', help='organization used for billing/report pages')
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--json')
    args = ap.parse_args()
    guard()
    from django.contrib.auth import get_user_model
    from core.models import Organization
    user = get_user_model().objects.get(username=args.user)
    org = Organization.objects.filter(name__icontains=args.org).first() or Organization.objects.first()
    msp = Organization.objects.filter(name__icontains=args.msp).first() or org
    clients = {}
    for key, o in (('customer', org), ('msp', msp)):
        clients[key] = _client(user, o)
    out = []
    for spec in pages(org):
        c = clients['msp' if spec[0] in MSP_PAGES else 'customer']
        label, name, kw = spec[0], spec[1], spec[2]
        qs = spec[3] if len(spec) > 3 else ''
        res = measure(c, label, name, kw, qs, args.runs)
        out.append(res)
        print(res, flush=True)
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(out, f, indent=1)


def _client(user, org):
    st = SessionStore()
    st['_auth_user_id'] = str(user.pk)
    st['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    st['_auth_user_hash'] = user.get_session_auth_hash()
    st['current_organization_id'] = org.pk
    st['organization_id'] = org.pk
    st.create()
    c = Client(SERVER_NAME='localhost')
    c.cookies[settings.SESSION_COOKIE_NAME] = st.session_key
    return c


def measure(c, label, name, kw, qs, runs):
    if kw is None:
        return {'page': label, 'skipped': 'no sample record'}
    try:
        path = reverse(name, kwargs=kw) + qs
    except NoReverseMatch as e:
        return {'page': label, 'skipped': f'no route: {e}'}
    hdr = {'HTTP_X_PALETTE_QUERY': qs[3:]} if 'palette' in name else {}
    t0 = time.perf_counter()
    r0 = c.get(path, **hdr)
    cold = (time.perf_counter() - t0) * 1000
    times, nq, sql_ms = [], 0, 0
    r = r0
    for _ in range(runs):
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            r = c.get(path, **hdr)
            times.append((time.perf_counter() - t0) * 1000)
        nq = len(ctx.captured_queries)
        sql_ms = sum(float(q['time']) for q in ctx.captured_queries) * 1000
    return {'page': label, 'path': path, 'status': r.status_code, 'cold_ms': round(cold),
            'median_ms': round(statistics.median(times)), 'min_ms': round(min(times)), 'max_ms': round(max(times)),
            'queries': nq, 'sql_ms': round(sql_ms), 'html_kb': round(len(r.content) / 1024, 1)}


if __name__ == '__main__':
    main()
