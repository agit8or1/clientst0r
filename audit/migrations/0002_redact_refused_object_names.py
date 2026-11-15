"""Clear object names that older audit entries recorded for refused requests.

Before v3.17.683 the audit middleware stored the name of the object in a
detail URL even when the request was refused, filed under the requester's
current client, so a customer administrator could read another customer's
record name in their own activity log. The middleware now names an object
only for an answered request for a record inside the entry's client
(audit.middleware._repr_belongs). This applies the same rule to the entries
written before the fix: the name is blanked, the entry itself is kept.

Only middleware entries are touched (their extra_data carries the HTTP
status_code); names written explicitly by views are left alone. An entry
whose object no longer exists cannot be checked and is blanked too.
"""
from django.db import migrations

# audit.middleware.AuditLoggingMiddleware._get_object_repr's model map.
MODEL_MAP = {
    'password': ('vault', 'Password'),
    'asset': ('assets', 'Asset'),
    'document': ('docs', 'Document'),
    'contact': ('assets', 'Contact'),
    'website_monitor': ('monitoring', 'WebsiteMonitor'),
    'expiration': ('monitoring', 'Expiration'),
    'rack': ('monitoring', 'Rack'),
    'rack_device': ('monitoring', 'RackDevice'),
    'subnet': ('monitoring', 'Subnet'),
    'ip_address': ('monitoring', 'IPAddress'),
    'personal_vault': ('vault', 'PersonalVault'),
    'organization': ('core', 'Organization'),
    'user': ('auth', 'User'),
}


def _descendants(Organization, root_pk, cache):
    """core.utils.descendant_org_ids against the historical model."""
    if root_pk in cache:
        return cache[root_pk]
    seen, frontier = {root_pk}, {root_pk}
    for _ in range(5):
        nxt = set(Organization.objects.filter(parent_id__in=frontier)
                  .values_list('pk', flat=True)) - seen
        if not nxt:
            break
        seen |= nxt
        frontier = nxt
    cache[root_pk] = seen
    return seen


def _keep(apps, entry, Organization, cache):
    status = (entry.extra_data or {}).get('status_code')
    try:
        status = int(status)
    except (TypeError, ValueError):
        return False
    if status >= 400:
        return False
    answered = 200 <= status < 300
    info = MODEL_MAP.get(entry.object_type)
    if not info or not entry.object_id:
        return answered
    try:
        model = apps.get_model(*info)
        obj = model.objects.get(pk=entry.object_id)
    except Exception:
        return False
    if info == ('core', 'Organization'):
        org_id = obj.pk
    elif hasattr(obj, 'organization_id'):
        org_id = obj.organization_id
    else:
        return answered
    if entry.organization_id is None or org_id is None:
        return answered
    return org_id in _descendants(Organization, entry.organization_id, cache)


def redact(apps, schema_editor):
    AuditLog = apps.get_model('audit', 'AuditLog')
    Organization = apps.get_model('core', 'Organization')
    cache, blank = {}, []
    rows = (AuditLog.objects.exclude(object_repr='')
            .only('pk', 'object_type', 'object_id', 'object_repr', 'organization_id', 'extra_data')
            .iterator(chunk_size=500))
    for entry in rows:
        if not isinstance(entry.extra_data, dict) or 'status_code' not in entry.extra_data:
            continue  # written by a view, not the middleware
        if not _keep(apps, entry, Organization, cache):
            blank.append(entry.pk)
    for i in range(0, len(blank), 500):
        AuditLog.objects.filter(pk__in=blank[i:i + 500]).update(object_repr='')


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
        ('core', '0104_dashboard_role_config'),
        ('assets', '0029_serial_events'),
        ('vault', '0016_password_encrypted_notes'),
        ('monitoring', '0015_vlangroup_alter_rackdevice_unique_together_and_more'),
        ('docs', '__latest__'),
        ('auth', '__latest__'),
    ]

    operations = [
        migrations.RunPython(redact, migrations.RunPython.noop),
    ]
