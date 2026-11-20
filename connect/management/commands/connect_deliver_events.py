"""Deliver queued Agit8or Connect events (scheduled task connect_deliver_events).

    manage.py connect_deliver_events [--limit N]
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Deliver queued signed events to connected applications (retry with backoff, dead letter) and '
            'summarise unauthenticated refusals into the audit chain')

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **opts):
        from connect import events, identity
        if not identity.enabled():
            self.stdout.write('Agit8or Connect is off (AGIT8OR_CONNECT_ENABLED); nothing to do.')
            return
        c = events.deliver_due(limit=opts['limit'])
        self.stdout.write(f"delivered {c['delivered']}, retry later {c['retry']}, dead letter {c['dead']}")
        from connect import denials
        summary = denials.summarise()   # unauthenticated refusals: one chain record per minute at most
        if summary is not None:
            self.stdout.write(f"summarised {summary.detail.get('total', 0)} refused request(s) into the audit chain")
