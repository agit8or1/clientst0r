from django.contrib.auth.backends import ModelBackend


class OIDCBackend(ModelBackend):
    """Session backend for users signed in by oidc_sso.

    authenticate() never accepts credentials: sign-in happens only in the
    callback view after the ID token is validated, which calls login() with
    this backend so the session records how the user signed in.
    """

    def authenticate(self, request, **kwargs):
        return None
