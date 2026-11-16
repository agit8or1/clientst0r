"""Transport interface and a minimal SSRF-guarded stdlib transport.

The SDK never opens a socket except through a Transport:

    transport.request(method, url, headers=dict, body=bytes|None) -> Response

`default_transport()` returns Clientst0r's core.safe_http-backed transport
when that module is importable (agit8or_connect.adapters.safe_http), else
MinimalGuardedTransport, which:

  * accepts https only (http only for loopback when allow_loopback_http),
  * resolves the host ONCE, refuses if ANY address is not allowed (metadata
    and non-unicast always; private/loopback/link-local unless the operator
    explicitly allowed private networks), and connects to the validated IP
    literal so DNS cannot rebind between check and connect,
  * verifies TLS (system store or a configured private CA bundle; minimum
    TLS 1.2; hostname checked) — there is no switch to turn it off,
  * never follows redirects, ignores proxies, caps the body and the time.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol
from urllib.parse import urlsplit

from .errors import BLOCKED_DESTINATION, ConnectError, TOO_LARGE, TRANSPORT

DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 10.0

_ALWAYS_BLOCKED = tuple(ipaddress.ip_network(n) for n in (
    '0.0.0.0/8', '169.254.169.254/32', '169.254.170.2/32', '169.254.170.23/32', '192.0.0.192/32',
    '100.100.100.200/32', '224.0.0.0/4', '240.0.0.0/4', '255.255.255.255/32', '::/128', 'fd00:ec2::254/128',
    'ff00::/8'))


@dataclass
class Response:
    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b''

    def header(self, name: str) -> str:
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return ''


class Transport(Protocol):
    def request(self, method: str, url: str, headers: Optional[dict] = None,
                body: Optional[bytes] = None) -> Response: ...


def ip_allowed(ip: str, allow_private: bool) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if any(addr in n for n in _ALWAYS_BLOCKED):
        return False
    if addr.is_global and not (addr.is_private or addr.is_reserved or addr.is_multicast):
        return True
    return bool(allow_private)


class MinimalGuardedTransport:
    def __init__(self, *, allow_private: bool = False, ca_pem: Optional[str] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = DEFAULT_TIMEOUT,
                 allow_loopback_http: bool = False, resolver=socket.getaddrinfo):
        self.allow_private = allow_private
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.allow_loopback_http = allow_loopback_http
        self.resolver = resolver
        ctx = ssl.create_default_context(cadata=ca_pem) if ca_pem else ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        self.context = ctx

    def _resolve(self, host: str, port: int):
        try:
            infos = self.resolver(host, port, 0, socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise ConnectError(TRANSPORT, f'{host} did not resolve', 502) from e
        ips = []
        for info in infos:
            ip = info[4][0]
            if not ip_allowed(ip, self.allow_private):
                raise ConnectError(BLOCKED_DESTINATION, f'{host} resolves to an address this connection may not '
                                                        'use (enable private networks for this connection to '
                                                        'reach an internal address)', 502)
            if ip not in ips:
                ips.append(ip)
        if not ips:
            raise ConnectError(TRANSPORT, f'{host} did not resolve', 502)
        return ips

    def request(self, method, url, headers=None, body=None) -> Response:
        p = urlsplit(url)
        host = p.hostname or ''
        if p.username or p.password or not host:
            raise ConnectError(BLOCKED_DESTINATION, 'URL must have a host and no credentials', 400)
        if p.scheme == 'https':
            port = p.port or 443
        elif p.scheme == 'http' and self.allow_loopback_http and host in ('127.0.0.1', '::1', 'localhost'):
            port = p.port or 80
        else:
            raise ConnectError(BLOCKED_DESTINATION, 'only https is allowed', 400)
        ips = self._resolve(host, port)
        path = (p.path or '/') + (f'?{p.query}' if p.query else '')
        transport = self

        class _Conn(http.client.HTTPSConnection if p.scheme == 'https' else http.client.HTTPConnection):
            def connect(self_inner):
                sock = socket.create_connection((ips[0], port), transport.timeout)
                peer = sock.getpeername()[0]
                if peer not in ips:
                    sock.close()
                    raise ConnectError(BLOCKED_DESTINATION, 'connected peer is not the validated address', 502)
                if p.scheme == 'https':
                    sock = transport.context.wrap_socket(sock, server_hostname=host)
                self_inner.sock = sock

        kwargs = {'timeout': self.timeout}
        if p.scheme == 'https':
            kwargs['context'] = self.context
        conn = _Conn(host, port, **kwargs)
        try:
            conn.request(method, path, body=body, headers=dict(headers or {}))
            r = conn.getresponse()
            data = r.read(self.max_bytes + 1)
            if len(data) > self.max_bytes:
                raise ConnectError(TOO_LARGE, 'response too large', 502)
            return Response(r.status, {k: v for k, v in r.getheaders()}, data)
        except ConnectError:
            raise
        except ssl.SSLError as e:
            raise ConnectError(TRANSPORT, f'TLS verification failed for {host} ({e.__class__.__name__})', 502) from e
        except (OSError, http.client.HTTPException) as e:
            raise ConnectError(TRANSPORT, f'{host} could not be reached ({e.__class__.__name__})', 502) from e
        finally:
            conn.close()


def default_transport(**kwargs) -> Transport:
    try:
        from .adapters.safe_http import SafeHttpTransport, available
        if available():
            return SafeHttpTransport(**kwargs)
    except ImportError:
        pass
    return MinimalGuardedTransport(**kwargs)
