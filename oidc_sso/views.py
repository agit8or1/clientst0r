"""Sign-in, linking, step-up, verification and logout endpoints.

Every endpoint of a provider returns 404 while the provider is disabled.
Local, Microsoft and LDAP sign-in are unaffected by anything here; a local
superuser can always sign in at /account/login/ (break-glass).
"""
import logging
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from accounts.sso_mfa import OIDC_SESSION_FLAG, OIDC_SESSION_MFA

from . import audit, claims as claimlib, client, keys, mapping, sessions
from .http import OPError
from .models import OIDCIdentity, OIDCProvider, ReplayRecord
from .tokens import TokenError, validate_id_token, validate_logout_token

logger = logging.getLogger('oidc_sso')

BACKEND = 'oidc_sso.backends.OIDCBackend'
DEFAULT_NEXT = '/core/dashboard/'
# Session keys (besides accounts.sso_mfa's flag / mfa keys).
S_PROVIDER, S_SID, S_SUB, S_ID_TOKEN, S_AUTH_TIME = (
    'oidc_sso_provider', 'oidc_sso_sid', 'oidc_sso_sub', 'oidc_sso_id_token', 'oidc_sso_auth_time')
VERIFY_MAX_FAILURES = 5

_USERINFO_PROTECTED = {'iss', 'aud', 'sub', 'azp', 'nonce', 'exp', 'iat', 'nbf', 'auth_time', 'acr', 'amr',
                       'sid', 'at_hash', 'jti'}


def enabled_provider(slug):
    provider = OIDCProvider.objects.filter(slug=slug, enabled=True).first()
    if provider is None:
        raise Http404('No such sign-in provider')
    return provider


def _safe_next(request, value, default=DEFAULT_NEXT):
    if value and url_has_allowed_host_and_scheme(url=value, allowed_hosts={request.get_host()},
                                                 require_https=request.is_secure()):
        return value
    return default


def _no_referrer(response):
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response


# --- sign-in ----------------------------------------------------------------------------

@never_cache
@require_GET
def login_start(request, slug):
    provider = enabled_provider(slug)
    next_url = _safe_next(request, request.GET.get('next'))
    if request.user.is_authenticated:
        return redirect(next_url)
    try:
        url = client.start(request, provider, client.MODE_LOGIN, next_url,
                           acr_values=provider.login_acr_values.strip())
    except OPError as exc:
        audit.log('sso_login_denied', request=request, provider=provider, success=False,
                  reason='op_unavailable', detail=str(exc), description=f'{provider.name} unavailable')
        messages.error(request, f'{provider.name} is not reachable right now. Sign in another way or try again.')
        return redirect('two_factor:login')
    return _no_referrer(redirect(url))


class _Denied(Exception):
    def __init__(self, reason, message, user=None, **extra):
        super().__init__(reason)
        self.reason, self.message, self.user, self.extra = reason, message, user, extra


def _deny(request, provider, mode, denied):
    audit.log('sso_login_denied', request=request, user=denied.user, provider=provider, success=False,
              reason=denied.reason, mode=mode, description=f'{provider.name}: {denied.reason}',
              **denied.extra)
    messages.error(request, denied.message)
    if mode == client.MODE_LOGIN or not request.user.is_authenticated:
        return _no_referrer(redirect('two_factor:login'))
    return _no_referrer(redirect('oidc_sso:account'))


@never_cache
@require_GET
def callback(request, slug):
    provider = enabled_provider(slug)
    state = request.GET.get('state', '')
    flow = client.pop_pending(request, state)
    mode = (flow or {}).get('mode', client.MODE_LOGIN)
    try:
        if flow is None or flow.get('provider') != provider.pk:
            raise _Denied('bad_state', 'That sign-in link has expired or was already used. Please start again.')
        if request.GET.get('error'):
            raise _Denied('op_error', f'{provider.name} did not sign you in.',
                          op_error=request.GET.get('error', '')[:60])
        code = request.GET.get('code', '')
        if not code or len(code) > 4096:
            raise _Denied('no_code', 'The sign-in did not complete. Please start again.')
        try:
            tokens = client.exchange_code(provider, code, flow)
            claims = validate_id_token(provider, tokens['id_token'], nonce=flow['nonce'],
                                       max_age=flow.get('max_age'), access_token=tokens.get('access_token'))
            if provider.use_userinfo:
                info = client.fetch_userinfo(provider, tokens.get('access_token'))
                if info is not None:
                    if info.get('sub') != claims['sub']:
                        raise TokenError('userinfo_sub', 'userinfo sub differs from the ID token')
                    for k, v in info.items():
                        if k not in _USERINFO_PROTECTED:
                            claims.setdefault(k, v)
        except OPError as exc:
            raise _Denied('token_exchange_failed', f'{provider.name} sign-in failed. Please try again.',
                          detail=str(exc))
        except TokenError as exc:
            raise _Denied(exc.reason, f'{provider.name} sign-in could not be verified. Please try again.',
                          detail=str(exc))
        try:
            claimlib.check_msp_pin(provider, claims)
        except TokenError as exc:
            raise _Denied(exc.reason, 'Your account is not part of this organization at '
                                      f'{provider.name}.', sub=claims.get('sub'))
        if mode == client.MODE_LINK:
            return _finish_link(request, provider, flow, claims)
        if mode == client.MODE_STEPUP:
            return _finish_stepup(request, provider, flow, claims)
        return _finish_login(request, provider, flow, claims, tokens.get('id_token'))
    except _Denied as denied:
        return _deny(request, provider, mode, denied)


def _jit_username(email, preferred):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    import re
    base = re.sub(r'[^\w.@+-]', '', (email.split('@')[0] if email else preferred) or 'sso-user')[:120] or 'sso-user'
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f'{base}{n}'
    return candidate


def _jit_create(request, provider, claims, roles, result):
    from django.contrib.auth import get_user_model
    from accounts.models import UserProfile, UserType
    User = get_user_model()
    given, family, email, preferred = claimlib.display_names(claims)
    if provider.require_email_verified and claimlib.email_verified(claims) is not True:
        raise _Denied('email_not_verified', 'Your e-mail address is not verified at '
                                            f'{provider.name}, so no account can be created.', sub=claims['sub'])
    if not email:
        raise _Denied('no_email', f'{provider.name} did not send an e-mail address.', sub=claims['sub'])
    if result.staff_mapping is None:
        raise _Denied('no_role', 'You have no MSP staff role for this application at '
                                 f'{provider.name}. Ask your administrator.', sub=claims['sub'])
    with transaction.atomic():
        user = User.objects.create(username=_jit_username(email, preferred), email=email,
                                   first_name=given, last_name=family, is_active=True)
        user.set_unusable_password()
        user.save(update_fields=['password'])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.user_type = UserType.STAFF
        profile.auth_source = 'oidc'
        profile.save(update_fields=['user_type', 'auth_source', 'updated_at'])
        identity = OIDCIdentity.objects.create(
            provider=provider, issuer=provider.issuer_normalized, sub=claims['sub'], user=user,
            manages_staff_role=True, email_at_link=email[:254])
    audit.log('sso_link', request=request, user=user, provider=provider, how='jit',
              description=f'{provider.name}: account {user.username} created at first sign-in')
    return identity


def _finish_login(request, provider, flow, claims, id_token):
    from django.contrib.auth import get_user_model
    from core.portal_surface import is_portal_user
    User = get_user_model()
    roles = claimlib.extract_roles(provider, claims)
    identity = OIDCIdentity.objects.filter(issuer=provider.issuer_normalized, sub=claims['sub']) \
        .select_related('user').first()
    result = mapping.resolve(provider, roles)
    if identity is None:
        _g, _f, email, _p = claimlib.display_names(claims)
        if email and User.objects.filter(email__iexact=email).exists():
            # Never link by e-mail (ARCHITECTURE.md §5.1 rule 1).
            raise _Denied('email_collision',
                          'An account with this e-mail address already exists. Sign in the usual way and '
                          f'link {provider.name} from your profile.', sub=claims['sub'])
        if not provider.jit_provisioning:
            raise _Denied('unknown_identity', f'Your {provider.name} account is not linked to an account here. '
                                              'Sign in the usual way and link it from your profile, or ask '
                                              'your administrator.', sub=claims['sub'])
        identity = _jit_create(request, provider, claims, roles, result)
    user = identity.user
    if not user.is_active:
        raise _Denied('user_inactive', 'This account is disabled.', user=user)
    # Removal is immediate: reconcile even when the sign-in is then refused.
    mapping.apply(provider, identity, roles, result)
    if not result.any_role or (identity.manages_staff_role and result.staff_mapping is None):
        raise _Denied('no_role', f'You have no role for this application at {provider.name}. '
                                 'Ask your administrator to assign one.', user=user,
                      roles=claimlib.as_list(roles.staff))
    user = User.objects.get(pk=user.pk)
    if is_portal_user(user):
        raise _Denied('portal_user', 'Customer accounts sign in at the customer portal.', user=user)

    login(request, user, backend=BACKEND)
    mfa_ok = bool(provider.accept_idp_mfa and claimlib.mfa_satisfied(provider, claims))
    s = request.session
    for k in ('azure_ad_authenticated', 'azure_ad_mfa'):
        s.pop(k, None)
    s[OIDC_SESSION_FLAG] = True
    s[OIDC_SESSION_MFA] = mfa_ok
    s[S_PROVIDER] = provider.pk
    s[S_SUB] = claims['sub']
    s[S_SID] = claims.get('sid') if isinstance(claims.get('sid'), str) else ''
    s[S_AUTH_TIME] = claims.get('auth_time') if isinstance(claims.get('auth_time'), (int, float)) else None
    if provider.rp_logout and id_token:
        s[S_ID_TOKEN] = id_token  # server-side session only, for id_token_hint at logout
    s['_auth_surface'] = 'staff'
    sessions.record(request, provider, claims, user)
    identity.last_login_at = timezone.now()
    identity.save(update_fields=['last_login_at'])
    audit.log('sso_login', request=request, user=user, provider=provider, mfa_accepted=mfa_ok,
              acr=claims.get('acr'), amr=claims.get('amr'), changes=[f'{a}:{o}' for a, o in result.changes],
              description=f'Signed in with {provider.name}' + (' (IdP MFA accepted)' if mfa_ok else ''))
    return _no_referrer(redirect(_safe_next(request, flow.get('next'))))


def _finish_link(request, provider, flow, claims):
    user = request.user
    if not user.is_authenticated or user.pk != flow.get('user_id'):
        raise _Denied('link_session_changed', 'Sign in again and restart linking.')
    existing = OIDCIdentity.objects.filter(issuer=provider.issuer_normalized, sub=claims['sub']).first()
    if existing is not None:
        if existing.user_id == user.pk:
            messages.info(request, f'Your {provider.name} account is already linked.')
            return _no_referrer(redirect('oidc_sso:account'))
        raise _Denied('identity_linked_elsewhere', f'That {provider.name} account is linked to another user.',
                      user=user)
    if OIDCIdentity.objects.filter(provider=provider, user=user).exists():
        raise _Denied('already_linked', f'Unlink your current {provider.name} account first.', user=user)
    _g, _f, email, _p = claimlib.display_names(claims)
    try:
        OIDCIdentity.objects.create(provider=provider, issuer=provider.issuer_normalized, sub=claims['sub'],
                                    user=user, manages_staff_role=False, email_at_link=email,
                                    linked_by=user)
    except IntegrityError:
        raise _Denied('identity_linked_elsewhere', f'That {provider.name} account is already linked.', user=user)
    audit.log('sso_link', request=request, user=user, provider=provider, how='self_service',
              description=f'{user.username} linked their {provider.name} account')
    messages.success(request, f'{provider.name} account linked. You can now sign in with it.')
    return _no_referrer(redirect('oidc_sso:account'))


def _has_local_totp(user):
    from django_otp.plugins.otp_totp.models import TOTPDevice
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def _finish_stepup(request, provider, flow, claims):
    from tech_access.protected import FRESH_AUTH_SECONDS, SESSION_KEY
    user = request.user
    if not user.is_authenticated or user.pk != flow.get('user_id'):
        raise _Denied('stepup_session_changed', 'Sign in again.')
    if not OIDCIdentity.objects.filter(issuer=provider.issuer_normalized, sub=claims['sub'], user=user).exists():
        raise _Denied('stepup_wrong_account', f'That is not the {provider.name} account linked to you.', user=user)
    auth_time = claims.get('auth_time')
    now = int(time.time())
    if not isinstance(auth_time, (int, float)) or now - auth_time > FRESH_AUTH_SECONDS:
        raise _Denied('stale_auth', f'{provider.name} did not ask you to sign in again. Try once more.', user=user)
    # Same strength as the local check: password + authenticator code when
    # the user has one. The OP's MFA (acr / amr) stands in for the code.
    if not claimlib.mfa_satisfied(provider, claims) and _has_local_totp(user):
        raise _Denied('stepup_no_mfa', f'{provider.name} did not confirm a second factor. Use your password '
                                       'and authenticator code instead.', user=user)
    request.session[SESSION_KEY] = min(int(auth_time), now)
    audit.log('sso_step_up', request=request, user=user, provider=provider, acr=claims.get('acr'),
              description=f'{user.username} confirmed their identity with {provider.name}')
    return _no_referrer(redirect(_safe_next(request, flow.get('next'), reverse('oidc_sso:account'))))


# --- verification (local TOTP when the OP's MFA is not accepted) ----------------------

@ratelimit(key='user_or_ip', rate='10/15m', method='POST', block=False)
@require_http_methods(['GET', 'POST'])
def verify(request):
    from django_otp import devices_for_user, login as otp_login
    if not request.user.is_authenticated or not request.session.get(OIDC_SESSION_FLAG):
        return redirect('two_factor:login')
    next_url = _safe_next(request, request.POST.get('next') or request.GET.get('next'))
    is_verified = getattr(request.user, 'is_verified', None)
    if callable(is_verified) and is_verified():
        return redirect(next_url)
    error = None
    if request.method == 'POST':
        token = (request.POST.get('token') or '').replace(' ', '').strip()
        if getattr(request, 'limited', False):
            error = 'Too many attempts. Wait a few minutes and try again.'
        elif not token or len(token) > 16 or not token.isalnum():
            error = 'Enter the code from your authenticator app, or a backup code.'
        else:
            device = next((d for d in devices_for_user(request.user, confirmed=True) if d.verify_token(token)), None)
            if device is not None:
                otp_login(request, device)
                request.session.pop('oidc_sso_verify_failures', None)
                audit.log('sso_login', request=request, user=request.user, local_2fa=True,
                          description='Single sign-on completed with the local authenticator code')
                return redirect(next_url)
            failures = request.session.get('oidc_sso_verify_failures', 0) + 1
            request.session['oidc_sso_verify_failures'] = failures
            audit.log('sso_login_denied', request=request, user=request.user, success=False,
                      reason='local_2fa_failed', failures=failures,
                      description=f'Wrong authenticator code after single sign-on ({failures})')
            if failures >= VERIFY_MAX_FAILURES:
                logout(request)
                messages.error(request, 'Too many wrong codes. Sign in again.')
                return redirect('two_factor:login')
            error = 'That code is not valid. Try again.'
    return render(request, 'oidc_sso/verify.html', {'error': error, 'next': next_url},
                  status=400 if error else 200)


# --- the user's own SSO page: link / unlink / step-up ----------------------------------

@login_required
@require_GET
def account(request):
    from tech_access.protected import has_fresh_auth
    providers = list(OIDCProvider.objects.filter(enabled=True))
    linked = {i.provider_id: i for i in OIDCIdentity.objects.filter(user=request.user, provider__in=providers)}
    rows = [{'provider': p, 'identity': linked.get(p.pk)} for p in providers]
    return render(request, 'oidc_sso/account.html', {
        'rows': rows, 'fresh_auth': has_fresh_auth(request),
        'has_password': request.user.has_usable_password(),
    })


@login_required
@require_POST
def reauth(request):
    from tech_access.protected import reauthenticate
    error = reauthenticate(request, request.POST.get('password', ''), request.POST.get('otp', ''))
    if error:
        messages.error(request, error)
    else:
        messages.success(request, 'Confirmed. You have five minutes to link or unlink.')
    return redirect('oidc_sso:account')


@login_required
@require_POST
def link_start(request, slug):
    from tech_access.protected import has_fresh_auth
    provider = enabled_provider(slug)
    if not has_fresh_auth(request):
        messages.error(request, 'Confirm your password (and authenticator code) first.')
        return redirect('oidc_sso:account')
    if OIDCIdentity.objects.filter(provider=provider, user=request.user).exists():
        messages.info(request, f'Your {provider.name} account is already linked.')
        return redirect('oidc_sso:account')
    try:
        url = client.start(request, provider, client.MODE_LINK, prompt='login')
    except OPError:
        messages.error(request, f'{provider.name} is not reachable right now.')
        return redirect('oidc_sso:account')
    return _no_referrer(redirect(url))


@login_required
@require_POST
def unlink_self(request, slug):
    from tech_access.protected import has_fresh_auth
    provider = enabled_provider(slug)
    if not has_fresh_auth(request):
        messages.error(request, 'Confirm it\'s you first.')
        return redirect('oidc_sso:account')
    identity = OIDCIdentity.objects.filter(provider=provider, user=request.user).first()
    if identity is not None:
        identity.delete()
        audit.log('sso_unlink', request=request, user=request.user, provider=provider, how='self_service',
                  description=f'{request.user.username} unlinked their {provider.name} account')
        messages.success(request, f'{provider.name} account unlinked.')
    return redirect('oidc_sso:account')


@login_required
@require_POST
def stepup_start(request, slug):
    from tech_access.protected import FRESH_AUTH_SECONDS
    provider = enabled_provider(slug)
    if not OIDCIdentity.objects.filter(provider=provider, user=request.user).exists():
        raise Http404('Not linked')
    next_url = _safe_next(request, request.POST.get('next'), reverse('oidc_sso:account'))
    try:
        url = client.start(request, provider, client.MODE_STEPUP, next_url, prompt='login',
                           max_age=FRESH_AUTH_SECONDS, acr_values=provider.stepup_acr_values.strip())
    except OPError:
        messages.error(request, f'{provider.name} is not reachable right now. Use your password instead.')
        return redirect(next_url)
    return _no_referrer(redirect(url))


# --- back-channel logout -------------------------------------------------------------

def _bcl_response(status, error=None):
    response = JsonResponse({'error': error} if error else {}, status=status)
    response['Cache-Control'] = 'no-store'
    return response


@csrf_exempt  # server-to-server POST from the OP; authenticated by the signed logout_token
@require_POST
def backchannel_logout(request, slug):
    provider = enabled_provider(slug)
    token = request.POST.get('logout_token', '')
    try:
        claims = validate_logout_token(provider, token)
    except TokenError as exc:
        audit.log('sso_backchannel_logout', request=request, provider=provider, success=False,
                  reason=exc.reason, description=f'{provider.name}: logout token refused ({exc.reason})')
        return _bcl_response(400, 'invalid_request')
    iat = claims.get('iat')
    expires = timezone.now() + timedelta(days=2)
    if isinstance(claims.get('exp'), (int, float)):
        expires = max(expires, datetime.fromtimestamp(claims['exp'], tz=dt_timezone.utc) + timedelta(days=1))
    try:
        with transaction.atomic():
            ReplayRecord.objects.filter(expires_at__lt=timezone.now()).delete()
            ReplayRecord.objects.create(issuer=provider.issuer_normalized, jti=claims['jti'], expires_at=expires)
    except IntegrityError:
        audit.log('sso_backchannel_logout', request=request, provider=provider, success=False,
                  reason='replay', description=f'{provider.name}: replayed logout token refused')
        return _bcl_response(400, 'invalid_request')
    if isinstance(claims.get('sid'), str) and claims['sid']:
        killed, users = sessions.logout_sid(provider, claims['sid'])
        how = 'sid'
    else:
        killed, users = sessions.logout_sub(provider, claims['sub'])
        how = 'sub'
    audit.log('sso_backchannel_logout', request=request, provider=provider, by=how,
              sid=claims.get('sid', ''), sub=claims.get('sub', ''), sessions_ended=killed,
              user_ids=sorted(users), iat=iat,
              description=f'{provider.name}: back-channel logout ended {killed} session(s)')
    return _bcl_response(200)


# --- public JWK for private_key_jwt ------------------------------------------------------

@require_GET
def jwks(request, slug):
    provider = enabled_provider(slug)
    if provider.client_auth_method != OIDCProvider.AUTH_PRIVATE_KEY_JWT:
        raise Http404('No key')
    response = JsonResponse(keys.public_jwks(provider))
    response['Cache-Control'] = 'public, max-age=300'
    return response


# --- logout: local first, then the OP's end_session_endpoint ------------------------------

class SSOLogoutView(LogoutView):
    """The site's sign-out. For an SSO session, after the local logout the
    browser goes on to the OP's end_session_endpoint (RP-initiated logout)
    with id_token_hint and post_logout_redirect_uri."""

    def post(self, request, *args, **kwargs):
        provider_id = request.session.get(S_PROVIDER) if request.session.get(OIDC_SESSION_FLAG) else None
        id_token = request.session.get(S_ID_TOKEN)
        response = super().post(request, *args, **kwargs)
        if provider_id:
            provider = OIDCProvider.objects.filter(pk=provider_id, enabled=True, rp_logout=True).first()
            if provider is not None:
                url = client.end_session_url(provider, id_token,
                                             request.build_absolute_uri(reverse('two_factor:login')))
                if url:
                    return redirect(url)
        return response
