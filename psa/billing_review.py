"""Phase 36: recurring agreement billing review.

One row per agreement for a billing cycle (a calendar month): the included
hours consumed in the cycle, the overage hours, and the draft invoice raised
for it. Approve and hold act on the invoice's existing pre-invoice approval
gate (`Invoice.requires_approval` / `approve()`, v3.17.228), so a held invoice
cannot be sent or pushed to accounting until someone approves it.

Consumption follows the contract's own rules — `Contract.qualifying_time_entries`
(billable, stopped, in the contract window, role gates). The allowance is the
contract's (`effective_total_minutes`, i.e. hours plus unexpired rollover),
consumed chronologically from the contract's start: an entry in this cycle is
included while the running total is inside the allowance and overage once it
is past it — the same split as the reconciliation detail page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone

HOLD_PREFIX = 'Held at billing review'


def parse_cycle(raw, today=None):
    """'YYYY-MM' -> (first day, first day of next month). Bad or missing
    input falls back to the current month."""
    today = today or date.today()
    try:
        y, m = (int(p) for p in (raw or '').split('-', 1))
        start = date(y, m, 1)
    except (TypeError, ValueError):
        start = today.replace(day=1)
    return start, start + relativedelta(months=1)


def _hours(minutes):
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass
class ReviewRow:
    contract: object
    allowance_minutes: int = 0
    cycle_minutes: int = 0
    included_minutes: int = 0
    overage_minutes: int = 0
    to_date_minutes: int = 0
    invoice: object = None
    other_invoices: list = field(default_factory=list)

    @property
    def unlimited(self):
        return self.allowance_minutes <= 0

    @property
    def cycle_hours(self):
        return _hours(self.cycle_minutes)

    @property
    def included_hours(self):
        return _hours(self.included_minutes)

    @property
    def overage_hours(self):
        return _hours(self.overage_minutes)

    @property
    def allowance_hours(self):
        return _hours(self.allowance_minutes)

    @property
    def remaining_hours(self):
        if self.unlimited:
            return None
        return _hours(max(0, self.allowance_minutes - self.to_date_minutes))

    @property
    def overage_rate(self):
        c = self.contract
        return c.overage_rate if c.overage_rate else c.hourly_rate

    @property
    def overage_value(self):
        return (self.overage_hours * Decimal(str(self.overage_rate or 0))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def state(self):
        """none | draft | held | approved | sent — the review state of the invoice."""
        inv = self.invoice
        if inv is None:
            return 'none'
        if inv.requires_approval:
            return 'held' if (inv.approval_reason or '').startswith(HOLD_PREFIX) else 'flagged'
        if inv.status != 'draft':
            return 'sent'
        if inv.approved_at:
            return 'approved'
        return 'draft'


def contracts_for_cycle(contracts, start, end):
    """Contracts whose window overlaps [start, end)."""
    return (contracts.filter(start_date__lt=end)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=start))
            .exclude(status__in=['draft', 'cancelled'])
            .select_related('client_org', 'organization')
            .order_by('client_org__name', 'name'))


def build_rows(contracts, start, end):
    from .models import Invoice

    rows = []
    for c in contracts:
        row = ReviewRow(contract=c, allowance_minutes=c.effective_total_minutes())
        running = 0
        entries = (c.qualifying_time_entries()
                   .filter(started_at__date__lt=end)
                   .order_by('started_at', 'pk')
                   .values_list('started_at', 'duration_minutes'))
        for started_at, minutes in entries:
            minutes = int(minutes or 0)
            before = running
            running += minutes
            if timezone.localtime(started_at).date() < start:
                continue
            row.cycle_minutes += minutes
            if row.unlimited:
                row.included_minutes += minutes
            else:
                covered = max(0, min(minutes, row.allowance_minutes - before))
                row.included_minutes += covered
                row.overage_minutes += minutes - covered
        row.to_date_minutes = running

        invoices = list(Invoice.objects.filter(source_contract=c, is_credit_memo=False)
                        .exclude(status='void')
                        .filter(Q(billing_period_start__gte=start, billing_period_start__lt=end)
                                | Q(billing_period_start__isnull=True,
                                    invoice_date__gte=start, invoice_date__lt=end))
                        .select_related('approved_by')
                        .order_by('-invoice_date', '-pk'))
        if invoices:
            drafts = [i for i in invoices if i.status == 'draft']
            row.invoice = drafts[0] if drafts else invoices[0]
            row.other_invoices = [i for i in invoices if i.pk != row.invoice.pk]
        rows.append(row)
    return rows


def summary(rows):
    out = {'agreements': len(rows), 'with_invoice': 0, 'without_invoice': 0,
           'overage': 0, 'held': 0, 'flagged': 0, 'approved': 0, 'draft': 0, 'sent': 0,
           'overage_hours': Decimal('0.00'), 'draft_total': Decimal('0.00')}
    for r in rows:
        if r.invoice is None:
            out['without_invoice'] += 1
        else:
            out['with_invoice'] += 1
            out[r.state] = out.get(r.state, 0) + 1
            if r.invoice.status == 'draft':
                out['draft_total'] += Decimal(str(r.invoice.total or 0))
        if r.overage_minutes:
            out['overage'] += 1
            out['overage_hours'] += r.overage_hours
    return out


def hold(invoice, *, user, note=''):
    """Put the invoice on the pre-invoice approval gate."""
    reason = HOLD_PREFIX + (f': {note}' if note else '')
    invoice.requires_approval = True
    invoice.approval_reason = reason[:200]
    invoice.approved_by = None
    invoice.approved_at = None
    invoice.save(update_fields=['requires_approval', 'approval_reason',
                                'approved_by', 'approved_at', 'updated_at'])
    return reason


def approve(invoice, *, user):
    """Clear the gate (or record the review approval of an unflagged draft)."""
    invoice.approve(user=user)
