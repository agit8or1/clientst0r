"""Install guidance: a checklist and the command an administrator runs.

Django never runs shell commands for this. The page shows what to run, the
administrator runs it on the right machine with their own privileges.

OPS HOOK — the installers themselves are not part of this module:
  * ``manage.py office_setup`` (office/management/commands/office_setup.py)
    is the trusted CLI entry point on the clientst0r server. Today it prints
    this same checklist (``--plan``) and records/validates an instance; the
    package installation steps are left for the installer work.
  * ``scripts/office/install-editor.sh`` is the planned editor-only installer
    for a separate VM. ``EDITOR_INSTALLER`` below names it; until it exists
    the guidance says so instead of showing a command that cannot work.

Every value placed in a command is validated (host names, ids, provider
keys) and shell-quoted. Secrets never appear in a command or URL: commands
take ``--secret-file`` naming a root-only file the administrator creates.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

PROVIDERS = {'onlyoffice': 'ONLYOFFICE Docs', 'collabora': 'Collabora Online'}
MODES = {
    'same_server': 'Install the editor on this server',
    'separate_server': 'Install the editor on a separate VM / server',
    'existing_service': 'Connect an editor service that already runs',
}
EDITOR_INSTALLER = 'scripts/office/install-editor.sh'
SECRET_FILE = '/root/clientst0r-office-secret'

_HOST_RE = re.compile(r'^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)'
                      r'(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$')


def clean_host(value) -> str:
    """A DNS host name or '' — never anything a shell would interpret."""
    value = (value or '').strip().lower().rstrip('.')
    if value.startswith(('http://', 'https://')):
        value = urlsplit(value).hostname or ''
    return value if _HOST_RE.match(value) else ''


def _host_of(url):
    try:
        return clean_host(urlsplit(url or '').hostname or '')
    except ValueError:
        return ''


def _installer_present() -> bool:
    return (Path(settings.BASE_DIR) / EDITOR_INSTALLER).is_file()


def build(provider, mode, *, instance=None, editor_host='', app_url=''):
    provider = provider if provider in PROVIDERS else 'onlyoffice'
    mode = mode if mode in MODES else 'separate_server'
    label = PROVIDERS[provider]
    editor_host = clean_host(editor_host) or (_host_of(instance.browser_url) if instance else '')
    app_host = _host_of(app_url)
    shown_editor = editor_host or 'docs.example.com'
    shown_app = app_host or 'clientst0r.example.com'
    q = shlex.quote
    base = Path(settings.BASE_DIR)
    manage = f'{q(str(base / "venv" / "bin" / "python"))} {q(str(base / "manage.py"))}'

    flows = [
        ('Browser → editor', f'Users\' browsers load the editor from https://{shown_editor} '
                             f'(HTTPS and WebSockets on port 443).'),
        ('Editor → clientst0r', f'The editor downloads files and sends saves to '
                                f'https://{shown_app}/office/api/… (HTTPS, port 443).'),
        ('clientst0r → editor', f'clientst0r checks health, fetches discovery and saved files from '
                                f'the editor\'s internal or browser address only (HTTPS, port 443).'),
    ]

    checklist = []
    if mode == 'same_server':
        checklist.append(('Before you start', [
            'Spare capacity beyond what clientst0r uses: check the editor\'s published '
            'hardware requirements for your user count. If this server is short on CPU, '
            'memory or disk, use a separate VM instead.',
            f'A dedicated HTTPS host name for the editor (e.g. {shown_editor}) pointing at '
            'this server, with a certificate (public CA or your private CA).',
            'Ports 80/443 are served by this server\'s Nginx; the editor listens on '
            'localhost only and Nginx proxies the dedicated host name to it.',
            'The editor runs as its own system service and user, with no access to '
            'clientst0r\'s .env, database or media directory.',
        ]))
    elif mode == 'separate_server':
        checklist.append(('Editor VM', [
            'An Ubuntu LTS / Debian release the editor vendor supports, sized to the '
            'vendor\'s published hardware requirements.',
            f'DNS name {shown_editor} on your LAN/VPN, and a certificate for it '
            '(public CA, or your private CA — paste that CA under "CA bundle").',
            f'Firewall: allow 443/tcp from users\' networks and from {shown_app}; '
            f'allow the editor to reach {shown_app} on 443/tcp. Nothing else inbound.',
        ]))
    else:
        checklist.append(('Existing service', [
            f'Note the editor\'s browser address (https://{shown_editor}) and, if '
            'clientst0r reaches it differently, its internal address.',
            'Get the shared secret (ONLYOFFICE JWT secret / Collabora WOPI settings) from '
            'whoever runs the service.',
            f'Ask them to allow {shown_app} as a WOPI host / callback origin.',
            'Licensing: use an edition licensed for your number of users. Collabora '
            'CODE is for evaluation and development only.',
        ]))
    checklist.append(('In clientst0r', [
        'Settings → Integrations → Office Documents → Add instance: provider, mode, '
        'browser address, internal address (optional), callback address.',
        'Paste the shared secret into the form (stored encrypted). It is never shown again.',
        'Paste your private CA under "CA bundle" if the editor certificate is not from a public CA. '
        'TLS verification cannot be switched off in the web UI.',
        'Run Health check, then Diagnostics, then "Run round-trip test".',
        'Enable the instance and choose whether it is shared or dedicated to organizations.',
    ]))

    commands = []
    notes = []
    secret_prep = (f'sudo install -m 600 -o root -g root /dev/null {SECRET_FILE} && '
                   f'sudo editor {SECRET_FILE}')
    inst = ['--instance', str(int(instance.pk))] if instance is not None else []
    if mode == 'same_server':
        commands.append(('Create the secret file (paste the secret, save)', secret_prep))
        args = ['office_setup', '--plan', '--provider', provider, '--mode', 'same-server',
                '--editor-host', shown_editor, '--secret-file', SECRET_FILE] + inst
        commands.append(('Plan the installation on this server (run as root)',
                         f'sudo {manage} ' + ' '.join(q(a) for a in args)))
        notes.append('office_setup currently prints the plan and runs the preflight checks only; '
                     'package installation is performed by the installer step when it ships.')
    elif mode == 'separate_server':
        commands.append(('On the editor VM: create the secret file', secret_prep))
        if _installer_present():
            args = ['--provider', provider, '--hostname', shown_editor,
                    '--app-origin', f'https://{shown_app}', '--secret-file', SECRET_FILE]
            commands.append(('On the editor VM (as root)',
                             f'sudo bash {q(EDITOR_INSTALLER)} ' + ' '.join(q(a) for a in args)))
        else:
            notes.append(f'The editor-only installer ({EDITOR_INSTALLER}) is not included in this '
                         f'version. Install {label} on the VM following its official '
                         'packages for your OS, then connect it here.')
    else:
        notes.append('Nothing to install. Fill in the instance form and run the diagnostics.')
    return {
        'provider': provider, 'provider_label': label, 'mode': mode, 'mode_label': MODES[mode],
        'flows': flows, 'checklist': checklist, 'commands': commands, 'notes': notes,
        'editor_host': editor_host,
    }
