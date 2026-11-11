from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tech_access', '0005_assignment_approval_and_revoker'),
    ]

    operations = [
        migrations.AlterField(
            model_name='protectedchange',
            name='kind',
            field=models.CharField(choices=[('assignment', 'Technician access assignment'), ('preset', 'Preset capabilities'), ('group_members', 'Group membership'), ('business_mapping', 'RMM business mapping'), ('approvers', 'Approvers'), ('recovery_contact', 'Recovery contact'), ('provider_destination', 'AI provider destination'), ('security_limits', 'Security limits'), ('account_email', 'Account e-mail address'), ('superuser_grant', 'Superuser grant'), ('superuser_policy', 'Superuser-grant approval policy'), ('global_role', 'Global role with an RMM tier'), ('rmm_tier', 'Role template RMM tier')], max_length=30),
        ),
    ]
