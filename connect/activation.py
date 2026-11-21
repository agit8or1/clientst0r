"""
Two-sided authorisation, network approval and the commit gate (Quick Connect
increment C3; DESIGN.md §4.1, §6.7, §9, §11.3; roadmap 79.13, 79.14, 79.25).
Fixes QC-07 / C-02: a connection is never active before a passing test.

Lifecycle after both administrators approved permissions and customers
(``pairing.finalize_local`` / ``finalize_inbound``):

  awaiting_network  this side approves the other side's source address(es)
                    for this connection: a staged ``ConnectChange``
                    (``on_commit``). One administrator with a fresh
                    re-authentication when it is exactly an address already
                    approved for this pairing; a second administrator
                    (tech_access protected change, kind ``app_connection``)
                    when it widens: another address, a range, or a private
                    address that was not approved as private. Approving
                    writes ``staged`` rows, which the source policy never
                    evaluates.
                    v1 code flow: the addresses the administrator typed for
                    the pairing are staged in the approval step itself, so
                    it passes straight through (DESIGN §4.1).
  testing           test window: the approved rows become ``temporary``
                    (at most TEST_WINDOW, re-armed by each run) so the other
                    side can run its own test against us. A testing
                    connection gets tokens and may call only the test
                    endpoints (capabilities, test, health) and send
                    ``connect.test``; customer data needs ``active``.
                    The connection test (lifecycle.test_connection(full=True):
                    DNS, approved destination, TCP, TLS, certificate,
                    discovery + identity, protocol, source address, token,
                    permissions, customer mapping, signed event) runs here,
                    then the full diagnostics (connect/diagnostics.py,
                    increment E): steps 1-13 must pass, and step 14
                    (reverse connectivity) too for a Quick Connect
                    connection (DESIGN §9.1); step 15 is informational.
  active            only through ``commit_connection`` with the id of a
                    passing run and of its passing diagnostics run, in ONE
                    transaction: approved rows active,
                    pairing / poll rules removed, destination active, state
                    active, policy version bumped. If anything fails nothing
                    is active.

A failed run never activates anything:

  * DNS / destination / TCP / TLS / certificate, or this side's own source
    rules  -> back to ``awaiting_network``: the test rows return to
    ``staged`` (no exposure kept), the approval stays;
  * the other installation answers with a different identity -> the
    attempt is rolled back (``failed``);
  * anything else (the other side has not approved yet, refused our source,
    token, permissions, events) -> stays ``testing`` with the reason; the
    test rows stay time-limited.

A scope granted by one side never implies the reverse: what the other
application may do here is ``inbound_scopes`` (only our approval sets it),
what we may do there is what its token endpoint grants. Permission changes
after activation are staged in connect/permissions.py.
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta
from typing import Iterable, List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import audit_log, identity

logger = logging.getLogger('connect')

TEST_WINDOW = timedelta(minutes=15)
MAX_PEER_SOURCES = 8

# First failing step -> where the connection goes.
NETWORK_STEP_IDS = frozenset({'dns', 'destination', 'tcp', 'tls', 'certificate'})
LOCAL_SOURCE_CODES = frozenset({'source_not_authorised_here'})
IDENTITY_CODES = frozenset({'identity_changed'})

FRIENDLY = {
    'kill_switch': 'Connected applications are stopped by the emergency kill switch.',
    'not_awaiting_network': 'This connection is not waiting for network authorization.',
    'not_testing': 'This connection is not being tested.',
    'no_passing_test': 'The connection test has not passed; nothing was activated.',
    'nothing_approved': 'Approve the other application\'s address for this connection first.',
    'invalid_purpose': 'Choose what the other application may reach: every Connect endpoint, or only discovery '
                       '(one-directional).',
}


class ActivationRefused(Exception):
    def __init__(self, code, message=''):
        super().__init__(message or FRIENDLY.get(code, code))
        self.code = code
        self.message = message or FRIENDLY.get(code, code)


def _refuse_if_stopped():
    if identity.kill_switch_engaged():
        raise ActivationRefused('kill_switch')


# --- what is already approved for this pairing --------------------------------------

def pairing_networks(conn) -> dict:
    """Addresses an administrator here already approved for this pairing
    (temporary pairing / poll rules of the connection): network -> private."""
    from .models import SourceRule as SR
    rows = SR.objects.filter(connection=conn, layer=SR.CONNECTION, action=SR.ALLOW, status=SR.TEMPORARY,
                             purpose__in=(SR.PAIRING, SR.POLL))
    return {r.network: r.private for r in rows}


def suggested_networks(conn) -> List[dict]:
    """What the network-authorization step offers: the addresses of this
    pairing (v1: typed by an administrator; Quick Connect: the other side's
    signed egress, approved here for the pairing)."""
    from . import source_policy
    out = []
    for net, private in sorted(pairing_networks(conn).items()):
        out.append({'net': net, 'private': private, 'installation_ok': source_policy.installation_allows(net)})
    return out


def is_widening(conn, entries) -> bool:
    """A second administrator is needed unless every entry is exactly an
    address already approved for this pairing (with the same private flag
    or less): a different address, a range or a newly private address
    widens access."""
    proven = pairing_networks(conn)
    for e in entries:
        net = e['network']
        n = ipaddress.ip_network(net)
        if net not in proven or n.prefixlen != n.max_prefixlen:
            return True
        if e.get('private') and not proven[net]:
            return True
    return False


def _parse(networks, private) -> List[tuple]:
    from . import source_policy
    if isinstance(networks, str):
        networks = networks.replace(',', '\n').splitlines()
    out = []
    for raw in networks or []:
        raw = str(raw).strip()
        if not raw:
            continue
        net, is_private = source_policy.validate_entry(raw, private=private)
        if net not in [n for n, _ in out]:
            out.append((net, is_private))
    if not out:
        raise ValidationError('Enter the address(es) the other application connects from.')
    if len(out) > MAX_PEER_SOURCES:
        raise ValidationError(f'At most {MAX_PEER_SOURCES} addresses.')
    return out


# --- approval of the other side's addresses (awaiting_network) ------------------------

def propose_peer_sources(conn, networks, user, *, purpose='all', private=False, note=''):
    """Stage the other application's source address(es) for this connection
    (the reverse direction, DESIGN §6.7). ``purpose`` 'all' (every Connect
    endpoint) or 'discovery' (one-directional: it may read our discovery
    only, which its own commit test needs). Nothing is allowed until the
    change is approved, and nothing is active until the commit."""
    from .models import Connection, SourceRule as SR
    from . import source_policy
    _refuse_if_stopped()
    if conn.state != Connection.AWAITING_NETWORK:
        raise ActivationRefused('not_awaiting_network')
    if purpose not in (SR.ALL, SR.DISCOVERY):
        raise ActivationRefused('invalid_purpose')
    nets = _parse(networks, private)
    add = [{'layer': SR.CONNECTION, 'connection': str(conn.pk), 'network': n, 'private': p, 'purpose': purpose,
            'description': ('Approved for the connection' if purpose == SR.ALL else
                            'Discovery only (one-directional)')} for n, p in nets]
    widening = is_widening(conn, add)
    change = source_policy.propose(add=add, user=user, connection=conn, on_commit=True, widening=widening,
                                   note=(note or 'The other application\'s address(es) for this connection')[:300])
    audit_log.record('network.peer_sources_proposed', 'pending', connection=conn, user=user,
                     app=conn.remote_installation_id,
                     detail={'change': change.pk, 'sources': [n for n, _ in nets], 'purpose': purpose,
                             'widening': widening})
    return change


def approve_change(change, request):
    """One administrator (fresh re-authentication) approves a non-widening
    reverse-rule change; a widening one opens a tech_access protected change
    (kind ``app_connection``) that a different approver applies. Returns the
    ProtectedChange or None."""
    from .models import ConnectChange
    from .source_policy import ChangeRefused, _fresh, fingerprint
    user = request.user
    if change.status != ConnectChange.STAGED:
        raise ChangeRefused(f'This change is {change.get_status_display().lower()}.')
    if identity.kill_switch_engaged():
        raise ChangeRefused(FRIENDLY['kill_switch'])
    if not _fresh(request):
        raise ChangeRefused('Re-enter your password to approve the other application\'s address.')
    if fingerprint(change.payload) != change.fingerprint:
        raise ChangeRefused('The rules changed since this was proposed. Propose it again.')
    if change.connection is None or change.connection.state != change.connection.AWAITING_NETWORK:
        raise ChangeRefused(FRIENDLY['not_awaiting_network'])
    if change.widening:
        from tech_access.protected import can_widen_at_all, propose as tp
        if not can_widen_at_all(user):
            raise ChangeRefused('This address widens access (another address, a range or a private address), '
                                'which needs a second administrator, and there is none other than you.')
        gains = change.preview.get('gains', [])
        pc = tp('app_connection', f'Agit8or Connect: allow {", ".join(gains)[:160]} for connection '
                                  f'"{change.connection.remote_display_name or change.connection.pk}" (applied when '
                                  'its connection test passes)',
                {'connect_change': change.pk, 'fingerprint': change.fingerprint},
                [f'Connect source {g}' for g in gains], user, request=request)
        change.status, change.protected_change_id = ConnectChange.AWAITING_SECOND, pc.pk
        change.save(update_fields=['status', 'protected_change_id'])
        audit_log.record('network.second_approval_requested', 'pending', connection=change.connection, user=user,
                         detail={'change': change.pk, 'protected_change': pc.pk})
        return pc
    approve_staged(change, user)
    return None


def approve_staged(change, approver, *, protected=False):
    """Approved: the rows are written as ``staged`` (never evaluated) and
    belong to this change until commit_connection() activates them. Also
    the tech_access applier for a widening reverse rule (``protected``)."""
    from .models import Connection, ConnectChange, InstallationIdentity, SourceRule as SR
    from .source_policy import ChangeRefused, _audit_admin, create_rules, fingerprint
    expected = ConnectChange.AWAITING_SECOND if protected else ConnectChange.STAGED
    with transaction.atomic():
        InstallationIdentity.objects.select_for_update().get(pk=identity.get().pk)
        change = ConnectChange.objects.select_for_update().get(pk=change.pk)
        if change.status != expected:
            raise ChangeRefused('This change is no longer waiting to be approved.')
        if fingerprint(change.payload) != change.fingerprint:
            raise ChangeRefused('The rules changed since this was proposed. Propose it again.')
        if identity.kill_switch_engaged():
            raise ChangeRefused(FRIENDLY['kill_switch'])
        conn = Connection.objects.select_for_update().get(pk=change.connection_id)
        if conn.state != Connection.AWAITING_NETWORK:
            raise ChangeRefused(FRIENDLY['not_awaiting_network'])
        rows = create_rules([{**e, 'connection': conn.pk, 'expires_at': None}
                             for e in change.payload.get('add', [])],
                            user=change.proposed_by, approver=approver, change=change, status=SR.STAGED)
        change.status, change.approved_by = ConnectChange.APPROVED, approver
        change.save(update_fields=['status', 'approved_by'])
        audit_log.record('network.peer_sources_approved', 'ok', connection=conn, user=approver,
                         app=conn.remote_installation_id,
                         detail={'change': change.pk, 'sources': [r.network for r in rows],
                                 'purpose': rows[0].purpose if rows else '', 'widening': change.widening,
                                 'second_administrator': bool(protected), 'active': 'after a passing test'})
        maybe_start_testing(conn, approver)
    _audit_admin(approver, f'Agit8or Connect: the other application\'s address approved for connection '
                           f'{conn.pk} (active only after a passing test)',
                 {'change': change.pk, 'sources': [r.network for r in rows]})
    return change


# --- state transitions ------------------------------------------------------------------

def enter_awaiting_network(conn, user=None):
    """Called by pairing._approved inside the approval's transaction."""
    from .models import Connection, SourceRule as SR
    conn.state = Connection.AWAITING_NETWORK
    conn.last_error = ''
    conn.save()
    audit_log.record('connection.awaiting_network', 'ok', connection=conn, user=user,
                     app=conn.remote_installation_id, detail={'quick_connect': bool(conn.qc_revision)})
    if not conn.qc_revision:
        # v1 code flow: the administrator typed the other application's
        # address(es) for this pairing; approving the pairing approves them
        # for the connection (still active only after a passing test).
        nets = pairing_networks(conn)
        if nets:
            from . import source_policy
            add = [{'layer': SR.CONNECTION, 'connection': str(conn.pk), 'network': n, 'private': p,
                    'purpose': SR.ALL, 'description': 'Approved with the pairing'} for n, p in sorted(nets.items())]
            change = source_policy.propose(add=add, user=user, connection=conn, on_commit=True, widening=False,
                                           note='Addresses approved with the pairing (v1 code flow)')
            approve_staged(change, user)
    maybe_start_testing(conn, user)
    conn.refresh_from_db(fields=['state', 'last_error'])


def _approved_rows(conn):
    from .models import ConnectChange, SourceRule as SR
    return SR.objects.filter(connection=conn, change__status=ConnectChange.APPROVED,
                             status__in=(SR.STAGED, SR.TEMPORARY))


def maybe_start_testing(conn, user=None) -> bool:
    """awaiting_network -> testing once this side approved the other side's
    address(es) and the destination has approved addresses. Opens the test
    window (approved rows temporary, at most TEST_WINDOW). DB only."""
    from .models import Connection, SourceRule as SR
    from . import destinations, source_policy
    with transaction.atomic():
        locked = Connection.objects.select_for_update().get(pk=conn.pk)
        if locked.state != Connection.AWAITING_NETWORK or identity.kill_switch_engaged():
            return False
        rows = _approved_rows(locked)
        if not rows.exists() or not destinations.ready(locked):
            return False
        until = timezone.now() + TEST_WINDOW
        n = rows.update(status=SR.TEMPORARY, expires_at=until)
        Connection.objects.filter(pk=conn.pk).update(state=Connection.TESTING, last_error='',
                                                     updated_at=timezone.now())
        source_policy._bump()
        from . import health
        health.arm_retests(conn.pk)    # the monitor retests while the other side finishes (D)
    conn.state, conn.last_error = Connection.TESTING, ''
    audit_log.record('connection.testing', 'ok', connection=conn, user=user, app=conn.remote_installation_id,
                     detail={'test_rules': n, 'until': until.isoformat()})
    return True


def back_to_awaiting_network(conn, reason='', user=None, message=''):
    """testing -> awaiting_network: the test rows go back to staged (not
    evaluated); the approval stays, so a retest re-opens the window."""
    from .models import Connection, SourceRule as SR
    from . import client, source_policy
    with transaction.atomic():
        n = Connection.objects.filter(pk=conn.pk, state=Connection.TESTING).update(
            state=Connection.AWAITING_NETWORK, last_error=(message or reason)[:500], last_failure_at=timezone.now(),
            updated_at=timezone.now())
        if not n:
            return False
        _approved_rows(conn).update(status=SR.STAGED, expires_at=None)
        source_policy._bump()
    conn.state = Connection.AWAITING_NETWORK
    conn.last_error = (message or reason)[:500]
    client.clear_cache(conn)
    audit_log.record('connection.test_window_closed', str(reason or 'failed')[:32], connection=conn, user=user,
                     app=conn.remote_installation_id)
    return True


def _extend_window(conn):
    from .models import SourceRule as SR
    from . import source_policy
    n = _approved_rows(conn).filter(status=SR.TEMPORARY).update(expires_at=timezone.now() + TEST_WINDOW)
    if n:
        source_policy._bump()


def after_approval(conn, user=None):
    """After a direct (one-administrator) approval: the initiator's peer has
    already approved, so the test can run now; the responder waits for the
    other side to finish its pairing first (an administrator runs the test,
    or it runs after the network approval)."""
    from .models import Connection
    conn.refresh_from_db()
    if conn.state == Connection.TESTING and conn.direction == Connection.OUTBOUND:
        try:
            run_commit_test(conn, user)
        except ActivationRefused:
            pass


def run_commit_test(conn, user=None) -> dict:
    """Run the connection test of a ``testing`` connection (from
    ``awaiting_network`` the window is re-opened first) and commit it when
    every required step passed. Returns the report."""
    from .models import Connection
    from . import client, lifecycle
    conn.refresh_from_db()
    _refuse_if_stopped()
    if conn.state == Connection.AWAITING_NETWORK:
        if not _approved_rows(conn).exists():
            raise ActivationRefused('nothing_approved')
        maybe_start_testing(conn, user)
        conn.refresh_from_db()
    if conn.state != Connection.TESTING:
        raise ActivationRefused('not_testing')
    _extend_window(conn)
    with client.retesting(conn):
        report = lifecycle.test_connection(conn, user, full=True)
    if report['ok']:
        report = _with_diagnostics(conn, report, user)
    if report['ok']:
        try:
            commit_connection(conn, report['run_id'], user)
        except ActivationRefused as e:
            report = {**report, 'ok': False, 'commit_error': e.message}
    else:
        _after_failure(conn, report, user)
    return report


DIAGNOSTICS_MAX_AGE = timedelta(minutes=15)


def _with_diagnostics(conn, report, user):
    """The commit gate's second half (DESIGN §9.1, §11.3): the fifteen
    diagnostic steps, of which every required one must pass. The run id is
    kept in the report (``last_test``), and commit_connection() checks it."""
    from .models import Connection, DiagnosticRun
    from . import diagnostics
    try:
        row = diagnostics.run(conn, user, trigger=DiagnosticRun.RETEST)
    except diagnostics.DiagnosticsRefused as e:
        checks = report['checks'] + [{'id': 'diagnostics', 'name': 'Diagnostics', 'ok': False, 'status': 'fail',
                                      'code': e.code, 'message': e.message, 'next_action': ''}]
        report = {**report, 'ok': False, 'checks': checks, 'diagnostic_run': None, 'diagnostics_ok': False}
    else:
        ok, failures = diagnostics.gate(row, conn)
        checks = list(report['checks'])
        if not ok:
            checks += [{'id': f.get('id', ''), 'name': f'Diagnostics: {f.get("name", "")}', 'ok': False,
                        'status': 'fail', 'code': f.get('code') or 'diagnostics_failed',
                        'message': f.get('explanation', ''), 'next_action': f.get('next_action', '')}
                       for f in failures]
        report = {**report, 'ok': bool(report['ok'] and ok), 'checks': checks, 'diagnostic_run': row.pk,
                  'diagnostics_ok': ok}
    conn.last_test = report
    Connection.objects.filter(pk=conn.pk).update(last_test=report, updated_at=timezone.now())
    return report


def _diagnostics_passed(conn, last) -> bool:
    from .models import DiagnosticRun
    from . import diagnostics
    run_pk = last.get('diagnostic_run')
    if not run_pk or not last.get('diagnostics_ok'):
        return False
    row = DiagnosticRun.objects.filter(pk=run_pk, connection=conn).first()
    if row is None or row.finished_at is None or timezone.now() - row.finished_at > DIAGNOSTICS_MAX_AGE:
        return False
    return diagnostics.gate(row, conn)[0]


def _after_failure(conn, report, user):
    failed = [c for c in report['checks'] if c['status'] == 'fail']
    first = failed[0] if failed else {'id': '', 'code': '', 'name': 'Test', 'message': ''}
    text = f'Connection test failed at "{first["name"]}": {first["message"]}'
    if first.get('next_action'):
        text += ' ' + first['next_action']
    from . import destinations, health
    if destinations.committed(conn):
        # A connection that was active before (resume, retest after a block):
        # a security failure blocks it again with new evidence; anything else
        # keeps it in testing and the monitor retests with backoff. Its
        # committed rules stay as they are (nothing re-opened, nothing removed).
        def security_code(c):
            code = c.get('code') or ''
            if c.get('id') == 'token' and code in health.PEER_REVOKED_CODES:
                return 'peer_revoked'
            return code if (code in IDENTITY_CODES or health.classify(code) == 'security') else ''
        sec = next((security_code(c) for c in failed if security_code(c)), '')
        if sec:
            destinations.security_block(conn, sec, {}, user=user)
            return
        from .models import Connection
        Connection.objects.filter(pk=conn.pk).update(last_error=text[:500], last_failure_at=timezone.now())
        conn.last_error = text[:500]
        return
    if first.get('code') in IDENTITY_CODES:
        from . import quick_connect
        quick_connect.rollback_attempt(conn, 'identity_changed', user)
        return
    if first.get('id') in NETWORK_STEP_IDS or first.get('code') in LOCAL_SOURCE_CODES:
        back_to_awaiting_network(conn, first.get('code') or 'network', user, message=text)
        return
    from .models import Connection
    Connection.objects.filter(pk=conn.pk).update(last_error=text[:500], last_failure_at=timezone.now())
    conn.last_error = text[:500]


def commit_connection(conn, run_id: str, user=None):
    """testing -> active, only with the id of the latest passing run, in one
    transaction (DESIGN §11.3): approved rows active, pairing and poll rules
    removed, destination active, state active, policy version bumped. If
    any part fails, nothing was activated."""
    from .models import ConnectChange, Connection, InstallationIdentity, SourceRule as SR
    from . import client, destinations, source_policy
    with transaction.atomic():
        InstallationIdentity.objects.select_for_update().get(pk=identity.get().pk)
        locked = Connection.objects.select_for_update().get(pk=conn.pk)
        if locked.state != Connection.TESTING:
            raise ActivationRefused('not_testing')
        if identity.kill_switch_engaged():
            raise ActivationRefused('kill_switch')
        last = locked.last_test or {}
        if not run_id or last.get('run_id') != run_id or not last.get('ok') or not last.get('full'):
            raise ActivationRefused('no_passing_test')
        if not _diagnostics_passed(locked, last):
            raise ActivationRefused('no_passing_test')
        now = timezone.now()
        approved = list(ConnectChange.objects.filter(connection=locked, status=ConnectChange.APPROVED))
        activated = list(_approved_rows(locked).values_list('network', flat=True))
        _approved_rows(locked).update(status=SR.ACTIVE, expires_at=None)
        ConnectChange.objects.filter(pk__in=[c.pk for c in approved]).update(status=ConnectChange.APPLIED,
                                                                            applied_at=now)
        removed = SR.objects.filter(connection=locked, status=SR.TEMPORARY, purpose__in=(SR.PAIRING, SR.POLL)
                                    ).update(status=SR.REMOVED, removed_at=now)
        first_commit = not destinations.committed(locked)
        destinations.activate(locked)
        locked.state, locked.last_error = Connection.ACTIVE, ''
        if first_commit or not locked.next_rotation_at:
            locked.next_rotation_at = now + timedelta(days=locked.rotation_interval_days or 90)
        from . import health
        health.on_commit_fields(locked, now)      # Connected; first health check one interval out (D)
        locked.save()
        source_policy._bump()
    conn.refresh_from_db()
    client.clear_cache(conn)
    from . import alerts
    alerts.observe(conn, user=user)
    audit_log.record('connection.committed', 'ok', connection=conn, user=user, app=conn.remote_installation_id,
                     scopes=conn.inbound_scopes,
                     detail={'run_id': run_id, 'diagnostic_run': (conn.last_test or {}).get('diagnostic_run'),
                             'sources': activated, 'pairing_rules_removed': removed,
                             'changes': [c.pk for c in approved]})
    source_policy._audit_admin(user, f'Agit8or Connect connection {conn.pk} committed after a passing test',
                               {'run_id': run_id, 'sources': activated})
    return conn


def status_hint(conn) -> str:
    """One line for the detail page and the wizard."""
    from .models import Connection
    if conn.state == Connection.AWAITING_NETWORK:
        if _approved_rows(conn).exists():
            return 'Approved here. Run the connection test (the destination needs approved addresses).'
        return 'Approve the other application\'s address for this connection, then the connection test runs.'
    if conn.state == Connection.TESTING:
        return ('Testing: the connection becomes active only when every check passes. If the other application '
                'has not finished its side yet, run the test again afterwards.')
    return ''
