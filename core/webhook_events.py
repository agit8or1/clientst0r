"""Outbound webhook events: where each one fires, and how it is delivered.

Until this module, the Webhooks page offered 32 event types and exactly two of
them ever fired — `asset.created` and `asset.updated` — and only from the web
form views, so an asset created over the API, the mobile app or an RMM sync sent
nothing. The rest were checkboxes that did nothing.

Now:

* Events fire from model signals or explicit service-layer hooks, so every
  path that changes the record (web, REST API, mobile, sync jobs) fires them.
* `SUPPORTED_EVENTS` is the set that actually fires. The webhook form offers
  only these; event types that have no source in this application (or no
  organization to scope them to — webhooks are always per-organization) are no
  longer offered.
* Delivery happens after the triggering transaction commits, on a background
  worker, so a slow or failing receiver never slows down or breaks the save
  that triggered it. `WEBHOOK_DELIVERY_ASYNC = False` makes it synchronous
  (tests use this).
* Payloads carry identifiers and metadata only. Nothing secret or decrypted is
  ever included — password events in particular carry no username, URL,
  notes, password, OTP secret or license key.

Envelope (built by `core.webhook_sender.deliver_webhook`):
    {"event", "timestamp", "organization", "webhook_id", "data"}
"""
from __future__ import annotations

import logging
import queue
import threading

from django.conf import settings as django_settings
from django.db import connection as db_connection, transaction

logger = logging.getLogger('core')


# Event types that have a real source. Kept as strings so this module can be
# imported without the models (it is imported from AppConfig.ready()).
SUPPORTED_EVENTS = frozenset({
    'asset.created', 'asset.updated', 'asset.deleted',
    'document.created', 'document.updated', 'document.deleted',
    'password.created', 'password.updated', 'password.deleted',
    'password.accessed',
    'user.login', 'user.logout', 'user.login_failed', 'user.password_changed',
    'organization.updated',
    'location.created', 'location.updated', 'location.deleted',
    'monitor.up', 'monitor.down', 'monitor.check_failed',
    'wan.up', 'wan.down', 'wan.check_failed',
    'workflow.started', 'workflow.completed', 'workflow.failed',
    'integration.synced', 'integration.failed',
    'ticket.created', 'ticket.updated', 'ticket.status_changed',
    'contact.created', 'contact.updated',
    'invoice.created', 'invoice.updated', 'invoice.status_changed',
})


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

_queue: "queue.Queue[tuple]" = queue.Queue()
_worker = None
_lock = threading.Lock()


def fire(event: str, organization, data: dict) -> None:
    """Queue `event` for the organization's subscribed webhooks.

    Never raises. Without an organization there is nothing to scope the event
    to — webhooks belong to one organization — so it is dropped rather than
    broadcast to every tenant's endpoints.
    """
    try:
        org_id = getattr(organization, 'pk', organization)
        if not org_id:
            return
        payload = dict(data)
        transaction.on_commit(lambda: _after_commit(event, org_id, payload))
    except Exception:
        logger.exception('Could not queue webhook event %s', event)


def _subscribed_hook_ids(event, org_id):
    from core.models import SystemSetting, Webhook

    if not SystemSetting.get_settings().webhooks_enabled:
        return []
    return [
        pk for pk, events in Webhook.objects.filter(
            organization_id=org_id, is_active=True,
        ).values_list('pk', 'events')
        if event in (events or [])
    ]


def _after_commit(event, org_id, data):
    """Resolve subscribers in the request thread (one small query), so the
    background worker is only started when something will be delivered."""
    try:
        hook_ids = _subscribed_hook_ids(event, org_id)
    except Exception:
        logger.exception('Could not resolve webhooks for %s', event)
        return
    if not hook_ids:
        return
    job = (event, hook_ids, data)
    if not getattr(django_settings, 'WEBHOOK_DELIVERY_ASYNC', True):
        _deliver_job(job)
        return
    global _worker
    with _lock:
        _queue.put(job)
        if _worker is None:
            # Not a daemon: a management command (scheduler, sync) that fires
            # an event and exits would otherwise kill the delivery mid-flight.
            _worker = threading.Thread(target=_drain, name='webhook-delivery', daemon=False)
            _worker.start()


def _drain():
    global _worker
    try:
        while True:
            try:
                job = _queue.get(timeout=5)
            except queue.Empty:
                with _lock:
                    if _queue.empty():
                        _worker = None
                        return
                continue
            try:
                _deliver_job(job)
            except Exception:
                logger.exception('Webhook delivery job failed')
    finally:
        try:
            db_connection.close()
        except Exception:
            pass


def _deliver_job(job):
    from core.models import Webhook
    from core.webhook_sender import deliver_webhook

    event, hook_ids, data = job
    for hook in Webhook.objects.filter(pk__in=hook_ids, is_active=True).select_related('organization'):
        try:
            deliver_webhook(hook, event, data)
        except Exception:
            logger.exception('Webhook %s delivery raised for %s', hook.pk, event)


# --------------------------------------------------------------------------
# Payload builders — metadata only
# --------------------------------------------------------------------------

def _username(user):
    return getattr(user, 'username', None) if user else None


def asset_data(asset):
    return {
        'asset_id': asset.pk,
        'asset_name': asset.name,
        'asset_type': asset.asset_type,
        'serial_number': asset.serial_number or '',
        'created_by': _username(getattr(asset, 'created_by', None)),
    }


def document_data(doc):
    return {
        'document_id': doc.pk,
        'title': doc.title,
        'slug': doc.slug,
        'is_published': doc.is_published,
        'is_archived': doc.is_archived,
        'is_template': doc.is_template,
        'is_client_visible': getattr(doc, 'is_client_visible', False),
        'category': getattr(doc.category, 'name', None) if doc.category_id else None,
    }


def password_data(pw):
    """Vault entry metadata. Deliberately no username, URL, notes, secret,
    OTP secret, license key or custom fields."""
    return {
        'password_id': pw.pk,
        'title': pw.title,
        'password_type': pw.password_type,
        'folder_id': pw.folder_id,
    }


def location_data(loc):
    return {'location_id': loc.pk, 'name': loc.name}


def monitor_data(monitor):
    return {
        'monitor_id': monitor.pk,
        'name': monitor.name,
        'url': monitor.url,
        'status': monitor.status,
        'status_code': monitor.last_status_code,
        'response_time_ms': monitor.last_response_time_ms,
        'consecutive_failures': getattr(monitor, 'consecutive_failures', None),
        'error': (monitor.last_error or '')[:500],
        'checked_at': monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
    }


def workflow_data(execution):
    process = getattr(execution, 'process', None)
    return {
        'execution_id': execution.pk,
        'process_id': execution.process_id,
        'process_title': getattr(process, 'title', None),
        'status': execution.status,
        'assigned_to': _username(getattr(execution, 'assigned_to', None)),
    }


def integration_data(conn, kind, status, stats=None):
    """Sync outcome. The provider's error text is not included: provider
    exceptions can echo request URLs or tokens back."""
    return {
        'connection_type': kind,
        'connection_id': conn.pk,
        'name': getattr(conn, 'name', ''),
        'provider_type': getattr(conn, 'provider_type', ''),
        'status': status,
        'stats': _numeric_stats(stats or {}),
    }


def _iso(value):
    return value.isoformat() if value else None


def _money(value):
    return None if value is None else str(value)


def ticket_data(ticket):
    """Ticket metadata as a customer sees it in the portal. No description,
    comments (public or internal), time entries, assignee, internal notes,
    tags or custom fields."""
    status = ticket.status
    return {
        'ticket_id': ticket.pk,
        'ticket_number': ticket.ticket_number,
        'subject': ticket.subject,
        'status': status.slug,
        'status_name': status.name,
        'is_closed': bool(status.is_terminal),
        'priority': ticket.priority.name,
        'ticket_type': ticket.ticket_type.name,
        'source': ticket.source,
        'contact_id': ticket.contact_id,
        'created_at': _iso(ticket.created_at),
        'updated_at': _iso(ticket.updated_at),
        'resolved_at': _iso(ticket.resolved_at),
        'closed_at': _iso(ticket.closed_at),
    }


def contact_data(contact):
    """Contact details. `notes` is staff free text and is not included."""
    return {
        'contact_id': contact.pk,
        'first_name': contact.first_name,
        'last_name': contact.last_name,
        'email': contact.email or '',
        'phone': contact.phone or '',
        'title': contact.title or '',
    }


def invoice_data(invoice):
    """Invoice header figures. No description, line items, approval notes,
    accounting-system ids or push errors."""
    total = invoice.total or 0
    paid = invoice.amount_paid or 0
    return {
        'invoice_id': invoice.pk,
        'invoice_number': invoice.invoice_number,
        'title': invoice.title,
        'status': invoice.status,
        'invoice_date': _iso(invoice.invoice_date),
        'due_date': _iso(invoice.due_date),
        'sent_at': _iso(invoice.sent_at),
        'currency': invoice.currency,
        'subtotal': _money(invoice.subtotal),
        'tax_amount': _money(invoice.tax_amount),
        'total': _money(invoice.total),
        'amount_paid': _money(invoice.amount_paid),
        'balance_due': _money(total - paid),
    }


def _numeric_stats(stats):
    """Counts only (one level of nesting), so nothing free-form leaks out."""
    out = {}
    for key, value in stats.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, dict):
            inner = {k: v for k, v in value.items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool)}
            if inner:
                out[key] = inner
    return out


def user_member_org_ids(user):
    from accounts.models import Membership
    if not user or not getattr(user, 'pk', None):
        return []
    return list(Membership.objects.filter(user=user, is_active=True)
                .values_list('organization_id', flat=True).distinct())


def fire_for_user(event, user, extra=None):
    """User events go to each organization the user is an active member of —
    but only for customer users. MSP staff (superuser, Django is_staff, or a
    Staff profile) generate no user.* events at all: webhooks belong to
    customer organizations, and a customer has no business seeing when MSP
    technicians sign in. There are no MSP-level webhooks to send them to."""
    from psa.visibility import is_msp_staff
    if is_msp_staff(user):
        return
    data = {'user_id': user.pk, 'username': user.username}
    if extra:
        data.update(extra)
    for org_id in user_member_org_ids(user):
        fire(event, org_id, data)
