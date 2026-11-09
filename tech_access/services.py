"""
Changing technician access. Every change goes through here so it gets a
diff, an audit entry and — when it widens access — a protected change.

"Widening" means granting more than the L1 baseline, or more than the
technician (or preset, or group) had before. Narrowing applies at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import catalog
from .models import (AccessAssignment, AccessPreset, CustomerAccessPolicy, ExplicitDeny, ProtectionSettings,
                     TechnicianGroup)
from .protected import applier, propose


# --- seeding -----------------------------------------------------------------

def seed_presets(Preset=AccessPreset) -> Dict[str, str]:
    """Create any missing built-in preset. An existing one is left alone even
    if a newer release ships different contents — the reset preview shows
    the drift, and applying it is a reviewed change, never a silent one.
    Safe to run any number of times."""
    out = {}
    for key, name, level, desc, caps in catalog.BUILTIN_PRESETS:
        obj = Preset.objects.filter(key=key).first()
        if obj is None:
            if Preset.objects.filter(name=name).exists():
                # A custom preset already uses the name; keep it, rename ours.
                name = f'{name} (built in)'
            Preset.objects.create(key=key, name=name, level=level, description=desc,
                                  capabilities=dict(caps), builtin=True)
            out[key] = 'created'
        else:
            out[key] = 'unchanged' if catalog.clean_capabilities(obj.capabilities) == caps else 'differs'
    return out


def builtin(key) -> AccessPreset:
    seed_presets()
    return AccessPreset.objects.get(key=key)


# --- effective state and diffs -------------------------------------------------

def _best(presets) -> Dict[str, str]:
    out = {k: catalog.OFF for k in catalog.OPTIONAL}
    for p in presets:
        for k, v in p.caps().items():
            if catalog.RANK[v] > catalog.RANK[out[k]]:
                out[k] = v
    return out


def granted_map(user, organization, extra=(), without=()) -> Dict[str, str]:
    """What a technician's live assignments at one customer grant, before
    denies and restrictions. `extra` presets are added, `without` assignment
    pks removed — for previews."""
    from .resolver import live_assignments
    presets = [a.preset for a in live_assignments(user, organization) if a.pk not in set(without)]
    return _best(presets + list(extra))


@dataclass
class Plan:
    summary: str
    rows: List[dict] = field(default_factory=list)  # per technician: {user, before, after, changes}
    widening: List[str] = field(default_factory=list)
    affected: List[int] = field(default_factory=list)
    expires_at: Optional[object] = None

    @property
    def needs_review(self):
        return bool(self.widening)


def _row(user, before, after):
    changes = [{'key': k, 'label': catalog.OPTIONAL[k][0], 'before': before[k], 'after': after[k]}
               for k in catalog.OPTIONAL if before[k] != after[k]]
    return {'user': user, 'before': before, 'after': after, 'changes': changes}


def _members(subject):
    if isinstance(subject, TechnicianGroup):
        return list(subject.members.filter(is_active=True))
    return [subject]


def plan_assignment(subject, organization, preset, expires_at=None) -> Plan:
    plan = Plan(summary=f'Assign {preset.name} to '
                        f'{subject.name if isinstance(subject, TechnicianGroup) else subject.get_username()} '
                        f'at {organization.name}', expires_at=expires_at)
    widening = set(catalog.widens(catalog.L1, preset.caps()))
    for u in _members(subject):
        before = granted_map(u, organization)
        after = granted_map(u, organization, extra=[preset])
        plan.rows.append(_row(u, before, after))
        plan.affected.append(u.pk)
        widening |= set(catalog.widens(before, after)) & set(catalog.widens(catalog.L1, after))
    plan.widening = sorted(widening, key=list(catalog.OPTIONAL).index)
    return plan


def plan_preset_change(preset, new_caps) -> Plan:
    new_caps = catalog.clean_capabilities(new_caps)
    plan = Plan(summary=f'Change preset {preset.name}')
    widening = set(catalog.widens(preset.caps(), new_caps))
    tmp = AccessPreset(name=preset.name, capabilities=new_caps)
    for a in preset.assignments.live().select_related('organization', 'user', 'group'):
        for u in _members(a.user or a.group):
            before = granted_map(u, a.organization)
            after = granted_map(u, a.organization, extra=[tmp], without=[a.pk])
            plan.rows.append(dict(_row(u, before, after), organization=a.organization))
            plan.affected.append(u.pk)
    plan.widening = sorted(widening, key=list(catalog.OPTIONAL).index)
    plan.affected = sorted(set(plan.affected))
    return plan


def plan_group_members(group, new_members) -> Plan:
    current = set(group.members.values_list('pk', flat=True))
    added = [u for u in new_members if u.pk not in current]
    plan = Plan(summary=f'Change members of {group.name}')
    widening = set()
    for a in group.assignments.live().select_related('preset', 'organization'):
        for u in added:
            before = granted_map(u, a.organization)
            after = granted_map(u, a.organization, extra=[a.preset])
            plan.rows.append(dict(_row(u, before, after), organization=a.organization))
            plan.affected.append(u.pk)
            widening |= set(catalog.widens(before, after))
    plan.widening = sorted(widening, key=list(catalog.OPTIONAL).index)
    return plan


def _reset_target(preset) -> Dict[str, str]:
    """Built-in presets reset to what this release ships; custom presets to
    the preset they were cloned from, else the L1 baseline."""
    if preset.builtin:
        return preset.builtin_caps()
    return preset.based_on.caps() if preset.based_on_id else dict(catalog.L1)


def reset_preview(preset) -> Plan:
    return plan_preset_change(preset, _reset_target(preset))


# --- audit -------------------------------------------------------------------

def _audit(user, verb, obj_type, obj_id, text, organization=None, extra=None):
    from audit.models import AuditLog
    AuditLog.log(user=user, action=verb, organization=organization, object_type=obj_type, object_id=obj_id,
                 object_repr=text[:255], description=text, extra_data=extra or {})


# --- operations --------------------------------------------------------------

def assign(subject, organization, preset, by, expires_at=None, note='', request=None):
    """Create an assignment, or a protected change when it widens access.
    Returns (assignment or None, protected change or None, plan)."""
    plan = plan_assignment(subject, organization, preset, expires_at)
    payload = {'preset': preset.pk, 'organization': organization.pk, 'note': note[:200],
               'expires_at': expires_at.isoformat() if expires_at else None,
               'user': subject.pk if not isinstance(subject, TechnicianGroup) else None,
               'group': subject.pk if isinstance(subject, TechnicianGroup) else None}
    if plan.needs_review:
        change = propose('assignment', plan.summary, payload, plan.widening, by,
                         target_user=None if isinstance(subject, TechnicianGroup) else subject,
                         affected=plan.affected, request=request)
        return None, change, plan
    return _create_assignment(payload, by), None, plan


def _create_assignment(payload, by):
    from core.models import Organization
    expires = parse_datetime(payload['expires_at']) if payload.get('expires_at') else None
    a = AccessAssignment.objects.create(
        preset=AccessPreset.objects.get(pk=payload['preset']),
        organization=Organization.objects.get(pk=payload['organization']),
        user=get_user_model().objects.get(pk=payload['user']) if payload.get('user') else None,
        group=TechnicianGroup.objects.get(pk=payload['group']) if payload.get('group') else None,
        expires_at=expires, granted_by=by, note=payload.get('note') or '')
    _audit(by, 'create', 'tech_access_assignment', a.pk, f'Technician access: {a}', a.organization,
           {'preset': a.preset.name, 'expires_at': payload.get('expires_at')})
    return a


@applier('assignment')
def _apply_assignment(change, reviewer):
    _create_assignment(change.payload, change.requested_by)


def revoke(assignment, by):
    assignment.revoked_at = timezone.now()
    assignment.save(update_fields=['revoked_at'])
    _audit(by, 'delete', 'tech_access_assignment', assignment.pk, f'Revoked technician access: {assignment}',
           assignment.organization)


def clone_preset(preset, name, by):
    clone = AccessPreset.objects.create(name=name[:100], level=preset.level, description=preset.description,
                                        capabilities=preset.caps(), based_on=preset)
    _audit(by, 'create', 'tech_access_preset', clone.pk, f'Cloned preset {preset.name} as {clone.name}')
    return clone


def change_preset(preset, new_caps, by, request=None):
    """Returns (applied: bool, change or None, plan)."""
    if preset.builtin:
        raise ValueError('Built-in presets cannot be edited. Clone one to customise it.')
    plan = plan_preset_change(preset, new_caps)
    caps = catalog.clean_capabilities(new_caps)
    if plan.needs_review:
        change = propose('preset', plan.summary, {'preset': preset.pk, 'capabilities': caps}, plan.widening,
                         by, affected=plan.affected, request=request)
        return False, change, plan
    _set_caps(preset, caps, by)
    return True, None, plan


def reset_preset(preset, by, request=None):
    plan = reset_preview(preset)
    caps = catalog.clean_capabilities(_reset_target(preset))
    if plan.needs_review:
        change = propose('preset', f'Reset preset {preset.name}', {'preset': preset.pk, 'capabilities': caps},
                         plan.widening, by, affected=plan.affected, request=request)
        return False, change, plan
    _set_caps(preset, caps, by)
    return True, None, plan


def _set_caps(preset, caps, by):
    before = preset.caps()
    preset.capabilities = caps
    preset.save(update_fields=['capabilities', 'updated_at'])
    _audit(by, 'update', 'tech_access_preset', preset.pk, f'Preset {preset.name} changed',
           extra={'before': before, 'after': caps})


@applier('preset')
def _apply_preset(change, reviewer):
    _set_caps(AccessPreset.objects.get(pk=change.payload['preset']), change.payload['capabilities'],
              change.requested_by)


def set_group_members(group, users, by, request=None):
    users = list(users)
    plan = plan_group_members(group, users)
    keep = {u.pk for u in users}
    removed = list(group.members.exclude(pk__in=keep))
    if removed:
        group.members.remove(*removed)
        _audit(by, 'update', 'tech_access_group', group.pk,
               f'Removed {", ".join(u.get_username() for u in removed)} from {group.name}')
    added = [u for u in users if not group.members.filter(pk=u.pk).exists()]
    if not added:
        return True, None, plan
    if plan.needs_review:
        change = propose('group_members', f'Add {", ".join(u.get_username() for u in added)} to {group.name}',
                         {'group': group.pk, 'add': [u.pk for u in added]}, plan.widening, by,
                         target_user=added[0] if len(added) == 1 else None, affected=[u.pk for u in added],
                         request=request)
        return False, change, plan
    group.members.add(*added)
    _audit(by, 'update', 'tech_access_group', group.pk,
           f'Added {", ".join(u.get_username() for u in added)} to {group.name}')
    return True, None, plan


@applier('group_members')
def _apply_group(change, reviewer):
    group = TechnicianGroup.objects.get(pk=change.payload['group'])
    group.members.add(*get_user_model().objects.filter(pk__in=change.payload['add']))
    _audit(change.requested_by, 'update', 'tech_access_group', group.pk, f'Approved: {change.summary}')


def add_deny(user, capability, by, organization=None, reason='', expires_at=None):
    d = ExplicitDeny.objects.create(user=user, capability=capability, organization=organization,
                                    reason=reason[:200], expires_at=expires_at, created_by=by)
    _audit(by, 'create', 'tech_access_deny', d.pk, f'Denied {capability} for {user.get_username()}', organization)
    return d


def remove_deny(deny, by, request=None):
    """Lifting a deny widens access, so it is reviewed."""
    return propose('security_limits',
                   f'Lift deny of {deny.capability} for {deny.user.get_username()}',
                   {'op': 'lift_deny', 'deny': deny.pk}, [deny.capability], by, target_user=deny.user,
                   affected=[deny.user_id], request=request)


def set_restrictions(organization, restricted, by, request=None):
    """Adding restrictions applies at once; removing them is reviewed."""
    policy, _ = CustomerAccessPolicy.objects.get_or_create(organization=organization)
    want = sorted({c for c in restricted if c in catalog.OPTIONAL})
    have = set(policy.restricted or [])
    lifted = sorted(have - set(want))
    tightened = sorted(set(want) | have)
    if set(want) - have:
        policy.restricted = tightened
        policy.save(update_fields=['restricted', 'updated_at'])
        _audit(by, 'update', 'tech_access_customer_policy', policy.pk,
               f'Restricted {", ".join(sorted(set(want) - have))} at {organization.name}', organization)
    if lifted:
        return propose('security_limits', f'Lift restrictions at {organization.name}: {", ".join(lifted)}',
                       {'op': 'lift_restrictions', 'organization': organization.pk, 'lift': lifted},
                       lifted, by, request=request)
    return None


def set_default_preset(organization, preset, by):
    policy, _ = CustomerAccessPolicy.objects.get_or_create(organization=organization)
    policy.default_preset = preset
    policy.save(update_fields=['default_preset', 'updated_at'])
    _audit(by, 'update', 'tech_access_customer_policy', policy.pk,
           f'Default preset at {organization.name}: {preset.name if preset else "L1"}', organization)


def default_preset_for(organization):
    policy = CustomerAccessPolicy.objects.filter(organization=organization).select_related('default_preset').first()
    return (policy.default_preset if policy and policy.default_preset_id else None) or builtin('l1')


@applier('security_limits')
def _apply_limits(change, reviewer):
    p = change.payload
    op = p.get('op')
    if op == 'lift_deny':
        ExplicitDeny.objects.filter(pk=p['deny']).delete()
    elif op == 'lift_restrictions':
        policy = CustomerAccessPolicy.objects.get(organization_id=p['organization'])
        policy.restricted = sorted(set(policy.restricted or []) - set(p['lift']))
        policy.save(update_fields=['restricted', 'updated_at'])
    elif op == 'detection':
        from .models import DetectionSettings
        s = DetectionSettings.load()
        for k in ('enabled', 'thresholds', 'containment', 'notify_customers', 'recipients'):
            if k in p['values']:
                setattr(s, k, p['values'][k])
        s.save()
    else:
        raise ValueError(f'unknown security_limits op {op!r}')
    _audit(change.requested_by, 'update', 'tech_access_limits', change.pk, f'Approved: {change.summary}')


@applier('approvers')
def _apply_approvers(change, reviewer):
    s = ProtectionSettings.load()
    s.approvers.add(*get_user_model().objects.filter(pk__in=change.payload.get('add') or [], is_superuser=True))
    _audit(change.requested_by, 'update', 'tech_access_approvers', s.pk, f'Approved: {change.summary}')


@applier('recovery_contact')
def _apply_recovery(change, reviewer):
    s = ProtectionSettings.load()
    s.recovery_email = change.payload.get('recovery_email') or ''
    # Verified by the approval itself: a second administrator, freshly
    # authenticated, confirmed the address, and the old address was told.
    s.recovery_verified_at = timezone.now() if s.recovery_email else None
    s.save()
    _audit(change.requested_by, 'update', 'tech_access_recovery', s.pk, f'Approved: {change.summary}')


def propose_approvers(add_users, remove_users, by, request=None):
    s = ProtectionSettings.load()
    if remove_users:
        # Removing an approver narrows who can widen; applies at once, but
        # never down to zero explicit approvers by accident (empty = all
        # superusers, which is wider).
        remaining = s.approvers.exclude(pk__in=[u.pk for u in remove_users])
        if s.approvers.exists() and not remaining.exists():
            raise ValueError('Keep at least one approver, or the list falls back to every superuser.')
        s.approvers.remove(*remove_users)
        _audit(by, 'update', 'tech_access_approvers', s.pk,
               f'Removed approvers: {", ".join(u.get_username() for u in remove_users)}')
    if add_users:
        return propose('approvers', f'Add approvers: {", ".join(u.get_username() for u in add_users)}',
                       {'add': [u.pk for u in add_users]}, ['approvers'], by,
                       affected=[u.pk for u in add_users], request=request)
    return None


def propose_recovery_contact(email, by, request=None):
    return propose('recovery_contact', f'Set the security recovery contact to {email or "(none)"}',
                   {'recovery_email': email}, ['recovery_contact'], by, request=request)


def propose_detection(values, by, request=None):
    """Loosening detection (higher thresholds, disabling, alert-only
    containment) is reviewed; tightening applies at once."""
    from .models import DetectionSettings
    from .detection import loosens
    s = DetectionSettings.load()
    looser = loosens(s, values)
    if not looser:
        with transaction.atomic():
            for k, v in values.items():
                setattr(s, k, v)
            s.save()
        _audit(by, 'update', 'tech_access_detection', s.pk, 'Theft detection settings tightened',
               extra={'values': values})
        return None
    return propose('security_limits', 'Loosen theft detection: ' + ', '.join(looser),
                   {'op': 'detection', 'values': values}, looser, by, request=request)


# --- RMM business mapping (Rem0te ticket-processor pairing) ------------------

def propose_pairing(connection, pairing_request, by, request=None):
    what = []
    if pairing_request.get('enable'):
        what.append('ticket processing on')
    if pairing_request.get('location') == 'local':
        what.append('marked on-premises')
    return propose('business_mapping',
                   f'Rem0te pairing "{connection.name}" at {connection.organization.name}: {", ".join(what)}',
                   {'connection': connection.pk, **pairing_request}, what, by, request=request)


@applier('business_mapping')
def _apply_pairing(change, reviewer):
    from integrations.models import RMMConnection
    from integrations.providers.rmm.rem0te import INTEGRATION_ENABLED, INTEGRATION_LOCATION
    conn = RMMConnection.objects.get(pk=change.payload['connection'])
    mappings = dict(conn.field_mappings or {})
    if change.payload.get('enable'):
        mappings[INTEGRATION_ENABLED] = True
    if change.payload.get('location') == 'local':
        mappings[INTEGRATION_LOCATION] = 'local'
    conn.field_mappings = mappings
    conn.save(update_fields=['field_mappings'])
    _audit(change.requested_by, 'update', 'rmm_connection', conn.pk, f'Approved: {change.summary}',
           conn.organization)


# --- AI provider destinations ---------------------------------------------------

def propose_destination(profile, by, request=None):
    """Approve an Ollama profile's current address as its destination, and
    (when it is on-premises) as approved for local-only customers."""
    from psa_ai.services.gateway import origin
    dest = origin(profile.base_url)
    if not dest:
        raise ValueError('The Ollama address is not a valid http(s) URL.')
    return propose('provider_destination', f'Approve {dest} for AI profile {profile.name}',
                   {'profile': profile.pk, 'destination': dest, 'local': True},
                   [f'AI destination {dest}'], by, request=request)


@applier('provider_destination')
def _apply_destination(change, reviewer):
    from psa_ai.models import AIModelProfile
    from psa_ai.services.gateway import origin
    profile = AIModelProfile.objects.get(pk=change.payload['profile'])
    if origin(profile.base_url) != change.payload['destination']:
        from .protected import ProtectedChangeError
        raise ProtectedChangeError('The profile address changed after this was proposed. Propose it again.')
    profile.approved_destination = change.payload['destination']
    profile.local_approved = bool(change.payload.get('local'))
    profile.save(update_fields=['approved_destination', 'local_approved', 'updated_at'])
    _audit(change.requested_by, 'update', 'ai_model_profile', profile.pk, f'Approved: {change.summary}')
