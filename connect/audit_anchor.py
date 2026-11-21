"""Anchoring the Connect audit chain into the main audit log (C-05;
DESIGN.md §12, roadmap 79.19/79.20, Quick Connect increment E).

Connect keeps its own SHA-256 chain (``connect_audit``, the protocol's
audit format, PROTOCOL.md §14). On its own that chain cannot show that its
newest rows were removed, or that the whole table was rewritten by someone
with database access: a re-computed chain verifies. So its head
(``seq``, ``hash``) is written into ``AuditLog`` (``object_type =
'connect_audit_anchor'``)

  * once an hour by the monitor job (only when the head moved, plus one a
    day while it did not, so the anchor trail itself shows the job ran), and
  * on every Security Block (so the evidence is pinned at once),

and audit/chain.py then seals that row into the HMAC chain keyed from
APP_MASTER_KEY. ``verify()`` re-computes the Connect chain and checks every
anchor of the retention window against it: a truncated, emptied or
rewritten ``connect_audit`` no longer contains the anchored (seq, hash).
``manage.py connect_verify_audit_chain`` runs this and the main chain's
verification, so one command covers both.

No new table: the anchors are ordinary AuditLog rows. No secret in them.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import List, Optional, Tuple

from django.utils import timezone

logger = logging.getLogger('connect')

OBJECT_TYPE = 'connect_audit_anchor'
EVERY = timedelta(hours=1)
UNCHANGED_EVERY = timedelta(hours=24)
VERIFY_ANCHORS = 2000


def head() -> Tuple[int, str]:
    from .models import ConnectAuditEvent
    last = ConnectAuditEvent.objects.order_by('-seq').only('seq', 'hash').first()
    return (last.seq, last.hash) if last else (0, '')


def _anchors():
    from audit.models import AuditLog
    return AuditLog.objects.filter(object_type=OBJECT_TYPE)


def latest():
    return _anchors().order_by('-pk').first()


def anchor(reason: str = 'hourly', *, connection=None):
    """Write the current head into AuditLog. Never raises; returns the row."""
    try:
        from audit.models import AuditLog
        seq, h = head()
        if not seq:
            return None
        extra = {'seq': seq, 'hash': h, 'reason': reason[:40]}
        if connection is not None:
            extra['connection'] = str(getattr(connection, 'pk', connection))
        return AuditLog.log(user=None, action='create', object_type=OBJECT_TYPE, object_id=seq,
                            object_repr=f'Agit8or Connect audit chain head #{seq}',
                            description=f'Agit8or Connect audit chain head #{seq} {h} ({reason})',
                            extra_data=extra)
    except Exception:
        logger.exception('could not anchor the Connect audit chain')
        return None


def maybe_anchor(now=None):
    """The monitor's hourly anchor."""
    now = now or timezone.now()
    last = latest()
    seq, _ = head()
    if not seq:
        return None
    if last is not None:
        age = now - last.timestamp
        if age < EVERY:
            return None
        if (last.extra_data or {}).get('seq') == seq and age < UNCHANGED_EVERY:
            return None
    return anchor('hourly')


def verify() -> List[str]:
    """Problems found (empty = intact): the Connect chain itself, then each
    anchor still in the audit log against the Connect chain."""
    from .models import ConnectAuditEvent
    from . import audit_log
    problems = []
    bad = audit_log.verify()
    if bad is not None:
        problems.append(f'Connect audit chain broken at entry {bad}')
    seq_now, _ = head()
    rows = list(_anchors().order_by('-pk').values_list('pk', 'extra_data')[:VERIFY_ANCHORS])
    wanted = {}
    for pk, extra in rows:
        try:
            s, h = int((extra or {}).get('seq')), str((extra or {}).get('hash') or '')
        except (TypeError, ValueError):
            problems.append(f'audit log entry {pk} is not a valid Connect anchor')
            continue
        wanted.setdefault(s, set()).add(h)
    have = dict(ConnectAuditEvent.objects.filter(seq__in=list(wanted)).values_list('seq', 'hash'))
    for s in sorted(wanted):
        if s > seq_now or s not in have:
            problems.append(f'anchored Connect entry #{s} is missing: the Connect audit chain was truncated '
                            f'(now ends at #{seq_now})')
        elif have[s] not in wanted[s] or len(wanted[s]) > 1:
            problems.append(f'anchored Connect entry #{s} has a different hash: the Connect audit chain was '
                            'rewritten')
        if len(problems) >= 20:
            break
    return problems


def verify_main() -> Tuple[Optional[bool], List[str]]:
    """The main AuditLog HMAC chain (audit/chain.py), which seals the anchors."""
    try:
        from audit import chain
        return chain.verify(record=False)
    except Exception as e:
        logger.exception('could not verify the main audit chain')
        return None, [f'main audit chain could not be verified: {type(e).__name__}']
