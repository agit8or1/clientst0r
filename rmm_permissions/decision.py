"""
The one answer to "may this person do this RMM action here, now?".

    can(user, organization, action, device=None, ticket=None) -> Decision
        Pure: reads current rows, writes nothing. Use it to render buttons.

    rmm_action(user, organization, action, device=None, ticket=None,
               digest='', request=None) -> Decision
        The check every RMM operation makes right before it acts: the same
        decision, plus consuming a matching second-person approval when one
        is needed, plus an audit entry for the allow or the deny.

    require(...)  rmm_action, raising RMMPermissionDenied unless
                  `decision.permitted_now`.

    record_remote_refusal(decision, user, organization, code, ...)
        Rem0te (or another paired RMM) said no after ClientSt0r said yes.
        Returns a denying Decision and audits it. The RMM's refusal always
        wins; nothing here retries around it.

Evaluation order (first block wins; grants are only looked at after every
block has been checked, so a deny always beats an allow):

   1. Locked safeguards and unknown actions → no.
   2. Not an active MSP technician → no. Customer portal users never.
   3. Active theft-detection containment → no.
   4. Tenant: no customer for a device action, a device/ticket from another
      customer, a device with no customer, or a device whose connection
      belongs to another customer → no.
   5. A live deny override (this customer or every customer; this
      technician, their global role, or everyone) → no.
   6. Technician access (tech_access) for actions that map to one of its
      capabilities: an explicit deny, a customer restriction or an
      integration that can't do it → no. Unmapped actions: a '*' explicit
      deny → no.
   7. The device is managed by Rem0te and Rem0te's ticket-rmm-v1 contract
      has no route for the action → no.
   8. Grants, any of:
        a. the technician's role tier (global role template only), where
           the technician has a live technician-access assignment at this
           customer (device actions) — a tier never reaches a customer on
           its own; L1/L2 tiers cover only tickets assigned to the
           technician;
        b. the technician-access preset decision (unchanged behaviour);
        c. the permission flags these actions always used (legacy);
        d. an approved allow override at this customer.
      None → no.
   9. Constraints (workstation-only entries) → no if nothing is left.
  10. Approval: the best grant's approval level, raised by any live
      require-approval override. High-impact actions always need at
      least a peer.

Upgrade: every existing role template has no tier, there are no override
rows, and 8b/8c are exactly the checks those code paths made before, so
existing users get the same answers.
"""
from __future__ import annotations

from collections import namedtuple
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from django.utils import timezone

from . import catalog

GRANTS, BLOCKS, REQUIRES, INFO = 'grants', 'blocks', 'requires', 'info'

# tech_access Decision.source values that mean "blocked", not "not granted".
_TA_BLOCK_SOURCES = {'Containment', 'Explicit deny', 'Customer restriction', 'Integration',
                     'Mandatory safeguard'}


class RMMPermissionDenied(Exception):
    def __init__(self, decision):
        super().__init__(decision.reason)
        self.decision = decision


@dataclass
class Step:
    layer: str
    effect: str
    detail: str
    decisive: bool = False
    ref: str = ''


@dataclass
class Decision:
    allowed: bool
    needs_approval: bool = False
    approval_level: str = ''
    reason: str = ''
    action: str = ''
    organization_id: Optional[int] = None
    device_key: str = ''
    grant: str = ''          # 'allowed', or 'request' (the paired RMM grants the session itself)
    source: str = ''         # the layer that decided: tier:l2, tech_access, legacy:<flag>, override:<pk>, rem0te...
    rem0te_scope: Optional[str] = None
    approval_id: Optional[int] = None
    steps: List[Step] = field(default_factory=list)
    # Denied only because nothing grants it (no tier, preset, flag or allow
    # override; or a workstation-only grant on another device class), as
    # opposed to a block: locked, not a technician, containment, tenant, a
    # deny override, a technician-access deny or restriction, no Rem0te route.
    ungranted: bool = False

    @property
    def blocked(self) -> bool:
        """Denied by a block (see `ungranted`). For paths that never needed
        a grant before Phase 8 — they keep working for technicians nothing
        grants, but a deny or a containment still stops them."""
        return not self.allowed and not self.ungranted

    @property
    def permitted_now(self) -> bool:
        """May the operation run now (allowed, and approved if it needs it)."""
        return self.allowed and (not self.needs_approval or self.approval_id is not None)

    def __bool__(self):
        return self.permitted_now

    @property
    def label(self) -> str:
        if not self.allowed:
            return 'Denied'
        if self.needs_approval and self.approval_id is None:
            return 'Needs approval'
        return 'Request' if self.grant == catalog.REQUEST else 'Allowed'

    @property
    def approval_label(self) -> str:
        return catalog.APPROVAL_LABELS.get(self.approval_level, '')

    def as_dict(self) -> dict:
        d = asdict(self)
        d['permitted_now'] = self.permitted_now
        return d


_Grant = namedtuple('_Grant', 'source state approval workstation_only detail')


# --- inputs ---------------------------------------------------------------------

def is_technician(user) -> bool:
    from tech_access.resolver import is_technician as _is
    return _is(user)


def global_role(user):
    """The technician's global role template (MSP staff only), or None."""
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    try:
        return profile.get_global_permissions()
    except Exception:
        return None


def tier_of(user) -> str:
    role = global_role(user)
    return (getattr(role, 'rmm_tier', '') or '') if role is not None else ''


def scoped(user, organization) -> bool:
    """A live technician-access assignment at this customer (own or group)."""
    if organization is None:
        return False
    from tech_access.resolver import has_any_assignment
    return has_any_assignment(user, organization)


def device_ref(device):
    if device is None:
        return '', ''
    meta = device._meta
    label = getattr(device, 'device_name', '') or getattr(device, 'name', '') or str(device)
    return f'{meta.app_label}.{meta.model_name}:{device.pk}', str(label)[:255]


def resolve_device(key):
    if not key:
        return None
    from django.apps import apps
    try:
        label, pk = key.split(':', 1)
        app_label, model_name = label.split('.', 1)
        return apps.get_model(app_label, model_name).objects.filter(pk=int(pk)).first()
    except (ValueError, LookupError):
        return None


def _asset_of(device):
    if device is None:
        return None
    if device._meta.label_lower == 'assets.asset':
        return device
    return getattr(device, 'linked_asset', None)


def _device_type(device):
    if device is None:
        return None
    t = getattr(device, 'device_type', None)
    if t is None:
        t = getattr(device, 'asset_type', None)
    return (t or '').lower()


def _overrides(user, organization, action, now):
    from django.db.models import Q

    from .models import RMMPermissionOverride
    role = global_role(user)
    role_id = getattr(role, 'pk', None)
    qs = RMMPermissionOverride.objects.live(now).filter(action__in=[action, '*'])
    if organization is not None:
        qs = qs.filter(Q(organization=organization) | Q(organization__isnull=True))
    else:
        qs = qs.filter(organization__isnull=True)
    return [o for o in qs.select_related('organization', 'role_template', 'user').order_by('pk')
            if o.matches(user, role_id)]


def _perm(user, organization, flag) -> bool:
    from accounts.permission_utils import user_has_org_perm, user_has_perm
    if organization is None:
        return user_has_perm(user, flag)
    return user_has_org_perm(user, organization, flag)


def _vault_reveal(user, organization) -> bool:
    """The vault's own reveal rule at this customer (vault.permissions
    .can_access_password → accounts.permission_utils.user_has_org_perm):
    MSP staff with a global role get exactly what that role says, and a
    customer membership never widens it; staff without a global role and
    everyone else go by their memberships there."""
    return _perm(user, organization, 'vault_view_password')


def _legacy(user, organization, action, now, tier=''):
    """(source, detail) for the checks these actions always used, or None.

    A technician with a device tier (L1–L3) doesn't get device actions from
    global role flags: those reach every customer, and a tier must not. The
    tier and the technician's assignments decide where instead."""
    from tech_access.resolver import decide
    spec = catalog.ACTIONS[action]
    if tier in catalog.TIER_RANK and tier and spec.scope == 'device' and action != 'credential.reveal':
        return None
    if action in ('device.view', 'alert.view'):
        if scoped(user, organization):
            return 'legacy:assignment', f'Technician access assignment at {organization.name}.'
        flag = 'integrations_view' if action == 'device.view' else 'monitoring_view'
        if organization is not None and _perm(user, organization, flag):
            return f'legacy:{flag}', f'Role permission “{flag}” at this customer.'
        return None
    if action == 'diagnostics.view':
        for cap in ('diagnostics_readonly', 'diagnostics_advanced'):
            if organization is not None and decide(user, organization, cap, now=now).allowed:
                return 'tech_access', f'Technician access allows {cap.replace("_", " ")} here.'
        return None
    if action == 'credential.reveal':
        if organization is not None and _vault_reveal(user, organization):
            return 'legacy:vault_view_password', 'Vault reveal permission at this customer.'
        return None
    if action == 'integration.configure' and _perm(user, organization, 'integrations_configure'):
        return 'legacy:integrations_configure', 'Role permission “integrations_configure”.'
    if action == 'audit.review' and _perm(user, organization, 'audit_view'):
        return 'legacy:audit_view', 'Role permission “audit_view”.'
    if action in ('policy.manage', 'security.settings') and user.is_superuser:
        return 'legacy:superuser', 'Security administrator (superuser).'
    return None


# --- the decision --------------------------------------------------------------------

def can(user, organization, action, device=None, ticket=None, now=None) -> Decision:
    now = now or timezone.now()
    org_id = getattr(organization, 'pk', None)
    dkey, _ = device_ref(device)
    scope = catalog.rem0te_scope(action)
    steps: List[Step] = []

    def no(reason, layer, ref='', ungranted=False):
        steps.append(Step(layer, BLOCKS, reason, True, ref))
        return Decision(False, reason=reason, action=action, organization_id=org_id, device_key=dkey,
                        source=layer, rem0te_scope=scope, steps=steps, ungranted=ungranted)

    if action in catalog.LOCKED:
        return no(catalog.LOCKED[action], 'safeguard')
    spec = catalog.ACTIONS.get(action)
    if spec is None:
        return no('Unknown RMM action.', 'safeguard')
    if not is_technician(user):
        return no('Only active MSP technicians can do RMM work; customer portal users never can.', 'technician')
    steps.append(Step('technician', INFO, 'Active MSP technician.'))

    from tech_access.resolver import active_containment
    held = active_containment(user)
    if held is not None:
        return no(f'Your access is contained pending review: {held.reason}', 'containment')

    # --- tenant ---
    if spec.scope == 'device' and organization is None:
        return no('No customer given.', 'tenant')
    for obj, what in ((device, 'device'), (ticket, 'ticket')):
        if obj is None:
            continue
        oid = getattr(obj, 'organization_id', None)
        if oid is None:
            return no(f'That {what} has no customer yet; nobody can act on it until one is set.', 'tenant')
        if oid != org_id:
            return no(f'That {what} belongs to a different customer.', 'tenant')
    conn = getattr(device, 'connection', None) if device is not None and hasattr(device, 'connection_id') else None
    # A platform-owned connection (no organization) serves every customer;
    # the device's own customer, checked above, decides.
    if conn is not None and conn.organization_id is not None and conn.organization_id != org_id:
        return no("That device's RMM connection belongs to a different customer.", 'tenant')

    # --- deny overrides ---
    ovs = _overrides(user, organization, action, now)
    for o in ovs:
        if o.effect == o.DENY:
            return no(f'Denied by override #{o.pk} at {o.where_label}' + (f': {o.reason}' if o.reason else '.'),
                      'override', f'override:{o.pk}')

    # --- technician access blocks (and its preset grant) ---
    td = None
    if spec.tech_capability:
        from tech_access.resolver import UNAVAILABLE, decide
        td = decide(user, organization, spec.tech_capability, ticket=ticket, asset=_asset_of(device), now=now,
                    integration=action not in catalog.CAPABILITY_WITHOUT_INTEGRATION)
        if td.state == UNAVAILABLE or td.source in _TA_BLOCK_SOURCES:
            return no(td.reason, 'tech_access', f'capability:{spec.tech_capability}')
    elif organization is not None:
        from tech_access.resolver import _deny
        d = _deny(user, organization, '*', now)
        if d is not None:
            return no('Technician access: everything is denied for you here' + (f': {d.reason}' if d.reason
                                                                                else '.'), 'tech_access')

    # --- Rem0te route ---
    if conn is not None and getattr(conn, 'provider_type', '') == 'rem0te':
        if scope is None:
            return no("Rem0te's ticket-rmm-v1 contract has no route for this from ClientSt0r; do it in Rem0te, "
                      'where its own approvals apply.', 'rem0te')
        steps.append(Step('rem0te', INFO, f'Rem0te decides too ({scope or "synced data, no delegation"}); its '
                                          'refusal always wins.'))

    # --- grants ---
    grants: List[_Grant] = []
    tier = tier_of(user)
    is_scoped = scoped(user, organization) if spec.scope == 'device' else True
    e = catalog.entry(tier, action)
    if e is not None:
        tname = catalog.TIER_LABELS.get(tier, tier)
        if not is_scoped:
            steps.append(Step('scope', INFO, f'{tname} holds this, but you have no technician access assignment '
                                             f'at {organization.name}; a role tier never reaches a customer on its '
                                             'own.'))
        elif e['state'] == catalog.GRANTABLE:
            steps.append(Step('tier', INFO, f'{tname} can be granted this only by an approved allow override.'))
        elif (spec.scope == 'device' and ticket is not None and ticket.assigned_to_id != user.pk
              and tier != 'l3'):
            steps.append(Step('tier', INFO, f'The ticket is not assigned to you; {tname} covers only your own '
                                            'tickets.'))
        else:
            grants.append(_Grant(f'tier:{tier}', e['state'], e['approval'], e['workstation_only'],
                                 f'Role tier {tname} (global role).'))
    if td is not None:
        if td.allowed or td.requestable:
            grants.append(_Grant('tech_access', catalog.REQUEST if td.requestable else catalog.ALLOWED,
                                 spec.default_approval, False, f'Technician access: {td.reason}'))
        else:
            steps.append(Step('tech_access', INFO, f'Technician access: {td.reason}'))
    legacy = _legacy(user, organization, action, now, tier)
    if legacy is not None:
        grants.append(_Grant(legacy[0], catalog.ALLOWED, spec.default_approval, False, legacy[1]))
    for o in ovs:
        if o.effect != o.ALLOW or o.organization_id is None or o.action == '*' or action == 'credential.reveal':
            continue
        if not is_scoped:
            steps.append(Step('override', INFO, f'Allow override #{o.pk} needs a technician access assignment '
                                                'here.', ref=f'override:{o.pk}'))
            continue
        if action in catalog.HIGH_IMPACT and e is None:
            steps.append(Step('override', INFO, f'Allow override #{o.pk}: high-impact work needs a role tier that '
                                                'lists it.', ref=f'override:{o.pk}'))
            continue
        grants.append(_Grant(f'override:{o.pk}', catalog.ALLOWED,
                             catalog.stronger(e['approval'] if e else None, spec.default_approval),
                             bool(e and e['workstation_only']), f'Allow override #{o.pk} at {o.where_label}.'))

    if not grants:
        if td is not None and e is None:
            # Same words technician access always gave for this capability.
            return no(td.reason, 'tech_access', f'capability:{spec.tech_capability}', ungranted=True)
        where = f' at {organization.name}' if organization is not None else ''
        return no(f'Nothing grants this{where}: no role tier, technician access, permission or approved '
                  'override covers it.', 'grants', ungranted=True)

    dtype = _device_type(device)
    usable = []
    for g in grants:
        if g.workstation_only and dtype is not None and dtype not in catalog.STANDARD_WORKSTATION_TYPES:
            steps.append(Step('constraint', INFO, f'{g.detail} Standard workstations only; this is a '
                                                  f'{dtype or "unknown"} device.'))
        else:
            usable.append(g)
    if not usable:
        return no('Only standard workstations are covered; this device needs a higher tier.', 'constraint',
                  ungranted=True)

    best = min(usable, key=lambda g: (0 if g.state == catalog.ALLOWED else 1,
                                      catalog.APPROVAL_RANK.get(g.approval, 0)))
    for g in usable:
        steps.append(Step(g.source.split(':')[0], GRANTS, g.detail, g is best, g.source))
    level = best.approval or ''
    for o in ovs:
        if o.effect == o.REQUIRE_APPROVAL:
            lvl = o.approval_level or catalog.PEER
            steps.append(Step('override', REQUIRES, f'Override #{o.pk} at {o.where_label} requires approval by '
                                                    f'{catalog.APPROVAL_LABELS[lvl]}.', ref=f'override:{o.pk}'))
            level = catalog.stronger(level, lvl)
    if action in catalog.HIGH_IMPACT and not level:
        level = catalog.PEER
    reason = best.detail
    if level:
        reason += f' Needs approval by {catalog.APPROVAL_LABELS[level]} before it runs.'
        steps.append(Step('approval', REQUIRES, f'Second-person approval: {catalog.APPROVAL_LABELS[level]}.'))
    return Decision(True, needs_approval=bool(level), approval_level=level, reason=reason, action=action,
                    organization_id=org_id, device_key=dkey, grant=best.state, source=best.source,
                    rem0te_scope=scope, steps=steps)


# --- the audited check -----------------------------------------------------------------

def _audit(user, organization, decision, request=None, verb=None):
    from audit.models import AuditLog
    outcome = verb or ('allowed' if decision.permitted_now else
                       'needs approval' if decision.allowed else 'denied')
    meta = getattr(request, 'META', {}) if request is not None else {}
    AuditLog.log(user=user if getattr(user, 'pk', None) else None, action='api_call',
                 organization=organization, object_type='rmm_permission',
                 object_repr=f'{decision.action} {outcome}'[:255],
                 description=f'RMM action “{decision.action}” {outcome}: {decision.reason}'[:1000],
                 ip_address=meta.get('REMOTE_ADDR') or None, user_agent=(meta.get('HTTP_USER_AGENT') or '')[:255],
                 path=getattr(request, 'path', '') or '',
                 extra_data={k: v for k, v in decision.as_dict().items() if k != 'steps'}
                 | {'steps': [f'{s.layer}:{s.effect}:{s.detail}'[:300] for s in decision.steps]},
                 success=decision.permitted_now)


def rmm_action(user, organization, action, device=None, ticket=None, digest='', request=None,
               consume_approval=True) -> Decision:
    """The check every RMM operation makes before it acts. Audited."""
    d = can(user, organization, action, device=device, ticket=ticket)
    if d.allowed and d.needs_approval and consume_approval:
        from .approvals import consume
        approval = consume(user, organization, action, d.device_key, digest)
        if approval is not None:
            d.approval_id = approval.pk
            by = approval.decided_by.get_username() if approval.decided_by_id else '?'
            d.steps.append(Step('approval', GRANTS, f'Approval #{approval.pk} by {by} (used now).', True,
                                f'approval:{approval.pk}'))
            d.reason += f' Approved by {by} (#{approval.pk}).'
    _audit(user, organization, d, request)
    return d


def require(user, organization, action, **kw) -> Decision:
    d = rmm_action(user, organization, action, **kw)
    if not d.permitted_now:
        raise RMMPermissionDenied(d)
    return d


def audit_denial(user, organization, action, reason, device=None, request=None, source='caller') -> Decision:
    """Record a refusal a caller made on its own (e.g. the RMM doesn't
    advertise it) so every denied RMM action is in the audit trail."""
    d = can(user, organization, action, device=device)
    if d.allowed:
        d = Decision(False, reason=reason, action=action, organization_id=getattr(organization, 'pk', None),
                     device_key=d.device_key, source=source, rem0te_scope=d.rem0te_scope,
                     steps=d.steps + [Step(source, BLOCKS, reason, True)])
    _audit(user, organization, d, request)
    return d


def record_remote_refusal(decision, user, organization, code='', message='', request=None) -> Decision:
    """The paired RMM refused what ClientSt0r allowed. Its refusal wins."""
    text = ''
    try:
        from integrations.rem0te.actions import REFUSAL_TEXT
        text = REFUSAL_TEXT.get(code, '')
    except Exception:  # pragma: no cover - import guard only
        pass
    text = text or (message or 'The RMM refused this.')
    reason = f'{text}' + (f' ({code})' if code else '')
    steps = list(decision.steps) + [Step('rem0te', BLOCKS, f'The RMM refused: {reason}', True, code)]
    for s in steps[:-1]:
        s.decisive = False
    out = Decision(False, reason=f'Refused by the RMM: {reason}', action=decision.action,
                   organization_id=decision.organization_id, device_key=decision.device_key, source='rem0te',
                   rem0te_scope=decision.rem0te_scope, approval_id=decision.approval_id, steps=steps)
    _audit(user, organization, out, request, verb='refused by the RMM')
    return out


# --- effective permissions ---------------------------------------------------------------

def effective(user, organization) -> List[Decision]:
    """Every action (and locked safeguard) for one technician at one customer."""
    keys = list(catalog.ACTIONS) + list(catalog.LOCKED)
    return [can(user, organization, k) for k in keys]
