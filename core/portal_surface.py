"""
Customer portal vs staff backend: which "surface" a request belongs to.

The customer portal (portal pages, the portal sign-in, and the links sent to
customers: quote signing, CSAT surveys, secure replies and secure notes,
public status pages, unsubscribe links) is one surface. Everything else is
the staff backend. The split lets the firewall apply a separate country
policy to each (core/firewall_middleware.py), keeps customer accounts on the
portal, and optionally moves the portal to its own host name.

Classification is server-side only: by URL resolution of the request path
and by the request's validated host, never by anything the client sends.
A path that does not resolve counts as staff, the stricter surface.

Shared paths (static files, uploaded media, CSP reports, the favicon, the
offline page) are needed by both. The firewall judges them by the portal
policy for anonymous visitors and customer portal users, and by the staff
policy for everyone else. Uploaded media still goes through
core.media_views, which decides per file and per user what may be read,
so the portal policy never opens backend files.

Session cookies: one session cookie per host. On a single host a browser
holds one session, and a customer portal user's session never reaches the
backend (PortalUserGuardMiddleware sends them to the portal), while staff
accounts cannot sign in on the portal. With a dedicated portal host name the
cookies are host-only (SESSION_COOKIE_DOMAIN is not set), so the portal and
the backend have separate cookies as well.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpResponseNotFound, HttpResponseRedirect
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)

PORTAL = 'portal'
STAFF = 'staff'
SHARED = 'shared'

# URL namespaces that are wholly portal.
PORTAL_NAMESPACES = frozenset({'portal', 'portal_auth'})

# Customer-facing views outside those namespaces: token links sent to
# customers by email, and pages a customer opens without a staff account.
PUBLIC_CUSTOMER_VIEWS = frozenset({
    'core:secure_note_view_link',          # /core/secret/<token>/
    'psa:secure_reply_submit',             # /psa/secure-reply/<token>/
    'psa:csat_respond',                    # /psa/csat/<token>/
    'statuspage:public',                   # /status/p/<token>/
    'security_alerts:digest_unsubscribe',  # /security/digest/unsubscribe/<token>/
    'accounts:portal_set_password',        # old invite links (now redirect)
})

# Needed by pages on both surfaces.
SHARED_PREFIXES = ('/static/',)
SHARED_PATHS = frozenset({'/favicon.ico', '/csp-report/', '/offline/'})
SHARED_VIEWS = frozenset({'serve_media'})


def classify_path(path: str) -> str:
    """PORTAL, STAFF or SHARED for a request path (path_info)."""
    path = path or '/'
    if path.startswith(SHARED_PREFIXES) or path in SHARED_PATHS:
        return SHARED
    try:
        match = resolve(path)
    except Resolver404:
        return STAFF
    except Exception:  # pragma: no cover - a broken URLconf is not a portal page
        logger.exception('portal_surface: could not resolve %s', path)
        return STAFF
    if match.view_name in SHARED_VIEWS:
        return SHARED
    if match.namespaces and match.namespaces[0] in PORTAL_NAMESPACES:
        return PORTAL
    if match.view_name in PUBLIC_CUSTOMER_VIEWS:
        return PORTAL
    return STAFF


# ---------------------------------------------------------------------------
# Portal host name
# ---------------------------------------------------------------------------

def _normalise_host(value) -> str:
    value = (value or '').strip().lower()
    if '://' in value:
        value = urlsplit(value).netloc
    value = value.split('/')[0]
    if value.startswith('[') and ']' in value:  # IPv6 literal
        return value[:value.index(']') + 1]
    return value.split(':')[0]


def portal_hostname() -> str:
    """The configured portal host name, or '' when the portal shares the
    main host. PORTAL_HOSTNAME in the environment wins over the setting."""
    env = getattr(settings, 'PORTAL_HOSTNAME', '') or ''
    if env:
        return _normalise_host(env)
    try:
        from core.models import SystemSetting
        return _normalise_host(SystemSetting.get_settings().portal_hostname)
    except Exception:
        # Settings table not migrated yet (upgrade window): no portal host.
        return ''


_HOST_RE = __import__('re').compile(
    r'^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$')


def portal_hostname_env_locked() -> bool:
    return bool(getattr(settings, 'PORTAL_HOSTNAME', '') or '')


def validate_portal_hostname(value, request=None):
    """(normalised host name, error message or ''). Empty is valid (one host).

    Refused: something that is not a DNS host name; the host this request
    came in on, or Site URL's host (staff pages there would become a 404 and
    lock administrators out); a host Django would reject (ALLOWED_HOSTS).
    """
    raw = (value or '').strip().lower()
    if not raw:
        return '', ''
    host = _normalise_host(raw)
    if not _HOST_RE.match(host):
        return host, 'Enter a host name such as portal.example.com (no scheme, path or port).'
    staff_hosts = set()
    if request is not None:
        staff_hosts.add(request_host(request))
    try:
        from core.models import SystemSetting
        site = SystemSetting.get_settings().site_url or ''
        if site:
            staff_hosts.add(_normalise_host(site))
    except Exception:
        pass
    if host in staff_hosts:
        return host, ('The portal host name must differ from the host staff use; '
                      'otherwise the staff pages would no longer be reachable.')
    from django.http.request import validate_host
    if not validate_host(host, settings.ALLOWED_HOSTS):
        return host, (f'{host} is not in ALLOWED_HOSTS. Add it to the ALLOWED_HOSTS '
                      'environment variable (or set PORTAL_HOSTNAME) and restart first.')
    return host, ''


def _request_hostname(request) -> str:
    cached = getattr(request, '_portal_surface_hostname', None)
    if cached is None:
        cached = portal_hostname()
        request._portal_surface_hostname = cached
    return cached


def request_host(request) -> str:
    try:
        return _normalise_host(request.get_host())
    except Exception:
        return ''


def on_portal_host(request) -> bool:
    host = _request_hostname(request)
    return bool(host) and request_host(request) == host


def portal_scheme() -> str:
    try:
        from core.models import SystemSetting
        site = (SystemSetting.get_settings().site_url or '').strip().lower()
    except Exception:
        site = ''
    return 'http' if site.startswith('http://') else 'https'


def portal_origin() -> str:
    """'https://portal.example.com' when a portal host is set, else ''."""
    host = portal_hostname()
    return f'{portal_scheme()}://{host}' if host else ''


def portal_absolute_url(path: str, request=None) -> str:
    """Absolute URL for a customer-facing `path`: on the portal host when one
    is configured, else on the request's host, else on Site URL."""
    origin = portal_origin()
    if origin:
        return origin + path
    if request is not None:
        return request.build_absolute_uri(path)
    try:
        from core.models import SystemSetting
        base = (SystemSetting.get_settings().site_url or '').rstrip('/')
    except Exception:
        base = ''
    return base + path


def portal_site_url(system_settings=None) -> str:
    """Base URL for links in emails to customers (no trailing slash)."""
    origin = portal_origin()
    if origin:
        return origin
    if system_settings is None:
        try:
            from core.models import SystemSetting
            system_settings = SystemSetting.get_settings()
        except Exception:
            return ''
    return (system_settings.site_url or '').rstrip('/')


def portal_login_path() -> str:
    return reverse('portal_auth:login')


def portal_login_url(request=None) -> str:
    """Where customers sign in, absolute when a portal host is set."""
    path = portal_login_path()
    if portal_hostname() and not (request is not None and on_portal_host(request)):
        return portal_absolute_url(path)
    if request is not None:
        return request.build_absolute_uri(path)
    return portal_absolute_url(path)


def staff_login_path() -> str:
    from django.shortcuts import resolve_url
    return resolve_url(settings.LOGIN_URL)


# ---------------------------------------------------------------------------
# Who is a portal user?
# ---------------------------------------------------------------------------

def is_msp_staff(user) -> bool:
    from psa.visibility import is_msp_staff as _is_msp_staff
    return _is_msp_staff(user)


def is_portal_user(user) -> bool:
    """A customer account that signs in on the portal: active, not MSP staff
    (superuser, Django staff, or a Staff-type profile), PSA switched on, and
    an active membership of at least one customer with the portal enabled.

    Customer users without portal access keep the staff sign-in, as before:
    they have nowhere else to go.
    """
    if user is None or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    cached = getattr(user, '_is_portal_user', None)
    if cached is not None:
        return cached
    result = False
    if not is_msp_staff(user):
        from psa.feature_flags import is_psa_enabled
        if is_psa_enabled():
            from accounts.models import Membership
            result = Membership.objects.filter(
                user=user, is_active=True,
                organization__psa_settings__portal_enabled=True,
            ).exists()
    try:
        user._is_portal_user = result
    except Exception:
        pass
    return result


def request_surface(request) -> str:
    """PORTAL or STAFF: the country policy that governs this request."""
    if on_portal_host(request):
        return PORTAL
    kind = classify_path(request.path_info)
    if kind != SHARED:
        return kind
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or is_portal_user(user):
        return PORTAL
    return STAFF


def safe_portal_next(request, url: str) -> str:
    """`url` when it is a same-host portal page, else ''."""
    if not url:
        return ''
    if not url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return ''
    if classify_path(urlsplit(url).path) != PORTAL:
        return ''
    return url


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class PortalHostMiddleware:
    """With a portal host name configured: on that host serve only portal and
    shared paths (staff paths are a 404, '/' goes to the portal); on any other
    host send portal paths to the portal host. Does nothing when unset.

    Runs after CommonMiddleware, so the host has passed ALLOWED_HOSTS.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = _request_hostname(request)
        if not host:
            return self.get_response(request)
        kind = classify_path(request.path_info)
        if request_host(request) == host:
            if request.path_info == '/':
                return HttpResponseRedirect(reverse('portal:ticket_list'))
            if kind == STAFF:
                return _portal_not_found(request)
            return self.get_response(request)
        if kind == PORTAL:
            target = portal_origin() + request.get_full_path()
            return HttpResponseRedirect(target)
        return self.get_response(request)


def _portal_not_found(request):
    from django.template.loader import render_to_string
    try:
        body = render_to_string('portal/auth/not_found.html', {}, request=request)
    except Exception:
        body = 'Not found'
    return HttpResponseNotFound(body)


class PortalUserGuardMiddleware:
    """Keep customer portal users on the portal surface, and send portal
    visitors who need to sign in to the portal sign-in.

    * A signed-in portal user (see is_portal_user) who opens a staff page is
      redirected to the portal home. Their session never reaches the backend.
    * On the portal surface, a redirect to the staff sign-in (login_required,
      session expiry, 2FA re-verification) is rewritten to the portal sign-in.

    Runs after AuthenticationMiddleware and OTPMiddleware and before the
    session-expiry and 2FA middleware, whose redirects pass back through it.
    """

    # Staff-surface paths a portal user may still reach.
    PORTAL_USER_ALLOWED = ('/logout/',)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        kind = classify_path(request.path_info)
        portal_host = on_portal_host(request)
        if (kind == STAFF and not portal_host and user is not None
                and user.is_authenticated
                and not request.path_info.startswith(self.PORTAL_USER_ALLOWED)
                and is_portal_user(user)):
            home = reverse('portal:ticket_list')
            if _request_hostname(request):
                home = portal_origin() + home
            return HttpResponseRedirect(home)

        response = self.get_response(request)

        if (kind == PORTAL or portal_host) and response.status_code in (301, 302, 303, 307, 308):
            location = response.get('Location', '')
            rewritten = self._rewrite_login_redirect(location)
            if rewritten:
                response['Location'] = rewritten
        return response

    @staticmethod
    def _rewrite_login_redirect(location: str) -> str:
        if not location:
            return ''
        parts = urlsplit(location)
        if parts.path != staff_login_path():
            return ''
        return urlunsplit(('', '', portal_login_path(), parts.query, ''))
