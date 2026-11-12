"""The only way the documents feature talks to Microsoft.

    send(method, url, *, allowed_hosts, headers=None, data=None,
         max_bytes=..., timeout=None) -> office.net.FetchResult

Rules (on top of office.net, which resolves once, pins the connection to the
checked addresses, verifies TLS, ignores proxies and caps the body):

* https only, port 443, no credentials in the URL.
* The host must be in `allowed_hosts`. Graph calls pass ``{GRAPH_HOST}``,
  token calls ``{LOGIN_HOST}``. A ``@microsoft.graph.downloadUrl`` or a
  ``webUrl`` is only followed / redirected to when its host is the tenant's
  SharePoint host or its ``-my`` OneDrive host (``sharepoint_hosts``).
* Only public addresses (``public_only``): Microsoft's endpoints are never
  on a private network, so a DNS answer pointing inside is refused.
* Redirects are not followed across hosts (office.net refuses them).
* Sharing and anonymous-viewer endpoints (createLink, invite, permissions,
  grant, shares, preview) are refused here, whatever the caller asks.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from office import net

GRAPH_HOST = 'graph.microsoft.com'
LOGIN_HOST = 'login.microsoftonline.com'
GRAPH_BASE = f'https://{GRAPH_HOST}/v1.0'

DEFAULT_MAX_BYTES = 4 * 1024 * 1024

_SHAREPOINT_HOST = re.compile(r'^([a-z0-9][a-z0-9-]{0,62}?)(-my)?\.sharepoint\.com$')
_SHARING = re.compile(r'/(createLink|invite|permissions|grant|shares|preview)(?=$|[/(?])', re.I)

# Indirection so tests replace the network with a fake Microsoft at the HTTP
# layer (method, URL, headers, body), keeping every check above it in place.
_net_fetch = net.fetch


class MicrosoftEndpoint:
    """The attributes office.net.fetch reads from an editor instance."""
    mode = 'existing_service'
    public_only = True
    verify_tls = True
    ca_bundle = ''
    internal_url = ''
    connect_timeout_s = 10

    def __init__(self, host, timeout=60):
        self.browser_url = f'https://{host}/'
        self.request_timeout_s = timeout


class RefusedURL(net.DestinationNotAllowed):
    pass


def tenant_prefix(host):
    m = _SHAREPOINT_HOST.match((host or '').strip().lower().rstrip('.'))
    return m.group(1) if m else None


def valid_sharepoint_host(host) -> bool:
    return tenant_prefix(host) is not None


def sharepoint_hosts(connection) -> set:
    """The tenant's SharePoint and OneDrive hosts, or an empty set when the
    connection's SharePoint host is not known yet."""
    prefix = tenant_prefix(connection.docs_sharepoint_host)
    if not prefix:
        return set()
    return {f'{prefix}.sharepoint.com', f'{prefix}-my.sharepoint.com'}


def check(url, allowed_hosts) -> str:
    if not isinstance(url, str) or not url:
        raise RefusedURL('Empty URL')
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise RefusedURL(f'Malformed URL: {e}')
    host = (parts.hostname or '').lower().rstrip('.')
    if parts.scheme != 'https' or port not in (None, 443):
        raise RefusedURL('Only https on port 443')
    if '@' in parts.netloc:
        raise RefusedURL('URLs with credentials are refused')
    if host not in {h.lower() for h in allowed_hosts}:
        raise RefusedURL(f'{host or "(no host)"} is not an allowed Microsoft host')
    if _SHARING.search(parts.path):
        raise RefusedURL('Sharing and preview endpoints are never called')
    return url


def is_allowed(url, allowed_hosts) -> bool:
    try:
        check(url, allowed_hosts)
    except RefusedURL:
        return False
    return True


def send(method, url, *, allowed_hosts, headers=None, data=None,
         max_bytes=DEFAULT_MAX_BYTES, timeout=None):
    check(url, allowed_hosts)
    host = urlsplit(url).hostname.lower()
    endpoint = MicrosoftEndpoint(host, timeout=timeout or 60)
    return _net_fetch(url, endpoint, max_bytes, method=method, headers=headers, data=data,
                      timeout=timeout)
