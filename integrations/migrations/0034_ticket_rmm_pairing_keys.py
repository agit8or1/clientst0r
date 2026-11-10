"""Ticket integration pairing becomes provider-neutral (v3.17.658).

Moves the pairing's field_mappings keys from their rem0te-only names to the
ticket_rmm_* names in integrations/ticket_rmm.py, value for value:

  rem0te_integration_enabled  → ticket_rmm_enabled
  rem0te_integration_key_id   → ticket_rmm_key_id
  rem0te_processing_location  → ticket_rmm_location
  rem0te_capabilities         → ticket_rmm_capabilities

and, for rem0te connections, copies the inventory pin rem0te_business_id
into the tenant pin ticket_rmm_tenant_id (rem0te_business_id itself stays —
the inventory sync still uses it).

Nothing else changes: the enabled flag keeps its value, so an approved,
live pairing stays approved and live with no re-approval; a pairing that
was waiting for approval keeps waiting (pending protected changes name the
connection, not the keys). Secrets live in the encrypted credentials under
names that were already neutral and are not touched. Reversible.
"""
from django.db import migrations

RENAMES = (
    ('rem0te_integration_enabled', 'ticket_rmm_enabled'),
    ('rem0te_integration_key_id', 'ticket_rmm_key_id'),
    ('rem0te_processing_location', 'ticket_rmm_location'),
    ('rem0te_capabilities', 'ticket_rmm_capabilities'),
)
BUSINESS_PIN, TENANT_PIN = 'rem0te_business_id', 'ticket_rmm_tenant_id'


def migrate_mappings(mappings, provider_type):
    """The new field_mappings for one connection (a copy), or None if unchanged."""
    if not isinstance(mappings, dict):
        return None
    out = dict(mappings)
    for old, new in RENAMES:
        if old in out:
            value = out.pop(old)
            out.setdefault(new, value)
    if provider_type == 'rem0te' and out.get(BUSINESS_PIN) and not out.get(TENANT_PIN):
        out[TENANT_PIN] = out[BUSINESS_PIN]
    return out if out != mappings else None


def unmigrate_mappings(mappings, provider_type):
    if not isinstance(mappings, dict):
        return None
    out = dict(mappings)
    for old, new in RENAMES:
        if new in out:
            value = out.pop(new)
            out.setdefault(old, value)
    if provider_type == 'rem0te' and out.get(TENANT_PIN) == out.get(BUSINESS_PIN):
        out.pop(TENANT_PIN, None)
    return out if out != mappings else None


def _run(apps, fn):
    RMMConnection = apps.get_model('integrations', 'RMMConnection')
    for pk, mappings, provider_type in RMMConnection.objects.values_list('pk', 'field_mappings', 'provider_type'):
        new = fn(mappings, provider_type)
        if new is not None:
            RMMConnection.objects.filter(pk=pk).update(field_mappings=new)


def forwards(apps, schema_editor):
    _run(apps, migrate_mappings)


def backwards(apps, schema_editor):
    _run(apps, unmigrate_mappings)


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0033_rem0te_provider'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
