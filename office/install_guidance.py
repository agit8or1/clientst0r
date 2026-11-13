"""Install guidance: a checklist and the commands an administrator runs.

Django never runs shell commands for this. The page shows what to run; the
administrator runs it on the right machine with their own privileges.

  * ``scripts/office/install-editor.sh`` installs ONLYOFFICE Docs or
    Collabora Online on the editor host (this server or a separate VM):
    preflight, verified vendor repository, pinned + held package, editor
    configuration for clientst0r only, a dedicated Nginx server block, a
    generated secret in a root-only file, health check.
  * ``manage.py office_setup --import-secret FILE`` (run as the app user on
    the clientst0r server) reads the one-time import file the installer
    writes, stores the secret encrypted and shreds the file.
  * ``manage.py office_sessions --drain N`` before an editor upgrade or a
    provider switch.

Every value placed in a command is validated (host names, URLs rebuilt from
validated parts, ids, provider keys, user names) and shell-quoted. Secrets
never appear in a command or URL: the installer generates the secret into a
root-only file, and the import reads a 0600 file.
"""
from __future__ import annotations

import hashlib
import pwd
import os
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
EDITIONS = {
    'collabora-code': 'CODE (development edition: evaluation and testing only)',
    'collabora-online': 'Collabora Online (licensed subscription)',
}
TLS_MODES = {
    'existing-cert': 'Use a certificate I already have',
    'certbot': "Get a Let's Encrypt certificate (public DNS needed)",
    'none-behind-proxy': 'No TLS here: a proxy in front terminates it',
}
EDITOR_INSTALLER = 'scripts/office/install-editor.sh'
INSTALLER_COPY = '/root/clientst0r-install-editor.sh'
IMPORT_DIR = '/var/lib/clientst0r-office-import'
EDITOR_SECRET_FILE = '/etc/clientst0r-office/secret'
SECRET_FILE = '/root/clientst0r-office-secret'
GITHUB_REPO = 'agit8or1/clientst0r'
ALLOWED_SIGNERS = '/etc/clientst0r/allowed_signers'

_HOST_RE = re.compile(r'^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)'
                      r'(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$')
_USER_RE = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
_TAG_RE = re.compile(r'^\d{1,4}\.\d{1,4}\.\d{1,6}$')


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


def clean_origin_url(url) -> str:
    """https://host[:port]/ rebuilt from validated parts, or ''."""
    try:
        parts = urlsplit(url or '')
        port = parts.port
    except ValueError:
        return ''
    host = clean_host(parts.hostname or '')
    if parts.scheme != 'https' or not host:
        return ''
    return f'https://{host}{":%d" % port if port and port != 443 else ""}/'


def _installer_path() -> Path:
    return Path(settings.BASE_DIR) / EDITOR_INSTALLER


def _installer_present() -> bool:
    return _installer_path().is_file()


def installer_sha256() -> str:
    try:
        return hashlib.sha256(_installer_path().read_bytes()).hexdigest()
    except OSError:
        return ''


def _app_user() -> str:
    try:
        name = pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        return ''
    return name if _USER_RE.match(name) and name != 'root' else ''


def _release_tag() -> str:
    from config.version import VERSION
    return f'v{VERSION}' if _TAG_RE.match(VERSION or '') else ''


def build(provider, mode, *, instance=None, editor_host='', app_url='', edition='',
          tls='', private_ca=False):
    provider = provider if provider in PROVIDERS else 'onlyoffice'
    mode = mode if mode in MODES else 'separate_server'
    tls = tls if tls in TLS_MODES else 'existing-cert'
    if provider == 'collabora':
        edition = edition if edition in EDITIONS else 'collabora-code'
    else:
        edition = 'onlyoffice'
    label = PROVIDERS[provider]
    editor_host = clean_host(editor_host) or (_host_of(instance.browser_url) if instance else '')
    app_origin = (clean_origin_url(instance.callback_base_url) if instance else '') or clean_origin_url(app_url)
    app_host = _host_of(app_origin)
    shown_editor = editor_host or 'docs.example.com'
    shown_app = app_host or 'clientst0r.example.com'
    shown_origin = app_origin or f'https://{shown_app}/'
    q = shlex.quote
    base = Path(settings.BASE_DIR)
    manage = f'{q(str(base / "venv" / "bin" / "python"))} {q(str(base / "manage.py"))}'
    app_user = _app_user()
    tag = _release_tag()

    flows = [
        ('Browser → editor', f'Users\' browsers load the editor from https://{shown_editor} '
                             f'(HTTPS and WebSockets, port 443).'),
        ('Editor → clientst0r', f'The editor downloads files and sends saves to '
                                f'{shown_origin}office/api/… (HTTPS, port 443).'),
        ('clientst0r → editor', f'clientst0r checks health, fetches discovery and saved files from '
                                f'the editor\'s internal or browser address only (HTTPS, port 443; '
                                f'loopback for an ONLYOFFICE on this server).'),
    ]

    checklist = []
    if mode == 'same_server':
        checklist.append(('Before you start', [
            'Spare capacity beyond what clientst0r uses. The installer\'s preflight checks CPU, '
            'memory and disk with headroom for clientst0r and refuses when short: use a '
            'separate VM then.',
            f'A dedicated HTTPS host name for the editor (e.g. {shown_editor}) pointing at '
            'this server. It must not be clientst0r\'s own host name.',
            'Nginx on this server keeps serving clientst0r unchanged. The installer adds one '
            'server block for the editor host name only and never edits clientst0r\'s site, '
            'its app directory or .env.',
            'The editor runs as its own system service and user, listening on loopback; Nginx '
            'proxies the dedicated host name to it.',
        ]))
    elif mode == 'separate_server':
        checklist.append(('Editor VM', [
            'Ubuntu 22.04/24.04 or Debian 12, 64-bit. ONLYOFFICE: at least 2 cores, 2 GB RAM '
            '(more is better), 4 GB swap, 40 GB disk. The preflight checks these.',
            f'DNS name {shown_editor} on your LAN/VPN, and a certificate for it '
            '(public CA, or your private CA — paste that CA under "CA bundle" in clientst0r).',
            f'Firewall: allow 443/tcp to the VM from users\' networks and from {shown_app}; '
            f'allow the VM to reach {shown_app} on 443/tcp. Nothing else inbound '
            '(see docs/office/INSTALL.md for ufw rules).',
        ]))
    else:
        checklist.append(('Existing service', [
            f'Note the editor\'s browser address (https://{shown_editor}) and, if '
            'clientst0r reaches it differently, its internal address.',
            'Get the shared secret (ONLYOFFICE JWT secret) from whoever runs the service.',
            f'Ask them to allow {shown_app} as a WOPI host / callback origin, and to allow the '
            'editor to fetch from clientst0r\'s address.',
            'Licensing: use an edition licensed for your number of users. Collabora '
            'CODE is for evaluation and development only.',
        ]))
    if mode != 'existing_service':
        tls_item = {
            'existing-cert': f'Certificate and key for {shown_editor} at '
                             f'/etc/ssl/clientst0r-office/{shown_editor}.crt and .key on the editor host.',
            'certbot': f'{shown_editor} resolves publicly and port 80 reaches the editor host '
                       f'(Let\'s Encrypt HTTP challenge). Replace the e-mail in the command.',
            'none-behind-proxy': f'Your proxy serves https://{shown_editor} and forwards to port 80 '
                                 'of the editor host, with WebSocket upgrade.',
        }[tls]
        items = [tls_item]
        if provider == 'onlyoffice':
            items.append('ONLYOFFICE needs ttf-mscorefonts-installer: the install command accepts '
                         'the Microsoft core fonts EULA (--accept-mscorefonts-eula). Read it first.')
        if edition == 'collabora-online':
            items.append('Collabora Online subscription: put your repository URL in a root-only '
                         'file (/root/collabora-repo-url, chmod 600) and set the exact package versions '
                         'in the command (from your subscription repository).')
        if edition == 'collabora-code':
            items.append('CODE is Collabora\'s development edition: evaluation and testing only, '
                         'not for production.')
        if private_ca:
            items.append('clientst0r\'s certificate is from a private CA: copy that CA certificate '
                         'to /root/clientst0r-ca.pem on the editor host so the editor trusts clientst0r.')
        checklist.append(('Installer prerequisites', items))
    checklist.append(('In clientst0r', [
        'Settings → Integrations → Office Documents → Add instance: provider, mode, '
        'browser address, internal address (optional), callback address — or import the '
        'installer\'s one-time file (below), which fills them in.',
        'The shared secret: import it, or paste it into the form (stored encrypted, never shown again).',
        'Paste your private CA under "CA bundle" if the editor certificate is not from a public CA. '
        'TLS verification cannot be switched off in the web UI.',
        'Run Health check, then Diagnostics, then "Run round-trip test".',
        'Enable the instance and choose whether it is shared or dedicated to organizations.',
    ]))

    commands = []
    notes = []
    if mode in ('same_server', 'separate_server') and _installer_present():
        flag_mode = 'same-server' if mode == 'same_server' else 'separate-server'
        args = ['--provider', edition, '--mode', flag_mode, '--hostname', shown_editor,
                '--clientstor-url', shown_origin, '--tls', tls]
        if tls == 'certbot':
            args += ['--certbot-email', 'admin@example.com']
        if private_ca:
            args += ['--ca-file', '/root/clientst0r-ca.pem']
        if edition == 'collabora-online':
            args += ['--repo-url-file', '/root/collabora-repo-url',
                     '--version', 'COOLWSD_VERSION', '--brand-version', 'BRAND_VERSION']
        if mode == 'same_server' and app_user:
            args += ['--app-user', app_user]
        run_args = ' '.join(q(a) for a in args)
        installer = q(INSTALLER_COPY)
        if mode == 'same_server':
            if tag:
                commands.append((
                    'Copy the installer from this release\'s signed tag (as your admin user)',
                    f'git -C {q(str(base))} -c gpg.ssh.allowedSignersFile={ALLOWED_SIGNERS} '
                    f'verify-tag {q(tag)} && git -C {q(str(base))} show '
                    f'{q(tag + ":" + EDITOR_INSTALLER)} | sudo install -m 0700 -o root -g root '
                    f'/dev/stdin {installer}'))
            else:
                commands.append(('Copy the installer (as your admin user)',
                                 f'sudo install -m 0700 -o root -g root {q(str(_installer_path()))} {installer}'))
        else:
            sha = installer_sha256()
            src = (f'https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}/{EDITOR_INSTALLER}'
                   if tag else '')
            if src and sha:
                commands.append((
                    'On the editor VM: download the installer and check it',
                    f'curl -fsSL -o {installer} {q(src)} && echo {q(sha + "  " + INSTALLER_COPY)} '
                    f'| sha256sum -c - && chmod 700 {installer}'))
                notes.append('If the checksum does not match, this clientst0r is not running a '
                             f'release build: copy {EDITOR_INSTALLER} from this server to the VM '
                             '(scp) instead.')
        on = 'On this server' if mode == 'same_server' else 'On the editor VM'
        commands.append((f'{on}: preflight only (changes nothing)', f'sudo bash {installer} {run_args} --preflight-only'))
        commands.append((f'{on}: dry run (prints every action, changes nothing)',
                         f'sudo bash {installer} {run_args} --dry-run'))
        install_args = run_args + (' --accept-mscorefonts-eula' if provider == 'onlyoffice' else '')
        commands.append((f'{on}: install', f'sudo bash {installer} {install_args}'))
        import_file = f'{IMPORT_DIR}/import-{shown_editor}.env'
        inst_arg = f' --instance {int(instance.pk)}' if instance is not None else ''
        if mode == 'separate_server':
            commands.append(('On the clientst0r server: fetch the one-time import file (holds the secret)',
                             f'scp root@{shown_editor}:{q(import_file)} ./office-import.env && '
                             f'chmod 600 ./office-import.env && ssh root@{shown_editor} '
                             f'shred -u {q(import_file)}'))
            import_path = './office-import.env'
        else:
            import_path = import_file
        user_prefix = f'sudo -u {q(app_user)} ' if app_user and mode == 'same_server' else ''
        commands.append(('On the clientst0r server, as the app user: import the secret (shreds the file)',
                         f'{user_prefix}{manage} office_setup --import-secret {q(import_path)}{inst_arg}'))
        notes.append(f'The installer writes the secret only to {EDITOR_SECRET_FILE} (root, 0600) and '
                     'the one-time import file. It never prints it. To paste it into the form '
                     f'instead: sudo cat {EDITOR_SECRET_FILE}')
        notes.append('Already have an instance and a secret in a file you own (chmod 600)? '
                     f'{manage} office_setup --set-secret <instance id> --secret-file FILE')
        if edition == 'collabora-online':
            notes.append('Replace COOLWSD_VERSION and BRAND_VERSION with the exact versions from your '
                         'subscription repository (apt-cache madison coolwsd collabora-online-brand).')
        notes.append('Upgrades are explicit and never part of clientst0r updates: drain first '
                     f'({manage} office_sessions --drain <instance id>), then '
                     f'sudo bash {installer} --upgrade --version X --confirm-drained.')
    elif mode in ('same_server', 'separate_server'):
        notes.append(f'The editor installer ({EDITOR_INSTALLER}) is missing from this installation. '
                     f'Install {label} following its official packages, then connect it here.')
    else:
        notes.append('Nothing to install. Fill in the instance form and run the diagnostics. '
                     f'A secret saved in a file you own (chmod 600) can be stored with: '
                     f'{manage} office_setup --set-secret <instance id> --secret-file FILE')
    return {
        'provider': provider, 'provider_label': label, 'mode': mode, 'mode_label': MODES[mode],
        'flows': flows, 'checklist': checklist, 'commands': commands, 'notes': notes,
        'editor_host': editor_host, 'edition': edition, 'tls': tls, 'private_ca': bool(private_ca),
    }


MANAGED_COPY_DIR = '/root/clientst0r-office-managed'


def managed_commands(*, app_url='', office_host='', deployment_id='', engine='onlyoffice',
                     layouts=('dedicated',), tls='existing-cert'):
    """Root setup for the managed local editor (docs/office/MANAGED_LOCAL.md).

    engine: 'onlyoffice' | 'collabora' (Collabora CODE). layouts: the helper's
    allowed layouts ('dedicated' and/or, Collabora only, 'same-host'). tls:
    'existing-cert' | 'certbot' | 'upstream' (TLS ends on a device in front of
    this server).

    The installer and the helper it installs as root are taken from this
    release's signed tag into a root-owned directory, never run from the app
    directory (the app user can write there)."""
    base = Path(settings.BASE_DIR)
    q = shlex.quote
    tag = _release_tag()
    origin = clean_origin_url(app_url) or 'https://clientst0r.example.com/'
    engine = engine if engine in ('onlyoffice', 'collabora') else 'onlyoffice'
    layouts = [l for l in (layouts or ()) if l in ('dedicated', 'same-host')] or ['dedicated']
    if engine == 'onlyoffice':
        layouts = ['dedicated']
    host = clean_host(office_host) or ('office.example.com' if 'dedicated' in layouts else '')
    dep = deployment_id if re.match(r'^[a-z0-9][a-z0-9-]{1,40}$', deployment_id or '') else 'my-deployment'
    app_user = _app_user()
    args = ['--provider', engine, '--mode', 'managed-local']
    if layouts != ['dedicated']:
        args += ['--layouts', ','.join(layouts)]
    if host:
        args += ['--hostname', host]
    args += ['--clientstor-url', origin, '--deployment-id', dep]
    if tls == 'upstream':
        args += ['--tls', 'upstream']
    elif tls == 'certbot':
        args += ['--tls', 'certbot', '--certbot-email', 'admin@example.com']
    elif host:
        args += ['--tls', 'existing-cert', '--cert-file', f'/etc/ssl/certs/{host}.pem',
                 '--key-file', f'/etc/ssl/private/{host}.key']
    else:
        args += ['--tls', 'upstream']
    if app_user:
        args += ['--app-user', app_user]
    run_args = ' '.join(q(a) for a in args)
    script = f'{MANAGED_COPY_DIR}/scripts/office/install-editor.sh'
    commands = []
    if tag:
        commands.append((
            "Copy the installer and the Office service helper from this release's signed tag",
            f'git -C {q(str(base))} -c gpg.ssh.allowedSignersFile={ALLOWED_SIGNERS} verify-tag {q(tag)} '
            f'&& sudo install -d -m 0700 {MANAGED_COPY_DIR} && git -C {q(str(base))} archive {q(tag)} '
            f'scripts/office deploy/office-helper | sudo tar -x -C {MANAGED_COPY_DIR}'))
    else:
        commands.append(('Copy the installer and the Office service helper (not a release build)',
                         f'sudo install -d -m 0700 {MANAGED_COPY_DIR} && sudo cp -r '
                         f'{q(str(base / "scripts/office"))} {q(str(base / "deploy/office-helper"))} '
                         f'{MANAGED_COPY_DIR}/  # then fix the layout to scripts/office + deploy/office-helper'))
    commands.append(('Preflight only (changes nothing)', f'sudo bash {script} {run_args} --preflight-only'))
    commands.append(('Dry run (prints every action)', f'sudo bash {script} {run_args} --dry-run'))
    commands.append(('Set up (Docker only if absent: add --install-docker)', f'sudo bash {script} {run_args}'))
    return commands
