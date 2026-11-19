"""Rate limits for public, token-authenticated pages (SR-11, SR-12).

Two buckets: per client address (the real visitor behind trusted proxies)
and, when the page has a token, per token, so one link cannot be hammered
from many addresses. Counts live in the default cache, so with the local
memory cache each web worker counts separately; the limits are set with that
in mind.
"""
import hashlib
from functools import wraps

from django.http import HttpResponse

METHODS = ['GET', 'HEAD', 'POST']
TOO_MANY = 'Too many requests. Please wait a minute and try again.'


def _token_key(token):
    return hashlib.sha256((token or '').encode()).hexdigest()[:32]


def limited(request, group, rate, token=None, token_rate=None, increment=True) -> bool:
    from django_ratelimit.core import is_ratelimited
    if is_ratelimited(request, group=f'{group}.ip', key='ip', rate=rate, method=METHODS, increment=increment):
        return True
    if token is not None and token_rate:
        key = _token_key(token)
        return is_ratelimited(request, group=f'{group}.token', key=lambda g, r: key, rate=token_rate,
                              method=METHODS, increment=increment)
    return False


def throttled(group, rate, token_rate=None):
    """Decorator for public views; ``token`` comes from the URL kwargs."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if limited(request, group, rate, kwargs.get('token'), token_rate):
                resp = HttpResponse(TOO_MANY, status=429, content_type='text/plain; charset=utf-8')
                resp['Retry-After'] = '60'
                resp['Cache-Control'] = 'no-store'
                return resp
            return view(request, *args, **kwargs)
        return wrapper
    return deco
