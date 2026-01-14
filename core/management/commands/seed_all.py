"""
Master seed command for new HuduGlue installations.

Seeds:
- Equipment catalog (3000+ models across Dell, HP, Lenovo, Cisco, etc.)
- Global KB articles (1000+ IT knowledge base articles)
- Sample data (optional)
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Seed all data for new installation (equipment catalog + KB articles)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--equipment',
            action='store_true',
            help='Seed equipment catalog only',
        )
        parser.add_argument(
            '--kb',
            action='store_true',
            help='Seed KB articles only',
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Delete existing data before seeding',
        )
        parser.add_argument(
            '--quick',
            action='store_true',
            help='Quick seed with limited data for testing',
        )
        parser.add_argument(
            '--from-github',
            action='store_true',
            help='Fetch KB articles from GitHub instead of generating locally',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('HuduGlue Data Seeding'))
        self.stdout.write(self.style.SUCCESS('=' * 70))

        seed_equipment = options['equipment'] or not options['kb']
        seed_kb = options['kb'] or not options['equipment']

        if seed_equipment:
            self.stdout.write('\\n' + self.style.WARNING('Seeding Equipment Catalog...'))
            self.stdout.write('-' * 70)
            try:
                call_command('seed_equipment_catalog', delete=options['delete'])
                self.stdout.write(self.style.SUCCESS('✓ Equipment catalog seeded'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ Equipment seeding failed: {e}'))

        if seed_kb:
            self.stdout.write('\\n' + self.style.WARNING('Seeding KB Articles...'))
            self.stdout.write('-' * 70)
            try:
                if options['from_github']:
                    # Fetch KB articles from GitHub
                    call_command('fetch_kb_from_github', delete=options['delete'])
                elif options['quick']:
                    call_command('seed_kb_articles', delete=options['delete'], limit=5)
                else:
                    call_command('seed_kb_articles', delete=options['delete'])
                self.stdout.write(self.style.SUCCESS('✓ KB articles seeded'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ KB seeding failed: {e}'))

        self.stdout.write('\\n' + self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('Seeding Complete!'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write('Next steps:')
        self.stdout.write('  • Navigate to Knowledge Base to see articles')
        self.stdout.write('  • Equipment catalog is available when creating assets')
        self.stdout.write('  • Users can delete items they don\\'t need')
        self.stdout.write('  • Asset filtering is available on Assets page')
        self.stdout.write('')
