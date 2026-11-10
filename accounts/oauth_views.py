"""
OAuth authentication views for Azure AD
"""
from django.shortcuts import redirect
from django.contrib.auth import login
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.http import url_has_allowed_host_and_scheme
from django_ratelimit.decorators import ratelimit
from .azure_auth import AzureOAuthClient, AzureADBackend, azure_mfa_asserted
import logging

logger = logging.getLogger('accounts')


@require_http_methods(["GET"])
def azure_login(request):
    """
    Redirect user to Azure AD login page with CSRF state protection.
    """
    import secrets

    client = AzureOAuthClient()

    if not client.is_enabled():
        messages.error(request, "Azure AD authentication is not configured.")
        return redirect('two_factor:login')

    # FIX: Generate cryptographically secure state token for CSRF protection
    state = secrets.token_urlsafe(32)
    request.session['azure_oauth_state'] = state

    # Get authorization URL with state parameter
    auth_url = client.get_authorization_url(state=state)
    if not auth_url:
        messages.error(request, "Failed to generate Azure AD login URL.")
        return redirect('two_factor:login')

    # Redirect to Azure login
    return redirect(auth_url)


@csrf_exempt  # SECURITY EXCEPTION: Azure OAuth callback uses state parameter for CSRF protection
@require_http_methods(["GET"])
def azure_callback(request):
    """
    Handle OAuth callback from Azure AD.
    Exchange authorization code for token and authenticate user.

    SECURITY NOTE: @csrf_exempt is required because OAuth callbacks don't include
    Django CSRF tokens. CSRF protection is provided by OAuth 2.0 state parameter
    validation, which prevents authorization code interception attacks.
    """
    # Get authorization code and state from query params
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')
    error_description = request.GET.get('error_description')

    if error:
        logger.error(f"Azure AD OAuth error: {error} - {error_description}")
        messages.error(request, f"Azure AD login failed: {error_description or error}")
        return redirect('two_factor:login')

    if not code:
        messages.error(request, "No authorization code received from Azure AD.")
        return redirect('two_factor:login')

    # FIX: Validate state parameter for CSRF protection
    session_state = request.session.get('azure_oauth_state')
    if not state or not session_state or state != session_state:
        logger.warning(f"Azure OAuth state mismatch - possible CSRF attack. Expected: {session_state}, Got: {state}")
        messages.error(request, "Invalid authentication state. Please try again.")
        return redirect('two_factor:login')

    # Clear state after use (single-use token)
    request.session.pop('azure_oauth_state', None)

    # Exchange code for token
    client = AzureOAuthClient()
    token_response = client.get_token_from_code(code)

    if not token_response or 'access_token' not in token_response:
        # Provide more helpful error message
        logger.error(f"Azure AD token exchange failed for user attempting login")
        messages.error(
            request,
            "Failed to obtain access token from Azure AD. "
            "This may happen if you clicked the login button multiple times, or if there's a configuration issue. "
            "Please try again. If the problem persists, contact your administrator."
        )
        return redirect('two_factor:login')

    # Authenticate user with token
    backend = AzureADBackend()
    user = backend.authenticate(request, azure_token=token_response)

    if user is None:
        messages.error(request, "Authentication failed. Please contact your administrator.")
        return redirect('two_factor:login')

    # Log user in
    login(request, user, backend='accounts.azure_auth.AzureADBackend')

    # A Microsoft sign-in stands in for ClientSt0r's 2FA only when Microsoft
    # confirms MFA (or the operator trusts the tenant); otherwise
    # Enforce2FAMiddleware asks for the user's authenticator code, or for
    # enrolment, as after a password sign-in (v3.17.660).
    request.session['azure_ad_authenticated'] = True
    request.session['azure_ad_mfa'] = azure_mfa_asserted(token_response)

    messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")

    # Redirect to dashboard or next URL (with security validation to prevent open redirect)
    next_url = request.GET.get('next', '/core/dashboard/')

    # Validate redirect URL to prevent open redirect attacks
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure()
    ):
        return redirect(next_url)
    else:
        # If next_url is invalid or points to external site, redirect to dashboard
        if next_url and next_url != '/core/dashboard/':
            logger.warning(f"Blocked potentially malicious redirect to: {next_url}")
        return redirect('/core/dashboard/')


@require_http_methods(["GET"])
def azure_status(request):
    """
    Check if Azure AD SSO is enabled.
    Used by login page to show/hide Azure button.
    """
    from django.http import JsonResponse
    client = AzureOAuthClient()

    # Basic response for login page
    response = {
        'enabled': client.is_enabled()
    }

    # Add diagnostic info for admins/superusers
    if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        response['debug'] = {
            'azure_ad_enabled': client.config.get('enabled', False),
            'has_tenant_id': bool(client.config.get('tenant_id')),
            'has_client_id': bool(client.config.get('client_id')),
            'has_client_secret': bool(client.config.get('client_secret')),
            'has_redirect_uri': bool(client.config.get('redirect_uri')),
        }

    return JsonResponse(response)


# After this many wrong codes the SSO session is ended (v3.17.660).
SSO_VERIFY_MAX_FAILURES = 5


def _safe_next(request, default='/core/dashboard/'):
    next_url = request.POST.get('next') or request.GET.get('next') or default
    if url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return next_url
    return default


@ratelimit(key='user_or_ip', rate='10/15m', method='POST', block=False)
@require_http_methods(['GET', 'POST'])
def azure_verify(request):
    """Ask a Microsoft-signed-in user for their ClientSt0r authenticator code
    when Microsoft didn't confirm MFA for the sign-in (v3.17.660).

    Enforce2FAMiddleware sends such sessions here instead of ending them
    (they may have no local password to restart the 2FA login with). A
    correct code verifies the session exactly like the 2FA login does; too
    many wrong ones end it.
    """
    from django.contrib.auth import logout
    from django.shortcuts import render
    from django_otp import devices_for_user, login as otp_login
    from audit.models import AuditLog

    if not request.user.is_authenticated or not request.session.get('azure_ad_authenticated', False):
        return redirect('two_factor:login')
    is_verified = getattr(request.user, 'is_verified', None)
    if callable(is_verified) and is_verified():
        return redirect(_safe_next(request))

    error = None
    if request.method == 'POST':
        token = (request.POST.get('token') or '').replace(' ', '').strip()
        if getattr(request, 'limited', False):
            error = 'Too many attempts. Wait a few minutes and try again.'
        elif not token or len(token) > 16 or not token.isalnum():
            error = 'Enter the code from your authenticator app, or a backup code.'
        else:
            device = next((d for d in devices_for_user(request.user, confirmed=True)
                           if d.verify_token(token)), None)
            if device is not None:
                otp_login(request, device)
                request.session.pop('azure_verify_failures', None)
                AuditLog.log(user=request.user, action='login', description=(
                    'Microsoft sign-in completed with the ClientSt0r authenticator '
                    '(Microsoft did not confirm MFA)'),
                    ip_address=request.META.get('REMOTE_ADDR'),
                    extra_data={'event': 'azure_sso_2fa_verified'})
                return redirect(_safe_next(request))
            failures = request.session.get('azure_verify_failures', 0) + 1
            request.session['azure_verify_failures'] = failures
            AuditLog.log(user=request.user, action='login_failed', success=False,
                         description=f'Wrong authenticator code after Microsoft sign-in ({failures})',
                         ip_address=request.META.get('REMOTE_ADDR'),
                         extra_data={'event': 'azure_sso_2fa_failed', 'failures': failures})
            if failures >= SSO_VERIFY_MAX_FAILURES:
                logout(request)
                messages.error(request, 'Too many wrong codes. Sign in again.')
                return redirect('two_factor:login')
            error = 'That code is not valid. Try again.'
    return render(request, 'accounts/sso_verify.html', {
        'error': error, 'next': _safe_next(request),
    }, status=400 if error else 200)
