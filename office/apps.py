from django.apps import AppConfig


class OfficeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'office'
    verbose_name = 'Office Documents'

    def ready(self):
        from . import signals  # noqa: F401  (revocation hooks)
        from .logging_filters import install_office_log_filter
        install_office_log_filter()
        from . import providers  # noqa: F401  (registers the provider stubs)
