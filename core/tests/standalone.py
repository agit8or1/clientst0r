"""Helpers that prove Clientst0r works with no peer and no network
(docs/ux/STANDALONE_REQUIREMENTS.md, test matrix A, H, O).

``no_network()``
    Any outbound connection (a TCP/UDP ``connect``, ``create_connection``, a
    DNS lookup, ``requests``, urllib3, ``urllib.request``, httpx) raises
    ``OutboundBlocked`` at once and is recorded in ``.attempts``. Unix-domain
    sockets are not outbound and stay allowed. Use as a context manager, a
    decorator, or ``NoNetworkMixin`` on a TestCase.

``peer_unreachable()``
    Simulates a configured peer (a Rem0te provider row, a Connect pairing or an
    RMM connection) whose HTTP calls fail: ``mode='refuse'`` raises a
    connection error immediately, ``mode='timeout'`` raises a timeout
    immediately (it never waits). The patch sits at the HTTP client layer
    (``requests.Session.request`` and ``HTTPAdapter.send``, the Rem0te client and
    the Connect transport) and also blocks sockets, so every attempt is
    recorded in ``.attempts`` as ``(layer, method, url)``.

Assert ``len(guard.attempts) == 0`` for anything that must not call out
(rendering a page). Use the helpers inside a test; they are not used at runtime.
"""
from __future__ import annotations

import contextlib
import functools
import socket
import urllib.request
from unittest import mock

import requests


class OutboundBlocked(OSError):
    """An outbound connection was attempted while no network is allowed."""


class OutboundBlockedHTTP(OutboundBlocked, requests.exceptions.ConnectionError):
    """The same for an HTTP call: also a ``requests`` ConnectionError, so code
    that handles an offline network behaves as it would in production."""


def _is_local_socket(sock) -> bool:
    return getattr(sock, 'family', None) == getattr(socket, 'AF_UNIX', object())


class NetworkGuard:
    """Records and refuses outbound connections while active."""

    def __init__(self, mode: str = 'block'):
        # mode 'block': raise OutboundBlocked; 'refuse'/'timeout': raise the error a dead peer gives.
        self.mode = mode
        self.attempts: list[tuple[str, str, str]] = []
        self._stack: contextlib.ExitStack | None = None

    # -- bookkeeping ---------------------------------------------------
    def record(self, layer, method, target):
        self.attempts.append((layer, str(method), str(target)))

    def _fail_socket(self, layer, target):
        self.record(layer, 'CONNECT', target)
        raise OutboundBlocked(f'outbound connection attempted ({layer}): {target}')

    def _fail_http(self, layer, method, url):
        self.record(layer, method, url)
        if self.mode == 'timeout':
            raise requests.exceptions.ConnectTimeout(f'simulated: {url} did not answer')
        if self.mode == 'refuse':
            raise requests.exceptions.ConnectionError(f'simulated: {url} refused the connection')
        raise OutboundBlockedHTTP(f'outbound HTTP request attempted ({layer}): {method} {url}')

    # -- patches -------------------------------------------------------
    def __enter__(self):
        guard = self
        stack = contextlib.ExitStack()
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex

        def connect(sock, address):
            if _is_local_socket(sock):
                return orig_connect(sock, address)
            guard._fail_socket('socket.connect', address)

        def connect_ex(sock, address):
            if _is_local_socket(sock):
                return orig_connect_ex(sock, address)
            guard._fail_socket('socket.connect_ex', address)

        def create_connection(address, *a, **kw):
            guard._fail_socket('socket.create_connection', address)

        def getaddrinfo(host, port, *a, **kw):
            guard._fail_socket('socket.getaddrinfo', f'{host}:{port}')

        def session_request(session, method, url, *a, **kw):
            guard._fail_http('requests.Session.request', method, url)

        def adapter_send(adapter, request, *a, **kw):
            guard._fail_http('requests.HTTPAdapter.send', request.method, request.url)

        def urlopen(url, *a, **kw):
            target = getattr(url, 'full_url', url)
            guard._fail_http('urllib.request.urlopen', 'GET', target)

        for obj, name, fn in ((socket.socket, 'connect', connect), (socket.socket, 'connect_ex', connect_ex),
                              (socket, 'create_connection', create_connection),
                              (socket, 'getaddrinfo', getaddrinfo),
                              (requests.Session, 'request', session_request),
                              (requests.adapters.HTTPAdapter, 'send', adapter_send),
                              (urllib.request, 'urlopen', urlopen)):
            stack.enter_context(mock.patch.object(obj, name, fn))
        try:
            import httpx
        except ImportError:
            httpx = None
        if httpx is not None:
            def httpx_send(client, request, *a, **kw):
                guard._fail_http('httpx.Client.send', request.method, request.url)

            def httpx_async_send(client, request, *a, **kw):
                guard._fail_http('httpx.AsyncClient.send', request.method, request.url)
            stack.enter_context(mock.patch.object(httpx.Client, 'send', httpx_send))
            stack.enter_context(mock.patch.object(httpx.AsyncClient, 'send', httpx_async_send))
        self._stack = stack
        return self

    def __exit__(self, *exc):
        stack, self._stack = self._stack, None
        return stack.__exit__(*exc) if stack else False

    def __call__(self, fn):
        """Decorator form: the guard is entered for each call; the guard
        object is not passed to the function (use the context form to read
        ``.attempts``)."""
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            with self.__class__(self.mode):
                return fn(*a, **kw)
        return wrapper


def no_network() -> NetworkGuard:
    """Context manager / decorator: any outbound connection raises at once."""
    return NetworkGuard('block')


class _PeerUnreachable(NetworkGuard):
    """no_network() plus the peer clients answering "down" without waiting."""

    def __enter__(self):
        super().__enter__()
        guard = self
        try:
            from integrations.rem0te import client as rem0te_client

            def rem0te_request(connection, method, path, *a, **kw):
                guard.record('rem0te.client.request', method, f'{getattr(connection, "base_url", "")}{path}')
                return rem0te_client.Result(False, code='UNREACHABLE',
                                            transport='timeout' if guard.mode == 'timeout' else 'refused',
                                            message='simulated: the peer did not answer')
            self._stack.enter_context(mock.patch.object(rem0te_client, 'request', rem0te_request))
        except (ImportError, AttributeError):
            pass
        try:
            from connect import transport

            def for_connection(connection, *a, **kw):
                guard.record('connect.transport.for_connection', 'GET', getattr(connection, 'base_url', ''))
                raise requests.exceptions.ConnectionError('simulated: the Connect peer is unreachable')
            self._stack.enter_context(mock.patch.object(transport, 'for_connection', for_connection))
        except (ImportError, AttributeError):
            pass
        return self


def peer_unreachable(mode: str = 'timeout') -> _PeerUnreachable:
    """A configured peer (Rem0te row, Connect pairing, RMM connection) that
    does not answer. ``mode`` is 'timeout' or 'refuse'. Never waits."""
    if mode not in ('timeout', 'refuse'):
        raise ValueError(mode)
    return _PeerUnreachable(mode)


class NoNetworkMixin:
    """TestCase mixin: the whole test runs under no_network(); the guard is
    ``self.net`` and ``self.assertNoOutbound()`` checks it."""

    def setUp(self):
        super().setUp()
        self.net = no_network()
        self.net.__enter__()
        self.addCleanup(self.net.__exit__, None, None, None)

    def assertNoOutbound(self, msg=''):
        self.assertEqual(self.net.attempts, [], msg or 'outbound attempts')
