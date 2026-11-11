"""Installation-wide AI settings (monthly cap across all customers, AI
Troubleshoot command allowlist) and the installation's monthly spend row."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('psa_ai', '0008_ai_troubleshoot'),
    ]

    operations = [
        migrations.CreateModel(
            name='AIBudgetInstallMonth',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(help_text='First day of the month.', unique=True)),
                ('reserved', models.PositiveBigIntegerField(default=0)),
                ('spent', models.PositiveBigIntegerField(default=0)),
            ],
            options={
                'db_table': 'psa_ai_budget_install_months',
            },
        ),
        migrations.CreateModel(
            name='AIInstallationSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('monthly_budget_cents', models.PositiveIntegerField(blank=True, help_text="Spend cap per calendar month for the whole installation, all customers together, in cents. Blank = no installation-wide cap (each customer's own ceilings still apply).", null=True)),
                ('command_allowlist', models.TextField(blank=True, help_text='AI Troubleshoot: read-only command patterns, one per line (* matches anything, ? one character; case-insensitive; lines starting with # are comments). When any are set, a suggested command is kept only if it matches one. The built-in denylist of commands that change a system always applies. Commands are only ever shown as text.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'psa_ai_installation_settings',
            },
        ),
    ]
