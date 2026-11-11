"""Outbound HTTP from clientst0r to an editor instance.

    allowed_fetch(url, instance) -> bool
    check_url(url, instance)                 raises DestinationNotAllowed
    fetch(url, instance, max_bytes, *, method='GET', headers=None, data=None,
          timeout=None) -> FetchResult        raises DestinationNotAllowed / OfficeFetchError

Every URL clientst0r fetches on an editor's behalf — an ONLYOFFICE download
URL from a save callback, Collabora discovery, conversion results, health
probes — goes through ``fetch``. Rules:

* The URL's origin (scheme, host, port) must be the origin of the instance's
  ``browser_url`` or ``internal_url``. Anything else is refused before any
  DNS lookup.
* The host is resolved once. Every address must pass ``ip_allowed``; the
  connection is then made to those already-checked addresses, so a second
  lookup cannot rebind the name (the hostname stays on the connection for
  SNI and certificate checks).
* Metadata / link-local / multicast / unspecified addresses are refused
  always (169.254.0.0/16 including 169.254.169.254, fe80::/10,
  fd00:ec2::254, 100.100.100.200, ...). Private ranges (RFC 1918, CGNAT,
  ULA) are allowed because the host is the approved editor host; loopback is
  allowed only for an instance installed on this server (mode
  ``same_server``). Nothing else about the global SSRF policy changes:
  core.safe_http is reused for its blocklists and stays as strict as before
  for every other caller.
* Redirects are followed manually (at most 3) and only to the same approved
  origin.
* TLS is verified: against the instance's private CA bundle (plus the
  default trust store) when one is set. ``verify_tls`` can only be turned off
  outside the UI and diagnostics flag it.
* Bodies are read in chunks under ``max_bytes`` and an overall deadline.
* Proxies and ~/.netrc are ignored.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from urllib3.util import connection as urllib3_connection

from core import safe_http

MAX_REDIRECTS = 3
MAX_URL_LENGTH = 4096

# On top of safe_http's always-blocked list: all of link-local, not only the
# known metadata addresses inside it.
_ALWAYS_BLOCKED = safe_http._ALWAYS_BLOCKED_NETWORKS + tuple(ipaddress.ip_network(n) for n in (
    '169.254.0.0/16', 'fe80::/10', 'fec0::/10',
))
_PRIVATE = tuple(ipaddress.ip_network(n) for n in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7',
))
_LOOPBACK = tuple(ipaddress.ip_network(n) for n in ('127.0.0.0/8', '::1/128'))

# Indirection points so tests can simulate DNS and sockets.
_getaddrinfo = socket.getaddrinfo
_create_connection = urllib3_connection.create_connection


class OfficeFetchError(Exception):
    """The fetch failed. Message is for logs and admin diagnostics, no secrets."""


class DestinationNotAllowed(OfficeFetchError, ValueError):
    pass


@dataclass
class FetchResult:
    url: str
    status_code: int
    headers: dict
    content: bytes
    peer_ip: str = ''
    redirects: list = field(default_factory=list)


def _origin(url):
    parts = urlsplit(url)
    scheme = (parts.scheme or '').lower()
    host = (parts.hostname or '').lower().rstrip('.')
    port = parts.port or (443 if scheme == 'https' else 80 if scheme == 'http' else None)
    return scheme, host, port


def approved_origins(instance) -> set:
    out = set()
    for url in (instance.browser_url, instance.internal_url):
        if url:
            try:
                out.add(_origin(url))
            except ValueError:
                continue
    return out


def _unmap(ip):
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in safe_http._NAT64_PREFIX:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def ip_allowed(value, instance) -> bool:
    try:
        ip = ipaddress.ip_address(str(value).split('%')[0])
    except ValueError:
        return False
    if '%' in str(value):
        return False   # scoped (link-local) IPv6
    ip = _unmap(ip)
    if any(ip in net for net in _ALWAYS_BLOCKED) or ip.is_multicast or ip.is_unspecified:
        return False
    if safe_http.is_public_ip(ip):
        return True
    if any(ip in net for net in _LOOPBACK):
        return instance.mode == 'same_server'
    return any(ip in net for net in _PRIVATE)


def check_url(url, instance) -> str:
    """Raise DestinationNotAllowed unless `url` may be fetched for `instance`."""
    if not isinstance(url, str) or not url.strip():
        raise DestinationNotAllowed('Empty URL')
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise DestinationNotAllowed('URL too long')
    if any(ord(c) <= 0x20 or ord(c) == 0x7f or c == '\\' for c in url):
        raise DestinationNotAllowed('URL contains whitespace, control or backslash characters')
    try:
        parts = urlsplit(url)
        origin = _origin(url)
    except ValueError as e:
        raise DestinationNotAllowed(f'Malformed URL: {e}')
    if origin[0] not in ('http', 'https'):
        raise DestinationNotAllowed('Only http(s) URLs are fetched')
    if '@' in parts.netloc:
        raise DestinationNotAllowed('URLs with credentials are not fetched')
    if origin not in approved_origins(instance):
        raise DestinationNotAllowed('The URL is not on the editor instance\'s approved host')
    host = origin[1]
    try:
        literal = ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        literal = None
    if literal is not None and not ip_allowed(literal, instance):
        raise DestinationNotAllowed('The address is not allowed')
    if host in safe_http._ALWAYS_BLOCKED_HOSTNAMES:
        raise DestinationNotAllowed('The host is not allowed')
    return url


def allowed_fetch(url, instance) -> bool:
    try:
        check_url(url, instance)
    except DestinationNotAllowed:
        return False
    return True


def resolve(host, port, instance) -> list:
    """All addresses of `host`, or DestinationNotAllowed if any is refused.
    One DNS lookup; the result is what fetch() connects to."""
    host = host.strip('[]').rstrip('.')
    try:
        infos = _getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise OfficeFetchError(f'{host} did not resolve: {e}')
    addresses = []
    for info in infos:
        ip = info[4][0]
        if not ip_allowed(ip, instance):
            raise DestinationNotAllowed(f'{host} resolves to an address that is not allowed')
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise OfficeFetchError(f'{host} did not resolve')
    return addresses


# ---------------------------------------------------------------------------
# Pinned connections
# ---------------------------------------------------------------------------

class _PinnedMixin:
    _pinned = ()
    _instance = None

    def _new_conn(self):
        sock, last_error = None, None
        for ip in self._pinned:
            try:
                sock = _create_connection((ip, self.port), self.timeout,
                                          source_address=self.source_address,
                                          socket_options=self.socket_options)
                break
            except socket.timeout as e:
                last_error = ConnectTimeoutError(self, f'Connection to {self.host} timed out')
                last_error.__cause__ = e
            except OSError as e:
                last_error = NewConnectionError(self, f'Failed to establish a new connection: {e}')
        if sock is None:
            raise last_error or NewConnectionError(self, 'No address to connect to')
        try:
            peer = sock.getpeername()[0]
        except OSError as e:
            sock.close()
            raise NewConnectionError(self, f'Could not read peer address: {e}')
        if peer not in self._pinned or not ip_allowed(peer, self._instance):
            sock.close()
            raise DestinationNotAllowed('Connected peer is not an approved address')
        return sock


def _adapter(pinned, instance):
    attrs = {'_pinned': tuple(pinned), '_instance': instance}
    http_conn = type('_OfficeHTTPConnection', (_PinnedMixin, HTTPConnection), attrs)
    https_conn = type('_OfficeHTTPSConnection', (_PinnedMixin, HTTPSConnection), attrs)
    pools = {
        'http': type('_OfficeHTTPPool', (HTTPConnectionPool,), {'ConnectionCls': http_conn}),
        'https': type('_OfficeHTTPSPool', (HTTPSConnectionPool,), {'ConnectionCls': https_conn}),
    }

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = dict(pools)

        def proxy_manager_for(self, *args, **kwargs):
            raise DestinationNotAllowed('Proxies are not used for editor connections')

    return _Adapter(max_retries=0)


class _Trust:
    """verify= value for requests: True, False, or a temp CA file path."""

    def __init__(self, instance):
        self.path = None
        if not instance.verify_tls:
            self.value = False
            return
        bundle = (instance.ca_bundle or '').strip()
        if not bundle:
            self.value = True
            return
        try:
            import certifi
            base = open(certifi.where(), 'r', encoding='ascii', errors='ignore').read()
        except Exception:
            base = ''
        fd, self.path = tempfile.mkstemp(prefix='office-ca-', suffix='.pem')
        with os.fdopen(fd, 'w') as fh:
            fh.write(base + '\n' + bundle + '\n')
        self.value = self.path

    def close(self):
        if self.path:
            try:
                os.unlink(self.path)
            except OSError:
                pass


def _read_capped(response, max_bytes, deadline):
    declared = response.headers.get('Content-Length')
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise OfficeFetchError(f'Response is larger than {max_bytes} bytes')
    chunks, total = [], 0
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > max_bytes:
            raise OfficeFetchError(f'Response is larger than {max_bytes} bytes')
        if time.monotonic() > deadline:
            raise OfficeFetchError('Timed out reading the response')
        chunks.append(chunk)
    return b''.join(chunks)


def fetch(url, instance, max_bytes, *, method='GET', headers=None, data=None,
          timeout=None) -> FetchResult:
    """Fetch `url` from the editor `instance`. See the module docstring."""
    connect_t = float(instance.connect_timeout_s or 5)
    total_t = float(timeout or instance.request_timeout_s or 30)
    deadline = time.monotonic() + total_t
    current = url
    redirects = []
    trust = _Trust(instance)
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            current = check_url(current, instance)
            scheme, host, port = _origin(current)
            pinned = resolve(host, port, instance)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OfficeFetchError('Timed out')
            with requests.Session() as session:
                session.trust_env = False
                adapter = _adapter(pinned, instance)
                session.mount('http://', adapter)
                session.mount('https://', adapter)
                try:
                    response = session.request(
                        method, current, headers=headers, data=data,
                        timeout=(min(connect_t, remaining), min(total_t, remaining)),
                        allow_redirects=False, stream=True, verify=trust.value)
                except DestinationNotAllowed:
                    raise
                except requests.exceptions.SSLError as e:
                    raise OfficeFetchError(f'TLS verification failed: {e}') from e
                except requests.Timeout as e:
                    raise OfficeFetchError(f'Timed out: {e}') from e
                except requests.RequestException as e:
                    cause = e
                    while cause is not None:
                        if isinstance(cause, DestinationNotAllowed):
                            raise cause
                        cause = cause.__cause__ or cause.__context__
                    raise OfficeFetchError(f'Request failed: {e}') from e
                with response:
                    if response.is_redirect:
                        target = urljoin(current, response.headers.get('Location', ''))
                        if _origin(target) != _origin(current):
                            raise DestinationNotAllowed('Redirect to a different host refused')
                        redirects.append(target)
                        current = target
                        continue
                    body = _read_capped(response, max_bytes, deadline)
                    return FetchResult(current, response.status_code, dict(response.headers),
                                       body, peer_ip=pinned[0], redirects=redirects)
        raise OfficeFetchError(f'More than {MAX_REDIRECTS} redirects')
    finally:
        trust.close()
