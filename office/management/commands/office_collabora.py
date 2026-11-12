"""Per-instance Collabora options (trusted CLI; there is no web form for them yet).

    manage.py office_collabora --instance N                      show the options
    manage.py office_collabora --instance N --require-proof on|off
    manage.py office_collabora --instance N --disable-print on|off --hide-export on|off
    manage.py office_collabora --instance N --discovery-ttl 3600
    manage.py office_collabora --instance N --refresh-discovery   drop the cached discovery

require-proof defaults to on: once Collabora publishes a proof key, unsigned
or badly signed WOPI requests are refused. Turning it off is audited.
"""
from django.core.management.base import BaseCommand, CommandError

from office import audit
from office.models import EditorInstance
from office.providers.collabora import discovery, options


def _onoff(value):
    if value is None:
        return None
    v = value.strip().lower()
    if v in ('on', 'yes', 'true', '1'):
        return True
    if v in ('off', 'no', 'false', '0'):
        return False
    raise CommandError(f'Expected on or off, got {value!r}.')


class Command(BaseCommand):
    help = 'Show or change Collabora Online options of one editor instance.'

    def add_arguments(self, parser):
        parser.add_argument('--instance', type=int, required=True)
        parser.add_argument('--require-proof')
        parser.add_argument('--disable-print')
        parser.add_argument('--hide-export')
        parser.add_argument('--discovery-ttl', type=int)
        parser.add_argument('--refresh-discovery', action='store_true')

    def handle(self, *args, **opts):
        inst = EditorInstance.objects.filter(pk=opts['instance'], provider='collabora').first()
        if inst is None:
            raise CommandError('No Collabora instance with that id.')
        changes = {}
        for key in ('require_proof', 'disable_print', 'hide_export'):
            value = _onoff(opts.get(key))
            if value is not None:
                changes[key] = value
        if opts.get('discovery_ttl') is not None:
            changes['discovery_ttl_s'] = opts['discovery_ttl']
        if changes:
            before = options.get(inst)
            after = options.set_options(inst, **changes)
            audit.log('settings_change', object_type='office.instance', object_id=inst.pk,
                      object_repr=inst.name,
                      description=f'Collabora options of {inst.name} changed from the CLI',
                      extra={'before': before, 'after': after})
            discovery.forget(inst)
        if opts['refresh_discovery']:
            discovery.forget(inst)
            self.stdout.write('Cached discovery dropped.')
        for key, value in options.get(inst).items():
            self.stdout.write(f'{key}: {value}')
