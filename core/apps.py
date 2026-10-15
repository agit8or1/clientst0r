from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core'

    def ready(self):
        # Outbound webhook events (asset/document/password/location/user/
        # organization/workflow). Monitor and integration events are fired
        # from their service code.
        from core import webhook_signals
        webhook_signals.connect()
        # Drop the cached Security settings whenever SystemSetting is saved.
        from core import security_policy
        security_policy._connect_signals()
