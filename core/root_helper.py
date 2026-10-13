"""
App side of the root helper (v3.17.597).

Every root action the app takes goes through
/usr/local/sbin/clientst0r-root-helper, which checks its arguments and is
the only thing the app user may run as root without a password. See
deploy/root-helper/clientst0r-root-helper for why.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from django.conf import settings

HELPER_PATH = '/usr/local/sbin/clientst0r-root-helper'
SUDO = '/usr/bin/sudo'
GUNICORN_UNIT = '/etc/systemd/system/clientst0r-gunicorn.service'


def bootstrap_script() -> Path:
    return Path(settings.BASE_DIR) / 'deploy' / 'root-helper' / 'install-root-helper.sh'


def bootstrap_command() -> str:
    return f'sudo bash {bootstrap_script()}'


def is_installed() -> bool:
    """Present, root-owned and not writable by anyone else."""
    try:
        st = os.stat(HELPER_PATH)
    except OSError:
        return False
    return st.st_uid == 0 and not st.st_mode & 0o022


def needs_bootstrap() -> bool:
    """A native (systemd) install that has not had the one-time setup yet.
    Docker installs have no sudo and no systemd units, so never."""
    if os.path.exists('/.dockerenv') or not os.path.exists(GUNICORN_UNIT):
        return False
    return not is_installed()


def run(args, timeout=120):
    """Run the helper with `args`. Returns a CompletedProcess, or None when
    the helper is not installed (callers then use their legacy path)."""
    if not is_installed():
        return None
    return subprocess.run(
        [SUDO, '-n', HELPER_PATH, *args],
        capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def bootstrap_with_password(password: str, timeout=300):
    """Run the one-time install with the operator's sudo password.

    Returns (ok, output). `-k` discards any cached sudo credential so the
    password typed is the one checked; `-p ''` keeps the prompt out of the
    output.
    """
    script = bootstrap_script()
    if not script.is_file():
        return False, f'{script} is missing'
    try:
        result = subprocess.run(
            [SUDO, '-S', '-k', '-p', '', '/bin/bash', str(script)],
            input=password + '\n', capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, 'Setup timed out.'
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0 and is_installed(), output
