"""One invoice per contract billing period, enforced on every database.

0068 added a *conditional* unique constraint for this. MariaDB/MySQL do not
support partial indexes and Django silently skips that constraint there, so on
those installs nothing at the database level stopped a duplicate. This adds
`contract_period_key` ("<contract id>:<period start>", NULL when not a
contract-period invoice) with a plain unique index, which works everywhere.

Before the index is created the existing data is checked. Duplicates are NOT
deleted — they are real invoices someone may have sent or been paid on. If any
exist the migration stops with the list and how to resolve them.
"""
from django.db import migrations, models


def find_duplicates(Invoice):
    """[(contract_id, period_start, [invoice ids...]), ...] — oldest id first."""
    from django.db.models import Count
    groups = (Invoice.objects
              .filter(source_contract__isnull=False,
                      billing_period_start__isnull=False,
                      is_credit_memo=False)
              .values('source_contract_id', 'billing_period_start')
              .annotate(n=Count('id')).filter(n__gt=1)
              .order_by('source_contract_id', 'billing_period_start'))
    out = []
    for g in groups:
        ids = list(Invoice.objects.filter(
            source_contract_id=g['source_contract_id'],
            billing_period_start=g['billing_period_start'],
            is_credit_memo=False).order_by('id').values_list('id', flat=True))
        out.append((g['source_contract_id'], g['billing_period_start'], ids))
    return out


def check_and_backfill(apps, schema_editor):
    Invoice = apps.get_model('psa', 'Invoice')
    dups = find_duplicates(Invoice)
    if dups:
        lines = '\n'.join(
            f'  contract #{c} period {p}: invoices {", ".join(str(i) for i in ids)}'
            for c, p, ids in dups[:50])
        more = f'\n  ... and {len(dups) - 50} more' if len(dups) > 50 else ''
        raise RuntimeError(
            'psa.0086: found contract billing periods invoiced more than once. '
            'The one-invoice-per-period index cannot be created until they are '
            'resolved. Nothing was changed or deleted.\n'
            f'{lines}{more}\n'
            'Run `python manage.py find_duplicate_contract_invoices` for details. '
            'For each extra invoice, either delete it (if it was never sent or '
            'pushed to accounting) or keep it and clear its billing period '
            '(Invoice.billing_period_start = NULL) so it is no longer counted as '
            'that period\'s invoice; issue a credit memo if the customer was '
            'billed twice. Then run `python manage.py migrate` again.')
    for inv in (Invoice.objects
                .filter(source_contract__isnull=False,
                        billing_period_start__isnull=False,
                        is_credit_memo=False)
                .only('id', 'source_contract_id', 'billing_period_start')
                .iterator()):
        Invoice.objects.filter(pk=inv.pk).update(
            contract_period_key=f'{inv.source_contract_id}:'
                                f'{inv.billing_period_start.isoformat()}')


class Migration(migrations.Migration):

    dependencies = [
        ('psa', '0085_request_form_versions_backfill'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='invoice',
            options={'ordering': ['-invoice_date', '-created_at'], 'permissions': [('force_repush_invoice', 'Can force re-push of an invoice to accounting')]},
        ),
        migrations.AddField(
            model_name='invoice',
            name='contract_period_key',
            field=models.CharField(blank=True, editable=False, help_text='Internal: enforces one invoice per contract billing period.', max_length=64, null=True),
        ),
        migrations.RunPython(check_and_backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='invoice',
            name='contract_period_key',
            field=models.CharField(blank=True, editable=False, help_text='Internal: enforces one invoice per contract billing period.', max_length=64, null=True, unique=True),
        ),
    ]
