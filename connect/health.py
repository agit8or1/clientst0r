"""Connection health, automatic reconnection and the security-failure rule
(Quick Connect increment D; DESIGN.md §4.2, §7.3, §8.2, §8.3; roadmap 79.16,
79.17).

Light check of an ``active`` connection (every ``monitor_interval_s``,
default 60 s, ±10 % jitter), five separate dimensions:

  transport      DNS resolves, TCP connects            (availability)
  tls            TLS handshake                         (availability)
                 certificate valid / name / SPKI pin   (security)
  authenticated  token issued with the active key      (peer_revoked, key_revoked: security)
  authorised     one harmless authorised call (v1 POST test, which every peer
                 answers; the qc-diagnostics probe is used by diagnostics)
  operational    events are accepted (no dead letter in the last hour)

Hysteresis: two failures -> Degraded; three transport / TLS failures (or no
full success for five minutes) -> Offline, circuit open; two passes ->
Connected again (from Offline: the half-open probe, then a second pass).

Backoff (per connection, persisted in ``retry_step`` / ``next_check_at``, so
a restart resumes where it was instead of hammering): 10 s, 30 s, 1 min,
2 min, 5 min, 10 min, 15 min, then 15 min, each ±20 % uniform jitter from
``secrets.SystemRandom``. While the circuit is open only the scheduled probe
runs; event deliveries are short-circuited without spending attempts.

Security failures (``SECURITY_CODES``) skip hysteresis: the connection is
Security Blocked at once with its evidence, ``next_check_at`` is cleared and
nothing reconnects by itself. Only an administrator's retest (through
``testing`` and the commit gate) brings it back. The same holds for
``suspended``, ``revoked`` and the kill switch: the monitor never selects
them.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from agit8or_connect.errors import ConnectError

logger = logging.getLogger('connect')

LADDER = (10, 30, 60, 120, 300, 600, 900)
BACKOFF_JITTER = 0.20
INTERVAL_JITTER = 0.10
MIN_INTERVAL, MAX_INTERVAL = 30, 900
DEGRADED_AFTER = 2
OFFLINE_AFTER = 3
RECOVER_AFTER = 2
NO_SUCCESS_OFFLINE = timedelta(minutes=5)
CLAIM_LEASE = timedelta(seconds=120)
AUTO_RETEST_WINDOW = timedelta(hours=2)
QUEUE_STALL = timedelta(hours=1)
DIMS = ('transport', 'tls', 'authenticated', 'authorised', 'operational')

# DESIGN.md §7.3: never retried automatically; an administrator decides.
SECURITY_CODES = frozenset({
    'destination_changed', 'blocked_destination', 'certificate_invalid', 'certificate_name_mismatch',
    'spki_mismatch', 'identity_changed', 'invalid_signature', 'peer_revoked', 'key_revoked',
    'source_not_authorised', 'scope_withdrawn', 'binding_mismatch',
})
# Availability: drive Degraded / Offline and the backoff ladder.
TRANSPORT_CODES = frozenset({
    'dns_nxdomain', 'dns_timeout', 'tcp_refused', 'tcp_timeout', 'tls_handshake', 'tls_version',
    'transport_error', 'probe_error', 'too_large', 'rate_limited', 'kill_switch', 'timeout', 'http_429',
})
# The subset that means the request never reached the other application.
NETWORK_CODES = frozenset({'dns_nxdomain', 'dns_timeout', 'tcp_refused', 'tcp_timeout', 'tls_handshake',
                           'tls_version', 'transport_error', 'timeout'})
# A refusal of our client at the other side's token endpoint for a
# connection it should know: it revoked it (or never had it).
PEER_REVOKED_CODES = frozenset({'invalid_client', 'connection_revoked', 'unknown_client'})

_rng = secrets.SystemRandom()


def jittered(seconds: float, spread: float, rng=None) -> float:
    r = rng or _rng
    return seconds * (1.0 + r.uniform(-spread, spread))


def backoff_delay(step: int, rng=None) -> float:
    return jittered(LADDER[max(0, min(step, len(LADDER) - 1))], BACKOFF_JITTER, rng)


def interval_delay(conn, rng=None) -> float:
    base = max(MIN_INTERVAL, min(MAX_INTERVAL, int(conn.monitor_interval_s or 60)))
    return jittered(base, INTERVAL_JITTER, rng)


def classify(code: str, status: Optional[int] = None) -> str:
    """'security', 'transport' or 'other' for a failure code."""
    code = str(code or '')
    if code in SECURITY_CODES:
        return 'security'
    if code in TRANSPORT_CODES or code.startswith('http_5') or (status is not None and (status >= 500 or
                                                                                         status == 429)):
        return 'transport'
    return 'other'


def token_failure_code(e: ConnectError) -> str:
    """Map a refusal at the other side's token endpoint onto §7.3."""
    if e.code in PEER_REVOKED_CODES:
        return 'peer_revoked'
    return e.code


@dataclass
class CheckResult:
    ok: bool
    kind: str = 'ok'                 # ok | transport | other | security
    code: str = ''
    message: str = ''
    dims: dict = field(default_factory=dict)       # dim -> (ok, code)
    evidence: dict = field(default_factory=dict)

    @classmethod
    def fail(cls, dim, code, message, dims=None, evidence=None, kind=None, status=None):
        d = dict(dims or {})
        d[dim] = (False, code)
        return cls(False, kind or classify(code, status), code, message, d, evidence or {})


# --- the light check ---------------------------------------------------------------------

def _network(conn, dims) -> Optional[CheckResult]:
    from . import destinations, transport
    d = destinations.get(conn)
    try:
        pv = transport.probe(conn.base_url, allow_private=bool(d and d.has_private),
                             ca_pem=(d.ca_bundle if d else '') or conn.tls_ca_bundle)
    except Exception:   # the probe never raises by contract; a defect is an availability failure here
        logger.exception('health probe failed for %s', conn.pk)
        return CheckResult.fail('transport', 'probe_error', 'The network check could not run.', dims)
    code = getattr(pv, 'code', '') or ''
    host = pv.host or destinations.host_port(conn.base_url)[0]
    if not pv.addresses:
        if code == 'blocked_destination':
            return CheckResult.fail('transport', 'destination_changed',
                                    f'{host} now resolves to an address Agit8or Connect never connects to.',
                                    dims, {'host': host})
        return CheckResult.fail('transport', code or 'dns_nxdomain', pv.error or f'{host} did not resolve.', dims)
    outside = [a for a in pv.addresses if not (d and destinations.contains(d.addresses, a))]
    if outside:
        return CheckResult.fail('transport', 'destination_changed', destinations.message(
            'destination_changed', conn, {'addresses': outside, 'host': host}), dims,
            {'addresses': outside, 'host': host, 'cert_names': list(pv.cert_names or [])})
    if code.startswith('tcp_'):
        return CheckResult.fail('transport', code, pv.error or 'The port did not answer.', dims)
    dims['transport'] = (True, '')
    if code.startswith('certificate'):
        return CheckResult.fail('tls', code, pv.error or 'The certificate was not accepted.', dims,
                                {'host': host, 'cert_names': list(pv.cert_names or [])})
    if code or pv.error:
        return CheckResult.fail('tls', code if code in ('tls_handshake', 'tls_version') else 'tls_handshake',
                                pv.error or 'TLS handshake failed.', dims)
    if d and d.spki_pins and pv.spki and pv.spki not in d.spki_pins:
        return CheckResult.fail('tls', 'spki_mismatch', destinations.message('spki_mismatch', conn), dims,
                                {'spki': pv.spki, 'host': host})
    dims['tls'] = (True, '')
    return None


def _call_failure(dim, e: ConnectError, dims) -> CheckResult:
    code = e.code
    if dim == 'authenticated':
        code = token_failure_code(e)
    if code in ('http_403',) and dim == 'authenticated':
        code = 'token_refused'
    if code in NETWORK_CODES:
        # The call never reached the other application (it went down
        # after the probe): a transport failure, not a refusal.
        dim = 'transport'
    return CheckResult.fail(dim, code, e.message or code, dims, status=e.status)


def _operation(conn, dims) -> Optional[CheckResult]:
    """v1 ``POST test``: answered by every peer (v1 and 1.1 alike), so the
    check is the same for a Rem0te link and a Quick Connect one. The 1.1
    probe is used by diagnostics (step 8 / 14), where its answer matters."""
    from . import client
    url = conn.endpoint('test')
    if not url:
        dims['authorised'] = (True, '')
        return None
    try:
        r = client.call(conn, 'POST', url)
    except ConnectError as e:
        return _call_failure('authorised', e, dims)
    if 200 <= r.status < 300:
        dims['authorised'] = (True, '')
        return None
    return _status_failure(r, dims)


def _status_failure(r, dims) -> CheckResult:
    body = r.body or b''
    if r.status == 403 and b'source_not_authorised' in body:
        return CheckResult.fail('authorised', 'source_not_authorised', 'The other application refused this '
                                'server\'s source address.', dims)
    if r.status in (401, 403):
        code = 'insufficient_scope' if r.status == 403 else 'invalid_token'
        return CheckResult.fail('authorised' if r.status == 403 else 'authenticated', code,
                                f'The other application answered HTTP {r.status}.', dims)
    return CheckResult.fail('authorised', f'http_{r.status}', f'The other application answered HTTP {r.status}.',
                            dims, status=r.status)


def _operational(conn, dims, now) -> Optional[CheckResult]:
    """Events are not failing: no dead letter in the last hour (the time a
    dead letter is made is kept in its next_attempt_at)."""
    from .models import OutboundEvent
    if OutboundEvent.objects.filter(connection=conn, status=OutboundEvent.DEAD,
                                    next_attempt_at__gte=now - QUEUE_STALL).exclude(event_type='connect.test').exists():
        return CheckResult.fail('operational', 'event_rejected',
                                'Events to the other application were refused in the last hour (see Events sent).',
                                dims)
    dims['operational'] = (True, '')
    return None


def light_check(conn, now=None) -> CheckResult:
    """One health check of an active connection. Never raises for a peer
    failure; security failures are reported, the caller blocks."""
    from . import client
    now = now or timezone.now()
    dims = {}
    res = _network(conn, dims)
    if res is not None:
        return res
    committed = set(conn.outbound_scopes or [])
    try:
        tok = client.get_token(conn)
    except ConnectError as e:
        return _call_failure('authenticated', e, dims)
    granted = set(str(tok.get('scope', '')).split())
    if not tok.get('cached') and committed - granted:
        return CheckResult.fail('authenticated', 'scope_withdrawn', 'The other application issued a token with '
                                'fewer permissions than were committed.', dims,
                                {'missing_scopes': sorted(committed - granted)})
    dims['authenticated'] = (True, '')
    res = _operation(conn, dims)
    if res is not None:
        return res
    res = _operational(conn, dims, now)
    if res is not None:
        return res
    return CheckResult(True, 'ok', '', '', dims)


# --- applying a result ---------------------------------------------------------------------

def _update_dims(conn, res, now):
    dims = dict(conn.health_dims or {})
    iso = now.isoformat()
    for dim, (ok, code) in res.dims.items():
        cur = dict(dims.get(dim) or {})
        if cur.get('ok') is not ok:
            cur['since'] = iso
        cur['ok'] = ok
        cur['code'] = '' if ok else str(code)[:40]
        cur['last_ok' if ok else 'last_fail'] = iso
        dims[dim] = cur
    # Dimensions after the failing one were not reached this time.
    return dims


def _last_full_success(conn):
    from django.utils.dateparse import parse_datetime
    v = ((conn.health_dims or {}).get('authorised') or {}).get('last_ok')
    return parse_datetime(v) if v else None


def apply(conn, res: CheckResult, now=None, rng=None):
    """Hysteresis, backoff and the circuit; persisted at once."""
    from .models import Connection as C
    from . import alerts, audit_log
    now = now or timezone.now()
    if res.kind == 'security':
        security_failure(conn, res.code, res.evidence)
        return
    prev = conn.health
    conn.health_dims = _update_dims(conn, res, now)
    if res.ok:
        conn.consecutive_ok = min(conn.consecutive_ok + 1, 1000)
        conn.consecutive_fail = 0
        conn.retry_step = 0
        conn.circuit = C.CIRCUIT_CLOSED
        if conn.health in ('', C.HEALTH_CONNECTED) or conn.consecutive_ok >= RECOVER_AFTER:
            conn.health = C.HEALTH_CONNECTED
        delay = interval_delay(conn, rng) if conn.health == C.HEALTH_CONNECTED else backoff_delay(0, rng)
        conn.last_outbound_ok_at = now
        conn.last_error = ''
    else:
        conn.consecutive_ok = 0
        conn.consecutive_fail = min(conn.consecutive_fail + 1, 1000)
        last = _last_full_success(conn)
        stale = last is not None and now - last >= NO_SUCCESS_OFFLINE and conn.consecutive_fail >= DEGRADED_AFTER
        if res.kind == 'transport' and (conn.consecutive_fail >= OFFLINE_AFTER or stale):
            conn.health = C.HEALTH_OFFLINE
        elif conn.consecutive_fail >= DEGRADED_AFTER:
            if conn.health != C.HEALTH_OFFLINE or res.kind != 'transport':
                conn.health = C.HEALTH_DEGRADED
        elif not conn.health:
            conn.health = C.HEALTH_CONNECTED
        conn.circuit = C.CIRCUIT_OPEN if conn.health == C.HEALTH_OFFLINE else C.CIRCUIT_CLOSED
        delay = backoff_delay(conn.retry_step, rng)
        conn.retry_step = min(conn.retry_step + 1, len(LADDER) - 1)
        conn.last_failure_at = now
        conn.last_error = (res.message or res.code)[:500]
    conn.last_check_at = now
    conn.next_check_at = now + timedelta(seconds=delay)
    n = C.objects.filter(pk=conn.pk, state=C.ACTIVE).update(
        health=conn.health, health_dims=conn.health_dims, consecutive_ok=conn.consecutive_ok,
        consecutive_fail=conn.consecutive_fail, retry_step=conn.retry_step, circuit=conn.circuit,
        last_check_at=now, next_check_at=conn.next_check_at, last_error=conn.last_error,
        last_failure_at=conn.last_failure_at, last_outbound_ok_at=conn.last_outbound_ok_at)
    if not n:
        return   # changed state meanwhile (suspended, revoked, blocked): nothing to schedule
    if prev != conn.health:
        audit_log.record('connection.health', conn.health or 'unknown', connection=conn,
                         app=conn.remote_installation_id,
                         detail={'from': prev or 'unknown', 'to': conn.health, 'code': res.code,
                                 'consecutive_fail': conn.consecutive_fail, 'circuit': conn.circuit})
    alerts.observe(conn, code=res.code)


def security_failure(conn, code: str, evidence=None, user=None) -> bool:
    """§7.3: Security Blocked now, evidence kept, nothing scheduled."""
    from . import destinations
    return destinations.security_block(conn, code, evidence, user=user)


# --- scheduling helpers ----------------------------------------------------------------------

def on_commit_fields(conn, now):
    """Set on the locked row inside commit_connection()."""
    from .models import Connection as C
    conn.health, conn.consecutive_ok, conn.consecutive_fail = C.HEALTH_CONNECTED, 0, 0
    conn.retry_step, conn.circuit, conn.retest_until = 0, C.CIRCUIT_CLOSED, None
    conn.next_check_at = now + timedelta(seconds=interval_delay(conn))
    conn.last_check_at = now
    conn.last_outbound_ok_at = now


def arm_retests(conn_pk, now=None):
    """A connection entering ``testing`` is retested automatically (backoff
    ladder) for AUTO_RETEST_WINDOW; after that an administrator runs it."""
    from .models import Connection as C
    now = now or timezone.now()
    C.objects.filter(pk=conn_pk).update(retry_step=0, retest_until=now + AUTO_RETEST_WINDOW,
                                        next_check_at=now + timedelta(seconds=backoff_delay(0)))


def note_delivery_trouble(conn):
    """An event delivery could not reach the peer: check it soon (the check,
    not each event, drives the backoff and the circuit)."""
    from django.db.models import Q
    from .models import Connection as C
    now = timezone.now()
    soon = now + timedelta(seconds=LADDER[0])
    C.objects.filter(pk=conn.pk, state=C.ACTIVE, circuit=C.CIRCUIT_CLOSED).filter(
        Q(next_check_at__isnull=True) | Q(next_check_at__gt=soon)).update(next_check_at=now)


def claim(conn, now=None) -> bool:
    """Compare-and-set on next_check_at: only one runner checks a
    connection; a crashed check is picked up again after the lease."""
    from .models import Connection as C
    now = now or timezone.now()
    return C.objects.filter(pk=conn.pk, state=conn.state, next_check_at=conn.next_check_at).update(
        next_check_at=now + CLAIM_LEASE) == 1


def retest_testing(conn, now=None, rng=None) -> str:
    """Automatic retest of a connection in ``testing`` (the other side had
    not approved yet, refused our source or token): the commit gate decides.
    Returns the state afterwards."""
    from .models import Connection as C
    from . import activation
    now = now or timezone.now()
    if conn.retest_until is None or conn.retest_until <= now:
        C.objects.filter(pk=conn.pk, state=C.TESTING).update(next_check_at=None)
        return conn.state
    try:
        activation.run_commit_test(conn, None)
    except activation.ActivationRefused:
        C.objects.filter(pk=conn.pk).update(next_check_at=None)
        return conn.state
    conn.refresh_from_db()
    if conn.state == C.TESTING:
        step = conn.retry_step
        nxt = now + timedelta(seconds=backoff_delay(step, rng))
        if conn.retest_until and nxt > conn.retest_until:
            nxt = None
        C.objects.filter(pk=conn.pk, state=C.TESTING).update(
            retry_step=min(step + 1, len(LADDER) - 1), next_check_at=nxt, last_check_at=now)
    elif conn.state != C.ACTIVE:
        C.objects.filter(pk=conn.pk).update(next_check_at=None)
    return conn.state


def check_one(conn, now=None, rng=None):
    """The monitor's unit of work for one claimed connection."""
    from .models import Connection as C
    now = now or timezone.now()
    if conn.state == C.TESTING:
        return retest_testing(conn, now, rng)
    if conn.state != C.ACTIVE:
        return conn.state
    if conn.circuit == C.CIRCUIT_OPEN:
        C.objects.filter(pk=conn.pk, state=C.ACTIVE).update(circuit=C.CIRCUIT_HALF_OPEN)
        conn.circuit = C.CIRCUIT_HALF_OPEN
    res = light_check(conn, now)
    apply(conn, res, now, rng)
    return conn.state


# --- administrator retest of a Security Blocked connection -------------------------------------

DESTINATION_BLOCKS = frozenset({'destination_changed', 'blocked_destination', 'spki_mismatch',
                                'certificate_name_mismatch'})


def admin_retest(conn, user=None) -> bool:
    """Security Blocked -> testing -> active only through the commit gate.
    A destination block needs an address approved after the block first;
    any other block is retested on the administrator's explicit request.
    Evidence is never cleared. Returns True when the connection is active."""
    from .models import Connection as C
    from . import activation, audit_log, destinations, identity
    conn.refresh_from_db()
    if conn.state != C.SECURITY_BLOCKED or identity.kill_switch_engaged():
        return False
    if conn.security_block_code in DESTINATION_BLOCKS:
        d = destinations.get(conn)
        since = int((conn.security_block_detail or {}).get('destination_version') or 0)
        if d is None or d.version <= since:
            return False
    now = timezone.now()
    if not C.objects.filter(pk=conn.pk, state=C.SECURITY_BLOCKED).update(state=C.TESTING, updated_at=now):
        return False
    arm_retests(conn.pk, now)
    conn.refresh_from_db()
    audit_log.record('connection.retest', 'testing', connection=conn, user=user, app=conn.remote_installation_id,
                     detail={'block_code': conn.security_block_code})
    try:
        report = activation.run_commit_test(conn, user)
    except activation.ActivationRefused:
        return False
    conn.refresh_from_db()
    if conn.state == C.ACTIVE:
        audit_log.record('connection.unblocked', 'ok', connection=conn, user=user,
                         detail={'block_code': conn.security_block_code, 'run_id': report.get('run_id', '')})
        return True
    return False
