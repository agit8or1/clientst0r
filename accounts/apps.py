from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'Accounts'

    def ready(self):
        # Encrypt TOTP seeds / hash backup codes stored by django-otp.
        # Not wrapped in try/except on purpose: if this cannot be installed,
        # starting up would write 2FA secrets in plaintext.
        from .otp_storage import install
        install()
