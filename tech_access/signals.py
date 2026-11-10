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
