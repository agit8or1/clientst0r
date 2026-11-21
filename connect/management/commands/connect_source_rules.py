"""Server-side recovery for the Agit8or Connect source policy (B1).

    manage.py connect_source_rules list
    manage.py connect_source_rules add --network 203.0.113.10 [--connection UUID] [--deny] [--private]
    manage.py connect_source_rules remove --id 12
    manage.py connect_source_rules enforce        # end the observe period now

Changes apply at once (whoever runs this already controls the server), bump
the policy version so every worker reloads, and are written to the Connect
audit chain and AuditLog. The same validation as the admin UI applies: no
allow-all, no over-broad ranges, private addresses only with --private.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'List, add or remove Agit8or Connect source rules, or end the observe period (recovery).'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['list', 'add', 'remove', 'enforce'])
        parser.add_argument('--network', default='')
        parser.add_argument('--connection', default='', help='Connection id (connection layer); omit for the '
                                                             'installation layer')
        parser.add_argument('--deny', action='store_true')
        parser.add_argument('--private', action='store_true')
        parser.add_argument('--id', type=int, action='append', default=[])

    def handle(self, *args, **o):
        from connect import source_policy
        from connect.models import Connection, SourceRule
        if o['action'] == 'list':
            for r in SourceRule.objects.exclude(status=SourceRule.REMOVED).order_by('layer', 'connection_id', 'pk'):
                self.stdout.write(f'{r.pk:>6} {r.layer:<12} {str(r.connection_id or "-"):<36} {r.action:<5} '
                                  f'{r.network:<43} {r.status:<9} {r.purpose}')
            obs = source_policy.observe_status()
            self.stdout.write(f'observe period until {obs["until"]:%Y-%m-%d %H:%M}' if obs else 'enforcing')
            return
        if o['action'] == 'enforce':
            self.stdout.write('enforcing now' if source_policy.enforce_now(None) else 'already enforcing')
            return
        try:
            if o['action'] == 'add':
                entry = {'layer': SourceRule.INSTALLATION, 'network': o['network'],
                         'action': SourceRule.DENY if o['deny'] else SourceRule.ALLOW, 'private': o['private']}
                if o['connection']:
                    conn = Connection.objects.filter(pk=o['connection']).first()
                    if conn is None:
                        raise CommandError('No such connection.')
                    entry.update(layer=SourceRule.CONNECTION, connection=conn.pk)
                rows = source_policy.apply_direct([entry])
                self.stdout.write(f'added rule {rows[0].pk}: {rows[0].action} {rows[0].network}')
            else:
                if not o['id']:
                    raise CommandError('Give --id.')
                source_policy.apply_direct(remove=o['id'])
                self.stdout.write(f'removed {len(o["id"])} rule(s)')
        except ValidationError as e:
            raise CommandError(' '.join(e.messages))
