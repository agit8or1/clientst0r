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


# --- tickets, contacts, invoices ----------------------------------------
#
# Each model keeps a snapshot of the fields its events report on (taken in
# post_init, refreshed after every save), so a save that changes nothing a
# receiver can see — SLA bookkeeping, response timestamps, AI fields — sends
# nothing. Fields deferred out of the load are left out of the comparison.
#
# A status change sends `*.status_changed` (with `previous_status`), never
# `*.updated`; `*.updated` sends when another reported field changed and
# lists them in `changed_fields`. A save that changes both sends both.

_TICKET_UPDATE_FIELDS = ('subject', 'priority_id', 'ticket_type_id', 'contact_id')
_TICKET_FIELDS = _TICKET_UPDATE_FIELDS + ('status_id', 'client_can_view')
_CONTACT_FIELDS = ('first_name', 'last_name', 'email', 'phone', 'title')
_INVOICE_UPDATE_FIELDS = ('invoice_number', 'title', 'invoice_date', 'due_date',
                          'currency', 'subtotal', 'tax_amount', 'total', 'amount_paid')
_INVOICE_FIELDS = _INVOICE_UPDATE_FIELDS + ('status',)


def _snapshot(instance, fields):
    return {f: instance.__dict__[f] for f in fields if f in instance.__dict__}


def _snapshot_init(fields):
    def receiver(sender, instance, **kwargs):
        instance._wh_fields = _snapshot(instance, fields)
    return receiver


ticket_init = _snapshot_init(_TICKET_FIELDS)
contact_init = _snapshot_init(_CONTACT_FIELDS)
invoice_init = _snapshot_init(_INVOICE_FIELDS)


def _diff(instance, fields):
    """(previous snapshot, names of fields that changed); refreshes the
    snapshot so the next save compares against what was just written."""
    previous = getattr(instance, '_wh_fields', None) or {}
    current = _snapshot(instance, fields)
    instance._wh_fields = current
    changed = {f for f, v in current.items() if f in previous and previous[f] != v}
    return previous, changed


def _field_names(changed, allowed):
    return sorted(f[:-3] if f.endswith('_id') else f for f in changed if f in allowed)


@_safe
def ticket_saved(sender, instance, created, **kwargs):
    """Ticket events follow the portal rule: only tickets shared with the
    customer (`client_can_view`) are announced, because a customer's own
    admins can create webhooks and read their deliveries. A ticket shared
    after it was created sends `ticket.created` at that point."""
    if _skip(kwargs):
        return
    previous, changed = _diff(instance, _TICKET_FIELDS)
    if not instance.client_can_view or not instance.organization_id:
        return
    org_id = instance.organization_id
    if created or 'client_can_view' in changed:
        wh.fire('ticket.created', org_id, wh.ticket_data(instance))
        return
    if 'status_id' in changed:
        from psa.models import TicketStatus
        data = wh.ticket_data(instance)
        data['previous_status'] = TicketStatus.objects.filter(
            pk=previous['status_id']).values_list('slug', flat=True).first()
        wh.fire('ticket.status_changed', org_id, data)
    fields = _field_names(changed, _TICKET_UPDATE_FIELDS)
    if fields:
        data = wh.ticket_data(instance)
        data['changed_fields'] = fields
        wh.fire('ticket.updated', org_id, data)


@_safe
def contact_saved(sender, instance, created, **kwargs):
    if _skip(kwargs):
        return
    _, changed = _diff(instance, _CONTACT_FIELDS)
    if not instance.organization_id:
        return
    if created:
        wh.fire('contact.created', instance.organization_id, wh.contact_data(instance))
        return
    fields = _field_names(changed, _CONTACT_FIELDS)
    if fields:
        data = wh.contact_data(instance)
        data['changed_fields'] = fields
        wh.fire('contact.updated', instance.organization_id, data)


@_safe
def invoice_saved(sender, instance, created, **kwargs):
    """Invoice events go to the billed customer (`client_org`). Drafts are
    never announced: `invoice.created` sends when an invoice is issued —
    created in a non-draft status, or moved out of draft."""
    if _skip(kwargs):
        return
    previous, changed = _diff(instance, _INVOICE_FIELDS)
    org_id = instance.client_org_id
    if not org_id or instance.status == 'draft':
        return
    if created or ('status' in changed and previous.get('status') == 'draft'):
        wh.fire('invoice.created', org_id, wh.invoice_data(instance))
        return
    if 'status' in changed:
        data = wh.invoice_data(instance)
        data['previous_status'] = previous['status']
        wh.fire('invoice.status_changed', org_id, data)
    fields = _field_names(changed, _INVOICE_UPDATE_FIELDS)
    if fields:
        data = wh.invoice_data(instance)
        data['changed_fields'] = fields
        wh.fire('invoice.updated', org_id, data)


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
    from assets.models import Contact
    from psa.models import Invoice, Ticket
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
    post_init.connect(ticket_init, sender=Ticket, dispatch_uid=uid + 'ticket_init')
    post_save.connect(ticket_saved, sender=Ticket, dispatch_uid=uid + 'ticket_saved')
    post_init.connect(contact_init, sender=Contact, dispatch_uid=uid + 'contact_init')
    post_save.connect(contact_saved, sender=Contact, dispatch_uid=uid + 'contact_saved')
    post_init.connect(invoice_init, sender=Invoice, dispatch_uid=uid + 'invoice_init')
    post_save.connect(invoice_saved, sender=Invoice, dispatch_uid=uid + 'invoice_saved')
    post_init.connect(user_init, sender=User, dispatch_uid=uid + 'user_init')
    post_save.connect(user_saved, sender=User, dispatch_uid=uid + 'user_saved')
    user_logged_in.connect(on_login, dispatch_uid=uid + 'login')
    user_logged_out.connect(on_logout, dispatch_uid=uid + 'logout')
    user_login_failed.connect(on_login_failed, dispatch_uid=uid + 'login_failed')
