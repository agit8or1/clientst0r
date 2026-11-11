"""Seed serial lifecycle history from records that predate it (Phase 13).

Creates, at most once each:
  * a "received" event per serial captured on a PO receipt line
  * an "assigned" event per asset with a serial and no history for it
  * an "RMA opened" event (plus the RMA's current status) per RMA with a serial

Safe to run more than once. Use --dry-run to only count.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from assets import serial_lifecycle


class Command(BaseCommand):
    help = 'Create serial lifecycle events for PO receipts, assets and RMAs recorded before serial tracking.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **opts):
        from assets.models import Asset, RMAReturn, SerialEvent
        from psa.models import POReceiptLine
        counts = {'received': 0, 'assigned': 0, 'rma': 0}
        with transaction.atomic():
            for line in POReceiptLine.objects.select_related('receipt__po__client_org',
                                                             'receipt__po__organization', 'po_line'):
                po = line.receipt.po
                org = po.client_org or po.organization
                for sn in line.serial_numbers or []:
                    key = serial_lifecycle.normalize(sn)
                    if not key or SerialEvent.objects.filter(receipt_line=line, serial_key=key,
                                                             event_type='received').exists():
                        continue
                    counts['received'] += 1
                    if not dry_run:
                        serial_lifecycle.record(org, sn, 'received', purchase_order=po, receipt_line=line,
                                                actor=line.receipt.received_by, when=line.receipt.received_at,
                                                notes=f'{po.po_number}: {line.po_line.description}'[:500])
            for asset in Asset.objects.exclude(serial_number='').select_related('organization', 'created_by'):
                key = serial_lifecycle.normalize(asset.serial_number)
                if not key or SerialEvent.objects.filter(asset=asset, serial_key=key).exists():
                    continue
                counts['assigned'] += 1
                if not dry_run:
                    serial_lifecycle.record(asset.organization, asset.serial_number, 'assigned', asset=asset,
                                            actor=asset.created_by, when=asset.created_at,
                                            notes='Recorded from the existing asset')
            for rma in RMAReturn.objects.select_related('asset', 'organization', 'purchase_order'):
                serial = serial_lifecycle._rma_serial(rma)
                if not serial_lifecycle.normalize(serial) or SerialEvent.objects.filter(rma=rma).exists():
                    continue
                counts['rma'] += 1
                if dry_run:
                    continue
                label = f'RMA {rma.rma_number}' if rma.rma_number else f'RMA #{rma.pk}'
                common = dict(asset=rma.asset, rma=rma, purchase_order=rma.purchase_order)
                serial_lifecycle.record(rma.organization, serial, 'rma_opened', when=rma.opened_at,
                                        notes=f'{label}: {rma.reason}'.strip(': '), **common)
                if rma.status != 'open':
                    when = {'sent': rma.sent_at, 'received_by_vendor': rma.received_at}.get(
                        rma.status, rma.closed_at) or rma.updated_at
                    if when < rma.opened_at:
                        when = rma.opened_at  # never before the "opened" event
                    serial_lifecycle.record(rma.organization, serial, f'rma_{rma.status}', when=when,
                                            notes=label, **common)
                    if rma.status == 'replaced' and rma.replacement_serial:
                        serial_lifecycle.record(rma.organization, rma.replacement_serial,
                                                'replacement_received', rma=rma, when=when,
                                                purchase_order=rma.purchase_order,
                                                notes=f'{label}: replaces {serial}')
        verb = 'Would create' if dry_run else 'Created'
        self.stdout.write(f"{verb}: {counts['received']} received, {counts['assigned']} assigned, "
                          f"{counts['rma']} RMA histories.")
