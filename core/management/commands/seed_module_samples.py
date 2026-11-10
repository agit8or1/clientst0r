"""Add sample data to modules the other demo seeders leave empty.

Additive and safe to re-run; see core/demo_samples. Not run automatically.
"""
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings

from core.demo_samples import GROUPS, build_context


class Command(BaseCommand):
    help = 'Add sample data (demo customers only) to inventory, scheduling, CRM, status pages, security incidents and more.'

    def add_arguments(self, parser):
        parser.add_argument('--only', choices=GROUPS, action='append',
                            help='Seed just this group (repeatable).')

    def handle(self, *args, **opts):
        groups = opts.get('only') or GROUPS
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'):
            ctx = build_context(self.stdout)
            if not ctx.customers or ctx.admin is None:
                raise CommandError('No demo customer organizations or no superuser; nothing to seed.')
            for name in groups:
                with transaction.atomic():
                    import_module(f'core.demo_samples.{name}').seed(ctx)
        for label in sorted(ctx.counts):
            self.stdout.write(f'  {label}: {ctx.counts[label]} created')
        self.stdout.write(self.style.SUCCESS(f'Module samples: {sum(ctx.counts.values())} rows created.'))
