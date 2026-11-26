from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core'

    def ready(self):
        # Decode only the image formats we accept, whatever a file is called
        # (v3.17.629). Must run before any upload is validated.
        from core.image_safety import restrict_decoders
        restrict_decoders()
        # Outbound webhook events (asset/document/password/location/user/
        # organization/workflow). Monitor and integration events are fired
        # from their service code.
        from core import webhook_signals
        webhook_signals.connect()
        # Drop the cached Security settings whenever SystemSetting is saved.
        from core import security_policy
        security_policy._connect_signals()
        # v3.17.681: a role's landing page applies to the first dashboard
        # view after sign-in (core.dashboard_views.note_sign_in).
        from django.contrib.auth.signals import user_logged_in
        from core.dashboard_views import note_sign_in
        user_logged_in.connect(note_sign_in, dispatch_uid='core.dashboard_landing')
        # Roadmap 113.10: drop the application switcher's cached entries when
        # a connection, customer mapping or RMM connection changes here.
        from core import app_switcher
        app_switcher.connect_signals()
        # First-install Setup Assistant (Phase 96): its steps on the
        # onboarding engine, and the sign-in hook that arms the offer.
        from core import setup_assistant, setup_assistant_steps
        setup_assistant_steps.register()
        user_logged_in.connect(setup_assistant.note_sign_in, dispatch_uid='core.setup_assistant_due')
