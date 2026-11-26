"""The Setup Assistant's install session (Phase 96.2).

Not purely additive: `organization` is relaxed from NOT NULL to NULL so an
install-wide session can exist before any organization does. A check
constraint keeps every other kind tied to a tenant, so existing customer
onboarding rows and queries are unaffected.

Reverse: deletes the install sessions (their step answers only; the settings
they wrote stay), then restores NOT NULL.
"""
import django.db.models.deletion
from django.db import migrations, models


def delete_install_sessions(apps, schema_editor):
    S = apps.get_model('onboarding', 'OnboardingSession')
    S.objects.using(schema_editor.connection.alias).filter(kind='install').delete()


KINDS = [('new_customer', 'New customer onboarding'), ('plan_change', 'Plan change'),
         ('add_users', 'Add users'), ('remove_users', 'Remove users'), ('add_devices', 'Add devices'),
         ('remove_devices', 'Remove devices'), ('add_location', 'Add location'), ('renewal', 'Renewal'),
         ('price_increase', 'Price increase'), ('offboarding', 'Offboarding'),
         ('install', 'Setup Assistant')]


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0126_systemsetting_setup_assistant'),
        ('onboarding', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='onboardingsession',
            name='kind',
            field=models.CharField(choices=KINDS, default='new_customer', max_length=20),
        ),
        migrations.AlterField(
            model_name='onboardingsession',
            name='organization',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='onboarding_sessions', to='core.organization',
                help_text='The tenant the session belongs to (empty for the Setup Assistant).'),
        ),
        migrations.RunPython(migrations.RunPython.noop, delete_install_sessions),
        migrations.AddConstraint(
            model_name='onboardingsession',
            constraint=models.CheckConstraint(
                condition=models.Q(organization__isnull=False) | models.Q(kind='install'),
                name='onboarding_tenant_unless_install'),
        ),
    ]
