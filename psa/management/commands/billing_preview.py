"""Phase 101.4: preview the next ticket invoices under the new rules.

    manage.py billing_preview                    # every customer with unbilled ticket work
    manage.py billing_preview --customer 12      # one customer (repeatable)
    manage.py billing_preview --include-earlier  # as if "include earlier unbilled time" were ticked
    manage.py billing_preview --lines            # also list each line

Read-only: no invoice is created or changed. For each ticket with billable
time or expenses not on a live invoice it prints what "Invoice this ticket"
would bill under the rules before 101.4 (old counter, $0 without an
agreement) and now (ledger, rate cards, billing rules, upgrade cutoff), with
what was left off and why.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from psa.billing.invoicing import lines_total
from psa.billing.legacy import legacy_ticket_billing_lines
from psa.models import Contract, Ticket


def _m(v):
    return f'${Decimal(v).quantize(Decimal("0.01")):,.2f}'


class Command(BaseCommand):
    help = 'Compare the next ticket invoices under the old and the Phase 101.4 billing rules (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--customer', type=int, action='append', help='Customer (organization) id.')
        parser.add_argument('--include-earlier', action='store_true',
                            help='Price time worked before the upgrade cutoff too.')
        parser.add_argument('--lines', action='store_true', help='List the lines of both versions.')

    def handle(self, *args, **opts):
        from psa.billing.invoicing import cutoff
        from psa.billing.billed import unbilled_expenses, unbilled_time
        from psa.models import TicketExpense, TicketTimeEntry
        # Phase 102.2: the same "is it billed" rule as invoicing.
        t_ids = set(unbilled_time(TicketTimeEntry.objects.all()).values_list('ticket_id', flat=True))
        t_ids |= set(unbilled_expenses(TicketExpense.objects.all()).values_list('ticket_id', flat=True))
        tickets = (Ticket.objects.filter(pk__in=t_ids).select_related('organization')
                   .order_by('organization__name', 'pk'))
        if opts.get('customer'):
            tickets = tickets.filter(organization_id__in=opts['customer'])
        self.stdout.write(f'Billing preview (read-only). Upgrade cutoff: {cutoff()}'
                          + ('; earlier time included' if opts['include_earlier'] else ''))
        per_customer = {}
        for t in tickets:
            old_lines, _old_info = legacy_ticket_billing_lines(t, Contract.for_ticket(t))
            new_lines, info = t.uninvoiced_billing_lines(include_before_cutoff=opts['include_earlier'])
            if not old_lines and not new_lines and not (info['awaiting_approval'] or info['needs_choice']
                                                        or info['no_rate'] or info.get('needs_classification')
                                                        or info.get('unused_stock')):
                continue
            old_total, new_total = lines_total(old_lines), lines_total(new_lines)
            cust = per_customer.setdefault(t.organization.name, [Decimal('0'), Decimal('0')])
            cust[0] += old_total
            cust[1] += new_total
            notes = []
            if info['awaiting_approval']:
                notes.append(f'{len(info["awaiting_approval"])} entr(ies) under prepaid hours wait for approval')
            if info['needs_choice']:
                notes.append(f'{len(info["needs_choice"])} entr(ies) need an agreement choice')
            if info['no_rate']:
                notes.append(f'{len(info["no_rate"])} entr(ies) have no rate (left off)')
            if info.get('needs_classification'):
                notes.append(f'{len(info["needs_classification"])} entr(ies) need classification (left off)')
            if info.get('unused_stock'):
                notes.append(f'{len(info["unused_stock"])} reserved stock item(s) not marked used (left off)')
            if info['before_cutoff']:
                notes.append(f'{len(info["before_cutoff"])} entr(ies) before the cutoff billed the old way')
            if info['fees']:
                notes.append(f'trip fees {_m(info["fees"])}')
            if info.get('held'):
                notes.append(f'{len(info["held"])} line(s) on hold at the Ready for Billing queue (left off)')
            if info.get('excluded'):
                notes.append(f'{len(info["excluded"])} line(s) excluded at the Ready for Billing queue (left off)')
            if info['billed_minutes'] and info['billed_minutes'] != (info['chargeable_minutes']
                                                                     + info['overage_minutes']):
                notes.append(f'rounding: {info["chargeable_minutes"] + info["overage_minutes"]} min worked, '
                             f'{info["billed_minutes"]} min billed')
            self.stdout.write(f'  {t.organization.name} / {t.ticket_number}: old {_m(old_total)} -> new '
                              f'{_m(new_total)} (difference {_m(new_total - old_total)})')
            for n in notes:
                self.stdout.write(f'      - {n}')
            if opts['lines']:
                for label, ls in (('old', old_lines), ('new', new_lines)):
                    for ln in ls:
                        self.stdout.write(f'      {label}: {ln["quantity"]} x {_m(ln["unit_price"])}  '
                                          f'{ln["description"]}')
        self.stdout.write('')
        self.stdout.write('Per customer (next ticket invoices, before tax):')
        for name, (old, new) in sorted(per_customer.items()):
            self.stdout.write(f'  {name}: old {_m(old)} -> new {_m(new)} (difference {_m(new - old)})')
        if not per_customer:
            self.stdout.write('  nothing unbilled')
