"""
Management command to populate Document categories for organization documents
"""
from django.core.management.base import BaseCommand
from core.models import Organization
from docs.models import DocumentCategory
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Populate Document categories for organization documents'

    def handle(self, *args, **options):
        # Get all organizations
        organizations = Organization.objects.all()

        if not organizations.exists():
            self.stdout.write(self.style.ERROR('No organizations found. Please create at least one organization first.'))
            return

        self.stdout.write(f'Found {organizations.count()} organization(s)')

        # Categories for organization documents
        categories_data = [
            {'name': 'Company Policies', 'icon': 'gavel', 'description': 'Company policies, guidelines, and procedures'},
            {'name': 'IT Procedures', 'icon': 'laptop-code', 'description': 'IT-specific procedures and documentation'},
            {'name': 'Employee Handbook', 'icon': 'book-open', 'description': 'Employee handbooks and onboarding materials'},
            {'name': 'Network Documentation', 'icon': 'network-wired', 'description': 'Network diagrams, configurations, and documentation'},
            {'name': 'Vendor Information', 'icon': 'handshake', 'description': 'Vendor contacts, contracts, and documentation'},
            {'name': 'Disaster Recovery', 'icon': 'first-aid', 'description': 'DR plans and business continuity documentation'},
            {'name': 'Security & Compliance', 'icon': 'shield-alt', 'description': 'Security policies and compliance documentation'},
            {'name': 'User Guides', 'icon': 'user-graduate', 'description': 'End-user guides and how-to documentation'},
            {'name': 'System Documentation', 'icon': 'server', 'description': 'Server and system documentation'},
            {'name': 'Processes & Workflows', 'icon': 'project-diagram', 'description': 'Business processes and workflow documentation'},
        ]

        for org in organizations:
            self.stdout.write(f'\nProcessing organization: {org.name}')

            for idx, cat_data in enumerate(categories_data):
                cat, created = DocumentCategory.objects.get_or_create(
                    organization=org,
                    slug=slugify(cat_data['name']),
                    defaults={
                        'name': cat_data['name'],
                        'icon': cat_data['icon'],
                        'description': cat_data['description'],
                        'order': idx
                    }
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f'  Created category: {cat.name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'  Already exists: {cat.name}'))

        self.stdout.write(self.style.SUCCESS('\nSuccessfully populated document categories for all organizations!'))
