"""Phase 102.4: consolidated invoices — several tickets, the customer's
account charges and (optionally) one agreement's next recurring fee on one
draft invoice.

Every line keeps its source (`source` / `source_id`, as on every other
invoice); ticket lines also carry `ticket`, and are written grouped by
ticket (ticket order, then each ticket's own line order), then the account
charges, then the agreement fee.

Integrity (the same rules as the single-ticket and account-charge drafts in
psa.billing.billed):

* One transaction under the customer billing lock; the tickets and the
  agreement row are locked too, and everything is re-read after the locks.
* Ticket lines are exactly `Ticket.uninvoiced_billing_lines()` (the
  invoicing rules of Phases 101 and 102.3: held / excluded work is left off).
* Account charges are claimed with a conditional UPDATE that only matches
  charges still unbilled (held / excluded ones are never read).
* Before commit the invoice is checked against every other live invoice
  (`assert_billed_once`); a concurrent writer or a stale read raises
  DoubleBilling and the whole draft rolls back.
* The agreement fee is the period at the agreement's `next_billing_date`,
  priced by `Contract.recurring_period_lines` (the recurring generator's
  own code) and claimed by the invoice's (source_contract,
  billing_period_start) — the unique per-period key the recurring generator
  uses — so the period can be billed once only, here or by the generator.
  The billing cursor advances in the same transaction, as the generator
  does. When the fee cannot be billed safely it is left off and the reason
  reported (see `contract_fee_status`).

Drafts are never sent from here. A sent invoice is corrected only with a
credit memo (Invoice.create_credit_memo); the invoice form refuses edits once
an invoice has left draft.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import billed


@dataclass
class FeeStatus:
    contract: object
    period: date | None = None
    lines: list = field(default_factory=list)
    reason: str = ''

    @property
    def ok(self):
        return self.period is not None and bool(self.lines) and not self.reason

    @property
    def total(self):
        from .invoicing import lines_total
        return lines_total(self.lines)


def _periods_due(contract, today):
    from psa.models import Contract
    due, nxt = 0, contract.next_billing_date
    while nxt is not None and nxt <= today and due < 1000:
        due += 1
        nxt = Contract._advance_billing(nxt, contract.billing_frequency)
    return due


def contract_fee_status(contract, today=None):
    """Whether the agreement's next recurring fee can go on a consolidated
    invoice now, with its lines, or why not. Read-only.

    Billed only when the recurring generator would bill it today, in its
    scheduled (no catch-up) mode: active, not paused, not ending at the
    period end, not past its end date, billing on, its next billing date
    reached and exactly one period due, the period not already invoiced and
    something to bill."""
    from psa.models import Invoice
    today = today or timezone.localdate()
    st = FeeStatus(contract=contract)
    name = contract.name
    if contract.status != 'active':
        st.reason = f'{name} is not active.'
    elif contract.billing_frequency == 'none':
        st.reason = f'{name} has no recurring billing.'
    elif not contract.esign_status(for_billing=True)['satisfied']:
        st.reason = f'{name} needs the customer\'s e-signature before it is billed.'
    elif contract.paused_at:
        st.reason = f'{name} is paused.'
    elif contract.cancel_at_period_end:
        st.reason = f'{name} ends at the end of its paid period; there is no next fee.'
    elif contract.end_date and contract.end_date < today:
        st.reason = f'{name} ended on {contract.end_date}.'
    elif not contract.next_billing_date:
        st.reason = f'{name} has no next billing date.'
    elif contract.next_billing_date > today:
        st.reason = (f'The next fee of {name} is due on {contract.next_billing_date}; it is billed then '
                     '(by the recurring billing run or here).')
    else:
        due = _periods_due(contract, today)
        if due > 1:
            st.reason = (f'{name} is {due} billing periods behind (next billing {contract.next_billing_date}); '
                         'bill or skip the missed periods from recurring billing first.')
        elif Invoice.objects.filter(source_contract=contract, billing_period_start=contract.next_billing_date,
                                    is_credit_memo=False).exists():
            st.reason = f'The {contract.next_billing_date} period of {name} is already invoiced.'
        else:
            st.period = contract.next_billing_date
            st.lines = contract.recurring_period_lines(st.period)
            if not st.lines:
                st.reason = f'{name} has nothing to bill for the period starting {st.period}.'
    return st


def fee_candidates(client, today=None):
    """[FeeStatus] for the customer's active agreements with recurring billing."""
    from psa.models import Contract
    qs = (Contract.objects.filter(client_org=client, status='active').exclude(billing_frequency='none')
          .order_by('name', 'pk'))
    return [contract_fee_status(c, today) for c in qs]


@dataclass
class Result:
    invoice: object = None
    notes: list = field(default_factory=list)
    fee_deferred: str = ''


def draft_consolidated(client, *, actor=None, msp_org=None, ticket_ids=(), include_charges=False,
                       contract_id=None, today=None):
    """One draft invoice for `client` with the selected tickets' unbilled
    lines, its account charges (`include_charges`) and the next fee of the
    agreement `contract_id` (when it can be billed safely). Returns Result;
    `invoice` is None when nothing was left to bill. Raises
    billed.DoubleBilling when a concurrent writer billed something first
    (nothing is created)."""
    from psa.models import Charge, Contract, Invoice, InvoiceLineItem, Ticket

    from .invoicing import single_agreement
    from .ticket_charges import after_invoice
    today = today or timezone.localdate()
    res = Result()
    ids = sorted({int(i) for i in ticket_ids if str(i).isdigit()})
    with transaction.atomic():
        billed.lock_customer(client)
        tickets = list(Ticket.objects.select_for_update().filter(organization=client, pk__in=ids).order_by('pk'))
        groups, agreements = [], set()
        for t in tickets:
            lines, info = t.uninvoiced_billing_lines()
            agreements |= set(info.get('agreements') or ())
            if lines:
                groups.append((t, lines))
            else:
                res.notes.append(f'Nothing left to invoice on {t.ticket_number}.')
        charges = billed._read_charges(client, msp_org) if include_charges else []
        if include_charges and not charges:
            res.notes.append('No account charges left to invoice.')

        fee = None
        if contract_id:
            contract = (Contract.objects.select_for_update()
                        .filter(pk=contract_id, client_org=client).first())
            if contract is None:
                res.fee_deferred = 'That agreement is not one of this customer\'s.'
            else:
                fee = contract_fee_status(contract, today)
                if not fee.ok:
                    res.fee_deferred = fee.reason
                    fee = None
            if res.fee_deferred:
                res.notes.append(f'Agreement fee not included: {res.fee_deferred}')

        if not groups and not charges and fee is None:
            return res

        source_contract = fee.contract if fee is not None else single_agreement({'agreements': agreements})
        parts = []
        if groups:
            parts.append(f'{len(groups)} ticket{"s" if len(groups) != 1 else ""}')
        if charges:
            parts.append('account charges')
        if fee is not None:
            parts.append(f'{fee.contract.name} {fee.period:%Y-%m-%d}')
        try:
            with transaction.atomic():
                invoice = Invoice.objects.create(
                    organization=msp_org or client, client_org=client,
                    title=f'Consolidated invoice — {client.name} {today:%Y-%m-%d}'[:300],
                    description=('Includes ' + ', '.join(parts))[:1000],
                    invoice_date=today,
                    source_ticket=groups[0][0] if len(groups) == 1 else None,
                    source_contract=source_contract,
                    billing_period_start=fee.period if fee is not None else None,
                    created_by=actor)
        except IntegrityError as exc:
            # Only the per-period key can collide here: the recurring
            # generator invoiced the period after our check.
            raise billed.DoubleBilling(f'the agreement period was invoiced at the same time ({exc})')

        order = 0
        written = []
        for t, lines in groups:
            for ln in lines:
                ln = dict(ln)
                ln['description'] = f'{t.ticket_number} — {ln["description"]}'[:300]
                InvoiceLineItem.objects.create(invoice=invoice, sort_order=order, ticket=t, **ln)
                written.append({'ticket': t.ticket_number, 'source': ln['source'],
                                'source_id': str(ln['source_id'])})
                order += 1
        if charges:
            cids = [c.pk for c in charges]
            claimed = billed.unbilled_charges(Charge.objects.filter(pk__in=cids)).update(
                invoiced=True, invoice=invoice)
            if claimed != len(cids):
                raise billed.DoubleBilling('another invoice took some of these charges first')
            for c in charges:
                amount = Decimal(str(c.amount))
                InvoiceLineItem.objects.create(
                    invoice=invoice, sort_order=order, description=f'Account charge — {c.description}'[:300],
                    quantity=1, unit_price=-amount if c.is_credit else amount, source='charge',
                    source_id=str(c.pk))
                written.append({'source': 'charge', 'source_id': str(c.pk)})
                order += 1
        if fee is not None:
            for ln in fee.lines:
                ln = dict(ln)
                ln['description'] = f'{fee.contract.name} — {ln["description"]}'[:300]
                InvoiceLineItem.objects.create(invoice=invoice, sort_order=order, **ln)
                written.append({'source': ln['source'], 'source_id': ln['source_id']})
                order += 1

        billed.assert_billed_once(invoice)
        if fee is not None:
            c = fee.contract
            c.mark_period_billed(fee.period)
            # As the recurring generator does in its transaction: the period is
            # billed, the cursor moves to the next one.
            c.next_billing_date = Contract._advance_billing(fee.period, c.billing_frequency)
            c.last_billed_at = today
            c.save(update_fields=['next_billing_date', 'last_billed_at', 'updated_at'])
        invoice.recompute_totals()
        for t, _lines in groups:
            after_invoice(t)
        billed._audit(actor, invoice,
                      f'Consolidated draft invoice {invoice.invoice_number} for {client.name}: ' + ', '.join(parts),
                      {'event': 'consolidated_invoice', 'tickets': [t.ticket_number for t, _ in groups],
                       'charges': [c.pk for c in charges],
                       'contract_period': ({'contract': fee.contract.pk, 'period': fee.period.isoformat()}
                                           if fee is not None else None),
                       'fee_deferred': res.fee_deferred, 'lines': written})
    res.invoice = invoice
    return res
