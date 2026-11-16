from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver


@receiver(user_logged_out, dispatch_uid='oidc_sso_forget_session')
def _forget_session(sender, request=None, **kwargs):
    if request is None:
        return
    from .sessions import forget_session_key
    try:
        forget_session_key(request.session.session_key)
    except Exception:
        pass
