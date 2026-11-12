"""
Management command to debug PSA organization import.
Shows what company data is being returned by the PSA provider.
"""
from django.core.management.base import BaseCommand
from integrations.models import PSAConnection
from integrations.providers import get_provider
import json


class Command(BaseCommand):
    help = 'Debug PSA organization import - shows company data from PSA'

    def add_arguments(self, parser):
        parser.add_argument(
            'connection_id',
            type=int,
            help='PSA Connection ID to debug'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=10,
            help='Number of companies to check (default: 10)'
        )

    def handle(self, *args, **options):
        connection_id = options['connection_id']
        limit = options['limit']

        try:
            connection = PSAConnection.objects.get(pk=connection_id)
        except PSAConnection.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'PSA Connection {connection_id} not found'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nDebugging PSA Connection: {connection}'))
        self.stdout.write(f'Provider: {connection.get_provider_type_display()}')
        self.stdout.write(f'Organization Import Enabled: {connection.import_organizations}')
        self.stdout.write(f'Organization Name Prefix: "{connection.org_name_prefix}"')
        self.stdout.write(f'Import as Active: {connection.org_import_as_active}')
        self.stdout.write(f'Sync Companies Enabled: {connection.sync_companies}\n')

        if not connection.sync_companies:
            self.stdout.write(self.style.ERROR('⚠ Company sync is DISABLED!'))
            self.stdout.write('Enable it in PSA connection settings to sync companies.\n')
            return

        # Get provider and fetch companies
        try:
            provider = get_provider(connection)
            self.stdout.write('Testing connection...')

            if not provider.test_connection():
                self.stdout.write(self.style.ERROR('Connection test failed!'))
                return

            self.stdout.write(self.style.SUCCESS('Connection test passed ✓\n'))

            # List companies
            self.stdout.write(f'Fetching first {limit} companies...\n')
            companies = provider.list_companies()[:limit]

            if not companies:
                self.stdout.write(self.style.WARNING('No companies returned!'))
                return

            self.stdout.write(self.style.SUCCESS(f'Found {len(companies)} companies\n'))
            self.stdout.write('=' * 80)

            # Analyze each company
            companies_with_data = 0
            companies_without_data = 0
            unique_orgs = {}

            for i, company in enumerate(companies, 1):
                company_name = company.get('name', 'Unknown')
                external_id = company.get('external_id', '')

                self.stdout.write(f'\nCompany {i}: {company_name}')
                self.stdout.write('-' * 80)

                # Check for required data
                has_required_data = bool(external_id and company_name)

                if has_required_data:
                    companies_with_data += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✓ External ID: {external_id}'))
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Name: {company_name}'))

                    # Show optional fields
                    if company.get('phone'):
                        self.stdout.write(f'  • Phone: {company.get("phone")}')
                    if company.get('address'):
                        self.stdout.write(f'  • Address: {company.get("address")}')
                    if company.get('website'):
                        self.stdout.write(f'  • Website: {company.get("website")}')

                    unique_orgs[external_id] = company_name
                else:
                    companies_without_data += 1
                    self.stdout.write(self.style.ERROR('  ✗ Missing required data'))
                    self.stdout.write(self.style.ERROR(f'    External ID: {external_id or "(empty)"}'))
                    self.stdout.write(self.style.ERROR(f'    Name: {company_name or "(empty)"}'))

                # Show what organization would be used
                if connection.import_organizations:
                    if has_required_data:
                        org_name = f"{connection.org_name_prefix}{company_name}" if connection.org_name_prefix else company_name
                        self.stdout.write(f'  → Would create/update organization: "{org_name}"')
                    else:
                        self.stdout.write(self.style.WARNING(f'  → Would use connection org: {connection.owner_label}'))
                else:
                    self.stdout.write(self.style.WARNING(f'  → Organization import disabled, would use: {connection.owner_label}'))

            # Summary
            self.stdout.write('\n' + '=' * 80)
            self.stdout.write(self.style.SUCCESS(f'\nSUMMARY'))
            self.stdout.write('=' * 80)
            self.stdout.write(f'Total companies checked: {len(companies)}')
            self.stdout.write(self.style.SUCCESS(f'Companies WITH required data: {companies_with_data}'))
            self.stdout.write(self.style.ERROR(f'Companies WITHOUT required data: {companies_without_data}'))

            if unique_orgs and connection.import_organizations:
                self.stdout.write(f'\nUnique organizations that would be created: {len(unique_orgs)}')
                for external_id, company_name in list(unique_orgs.items())[:10]:
                    final_name = f"{connection.org_name_prefix}{company_name}" if connection.org_name_prefix else company_name
                    self.stdout.write(f'  • {final_name}')
                if len(unique_orgs) > 10:
                    self.stdout.write(f'  ... and {len(unique_orgs) - 10} more')
            elif unique_orgs and not connection.import_organizations:
                self.stdout.write(self.style.WARNING('\n⚠ Organization import is DISABLED'))
                self.stdout.write(f'All {len(unique_orgs)} companies would use: {connection.owner_label}')
            else:
                self.stdout.write(self.style.WARNING('\nNo organizations would be created!'))

            # Recommendations
            self.stdout.write('\n' + '=' * 80)
            self.stdout.write('RECOMMENDATIONS')
            self.stdout.write('=' * 80)

            if not connection.import_organizations:
                self.stdout.write(self.style.ERROR('⚠ ORGANIZATION IMPORT IS DISABLED!'))
                self.stdout.write('\nTo enable PSA organization import:')
                self.stdout.write('1. Go to Integrations → PSA Connections')
                self.stdout.write(f'2. Edit connection: {connection}')
                self.stdout.write('3. Check "Import Organizations" checkbox')
                self.stdout.write('4. Optionally set "Organization Name Prefix"')
                self.stdout.write('5. Set "Import As Active" as needed')
                self.stdout.write('6. Save and re-run sync')
                self.stdout.write('')
                self.stdout.write('Without this enabled, all companies will use the connection\'s organization.')
            elif companies_without_data == len(companies):
                self.stdout.write(self.style.ERROR('⚠ NO companies have required data!'))
                self.stdout.write('\nPossible causes:')
                self.stdout.write('1. PSA provider API doesn\'t return company fields correctly')
                self.stdout.write('2. Companies don\'t have required information in PSA')
                self.stdout.write('3. Field mapping issue in provider code')
                self.stdout.write('\nNext steps:')
                self.stdout.write('• Check PSA system - do companies have names and IDs?')
                self.stdout.write('• Check API documentation for this PSA provider')
                self.stdout.write(f'• Contact support with this debug output')
            elif companies_without_data > 0:
                self.stdout.write(self.style.WARNING(f'⚠ {companies_without_data}/{len(companies)} companies missing required data'))
                self.stdout.write('\nThese companies will use the connection\'s organization:')
                self.stdout.write(f'  • {connection.owner_label}')
            else:
                self.stdout.write(self.style.SUCCESS('✓ All companies have required data!'))
                if connection.import_organizations:
                    self.stdout.write(f'\nOrganizations will be created/updated during sync.')
                    self.stdout.write('\nTo run full sync:')
                    self.stdout.write(f'  python manage.py sync_psa {connection.id}')
                else:
                    self.stdout.write(self.style.WARNING('\n⚠ Organization import is DISABLED'))
                    self.stdout.write('Enable it in PSA connection settings to create organizations.')

            self.stdout.write('\n')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
