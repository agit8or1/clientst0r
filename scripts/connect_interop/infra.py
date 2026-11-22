"""Process management for the interoperability harness: throwaway
installations served by gunicorn over HTTPS on 127.0.0.1."""
from __future__ import annotations

import base64
import json
import os
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PY = os.path.join(REPO, 'venv', 'bin', 'python')
GUNICORN = os.path.join(REPO, 'venv', 'bin', 'gunicorn')


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Network:
    """The harness's resolver / NAT file (netshim reads it on every lookup)."""

    def __init__(self, path):
        self.path = path
        self.data = {'hosts': {}, 'nat': {}, 'ports': {}, 'unreachable': []}

    def save(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)


class Installation:
    def __init__(self, run_dir, label, sim_ip, source_alias, net: Network, pki: dict, workers=2):
        self.label, self.sim_ip, self.source_alias, self.net, self.pki = label, sim_ip, source_alias, net, pki
        self.dir = os.path.join(run_dir, label)
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.port = free_port()
        self.host = f'{label}.interop.test'
        self.base = f'https://{self.host}'   # port 443, forwarded to self.port (netshim / browser)
        self.workers = workers
        self.proc = None
        self.cert = pki[label]
        self.secret = secrets.token_urlsafe(48)
        self.master = base64.b64encode(secrets.token_bytes(32)).decode()
        self.connect_enabled = False
        net.data['hosts'][self.host] = [sim_ip]
        net.data['nat'][source_alias] = sim_ip
        net.data['ports'][sim_ip] = self.port
        net.save()

    @property
    def db(self):
        return os.path.join(self.dir, 'db.sqlite3')

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DB_', 'AGIT8OR_', 'DJANGO_'))}
        env.update({
            'INTEROP_DIR': self.dir, 'INTEROP_PUBLIC_URL': self.base, 'INTEROP_NET_FILE': self.net.path,
            'INTEROP_SOURCE': self.source_alias, 'INTEROP_SECRET_KEY': self.secret, 'INTEROP_MASTER_KEY': self.master,
            'INTEROP_CONNECT_ENABLED': 'true' if self.connect_enabled else 'false',
            'DJANGO_SETTINGS_MODULE': 'interop_settings', 'PYTHONPATH': HERE + os.pathsep + REPO,
            'DB_ENGINE': 'sqlite3', 'PYTHONDONTWRITEBYTECODE': '1',
        })
        return env

    def manage(self, *args, timeout=600, check=True, input_text=None):
        r = subprocess.run([PY, os.path.join(REPO, 'manage.py'), *args], cwd=REPO, env=self.env(),
                           capture_output=True, text=True, timeout=timeout, input=input_text)
        if check and r.returncode != 0:
            raise RuntimeError(f'{self.label}: manage.py {" ".join(args)} failed:\n{r.stdout[-3000:]}\n'
                               f'{r.stderr[-3000:]}')
        return r

    def shell(self, code: str, timeout=300):
        """Run Python with Django set up for this installation; returns the
        JSON the code prints on its last line (harness setup only)."""
        r = subprocess.run([PY, '-c', 'import django; django.setup()\n' + code], cwd=REPO, env=self.env(),
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f'{self.label}: shell failed:\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}')
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else None

    def start(self, *, cert=None, ca=None):
        crt, key = cert or self.cert
        log = open(os.path.join(self.dir, 'logs', 'gunicorn.log'), 'ab')
        self.proc = subprocess.Popen(
            [GUNICORN, 'interop_wsgi:application', '--bind', f'127.0.0.1:{self.port}', '--workers',
             str(self.workers), '--worker-class', 'sync', '--timeout', '120', '--graceful-timeout', '5',
             '--certfile', crt, '--keyfile', key, '--chdir', REPO, '--config', '/dev/null',
             '--pid', os.path.join(self.dir, 'gunicorn.pid')],
            cwd=REPO, env=self.env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f'{self.label}: gunicorn exited ({self.proc.returncode}); see {log.name}')
            try:
                r = requests.get(f'https://127.0.0.1:{self.port}/health/', verify=ca or self.pki['ca'], timeout=5)
                if r.status_code < 500:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        raise RuntimeError(f'{self.label}: gunicorn did not become ready')

    def stop(self):
        if self.proc is None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait(timeout=10)
        self.proc = None

    def restart(self, **kw):
        self.stop()
        self.start(**kw)


def copy_db(src, dst):
    """SQLite backup API (never a file copy of a database)."""
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    with d:
        s.backup(d)
    s.close()
    d.close()


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, file=sys.stderr, flush=True)
