"""
Check every RMM device's customer and asset link against the association
rules, and optionally fix them.

Dry run by default: each device is worked through inside its own transaction
and rolled back, so the counts are exactly what --apply would do. Safe to run
again: a second --apply finds nothing new. Works from synced data only; it
never calls the RMM, so run a sync first if the connection hasn't synced
since the upgrade.

Usage:
    manage.py rmm_reconcile                 # preview
    manage.py rmm_reconcile --apply         # make the changes
    manage.py rmm_reconcile --connection 3  # one connection
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from integrations.models import RMMAlert, RMMConnection, RMMDevice, RMMSoftware
from integrations.rmm_association import (
    apply_customer_decision, associate, reported_identity, resolve_customer,
)
from integrations.sync import acquire_sync_lock, release_sync_lock

LABELS = [
    ('valid_links', 'Valid asset links kept'),
    ('proposed_matches', 'Devices matched to an existing asset'),
    ('proposed_creates', 'Assets created for unmatched devices'),
    ('conflicts', 'Asset matches sent to review (duplicate, conflict or replacement)'),
    ('cross_customer_links', 'Links to another customer\'s asset (removed, or hidden until reviewed)'),
    ('unresolved_customers', 'Devices with no settled customer (hidden until reviewed)'),
    ('moved_customers', 'Devices moved to another customer upstream (hidden until reviewed)'),
    ('customer_changes', 'Devices whose customer changed'),
    ('rehomed_alerts', 'Cached alerts moved to their device\'s customer'),
    ('rehomed_software', 'Cached software rows moved to their device\'s customer'),
    ('awaiting_sync', 'Devices not synced since the upgrade (customer checked on next sync)'),
    ('unchanged', 'Devices with no asset action'),
]


class Command(BaseCommand):
    help = 'Preview or apply RMM customer and asset reconciliation.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Make the changes (default is a dry run).')
        parser.add_argument('--connection', type=int, default=None, help='Only this RMM connection ID.')

    def handle(self, *args, **opts):
        apply = opts['apply']
        connections = RMMConnection.objects.all().order_by('pk')
        if opts['connection']:
            connections = connections.filter(pk=opts['connection'])
            if not connections.exists():
                raise CommandError(f"No RMM connection with ID {opts['connection']}.")

        self.stdout.write(('APPLYING' if apply else 'DRY RUN — nothing is saved') + '\n')
        grand = Counter()
        for connection in connections:
            if not acquire_sync_lock(connection):
                self.stdout.write(self.style.WARNING(
                    f'{connection} [{connection.pk}]: a sync is running; skipped. Run again when it finishes.'))
                continue
            try:
                stats = self.reconcile(connection, apply)
            finally:
                release_sync_lock(connection)
            grand.update(stats)
            self.report(f'{connection} [{connection.pk}] ({connection.get_customer_scope_display()})', stats)
        if connections.count() > 1:
            self.report('All connections', grand)
        if not apply:
            self.stdout.write('\nRun again with --apply to make these changes.')

    def report(self, title, stats):
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{title}'))
        for key, label in LABELS:
            self.stdout.write(f'  {label}: {stats.get(key, 0)}')

    def reconcile(self, connection, apply):
        stats = Counter()
        for pk in RMMDevice.objects.filter(connection=connection).values_list('pk', flat=True):
            with transaction.atomic():
                self.reconcile_device(connection, pk, stats)
                if not apply:
                    transaction.set_rollback(True)
        return stats

    def reconcile_device(self, connection, pk, stats):
        device = (RMMDevice.objects.select_for_update().select_related('linked_asset', 'organization')
                  .get(pk=pk))
        previous_org = device.organization_id

        if connection.is_single_customer:
            if device.organization_id != connection.organization_id or not device.is_exposed:
                device.organization = connection.organization
                device.ownership_status = RMMDevice.OWNERSHIP_RESOLVED
                device.ownership_note = ''
                device.pending_organization = None
                device.save(update_fields=['organization', 'ownership_status', 'ownership_note',
                                           'pending_organization'])
        else:
            identity = reported_identity(device)
            if identity is None:
                stats['awaiting_sync'] += 1
                # The old sync put devices it couldn't place under the
                # connection owner. Without a reported customer there's no
                # telling, so hide them until a sync or a technician settles it.
                if (connection.organization_id is not None
                        and device.organization_id == connection.organization_id
                        and not device.confirmed_customer_key
                        and device.ownership_status == RMMDevice.OWNERSHIP_RESOLVED):
                    device.organization = None
                    device.ownership_status = RMMDevice.OWNERSHIP_UNRESOLVED
                    device.ownership_note = ('Synced before customer tracking and filed under the '
                                             'connection owner. Confirm its customer.')
                    device.save(update_fields=['organization', 'ownership_status', 'ownership_note'])
            else:
                decision = resolve_customer(connection, {'client_id': device.client_id,
                                                         'client_name': device.client_name}, device)
                apply_customer_decision(device, decision, identity)
                device.save(update_fields=['organization', 'ownership_status', 'ownership_note',
                                           'pending_organization', 'customer_key'])

        if device.organization_id != previous_org:
            stats['customer_changes'] += 1
        if device.ownership_status == RMMDevice.OWNERSHIP_UNRESOLVED:
            stats['unresolved_customers'] += 1
        elif device.ownership_status == RMMDevice.OWNERSHIP_MOVED:
            stats['moved_customers'] += 1

        stats['rehomed_alerts'] += (RMMAlert.objects.filter(device=device)
                                    .exclude(organization_id=device.organization_id)
                                    .update(organization=device.organization))
        stats['rehomed_software'] += (RMMSoftware.objects.filter(device=device)
                                      .exclude(organization_id=device.organization_id)
                                      .update(organization=device.organization))

        linked = device.linked_asset
        if linked is not None and linked.organization_id != device.organization_id:
            stats['cross_customer_links'] += 1

        if device.is_exposed and (connection.map_to_assets or device.linked_asset_id):
            outcome = associate(device, auto_create=connection.map_to_assets,
                                auto_match=connection.map_to_assets)
            key = {'keep': 'valid_links', 'match': 'proposed_matches', 'create': 'proposed_creates',
                   'review': 'conflicts'}.get(outcome, 'unchanged')
            stats[key] += 1
        else:
            stats['unchanged'] += 1
