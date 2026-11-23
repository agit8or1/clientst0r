"""
OAuth authentication views for Azure AD
"""
from django.shortcuts import redirect
from django.contrib.auth import login
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit
from audit.models import AuditLog
from core.safe_redirect import safe_next
from .azure_auth import (
    MESSAGES, AzureIdentityError, AzureOAuthClient, azure_mfa_asserted, load_azure_config,
    resolve_sso_user, verify_id_token,
)
import logging

logger = logging.getLogger('accounts')


FLOW_SESSION_KEY = 'azure_auth_flow'
LINK_SESSION_KEY = 'azure_link_intent'
LINK_INTENT_SECONDS = 600


def _start_flow(request, prompt=None):
    client = AzureOAuthClient()
    if not client.is_enabled():
        return None, MESSAGES['not_configured']
    # MSAL's flow carries the state, the nonce and the PKCE verifier; it stays
    # server-side in the session until the callback (v3.17.688).
    flow = client.initiate_flow(prompt=prompt)
    if not flow:
        return None, "Failed to generate Azure AD login URL."
    request.session[FLOW_SESSION_KEY] = flow
    request.session.pop('azure_oauth_state', None)  # pre-v3.17.688 key
    return flow, None


@require_http_methods(["GET"])
def azure_login(request):
    """Redirect the user to Microsoft (auth code flow with PKCE, nonce and state)."""
    request.session.pop(LINK_SESSION_KEY, None)
    flow, err = _start_flow(request)
    if err:
        messages.error(request, err)
        return redirect('two_factor:login')
    return redirect(flow['auth_uri'])


@login_required
@ratelimit(key='user', rate='10/15m', method='POST', block=False)
@require_POST
def azure_link_start(request):
    """Link the signed-in user's account to a Microsoft identity (v3.17.688).

    The user re-enters their password (and authenticator code when they have
    one) here; the Microsoft identity they then sign in with is linked to this
    account. This and an administrator confirming a recorded request are the
    only ways an existing account becomes linked.
    """
    from tech_access.protected import verify_credentials
    if getattr(request, 'limited', False):
        messages.error(request, 'Too many attempts. Wait a few minutes and try again.')
        return redirect('accounts:profile')
    error = verify_credentials(request.user, request.POST.get('password', ''), request.POST.get('otp', ''))
    if error:
        AuditLog.log(user=request.user, action='login_failed', success=False,
                     description='Re-authentication to link Microsoft sign-in failed',
                     ip_address=request.META.get('REMOTE_ADDR'),
                     extra_data={'event': 'azure_sso_link_reauth_failed'})
        messages.error(request, error)
        return redirect('accounts:profile')
    flow, err = _start_flow(request, prompt='select_account')
    if err:
        messages.error(request, err)
        return redirect('accounts:profile')
    request.session[LINK_SESSION_KEY] = {'user_id': request.user.pk,
                                         'at': int(timezone.now().timestamp())}
    return redirect(flow['auth_uri'])


@login_required
@require_POST
def azure_unlink(request):
    """Remove the signed-in user's own Microsoft link."""
    from .azure_auth import unlink_identity
    if not request.user.has_usable_password():
        messages.error(request, 'This account has no password; unlinking Microsoft sign-in would '
                                'lock you out. Ask an administrator.')
        return redirect('accounts:profile')
    unlink_identity(request.user, request.user, request=request)
    messages.success(request, 'Microsoft sign-in unlinked.')
    return redirect('accounts:profile')


def _finish_link(request, intent, identity):
    from .azure_auth import link_identity
    now = int(timezone.now().timestamp())
    if (not request.user.is_authenticated or not isinstance(intent, dict)
            or intent.get('user_id') != request.user.pk
            or not isinstance(intent.get('at'), int)
            or not (0 <= now - intent['at'] <= LINK_INTENT_SECONDS)):
        messages.error(request, 'The link request expired. Start again from My Profile.')
        return redirect('accounts:profile' if request.user.is_authenticated else 'two_factor:login')
    err = link_identity(request.user, identity, request.user, 'self', request=request)
    if err == 'in_use':
        messages.error(request, 'That Microsoft account is already linked to another account here.')
    elif err:
        messages.error(request, MESSAGES.get(err, 'Linking failed.'))
    else:
        messages.success(request, 'Microsoft sign-in is now linked to your account.')
    return redirect('accounts:profile')


@csrf_exempt  # SECURITY EXCEPTION: OAuth callback; CSRF protection is the state + PKCE of the session's flow
@require_http_methods(["GET"])
def azure_callback(request):
    """
    Handle the OAuth callback from Microsoft.

    SECURITY NOTE: @csrf_exempt is required because OAuth callbacks don't
    include Django CSRF tokens. The flow kept in this session supplies the
    state (checked by MSAL), the PKCE verifier and the nonce; the ID token is
    then verified by verify_id_token and matched on (tid, oid) only.
    """
    error = request.GET.get('error')
    flow = request.session.pop(FLOW_SESSION_KEY, None)
    intent = request.session.pop(LINK_SESSION_KEY, None)
    fail_to = 'accounts:profile' if intent and request.user.is_authenticated else 'two_factor:login'

    if error:
        error_description = request.GET.get('error_description')
        logger.error(f"Azure AD OAuth error: {error} - {error_description}")
        messages.error(request, f"Azure AD login failed: {error_description or error}")
        return redirect(fail_to)

    if not request.GET.get('code'):
        messages.error(request, "No authorization code received from Azure AD.")
        return redirect(fail_to)

    if not isinstance(flow, dict) or not request.GET.get('state') or request.GET.get('state') != flow.get('state'):
        logger.warning("Azure OAuth state mismatch or no flow in session - possible CSRF attack")
        messages.error(request, "Invalid authentication state. Please try again.")
        return redirect(fail_to)

    client = AzureOAuthClient()
    token_response = client.complete_flow(flow, request.GET.dict())
    if not token_response:
        messages.error(
            request,
            "Failed to obtain a token from Azure AD. "
            "This may happen if you clicked the login button multiple times, or if there's a configuration issue. "
            "Please try again. If the problem persists, contact your administrator."
        )
        return redirect(fail_to)

    config = load_azure_config()
    if not config:
        messages.error(request, MESSAGES['not_configured'])
        return redirect(fail_to)
    try:
        identity = verify_id_token(token_response.get('id_token'), config, flow.get('nonce'))
    except AzureIdentityError as e:
        AuditLog.log(user=None, action='login_failed', success=False,
                     description='Microsoft ID token rejected', ip_address=request.META.get('REMOTE_ADDR'),
                     extra_data={'event': 'azure_sso_token_rejected', 'code': e.code, 'detail': e.detail[:300]})
        logger.warning(f"Azure AD ID token rejected ({e.code}): {e.detail}")
        messages.error(request, MESSAGES.get(e.code, MESSAGES['invalid_token']))
        return redirect(fail_to)

    if intent:
        return _finish_link(request, intent, identity)

    user, err = resolve_sso_user(identity, config, request)
    if user is None:
        text = MESSAGES.get(err, "Authentication failed. Please contact your administrator.")
        if err == 'no_account' and identity.email:
            text = f'{text} You signed in as {identity.email}.'
        messages.error(request, text)
        return redirect('two_factor:login')

    login(request, user, backend='accounts.azure_auth.AzureADBackend')
    AuditLog.objects.create(
        action='login', user=user, username=user.username,
        description='User logged in via Azure AD', ip_address=request.META.get('REMOTE_ADDR'),
        extra_data={'auth_source': 'azure_ad', 'tid': identity.tid, 'oid': identity.oid},
    )

    # A Microsoft sign-in stands in for ClientSt0r's 2FA only when Microsoft
    # confirms MFA (or the operator trusts the tenant); otherwise
    # Enforce2FAMiddleware asks for the user's authenticator code, or for
    # enrolment, as after a password sign-in (v3.17.660).
    request.session['azure_ad_authenticated'] = True
    request.session['azure_ad_mfa'] = azure_mfa_asserted(token_response)

    messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")

    # Redirect to dashboard or next URL (with security validation to prevent open redirect)
    next_url = request.GET.get('next', '/core/dashboard/')
    safe_url = safe_next(request, next_url, '')
    if safe_url:
        return redirect(safe_url)
    if next_url and next_url != '/core/dashboard/':
        logger.warning(f"Blocked potentially malicious redirect to: {next_url}")
    return redirect('/core/dashboard/')


@login_required
@require_POST
def azure_link_request_decide(request, user_id, request_id):
    """An administrator approves or rejects a recorded link request (v3.17.688).

    Approving needs the administrator's own password (and authenticator code)
    and is refused for their own account.
    """
    from django.shortcuts import get_object_or_404
    from django.contrib.auth.models import User
    from tech_access.protected import verify_credentials
    from .azure_auth import approve_link_request
    from .models import AzureADLinkRequest
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to do that.")
        return redirect('core:dashboard')
    target = get_object_or_404(User, pk=user_id)
    link_request = get_object_or_404(AzureADLinkRequest, pk=request_id, user=target)
    decision = request.POST.get('decision')
    if decision == 'reject':
        if link_request.status == 'pending':
            AzureADLinkRequest.objects.filter(pk=link_request.pk).update(
                status='rejected', decided_at=timezone.now(), decided_by=request.user)
            AuditLog.log(user=request.user, action='update', object_type='User', object_id=target.pk,
                         object_repr=str(target), ip_address=request.META.get('REMOTE_ADDR'),
                         description='Microsoft sign-in link request rejected',
                         extra_data={'event': 'azure_sso_link_rejected', 'request_id': link_request.pk})
        messages.success(request, 'Link request rejected.')
        return redirect('accounts:user_detail', user_id=target.pk)
    if decision != 'approve':
        return redirect('accounts:user_detail', user_id=target.pk)
    error = verify_credentials(request.user, request.POST.get('password', ''), request.POST.get('otp', ''))
    if error:
        messages.error(request, error)
        return redirect('accounts:user_detail', user_id=target.pk)
    err = approve_link_request(link_request, request.user, request=request)
    if err == 'own_account':
        messages.error(request, 'You cannot confirm a link to your own account. Link it from My Profile.')
    elif err == 'in_use':
        messages.error(request, 'That Microsoft identity is already linked to another account.')
    elif err:
        messages.error(request, 'This request can no longer be approved.')
    else:
        messages.success(request, 'Microsoft sign-in linked.')
    return redirect('accounts:user_detail', user_id=target.pk)


@login_required
@require_POST
def azure_admin_unlink(request, user_id):
    """An administrator removes a user's Microsoft link (narrowing; audited)."""
    from django.shortcuts import get_object_or_404
    from django.contrib.auth.models import User
    from .azure_auth import unlink_identity
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to do that.")
        return redirect('core:dashboard')
    target = get_object_or_404(User, pk=user_id)
    unlink_identity(target, request.user, request=request)
    messages.success(request, 'Microsoft sign-in unlinked.')
    return redirect('accounts:user_detail', user_id=target.pk)


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
    return safe_next(request, next_url, default)


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
