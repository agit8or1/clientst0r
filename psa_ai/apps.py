from django.apps import AppConfig


class PsaAiConfig(AppConfig):
    name = 'psa_ai'
    verbose_name = 'PSA AI Assist'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # My Work panels for remote session launches and remote jobs.
        from .workspace_sources import register
        register()
