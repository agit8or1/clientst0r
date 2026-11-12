"""
Management command to debug RMM organization import.
Shows what site/client data is being returned by the RMM provider.
"""
from django.core.management.base import BaseCommand
from integrations.models import RMMConnection
from integrations.providers.rmm import get_rmm_provider
import json


class Command(BaseCommand):
    help = 'Debug RMM organization import - shows site/client data from devices'

    def add_arguments(self, parser):
        parser.add_argument(
            'connection_id',
            type=int,
            help='RMM Connection ID to debug'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Number of devices to check (default: 10)'
        )
        parser.add_argument(
            '--show-raw',
            action='store_true',
            help='Show raw API data for debugging'
        )

    def handle(self, *args, **options):
        connection_id = options['connection_id']
        limit = options['limit']
        show_raw = options.get('show_raw', False)

        try:
            connection = RMMConnection.objects.get(pk=connection_id)
        except RMMConnection.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'RMM Connection {connection_id} not found'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nDebugging RMM Connection: {connection}'))
        self.stdout.write(f'Provider: {connection.get_provider_type_display()}')
        self.stdout.write(f'Organization Import Enabled: {connection.import_organizations}')
        self.stdout.write(f'Organization Name Prefix: "{connection.org_name_prefix}"')
        self.stdout.write(f'Import as Active: {connection.org_import_as_active}\n')

        # Get provider and fetch devices
        try:
            provider = get_rmm_provider(connection)
            self.stdout.write('Testing connection...')

            if not provider.test_connection():
                self.stdout.write(self.style.ERROR('Connection test failed!'))
                return

            self.stdout.write(self.style.SUCCESS('Connection test passed ✓\n'))

            # List devices
            self.stdout.write(f'Fetching first {limit} devices...\n')
            devices = provider.list_devices()[:limit]

            if not devices:
                self.stdout.write(self.style.WARNING('No devices returned!'))
                return

            self.stdout.write(self.style.SUCCESS(f'Found {len(devices)} devices\n'))
            self.stdout.write('=' * 80)

            # Analyze each device
            devices_with_site = 0
            devices_without_site = 0
            unique_orgs = {}

            for i, device in enumerate(devices, 1):
                device_name = device.get('device_name', 'Unknown')
                site_id = device.get('site_id', '')
                site_name = device.get('site_name', '')
                client_id = device.get('client_id', '')
                client_name = device.get('client_name', '')

                self.stdout.write(f'\nDevice {i}: {device_name}')
                self.stdout.write('-' * 80)

                # Show raw API data if requested
                if show_raw:
                    raw_data = device.get('raw_data', {})
                    self.stdout.write(self.style.WARNING('\n  RAW API DATA:'))
                    import json
                    # Show relevant fields from raw data
                    relevant_fields = {
                        'agent_id': raw_data.get('agent_id'),
                        'hostname': raw_data.get('hostname'),
                        'site': raw_data.get('site'),
                        'site_name': raw_data.get('site_name'),
                        'client': raw_data.get('client'),
                        'client_name': raw_data.get('client_name'),
                    }
                    self.stdout.write(f'  {json.dumps(relevant_fields, indent=4)}')
                    self.stdout.write('')

                # Check for site/client data
                has_site_data = bool(site_id or client_id)

                if has_site_data:
                    devices_with_site += 1

                    if site_id and site_name:
                        self.stdout.write(self.style.SUCCESS(f'  ✓ Site ID: {site_id}'))
                        self.stdout.write(self.style.SUCCESS(f'  ✓ Site Name: {site_name}'))
                        org_key = f'site:{site_id}'
                        unique_orgs[org_key] = site_name
                    else:
                        self.stdout.write(self.style.WARNING(f'  ⚠ Site ID: {site_id or "(empty)"}'))
                        self.stdout.write(self.style.WARNING(f'  ⚠ Site Name: {site_name or "(empty)"}'))

                    if client_id and client_name:
                        self.stdout.write(self.style.SUCCESS(f'  ✓ Client ID: {client_id}'))
                        self.stdout.write(self.style.SUCCESS(f'  ✓ Client Name: {client_name}'))
                        org_key = f'client:{client_id}'
                        unique_orgs[org_key] = client_name
                    else:
                        self.stdout.write(self.style.WARNING(f'  ⚠ Client ID: {client_id or "(empty)"}'))
                        self.stdout.write(self.style.WARNING(f'  ⚠ Client Name: {client_name or "(empty)"}'))

                else:
                    devices_without_site += 1
                    self.stdout.write(self.style.ERROR('  ✗ No site/client data'))
                    self.stdout.write(self.style.ERROR('    Site ID: (empty)'))
                    self.stdout.write(self.style.ERROR('    Site Name: (empty)'))
                    self.stdout.write(self.style.ERROR('    Client ID: (empty)'))
                    self.stdout.write(self.style.ERROR('    Client Name: (empty)'))

                # Show what organization would be used
                if connection.import_organizations:
                    if site_id and site_name:
                        org_name = f"{connection.org_name_prefix}{site_name}" if connection.org_name_prefix else site_name
                        self.stdout.write(f'  → Would create/update organization: "{org_name}"')
                    elif client_id and client_name:
                        org_name = f"{connection.org_name_prefix}{client_name}" if connection.org_name_prefix else client_name
                        self.stdout.write(f'  → Would create/update organization: "{org_name}"')
                    else:
                        self.stdout.write(self.style.WARNING(f'  → Would use connection org: {connection.owner_label}'))
                else:
                    self.stdout.write(self.style.WARNING(f'  → Organization import disabled, would use: {connection.owner_label}'))

            # Summary
            self.stdout.write('\n' + '=' * 80)
            self.stdout.write(self.style.SUCCESS(f'\nSUMMARY'))
            self.stdout.write('=' * 80)
            self.stdout.write(f'Total devices checked: {len(devices)}')
            self.stdout.write(self.style.SUCCESS(f'Devices WITH site/client data: {devices_with_site}'))
            self.stdout.write(self.style.ERROR(f'Devices WITHOUT site/client data: {devices_without_site}'))

            if unique_orgs:
                self.stdout.write(f'\nUnique organizations that would be created: {len(unique_orgs)}')
                for org_key, org_name in unique_orgs.items():
                    org_type = org_key.split(':')[0]
                    final_name = f"{connection.org_name_prefix}{org_name}" if connection.org_name_prefix else org_name
                    self.stdout.write(f'  • {final_name} ({org_type})')
            else:
                self.stdout.write(self.style.WARNING('\nNo organizations would be created!'))

            # Recommendations
            self.stdout.write('\n' + '=' * 80)
            self.stdout.write('RECOMMENDATIONS')
            self.stdout.write('=' * 80)

            if devices_without_site == len(devices):
                self.stdout.write(self.style.ERROR('⚠ NO devices have site/client data!'))
                self.stdout.write('\nPossible causes:')
                self.stdout.write('1. RMM provider API doesn\'t return site/client fields')
                self.stdout.write('2. Devices don\'t have site/client assignments in RMM')
                self.stdout.write('3. Field names don\'t match what provider expects')
                self.stdout.write('4. API endpoint needs different parameters')
                self.stdout.write('\nNext steps:')
                self.stdout.write('• Check RMM console - do devices have site/client assignments?')
                self.stdout.write('• Run with --show-raw to see actual API response:')
                self.stdout.write(f'  python manage.py debug_rmm_sync {connection_id} --show-raw --limit 3')
                self.stdout.write('• Check API documentation for this RMM provider')
                self.stdout.write(f'• Share output with support (including --show-raw output)')
            elif devices_without_site > 0:
                self.stdout.write(self.style.WARNING(f'⚠ {devices_without_site}/{len(devices)} devices missing site/client data'))
                self.stdout.write('\nThese devices will use the connection\'s organization:')
                self.stdout.write(f'  • {connection.owner_label}')
            else:
                self.stdout.write(self.style.SUCCESS('✓ All devices have site/client data!'))
                if connection.import_organizations:
                    self.stdout.write(f'\nOrganizations will be created/updated during sync.')
                else:
                    self.stdout.write(self.style.WARNING('\n⚠ Organization import is DISABLED'))
                    self.stdout.write('Enable it in RMM connection settings to create organizations.')

            self.stdout.write('\n')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
