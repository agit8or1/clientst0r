"""
Azure AD / Microsoft Entra ID sign-in (OpenID Connect, authorization code flow).

How a Microsoft sign-in becomes a Clientst0r session (v3.17.688):

1. ``AzureOAuthClient.initiate_flow`` starts MSAL's auth code flow, which adds
   PKCE (S256), a nonce and the state; the flow is kept in the session.
2. ``AzureOAuthClient.complete_flow`` exchanges the code through MSAL (which
   checks the state and the PKCE verifier).
3. ``verify_id_token`` checks the ID token itself: RS256 signature against
   Microsoft's published keys, audience = our client id, expiry, the nonce of
   this flow, and an issuer of an accepted tenant (``allowed_tenants``).
4. ``resolve_sso_user`` finds the account linked to that token's
   (tenant id, object id). Nothing else identifies the user. In particular an
   e-mail address — from the token or from Microsoft Graph — never selects an
   account: before v3.17.688 it did, so whoever controlled that address in
   Entra signed in as the local account, superusers included.

Linking an existing account to a Microsoft identity happens only when its
owner, signed in locally, re-authenticates and links it (``link_identity``
via ``oauth_views.azure_link_start``), or when an administrator confirms a
recorded ``AzureADLinkRequest``. A superuser whose link predates v3.17.688
(an automatic e-mail link, ``azure_ad_linked_at`` empty) must link again once.
"""
import hashlib
import hmac
import logging
import re
import threading
from dataclasses import dataclass

import jwt
import msal
import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.utils import timezone

from django.db.models import Q

from accounts.models import AzureADLinkRequest, UserProfile
from audit.models import AuditLog
from core.models import SystemSetting

logger = logging.getLogger('accounts')
User = get_user_model()

AUTHORITY_HOST = 'https://login.microsoftonline.com'
# MSAL adds openid/profile/offline_access itself. 'email' makes the ID token
# carry the mailbox address, which often differs from the sign-in name (UPN).
SCOPES = ['User.Read', 'email']
GUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
TENANT_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9.-]{0,252}$')
MULTI_TENANT_AUTHORITIES = {'common', 'organizations', 'consumers'}
ID_TOKEN_LEEWAY_SECONDS = 120
MAX_PENDING_LINK_REQUESTS = 10

# Messages shown on the sign-in page. They say what to do, never which
# account an address belongs to beyond "an account uses it".
MESSAGES = {
    'link_required': (
        'An account here already uses this e-mail address, but it is not linked to '
        'this Microsoft account. Sign in with your password, then link Microsoft '
        'sign-in from My Profile, or ask an administrator to confirm the link.'),
    'superuser_link_required': (
        'This administrator account must be linked to Microsoft sign-in again. '
        'Sign in with your password, then link Microsoft sign-in from My Profile.'),
    'tenant_mismatch': 'This Microsoft account is not the one linked to your account here.',
    'tenant_not_allowed': 'Sign-in from this Microsoft organization is not allowed.',
    'no_account': ('No account here is linked to this Microsoft account. Ask an '
                   'administrator to give an account here your Microsoft e-mail address; '
                   'after your next Microsoft sign-in they can confirm the link.'),
    'inactive': 'This account is disabled.',
    'ambiguous': 'This Microsoft account is linked to more than one account here. Contact an administrator.',
    'invalid_token': 'Microsoft sign-in could not be verified. Please try again.',
    'not_configured': 'Azure AD authentication is not configured.',
}


class AzureIdentityError(Exception):
    def __init__(self, code, detail=''):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


# Only verify_id_token() makes AzureIdentity objects, so AzureADBackend
# can't be handed an unverified identity by accident.
_VERIFIED = object()


@dataclass(frozen=True)
class AzureIdentity:
    tid: str
    oid: str
    email: str
    name: str
    given_name: str
    family_name: str
    _token: object = None
    # Every address the token names (email, preferred_username, upn), lower-case,
    # primary first. Used only to find an account to *ask* about linking.
    addresses: tuple = ()

    def __post_init__(self):
        if self._token is not _VERIFIED:
            raise TypeError('AzureIdentity is created only by verify_id_token()')


# --- configuration ---------------------------------------------------------

def _parse_tenant_list(text):
    out = set()
    for part in re.split(r'[\s,;]+', (text or '').strip().lower()):
        if not part:
            continue
        if GUID_RE.match(part):
            out.add(part)
        else:
            logger.warning('Ignoring allowed Entra tenant that is not a GUID: %r', part[:80])
    return frozenset(out)


def load_azure_config():
    """Azure settings from SystemSetting, or None when SSO is off or incomplete."""
    try:
        settings = SystemSetting.get_settings()
        if not getattr(settings, 'azure_ad_enabled', False):
            return None
        config = {
            'enabled': True,
            'tenant_id': (getattr(settings, 'azure_ad_tenant_id', '') or '').strip().lower(),
            'client_id': (getattr(settings, 'azure_ad_client_id', '') or '').strip(),
            'client_secret': settings.get_azure_ad_client_secret_decrypted(),
            'redirect_uri': (getattr(settings, 'azure_ad_redirect_uri', '') or '').strip(),
            'auto_create': bool(getattr(settings, 'azure_ad_auto_create_users', False)),
            'sync_groups': getattr(settings, 'azure_ad_sync_groups', False),
            'allowed_tenants': _parse_tenant_list(getattr(settings, 'azure_ad_allowed_tenant_ids', '')),
        }
    except Exception as e:
        logger.error(f"Error getting Azure config: {e}")
        return None
    missing = [f for f in ('tenant_id', 'client_id', 'client_secret', 'redirect_uri') if not config.get(f)]
    if missing:
        logger.error(f"Incomplete Azure AD configuration. Missing fields: {', '.join(missing)}")
        return None
    if not TENANT_NAME_RE.match(config['tenant_id']):
        logger.error('Azure AD tenant ID is not a GUID or tenant domain name')
        return None
    return config


_domain_tenant_cache = {}
_domain_tenant_lock = threading.Lock()


def _tenant_guid_for_domain(domain):
    """The tenant GUID behind a tenant domain name (contoso.onmicrosoft.com),
    from that tenant's OpenID configuration issuer."""
    with _domain_tenant_lock:
        if domain in _domain_tenant_cache:
            return _domain_tenant_cache[domain]
    try:
        r = requests.get(f'{AUTHORITY_HOST}/{domain}/v2.0/.well-known/openid-configuration', timeout=10)
        r.raise_for_status()
        issuer = r.json().get('issuer', '')
    except Exception as e:
        logger.error(f'Could not resolve Entra tenant {domain!r}: {e}')
        return None
    m = re.match(r'^https://login\.microsoftonline\.com/([0-9a-f-]{36})/v2\.0$', issuer or '')
    guid = m.group(1) if m and GUID_RE.match(m.group(1)) else None
    if guid:
        with _domain_tenant_lock:
            _domain_tenant_cache[domain] = guid
    return guid


def allowed_tenants(config):
    """Tenant GUIDs whose ID tokens are accepted.

    The configured tenant (a GUID, or a tenant domain resolved to its GUID),
    plus the explicit allowlist. With a multi-tenant authority ("common",
    "organizations") only the allowlist: an empty allowlist then accepts no
    tenant at all, rather than every tenant in the world.
    """
    tenants = set(config.get('allowed_tenants') or ())
    configured = config.get('tenant_id', '')
    if configured in MULTI_TENANT_AUTHORITIES:
        pass
    elif GUID_RE.match(configured):
        tenants.add(configured)
    else:
        guid = _tenant_guid_for_domain(configured)
        if guid:
            tenants.add(guid)
    return frozenset(tenants)


# --- ID token verification -------------------------------------------------

_jwks_clients = {}
_jwks_lock = threading.Lock()


def _jwks_client(authority_tenant):
    url = f'{AUTHORITY_HOST}/{authority_tenant}/discovery/v2.0/keys'
    with _jwks_lock:
        client = _jwks_clients.get(url)
        if client is None:
            client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=10)
            _jwks_clients[url] = client
        return client


def nonce_claim(flow_nonce):
    """The nonce claim Microsoft returns for a flow: MSAL sends (and expects
    back) the SHA-256 hex of the nonce it keeps in the flow."""
    return hashlib.sha256(flow_nonce.encode('ascii')).hexdigest()


def verify_id_token(id_token, config, flow_nonce):
    """Verify a Microsoft v2.0 ID token and return the identity it names.

    ``flow_nonce`` is the ``nonce`` of the MSAL flow this sign-in started.
    MSAL checks the nonce and claims but deliberately not the signature, so
    all of it is checked here. Raises AzureIdentityError.
    """
    if not id_token or not isinstance(id_token, str):
        raise AzureIdentityError('invalid_token', 'no id_token in the token response')
    if not flow_nonce or not isinstance(flow_nonce, str):
        raise AzureIdentityError('invalid_token', 'no nonce in the auth flow')
    tenants = allowed_tenants(config)
    if not tenants:
        raise AzureIdentityError('tenant_not_allowed', 'no tenant is accepted by this configuration')
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get('alg') != 'RS256':
            raise AzureIdentityError('invalid_token', f'unexpected alg {header.get("alg")!r}')
        key = _jwks_client(config['tenant_id']).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token, key, algorithms=['RS256'], audience=config['client_id'],
            leeway=ID_TOKEN_LEEWAY_SECONDS,
            options={'require': ['exp', 'iat', 'aud', 'iss', 'tid', 'oid', 'nonce']},
        )
    except AzureIdentityError:
        raise
    except Exception as e:
        raise AzureIdentityError('invalid_token', f'ID token rejected: {e}')

    tid = str(claims.get('tid', '')).lower()
    oid = str(claims.get('oid', '')).lower()
    if not GUID_RE.match(tid) or not GUID_RE.match(oid):
        raise AzureIdentityError('invalid_token', 'tid/oid are not GUIDs')
    if claims.get('iss') != f'{AUTHORITY_HOST}/{tid}/v2.0':
        raise AzureIdentityError('invalid_token', 'issuer does not match the tenant')
    if tid not in tenants:
        raise AzureIdentityError('tenant_not_allowed', f'tenant {tid} is not accepted')
    if not hmac.compare_digest(str(claims.get('nonce', '')), nonce_claim(flow_nonce)):
        raise AzureIdentityError('invalid_token', 'nonce mismatch')

    def _s(name, limit):
        v = claims.get(name)
        return v.strip()[:limit] if isinstance(v, str) else ''

    addresses = []
    for claim in ('email', 'preferred_username', 'upn'):
        v = _s(claim, 254).lower()
        if v and '@' in v and v not in addresses:
            addresses.append(v)
    return AzureIdentity(
        tid=tid, oid=oid,
        email=addresses[0] if addresses else '',
        addresses=tuple(addresses),
        name=_s('name', 255),
        given_name=_s('given_name', 150),
        family_name=_s('family_name', 150),
        _token=_VERIFIED,
    )


# --- matching an identity to an account ------------------------------------

def _ip(request):
    return request.META.get('REMOTE_ADDR') if request is not None else None


def _security_event(event, description, user=None, identity=None, request=None, **extra):
    data = {'event': event, 'auth_source': 'azure_ad'}
    if identity is not None:
        data.update({'tid': identity.tid, 'oid': identity.oid})
    data.update(extra)
    try:
        AuditLog.log(user=user, action='login_failed', success=False, description=description,
                     ip_address=_ip(request), extra_data=data)
    except Exception:
        logger.exception('Could not write Azure AD audit entry')
    logger.warning('Azure AD sign-in refused (%s): %s', event, description)


def _record_link_request(user, identity, request):
    with transaction.atomic():
        req, created = AzureADLinkRequest.objects.get_or_create(
            user=user, tenant_id=identity.tid, object_id=identity.oid, status='pending',
            defaults={'claimed_email': identity.email[:320], 'claimed_name': identity.name[:255],
                      'ip_address': _ip(request)})
        stale = list(AzureADLinkRequest.objects.filter(user=user, status='pending')
                     .order_by('-created_at').values_list('pk', flat=True)[MAX_PENDING_LINK_REQUESTS:])
        if stale:
            AzureADLinkRequest.objects.filter(pk__in=stale).delete()
    return req


def resolve_sso_user(identity, config, request=None):
    """Return (user, None) for the account linked to this verified identity,
    or (None, error_code). See MESSAGES for the codes."""
    if not isinstance(identity, AzureIdentity):
        return None, 'invalid_token'

    profiles = list(UserProfile.objects.select_related('user')
                    .filter(azure_ad_oid__iexact=identity.oid)[:2])
    if len(profiles) > 1:
        _security_event('azure_sso_ambiguous_link', 'Microsoft identity is linked to more than one account',
                        identity=identity, request=request)
        return None, 'ambiguous'

    if profiles:
        profile = profiles[0]
        user = profile.user
        if profile.azure_ad_tid and profile.azure_ad_tid.lower() != identity.tid:
            _security_event('azure_sso_tenant_mismatch',
                            'Microsoft sign-in from a different tenant than the linked identity',
                            user=user, identity=identity, request=request,
                            linked_tid=profile.azure_ad_tid)
            return None, 'tenant_mismatch'
        if not user.is_active:
            return None, 'inactive'
        if user.is_superuser and not profile.azure_ad_linked_at:
            # Linked automatically by e-mail before v3.17.688: an administrator
            # account must be linked deliberately once.
            _security_event('azure_sso_superuser_relink_required',
                            'Superuser has a pre-v3.17.688 automatic Microsoft link; must link explicitly',
                            user=user, identity=identity, request=request)
            return None, 'superuser_link_required'
        if not profile.azure_ad_tid:
            # First sign-in since v3.17.688 on a legacy link: capture the tenant.
            profile.azure_ad_tid = identity.tid
            profile.save(update_fields=['azure_ad_tid'])
        return user, None

    # Not linked. An e-mail match never links: refuse and record it.
    if identity.addresses:
        q = Q()
        for addr in identity.addresses:
            q |= Q(email__iexact=addr)
        matches = list(User.objects.filter(q).distinct()[:2])
        if matches:
            target = matches[0] if len(matches) == 1 else None
            if target is not None:
                _record_link_request(target, identity, request)
            _security_event('azure_sso_email_match_refused',
                            'Microsoft sign-in named the e-mail of an account it is not linked to',
                            user=target, identity=identity, request=request,
                            claimed_email=identity.email)
            return None, 'link_required'

    if not config.get('auto_create', False):
        _security_event('azure_sso_no_account', 'No account is linked to this Microsoft identity',
                        identity=identity, request=request,
                        claimed_addresses=list(identity.addresses))
        return None, 'no_account'

    return _create_sso_user(identity), None


def _create_sso_user(identity):
    """A new account for an unlinked identity: no organisation membership, no
    staff or superuser rights, no usable password."""
    base = re.sub(r'[^a-z0-9._-]', '', (identity.email.split('@')[0] if identity.email else '')) or 'sso-user'
    base = base[:140]
    username, counter = base, 1
    while User.objects.filter(username=username).exists():
        username = f'{base}{counter}'
        counter += 1
    with transaction.atomic():
        user = User.objects.create_user(
            username=username, email=identity.email, password=None,
            first_name=identity.given_name or identity.name[:150], last_name=identity.family_name,
            is_staff=False, is_superuser=False,
        )
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.auth_source = 'azure_ad'
        profile.azure_ad_oid = identity.oid
        profile.azure_ad_tid = identity.tid
        profile.azure_ad_linked_at = timezone.now()
        profile.save(update_fields=['auth_source', 'azure_ad_oid', 'azure_ad_tid', 'azure_ad_linked_at'])
    AuditLog.objects.create(
        action='create', user=user, username=user.username, object_type='User',
        object_id=user.id, object_repr=str(user),
        description='New user created from Microsoft sign-in (no client access)',
        extra_data={'source': 'azure_ad', 'tid': identity.tid, 'oid': identity.oid},
    )
    logger.info('Created new user %s from Azure AD', username)
    return user


def link_identity(user, identity, actor, method, request=None):
    """Link ``user`` to a verified identity. ``method`` is 'self' (the user,
    after re-authenticating) or 'admin' (an administrator confirming a
    request). Returns an error code or None."""
    if not isinstance(identity, AzureIdentity):
        return 'invalid_token'
    with transaction.atomic():
        clash = (UserProfile.objects.select_for_update()
                 .filter(azure_ad_oid__iexact=identity.oid).exclude(user=user).exists())
        if clash:
            _security_event('azure_sso_link_in_use', 'Microsoft identity is already linked to another account',
                            user=user, identity=identity, request=request, method=method)
            return 'in_use'
        profile, _ = UserProfile.objects.select_for_update().get_or_create(user=user)
        before = {'tid': profile.azure_ad_tid, 'oid': profile.azure_ad_oid}
        profile.azure_ad_oid = identity.oid
        profile.azure_ad_tid = identity.tid
        profile.azure_ad_linked_at = timezone.now()
        profile.save(update_fields=['azure_ad_oid', 'azure_ad_tid', 'azure_ad_linked_at'])
        AzureADLinkRequest.objects.filter(user=user, status='pending').update(
            status='rejected', decided_at=timezone.now(), decided_by=actor)
    AuditLog.log(user=actor, action='update', object_type='User', object_id=user.pk,
                 object_repr=str(user), ip_address=_ip(request),
                 description=f'Microsoft sign-in linked ({method})',
                 extra_data={'event': 'azure_sso_linked', 'method': method, 'before': before,
                             'tid': identity.tid, 'oid': identity.oid})
    return None


def unlink_identity(user, actor, request=None):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    before = {'tid': profile.azure_ad_tid, 'oid': profile.azure_ad_oid}
    profile.azure_ad_oid = ''
    profile.azure_ad_tid = ''
    profile.azure_ad_linked_at = None
    profile.save(update_fields=['azure_ad_oid', 'azure_ad_tid', 'azure_ad_linked_at'])
    AuditLog.log(user=actor, action='update', object_type='User', object_id=user.pk,
                 object_repr=str(user), ip_address=_ip(request),
                 description='Microsoft sign-in unlinked',
                 extra_data={'event': 'azure_sso_unlinked', 'before': before})


def approve_link_request(link_request, admin, request=None):
    """An administrator confirms a recorded request. Returns an error code or None."""
    if link_request.status != 'pending':
        return 'not_pending'
    if link_request.user_id == admin.pk:
        return 'own_account'
    tid, oid = link_request.tenant_id.lower(), link_request.object_id.lower()
    if not GUID_RE.match(tid) or not GUID_RE.match(oid):
        return 'invalid_token'
    identity = AzureIdentity(tid=tid, oid=oid, email=link_request.claimed_email,
                             name=link_request.claimed_name, given_name='', family_name='',
                             _token=_VERIFIED)
    err = link_identity(link_request.user, identity, admin, 'admin', request=request)
    if err:
        return err
    AzureADLinkRequest.objects.filter(pk=link_request.pk).update(
        status='approved', decided_at=timezone.now(), decided_by=admin)
    return None


class AzureADBackend(ModelBackend):
    """Authentication backend for Microsoft sign-ins.

    ``authenticate`` accepts only an ``AzureIdentity`` from verify_id_token();
    the sign-in view calls ``resolve_sso_user`` directly so it can tell the
    user why a sign-in was refused.
    """

    def authenticate(self, request, azure_identity=None, **kwargs):
        if not isinstance(azure_identity, AzureIdentity):
            return None
        config = load_azure_config()
        if not config:
            return None
        user, _error = resolve_sso_user(azure_identity, config, request)
        return user


class AzureOAuthClient:
    """MSAL authorization code flow (PKCE + nonce + state)."""

    def __init__(self):
        self.config = self.load_config()

    def load_config(self):
        settings = SystemSetting.get_settings()
        return {
            'enabled': getattr(settings, 'azure_ad_enabled', False),
            'tenant_id': (getattr(settings, 'azure_ad_tenant_id', '') or '').strip().lower(),
            'client_id': (getattr(settings, 'azure_ad_client_id', '') or '').strip(),
            'client_secret': settings.get_azure_ad_client_secret_decrypted(),
            'redirect_uri': (getattr(settings, 'azure_ad_redirect_uri', '') or '').strip(),
        }

    def is_enabled(self):
        return bool(
            self.config.get('enabled', False) and
            self.config.get('tenant_id') and
            self.config.get('client_id') and
            self.config.get('client_secret') and
            self.config.get('redirect_uri')
        )

    def _app(self):
        return msal.ConfidentialClientApplication(
            self.config['client_id'],
            authority=f"{AUTHORITY_HOST}/{self.config['tenant_id']}",
            client_credential=self.config['client_secret'],
        )

    def initiate_flow(self, prompt=None):
        """Start an auth code flow. Returns MSAL's flow dict (auth_uri, state,
        nonce, code_verifier, ...) for the caller to keep in the session, or None."""
        if not self.is_enabled() or not TENANT_NAME_RE.match(self.config['tenant_id']):
            return None
        try:
            kwargs = {'redirect_uri': self.config['redirect_uri']}
            if prompt:
                kwargs['prompt'] = prompt
            flow = self._app().initiate_auth_code_flow(SCOPES, **kwargs)
        except Exception as e:
            logger.error(f"Error generating Azure authorization URL: {e}")
            return None
        if not flow.get('code_verifier') or not flow.get('nonce') or not flow.get('state'):
            logger.error('MSAL auth code flow is missing PKCE, nonce or state')
            return None
        return flow

    def complete_flow(self, flow, auth_response):
        """Exchange the code. MSAL checks state, PKCE and the nonce. Returns the
        token response (with id_token) or None."""
        if not self.is_enabled():
            logger.error("Azure AD is not enabled or not fully configured")
            return None
        try:
            result = self._app().acquire_token_by_auth_code_flow(flow, auth_response, scopes=SCOPES)
        except ValueError as e:
            logger.warning(f"Azure AD auth code flow rejected the response: {e}")
            return None
        except Exception as e:
            logger.exception(f"Exception while exchanging code for token: {e}")
            return None
        if 'id_token' in result and 'access_token' in result:
            return result
        error_description = result.get('error_description', 'No description provided')
        logger.error(
            f"Azure AD token acquisition failed:\n"
            f"  Error: {result.get('error', 'unknown_error')}\n"
            f"  Description: {error_description}\n"
            f"  Error Codes: {result.get('error_codes', [])}\n"
            f"  Correlation ID: {result.get('correlation_id', 'N/A')}\n"
            f"  Redirect URI: {self.config['redirect_uri']}"
        )
        if 'AADSTS54005' in error_description:
            logger.error("OAuth2 authorization code was already used.")
        elif 'AADSTS50011' in error_description:
            logger.error("Redirect URI mismatch. Check the Azure app registration redirect URI.")
        elif 'AADSTS700016' in error_description:
            logger.error("Application not found. Check that Client ID is correct.")
        return None


def azure_mfa_asserted(token_response):
    """True when Microsoft says this sign-in used multi-factor authentication
    (`mfa` in the `amr` claim) — v3.17.660.

    Before v3.17.660 every Microsoft sign-in skipped Clientst0r's 2FA, even
    when the tenant never asked for a second factor. `amr` is read from the
    ID token claims MSAL validated; when the ID token doesn't carry it (v2
    tokens usually don't), from the access token's payload. That token came
    straight from Microsoft's token endpoint over TLS in this request
    (authorization-code exchange with our client secret), so its payload is
    Microsoft's statement even though it isn't ours to verify.
    """
    import base64
    import json
    if not isinstance(token_response, dict):
        return False
    amr = (token_response.get('id_token_claims') or {}).get('amr')
    if not amr:
        try:
            payload = token_response.get('access_token', '').split('.')[1]
            payload += '=' * (-len(payload) % 4)
            amr = json.loads(base64.urlsafe_b64decode(payload)).get('amr')
        except Exception:
            amr = None
    return isinstance(amr, (list, tuple)) and 'mfa' in amr


def azure_sso_counts_as_2fa(request):
    """Whether this session's Microsoft sign-in stands in for Clientst0r's 2FA:
    Microsoft confirmed MFA, or the operator set AZURE_SSO_TRUSTED_AS_2FA
    (their tenant enforces MFA, e.g. by Conditional Access, but the tokens
    don't say so)."""
    from django.conf import settings
    session = request.session
    if not session.get('azure_ad_authenticated', False):
        return False
    return bool(session.get('azure_ad_mfa', False) or getattr(settings, 'AZURE_SSO_TRUSTED_AS_2FA', False))
