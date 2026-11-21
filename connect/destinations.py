"""Approved outbound destinations (Quick Connect increment B2; DESIGN.md §7,
roadmap 79.12 / 79.15).

Every connection reaches the other application only at its approved
destination: host, port, approved address set (exact IPs or small ranges),
trust anchor (system CAs or ONLY a per-connection private CA), optional
SPKI pins, expected installation id. ``connect.transport.for_connection``
pins the guarded transport to that set:

  * every address the name resolves to, and the connected peer, must be in
    the set; otherwise nothing is sent (``destination_changed``);
  * the socket goes to the validated IP literal, the TLS handshake keeps
    SNI and hostname verification (an IP-literal destination passes only
    when the certificate names that IP);
  * no redirects, no proxies, loopback / link-local / metadata never, a
    private address only when it is an approved entry marked private;
  * an SPKI pin, when set, is compared after the handshake.

A security failure (changed address, SPKI mismatch, certificate name
mismatch) moves an active connection to ``security_blocked`` at once, with
evidence. Nothing reconnects by itself: an administrator approves the new
address (a staged ConnectChange; a second administrator when it widens),
then a retest has to pass before the connection is active again.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
import threading
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from agit8or_connect.errors import ConnectError

logger = logging.getLogger('connect')

# Widest range an administrator may approve for a peer behind rotating addresses.
DEST_MIN_PREFIX = {4: 24, 6: 48}
MAX_ADDRESSES = 16
SECURITY_CODES = frozenset({'destination_changed', 'spki_mismatch', 'certificate_name_mismatch'})
UNAPPROVED = 'destination_unapproved'

_NEVER = tuple(ipaddress.ip_network(n) for n in (
    '127.0.0.0/8', '169.254.0.0/16', '0.0.0.0/8', '224.0.0.0/4', '240.0.0.0/4', '100.100.100.200/32',
    '192.0.0.192/32', '::/128', '::1/128', 'fe80::/10', 'ff00::/8', 'fd00:ec2::254/128'))

MESSAGES = {
    'destination_changed': 'The other application\'s address changed: {host} now resolves to {seen} (approved: '
                           '{approved}). Nothing was sent. Check with its administrator, then approve the new '
                           'address under Network and retest.',
    'spki_mismatch': 'The other application presented a different certificate key than the pinned one. Nothing '
                     'was sent. Confirm the new certificate with its administrator before changing the pin.',
    'certificate_name_mismatch': 'The certificate presented at {host} does not name that host (or IP address). '
                                 'Nothing was sent.',
    'certificate_invalid': 'The other application\'s certificate is no longer valid (expired, not trusted, or '
                           'issued for another name). Nothing was sent. Check it with its administrator, then '
                           'retest.',
    'blocked_destination': '{host} now resolves to an address Agit8or Connect never connects to. Nothing was sent.',
    'identity_changed': 'The other application\'s address now leads to a different installation. Nothing was '
                        'sent. Find out why with its administrator before retesting.',
    'invalid_signature': 'A response from the other application had a signature that did not verify.',
    'peer_revoked': 'The other application no longer accepts this connection (it was revoked or removed there). '
                    'Check with its administrator; pair again if it was ended on purpose.',
    'key_revoked': 'The other application refused this installation\'s key. Check with its administrator.',
    'source_not_authorised': 'The other application refused this server\'s source address: this installation\'s '
                             'egress may have changed. Update it under Network and ask the other administrator to '
                             'approve it, then retest.',
    'scope_withdrawn': 'The other application now grants fewer permissions than were committed ({missing}). '
                       'Review the change with its administrator, then retest.',
    'binding_mismatch': 'A request for this connection came from an address bound to another connection.',
    UNAPPROVED: 'No destination address is approved for this connection yet. Open the connection, check the '
                'addresses its host name resolves to, and approve them.',
}


# --- validation ------------------------------------------------------------------------

def validate_address(value: str, *, private: bool = False) -> tuple:
    """(canonical network, is_private). Exact IPs, or ranges up to IPv4 /24 and
    IPv6 /48. Loopback, link-local, metadata and non-unicast are refused even
    when marked private; other private addresses need the flag."""
    from api_access.models import normalize_limited_network
    net, is_private = normalize_limited_network(value, min_prefix=DEST_MIN_PREFIX, private_ok=True,
                                                label='destination range')
    n = ipaddress.ip_network(net)
    if any(n.version == b.version and n.overlaps(b) for b in _NEVER):
        raise ValidationError(f'{net} is a loopback, link-local, metadata or non-unicast address. Agit8or '
                              'Connect never connects there.')
    if is_private and not private:
        raise ValidationError(f'{net} is a private address. Tick "private address" to approve it for this '
                              'connection.')
    return net, is_private


def entries_for(addresses, *, private=False, user=None) -> List[dict]:
    if isinstance(addresses, str):
        addresses = addresses.replace(',', '\n').splitlines()
    out, seen = [], set()
    now = timezone.now().isoformat()
    for raw in addresses or []:
        raw = str(raw).strip()
        if not raw:
            continue
        net, is_private = validate_address(raw, private=private)
        if net in seen:
            continue
        seen.add(net)
        out.append({'net': net, 'private': is_private, 'approved_by': getattr(user, 'pk', None), 'approved_at': now})
    if not out:
        raise ValidationError('Approve at least one address for the other application.')
    if len(out) > MAX_ADDRESSES:
        raise ValidationError(f'At most {MAX_ADDRESSES} approved addresses.')
    return out


def pinned_of(entries) -> frozenset:
    return frozenset(ipaddress.ip_network(e['net']) for e in entries or [])


def contains(entries, ip) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    return any(a.version == n.version and a in n for n in pinned_of(entries))


# --- preview (DNS + TLS handshake, no HTTP request) -------------------------------------

@dataclass
class Preview:
    host: str
    port: int
    addresses: List[str] = field(default_factory=list)
    cert_names: List[str] = field(default_factory=list)
    spki: str = ''
    error: str = ''
    # Which step failed (connection test, C3): blocked_destination,
    # dns_nxdomain, tcp_refused, tcp_timeout, tls_handshake,
    # certificate_invalid, certificate_name_mismatch.
    code: str = ''
    # Certificate expiry (ISO 8601), for diagnostics step 5.
    not_after: str = ''


def host_port(url: str):
    p = urlsplit(url or '')
    return (p.hostname or '').lower().rstrip('.'), p.port or 443


def probe(url: str, *, allow_private=False, ca_pem='', timeout=5.0) -> Preview:
    """Resolve the host under Connect's outbound policy and make a TLS
    handshake to the first address (certificate verified) to show the
    administrator what they approve. Sends no HTTP request."""
    from core.safe_http import OutboundPolicy, UnsafeURLError, resolve_public_addresses, spki_sha256, validate_url
    from agit8or_connect.adapters.safe_http import ports_for
    host, port = host_port(url)
    policy = OutboundPolicy(allow_lan=bool(allow_private), allow_local=False, allowed_ports=ports_for(url))
    pv = Preview(host=host, port=port)
    try:
        validate_url(url, policy)
        pv.addresses = resolve_public_addresses(host, port, policy)
    except (UnsafeURLError, OSError) as e:
        pv.error = 'The address is not allowed or does not resolve.' if isinstance(e, UnsafeURLError) else \
            'The host name did not resolve.'
        pv.code = 'blocked_destination' if isinstance(e, UnsafeURLError) else 'dns_nxdomain'
        return pv
    ctx = ssl.create_default_context(cadata=ca_pem) if ca_pem else ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        raw = socket.create_connection((pv.addresses[0], port), timeout)
    except socket.timeout:
        pv.error, pv.code = f'Port {port} did not answer within {int(timeout)} s.', 'tcp_timeout'
        return pv
    except OSError:
        pv.error, pv.code = f'The connection to port {port} was refused.', 'tcp_refused'
        return pv
    try:
        with raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        pv.spki = spki_sha256(der)
        from cryptography import x509
        cert = x509.load_der_x509_certificate(der)
        expiry = getattr(cert, 'not_valid_after_utc', None) or cert.not_valid_after
        pv.not_after = expiry.isoformat()
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            pv.cert_names = [str(n) for n in san.get_values_for_type(x509.DNSName)] + \
                [str(n) for n in san.get_values_for_type(x509.IPAddress)]
        except x509.ExtensionNotFound:
            pv.cert_names = []
    except ssl.SSLCertVerificationError as e:
        msg = getattr(e, 'verify_message', '') or 'verification failed'
        pv.error = f'TLS certificate not accepted ({msg}).'
        pv.code = 'certificate_name_mismatch' if 'mismatch' in msg.lower() else 'certificate_invalid'
    except (OSError, ssl.SSLError, ValueError):
        pv.error, pv.code = 'TLS handshake failed.', 'tls_handshake'
    return pv


# --- the row -----------------------------------------------------------------------------

def get(conn):
    from .models import ApprovedDestination
    pk = getattr(conn, 'pk', None)
    return ApprovedDestination.objects.filter(connection_id=pk).first() if pk else None


def ready(conn) -> bool:
    d = get(conn)
    return d is not None and bool(d.addresses)


def stage(conn, entries, user=None, *, preview: Optional[Preview] = None, ca_pem='', spki_pins=None):
    """Create or replace the destination of a connection that is not active
    yet (pairing). Activation makes it active (``activate``)."""
    from .models import ApprovedDestination
    host, port = host_port(conn.base_url)
    d, _ = ApprovedDestination.objects.update_or_create(connection=conn, defaults={
        'host': host, 'port': port, 'addresses': entries, 'status': ApprovedDestination.STAGED,
        'trust': ApprovedDestination.PRIVATE_CA if (ca_pem or conn.tls_ca_bundle) else ApprovedDestination.SYSTEM,
        'ca_bundle': ca_pem or conn.tls_ca_bundle or '', 'expected_installation_id': conn.remote_installation_id,
        'expected_cert_names': list(preview.cert_names) if preview else [],
        'spki_pins': [p.strip() for p in (spki_pins or []) if p and p.strip()][:4]})
    from . import audit_log
    audit_log.record('destination.staged', 'ok', connection=conn, user=user,
                     detail={'host': host, 'port': port, 'addresses': [e['net'] for e in entries]})
    return d


def activate(conn):
    from .models import ApprovedDestination
    ApprovedDestination.objects.filter(connection=conn).update(status=ApprovedDestination.ACTIVE)


# --- security block -------------------------------------------------------------------------

def message(code, conn=None, evidence=None) -> str:
    d = get(conn) if conn is not None else None
    ev = evidence or {}
    return MESSAGES.get(code, code).format(host=getattr(d, 'host', '') or ev.get('host', ''),
                                           seen=', '.join(ev.get('addresses', [])) or '?',
                                           approved=', '.join(e['net'] for e in (d.addresses if d else [])) or '—',
                                           missing=', '.join(ev.get('missing_scopes', [])) or '?')


EVIDENCE_KEYS = ('addresses', 'spki', 'host', 'cert_names', 'observed_installation', 'missing_scopes',
                 'observed_source', 'route')


def committed(conn) -> bool:
    """The connection was active before (its destination was activated by
    commit_connection); a new pairing under test is not."""
    from .models import ApprovedDestination
    return ApprovedDestination.objects.filter(connection_id=conn.pk, status=ApprovedDestination.ACTIVE).exists()


def security_block(conn, code, evidence=None, user=None):
    """Active, suspended, or a previously committed connection under retest
    -> security_blocked at once, evidence kept (DESIGN.md §7.3). No
    automatic retry: the monitor never selects it, nothing calls the peer
    while blocked, and only an administrator's retest (through testing and
    the commit gate) brings it back. Inside a diagnostics run nothing is
    changed (diagnostics are read-only; the monitor finds it)."""
    from .models import ApprovedDestination, Connection
    from . import audit_log, client
    if client.diagnosing(conn):
        return False
    ev = {k: v for k, v in (evidence or {}).items() if k in EVIDENCE_KEYS}
    d = get(conn)
    if d is not None:
        ev.setdefault('host', d.host)
        ev['approved'] = [e['net'] for e in d.addresses]
        ev['destination_version'] = d.version
    states = [Connection.ACTIVE, Connection.SUSPENDED]
    if committed(conn):
        states.append(Connection.TESTING)
    now = timezone.now()
    blocked = Connection.objects.filter(pk=conn.pk, state__in=states).update(
        state=Connection.SECURITY_BLOCKED, security_block_code=code[:40], security_block_at=now,
        security_block_detail=ev, last_error=message(code, conn, ev)[:500], last_failure_at=now,
        next_check_at=None, circuit=Connection.CIRCUIT_CLOSED, retest_until=None)
    if blocked:
        if d is not None:
            ApprovedDestination.objects.filter(pk=d.pk).update(observed={**ev, 'code': code, 'at': now.isoformat()})
        conn.state = Connection.SECURITY_BLOCKED
        conn.security_block_code = code[:40]
        client.clear_cache(conn)
        audit_log.record('connection.security_blocked', code, connection=conn, user=user,
                         app=conn.remote_installation_id, detail={k: v for k, v in ev.items()
                                                                  if k != 'cert_names'})
        from . import alerts, audit_anchor
        audit_anchor.anchor('security_block', connection=conn)     # C-05: the evidence is pinned at once
        alerts.observe(conn, code=code, user=user)
    return bool(blocked)


# --- address change (staged, DESIGN §7.2 / §11) ---------------------------------------------

def _fingerprint(conn, payload):
    import hashlib
    import json
    d = get(conn)
    state = [d.version, d.addresses] if d else [0, []]
    return hashlib.sha256(json.dumps([str(conn.pk), payload, state], sort_keys=True, default=str)
                          .encode()).hexdigest()


def is_widening(old_entries, new_entries) -> bool:
    """A change needs a second administrator when it adds a private address
    or a range (anything but exact public addresses). Replacing exact public
    addresses, e.g. with the one the peer now resolves to, is single
    administrator with a fresh re-authentication."""
    old = {e['net'] for e in old_entries or []}
    for e in new_entries:
        if e['net'] in old:
            continue
        n = ipaddress.ip_network(e['net'])
        if e.get('private') or n.prefixlen != n.max_prefixlen:
            return True
    return False


def propose_change(conn, addresses, user, *, private=False, spki_pins=None, note=''):
    from .models import ConnectChange
    entries = entries_for(addresses, private=private, user=user)
    d = get(conn)
    before = [e['net'] for e in (d.addresses if d else [])]
    payload = {'addresses': entries}
    if spki_pins is not None:
        payload['spki_pins'] = [p.strip() for p in spki_pins if p.strip()][:4]
    widening = is_widening(d.addresses if d else [], entries)
    change = ConnectChange.objects.create(
        connection=conn, kind=ConnectChange.DESTINATION, payload=payload, widening=widening,
        preview={'before_addresses': before, 'after_addresses': [e['net'] for e in entries],
                 'gains': [f"destination {e['net']}" for e in entries if e['net'] not in before],
                 'loses': [f'destination {n}' for n in before if n not in {e['net'] for e in entries}],
                 'widening': widening},
        fingerprint=_fingerprint(conn, payload), proposed_by=user, note=note[:300])
    from . import audit_log
    audit_log.record('destination.proposed', 'ok', connection=conn, user=user,
                     detail={'change': change.pk, 'before': before, 'after': [e['net'] for e in entries],
                             'widening': widening})
    return change


def approve(change, request):
    from .models import ConnectChange
    from .source_policy import ChangeRefused, _fresh
    user = request.user
    if change.status != ConnectChange.STAGED:
        raise ChangeRefused(f'This change is {change.get_status_display().lower()}.')
    if not _fresh(request):
        raise ChangeRefused('Re-enter your password to approve a destination change.')
    if _fingerprint(change.connection, change.payload) != change.fingerprint:
        raise ChangeRefused('The destination changed since this was proposed. Propose it again.')
    if change.widening:
        from tech_access.protected import can_widen_at_all, propose as tp
        if not can_widen_at_all(user):
            raise ChangeRefused('A private address or a range needs a second administrator, and there is none '
                                'other than you.')
        pc = tp('app_connection', f'Agit8or Connect destination change #{change.pk}: '
                + ', '.join(change.preview.get('after_addresses', []))[:200],
                {'connect_change': change.pk, 'fingerprint': change.fingerprint},
                [f'Connect destination {g}' for g in change.preview.get('gains', [])], user, request=request)
        change.status, change.protected_change_id = ConnectChange.AWAITING_SECOND, pc.pk
        change.save(update_fields=['status', 'protected_change_id'])
        return pc
    apply_change(change, user)
    return None


def apply_change(change, approver, *, protected=False):
    from .models import ApprovedDestination, ConnectChange
    from .source_policy import ChangeRefused
    from . import audit_log
    expected = ConnectChange.AWAITING_SECOND if protected else ConnectChange.STAGED
    conn = change.connection
    with transaction.atomic():
        change = ConnectChange.objects.select_for_update().get(pk=change.pk)
        if change.status != expected:
            raise ChangeRefused('This change is no longer waiting to be applied.')
        if _fingerprint(conn, change.payload) != change.fingerprint:
            raise ChangeRefused('The destination changed since this was proposed. Propose it again.')
        d = get(conn)
        if d is None:
            host, port = host_port(conn.base_url)
            d = ApprovedDestination.objects.create(connection=conn, host=host, port=port,
                                                   ca_bundle=conn.tls_ca_bundle or '',
                                                   status=ApprovedDestination.ACTIVE
                                                   if conn.state != conn.PENDING_PAIRING
                                                   else ApprovedDestination.STAGED)
        d.addresses = change.payload['addresses']
        if 'spki_pins' in change.payload:
            d.spki_pins = change.payload['spki_pins']
        d.version += 1
        d.save()
        change.status, change.approved_by, change.applied_at = ConnectChange.APPLIED, approver, timezone.now()
        change.save(update_fields=['status', 'approved_by', 'applied_at'])
        audit_log.record('destination.applied', 'ok', connection=conn, user=approver,
                         detail={'change': change.pk, 'addresses': [e['net'] for e in d.addresses],
                                 'version': d.version})
    return change


def reject(change, user):
    from .models import ConnectChange
    from .source_policy import ChangeRefused
    if change.status not in (ConnectChange.STAGED, ConnectChange.AWAITING_SECOND):
        raise ChangeRefused('This change is no longer waiting for a decision.')
    change.status = ConnectChange.REJECTED
    change.save(update_fields=['status'])


def retest(conn, user=None) -> bool:
    """Security Blocked -> testing -> active only when an address was
    approved after the block AND the commit-gate test passes (increment D:
    through ``testing``, never straight to active). The evidence is kept."""
    from . import health
    return health.admin_retest(conn, user)
