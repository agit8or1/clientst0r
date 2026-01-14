"""
Fetch demo/sample KB articles from GitHub repository.

Pulls curated KB articles from the HuduGlue GitHub repository
and populates the knowledge base with professional IT documentation.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from docs.models import Document, DocumentCategory
import requests
import json


class Command(BaseCommand):
    help = 'Fetch KB articles from GitHub repository'

    GITHUB_REPO = 'agit8or1/huduglue'
    GITHUB_BRANCH = 'main'
    KB_ARTICLES_PATH = 'fixtures/kb_articles.json'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Delete existing global KB articles before importing',
        )
        parser.add_argument(
            '--repo',
            type=str,
            default='agit8or1/huduglue',
            help='GitHub repository (owner/repo)',
        )
        parser.add_argument(
            '--branch',
            type=str,
            default='main',
            help='Git branch to fetch from',
        )
        parser.add_argument(
            '--file',
            type=str,
            default='fixtures/kb_articles.json',
            help='Path to KB articles JSON file in repo',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('Generating KB Articles'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Note: Generating articles locally (GitHub fixtures not yet available)'))
        self.stdout.write('')

        # Simply delegate to the seed_kb_articles command
        # This generates the 1,042 comprehensive IT articles
        from django.core.management import call_command

        try:
            call_command('seed_kb_articles', delete=options['delete'], stdout=self.stdout, stderr=self.stderr)

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=' * 70))
            self.stdout.write(self.style.SUCCESS('KB Article Generation Complete!'))
            self.stdout.write(self.style.SUCCESS('=' * 70))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to generate articles: {e}'))
            raise

        return

        # Original GitHub fetching code (disabled until fixtures are available)
        repo = options.get('repo', self.GITHUB_REPO)
        branch = options.get('branch', self.GITHUB_BRANCH)
        file_path = options.get('file', self.KB_ARTICLES_PATH)

        if options['delete']:
            self.stdout.write('Deleting existing global KB articles...')
            deleted_articles = Document.objects.filter(is_global=True, organization=None).delete()
            deleted_categories = DocumentCategory.objects.filter(organization=None).delete()
            self.stdout.write(self.style.SUCCESS(f'✓ Deleted {deleted_articles[0]} articles and {deleted_categories[0]} categories'))

        # Construct GitHub raw content URL
        url = f'https://raw.githubusercontent.com/{repo}/{branch}/{file_path}'

        self.stdout.write(f'Fetching from: {url}')

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            kb_data = response.json()

            self.stdout.write(self.style.SUCCESS(f'✓ Downloaded KB data'))

            # Import categories
            categories_created = 0
            categories_map = {}

            if 'categories' in kb_data:
                self.stdout.write('\\nCreating categories...')
                for cat_data in kb_data['categories']:
                    category, created = DocumentCategory.objects.get_or_create(
                        organization=None,
                        slug=cat_data['slug'],
                        defaults={
                            'name': cat_data['name'],
                            'description': cat_data.get('description', ''),
                            'icon': cat_data.get('icon', 'folder'),
                            'order': cat_data.get('order', 0),
                        }
                    )
                    categories_map[cat_data['slug']] = category
                    if created:
                        categories_created += 1

                self.stdout.write(self.style.SUCCESS(f'✓ Created {categories_created} categories'))

            # Import articles
            articles_created = 0
            articles_updated = 0

            if 'articles' in kb_data:
                self.stdout.write('\\nImporting articles...')

                for article_data in kb_data['articles']:
                    category = None
                    if 'category_slug' in article_data and article_data['category_slug'] in categories_map:
                        category = categories_map[article_data['category_slug']]

                    article, created = Document.objects.update_or_create(
                        organization=None,
                        slug=slugify(article_data['title']),
                        defaults={
                            'title': article_data['title'],
                            'body': article_data['body'],
                            'content_type': article_data.get('content_type', 'markdown'),
                            'is_global': True,
                            'is_published': article_data.get('is_published', True),
                            'category': category,
                        }
                    )

                    if created:
                        articles_created += 1
                    else:
                        articles_updated += 1

                    if (articles_created + articles_updated) % 50 == 0:
                        self.stdout.write(f'  Imported {articles_created + articles_updated} articles...')

                self.stdout.write(self.style.SUCCESS(f'✓ Created {articles_created} new articles'))
                if articles_updated > 0:
                    self.stdout.write(self.style.SUCCESS(f'✓ Updated {articles_updated} existing articles'))

            self.stdout.write('\\n' + self.style.SUCCESS('=' * 70))
            self.stdout.write(self.style.SUCCESS('KB Import Complete!'))
            self.stdout.write(self.style.SUCCESS('=' * 70))
            self.stdout.write('')
            self.stdout.write('Next steps:')
            self.stdout.write('  • Navigate to Knowledge Base to see articles')
            self.stdout.write('  • Articles are marked as global and visible to all organizations')
            self.stdout.write('  • You can edit or delete articles as needed')
            self.stdout.write('')

        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f'\\n✗ Failed to fetch KB articles from GitHub'))
            self.stdout.write(self.style.ERROR(f'  Error: {str(e)}'))
            self.stdout.write('')
            self.stdout.write('Troubleshooting:')
            self.stdout.write('  • Check internet connectivity')
            self.stdout.write('  • Verify repository and file path are correct')
            self.stdout.write('  • Check GitHub is accessible')
            self.stdout.write(f'  • URL attempted: {url}')
            self.stdout.write('')
            self.stdout.write('Alternative: Use local seed command:')
            self.stdout.write('  python manage.py seed_kb_articles')
            return

        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f'\\n✗ Invalid JSON format in KB articles file'))
            self.stdout.write(self.style.ERROR(f'  Error: {str(e)}'))
            return

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\\n✗ Unexpected error: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
            return
