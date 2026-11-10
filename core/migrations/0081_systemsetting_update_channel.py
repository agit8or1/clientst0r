from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0080_systemsetting_latest_release'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsetting',
            name='update_channel',
            field=models.CharField(
                choices=[('stable', 'Stable: latest signed published release'),
                         ('preview', 'Preview: newest commit on main (unreleased)')],
                default='stable', max_length=10),
        ),
    ]
