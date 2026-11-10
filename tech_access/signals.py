"""Record every superuser grant that did not come through an approval (v3.17.653).

The application's own paths (user create and edit pages, Django admin) turn
a grant into a protected change while the policy is on. Anything else that
sets `is_superuser` — `manage.py createsuperuser`, the Django shell, a script
on the host — is outside the application's control. Such grants are not
blocked (they are how a locked-out install recovers), but each one is audited
and announced to the verified recovery contact and the other superusers.
"""
import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger('tech_access')
User = get_user_model()


@receiver(pre_save, sender=User, dispatch_uid='tech_access_superuser_before')
def _remember_superuser_flag(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or (update_fields is not None and 'is_superuser' not in update_fields):
        return  # e.g. last_login on every sign-in: nothing to compare
    instance._was_superuser = bool(instance.pk and User.objects.filter(
        pk=instance.pk, is_superuser=True).exists())


@receiver(post_save, sender=User, dispatch_uid='tech_access_superuser_after')
def _record_superuser_grant(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw or (update_fields is not None and 'is_superuser' not in update_fields):
        return
    if not instance.is_superuser or getattr(instance, '_was_superuser', False):
        return
    instance._was_superuser = True
    approved = getattr(instance, '_approved_superuser_grant', None)
    if approved:
        return  # recorded by the approval itself
    try:
        from audit.models import AuditLog
        from .models import ProtectionSettings
        settings_obj = ProtectionSettings.load()
        policy = settings_obj.superuser_grant_requires_approval
        first = not User.objects.filter(is_superuser=True).exclude(pk=instance.pk).exists()
        AuditLog.log(user=None, action='update', object_type='user', object_id=instance.pk,
                     object_repr=instance.get_username()[:255],
                     description=(f'Superuser granted to {instance.get_username()} outside the approval '
                                  f'process{" (first superuser)" if first else ""}'),
                     extra_data={'event': 'superuser_granted_outside_approval', 'target': instance.get_username(),
                                 'policy_on': policy, 'created': created, 'first_superuser': first,
                                 'outcome': 'applied'})
        if policy and not first:
            _announce(instance, settings_obj)
    except Exception:  # the grant itself must not fail because the record did
        logger.exception('could not record superuser grant')


def _announce(user, settings_obj):
    from django.core.mail import send_mail
    recipients = {u.email for u in User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk)
                  if u.email}
    if settings_obj.recovery_email and settings_obj.recovery_verified_at:
        recipients.add(settings_obj.recovery_email)
    if not recipients:
        return
    send_mail('[ClientSt0r] Superuser granted outside approval',
              f'{user.get_username()} was made a superuser without a second administrator\'s approval — '
              'for example with manage.py createsuperuser on the host. If you did not expect this, review '
              'the account and the audit log now.',
              None, sorted(recipients), fail_silently=True)


# --- role changes, with before/after (for the effective-access "why") --------
#
# A technician's global standing (user type, global role template) and their
# membership role at a customer are inputs to the "why" view. Changes to them
# are recorded here, whatever path made them, so the view can show when and
# by whom each was set.

from accounts.models import Membership, UserProfile  # noqa: E402

ROLE_FIELDS = {
    Membership: ('role', 'role_template_id', 'is_active'),
    UserProfile: ('user_type', 'global_role_template_id'),
}


def _role_state(instance):
    from accounts.models import RoleTemplate
    out = {}
    for f in ROLE_FIELDS[type(instance)]:
        value = getattr(instance, f)
        if f.endswith('_template_id'):
            value = RoleTemplate.objects.filter(pk=value).values_list('name', flat=True).first() if value else None
            f = f[:-3]
        out[f] = value
    return out


def _remember_roles(sender, instance, raw=False, **kwargs):
    if raw:
        return
    try:
        old = sender.objects.filter(pk=instance.pk).first() if instance.pk else None
        instance._role_before = _role_state(old) if old is not None else None
    except Exception:  # noqa: BLE001
        instance._role_before = None


def _record_roles(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        before = getattr(instance, '_role_before', None)
        after = _role_state(instance)
        if before == after:
            return
        if sender is UserProfile and before is None and after.get('user_type') != 'staff' \
                and not after.get('global_role_template'):
            return  # every new account gets a customer-user profile; nothing to explain
        from audit.models import AuditLog
        from .actor import current
        user, ip, path = current()
        if sender is Membership:
            obj_type, org = 'membership', instance.organization
            text = (f'Membership of {instance.user.get_username()} at {instance.organization.name}: '
                    f'{"created" if before is None else "role changed"}')
        else:
            obj_type, org = 'user_profile', None
            text = f'Staff standing of {instance.user.get_username()}: {"created" if before is None else "changed"}'
        AuditLog.log(user=user, action='create' if before is None else 'update', organization=org,
                     object_type=obj_type, object_id=instance.pk, object_repr=text[:255], description=text,
                     ip_address=ip, path=path,
                     extra_data={'event': 'role_change', 'user_id': instance.user_id, 'before': before,
                                 'after': after, 'actor_known': user is not None})
    except Exception:  # an audit entry must never break the save
        logger.exception('could not record role change')


for _model in ROLE_FIELDS:
    pre_save.connect(_remember_roles, sender=_model, dispatch_uid=f'tech_access_roles_before_{_model.__name__}')
    post_save.connect(_record_roles, sender=_model, dispatch_uid=f'tech_access_roles_after_{_model.__name__}')
