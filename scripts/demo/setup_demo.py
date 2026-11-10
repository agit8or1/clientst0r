"""Build the isolated demo instance used for the documentation media.

    export DEMO_DIR=/var/tmp/clientst0r-demo
    export PYTHONPATH=scripts/demo:.
    python scripts/demo/setup_demo.py

Creates the SQLite schema under $DEMO_DIR, then fills it with the invented
dataset: the application's own seed commands (sample tenant, PSA reference
data, compliance frameworks, the sample readiness standard and portal request
types, the hardware catalog and its demo client) plus scripts/demo/seed_demo.py
and scripts/demo/seed_compliance.py. After the hardware demo it runs the rack
artwork step, the sample conversations and module samples pointed at this
instance's customers, and the late seed_demo steps (named approvers, readiness
custom fields, the secure-message link, ticket AI, superuser approval and the
RMM fixture and pairing) — all rows written directly; nothing calls out.

HARDWARE_CATALOG_SOURCE=<devicetype-library checkout> reuses an existing
checkout instead of cloning one.

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
# Hardware inventory: the device-type catalog, then the "Client XYZ" demo built
# from it. HARDWARE_CATALOG_SOURCE reuses an existing devicetype-library
# checkout instead of cloning one.
catalog_source = os.environ.get('HARDWARE_CATALOG_SOURCE')
call_command('import_hardware_catalog', verbosity=0, **({'source_dir': catalog_source} if catalog_source else {}))
call_command('seed_hardware_demo')

# Everything below runs after the hardware demo so the primary keys the
# manifest names for the steps above stay what a fresh build produces.
# Rack A drawn from catalog artwork (needs the catalog imported above).
print('seed_rack_artwork')
seed_demo.seed_rack_artwork()
# The application's sample conversations and module samples, pointed at this
# instance's invented customers instead of their built-in demo slugs.
call_command('psa_seed_sample_conversations', tech='demo.tech', org_map=seed_demo.CONVERSATION_ORG_MAP)
call_command('seed_module_samples', **seed_demo.MODULE_SAMPLE_OPTIONS)
for step in (seed_demo.seed_named_approvers, seed_demo.seed_readiness_custom_fields,
             seed_demo.seed_secure_link, seed_demo.seed_ticket_ai, seed_demo.seed_superuser_approval,
             seed_demo.seed_rmm_fixture, seed_demo.seed_rmm_pairing):
    print(step.__name__)
    step()
print(f"demo instance ready: {db['NAME']}")
