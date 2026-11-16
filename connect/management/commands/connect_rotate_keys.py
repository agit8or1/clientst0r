"""Rotate due Agit8or Connect keys (scheduled task connect_rotate_keys).

    manage.py connect_rotate_keys [--connection UUID] [--now]

A new key is staged, published in this connection's endorsed JWKS and used
only after the other application accepted a token request signed with it.
If it is refused, the old key stays active and the failure is shown on the
connection. Keys whose overlap ended are retired (private half wiped).
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Rotate connected-application keys that are due and retire keys past their overlap'

    def add_arguments(self, parser):
        parser.add_argument('--connection', help='Rotate this connection now, due or not')

    def handle(self, *args, **opts):
        from connect import identity, lifecycle
        from connect.models import Connection
        if not identity.enabled():
            self.stdout.write('Agit8or Connect is off (AGIT8OR_CONNECT_ENABLED); nothing to do.')
            return
        if opts.get('connection'):
            conn = Connection.objects.filter(pk=opts['connection']).first()
            if conn is None:
                raise CommandError('No such connection.')
            ok = lifecycle.rotate(conn)
            self.stdout.write('rotated' if ok else f'rotation failed: {conn.last_rotation_error}')
            return
        r = lifecycle.rotate_due()
        self.stdout.write(f"rotated {r['rotated']}, failed {r['failed']}, retired {r['retired']}")
