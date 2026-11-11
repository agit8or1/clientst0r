"""Find dead links in published KB articles (scheduler: "KB Dead Link Check").

Internal links to missing / archived / unpublished documents, and external
links that fail an SSRF-safe HEAD check (core.safe_http). See
docs/services/link_check.py.
"""
from django.core.management.base import BaseCommand

from docs.services import link_check


class Command(BaseCommand):
    help = 'Check KB articles for dead internal and external links.'

    def add_arguments(self, parser):
        parser.add_argument('--internal-only', action='store_true',
                            help='Check internal links only; make no outbound requests.')
        parser.add_argument('--max-external', type=int, default=link_check.MAX_EXTERNAL_PER_RUN,
                            help='Most external URLs to fetch this run.')

    def handle(self, *args, **options):
        counts = link_check.run(check_external=not options['internal_only'],
                                max_external=max(0, options['max_external']))
        self.stdout.write(f'KB link check: {counts}')
