from django.apps import AppConfig


class TechAccessConfig(AppConfig):
    name = 'tech_access'
    verbose_name = 'Technician Access'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from . import signals  # noqa: F401  superuser grants outside approval
