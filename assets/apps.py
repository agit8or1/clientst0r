from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assets'
    verbose_name = 'Assets'

    def ready(self):
        from . import serial_lifecycle
        serial_lifecycle.connect()
