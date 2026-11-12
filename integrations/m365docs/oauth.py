"""Delegated sign-in for documents: authorization code + PKCE (S256).

    start(request, connection, next_url='') -> authorize URL
    finish(request) -> (M365DocsGrant, next_url)       raises OAuthError
    access_token(grant) -> str                          refreshes when needed
    disconnect(grant, *, request=None)

* ``state`` is 256 random bits, kept server-side in the user's Django
  session together with the PKCE verifier, the connection, the user and the
  scopes; it is single use and expires after STATE_TTL seconds. The callback
  is a GET from Microsoft, so Django's CSRF token cannot ride along: the
  state check is the CSRF protection (as for the existing Azure SSO).
* The connection's own app registration is used (client id + secret). The
  authority is the connection's tenant, so only that tenant's accounts (and
  its guests) can sign in.
* Tokens are stored per (connection, user) in M365DocsGrant, encrypted.
  Microsoft rotates refresh tokens; the newest one always replaces the old.
* Disconnect deletes both tokens. Microsoft's identity platform documents no
  endpoint that revokes one application's refresh token on request, so the
  page tells the user how to remove the app's consent at Microsoft too.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from office.logging_filters import get_logger

from . import http, scopes

logger = get_logger('office.m365')

SESSION_KEY = 'm365docs_oauth'
STATE_TTL = 600
MAX_PENDING = 5
AUTHORIZE_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
_TENANT_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')


class OAuthError(Exception):
    def __init__(self, message, code=''):
        super().__init__(message)
        self.code = code


class NotConnected(OAuthError):
    """The user has no usable sign-in for this connection."""


def _tenant(connection):
    tenant = (connection.tenant_id or '').strip()
    if not _TENANT_RE.match(tenant):
        raise OAuthError('The connection\'s tenant ID is not valid.', 'tenant')
    return tenant


def redirect_uri(request):
    configured = getattr(settings, 'M365_DOCS_REDIRECT_URI', '')
    if configured:
        return configured
    uri = request.build_absolute_uri(reverse('integrations:m365docs_callback'))
    if uri.startswith('http://') and not settings.DEBUG:
        uri = 'https://' + uri[len('http://'):]
    return uri


def pkce_pair():
    verifier = secrets.token_urlsafe(64)            # 86 chars, within 43..128
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
    return verifier, challenge


def _credentials(connection):
    creds = connection.get_credentials() or {}
    client_id, secret = creds.get('client_id', ''), creds.get('client_secret', '')
    if not client_id or not secret:
        raise OAuthError('The connection has no client ID / secret.', 'credentials')
    return client_id, secret


def start(request, connection, next_url=''):
    if not connection.docs_enabled or not connection.is_active:
        raise OAuthError('Documents are not enabled for this connection.', 'disabled')
    tenant = _tenant(connection)
    client_id, _secret = _credentials(connection)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    now = time.time()
    pending = {k: v for k, v in (request.session.get(SESSION_KEY) or {}).items()
               if isinstance(v, dict) and now - v.get('t', 0) < STATE_TTL}
    while len(pending) >= MAX_PENDING:
        pending.pop(min(pending, key=lambda k: pending[k].get('t', 0)))
    scope = scopes.request_scopes(connection)
    pending[state] = {'c': connection.pk, 'u': request.user.pk, 'v': verifier,
                      's': scope, 't': now, 'n': next_url or '',
                      'r': redirect_uri(request)}
    request.session[SESSION_KEY] = pending
    request.session.modified = True
    query = urlencode({
        'client_id': client_id, 'response_type': 'code', 'response_mode': 'query',
        'redirect_uri': pending[state]['r'], 'scope': scope, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    })
    return AUTHORIZE_URL.format(tenant=tenant) + '?' + query


def _pop_state(request, state):
    pending = request.session.get(SESSION_KEY) or {}
    entry = pending.pop(state, None) if isinstance(state, str) and state else None
    request.session[SESSION_KEY] = pending
    request.session.modified = True
    return entry


def _token_call(connection, form):
    tenant = _tenant(connection)
    client_id, secret = _credentials(connection)
    body = urlencode({'client_id': client_id, 'client_secret': secret, **form})
    try:
        res = http.send('POST', TOKEN_URL.format(tenant=tenant),
                        allowed_hosts={http.LOGIN_HOST}, data=body.encode('ascii'),
                        headers={'Content-Type': 'application/x-www-form-urlencoded',
                                 'Accept': 'application/json'},
                        max_bytes=256 * 1024, timeout=30)
    except Exception as e:  # network / TLS / refused address
        raise OAuthError(f'Could not reach Microsoft sign-in: {e.__class__.__name__}', 'network')
    try:
        payload = json.loads(res.content or b'{}')
    except ValueError:
        payload = {}
    if res.status_code != 200 or 'access_token' not in payload:
        code = str(payload.get('error') or res.status_code)
        desc = str(payload.get('error_description') or '').split('\r\n')[0][:300]
        raise OAuthError(f'Microsoft refused the token request ({code}). {desc}'.strip(), code)
    return payload


def _store(grant, payload):
    grant.access_token = payload['access_token']
    grant.access_expires_at = timezone.now() + timedelta(
        seconds=max(int(payload.get('expires_in') or 0) - 60, 0))
    if payload.get('refresh_token'):
        grant.refresh_token = payload['refresh_token']
    if payload.get('scope'):
        grant.scopes = ' '.join(sorted(scopes.normalise(payload['scope'])))
    grant.refreshed_at = timezone.now()


def finish(request):
    """Handle Microsoft's redirect back. Returns (grant, next_url)."""
    from integrations.models import M365Connection, M365DocsGrant
    entry = _pop_state(request, request.GET.get('state'))
    if entry is None:
        raise OAuthError('The sign-in request was not recognised or was already used. '
                         'Start again from the connection page.', 'state')
    if entry.get('u') != request.user.pk:
        raise OAuthError('The sign-in was started by a different user.', 'state')
    if time.time() - entry.get('t', 0) > STATE_TTL:
        raise OAuthError('The sign-in request expired. Start again.', 'state')
    if request.GET.get('error'):
        code = request.GET.get('error', '')[:100]
        desc = (request.GET.get('error_description') or '').split('\r\n')[0][:300]
        raise OAuthError(f'Microsoft did not grant access ({code}). {desc}'.strip(), code)
    code = request.GET.get('code')
    if not code:
        raise OAuthError('Microsoft returned no authorization code.', 'code')
    connection = M365Connection.objects.filter(pk=entry['c'], is_active=True,
                                               docs_enabled=True).first()
    if connection is None:
        raise OAuthError('Documents are no longer enabled for this connection.', 'disabled')
    payload = _token_call(connection, {
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': entry['r'],
        'code_verifier': entry['v'], 'scope': entry['s'],
    })
    if not payload.get('refresh_token'):
        raise OAuthError('Microsoft returned no refresh token (offline_access was not granted).',
                         'offline_access')
    grant, _ = M365DocsGrant.objects.get_or_create(connection=connection, user=request.user)
    _store(grant, payload)
    if not payload.get('scope'):
        grant.scopes = ' '.join(s for s in scopes.for_connection(connection))
    grant.save()
    return grant, entry.get('n') or ''


def refresh(grant):
    if not grant.refresh_token:
        grant.delete()
        raise NotConnected('Sign in to Microsoft 365 again.', 'no_refresh_token')
    try:
        payload = _token_call(grant.connection, {
            'grant_type': 'refresh_token', 'refresh_token': grant.refresh_token,
            'scope': scopes.request_scopes(grant.connection),
        })
    except OAuthError as e:
        if e.code in ('invalid_grant', 'interaction_required', 'consent_required'):
            logger.info('M365 documents sign-in for user %s on connection %s ended (%s)',
                        grant.user_id, grant.connection_id, e.code)
            grant.delete()
            raise NotConnected('Your Microsoft 365 sign-in has expired or was revoked. '
                               'Connect again.', e.code)
        raise
    _store(grant, payload)
    grant.save()
    return grant


def access_token(grant) -> str:
    if grant.access_token and grant.access_expires_at and grant.access_expires_at > timezone.now():
        return grant.access_token
    return refresh(grant).access_token


def disconnect(grant, *, request=None, user=None):
    from . import audit
    connection = grant.connection
    who = user or grant.user
    grant.delete()
    audit.log('m365_disconnect', user=who, organization_id=connection.organization_id,
              request=request, object_type='integrations.m365connection',
              object_id=connection.pk, object_repr=connection.name,
              description=f'Disconnected Microsoft 365 documents for {who.username} '
                          f'on {connection.name}; stored tokens deleted')


def app_token(connection) -> str:
    """The connection's existing client-credentials token (scope ``.default``,
    the same request the tenant-read features make). Used only to look up a
    SharePoint site by URL for the allowed-locations picker, which needs the
    tenant-read app's existing Sites.Read.All application permission."""
    payload = _token_call(connection, {'grant_type': 'client_credentials',
                                       'scope': scopes.TENANT_READ_SCOPE})
    return payload['access_token']
