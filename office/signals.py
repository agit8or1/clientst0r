"""Revocation hooks and file cleanup.

Sessions are revoked promptly when:
  * a membership is deactivated, deleted or changes role (that user's
    sessions are re-checked);
  * a role template changes (every live session is re-checked);
  * a user is deactivated;
  * a document / attachment / ticket attachment / Office file is deleted.

These signals are the fast path. The authoritative check is still the one in
office.tokens.validate and office.storage, which re-evaluate permission on
every read and write, so a change these signals miss (e.g. a bulk
queryset.update()) still takes effect on the next request.
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from .logging_filters import get_logger

logger = get_logger('office.signals')


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        logger.exception('Office revocation hook failed')


def _recheck_user_later(user_id, reason):
    from .sessions import recheck_user
    transaction.on_commit(lambda: _safe(recheck_user, user_id, reason))


@receiver(post_save, sender='accounts.Membership')
def membership_saved(sender, instance, created, **kwargs):
    if not created:
        _recheck_user_later(instance.user_id, 'membership changed')


@receiver(post_delete, sender='accounts.Membership')
def membership_deleted(sender, instance, **kwargs):
    _recheck_user_later(instance.user_id, 'membership removed')


@receiver(post_save, sender='accounts.RoleTemplate')
def role_template_saved(sender, instance, created, **kwargs):
    if not created:
        from .sessions import recheck_all
        transaction.on_commit(lambda: _safe(recheck_all, 'role changed'))


@receiver(post_save, sender='accounts.UserProfile')
def profile_saved(sender, instance, created, **kwargs):
    if not created:
        _recheck_user_later(instance.user_id, 'user type changed')


@receiver(post_save, sender='auth.User')
def user_saved(sender, instance, created, **kwargs):
    if not created and not instance.is_active:
        _recheck_user_later(instance.pk, 'user deactivated')


def _revoke_target(obj, reason):
    from .sessions import revoke_for_target
    from .targets import target_for
    _safe(revoke_for_target, target_for(obj), reason)


@receiver(pre_delete, sender='docs.Document')
def document_deleting(sender, instance, **kwargs):
    if instance.content_type == 'file':
        _revoke_target(instance, 'document deleted')


@receiver(post_save, sender='docs.Document')
def document_saved(sender, instance, created, **kwargs):
    if not created and instance.content_type != 'file':
        # Switched away from an uploaded file: Office sessions on it end.
        from .models import EditSession
        if EditSession.objects.filter(document=instance, state__in=EditSession.LIVE_STATES).exists():
            _revoke_target(instance, 'document is no longer a file')


@receiver(pre_delete, sender='files.Attachment')
def attachment_deleting(sender, instance, **kwargs):
    _revoke_target(instance, 'attachment deleted')


@receiver(pre_delete, sender='psa.TicketAttachment')
def ticket_attachment_deleting(sender, instance, **kwargs):
    _revoke_target(instance, 'attachment deleted')


@receiver(pre_delete, sender='office.OfficeFile')
def office_file_deleting(sender, instance, **kwargs):
    _revoke_target(instance, 'file deleted')


@receiver(post_delete, sender='office.FileRevision')
def revision_deleted(sender, instance, **kwargs):
    name = instance.file.name if instance.file else ''
    if name:
        from .storage import purge_unreferenced_file
        transaction.on_commit(lambda: _safe(purge_unreferenced_file, name))
