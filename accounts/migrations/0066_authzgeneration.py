from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0065_builtin_role_display_names'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthzGeneration',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ('value', models.BigIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Authorization generation',
                'db_table': 'accounts_authz_generation',
            },
        ),
    ]
