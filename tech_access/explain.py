"""
"Why can this technician do this for this customer, who granted it, and
when does it expire?"

    explain(user, organization, capability) -> Explanation

The verdict is always `resolver.decide` — this module never decides
anything itself. It gathers every record that fed (or could have fed) that
decision, at this one customer only, with who set it, when, its expiry,
the protected change that approved it and its audit history (before/after
where the audit entry carries it):

  safeguard      a locked capability (nothing can switch it on)
  technician     why the account counts as an MSP technician at all:
                 superuser (and the approved Superuser grant, if any),
                 Django staff, or staff user type + global role template.
                 Required, but grants nothing on its own.
  membership     the technician's membership role at this customer.
                 Shown for completeness; it grants no technician-access
                 capability.
  containment    active theft-detection containment (blocks everything)
  deny           explicit denies at this customer or everywhere
                 (active and expired)
  restriction    the customer's restriction list
  pairing        each paired RMM at this customer and whether it
                 advertises what the capability needs
  assignment     every assignment at this customer for the technician or
                 one of their groups — active, expired and revoked — each
                 with the state its preset gives, the group membership that
                 carries it, and the preset's own change history

Nothing here reads another customer's rows: assignments, denies, policies,
pairings and memberships are all filtered to `organization` (or to
"everywhere" denies, which apply here).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional

from django.db.models import Q
from django.utils import timezone

from . import catalog
from .resolver import LOCKED, UNAVAILABLE, _evaluate, active_containment, decide, is_technician

HISTORY_LIMIT = 25

GRANTS, BLOCKS, REQUIRES, INFO, NOT_COUNTED = 'grants', 'blocks', 'requires', 'info', 'not counted'


@dataclass
class Source:
    kind: str
    label: str
    effect: str
    detail: str = ''
    status: str = ''
    state: str = ''
    decisive: bool = False
    granted_by: str = ''
    granted_at: object = None
    expires_at: object = None
    revoked_by: str = ''
    revoked_at: object = None
    record_url: str = ''
    approval: object = None  # ProtectedChange
    history: List[object] = field(default_factory=list)  # AuditLog rows
    assignment: object = None


@dataclass
class Explanation:
    user: object
    organization: object
    capability: str
    decision: object
    sources: List[Source]
    expires_at: object = None
    expiry_note: str = ''

    @property
    def outcome(self):
        return self.decision.state


def _name(user):
    return user.get_username() if user is not None else ''


def _audit(object_type, object_id, organization=None, extra_q=None, limit=HISTORY_LIMIT):
    from audit.models import AuditLog
    if object_id is None:
        return []
    qs = AuditLog.objects.filter(object_type=object_type, object_id=object_id).select_related('user')
    if extra_q is not None:
        qs = qs.filter(extra_q)
    return list(qs.order_by('-timestamp', '-pk')[:limit])


def _change_history(change):
    return _audit('protected_change', change.pk) if change is not None else []


def _approval_for_assignment(a):
    """The protected change that created `a`. Recorded on the row since
    the explain view shipped; older rows are matched by payload (same
    subject, customer and preset, applied before or when the row was made)."""
    if a.approved_change_id:
        return a.approved_change
    from .models import ProtectedChange
    candidates = ProtectedChange.objects.filter(kind='assignment', status=ProtectedChange.APPLIED,
                                                reviewed_at__lte=a.created_at + timedelta(minutes=1),
                                                reviewed_at__gte=a.created_at - timedelta(minutes=1))
    for c in candidates.select_related('requested_by', 'reviewed_by'):
        p = c.payload or {}
        if (p.get('organization') == a.organization_id and p.get('preset') == a.preset_id
                and p.get('user') == a.user_id and p.get('group') == a.group_id):
            return c
    return None


def _url(name, *args):
    from django.urls import NoReverseMatch, reverse
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


# --- sources -------------------------------------------------------------------

def _technician_source(user) -> Source:
    from .models import ProtectedChange
    reasons = []
    profile = getattr(user, 'profile', None)
    if user.is_superuser:
        reasons.append('superuser')
    if user.is_staff:
        reasons.append('Django staff flag')
    if profile is not None and profile.is_staff_user():
        tpl = profile.global_role_template
        reasons.append('MSP staff user type' + (f', global role “{tpl.name}”' if tpl else ', no global role'))
    ok = is_technician(user)
    src = Source('technician', 'MSP technician standing', REQUIRES if ok else BLOCKS,
                 detail=(f'Counts as an MSP technician because of: {", ".join(reasons)}. This is required but '
                         'grants no capability by itself; staff, admin and superuser flags never imply a preset.'
                         if ok else 'Not an active MSP technician, so technician access does not apply.'),
                 status='active' if ok else 'inactive', granted_at=user.date_joined,
                 record_url=_url('accounts:user_detail', user.pk))
    if user.is_superuser:
        change = (ProtectedChange.objects.filter(kind='superuser_grant', target_user=user,
                                                 status=ProtectedChange.APPLIED)
                  .select_related('requested_by', 'reviewed_by').order_by('-reviewed_at').first())
        if change is not None:
            src.approval = change
            src.granted_by = f'{_name(change.requested_by)} (approved by {_name(change.reviewed_by)})'
            src.granted_at = change.reviewed_at
    history = _audit('user', user.pk, extra_q=Q(description__icontains='superuser'))
    if profile is not None:
        history += _audit('user_profile', profile.pk)
    src.history = sorted(history, key=lambda e: (e.timestamp, e.pk), reverse=True)[:HISTORY_LIMIT]
    if not src.granted_by and src.history:
        first = src.history[-1]
        src.granted_by = first.username or '(system)'
    return src


def _membership_source(user, organization) -> Optional[Source]:
    from accounts.models import Membership
    m = (Membership.objects.filter(user=user, organization=organization)
         .select_related('role_template', 'invited_by').first())
    if m is None:
        return Source('membership', f'Membership at {organization.name}', INFO,
                      detail='No membership at this customer. Technician access does not need one.')
    role = m.role_template.name if m.role_template_id else m.get_role_display()
    return Source('membership', f'Membership at {organization.name}: {role}', INFO,
                  detail='Customer membership roles control ordinary pages (documents, assets, tickets); they '
                         'grant no ticket AI or RMM capability.',
                  status='active' if m.is_active else 'inactive', granted_by=_name(m.invited_by),
                  granted_at=m.created_at, history=_audit('membership', m.pk))


def _containment_source(user, now) -> Optional[Source]:
    held = active_containment(user)
    if held is None:
        return None
    return Source('containment', 'Containment (theft detection)', BLOCKS, detail=held.reason, status='active',
                  granted_by='theft detection' if held.alert_id else '', granted_at=held.created_at,
                  history=_audit('tech_access_containment', held.pk))


def _deny_sources(user, organization, capability, now) -> List[Source]:
    from .models import ExplicitDeny
    out = []
    qs = (ExplicitDeny.objects.filter(user=user, capability__in=[capability, '*'])
          .filter(Q(organization=organization) | Q(organization__isnull=True))
          .select_related('created_by').order_by('-created_at'))
    for d in qs:
        live = d.expires_at is None or d.expires_at > now
        where = 'every customer' if d.organization_id is None else organization.name
        out.append(Source('deny', f'Explicit deny of {"everything" if d.capability == "*" else "this"} at {where}',
                          BLOCKS if live else NOT_COUNTED, detail=d.reason,
                          status='active' if live else 'expired', granted_by=_name(d.created_by),
                          granted_at=d.created_at, expires_at=d.expires_at,
                          record_url=_url('tech_access:index') + '#denies',
                          history=_audit('tech_access_deny', d.pk)))
    return out


def _restriction_source(organization, capability) -> Optional[Source]:
    from .models import CustomerAccessPolicy
    policy = CustomerAccessPolicy.objects.filter(organization=organization).first()
    if policy is None:
        return None
    on = capability in (policy.restricted or [])
    history = _audit('tech_access_customer_policy', policy.pk)
    if not on and not any(capability in str(e.extra_data or '') or capability in e.description for e in history):
        return None
    return Source('restriction', f'Customer restriction at {organization.name}', BLOCKS if on else NOT_COUNTED,
                  detail=('Switched off at this customer for every technician.' if on
                          else 'Was restricted here before; not restricted now.'),
                  status='active' if on else 'lifted', granted_at=policy.updated_at,
                  record_url=_url('tech_access:index') + '#customers', history=history)


def _pairing_sources(organization, capability) -> List[Source]:
    need = catalog.INTEGRATION_REQUIRES.get(capability)
    if need is None:
        return []
    from integrations.models import RMMConnection
    from integrations.ticket_rmm import advertised, is_processor
    from .models import ProtectedChange
    out = []
    conns = list(RMMConnection.objects.filter(organization=organization).order_by('pk'))
    approvals = list(ProtectedChange.objects.filter(kind='business_mapping', status=ProtectedChange.APPLIED)
                     .select_related('requested_by', 'reviewed_by').order_by('-reviewed_at'))
    for conn in conns:
        try:
            paired = conn.is_active and is_processor(conn)
            has = paired and need in advertised(conn)
        except Exception:  # noqa: BLE001 — a broken pairing explains as unpaired
            paired = has = False
        if not paired and not any((c.payload or {}).get('connection') == conn.pk for c in approvals):
            continue  # an RMM connection that was never paired for tickets is not a source
        approval = next((c for c in approvals if (c.payload or {}).get('connection') == conn.pk), None)
        out.append(Source(
            'pairing', f'Paired RMM “{conn.name}” ({conn.get_provider_type_display()})',
            REQUIRES if has else BLOCKS,
            detail=(f'Advertises “{need}”, which this capability needs.' if has else
                    (f'Paired, but has not advertised “{need}”.' if paired else
                     'Ticket integration pairing is not live (disabled, unchecked or failing).')),
            status='active' if paired else 'inactive',
            granted_by=(f'{_name(approval.requested_by)} (approved by {_name(approval.reviewed_by)})'
                        if approval else ''),
            granted_at=approval.reviewed_at if approval else None, approval=approval,
            record_url=_url('integrations:rmm_detail', conn.pk),
            history=_audit('rmm_connection', conn.pk)))
    if not out:
        out.append(Source('pairing', 'Paired RMM', BLOCKS,
                          detail=f'No RMM is paired with {organization.name} for ticket integration, and this '
                                 f'capability needs one that advertises “{need}”.', status='none'))
    return out


def _group_membership_history(group, user):
    entries = _audit('tech_access_group', group.pk, limit=200)
    mine = [e for e in entries if user.pk in ((e.extra_data or {}).get('users') or [])
            or user.get_username() in (e.description or '')]
    return mine[:HISTORY_LIMIT]


def _assignment_sources(user, organization, capability, now):
    from .models import AccessAssignment
    group_ids = list(user.technician_groups.values_list('pk', flat=True))
    qs = (AccessAssignment.objects.filter(organization=organization)
          .filter(Q(user=user) | Q(group_id__in=group_ids))
          .select_related('preset', 'group', 'granted_by', 'revoked_by', 'approved_change__requested_by',
                          'approved_change__reviewed_by')
          .order_by('-created_at', '-pk'))
    out = []
    for a in qs:
        status = a.status(now)
        state = _evaluate(a, user, capability, None, None).state
        if status != 'active':
            effect = NOT_COUNTED
        else:
            effect = GRANTS if state != catalog.OFF else INFO
        approval = _approval_for_assignment(a)
        history = _audit('tech_access_assignment', a.pk) + _change_history(approval)
        detail = f'{a.preset.name} gives “{catalog.STATE_LABELS.get(state, state)}”.'
        if a.group_id:
            detail += f' Through group {a.group.name}.'
            history += _group_membership_history(a.group, user)
        if status == 'expired':
            detail += ' Expired — not counted.'
        elif status == 'revoked':
            detail += ' Revoked — not counted.'
        if a.note:
            detail += f' Note: {a.note}'
        history += _audit('tech_access_preset', a.preset_id, limit=10)
        history = sorted({e.pk: e for e in history}.values(), key=lambda e: (e.timestamp, e.pk), reverse=True)
        granted_by = _name(a.granted_by)
        if approval is not None and approval.reviewed_by_id:
            granted_by = f'{granted_by or _name(approval.requested_by)} (approved by {_name(approval.reviewed_by)})'
        out.append(Source('assignment', f'{a.preset.name} — {a.subject_label}', effect, detail=detail,
                          status=status, state=state, granted_by=granted_by, granted_at=a.created_at,
                          expires_at=a.expires_at, revoked_by=_name(a.revoked_by), revoked_at=a.revoked_at,
                          record_url=_url('tech_access:assignment_detail', a.pk), approval=approval,
                          history=history[:HISTORY_LIMIT], assignment=a))
    return out


# --- the answer -----------------------------------------------------------------

def explain(user, organization, capability, now=None) -> Explanation:
    now = now or timezone.now()
    decision = decide(user, organization, capability, now=now)
    sources: List[Source] = []
    if capability in catalog.LOCKED:
        sources.append(Source('safeguard', 'Mandatory safeguard', BLOCKS, detail=catalog.LOCKED[capability][1],
                              status='active', state=LOCKED, decisive=True))
        return Explanation(user, organization, capability, decision, sources,
                           expiry_note='Locked for everyone; it never expires.')

    tech = _technician_source(user)
    sources.append(tech)
    sources.append(_membership_source(user, organization))
    if not is_technician(user):
        tech.decisive = True
        return Explanation(user, organization, capability, decision, sources)

    cont = _containment_source(user, now)
    if cont:
        sources.append(cont)
    denies = _deny_sources(user, organization, capability, now)
    sources += denies
    restriction = _restriction_source(organization, capability)
    if restriction:
        sources.append(restriction)
    pairings = _pairing_sources(organization, capability)
    sources += pairings
    assignments = _assignment_sources(user, organization, capability, now)
    sources += assignments

    # Mark what decided it, following the resolver's order.
    expires_at, note = None, ''
    src = decision.source
    if src == 'Containment' and cont:
        cont.decisive = True
    elif src == 'Explicit deny':
        live = [d for d in denies if d.effect == BLOCKS]
        if live:
            live[0].decisive = True
            expires_at = live[0].expires_at
            note = 'The deny ends ' + (f'at {expires_at:%Y-%m-%d %H:%M}.' if expires_at else 'only when lifted.')
    elif src == 'Customer restriction' and restriction:
        restriction.decisive = True
        note = 'Applies until the customer restriction is lifted (a reviewed change).'
    elif decision.state == UNAVAILABLE:
        for p in pairings:
            p.decisive = True
        note = 'Unavailable until a paired RMM at this customer advertises what it needs.'
    else:
        live = [s for s in assignments if s.status == 'active']
        winners = [s for s in live if s.state == decision.state and decision.state != catalog.OFF]
        for s in winners:
            s.decisive = True
        if winners:
            if any(s.expires_at is None for s in winners):
                note = 'Does not expire: at least one assignment giving it has no expiry.'
            else:
                expires_at = max(s.expires_at for s in winners)
                note = f'Expires at {expires_at:%Y-%m-%d %H:%M} unless renewed (latest expiry of the ' \
                       'assignments giving it).'
            group_winners = [s for s in winners if s.assignment.group_id]
            if group_winners:
                note += ' Group assignments also end when the technician leaves the group.'
        elif not live:
            note = 'No live assignment at this customer.'
    return Explanation(user, organization, capability, decision, sources, expires_at=expires_at,
                       expiry_note=note)
