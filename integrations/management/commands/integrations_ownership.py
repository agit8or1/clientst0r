"""List integration connections by owner, or make one platform-owned.

    manage.py integrations_ownership --list
    manage.py integrations_ownership --make-platform psa 12

`--make-platform` is the same action as "Make platform-owned" on the
Integrations page in global view (integrations.ownership.make_platform_owned):
every row the connection already assigned keeps its customer, and new data that
maps to no customer stays unassigned for platform staff to place.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'List integration connections with their owner, or make one platform-owned.'

    def add_arguments(self, parser):
        parser.add_argument('--list', action='store_true', help='List every connection and its owner.')
        parser.add_argument('--make-platform', nargs=2, metavar=('TYPE', 'ID'),
                            help='Make one connection platform-owned. TYPE is one of: '
                                 'psa, rmm, unifi, omada, grandstream, m365, distributor, '
                                 'accounting, payment, warranty, tax.')

    def handle(self, *args, **options):
        from integrations.ownership import OwnershipError, connection_types, make_platform_owned
        types = connection_types()
        if options.get('make_platform'):
            key, raw_id = options['make_platform']
            if key not in types:
                raise CommandError(f'Unknown type "{key}". Use one of: {", ".join(types)}.')
            try:
                pk = int(raw_id)
            except ValueError:
                raise CommandError('ID must be a number.')
            model = types[key][0]
            conn = model._default_manager.filter(pk=pk).select_related('organization').first()
            if conn is None:
                raise CommandError(f'No {key} connection with id {pk}.')
            try:
                summary = make_platform_owned(conn, None)
            except OwnershipError as exc:
                raise CommandError(str(exc))
            self.stdout.write(self.style.SUCCESS(
                f'{key} #{pk} "{conn.name}" is now platform-owned (was {summary["previous_owner"]}). '
                f'Assigned data kept its customers.'))
            extra = {k: v for k, v in summary.items()
                     if k not in ('type', 'connection_id', 'previous_owner_id', 'previous_owner')}
            if extra:
                self.stdout.write('  ' + ', '.join(f'{k}: {v}' for k, v in extra.items()))
            return
        if not options.get('list'):
            raise CommandError('Pass --list or --make-platform TYPE ID.')
        for key, (model, label, _url) in types.items():
            for conn in model._default_manager.select_related('organization').order_by('pk'):
                owner = 'Platform' if conn.organization_id is None else \
                    f'{conn.organization.name} (organization #{conn.organization_id})'
                self.stdout.write(f'{key:12} #{conn.pk:<5} {conn.name[:40]:40}  owner: {owner}')
