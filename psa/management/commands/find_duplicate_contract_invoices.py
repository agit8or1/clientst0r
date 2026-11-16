"""Report contract billing periods that were invoiced more than once.

Read-only. Lists every (contract, billing period) with more than one
non-credit-memo invoice, with each invoice's number, status, total, amount
paid and accounting id, so a person can decide which to keep. Migration
psa.0086 refuses to run while any exist.

Exits non-zero (CommandError) when duplicates are found, 0 otherwise.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Report contract billing periods invoiced more than once (read-only).'

    def handle(self, *args, **options):
        from django.db.models import Count
        from psa.models import Invoice

        groups = (Invoice.objects
                  .filter(source_contract__isnull=False,
                          billing_period_start__isnull=False,
                          is_credit_memo=False)
                  .values('source_contract_id', 'billing_period_start')
                  .annotate(n=Count('id')).filter(n__gt=1)
                  .order_by('source_contract_id', 'billing_period_start'))
        found = 0
        for g in groups:
            found += 1
            invs = (Invoice.objects
                    .filter(source_contract_id=g['source_contract_id'],
                            billing_period_start=g['billing_period_start'],
                            is_credit_memo=False)
                    .select_related('source_contract').order_by('id'))
            first = invs[0]
            name = first.source_contract.name if first.source_contract else '?'
            self.stdout.write(
                f'Contract #{g["source_contract_id"]} ({name}) period '
                f'{g["billing_period_start"]}: {g["n"]} invoices')
            for inv in invs:
                self.stdout.write(
                    f'  id={inv.pk} {inv.invoice_number} status={inv.status} '
                    f'total={inv.total} paid={inv.amount_paid} '
                    f'accounting={inv.accounting_provider or "-"}:'
                    f'{inv.accounting_external_id or "-"} created={inv.created_at:%Y-%m-%d}')
        if not found:
            self.stdout.write(self.style.SUCCESS(
                'No contract billing period has more than one invoice.'))
            return
        raise CommandError(
            f'{found} duplicated period(s). Nothing was changed. For each extra '
            f'invoice: delete it if it was never sent or pushed; otherwise keep it, '
            f'clear its billing_period_start, and credit the customer if they '
            f'were billed twice.')
