"""
Debug command to check organization import from RMM
Helps diagnose why devices aren't being assigned to correct organizations
"""
from django.core.management.base import BaseCommand
from integrations.models import RMMConnection, RMMDevice
from integrations.providers.rmm import get_rmm_provider
import json


class Command(BaseCommand):
    help = 'Debug RMM organization import - shows device data and org assignment logic'

    def add_arguments(self, parser):
        parser.add_argument(
            '--connection-id',
            type=int,
            required=True,
            help='RMM connection ID to debug'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=5,
            help='Number of devices to check (default: 5)'
        )

    def handle(self, *args, **options):
        connection_id = options['connection_id']
        limit = options['limit']

        try:
            connection = RMMConnection.objects.get(id=connection_id)
        except RMMConnection.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Connection {connection_id} not found'))
            return

        self.stdout.write(self.style.SUCCESS(f'=== RMM Organization Import Debug ==='))
        self.stdout.write(f'Connection: {connection.name} ({connection.get_provider_type_display()})')
        self.stdout.write(f'Parent Organization: {connection.organization.name}')
        self.stdout.write(f'Import Organizations Enabled: {connection.import_organizations}')
        self.stdout.write(f'Organization Prefix: "{connection.org_name_prefix}"')
        self.stdout.write('')

        # Get provider
        try:
            provider = get_rmm_provider(connection)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to initialize provider: {e}'))
            return

        # Test connection
        self.stdout.write('Testing connection...')
        if not provider.test_connection():
            self.stdout.write(self.style.ERROR('Connection test failed'))
            return
        self.stdout.write(self.style.SUCCESS('✓ Connection successful'))
        self.stdout.write('')

        # Get devices
        self.stdout.write(f'Fetching up to {limit} devices...')
        try:
            devices = provider.list_devices()
            devices = list(devices)[:limit]
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to fetch devices: {e}'))
            return

        if not devices:
            self.stdout.write(self.style.WARNING('No devices found'))
            return

        self.stdout.write(self.style.SUCCESS(f'✓ Found {len(devices)} devices'))
        self.stdout.write('')

        # Analyze each device
        for i, device_data in enumerate(devices, 1):
            self.stdout.write(f'--- Device {i}: {device_data.get("device_name", "Unknown")} ---')

            # Show relevant fields
            device_name = device_data.get('device_name', 'N/A')
            external_id = device_data.get('external_id', 'N/A')

            self.stdout.write(f'  Device Name: {device_name}')
            self.stdout.write(f'  External ID: {external_id}')

            # Check for organization/client data
            client_id = device_data.get('client_id', '') or device_data.get('organization_id', '')
            client_name = device_data.get('client_name', '') or device_data.get('organization_name', '')
            site_id = device_data.get('site_id', '') or device_data.get('location_id', '')
            site_name = device_data.get('site_name', '') or device_data.get('location_name', '')

            self.stdout.write(f'  Client ID: {client_id if client_id else "(not provided)"}')
            self.stdout.write(f'  Client Name: {client_name if client_name else "(not provided)"}')
            self.stdout.write(f'  Site ID: {site_id if site_id else "(not provided)"}')
            self.stdout.write(f'  Site Name: {site_name if site_name else "(not provided)"}')

            # Determine what would happen
            if not connection.import_organizations:
                result = f'Would use connection org: {connection.organization.name}'
                self.stdout.write(self.style.WARNING(f'  → {result}'))
            elif not (client_id or site_id) or not (client_name or site_name):
                result = f'No client/site data - would fallback to connection org: {connection.organization.name}'
                self.stdout.write(self.style.WARNING(f'  → {result}'))
            else:
                org_name = client_name if client_name else site_name
                if connection.org_name_prefix:
                    org_name = f"{connection.org_name_prefix}{org_name}"
                result = f'Would import/use org: {org_name}'
                self.stdout.write(self.style.SUCCESS(f'  → {result}'))

            # Check current assignment in database
            try:
                db_device = RMMDevice.objects.get(connection=connection, external_id=external_id)
                self.stdout.write(f'  Current DB Org: {db_device.organization.name}')
            except RMMDevice.DoesNotExist:
                self.stdout.write(f'  Current DB Org: (not yet synced)')

            self.stdout.write('')

        # Summary and recommendations
        self.stdout.write(self.style.SUCCESS('=== Summary & Recommendations ==='))

        has_client_data = any(
            device_data.get('client_id') or device_data.get('client_name') or
            device_data.get('site_id') or device_data.get('site_name')
            for device_data in devices
        )

        if not connection.import_organizations:
            self.stdout.write(self.style.WARNING(
                '⚠ Import Organizations is DISABLED\n'
                '  All devices will use connection organization: ' + connection.organization.name + '\n'
                '  Enable it in: Integrations → Edit Connection → Enable "Import Organizations"'
            ))
        elif not has_client_data:
            self.stdout.write(self.style.WARNING(
                '⚠ Devices have NO client/site data\n'
                '  Your RMM provider is not returning organization/site information.\n'
                '  Possible causes:\n'
                '  - Devices not assigned to clients/sites in RMM UI\n'
                '  - Provider doesn\'t support multi-tenant data\n'
                '  - API permissions too restrictive'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                '✓ Devices have client/site data and would be properly distributed!\n'
                '  If existing devices are in wrong org, you need to:\n'
                '  1. Delete devices in Client St0r (or use --force flag)\n'
                '  2. Run sync again to reassign them to correct orgs'
            ))
