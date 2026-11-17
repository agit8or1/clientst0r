"""Same-site redirect targets.

Every redirect whose target comes from the request (a ``next`` field, the
Referer header) goes through ``safe_next`` / ``safe_referer``. A target is
used only when Django's ``url_has_allowed_host_and_scheme`` accepts it for
this request's own host (and, on HTTPS, only an https or relative URL);
anything else gets the caller's fallback.

``startswith('/') and not startswith('//')`` is not enough on its own:
browsers treat ``/\\evil.example`` as ``//evil.example``. Backslashes,
control characters and leading or trailing whitespace are therefore refused
outright; a real same-site URL never contains them.
"""
import re

from django.utils.http import url_has_allowed_host_and_scheme

_UNSAFE = re.compile(r'[\x00-\x1f\x7f\\]')


def safe_next(request, candidate, fallback='/'):
    """Return ``candidate`` if it is a URL on this site, else ``fallback``.

    ``fallback`` may be a path or a URL pattern name (``redirect()`` resolves
    either); it is trusted and returned unchanged.
    """
    if (not isinstance(candidate, str) or not candidate or candidate != candidate.strip()
            or _UNSAFE.search(candidate)):
        return fallback
    if url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return candidate
    return fallback


def safe_referer(request, fallback='/'):
    """The Referer if it is a page on this site, else ``fallback``."""
    return safe_next(request, request.META.get('HTTP_REFERER'), fallback)


def safe_post_next(request, fallback='/'):
    """The POSTed ``next`` field if it is on this site, else ``fallback``."""
    return safe_next(request, request.POST.get('next'), fallback)
