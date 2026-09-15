"""Read-only report of invoices whose stored tax disagrees with the corrected
calculation.

Until v3.17.561 both `Invoice.recompute_totals` and `Quote.recompute_totals`
computed tax from the whole subtotal, ignoring the per-line `is_taxable` flag,
and rounded with Decimal's default banker's rounding. An invoice mixing taxable
goods with non-taxable labour or reimbursed expenses was overcharged.

Fixing the calculation does not rewrite history: stored totals stay as issued
until something recomputes them. This command tells you which invoices are
affected and by how much, so the decision about refunds, credit memos or
leaving settled invoices alone stays with you and your accountant.

It writes nothing. No invoice is modified, no total recomputed, no status
changed. Run it as often as you like.

    manage.py psa_tax_audit
    manage.py psa_tax_audit --org acme --since 2026-01-01
    manage.py psa_tax_audit --csv /path/to/tax-audit.csv
    manage.py psa_tax_audit --all-statuses --include-credit-memos
"""
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch

from psa.models import Invoice, InvoiceLineItem

CENT = Decimal('0.01')


def corrected_tax(invoice):
    """The tax the fixed calculation produces. Pure — touches no database row."""
    try:
        rate = Decimal(str(invoice.tax_rate or '0'))
    except (InvalidOperation, ValueError, TypeError):
        rate = Decimal('0')
    taxable = sum((li.line_total for li in invoice.line_items.all()
                   if li.is_taxable), Decimal('0'))
    return (taxable * rate).quantize(CENT, rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = ('Read-only: list invoices whose stored tax differs from the '
            'corrected per-line calculation. Modifies nothing.')

    def add_arguments(self, parser):
        parser.add_argument('--org', type=str, default=None,
                            help='Limit to one client organization, by slug.')
        parser.add_argument('--since', type=str, default=None,
                            help='Only invoices dated on or after YYYY-MM-DD.')
        parser.add_argument('--csv', type=str, default=None,
                            help='Also write the rows to this CSV path.')
        parser.add_argument('--all-statuses', action='store_true',
                            help='Include draft and void invoices (excluded by '
                                 'default — a draft has not been sent to anyone '
                                 'and a void one has been withdrawn).')
        parser.add_argument('--include-credit-memos', action='store_true',
                            help='Include credit memos. Excluded by default so '
                                 'the overcharge total is not netted off by '
                                 'credits that carry the same defect.')

    def handle(self, *args, **opts):
        qs = (Invoice.objects
              .select_related('client_org')
              .prefetch_related(Prefetch('line_items',
                                         queryset=InvoiceLineItem.objects.all()))
              .order_by('client_org__name', 'invoice_date', 'pk'))

        if not opts['all_statuses']:
            qs = qs.exclude(status__in=('draft', 'void'))
        if not opts['include_credit_memos']:
            qs = qs.filter(is_credit_memo=False)
        if opts['org']:
            qs = qs.filter(client_org__slug=opts['org'])
            if not qs.exists():
                raise CommandError(f"No invoices for client org '{opts['org']}'.")
        if opts['since']:
            qs = qs.filter(invoice_date__gte=opts['since'])

        rows = []
        scanned = 0
        for inv in qs.iterator(chunk_size=500):
            scanned += 1
            stored = Decimal(str(inv.tax_amount or '0')).quantize(CENT)
            fixed = corrected_tax(inv)
            if stored == fixed:
                continue
            lines = list(inv.line_items.all())
            rows.append({
                'invoice': inv.invoice_number or f'(unnumbered #{inv.pk})',
                'client': inv.client_org.name if inv.client_org else '—',
                'date': inv.invoice_date,
                'status': inv.status,
                'subtotal': Decimal(str(inv.subtotal or '0')),
                'non_taxable_lines': sum(1 for li in lines if not li.is_taxable),
                'line_count': len(lines),
                'tax_charged': stored,
                'tax_corrected': fixed,
                'delta': (stored - fixed).quantize(CENT),
            })

        self._report(rows, scanned, opts)

    def _report(self, rows, scanned, opts):
        w = self.stdout.write
        w('')
        w(self.style.MIGRATE_HEADING(
            f'Tax audit — {scanned} invoice(s) scanned, {len(rows)} with a discrepancy'))
        w(self.style.WARNING('This command is read-only. Nothing was modified.'))
        w('')

        if not rows:
            w(self.style.SUCCESS('No invoice has a stored tax amount that '
                                 'disagrees with the corrected calculation.'))
            return

        hdr = (f'{"Invoice":<18}{"Client":<26}{"Date":<12}{"Status":<10}'
               f'{"Charged":>12}{"Correct":>12}{"Delta":>12}')
        w(hdr)
        w('-' * len(hdr))

        by_client = {}
        total = Decimal('0')
        for r in rows:
            w(f'{r["invoice"][:17]:<18}{r["client"][:25]:<26}'
              f'{str(r["date"]):<12}{r["status"]:<10}'
              f'{r["tax_charged"]:>12}{r["tax_corrected"]:>12}{r["delta"]:>12}')
            by_client.setdefault(r['client'], Decimal('0'))
            by_client[r['client']] += r['delta']
            total += r['delta']

        w('')
        w(self.style.MIGRATE_HEADING('By client'))
        for client, amount in sorted(by_client.items(), key=lambda kv: -kv[1]):
            label = 'overcharged' if amount > 0 else 'undercharged'
            w(f'  {client[:40]:<42}{abs(amount):>12}  {label}')

        w('')
        if total > 0:
            w(self.style.ERROR(f'  Net overcharged across all clients: {total}'))
        elif total < 0:
            w(self.style.WARNING(f'  Net undercharged across all clients: {abs(total)}'))
        else:
            w(f'  Net across all clients: {total} (over- and undercharges cancel)')

        w('')
        w('A positive delta means the customer was charged more tax than the')
        w('corrected calculation produces. Not every difference is necessarily')
        w('the per-line bug: a tax amount edited by hand, or a rate changed')
        w('after the invoice was issued, lands here too. Check a sample before')
        w('acting on the total.')
        w('')
        w('Nothing here is a refund decision. Stored totals are untouched and')
        w('stay that way until something recomputes the invoice.')

        if opts['csv']:
            self._write_csv(rows, opts['csv'])

    def _write_csv(self, rows, path):
        cols = ['invoice', 'client', 'date', 'status', 'subtotal',
                'line_count', 'non_taxable_lines',
                'tax_charged', 'tax_corrected', 'delta']
        try:
            with open(path, 'w', newline='') as fh:
                writer = csv.DictWriter(fh, fieldnames=cols)
                writer.writeheader()
                for r in rows:
                    writer.writerow({c: r[c] for c in cols})
        except OSError as exc:
            raise CommandError(f'Could not write {path}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'\nWrote {len(rows)} row(s) to {path}'))
