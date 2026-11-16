from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'onboarding'
    verbose_name = 'Customer Onboarding'

    def ready(self):
        # Registers the built-in steps. Other apps contribute theirs the same
        # way (see docs/plans/ONBOARDING_STEPS.md).
        from . import steps  # noqa: F401
