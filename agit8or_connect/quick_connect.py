"""Protocol revision 1.1: Quick Connect extensions (PROTOCOL-1.1.md).

Three optional, negotiated extensions on top of agit8or-connect/1. Nothing
in v1 changes: every v1 message, header, signing string and vector keeps its
bytes and meaning, and a peer that only speaks v1 never sees any of this.

  qc-bootstrap/1       browser-mediated pairing: a signed, single-use
                       invitation (typ agit8or-qc-invitation+jwt) carried by
                       the administrator's browser to the responder's own admin
                       UI; an authorisation response with a one-time code and a
                       signed acceptance (typ agit8or-qc-accept+jwt); a server
                       to server exchange (typ agit8or-qc-exchange+jwt, PKCE
                       S256, DPoP) answered with the UNCHANGED v1 pairing ack.
                       From the ack on, everything is v1 (poll, result, tokens,
                       JWKS, events).
  qc-source-binding/1  signed egress-address declarations in the invitation
                       and the acceptance, and the error code
                       source_not_authorised (HTTP 403).
  qc-diagnostics/1     POST qc_probe (v1 DPoP access token) answering the
                       source address the peer observed.

The OAuth shape is authorization code + PKCE only. There is no password
grant (ROPC) and no field that could carry a password anywhere in 1.1.

Every function here is pure: time comes from `now`, replay state from a
ReplayStore, randomness only from the generate_* helpers. That is what lets
both SDKs reproduce docs/agit8or-connect/test-vectors/qc-*.json byte for byte.
"""
from __future__ import annotations

import hmac
import ipaddress
import re
import secrets
import time
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import PROTOCOL
from . import keys as _keys
from . import tokens as _tokens
from .canonical import b64url, canonical_json, sha256_b64url, sha256_hex
from .errors import (ConnectError, CODE_EXPIRED, CODE_USED, DESTINATION_MISMATCH, DOWNGRADE_DETECTED,
                     EXPIRED, IDENTITY_MISMATCH, INVALID_BASE, INVALID_EGRESS, INVALID_GRANT, INVALID_REDIRECT_URI,
                     INVALID_REQUEST, INVALID_SIGNATURE, INVITATION_EXPIRED, INVITATION_USED, KEY_MISMATCH,
                     PKCE_MISMATCH, REPLAYED, TOO_LARGE, UNSUPPORTED_VERSION, WRONG_ATTEMPT, WRONG_AUDIENCE)
from .jws import sign_compact, unverified_header, unverified_payload, verify_compact
from .pairing import short_authentication_string
from .replay import ReplayStore

REVISION = '1.1'
PROTOCOL_ID_1_1 = f'{PROTOCOL}/{REVISION}'

EXT_BOOTSTRAP = 'qc-bootstrap'
EXT_SOURCE_BINDING = 'qc-source-binding'
EXT_DIAGNOSTICS = 'qc-diagnostics'
BOOTSTRAP_ID = f'{EXT_BOOTSTRAP}/1'
# What this SDK implements: extension name -> supported versions.
SUPPORTED_EXTENSIONS: Dict[str, Tuple[int, ...]] = {EXT_BOOTSTRAP: (1,), EXT_SOURCE_BINDING: (1,),
                                                    EXT_DIAGNOSTICS: (1,)}
# An extension counts as advertised only with these discovery endpoints,
# each on the discovery origin.
EXTENSION_ENDPOINTS: Dict[str, Tuple[str, ...]] = {EXT_BOOTSTRAP: ('qc_authorize', 'qc_exchange'),
                                                   EXT_SOURCE_BINDING: (), EXT_DIAGNOSTICS: ('qc_probe',)}
# qc-bootstrap/1 is only used together with qc-source-binding/1.
EXTENSION_REQUIRES: Dict[str, Tuple[str, ...]] = {EXT_BOOTSTRAP: (EXT_SOURCE_BINDING,)}

TYP_INVITATION = 'agit8or-qc-invitation+jwt'
TYP_ACCEPT = 'agit8or-qc-accept+jwt'
TYP_EXCHANGE = 'agit8or-qc-exchange+jwt'

INVITATION_MAX_LIFETIME = 600
ACCEPT_MAX_LIFETIME = 600
EXCHANGE_MAX_LIFETIME = 120
CODE_TTL = 120
TEMPORARY_RULE_TTL = 900          # informative: how long the responder's temporary pairing rule lives
MAX_INVITATION_LENGTH = 4096      # the whole compact JWS, so it fits in a URL
MAX_EGRESS = 8
MAX_NOTE = 100
MAX_URL = 512
SKEW = 120

API = '/connect/v1'
AUTHORIZE_ENTRY_PATH = '/agit8or-connect/qc-authorize'   # conventional browser entry point (§5.2)
EXCHANGE_PATH = f'{API}/qc/exchange'
PROBE_PATH = f'{API}/qc/probe'

# Replay-store namespaces (in addition to v1's).
NS_INVITATION = 'qc-inv'
NS_EXCHANGE = 'qc-exchange'
NS_CODE = 'qc-code'

_B64URL_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_JTI_RE = re.compile(r'^[A-Za-z0-9_-]{16,128}$')
_VERIFIER_RE = re.compile(r'^[A-Za-z0-9._~-]{43,128}$')
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

# Never valid as an egress declaration or a base host literal (overlap refused).
_REFUSED_NETS = tuple(ipaddress.ip_network(n) for n in (
    '0.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16', '224.0.0.0/4', '240.0.0.0/4', '100.100.100.200/32',
    '192.0.0.192/32', '::/128', '::1/128', '::ffff:0:0/96', 'fe80::/10', 'ff00::/8', 'fd00:ec2::254/128'))
# Flagged to the administrator as "private" (never trusted implicitly).
_PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7'))
MIN_PREFIX = {4: 16, 6: 32}
_MAPPED = ipaddress.ip_network('::ffff:0:0/96')
# Text accepted before parsing (PROTOCOL-1.1.md §4.1): an IPv4 dotted quad or
# IPv6 text, optionally "/" and a decimal prefix without leading zeros. No
# netmask form, zone id or whitespace.
_NET_SYNTAX = re.compile(r'^(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9A-Fa-f:.]{2,45})(?:/(?:0|[1-9][0-9]{0,2}))?$')


def _now(now) -> int:
    return int(time.time() if now is None else now)


# --- random values ------------------------------------------------------------------

def generate_code() -> str:
    """Authorisation code: 256 bits, base64url (43 characters)."""
    return b64url(secrets.token_bytes(32))


def generate_state() -> str:
    return b64url(secrets.token_bytes(32))


def generate_nonce() -> str:
    return b64url(secrets.token_bytes(32))


def generate_pkce_verifier() -> str:
    """RFC 7636 code verifier: 32 random bytes, base64url (43 characters)."""
    return b64url(secrets.token_bytes(32))


def pkce_challenge(verifier: str) -> str:
    """S256: base64url(SHA-256(ASCII(verifier)))."""
    if not isinstance(verifier, str) or not _VERIFIER_RE.match(verifier):
        raise ConnectError(INVALID_REQUEST, 'code_verifier malformed')
    return sha256_b64url(verifier.encode('ascii'))


# --- addresses and URLs --------------------------------------------------------------

def normalize_net(value: str) -> str:
    """Canonical text of an address or network: an exact address gets /32 or
    /128; IPv4 dotted decimal without leading zeros; IPv6 per RFC 5952
    (lower case, longest run of two or more zero groups compressed, the
    first on a tie). Host bits must be zero. Zone ids are refused."""
    if not isinstance(value, str) or not _NET_SYNTAX.match(value):
        raise ConnectError(INVALID_EGRESS, 'address malformed')
    try:
        net = ipaddress.ip_network(value, strict=True)
    except ValueError as e:
        raise ConnectError(INVALID_EGRESS, 'address malformed') from e
    if net.version == 6 and net.overlaps(_MAPPED):
        # Refused before formatting: text forms of IPv4-mapped addresses differ between libraries.
        raise ConnectError(INVALID_EGRESS, 'IPv4-mapped IPv6 addresses are not accepted')
    return net.with_prefixlen


def is_private_net(net: str) -> bool:
    n = ipaddress.ip_network(normalize_net(net))
    return any(n.version == p.version and n.overlaps(p) for p in _PRIVATE_NETS)


def check_net(value: str) -> str:
    """A canonical, acceptable egress network, or invalid_egress."""
    canon = normalize_net(value)
    if canon != value:
        raise ConnectError(INVALID_EGRESS, 'address is not in canonical form')
    n = ipaddress.ip_network(canon)
    if n.prefixlen < MIN_PREFIX[n.version]:
        raise ConnectError(INVALID_EGRESS, 'address range too broad')
    if any(n.version == r.version and n.overlaps(r) for r in _REFUSED_NETS):
        raise ConnectError(INVALID_EGRESS, 'loopback, link-local, multicast, unspecified, mapped or metadata '
                                           'address')
    return canon


def egress_entries(nets: Iterable, notes: Optional[Mapping[str, str]] = None) -> List[dict]:
    """Builder helper: [{'net': canonical, 'note': str}] in the given order."""
    out = []
    for item in nets:
        net, note = (item.get('net'), item.get('note', '')) if isinstance(item, dict) else (item, '')
        canon = normalize_net(net)
        out.append({'net': canon, 'note': str((notes or {}).get(canon, note) or '')[:MAX_NOTE]})
    return validate_egress(out)


def validate_egress(entries) -> List[dict]:
    """1..8 entries {net, note}; nets canonical, acceptable, distinct."""
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_EGRESS:
        raise ConnectError(INVALID_EGRESS, 'egress must list 1 to 8 addresses')
    seen = set()
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get('net'), str):
            raise ConnectError(INVALID_EGRESS, 'egress entry malformed')
        note = e.get('note', '')
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            raise ConnectError(INVALID_EGRESS, 'egress note malformed')
        net = check_net(e['net'])
        if net in seen:
            raise ConnectError(INVALID_EGRESS, 'egress address listed twice')
        seen.add(net)
    return entries


def egress_nets(entries) -> List[str]:
    return [e['net'] for e in entries]


def source_in_egress(source: str, entries) -> bool:
    """Is an observed source address inside one of the declared networks?"""
    try:
        addr = ipaddress.ip_address(source)
    except (ValueError, TypeError):
        return False
    return any(addr in ipaddress.ip_network(e['net']) for e in entries)


def _ascii(s) -> bool:
    return isinstance(s, str) and all(0x21 <= ord(c) <= 0x7e for c in s)


_LABEL = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
_URL_RE = re.compile(r'^https://(' + _LABEL + r'(?:\.' + _LABEL + r')*|\[[0-9a-f:.]+\])'
                     r'(?::([1-9][0-9]{0,4}))?((?:/[A-Za-z0-9._~-]+)*)$')


def parse_https_url(url: str, code: str = INVALID_BASE) -> Tuple[str, int, str]:
    """(host, port, path) of a URL in the strict canonical grammar of
    PROTOCOL-1.1.md §4.3: lower-case https, a DNS name, canonical IPv4 or
    bracketed canonical IPv6 host, an explicit port only when not 443,
    a path of non-empty unreserved segments (no '.', '..', trailing slash,
    query, fragment, user info or percent-encoding)."""
    if not _ascii(url) or len(url) > MAX_URL:
        raise ConnectError(code, 'URL malformed')
    m = _URL_RE.match(url)
    if not m:
        raise ConnectError(code, 'URL is not in canonical form')
    host, port_s, path = m.group(1), m.group(2), m.group(3)
    if any(seg in ('.', '..') for seg in path.split('/')):
        raise ConnectError(code, 'URL path malformed')
    port = int(port_s) if port_s else 443
    if port > 65535 or port == 443 and port_s:
        raise ConnectError(code, 'URL port malformed')
    if host.startswith('['):
        inner = host[1:-1]
        try:
            ip = ipaddress.IPv6Address(inner)
        except ValueError as e:
            raise ConnectError(code, 'URL host malformed') from e
        if str(ip) != inner or ip in ipaddress.ip_network('::ffff:0:0/96'):
            raise ConnectError(code, 'URL host is not canonical')
    elif re.match(r'^[0-9.]+$', host):
        try:
            ip = ipaddress.IPv4Address(host)
        except ValueError as e:
            raise ConnectError(code, 'URL host malformed') from e
        if str(ip) != host:
            raise ConnectError(code, 'URL host is not canonical')
    elif len(host) > 253:
        raise ConnectError(code, 'URL host too long')
    return host, port, path


def origin_of(url: str, code: str = INVALID_BASE) -> str:
    """https://host[:port] of a canonical URL."""
    host, port, _ = parse_https_url(url, code)
    return f'https://{host}' + (f':{port}' if port != 443 else '')


def origin_host_port(origin: str) -> Tuple[str, int]:
    host, port, _ = parse_https_url(origin)
    return (host[1:-1] if host.startswith('[') else host), port


def check_base(url: str, allowed_ports: Sequence[int] = (443,)) -> str:
    """Static check of a peer's public base (nothing is fetched): canonical
    grammar, port allowed, host not localhost and not a refused literal."""
    host, port, _ = parse_https_url(url, INVALID_BASE)
    if port not in tuple(allowed_ports):
        raise ConnectError(INVALID_BASE, 'base port not allowed')
    if host == 'localhost' or host.endswith('.localhost'):
        raise ConnectError(INVALID_BASE, 'base host not allowed')
    try:
        ip = ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        ip = None
    if ip is not None and any(ip.version == r.version and ip in r for r in _REFUSED_NETS):
        raise ConnectError(INVALID_BASE, 'base host not allowed')
    return url


def check_redirect_uri(redirect_uri: str, base: str) -> str:
    """Canonical grammar, at least one path segment, same origin as `base`."""
    _, _, path = parse_https_url(redirect_uri, INVALID_REDIRECT_URI)
    if not path:
        raise ConnectError(INVALID_REDIRECT_URI, 'redirect_uri needs a path')
    if origin_of(redirect_uri, INVALID_REDIRECT_URI) != origin_of(base, INVALID_REDIRECT_URI):
        raise ConnectError(INVALID_REDIRECT_URI, 'redirect_uri is not on the initiator origin')
    return redirect_uri


# --- extensions and negotiation -------------------------------------------------------

def _versions(value) -> Tuple[int, ...]:
    if isinstance(value, bool):
        return ()
    if isinstance(value, int):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(sorted({v for v in value if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 1000}))


def normalize_extensions(value) -> Dict[str, List[int]]:
    """{name: int | [int]} -> {name: sorted [int]}; malformed members dropped."""
    out = {}
    if isinstance(value, dict):
        for name, v in value.items():
            vs = _versions(v)
            if isinstance(name, str) and vs and len(name) <= 64:
                out[name] = list(vs)
    return out


def signed_extensions(supported: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS) -> Dict[str, List[int]]:
    """The form carried in invitation and accept: {name: sorted [versions]}."""
    return normalize_extensions({k: list(v) for k, v in supported.items()})


def advertised_extensions(doc: dict, discovery_url: str) -> Dict[str, List[int]]:
    """Extensions a discovery document advertises. An extension whose
    required endpoints are missing or on another origin is not advertised.
    A v1 document (no `extensions`) advertises nothing."""
    from .discovery import origin
    if not isinstance(doc, dict):
        return {}
    ext = normalize_extensions(doc.get('extensions'))
    eps = doc.get('endpoints') if isinstance(doc.get('endpoints'), dict) else {}
    want = origin(discovery_url)
    for name, needed in EXTENSION_ENDPOINTS.items():
        if name not in ext:
            continue
        for ep in needed:
            v = eps.get(ep)
            if not isinstance(v, str) or not v or not _ascii(v) or origin(v) != want:
                del ext[name]
                break
    return ext


def negotiate_extensions(theirs: Mapping[str, Sequence[int]],
                         ours: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS) -> Dict[str, int]:
    """{name: highest common version}. Extensions whose prerequisite was not
    negotiated are dropped. Empty for a v1 peer."""
    out = {}
    for name, our_versions in ours.items():
        common = set(our_versions) & set(_versions(list(theirs.get(name, ()))))
        if common:
            out[name] = max(common)
    for name, needs in EXTENSION_REQUIRES.items():
        if name in out and any(n not in out for n in needs):
            del out[name]
    return dict(sorted(out.items()))


def pairing_flow(negotiated: Mapping[str, int]) -> str:
    """'qc-bootstrap/1' when Quick Connect can be used, else 'code' (v1)."""
    return BOOTSTRAP_ID if negotiated.get(EXT_BOOTSTRAP) == 1 else 'code'


def check_no_downgrade(signed: Mapping[str, Sequence[int]], discovered: Mapping[str, Sequence[int]],
                       ours: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS) -> None:
    """A peer's discovery document must advertise every extension version the
    peer SIGNED (in its invitation or accept) that we also implement.
    Anything less means the document was altered or the peer was replaced:
    downgrade_detected."""
    disc = normalize_extensions(dict(discovered))
    for name, versions in normalize_extensions(dict(signed)).items():
        if name not in ours:
            continue
        mine = [v for v in versions if v in ours[name]]
        if any(v not in disc.get(name, []) for v in mine):
            raise ConnectError(DOWNGRADE_DETECTED, f'discovery no longer advertises {name}', 403)


def discovery_endpoints(base: str, authorize_url: Optional[str] = None,
                        extensions: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS) -> dict:
    """The 1.1 endpoint members for a discovery document."""
    b = base.rstrip('/')
    out = {}
    if EXT_BOOTSTRAP in extensions:
        out['qc_authorize'] = authorize_url or b + AUTHORIZE_ENTRY_PATH
        out['qc_exchange'] = b + EXCHANGE_PATH
    if EXT_DIAGNOSTICS in extensions:
        out['qc_probe'] = b + PROBE_PATH
    return out


def extend_discovery_document(doc: dict, base: str, authorize_url: Optional[str] = None,
                              extensions: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS) -> dict:
    """Add the 1.1 members to a v1 document (v1 peers ignore them)."""
    out = dict(doc)
    out['revision'] = REVISION
    out['extensions'] = {k: (v[0] if len(v) == 1 else list(v)) for k, v in signed_extensions(extensions).items()}
    eps = dict(out.get('endpoints') or {})
    eps.update(discovery_endpoints(base, authorize_url, extensions))
    out['endpoints'] = eps
    return out


# --- browser legs ------------------------------------------------------------------------

def parse_query(url_or_query: str) -> Dict[str, str]:
    """Single-valued query parameters; a repeated parameter is refused."""
    q = url_or_query.split('?', 1)[1] if '?' in url_or_query else url_or_query
    q = q.split('#', 1)[0]
    out: Dict[str, str] = {}
    for k, v in parse_qsl(q, keep_blank_values=True, strict_parsing=False):
        if k in out:
            raise ConnectError(INVALID_REQUEST, f'parameter {k} repeated')
        out[k] = v
    return out


def _check_state(state: str) -> str:
    if not isinstance(state, str) or not _B64URL_RE.match(state) or not 22 <= len(state) <= 128:
        raise ConnectError(INVALID_REQUEST, 'state malformed')
    return state


def authorization_url(authorize_endpoint: str, invitation: str, state: str) -> str:
    """GET {qc_authorize}?invitation=<JWS>&state=<state>"""
    _check_state(state)
    sep = '&' if '?' in authorize_endpoint else '?'
    return f'{authorize_endpoint}{sep}' + urlencode([('invitation', invitation), ('state', state)])


def authorization_response_url(redirect_uri: str, *, state: str, code: Optional[str] = None,
                               accept: Optional[str] = None, error: Optional[str] = None) -> str:
    """Success: redirect_uri?accept=..&code=..&state=..  Refusal: redirect_uri?error=..&state=..
    Only ever built for a redirect_uri taken from a VERIFIED invitation."""
    _check_state(state)
    if error is not None:
        params = [('error', error), ('state', state)]
    else:
        if not code or not accept:
            raise ValueError('code and accept are required')
        params = [('accept', accept), ('code', code), ('state', state)]
    return f'{redirect_uri}?' + urlencode(params)


def parse_authorization_response(url: str, *, expected_state: str) -> dict:
    """{'code', 'accept', 'state'} or raises the responder's error code
    (access_denied, invitation_expired, ...). `state` is compared in
    constant time with the one bound to the administrator's session."""
    q = parse_query(url)
    state = q.get('state', '')
    if not hmac.compare_digest(state.encode(), (expected_state or '').encode()) or not state:
        from .errors import STATE_MISMATCH
        raise ConnectError(STATE_MISMATCH, 'state does not match this attempt', 400)
    if 'error' in q:
        err = q['error'] if re.match(r'^[a-z_]{1,64}$', q['error']) else INVALID_REQUEST
        raise ConnectError(err, 'the other application refused the request', 400)
    code, accept = q.get('code', ''), q.get('accept', '')
    if not _B64URL_RE.match(code or '') or len(code) != 43 or not accept:
        raise ConnectError(INVALID_REQUEST, 'authorisation response incomplete')
    return {'code': code, 'accept': accept, 'state': state}


# --- shared claim checks ----------------------------------------------------------------

def _app(app: dict) -> dict:
    return {k: str(app.get(k) or '') for k in ('type', 'version', 'display_name', 'installation_id')}


def _require_str(claims, name, pattern=None, code=INVALID_REQUEST):
    v = claims.get(name)
    if not isinstance(v, str) or not v or (pattern is not None and not pattern.match(v)):
        raise ConnectError(code, f'{name} malformed')
    return v


def _check_extension_claims(claims) -> None:
    if claims.get('protocol') != PROTOCOL_ID_1_1 or claims.get('ext') != BOOTSTRAP_ID:
        raise ConnectError(UNSUPPORTED_VERSION, 'not an agit8or-connect/1.1 qc-bootstrap/1 message')


def _check_signed_extensions(claims) -> Dict[str, List[int]]:
    ext = normalize_extensions(claims.get('extensions'))
    if 1 not in ext.get(EXT_BOOTSTRAP, []) or 1 not in ext.get(EXT_SOURCE_BINDING, []):
        raise ConnectError(INVALID_REQUEST, 'extensions must include qc-bootstrap/1 and qc-source-binding/1')
    return ext


def _header_key(token: str, typ: str):
    header = unverified_header(token)
    if header.get('typ') != typ:
        raise ConnectError(INVALID_REQUEST, f'expected a {typ} token', 401)
    try:
        key = _keys.public_key_from_jwk(header.get('jwk'))
    except ConnectError as e:
        raise ConnectError(INVALID_SIGNATURE, e.message, 401) from e
    if header.get('kid') is not None and header['kid'] != _keys.thumbprint(key):
        raise ConnectError(INVALID_SIGNATURE, 'kid does not match the header key', 401)
    return header, key


# --- invitation (initiator A -> browser -> responder B) ------------------------------

def build_invitation(private_key: Ed25519PrivateKey, *, initiator_app: dict, responder_origin: str, attempt: str,
                     base: str, redirect_uri: str, egress, requested_scopes: Iterable[str], code_challenge: str,
                     nonce: str, responder_installation: Optional[str] = None,
                     extensions: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS, now=None, jti=None,
                     lifetime: int = INVITATION_MAX_LIFETIME) -> Tuple[str, dict]:
    if not 0 < lifetime <= 3600:
        raise ValueError('lifetime out of range')
    iat = _now(now)
    jwk = _keys.public_jwk(private_key)
    claims = {
        'protocol': PROTOCOL_ID_1_1, 'ext': BOOTSTRAP_ID, 'extensions': signed_extensions(extensions),
        'iss': initiator_app['installation_id'], 'aud': origin_of(responder_origin),
        'iat': iat, 'exp': iat + lifetime, 'jti': jti or b64url(secrets.token_bytes(18)),
        'attempt': attempt, 'app': _app(initiator_app), 'base': base, 'redirect_uri': redirect_uri,
        'egress': egress_entries(egress), 'requested_scopes': sorted(set(requested_scopes)),
        'code_challenge': code_challenge, 'code_challenge_method': 'S256', 'nonce': nonce,
    }
    if responder_installation:
        claims['responder_installation'] = responder_installation
    token = sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_INVITATION, 'kid': jwk['kid'], 'jwk': jwk},
                         claims)
    return token, claims


def verify_invitation(token: str, *, responder_origin: str, replay: ReplayStore, now=None,
                      responder_installation: Optional[str] = None,
                      allowed_ports: Sequence[int] = (443,)) -> Tuple[dict, dict]:
    """Responder (B), when the browser presents the invitation. Returns
    (claims, initiator public JWK). Checks, in order (PROTOCOL-1.1.md §5.3):
    size, typ, header key, signature, times, protocol/ext, audience, claim
    formats, base, redirect_uri, egress, extensions, single use."""
    if isinstance(token, str) and len(token) > MAX_INVITATION_LENGTH:
        raise ConnectError(TOO_LARGE, 'invitation too large', 413)
    _, key = _header_key(token, TYP_INVITATION)
    try:
        claims = verify_compact(token, key, typ=TYP_INVITATION, now=now, max_lifetime=INVITATION_MAX_LIFETIME,
                                skew=SKEW, required=('protocol', 'ext', 'iss', 'aud', 'iat', 'exp', 'jti', 'attempt',
                                                     'app', 'base', 'redirect_uri', 'egress', 'code_challenge',
                                                     'code_challenge_method', 'nonce', 'extensions'))
    except ConnectError as e:
        if e.code == EXPIRED:
            raise ConnectError(INVITATION_EXPIRED, 'invitation expired', 400) from e
        raise
    _check_extension_claims(claims)
    if claims.get('aud') != origin_of(responder_origin):
        raise ConnectError(WRONG_AUDIENCE, 'invitation is for another application', 400)
    if 'responder_installation' in claims and claims['responder_installation'] != responder_installation:
        raise ConnectError(WRONG_AUDIENCE, 'invitation is for another installation', 400)
    _require_str(claims, 'iss', _UUID_RE)
    _require_str(claims, 'jti', _JTI_RE)
    _require_str(claims, 'attempt', _UUID_RE)
    app = claims.get('app')
    if not isinstance(app, dict) or app.get('installation_id') != claims['iss']:
        raise ConnectError(INVALID_REQUEST, 'app identity does not match the issuer')
    if claims.get('code_challenge_method') != 'S256':
        raise ConnectError(INVALID_REQUEST, 'only S256 is accepted')
    if not isinstance(claims.get('code_challenge'), str) or len(claims['code_challenge']) != 43 or \
            not _B64URL_RE.match(claims['code_challenge']):
        raise ConnectError(INVALID_REQUEST, 'code_challenge malformed')
    if not isinstance(claims.get('nonce'), str) or not 22 <= len(claims['nonce']) <= 128 or \
            not _B64URL_RE.match(claims['nonce']):
        raise ConnectError(INVALID_REQUEST, 'nonce malformed')
    scopes = claims.get('requested_scopes', [])
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise ConnectError(INVALID_REQUEST, 'requested_scopes must be a list of strings')
    check_base(claims['base'], allowed_ports)
    check_redirect_uri(claims['redirect_uri'], claims['base'])
    validate_egress(claims['egress'])
    _check_signed_extensions(claims)
    if not replay.add(NS_INVITATION, f'{claims["iss"]}:{claims["jti"]}', claims['exp'] + SKEW):
        raise ConnectError(INVITATION_USED, 'invitation already used', 400)
    return claims, _keys.public_jwk(key)


# --- accept (responder B -> browser -> initiator A) ---------------------------------

def build_accept(private_key: Ed25519PrivateKey, *, responder_app: dict, invitation: dict, invitation_jws: str,
                 connection_id: str, base: str, egress, code: str,
                 extensions: Mapping[str, Sequence[int]] = SUPPORTED_EXTENSIONS, now=None,
                 lifetime: int = ACCEPT_MAX_LIFETIME) -> str:
    """`private_key` is B's new connection key K_B; the same key signs the v1 ack."""
    iat = _now(now)
    jwk = _keys.public_jwk(private_key)
    return sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_ACCEPT, 'kid': jwk['kid'], 'jwk': jwk}, {
        'protocol': PROTOCOL_ID_1_1, 'ext': BOOTSTRAP_ID, 'extensions': signed_extensions(extensions),
        'iss': responder_app['installation_id'], 'aud': invitation['iss'], 'iat': iat, 'exp': iat + lifetime,
        'attempt': invitation['attempt'], 'invitation': invitation['jti'],
        'invitation_sha256': sha256_hex(invitation_jws), 'connection_id': connection_id,
        'app': _app(responder_app), 'base': base, 'egress': egress_entries(egress),
        'code_sha256': sha256_hex(code)})


def verify_accept(token: str, *, invitation: dict, invitation_jws: str, code: str, now=None,
                  allowed_ports: Sequence[int] = (443,)) -> Tuple[dict, dict]:
    """Initiator (A), on the callback. Returns (claims, responder public JWK)."""
    _, key = _header_key(token, TYP_ACCEPT)
    claims = verify_compact(token, key, typ=TYP_ACCEPT, now=now, max_lifetime=ACCEPT_MAX_LIFETIME, skew=SKEW,
                            required=('protocol', 'ext', 'extensions', 'iss', 'aud', 'iat', 'exp', 'attempt',
                                      'invitation', 'invitation_sha256', 'connection_id', 'app', 'base', 'egress',
                                      'code_sha256'))
    _check_extension_claims(claims)
    if claims.get('aud') != invitation['iss']:
        raise ConnectError(WRONG_AUDIENCE, 'acceptance is for another installation', 401)
    if claims.get('invitation') != invitation['jti'] or claims.get('attempt') != invitation['attempt'] or \
            claims.get('invitation_sha256') != sha256_hex(invitation_jws):
        raise ConnectError(WRONG_ATTEMPT, 'acceptance is for another attempt', 401)
    if not isinstance(code, str) or not hmac.compare_digest(str(claims.get('code_sha256')), sha256_hex(code)):
        raise ConnectError(INVALID_GRANT, 'code does not belong to this acceptance', 401)
    _require_str(claims, 'iss', _UUID_RE)
    _require_str(claims, 'connection_id', _UUID_RE)
    app = claims.get('app')
    if not isinstance(app, dict) or app.get('installation_id') != claims['iss']:
        raise ConnectError(INVALID_REQUEST, 'app identity does not match the issuer')
    check_base(claims['base'], allowed_ports)
    if origin_of(claims['base']) != invitation['aud']:
        raise ConnectError(DESTINATION_MISMATCH, 'the answering application is not the approved destination', 401)
    validate_egress(claims['egress'])
    _check_signed_extensions(claims)
    return claims, _keys.public_jwk(key)


def check_discovered_identity(accept: dict, discovery_doc: dict, discovery_url: str) -> Dict[str, int]:
    """After the callback A reads B's discovery: same installation id as the
    accept, no downgrade, qc-bootstrap/1 negotiated. Returns the negotiated set."""
    app = discovery_doc.get('app') if isinstance(discovery_doc, dict) else None
    if not isinstance(app, dict) or app.get('installation_id') != accept['iss']:
        raise ConnectError(IDENTITY_MISMATCH, 'discovery identity differs from the signed acceptance', 403)
    adv = advertised_extensions(discovery_doc, discovery_url)
    check_no_downgrade(accept.get('extensions') or {}, adv)
    negotiated = negotiate_extensions(adv)
    if pairing_flow(negotiated) != BOOTSTRAP_ID:
        raise ConnectError(DOWNGRADE_DETECTED, 'qc-bootstrap/1 not negotiated', 403)
    return negotiated


# --- exchange (initiator A -> responder B, server to server) -------------------------

def build_exchange(private_key: Ed25519PrivateKey, *, invitation: dict, accept: dict, accept_jws: str, code: str,
                   code_verifier: str, initiator_app: dict, discovery_url: str, requested_scopes: Iterable[str],
                   proposed_tenants: Iterable[dict] = (), now=None, jti=None,
                   lifetime: int = 60) -> Tuple[str, dict]:
    """Signed with K_A (the invitation key). Carries every v1 pairing-request
    claim except pairing_code."""
    if not 0 < lifetime <= EXCHANGE_MAX_LIFETIME:
        raise ValueError('lifetime out of range')
    iat = _now(now)
    jwk = _keys.public_jwk(private_key)
    claims = {
        'protocol': PROTOCOL_ID_1_1, 'ext': BOOTSTRAP_ID, 'iss': initiator_app['installation_id'],
        'aud': accept['iss'], 'iat': iat, 'exp': iat + lifetime, 'jti': jti or b64url(secrets.token_bytes(18)),
        'code': code, 'code_verifier': code_verifier, 'invitation': invitation['jti'],
        'accept_sha256': sha256_hex(accept_jws), 'app': _app(initiator_app),
        'connection_id': invitation['attempt'], 'discovery_url': discovery_url, 'connection_key': jwk,
        'requested_scopes': sorted(set(requested_scopes)),
        'proposed_tenants': [{'id': str(t['id']), 'label': str(t.get('label') or '')[:200]}
                             for t in proposed_tenants],
    }
    return sign_compact(private_key, {'alg': 'EdDSA', 'typ': TYP_EXCHANGE, 'kid': jwk['kid']}, claims), claims


def exchange_code_sha256(token: str) -> str:
    """sha256_hex of the code in an exchange, WITHOUT verification — only to
    find the grant whose stored key then verifies the exchange."""
    try:
        code = unverified_payload(token).get('code')
    except ConnectError:
        return ''
    return sha256_hex(code) if isinstance(code, str) and code else ''


def verify_exchange(token: str, *, dpop: str, url: str, invitation: dict, invitation_jwk: dict, accept_jws: str,
                    code_sha256: str, code_expires_at: int, responder_installation: str, replay: ReplayStore,
                    now=None) -> dict:
    """Responder (B), at POST qc_exchange, after the source-address layer
    passed (the request came from this attempt's temporary rule). Order is
    normative (PROTOCOL-1.1.md §6.4). Single-use values are recorded last."""
    now_i = _now(now)
    header = unverified_header(token)
    if header.get('typ') != TYP_EXCHANGE:
        raise ConnectError(INVALID_REQUEST, f'expected a {TYP_EXCHANGE} token', 401)
    key = _keys.public_key_from_jwk(invitation_jwk)
    kid = _keys.thumbprint(key)
    if header.get('kid') != kid:
        raise ConnectError(KEY_MISMATCH, 'exchange not signed by the invitation key', 401)
    claims = verify_compact(token, key, typ=TYP_EXCHANGE, now=now_i, max_lifetime=EXCHANGE_MAX_LIFETIME,
                            skew=SKEW, required=('protocol', 'ext', 'iss', 'aud', 'iat', 'exp', 'jti', 'code',
                                                 'code_verifier', 'invitation', 'accept_sha256', 'app',
                                                 'connection_id', 'connection_key'))
    _check_extension_claims(claims)
    if claims.get('aud') != responder_installation:
        raise ConnectError(WRONG_AUDIENCE, 'exchange is for another installation', 401)
    if claims.get('iss') != invitation['iss'] or claims.get('invitation') != invitation['jti'] or \
            claims.get('connection_id') != invitation['attempt'] or \
            claims.get('accept_sha256') != sha256_hex(accept_jws):
        raise ConnectError(WRONG_ATTEMPT, 'exchange is for another attempt', 401)
    try:
        announced = _keys.thumbprint(_keys.public_key_from_jwk(claims.get('connection_key')))
    except ConnectError as e:
        raise ConnectError(KEY_MISMATCH, e.message, 401) from e
    if announced != kid:
        raise ConnectError(KEY_MISMATCH, 'connection_key is not the invitation key', 401)
    app = claims.get('app')
    if not isinstance(app, dict) or app.get('installation_id') != claims['iss']:
        raise ConnectError(INVALID_REQUEST, 'app identity does not match the issuer')
    _require_str(claims, 'jti', _JTI_RE)
    if not isinstance(claims.get('requested_scopes', []), list):
        raise ConnectError(INVALID_REQUEST, 'requested_scopes must be a list')
    code = claims.get('code')
    if not isinstance(code, str) or not hmac.compare_digest(sha256_hex(code), code_sha256 or ''):
        raise ConnectError(INVALID_GRANT, 'unknown authorisation code', 400)
    if now_i >= code_expires_at:
        raise ConnectError(CODE_EXPIRED, 'authorisation code expired', 400)
    verifier = claims.get('code_verifier')
    if not isinstance(verifier, str) or not _VERIFIER_RE.match(verifier):
        raise ConnectError(INVALID_REQUEST, 'code_verifier malformed')
    if not hmac.compare_digest(pkce_challenge(verifier), str(invitation.get('code_challenge'))):
        raise ConnectError(PKCE_MISMATCH, 'code_verifier does not match the challenge', 400)
    _tokens.verify_dpop_proof(dpop, method='POST', url=url, replay=replay, now=now_i, expected_jkt=kid)
    if not replay.add(NS_EXCHANGE, f'{claims["iss"]}:{claims["jti"]}', claims['exp'] + SKEW):
        raise ConnectError(REPLAYED, 'exchange already submitted', 401)
    if not replay.add(NS_CODE, code_sha256, code_expires_at + SKEW):
        raise ConnectError(CODE_USED, 'authorisation code already used', 400)
    return claims


# --- transcript and SAS -----------------------------------------------------------------

def transcript_hash(*, invitation_jws: str, accept_jws: str, exchange_jws: str, initiator_installation: str,
                    initiator_jkt: str, initiator_egress: Sequence[str], responder_installation: str,
                    responder_jkt: str, responder_egress: Sequence[str], destination_host: str,
                    destination_port: int) -> str:
    return sha256_hex(canonical_json({
        'v': f'{PROTOCOL_ID_1_1} qc-transcript',
        'invitation_sha256': sha256_hex(invitation_jws),
        'accept_sha256': sha256_hex(accept_jws),
        'exchange_sha256': sha256_hex(exchange_jws),
        'initiator': {'installation_id': initiator_installation, 'jkt': initiator_jkt,
                      'egress': list(initiator_egress)},
        'responder': {'installation_id': responder_installation, 'jkt': responder_jkt,
                      'egress': list(responder_egress)},
        'destination': {'host': destination_host, 'port': int(destination_port)},
    }))


def transcript_from_messages(invitation_jws: str, accept_jws: str, exchange_jws: str) -> str:
    """The transcript from the three messages as sent. Call only with
    messages this side has already verified."""
    inv, acc = unverified_payload(invitation_jws), unverified_payload(accept_jws)
    ka = _keys.public_key_from_jwk(unverified_header(invitation_jws).get('jwk'))
    kb = _keys.public_key_from_jwk(unverified_header(accept_jws).get('jwk'))
    host, port = origin_host_port(inv['aud'])
    return transcript_hash(invitation_jws=invitation_jws, accept_jws=accept_jws, exchange_jws=exchange_jws,
                           initiator_installation=inv['iss'], initiator_jkt=_keys.thumbprint(ka),
                           initiator_egress=egress_nets(inv['egress']), responder_installation=acc['iss'],
                           responder_jkt=_keys.thumbprint(kb), responder_egress=egress_nets(acc['egress']),
                           destination_host=host, destination_port=port)


def sas(transcript: str) -> str:
    """The v1 SAS function applied to the 1.1 transcript (NNNN-NNNN)."""
    return short_authentication_string(transcript)


def check_ack_key(ack_jwk: dict, accept_jwk: dict) -> None:
    """The v1 ack answering an exchange MUST be signed by K_B, the accept key."""
    if _keys.thumbprint(_keys.public_key_from_jwk(ack_jwk)) != _keys.thumbprint(_keys.public_key_from_jwk(accept_jwk)):
        raise ConnectError(KEY_MISMATCH, 'ack not signed by the acceptance key', 401)


# --- qc-diagnostics/1 ------------------------------------------------------------------

def probe_request_body(nonce: Optional[str] = None) -> dict:
    return {'nonce': nonce} if nonce else {}


def build_probe_response(*, observed_source: str, server_time: int, connection_state: str, source_check: str,
                         token_check: str = 'ok', peer_reached_at: Optional[int] = None,
                         nonce: Optional[str] = None) -> dict:
    out = {'protocol': PROTOCOL_ID_1_1, 'observed_source': str(ipaddress.ip_address(observed_source)),
           'server_time': int(server_time), 'connection_state': connection_state,
           'checks': {'source': source_check, 'token': token_check},
           'peer_reached_at': None if peer_reached_at is None else int(peer_reached_at)}
    if nonce:
        out['nonce'] = nonce
    return validate_probe_response(out, nonce=nonce)


PROBE_SOURCE_CHECKS = ('ok', 'not_authorised', 'not_enforced')


def validate_probe_response(obj, *, nonce: Optional[str] = None) -> dict:
    if not isinstance(obj, dict):
        raise ConnectError(INVALID_REQUEST, 'probe response must be an object')
    src = obj.get('observed_source')
    try:
        if not isinstance(src, str) or not re.match(r'^[0-9A-Fa-f:.]{2,45}$', src):
            raise ValueError(src)
        ip = ipaddress.ip_address(src)
    except (ValueError, TypeError) as e:
        raise ConnectError(INVALID_REQUEST, 'observed_source malformed') from e
    if str(ip) != obj['observed_source']:
        raise ConnectError(INVALID_REQUEST, 'observed_source not canonical')
    st = obj.get('server_time')
    if isinstance(st, bool) or not isinstance(st, int):
        raise ConnectError(INVALID_REQUEST, 'server_time malformed')
    checks = obj.get('checks')
    if not isinstance(checks, dict) or checks.get('source') not in PROBE_SOURCE_CHECKS or \
            checks.get('token') != 'ok':
        raise ConnectError(INVALID_REQUEST, 'checks malformed')
    if not isinstance(obj.get('connection_state'), str):
        raise ConnectError(INVALID_REQUEST, 'connection_state malformed')
    pr = obj.get('peer_reached_at')
    if pr is not None and (isinstance(pr, bool) or not isinstance(pr, int)):
        raise ConnectError(INVALID_REQUEST, 'peer_reached_at malformed')
    if nonce is not None and obj.get('nonce') != nonce:
        raise ConnectError(INVALID_REQUEST, 'probe nonce not echoed')
    return obj
