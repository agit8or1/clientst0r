"""
Rem0te pairings made with shared secrets (HMAC, v3.17.658) → "needs
re-pairing with Ed25519".

Rem0te speaks only its Ed25519 protocol (ticket-rmm-v1: signed requests,
delegation tokens, signed events), so an HMAC Rem0te pairing never worked
against a real Rem0te. Forward, for every Rem0te connection with an HMAC
pairing configured: the pairing is switched off (no HMAC traffic to or from
Rem0te), marked as needing re-pairing, and its old settings are kept under
`ticket_rmm_legacy_hmac` so reversing this migration restores them exactly.
The encrypted shared secrets stay where they are in the connection's
credentials (they are not read for Rem0te any more) and are untouched in
both directions. Other providers are not touched.
"""
from django.db import migrations

ENABLED = 'ticket_rmm_enabled'
KEY_ID = 'ticket_rmm_key_id'
CAPS = 'ticket_rmm_capabilities'
AUTH = 'ticket_rmm_auth'
NEEDS_REPAIR = 'ticket_rmm_needs_repair'
LEGACY = 'ticket_rmm_legacy_hmac'
SAVED = (ENABLED, KEY_ID, CAPS, AUTH)
ABSENT = {'__absent__': True}


def forwards(apps, schema_editor):
    RMMConnection = apps.get_model('integrations', 'RMMConnection')
    for conn in RMMConnection.objects.filter(provider_type='rem0te'):
        m = dict(conn.field_mappings or {})
        if m.get(AUTH) == 'ed25519' or LEGACY in m:
            continue
        if not (m.get(ENABLED) or m.get(KEY_ID) or m.get(CAPS)):
            continue  # never paired: nothing to mark
        m[LEGACY] = {k: (m[k] if k in m else ABSENT) for k in SAVED}
        m[ENABLED] = False
        m.pop(KEY_ID, None)
        m.pop(CAPS, None)
        m[AUTH] = 'ed25519'
        m[NEEDS_REPAIR] = True
        conn.field_mappings = m
        conn.save(update_fields=['field_mappings'])


def backwards(apps, schema_editor):
    RMMConnection = apps.get_model('integrations', 'RMMConnection')
    for conn in RMMConnection.objects.filter(provider_type='rem0te'):
        m = dict(conn.field_mappings or {})
        legacy = m.pop(LEGACY, None)
        if not isinstance(legacy, dict):
            continue
        for k in SAVED:
            v = legacy.get(k, ABSENT)
            if v == ABSENT:
                m.pop(k, None)
            else:
                m[k] = v
        m.pop(NEEDS_REPAIR, None)
        conn.field_mappings = m
        conn.save(update_fields=['field_mappings'])


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0035_rem0teidentity_rem0tereplayguard'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
