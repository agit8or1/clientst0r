"""
Alias command for seed_vendor_data.
Seeds equipment catalog (vendors, categories, and 3000+ equipment models).
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Seed equipment catalog (alias for seed_vendor_data)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Delete existing equipment data before seeding',
        )

    def handle(self, *args, **options):
        # Call the actual seeding command
        call_command('seed_vendor_data', clear=options['delete'])
