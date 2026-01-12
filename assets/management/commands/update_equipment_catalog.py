"""
Management command to update equipment catalog with new hardware releases.

This command supports multiple data sources:
1. Manual JSON file import
2. Vendor API integrations (future)
3. Web scraping vendor product pages (future)
4. RSS feed monitoring (future)

Usage:
    python manage.py update_equipment_catalog                    # Check all sources
    python manage.py update_equipment_catalog --source json     # Import from JSON
    python manage.py update_equipment_catalog --vendor dell     # Update specific vendor
    python manage.py update_equipment_catalog --dry-run         # Preview changes
"""
import json
import logging
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.utils import timezone
from django.conf import settings
from assets.models import Vendor, EquipmentModel
from audit.models import AuditLog
from pathlib import Path

logger = logging.getLogger('assets')


class Command(BaseCommand):
    help = 'Update equipment catalog with new hardware releases'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            choices=['json', 'api', 'rss', 'web'],
            help='Data source to use for updates'
        )
        parser.add_argument(
            '--vendor',
            type=str,
            help='Update specific vendor only'
        )
        parser.add_argument(
            '--file',
            type=str,
            help='Path to JSON file for manual import'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving'
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.stats = {
            'vendors_created': 0,
            'vendors_updated': 0,
            'equipment_created': 0,
            'equipment_updated': 0,
            'equipment_skipped': 0,
        }

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("Equipment Catalog Update"))
        self.stdout.write("=" * 80)

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be saved"))

        # Determine update source
        source = options.get('source')
        vendor_filter = options.get('vendor')
        json_file = options.get('file')

        try:
            if source == 'json' or json_file:
                self.update_from_json(json_file, vendor_filter)
            elif source == 'api':
                self.update_from_vendor_apis(vendor_filter)
            elif source == 'rss':
                self.update_from_rss_feeds(vendor_filter)
            elif source == 'web':
                self.update_from_web_scraping(vendor_filter)
            else:
                # Default: Try all available sources
                self.stdout.write("\nChecking all available data sources...")
                self.update_from_json(None, vendor_filter)

            # Print summary
            self.print_summary()

            # Create audit log (if not dry run)
            if not self.dry_run:
                AuditLog.objects.create(
                    action='sync',
                    object_type='equipment_catalog',
                    description=f'Equipment catalog updated: {self.stats["equipment_created"]} created, '
                               f'{self.stats["equipment_updated"]} updated, '
                               f'{self.stats["vendors_created"]} new vendors'
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Update failed: {e}"))
            logger.error(f"Equipment catalog update failed: {e}", exc_info=True)
            raise

    def update_from_json(self, json_file=None, vendor_filter=None):
        """Import equipment data from JSON file."""
        self.stdout.write("\n" + "─" * 80)
        self.stdout.write("📄 Updating from JSON file...")
        self.stdout.write("─" * 80)

        # Determine JSON file path
        if json_file:
            file_path = Path(json_file)
        else:
            # Check default location
            default_path = Path(settings.BASE_DIR) / 'data' / 'equipment_updates.json'
            if not default_path.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"  No JSON file found at {default_path}\n"
                        f"  Use --file to specify custom path"
                    )
                )
                return
            file_path = default_path

        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"  ✗ File not found: {file_path}"))
            return

        # Load JSON data
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f"  ✗ Invalid JSON: {e}"))
            return

        # Process each vendor
        vendors_data = data.get('vendors', [])
        for vendor_data in vendors_data:
            vendor_name = vendor_data.get('name')

            # Apply vendor filter
            if vendor_filter and vendor_name.lower() != vendor_filter.lower():
                continue

            self.process_vendor(vendor_data)

    def update_from_vendor_apis(self, vendor_filter=None):
        """Update from vendor APIs (Dell, HP, Cisco APIs)."""
        self.stdout.write("\n" + "─" * 80)
        self.stdout.write("🔌 Updating from Vendor APIs...")
        self.stdout.write("─" * 80)
        self.stdout.write(self.style.WARNING("  ⚠ Vendor API integration not yet implemented"))
        self.stdout.write("  Future support planned for:")
        self.stdout.write("    - Dell TechDirect API")
        self.stdout.write("    - HP API")
        self.stdout.write("    - Cisco Support API")
        self.stdout.write("    - Ubiquiti API")

    def update_from_rss_feeds(self, vendor_filter=None):
        """Monitor vendor RSS feeds for new product announcements."""
        self.stdout.write("\n" + "─" * 80)
        self.stdout.write("📡 Updating from RSS Feeds...")
        self.stdout.write("─" * 80)
        self.stdout.write(self.style.WARNING("  ⚠ RSS feed monitoring not yet implemented"))
        self.stdout.write("  Future support planned for:")
        self.stdout.write("    - Vendor press release feeds")
        self.stdout.write("    - Product launch announcements")
        self.stdout.write("    - EOL/EOS notifications")

    def update_from_web_scraping(self, vendor_filter=None):
        """Scrape vendor product pages for new equipment."""
        self.stdout.write("\n" + "─" * 80)
        self.stdout.write("🕷️  Updating from Web Scraping...")
        self.stdout.write("─" * 80)
        self.stdout.write(self.style.WARNING("  ⚠ Web scraping not yet implemented"))
        self.stdout.write("  Future support planned for:")
        self.stdout.write("    - Vendor product catalog pages")
        self.stdout.write("    - Spec sheet extraction")
        self.stdout.write("    - Price monitoring")

    def process_vendor(self, vendor_data):
        """Process a single vendor and its equipment."""
        vendor_name = vendor_data.get('name')
        self.stdout.write(f"\n  Processing vendor: {vendor_name}")

        # Get or create vendor
        vendor, created = Vendor.objects.get_or_create(
            name=vendor_name,
            defaults={
                'slug': slugify(vendor_name),
                'website': vendor_data.get('website', ''),
                'support_url': vendor_data.get('support_url', ''),
                'support_phone': vendor_data.get('support_phone', ''),
                'description': vendor_data.get('description', ''),
                'is_active': vendor_data.get('is_active', True),
                'custom_fields': vendor_data.get('custom_fields', {}),
            }
        )

        if created:
            self.stats['vendors_created'] += 1
            if not self.dry_run:
                self.stdout.write(
                    self.style.SUCCESS(f"    ✓ Created vendor: {vendor_name}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"    [DRY RUN] Would create vendor: {vendor_name}")
                )
        else:
            # Update existing vendor if data changed
            updated = False
            for field in ['website', 'support_url', 'support_phone', 'description']:
                new_value = vendor_data.get(field, '')
                if new_value and getattr(vendor, field) != new_value:
                    if not self.dry_run:
                        setattr(vendor, field, new_value)
                    updated = True

            if updated:
                if not self.dry_run:
                    vendor.save()
                self.stats['vendors_updated'] += 1
                self.stdout.write(f"    ↻ Updated vendor: {vendor_name}")

        # Process equipment models
        equipment_list = vendor_data.get('equipment', [])
        for equipment_data in equipment_list:
            self.process_equipment(vendor, equipment_data)

    def process_equipment(self, vendor, equipment_data):
        """Process a single equipment model."""
        model_name = equipment_data.get('model_name')

        # Check if equipment already exists
        existing = EquipmentModel.objects.filter(
            vendor=vendor,
            model_name=model_name
        ).first()

        if existing:
            # Check if specifications have changed
            new_specs = equipment_data.get('specifications', {})
            if new_specs and new_specs != existing.specifications:
                if not self.dry_run:
                    # Update specifications and other fields
                    for field in ['model_number', 'description', 'specifications',
                                  'datasheet_url', 'documentation_url', 'release_date',
                                  'eol_date', 'eos_date']:
                        new_value = equipment_data.get(field)
                        if new_value:
                            if field in ['release_date', 'eol_date', 'eos_date']:
                                # Handle date fields
                                from django.utils.dateparse import parse_date
                                new_value = parse_date(new_value) if isinstance(new_value, str) else new_value
                            setattr(existing, field, new_value)
                    existing.save()

                self.stats['equipment_updated'] += 1
                self.stdout.write(f"      ↻ Updated: {model_name}")
            else:
                self.stats['equipment_skipped'] += 1
                # Don't log skipped items to reduce noise
        else:
            # Create new equipment
            if not self.dry_run:
                equipment = EquipmentModel.objects.create(
                    vendor=vendor,
                    model_name=model_name,
                    model_number=equipment_data.get('model_number', ''),
                    slug=slugify(f"{vendor.name}-{model_name}"),
                    equipment_type=equipment_data.get('equipment_type', 'other'),
                    description=equipment_data.get('description', ''),
                    is_rackmount=equipment_data.get('is_rackmount', False),
                    rack_units=equipment_data.get('rack_units'),
                    specifications=equipment_data.get('specifications', {}),
                    datasheet_url=equipment_data.get('datasheet_url', ''),
                    documentation_url=equipment_data.get('documentation_url', ''),
                    release_date=self.parse_date(equipment_data.get('release_date')),
                    eol_date=self.parse_date(equipment_data.get('eol_date')),
                    eos_date=self.parse_date(equipment_data.get('eos_date')),
                    is_active=equipment_data.get('is_active', True),
                    custom_fields=equipment_data.get('custom_fields', {}),
                )

            self.stats['equipment_created'] += 1
            if not self.dry_run:
                self.stdout.write(
                    self.style.SUCCESS(f"      ✓ Created: {model_name}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"      [DRY RUN] Would create: {model_name}")
                )

    def parse_date(self, date_value):
        """Parse date string to date object."""
        if not date_value:
            return None
        if isinstance(date_value, str):
            from django.utils.dateparse import parse_date
            return parse_date(date_value)
        return date_value

    def print_summary(self):
        """Print update summary."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("Update Summary"))
        self.stdout.write("=" * 80)

        if self.dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN - No changes were saved)\n"))

        self.stdout.write(f"  Vendors Created:        {self.stats['vendors_created']}")
        self.stdout.write(f"  Vendors Updated:        {self.stats['vendors_updated']}")
        self.stdout.write(f"  Equipment Created:      {self.stats['equipment_created']}")
        self.stdout.write(f"  Equipment Updated:      {self.stats['equipment_updated']}")
        self.stdout.write(f"  Equipment Unchanged:    {self.stats['equipment_skipped']}")

        total_changes = (
            self.stats['vendors_created'] +
            self.stats['vendors_updated'] +
            self.stats['equipment_created'] +
            self.stats['equipment_updated']
        )

        if total_changes > 0:
            self.stdout.write("\n" + self.style.SUCCESS(f"✓ Total changes: {total_changes}"))
        else:
            self.stdout.write("\n" + self.style.WARNING("  No changes needed - catalog is up to date"))

        self.stdout.write("=" * 80 + "\n")
