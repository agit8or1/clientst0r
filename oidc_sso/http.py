"""Outbound requests to the OP, through core.safe_http's guard.

Every URL (issuer, discovery document endpoints, JWKS, token, userinfo) is
checked twice: as text (core.safe_http.validate_url) and at socket-open time
by the guarded adapter, so DNS rebinding cannot reach an internal address.

Policy:
  * default — public addresses only, unless the install-wide
    ALLOW_PRIVATE_IP_INTEGRATIONS opt-in is on (configured_service_policy);
  * provider.allow_private_network — the explicit per-provider admin opt-in:
    RFC 1918 / CGNAT / ULA addresses as for LAN controllers
    (lan_controller_policy); loopback / link-local still need the global
    opt-in. Cloud metadata endpoints are refused under every policy.
"""
import hashlib
import json
import os
import tempfile
from urllib.parse import urlsplit

import requests

from core.safe_http import (
    UnsafeURLError, configured_service_policy, guard_session, lan_controller_policy, validate_url,
)

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
MAX_BYTES = 512 * 1024


class OPError(Exception):
    """The OP could not be used. The message is for admins / logs, never contains tokens."""


def policy_for(provider):
    return lan_controller_policy() if provider.allow_private_network else configured_service_policy()


def check_url(provider, url):
    """Validate one OP URL as text. Returns it or raises OPError."""
    try:
        url = validate_url(url, policy_for(provider))
    except UnsafeURLError as exc:
        raise OPError(f'URL refused by the outbound request guard: {exc}') from None
    scheme = urlsplit(url).scheme.lower()
    if scheme != 'https' and not provider.allow_private_network:
        raise OPError('The OP must use https:// (http:// only with "private network" on, for testing).')
    return url


def _ca_bundle_path(pem):
    """A file holding the provider's CA bundle (requests wants a path)."""
    digest = hashlib.sha256(pem.encode()).hexdigest()[:32]
    directory = os.path.join(tempfile.gettempdir(), 'clientst0r-oidc-ca')
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, f'{digest}.pem')
    if not os.path.exists(path):
        fd, tmp = tempfile.mkstemp(dir=directory)
        with os.fdopen(fd, 'w') as fh:
            fh.write(pem)
        os.replace(tmp, path)
    return path


def session_for(provider):
    """A guarded requests session for this provider. Patched in tests."""
    session = requests.Session()
    session.trust_env = False
    return guard_session(session, policy_for(provider))


def _verify(provider):
    pem = (provider.ca_bundle_pem or '').strip()
    return _ca_bundle_path(pem + '\n') if pem else True


def _read_json(response):
    declared = response.headers.get('Content-Length')
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise OPError('Response from the OP is too large')
    body = b''
    for chunk in response.iter_content(chunk_size=16384):
        body += chunk
        if len(body) > MAX_BYTES:
            raise OPError('Response from the OP is too large')
    try:
        return json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise OPError('The OP did not return JSON') from None


def request_json(provider, method, url, *, data=None, headers=None, auth=None, ok_statuses=(200,)):
    """One request to the OP; returns (status, json). Redirects are not followed."""
    url = check_url(provider, url)
    session = session_for(provider)
    try:
        response = session.request(
            method, url, data=data, headers=dict({'Accept': 'application/json'}, **(headers or {})),
            auth=auth, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=False,
            stream=True, verify=_verify(provider),
        )
    except UnsafeURLError as exc:
        raise OPError(f'Connection refused by the outbound request guard: {exc}') from None
    except requests.RequestException as exc:
        raise OPError(f'Could not reach the OP ({type(exc).__name__})') from None
    with response:
        status = response.status_code
        try:
            payload = _read_json(response)
        except OPError:
            if status not in ok_statuses:
                raise OPError(f'The OP answered HTTP {status}') from None
            raise
    if status not in ok_statuses:
        error = payload.get('error') if isinstance(payload, dict) else None
        raise OPError(f'The OP answered HTTP {status}' + (f' ({str(error)[:80]})' if error else ''))
    return status, payload
