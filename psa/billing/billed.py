"""Phase 102.1 / 102.2: what counts as billed, the customer billing lock, and
bundling account charges into an invoice.

One rule says whether work is billed, and every reader uses it: invoicing
(psa.billing.invoicing), the client account's "Unbilled work" list, the
account balance, the Ready for Billing queue and `billing_preview`.

* Time, items/expenses and billing-rule fees are billed while an invoice line
  points at them (`source` / `source_id`) on a *live* invoice: one that is
  neither void nor a credit memo. Voiding the invoice releases them.
* An account charge (psa.Charge) is billed while its `invoice` link points at
  a live invoice, or it is marked invoiced without an invoice (marked by hand,
  or its draft was deleted - kept billed, as before). A void invoice releases
  it, like time.

Locking: `lock_customer` takes a per-customer row lock (psa.CustomerBillingLock)
the same way the prepaid-hour ledger locks an agreement: an UPDATE first (on
SQLite that takes the database write lock; on MySQL / PostgreSQL the row
lock), then SELECT ... FOR UPDATE. Everything that turns a customer's work or
charges into an invoice runs inside one transaction holding it, reads what is
unbilled after taking it, claims what it bills with a conditional UPDATE and
checks the finished invoice against every other live invoice
(`assert_billed_once`), so a double click, a retry or a stale read bills
nothing twice: the late writer rolls back and creates nothing.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.models import CharField, Exists, F, OuterRef, Q
from django.db.models.functions import Cast
from django.utils import timezone

# Sources whose `source_id` points at exactly one billable record.
SINGLE_SOURCES = ('time', 'expense', 'fee', 'charge')


class DoubleBilling(RuntimeError):
    """Something on the invoice being written is already on another live
    invoice (a concurrent writer got there first). The transaction rolls
    back; nothing is billed."""


# --- the "is it billed" rule ----------------------------------------------------

def live_lines(source=None):
    """Invoice lines on live invoices (not void, not a credit memo)."""
    from psa.models import InvoiceLineItem
    qs = InvoiceLineItem.objects.exclude(invoice__status='void').exclude(invoice__is_credit_memo=True)
    if source:
        qs = qs.filter(source=source)
    return qs


def billed_exists(source):
    """Exists() expression: the outer row (by pk) is on a live invoice."""
    return Exists(live_lines(source).filter(source_id=Cast(OuterRef('pk'), output_field=CharField())))


def billable_time(qs):
    """Billable, stopped time with a positive duration."""
    return qs.filter(is_billable=True, ended_at__isnull=False, duration_minutes__gt=0)


def unbilled_time(qs):
    """Billable time (TicketTimeEntry queryset) not on a live invoice."""
    return billable_time(qs).filter(~billed_exists('time'))


def unbilled_expenses(qs):
    """Billable items / expenses (TicketExpense queryset) not on a live invoice."""
    return qs.filter(is_billable=True).filter(~billed_exists('expense'))


UNBILLED_CHARGE = Q(invoiced=False) | Q(invoice__status='void') | Q(invoice__is_credit_memo=True)


def unbilled_charges(qs):
    """Account charges (psa.Charge queryset) not on a live invoice."""
    return qs.filter(UNBILLED_CHARGE)


def charge_is_billed(charge):
    from psa.models import Charge
    return not unbilled_charges(Charge.objects.filter(pk=charge.pk)).exists()


# --- queue decisions that keep work off invoices --------------------------------

def withheld(source, ids, today=None):
    """{source_id: decision} for the ids of `source` held or excluded at the
    Ready for Billing queue (Phase 102.3); those are not billed."""
    from psa.models import BillingQueueDecision
    ids = [str(i) for i in ids]
    if not ids:
        return {}
    today = today or timezone.localdate()
    return {d.source_id: d for d in BillingQueueDecision.objects.filter(
        source=source, source_id__in=ids, state__in=('held', 'excluded')) if d.withholds(today)}


def decisions_for(pairs):
    """{(source, source_id): decision} for (source, source_id) pairs."""
    from psa.models import BillingQueueDecision
    by_source = {}
    for src, sid in pairs:
        by_source.setdefault(src, set()).add(str(sid))
    out = {}
    for src, ids in by_source.items():
        for d in BillingQueueDecision.objects.filter(source=src, source_id__in=list(ids)):
            out[(d.source, d.source_id)] = d
    return out


# --- locking ---------------------------------------------------------------------

def lock_customer(client_org):
    """Take the customer's billing lock. Must run inside transaction.atomic()."""
    from psa.models import CustomerBillingLock
    if not connection.in_atomic_block:
        raise RuntimeError('lock_customer must run inside a transaction')
    org_id = getattr(client_org, 'pk', client_org)
    lock = CustomerBillingLock.objects.filter(client_org_id=org_id).first()
    if lock is None:
        try:
            with transaction.atomic():
                lock = CustomerBillingLock.objects.create(client_org_id=org_id)
        except IntegrityError:
            lock = CustomerBillingLock.objects.get(client_org_id=org_id)
    CustomerBillingLock.objects.filter(pk=lock.pk).update(revision=F('revision') + 1)
    return CustomerBillingLock.objects.select_for_update().get(pk=lock.pk)


def assert_billed_once(invoice):
    """Raise DoubleBilling when a line of `invoice` bills a record that is
    already on another live invoice. Call before the transaction commits."""
    from psa.models import Charge
    pairs = set(invoice.line_items.filter(source__in=SINGLE_SOURCES).exclude(source_id='')
                .values_list('source', 'source_id'))
    if not pairs:
        return
    q = Q()
    for src, sid in pairs:
        q |= Q(source=src, source_id=sid)
    clash = live_lines().filter(q).exclude(invoice_id=invoice.pk).values_list('source', 'source_id').first()
    if clash:
        raise DoubleBilling(f'{clash[0]} {clash[1]} is already on another invoice')
    charge_ids = [int(sid) for src, sid in pairs if src == 'charge' and sid.isdigit()]
    if charge_ids and Charge.objects.filter(pk__in=charge_ids).exclude(invoice_id=invoice.pk).exists():
        raise DoubleBilling('an account charge on this invoice is linked to another invoice')


# --- account charges -------------------------------------------------------------

def _read_charges(client_org, msp_org=None, charge_ids=None):
    """Unbilled, not withheld account charges of the customer, oldest first.
    Separate so the concurrency tests can hand back a stale read."""
    from psa.models import Charge
    qs = unbilled_charges(Charge.objects.filter(client_org=client_org))
    if msp_org is not None:
        qs = qs.filter(organization=msp_org)
    if charge_ids is not None:
        qs = qs.filter(pk__in=list(charge_ids))
    charges = list(qs.order_by('charge_date', 'pk'))
    held = withheld('charge', [c.pk for c in charges])
    return [c for c in charges if str(c.pk) not in held]


def bundle_charges(client_org, *, actor=None, msp_org=None, charge_ids=None, title=None):
    """Bundle the customer's unbilled account charges and credits into one
    new draft invoice, under the customer lock. Returns (invoice, count);
    (None, 0) when nothing is left to bill. Raises DoubleBilling when a
    concurrent writer billed one of them first (nothing is created).

    Each charge becomes a line with source 'charge' pointing at it, and the
    charge is claimed with a conditional UPDATE that only matches charges
    still unbilled, so the same charge can never be claimed twice."""
    from psa.models import Charge, Invoice, InvoiceLineItem
    today = timezone.localdate()
    with transaction.atomic():
        lock_customer(client_org)
        charges = _read_charges(client_org, msp_org, charge_ids)
        if not charges:
            return None, 0
        invoice = Invoice.objects.create(
            organization=msp_org or client_org, client_org=client_org,
            title=title or f'Account charges through {today:%Y-%m-%d}',
            invoice_date=today, created_by=actor)
        ids = [c.pk for c in charges]
        claimed = unbilled_charges(Charge.objects.filter(pk__in=ids)).update(invoiced=True, invoice=invoice)
        if claimed != len(ids):
            raise DoubleBilling('another invoice took some of these charges first')
        for i, c in enumerate(charges):
            # Credits come through as negative-priced line items.
            amount = Decimal(str(c.amount))
            InvoiceLineItem.objects.create(
                invoice=invoice, sort_order=i, description=c.description[:300], quantity=1,
                unit_price=-amount if c.is_credit else amount, source='charge', source_id=str(c.pk))
        assert_billed_once(invoice)
        invoice.recompute_totals()
        _audit(actor, invoice, f'Bundled {len(ids)} account charge(s) into draft invoice {invoice.invoice_number}',
               {'event': 'bundle_charges', 'charges': ids})
    return invoice, len(ids)


# --- ticket invoices -------------------------------------------------------------

def draft_ticket_invoice(ticket, *, actor=None, msp_org=None, include_before_cutoff=False):
    """Draft invoice for a ticket's unbilled work ("Invoice this ticket"),
    under the customer lock. Returns (invoice or None, info, contract).
    Raises DoubleBilling when a concurrent writer billed a line first."""
    from datetime import date as _date

    from psa.models import Contract, Invoice, InvoiceLineItem, Ticket

    from .invoicing import single_agreement
    from .ticket_charges import after_invoice
    with transaction.atomic():
        lock_customer(ticket.organization_id)
        Ticket.objects.select_for_update().filter(pk=ticket.pk).first()
        lines, info = ticket.uninvoiced_billing_lines(include_before_cutoff=include_before_cutoff)
        contract = single_agreement(info) or Contract.for_ticket(ticket)
        if not lines:
            return None, info, contract
        invoice = Invoice.objects.create(
            organization=msp_org or ticket.organization,
            client_org=ticket.organization,
            title=f'Invoice for {ticket.ticket_number} — {ticket.subject}'[:300],
            description=f'Billable time + expenses for ticket {ticket.ticket_number}',
            invoice_date=_date.today(),
            source_ticket=ticket,
            source_contract=contract,
            created_by=actor,
        )
        for sort_order, line in enumerate(lines):
            InvoiceLineItem.objects.create(invoice=invoice, sort_order=sort_order, **line)
        assert_billed_once(invoice)
        invoice.recompute_totals()
        # Phase 101.7: invoiced when nothing is left, else back to review.
        after_invoice(ticket)
    return invoice, info, contract


def _audit(actor, invoice, description, extra):
    try:
        from audit.models import AuditLog
        AuditLog.log(user=actor, action='create', organization=invoice.organization,
                     object_type='psa.Invoice', object_id=invoice.pk, object_repr=invoice.invoice_number,
                     description=description[:500], extra_data=extra)
    except Exception:  # pragma: no cover - the audit log never blocks billing
        import logging
        logging.getLogger('psa.billing').exception('audit log for invoice %s failed', invoice.pk)
