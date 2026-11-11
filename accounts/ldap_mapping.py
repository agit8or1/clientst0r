"""
LDAP / Active Directory group -> customer membership mapping.

Admins map a directory group DN to a customer and a role (Settings ->
Directory Services -> Group mappings). On each LDAP sign-in:

- for every mapped group the user is in, the user gets an active membership
  in the mapped customer with the mapped role (created, re-activated or
  re-roled as needed);
- a membership the mapping created is deactivated when the user is no longer
  in any active mapped group for that customer;
- a membership that was not created by a mapping (made by hand, by invite,
  by import) is never created over, changed or deactivated.

Every change is written to the audit log. Group DNs compare
case-insensitively. Membership is evaluated per customer: a group mapped to
customer A can only ever create or keep a membership in A.
"""
import logging

from django.db import transaction

logger = logging.getLogger('accounts.ldap')


def active_mappings():
    from accounts.models import LDAPGroupMapping
    return list(LDAPGroupMapping.objects.filter(
        is_active=True, organization__is_active=True,
    ).select_related('organization', 'role_template').order_by('pk'))


def member_mapping_ids(mappings, is_member):
    """Ids of `mappings` whose group the user belongs to. `is_member(dn)` is
    called once per distinct (case-insensitive) group DN."""
    seen = {}
    ids = set()
    for m in mappings:
        key = m.group_dn_normalized
        if key not in seen:
            seen[key] = bool(is_member(m.group_dn))
        if seen[key]:
            ids.add(m.pk)
    return ids


def _audit(user, action, membership, description, extra):
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=user, action=action, organization=membership.organization,
            object_type='membership', object_id=membership.pk,
            object_repr=str(membership)[:255], description=description,
            extra_data=dict(extra, source='ldap_group_mapping'),
        )
    except Exception:  # never let auditing break a sign-in
        logger.exception('Could not write LDAP mapping audit entry')


def sync_memberships(user, mappings, member_ids, skip_org_ids=(), trigger='sign_in'):
    """Apply the mapping result for `user`. Returns a list of change tuples
    (action, organization_id) for callers / tests.

    `skip_org_ids`: customers whose result is uncertain (a group lookup
    failed); nothing is granted, changed or removed there. `trigger` is
    recorded on every audit entry ('sign_in' or 'background_sync').
    """
    from accounts.models import Membership, Role

    skip_org_ids = set(skip_org_ids or ())
    changes = []
    # Customer -> mapping that grants it (lowest pk wins, but a mapping that
    # already manages the membership is kept so the role doesn't flap).
    managed = {m.organization_id: m for m in Membership.objects.filter(
        user=user, ldap_group_mapping__isnull=False).select_related('ldap_group_mapping')}
    wanted = {}
    for mapping in mappings:
        if (mapping.pk not in member_ids or not mapping.role_allowed()
                or mapping.organization_id in skip_org_ids):
            continue
        current = wanted.get(mapping.organization_id)
        existing = managed.get(mapping.organization_id)
        if current is None or (existing is not None
                               and existing.ldap_group_mapping_id == mapping.pk):
            wanted[mapping.organization_id] = mapping

    with transaction.atomic():
        for org_id, mapping in wanted.items():
            membership = Membership.objects.filter(user=user, organization_id=org_id).first()
            extra = {'group_dn': mapping.group_dn, 'mapping_id': mapping.pk,
                     'role_template': mapping.role_template.name, 'trigger': trigger}
            if membership is None:
                membership = Membership.objects.create(
                    user=user, organization_id=org_id, role=Role.READONLY,
                    role_template=mapping.role_template, ldap_group_mapping=mapping,
                    is_active=True)
                _audit(user, 'create', membership,
                       f'LDAP group mapping added {user.username} to {mapping.organization.name} '
                       f'as {mapping.role_template.name} (group {mapping.group_dn})', extra)
                changes.append(('create', org_id))
                continue
            if membership.ldap_group_mapping_id is None:
                # Created by hand: never touched by the mapping.
                continue
            fields, what = [], []
            if not membership.is_active:
                membership.is_active = True
                fields.append('is_active')
                what.append('re-activated')
            if membership.role_template_id != mapping.role_template_id:
                old = membership.role_template.name if membership.role_template else '(none)'
                membership.role_template = mapping.role_template
                fields.append('role_template')
                what.append(f'role {old} -> {mapping.role_template.name}')
                extra['previous_role_template'] = old
            if membership.ldap_group_mapping_id != mapping.pk:
                membership.ldap_group_mapping = mapping
                fields.append('ldap_group_mapping')
            if fields:
                membership.save(update_fields=fields + ['updated_at'])
                if what:
                    _audit(user, 'update', membership,
                           f'LDAP group mapping updated {user.username} in '
                           f'{mapping.organization.name}: {", ".join(what)} (group {mapping.group_dn})',
                           extra)
                    changes.append(('update', org_id))

        for org_id, membership in managed.items():
            if org_id in wanted or org_id in skip_org_ids or not membership.is_active:
                continue
            membership.is_active = False
            membership.save(update_fields=['is_active', 'updated_at'])
            _audit(user, 'update', membership,
                   f'LDAP group mapping deactivated {user.username} in '
                   f'{membership.organization.name}: no longer in a mapped group',
                   {'group_dn': membership.ldap_group_mapping.group_dn,
                    'mapping_id': membership.ldap_group_mapping_id,
                    'deactivated': True, 'trigger': trigger})
            changes.append(('deactivate', org_id))
    return changes


def deactivate_for_mapping(mapping, actor):
    """Before a mapping is deleted: deactivate the active memberships it
    manages (audited). They stay as inactive, unmanaged memberships."""
    changes = 0
    for membership in mapping.memberships.filter(is_active=True).select_related('user', 'organization'):
        membership.is_active = False
        membership.save(update_fields=['is_active', 'updated_at'])
        try:
            from audit.models import AuditLog
            AuditLog.log(
                user=actor, action='update', organization=membership.organization,
                object_type='membership', object_id=membership.pk,
                object_repr=str(membership)[:255],
                description=(f'LDAP group mapping {mapping.group_dn} removed: deactivated '
                             f'{membership.user.username} in {membership.organization.name}'),
                extra_data={'source': 'ldap_group_mapping', 'mapping_id': mapping.pk,
                            'deactivated': True})
        except Exception:
            logger.exception('Could not write LDAP mapping audit entry')
        changes += 1
    return changes
