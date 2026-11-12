"""
Authorization side effects of every change, whatever path made it (views,
API, LDAP / Azure sign-in, imports, Django admin, shell):

  * drop the authorization memo (accounts.authz_cache.invalidate), so the
    next check reads the new state;
  * write the role audit trail (accounts.role_audit) with safe before/after.

Hooked up in AccountsConfig.ready().
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from . import authz_cache, role_audit
from .models import Membership, RoleTemplate, UserProfile

_MEMBERSHIP_FIELDS = ('role', 'role_template_id', 'is_active', 'record_scope', 'is_org_admin', 'organization_id',
                      'user_id')
_PROFILE_FIELDS = ('user_type', 'global_role_template_id', 'client_scope', 'record_scope')
_USER_FIELDS = ('is_active', 'is_superuser', 'is_staff')


def _snapshot(obj, fields):
    return {f: getattr(obj, f) for f in fields}


def _role_snapshot(rt):
    data = rt.permission_values()
    data.update(name=rt.name, rmm_tier=rt.rmm_tier, is_archived=rt.is_archived, audience=rt.audience,
                organization_id=rt.organization_id)
    return data


def _load_before(sender, instance, fields=None, snap=None):
    if not instance.pk:
        return None
    old = sender._default_manager.filter(pk=instance.pk).first()
    if old is None:
        return None
    return snap(old) if snap else _snapshot(old, fields)


# --- role templates -------------------------------------------------------------

@receiver(pre_save, sender=RoleTemplate)
def _rt_pre(sender, instance, raw=False, **kw):
    if raw:
        return
    instance._authz_before = _load_before(sender, instance, snap=_role_snapshot)


@receiver(post_save, sender=RoleTemplate)
def _rt_post(sender, instance, created, raw=False, **kw):
    authz_cache.invalidate('role_template')
    if raw:
        return
    after = _role_snapshot(instance)
    before = getattr(instance, '_authz_before', None)
    if created:
        role_audit.record('role.created', target_type='role_template', target_id=instance.pk,
                          target_repr=instance.name, organization=instance.organization_id,
                          after={k: v for k, v in after.items() if v not in (False, '', None)})
        return
    if before is None:
        return
    b, a = role_audit.diff(before, after)
    if b or a:
        event = 'role.archived' if a.get('is_archived') is True else 'role.updated'
        affected = Membership.objects.filter(role_template=instance).count()
        role_audit.record(event, target_type='role_template', target_id=instance.pk,
                          target_repr=instance.name, organization=instance.organization_id, before=b, after=a,
                          extra={'affected_memberships': affected})


@receiver(post_delete, sender=RoleTemplate)
def _rt_delete(sender, instance, **kw):
    authz_cache.invalidate('role_template')
    role_audit.record('role.deleted', target_type='role_template', target_id=instance.pk,
                      target_repr=instance.name, organization=instance.organization_id)


# --- memberships ----------------------------------------------------------------

@receiver(pre_save, sender=Membership)
def _m_pre(sender, instance, raw=False, **kw):
    if raw:
        return
    instance._authz_before = _load_before(sender, instance, _MEMBERSHIP_FIELDS)


def _membership_repr(m):
    try:
        return f'{m.user.username} @ {m.organization.name}'
    except Exception:
        return f'membership {m.pk}'


@receiver(post_save, sender=Membership)
def _m_post(sender, instance, created, raw=False, **kw):
    authz_cache.invalidate('membership')
    if raw:
        return
    after = _snapshot(instance, _MEMBERSHIP_FIELDS)
    if created:
        role_audit.record('membership.created', target_type='membership', target_id=instance.pk,
                          target_repr=_membership_repr(instance), organization=instance.organization_id,
                          after=after)
        return
    before = getattr(instance, '_authz_before', None)
    if before is None:
        return
    b, a = role_audit.diff(before, after)
    if b or a:
        role_audit.record('membership.updated', target_type='membership', target_id=instance.pk,
                          target_repr=_membership_repr(instance), organization=instance.organization_id,
                          before=b, after=a)


@receiver(post_delete, sender=Membership)
def _m_delete(sender, instance, **kw):
    authz_cache.invalidate('membership')
    role_audit.record('membership.deleted', target_type='membership', target_id=instance.pk,
                      target_repr=f'user {instance.user_id} @ org {instance.organization_id}',
                      organization=instance.organization_id,
                      before=_snapshot(instance, _MEMBERSHIP_FIELDS))


@receiver(m2m_changed, sender=Membership.additional_roles.through)
def _m_roles(sender, instance, action, pk_set, **kw):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return
    authz_cache.invalidate('membership_roles')
    if hasattr(instance, '_additional_roles_memo'):
        del instance._additional_roles_memo
    if isinstance(instance, Membership):
        names = list(RoleTemplate.objects.filter(pk__in=pk_set or []).values_list('name', flat=True))
        role_audit.record('membership.roles_changed', target_type='membership', target_id=instance.pk,
                          target_repr=_membership_repr(instance), organization=instance.organization_id,
                          extra={'change': action.replace('post_', ''), 'roles': names})


# --- profiles and accounts --------------------------------------------------------

@receiver(pre_save, sender=UserProfile)
def _p_pre(sender, instance, raw=False, **kw):
    if raw:
        return
    instance._authz_before = _load_before(sender, instance, _PROFILE_FIELDS)


@receiver(post_save, sender=UserProfile)
def _p_post(sender, instance, created, raw=False, **kw):
    before = getattr(instance, '_authz_before', None)
    after = _snapshot(instance, _PROFILE_FIELDS)
    if created or before is None:
        authz_cache.invalidate('profile')
        return
    b, a = role_audit.diff(before, after)
    if b or a:
        authz_cache.invalidate('profile')
        role_audit.record('profile.access_changed', target_type='user', target_id=instance.user_id,
                          target_repr=getattr(instance.user, 'username', ''), before=b, after=a)


@receiver(m2m_changed, sender=UserProfile.scope_organizations.through)
def _p_scope(sender, instance, action, pk_set, **kw):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return
    authz_cache.invalidate('client_scope')
    if isinstance(instance, UserProfile):
        role_audit.record('profile.access_changed', target_type='user', target_id=instance.user_id,
                          target_repr=getattr(instance.user, 'username', ''),
                          extra={'scope_organizations': action.replace('post_', ''),
                                 'organization_ids': sorted(pk_set or [])})


@receiver(pre_save, sender=User)
def _u_pre(sender, instance, raw=False, **kw):
    if raw:
        return
    instance._authz_before = _load_before(sender, instance, _USER_FIELDS)


@receiver(post_save, sender=User)
def _u_post(sender, instance, created, raw=False, **kw):
    before = getattr(instance, '_authz_before', None)
    if created or before is None or raw:
        return
    b, a = role_audit.diff(before, _snapshot(instance, _USER_FIELDS))
    if b or a:
        authz_cache.invalidate('account')
        role_audit.record('account.status_changed', target_type='user', target_id=instance.pk,
                          target_repr=instance.username, before=b, after=a)


# --- anything else that changes reach -------------------------------------------------

def _invalidate(*_a, **_k):
    authz_cache.invalidate('related')


def connect_related():
    from core.models import Organization
    post_save.connect(_invalidate, sender=Organization, dispatch_uid='authz_org_save')
    post_delete.connect(_invalidate, sender=Organization, dispatch_uid='authz_org_delete')
    try:
        from tech_access.models import AccessAssignment, TechnicianGroup
        post_save.connect(_invalidate, sender=AccessAssignment, dispatch_uid='authz_ta_save')
        post_delete.connect(_invalidate, sender=AccessAssignment, dispatch_uid='authz_ta_delete')
        m2m_changed.connect(_invalidate, sender=TechnicianGroup.members.through, dispatch_uid='authz_ta_group')
    except Exception:  # pragma: no cover - app missing
        pass
