"""Transport backed by Clientst0r's core.safe_http (requests + the
connect-time SSRF guard: DNS resolved once, every address checked, the
socket opened to the validated IP, peer re-checked).

Used automatically by `agit8or_connect.http.default_transport()` when
core.safe_http is importable. TLS is always verified (system CAs, or ONLY the
connection's private CA bundle when one is configured), minimum TLS 1.2,
redirects never followed, proxies ignored, body capped.
"""
from __future__ import annotations

import os
import ssl
import tempfile
from typing import Optional

from ..errors import BLOCKED_DESTINATION, ConnectError, TOO_LARGE, TRANSPORT
from ..http import DEFAULT_MAX_BYTES, DEFAULT_TIMEOUT, Response


def available() -> bool:
    try:
        import requests  # noqa: F401
        from core import safe_http  # noqa: F401
        return True
    except Exception:
        return False


class SafeHttpTransport:
    def __init__(self, *, allow_private: bool = False, ca_pem: Optional[str] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = DEFAULT_TIMEOUT,
                 client_cert_pem: Optional[str] = None, client_key_pem: Optional[str] = None,
                 allow_loopback_http: bool = False, **_ignored):
        self.allow_private = allow_private
        self.ca_pem = ca_pem
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.client_cert_pem = client_cert_pem
        self.client_key_pem = client_key_pem

    def _policy(self):
        from core.safe_http import OutboundPolicy, configured_service_policy
        base = configured_service_policy()
        if self.allow_private:
            return OutboundPolicy(allow_lan=True, allow_local=base.allow_local, allowed_ports=None)
        return base

    def _session(self):
        import requests
        from core.safe_http import GuardedHTTPAdapter

        class _TLS12Adapter(GuardedHTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs['ssl_minimum_version'] = ssl.TLSVersion.TLSv1_2
                super().init_poolmanager(*args, **kwargs)

        s = requests.Session()
        s.trust_env = False
        adapter = _TLS12Adapter(policy=self._policy(), max_retries=0)
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
            raise ConnectError(BLOCKED_DESTINATION, 'destination not allowed for this connection (enable private '
                                                    'networks for this connection to reach an internal address)',
                               400) from e
        tmp = []
        try:
            verify = True
            if self.ca_pem:
                verify = self._tmp(self.ca_pem, tmp)
            cert = None
            if self.client_cert_pem and self.client_key_pem:
                cert = (self._tmp(self.client_cert_pem, tmp), self._tmp(self.client_key_pem, tmp))
            with self._session() as s:
                r = s.request(method, url, headers=headers or {}, data=body, timeout=(5, self.timeout),
                              allow_redirects=False, stream=True, verify=verify, cert=cert)
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
            raise ConnectError(BLOCKED_DESTINATION, 'destination not allowed for this connection', 502) from e
        except requests.exceptions.SSLError as e:
            raise ConnectError(TRANSPORT, 'TLS verification failed (check the certificate or the private CA '
                                          'bundle for this connection)', 502) from e
        except requests.RequestException as e:
            raise ConnectError(TRANSPORT, f'could not be reached ({e.__class__.__name__})', 502) from e
        finally:
            for path in tmp:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    @staticmethod
    def _tmp(content: str, bucket: list) -> str:
        fd, path = tempfile.mkstemp(prefix='a8c-', suffix='.pem')
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.chmod(path, 0o600)
        bucket.append(path)
        return path
