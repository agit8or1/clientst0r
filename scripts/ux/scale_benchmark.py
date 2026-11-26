"""Page benchmark against a synthetic scale database (see seed_scale.py).

Uses the page set and the measurement of page_baseline.py (in-process Django
test client: server time and SQL query count per page, median of N runs) and
runs it twice: as the superuser technician and as the L1 technician whose
client scope is a tenth of the customers. Read-only apart from two session
rows. Refuses a database that is not a generated scale database.

    nice -n 10 python scripts/ux/scale_benchmark.py /var/tmp/clientst0r-scale-60/demo.sqlite3 \\
        --json out.json --md out.md
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts' / 'demo'), str(ROOT / 'scripts' / 'ux')]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--json')
    ap.add_argument('--md')
    args = ap.parse_args(argv)
    db = pathlib.Path(args.db).resolve()
    if not db.is_file() or db == pathlib.Path('/home/administrator/db.sqlite3'):
        sys.exit(f'Refusing: {db} is not a scale database file.')
    os.environ['DEMO_DIR'] = str(db.parent)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'demo_settings'
    import page_baseline as pb  # noqa: E402  (runs django.setup)
    from django.conf import settings
    from django.db import connections
    settings.DATABASES['default']['NAME'] = str(db)
    connections['default'].settings_dict['NAME'] = str(db)

    from django.contrib.auth import get_user_model
    from core.models import Organization
    if not Organization.objects.filter(name='Scale MSP Services').exists():
        sys.exit('Refusing: no "Scale MSP Services" organization, this is not a generated scale database.')
    User = get_user_model()
    msp = Organization.objects.get(name='Scale MSP Services')
    # first customer (inside the L1 technician's scope); a mid-list one too
    first = Organization.objects.exclude(pk=msp.pk).order_by('pk').first()

    runs = {}
    for label, username in (('superuser', 'scale.super'), ('L1 technician (10% of customers)', 'scale.l1')):
        user = User.objects.get(username=username)
        clients = {'customer': pb._client(user, first), 'msp': pb._client(user, msp)}
        rows = []
        for spec in pb.pages(first):
            c = clients['msp' if spec[0] in pb.MSP_PAGES else 'customer']
            res = pb.measure(c, spec[0], spec[1], spec[2], spec[3] if len(spec) > 3 else '', args.runs)
            rows.append(res)
            print(label, res, flush=True)
        runs[label] = rows

    from django.db import connection
    counts = {}
    from assets.models import Asset
    from assets.models import Contact
    from docs.models import Document
    from psa.models import Charge, Invoice, Ticket, TicketComment, TicketTimeEntry
    from vault.models import Password
    for name, model in (('customers', None), ('assets', Asset), ('contacts', Contact), ('tickets', Ticket),
                        ('comments', TicketComment), ('time entries', TicketTimeEntry), ('documents', Document),
                        ('vault entries', Password), ('charges', Charge), ('invoices', Invoice)):
        counts[name] = (Organization.objects.count() - 1) if model is None else model.objects.count()
    meta = {'database': str(db), 'size_mb': round(db.stat().st_size / 1e6), 'nproc': os.cpu_count(),
            'load_average': os.getloadavg(), 'runs': args.runs, 'counts': counts,
            'git_diff_stat': subprocess.run(['git', 'diff', '--stat', '--', '.'], capture_output=True, text=True,
                                            cwd=ROOT).stdout}
    out = {'meta': meta, 'results': runs}
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(out, indent=1))
    md = markdown(out)
    if args.md:
        pathlib.Path(args.md).write_text(md)
    print(md)


def markdown(out):
    labels = list(out['results'])
    by = {lab: {r['page']: r for r in rows} for lab, rows in out['results'].items()}
    lines = ['| Page | ' + ' | '.join(f'{lab}: ms / queries / status' for lab in labels) + ' |',
             '|---|' + '---|' * len(labels)]
    for r in out['results'][labels[0]]:
        cells = []
        for lab in labels:
            x = by[lab].get(r['page'], {})
            cells.append(x['skipped'][:30] if 'skipped' in x else
                         f"{x['median_ms']} / {x['queries']} / {x['status']}" if x else '-')
        lines.append(f"| {r['page']} | " + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


def slowest(out, label, n=10):
    rows = [r for r in out['results'][label] if 'median_ms' in r]
    return sorted(rows, key=lambda r: -r['median_ms'])[:n]


if __name__ == '__main__':
    main()
