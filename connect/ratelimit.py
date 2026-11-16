"""Fixed-window rate limits on the Django cache (per process with locmem,
shared with a shared cache). The durable brute-force protection for pairing
codes is in the database (PairingInvitation.attempts), not here."""
from __future__ import annotations

import time

from django.core.cache import cache

LIMITS = {
    'pairing_ip': (10, 600), 'pairing_global': (60, 600),
    'token_ip': (120, 60), 'token_global': (1200, 60),
    'events_ip': (600, 60), 'api_ip': (600, 60), 'poll_ip': (120, 60), 'jwks_ip': (120, 60),
}


def hit(bucket: str, key: str = '') -> bool:
    """Count one request; True while within the limit."""
    limit, window = LIMITS[bucket]
    slot = int(time.time() // window)
    k = f'connect:rl:{bucket}:{key}:{slot}'
    if cache.add(k, 1, window + 5):
        return True
    try:
        n = cache.incr(k)
    except ValueError:
        cache.set(k, 1, window + 5)
        n = 1
    return n <= limit


def client_ip(request) -> str:
    return request.META.get('REMOTE_ADDR', '') or 'unknown'
