"""Authorization code flow with PKCE (S256), state and nonce.

The per-flow secrets (state, nonce, code_verifier) live only in the
server-side Django session, keyed by state, and are popped on first use: a
state can be redeemed once, and only in the browser session that started
it. Pending flows expire after PENDING_TTL seconds; at most MAX_PENDING are
kept per session.
"""
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

from django.urls import reverse

from . import discovery, keys
from .http import OPError, request_json
from .models import OIDCProvider

SESSION_PENDING = 'oidc_sso_pending'
PENDING_TTL = 600
MAX_PENDING = 5

MODE_LOGIN, MODE_LINK, MODE_STEPUP = 'login', 'link', 'stepup'


def pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()
    return verifier, challenge


def redirect_uri(request, provider):
    return request.build_absolute_uri(reverse('oidc_sso:callback', args=[provider.slug]))


def start(request, provider, mode, next_url='', *, prompt=None, max_age=None, acr_values=''):
    """Store a pending flow and return the authorization URL."""
    meta = discovery.get_metadata(provider)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    uri = redirect_uri(request, provider)

    now = time.time()
    pending = {k: v for k, v in (request.session.get(SESSION_PENDING) or {}).items()
               if isinstance(v, dict) and now - v.get('created', 0) < PENDING_TTL}
    while len(pending) >= MAX_PENDING:
        pending.pop(min(pending, key=lambda k: pending[k].get('created', 0)))
    pending[state] = {
        'provider': provider.pk, 'mode': mode, 'nonce': nonce, 'verifier': verifier,
        'redirect_uri': uri, 'next': next_url or '', 'created': now, 'max_age': max_age,
        'user_id': request.user.pk if request.user.is_authenticated else None,
    }
    request.session[SESSION_PENDING] = pending

    params = {
        'response_type': 'code', 'client_id': provider.client_id, 'redirect_uri': uri,
        'scope': ' '.join(provider.scope_list()), 'state': state, 'nonce': nonce,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    }
    if prompt:
        params['prompt'] = prompt
    if max_age is not None:
        params['max_age'] = str(int(max_age))
    if acr_values:
        params['acr_values'] = acr_values
    sep = '&' if '?' in meta['authorization_endpoint'] else '?'
    return meta['authorization_endpoint'] + sep + urlencode(params)


def pop_pending(request, state):
    """The pending flow for `state` (removed), or None."""
    if not isinstance(state, str) or not state or len(state) > 200:
        return None
    pending = request.session.get(SESSION_PENDING) or {}
    flow = pending.pop(state, None)
    request.session[SESSION_PENDING] = pending
    if not isinstance(flow, dict) or time.time() - flow.get('created', 0) >= PENDING_TTL:
        return None
    return flow


def exchange_code(provider, code, flow):
    """Token endpoint call. Returns the token response dict."""
    meta = discovery.get_metadata(provider)
    data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': flow['redirect_uri'],
            'code_verifier': flow['verifier']}
    auth = None
    if provider.client_auth_method == OIDCProvider.AUTH_PRIVATE_KEY_JWT:
        try:
            assertion = keys.client_assertion(provider, meta['token_endpoint'])
        except ValueError as exc:
            raise OPError(str(exc)) from None
        data.update({'client_id': provider.client_id,
                     'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                     'client_assertion': assertion})
    else:
        from urllib.parse import quote
        # RFC 6749 §2.3.1: form-urlencode both parts before Basic auth.
        auth = (quote(provider.client_id, safe=''), quote(provider.client_secret or '', safe=''))
    _status, payload = request_json(provider, 'POST', meta['token_endpoint'], data=data, auth=auth,
                                    headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if not isinstance(payload, dict) or not isinstance(payload.get('id_token'), str):
        raise OPError('Token response has no id_token')
    token_type = payload.get('token_type')
    if token_type is not None and str(token_type).lower() != 'bearer':
        raise OPError('Unexpected token_type')
    return payload


def fetch_userinfo(provider, access_token):
    meta = discovery.get_metadata(provider)
    url = meta.get('userinfo_endpoint')
    if not url or not access_token:
        return None
    _status, payload = request_json(provider, 'GET', url,
                                    headers={'Authorization': f'Bearer {access_token}'})
    return payload if isinstance(payload, dict) else None


def end_session_url(provider, id_token, post_logout_redirect_uri):
    meta = discovery.cached_metadata(provider)
    if meta is None:
        try:
            meta = discovery.get_metadata(provider)
        except OPError:
            return None
    endpoint = meta.get('end_session_endpoint')
    if not endpoint:
        return None
    params = {'client_id': provider.client_id, 'post_logout_redirect_uri': post_logout_redirect_uri}
    if id_token:
        params['id_token_hint'] = id_token
    sep = '&' if '?' in endpoint else '?'
    return endpoint + sep + urlencode(params)
