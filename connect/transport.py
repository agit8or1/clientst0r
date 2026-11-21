"""Outbound HTTP for Connect: always through core.safe_http (connect-time
SSRF / DNS-rebinding guard), strict TLS (system CAs, or only the
connection's private CA bundle), TLS 1.2+, no redirects, no proxies, capped
bodies. There is deliberately no option to disable certificate checks.

The destination policy is Connect's own (PROTOCOL.md §4), never the
site-wide ALLOW_PRIVATE_IP_INTEGRATIONS opt-in: loopback, link-local and
metadata addresses are always refused, private ranges only when approved
for the connection, and only port 443 or the explicit port of the
connection's base URL.

Approved destinations (Quick Connect B2, connect/destinations.py): a
connection's transport is pinned to its approved address set (every
resolved and the connected address must be inside it) and, when set, to
its SPKI pins. A connection without approved addresses makes no request
(``destination_unapproved``). A destination change, SPKI mismatch or
certificate name mismatch moves the connection to Security Blocked.

Tests replace `factory` with a router to the in-memory reference peer, and
`probe` with a fixed preview.
"""
from __future__ import annotations

from agit8or_connect.adapters.safe_http import SafeHttpTransport, ports_for
from agit8or_connect.errors import ConnectError

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15


def _default_factory(*, allow_private=False, ca_pem=None, client_cert_pem=None, client_key_pem=None,
                     allowed_ports=None, pinned=None, spki_pins=None):
    return SafeHttpTransport(allow_private=allow_private, ca_pem=ca_pem or None, max_bytes=MAX_BYTES,
                             timeout=TIMEOUT, client_cert_pem=client_cert_pem or None,
                             client_key_pem=client_key_pem or None, allowed_ports=allowed_ports,
                             pinned=pinned, spki_pins=spki_pins)


factory = _default_factory


def probe(url, *, allow_private=False, ca_pem=''):
    """DNS + TLS handshake preview of a destination (no HTTP request)."""
    from . import destinations
    return destinations.probe(url, allow_private=allow_private, ca_pem=ca_pem)


def for_destination(base_url, *, allow_private=False, ca_pem='', pinned=None, spki_pins=None,
                    client_cert_pem='', client_key_pem=''):
    return factory(allow_private=allow_private, ca_pem=ca_pem, client_cert_pem=client_cert_pem,
                   client_key_pem=client_key_pem, allowed_ports=ports_for(base_url), pinned=pinned,
                   spki_pins=spki_pins)


class _Watched:
    """The connection's transport: security failures block the connection."""

    def __init__(self, inner, connection):
        self.inner, self.connection = inner, connection

    def request(self, method, url, headers=None, body=None):
        from . import destinations
        try:
            return self.inner.request(method, url, headers=headers, body=body)
        except ConnectError as e:
            if e.code in destinations.SECURITY_CODES:
                destinations.security_block(self.connection, e.code, getattr(e, 'evidence', None))
            raise


def for_connection(connection):
    from . import destinations
    dest = destinations.get(connection)
    if dest is None or not dest.addresses:
        raise ConnectError(destinations.UNAPPROVED, destinations.MESSAGES[destinations.UNAPPROVED], 409)
    inner = for_destination(connection.base_url, allow_private=dest.has_private,
                            ca_pem=dest.ca_bundle or connection.tls_ca_bundle, pinned=dest.pinned(),
                            spki_pins=frozenset(dest.spki_pins) if dest.spki_pins else None,
                            client_cert_pem=connection.tls_client_cert,
                            client_key_pem=connection.client_key_pem())
    return _Watched(inner, connection)


def for_settings(*, allow_private=False, ca_pem='', base_url='', addresses=None):
    """Before a connection exists (discovery): 443 plus the explicit port of
    the address the administrator typed, pinned to the addresses just
    resolved for the preview."""
    import ipaddress
    pinned = frozenset(ipaddress.ip_network(a, strict=False) for a in addresses) if addresses is not None else None
    return for_destination(base_url, allow_private=allow_private, ca_pem=ca_pem, pinned=pinned)
