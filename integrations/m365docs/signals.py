"""Revoke Edit in Microsoft 365 sessions when permission goes away.

The same events that revoke ONLYOFFICE / Collabora sessions (office.signals):
membership or role changes, a user deactivated or turned into another user
type, a file deleted. Only database rows change here; the working copy is
deleted (when policy says so) by the m365_edit_sessions scheduled task.
Every session action re-checks permission anyway, so a change these signals
miss still takes effect on the next request.
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from office.logging_filters import get_logger

logger = get_logger('office.m365')


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        logger.exception('Microsoft 365 edit-session revocation hook failed')


def _recheck_user(user_id, reason):
    from . import editing
    transaction.on_commit(lambda: _safe(editing.recheck_user, user_id, reason))


@receiver(post_save, sender='accounts.Membership', dispatch_uid='m365edit_membership_saved')
def membership_saved(sender, instance, created, **kwargs):
    if not created:
        _recheck_user(instance.user_id, 'membership changed')


@receiver(post_delete, sender='accounts.Membership', dispatch_uid='m365edit_membership_deleted')
def membership_deleted(sender, instance, **kwargs):
    _recheck_user(instance.user_id, 'membership removed')


@receiver(post_save, sender='accounts.RoleTemplate', dispatch_uid='m365edit_role_saved')
def role_template_saved(sender, instance, created, **kwargs):
    if not created:
        from . import editing
        transaction.on_commit(lambda: _safe(editing.recheck_all, 'role changed'))


@receiver(post_save, sender='accounts.UserProfile', dispatch_uid='m365edit_profile_saved')
def profile_saved(sender, instance, created, **kwargs):
    if not created:
        _recheck_user(instance.user_id, 'user type changed')


@receiver(post_save, sender='auth.User', dispatch_uid='m365edit_user_saved')
def user_saved(sender, instance, created, **kwargs):
    if not created and not instance.is_active:
        _recheck_user(instance.pk, 'user deactivated')


def _revoke_target(obj, reason):
    from office.targets import target_for
    from . import editing
    _safe(editing.revoke_for_target, target_for(obj), reason)


@receiver(pre_delete, sender='docs.Document', dispatch_uid='m365edit_document_deleting')
def document_deleting(sender, instance, **kwargs):
    if instance.content_type == 'file':
        _revoke_target(instance, 'file deleted')


@receiver(pre_delete, sender='files.Attachment', dispatch_uid='m365edit_attachment_deleting')
def attachment_deleting(sender, instance, **kwargs):
    _revoke_target(instance, 'file deleted')


@receiver(pre_delete, sender='psa.TicketAttachment', dispatch_uid='m365edit_ticket_att_deleting')
def ticket_attachment_deleting(sender, instance, **kwargs):
    _revoke_target(instance, 'file deleted')
