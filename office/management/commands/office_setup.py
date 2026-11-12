"""Trusted CLI for Office editor setup. Run by an administrator, never by Django.

    manage.py office_setup --plan --provider onlyoffice --mode same-server \\
        --editor-host docs.example.com [--instance N]
    manage.py office_setup --install [same options as --plan]
    manage.py office_setup --import-secret FILE [--instance N] [--name NAME]
    manage.py office_setup --set-secret N --secret-file PATH
    manage.py office_setup --verify-tls N

--plan           print the checklist and commands the Settings page shows.
--install        Django never installs packages. Prints how to run the editor
                 installer (scripts/office/install-editor.sh) as root on the
                 editor host, then exits; nothing is installed by this command.
--import-secret  read the one-time file written by install-editor.sh (owner-only,
                 0600, owned by the user running this command), store the secret
                 encrypted, and shred the file. With --instance N it sets the
                 secret of instance N (provider must match); without it, it
                 creates a new, disabled instance from the file's addresses.
--set-secret     store the secret read from a root-only file on instance N
                 (the secret never appears on a command line or in a URL).
--verify-tls     switch TLS verification back on for instance N (it cannot be
                 switched off from the web UI, and this command has no way to
                 switch it off either).
"""
import os
import stat

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from office import audit, install_guidance
from office.models import PROVIDER_CHOICES, EditorInstance, secret_problem

IMPORT_KEYS = ('PROVIDER', 'EDITION', 'MODE', 'NAME', 'BROWSER_URL', 'INTERNAL_URL',
               'CALLBACK_URL', 'SECRET')
MAX_IMPORT_BYTES = 8192


def _check_owner_only(path, *, own=False):
    try:
        st = os.lstat(path)
    except OSError as e:
        raise CommandError(f'Cannot read {path}: {e.strerror}')
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise CommandError(f'{path} must be a regular file (not a link).')
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CommandError(f'{path} must be readable by its owner only (chmod 600).')
    if own and st.st_uid != os.geteuid():
        raise CommandError(f'{path} must be owned by the user running this command '
                           f'(it is shredded after import).')
    return st


def _read_secret_file(path):
    _check_owner_only(path)
    with open(path, 'r', encoding='utf-8') as fh:
        value = fh.read().strip()
    problem = secret_problem(value)
    if problem:
        raise CommandError(problem)
    return value


def parse_import_file(path):
    st = _check_owner_only(path, own=True)
    if st.st_size > MAX_IMPORT_BYTES:
        raise CommandError(f'{path} is too large to be an import file.')
    data = {}
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep or key not in IMPORT_KEYS:
                raise CommandError(f'{path} is not an install-editor.sh import file.')
            data[key] = value.strip()
    if data.get('PROVIDER') not in dict(PROVIDER_CHOICES):
        raise CommandError(f'{path} names no known provider.')
    problem = secret_problem(data.get('SECRET', ''))
    if problem:
        raise CommandError(f'The secret in {path} is not usable: {problem}')
    return data


def shred_file(path):
    """Overwrite with random bytes, fsync, unlink. On copy-on-write or
    journaling filesystems and SSDs overwriting is best-effort; the unlink
    is what matters most, and the file was 0600 throughout."""
    try:
        size = os.path.getsize(path)
        with open(path, 'r+b', buffering=0) as fh:
            for _ in range(2):
                fh.seek(0)
                fh.write(os.urandom(max(size, 1)))
                os.fsync(fh.fileno())
    finally:
        os.unlink(path)


class Command(BaseCommand):
    help = 'Plan / configure an Office editor instance (see docs/office/INSTALL.md).'

    def add_arguments(self, parser):
        parser.add_argument('--plan', action='store_true')
        parser.add_argument('--install', action='store_true',
                            help='Show how to run the editor installer (Django installs nothing).')
        parser.add_argument('--provider', choices=sorted(install_guidance.PROVIDERS), default='onlyoffice')
        parser.add_argument('--edition', choices=sorted(install_guidance.EDITIONS), default='')
        parser.add_argument('--mode', choices=['same-server', 'separate-server', 'existing-service'],
                            default='separate-server')
        parser.add_argument('--editor-host', default='')
        parser.add_argument('--app-url', default='', help='clientst0r address the editor reaches.')
        parser.add_argument('--tls', choices=sorted(install_guidance.TLS_MODES), default='existing-cert')
        parser.add_argument('--instance', type=int)
        parser.add_argument('--name', default='')
        parser.add_argument('--secret-file')
        parser.add_argument('--import-secret', metavar='FILE')
        parser.add_argument('--set-secret', type=int, metavar='INSTANCE_ID')
        parser.add_argument('--verify-tls', type=int, metavar='INSTANCE_ID')

    def handle(self, *args, **opts):
        if opts['import_secret']:
            return self._import(opts['import_secret'], opts['instance'], opts['name'])
        if opts['set_secret']:
            inst = self._instance(opts['set_secret'])
            if not opts['secret_file']:
                raise CommandError('--secret-file is required')
            inst.shared_secret = _read_secret_file(opts['secret_file'])
            inst.health_status = 'unknown'
            inst.save(update_fields=['shared_secret', 'health_status', 'updated_at'])
            audit.log('settings_change', object_type='office.instance', object_id=inst.pk,
                      object_repr=inst.name,
                      description=f'Set the shared secret of {inst.name} from the CLI (value not logged)')
            self.stdout.write(self.style.SUCCESS(f'Secret stored (encrypted) for {inst.name}.'))
            return
        if opts['verify_tls']:
            inst = self._instance(opts['verify_tls'])
            inst.verify_tls = True
            inst.save(update_fields=['verify_tls', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(f'TLS verification is on for {inst.name}.'))
            return
        instance = self._instance(opts['instance']) if opts['instance'] else None
        guide = install_guidance.build(opts['provider'], opts['mode'].replace('-', '_'),
                                       instance=instance, editor_host=opts['editor_host'],
                                       app_url=opts['app_url'], edition=opts['edition'],
                                       tls=opts['tls'])
        if opts['install']:
            self.stdout.write('Django never installs packages or runs root commands. Install the '
                              f'editor by running {install_guidance.EDITOR_INSTALLER} as root on the '
                              'editor host (this server for same-server). Commands:\n')
            for title, cmd in guide['commands']:
                self.stdout.write(f'# {title}\n{cmd}\n')
            for note in guide['notes']:
                self.stdout.write(f'Note: {note}')
            self.stdout.write('\nNothing was installed by this command.')
            return
        self.stdout.write(f"{guide['provider_label']} — {guide['mode_label']}\n")
        for title, text in guide['flows']:
            self.stdout.write(f'  {title}: {text}')
        for title, items in guide['checklist']:
            self.stdout.write(f'\n{title}')
            for i, item in enumerate(items, 1):
                self.stdout.write(f'  {i}. {item}')
        if guide['commands']:
            self.stdout.write('\nCommands')
            for title, cmd in guide['commands']:
                self.stdout.write(f'  # {title}\n  {cmd}')
        for note in guide['notes']:
            self.stdout.write(f'\nNote: {note}')

    def _import(self, path, instance_id, name):
        from office.forms import _check_url
        from django import forms
        data = parse_import_file(path)
        provider = data['PROVIDER']
        with transaction.atomic():
            if instance_id:
                inst = self._instance(instance_id)
                if inst.provider != provider:
                    raise CommandError(f'{inst.name} is a {inst.get_provider_display()} instance; '
                                       f'the file is for {dict(PROVIDER_CHOICES)[provider]}.')
                inst.shared_secret = data['SECRET']
                inst.health_status, inst.health_detail, inst.last_check_at = 'unknown', '', None
                inst.save(update_fields=['shared_secret', 'health_status', 'health_detail',
                                         'last_check_at', 'updated_at'])
                created = False
            else:
                mode = data.get('MODE', '')
                if mode not in dict(EditorInstance.MODE_CHOICES):
                    mode = 'separate_server'
                urls = {}
                try:
                    for key, field, label in (('BROWSER_URL', 'browser_url', 'Browser URL'),
                                              ('INTERNAL_URL', 'internal_url', 'Internal URL'),
                                              ('CALLBACK_URL', 'callback_base_url', 'Callback URL')):
                        urls[field] = _check_url(data.get(key, ''), mode, label) or ''
                except forms.ValidationError as e:
                    raise CommandError('; '.join(e.messages))
                if not urls['browser_url'] or not urls['callback_base_url']:
                    raise CommandError('The import file lacks the browser or callback URL.')
                name = (name or data.get('NAME') or install_guidance.clean_host(urls['browser_url']))[:100]
                if EditorInstance.objects.filter(name=name).exists():
                    raise CommandError(f'An instance named {name!r} exists. Use --instance N to set '
                                       f'its secret, or --name to pick another name.')
                inst = EditorInstance.objects.create(
                    provider=provider, name=name, mode=mode, shared_secret=data['SECRET'],
                    enabled=False, shared=True, **urls)
                created = True
            audit.log('settings_change', object_type='office.instance', object_id=inst.pk,
                      object_repr=inst.name,
                      description=f'{"Created" if created else "Updated"} Office editor instance '
                                  f'{inst.name} from an installer import file (secret not logged)',
                      extra={'changed': ['shared_secret (value not logged)'] +
                             (['provider', 'mode', 'browser_url', 'internal_url', 'callback_base_url']
                              if created else [])})
        data.clear()
        try:
            shred_file(path)
        except OSError as e:
            self.stderr.write(self.style.ERROR(
                f'The secret was stored, but {path} could not be removed ({e.strerror}). '
                f'Delete it now: shred -u {path}'))
            raise SystemExit(1)
        verb = 'Created disabled instance' if created else 'Stored the secret for'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {inst.name} (id {inst.pk}). {path} was shredded.\n'
            f'Next: Settings → Integrations → Office Documents → {inst.name}: Health check, '
            f'Diagnostics, round-trip test, then enable it.'))

    def _instance(self, pk):
        inst = EditorInstance.objects.filter(pk=pk).first()
        if inst is None:
            raise CommandError(f'No Office editor instance {pk}.')
        return inst
