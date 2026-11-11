from django.apps import AppConfig


class SupportWorkflowsConfig(AppConfig):
    name = 'psa.support_workflows'
    label = 'support_workflows'
    verbose_name = 'Support Workflows'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from . import receivers  # noqa: F401
