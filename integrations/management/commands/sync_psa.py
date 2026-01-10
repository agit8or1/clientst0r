"""
Management command to run PSA sync for all active connections
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from integrations.models import PSAConnection
from integrations.sync import PSASync
import logging

logger = logging.getLogger('integrations')


class Command(BaseCommand):
    help = 'Sync PSA data for all active connections'

    def add_arguments(self, parser):
        parser.add_argument(
            '--connection-id',
            type=int,
            help='Sync specific connection by ID'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force sync even if recently synced'
        )

    def handle(self, *args, **options):
        connection_id = options.get('connection_id')
        force = options.get('force', False)

        if connection_id:
            # Sync specific connection
            try:
                connection = PSAConnection.objects.get(id=connection_id)
                self.sync_connection(connection, force)
            except PSAConnection.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Connection {connection_id} not found'))
                return
        else:
            # Sync all active connections
            connections = PSAConnection.objects.filter(
                is_active=True,
                sync_enabled=True
            )

            if not connections.exists():
                self.stdout.write(self.style.WARNING('No active connections found'))
                return

            for connection in connections:
                self.sync_connection(connection, force)

    def sync_connection(self, connection, force=False):
        """Sync a single connection."""
        self.stdout.write(f'Processing: {connection.name} ({connection.get_provider_type_display()})')

        # Check if sync is needed
        if not force and connection.last_sync_at:
            next_sync = connection.last_sync_at + timedelta(minutes=connection.sync_interval_minutes)
            if timezone.now() < next_sync:
                self.stdout.write(f'  Skipping: next sync at {next_sync}')
                return

        try:
            syncer = PSASync(connection)
            stats = syncer.sync_all()

            self.stdout.write(self.style.SUCCESS(f'  Success: {stats}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Error: {e}'))
            logger.exception(f'Sync failed for {connection}')
