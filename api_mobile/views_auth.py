"""
Mobile API auth views — login, MFA challenge, logout, me, refresh.

All endpoints are prefixed `/api/mobile/v1/auth/`. `login` and `mfa` are
the only anonymous-callable endpoints; `logout`, `me`, and `refresh`
require a valid token in the `Authorization: Token <key>` header.
"""
from __future__ import annotations

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from audit.models import AuditLog

from .auth_utils import (
    client_ip, consume_mfa_token, issue_mfa_token, user_has_2fa_enabled,
    verify_totp_code,
)
from .authentication import MobileTokenAuthentication
from .models import MobileAuthToken
from .throttles import MobileLoginRateThrottle


def _audit(user, action, request, extra=None):
    try:
        AuditLog.objects.create(
            user=user if isinstance(user, User) else None,
            username=getattr(user, 'username', '') or (user if isinstance(user, str) else ''),
            action=action,
            object_type='MobileAPI',
            ip_address=client_ip(request),
            extra_data=extra or {},
        )
    except Exception:
        # Never block auth on audit log failure.
        pass


def _device_label(request) -> str:
    """What signed in, for the user's session list. Optional `device_name`
    in the login body (not sent by older app builds), else the User-Agent."""
    label = ''
    try:
        label = (request.data.get('device_name') or '').strip()
    except Exception:
        label = ''
    if not label:
        label = (request.META.get('HTTP_USER_AGENT') or 'Mobile app').strip()
    return label[:120]


def _issue_token(user, request) -> str:
    """A new token for this sign-in. Returned once; only its hash is stored."""
    raw, _row = MobileAuthToken.issue(user, device_label=_device_label(request))
    return raw


def _user_payload(user):
    full_name = (user.get_full_name() or '').strip() or user.username
    org_id = None
    role = None
    try:
        m = user.memberships.filter(is_active=True).first()
        if m:
            org_id = m.organization_id
            role = m.role
    except Exception:
        pass
    # v3.17.477 — surface role-template flags the mobile UI gates on
    # (ticket assignment picker, "Edit" / "Close" affordances, …). We
    # only expose the booleans the mobile app actually reads to keep
    # the payload small.
    permissions: dict = {}
    try:
        from accounts.permission_utils import user_has_perm
        for perm in (
            # PSA tickets (v3.17.477)
            'tickets_view', 'tickets_create', 'tickets_edit',
            'tickets_assign', 'tickets_view_all',
            'tickets_close', 'tickets_delete',
            # Vault (v3.17.479) — gate mobile Edit / New / Rotate UI.
            'vault_view', 'vault_create', 'vault_edit', 'vault_delete',
            'vault_view_password',
            # Assets (v3.17.480) — gate mobile Edit / Link-vault UI.
            'assets_view', 'assets_create', 'assets_edit', 'assets_delete',
            # KB / docs
            'docs_view',
        ):
            permissions[perm] = user_has_perm(user, perm)
        # The *_view flags are enforced per customer server-side; report
        # them through the same resolver the endpoints use (which also
        # honours an MSP staff member's global role) so the app's tab
        # gating agrees with what the list endpoints will return.
        from .scoping import has_any_perm
        for perm in ('vault_view', 'docs_view', 'assets_view'):
            permissions[perm] = has_any_perm(user, perm)
    except Exception:
        permissions = {}
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'full_name': full_name,
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'organization_id': org_id,
        'role': role,
        'permissions': permissions,
    }


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([MobileLoginRateThrottle])
def login_view(request):
    """
    POST /api/mobile/v1/auth/login/

    Body: `{username, password}`. `username` may be email or username.
    Returns either `{token, user}` or `{mfa_required: true, mfa_token}`.
    """
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    if not username or not password:
        return Response(
            {'detail': 'username and password are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Allow email-as-username for convenience.
    user = authenticate(request, username=username, password=password)
    if user is None and '@' in username:
        try:
            real = User.objects.get(email__iexact=username, is_active=True)
            user = authenticate(request, username=real.username, password=password)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            user = None

    if user is None:
        _audit(username, 'login_failed', request, {'reason': 'invalid_credentials', 'channel': 'mobile'})
        return Response(
            {'detail': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        _audit(user, 'login_failed', request, {'reason': 'inactive', 'channel': 'mobile'})
        return Response({'detail': 'Account inactive'}, status=status.HTTP_403_FORBIDDEN)

    if user_has_2fa_enabled(user):
        mfa_token = issue_mfa_token(user)
        _audit(user, 'login', request, {'channel': 'mobile', 'stage': 'mfa_required'})
        return Response({'mfa_required': True, 'mfa_token': mfa_token})

    token = _issue_token(user, request)
    _audit(user, 'login', request, {'channel': 'mobile', 'stage': 'token_issued'})
    return Response({'token': token, 'user': _user_payload(user)})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([MobileLoginRateThrottle])
def mfa_view(request):
    """
    POST /api/mobile/v1/auth/mfa/

    Body: `{mfa_token, code}`. On success returns `{token, user}`.
    """
    mfa_token = (request.data.get('mfa_token') or '').strip()
    code = (request.data.get('code') or '').strip()
    if not mfa_token or not code:
        return Response(
            {'detail': 'mfa_token and code are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = consume_mfa_token(mfa_token)
    if user is None:
        return Response(
            {'detail': 'Invalid or expired mfa_token'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not verify_totp_code(user, code):
        _audit(user, 'login_failed', request, {'reason': 'bad_totp', 'channel': 'mobile'})
        return Response(
            {'detail': 'Invalid 2FA code'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token = _issue_token(user, request)
    _audit(user, 'login', request, {'channel': 'mobile', 'stage': 'token_issued_after_mfa'})
    return Response({'token': token, 'user': _user_payload(user)})


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """POST /api/mobile/v1/auth/logout/ — revokes the token this request
    was made with. Other devices stay signed in."""
    user = request.user
    if isinstance(request.auth, MobileAuthToken):
        request.auth.revoke()
    _audit(user, 'logout', request, {'channel': 'mobile'})
    return Response({'detail': 'Logged out'})


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def me_view(request):
    """GET /api/mobile/v1/auth/me/ — returns the authenticated user profile."""
    return Response({'user': _user_payload(request.user)})


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def refresh_view(request):
    """POST /api/mobile/v1/auth/refresh/ — rotate the caller's token: a new
    one is issued (returned once) and the presented one is revoked."""
    user = request.user
    old = request.auth if isinstance(request.auth, MobileAuthToken) else None
    raw, _row = MobileAuthToken.issue(
        user, device_label=(old.device_label if old else _device_label(request)))
    if old is not None:
        old.revoke()
    _audit(user, 'api_call', request, {'channel': 'mobile', 'op': 'token_refresh'})
    return Response({'token': raw, 'user': _user_payload(user)})


def _session_payload(row, current):
    return {
        'id': row.pk,
        'device_label': row.device_label,
        'token_prefix': row.key_prefix,
        'created_at': row.created_at,
        'last_used_at': row.last_used_at,
        'expires_at': row.expires_at,
        'current': current is not None and row.pk == current.pk,
    }


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def sessions_view(request):
    """GET /api/mobile/v1/auth/sessions/ — the caller's active mobile sessions."""
    current = request.auth if isinstance(request.auth, MobileAuthToken) else None
    rows = MobileAuthToken.active_for(request.user)
    return Response({'sessions': [_session_payload(r, current) for r in rows]})


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def revoke_all_view(request):
    """POST /api/mobile/v1/auth/revoke-all/ — sign out every mobile device
    of the caller, including this one."""
    n = MobileAuthToken.revoke_all_for(request.user)
    _audit(request.user, 'logout', request,
           {'channel': 'mobile', 'op': 'revoke_all_mobile_sessions', 'revoked': n})
    return Response({'detail': 'All mobile sessions signed out', 'revoked': n})
