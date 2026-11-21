"""Transport backed by Clientst0r's core.safe_http (requests + the
connect-time SSRF guard: DNS resolved once, every address checked, the
socket opened to the validated IP, peer re-checked).

Used automatically by `agit8or_connect.http.default_transport()` when
core.safe_http is importable. TLS is always verified (system CAs, or ONLY the
connection's private CA bundle when one is configured), minimum TLS 1.2,
redirects never followed, proxies ignored, body capped.

Destination policy (PROTOCOL.md §4). It never follows the site-wide
ALLOW_PRIVATE_IP_INTEGRATIONS opt-in:

  * loopback, link-local and cloud metadata addresses are always refused;
  * RFC1918 / CGNAT / ULA addresses only with ``allow_private`` (the
    per-connection "private network" setting);
  * port 443 only, plus the ports passed in ``allowed_ports`` (the explicit
    port of the connection's base URL);
  * with ``pinned`` (approved destination addresses / ranges), EVERY address
    the host resolves to and the connected peer must be inside it, or the
    request fails with ``destination_changed`` before any byte is sent;
  * with ``spki_pins``, the leaf certificate's SPKI SHA-256 must match one of
    them (``spki_mismatch``); a certificate that does not name the host or IP
    gives ``certificate_name_mismatch``.

TLS material never touches the disk in plaintext. The CA bundle is loaded
from memory (``cadata``). The mTLS client certificate and key are handed to
OpenSSL through an anonymous in-memory file (``memfd_create``) that is never
linked into a directory and vanishes with the process, even if the worker is
killed mid-request. Where memfd is unavailable (not Linux), a 0600 file in a
private 0700 directory is used and always removed in ``finally``;
``sweep_leftovers()`` removes what a killed process left behind.
"""
from __future__ import annotations

import glob
import os
import shutil
import ssl
import tempfile
import time
from typing import Iterable, Optional
from urllib.parse import urlsplit

from ..errors import (BLOCKED_DESTINATION, CERT_NAME_MISMATCH, DESTINATION_CHANGED, SPKI_MISMATCH, ConnectError,
                      TOO_LARGE, TRANSPORT)
from ..http import DEFAULT_MAX_BYTES, DEFAULT_TIMEOUT, Response

DEFAULT_PORT = 443
TMP_PREFIX = 'a8c-'


def available() -> bool:
    try:
        import requests  # noqa: F401
        from core import safe_http  # noqa: F401
        return True
    except Exception:
        return False


def ports_for(*urls: str) -> frozenset:
    """{443} plus the explicit port of each URL (if any)."""
    out = {DEFAULT_PORT}
    for u in urls:
        try:
            port = urlsplit(u or '').port
        except ValueError:
            port = None
        if port:
            out.add(int(port))
    return frozenset(out)


def _private_dir_root() -> str:
    try:
        from django.conf import settings
        root = getattr(settings, 'AGIT8OR_CONNECT_RUNTIME_DIR', '') or ''
    except Exception:
        root = ''
    return root or tempfile.gettempdir()


def sweep_leftovers(max_age_seconds: int = 300) -> int:
    """Remove TLS material a killed process left behind (fallback files and
    the per-request files older releases wrote to the temp dir). Only entries
    owned by this user and older than ``max_age_seconds``."""
    n = 0
    now = time.time()
    uid = os.getuid() if hasattr(os, 'getuid') else None
    roots = {_private_dir_root(), tempfile.gettempdir()}
    for root in roots:
        for path in glob.glob(os.path.join(root, TMP_PREFIX + '*')):
            try:
                st = os.lstat(path)
                if (uid is not None and st.st_uid != uid) or now - st.st_mtime < max_age_seconds:
                    continue
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif path.endswith('.pem'):
                    os.unlink(path)
                else:
                    continue
                n += 1
            except OSError:
                continue
    return n


class _SecretFiles:
    """Paths OpenSSL can read for PEM text, without plaintext on disk when
    the platform allows it. Use as a context manager; everything is closed
    or removed on exit."""

    def __init__(self):
        self._fds = []
        self._dir = None

    def __enter__(self):
        return self

    def path_for(self, content: str) -> str:
        data = content.encode('utf-8')
        if hasattr(os, 'memfd_create'):
            try:
                fd = os.memfd_create(TMP_PREFIX + 'pem', getattr(os, 'MFD_CLOEXEC', 0))
            except OSError:
                fd = None
            if fd is not None:
                self._fds.append(fd)
                os.write(fd, data)
                return f'/proc/self/fd/{fd}'
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix=TMP_PREFIX, dir=_private_dir_root())
            os.chmod(self._dir, 0o700)
        fd, path = tempfile.mkstemp(prefix='k-', suffix='.pem', dir=self._dir)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
        finally:
            os.close(fd)
        return path

    def __exit__(self, *exc):
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None
        return False


class SafeHttpTransport:
    def __init__(self, *, allow_private: bool = False, ca_pem: Optional[str] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = DEFAULT_TIMEOUT,
                 client_cert_pem: Optional[str] = None, client_key_pem: Optional[str] = None,
                 allowed_ports: Optional[Iterable[int]] = None, allow_loopback_http: bool = False,
                 pinned: Optional[Iterable] = None, spki_pins: Optional[Iterable[str]] = None, **_ignored):
        self.allow_private = allow_private
        self.ca_pem = ca_pem
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.client_cert_pem = client_cert_pem
        self.client_key_pem = client_key_pem
        self.allowed_ports = frozenset(int(p) for p in (allowed_ports or ())) | {DEFAULT_PORT}
        import ipaddress
        self.pinned = (frozenset(ipaddress.ip_network(str(n), strict=False) for n in pinned)
                       if pinned is not None else None)
        self.spki_pins = frozenset(str(p) for p in spki_pins) if spki_pins else None

    def _policy(self):
        # Built here, never from configured_service_policy(): the site-wide
        # private-IP opt-in must not widen what Connect may reach (QC-04).
        from core.safe_http import OutboundPolicy
        return OutboundPolicy(allow_lan=bool(self.allow_private), allow_local=False,
                              allowed_ports=self.allowed_ports, pinned=self.pinned, spki_pins=self.spki_pins)

    def ssl_context(self, files: _SecretFiles) -> ssl.SSLContext:
        """Verification against the system bundle, or ONLY the private CA;
        TLS 1.2+; hostname checked; optional client certificate."""
        if self.ca_pem:
            ctx = ssl.create_default_context(cadata=self.ca_pem)
        else:
            from requests.utils import DEFAULT_CA_BUNDLE_PATH
            ctx = ssl.create_default_context(cafile=DEFAULT_CA_BUNDLE_PATH)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        if self.client_cert_pem and self.client_key_pem:
            ctx.load_cert_chain(files.path_for(self.client_cert_pem), files.path_for(self.client_key_pem))
        return ctx

    def _session(self, ctx):
        import requests
        from core.safe_http import GuardedHTTPAdapter

        class _ContextAdapter(GuardedHTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs['ssl_context'] = ctx
                super().init_poolmanager(*args, **kwargs)

            def cert_verify(self, conn, url, verify, cert):
                # Trust comes only from ctx: requests must not add its own
                # CA bundle path (which would widen a private-CA-only set).
                conn.cert_reqs = 'CERT_REQUIRED'
                conn.ca_certs = None
                conn.ca_cert_dir = None

        s = requests.Session()
        s.trust_env = False
        adapter = _ContextAdapter(policy=self._policy(), max_retries=0)
        s.mount('https://', adapter)
        s.mount('http://', adapter)
        return s

    def request(self, method, url, headers=None, body=None) -> Response:
        import requests
        from core.safe_http import BlockedDestinationError, UnsafeURLError, validate_url
        if not url.startswith('https://'):
            raise ConnectError(BLOCKED_DESTINATION, 'only https is allowed', 400)
        policy = self._policy()
        try:
            validate_url(url, policy)
        except UnsafeURLError as e:
            raise ConnectError(BLOCKED_DESTINATION, 'destination not allowed for this connection (port 443 or '
                                                    'the port of its address only; enable private networks for '
                                                    'this connection to reach an internal address; loopback, '
                                                    'link-local and metadata addresses are always refused)',
                               400) from e
        try:
            with _SecretFiles() as files:
                try:
                    ctx = self.ssl_context(files)
                except (ssl.SSLError, ValueError) as e:
                    raise ConnectError(TRANSPORT, 'the private CA bundle or client certificate for this '
                                                  'connection could not be loaded', 502) from e
            # The memfd / private files are closed and removed here: OpenSSL
            # has copied the certificate and key into the context.
            with self._session(ctx) as s:
                r = s.request(method, url, headers=headers or {}, data=body, timeout=(5, self.timeout),
                              allow_redirects=False, stream=True, verify=True)
                data = b''
                for chunk in r.iter_content(65536):
                    data += chunk
                    if len(data) > self.max_bytes:
                        r.close()
                        raise ConnectError(TOO_LARGE, 'response too large', 502)
                return Response(r.status_code, dict(r.headers), data)
        except ConnectError:
            raise
        except BlockedDestinationError as e:
            from core.safe_http import DestinationChangedError, SpkiMismatchError
            cause = e.__cause__
            if isinstance(cause, DestinationChangedError):
                err = ConnectError(DESTINATION_CHANGED, 'the destination resolves to an address outside the '
                                                        'approved set; nothing was sent', 502)
                err.evidence = {'addresses': list(cause.addresses)}
                raise err from e
            if isinstance(cause, SpkiMismatchError):
                err = ConnectError(SPKI_MISMATCH, 'the certificate key does not match the pinned key', 502)
                err.evidence = {'spki': cause.digest}
                raise err from e
            raise ConnectError(BLOCKED_DESTINATION, 'destination not allowed for this connection', 502) from e
        except requests.exceptions.SSLError as e:
            text = str(e).lower()
            if 'mismatch' in text or "doesn't match" in text or 'not valid for' in text:
                raise ConnectError(CERT_NAME_MISMATCH, 'the certificate does not name this host or IP address',
                                   502) from e
            raise ConnectError(TRANSPORT, 'TLS verification failed (check the certificate or the private CA '
                                          'bundle for this connection)', 502) from e
        except requests.RequestException as e:
            raise ConnectError(TRANSPORT, f'could not be reached ({e.__class__.__name__})', 502) from e
