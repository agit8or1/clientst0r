"""The ticket invoicing rules from before Phase 101.4, kept verbatim for the
billing preview (`manage.py billing_preview`) so the owner can compare the
next invoice under the old and the new logic. Nothing bills from this.

`self` is the ticket; `contract` is what `Contract.for_ticket` returns. It
reads the old hour counter (`Contract.hours_used_minutes`), which counts
unapproved time, and bills time without an agreement at $0.
"""


def legacy_ticket_billing_lines(self, contract=None):
    """What a ticket invoice should bill right now, as line-item dicts.

    Returns `(lines, info)`. Each line is a dict of InvoiceLineItem
    fields. `info` summarises the split for the caller's message:
    `{'covered_minutes', 'overage_minutes', 'rate', 'allowance'}`.

    Two rules, both added after the ticket-invoice path was found billing
    the same work twice and billing prepaid hours a second time:

    1. Entries and expenses already on a live invoice are left out. "Live"
       means not void and not a credit memo — see
       `InvoiceLineItem.billed_source_ids`.

    2. Under a contract with an hours allowance (block hours / retainer,
       `effective_total_minutes() > 0`), time is already paid for by the
       contract's recurring invoice (`Contract.generate_invoice` bills the
       block; it never bills time). Only the minutes the contract has
       consumed beyond its allowance — and not already billed as overage
       on another invoice for this contract — are charged, at
       `overage_rate` (or `hourly_rate` when no overage rate is set). The
       covered remainder goes on the invoice as a zero-priced line, so the
       customer sees the work and the entry is recorded as invoiced. When
       only part of the work is overage, the latest entries are treated as
       the overage — they are the ones logged after the allowance ran out.

    3. Flat-fee contracts — `contract_type` in `Contract.FLAT_FEE_TYPES`
       (managed services, retainer) with no allowance — cover all ticket
       time: every entry goes on as a zero-priced covered line, recorded
       as invoiced so it is never billed later. Expenses are still billed.

    Other contracts without an allowance (block_hours with 0 hours,
    per_incident) or no contract bill all time at `contract.hourly_rate`
    (0 without a contract), as before.
    """
    from decimal import Decimal
    from psa.models import Contract, InvoiceLineItem

    def _hours(minutes):
        return (Decimal(minutes) / Decimal(60)).quantize(Decimal('0.01'))

    entries = [
        te for te in self.time_entries.filter(is_billable=True)
        .exclude(ended_at__isnull=True).order_by('started_at', 'pk')
        if (te.duration_minutes or 0) > 0
    ]
    billed_time = InvoiceLineItem.billed_source_ids(
        'time', [te.pk for te in entries])
    entries = [te for te in entries if te.pk not in billed_time]
    expenses = list(self.expenses.filter(is_billable=True)
                    .order_by('incurred_on', 'pk'))
    billed_exp = InvoiceLineItem.billed_source_ids(
        'expense', [e.pk for e in expenses])
    expenses = [e for e in expenses if e.pk not in billed_exp]

    allowance = contract.effective_total_minutes() if contract else 0
    overage_by_entry = {}
    if contract and allowance > 0:
        rate = Decimal(str(contract.overage_rate or contract.hourly_rate or 0))
        over_total = max(0, (contract.hours_used_minutes or 0) - allowance)
        over_left = max(0, over_total - contract.overage_minutes_invoiced())
        for te in reversed(entries):
            if over_left <= 0:
                break
            take = min(over_left, te.duration_minutes)
            overage_by_entry[te.pk] = take
            over_left -= take
    else:
        rate = Decimal(str(contract.hourly_rate)) if contract else Decimal('0')
    # Flat-fee contracts (managed services / retainer with no hours
    # allowance) cover all ticket time: the recurring fee is the price.
    # Product decision 2026-10-15. Expenses are still billed.
    flat_fee = bool(contract and allowance <= 0
                    and contract.contract_type in Contract.FLAT_FEE_TYPES)

    lines = []
    covered_total = 0
    over_total_now = 0
    for te in entries:
        work = (te.notes or 'work').strip() or 'work'
        if flat_fee:
            covered_total += te.duration_minutes
            lines.append({
                'description': f'Time (covered by {contract.name}): {work}'[:300],
                'quantity': _hours(te.duration_minutes),
                'unit_price': Decimal('0'),
                'source': 'time', 'source_id': str(te.pk),
            })
        elif contract and allowance > 0:
            over = overage_by_entry.get(te.pk, 0)
            covered = te.duration_minutes - over
            if covered > 0:
                covered_total += covered
                lines.append({
                    'description': f'Time (covered by {contract.name} prepaid hours): {work}'[:300],
                    'quantity': _hours(covered),
                    'unit_price': Decimal('0'),
                    'source': 'time', 'source_id': str(te.pk),
                })
            if over > 0:
                over_total_now += over
                lines.append({
                    'description': f'Time (beyond prepaid hours): {work}'[:300],
                    'quantity': _hours(over),
                    'unit_price': rate,
                    'source': 'time', 'source_id': str(te.pk),
                })
        else:
            lines.append({
                'description': f'Time: {work}'[:300],
                'quantity': _hours(te.duration_minutes),
                'unit_price': rate,
                'source': 'time', 'source_id': str(te.pk),
            })
    for e in expenses:
        lines.append({
            'description': f'Expense: {e.description}'[:300],
            'quantity': Decimal('1'),
            'unit_price': Decimal(str(e.amount)),
            'source': 'expense', 'source_id': str(e.pk),
        })
    return lines, {
        'covered_minutes': covered_total,
        'overage_minutes': over_total_now,
        'rate': rate,
        'allowance': allowance,
    }

