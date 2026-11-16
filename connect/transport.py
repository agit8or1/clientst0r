"""Outbound HTTP for Connect: always through core.safe_http (connect-time
SSRF / DNS-rebinding guard), strict TLS (system CAs, or only the
connection's private CA bundle), TLS 1.2+, no redirects, no proxies, capped
bodies. There is deliberately no option to disable certificate checks.

Tests replace `factory` with a router to the in-memory reference peer.
"""
from __future__ import annotations

from agit8or_connect.adapters.safe_http import SafeHttpTransport

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15


def _default_factory(*, allow_private=False, ca_pem=None, client_cert_pem=None, client_key_pem=None):
    return SafeHttpTransport(allow_private=allow_private, ca_pem=ca_pem or None, max_bytes=MAX_BYTES,
                             timeout=TIMEOUT, client_cert_pem=client_cert_pem or None,
                             client_key_pem=client_key_pem or None)


factory = _default_factory


def for_connection(connection):
    return factory(allow_private=connection.allow_private_network, ca_pem=connection.tls_ca_bundle,
                   client_cert_pem=connection.tls_client_cert, client_key_pem=connection.client_key_pem())


def for_settings(*, allow_private=False, ca_pem=''):
    return factory(allow_private=allow_private, ca_pem=ca_pem)
