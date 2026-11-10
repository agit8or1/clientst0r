from django.apps import AppConfig


class TicketRoutingConfig(AppConfig):
    name = 'psa.routing'
    label = 'ticket_routing'
    verbose_name = 'Ticket Routing'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from . import signals  # noqa: F401
