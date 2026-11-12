"""Snyk CLI version check, shared by Settings -> Snyk and the scheduler.

`check_versions()` finds the snyk binary, asks it for its version, and looks up
the newest release (`npm view snyk version` when npm is available, otherwise the
npm registry's metadata over HTTPS). The result is stored on SystemSetting so
the settings page can show it without running anything.

`run_scheduled_check()` is the daily task: it does nothing when Snyk is disabled
or the CLI is not installed, never raises, and e-mails superusers once per new
version through the same alert path the automated security scan uses.

Nothing here installs anything. Upgrading stays a manual superuser action
(`upgrade_snyk_cli`), and it installs exactly the version stored here.
"""
import glob
import logging
import os
import re
import subprocess

from django.conf import settings as django_settings
from django.utils import timezone

logger = logging.getLogger('core')

REGISTRY_URL = 'https://registry.npmjs.org/snyk/latest'
REGISTRY_TIMEOUT = 10
COMMAND_TIMEOUT = 10

# Plain MAJOR.MINOR.PATCH, no leading zeros, nothing else. Anything that goes
# into `npm install -g snyk@<version>` must match this (with fullmatch).
SEMVER_RE = re.compile(r'(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})')

_SYSTEM_PATHS = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


def is_valid_version(value):
    # fullmatch, not match + $: `$` also matches before a trailing newline.
    return isinstance(value, str) and bool(SEMVER_RE.fullmatch(value))


def is_newer(latest, installed):
    """True when `latest` is a strictly newer version than `installed`."""
    if not latest or not installed:
        return False
    try:
        from packaging.version import InvalidVersion, Version
        return Version(latest) > Version(installed)
    except (InvalidVersion, TypeError, ValueError):
        return False


def _project_home():
    return str(django_settings.BASE_DIR)


def find_command(cmd):
    """Find an executable: nvm node installs first, then PATH, then common dirs."""
    for path in glob.glob(f'{_project_home()}/.nvm/versions/node/*/bin/{cmd}'):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    for path_dir in os.environ.get('PATH', '').split(':'):
        if path_dir:
            full_path = os.path.join(path_dir, cmd)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                return full_path

    for path in (
        f'/usr/local/bin/{cmd}',
        f'/usr/bin/{cmd}',
        f'{_project_home()}/.local/bin/{cmd}',
        f'/opt/homebrew/bin/{cmd}',
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def command_env(binary_path):
    """Environment with the binary's own bin dir (nvm node) first on PATH."""
    env = os.environ.copy()
    env['PATH'] = f"{os.path.dirname(binary_path)}:{_SYSTEM_PATHS}:{env.get('PATH', '')}"
    return env


def installed_version(snyk_path):
    """Return (version, error) from `snyk --version`."""
    try:
        result = subprocess.run(
            [snyk_path, '--version'], capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT, env=command_env(snyk_path),
        )
    except Exception as e:
        return None, f'snyk --version failed: {e}'
    if result.returncode != 0:
        return None, f'snyk --version exit code {result.returncode}: {(result.stderr or "").strip()[:300]}'
    match = re.search(r'(\d+\.\d+\.\d+)', result.stdout or '')
    if not match:
        return None, 'snyk --version printed no version number'
    return match.group(1), None


def _latest_from_npm(npm_path):
    try:
        result = subprocess.run(
            [npm_path, 'view', 'snyk', 'version'], capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT, env=command_env(npm_path),
        )
    except Exception as e:
        return None, f'npm view failed: {e}'
    if result.returncode != 0:
        return None, f'npm view exit code {result.returncode}: {(result.stderr or "").strip()[:300]}'
    version = (result.stdout or '').strip()
    if not is_valid_version(version):
        return None, f'npm view returned an unexpected version: {version[:50]!r}'
    return version, None


def _latest_from_registry():
    import requests
    try:
        resp = requests.get(REGISTRY_URL, timeout=REGISTRY_TIMEOUT,
                            headers={'Accept': 'application/json'})
        resp.raise_for_status()
        version = resp.json().get('version')
    except Exception as e:
        return None, f'npm registry lookup failed: {e}'
    if not is_valid_version(version):
        return None, f'npm registry returned an unexpected version: {str(version)[:50]!r}'
    return version, None


def latest_version(npm_path=None):
    """Return (version, error) for the newest Snyk CLI release.

    Uses npm when it is installed, and the registry over HTTPS when npm is not
    on the server or its lookup fails.
    """
    npm_error = None
    if npm_path:
        version, npm_error = _latest_from_npm(npm_path)
        if version:
            return version, None
    version, reg_error = _latest_from_registry()
    if version:
        return version, None
    return None, '; '.join(e for e in (npm_error, reg_error) if e)


def check_versions(settings=None, save=True):
    """Run a full version check and store the result. Never raises.

    Returns a dict: installed_version, latest_version, update_available,
    snyk_path, npm_path, checked_at, error.
    """
    from core.models import SystemSetting

    result = {
        'installed_version': None, 'latest_version': None, 'update_available': False,
        'snyk_path': None, 'npm_path': None, 'checked_at': None, 'error': '',
    }
    errors = []
    try:
        if settings is None:
            settings = SystemSetting.get_settings()
        snyk_path = find_command('snyk')
        npm_path = find_command('npm')
        result['snyk_path'], result['npm_path'] = snyk_path, npm_path

        if snyk_path:
            inst, err = installed_version(snyk_path)
            result['installed_version'] = inst
            if err:
                errors.append(err)
        latest, err = latest_version(npm_path)
        result['latest_version'] = latest
        if err:
            errors.append(err)
    except Exception as e:  # pragma: no cover - defensive
        logger.exception('[snyk_cli] version check failed')
        errors.append(str(e))

    result['update_available'] = is_newer(result['latest_version'], result['installed_version'])
    result['error'] = '; '.join(errors)[:2000]
    result['checked_at'] = timezone.now()

    if save and settings is not None:
        _store(settings, result)
    return result


def _store(settings, result):
    try:
        settings.snyk_cli_installed_version = result['installed_version'] or ''
        # Keep the last known latest version when only the lookup failed, so
        # a registry hiccup does not hide an update the page already showed.
        if result['latest_version']:
            settings.snyk_cli_latest_version = result['latest_version']
        settings.snyk_cli_checked_at = result['checked_at']
        settings.snyk_cli_check_error = result['error']
        settings.save(update_fields=[
            'snyk_cli_installed_version', 'snyk_cli_latest_version',
            'snyk_cli_checked_at', 'snyk_cli_check_error',
        ])
    except Exception:
        logger.exception('[snyk_cli] could not store version check result')


def notify_if_new(settings):
    """E-mail superusers about a newer CLI, once per version.

    Returns the number of e-mails sent. `snyk_cli_notified_version` is only
    recorded once at least one message went out, so an install without SMTP
    gets the alert once it is configured.
    """
    latest = settings.snyk_cli_latest_version
    installed = settings.snyk_cli_installed_version
    if not is_newer(latest, installed):
        return 0
    if settings.snyk_cli_notified_version == latest:
        return 0

    from core.superuser_alerts import email_superusers

    site_name = settings.site_name or 'Client St0r'
    site_url = (settings.site_url or '').rstrip('/')
    subject = f'[{site_name}] Snyk CLI update available: {installed} → {latest}'
    lines = [
        f'Snyk CLI update available: {installed} → {latest}',
        '',
        'Nothing has been installed. To upgrade, open Settings → Snyk and use '
        '"Upgrade Snyk CLI".',
    ]
    if site_url:
        lines += ['', f'Settings → Snyk: {site_url}/core/settings/snyk/']
    lines += ['', '---', f'This is an automated alert from {site_name}. '
              'You get it once per new Snyk CLI version.']
    sent = email_superusers(subject, '\n'.join(lines), settings=settings, log_prefix='snyk_cli')
    if sent:
        settings.snyk_cli_notified_version = latest
        settings.save(update_fields=['snyk_cli_notified_version'])
    return sent


def run_scheduled_check():
    """Daily task body. Returns a short status string; never raises."""
    from core.models import SystemSetting
    try:
        settings = SystemSetting.get_settings()
        if not settings.snyk_enabled:
            return 'skipped: Snyk is disabled'
        if not find_command('snyk'):
            return 'skipped: Snyk CLI is not installed'
        result = check_versions(settings=settings)
        sent = 0
        if result['update_available']:
            sent = notify_if_new(settings)
        if result['error']:
            return f'checked with errors: {result["error"]}'
        if result['update_available']:
            return (f'update available: {result["installed_version"]} → '
                    f'{result["latest_version"]} ({sent} alert(s) sent)')
        return f'up to date ({result["installed_version"]})'
    except Exception as e:
        logger.exception('[snyk_cli] scheduled check failed')
        return f'failed: {e}'
