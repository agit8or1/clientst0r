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
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
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

    token, _ = Token.objects.get_or_create(user=user)
    _audit(user, 'login', request, {'channel': 'mobile', 'stage': 'token_issued'})
    return Response({'token': token.key, 'user': _user_payload(user)})


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

    token, _ = Token.objects.get_or_create(user=user)
    _audit(user, 'login', request, {'channel': 'mobile', 'stage': 'token_issued_after_mfa'})
    return Response({'token': token.key, 'user': _user_payload(user)})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """POST /api/mobile/v1/auth/logout/ — revokes the caller's token."""
    user = request.user
    Token.objects.filter(user=user).delete()
    _audit(user, 'logout', request, {'channel': 'mobile'})
    return Response({'detail': 'Logged out'})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def me_view(request):
    """GET /api/mobile/v1/auth/me/ — returns the authenticated user profile."""
    return Response({'user': _user_payload(request.user)})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def refresh_view(request):
    """POST /api/mobile/v1/auth/refresh/ — rotate the caller's token."""
    user = request.user
    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    _audit(user, 'api_call', request, {'channel': 'mobile', 'op': 'token_refresh'})
    return Response({'token': token.key, 'user': _user_payload(user)})
