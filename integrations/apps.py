from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations'
    verbose_name = 'Integrations'

    def ready(self):
        from .m365docs import signals  # noqa: F401  (Edit in Microsoft 365 revocation hooks)
