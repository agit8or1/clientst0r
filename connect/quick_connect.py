"""
Quick Connect: browser-mediated bootstrap (protocol revision 1.1,
``qc-bootstrap/1`` + ``qc-source-binding/1``; PROTOCOL-1.1.md §5–§7,
DESIGN.md §6, increment C2 / roadmap 79.9).

Initiator (A, "we connect to them"):

  1. address        the administrator types the other application's address
  2. network check  DNS + TLS preview (no HTTP request to an unapproved
                    address), approved destination, this installation's
                    egress confirmed; ``start_attempt`` creates the attempt,
                    K_A, the PKCE verifier and the signed invitation
  3. authorise      the browser opens the other application's own admin UI;
                    its administrator signs in THERE (no password ever
                    reaches Clientst0r)
  4. callback       ``handle_callback`` checks ``state`` (session + attempt),
                    verifies the signed accept; the administrator then
                    explicitly approves the other side's declared egress
                    (``confirm_peer``), and only then is its discovery read
                    and the exchange sent (``_exchange``)
  5. compare codes  the SAS from the 1.1 transcript; from here on the v1
                    poll / result / approval flow is unchanged

Responder (B, "they connect to us"):

  ``review_invitation``  verify the invitation (nothing recorded, nothing
                         fetched) for the signed-in administrator
  ``decide``             approve (fresh re-authentication): temporary
                         pairing rule for the initiator's declared egress
                         (15 min, this attempt only), K_B, one-time code
                         (120 s), signed accept -> 303 back; or deny
  ``receive_exchange``   POST /connect/v1/qc/exchange after the source
                         layer admitted it: PKCE, K_A, DPoP, single use, in
                         one transaction with the state change -> v1 ack

Nothing is approved automatically: B's administrator approves the
temporary rule, A's administrator approves B's egress, and both still
approve the connection itself through the v1 flow after comparing the SAS.
After the exchange B keeps only a pairing-status poll rule for A (until the
attempt deadline). Steps 5-8 (permissions and customers, each side's
approval of the other side's addresses, the connection test, commit) are
in connect/activation.py (increment C3): a Quick Connect connection is
active only after its test passed.
A browser's address is never used for any rule. ``reap`` rolls back
attempts past their deadline (temporary rules removed, keys retired,
state failed, policy version bumped).
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from agit8or_connect import discovery as sdk_discovery
from agit8or_connect import pairing as sdk_pairing
from agit8or_connect import quick_connect as qc
from agit8or_connect import tokens as sdk_tokens
from agit8or_connect.canonical import sha256_hex
from agit8or_connect.errors import ConnectError
from agit8or_connect.jws import unverified_header, unverified_payload

from . import audit_log, catalog, identity, store, transport

logger = logging.getLogger('connect')

# What Clientst0r implements of 1.1 in this release (qc-diagnostics/1, the
# probe, comes with the diagnostics increment). Advertised in discovery and
# signed into the invitation and the accept.
OUR_EXTENSIONS = {qc.EXT_BOOTSTRAP: (1,), qc.EXT_SOURCE_BINDING: (1,)}
ATTEMPT_TTL = timedelta(minutes=30)
SESSION_KEY = 'connect_qc_attempts'
REVIEW_LIMIT_USER = 10        # invitation reviews per administrator per hour (DESIGN §6.4 item 8)
REVIEW_LIMIT_INSTALLATION = 30
MAX_SCOPES = 32
_SCOPE_RE = re.compile(r'^[a-z0-9][a-z0-9_.:-]{0,63}$')

FRIENDLY = {
    'not_configured': 'Quick Connect is not available.',
    'qc_disabled': 'Quick Connect is turned off on this installation (Connected Applications → Network).',
    'invalid_egress': 'This installation\'s egress address is not set or not valid. Set it under Connected '
                      'Applications → Network first: the address this server\'s requests come from, as other '
                      'applications see it.',
    'egress_unconfirmed': 'Confirm this installation\'s egress address before continuing.',
    'state_mismatch': 'This answer does not belong to a Quick Connect attempt you started in this browser '
                      'session. Nothing was changed.',
    'callback_used': 'This answer was already processed. Start Quick Connect again if the attempt failed.',
    'access_denied': 'The other application\'s administrator denied the request.',
    'invitation_expired': 'The request expired (requests are valid for 10 minutes). Ask the other administrator '
                          'to start Quick Connect again.',
    'invitation_used': 'This request was already used. Ask the other administrator to start Quick Connect '
                       'again.',
    'wrong_audience': 'This request was made for another application, not this one.',
    'invalid_signature': 'A signature did not verify. Do not continue: the request may have been altered.',
    'invalid_base': 'The requesting application\'s address is not acceptable (it must be a public https '
                    'address; loopback, link-local and metadata addresses are never accepted).',
    'invalid_redirect_uri': 'The address to return to is not on the requesting application\'s own address.',
    'expired': 'The answer from the other application expired. Start Quick Connect again.',
    'wrong_attempt': 'The answer belongs to another attempt. Start Quick Connect again.',
    'invalid_grant': 'The answer and its one-time code do not belong together. Start Quick Connect again.',
    'destination_mismatch': 'The application that answered is not at the address you approved.',
    'identity_mismatch': 'The other application\'s discovery document names a different installation than its '
                         'signed answer. Do not continue.',
    'downgrade_detected': 'The other application\'s discovery document offers less than it signed. Do not '
                          'continue: something between the two applications may be altering it.',
    'key_mismatch': 'The other application answered with a different key than it signed with.',
    'code_expired': 'The one-time code expired (2 minutes) before the exchange. Start Quick Connect again.',
    'code_used': 'The one-time code was already used.',
    'pkce_mismatch': 'The exchange did not prove it came from the attempt that was started.',
    'source_not_authorised': 'The other application refused this server\'s address. Check this installation\'s '
                             'egress address, and that the other administrator approved it.',
    'duplicate': 'This Clientst0r already has a connection to that installation (connected, waiting, or '
                 'Security Blocked). Resolve or disconnect it first.',
    'attempt_expired': 'The Quick Connect attempt expired (30 minutes). Nothing stays reachable; start again.',
    'reauth_required': 'Confirm your password first (approving gives the other application temporary access).',
    'rate_limited': 'Too many Quick Connect requests were reviewed in the last hour. Try again later.',
    'kill_switch': 'Connected applications are stopped by the emergency kill switch.',
    'self': 'That address is this Clientst0r installation itself.',
    'cancelled': 'Cancelled by an administrator.',
    'identity_changed': 'The connection test reached a different installation at the other application\'s address '
                        'than the one that paired. Nothing was activated and everything this pairing allowed was '
                        'removed. Pair again once you know why.',
}


class QuickConnectError(Exception):
    """Shown to the administrator: a protocol error code plus plain language."""

    def __init__(self, code, message=''):
        super().__init__(message or FRIENDLY.get(code, code))
        self.code = code
        self.message = message or FRIENDLY.get(code) or code.replace('_', ' ')


def _from(e: ConnectError) -> QuickConnectError:
    return QuickConnectError(e.code, FRIENDLY.get(e.code) or e.message)


# --- availability and this installation's settings ------------------------------------

def enabled_here() -> bool:
    if not identity.enabled():
        return False
    from .models import InstallationIdentity
    return InstallationIdentity.objects.filter(pk=identity.get().pk, qc_enabled=True).exists()


CANONICAL_BASE_MESSAGE = ('Quick Connect needs AGIT8OR_CONNECT_PUBLIC_URL in canonical form: https, lower case, no '
                          'path, no trailing slash, and no ":443" (for example https://psa.example.com). Other '
                          'applications compare it byte for byte.')


def public_base_problem() -> str:
    """'' when AGIT8OR_CONNECT_PUBLIC_URL is usable as a 1.1 ``base``
    (PROTOCOL-1.1.md §4.3): the verifier applies no normalisation."""
    problem = identity.public_url_problem()
    if problem:
        return problem
    raw = str(getattr(settings, 'AGIT8OR_CONNECT_PUBLIC_URL', '') or '').strip()
    try:
        _, port, path = qc.parse_https_url(raw)
        qc.check_base(raw, allowed_ports=(port,))
    except ConnectError:
        return CANONICAL_BASE_MESSAGE
    return CANONICAL_BASE_MESSAGE if path else ''


def public_base() -> str:
    problem = public_base_problem()
    if problem:
        raise QuickConnectError('not_configured', problem)
    return str(settings.AGIT8OR_CONNECT_PUBLIC_URL).strip()


def available() -> bool:
    return enabled_here() and not public_base_problem()


def require_available():
    if not enabled_here():
        raise QuickConnectError('qc_disabled')
    public_base()


def extend_document(doc: dict) -> dict:
    return qc.extend_discovery_document(doc, public_base(), extensions=OUR_EXTENSIONS)


def callback_url() -> str:
    return public_base() + reverse('connect:qc_callback')


def exchange_url() -> str:
    return public_base() + qc.EXCHANGE_PATH


def own_egress() -> List[dict]:
    """This installation's declared egress ({net, note}), canonical."""
    try:
        return qc.validate_egress(list(identity.get().egress_addresses or []))
    except ConnectError as e:
        raise QuickConnectError('invalid_egress') from e


def parse_egress_text(text: str) -> List[dict]:
    """Administrator input (one address or network per line or comma
    separated) -> canonical egress entries. Never a browser address."""
    items = [x.strip() for x in str(text or '').replace(',', '\n').splitlines() if x.strip()]
    if not items:
        return []
    try:
        return qc.egress_entries(items)
    except ConnectError as e:
        raise ValidationError(f'Egress address: {e.message}. Give exact public addresses (or a range of at most '
                              '/16 for IPv4, /32 for IPv6); loopback, link-local and metadata addresses are refused.'
                              ) from e


def set_own_egress(entries: List[dict], user):
    from .models import InstallationIdentity
    from . import source_policy
    ident = identity.get()
    before = [e.get('net') for e in ident.egress_addresses or []]
    InstallationIdentity.objects.filter(pk=ident.pk).update(egress_addresses=entries)
    after = [e['net'] for e in entries]
    audit_log.record('qc.egress_set', 'ok', user=user, detail={'before': before, 'after': after})
    source_policy._audit_admin(user, 'Agit8or Connect egress address set', {'before': before, 'after': after})


def set_enabled(on: bool, user):
    from .models import InstallationIdentity
    from . import source_policy
    InstallationIdentity.objects.filter(pk=identity.get().pk).update(qc_enabled=bool(on))
    audit_log.record('qc.enabled' if on else 'qc.disabled', 'ok', user=user)
    source_policy._audit_admin(user, f'Agit8or Connect Quick Connect turned {"on" if on else "off"}', {})


def _refuse_if_stopped():
    if identity.kill_switch_engaged():
        raise QuickConnectError('kill_switch')


def _pre_active():
    from .models import Connection
    return (Connection.PENDING_PAIRING, Connection.AWAITING_REMOTE, Connection.AWAITING_LOCAL,
            Connection.AWAITING_SECOND, Connection.AWAITING_NETWORK, Connection.TESTING)


def _existing(installation_id, exclude=None):
    """Other connections to that installation that block a new one."""
    from .models import Connection
    qs = Connection.objects.filter(remote_installation_id=installation_id, state__in=(
        Connection.ACTIVE, Connection.SUSPENDED, Connection.SECURITY_BLOCKED, Connection.AWAITING_REMOTE,
        Connection.AWAITING_LOCAL, Connection.AWAITING_SECOND, Connection.AWAITING_NETWORK, Connection.TESTING))
    return qs.exclude(pk=exclude.pk) if exclude is not None else qs


# --- initiator (A) ---------------------------------------------------------------------

def normalize_destination(text: str) -> str:
    """What the administrator typed -> canonical origin https://host[:port]."""
    raw = str(text or '').strip()
    if not raw:
        raise QuickConnectError('invalid_base', 'Enter the other application\'s https address.')
    if '://' not in raw:
        raw = 'https://' + raw
    try:
        p = urlsplit(raw)
        port = p.port or 443
        host = (p.hostname or '').rstrip('.')
    except ValueError as e:
        raise QuickConnectError('invalid_base', 'That is not a valid address.') from e
    if p.scheme.lower() != 'https' or not host or p.username or p.password or p.query or p.fragment or \
            p.path not in ('', '/'):
        raise QuickConnectError('invalid_base', 'Enter an https address with a host name or IP address only '
                                                '(no path), such as https://rem0te.example.com.')
    try:
        ip = ipaddress.ip_address(host)
        host = f'[{ip.compressed}]' if ip.version == 6 else ip.compressed
    except ValueError:
        host = host.lower()
    origin = f'https://{host}' + (f':{port}' if port != 443 else '')
    try:
        qc.check_base(origin, allowed_ports=(port,))
    except ConnectError as e:
        raise QuickConnectError('invalid_base') from e
    return origin


@dataclass
class PeerCheck:
    origin: str
    preview: object
    info: object = None            # DiscoveryInfo when the peer's discovery was readable
    flow: str = qc.BOOTSTRAP_ID    # or 'code' (v1 code flow)
    authorize_endpoint: str = ''
    negotiated: dict = field(default_factory=dict)


def check_peer(origin: str, *, allow_private=False, ca_pem='') -> PeerCheck:
    """Screen 2: DNS + TLS preview, then (pinned to the previewed addresses)
    an attempt to read the peer's discovery. A default-deny responder does
    not answer it yet, which is normal: the conventional entry point
    ``/agit8or-connect/qc-authorize`` is used. A readable document that
    does not offer qc-bootstrap/1 means: use the v1 code flow."""
    from . import pairing
    try:
        pv = pairing.preview_destination(origin, allow_private=allow_private, ca_pem=ca_pem)
    except pairing.PairingFailed as e:
        raise QuickConnectError(e.code or 'blocked_destination', e.message) from e
    out = PeerCheck(origin=origin, preview=pv, authorize_endpoint=origin + qc.AUTHORIZE_ENTRY_PATH)
    try:
        info = pairing.discover(origin, allow_private=allow_private, ca_pem=ca_pem, addresses=pv.addresses)
    except pairing.PairingFailed as e:
        if e.code == 'self':
            raise QuickConnectError('self') from e
        return out
    out.info = info
    out.negotiated = qc.negotiate_extensions(qc.advertised_extensions(info.raw, info.url))
    out.flow = qc.pairing_flow(out.negotiated)
    if out.flow == qc.BOOTSTRAP_ID:
        out.authorize_endpoint = info.raw['endpoints']['qc_authorize']
    return out


def _scopes(values) -> List[str]:
    if isinstance(values, str):
        values = values.replace(',', ' ').split()
    out = sorted({str(v).strip() for v in values or [] if str(v).strip()})
    bad = [s for s in out if not _SCOPE_RE.match(s)]
    if bad or not out or len(out) > MAX_SCOPES:
        raise QuickConnectError('invalid_scope', 'Enter the permissions to ask for as names such as '
                                                 'customers:read (at least one, at most 32).')
    return out


def start_attempt(check: PeerCheck, *, user, request, requested_scopes, organizations=(),
                  destination_addresses='', allow_private=False, ca_pem='', spki_pin='',
                  egress_confirmed=False):
    """Create the attempt (pending_pairing), K_A, PKCE verifier, state and
    the signed invitation. Returns the connection. The plain ``state`` is
    kept only in the administrator's session."""
    from .models import Connection, QuickConnectInvitation
    from . import destinations, pairing
    _refuse_if_stopped()
    require_available()
    if check.flow != qc.BOOTSTRAP_ID:
        raise QuickConnectError('extension_not_negotiated', 'The other application does not offer Quick Connect. '
                                                            'Use a pairing code instead.')
    egress = own_egress()
    if not egress_confirmed:
        raise QuickConnectError('egress_unconfirmed')
    scopes = _scopes(requested_scopes)
    try:
        dest_entries = destinations.entries_for(destination_addresses, private=allow_private, user=user)
    except ValidationError as e:
        raise QuickConnectError('invalid_destination', ' '.join(e.messages)) from e
    info = check.info
    if info is not None and _existing(info.installation_id).exists():
        raise QuickConnectError('duplicate')
    orgs = list(organizations)
    verifier, state, nonce = qc.generate_pkce_verifier(), qc.generate_state(), qc.generate_nonce()
    with transaction.atomic():
        conn = Connection.objects.create(
            direction=Connection.OUTBOUND, state=Connection.PENDING_PAIRING, qc_revision=qc.REVISION,
            qc_attempt_expires_at=timezone.now() + ATTEMPT_TTL,
            remote_app_type=(info.app_type[:64] if info else 'unknown'),
            remote_installation_id=(info.installation_id if info else ''),
            remote_display_name=(info.display_name if info else ''),
            remote_app_version=(info.app_version if info else ''),
            base_url=check.origin + sdk_discovery.WELL_KNOWN,
            remote_endpoints=(info.endpoints if info else {}), remote_catalog=(info.catalog.as_list() if info else []),
            requested_outbound_scopes=scopes, allow_private_network=bool(allow_private), tls_ca_bundle=ca_pem or '',
            proposed_tenants=[pairing.org_tenant(o) for o in orgs], created_by=user)
        destinations.stage(conn, dest_entries, user, ca_pem=ca_pem, spki_pins=[spki_pin] if spki_pin else None)
        _, priv = store.new_key(conn)
        jws, claims = qc.build_invitation(
            priv, initiator_app=identity.app_info(), responder_origin=check.origin, attempt=str(conn.pk),
            base=public_base(), redirect_uri=callback_url(), egress=egress, requested_scopes=scopes,
            code_challenge=qc.pkce_challenge(verifier), nonce=nonce,
            responder_installation=info.installation_id if info else None, extensions=OUR_EXTENSIONS)
        if len(jws) > qc.MAX_INVITATION_LENGTH:
            raise QuickConnectError('too_large', 'The request is too large for a browser address. Offer fewer '
                                                 'permissions or egress addresses.')
        inv = QuickConnectInvitation(
            connection=conn, jti=claims['jti'], invitation_jws=jws, state_hash=sha256_hex(state),
            nonce_hash=sha256_hex(nonce), code_challenge=claims['code_challenge'], responder_origin=claims['aud'],
            authorize_url=check.authorize_endpoint, redirect_uri=claims['redirect_uri'], egress=claims['egress'],
            requested_scopes=scopes, expires_at=timezone.now() + timedelta(seconds=qc.INVITATION_MAX_LIFETIME),
            created_by=user)
        inv.set_verifier(verifier)
        inv.save()
    bound = dict(request.session.get(SESSION_KEY) or {})
    bound[str(conn.pk)] = state
    request.session[SESSION_KEY] = bound
    audit_log.record('qc.attempt_started', 'ok', connection=conn, user=user,
                     app=conn.remote_installation_id, scopes=scopes,
                     detail={'destination': check.origin, 'egress': qc.egress_nets(egress),
                             'authorize_endpoint': check.authorize_endpoint,
                             'discovery_readable': info is not None, 'tenants_proposed': len(orgs)})
    return conn


def authorization_url(request, conn) -> str:
    """Screen 3's link to the other application's own admin UI. Built from
    the session-bound state (never stored server-side in plain text)."""
    inv = conn.qc_invitation
    state = (request.session.get(SESSION_KEY) or {}).get(str(conn.pk), '')
    if not state or not hmac.compare_digest(sha256_hex(state), inv.state_hash):
        return ''
    return qc.authorization_url(inv.authorize_url, inv.invitation_jws, state)


def handle_callback(request):
    """Browser leg 2 at A (GET, the administrator's own session). Processed
    at most once per attempt. Returns the connection; the exchange waits for
    the administrator to approve the other side's egress (``confirm_peer``)."""
    from .models import Connection, QuickConnectInvitation
    raw = request.META.get('QUERY_STRING', '')
    try:
        params = qc.parse_query(raw)
    except ConnectError:
        params = {}
    state = params.get('state', '')
    inv = QuickConnectInvitation.objects.select_related('connection').filter(
        state_hash=sha256_hex(state)).first() if state else None
    bound = (request.session.get(SESSION_KEY) or {}).get(str(inv.connection_id), '') if inv else ''
    if inv is None or not bound or not hmac.compare_digest(bound, state) or \
            inv.created_by_id != getattr(request.user, 'pk', None):
        audit_log.record('qc.callback_refused', 'state_mismatch', user=request.user,
                         connection=inv.connection if inv else None)
        raise QuickConnectError('state_mismatch')
    conn = inv.connection
    with transaction.atomic():
        locked = QuickConnectInvitation.objects.select_for_update().get(pk=inv.pk)
        if locked.callback_at or locked.burned_at or conn.state != Connection.PENDING_PAIRING:
            raise QuickConnectError('callback_used')
        locked.callback_at = timezone.now()
        locked.save(update_fields=['callback_at'])
    inv.refresh_from_db()
    if conn.qc_attempt_expires_at and conn.qc_attempt_expires_at <= timezone.now():
        rollback_attempt(conn, 'attempt_expired', request.user)
        raise QuickConnectError('attempt_expired')
    try:
        resp = qc.parse_authorization_response(raw, expected_state=state)
        accept, bjwk = qc.verify_accept(resp['accept'], invitation=unverified_payload(inv.invitation_jws),
                                        invitation_jws=inv.invitation_jws, code=resp['code'])
        if conn.remote_installation_id and conn.remote_installation_id != accept['iss']:
            raise ConnectError('identity_mismatch', 'answer from another installation', 403)
    except ConnectError as e:
        rollback_attempt(conn, e.code, request.user)
        audit_log.record('qc.callback_refused', e.code, connection=conn, user=request.user)
        raise _from(e) from e
    if _existing(accept['iss'], exclude=conn).exists():
        rollback_attempt(conn, 'duplicate', request.user)
        raise QuickConnectError('duplicate')
    app = accept.get('app') or {}
    with transaction.atomic():
        inv.accept_jws = resp['accept']
        inv.set_code(resp['code'])
        inv.peer_egress = accept['egress']
        inv.save(update_fields=['accept_jws', 'pending_code', 'peer_egress'])
        conn.remote_installation_id = accept['iss']
        conn.remote_app_type = str(app.get('type') or conn.remote_app_type)[:64]
        conn.remote_display_name = str(app.get('display_name') or '')[:200]
        conn.remote_app_version = str(app.get('version') or '')[:64]
        conn.remote_connection_id = accept['connection_id']
        conn.remote_jwks = {'keys': [bjwk]}
        conn.save()
        from .models import ApprovedDestination
        ApprovedDestination.objects.filter(connection=conn).update(expected_installation_id=accept['iss'])
    audit_log.record('qc.callback_accepted', 'ok', connection=conn, user=request.user, app=accept['iss'],
                     detail={'peer_egress': qc.egress_nets(accept['egress']), 'peer_base': accept['base']})
    return conn


def peer_egress_rows(conn) -> List[dict]:
    from . import source_policy
    out = []
    for e in getattr(getattr(conn, 'qc_invitation', None), 'peer_egress', None) or []:
        out.append({'net': e['net'], 'note': e.get('note', ''), 'private': qc.is_private_net(e['net']),
                    'installation_ok': source_policy.installation_allows(e['net'])})
    return out


def confirm_peer(conn, user, *, private_ok=False):
    """Screen 4 (POST): the administrator approves the other side's declared
    egress as this attempt's temporary pairing rule (it may read our
    discovery and poll), then the exchange runs. Explicit; never inferred."""
    from .models import Connection
    from . import source_policy
    _refuse_if_stopped()
    inv = conn.qc_invitation
    if conn.state != Connection.PENDING_PAIRING or not inv.callback_at or inv.exchanged_at or inv.burned_at:
        raise QuickConnectError('callback_used', 'This attempt is not waiting for this step.')
    if conn.qc_attempt_expires_at and conn.qc_attempt_expires_at <= timezone.now():
        rollback_attempt(conn, 'attempt_expired', user)
        raise QuickConnectError('attempt_expired')
    nets = []
    try:
        for e in inv.peer_egress:
            net, _ = source_policy.validate_entry(e['net'], private=private_ok)
            nets.append(net)
    except ValidationError as e:
        raise QuickConnectError('invalid_egress', ' '.join(e.messages)) from e
    source_policy.pairing_rules_for_connection(conn, nets, user, expires_at=conn.qc_attempt_expires_at,
                                               private=private_ok)
    return _exchange(conn, inv, user)


def _exchange(conn, inv, user):
    from .models import Connection
    accept_jws = inv.accept_jws
    accept = unverified_payload(accept_jws)          # verified at the callback
    accept_jwk = unverified_header(accept_jws)['jwk']
    claims_inv = unverified_payload(inv.invitation_jws)
    try:
        t = transport.for_connection(conn)
        info = sdk_discovery.fetch(t, accept['base'])
        negotiated = qc.check_discovered_identity(accept, info.raw, info.url)
        _, priv = store.active_key(conn)
        exch, eclaims = qc.build_exchange(
            priv, invitation=claims_inv, accept=accept, accept_jws=accept_jws, code=inv.code(),
            code_verifier=inv.verifier(), initiator_app=identity.app_info(),
            discovery_url=public_base() + sdk_discovery.WELL_KNOWN, requested_scopes=inv.requested_scopes,
            proposed_tenants=conn.proposed_tenants)
        ep = info.raw['endpoints']['qc_exchange']
        r = t.request('POST', ep, headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                           'DPoP': sdk_tokens.build_dpop_proof(priv, 'POST', ep)},
                      body=json.dumps({'exchange': exch}).encode())
        try:
            data = json.loads(r.body or b'{}')
        except ValueError:
            data = {}
        if r.status != 202:
            err = data.get('error') if isinstance(data, dict) else None
            code = (str(err.get('code') or '') if isinstance(err, dict) else '')[:40] or f'http_{r.status}'
            raise ConnectError(code, f'exchange answered HTTP {r.status}', r.status)
        ack, ack_jwk = sdk_pairing.verify_ack(data.get('ack', ''), initiator_installation=identity.installation_id(),
                                              responder_installation=accept['iss'], request_jti=eclaims['jti'])
        qc.check_ack_key(ack_jwk, accept_jwk)
        if ack.get('connection_id') != accept['connection_id']:
            raise ConnectError('wrong_attempt', 'ack for another connection', 401)
    except ConnectError as e:
        rollback_attempt(conn, e.code, user)
        audit_log.record('qc.exchange_sent', e.code, connection=conn, user=user, app=conn.remote_installation_id)
        raise _from(e) from e
    with transaction.atomic():
        conn.remote_endpoints = info.endpoints
        conn.remote_catalog = info.catalog.as_list()
        conn.remote_protocol_version = info.version
        conn.remote_app_type = info.app_type[:64]
        conn.remote_display_name = info.display_name or conn.remote_display_name
        conn.remote_app_version = info.app_version or conn.remote_app_version
        conn.pairing_request_id = str(data.get('request_id') or ack['request_id'])[:128]
        conn.pairing_request_jti, conn.pairing_request_jws = eclaims['jti'], exch
        conn.sas = qc.sas(qc.transcript_from_messages(inv.invitation_jws, accept_jws, exch))
        conn.state = Connection.AWAITING_REMOTE
        conn.last_success_at = timezone.now()
        conn.save()
        inv.exchanged_at = timezone.now()
        inv.pending_code, inv.code_verifier = '', ''      # single use: wiped
        inv.save(update_fields=['exchanged_at', 'pending_code', 'code_verifier'])
    audit_log.record('qc.exchange_sent', 'ok', connection=conn, user=user, app=conn.remote_installation_id,
                     scopes=inv.requested_scopes, detail={'sas_shown': True, 'negotiated': sorted(negotiated)})
    return conn


def cancel(conn, user):
    if not rollback_attempt(conn, 'cancelled', user):
        raise QuickConnectError('callback_used', 'This attempt can no longer be cancelled here.')


# --- responder (B) ---------------------------------------------------------------------

class _PeekReplay:
    """Answers 'already used?' without recording anything: the review page
    (GET) must not consume the invitation; the decision does."""

    def add(self, namespace, key, expires_at) -> bool:
        from .models import ReplayRecord
        return not ReplayRecord.objects.filter(namespace=namespace, key=key[:255],
                                               expires_at__gt=timezone.now()).exists()


def _responder_origin():
    return qc.origin_of(public_base())


def _reviews_in_last_hour(user=None) -> int:
    import time
    from .models import ConnectAuditEvent
    qs = ConnectAuditEvent.objects.filter(operation='qc.invitation_reviewed',
                                          ts_us__gte=int((time.time() - 3600) * 1_000_000))
    if user is not None:
        qs = qs.filter(actor=audit_log.actor_for(user))
    return qs.count()


@dataclass
class Review:
    claims: dict
    jwk: dict
    invitation: str
    state: str
    egress: list
    known_scopes: list
    unknown_scopes: list
    duplicates: list
    needs_private: bool


def review_invitation(request, invitation: str, state: str) -> Review:
    """Verify (PROTOCOL-1.1.md §5.3 steps 1–10, and 'already used') for the
    signed-in administrator. Records nothing single-use and fetches nothing."""
    from . import source_policy
    require_available()
    if _reviews_in_last_hour(request.user) >= REVIEW_LIMIT_USER or \
            _reviews_in_last_hour() >= REVIEW_LIMIT_INSTALLATION:
        raise QuickConnectError('rate_limited')
    try:
        qc._check_state(state)
        claims, jwk = qc.verify_invitation(invitation, responder_origin=_responder_origin(), replay=_PeekReplay(),
                                           responder_installation=identity.installation_id())
    except ConnectError as e:
        audit_log.record('qc.invitation_refused', e.code, user=request.user)
        raise _from(e) from e
    audit_log.record('qc.invitation_reviewed', 'ok', user=request.user, app=claims['iss'],
                     scopes=claims.get('requested_scopes') or [],
                     detail={'initiator_base': claims['base'], 'egress': qc.egress_nets(claims['egress']),
                             'attempt': claims['attempt']})
    egress = [{'net': e['net'], 'note': e.get('note', ''), 'private': qc.is_private_net(e['net']),
               'installation_ok': source_policy.installation_allows(e['net'])} for e in claims['egress']]
    asked = [s for s in claims.get('requested_scopes') or [] if isinstance(s, str)]
    return Review(claims=claims, jwk=jwk, invitation=invitation, state=state, egress=egress,
                  known_scopes=[s for s in asked if catalog.CATALOG.get(s)],
                  unknown_scopes=[s for s in asked if not catalog.CATALOG.get(s)],
                  duplicates=list(_existing(claims['iss'])), needs_private=any(e['private'] for e in egress))


def decide(request, invitation: str, state: str, *, approve: bool, private_ok=False) -> str:
    """The administrator's decision. Returns the URL to redirect the browser
    to (303). Approve needs a fresh re-authentication; it creates the
    attempt, K_B, the temporary pairing rule for the initiator's declared
    egress, the one-time code and the signed accept, all in one transaction
    with the invitation's single-use record."""
    from tech_access.protected import has_fresh_auth
    from .models import Connection, QuickConnectGrant
    from . import source_policy
    user = request.user
    require_available()
    if approve:
        _refuse_if_stopped()
        if not has_fresh_auth(request):
            raise QuickConnectError('reauth_required')
        egress_b = own_egress()
    try:
        qc._check_state(state)
        with transaction.atomic():
            claims, jwk = qc.verify_invitation(invitation, responder_origin=_responder_origin(),
                                               replay=store.replay_store,
                                               responder_installation=identity.installation_id())
            if not approve:
                url = qc.authorization_response_url(claims['redirect_uri'], state=state, error='access_denied')
            else:
                nets = []
                try:
                    for e in claims['egress']:
                        net, _ = source_policy.validate_entry(e['net'], private=private_ok)
                        nets.append(net)
                except ValidationError as ve:
                    raise QuickConnectError('invalid_egress', ' '.join(ve.messages)) from ve
                app = claims['app']
                now = timezone.now()
                conn = Connection.objects.create(
                    direction=Connection.INBOUND, state=Connection.PENDING_PAIRING, qc_revision=qc.REVISION,
                    qc_attempt_expires_at=now + ATTEMPT_TTL,
                    remote_app_type=str(app.get('type') or '')[:64] or 'unknown',
                    remote_installation_id=claims['iss'], remote_display_name=str(app.get('display_name') or '')[:200],
                    remote_app_version=str(app.get('version') or '')[:64],
                    base_url=claims['base'] + sdk_discovery.WELL_KNOWN, remote_connection_id=claims['attempt'],
                    remote_jwks={'keys': [jwk]},
                    peer_requested_scopes=sorted({s for s in claims.get('requested_scopes') or []
                                                  if isinstance(s, str)})[:64],
                    created_by=user)
                _, priv = store.new_key(conn)
                code = qc.generate_code()
                accept = qc.build_accept(priv, responder_app=identity.app_info(), invitation=claims,
                                         invitation_jws=invitation, connection_id=str(conn.pk), base=public_base(),
                                         egress=egress_b, code=code, extensions=OUR_EXTENSIONS)
                rule_expires = now + timedelta(seconds=qc.TEMPORARY_RULE_TTL)
                QuickConnectGrant.objects.create(
                    connection=conn, code_hash=sha256_hex(code), code_expires_at=now + timedelta(seconds=qc.CODE_TTL),
                    invitation_jti=claims['jti'], invitation_iss=claims['iss'], invitation_jws=invitation,
                    initiator_jwk=jwk, accept_jws=accept, egress=claims['egress'], rule_expires_at=rule_expires,
                    created_by=user)
                source_policy.pairing_rules_for_connection(conn, nets, user, expires_at=rule_expires,
                                                           private=private_ok)
                url = qc.authorization_response_url(claims['redirect_uri'], state=state, code=code, accept=accept)
    except ConnectError as e:
        audit_log.record('qc.invitation_refused', e.code, user=user)
        raise _from(e) from e
    if not approve:
        audit_log.record('qc.invitation_denied', 'denied', user=user, app=claims['iss'],
                         detail={'attempt': claims['attempt']})
        return url
    audit_log.record('qc.invitation_approved', 'ok', connection=conn, user=user, app=claims['iss'],
                     scopes=conn.peer_requested_scopes,
                     detail={'temporary_sources': nets, 'expires': rule_expires.isoformat(),
                             'initiator_base': claims['base']})
    source_policy._audit_admin(user, f'Agit8or Connect Quick Connect: temporary pairing access approved for '
                                     f'{", ".join(nets)}', {'connection': str(conn.pk), 'sources': nets})
    return url


def note_refused_source(connection_id, ip):
    """The source layer refused an exchange naming a live grant (the request
    knew the one-time code): shown to the administrator as observed vs
    approved. Adds nothing."""
    from django.core.cache import cache
    from .models import QuickConnectGrant
    n = QuickConnectGrant.objects.filter(connection_id=connection_id, used_at=None).update(
        refused_source=str(ip), refused_at=timezone.now())
    if n and cache.add(f'connect:qc-refused:{connection_id}', 1, 60):
        audit_log.record('qc.exchange_refused', 'source_not_authorised', connection=str(connection_id),
                         detail={'source_ip': str(ip)})


def named_attempt(token) -> Optional[str]:
    """Source layer, before authentication: the attempt an exchange names
    through its code (looked up by hash; never trusted on its own)."""
    from .models import QuickConnectGrant
    h = qc.exchange_code_sha256(token) if isinstance(token, str) else ''
    if not h:
        return None
    cid = QuickConnectGrant.objects.filter(code_hash=h).values_list('connection_id', flat=True).first()
    return str(cid) if cid else None


def receive_exchange(request, token: str, dpop: str) -> dict:
    """POST qc_exchange, after the source layer admitted it from this
    attempt's temporary rule (PROTOCOL-1.1.md §5.6). Single-use values and
    the state change are written in one transaction; any failure rolls all
    of them back."""
    from .models import Connection, PairingRequest, QuickConnectGrant, SourceRule
    from . import ratelimit, source_policy
    cid = named_attempt(token)
    grant = QuickConnectGrant.objects.select_related('connection').filter(connection_id=cid).first() if cid else None
    if grant is None:
        raise ConnectError('source_not_authorised', source_policy.PUBLIC_MESSAGE, 403)
    conn = grant.connection
    source_policy.bind(request, conn)
    ip = ratelimit.client_ip(request)
    try:
        with transaction.atomic():
            g = QuickConnectGrant.objects.select_for_update().get(pk=grant.pk)
            claims = qc.verify_exchange(
                token, dpop=dpop, url=exchange_url(), invitation=unverified_payload(g.invitation_jws),
                invitation_jwk=g.initiator_jwk, accept_jws=g.accept_jws, code_sha256=g.code_hash,
                code_expires_at=int(g.code_expires_at.timestamp()),
                responder_installation=identity.installation_id(), replay=store.replay_store)
            conn = Connection.objects.select_for_update().get(pk=conn.pk)
            if g.used_at or conn.state != Connection.PENDING_PAIRING:
                raise ConnectError('code_used', 'authorisation code already used', 400)
            disc = claims.get('discovery_url')
            inv_base = unverified_payload(g.invitation_jws)['base']
            if not isinstance(disc, str) or sdk_discovery.origin(sdk_discovery.discovery_url(disc)) != \
                    sdk_discovery.origin(inv_base):
                raise ConnectError('invalid_request', 'discovery_url is not on the initiator\'s base', 400)
            app = claims['app']
            conn.remote_app_type = str(app.get('type') or conn.remote_app_type)[:64]
            conn.remote_display_name = str(app.get('display_name') or conn.remote_display_name)[:200]
            conn.remote_app_version = str(app.get('version') or '')[:64]
            conn.base_url = sdk_discovery.discovery_url(disc)[:500]
            conn.peer_requested_scopes = sorted({s for s in claims.get('requested_scopes') or []
                                                 if isinstance(s, str)})[:64]
            conn.proposed_tenants = sdk_pairing.tenant_list(claims.get('proposed_tenants'))[:200]
            conn.pairing_request_jti, conn.pairing_request_jws = claims['jti'], token
            conn.sas = qc.sas(qc.transcript_from_messages(g.invitation_jws, g.accept_jws, token))
            conn.state = Connection.AWAITING_LOCAL
            conn.save()
            preq = PairingRequest.objects.create(invitation=None, connection=conn, initiator_jwk=g.initiator_jwk,
                                                 source_ip=ip if ip != 'unknown' else None,
                                                 expires_at=conn.qc_attempt_expires_at or
                                                 timezone.now() + ATTEMPT_TTL)
            conn.pairing_request_id = str(preq.pk)
            conn.save(update_fields=['pairing_request_id'])
            g.used_at, g.observed_source = timezone.now(), (ip if ip != 'unknown' else None)
            g.save(update_fields=['used_at', 'observed_source'])
            SourceRule.objects.filter(connection=conn, status=SourceRule.TEMPORARY, observed_first_at=None).update(
                observed_first_at=timezone.now())
            # The 15-minute pairing rule would expire before a later approval
            # could be polled: keep only the status poll, until the deadline.
            source_policy.narrow_to_poll(conn, conn.qc_attempt_expires_at)
            _, priv = store.active_key(conn)
            ack = sdk_pairing.build_ack(priv, responder_app=identity.app_info(), initiator_installation=claims['iss'],
                                        request_id=str(preq.pk), request_jti=claims['jti'],
                                        connection_id=str(conn.pk))
    except ConnectError as e:
        audit_log.record('qc.exchange_refused', e.code, connection=conn, app=conn.remote_installation_id,
                         detail={'source_ip': ip})
        raise
    audit_log.record('qc.exchange_accepted', 'pending', connection=conn, app=conn.remote_installation_id,
                     scopes=conn.peer_requested_scopes, detail={'source_ip': ip, 'sas_shown': True})
    return {'status': 'pending_approval', 'request_id': str(preq.pk), 'ack': ack}


# --- rollback and reaper ---------------------------------------------------------------

def rollback_attempt(conn, reason='', user=None) -> bool:
    """Before both administrators approved: remove every rule of the attempt,
    drop its staged destination, retire its keys (private halves wiped),
    state failed, policy version bumped. One transaction; only ever removes
    access (DESIGN.md §6.5)."""
    from .models import (ApprovedDestination, Connection, PairingRequest, QuickConnectInvitation,
                         SourceRule)
    from . import client, lifecycle, source_policy
    with transaction.atomic():
        conn = Connection.objects.select_for_update().get(pk=conn.pk)
        if conn.state not in _pre_active():
            return False
        now = timezone.now()
        n = SourceRule.objects.filter(connection=conn, status__in=(SourceRule.STAGED, SourceRule.TEMPORARY,
                                                                   SourceRule.ACTIVE)).update(
            status=SourceRule.REMOVED, removed_at=now)
        ApprovedDestination.objects.filter(connection=conn, status=ApprovedDestination.STAGED).delete()
        lifecycle.retire_keys(conn)
        conn.state = Connection.FAILED
        conn.last_error = FRIENDLY.get(reason, f'Quick Connect failed ({reason}).')[:500]
        conn.last_failure_at = now
        conn.save()
        QuickConnectInvitation.objects.filter(connection=conn).update(burned_at=now, error=str(reason)[:40],
                                                                      pending_code='', code_verifier='')
        PairingRequest.objects.filter(connection=conn, status__in=(PairingRequest.PENDING,
                                                                   PairingRequest.AWAITING_SECOND)).update(
            status=PairingRequest.EXPIRED, decided_at=now)
        source_policy._bump()
    client.clear_cache(conn)
    audit_log.record('qc.attempt_rolled_back', str(reason or 'failed')[:32], connection=conn, user=user,
                     app=conn.remote_installation_id, detail={'rules_removed': n})
    return True


def reap(now=None) -> int:
    """Roll back every Quick Connect attempt past its deadline. Called by the
    per-minute delivery job (connect_deliver_events); expired temporary
    rules are inert anyway (evaluate() checks expires_at)."""
    from .models import Connection
    now = now or timezone.now()
    n = 0
    for conn in Connection.objects.filter(qc_revision=qc.REVISION, state__in=_pre_active(),
                                          qc_attempt_expires_at__lte=now):
        try:
            if rollback_attempt(conn, 'attempt_expired'):
                n += 1
        except Exception:   # one bad row must not stop the others
            logger.exception('Quick Connect reaper could not roll back %s', conn.pk)
    return n
