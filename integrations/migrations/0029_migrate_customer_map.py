"""
Phase 44.1 (v3.17.531): lift the customer map out of the credentials blob.

Existing mappings live inside `AccountingConnection.encrypted_credentials` —
as `customer_map` for QuickBooks Online and `contact_map` for Xero. Copy each
entry into a real `AccountingCustomerLink` row so the mapping survives a
credentials reset and becomes queryable.

The blob's copy is deliberately left in place. If this release is rolled back,
the old code still finds its map and keeps working; the reverse migration
therefore only has to delete the rows it created. The blob copy stops being
read once 44.1 ships, and is cleaned up in a later release once the rows have
proven themselves in the field.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    AccountingConnection = apps.get_model('integrations', 'AccountingConnection')
    AccountingCustomerLink = apps.get_model('integrations', 'AccountingCustomerLink')
    Organization = apps.get_model('core', 'Organization')

    # Historical models have no custom methods, so decrypt via the real one.
    from integrations.models import AccountingConnection as LiveConnection

    for row in AccountingConnection.objects.all():
        try:
            creds = LiveConnection(
                encrypted_credentials=row.encrypted_credentials).get_credentials()
        except Exception:
            # An undecryptable blob (rotated key, corrupt row) must not stop the
            # migration — the mapping is rebuilt on next push either way.
            continue

        # QBO calls it customer_map, Xero contact_map. Same shape either way:
        # {local organization id: provider-side id}.
        customer_map = {}
        for key in ('customer_map', 'contact_map'):
            value = (creds or {}).get(key)
            if isinstance(value, dict):
                customer_map.update(value)
        if not customer_map:
            continue

        seen_customers = set()
        for client_org_id, customer_id in customer_map.items():
            if not customer_id:
                continue
            customer_id = str(customer_id)
            # The blob could hold two clients pointing at one customer; the new
            # unique constraint forbids that, so keep the first and skip the rest
            # rather than failing the whole migration.
            if customer_id in seen_customers:
                continue
            try:
                client_org_pk = int(client_org_id)
            except (TypeError, ValueError):
                continue
            if not Organization.objects.filter(pk=client_org_pk).exists():
                continue
            if AccountingCustomerLink.objects.filter(
                    connection_id=row.pk, client_org_id=client_org_pk).exists():
                continue
            seen_customers.add(customer_id)
            AccountingCustomerLink.objects.create(
                organization_id=row.organization_id,
                connection_id=row.pk,
                client_org_id=client_org_pk,
                provider_customer_id=customer_id,
                source='matched',
            )


def backwards(apps, schema_editor):
    # The blob copy was never removed, so undoing this only means dropping the
    # rows it created.
    AccountingCustomerLink = apps.get_model('integrations', 'AccountingCustomerLink')
    AccountingCustomerLink.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0028_accountingcustomerlink'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
