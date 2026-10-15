"""Build the isolated demo instance used for the documentation media.

    export DEMO_DIR=/var/tmp/clientst0r-demo
    export PYTHONPATH=scripts/demo:.
    python scripts/demo/setup_demo.py

Creates the SQLite schema under $DEMO_DIR, then fills it with the invented
dataset: the application's own seed commands (sample tenant, PSA reference
data, compliance frameworks, the sample readiness standard and portal request
types) plus scripts/demo/seed_demo.py and scripts/demo/seed_compliance.py.

Refuses to run unless the configured database is the demo SQLite file under
$DEMO_DIR. Start from an empty $DEMO_DIR: the screenshot manifest refers to
primary keys that a fresh build produces.
"""
import os
import pathlib
import runpy
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts' / 'demo'))
os.chdir(ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402

db = settings.DATABASES['default']
demo_dir = os.environ.get('DEMO_DIR', '')
if 'sqlite' not in db['ENGINE'] or not demo_dir or not str(db['NAME']).startswith(demo_dir):
    raise SystemExit(f"Refusing to run: {db['NAME']!r} is not the demo SQLite database under $DEMO_DIR.")

call_command('migrate', interactive=False, verbosity=0)
call_command('seed_demo_data')          # sample tenant (renamed to Beacon Managed IT below)
call_command('psa_seed_defaults')       # queues, statuses, priorities, ticket types

import seed_demo  # noqa: E402

for step in (seed_demo.seed_showcase, seed_demo.seed_presentation, seed_demo.seed_asset_detail,
             seed_demo.seed_commercial, seed_demo.rename_msp_tenant, seed_demo.seed_project_work,
             seed_demo.seed_visual, seed_demo.seed_dispatch):
    print(step.__name__)
    step()

call_command('seed_pci_dss')
call_command('seed_hipaa')
runpy.run_path(str(ROOT / 'scripts' / 'demo' / 'seed_compliance.py'), run_name='__main__')

call_command('readiness_seed_samples')
call_command('psa_seed_portal_requests')
for step in (seed_demo.seed_my_work, seed_demo.seed_document_lifecycle,
             seed_demo.seed_readiness, seed_demo.seed_portal_request,
             seed_demo.seed_scheduler_history):
    print(step.__name__)
    step()
print(f"demo instance ready: {db['NAME']}")
