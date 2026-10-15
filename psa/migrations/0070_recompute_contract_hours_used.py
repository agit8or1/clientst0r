"""v3.17.600: recompute Contract.hours_used_minutes once from time entries.

Until v3.17.600 the field was a running counter bumped on every
`TicketTimeEntry.save()`: non-billable entries and excluded roles were
counted, re-saved entries were counted again, deletes were never subtracted.
From now on it is derived from the entries (`Contract.qualifying_time_entries`);
this brings existing rows in line.

The rule is copied here rather than imported so the migration keeps doing
what it did when it was written. Idempotent: running it again computes the
same values. `manage.py psa_recompute_contract_hours` does the same on demand.
"""
from django.db import migrations, models


def _recompute(apps, schema_editor):
    Contract = apps.get_model('psa', 'Contract')
    TicketTimeEntry = apps.get_model('psa', 'TicketTimeEntry')
    for c in Contract.objects.all().iterator():
        qs = TicketTimeEntry.objects.filter(
            ticket__organization_id=c.client_org_id,
            ended_at__isnull=False,
            duration_minutes__gt=0,
            is_billable=True,
        )
        if c.start_date:
            qs = qs.filter(started_at__date__gte=c.start_date)
        if c.end_date:
            qs = qs.filter(started_at__date__lte=c.end_date)
        excluded = [x for x in (c.excluded_role_codes or []) if x]
        if excluded:
            qs = qs.exclude(role_code__in=excluded)
        included = [x for x in (c.billable_role_codes or []) if x]
        if included:
            qs = qs.filter(models.Q(role_code='') | models.Q(role_code__in=included))
        minutes = int(qs.aggregate(m=models.Sum('duration_minutes'))['m'] or 0)
        if minutes != (c.hours_used_minutes or 0):
            Contract.objects.filter(pk=c.pk).update(hours_used_minutes=minutes)


class Migration(migrations.Migration):

    dependencies = [
        ('psa', '0069_time_entry_role_code'),
    ]

    operations = [
        migrations.RunPython(_recompute, migrations.RunPython.noop),
    ]
