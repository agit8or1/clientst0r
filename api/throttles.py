"""
Custom DRF throttles for sensitive and AI endpoints.
Provides granular rate limiting for authentication, password reset, tokens, and AI requests.
"""
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    """
    Strict throttle for login attempts.
    Rate: 10/hour (configurable via settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'])
    """
    scope = 'login'


class PasswordResetThrottle(AnonRateThrottle):
    """
    Very strict throttle for password reset requests.
    Rate: 5/hour (configurable via settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['password_reset'])
    """
    scope = 'password_reset'


class TokenThrottle(UserRateThrottle):
    """
    Throttle for API token operations (create, refresh, revoke).
    Rate: 20/hour (configurable via settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['token'])
    """
    scope = 'token'


class AIRequestThrottle(UserRateThrottle):
    """
    Daily throttle for AI/Anthropic API requests (cost protection).
    Rate: 100/day (configurable via settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['ai_request'])
    """
    scope = 'ai_request'


class AIBurstThrottle(UserRateThrottle):
    """
    Burst protection for AI requests (prevent rapid-fire abuse).
    Rate: 10/minute (configurable via settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['ai_burst'])
    """
    scope = 'ai_burst'


class StaffOnlyThrottle(UserRateThrottle):
    """
    Bypass throttling for staff users (admins).
    All staff users get unlimited requests.
    """
    def allow_request(self, request, view):
        # Staff users bypass throttling
        if request.user and request.user.is_authenticated and request.user.is_staff:
            return True
        return super().allow_request(request, view)


# Per-key request limit (roadmap 81.4, v3.17.714). A key with
# rate_limit_per_minute set is held to that rate, on top of the standard user
# and anonymous limits. Counters live in the configured cache, so with the
# default per-process cache each application worker counts separately.
class APIKeyRateThrottle(SimpleRateThrottle):
    scope = 'api_key'
    rate = None  # set per request from the key

    def __init__(self):
        # SimpleRateThrottle reads THROTTLE_RATES[scope] here; the rate comes
        # from the key instead, so skip that lookup.
        self.num_requests, self.duration = None, 60

    def allow_request(self, request, view):
        key = getattr(request, 'api_key', None)
        if key is None:
            key = getattr(getattr(request, '_request', None), 'api_key', None)
        limit = getattr(key, 'rate_limit_per_minute', None)
        if not limit:
            return True
        self.num_requests, self.duration = int(limit), 60
        self.key = f'throttle_api_key_{key.pk}'
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        if len(self.history) >= self.num_requests:
            return self.throttle_failure()
        return self.throttle_success()

    def get_cache_key(self, request, view):  # not used: allow_request sets self.key
        return None
