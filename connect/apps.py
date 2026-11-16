from django.apps import AppConfig


class ConnectConfig(AppConfig):
    name = 'connect'
    verbose_name = 'Agit8or Connect'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Registers the protected-change applier for elevated app grants.
        from . import approvals  # noqa: F401
