"""Harness-only address simulation on 127.0.0.1 (never imported by the app).

Agit8or Connect never connects to loopback (PROTOCOL.md §4, roadmap 79.8),
and protocol 1.1 refuses a loopback egress declaration. To run two real
installations on 127.0.0.1 without changing that policy, each installation
gets a simulated private address in SIM_NET (RFC 1918), the way the public
agit8or-connect harness maps documentation addresses to local ports:

  * name resolution: ``*.interop.test`` names resolve, through the harness's
    resolver file (re-read on every lookup, so a test can "change DNS"),
    to simulated addresses. Every other name goes to the real resolver.
  * dialling: a TCP connection to a simulated address goes to 127.0.0.1,
    port 443 to that installation's own high port (the file's ``ports``
    map: the port forward a reverse proxy would do), from this process's
    own loopback source alias
    (INTEROP_SOURCE, e.g. 127.0.0.11). The socket reports the simulated
    address as its peer, so the app's connect-time checks (every resolved
    and the connected address inside the approved set) run unchanged.
  * inbound: ``translate_remote_addr`` maps the loopback source alias of a
    request to the sender's simulated address (a NAT table in the same
    file). The browser / driver (127.0.0.1) is not translated.

TLS, HTTP, gunicorn workers, sockets and every Connect check are real; only
the address labels are simulated. Nothing listens anywhere but 127.0.0.1.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket

SIM_NET = ipaddress.ip_network('10.231.0.0/16')
SUFFIX = '.interop.test'

_real_getaddrinfo = socket.getaddrinfo
_real_create_connection = socket.create_connection
_installed = False


def _cfg() -> dict:
    path = os.environ.get('INTEROP_NET_FILE', '')
    if not path:
        return {}
    with open(path) as f:
        return json.load(f)


def _is_sim(ip) -> bool:
    try:
        return ipaddress.ip_address(ip) in SIM_NET
    except ValueError:
        return False


def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    h = host.decode() if isinstance(host, bytes) else str(host or '')
    h = h.lower().rstrip('.')
    if h.endswith(SUFFIX):
        ips = _cfg().get('hosts', {}).get(h) or []
        if not ips:
            raise socket.gaierror(socket.EAI_NONAME, 'Name or service not known')
        if family not in (0, socket.AF_INET, socket.AF_UNSPEC):
            raise socket.gaierror(socket.EAI_ADDRFAMILY, 'no address of that family')
        p = int(port or 0)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, p)) for ip in ips]
    return _real_getaddrinfo(host, port, family, type, proto, flags)


class _SimSocket(socket.socket):
    """A connected TCP socket that reports the simulated peer address."""
    __slots__ = ('_sim_peer',)

    def getpeername(self):
        return self._sim_peer


def _dial(ip, port, timeout, socket_options=None):
    src = os.environ.get('INTEROP_SOURCE', '127.0.0.1')
    cfg = _cfg()
    if ip in cfg.get('unreachable', []):
        raise ConnectionRefusedError(111, 'Connection refused (harness: address unreachable)')
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        for opt in socket_options or ():
            raw.setsockopt(*opt)
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            raw.settimeout(timeout)
        raw.bind((src, 0))
        target = int(port)
        if target == 443:
            target = int(cfg.get('ports', {}).get(ip, 443))
        raw.connect(('127.0.0.1', target))
    except BaseException:
        raw.close()
        raise
    t = raw.gettimeout()
    s = _SimSocket(raw.family, raw.type, raw.proto, fileno=raw.detach())
    s.settimeout(t)
    s._sim_peer = (ip, int(port))
    return s


def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *args, **kwargs):
    host, port = address[0], address[1]
    if _is_sim(host):
        return _dial(host, port, timeout)
    return _real_create_connection(address, timeout, source_address, *args, **kwargs)


def _urllib3_create_connection(real):
    def wrapper(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, socket_options=None):
        host, port = address[0], address[1]
        if _is_sim(host):
            return _dial(host, port, timeout, socket_options)
        return real(address, timeout, source_address, socket_options)
    return wrapper


def install():
    """Patch name resolution and dialling in THIS process (harness settings only)."""
    global _installed
    if _installed:
        return
    socket.getaddrinfo = getaddrinfo
    socket.create_connection = create_connection
    from urllib3.util import connection as u3
    u3.create_connection = _urllib3_create_connection(u3.create_connection)
    _installed = True


def translate_remote_addr(remote: str) -> str:
    """Inbound NAT: loopback source alias -> the sender's simulated address."""
    return _cfg().get('nat', {}).get(remote, remote)
