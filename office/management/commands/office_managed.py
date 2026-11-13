"""The managed local editor (ONLYOFFICE Docs or Collabora CODE) from the
command line.

    manage.py office_managed --run-pending      advance the active operation
                                                (the scheduler runs this every
                                                minute: task office_managed_operations)
    manage.py office_managed --status           helper status and the last operations
    manage.py office_managed --queue ACTION [--release ID] [--engine E]
                                 [--layout L [--accept-same-host]] --user NAME
                                                queue install/start/stop/restart/
                                                update/rollback/uninstall/
                                                switch_engine/set_layout
                                                (the operation runs as NAME, an
                                                active superuser)

Output never contains secrets. Root-only actions (purge, firewall) are not
here: run `sudo clientst0r-office-helper cli ...` on the server.
"""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from office.managed import jobs
from office.models import ManagedOfficeOperation, ManagedOfficeService


class Command(BaseCommand):
    help = 'Run, queue or show managed local editor operations.'

    def add_arguments(self, parser):
        g = parser.add_mutually_exclusive_group(required=True)
        g.add_argument('--run-pending', action='store_true')
        g.add_argument('--status', action='store_true')
        g.add_argument('--queue', choices=[a for a, _ in ManagedOfficeOperation.ACTIONS])
        parser.add_argument('--release', default='')
        parser.add_argument('--engine', default='', choices=['', 'onlyoffice', 'collabora'],
                            help='switch_engine: the engine to switch to.')
        parser.add_argument('--layout', default='', choices=['', 'dedicated', 'same-host'],
                            help='set_layout: the address layout to switch to.')
        parser.add_argument('--accept-same-host', action='store_true',
                            help='set_layout same-host: accept that the editor front-end runs on '
                                 "clientst0r's own origin (recorded and audited).")
        parser.add_argument('--user', default='', help='Superuser the operation is recorded for.')

    def handle(self, *args, **opts):
        if opts['run_pending']:
            jobs.maybe_schedule_update()
            result = jobs.run_pending()
            self.stdout.write('no managed operation queued' if result is None
                              else f'operation {result[0]}: {result[1]}')
            return
        if opts['status']:
            status = jobs.refresh_status()
            service = ManagedOfficeService.get()
            if status is None:
                self.stdout.write(f'Helper unreachable: {service.status_error}')
            else:
                self.stdout.write(json.dumps(status, indent=1, default=str))
            for op in ManagedOfficeOperation.objects.all()[:5]:
                self.stdout.write(f'{op.pk} {op.action} {op.state} {op.queued_at:%Y-%m-%d %H:%M} '
                                  f'{(op.progress or {}).get("message", "")[:80]} {op.error[:200]}')
            return
        user = None
        if opts['user']:
            user = get_user_model().objects.filter(username=opts['user'], is_superuser=True).first()
            if user is None:
                raise CommandError(f'No superuser named {opts["user"]}.')
        if not ManagedOfficeService.get().enabled:
            raise CommandError('The managed local editor is off (Settings → Office Documents → '
                               'Managed local editor).')
        if opts['queue'] == 'set_layout' and opts['layout'] == 'same-host':
            if not opts['accept_same_host']:
                raise CommandError('The same-host layout serves the editor on clientst0r\'s own origin; '
                                   'pass --accept-same-host to accept that (see docs/office/MANAGED_LOCAL.md).')
            if user is None:
                raise CommandError('--user is required to record who accepted the same-host layout.')
            from django.utils import timezone
            from office import audit
            ManagedOfficeService.objects.filter(pk=1).update(same_host_acknowledged_at=timezone.now(),
                                                             same_host_acknowledged_by=user)
            audit.log('settings_change', user=user, object_type='office.managed', object_id=1,
                      object_repr='Managed Office editor',
                      description='Accepted the same-host layout warning (command line)',
                      extra={'changed': ['same_host_acknowledged'], 'layout': 'same-host'})
        try:
            op = jobs.enqueue(opts['queue'], user=user, release=opts['release'], engine=opts['engine'],
                              layout=opts['layout'])
        except (jobs.AlreadyActive, ValueError) as e:
            raise CommandError(str(e))
        self.stdout.write(f'Queued operation {op.pk} ({op.action}); the scheduler runs it within a minute.')
