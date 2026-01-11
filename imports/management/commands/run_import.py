"""
Management command to run data imports from IT Glue or Hudu
"""
from django.core.management.base import BaseCommand
from imports.models import ImportJob
from imports.services import get_import_service


class Command(BaseCommand):
    help = 'Run data import from IT Glue or Hudu'

    def add_arguments(self, parser):
        parser.add_argument(
            'job_id',
            type=int,
            help='Import job ID to run'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force run even if job already completed'
        )

    def handle(self, *args, **options):
        job_id = options['job_id']
        force = options.get('force', False)

        try:
            job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Import job {job_id} not found'))
            return

        # Check if already completed
        if job.status == 'completed' and not force:
            self.stdout.write(self.style.WARNING(f'Job {job_id} already completed. Use --force to re-run.'))
            return

        self.stdout.write(f'Starting import job {job_id}: {job.get_source_type_display()} -> {job.target_organization.name}')
        if job.dry_run:
            self.stdout.write(self.style.WARNING('  DRY RUN MODE - No data will be saved'))

        try:
            service = get_import_service(job)
            stats = service.run_import()

            self.stdout.write(self.style.SUCCESS('\nImport completed successfully!'))
            self.stdout.write(f'  Assets: {stats.get("assets", 0)}')
            self.stdout.write(f'  Passwords: {stats.get("passwords", 0)}')
            self.stdout.write(f'  Documents: {stats.get("documents", 0)}')
            self.stdout.write(f'  Contacts: {stats.get("contacts", 0)}')
            self.stdout.write(f'  Locations: {stats.get("locations", 0)}')
            self.stdout.write(f'  Networks: {stats.get("networks", 0)}')
            self.stdout.write(f'\nTotal imported: {job.items_imported}')
            self.stdout.write(f'Skipped: {job.items_skipped}')
            self.stdout.write(f'Failed: {job.items_failed}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nImport failed: {e}'))
            raise
