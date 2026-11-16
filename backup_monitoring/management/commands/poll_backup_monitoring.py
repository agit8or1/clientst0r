"""Poll backup providers (API ones) and evaluate alerts for every active
connection, including push-style ones whose "missed" state ages with time.

    manage.py poll_backup_monitoring [--connection ID] [--no-alerts]
"""
from django.core.management.base import BaseCommand, CommandError

from backup_monitoring.alerts import evaluate_connection
from backup_monitoring.models import BackupConnection
from backup_monitoring.recording import poll_connection


class Command(BaseCommand):
    help = 'Poll backup monitoring connections and evaluate alert rules.'

    def add_arguments(self, parser):
        parser.add_argument('--connection', type=int, help='Only this connection id.')
        parser.add_argument('--no-alerts', action='store_true', help='Poll only; do not evaluate alerts.')

    def handle(self, *args, **opts):
        qs = BackupConnection.objects.filter(active=True)
        if opts['connection']:
            qs = qs.filter(pk=opts['connection'])
        failures = 0
        for conn in qs:
            result = poll_connection(conn)
            if not result['ok']:
                failures += 1
            line = f"{conn.name}: {'ok' if result['ok'] else 'ERROR ' + result['message']}"
            if not opts['no_alerts']:
                stats = evaluate_connection(conn)
                line += f" (alerts opened {stats['opened']}, resolved {stats['resolved']})"
            self.stdout.write(line)
        if failures:
            raise CommandError(f'{failures} connection(s) failed to poll.')
