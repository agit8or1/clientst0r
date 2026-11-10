from django.apps import AppConfig


class DocsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'docs'
    verbose_name = 'Documentation'

    def ready(self):
        from . import signals  # noqa: F401  agreement revisions on document save
