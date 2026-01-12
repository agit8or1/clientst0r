"""
OAuth authentication views for Azure AD
"""
from django.shortcuts import redirect
from django.contrib.auth import login
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .azure_auth import AzureOAuthClient, AzureADBackend
import logging

logger = logging.getLogger('accounts')


@require_http_methods(["GET"])
def azure_login(request):
    """
    Redirect user to Azure AD login page.
    """
    client = AzureOAuthClient()

    if not client.is_enabled():
        messages.error(request, "Azure AD authentication is not configured.")
        return redirect('two_factor:login')

    # Get authorization URL
    auth_url = client.get_authorization_url()
    if not auth_url:
        messages.error(request, "Failed to generate Azure AD login URL.")
        return redirect('two_factor:login')

    # Redirect to Azure login
    return redirect(auth_url)


@csrf_exempt  # Azure callback doesn't include CSRF token
@require_http_methods(["GET"])
def azure_callback(request):
    """
    Handle OAuth callback from Azure AD.
    Exchange authorization code for token and authenticate user.
    """
    # Get authorization code from query params
    code = request.GET.get('code')
    error = request.GET.get('error')
    error_description = request.GET.get('error_description')

    if error:
        logger.error(f"Azure AD OAuth error: {error} - {error_description}")
        messages.error(request, f"Azure AD login failed: {error_description or error}")
        return redirect('two_factor:login')

    if not code:
        messages.error(request, "No authorization code received from Azure AD.")
        return redirect('two_factor:login')

    # Exchange code for token
    client = AzureOAuthClient()
    token_response = client.get_token_from_code(code)

    if not token_response or 'access_token' not in token_response:
        messages.error(request, "Failed to obtain access token from Azure AD.")
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

    # Redirect to dashboard or next URL
    next_url = request.GET.get('next', '/core/dashboard/')
    return redirect(next_url)


@require_http_methods(["GET"])
def azure_status(request):
    """
    Check if Azure AD SSO is enabled.
    Used by login page to show/hide Azure button.
    """
    from django.http import JsonResponse
    client = AzureOAuthClient()
    return JsonResponse({
        'enabled': client.is_enabled()
    })
