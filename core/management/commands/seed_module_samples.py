"""Add sample data to modules the other demo seeders leave empty.

Additive and safe to re-run; see core/demo_samples. Not run automatically.

By default it targets the built-in demo customers (``CUSTOMER_SLUGS``) and
the Demo MSP (``MSP_SLUG``) and adds three demo technicians. A demo instance
with its own invented customers can point it at them instead:

    manage.py seed_module_samples --customers northwind-logistics,ridgeline-dental-group \\
        --msp beacon-managed-it --techs demo.ipatel,demo.mokafor --owner demo.tech
"""
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings

from core.demo_samples import GROUPS, build_context


def _csv(value):
    return [v.strip() for v in (value or '').split(',') if v.strip()]


class Command(BaseCommand):
    help = 'Add sample data (demo customers only) to inventory, scheduling, CRM, status pages, security incidents and more.'

    def add_arguments(self, parser):
        parser.add_argument('--only', choices=GROUPS, action='append',
                            help='Seed just this group (repeatable).')
        parser.add_argument('--customers', default='',
                            help='Comma-separated customer organization slugs to seed, in order '
                                 '(default: the built-in demo customers).')
        parser.add_argument('--msp', default='', help='Slug of the MSP organization (default: demo-msp).')
        parser.add_argument('--techs', default='',
                            help='Comma-separated usernames of existing MSP staff to use instead of '
                                 'creating the three demo technicians.')
        parser.add_argument('--owner', default='',
                            help='Username of the superuser who owns created rows (default: "admin", '
                                 'else the first superuser).')

    def handle(self, *args, **opts):
        groups = opts.get('only') or GROUPS
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'):
            try:
                ctx = build_context(self.stdout, customer_slugs=_csv(opts.get('customers')),
                                    msp_slug=opts.get('msp') or None, tech_usernames=_csv(opts.get('techs')),
                                    owner_username=opts.get('owner') or None)
            except ValueError as e:
                raise CommandError(str(e))
            if not ctx.customers or ctx.admin is None:
                raise CommandError('No demo customer organizations or no superuser; nothing to seed.')
            for name in groups:
                with transaction.atomic():
                    import_module(f'core.demo_samples.{name}').seed(ctx)
        for label in sorted(ctx.counts):
            self.stdout.write(f'  {label}: {ctx.counts[label]} created')
        self.stdout.write(self.style.SUCCESS(f'Module samples: {sum(ctx.counts.values())} rows created.'))
