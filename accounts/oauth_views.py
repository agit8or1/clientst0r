"""
OAuth authentication views for Azure AD
"""
from django.shortcuts import redirect
from django.contrib.auth import login
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.http import url_has_allowed_host_and_scheme
from .azure_auth import AzureOAuthClient, AzureADBackend
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

    # Set session to bypass 2FA for Azure AD users (SSO is already secure)
    request.session['azure_ad_authenticated'] = True

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
