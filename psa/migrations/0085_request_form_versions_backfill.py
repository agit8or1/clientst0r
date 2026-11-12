"""Give existing request types a version 1 and existing guided-request
tickets a submission record.

Additive only: no existing row is changed apart from setting the new
`published_version` pointer. Items whose form lives only in the legacy
`fields_json` get their first version when the form is next served
(psa/request_forms.py:ensure_version). Tickets keep their
custom_fields["service_request"] record unchanged; the new submission row
copies it so request type can be filtered and reported on.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Item = apps.get_model('psa', 'ServiceCatalogItem')
    Version = apps.get_model('psa', 'ServiceRequestFormVersion')
    Ticket = apps.get_model('psa', 'Ticket')
    Submission = apps.get_model('psa', 'ServiceRequestSubmission')
    User = apps.get_model('auth', 'User')

    for item in Item.objects.all().iterator():
        if not item.form_schema or Version.objects.filter(catalog_item=item).exists():
            continue
        v = Version.objects.create(
            catalog_item=item, number=1, schema=item.form_schema,
            subject_pattern=(item.default_subject or '')[:300],
            note='Existing form at upgrade', published_by_id=item.last_published_by_id,
        )
        Item.objects.filter(pk=item.pk).update(published_version=v)

    item_ids = set(Item.objects.values_list('pk', flat=True))
    user_ids = set(User.objects.values_list('pk', flat=True))
    try:
        tickets = list(Ticket.objects.filter(custom_fields__has_key='service_request')
                       .values('pk', 'organization_id', 'custom_fields', 'created_at'))
    except Exception:  # JSON lookups unavailable: skip the optional backfill
        tickets = []
    for t in tickets:
        rec = (t['custom_fields'] or {}).get('service_request')
        if not isinstance(rec, dict) or Submission.objects.filter(ticket_id=t['pk']).exists():
            continue
        rows = [r for r in (rec.get('answers') or []) if isinstance(r, dict)]
        snapshot = [{k: r[k] for k in ('key', 'label', 'type') if k in r} for r in rows]
        sub = Submission.objects.create(
            idempotency_key=f'legacy-{t["pk"]}', ticket_id=t['pk'],
            catalog_item_id=rec.get('catalog_item_id') if rec.get('catalog_item_id') in item_ids else None,
            catalog_item_name=str(rec.get('catalog_item_name') or '')[:120],
            organization_id=t['organization_id'],
            submitted_by_id=rec.get('submitted_by_id') if rec.get('submitted_by_id') in user_ids else None,
            schema_snapshot=snapshot, original_answers=rows, answers=rows,
        )
        Submission.objects.filter(pk=sub.pk).update(created_at=t['created_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('psa', '0084_request_types_dynamic_forms'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
