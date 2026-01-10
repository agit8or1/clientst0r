"""
Management command to generate thumbnails for diagrams and templates.

Usage:
    python manage.py generate_diagram_thumbnails
    python manage.py generate_diagram_thumbnails --templates-only
    python manage.py generate_diagram_thumbnails --diagrams-only
"""

from django.core.management.base import BaseCommand
from docs.models import Diagram, Document
from docs.utils import generate_diagram_thumbnail


class Command(BaseCommand):
    help = 'Generate thumbnails for diagrams and document templates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--templates-only',
            action='store_true',
            help='Only generate thumbnails for document templates',
        )
        parser.add_argument(
            '--diagrams-only',
            action='store_true',
            help='Only generate thumbnails for diagrams',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate thumbnails even if they already exist',
        )

    def handle(self, *args, **options):
        templates_only = options.get('templates_only', False)
        diagrams_only = options.get('diagrams_only', False)
        force = options.get('force', False)

        # Generate diagram thumbnails
        if not templates_only:
            self.stdout.write(self.style.SUCCESS('Generating diagram thumbnails...'))
            diagrams = Diagram.objects.all()

            if not force:
                # Only generate for diagrams without thumbnails
                diagrams = diagrams.filter(thumbnail__isnull=True) | diagrams.filter(thumbnail='')

            count = 0
            for diagram in diagrams:
                try:
                    generate_diagram_thumbnail(diagram)
                    diagram.save()
                    self.stdout.write(f'  ✓ Generated thumbnail for: {diagram.title}')
                    count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  ✗ Failed for {diagram.title}: {str(e)}'))

            self.stdout.write(self.style.SUCCESS(f'\nGenerated {count} diagram thumbnails'))

        # Note: Document templates don't have a thumbnail field in the model
        # They would need to be added similarly to diagrams if needed
        if not diagrams_only and not templates_only:
            self.stdout.write(self.style.WARNING('\nDocument template previews: Not implemented (no thumbnail field in model)'))
            self.stdout.write('To add document template previews, add an ImageField to the Document model')

        self.stdout.write(self.style.SUCCESS('\nThumbnail generation complete!'))
