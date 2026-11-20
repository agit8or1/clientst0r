"""Second-administrator approval for elevated app permissions.

Granting a high_risk or admin scope to a connected application is a
protected change (tech_access.protected), and so is approving an inbound
request that claims the installation id of an application already connected
here (QC-12): proposed by one administrator,
confirmed by them with a fresh password, approved by a different approver
after re-authenticating, and applied in the same transaction. If the
connection's keys, scopes or grants changed after the proposal, applying it
is refused (fingerprint check).
"""
from __future__ import annotations

from tech_access.protected import ProtectedChangeError, applier


@applier('app_connection')
def _apply_app_connection(change, reviewer):
    from .models import Connection, PairingRequest
    from . import identity, pairing
    if identity.kill_switch_engaged():
        raise ProtectedChangeError('Connected applications are stopped by the emergency kill switch. Release it '
                                   'before approving this change.')
    p = change.payload
    conn = Connection.objects.filter(pk=p.get('connection')).first()
    if conn is None or conn.state != Connection.AWAITING_SECOND:
        raise ProtectedChangeError('The connection is no longer waiting for this approval.')
    grants = [(int(o), str(t), list(s)) for o, t, s in p.get('grants') or []]
    if p.get('fingerprint') != pairing.scope_fingerprint(conn, p.get('scopes') or [], grants):
        raise ProtectedChangeError('The connection changed after this was proposed. Approve it again from '
                                   'Connected Applications.')
    if p.get('mode') == 'inbound':
        preq = PairingRequest.objects.filter(connection=conn, status=PairingRequest.AWAITING_SECOND).first()
        if preq is None:
            raise ProtectedChangeError('The pairing request is no longer waiting for this approval.')
        preq.status = PairingRequest.PENDING
        pairing.finalize_inbound(preq, p['scopes'], grants, p.get('requested_scopes') or [], change.requested_by)
    else:
        pairing.finalize_local(conn, p['scopes'], grants, change.requested_by)
    # finalize_* re-check the kill switch; PairingFailed from them aborts the
    # protected change's transaction like ProtectedChangeError.
