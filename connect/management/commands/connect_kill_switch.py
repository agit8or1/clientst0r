"""Emergency kill switch for every connected application.

    manage.py connect_kill_switch            engage: suspend all, refuse every API call
    manage.py connect_kill_switch --release  lift it (connections stay suspended until resumed)
    manage.py connect_kill_switch --status
Works whether or not AGIT8OR_CONNECT_ENABLED is on.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Engage or release the Agit8or Connect emergency kill switch'

    def add_arguments(self, parser):
        parser.add_argument('--release', action='store_true')
        parser.add_argument('--status', action='store_true')

    def handle(self, *args, **opts):
        from connect import identity, lifecycle
        if opts['status']:
            self.stdout.write('engaged' if identity.kill_switch_engaged() else 'released')
            return
        if opts['release']:
            lifecycle.release_kill_switch()
            self.stdout.write('Kill switch released. Resume connections individually.')
            return
        n = lifecycle.engage_kill_switch()
        self.stdout.write(self.style.WARNING(f'Kill switch engaged: {n} connection(s) suspended.'))
