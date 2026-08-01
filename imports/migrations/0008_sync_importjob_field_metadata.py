"""Catch up the migration state with three ImportJob field edits that were made
in the model without a migration (v3.17.509).

All three are Python-level only — the columns are byte-for-byte identical
before and after:

  * ``skip_duplicates``  — help_text reworded.
  * ``source_type``      — a 'csv' choice was added.
  * ``source_file``      — help_text reworded, and ``upload_to`` moved from
    ``imports/magicplan/%Y/%m/`` to ``imports/files/%Y/%m/`` when the importer
    grew CSV support. The column is ``varchar(100) NULL`` either way.

``upload_to`` is not in Django's ``Field.non_db_attrs``, so the autodetector
treats that last one as schema-affecting. On SQLite (which this project uses
when ``DB_ENGINE=sqlite3``) an AlterField means a full ``import_jobs`` table
rebuild — copy every row into a new table, drop the original, rename, recreate
all seven indexes. That is real risk and a real outage window for a change that
alters no column.

So the operations are wrapped in ``SeparateDatabaseAndState`` with an empty
``database_operations``: Django records the new field state and touches nothing.
Safe precisely because the generated SQL for the other two was already
``-- (no-op)``, and ``source_file``'s rebuild would have produced an identical
column definition.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0007_importjob_skip_duplicates'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name='importjob',
                    name='skip_duplicates',
                    field=models.BooleanField(
                        default=True,
                        help_text='Skip items already imported in any previous job '
                                  'for this organization'),
                ),
                migrations.AlterField(
                    model_name='importjob',
                    name='source_file',
                    field=models.FileField(
                        blank=True,
                        help_text='Upload file: MagicPlan JSON export or CSV/spreadsheet',
                        null=True,
                        upload_to='imports/files/%Y/%m/'),
                ),
                migrations.AlterField(
                    model_name='importjob',
                    name='source_type',
                    field=models.CharField(
                        choices=[('itglue', 'IT Glue'), ('hudu', 'Hudu'),
                                 ('magicplan', 'MagicPlan Floor Plans'),
                                 ('csv', 'CSV / Spreadsheet')],
                        max_length=20),
                ),
            ],
        ),
    ]
