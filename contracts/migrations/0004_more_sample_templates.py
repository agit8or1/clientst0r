"""Starter contract library: key the shipped samples (so a renamed or edited
sample is recognised and never re-created or overwritten) and add the new
ones — month-to-month and 36-month managed services agreements, prepaid
block hours, break-fix / time-and-materials terms and a master services
agreement with a service schedule. Existing templates, including edited
samples, are not changed; on a new install this seeds the whole library."""
from django.db import migrations


def seed(apps, schema_editor):
    from contracts.starter_templates import seed as do_seed
    do_seed(apps)


def map_document_terms(apps, schema_editor):
    """Existing contract documents get the term their duration implies:
    no duration -> month-to-month, 12 months -> annual, 24+ months in whole
    years -> multi-year, anything else -> custom fixed term. Signed versions
    keep their frozen content; this only labels the record."""
    ContractDocument = apps.get_model('contracts', 'ContractDocument')
    for d in ContractDocument.objects.exclude(duration_months__isnull=True).iterator():
        m = d.duration_months
        term = 'annual' if m == 12 else 'multi_year' if (m >= 24 and m % 12 == 0) else 'fixed'
        ContractDocument.objects.filter(pk=d.pk).update(term_type=term)


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0003_term_type_sample_key'),
    ]

    operations = [
        migrations.RunPython(map_document_terms, migrations.RunPython.noop),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
