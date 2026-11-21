"""Health checks, automatic reconnection and the ordered event drain for
Agit8or Connect (scheduled task connect_monitor, every minute; Quick Connect
increment D). See connect/monitor.py.

    manage.py connect_monitor [--budget SECONDS]
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Check connected applications, reconnect after outages with backoff (never after a security '
            'failure) and deliver queued events in order')

    def add_arguments(self, parser):
        parser.add_argument('--budget', type=float, default=50.0,
                            help='Seconds of wall time to keep checking (default 50, at most 55).')

    def handle(self, *args, **opts):
        from connect import identity, monitor
        if not identity.enabled():
            self.stdout.write('Agit8or Connect is off (AGIT8OR_CONNECT_ENABLED); nothing to do.')
            return
        t = monitor.run(budget=max(0.0, min(55.0, opts['budget'])))
        self.stdout.write(f"checked {t['checked']} connection(s) in {t['passes']} pass(es), "
                          f"delivered {t['delivered']} event(s), errors {t['errors']}"
                          + (', kill switch engaged' if t.get('kill_switch') else ''))
        for k in ('reaped', 'expired_events', 'pruned_events'):
            if t.get(k):
                self.stdout.write(f'{k.replace("_", " ")}: {t[k]}')
