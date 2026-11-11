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


def _assignment_state(a) -> dict:
    """An assignment as recorded in its audit entries' before/after."""
    return {'subject': a.subject_label, 'organization': a.organization.name, 'preset': a.preset.name,
            'expires_at': a.expires_at.isoformat() if a.expires_at else None,
            'revoked_at': a.revoked_at.isoformat() if a.revoked_at else None, 'note': a.note}


def _create_assignment(payload, by, change=None):
    from core.models import Organization
    expires = parse_datetime(payload['expires_at']) if payload.get('expires_at') else None
    a = AccessAssignment.objects.create(
        preset=AccessPreset.objects.get(pk=payload['preset']),
        organization=Organization.objects.get(pk=payload['organization']),
        user=get_user_model().objects.get(pk=payload['user']) if payload.get('user') else None,
        group=TechnicianGroup.objects.get(pk=payload['group']) if payload.get('group') else None,
        expires_at=expires, granted_by=by, note=payload.get('note') or '', approved_change=change)
    _audit(by, 'create', 'tech_access_assignment', a.pk, f'Technician access: {a}', a.organization,
           {'preset': a.preset.name, 'expires_at': payload.get('expires_at'),
            'change': change.pk if change else None,
            'approved_by': _name(change.reviewed_by) if change and change.reviewed_by_id else '',
            'before': None, 'after': _assignment_state(a)})
    return a


@applier('assignment')
def _apply_assignment(change, reviewer):
    change.reviewed_by = reviewer  # saved by protected.approve right after
    _create_assignment(change.payload, change.requested_by, change)


def revoke(assignment, by):
    before = _assignment_state(assignment)
    assignment.revoked_at, assignment.revoked_by = timezone.now(), by
    assignment.save(update_fields=['revoked_at', 'revoked_by'])
    _audit(by, 'delete', 'tech_access_assignment', assignment.pk, f'Revoked technician access: {assignment}',
           assignment.organization, {'before': before, 'after': _assignment_state(assignment)})


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
    before = sorted(group.members.values_list('username', flat=True))
    if removed:
        group.members.remove(*removed)
        _audit(by, 'update', 'tech_access_group', group.pk,
               f'Removed {", ".join(u.get_username() for u in removed)} from {group.name}',
               extra={'users': [u.pk for u in removed], 'before': before,
                      'after': sorted(group.members.values_list('username', flat=True))})
    added = [u for u in users if not group.members.filter(pk=u.pk).exists()]
    if not added:
        return True, None, plan
    if plan.needs_review:
        change = propose('group_members', f'Add {", ".join(u.get_username() for u in added)} to {group.name}',
                         {'group': group.pk, 'add': [u.pk for u in added]}, plan.widening, by,
                         target_user=added[0] if len(added) == 1 else None, affected=[u.pk for u in added],
                         request=request)
        return False, change, plan
    before = sorted(group.members.values_list('username', flat=True))
    group.members.add(*added)
    _audit(by, 'update', 'tech_access_group', group.pk,
           f'Added {", ".join(u.get_username() for u in added)} to {group.name}',
           extra={'users': [u.pk for u in added], 'before': before,
                  'after': sorted(group.members.values_list('username', flat=True))})
    return True, None, plan


@applier('group_members')
def _apply_group(change, reviewer):
    group = TechnicianGroup.objects.get(pk=change.payload['group'])
    before = sorted(group.members.values_list('username', flat=True))
    group.members.add(*get_user_model().objects.filter(pk__in=change.payload['add']))
    _audit(change.requested_by, 'update', 'tech_access_group', group.pk, f'Approved: {change.summary}',
           extra={'users': list(change.payload['add']), 'change': change.pk, 'approved_by': _name(reviewer),
                  'before': before, 'after': sorted(group.members.values_list('username', flat=True))})


def add_deny(user, capability, by, organization=None, reason='', expires_at=None):
    d = ExplicitDeny.objects.create(user=user, capability=capability, organization=organization,
                                    reason=reason[:200], expires_at=expires_at, created_by=by)
    _audit(by, 'create', 'tech_access_deny', d.pk, f'Denied {capability} for {user.get_username()}', organization,
           {'before': None, 'after': {'user': user.get_username(), 'capability': capability,
                                      'organization': organization.name if organization else 'every customer',
                                      'reason': d.reason,
                                      'expires_at': expires_at.isoformat() if expires_at else None}})
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
               f'Restricted {", ".join(sorted(set(want) - have))} at {organization.name}', organization,
               {'before': {'restricted': sorted(have)}, 'after': {'restricted': tightened}})
    if lifted:
        return propose('security_limits', f'Lift restrictions at {organization.name}: {", ".join(lifted)}',
                       {'op': 'lift_restrictions', 'organization': organization.pk, 'lift': lifted},
                       lifted, by, request=request)
    return None


def set_default_preset(organization, preset, by):
    policy, _ = CustomerAccessPolicy.objects.get_or_create(organization=organization)
    before = policy.default_preset.name if policy.default_preset_id else None
    policy.default_preset = preset
    policy.save(update_fields=['default_preset', 'updated_at'])
    _audit(by, 'update', 'tech_access_customer_policy', policy.pk,
           f'Default preset at {organization.name}: {preset.name if preset else "L1"}', organization,
           {'before': {'default_preset': before}, 'after': {'default_preset': preset.name if preset else None}})


def default_preset_for(organization):
    policy = CustomerAccessPolicy.objects.filter(organization=organization).select_related('default_preset').first()
    return (policy.default_preset if policy and policy.default_preset_id else None) or builtin('l1')


@applier('security_limits')
def _apply_limits(change, reviewer):
    p = change.payload
    op = p.get('op')
    if op == 'lift_deny':
        deny = ExplicitDeny.objects.filter(pk=p['deny']).select_related('user', 'organization').first()
        if deny is not None:
            _audit(change.requested_by, 'delete', 'tech_access_deny', deny.pk, f'Approved: {change.summary}',
                   deny.organization, {'change': change.pk, 'approved_by': _name(reviewer),
                                       'before': {'user': deny.user.get_username(), 'capability': deny.capability},
                                       'after': None})
            deny.delete()
    elif op == 'lift_restrictions':
        policy = CustomerAccessPolicy.objects.get(organization_id=p['organization'])
        before = sorted(policy.restricted or [])
        policy.restricted = sorted(set(policy.restricted or []) - set(p['lift']))
        policy.save(update_fields=['restricted', 'updated_at'])
        _audit(change.requested_by, 'update', 'tech_access_customer_policy', policy.pk,
               f'Approved: {change.summary}', policy.organization,
               {'change': change.pk, 'approved_by': _name(reviewer), 'before': {'restricted': before},
                'after': {'restricted': policy.restricted}})
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


# --- RMM business mapping (ticket-rmm-v1 pairing, any RMM provider) -----------

def pairing_fingerprint(connection) -> str:
    """What a pairing approval approves: provider, address, key ID and both
    secrets (hashed). If any of them changes after the proposal, approving
    it is refused — the new pairing has to be proposed again."""
    import hashlib
    import json
    from integrations.ticket_rmm import secrets, settings
    s = settings(connection)
    if connection.provider_type == 'rem0te':
        # Rem0te pairs with Ed25519: what is approved is Rem0te's audience and
        # the public keys ClientSt0r will trust for it.
        raw = json.dumps([connection.provider_type, s['site'], s.get('rem0te_audience', ''),
                          sorted((k.get('kid', ''), k.get('public_key_pem', '').strip())
                                 for k in s.get('signing_keys', []))])
        return hashlib.sha256(raw.encode()).hexdigest()
    sec = secrets(connection)
    raw = json.dumps([connection.provider_type, s['site'], s['key_id'],
                      hashlib.sha256(sec['outbound'].encode()).hexdigest(),
                      hashlib.sha256(sec['inbound'].encode()).hexdigest()])
    return hashlib.sha256(raw.encode()).hexdigest()


def propose_pairing(connection, pairing_request, by, request=None):
    what = []
    if pairing_request.get('enable'):
        what.append('ticket processing on')
    if pairing_request.get('location') == 'local':
        what.append('marked on-premises')
    return propose('business_mapping',
                   f'{connection.get_provider_type_display()} ticket integration pairing "{connection.name}" at '
                   f'{connection.organization.name}: {", ".join(what)}',
                   {'connection': connection.pk, 'provider': connection.provider_type,
                    'fingerprint': pairing_fingerprint(connection), **pairing_request}, what, by, request=request)


@applier('business_mapping')
def _apply_pairing(change, reviewer):
    from integrations.models import RMMConnection
    from integrations.ticket_rmm import ENABLED, LOCATION
    conn = RMMConnection.objects.get(pk=change.payload['connection'])
    want = change.payload.get('fingerprint')
    # Proposals made before v3.17.658 carry no fingerprint and apply as before.
    if want and want != pairing_fingerprint(conn):
        from .protected import ProtectedChangeError
        raise ProtectedChangeError('The pairing\'s provider, address, key ID or secrets changed after this was '
                                   'proposed. Save the connection again to propose the new pairing.')
    mappings = dict(conn.field_mappings or {})
    if change.payload.get('enable'):
        mappings[ENABLED] = True
    if change.payload.get('location') == 'local':
        mappings[LOCATION] = 'local'
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


# --- account e-mail addresses ---------------------------------------------------
# A protected account's address is where its password resets, theft alerts
# and protected-change notices go, so moving it takes two administrators like
# any other protected change. Directory sync (LDAP / Entra ID) still writes
# addresses from the directory, which is the source of truth there.

def email_is_protected(user) -> bool:
    """Superusers, approvers and MSP technicians. Customer portal users keep
    changing their own address freely."""
    from .protected import is_approver
    from .resolver import is_technician
    return bool(user is not None and user.pk and (user.is_superuser or is_technician(user) or is_approver(user)))


def propose_email_change(user, new_email, by, request=None, confirmed=False):
    """Record a pending e-mail change for `user`. `confirmed` marks the
    requester as having just re-authenticated in the same form."""
    from .protected import can_widen_at_all
    new_email = (new_email or '').strip()
    if not can_widen_at_all(by):
        raise ValueError('Changing this e-mail address needs a second administrator to approve it, '
                         'and this install has only one. Add a second superuser first.')
    change = propose('account_email', f'Change the e-mail address of {user.get_username()} to {new_email or "(none)"}',
                     {'user': user.pk, 'old_email': user.email or '', 'new_email': new_email},
                     ['account e-mail'], by, target_user=user, affected=[user.pk], request=request)
    if confirmed:
        change.requester_reauth_at = timezone.now()
        change.save(update_fields=['requester_reauth_at'])
    return change


def pending_email_change(user):
    from .models import ProtectedChange
    return (ProtectedChange.objects.filter(kind='account_email', target_user=user, status=ProtectedChange.PENDING,
                                           expires_at__gt=timezone.now()).order_by('-requested_at').first())


@applier('account_email')
def _apply_email(change, reviewer):
    from .protected import ProtectedChangeError
    user = get_user_model().objects.filter(pk=change.payload.get('user')).first()
    if user is None:
        raise ProtectedChangeError('That account no longer exists.')
    if (user.email or '') != change.payload.get('old_email', ''):
        raise ProtectedChangeError('The address changed after this was proposed. Propose it again.')
    user.email = change.payload.get('new_email', '')
    user.save(update_fields=['email'])
    _audit(change.requested_by, 'update', 'user', user.pk, f'Approved: {change.summary}')


# --- superuser grants (v3.17.653) ----------------------------------------------
# A superuser controls the whole installation. With the policy on, granting it
# from the application — creating a superuser, or promoting an account on the
# user edit page or in Django admin — records a protected change; the account
# becomes a superuser only when a different approver approves it. The policy
# is off on upgrade, can be turned on only while two eligible administrators
# exist, and turning it off is itself a protected change. Host-level commands
# (manage.py createsuperuser, the Django shell) are outside the application;
# the grant is still recorded and announced (accounts.signals).

SUPERUSER_WIDENING = 'superuser (installation-wide control)'


def superuser_policy_on() -> bool:
    return ProtectionSettings.load().superuser_grant_requires_approval


def eligible_admins():
    """Administrators who may request and approve superuser grants: the
    protected-change approvers (active superusers)."""
    from .protected import approvers
    return approvers()


def enable_superuser_policy(by, request=None):
    """Turn the policy on. Tightening, so it applies at once — but only when
    a second eligible administrator exists to approve future grants."""
    from .protected import is_approver
    if not is_approver(by):
        raise ValueError('Only an approver for protected changes can turn this on.')
    if eligible_admins().count() < 2:
        raise ValueError('This needs two different eligible administrators (active superusers who approve '
                         'protected changes). With one, nobody could approve a grant.')
    s = ProtectionSettings.load()
    if not s.superuser_grant_requires_approval:
        s.superuser_grant_requires_approval = True
        s.save(update_fields=['superuser_grant_requires_approval', 'updated_at'])
        _audit(by, 'update', 'superuser_policy', s.pk, 'Superuser grants now need a second administrator',
               extra={'event': 'superuser_policy_enabled', 'requested_by': by.get_username()})
    return s


def pending_superuser_policy_change():
    from .models import ProtectedChange
    return (ProtectedChange.objects.filter(kind='superuser_policy', status=ProtectedChange.PENDING,
                                           expires_at__gt=timezone.now()).first())


def propose_disable_superuser_policy(by, request=None):
    """Turning the policy off widens what one administrator can do, so it
    takes a second administrator like any other widening."""
    from .protected import can_widen_at_all, is_approver
    if not superuser_policy_on():
        raise ValueError('The policy is already off.')
    if not is_approver(by):
        raise ValueError('Only an approver for protected changes can request this.')
    existing = pending_superuser_policy_change()
    if existing is not None:
        return existing
    if not can_widen_at_all(by):
        raise ValueError('Turning this off needs a second administrator to approve it, and no other eligible '
                         'administrator exists. See docs/CLIENT_DATA_PROTECTION.md for host-level recovery.')
    return propose('superuser_policy', 'Turn off second-administrator approval for superuser grants',
                   {'enabled': False}, ['superuser grants without approval'], by, request=request)


@applier('superuser_policy')
def _apply_superuser_policy(change, reviewer):
    s = ProtectionSettings.load()
    s.superuser_grant_requires_approval = bool(change.payload.get('enabled'))
    s.save(update_fields=['superuser_grant_requires_approval', 'updated_at'])
    _audit(change.requested_by, 'update', 'superuser_policy', s.pk, f'Approved: {change.summary}',
           extra={'event': 'superuser_policy_disabled', 'requested_by': _name(change.requested_by),
                  'approved_by': _name(reviewer), 'change': change.pk})


def pending_superuser_grant(user):
    from .models import ProtectedChange
    return (ProtectedChange.objects.filter(kind='superuser_grant', target_user=user, status=ProtectedChange.PENDING,
                                           expires_at__gt=timezone.now()).order_by('-requested_at').first())


def propose_superuser_grant(user, by, request=None):
    """Record a pending superuser grant for `user`. One pending grant per
    account: asking again returns the open one."""
    from .protected import can_widen_at_all, is_approver
    if user.is_superuser:
        raise ValueError(f'{user.get_username()} is already a superuser.')
    if not is_approver(by):
        raise ValueError('Only an approver for protected changes can request a superuser grant.')
    existing = pending_superuser_grant(user)
    if existing is not None:
        return existing
    if not can_widen_at_all(by):
        raise ValueError('Granting superuser needs a second administrator to approve it, and no other eligible '
                         'administrator exists.')
    change = propose('superuser_grant', f'Grant superuser to {user.get_username()}', {'user': user.pk},
                     [SUPERUSER_WIDENING], by, target_user=user, affected=[user.pk], request=request)
    _audit(by, 'update', 'user', user.pk, f'Superuser grant requested for {user.get_username()}',
           extra={'event': 'superuser_grant_requested', 'change': change.pk,
                  'requested_by': by.get_username(), 'target': user.get_username()})
    return change


@applier('superuser_grant')
def _apply_superuser_grant(change, reviewer):
    from .protected import ProtectedChangeError
    user = get_user_model().objects.filter(pk=change.payload.get('user')).first()
    if user is None:
        raise ProtectedChangeError('That account no longer exists.')
    if user.is_superuser:
        raise ProtectedChangeError(f'{user.get_username()} is already a superuser.')
    user.is_superuser = True
    user._approved_superuser_grant = change.pk  # read by accounts.signals
    user.save(update_fields=['is_superuser'])
    _audit(change.requested_by, 'update', 'user', user.pk, f'Approved: {change.summary}',
           extra={'event': 'superuser_grant_approved', 'change': change.pk,
                  'requested_by': _name(change.requested_by), 'approved_by': _name(reviewer),
                  'target': user.get_username(), 'outcome': 'applied'})


def _name(user):
    return user.get_username() if user is not None else ''


# --- RMM tiers ---------------------------------------------------------------
#
# A technician's RMM tier comes from their global role template's rmm_tier
# (rmm_permissions.decision.tier_of). Giving or taking one — moving a
# technician's global role to or from a tiered template, or changing a
# template's tier — takes two administrators. The user edit / create pages
# go through propose_global_role; changes made elsewhere (shell, scripts)
# are not blocked but are audited (tech_access.signals).

RMM_TIERS = ('l1', 'l2', 'l3', 'platform_admin')


def template_tier(template) -> str:
    return (getattr(template, 'rmm_tier', '') or '') if template is not None else ''


def global_role_change_is_protected(old, new) -> bool:
    """A change of global role template that gives, takes or swaps a tier."""
    if getattr(old, 'pk', None) == getattr(new, 'pk', None):
        return False
    return bool(template_tier(old) or template_tier(new))


def _role_label(template):
    if template is None:
        return 'no global role'
    t = template_tier(template)
    return f'{template.name} (RMM {t})' if t else template.name


def pending_global_role(user):
    from .models import ProtectedChange
    return (ProtectedChange.objects.filter(kind='global_role', target_user=user, status=ProtectedChange.PENDING,
                                           expires_at__gt=timezone.now()).order_by('-requested_at').first())


def propose_global_role(user, template, by, request=None):
    """Record a pending change of `user`'s global role template to `template`
    (None = no global role). Asking again for the same role returns the open
    request; a different role while one is open is refused."""
    from accounts.models import UserProfile
    from .protected import can_widen_at_all, is_approver
    profile, _ = UserProfile.objects.get_or_create(user=user)
    old = profile.global_role_template
    if not global_role_change_is_protected(old, template):
        raise ValueError('This role change does not involve an RMM tier.')
    if not is_approver(by):
        raise ValueError('Only an approver for protected changes can change an RMM-tier role.')
    want = template.pk if template is not None else None
    existing = pending_global_role(user)
    if existing is not None:
        if existing.payload.get('role_template') == want:
            return existing
        raise ValueError(f'A global-role change for {user.get_username()} is already waiting for approval '
                         '(Settings → Security → Technician Access). Cancel it first.')
    if not can_widen_at_all(by):
        raise ValueError('Changing an RMM-tier role needs a second administrator to approve it, and no other '
                         'eligible administrator exists.')
    summary = f'Change the global role of {user.get_username()} from {_role_label(old)} to {_role_label(template)}'
    widening = [f'RMM tier {template_tier(template)}'] if template_tier(template) else \
        [f'RMM tier {template_tier(old)} removed; the role flags of {_role_label(template)} apply']
    change = propose('global_role', summary,
                     {'user': user.pk, 'role_template': want, 'from': old.pk if old is not None else None},
                     widening, by, target_user=user, affected=[user.pk], request=request)
    _audit(by, 'update', 'user_profile', profile.pk, f'RMM-tier role change requested for {user.get_username()}',
           extra={'event': 'rmm_tier_role_requested', 'change': change.pk, 'requested_by': by.get_username(),
                  'target': user.get_username(), 'from': _role_label(old), 'to': _role_label(template)})
    return change


@applier('global_role')
def _apply_global_role(change, reviewer):
    from accounts.models import RoleTemplate, UserProfile
    from .protected import ProtectedChangeError
    profile = UserProfile.objects.filter(user_id=change.payload.get('user')).select_related('user').first()
    if profile is None:
        raise ProtectedChangeError('That account no longer exists.')
    if profile.global_role_template_id != change.payload.get('from'):
        raise ProtectedChangeError('Their global role changed since this was requested. Propose it again.')
    want = change.payload.get('role_template')
    template = RoleTemplate.objects.filter(pk=want).first() if want else None
    if want and template is None:
        raise ProtectedChangeError('That role template no longer exists.')
    profile.global_role_template = template
    profile._approved_rmm_tier_change = change.pk  # read by tech_access.signals
    profile.save(update_fields=['global_role_template'])
    _audit(change.requested_by, 'update', 'user_profile', profile.pk, f'Approved: {change.summary}',
           extra={'event': 'rmm_tier_role_approved', 'change': change.pk,
                  'requested_by': _name(change.requested_by), 'approved_by': _name(reviewer),
                  'target': profile.user.get_username(), 'outcome': 'applied'})


def propose_rmm_tier(template, new_tier, by, request=None):
    """Record a pending change of `template`'s rmm_tier. Technicians who hold
    the template as their global role are affected and cannot approve it."""
    from accounts.models import UserProfile
    from .models import ProtectedChange
    from .protected import can_widen_at_all, is_approver
    new_tier = (new_tier or '').strip()
    if new_tier and new_tier not in RMM_TIERS:
        raise ValueError(f'Unknown RMM tier {new_tier!r}.')
    old_tier = template_tier(template)
    if new_tier == old_tier:
        raise ValueError(f'{template.name} already has that tier.')
    if not is_approver(by):
        raise ValueError('Only an approver for protected changes can change a role template\'s RMM tier.')
    existing = (ProtectedChange.objects.filter(kind='rmm_tier', status=ProtectedChange.PENDING,
                                               expires_at__gt=timezone.now(), payload__template=template.pk)
                .first())
    if existing is not None:
        if existing.payload.get('to') == new_tier:
            return existing
        raise ValueError(f'A tier change for {template.name} is already waiting for approval.')
    if not can_widen_at_all(by):
        raise ValueError('Changing an RMM tier needs a second administrator to approve it, and no other eligible '
                         'administrator exists.')
    holders = list(UserProfile.objects.filter(global_role_template=template).values_list('user_id', flat=True))
    summary = f'Change the RMM tier of role template {template.name} from {old_tier or "none"} to {new_tier or "none"}'
    widening = [f'RMM tier {new_tier} for {len(holders)} technician(s)'] if new_tier else \
        [f'RMM tier {old_tier} removed from {len(holders)} technician(s)']
    return propose('rmm_tier', summary, {'template': template.pk, 'from': old_tier, 'to': new_tier},
                   widening, by, affected=holders, request=request)


@applier('rmm_tier')
def _apply_rmm_tier(change, reviewer):
    from accounts.models import RoleTemplate
    from .protected import ProtectedChangeError
    template = RoleTemplate.objects.filter(pk=change.payload.get('template')).first()
    if template is None:
        raise ProtectedChangeError('That role template no longer exists.')
    if template_tier(template) != (change.payload.get('from') or ''):
        raise ProtectedChangeError('Its tier changed since this was requested. Propose it again.')
    template.rmm_tier = change.payload.get('to') or ''
    template._approved_rmm_tier_change = change.pk  # read by tech_access.signals
    template.save(update_fields=['rmm_tier'])
    _audit(change.requested_by, 'update', 'role_template', template.pk, f'Approved: {change.summary}',
           extra={'event': 'rmm_tier_template_approved', 'change': change.pk,
                  'requested_by': _name(change.requested_by), 'approved_by': _name(reviewer),
                  'template': template.name, 'outcome': 'applied'})
