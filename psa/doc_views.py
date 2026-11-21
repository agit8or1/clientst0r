"""Viewed tracking for quotes and invoices sent to a customer or lead.

A view is recorded only from the page itself, never from the bare GET:

* the quote's public sign page and the portal invoice page carry a signed,
  per-page-load nonce; `static/js/doc-view-beacon.js` POSTs it (same
  origin, with the CSRF token) once a person interacts with the visible page
  (scroll, pointer, key or touch at least 1.5 s after load);
* HEAD requests, prefetch / preview requests, automated user agents (e-mail
  security scanners, link-preview bots, HTTP libraries, headless browsers —
  the same classifier as contract links, contracts.tracking.classify) and
  MSP staff who are signed in are ignored;
* the endpoint answers 204 whatever happens, so it reveals nothing (not even
  whether a token or invoice exists), is rate-limited, and writes nothing but
  the view record: no status, total or signature changes.

What is kept per recipient (psa.DocumentView): first and last view, count,
the last IP address and user agent (the same detail the audit log and the
contract event history already keep). A quote has one shared sign link, so
its viewer is "the link holder"; an invoice is opened by a signed-in portal
user, so each person is a recipient. The first view of each recipient is
written to the audit log, fires the `quote.viewed` / `invoice.viewed`
webhook and e-mails the document's owner (the staff member who created it)
when their profile has e-mail notifications on.
"""
from __future__ import annotations

import logging
import secrets

from django.core import signing as dsigning
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger('psa')

NONCE_SALT = 'psa.doc_views.nonce'
NONCE_MAX_AGE = 6 * 3600


def nonce(doc_type, pk) -> str:
    return dsigning.dumps({'t': doc_type, 'i': pk, 'n': secrets.token_hex(8)}, salt=NONCE_SALT)


def check_nonce(doc_type, pk, value):
    try:
        data = dsigning.loads(value or '', salt=NONCE_SALT, max_age=NONCE_MAX_AGE)
    except dsigning.BadSignature:
        return None
    if data.get('t') != doc_type or data.get('i') != pk:
        return None
    return data.get('n')


def ignore_reason(request) -> str:
    """'' when this request may count as a customer's view."""
    if request.method != 'POST':
        return 'not_a_beacon'
    if request.POST.get('interacted') != '1':
        return 'no_interaction'
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        from psa.visibility import is_msp_staff
        if is_msp_staff(user):
            return 'staff'
    from contracts.tracking import classify
    cls = classify(request)
    if cls['automated']:
        return 'automated'
    return ''


def _client_ip(request):
    try:
        from core.client_ip import get_client_ip
        return get_client_ip(request) or None
    except Exception:  # noqa: BLE001
        return None


def record(doc, doc_type, request, *, user=None, now=None):
    """Record one view of `doc` (a Quote or Invoice). Returns the
    DocumentView row, or None when the page view was already counted."""
    from .models import DocumentView, Invoice, Quote
    now = now or timezone.now()
    page_nonce = check_nonce(doc_type, doc.pk, request.POST.get('nonce'))
    if not page_nonce:
        return None
    if user is not None:
        key = f'user:{user.pk}'
        label = (user.get_full_name() or user.username)
        if user.email:
            label = f'{label} <{user.email}>'
    else:
        key, label = 'link', 'Link holder (identity not verified)'
    ip = _client_ip(request)
    ua = (request.META.get('HTTP_USER_AGENT') or '')[:400]
    first_for_viewer = False
    with transaction.atomic():
        row = DocumentView.objects.select_for_update().filter(doc_type=doc_type, object_id=doc.pk,
                                                              viewer_key=key).first()
        if row is None:
            try:
                with transaction.atomic():
                    row = DocumentView.objects.create(
                        doc_type=doc_type, object_id=doc.pk, client_org_id=doc.client_org_id, viewer_key=key,
                        viewer_user=user, viewer_label=label[:255], first_viewed_at=now, last_viewed_at=now,
                        view_count=1, last_ip=ip, last_user_agent=ua, last_nonce=page_nonce)
                first_for_viewer = True
            except IntegrityError:
                row = DocumentView.objects.select_for_update().get(doc_type=doc_type, object_id=doc.pk,
                                                                   viewer_key=key)
        if not first_for_viewer:
            if row.last_nonce == page_nonce:
                return None  # this page load was already counted
            DocumentView.objects.filter(pk=row.pk).update(
                view_count=F('view_count') + 1, last_viewed_at=now, last_ip=ip, last_user_agent=ua,
                last_nonce=page_nonce, viewer_label=label[:255])
        model = Quote if doc_type == DocumentView.QUOTE else Invoice
        # .update(): no save() signals, so no document webhook or
        # recalculation fires for a view.
        model.objects.filter(pk=doc.pk).update(view_count=F('view_count') + 1, last_viewed_at=now)
        first_for_doc = bool(model.objects.filter(pk=doc.pk, first_viewed_at__isnull=True)
                             .update(first_viewed_at=now))
    if first_for_viewer:
        transaction.on_commit(lambda: _announce(doc, doc_type, label, ip, first_for_doc))
    return row


def _number(doc, doc_type):
    return doc.quote_number if doc_type == 'quote' else doc.invoice_number


def _announce(doc, doc_type, label, ip, first_for_doc):
    number = _number(doc, doc_type)
    what = 'Quote' if doc_type == 'quote' else 'Invoice'
    try:
        from audit.models import AuditLog
        AuditLog.log(user=None, action='read', organization=doc.organization,
                     object_type=f'psa.{what}', object_id=doc.pk, object_repr=number,
                     description=f'{what} {number} viewed by the customer: {label}',
                     ip_address=ip, extra_data={'event': f'{doc_type}.viewed', 'viewer': label})
    except Exception:  # noqa: BLE001
        logger.exception('audit of %s view failed', doc_type)
    try:
        from core import webhook_events as wh
        wh.fire(f'{doc_type}.viewed', doc.client_org_id, {
            f'{doc_type}_id': doc.pk, f'{doc_type}_number': number, 'status': doc.status,
            'viewed_at': timezone.now().isoformat(), 'first_view': first_for_doc,
            'viewer': 'portal_user' if doc_type == 'invoice' else 'link_holder'})
    except Exception:  # noqa: BLE001
        logger.exception('webhook for %s view failed', doc_type)
    if first_for_doc:
        notify_owner(doc, doc_type, label)


def notify_owner(doc, doc_type, label):
    """E-mail the staff member who created the document, once (first view),
    when their profile has e-mail notifications on and they are still active
    MSP staff."""
    owner = getattr(doc, 'created_by', None)
    if owner is None or not owner.is_active or not owner.email:
        return False
    from psa.visibility import is_msp_staff
    if not is_msp_staff(owner):
        return False
    profile = getattr(owner, 'profile', None)
    try:
        if profile is not None and not profile.email_notifications:
            return False
    except Exception:  # noqa: BLE001
        pass
    from django.urls import reverse
    from .notifications import _send_email
    number = _number(doc, doc_type)
    what = 'Quote' if doc_type == 'quote' else 'Invoice'
    path = reverse('psa:quote_detail' if doc_type == 'quote' else 'psa:invoice_detail', args=[doc.pk])
    from django.conf import settings as dj
    base = (getattr(dj, 'SITE_URL', '') or '').rstrip('/')
    ok, _err = _send_email(owner, f'[{number}] {what} opened by the customer',
                           f'{what} {number} "{doc.title}" for {doc.client_org.name} was opened: {label}.\n\n'
                           f'{base}{path}\n')
    return ok


def summary(doc, doc_type):
    """For the staff page: aggregate figures and the per-recipient rows."""
    from .models import DocumentView
    return {'first': doc.first_viewed_at, 'last': doc.last_viewed_at, 'count': doc.view_count,
            'viewers': list(DocumentView.objects.filter(doc_type=doc_type, object_id=doc.pk)
                            .order_by('-last_viewed_at')[:20])}


def progress(doc, doc_type):
    """Sent → Viewed → Signed / Accepted / Paid for the staff page: a list of
    {label, done, at, detail}."""
    from .models import DocumentView
    viewers = list(DocumentView.objects.filter(doc_type=doc_type, object_id=doc.pk).order_by('first_viewed_at'))
    first = viewers[0] if viewers else None
    steps = [{'label': 'Sent', 'done': bool(doc.sent_at) or doc.status not in ('draft',), 'at': doc.sent_at,
              'detail': ''}]
    steps.append({'label': 'Viewed', 'done': bool(doc.first_viewed_at), 'at': doc.first_viewed_at,
                  'detail': (f'by {first.viewer_label}' if first else '')
                  + (f' · {doc.view_count} view{"s" if doc.view_count != 1 else ""}' if doc.view_count else '')
                  + (f' · last {timezone.localtime(doc.last_viewed_at):%Y-%m-%d %H:%M}'
                     if doc.last_viewed_at and doc.view_count > 1 else '')})
    if doc_type == 'quote':
        sig = getattr(doc, 'signature', None) if doc.pk else None
        steps.append({'label': 'Signed', 'done': sig is not None, 'at': sig.signed_at if sig else None,
                      'detail': f'by {sig.signed_by_name}' if sig else ''})
        steps.append({'label': 'Accepted', 'done': doc.status == 'accepted', 'at': doc.accepted_at, 'detail': ''})
    else:
        paid = doc.status == 'paid'
        last_payment = doc.payments.order_by('-paid_on', '-pk').first() if paid else None
        steps.append({'label': 'Paid', 'done': paid, 'at': getattr(last_payment, 'paid_on', None),
                      'detail': ''})
    return {'steps': steps, 'viewers': viewers}
