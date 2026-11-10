"""Run the upgrade preflight checks (the first thing Apply does).

    manage.py upgrade_preflight [--kind release|preview --target-ref REF --target-sha SHA] [--skip-deps]

Exit status 1 when any check fails.
"""
import sys

from django.core.management.base import BaseCommand, CommandError

from core.upgrade import preflight
from core.upgrade.revision import RevisionError, Target, head_sha


class Command(BaseCommand):
    help = 'Check that an upgrade can run safely (disk, database, keys, backups, dependencies)'

    def add_arguments(self, parser):
        parser.add_argument('--target-ref')
        parser.add_argument('--target-sha')
        parser.add_argument('--kind', default='release', choices=['release', 'preview'])
        parser.add_argument('--skip-deps', action='store_true')

    def handle(self, *args, **opts):
        target = None
        if opts['target_sha']:
            try:
                target = Target(opts['kind'], opts['target_ref'] or 'main', opts['target_sha']).validate()
            except RevisionError as e:
                raise CommandError(str(e))
        checks = preflight.run(target, installed_sha=head_sha(), deps=not opts['skip_deps'])
        for c in checks:
            self.stdout.write(f'[{c.status.upper():4}] {c.name}: {c.detail}')
            if c.hint and c.status != 'ok':
                self.stdout.write(f'       -> {c.hint}')
        if preflight.failed(checks):
            sys.exit(1)
