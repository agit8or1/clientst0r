"""Which single sign-on sessions stand in for Clientst0r's own 2FA.

One place for Enforce2FAMiddleware to ask, whatever signed the user in:

  * Microsoft (accounts.azure_auth.azure_sso_counts_as_2fa): Microsoft
    confirmed MFA, or AZURE_SSO_TRUSTED_AS_2FA is set.
  * A generic OIDC provider (oidc_sso): the provider is set to accept the
    identity provider's MFA *and* the ID token's acr / amr met the values
    configured for it. The callback decides that once, at sign-in, and
    records it in the session (oidc_sso.mfa.SESSION_MFA); nothing here
    re-reads claims.

Neither fakes a django-otp device: the session is not "OTP verified", the
middleware simply does not ask for the local code. An SSO session that does
not qualify is sent to that provider's "enter your authenticator code" page
instead of being ended (the user may have no local password to restart with).
"""

# Session keys written by oidc_sso at sign-in (kept here so the middleware
# does not import the app).
OIDC_SESSION_FLAG = 'oidc_sso_authenticated'
OIDC_SESSION_MFA = 'oidc_sso_mfa'


def oidc_sso_counts_as_2fa(request) -> bool:
    session = request.session
    return bool(session.get(OIDC_SESSION_FLAG, False) and session.get(OIDC_SESSION_MFA, False))


def sso_counts_as_2fa(request) -> bool:
    from .azure_auth import azure_sso_counts_as_2fa
    return bool(azure_sso_counts_as_2fa(request) or oidc_sso_counts_as_2fa(request))


def sso_kind(request) -> str:
    """'azure', 'oidc' or '' — which SSO signed this session in."""
    session = request.session
    if session.get('azure_ad_authenticated', False):
        return 'azure'
    if session.get(OIDC_SESSION_FLAG, False):
        return 'oidc'
    return ''


def sso_verify_url(request):
    """Where an SSO session without accepted MFA enters the local code, or None."""
    from django.urls import NoReverseMatch, reverse
    kind = sso_kind(request)
    try:
        if kind == 'azure':
            return reverse('accounts:azure_verify')
        if kind == 'oidc':
            return reverse('oidc_sso:verify')
    except NoReverseMatch:
        return None
    return None
