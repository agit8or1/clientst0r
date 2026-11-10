"""HTTP access to the source system.

``RequestsTransport`` is the only code in the rehearsal that touches the
network. Tests replace it with a recorded-fixture transport.

* API calls go to the configured source URL with the API key, through a
  session guarded by ``core.safe_http`` (no metadata endpoints, private ranges
  only on the operator opt-in).
* File downloads are size-capped while streaming. The API key is sent only
  when the download URL is on the API's own host; anything else (e.g. a
  pre-signed storage URL) is fetched without credentials under the public-web
  policy.
"""
from __future__ import annotations

import time
from urllib.parse import urljoin, urlparse

import requests


class SourceUnavailable(Exception):
    """An endpoint could not be read. ``kind``: permission / api_gap / error."""

    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind = kind
        self.status = status


class DownloadRejected(Exception):
    """A file was not downloaded (too large, wrong type, unsafe URL)."""


def classify_status(status):
    if status in (401, 403):
        return 'permission'
    if status in (404, 405, 501):
        return 'api_gap'
    return 'error'


class RequestsTransport:
    timeout = 30

    def __init__(self, base_url, headers):
        from core.safe_http import configured_service_policy, guard_session
        self.base_url = base_url.rstrip('/')
        self.base_host = (urlparse(self.base_url).hostname or '').lower()
        self.headers = dict(headers)
        self.session = guard_session(requests.Session(), configured_service_policy())

    def get_json(self, path, params=None):
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params or {}, headers=self.headers,
                                    timeout=self.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise SourceUnavailable('error', f'request failed: {type(exc).__name__}') from exc
        if resp.status_code >= 400:
            raise SourceUnavailable(classify_status(resp.status_code),
                                    f'HTTP {resp.status_code}', status=resp.status_code)
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceUnavailable('error', 'response was not JSON') from exc

    def get_bytes(self, url, max_bytes):
        """Return (content, content_type) or raise DownloadRejected."""
        from core.safe_http import (PUBLIC_WEB, FetchError, UnsafeURLError,
                                    _read_capped, guard_session)
        absolute = urljoin(self.base_url + '/', url)
        host = (urlparse(absolute).hostname or '').lower()
        if urlparse(absolute).scheme not in ('http', 'https'):
            raise DownloadRejected('unsupported URL scheme')
        same_host = host == self.base_host
        if same_host:
            session, headers = self.session, {k: v for k, v in self.headers.items()
                                              if k.lower() != 'content-type'}
        else:
            session, headers = guard_session(requests.Session(), PUBLIC_WEB), {}
        try:
            resp = session.get(absolute, headers=headers, timeout=self.timeout,
                               allow_redirects=False, stream=True)
        except UnsafeURLError as exc:
            raise DownloadRejected('download URL not allowed') from exc
        except requests.RequestException as exc:
            raise DownloadRejected(f'download failed: {type(exc).__name__}') from exc
        with resp:
            if resp.status_code >= 400:
                raise DownloadRejected(f'download returned HTTP {resp.status_code}')
            if resp.status_code != 200:
                raise DownloadRejected(f'unexpected download status {resp.status_code}')
            try:
                body = _read_capped(resp, max_bytes, time.monotonic() + 120)
            except FetchError as exc:
                raise DownloadRejected('file exceeds the size limit') from exc
            ctype = resp.headers.get('Content-Type', '').split(';')[0].strip().lower()
        return body, ctype
