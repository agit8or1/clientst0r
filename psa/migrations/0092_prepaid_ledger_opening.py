"""Phase 101.2: open the prepaid-hour ledger from the old hour counter.

Contracts and invoices are not changed. Each contract with an allowance gets
its blocks and an opening set of 'migrated' postings equal to what the old
counter counted (psa.billing.seed explains the rules), so the remaining hours
shown stay the same, except retainers billed per cycle, which now show the
current cycle. `manage.py prepaid_ledger_reconcile --dry-run` lists the
before/after figures of every block.
"""
from types import SimpleNamespace

from django.db import migrations


def forwards(apps, schema_editor):
    from psa.billing import seed
    M = SimpleNamespace(
        Contract=apps.get_model('psa', 'Contract'),
        TicketTimeEntry=apps.get_model('psa', 'TicketTimeEntry'),
        PrepaidLedgerAccount=apps.get_model('psa', 'PrepaidLedgerAccount'),
        PrepaidBlock=apps.get_model('psa', 'PrepaidBlock'),
        PrepaidPosting=apps.get_model('psa', 'PrepaidPosting'),
    )
    seed.seed_all(M)


def backwards(apps, schema_editor):
    apps.get_model('psa', 'PrepaidPosting').objects.all().delete()
    apps.get_model('psa', 'PrepaidBlock').objects.all().delete()
    apps.get_model('psa', 'PrepaidLedgerAccount').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('psa', '0091_prepaid_ledger'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
