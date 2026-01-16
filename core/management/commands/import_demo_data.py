"""
Management command to import Acme Corporation demo data.

This command imports a complete demo company with:
- Documents (procedures, policies, runbooks)
- Diagrams (network, rack, process flowcharts)
- Assets (workstations, servers, network equipment)
- Passwords (various types and categories)
- Global KB articles
- Processes with execution history
"""
import json
import os
import requests
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction

from core.models import Organization
from docs.models import Document, DocumentCategory, GlobalKnowledge, Diagram
from assets.models import Asset, AssetType
from vault.models import Password
from processes.models import Process, ProcessExecution


class Command(BaseCommand):
    help = 'Import Acme Corporation demo data from GitHub'

    def add_arguments(self, parser):
        parser.add_argument(
            '--github-repo',
            type=str,
            default='agit8or1/huduglue-demo-data',
            help='GitHub repository containing demo data (default: agit8or1/huduglue-demo-data)'
        )
        parser.add_argument(
            '--branch',
            type=str,
            default='main',
            help='Branch to import from (default: main)'
        )
        parser.add_argument(
            '--organization',
            type=str,
            required=True,
            help='Organization name or ID to import data into'
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Username to assign as creator (defaults to first superuser)'
        )

    def handle(self, *args, **options):
        github_repo = options['github_repo']
        branch = options['branch']
        org_identifier = options['organization']
        username = options.get('user')

        self.stdout.write(
            self.style.WARNING(
                f'Importing Acme Corporation demo data...'
            )
        )

        # Get organization
        try:
            if org_identifier.isdigit():
                organization = Organization.objects.get(id=int(org_identifier))
            else:
                organization = Organization.objects.get(name__iexact=org_identifier)
        except Organization.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f'Organization "{org_identifier}" not found. '
                    f'Please create it first or use an existing organization.'
                )
            )
            return

        # Get user
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
                return
        else:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                self.stdout.write(self.style.ERROR('No superuser found'))
                return

        self.stdout.write(f'Importing into organization: {organization.name}')
        self.stdout.write(f'Created by user: {user.username}')

        # GitHub API base URL
        github_api_base = f'https://api.github.com/repos/{github_repo}/contents'
        github_raw_base = f'https://raw.githubusercontent.com/{github_repo}/{branch}'

        try:
            with transaction.atomic():
                stats = {
                    'documents': 0,
                    'diagrams': 0,
                    'assets': 0,
                    'passwords': 0,
                    'kb_articles': 0,
                    'processes': 0,
                }

                # Import categories first
                self.stdout.write('Creating document categories...')
                categories = self._create_categories(organization)

                # Import documents
                self.stdout.write('Importing documents...')
                docs_data = self._fetch_json_from_github(
                    f'{github_raw_base}/data/documents.json'
                )
                if docs_data:
                    for doc_data in docs_data:
                        self._import_document(doc_data, organization, user, categories)
                        stats['documents'] += 1

                # Import diagrams
                self.stdout.write('Importing diagrams...')
                diagrams_data = self._fetch_json_from_github(
                    f'{github_raw_base}/data/diagrams.json'
                )
                if diagrams_data:
                    for diagram_data in diagrams_data:
                        self._import_diagram(diagram_data, organization, user)
                        stats['diagrams'] += 1

                # Import assets
                self.stdout.write('Importing assets...')
                assets_data = self._fetch_json_from_github(
                    f'{github_raw_base}/data/assets.json'
                )
                if assets_data:
                    for asset_data in assets_data:
                        self._import_asset(asset_data, organization, user)
                        stats['assets'] += 1

                # Import passwords
                self.stdout.write('Importing passwords...')
                passwords_data = self._fetch_json_from_github(
                    f'{github_raw_base}/data/passwords.json'
                )
                if passwords_data:
                    for password_data in passwords_data:
                        self._import_password(password_data, organization, user)
                        stats['passwords'] += 1

                # Import KB articles
                self.stdout.write('Importing knowledge base articles...')
                kb_data = self._fetch_json_from_github(
                    f'{github_raw_base}/data/knowledge_base.json'
                )
                if kb_data:
                    for kb_item in kb_data:
                        self._import_kb_article(kb_item, organization, user)
                        stats['kb_articles'] += 1

                # Import processes
                self.stdout.write('Importing processes...')
                processes_data = self._fetch_json_from_github(
                    f'{github_raw_base}/data/processes.json'
                )
                if processes_data:
                    for process_data in processes_data:
                        self._import_process(process_data, organization, user)
                        stats['processes'] += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n✓ Successfully imported Acme Corporation demo data:'
                    )
                )
                self.stdout.write(f'  • Documents: {stats["documents"]}')
                self.stdout.write(f'  • Diagrams: {stats["diagrams"]}')
                self.stdout.write(f'  • Assets: {stats["assets"]}')
                self.stdout.write(f'  • Passwords: {stats["passwords"]}')
                self.stdout.write(f'  • KB Articles: {stats["kb_articles"]}')
                self.stdout.write(f'  • Processes: {stats["processes"]}')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Import failed: {e}')
            )
            raise

    def _fetch_json_from_github(self, url):
        """Fetch JSON data from GitHub."""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.stdout.write(
                self.style.WARNING(f'Failed to fetch {url}: {e}')
            )
            return None
        except json.JSONDecodeError:
            self.stdout.write(
                self.style.WARNING(f'Invalid JSON at {url}')
            )
            return None

    def _create_categories(self, organization):
        """Create document categories."""
        categories = {}
        category_names = [
            'IT Procedures',
            'Security Policies',
            'Network Documentation',
            'Server Documentation',
            'User Guides',
            'Runbooks',
            'Disaster Recovery',
        ]

        for name in category_names:
            category, created = DocumentCategory.objects.get_or_create(
                organization=organization,
                name=name
            )
            categories[name] = category
            if created:
                self.stdout.write(f'  Created category: {name}')

        return categories

    def _import_document(self, data, organization, user, categories):
        """Import a single document."""
        category = categories.get(data.get('category'))

        document = Document.objects.create(
            organization=organization,
            title=data['title'],
            slug=data.get('slug', data['title'].lower().replace(' ', '-')),
            body=data['body'],
            content_type=data.get('content_type', 'html'),
            category=category,
            is_published=True,
            created_by=user,
        )

        if 'tags' in data:
            document.tags.set(data['tags'])

        self.stdout.write(f'  Imported document: {document.title}')

    def _import_diagram(self, data, organization, user):
        """Import a single diagram."""
        diagram = Diagram.objects.create(
            organization=organization,
            title=data['title'],
            diagram_type=data.get('diagram_type', 'network'),
            diagram_xml=data['diagram_xml'],
            description=data.get('description', ''),
            created_by=user,
        )

        self.stdout.write(f'  Imported diagram: {diagram.title}')

    def _import_asset(self, data, organization, user):
        """Import a single asset."""
        asset = Asset.objects.create(
            organization=organization,
            name=data['name'],
            asset_type=data.get('asset_type', 'computer'),
            serial_number=data.get('serial_number', ''),
            manufacturer=data.get('manufacturer', ''),
            model=data.get('model', ''),
            hostname=data.get('hostname', ''),
            ip_address=data.get('ip_address', ''),
            mac_address=data.get('mac_address', ''),
            status=data.get('status', 'active'),
            notes=data.get('notes', ''),
        )

        self.stdout.write(f'  Imported asset: {asset.name}')

    def _import_password(self, data, organization, user):
        """Import a single password."""
        password = Password.objects.create(
            organization=organization,
            title=data['title'],
            username=data.get('username', ''),
            password_type=data.get('password_type', 'login'),
            url=data.get('url', ''),
            notes=data.get('notes', ''),
        )

        # Encrypt password if provided
        if 'password' in data:
            password.set_password(data['password'])

        # Add OTP secret if provided
        if 'otp_secret' in data:
            password.otp_secret = data['otp_secret']
            password.save()

        self.stdout.write(f'  Imported password: {password.title}')

    def _import_kb_article(self, data, organization, user):
        """Import a single knowledge base article."""
        kb = GlobalKnowledge.objects.create(
            organization=organization,
            title=data['title'],
            slug=data.get('slug', data['title'].lower().replace(' ', '-')),
            body=data['body'],
            content_type=data.get('content_type', 'html'),
            category=data.get('category'),
            is_published=True,
        )

        if 'tags' in data:
            kb.tags.set(data['tags'])

        self.stdout.write(f'  Imported KB article: {kb.title}')

    def _import_process(self, data, organization, user):
        """Import a single process."""
        process = Process.objects.create(
            organization=organization,
            title=data['title'],
            description=data.get('description', ''),
            process_steps=data.get('process_steps', []),
            estimated_duration=data.get('estimated_duration', 30),
            created_by=user,
        )

        # Create sample execution if requested
        if data.get('create_sample_execution'):
            execution = ProcessExecution.objects.create(
                organization=organization,
                process=process,
                status='completed',
                started_by=user,
                started_at=timezone.now(),
                completed_at=timezone.now(),
            )

        self.stdout.write(f'  Imported process: {process.title}')
