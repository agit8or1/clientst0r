"""clientst0r -> ONLYOFFICE Docs calls (healthcheck, command service,
conversion service, downloads). Everything goes through office.net.fetch.

Endpoints (Docs 10.0):

    GET  <server>/healthcheck            -> body ``true`` when ready
    POST <server>/command                -> {"error": 0, ...}
         c = version | license | info | forcesave | drop | ...
    POST <server>/converter              -> {"endConvert", "fileUrl", "fileType", "percent"}
                                            or {"error": <negative code>}

``<server>`` is the instance's internal URL when set, else its browser URL.
"""
from __future__ import annotations

import json
import secrets
import time

from office import net
from office.logging_filters import get_logger

from . import signing

log = get_logger('office.onlyoffice')

JSON_LIMIT = 1024 * 1024
DEFAULT_SECRET = 'developer-only-not-a-real-secret'

# Command service error codes [OO-CMD].
COMMAND_ERRORS = {
    0: 'no errors',
    1: 'document key is missing or no document with such key could be found',
    2: 'callback url not correct',
    3: 'internal server error',
    4: 'no changes were applied to the document before the forcesave command was received',
    5: 'command not correct',
    6: 'invalid token',
}

# Conversion service error codes, as listed on the conversion API response
# page (negative numbers).
CONVERT_ERRORS = {
    -1: 'unknown error',
    -2: 'conversion timeout error',
    -3: 'conversion error',
    -4: 'error while downloading the document file to be converted',
    -5: 'incorrect password',
    -6: 'error while accessing the conversion result database',
    -7: 'input error',
    -8: 'invalid token',
    -9: 'the converter cannot automatically determine the output file format',
    -10: 'size limit exceeded',
}


class DocsError(Exception):
    """A call to the Document Server failed. ``code`` is the service's error
    code when it answered with one."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def base_url(instance) -> str:
    return (instance.server_url() or '').rstrip('/')


def browser_base(instance) -> str:
    return (instance.browser_url or '').rstrip('/')


def healthcheck(instance, *, url=None) -> net.FetchResult:
    return net.fetch((url or base_url(instance)) + '/healthcheck', instance, 4096)


def _post_json(instance, path, params, operation, *, secret=None, timeout=None):
    headers, body = signing.inbox_request(params, secret or instance.shared_secret, operation)
    result = net.fetch(base_url(instance) + path, instance, JSON_LIMIT, method='POST',
                       headers=headers, data=json.dumps(body).encode(), timeout=timeout)
    if result.status_code != 200:
        raise DocsError(f'{path} answered HTTP {result.status_code}')
    try:
        data = json.loads(result.content.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise DocsError(f'{path} did not answer with JSON')
    if not isinstance(data, dict):
        raise DocsError(f'{path} answered with an unexpected document')
    return data


def command(instance, c, *, secret=None, **params) -> dict:
    """Run a command-service command. Returns the JSON answer when ``error``
    is 0; raises DocsError(code=...) otherwise."""
    data = _post_json(instance, '/command', {'c': c, **params}, 'command', secret=secret)
    code = data.get('error', 0)
    if code not in (0, '0'):
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None
        raise DocsError(f'command {c}: {COMMAND_ERRORS.get(code, f"error {code}")}', code=code)
    return data


def new_conversion_key(prefix='cv') -> str:
    # [0-9a-zA-Z.=_-], at most 128 characters.
    return f'{prefix}-{secrets.token_urlsafe(18)}'


def convert(instance, *, url, filetype, outputtype, title, key=None, timeout=None) -> dict:
    """Synchronous conversion request; repeats the request (same key) while
    the server reports the conversion is still running, up to `timeout`.
    Returns the final answer (with ``fileUrl``). Raises DocsError."""
    key = key or new_conversion_key()
    timeout = float(timeout or instance.conversion_timeout_s or 120)
    deadline = time.monotonic() + timeout
    params = {'async': False, 'filetype': filetype, 'outputtype': outputtype,
              'key': key, 'title': title[:128], 'url': url}
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DocsError('The conversion did not finish in time.', code=-2)
        data = _post_json(instance, '/converter', params, 'converter',
                          timeout=max(1.0, remaining))
        if data.get('error') not in (None, 0, '0'):
            try:
                code = int(data.get('error'))
            except (TypeError, ValueError):
                code = None
            raise DocsError(f'conversion: {CONVERT_ERRORS.get(code, f"error {code}")}', code=code)
        if data.get('endConvert') in (True, 'true', 'True'):
            if not data.get('fileUrl'):
                raise DocsError('conversion finished without a result URL')
            return data
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def download(instance, url, max_bytes) -> bytes:
    """Fetch a file the Document Server offers (callback ``url``, conversion
    ``fileUrl``). Only from the instance's own origins (net.check_url)."""
    result = net.fetch(url, instance, max_bytes)
    if result.status_code != 200:
        raise net.OfficeFetchError(f'Download answered HTTP {result.status_code}')
    return result.content


def version_tuple(text):
    parts = []
    for piece in str(text or '').replace('-', '.').split('.'):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)
