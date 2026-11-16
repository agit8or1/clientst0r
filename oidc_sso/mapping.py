"""Token roles -> local access, applied at every SSO sign-in.

Rules (ARCHITECTURE.md §5.1 / §5.2, CLIENTST0R_TASKS.md CS-ID-06):

* Customer roles ("<alias>:customer:<key>:<role>") -> a membership in the
  customer mapped to <key>, with the role mapped for <role>. Only
  memberships SSO created (OIDCManagedMembership) are ever re-roled,
  re-activated or deactivated; a membership made by hand, invite or LDAP
  for the same customer is never touched. When a role disappears from the
  token, the membership it created is deactivated at the next sign-in.
* Staff roles ("<alias>:<role>") -> MSP staff global role. Only applied to
  accounts SSO manages (identity.manages_staff_role, i.e. created by JIT, or
  switched on by a superuser). Linked accounts keep their local role.
* Customer claims are a ceiling for managed staff: when the token lists any
  customer, the client scope becomes those (mapped) customers, intersected
  with the mapping's own scope. They never widen it.
* Never: is_superuser, is_staff (Django admin), or anything else outside
  user type / global role / client scope / tagged memberships.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from django.db import transaction

from .models import OIDCCustomerMapping, OIDCManagedMembership, OIDCManagedScope, OIDCRoleMapping

logger = logging.getLogger('oidc_sso')


@dataclass
class MappingResult:
    staff_mapping: Optional[OIDCRoleMapping] = None
    customer_roles: dict = field(default_factory=dict)  # org_id -> OIDCRoleMapping
    changes: list = field(default_factory=list)

    @property
    def any_role(self):
        return self.staff_mapping is not None or bool(self.customer_roles)


def _role_allowed_for(rt, org_id=None):
    if rt is None or rt.is_archived:
        return False
    if org_id is None:
        return rt.organization_id is None and rt.audience != 'customer'
    return rt.organization_id in (None, org_id)


def resolve(provider, roles) -> MappingResult:
    """What the token's roles map to (no writes)."""
    result = MappingResult()
    mappings = list(OIDCRoleMapping.objects.filter(provider=provider, is_active=True)
                    .select_related('role_template').order_by('priority', 'pk'))
    for m in mappings:
        if m.target == OIDCRoleMapping.TARGET_STAFF and m.role_key in roles.staff \
                and _role_allowed_for(m.role_template):
            result.staff_mapping = m
            break
    if roles.customers:
        customer_maps = {c.customer_key: c for c in OIDCCustomerMapping.objects.filter(
            provider=provider, customer_key__in=list(roles.customers), organization__is_active=True)}
        by_key = {}
        for m in mappings:
            if m.target == OIDCRoleMapping.TARGET_CUSTOMER:
                by_key.setdefault(m.role_key, m)
        for key, role_keys in sorted(roles.customers.items()):
            cmap = customer_maps.get(key)
            if cmap is None:
                continue
            for rk in sorted(role_keys, key=lambda r: (by_key[r].priority, by_key[r].pk) if r in by_key else (0, 0)):
                m = by_key.get(rk)
                if m is not None and _role_allowed_for(m.role_template, cmap.organization_id):
                    result.customer_roles.setdefault(cmap.organization_id, m)
                    break
    return result


def customer_org_ids(provider, roles):
    """Organizations of every mapped customer key in the token (the ceiling)."""
    if not roles.customers:
        return set()
    return set(OIDCCustomerMapping.objects.filter(
        provider=provider, customer_key__in=list(roles.customers),
        organization__is_active=True).values_list('organization_id', flat=True))


def _audit(event, user, membership=None, **extra):
    from accounts import role_audit
    role_audit.record(
        event, target_type='membership' if membership else 'user_profile',
        target_id=membership.pk if membership else user.pk,
        target_repr=str(membership or user)[:255],
        organization=membership.organization if membership else None,
        extra=dict(extra, source='oidc', user=user.username),
        description=f'SSO mapping: {event} for {user.username}')


def sync_memberships(provider, user, result: MappingResult):
    from accounts.models import Membership, Role
    changes = []
    managed = {t.membership.organization_id: t for t in OIDCManagedMembership.objects.filter(
        provider=provider, membership__user=user).select_related('membership', 'membership__organization')}
    with transaction.atomic():
        for org_id, mapping in result.customer_roles.items():
            membership = Membership.objects.filter(user=user, organization_id=org_id).first()
            if membership is None:
                membership = Membership.objects.create(
                    user=user, organization_id=org_id, role=Role.READONLY,
                    role_template=mapping.role_template, is_active=True)
                OIDCManagedMembership.objects.create(membership=membership, provider=provider,
                                                     role_mapping=mapping)
                _audit('membership.created', user, membership, role=mapping.role_template.name,
                       role_key=mapping.role_key)
                changes.append(('create', org_id))
                continue
            tag = managed.get(org_id)
            if tag is None or tag.membership_id != membership.pk:
                continue  # made by hand / invite / LDAP: never touched
            fields = []
            if not membership.is_active:
                membership.is_active = True
                fields.append('is_active')
            if membership.role_template_id != mapping.role_template_id:
                membership.role_template = mapping.role_template
                fields.append('role_template')
            if tag.role_mapping_id != mapping.pk:
                tag.role_mapping = mapping
                tag.save(update_fields=['role_mapping'])
            if fields:
                membership.save(update_fields=fields + ['updated_at'])
                _audit('membership.updated', user, membership, changed=fields,
                       role=mapping.role_template.name, role_key=mapping.role_key)
                changes.append(('update', org_id))
        for org_id, tag in managed.items():
            if org_id in result.customer_roles or not tag.membership.is_active:
                continue
            tag.membership.is_active = False
            tag.membership.save(update_fields=['is_active', 'updated_at'])
            _audit('membership.updated', user, tag.membership, deactivated=True,
                   reason='role no longer in the token')
            changes.append(('deactivate', org_id))
    return changes


def sync_staff_profile(provider, identity, roles, result: MappingResult):
    """Managed accounts only: user type, global role and client scope."""
    from accounts.models import UserProfile, UserType
    if not identity.manages_staff_role or result.staff_mapping is None:
        return []
    user = identity.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    mapping = result.staff_mapping
    before = {'user_type': profile.user_type, 'global_role': profile.global_role_template_id,
              'client_scope': profile.client_scope}

    ceiling = customer_org_ids(provider, roles) if roles.has_customer_claims else None
    scope_ids = None
    if ceiling is not None:
        if mapping.client_scope == 'assigned':
            from django.db.models import Q
            from tech_access.models import AccessAssignment
            assigned = set(AccessAssignment.objects.live().filter(Q(user=user) | Q(group__members=user))
                           .values_list('organization_id', flat=True))
            ceiling &= assigned
        scope = 'selected'
        scope_ids = sorted(ceiling)
    else:
        scope = mapping.client_scope

    with transaction.atomic():
        profile.user_type = UserType.STAFF
        profile.global_role_template = mapping.role_template
        profile.client_scope = scope
        profile.save(update_fields=['user_type', 'global_role_template', 'client_scope', 'updated_at'])
        tracked, _ = OIDCManagedScope.objects.get_or_create(identity=identity)
        if scope == 'selected':
            # Exactly the ceiling: anything else on the list would widen it.
            profile.scope_organizations.set(scope_ids)
            tracked.organization_ids = scope_ids
        else:
            if tracked.organization_ids:
                profile.scope_organizations.remove(*tracked.organization_ids)
            tracked.organization_ids = []
        tracked.save()
    after = {'user_type': profile.user_type, 'global_role': profile.global_role_template_id,
             'client_scope': profile.client_scope}
    if before != after:
        from accounts import role_audit
        b, a = role_audit.diff(before, after)
        role_audit.record('profile.access_changed', target_type='user', target_id=user.pk,
                          target_repr=user.username, before=b, after=a,
                          extra={'source': 'oidc', 'role_key': mapping.role_key,
                                 'scope_organizations': scope_ids},
                          description=f'SSO mapping updated staff access for {user.username}')
        return [('profile', user.pk)]
    return []


def apply(provider, identity, roles, result=None):
    result = result or resolve(provider, roles)
    changes = sync_memberships(provider, identity.user, result)
    changes += sync_staff_profile(provider, identity, roles, result)
    if changes:
        try:
            from accounts import authz_cache
            authz_cache.invalidate('oidc mapping')
        except Exception:
            logger.exception('authz cache invalidation failed')
    result.changes = changes
    return result
