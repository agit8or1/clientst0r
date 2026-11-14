from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Additive: two small per-user tables for the top bar's Favorites and
    Recent menus and the command palette (core.palette)."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0101_portal_branding_layout'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageFavorite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='page_favorites', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_page_favorites',
                'ordering': ['-created_at'],
                'unique_together': {('user', 'path')},
            },
        ),
        migrations.CreateModel(
            name='RecentPage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('path', models.CharField(max_length=255)),
                ('visited_at', models.DateTimeField(db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='recent_pages', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_recent_pages',
                'ordering': ['-visited_at'],
                'unique_together': {('user', 'path')},
                'indexes': [models.Index(fields=['user', '-visited_at'], name='core_recent_user_id_2897aa_idx')],
            },
        ),
    ]
