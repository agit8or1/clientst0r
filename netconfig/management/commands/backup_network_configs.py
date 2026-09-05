"""
Phase 34.2 (v3.17.545) — collect device configs on a schedule.

Run from the scheduler (task type `network_config_backup`) or by hand:

    manage.py backup_network_configs            # everything due
    manage.py backup_network_configs --force    # ignore cadence
    manage.py backup_network_configs --target 4 # one device
"""
from django.core.management.base import BaseCommand

from netconfig.collector import collect_due, collect_target
from netconfig.models import BackupTarget


class Command(BaseCommand):
    help = 'Collect network device configurations over SSH.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Collect every enabled target regardless of cadence.')
        parser.add_argument('--target', type=int,
                            help='Collect one target by id, ignoring cadence.')
        parser.add_argument('--limit', type=int,
                            help='Stop after this many devices.')

    def handle(self, *args, **options):
        if options.get('target'):
            target = BackupTarget.objects.filter(pk=options['target']).first()
            if target is None:
                self.stderr.write(self.style.ERROR('No such target.'))
                return
            result = collect_target(target)
            style = self.style.SUCCESS if result['ok'] else self.style.ERROR
            self.stdout.write(style(f'{target.asset}: {result["message"]}'))
            return

        summary = collect_due(force=options.get('force'), limit=options.get('limit'))
        for target, result in summary['results']:
            style = self.style.SUCCESS if result['ok'] else self.style.WARNING
            self.stdout.write(style(f'  {target.asset}: {result["message"]}'))

        self.stdout.write(self.style.SUCCESS(
            f'{summary["attempted"]} attempted, {summary["ok"]} ok, '
            f'{summary["failed"]} failed, {summary["changed"]} changed.'))
