"""Client for browser_worker.py, which runs under its own Python.

The production venv does not need Playwright: ``--browser-python`` names
any interpreter that can ``import playwright`` (a separate venv, or the app
user's ``pip install --user playwright``). Without the option the harness
tries this interpreter, then ``python3`` on PATH.
"""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'browser_worker.py')


class BrowserError(Exception):
    pass


def probe_python(python, timeout=30):
    """(ok, detail) for an interpreter that should have Playwright."""
    if not python or not (os.path.isfile(python) or shutil.which(python)):
        return False, f'{python}: not found'
    try:
        r = subprocess.run([python, '-c', 'import playwright, importlib.metadata as m; '
                                          'print(m.version("playwright"))'],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f'{python}: {e}'
    if r.returncode != 0:
        return False, f'{python}: Playwright is not importable'
    return True, f'{python}: playwright {r.stdout.strip()}'


def find_python(explicit=None):
    candidates = [explicit] if explicit else [sys.executable, shutil.which('python3') or '']
    details = []
    for c in candidates:
        if not c:
            continue
        ok, detail = probe_python(c)
        if ok:
            return c, detail
        details.append(detail)
    return None, '; '.join(details) or 'no interpreter'


def chromium_present(explicit=None):
    if explicit:
        return os.path.isfile(explicit), explicit
    cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or os.path.expanduser('~/.cache/ms-playwright')
    try:
        found = [n for n in os.listdir(cache) if n.startswith(('chromium-', 'chromium_headless_shell-'))]
    except OSError:
        found = []
    return bool(found), (f'{cache}: {", ".join(sorted(found))}' if found
                         else f'no Chromium under {cache} (run: <browser python> -m playwright install chromium)')


class Browser:
    """One worker process. ``call(cmd, **kw)`` -> reply dict (raises
    BrowserError on {"ok": false} unless check=False)."""

    def __init__(self, python, *, redactor=None, timeout=900):
        self.python = python
        self.redactor = redactor
        self.timeout = timeout
        self.proc = subprocess.Popen([python, WORKER], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1)

    def call(self, cmd, check=True, timeout=None, **kw):
        if self.proc.poll() is not None:
            raise BrowserError('the browser worker has exited')
        self.proc.stdin.write(json.dumps(dict(kw, cmd=cmd)) + '\n')
        self.proc.stdin.flush()
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.proc.kill()
                raise BrowserError(f'browser worker did not answer {cmd} in time')
            ready, _, _ = select.select([self.proc.stdout], [], [], min(left, 5))
            if ready:
                line = self.proc.stdout.readline()
                if not line:
                    raise BrowserError(f'browser worker exited during {cmd}')
                break
        reply = json.loads(line)
        if self.redactor is not None:
            reply = self.redactor.obj(reply)
        if check and not reply.get('ok'):
            raise BrowserError(f'{cmd}: {reply.get("error")}')
        return reply

    def close(self):
        try:
            if self.proc.poll() is None:
                self.call('quit', check=False, timeout=60)
        except Exception:   # noqa: BLE001
            pass
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
