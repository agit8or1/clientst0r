from django.apps import AppConfig


class TaxConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tax'
    verbose_name = 'Sales tax'

    def ready(self):
        from . import signals  # noqa: F401
