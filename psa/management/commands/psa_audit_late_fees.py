"""Read-only report of late fees charged on money the client had already been
credited back.

Until v3.17.578 `psa_apply_late_fees` computed its fee from
`Invoice.balance`. A credit memo is a separate negative invoice pointing at
the original through `credits_invoice`; issuing one leaves the original's
`amount_paid` and `status` untouched, so `balance` still read as the full
amount due. An invoice credited in full still drew a fee on the whole original
amount.

Fixing the cron does not rewrite history. The `Charge` rows it already wrote
are still on the client's account, and they are real charges rather than a
display artefact. This command tells you which ones were overcharged and by
how much, so the decision about credits, refunds or leaving settled accounts
alone stays with you and your accountant.

It writes nothing. No charge is modified or removed, no invoice recomputed.
Run it as often as you like.

    manage.py psa_audit_late_fees
    manage.py psa_audit_late_fees --org acme --since 2026-01-01
    manage.py psa_audit_late_fees --csv /path/to/late-fee-audit.csv

How a fee is judged
-------------------

`psa_apply_late_fees` records its working in the charge description:

    Late fee for INV-2026-00001 (overdue $1000.00, 5.00% applied)

so the amount it billed on and the rate it used are both recoverable. Against
that, the credits that *existed when the fee was applied* are summed — memos
dated after the charge are not counted, because the fee was correct on the day
it was raised. What remains is what the fee should have been.
"""
import csv
import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from psa.models import Charge, Invoice

CENT = Decimal('0.01')

# "Late fee for INV-2026-00001 (overdue $1000.00, 5.00% applied)"
FEE_RE = re.compile(
    r'^Late fee for (?P<number>\S+)\s*'
    r'\(overdue \$(?P<overdue>[\d.,]+),\s*(?P<pct>[\d.]+)% applied\)'
)


def _dec(text):
    try:
        return Decimal(str(text).replace(',', ''))
    except (InvalidOperation, ValueError, TypeError):
        return None


class Command(BaseCommand):
    help = ('Read-only: list late fees charged on amounts that had already '
            'been credited back by a credit memo. Modifies nothing.')

    def add_arguments(self, parser):
        parser.add_argument('--org', type=str, default=None,
                            help='Limit to one client organization, by slug.')
        parser.add_argument('--since', type=str, default=None,
                            help='Only fees charged on or after YYYY-MM-DD.')
        parser.add_argument('--csv', type=str, default=None,
                            help='Also write the rows to this CSV path.')

    def handle(self, *args, **options):
        charges = Charge.objects.filter(
            description__startswith='Late fee for ',
            is_credit=False,
        ).select_related('client_org', 'organization').order_by('charge_date')

        if options['org']:
            charges = charges.filter(client_org__slug=options['org'])
            if not charges.exists():
                raise CommandError(
                    f'No late-fee charges found for organization '
                    f'"{options["org"]}".')

        if options['since']:
            from datetime import date
            try:
                since = date.fromisoformat(options['since'])
            except ValueError:
                raise CommandError('--since must be YYYY-MM-DD.')
            charges = charges.filter(charge_date__gte=since)

        rows = []
        unparseable = []
        missing_invoice = []

        for charge in charges:
            match = FEE_RE.match(charge.description or '')
            if not match:
                unparseable.append(charge)
                continue

            number = match.group('number')
            billed_on = _dec(match.group('overdue'))
            pct = _dec(match.group('pct'))
            if billed_on is None or pct is None:
                unparseable.append(charge)
                continue

            invoice = Invoice.objects.filter(invoice_number=number).first()
            if invoice is None:
                missing_invoice.append((charge, number))
                continue

            # Only credits that existed when the fee was raised. A memo issued
            # afterwards does not make the fee wrong at the time.
            credited_then = Decimal('0')
            for memo in invoice.credit_memos.exclude(status='void'):
                if memo.invoice_date and memo.invoice_date <= charge.charge_date:
                    credited_then += -Decimal(str(memo.total or '0'))

            if credited_then <= 0:
                continue

            should_have_billed_on = max(Decimal('0'), billed_on - credited_then)
            should_have_been = (
                should_have_billed_on * pct / Decimal('100')).quantize(CENT)
            charged = Decimal(str(charge.amount or '0'))
            overcharge = (charged - should_have_been).quantize(CENT)
            if overcharge <= 0:
                continue

            rows.append({
                'charge_id': charge.pk,
                'charge_date': charge.charge_date,
                'client': charge.client_org.name if charge.client_org else '',
                'client_slug': charge.client_org.slug if charge.client_org else '',
                'invoice': number,
                'billed_on': billed_on,
                'credited_at_the_time': credited_then,
                'rate_pct': pct,
                'charged': charged,
                'should_have_been': should_have_been,
                'overcharged_by': overcharge,
                'already_invoiced': charge.invoiced,
            })

        self._report(rows, unparseable, missing_invoice)

        if options['csv'] and rows:
            self._write_csv(options['csv'], rows)

    def _report(self, rows, unparseable, missing_invoice):
        if not rows:
            self.stdout.write(self.style.SUCCESS(
                'No late fees were charged on credited amounts.'))
        else:
            total = sum((r['overcharged_by'] for r in rows), Decimal('0'))
            self.stdout.write(self.style.WARNING(
                f'{len(rows)} late fee(s) charged on amounts already credited '
                f'— ${total} overcharged in total.\n'))
            header = (f'{"charge":>7}  {"date":<11}  {"client":<22}  '
                      f'{"invoice":<16}  {"charged":>10}  {"should be":>10}  '
                      f'{"over":>10}  invoiced')
            self.stdout.write(header)
            self.stdout.write('-' * len(header))
            for r in rows:
                self.stdout.write(
                    f'{r["charge_id"]:>7}  {str(r["charge_date"]):<11}  '
                    f'{r["client"][:22]:<22}  {r["invoice"]:<16}  '
                    f'{r["charged"]:>10}  {r["should_have_been"]:>10}  '
                    f'{r["overcharged_by"]:>10}  '
                    f'{"yes" if r["already_invoiced"] else "no"}'
                )
            self.stdout.write('')
            billed = [r for r in rows if r['already_invoiced']]
            if billed:
                self.stdout.write(self.style.WARNING(
                    f'{len(billed)} of these are already on an invoice, so a '
                    f'credit memo is the cleaner correction for those.'))
            self.stdout.write(
                'Nothing has been changed. Reversing a fee is a financial '
                'decision: an uninvoiced charge can simply be removed, while '
                'one already invoiced usually wants a credit memo against the '
                'invoice that carried it.')

        if unparseable:
            self.stdout.write(self.style.NOTICE(
                f'\n{len(unparseable)} late-fee charge(s) did not match the '
                f'expected description format and were not assessed — review '
                f'by hand: '
                + ', '.join(str(c.pk) for c in unparseable[:20])
                + ('…' if len(unparseable) > 20 else '')))

        if missing_invoice:
            self.stdout.write(self.style.NOTICE(
                f'\n{len(missing_invoice)} late-fee charge(s) name an invoice '
                f'that no longer exists: '
                + ', '.join(f'{c.pk}→{n}' for c, n in missing_invoice[:20])
                + ('…' if len(missing_invoice) > 20 else '')))

    def _write_csv(self, path, rows):
        try:
            with open(path, 'w', newline='') as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            raise CommandError(f'Could not write {path}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'\nWrote {len(rows)} row(s) to {path}'))
