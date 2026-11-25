"""Module switches: every one on for a new install, nothing changes on upgrade.

* AddField (default True) for the modules that were always available until
  now. Existing rows are filled with True, so each module stays on.
* AlterField for psa_enabled, crm_enabled and pulse_enabled: only the
  default for rows created from now on changes (off -> on). AlterField does
  not touch existing rows; an install that had PSA, CRM or pulse checks off
  keeps them off. A new install creates its settings row through
  SystemSetting.get_settings() (get_or_create), which uses the new default.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0124_scheduledtask_vehicles_service_alerts'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsetting',
            name='backup_monitoring_enabled',
            field=models.BooleanField(default=True, help_text='Customer backup monitoring, alerts and restore tests'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='change_management_enabled',
            field=models.BooleanField(default=True, help_text='Change requests, problems and releases (PSA)'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='client_health_enabled',
            field=models.BooleanField(default=True, help_text='Client health scores'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='contracts_enabled',
            field=models.BooleanField(default=True, help_text='Contract documents: drafting, templates, clauses and signing'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='diagrams_enabled',
            field=models.BooleanField(default=True, help_text='Diagrams in documentation (drawings and floor plans)'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='field_ops_enabled',
            field=models.BooleanField(default=True, help_text='Field operations: timeclock, location sharing and geo-aware dispatch'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='licensing_enabled',
            field=models.BooleanField(default=True, help_text='Software licensing: subscriptions, renewals and license sync'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='netconfig_enabled',
            field=models.BooleanField(default=True, help_text='Network device configuration backups'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='onboarding_enabled',
            field=models.BooleanField(default=True, help_text='Customer onboarding wizard'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='procurement_enabled',
            field=models.BooleanField(default=True, help_text='Requisitions, purchase orders, back-orders and vendors (PSA)'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='projects_enabled',
            field=models.BooleanField(default=True, help_text='Projects, project templates and project tasks (PSA)'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='quotes_enabled',
            field=models.BooleanField(default=True, help_text='Quotes: drafting, sending and accepting (PSA)'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='readiness_enabled',
            field=models.BooleanField(default=True, help_text='Documentation readiness checks'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='security_alerts_enabled',
            field=models.BooleanField(default=True, help_text='Security alerts, incidents, SIEM endpoints and weekly digests'),
        ),
        migrations.AddField(
            model_name='systemsetting',
            name='status_pages_enabled',
            field=models.BooleanField(default=True, help_text='Status pages (public and customer portal)'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='crm_enabled',
            field=models.BooleanField(default=True, help_text='Enable CRM / sales pipeline (leads, opportunities, campaigns, commissions)'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='psa_enabled',
            field=models.BooleanField(default=True, help_text='Enable native PSA / Service Desk feature'),
        ),
        migrations.AlterField(
            model_name='systemsetting',
            name='pulse_enabled',
            field=models.BooleanField(default=True, help_text='Enable pulse checks: periodic service-feedback surveys sent to people at client organizations'),
        ),
    ]
