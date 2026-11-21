"""
Permission and customer changes of an active connection (Quick Connect
increment C3, rest of roadmap 79.14; DESIGN.md §11): staged with a
server-side preview, approved, applied atomically, rolled back only by
narrowing.

  propose   a ConnectChange (kind ``permissions``) with the full target set:
            the scopes the other application may use here and each
            customer's tenant id and scopes. The preview lists what is
            gained and what is lost. Nothing changes yet.
  approve   fresh re-authentication. Narrowing, or adding non-elevated
            permissions / customers: this administrator. Adding a high_risk
            or admin scope: a tech_access protected change (kind
            ``app_connection``) that a different approver applies.
  apply     one transaction, refused if the connection's keys, scopes or
            customers changed since the proposal (fingerprint).
  rollback  the result is the intersection of the state before the change,
            the change itself and the state now: it never restores a
            permission or customer the change removed (that is a new,
            approved change).

Only what an administrator here approves is ever granted to the other
application: a scope it grants us does not imply anything here, it cannot
request more than it was granted (token endpoint), and it never gains a
scope it did not ask for in the pairing.
"""
from __future__ import annotations

import hashlib
import json
from typing import List, Tuple

from django.db import transaction
from django.utils import timezone

from . import audit_log, catalog, identity


class PermissionChangeRefused(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _current(conn) -> dict:
    grants = sorted([g.organization_id, g.remote_tenant_id, sorted(g.scopes or [])]
                    for g in conn.tenant_grants.filter(active=True))
    return {'scopes': sorted(set(conn.inbound_scopes or [])), 'grants': grants}


def _fingerprint(conn, payload) -> str:
    from . import store
    raw = json.dumps({'connection': str(conn.pk), 'payload': payload, 'now': _current(conn),
                      'keys': sorted(store.remote_keyring(conn))}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _diff(before: dict, after: dict) -> Tuple[List[str], List[str], List[str]]:
    """(gains, loses, elevated scopes gained)."""
    gains, loses = [], []
    bs, as_ = set(before['scopes']), set(after['scopes'])
    gains += [f'permission {s}' for s in sorted(as_ - bs)]
    loses += [f'permission {s}' for s in sorted(bs - as_)]
    bg = {int(o): (t, set(sc)) for o, t, sc in before['grants']}
    ag = {int(o): (t, set(sc)) for o, t, sc in after['grants']}
    gained_scopes = set(as_ - bs)
    for o, (t, sc) in ag.items():
        if o not in bg:
            gains.append(f'customer {o} as {t} ({", ".join(sorted(sc)) or "no permissions"})')
            gained_scopes |= sc
            continue
        bt, bsc = bg[o]
        if bt != t:
            gains.append(f'customer {o} as {t} (was {bt})')
            loses.append(f'customer {o} as {bt}')
        if sc - bsc:
            gains.append(f'customer {o}: {", ".join(sorted(sc - bsc))}')
            gained_scopes |= sc - bsc
        if bsc - sc:
            loses.append(f'customer {o}: {", ".join(sorted(bsc - sc))}')
    for o, (t, sc) in bg.items():
        if o not in ag:
            loses.append(f'customer {o} as {t}')
    return gains, loses, sorted(catalog.CATALOG.elevated(sorted(gained_scopes)))


def propose(conn, *, scopes, grants, user, note=''):
    """Stage the target permission set of an active connection."""
    from .models import Connection, ConnectChange
    from . import pairing
    if conn.state != Connection.ACTIVE:
        raise PermissionChangeRefused('Permissions can be changed only on an active connection.')
    scopes = sorted(set(scopes))
    try:
        pairing._check_grantable(scopes, conn.peer_requested_scopes)
        clean = pairing._validate_grants(scopes, grants)
    except pairing.PairingFailed as e:
        raise PermissionChangeRefused(e.message) from e
    before = _current(conn)
    after = {'scopes': scopes, 'grants': sorted([o, t, sorted(s)] for o, t, s in clean)}
    if after == before:
        raise PermissionChangeRefused('Nothing to change.')
    gains, loses, elevated = _diff(before, after)
    payload = {'before': before, 'after': after}
    change = ConnectChange.objects.create(
        connection=conn, kind=ConnectChange.PERMISSIONS, payload=payload,
        preview={'gains': gains, 'loses': loses, 'widening': bool(gains), 'elevated': elevated,
                 'second_admin': bool(elevated)},
        widening=bool(elevated), fingerprint=_fingerprint(conn, payload), proposed_by=user,
        base_version=identity.get().connect_policy_version, note=str(note or '')[:300])
    audit_log.record('permissions.proposed', 'pending', connection=conn, user=user, app=conn.remote_installation_id,
                     scopes=after['scopes'], detail={'change': change.pk, 'gains': gains, 'loses': loses,
                                                     'elevated': elevated})
    return change


def approve(change, request):
    from tech_access.protected import can_widen_at_all, propose as tp
    from .models import ConnectChange
    from .source_policy import ChangeRefused, _fresh
    user = request.user
    if change.status != ConnectChange.STAGED:
        raise ChangeRefused(f'This change is {change.get_status_display().lower()}.')
    if not _fresh(request):
        raise ChangeRefused('Re-enter your password to approve a permission change.')
    if _fingerprint(change.connection, change.payload) != change.fingerprint:
        raise ChangeRefused('The connection changed since this was proposed. Propose it again.')
    if change.preview.get('second_admin'):
        if not can_widen_at_all(user):
            raise ChangeRefused('High-risk or administrative permissions need a second administrator, and there is '
                                'none other than you.')
        name = change.connection.remote_display_name or change.connection.remote_app_type
        pc = tp('app_connection', f'Connected application "{name}": permission change #{change.pk} grants '
                + ', '.join(change.preview.get('elevated', []))[:200],
                {'connect_change': change.pk, 'fingerprint': change.fingerprint},
                [f'App permission {s}' for s in change.preview.get('elevated', [])], user, request=request)
        change.status, change.protected_change_id = ConnectChange.AWAITING_SECOND, pc.pk
        change.save(update_fields=['status', 'protected_change_id'])
        audit_log.record('permissions.second_approval_requested', 'pending', connection=change.connection,
                         user=user, detail={'change': change.pk, 'protected_change': pc.pk})
        return pc
    apply_change(change, user)
    return None


def _write(conn, target: dict, user):
    """Set scopes and customers to exactly ``target`` (caller's transaction)."""
    from .models import TenantGrant
    from . import pairing
    now = timezone.now()
    conn.inbound_scopes = sorted(set(target['scopes']))
    conn.inbound_event_types = pairing._event_types(conn.inbound_scopes)
    conn.save(update_fields=['inbound_scopes', 'inbound_event_types', 'updated_at'])
    wanted = {int(o): (t, sorted(s)) for o, t, s in target['grants']}
    for g in conn.tenant_grants.filter(active=True):
        if g.organization_id not in wanted:
            g.active, g.revoked_at, g.revoked_by = False, now, user
            g.save(update_fields=['active', 'revoked_at', 'revoked_by'])
            audit_log.record('tenant_grant.revoked', 'ok', connection=conn, user=user, tenant=g.remote_tenant_id,
                             detail={'organization_id': g.organization_id, 'via': 'permission change'})
    for org_id, (tenant, scopes) in wanted.items():
        g = TenantGrant.objects.filter(connection=conn, organization_id=org_id).first()
        if g is None:
            TenantGrant.objects.create(connection=conn, organization_id=org_id, remote_tenant_id=tenant,
                                       scopes=scopes, created_by=user)
        elif (g.remote_tenant_id, sorted(g.scopes or []), g.active) != (tenant, scopes, True):
            g.remote_tenant_id, g.scopes, g.active, g.revoked_at, g.revoked_by = tenant, scopes, True, None, None
            g.save()
        else:
            continue
        audit_log.record('tenant_grant.created', 'ok', connection=conn, user=user, tenant=tenant, scopes=scopes,
                         detail={'organization_id': org_id, 'via': 'permission change'})


def apply_change(change, approver, *, protected=False):
    from .models import Connection, ConnectChange
    from .source_policy import ChangeRefused, _audit_admin
    expected = ConnectChange.AWAITING_SECOND if protected else ConnectChange.STAGED
    with transaction.atomic():
        change = ConnectChange.objects.select_for_update().get(pk=change.pk)
        conn = Connection.objects.select_for_update().get(pk=change.connection_id)
        if change.status != expected:
            raise ChangeRefused('This change is no longer waiting to be applied.')
        if conn.state != Connection.ACTIVE:
            raise ChangeRefused('The connection is no longer active.')
        if change.preview.get('gains') and identity.kill_switch_engaged():
            raise ChangeRefused('Connected applications are stopped by the emergency kill switch.')
        if _fingerprint(conn, change.payload) != change.fingerprint:
            raise ChangeRefused('The connection changed since this was proposed. Propose it again.')
        _write(conn, change.payload['after'], approver)
        change.status, change.approved_by, change.applied_at = ConnectChange.APPLIED, approver, timezone.now()
        change.save(update_fields=['status', 'approved_by', 'applied_at'])
        audit_log.record('permissions.applied', 'ok', connection=conn, user=approver,
                         app=conn.remote_installation_id, scopes=conn.inbound_scopes,
                         detail={'change': change.pk, 'gains': change.preview.get('gains', []),
                                 'loses': change.preview.get('loses', []), 'second_administrator': protected})
    _audit_admin(approver, f'Agit8or Connect permission change #{change.pk} applied',
                 {'gains': change.preview.get('gains', []), 'loses': change.preview.get('loses', [])})
    return change


def reject(change, user):
    from .models import ConnectChange
    from .source_policy import ChangeRefused
    if change.status not in (ConnectChange.STAGED, ConnectChange.AWAITING_SECOND):
        raise ChangeRefused('This change is no longer waiting for a decision.')
    change.status = ConnectChange.REJECTED
    change.save(update_fields=['status'])
    audit_log.record('permissions.rejected', 'ok', connection=change.connection, user=user,
                     detail={'change': change.pk})


def narrowest(*states: dict) -> dict:
    """Intersection of permission states: scopes in all of them; a customer
    only when every state maps it to the same tenant, with the scopes common
    to all (and allowed by the resulting connection scopes)."""
    scopes = set(states[0]['scopes'])
    for st in states[1:]:
        scopes &= set(st['scopes'])
    maps = [{int(o): (t, set(sc)) for o, t, sc in st['grants']} for st in states]
    grants = []
    for o in sorted(set(maps[0]).intersection(*maps[1:])):
        tenants = {m[o][0] for m in maps}
        if len(tenants) != 1:
            continue
        sc = set.intersection(*(m[o][1] for m in maps)) & scopes
        grants.append([o, tenants.pop(), sorted(sc)])
    return {'scopes': sorted(scopes), 'grants': grants}


def rollback(change, request):
    """Undo an applied permission change without widening anything."""
    from .models import Connection, ConnectChange
    from .source_policy import ChangeRefused, _audit_admin, _fresh
    user = request.user
    if change.status != ConnectChange.APPLIED or change.kind != ConnectChange.PERMISSIONS or change.rollback_of_id:
        raise ChangeRefused('Only an applied permission change can be rolled back.')
    if not _fresh(request):
        raise ChangeRefused('Re-enter your password to roll back a permission change.')
    with transaction.atomic():
        conn = Connection.objects.select_for_update().get(pk=change.connection_id)
        now_state = _current(conn)
        target = narrowest(change.payload['before'], change.payload['after'], now_state)
        rb = ConnectChange.objects.create(
            connection=conn, kind=ConnectChange.PERMISSIONS, status=ConnectChange.APPLIED, widening=False,
            rollback_of=change, proposed_by=user, approved_by=user, applied_at=timezone.now(),
            payload={'before': now_state, 'after': target},
            preview={'gains': [], 'loses': _diff(now_state, target)[1], 'widening': False},
            note=f'Rollback of change #{change.pk} (narrowing only)')
        _write(conn, target, user)
        change.status = ConnectChange.ROLLED_BACK
        change.save(update_fields=['status'])
        audit_log.record('permissions.rolled_back', 'ok', connection=conn, user=user, scopes=target['scopes'],
                         detail={'change': change.pk, 'rollback': rb.pk, 'loses': rb.preview['loses']})
    _audit_admin(user, f'Agit8or Connect permission change #{change.pk} rolled back (narrowing only)',
                 {'rollback': rb.pk})
    return rb
