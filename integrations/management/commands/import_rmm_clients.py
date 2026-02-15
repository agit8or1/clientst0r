"""
Management command to import RMM clients as organizations.

Usage:
    python manage.py import_rmm_clients <connection_id> [--dry-run]

This command fetches all unique clients from an RMM system (e.g., Tactical RMM)
and creates corresponding organizations in Client St0r.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from integrations.models import RMMConnection
from core.models import Organization
import logging

logger = logging.getLogger('integrations')


class Command(BaseCommand):
    help = 'Import RMM clients as organizations'

    def add_arguments(self, parser):
        parser.add_argument(
            'connection_id',
            type=int,
            help='RMM connection ID to import clients from'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually creating organizations'
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip clients that already have matching organizations (by name)'
        )

    def handle(self, *args, **options):
        connection_id = options['connection_id']
        dry_run = options['dry_run']
        skip_existing = options['skip_existing']

        # Get RMM connection
        try:
            connection = RMMConnection.objects.get(pk=connection_id)
        except RMMConnection.DoesNotExist:
            raise CommandError(f'RMM connection {connection_id} does not exist')

        self.stdout.write(
            self.style.SUCCESS(
                f'\n📡 Importing clients from: {connection.name} ({connection.provider_type})\n'
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('🔍 DRY RUN MODE - No organizations will be created\n')
            )

        # Get provider
        try:
            provider = connection.get_provider()
        except Exception as e:
            raise CommandError(f'Failed to get RMM provider: {e}')

        # Test connection first
        self.stdout.write('Testing RMM connection...')
        if not provider.test_connection():
            raise CommandError('❌ RMM connection test failed. Check your API credentials.')
        self.stdout.write(self.style.SUCCESS('✅ Connection successful\n'))

        # Fetch all devices to extract unique clients
        self.stdout.write('Fetching devices from RMM...')
        try:
            devices = provider.list_devices()
        except Exception as e:
            raise CommandError(f'Failed to fetch devices: {e}')

        self.stdout.write(self.style.SUCCESS(f'✅ Retrieved {len(devices)} devices\n'))

        # Extract unique clients
        clients = {}  # {client_id: client_name}
        for device in devices:
            client_id = device.get('client_id')
            client_name = device.get('client_name')

            if client_id and client_name:
                clients[client_id] = client_name

        if not clients:
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  No clients found in RMM devices.\n'
                    'This may be normal if your RMM system doesn\'t organize devices by client.'
                )
            )
            return

        self.stdout.write(f'📋 Found {len(clients)} unique client(s):\n')

        # Show what will be imported
        created_count = 0
        skipped_count = 0
        error_count = 0

        for client_id, client_name in sorted(clients.items(), key=lambda x: x[1]):
            # Check if organization already exists
            existing = Organization.objects.filter(name=client_name).first()

            if existing:
                if skip_existing:
                    self.stdout.write(
                        f'  ⏭️  {client_name} (client_id: {client_id}) - Already exists, skipping'
                    )
                    skipped_count += 1
                    continue
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'  ⚠️  {client_name} (client_id: {client_id}) - Already exists'
                        )
                    )
                    skipped_count += 1
                    continue

            # Create organization
            if not dry_run:
                try:
                    with transaction.atomic():
                        org = Organization.objects.create(
                            name=client_name,
                            is_active=True,
                            description=f'Imported from {connection.name} (RMM Client ID: {client_id})'
                        )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✅ {client_name} (client_id: {client_id}) - Created (ID: {org.id})'
                            )
                        )
                        created_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ❌ {client_name} (client_id: {client_id}) - Error: {e}'
                        )
                    )
                    error_count += 1
            else:
                self.stdout.write(
                    f'  🔍 {client_name} (client_id: {client_id}) - Would be created'
                )
                created_count += 1

        # Summary
        self.stdout.write('\n' + '=' * 60)
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ DRY RUN COMPLETE\n\n'
                    f'  Would create: {created_count} organization(s)\n'
                    f'  Would skip: {skipped_count} organization(s)\n'
                    f'  Total clients: {len(clients)}\n\n'
                    f'Run without --dry-run to actually create organizations.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ IMPORT COMPLETE\n\n'
                    f'  Created: {created_count} organization(s)\n'
                    f'  Skipped: {skipped_count} organization(s)\n'
                    f'  Errors: {error_count}\n'
                    f'  Total clients: {len(clients)}\n'
                )
            )

        # Next steps
        if created_count > 0 and not dry_run:
            self.stdout.write(
                '\n📝 Next Steps:\n'
                f'  1. Review the created organizations in Settings → Organizations\n'
                f'  2. Assign users to organizations via Settings → Organization Memberships\n'
                f'  3. Run RMM sync to populate devices for each organization\n'
            )
