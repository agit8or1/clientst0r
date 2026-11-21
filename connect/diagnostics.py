"""Connection diagnostics: fifteen independent steps (DESIGN.md §9.1, §9.2;
roadmap 79.20; increment D, completed in increment E with the commit gate
``gate()``, the periodic full run ``periodic_due()`` and the redacted export
``export()``).

Every step returns ``{n, id, name, status, code, explanation, next_action,
at, duration_ms, data}`` with status ``pass`` / ``fail`` / ``skipped`` /
``not_tested``. A step whose prerequisite failed is ``skipped`` ("skipped
because step N failed"). ``data`` is sanitised: addresses, certificate
names / expiry / SPKI hash, HTTP status, protocol, counts and times. Never a
token, assertion, proof, code, signature or key.

Read-only by rule:

  * nothing is approved, widened, activated, blocked or unblocked here; a
    security failure found here is reported (the monitor acts on it);
  * a Security Blocked or suspended connection gets the network and
    discovery steps only: no credential is sent to an address or
    installation an administrator has not confirmed;
  * the one message sent is the protocol's own ``connect.test`` event (no
    customer data); if it is not accepted it is cancelled, not retried;
  * administrators only (manage_app_connections) and rate limited per
    connection and per administrator, counted in the database;
  * the one thing a run remembers is where the other side's qc-diagnostics
    probe is (``Connection.remote_probe_url``, advertised in its discovery
    on the same origin), so the light health check can use it.
"""
from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from agit8or_connect import discovery as sdk_discovery
from agit8or_connect import quick_connect as qc
from agit8or_connect.errors import ConnectError

STEPS = (
    (1, 'dns', 'DNS'),
    (2, 'destination', 'Approved destination address'),
    (3, 'tcp', 'TCP'),
    (4, 'tls', 'TLS handshake'),
    (5, 'certificate', 'Certificate'),
    (6, 'protocol', 'Discovery and protocol'),
    (7, 'identity', 'Identity'),
    (8, 'source', 'Source address policy'),
    (9, 'token', 'Key and token'),
    (10, 'permissions', 'Permissions'),
    (11, 'tenants', 'Customer mapping'),
    (12, 'operation', 'Authorised operation'),
    (13, 'event', 'Signed event'),
    (14, 'reverse', 'Reverse connectivity'),
    (15, 'last_success', 'Last success'),
)
NAMES = {sid: (n, name) for n, sid, name in STEPS}
REQUIRED = tuple(sid for n, sid, _ in STEPS if n <= 13)
# Full diagnostics of an active connection by the monitor (DESIGN §8.2).
PERIODIC_EVERY = timedelta(minutes=15)

RATE_PER_CONNECTION = (6, timedelta(minutes=10))
RATE_PER_USER = (20, timedelta(hours=1))
CLOCK_SKEW_MAX = 120          # seconds; tokens and assertions are refused beyond this
CERT_FAIL_DAYS, CERT_WARN_DAYS = 7, 21
REVERSE_WINDOW = timedelta(minutes=15)
_DATA_KEYS = frozenset({'addresses', 'approved', 'host', 'port', 'cert_names', 'not_after', 'days_left', 'spki',
                        'status', 'protocol', 'versions', 'extensions', 'installation', 'expected', 'observed_source',
                        'declared_egress', 'peer_source_check', 'last_source_ip', 'skew_s', 'granted', 'committed',
                        'missing', 'declined', 'remote_tenants', 'granted_here', 'reported', 'peer_reached_at',
                        'inbound_test_at', 'outbound_last_ok', 'inbound_last_ok', 'age_s', 'stale', 'via', 'warning'})


class DiagnosticsRefused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _clean(data: Optional[dict]) -> dict:
    out = {}
    for k, v in (data or {}).items():
        if k not in _DATA_KEYS:
            continue
        if isinstance(v, (list, tuple)):
            out[k] = [str(x)[:200] for x in list(v)[:20]]
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)[:300]
    return out


class _Run:
    def __init__(self, conn):
        self.conn = conn
        self.steps = {}
        self.t0 = time.monotonic()

    def put(self, sid, status, explanation, *, code='', next_action='', data=None, started=None):
        n, name = NAMES[sid]
        self.steps[sid] = {'n': n, 'id': sid, 'name': name, 'status': status, 'code': code if status != 'pass'
                           or code in ('stale', 'certificate_expiring') else '',
                           'explanation': explanation, 'next_action': next_action if status != 'pass' or
                           code in ('stale', 'certificate_expiring') else '',
                           'at': timezone.now().isoformat(),
                           'duration_ms': int((time.monotonic() - (started or time.monotonic())) * 1000),
                           'data': _clean(data)}

    def ok(self, sid, explanation, data=None, **kw):
        self.put(sid, 'pass', explanation, data=data, **kw)

    def fail(self, sid, code, explanation, next_action='', data=None, **kw):
        self.put(sid, 'fail', explanation, code=code, next_action=next_action, data=data, **kw)

    def passed(self, sid):
        return self.steps.get(sid, {}).get('status') == 'pass'

    def skip(self, sid, because_sid, reason=''):
        if sid in self.steps:
            return
        if reason:
            self.put(sid, 'skipped', reason)
        else:
            self.put(sid, 'skipped', f'Skipped because step {NAMES[because_sid][0]} '
                                     f'({NAMES[because_sid][1]}) failed.')

    def skip_rest(self, because_sid, reason=''):
        for _, sid, _ in STEPS:
            if sid not in self.steps and sid != 'last_success':
                self.skip(sid, because_sid, reason)

    def ordered(self):
        return [self.steps[sid] for _, sid, _ in STEPS if sid in self.steps]


# --- steps 1-5: from a DNS + TLS handshake preview (no HTTP request) ---------------------

def _network(run: _Run) -> bool:
    from . import destinations, transport
    conn = run.conn
    d = destinations.get(conn)
    t = time.monotonic()
    try:
        pv = transport.probe(conn.base_url, allow_private=bool(d and d.has_private),
                             ca_pem=(d.ca_bundle if d else '') or conn.tls_ca_bundle)
    except Exception as e:   # never raises by contract
        pv = destinations.Preview(host='', port=0, error=str(e)[:200], code='probe_error')
    host, port = destinations.host_port(conn.base_url)
    code = getattr(pv, 'code', '') or ''
    if not pv.addresses:
        if code == 'blocked_destination':
            run.fail('dns', 'blocked_destination', f'{host} resolves to an address Agit8or Connect never connects '
                     'to (loopback, link-local, metadata, or a private address not approved).',
                     'Check the name with the other administrator; it may have been pointed somewhere else.',
                     {'host': host}, started=t)
        else:
            run.fail('dns', 'dns_timeout' if code == 'dns_timeout' else 'dns_nxdomain',
                     pv.error or f'{host} did not resolve.',
                     'Check the other application\'s host name and this server\'s DNS resolver.', {'host': host},
                     started=t)
        run.skip_rest('dns')
        return False
    run.ok('dns', f'{host} resolves to {", ".join(pv.addresses)}.', {'host': host, 'addresses': pv.addresses},
           started=t)
    approved = d.nets if d else []
    outside = [a for a in pv.addresses if not (d and destinations.contains(d.addresses, a))]
    if outside:
        run.fail('destination', 'destination_changed', f'{", ".join(outside)} is not an approved address for this '
                 f'connection (approved: {", ".join(approved) or "none"}).',
                 'Confirm the new address with the other administrator, then approve it under Network '
                 '("Approve new address") and retest.', {'addresses': outside, 'approved': approved})
        run.skip_rest('destination')
        return False
    run.ok('destination', 'Every resolved address is approved for this connection.', {'approved': approved})
    if code.startswith('tcp_'):
        run.fail('tcp', code, pv.error or f'Port {port} did not answer.',
                 f'The other side\'s firewall or port {port} forwarding has to let this server in. Clientst0r '
                 'never changes firewalls; its administrator does.', {'port': port})
        run.skip_rest('tcp')
        return False
    run.ok('tcp', f'Port {port} accepts connections.', {'port': port})
    if (code and not code.startswith('certificate')) or (pv.error and not code):
        run.fail('tls', code if code in ('tls_handshake', 'tls_version') else 'tls_handshake',
                 pv.error or 'TLS handshake failed.', 'The other application must offer TLS 1.2 or later on this '
                 'port (check its reverse proxy).')
        run.skip_rest('tls')
        return False
    run.ok('tls', 'TLS 1.2 or later negotiated.')
    if code.startswith('certificate'):
        run.fail('certificate', code, pv.error or 'The certificate was not accepted.',
                 'Renew or fix the other application\'s certificate, or set its private CA for this connection.',
                 {'host': host, 'cert_names': pv.cert_names})
        run.skip_rest('certificate')
        return False
    if d and d.spki_pins and pv.spki and pv.spki not in d.spki_pins:
        run.fail('certificate', 'spki_mismatch', 'The certificate key does not match the pinned key.',
                 'Confirm the new certificate with the other administrator before changing the pin.',
                 {'spki': pv.spki, 'host': host})
        run.skip_rest('certificate')
        return False
    data = {'host': host, 'cert_names': pv.cert_names, 'spki': pv.spki}
    days = _days_left(getattr(pv, 'not_after', ''))
    if days is not None:
        data.update(not_after=pv.not_after, days_left=days)
        if days < CERT_FAIL_DAYS:
            run.fail('certificate', 'certificate_expiring', f'The certificate expires in {days} day(s).',
                     'Renew the other application\'s certificate now.', data)
            run.skip_rest('certificate')
            return False
        if days < CERT_WARN_DAYS:
            run.ok('certificate', f'Valid for {host}; expires in {days} days.', data, code='certificate_expiring',
                   next_action='Renew the other application\'s certificate soon.')
            return True
    run.ok('certificate', f'Valid for {host}' + (f'; expires in {days} days.' if days is not None else '.'), data)
    return True


def _days_left(not_after: str) -> Optional[int]:
    from django.utils.dateparse import parse_datetime
    if not not_after:
        return None
    dt = parse_datetime(not_after)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return int((dt - timezone.now()).total_seconds() // 86400)


# --- steps 6-7: discovery, protocol, identity (no credentials) -----------------------------

def _discovery(run: _Run) -> Optional[dict]:
    from . import transport
    conn = run.conn
    t = time.monotonic()
    url = sdk_discovery.discovery_url(conn.base_url)
    try:
        r = transport.for_connection(conn).request('GET', url, headers={'Accept': 'application/json'})
    except ConnectError as e:
        run.fail('protocol', e.code, f'Discovery could not be fetched ({e.message}).',
                 'Check that the other application is running and its address is right.', started=t)
        run.skip_rest('protocol')
        return None
    if r.status == 403 and b'source_not_authorised' in (r.body or b''):
        run.fail('source', 'source_not_authorised', 'The other application refused this server\'s source address '
                 '(HTTP 403 source_not_authorised).', 'The other administrator approves this installation\'s egress '
                 'address (Connected Applications → Network shows it); check it is still right.',
                 {'declared_egress': _own_egress()})
        run.skip_rest('source')
        return None
    if r.status != 200:
        run.fail('protocol', f'http_{r.status}', f'Discovery answered HTTP {r.status}.',
                 'The other application\'s Connect endpoints may be off or behind a proxy that rewrites them.',
                 {'status': r.status}, started=t)
        run.skip_rest('protocol')
        return None
    try:
        raw = json.loads(r.body)
        info = sdk_discovery.parse_document(raw, url)
    except (ValueError, ConnectError) as e:
        run.fail('protocol', getattr(e, 'code', 'invalid_request'), 'The discovery document is not valid.',
                 'The other application may not be an Agit8or Connect application, or a proxy alters it.',
                 started=t)
        run.skip_rest('protocol')
        return None
    ext = qc.negotiate_extensions(qc.advertised_extensions(raw, url))
    run.ok('protocol', f'agit8or-connect/{info.version}' + (f', revision {raw.get("revision")}'
                                                             if raw.get('revision') else '') +
           (f'; extensions {", ".join(sorted(ext))}' if ext else '; version 1 only') + '.',
           {'protocol': info.version, 'extensions': sorted(ext)}, started=t)
    if info.installation_id != conn.remote_installation_id:
        run.fail('identity', 'identity_changed', 'The address now leads to a different installation than the one '
                 'that paired.', 'Do not approve anything. Find out with the other administrator why; pair again '
                 'only if the application was really reinstalled.',
                 {'installation': info.installation_id, 'expected': conn.remote_installation_id})
        run.skip_rest('identity')
        return None
    run.ok('identity', f'Installation {info.installation_id} as paired.', {'installation': info.installation_id})
    return {'info': info, 'raw': raw, 'extensions': ext}


def _own_egress():
    from . import identity
    return [e.get('net') for e in identity.get().egress_addresses or [] if isinstance(e, dict)]


def _peer_time(conn) -> Optional[int]:
    """Server time from the other side's unauthenticated health endpoint."""
    from . import transport
    url = conn.endpoint('health')
    if not url:
        return None
    try:
        r = transport.for_connection(conn).request('GET', url, headers={'Accept': 'application/json'})
        if r.status != 200:
            return None
        v = json.loads(r.body or b'{}').get('time')
        return int(v) if isinstance(v, int) and not isinstance(v, bool) else None
    except (ConnectError, ValueError):
        return None


# --- steps 8-14 ------------------------------------------------------------------------------

def _local_source(run: _Run, peer_part: str, data: dict):
    from .models import SourceRule as SR
    from . import source_policy
    conn = run.conn
    data['last_source_ip'] = conn.last_source_ip or ''
    if conn.last_source_ip:
        try:
            allowed = source_policy.test_address(conn.last_source_ip, str(conn.pk))['allowed']
        except Exception:
            allowed = False
        if not allowed:
            run.fail('source', 'source_not_authorised_here', peer_part + f' The other application last came from '
                     f'{conn.last_source_ip}, which this installation\'s rules no longer allow for this connection.',
                     'If its address changed, approve the new one under this connection\'s Network section '
                     '(a staged change).', data)
            return
        run.ok('source', peer_part + f' Its last address here, {conn.last_source_ip}, is allowed.', data)
        return
    rules = SR.objects.filter(connection=conn, layer=SR.CONNECTION, action=SR.ALLOW,
                              status__in=(SR.TEMPORARY, SR.ACTIVE)).exists()
    if not rules:
        run.fail('source', 'source_not_authorised_here', peer_part + ' No address of the other application is '
                 'allowed here for this connection.', 'Approve the other application\'s address for this '
                 'connection.', data)
        return
    run.ok('source', peer_part + ' The other application has not called here yet; its approved addresses are in '
           'place.', data)


def _credentialed(run: _Run, disc: dict):
    from .models import Connection
    from . import client, events
    conn = run.conn
    # advertised_extensions() already checked the probe URL is on the discovery origin.
    raw_eps = disc['raw'].get('endpoints') if isinstance(disc['raw'].get('endpoints'), dict) else {}
    probe_url = str(raw_eps.get('qc_probe') or '') if qc.EXT_DIAGNOSTICS in disc['extensions'] else ''
    uses_probe = bool(probe_url)
    _remember_probe(conn, probe_url)
    usable = conn.state in (Connection.ACTIVE, Connection.TESTING)
    one_way = not (conn.requested_outbound_scopes or conn.outbound_scopes)
    if not usable:
        why = (f'Not run: the connection is {conn.get_state_display()}. Credentials are not sent until an '
               'administrator confirms the change and retests.')
        _local_source(run, 'Not checked at the other application (no credentials sent).', {})
        for sid in ('token', 'permissions', 'tenants', 'operation', 'event', 'reverse'):
            run.put(sid, 'not_tested', why)
        return
    if one_way:
        _local_source(run, 'This installation was granted nothing at the other application (one-directional).', {})
        for sid in ('token', 'permissions', 'tenants', 'operation', 'event'):
            run.put(sid, 'not_tested', 'Not tested: one-directional connection (nothing granted to this '
                                       'installation at the other application).')
        _reverse(run, None, False)
        return
    # 9. key and token (clock first: assertions are refused beyond the skew).
    t = time.monotonic()
    peer_time = _peer_time(conn)
    skew = None if peer_time is None else int(peer_time - time.time())
    if skew is not None and abs(skew) > CLOCK_SKEW_MAX:
        run.fail('token', 'clock_skew', f'The clocks of the two servers differ by {abs(skew)} seconds; signed '
                 'requests are refused beyond 120 seconds.', 'Synchronise the clock (NTP) of the server that is '
                 'wrong.', {'skew_s': skew}, started=t)
        _local_source(run, 'Not checked at the other application (token step failed).', {})
        run.skip_rest('token')
        _reverse(run, None, uses_probe)
        return
    committed = sorted(conn.outbound_scopes or [])
    try:
        tok = client.get_token(conn, use_cache=False)
    except ConnectError as e:
        if e.code == 'source_not_authorised':
            run.fail('source', 'source_not_authorised', 'The other application refused this server\'s source '
                     'address at its token endpoint.', 'The other administrator approves this installation\'s '
                     'egress address.', {'declared_egress': _own_egress()})
            run.skip_rest('source')
            return
        code = e.code
        nxt = {'invalid_client': 'The other application does not accept this connection (revoked there, or its '
                                 'approval is not finished). Check with its administrator.',
               'key_revoked': 'The other application refused this installation\'s key; check with its '
                              'administrator.',
               'scope_withdrawn': 'The other application withdrew permissions; review with its administrator.'}
        run.fail('token', code, f'Token refused ({code}): {e.message}', nxt.get(code, 'Check the connection on '
                 'the other application.'), {'skew_s': skew} if skew is not None else None, started=t)
        _local_source(run, 'The token step failed, so the probe did not run.', {})
        run.skip_rest('token')
        _reverse(run, None, uses_probe)
        return
    granted = sorted(set(str(tok.get('scope', '')).split()))
    run.ok('token', 'A short-lived, key-bound token was issued with the active key.',
           {'skew_s': skew} if skew is not None else None, started=t)
    # 10. permissions
    missing = sorted(set(committed) - set(granted))
    if missing:
        run.fail('permissions', 'scope_withdrawn', 'Granted at pairing but missing from the token: '
                 + ', '.join(missing) + '.', 'Review the change with the other administrator.',
                 {'granted': granted, 'committed': committed, 'missing': missing})
    else:
        run.ok('permissions', 'Every committed permission is in the token.',
               {'granted': granted, 'committed': committed})
    # 8. source (both directions; the peer's view through qc_probe when offered)
    probe = None
    peer_part = 'The other application accepted this server\'s source address.'
    data = {'declared_egress': _own_egress()}
    if uses_probe and probe_url:
        try:
            nonce = qc.generate_nonce()
            r = client.call(conn, 'POST', probe_url, body=json.dumps(qc.probe_request_body(nonce)).encode())
            if r.status == 200:
                probe = qc.validate_probe_response(json.loads(r.body or b'{}'), nonce=nonce)
                data.update(observed_source=probe['observed_source'], peer_source_check=probe['checks']['source'])
                if probe['checks']['source'] == 'not_authorised':
                    run.fail('source', 'source_not_authorised', f'The other application sees this server at '
                             f'{probe["observed_source"]} and does not authorise that address.',
                             'The other administrator approves this installation\'s egress address.', data)
                else:
                    peer_part = (f'The other application sees this server at {probe["observed_source"]} '
                                 f'({probe["checks"]["source"].replace("_", " ")}).')
                    if data['declared_egress'] and not _covered(probe['observed_source'], data['declared_egress']):
                        data['warning'] = 'observed address is not in this installation\'s declared egress'
                        peer_part += (' That is not one of this installation\'s declared egress addresses; '
                                      'update Network → egress if it changed (a suggestion only).')
            elif r.status == 403 and b'source_not_authorised' in (r.body or b''):
                run.fail('source', 'source_not_authorised', 'The other application refused this server\'s source '
                         'address.', 'The other administrator approves this installation\'s egress address.', data)
        except (ConnectError, ValueError):
            probe = None
    if 'source' not in run.steps:
        _local_source(run, peer_part, data)
    # 12 then 11: one harmless authorised call (capabilities), then the customer mapping.
    url = conn.endpoint('capabilities')
    caps = None
    t = time.monotonic()
    if url:
        try:
            r = client.call(conn, 'GET', url)
            if r.status == 200:
                caps = json.loads(r.body or b'{}')
                run.ok('operation', 'GET capabilities succeeded.', {'status': 200}, started=t)
            else:
                run.fail('operation', 'insufficient_scope' if r.status == 403 else f'http_{r.status}',
                         f'Capabilities answered HTTP {r.status}.', 'Check what the other application granted '
                         'this installation.', {'status': r.status}, started=t)
        except (ConnectError, ValueError) as e:
            run.fail('operation', getattr(e, 'code', 'invalid_request'), str(getattr(e, 'message', e))[:200],
                     started=t)
    else:
        run.put('operation', 'not_tested', 'The other application does not list a capabilities endpoint.')
    if caps is not None:
        remote = sorted({str(t.get('tenant')) for t in caps.get('tenants', []) if isinstance(t, dict)})
        # Both lists name the customer in this installation's terms: the
        # pairing result's ``remote_tenant`` (PROTOCOL §5, responder's view)
        # and the ``tenant`` of each capabilities grant.
        reported = sorted({str(g.get('remote_tenant') or g.get('tenant') or '') for g in conn.remote_tenant_grants or []
                           if isinstance(g, dict)} - {''})
        here = conn.tenant_grants.filter(active=True).count()
        if reported and set(remote) != set(reported):
            run.fail('tenants', 'tenant_mismatch', f'The other application now reports {len(remote)} customer '
                     f'grant(s) for this installation; {len(reported)} were reported at pairing.',
                     'Review the customer mapping with the other administrator.',
                     {'remote_tenants': remote, 'reported': reported, 'granted_here': here})
        else:
            run.ok('tenants', f'{here} customer(s) granted here; the other application reports {len(remote)} '
                   f'customer grant(s) for this installation.', {'remote_tenants': remote, 'granted_here': here})
    elif 'tenants' not in run.steps:
        if run.steps.get('operation', {}).get('status') == 'not_tested':
            run.put('tenants', 'not_tested', 'Not tested: the other application does not list a capabilities '
                                             'endpoint, which reports its customer grants.')
        else:
            run.skip('tenants', 'operation')
    # 13. signed event
    t = time.monotonic()
    try:
        ev = events.enqueue(conn, 'connect.test', {'requested_by': 'diagnostics'})
        ok = events.deliver(ev, force=True)
        if not ok and ev.status == ev.QUEUED:
            type(ev).objects.filter(pk=ev.pk).update(status=ev.CANCELLED)
        if ok:
            run.ok('event', 'A signed connect.test event was accepted.', started=t)
        else:
            run.fail('event', 'event_rejected', f'The test event was not accepted ({ev.last_error or "no answer"}).',
                     'Check the other application\'s event endpoint and its copy of this installation\'s keys.',
                     started=t)
    except ConnectError as e:
        run.fail('event', e.code, e.message, started=t)
    _reverse(run, probe, uses_probe)


def _remember_probe(conn, probe_url):
    """Where the light check finds the other side's probe (or that it has
    none any more). Learnt only from a discovery document that passed the
    identity step; the URL is on the discovery origin (advertised_extensions)."""
    from .models import Connection
    url = (probe_url or '')[:500]
    if (conn.remote_probe_url or '') != url:
        Connection.objects.filter(pk=conn.pk).update(remote_probe_url=url)
        conn.remote_probe_url = url


def _covered(ip, nets) -> bool:
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
        return any(a in ipaddress.ip_network(n, strict=False) for n in nets if n)
    except ValueError:
        return False


def _reverse(run: _Run, probe, uses_probe):
    """14: has the other application reached this one recently?"""
    from .models import InboundEvent
    conn = run.conn
    now = timezone.now()
    test_in = (InboundEvent.objects.filter(connection=conn, event_type='connect.test')
               .order_by('-received_at').values_list('received_at', flat=True).first())
    recent_test = test_in is not None and now - test_in <= REVERSE_WINDOW
    if uses_probe:
        reached = probe.get('peer_reached_at') if probe else None
        if reached is not None and now.timestamp() - reached <= REVERSE_WINDOW.total_seconds():
            run.ok('reverse', 'The other application reports it reached this installation recently.',
                   {'peer_reached_at': reached, 'via': 'qc_probe'})
            return
        if recent_test or (conn.last_source_at and now - conn.last_source_at <= REVERSE_WINDOW):
            run.ok('reverse', 'The other application called this installation in the last 15 minutes.',
                   {'inbound_test_at': test_in.isoformat() if test_in else None, 'via': 'inbound'})
            return
        if probe is None and 'token' in run.steps and not run.passed('token'):
            run.skip('reverse', 'token')
            return
        run.fail('reverse', 'reverse_failed', 'The other application has not reached this installation in the last '
                 '15 minutes.', 'Ask the other administrator to run diagnostics (or a connection test) on their '
                 'side; check that this installation allows its address.',
                 {'peer_reached_at': reached, 'via': 'qc_probe'})
        return
    if recent_test:
        run.ok('reverse', 'A connect.test event from the other application arrived in the last 15 minutes.',
               {'inbound_test_at': test_in.isoformat(), 'via': 'inbound'})
        return
    run.put('reverse', 'not_tested', 'Not tested: the other application does not offer qc-diagnostics and sent no '
                                     'connect.test event here in the last 15 minutes.')


def _last_success(run: _Run):
    conn = run.conn
    now = timezone.now()
    interval = max(30, int(conn.monitor_interval_s or 60))
    out_ok, in_ok = conn.last_outbound_ok_at, conn.last_source_at
    if not out_ok and not in_ok:
        run.put('last_success', 'not_tested', 'No successful exchange recorded yet in either direction.')
        return
    newest = max(x for x in (out_ok, in_ok) if x)
    age = int((now - newest).total_seconds())
    data = {'outbound_last_ok': out_ok.isoformat() if out_ok else None,
            'inbound_last_ok': in_ok.isoformat() if in_ok else None, 'age_s': age, 'stale': age > 3 * interval}
    text = (f'Last successful call to the other application: {out_ok:%Y-%m-%d %H:%M:%S} UTC. ' if out_ok else
            'No successful call to the other application yet. ')
    text += (f'Last authenticated request from it: {in_ok:%Y-%m-%d %H:%M:%S} UTC.' if in_ok else
             'No authenticated request from it yet.')
    if data['stale']:
        run.ok('last_success', text, data, code='stale', next_action='Older than three check intervals: see the '
                                                                     'health checks and the steps above.')
    else:
        run.ok('last_success', text, data)


# --- the run ---------------------------------------------------------------------------------

def check_rate(conn, user):
    from .models import DiagnosticRun
    now = timezone.now()
    n, window = RATE_PER_CONNECTION
    if DiagnosticRun.objects.filter(connection=conn, started_at__gte=now - window,
                                    trigger=DiagnosticRun.MANUAL).count() >= n:
        raise DiagnosticsRefused('rate_limited', f'Diagnostics ran {n} times for this connection in the last '
                                                 f'{int(window.total_seconds() // 60)} minutes. Try again later.')
    n, window = RATE_PER_USER
    if user is not None and DiagnosticRun.objects.filter(run_by=user, started_at__gte=now - window).count() >= n:
        raise DiagnosticsRefused('rate_limited', f'You ran diagnostics {n} times in the last hour. Try again later.')


def run(conn, user=None, *, trigger='manual'):
    """Run the fifteen steps for one connection; returns the DiagnosticRun."""
    from .models import Connection, DiagnosticRun
    from . import audit_log, client, identity
    conn.refresh_from_db()
    if identity.kill_switch_engaged():
        raise DiagnosticsRefused('kill_switch', 'Connected applications are stopped by the emergency kill switch.')
    if conn.state in (Connection.REVOKED, Connection.FAILED, Connection.PENDING_PAIRING):
        raise DiagnosticsRefused('connection_inactive', 'Diagnostics run for connections that are set up, '
                                                        'testing, active, suspended or Security Blocked.')
    if trigger == DiagnosticRun.MANUAL:
        check_rate(conn, user)
    row = DiagnosticRun.objects.create(connection=conn, trigger=trigger, run_by=user)
    r = _Run(conn)
    retest = client.retesting(conn) if conn.state == Connection.TESTING else _null()
    with client.diagnostics_run(conn), retest:
        try:
            if _network(r):
                disc = _discovery(r)
                if disc is not None:
                    _credentialed(r, disc)
        except Exception:   # a defect must not leave a half run looking like a pass
            import logging
            logging.getLogger('connect').exception('diagnostics run failed for %s', conn.pk)
            for _, sid, _ in STEPS:
                if sid not in r.steps and sid != 'last_success':
                    r.put(sid, 'fail' if not r.steps else 'skipped', 'The diagnostics run stopped unexpectedly.',
                          code='internal_error')
        _last_success(r)
    steps = r.ordered()
    result = DiagnosticRun.PASS if all(s['status'] in ('pass', 'not_tested') for s in steps
                                       if s['id'] != 'last_success') else DiagnosticRun.FAIL
    DiagnosticRun.objects.filter(pk=row.pk).update(steps=steps, result=result, finished_at=timezone.now())
    row.refresh_from_db()
    audit_log.record('diagnostics.run', result, connection=conn, user=user, app=conn.remote_installation_id,
                     detail={'run': row.pk, 'trigger': trigger,
                             'failed': [s['id'] for s in steps if s['status'] == 'fail'],
                             'skipped': [s['id'] for s in steps if s['status'] == 'skipped']})
    return row


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- the commit gate (DESIGN §9.1, §11.3) -------------------------------------------------------

def required_steps(conn) -> tuple:
    """Steps 1-13; for a Quick Connect connection (both sides protocol 1.1)
    step 14, reverse connectivity, too -- unless this side let the other
    one reach only discovery (one-directional: it cannot authenticate here,
    so it can never prove it reached us). Step 15 is informational."""
    return REQUIRED + (('reverse',) if conn.qc_revision == '1.1' and _reverse_allowed(conn) else ())


def _reverse_allowed(conn) -> bool:
    from .models import SourceRule as SR
    return SR.objects.filter(connection=conn, layer=SR.CONNECTION, action=SR.ALLOW, purpose=SR.ALL,
                             status__in=(SR.STAGED, SR.TEMPORARY, SR.ACTIVE)).exists()


def gate(row, conn=None):
    """(ok, failures) for a finished DiagnosticRun: every required step
    passed. ``not_tested`` counts only for steps 1-13 that the protocol lets
    a peer leave out (a one-directional connection, no capabilities
    endpoint); for step 14 of a Quick Connect connection it is a failure."""
    conn = conn or row.connection
    steps = {s.get('id'): s for s in (row.steps or [])}
    failures = []
    for sid in required_steps(conn):
        s = steps.get(sid)
        status = (s or {}).get('status')
        if status == 'pass' or (status == 'not_tested' and sid != 'reverse'):
            continue
        failures.append(s or {'id': sid, 'n': NAMES[sid][0], 'name': NAMES[sid][1], 'status': 'missing',
                              'code': 'not_run', 'explanation': 'The step did not run.', 'next_action': ''})
    return (row.finished_at is not None and not failures), failures


# --- periodic full run (monitor, DESIGN §8.2) ---------------------------------------------------

def periodic_due(conn, now=None) -> bool:
    """An active, healthy connection gets a full run every 15 minutes."""
    from .models import Connection, DiagnosticRun
    now = now or timezone.now()
    if conn.state != Connection.ACTIVE or conn.health not in ('', Connection.HEALTH_CONNECTED):
        return False
    return not DiagnosticRun.objects.filter(connection=conn, trigger=DiagnosticRun.MONITOR,
                                            started_at__gt=now - PERIODIC_EVERY).exists()


# --- redacted export (DESIGN §9.2) --------------------------------------------------------------

import re as _re

_SECRET_PATTERNS = (
    # name=value first, so the name goes with the value
    _re.compile(r'(?i)\b(code|code_verifier|access_token|refresh_token|token|assertion|client_assertion|secret|'
                r'password|signature|sig|private_key)\s*[=:]\s*["\']?[^\s"\',;]{6,}'),
    _re.compile(r'-----BEGIN [A-Z ]+-----[\s\S]*?(-----END [A-Z ]+-----|$)'),       # PEM
    _re.compile(r'eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.?[A-Za-z0-9_-]*'),      # JWS / JWT / DPoP proof
    _re.compile(r'(?i)\b(bearer|dpop)\s+[A-Za-z0-9._~+/=-]{8,}'),                  # an Authorization value
    _re.compile(r'\b[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}\b'),               # a pairing code
)
# The only keys an export carries; every value is scrubbed again.
_EXPORT_STEP_KEYS = ('n', 'id', 'name', 'status', 'code', 'explanation', 'next_action', 'at', 'duration_ms', 'data')


def scrub(text) -> str:
    out = str(text if text is not None else '')
    for p in _SECRET_PATTERNS:
        out = p.sub('[redacted]', out)
    return out[:1000]


def _scrub_value(v):
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_scrub_value(x) for x in list(v)[:20]]
    return scrub(v)


def _export_step(step) -> dict:
    out = {}
    for k in _EXPORT_STEP_KEYS:
        if k not in step:
            continue
        v = step[k]
        if k == 'data':
            # The run's own allowlist (addresses, certificate names, expiry,
            # SPKI hash, status, counts), applied again, then scrubbed.
            v = {dk: _scrub_value(dv) for dk, dv in _clean(v if isinstance(v, dict) else {}).items()}
        else:
            v = _scrub_value(v)
        out[k] = v
    return out


def export(row, user=None, *, fmt='json'):
    """A redacted copy of one run for a support case: no token, assertion,
    DPoP proof, code, signature, private key, pairing secret or customer
    data. Addresses, certificate names / expiry / SPKI hash and statuses
    stay. Audited. Returns (filename, content_type, bytes)."""
    from . import audit_log, status as st
    conn = row.connection
    ok, failures = gate(row, conn)
    doc = {
        'format': 'agit8or-connect-diagnostics/1',
        'exported_at': timezone.now().isoformat(),
        'connection': {
            'id': str(conn.pk), 'name': scrub(conn.remote_display_name), 'app_type': scrub(conn.remote_app_type),
            'remote_installation_id': scrub(conn.remote_installation_id), 'direction': conn.direction,
            'base_url': scrub(conn.base_url), 'protocol': conn.remote_protocol_version,
            'quick_connect': conn.qc_revision == '1.1', 'status': st.display(conn).key,
            'health': {d: {'ok': (v or {}).get('ok'), 'code': scrub((v or {}).get('code', ''))}
                       for d, v in (conn.health_dims or {}).items() if isinstance(v, dict)},
        },
        'run': {'id': row.pk, 'trigger': row.trigger, 'started_at': row.started_at.isoformat(),
                'finished_at': row.finished_at.isoformat() if row.finished_at else None, 'result': row.result,
                'commit_gate': {'passes': ok, 'required': list(required_steps(conn)),
                                'failing': [f.get('id') for f in failures]},
                'steps': [_export_step(s) for s in (row.steps or []) if isinstance(s, dict)]},
    }
    audit_log.record('diagnostics.export', fmt, connection=conn, user=user, app=conn.remote_installation_id,
                     detail={'run': row.pk, 'format': fmt})
    stamp = row.started_at.strftime('%Y%m%dT%H%M%S')
    name = f'connect-diagnostics-{str(conn.pk)[:8]}-{stamp}'
    if fmt == 'text':
        return f'{name}.txt', 'text/plain; charset=utf-8', _as_text(doc).encode()
    return f'{name}.json', 'application/json', json.dumps(doc, indent=2, sort_keys=True).encode()


def _as_text(doc) -> str:
    c, r = doc['connection'], doc['run']
    lines = [f'Agit8or Connect diagnostics — {c["name"] or c["app_type"]} ({c["id"]})',
             f'Status: {c["status"]}   Direction: {c["direction"]}   Protocol: {c["protocol"]}'
             f'{"   Quick Connect" if c["quick_connect"] else ""}',
             f'Address: {c["base_url"]}   Installation: {c["remote_installation_id"]}',
             f'Run {r["id"]} ({r["trigger"]}) {r["started_at"]} -> {r["result"] or "running"}; commit gate '
             + ('passes' if r['commit_gate']['passes'] else 'fails: ' + ', '.join(r['commit_gate']['failing'])),
             f'Exported {doc["exported_at"]}', '']
    for s in r['steps']:
        lines.append(f'{s.get("n", "?"):>2}. [{s.get("status", "")}] {s.get("name", "")}'
                     + (f' ({s["code"]})' if s.get('code') else ''))
        if s.get('explanation'):
            lines.append(f'    {s["explanation"]}')
        if s.get('next_action'):
            lines.append(f'    Next: {s["next_action"]}')
        for k, v in (s.get('data') or {}).items():
            lines.append(f'    {k}: {", ".join(map(str, v)) if isinstance(v, list) else v}')
    lines += ['', 'Redacted: no token, assertion, proof, code, signature or key is included.']
    return '\n'.join(lines) + '\n'
