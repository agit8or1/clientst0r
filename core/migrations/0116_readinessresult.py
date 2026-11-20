from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0115_scheduledtask_events_tick'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReadinessResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100, unique=True)),
                ('data', models.JSONField(default=dict)),
                ('checked_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'core_readiness_result',
            },
        ),
    ]
