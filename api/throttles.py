"""Per-key request limit (roadmap 81.4).

A key with ``rate_limit_per_minute`` set is held to that rate, on top of the
standard user and anonymous limits. Counters live in the configured cache,
like the other API throttles, so with the default per-process cache each
application worker counts separately."""
from rest_framework.throttling import SimpleRateThrottle


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
