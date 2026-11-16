from django.apps import AppConfig


class OidcSsoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'oidc_sso'
    verbose_name = 'Single sign-on (OIDC)'

    def ready(self):
        from . import signals  # noqa: F401
