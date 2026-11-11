"""Trusted CLI for Office editor setup. Run by an administrator, never by Django.

    manage.py office_setup --plan --provider onlyoffice --mode same-server \\
        --editor-host docs.example.com [--instance N] [--secret-file PATH]
    manage.py office_setup --set-secret N --secret-file PATH
    manage.py office_setup --verify-tls N

--plan          print the checklist the Settings page shows (no changes).
--set-secret    store the secret read from a root-only file on instance N
                (the secret never appears on a command line or in a URL).
--verify-tls    switch TLS verification back on for instance N (it cannot be
                switched off from the web UI, and this command has no way to
                switch it off either).

OPS HOOK: package installation for "install on this server" is not part of
this command yet. --install is reserved for the installer work and currently
exits with status 2 after printing the plan, so nothing pretends to have
installed an editor.
"""
import os
import stat

from django.core.management.base import BaseCommand, CommandError

from office import install_guidance
from office.models import EditorInstance, secret_problem


def _read_secret_file(path):
    try:
        st = os.stat(path)
    except OSError as e:
        raise CommandError(f'Cannot read {path}: {e.strerror}')
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CommandError(f'{path} must be readable by its owner only (chmod 600).')
    with open(path, 'r', encoding='utf-8') as fh:
        value = fh.read().strip()
    problem = secret_problem(value)
    if problem:
        raise CommandError(problem)
    return value


class Command(BaseCommand):
    help = 'Plan / configure an Office editor instance (see docs/OFFICE_DOCUMENTS.md).'

    def add_arguments(self, parser):
        parser.add_argument('--plan', action='store_true')
        parser.add_argument('--install', action='store_true',
                            help='Reserved for the installer; not implemented in this version.')
        parser.add_argument('--provider', choices=sorted(install_guidance.PROVIDERS), default='onlyoffice')
        parser.add_argument('--mode', choices=['same-server', 'separate-server', 'existing-service'],
                            default='separate-server')
        parser.add_argument('--editor-host', default='')
        parser.add_argument('--instance', type=int)
        parser.add_argument('--secret-file')
        parser.add_argument('--set-secret', type=int, metavar='INSTANCE_ID')
        parser.add_argument('--verify-tls', type=int, metavar='INSTANCE_ID')

    def handle(self, *args, **opts):
        if opts['set_secret']:
            inst = self._instance(opts['set_secret'])
            if not opts['secret_file']:
                raise CommandError('--secret-file is required')
            inst.shared_secret = _read_secret_file(opts['secret_file'])
            inst.health_status = 'unknown'
            inst.save(update_fields=['shared_secret', 'health_status', 'updated_at'])
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
                                       instance=instance, editor_host=opts['editor_host'])
        self.stdout.write(f"{guide['provider_label']} — {guide['mode_label']}\n")
        for title, text in guide['flows']:
            self.stdout.write(f'  {title}: {text}')
        for title, items in guide['checklist']:
            self.stdout.write(f'\n{title}')
            for i, item in enumerate(items, 1):
                self.stdout.write(f'  {i}. {item}')
        for note in guide['notes']:
            self.stdout.write(f'\nNote: {note}')
        if opts['install']:
            self.stderr.write('\n--install is not implemented in this version: nothing was installed.')
            raise SystemExit(2)

    def _instance(self, pk):
        inst = EditorInstance.objects.filter(pk=pk).first()
        if inst is None:
            raise CommandError(f'No Office editor instance {pk}.')
        return inst
