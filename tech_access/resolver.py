"""
The one answer to "may this technician do X here, now?".

    decide(user, organization, capability, ticket=None, asset=None) -> Decision

Order, first match wins:

  1. Locked safeguards are always Locked.
  2. Anyone who isn't an active MSP technician gets Off. Customer portal
     users are outside technician access.
  3. A technician under active containment gets Off.
  4. A ticket or asset from another customer than `organization` gets Off.
  5. An explicit deny (at this customer or everywhere) gets Off.
  6. A customer restriction gets Off.
  7. The integration can't do it here → Unavailable.
  8. Otherwise each live assignment at this customer — the technician's own
     and their groups' — is evaluated on its own, scope included; the best
     result wins. One assignment's capability is never combined with another
     assignment's scope (review_others on assignment A doesn't widen
     assignment B).
  9. No live assignment → Off.

Nothing is cached: every call reads the current rows, so demotion,
reassignment, expiry and policy changes apply to the next call, including
a call made while a job sits in a queue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from django.db.models import Q
from django.utils import timezone

from . import catalog

LOCKED, UNAVAILABLE = 'locked', 'unavailable'


@dataclass
class Decision:
    state: str
    reason: str
    source: str = ''
    capability: str = ''
    notes: List[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.state == catalog.ALLOWED

    @property
    def requestable(self) -> bool:
        return self.state == catalog.REQUEST

    def __bool__(self):
        return self.allowed

    @property
    def label(self) -> str:
        if self.state == LOCKED:
            return 'Locked'
        if self.state == UNAVAILABLE:
            return 'Unavailable'
        return catalog.STATE_LABELS.get(self.state, self.state)


def is_technician(user) -> bool:
    from psa.visibility import is_msp_staff
    return bool(user is not None and getattr(user, 'is_authenticated', False)
                and getattr(user, 'is_active', False) and is_msp_staff(user))


def active_containment(user):
    from .models import Containment
    return Containment.objects.filter(user=user, lifted_at__isnull=True).order_by('-created_at').first()


def live_assignments(user, organization, now=None):
    from .models import AccessAssignment
    return (AccessAssignment.objects.live(now)
            .filter(organization=organization)
            .filter(Q(user=user) | Q(group__members=user))
            .select_related('preset', 'group')
            .distinct()
            .order_by('pk'))


def _deny(user, organization, capability, now):
    from .models import ExplicitDeny
    return (ExplicitDeny.objects
            .filter(user=user, capability__in=[capability, '*'])
            .filter(Q(organization=organization) | Q(organization__isnull=True))
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .first())


def _restricted(organization, capability) -> bool:
    from .models import CustomerAccessPolicy
    policy = CustomerAccessPolicy.objects.filter(organization=organization).first()
    return bool(policy and capability in (policy.restricted or []))


def unavailable_reason(capability, organization) -> str:
    """'' if the integrations at this customer can support `capability`.

    Ticket AI needs nothing beyond its own settings (checked by the AI
    paths themselves). RMM, remote and fix capabilities need a live
    ticket-rmm-v1 pairing at this customer (any RMM provider) whose last
    capabilities check advertised what catalog.INTEGRATION_REQUIRES names —
    available exactly when one does."""
    need = catalog.INTEGRATION_REQUIRES.get(capability)
    if need is None:
        return ''
    from integrations.ticket_rmm import advertised, paired_connections
    conns = paired_connections(organization)
    if not conns:
        return 'No RMM is paired with this customer for ticket integration.'
    if not any(need in advertised(c) for c in conns):
        return f"This customer's paired RMM doesn't offer this (it hasn't advertised “{need}”)."
    return ''


def _evaluate(assignment, user, capability, ticket, asset) -> Decision:
    caps = assignment.preset.caps()
    where = f'{assignment.preset.name} ({assignment.subject_label})'
    state = caps.get(capability, catalog.OFF)
    if state == catalog.OFF:
        return Decision(catalog.OFF, f'{assignment.preset.name} does not include this.', where, capability)
    if capability in catalog.TICKET_SCOPED and ticket is not None and ticket.assigned_to_id != user.pk:
        if caps.get('review_others') != catalog.ALLOWED:
            return Decision(catalog.OFF, f'The ticket is not assigned to you, and {assignment.preset.name} '
                                         "doesn't cover other technicians' tickets.", where, capability)
    if capability == 'diagnostics_readonly' and asset is not None:
        if (asset.asset_type or '') not in catalog.STANDARD_WORKSTATION_TYPES:
            return Decision(catalog.OFF, 'Read-only diagnostics cover standard workstations only; '
                                         'this device needs advanced diagnostics.', where, capability)
    return Decision(state, f'Granted by {where}.', where, capability)


def decide(user, organization, capability, ticket=None, asset=None, now=None, integration=True) -> Decision:
    """`integration=False` skips the "does a paired RMM advertise this"
    check, for callers whose operation is not the advertised capability
    itself (rmm_permissions' alert.read_live: a service-level read of
    monitoring state that only borrows the read-only diagnostics grant)."""
    now = now or timezone.now()
    if capability in catalog.LOCKED:
        return Decision(LOCKED, catalog.LOCKED[capability][1], 'Mandatory safeguard', capability)
    if capability not in catalog.OPTIONAL:
        return Decision(catalog.OFF, 'Unknown capability.', '', capability)
    if not is_technician(user):
        return Decision(catalog.OFF, 'Only MSP technicians can use this. Customer portal users are outside '
                                     'technician access.', '', capability)
    if organization is None:
        return Decision(catalog.OFF, 'No customer given.', '', capability)
    held = active_containment(user)
    if held is not None:
        return Decision(catalog.OFF, f'Your access is contained pending review: {held.reason}',
                        'Containment', capability)
    for obj in (ticket, asset):
        if obj is not None and obj.organization_id != organization.pk:
            return Decision(catalog.OFF, 'That record belongs to a different customer.', '', capability)
    deny = _deny(user, organization, capability, now)
    if deny is not None:
        where = 'at every customer' if deny.organization_id is None else f'at {organization.name}'
        return Decision(catalog.OFF, f'Denied {where}' + (f': {deny.reason}' if deny.reason else '.'),
                        'Explicit deny', capability)
    if _restricted(organization, capability):
        return Decision(catalog.OFF, f'{organization.name} has switched this off for all technicians.',
                        'Customer restriction', capability)
    missing = unavailable_reason(capability, organization) if integration else ''
    if missing:
        return Decision(UNAVAILABLE, missing, 'Integration', capability)

    best: Optional[Decision] = None
    notes = []
    for a in live_assignments(user, organization, now):
        d = _evaluate(a, user, capability, ticket, asset)
        notes.append(f'{a.preset.name} via {a.subject_label}: {d.label}')
        if best is None or catalog.RANK[d.state] > catalog.RANK[best.state]:
            best = d
    if best is None:
        return Decision(catalog.OFF, f'You have no technician access assignment at {organization.name}.',
                        '', capability)
    best.notes = notes
    return best


def allowed(user, organization, capability, **kw) -> bool:
    return decide(user, organization, capability, **kw).allowed


def effective_access(user, organization) -> List[Decision]:
    """Every catalog entry for one technician at one customer, explained."""
    rows = [decide(user, organization, key) for key in catalog.OPTIONAL]
    rows += [decide(user, organization, key) for key in catalog.LOCKED]
    return rows


def has_any_assignment(user, organization) -> bool:
    return is_technician(user) and live_assignments(user, organization).exists()
