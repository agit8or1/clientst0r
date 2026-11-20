"""Outbound HTTP for Connect: always through core.safe_http (connect-time
SSRF / DNS-rebinding guard), strict TLS (system CAs, or only the
connection's private CA bundle), TLS 1.2+, no redirects, no proxies, capped
bodies. There is deliberately no option to disable certificate checks.

The destination policy is Connect's own (PROTOCOL.md §4), never the
site-wide ALLOW_PRIVATE_IP_INTEGRATIONS opt-in: loopback, link-local and
metadata addresses are always refused, private ranges only when the
connection allows private networks, and only port 443 or the explicit port
of the connection's base URL.

Tests replace `factory` with a router to the in-memory reference peer.
"""
from __future__ import annotations

from agit8or_connect.adapters.safe_http import SafeHttpTransport, ports_for

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15


def _default_factory(*, allow_private=False, ca_pem=None, client_cert_pem=None, client_key_pem=None,
                     allowed_ports=None):
    return SafeHttpTransport(allow_private=allow_private, ca_pem=ca_pem or None, max_bytes=MAX_BYTES,
                             timeout=TIMEOUT, client_cert_pem=client_cert_pem or None,
                             client_key_pem=client_key_pem or None, allowed_ports=allowed_ports)


factory = _default_factory


def for_connection(connection):
    return factory(allow_private=connection.allow_private_network, ca_pem=connection.tls_ca_bundle,
                   client_cert_pem=connection.tls_client_cert, client_key_pem=connection.client_key_pem(),
                   allowed_ports=ports_for(connection.base_url))


def for_settings(*, allow_private=False, ca_pem='', base_url=''):
    """Before a connection exists (discovery): 443 plus the explicit port of
    the address the administrator typed."""
    return factory(allow_private=allow_private, ca_pem=ca_pem, allowed_ports=ports_for(base_url))
