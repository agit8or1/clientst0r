"""
Management command to initialize system role templates.
"""
from django.core.management.base import BaseCommand
from accounts.models import RoleTemplate


class Command(BaseCommand):
    help = 'Initialize system role templates'

    def handle(self, *args, **options):
        self.stdout.write("Initializing system role templates...")

        RoleTemplate.get_or_create_system_templates()

        templates = RoleTemplate.objects.filter(is_system_template=True)
        self.stdout.write(self.style.SUCCESS(f"✓ Created {templates.count()} system role templates:"))

        for template in templates:
            self.stdout.write(f"  - {template.name}: {template.description}")

        self.stdout.write(self.style.SUCCESS("Role templates initialized successfully!"))
