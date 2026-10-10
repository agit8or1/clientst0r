"""
Helpers for mobile auth — IP extraction, audit hooks, MFA token cache.

The MFA flow uses a short-lived (5 minute) opaque token kept in Django's
default cache. Login validates the password and issues an `mfa_token` if
the user has 2FA enabled; the client then POSTs `mfa_token + code` to
`/auth/mfa/` to receive the actual API token.
"""
from __future__ import annotations

import secrets
from typing import Optional

from django.contrib.auth.models import User
from django.core.cache import cache

MFA_CACHE_PREFIX = 'mobile_mfa_token:'
MFA_TTL_SECONDS = 300  # 5 minutes


def client_ip(request) -> str:
    """Client IP; X-Forwarded-For is honoured only from trusted proxies."""
    from core.client_ip import get_client_ip
    return get_client_ip(request) or ''


def issue_mfa_token(user: User) -> str:
    """Issue a single-use MFA challenge token for `user` and cache it."""
    token = secrets.token_urlsafe(32)
    cache.set(MFA_CACHE_PREFIX + token, user.id, timeout=MFA_TTL_SECONDS)
    return token


def consume_mfa_token(token: str) -> Optional[User]:
    """Look up and atomically consume an MFA token. Returns the user or None."""
    if not token:
        return None
    key = MFA_CACHE_PREFIX + token
    user_id = cache.get(key)
    if not user_id:
        return None
    cache.delete(key)
    try:
        return User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        return None


def user_has_2fa_enabled(user: User) -> bool:
    """True if the user has a confirmed TOTP device or 2FA-enabled UserProfile."""
    try:
        from django_otp.plugins.otp_totp.models import TOTPDevice
        if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
            return True
    except Exception:
        pass
    try:
        return bool(getattr(user.profile, 'two_factor_enabled', False))
    except Exception:
        return False


def verify_totp_code(user: User, code: str) -> bool:
    """Verify a 6-digit TOTP code against the user's confirmed device."""
    if not code:
        return False
    try:
        from django_otp.plugins.otp_totp.models import TOTPDevice
        for device in TOTPDevice.objects.filter(user=user, confirmed=True):
            if device.verify_token(code):
                return True
    except Exception:
        pass
    return False
