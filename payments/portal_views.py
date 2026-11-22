"""
Customer portal: invoices, online payment, payment history, receipts and
autopay. Mounted in the portal namespace (portal/urls.py, /portal/billing/).

Access: the portal's own rules (portal_required: signed in, active
membership in a portal-enabled customer, the customer switcher) plus the
customer role permission `portal_billing_contact`, read with a default of
False — financial pages are for billing contacts only, unlike the portal's
ticket flags that default to True.

Every lookup is scoped to the active portal customer: an invoice, payment,
attempt, method or setup request of another customer is a 404. Internal
fields (GL codes, cost, approval and accounting fields, internal notes) are
never rendered; the invoice page shows the customer-facing lines and totals.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from portal.views import portal_required

from . import services
from .models import PaymentAttempt, SetupRequest, StoredPaymentMethod

BILLING_FLAG = 'portal_billing_contact'
OPEN_STATUSES = ('sent', 'partial', 'overdue')


def can_bill(request) -> bool:
    from psa.visibility import membership_flag
    return membership_flag(getattr(request, 'portal_membership', None), BILLING_FLAG, False)


def billing_required(view):
    from functools import wraps

    @wraps(view)
    @portal_required
    def wrapped(request, *args, **kwargs):
        if not can_bill(request):
            raise PermissionDenied('Billing is available to your organization\'s billing contacts.')
        return view(request, *args, **kwargs)
    return wrapped


def _org(request):
    return request.portal_membership.organization


def portal_invoices(org):
    """Invoices a billing contact of `org` may see: billed to `org`, never drafts."""
    from psa.models import Invoice
    return Invoice.objects.filter(client_org=org).exclude(status='draft')


def _invoice(request, pk):
    return get_object_or_404(portal_invoices(_org(request)), pk=pk)


def _portal_payments(org):
    from psa.models import Payment
    return Payment.objects.filter(invoice__client_org=org).exclude(invoice__status='draft')


@billing_required
def billing_home(request):
    org = _org(request)
    invoices = list(portal_invoices(org).order_by('-invoice_date', '-pk')[:200])
    outstanding = sum((i.net_balance_due for i in invoices if i.status in OPEN_STATUSES and not i.is_credit_memo),
                      Decimal('0.00'))
    connection = services.connection_for(org)
    methods = StoredPaymentMethod.objects.filter(client_org=org).exclude(status='detached')
    payments = _portal_payments(org).select_related('invoice').order_by('-paid_on', '-pk')[:50]
    return render(request, 'payments/portal/billing_home.html', {
        'organization': org, 'invoices': invoices, 'outstanding': outstanding,
        'currency': invoices[0].currency if invoices else 'USD',
        'payments': payments, 'methods': methods, 'can_pay_online': connection is not None,
        'autopay_method': methods.filter(is_default=True, authorized_for_autopay=True).first(),
    })


@billing_required
def invoice_detail(request, pk):
    invoice = _invoice(request, pk)
    connection = services.connection_for_invoice(invoice)
    due = services.amount_due(invoice)
    processing = PaymentAttempt.objects.filter(invoice=invoice, status='processing').exists()
    from psa.billing import presentation
    return render(request, 'payments/portal/invoice_detail.html', {
        'invoice': invoice, 'lines': invoice.line_items.all(), 'due': due,
        'present': presentation.build(invoice, detail=True), 'brand': presentation.branding(invoice),
        'payments': invoice.payments.all().order_by('-paid_on', '-pk'),
        'can_pay': bool(connection) and due > 0 and not processing
        and services.settings_for(connection).portal_payments_enabled,
        'processing': processing, 'provider': connection.provider_type if connection else '',
        'view_nonce': _view_nonce(invoice),
    })


def _view_nonce(invoice):
    from psa import doc_views
    return doc_views.nonce('invoice', invoice.pk)


@require_POST
def invoice_seen(request, pk):
    """View beacon of the portal invoice page (psa.doc_views): records which
    of the customer's users opened it. Always 204 — it reveals nothing about
    invoices the user may not see and changes nothing but the view record."""
    from core.public_throttle import limited
    from psa import doc_views
    if limited(request, 'portal.invoice_seen', '30/m'):
        return HttpResponse(status=204)
    if not request.user.is_authenticated or doc_views.ignore_reason(request):
        return HttpResponse(status=204)
    try:
        resp = _record_invoice_view(request, pk)
    except (Http404, PermissionDenied):
        resp = None
    return resp or HttpResponse(status=204)


@billing_required
def _record_invoice_view(request, pk):
    from psa import doc_views
    invoice = _invoice(request, pk)
    try:
        doc_views.record(invoice, 'invoice', request, user=request.user)
    except Exception:  # noqa: BLE001 — tracking never breaks the page
        import logging
        logging.getLogger('payments').exception('invoice view tracking failed')
    return HttpResponse(status=204)


@billing_required
@require_POST
def invoice_pay(request, pk):
    invoice = _invoice(request, pk)
    save = request.POST.get('save_for_autopay') == 'on'
    if save and request.POST.get('autopay_consent') != 'on':
        messages.error(request, 'Tick the authorization box to save this method for autopay.')
        return redirect('portal:billing_invoice', pk=invoice.pk)
    try:
        _attempt, url = services.start_checkout(
            invoice, request.user, save_for_autopay=save,
            success_url=lambda a: request.build_absolute_uri(reverse('portal:billing_pay_return', args=[a.pk])),
            cancel_url=lambda a: request.build_absolute_uri(reverse('portal:billing_pay_cancel', args=[a.pk])))
    except services.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('portal:billing_invoice', pk=invoice.pk)
    return redirect(url)


def _attempt(request, pk):
    return get_object_or_404(PaymentAttempt.objects.select_related('invoice', 'connection'),
                             pk=pk, client_org=_org(request), invoice__client_org=_org(request))


@billing_required
def pay_return(request, pk):
    """Back from the provider's page. Re-reads the provider so the payment
    is recorded even if the webhook is late (idempotent with the webhook)."""
    attempt = _attempt(request, pk)
    try:
        provider = services.provider_for(attempt.connection)
        if attempt.provider == 'stripe' and attempt.provider_session_id:
            services.stripe_complete_session(attempt.connection,
                                             provider.retrieve_checkout_session(attempt.provider_session_id))
        elif attempt.provider == 'gocardless' and attempt.provider_session_id and not attempt.provider_object_id:
            services.gocardless_complete_billing_request(
                attempt.connection, provider.retrieve_billing_request(attempt.provider_session_id))
    except Exception:  # noqa: BLE001 — the webhook will settle it
        pass
    attempt.refresh_from_db()
    if attempt.status == 'succeeded':
        messages.success(request, 'Thank you — your payment was received.')
    elif attempt.status == 'processing':
        messages.info(request, 'Thank you — your payment is processing. Bank payments can take a few days to clear.')
    elif attempt.status == 'failed':
        messages.error(request, f'The payment did not go through: {attempt.failure_message or "declined"}.')
    else:
        messages.info(request, 'We are waiting for confirmation from the payment provider.')
    return redirect('portal:billing_invoice', pk=attempt.invoice_id)


@billing_required
def pay_cancel(request, pk):
    attempt = _attempt(request, pk)
    if attempt.status in ('created', 'requires_action') and attempt.kind == 'checkout':
        services.record_canceled(attempt, provider_status='customer_cancelled')
    messages.info(request, 'Payment cancelled. Nothing was charged.')
    return redirect('portal:billing_invoice', pk=attempt.invoice_id)


@billing_required
def receipt(request, pk):
    payment = get_object_or_404(_portal_payments(_org(request)).select_related('invoice'), pk=pk)
    if payment.amount <= 0:
        raise Http404()
    from .receipts import render_receipt_pdf
    pdf = render_receipt_pdf(payment)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="receipt-{payment.invoice.invoice_number}-{payment.pk}.pdf"'
    return resp


@billing_required
def methods(request):
    org = _org(request)
    connection = services.connection_for(org)
    rows = StoredPaymentMethod.objects.filter(client_org=org).exclude(status='detached')
    gs = services.settings_for(connection) if connection else None
    return render(request, 'payments/portal/methods.html', {
        'organization': org, 'methods': rows, 'connection': connection,
        'autopay_available': bool(gs and gs.autopay_enabled),
    })


@billing_required
@require_POST
def method_action(request, pk):
    org = _org(request)
    method = get_object_or_404(StoredPaymentMethod, pk=pk, client_org=org)
    action = request.POST.get('action')
    try:
        if action == 'default':
            services.set_default(method, request.user)
            messages.success(request, f'{method.display} is now your default method.')
        elif action == 'autopay_on':
            if request.POST.get('autopay_consent') != 'on':
                raise services.PaymentError('Tick the authorization box to turn on autopay.')
            services.set_autopay(method, request.user, True)
            messages.success(request, f'Autopay is on: due invoices will be charged to {method.display}.')
        elif action == 'autopay_off':
            services.set_autopay(method, request.user, False)
            messages.success(request, 'Autopay is off.')
        elif action == 'remove':
            services.remove_method(method, request.user)
            messages.success(request, f'{method.display} was removed.')
        else:
            raise Http404()
    except services.PaymentError as exc:
        messages.error(request, str(exc))
    return redirect('portal:billing_methods')


@billing_required
@require_POST
def method_add(request):
    org = _org(request)
    connection = services.connection_for(org)
    if connection is None:
        raise Http404()
    autopay = request.POST.get('autopay') == 'on'
    if autopay and request.POST.get('autopay_consent') != 'on':
        messages.error(request, 'Tick the authorization box to use the new method for autopay.')
        return redirect('portal:billing_methods')
    try:
        _setup, url = services.start_method_setup(
            connection, org, request.user, autopay=autopay,
            success_url=lambda s: request.build_absolute_uri(reverse('portal:billing_setup_return', args=[s.pk])),
            cancel_url=lambda s: request.build_absolute_uri(reverse('portal:billing_methods')))
    except services.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('portal:billing_methods')
    return redirect(url)


@billing_required
@require_http_methods(['GET'])
def setup_return(request, pk):
    setup = get_object_or_404(SetupRequest, pk=pk, client_org=_org(request))
    try:
        provider = services.provider_for(setup.connection)
        if setup.status == 'open' and setup.provider_reference:
            if setup.connection.provider_type == 'stripe':
                services.stripe_complete_session(setup.connection,
                                                 provider.retrieve_checkout_session(setup.provider_reference))
            else:
                services.gocardless_complete_billing_request(
                    setup.connection, provider.retrieve_billing_request(setup.provider_reference))
    except Exception:  # noqa: BLE001 — the webhook will finish it
        pass
    setup.refresh_from_db()
    if setup.status == 'completed':
        messages.success(request, 'Your payment method was saved.')
    else:
        messages.info(request, 'We are waiting for confirmation from the payment provider.')
    return redirect('portal:billing_methods')
