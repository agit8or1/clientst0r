"""
Outbound HTTP to user-supplied URLs, with SSRF protection.

Use `fetch_public_url()` whenever a URL that a user typed is fetched
server-side. It refuses anything that is not a public http(s) address on
port 80 or 443.

Two layers, because either one alone can be bypassed:

  * `validate_public_url()` checks the URL text: scheme, credentials, port,
    hostname, and literal IPs in any spelling. It runs on the original URL
    and again on every redirect target.

  * `_GuardedConnectionMixin._new_conn()` is the authoritative check. It
    runs at socket-open time inside urllib3. It resolves the hostname once,
    refuses if *any* resolved address is non-public, connects to the
    already-validated IP literal (so no second DNS lookup can rebind it),
    and re-checks the connected peer. The hostname stays on the connection,
    so SNI, certificate verification and the Host header are unchanged.

Redirects are followed manually (max `MAX_REDIRECTS`), proxies and .netrc
are ignored, and the body is read in chunks under a byte cap and a
wall-clock deadline.
"""
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util import connection as urllib3_connection

ALLOWED_SCHEMES = frozenset({'http', 'https'})
ALLOWED_PORTS = frozenset({80, 443})
MAX_REDIRECTS = 3
MAX_URL_LENGTH = 2048
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
TOTAL_TIMEOUT = 25

HTML_CONTENT_TYPES = frozenset({'text/html', 'application/xhtml+xml', 'text/plain'})

_BLOCKED_HOSTNAMES = frozenset({
    'localhost', 'localhost.localdomain', 'ip6-localhost', 'ip6-loopback',
    'metadata', 'metadata.google.internal', 'instance-data',
})
_BLOCKED_SUFFIXES = ('.localhost', '.local', '.localdomain', '.internal', '.home.arpa', '.arpa')

# Explicit list on top of the `ipaddress` flags, so protection does not
# depend on which ranges a given Python release classifies as global.
_BLOCKED_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    # IPv4
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
    '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24', '192.88.99.0/24',
    '192.168.0.0/16', '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24',
    '224.0.0.0/4', '240.0.0.0/4', '255.255.255.255/32',
    # IPv6
    '::/128', '::1/128', '::ffff:0:0/96', '64:ff9b:1::/48', '100::/64',
    '2001::/23', '2001:db8::/32', '2002::/16', '3fff::/20', 'fc00::/7',
    'fe80::/10', 'fec0::/10', 'ff00::/8',
))
_NAT64_PREFIX = ipaddress.ip_network('64:ff9b::/96')


class UnsafeURLError(ValueError):
    """The URL or the address it leads to is not allowed. Message is for logs only."""


class FetchError(Exception):
    """The fetch failed (timeout, connection, status, size, content). Message is for logs only."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str


def is_public_ip(value) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False

    if ip.version == 6:
        if ip.scope_id:
            return False
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip in _NAT64_PREFIX:
            return is_public_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.is_site_local:
            return False

    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_unspecified or ip.is_reserved or not ip.is_global):
        return False
    return not any(ip in net for net in _BLOCKED_NETWORKS)


def _looks_like_ipv4(host: str) -> bool:
    """WHATWG rule: a host whose last label is numeric is parsed as IPv4.

    Catches decimal (2130706433), hex (0x7f.1), octal (0177.0.0.1) and
    shortened (127.1) forms that resolvers accept but that are not
    canonical dotted quads.
    """
    last = host.rsplit('.', 1)[-1]
    if last.isdigit():
        return True
    return last.startswith('0x') and all(c in '0123456789abcdef' for c in last[2:])


def validate_public_url(url) -> str:
    """Check the URL text. Returns the stripped URL or raises UnsafeURLError.

    This is not sufficient on its own; DNS is re-checked at connect time.
    """
    if not isinstance(url, str):
        raise UnsafeURLError('URL must be a string')
    url = url.strip()
    if not url:
        raise UnsafeURLError('URL is empty')
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeURLError('URL too long')
    if any(ord(c) <= 0x20 or ord(c) == 0x7f or c == '\\' for c in url):
        raise UnsafeURLError('URL contains whitespace, control or backslash characters')

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise UnsafeURLError(f'Malformed URL: {e}') from None

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f'Scheme not allowed: {parts.scheme!r}')
    if not parts.netloc or '@' in parts.netloc:
        raise UnsafeURLError('URL must have a host and no embedded credentials')
    if port is not None and port not in ALLOWED_PORTS:
        raise UnsafeURLError(f'Port not allowed: {port}')

    host = (parts.hostname or '').lower()
    if host.endswith('.'):
        host = host[:-1]
    if not host or host.endswith('.') or '%' in host:
        raise UnsafeURLError('Invalid hostname')

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if not is_public_ip(literal):
            raise UnsafeURLError(f'Address not allowed: {host}')
        return url

    if ':' in host or _looks_like_ipv4(host):
        raise UnsafeURLError(f'Non-canonical IP address: {host}')
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError(f'Hostname not allowed: {host}')
    try:
        host.encode('idna')
    except UnicodeError:
        raise UnsafeURLError('Invalid hostname') from None
    return url


def resolve_public_addresses(host: str, port: int) -> list:
    """Resolve `host` and return its addresses, or raise if any is non-public.

    Rejecting on *any* blocked record (not just the first) stops a name that
    publishes one public and one internal address.
    """
    host = host.strip('[]').rstrip('.')
    infos = socket.getaddrinfo(host, port, urllib3_connection.allowed_gai_family(), socket.SOCK_STREAM)
    addresses = []
    for info in infos:
        ip = info[4][0]
        if not is_public_ip(ip):
            raise UnsafeURLError(f'{host} resolves to a non-public address')
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise UnsafeURLError(f'{host} did not resolve')
    return addresses


class _GuardedConnectionMixin:
    """Replaces urllib3's resolve-and-connect with a validated one."""

    def _new_conn(self):
        if self.port not in ALLOWED_PORTS:
            raise UnsafeURLError(f'Port not allowed: {self.port}')
        try:
            addresses = resolve_public_addresses(self._dns_host, self.port)
        except socket.gaierror as e:
            raise NameResolutionError(self.host, self, e) from e

        sock, last_error = None, None
        for ip in addresses:
            try:
                # An IP literal: create_connection's getaddrinfo is purely
                # numeric here, so DNS is not consulted a second time.
                sock = urllib3_connection.create_connection(
                    (ip, self.port), self.timeout,
                    source_address=self.source_address,
                    socket_options=self.socket_options,
                )
                break
            except socket.timeout as e:
                last_error = ConnectTimeoutError(self, f'Connection to {self.host} timed out')
                last_error.__cause__ = e
            except OSError as e:
                last_error = NewConnectionError(self, f'Failed to establish a new connection: {e}')
        if sock is None:
            raise last_error

        try:
            peer = sock.getpeername()[0]
        except OSError as e:
            sock.close()
            raise NewConnectionError(self, f'Could not read peer address: {e}') from e
        if peer not in addresses or not is_public_ip(peer):
            sock.close()
            raise UnsafeURLError('Connected peer is not an allowed address')
        return sock


class _GuardedHTTPConnection(_GuardedConnectionMixin, HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedConnectionMixin, HTTPSConnection):
    pass


class _GuardedHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _GuardedHTTPSConnection


class GuardedHTTPAdapter(HTTPAdapter):
    """requests adapter whose every socket goes through the guard."""

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            'http': _GuardedHTTPConnectionPool,
            'https': _GuardedHTTPSConnectionPool,
        }

    def proxy_manager_for(self, *args, **kwargs):
        # Through a proxy the proxy does the DNS, and the guard would only
        # see the proxy's address.
        raise UnsafeURLError('Proxies are not supported for guarded fetches')


def build_guarded_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # ignore *_PROXY env vars and ~/.netrc
    adapter = GuardedHTTPAdapter(max_retries=0)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def _read_capped(response, max_bytes: int, deadline: float) -> bytes:
    declared = response.headers.get('Content-Length')
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise FetchError(f'Declared Content-Length {declared} exceeds {max_bytes}')

    chunks, total = [], 0
    for chunk in response.iter_content(chunk_size=16384):
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f'Response exceeds {max_bytes} bytes')
        if time.monotonic() > deadline:
            raise FetchError('Total fetch deadline exceeded')
        chunks.append(chunk)
    return b''.join(chunks)


def fetch_public_url(
    url: str,
    *,
    headers: Optional[dict] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allowed_content_types=HTML_CONTENT_TYPES,
    total_timeout: float = TOTAL_TIMEOUT,
) -> FetchResult:
    """GET a public URL safely and return its decoded text.

    Raises UnsafeURLError for a disallowed destination (including via a
    redirect) and FetchError for every other failure. Neither message is
    meant for end users.
    """
    deadline = time.monotonic() + total_timeout
    current = url

    with build_guarded_session() as session:
        for _hop in range(MAX_REDIRECTS + 1):
            current = validate_public_url(current)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError('Total fetch deadline exceeded')
            timeout = (min(CONNECT_TIMEOUT, remaining), min(READ_TIMEOUT, remaining))

            try:
                response = session.get(
                    current, headers=headers, timeout=timeout,
                    allow_redirects=False, stream=True,
                )
            except requests.Timeout as e:
                raise FetchError(f'Timed out: {e}') from e
            except requests.RequestException as e:
                raise FetchError(f'Request failed: {e}') from e

            with response:
                if response.is_redirect:
                    current = urljoin(current, response.headers['Location'])
                    continue
                if response.status_code >= 400:
                    raise FetchError(f'Upstream returned HTTP {response.status_code}')
                if response.status_code != 200:
                    raise FetchError(f'Unexpected upstream status {response.status_code}')

                content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                if allowed_content_types and content_type and content_type not in allowed_content_types:
                    raise FetchError(f'Unsupported content type {content_type!r}')

                try:
                    body = _read_capped(response, max_bytes, deadline)
                except requests.RequestException as e:
                    raise FetchError(f'Failed reading body: {e}') from e

                if b'\x00' in body[:4096]:
                    raise FetchError('Response looks binary')
                encoding = response.encoding or 'utf-8'
                try:
                    text = body.decode(encoding, errors='replace')
                except LookupError:
                    text = body.decode('utf-8', errors='replace')
                return FetchResult(current, response.status_code, content_type, text)

    raise FetchError(f'More than {MAX_REDIRECTS} redirects')
