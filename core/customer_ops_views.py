"""Customer operations pages (see core/customer_ops.py for the rules)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import customer_ops as ops
from .models import Organization


def _customer_or_404(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    if not ops.can_open_customer(request, org):
        raise Http404
    return org


def _follow_customer(request, org):
    """Make the session's current customer this one, so the action links
    (asset, monitor, invoice pages scoped to the current customer) open the
    right record. Same steps and rule as core.org_handoff. Global View is
    left alone: from there every link already works."""
    current = getattr(request, 'current_organization', None)
    if current is None or current.pk == org.pk:
        return
    from .client_switcher import authorized_organizations
    from .org_handoff import switch_session_org
    if authorized_organizations(request).filter(pk=org.pk).exists():
        switch_session_org(request, org)
        messages.info(request, f'Switched to {org.name}.')


@login_required
def customer_ops_current(request):
    """The current customer's operations page; without one, a short picker."""
    org = getattr(request, 'current_organization', None)
    if org is not None and ops.can_open_customer(request, org):
        return redirect('core:customer_ops', org_id=org.pk)
    from .client_switcher import authorized_organizations
    customers = authorized_organizations(request).order_by('name')
    return render(request, 'core/customer_ops_pick.html', {
        'customers': customers[:50],
        'more': customers.count() > 50,
    })


@login_required
def customer_ops(request, org_id):
    org = _customer_or_404(request, org_id)
    _follow_customer(request, org)
    sections = ops.build(request, org)
    return render(request, 'core/customer_ops.html', {
        'organization': org,
        'sections': sections,
        'hidden_any': len(sections) < len(ops.SECTION_ORDER),
        'is_msp_staff': ops.is_msp_staff(request.user),
    })


@login_required
def customer_ops_section(request, org_id, section):
    org = _customer_or_404(request, org_id)
    if section not in ops.SECTION_ORDER:
        raise Http404
    built = ops.build_section(request, org, section)
    if built is None:
        raise PermissionDenied('Your role does not include this section for this customer.')
    _follow_customer(request, org)
    return render(request, 'core/customer_ops_section.html', {
        'organization': org,
        'section': built,
    })


@login_required
@require_POST
def invoice_reminder(request, org_id, invoice_id):
    """One-click overdue reminder from the Overdue invoices section.

    Needs MSP staff with `billing_send_invoices` for this customer. Sends the
    existing invoice email (psa.pdf.email_invoice: the PDF attached) with a
    reminder subject and body to the customer's contact address, the same
    default the invoice page's email form offers. Refused, and nothing sent,
    when the invoice is not overdue with a balance, is held for approval, the
    customer has no contact address, or a reminder went out within
    REMINDER_COOLDOWN_MINUTES (a double click). Every attempt that reaches
    the mail step is audit-logged, sent or failed."""
    from datetime import timedelta

    from django.utils import timezone

    from audit.models import AuditLog
    from core.client_ip import get_client_ip

    org = _customer_or_404(request, org_id)
    if not ops.module_on('invoices'):
        raise Http404
    if not ops.can_send_reminders(request.user, org):
        raise PermissionDenied("You don't have the 'billing_send_invoices' permission for this customer.")
    invoice = get_object_or_404(ops.overdue_invoices(org).select_related('client_org', 'organization'),
                                pk=invoice_id)
    back = redirect(f"{reverse('core:customer_ops', args=[org.pk])}#ops-invoices")
    if invoice.balance <= 0:
        messages.info(request, f'Invoice {invoice.invoice_number} has no balance left; no reminder sent.')
        return back
    if invoice.requires_approval:
        messages.error(request, f'Invoice {invoice.invoice_number} requires approval before it can be sent.')
        return back
    recipient = (org.primary_contact_email or org.email or '').strip()
    if not recipient:
        messages.error(request, f'{org.name} has no contact email address. Add one on the customer page, '
                                f'or send the invoice from its own page.')
        return back
    recent = AuditLog.objects.filter(
        object_type='psa.Invoice', object_id=invoice.pk, extra_data__kind='overdue_reminder',
        success=True, timestamp__gte=timezone.now() - timedelta(minutes=ops.REMINDER_COOLDOWN_MINUTES),
    ).exists()
    if recent:
        messages.info(request, f'A reminder for {invoice.invoice_number} was sent in the last '
                               f'{ops.REMINDER_COOLDOWN_MINUTES} minutes; not sent again.')
        return back

    from psa.pdf import email_invoice
    days = (timezone.localdate() - invoice.due_date).days if invoice.due_date else None
    subject = f'Reminder: invoice {invoice.invoice_number} is overdue'
    body = (
        'Hello,\n\n'
        f'This is a reminder that invoice {invoice.invoice_number}'
        + (f' was due on {invoice.due_date:%Y-%m-%d}' if invoice.due_date else ' is overdue')
        + (f' ({days} day(s) ago)' if days and days > 0 else '') + '.\n\n'
        f'Balance due: {invoice.balance:,.2f} {invoice.currency}\n\n'
        'The invoice is attached. If you have already paid, please disregard this message.\n\n'
        f'Thank you,\n{invoice.organization.name}'
    )
    try:
        ok, error = bool(email_invoice(invoice, recipient=recipient, subject=subject, body=body)), ''
    except Exception as exc:  # SMTP and PDF errors are reported, not raised
        ok, error = False, str(exc)[:300]
    AuditLog.log(
        user=request.user, action='update', organization=invoice.organization,
        object_type='psa.Invoice', object_id=invoice.pk, object_repr=invoice.invoice_number,
        description=(f'Sent overdue reminder for invoice {invoice.invoice_number} to {recipient}' if ok
                     else f'Overdue reminder for invoice {invoice.invoice_number} to {recipient} failed'),
        ip_address=get_client_ip(request), path=request.path,
        extra_data={'kind': 'overdue_reminder', 'recipient': recipient, 'customer_id': org.pk,
                    'balance': f'{invoice.balance:.2f}', 'currency': invoice.currency,
                    **({'error': error} if error else {})},
        success=ok,
    )
    if ok:
        messages.success(request, f'Reminder for {invoice.invoice_number} sent to {recipient}.')
    else:
        messages.error(request, f'Reminder for {invoice.invoice_number} could not be sent'
                                + (f': {error}' if error else '.'))
    return back
