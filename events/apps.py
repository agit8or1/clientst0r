from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'events'
    verbose_name = 'Operational events'

    def ready(self):
        from . import signals  # noqa: F401  (queue source changes for projection)
