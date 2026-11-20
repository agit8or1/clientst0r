"""
Staff payment pages (/payments/, MSP staff only — a staff-only prefix in
accounts.middleware) and the provider webhook receivers
(/payments/webhooks/..., no sign-in, signature-verified, CSRF-exempt).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.models import PaymentConnection

from . import permissions, services, webhooks
from .forms import ConnectionForm, RefundForm
from .models import GatewayEvent, PaymentAttempt


def staff_required(view):
    from functools import wraps

    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        from psa.visibility import is_msp_staff
        if not is_msp_staff(request.user):
            raise PermissionDenied('Payments are managed by MSP staff.')
        return view(request, *args, **kwargs)
    return wrapped


@staff_required
def index(request):
    connections = permissions.manageable_connections(request.user)
    attempts = permissions.visible_attempts(request.user)
    status = request.GET.get('status', '')
    if status in dict(PaymentAttempt.STATUS_CHOICES):
        attempts = attempts.filter(status=status)
    invoice = request.GET.get('invoice', '')
    if invoice.isdigit():
        attempts = attempts.filter(invoice_id=int(invoice))
    return render(request, 'payments/index.html', {
        'connections': connections, 'attempts': attempts[:200], 'status': status,
        'can_create': permissions.can_manage_connection(request.user),
        'pending_accounting': attempts.filter(accounting_post_status='pending').count(),
    })


def _connection_initial(conn):
    creds = conn.get_credentials()
    gs = services.settings_for(conn)
    return {
        'name': conn.name, 'provider_type': conn.provider_type,
        'is_active': conn.is_active, 'sync_enabled': conn.sync_enabled,
        'publishable_key': creds.get('publishable_key', ''), 'environment': creds.get('environment', 'live'),
        'portal_payments_enabled': gs.portal_payments_enabled, 'autopay_enabled': gs.autopay_enabled,
        'autopay_lead_days': gs.autopay_lead_days, 'autopay_max_attempts': gs.autopay_max_attempts,
        'autopay_retry_days': gs.autopay_retry_days, 'failure_notify_email': gs.failure_notify_email,
    }


@staff_required
def connection_edit(request, pk=None):
    # Gateway connections are the MSP's own (one MSP per install): always
    # platform-owned. A customer-owned row is not shown or edited here.
    conn = get_object_or_404(PaymentConnection, pk=pk, organization__isnull=True) if pk else None
    if not permissions.can_manage_connection(request.user, conn):
        raise PermissionDenied('You may not manage payment connections.')
    form = ConnectionForm(request.POST or None, initial=_connection_initial(conn) if conn else None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        org = None
        created = conn is None
        conn = conn or PaymentConnection()
        conn.organization, conn.name, conn.provider_type = None, d['name'], d['provider_type']
        conn.is_active, conn.sync_enabled = d['is_active'], d['sync_enabled']
        creds = conn.get_credentials() if conn.pk else {}
        key_field = 'api_key' if d['provider_type'] == 'stripe' else 'access_token'
        if d['secret_key']:
            creds[key_field] = d['secret_key'].strip()
        if d['webhook_secret']:
            creds['webhook_secret'] = d['webhook_secret'].strip()
        creds['publishable_key'] = d['publishable_key'].strip()
        creds['environment'] = d['environment']
        conn.set_credentials(creds)
        if d['provider_type'] == 'gocardless':
            from integrations.providers.payment.gocardless import LIVE_URL, SANDBOX_URL
            conn.base_url = SANDBOX_URL if d['environment'] == 'sandbox' else LIVE_URL
        elif not conn.base_url or 'gocardless' in conn.base_url:
            conn.base_url = 'https://api.stripe.com'
        conn.save()
        gs = services.settings_for(conn)
        for f in ('portal_payments_enabled', 'autopay_enabled', 'autopay_lead_days', 'autopay_max_attempts',
                  'autopay_retry_days', 'failure_notify_email'):
            setattr(gs, f, d[f])
        gs.save()
        services.audit(request.user, 'create' if created else 'update', org, conn,
                       f'Payment connection {conn.name} {"created" if created else "updated"}',
                       live=conn.sync_enabled, autopay=gs.autopay_enabled,
                       secret_changed=bool(d['secret_key']), webhook_secret_changed=bool(d['webhook_secret']))
        messages.success(request, 'Payment connection saved.')
        return redirect('payments:connection_edit', pk=conn.pk)
    webhook_url = ''
    has = {}
    if conn is not None:
        name = 'payments:stripe_webhook' if conn.provider_type == 'stripe' else 'payments:gocardless_webhook'
        webhook_url = request.build_absolute_uri(reverse(name, args=[conn.pk]))
        creds = conn.get_credentials()
        has = {'secret': bool(creds.get('api_key') or creds.get('access_token')),
               'webhook': bool(creds.get('webhook_secret'))}
    return render(request, 'payments/connection_form.html', {
        'form': form, 'connection': conn, 'webhook_url': webhook_url, 'has': has,
        'events': GatewayEvent.objects.filter(connection=conn)[:20] if conn else [],
    })


@staff_required
@require_POST
def connection_verify(request, pk):
    conn = get_object_or_404(PaymentConnection, pk=pk, organization__isnull=True)
    if not permissions.can_manage_connection(request.user, conn):
        raise PermissionDenied()
    try:
        services.provider_for(conn).verify_credentials()
        conn.last_error = ''
        messages.success(request, 'The provider accepted the credentials.')
    except Exception as exc:  # noqa: BLE001
        conn.last_error = str(exc)[:2000]
        messages.error(request, f'The provider refused the credentials: {exc}')
    conn.save(update_fields=['last_error', 'updated_at'])
    return redirect('payments:connection_edit', pk=conn.pk)


@staff_required
def attempt_detail(request, pk):
    attempt = get_object_or_404(PaymentAttempt.objects.select_related('invoice', 'client_org', 'connection'), pk=pk)
    if not permissions.can_view_attempt(request.user, attempt):
        raise Http404()
    can_refund = permissions.can_refund(request.user, attempt) and attempt.refundable_amount > 0
    return render(request, 'payments/attempt_detail.html', {
        'attempt': attempt, 'refunds': attempt.refunds.all(), 'disputes': attempt.disputes.all(),
        'can_refund': can_refund,
        'refund_form': RefundForm(initial={'amount': attempt.refundable_amount}) if can_refund else None,
    })


@staff_required
@require_POST
def attempt_refund(request, pk):
    attempt = get_object_or_404(PaymentAttempt, pk=pk)
    if not permissions.can_refund(request.user, attempt):
        raise PermissionDenied('You may not refund payments for this customer.')
    form = RefundForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter an amount and confirm the refund.')
        return redirect('payments:attempt_detail', pk=attempt.pk)
    try:
        refund = services.request_refund(attempt, form.cleaned_data['amount'], request.user,
                                         form.cleaned_data['reason'])
        messages.success(request, f'Refund of {refund.amount} {refund.currency} is {refund.get_status_display().lower()}.')
    except services.PaymentError as exc:
        messages.error(request, str(exc))
    return redirect('payments:attempt_detail', pk=attempt.pk)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def _webhook_connection(pk, provider_type):
    conn = PaymentConnection.objects.filter(pk=pk, provider_type=provider_type, is_active=True,
                                            organization__isnull=True).first()
    if conn is None:
        raise Http404()
    return conn


# CSRF-exempt: provider-to-server call with no session; the request is authenticated by the stripe signature check in payments.webhooks (rejected before anything is recorded).
@csrf_exempt
@require_POST
def stripe_webhook(request, pk):
    conn = _webhook_connection(pk, 'stripe')
    status, msg = webhooks.receive_stripe(conn, request.body, request.headers)
    return HttpResponse(msg, status=status, content_type='text/plain')


# CSRF-exempt: provider-to-server call with no session; the request is authenticated by the gocardless signature check in payments.webhooks (rejected before anything is recorded).
@csrf_exempt
@require_POST
def gocardless_webhook(request, pk):
    conn = _webhook_connection(pk, 'gocardless')
    status, msg = webhooks.receive_gocardless(conn, request.body, request.headers)
    return HttpResponse(msg, status=status, content_type='text/plain')
