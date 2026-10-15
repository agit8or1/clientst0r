"""Signal receivers that fire outbound webhook events.

Connected from `CoreConfig.ready()`. Every receiver is wrapped so that a
webhook problem can never break the save, delete or login that triggered it;
delivery itself is deferred to after commit by `core.webhook_events.fire`.

Monitor and integration events are fired from their service code instead
(`monitoring.down_notifications`, `integrations.sync`), because what they
report is an outcome, not a row change.
"""
import functools
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_init, post_save

from core import webhook_events as wh

logger = logging.getLogger('core')


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception('Webhook signal %s failed', fn.__name__)
    return wrapper


def _skip(kwargs):
    return kwargs.get('raw', False)


# --- assets --------------------------------------------------------------

@_safe
def asset_saved(sender, instance, created, **kwargs):
    if _skip(kwargs):
        return
    wh.fire('asset.created' if created else 'asset.updated',
            instance.organization_id, wh.asset_data(instance))


@_safe
def asset_deleted(sender, instance, **kwargs):
    wh.fire('asset.deleted', instance.organization_id, wh.asset_data(instance))


# --- documents -----------------------------------------------------------

@_safe
def document_saved(sender, instance, created, **kwargs):
    if _skip(kwargs) or not instance.organization_id:
        return  # global KB articles belong to no organization
    wh.fire('document.created' if created else 'document.updated',
            instance.organization_id, wh.document_data(instance))


@_safe
def document_deleted(sender, instance, **kwargs):
    if instance.organization_id:
        wh.fire('document.deleted', instance.organization_id, wh.document_data(instance))


# --- vault (metadata only) -----------------------------------------------

@_safe
def password_saved(sender, instance, created, **kwargs):
    if _skip(kwargs) or instance.is_personal:
        return  # personal "My Vault" entries are never announced
    wh.fire('password.created' if created else 'password.updated',
            instance.organization_id, wh.password_data(instance))


@_safe
def password_deleted(sender, instance, **kwargs):
    if not instance.is_personal:
        wh.fire('password.deleted', instance.organization_id, wh.password_data(instance))


_REVEAL_EVENTS = {'vault_extension_reveal', 'vault_extension_totp'}


@_safe
def audit_logged(sender, instance, created, **kwargs):
    """`password.accessed`: a successful reveal on any channel.

    Web, REST API and mobile reveals log action='reveal'; the browser
    extension logs action='read' with an `event` marker. Blocked attempts and
    list/autofill reads are not reveals.
    """
    if not created or _skip(kwargs):
        return
    if instance.object_type not in ('password', 'vault.Password') or not instance.object_id:
        return
    extra = instance.extra_data or {}
    if not instance.success or 'blocked_reason' in extra:
        return
    is_reveal = instance.action == 'reveal' or (
        instance.action == 'read' and extra.get('event') in _REVEAL_EVENTS)
    if not is_reveal:
        return
    from vault.models import Password
    pw = Password.objects.filter(pk=instance.object_id).only(
        'id', 'title', 'password_type', 'folder_id', 'organization_id', 'is_personal').first()
    if pw is None or pw.is_personal:
        return
    data = wh.password_data(pw)
    data['accessed_by'] = instance.username or wh._username(instance.user)
    wh.fire('password.accessed', pw.organization_id, data)


# --- locations / organizations ------------------------------------------

@_safe
def location_saved(sender, instance, created, **kwargs):
    if _skip(kwargs) or not instance.organization_id:
        return
    wh.fire('location.created' if created else 'location.updated',
            instance.organization_id, wh.location_data(instance))


@_safe
def location_deleted(sender, instance, **kwargs):
    if instance.organization_id:
        wh.fire('location.deleted', instance.organization_id, wh.location_data(instance))


@_safe
def organization_saved(sender, instance, created, **kwargs):
    # A new organization has no webhooks yet, and a deleted one takes its
    # webhooks with it, so only updates are deliverable.
    if _skip(kwargs) or created:
        return
    wh.fire('organization.updated', instance.pk,
            {'organization_id': instance.pk, 'name': instance.name, 'slug': instance.slug})


# --- workflows (process executions) -------------------------------------

_WORKFLOW_EVENTS = {
    'in_progress': 'workflow.started',
    'completed': 'workflow.completed',
    'failed': 'workflow.failed',
}


def execution_init(sender, instance, **kwargs):
    instance._wh_status = instance.__dict__.get('status')


@_safe
def execution_saved(sender, instance, created, **kwargs):
    if _skip(kwargs):
        return
    previous = None if created else getattr(instance, '_wh_status', None)
    instance._wh_status = instance.status
    if instance.status == previous:
        return
    event = _WORKFLOW_EVENTS.get(instance.status)
    if event:
        wh.fire(event, instance.organization_id, wh.workflow_data(instance))


# --- users ---------------------------------------------------------------

@_safe
def on_login(sender, request, user, **kwargs):
    wh.fire_for_user('user.login', user)


@_safe
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        wh.fire_for_user('user.logout', user)


@_safe
def on_login_failed(sender, credentials, request=None, **kwargs):
    # Only the username is read from `credentials`; nothing else is sent.
    username = (credentials or {}).get('username')
    if not username:
        return
    user = get_user_model().objects.filter(username=username).first()
    if user is not None:
        wh.fire_for_user('user.login_failed', user)


def user_init(sender, instance, **kwargs):
    instance._wh_password = instance.__dict__.get('password')


@_safe
def user_saved(sender, instance, created, **kwargs):
    if _skip(kwargs):
        return
    previous = getattr(instance, '_wh_password', None)
    instance._wh_password = instance.password
    if not created and previous and instance.password != previous:
        wh.fire_for_user('user.password_changed', instance)


def connect():
    from assets.models import Asset
    from audit.models import AuditLog
    from core.models import Organization
    from docs.models import Document
    from locations.models import Location
    from processes.models import ProcessExecution
    from vault.models import Password

    User = get_user_model()
    uid = 'core.webhooks.'

    post_save.connect(asset_saved, sender=Asset, dispatch_uid=uid + 'asset_saved')
    post_delete.connect(asset_deleted, sender=Asset, dispatch_uid=uid + 'asset_deleted')
    post_save.connect(document_saved, sender=Document, dispatch_uid=uid + 'document_saved')
    post_delete.connect(document_deleted, sender=Document, dispatch_uid=uid + 'document_deleted')
    post_save.connect(password_saved, sender=Password, dispatch_uid=uid + 'password_saved')
    post_delete.connect(password_deleted, sender=Password, dispatch_uid=uid + 'password_deleted')
    post_save.connect(audit_logged, sender=AuditLog, dispatch_uid=uid + 'audit_logged')
    post_save.connect(location_saved, sender=Location, dispatch_uid=uid + 'location_saved')
    post_delete.connect(location_deleted, sender=Location, dispatch_uid=uid + 'location_deleted')
    post_save.connect(organization_saved, sender=Organization, dispatch_uid=uid + 'org_saved')
    post_init.connect(execution_init, sender=ProcessExecution, dispatch_uid=uid + 'exec_init')
    post_save.connect(execution_saved, sender=ProcessExecution, dispatch_uid=uid + 'exec_saved')
    post_init.connect(user_init, sender=User, dispatch_uid=uid + 'user_init')
    post_save.connect(user_saved, sender=User, dispatch_uid=uid + 'user_saved')
    user_logged_in.connect(on_login, dispatch_uid=uid + 'login')
    user_logged_out.connect(on_logout, dispatch_uid=uid + 'logout')
    user_login_failed.connect(on_login_failed, dispatch_uid=uid + 'login_failed')
