from django.apps import AppConfig


class ConnectConfig(AppConfig):
    name = 'connect'
    verbose_name = 'Agit8or Connect'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Registers the protected-change applier for elevated app grants.
        from . import approvals  # noqa: F401
        self._sweep_tls_leftovers()

    @staticmethod
    def _sweep_tls_leftovers():
        """Startup sweep: TLS material a killed worker may have left in the
        fallback private directory (or in the temp dir, from releases that
        wrote the mTLS key there per request)."""
        from django.conf import settings
        if not getattr(settings, 'AGIT8OR_CONNECT_ENABLED', False):
            return
        try:
            from agit8or_connect.adapters.safe_http import sweep_leftovers
            sweep_leftovers()
        except Exception:  # never block start-up
            import logging
            logging.getLogger('connect').warning('Connect TLS leftover sweep failed', exc_info=True)
