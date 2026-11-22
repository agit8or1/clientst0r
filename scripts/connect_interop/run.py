#!/usr/bin/env python3
"""Agit8or Connect / Quick Connect interoperability harness (increment G,
roadmap 79.23): two independently running Clientst0r installations, real
HTTPS on 127.0.0.1, a per-run test-only CA, the real code on both sides.

    cd <repo> && DB_ENGINE=sqlite3 venv/bin/python scripts/connect_interop/run.py \
        [--out DIR] [--keep] [--template-cache DIR]

What it does (see README-style notes in the report):
  * builds a throwaway CA + certificates, two installation directories
    (SQLite, media, logs, runtime) and secrets for this run only;
  * migrates one template database and copies it (SQLite backup API) to
    each installation before either has an identity, seeds two
    administrators with authenticator devices and two customers per side;
  * serves each with gunicorn over HTTPS on 127.0.0.1 (A: 3 workers,
    B: 2 workers) and drives every administrator step through the admin
    pages over HTTPS (requests sessions, CSRF, password + TOTP
    re-authentication), background work through the real management
    commands, and the protocol probes (replay, cross-tenant, rogue source)
    from a process with the installation's own code and keys;
  * writes report.json and report.md (each step, pass/fail, timestamps,
    evidence) under --out, labelled "local real-network (127.0.0.1, test
    CA)": not production, not an independent review;
  * stops every process and removes the run directory (unless --keep).

Nothing touches the deployment: no .env, no production database, no
nginx / firewall / systemd, nothing bound outside 127.0.0.1.
"""
from __future__ import annotations

import argparse
import hashlib
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import infra  # noqa: E402
import pki  # noqa: E402
from browser import Browser  # noqa: E402

LABEL = 'local real-network (127.0.0.1, test CA)'
SIM = {'a': '10.231.0.1', 'b': '10.231.0.2'}
ALIAS = {'a': '127.0.0.11', 'b': '127.0.0.12', 'rogue': '127.0.0.13'}
ROGUE_SIM = '10.231.0.13'
MOVED_SIM = '10.231.0.22'
PASSWORDS = {'admin1': 'Interop-Admin-1-pw!', 'admin2': 'Interop-Admin-2-pw!'}
SCOPES = ['connection:read', 'customers:read', 'events:publish']


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Abort(Exception):
    pass


class Report:
    def __init__(self):
        self.steps = []
        self.started = now_iso()
        self.meta = {}

    class _Step:
        def __init__(self, report, sid, title, critical):
            self.report, self.sid, self.title, self.critical = report, sid, title, critical
            self.detail = {}

        def __enter__(self):
            self.t0 = time.time()
            self.row = {'id': self.sid, 'title': self.title, 'started': now_iso(), 'result': 'running',
                        'detail': self.detail}
            self.report.steps.append(self.row)
            infra.log(f'[{self.sid}] {self.title}')
            return self

        def __exit__(self, et, ev, tb):
            self.row['ended'] = now_iso()
            self.row['seconds'] = round(time.time() - self.t0, 2)
            if et is None:
                self.row['result'] = 'pass'
                infra.log(f'[{self.sid}] PASS')
                return False
            self.row['result'] = 'fail'
            self.row['error'] = f'{et.__name__}: {ev}'[:2000]
            self.row['traceback'] = ''.join(traceback.format_exception(et, ev, tb))[-4000:]
            infra.log(f'[{self.sid}] FAIL {self.row["error"]}')
            if self.critical:
                raise Abort(self.sid) from ev
            return True   # recorded; continue with the next step

    def step(self, sid, title, critical=False):
        return Report._Step(self, sid, title, critical)

    def skip_rest(self, titles):
        for sid, title in titles:
            self.steps.append({'id': sid, 'title': title, 'result': 'skipped', 'started': now_iso(),
                               'ended': now_iso(), 'detail': {'reason': 'an earlier critical step failed'}})


def check(cond, msg, **ctx):
    if not cond:
        raise AssertionError(msg + (f' {json.dumps(ctx, default=str)[:1500]}' if ctx else ''))


# --- read-only evidence from an installation's database ------------------------------------

def q(inst, sql, params=()):
    con = sqlite3.connect(f'file:{inst.db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def conn_row(inst, pk=None, remote=None):
    if pk:
        rows = q(inst, 'SELECT * FROM connect_connections WHERE id = ?', (pk.replace('-', ''),))
    else:
        rows = q(inst, 'SELECT * FROM connect_connections WHERE remote_installation_id = ? ORDER BY created_at DESC',
                 (remote,))
    return rows[0] if rows else None


def uuid_text(hexid):
    h = hexid.replace('-', '')
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}'


def brief(row):
    keys = ('state', 'health', 'circuit', 'retry_step', 'security_block_code', 'last_error', 'next_check_at',
            'last_check_at', 'consecutive_fail', 'consecutive_ok', 'sas', 'direction', 'qc_revision')
    return {k: row.get(k) for k in keys} if row else None


# --- the harness --------------------------------------------------------------------------

class Harness:
    def __init__(self, args):
        self.args = args
        self.report = Report()
        self.run_dir = tempfile.mkdtemp(prefix='clientst0r-interop-', dir=args.work_dir)
        os.chmod(self.run_dir, 0o700)
        self.insts = {}
        self.b = {}        # (side, user) -> Browser
        self.ctx = {}

    # setup ---------------------------------------------------------------------------------
    def build(self):
        r = self.report
        with r.step('S01', 'Per-run test CA and certificates (127.0.0.1 listeners; trusted only explicitly)',
                    critical=True) as st:
            self.pki = pki.build(os.path.join(self.run_dir, 'pki'), {'a': 'a.interop.test', 'b': 'b.interop.test'})
            with open(self.pki['ca']) as f:
                self.ca_pem = f.read()
            st.detail['ca_sha256'] = hashlib.sha256(self.ca_pem.encode()).hexdigest()
            st.detail['system_trust_store_modified'] = False
        with r.step('S02', 'Two throwaway installations: separate SQLite databases, media, logs, runtime and '
                           'secrets', critical=True) as st:
            self.net = infra.Network(os.path.join(self.run_dir, 'net.json'))
            self.net.data['nat'][ALIAS['rogue']] = ROGUE_SIM
            self.insts['a'] = infra.Installation(self.run_dir, 'a', SIM['a'], ALIAS['a'], self.net, self.pki, workers=3)
            self.insts['b'] = infra.Installation(self.run_dir, 'b', SIM['b'], ALIAS['b'], self.net, self.pki, workers=2)
            template = self._template()
            for inst in self.insts.values():
                infra.copy_db(template, inst.db)
            st.detail['installations'] = {k: {'dir': i.dir, 'public_url': i.base, 'simulated_address': i.sim_ip,
                                              'loopback_source': i.source_alias, 'workers': i.workers,
                                              'listen': f'127.0.0.1:{i.port}'} for k, i in self.insts.items()}
        with r.step('S03', 'Seed administrators (password + confirmed TOTP device) and customers',
                    critical=True) as st:
            self.seed = {}
            for side, inst in self.insts.items():
                self.seed[side] = inst.shell(SEED_CODE % {'side': side.upper(), 'pw1': PASSWORDS['admin1'],
                                                          'pw2': PASSWORDS['admin2']})
            check(self.seed['a']['installation_id'] != self.seed['b']['installation_id'], 'identities differ')
            st.detail['identities'] = {k: v['installation_id'] for k, v in self.seed.items()}
            st.detail['customers'] = {k: v['orgs'] for k, v in self.seed.items()}

    def _template(self):
        """One migrated database without an identity, cached by migration set."""
        files = sorted(glob.glob(os.path.join(infra.REPO, '*', 'migrations', '0*.py')))
        h = hashlib.sha256()
        for p in files:
            h.update(p.encode())
            with open(p, 'rb') as f:
                h.update(f.read())
        cache_dir = self.args.template_cache or self.run_dir
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f'template-{h.hexdigest()[:16]}.sqlite3')
        if not os.path.exists(path):
            tmp = infra.Installation(self.run_dir, 'template', '10.231.0.250', '127.0.0.1', self.net, self.pki)
            tmp.manage('migrate', '--noinput', timeout=3600)
            ids = q(tmp, 'SELECT COUNT(*) AS n FROM connect_installation')[0]['n']
            check(ids == 0, 'template database must not hold an installation identity', n=ids)
            infra.copy_db(tmp.db, path + '.tmp')
            os.replace(path + '.tmp', path)
            self.net.data['hosts'].pop(tmp.host, None)
            self.net.save()
        return path

    def browsers(self):
        for side, inst in self.insts.items():
            for user in ('admin1', 'admin2'):
                br = Browser(inst, user, PASSWORDS[user], self.seed[side]['otp'][user], self.pki['ca'])
                br.login()
                self.b[(side, user)] = br
        self.by_host = {self.insts[s].host: self.b[(s, 'admin1')] for s in self.insts}

    def start_all(self, enabled):
        for inst in self.insts.values():
            inst.connect_enabled = enabled
            inst.restart()

    def cleanup(self):
        for inst in self.insts.values():
            try:
                inst.stop()
            except Exception as e:   # keep cleaning up
                infra.log(f'stop {inst.label}: {e}')
        if not self.args.keep:
            shutil.rmtree(self.run_dir, ignore_errors=True)

    # helpers -------------------------------------------------------------------------------
    def raw_get(self, side, path, *, source=ALIAS['a']):
        """One HTTPS request from a chosen loopback source alias (the harness
        NAT maps it to a simulated address), certificate verified."""
        import http.client
        import ssl
        inst = self.insts[side]
        ctx = ssl.create_default_context(cafile=self.pki['ca'])
        c = http.client.HTTPSConnection(inst.host, inst.port, context=ctx, timeout=30, source_address=(source, 0))
        # connect to 127.0.0.1 while verifying the certificate for inst.host
        import socket
        sock = socket.create_connection(('127.0.0.1', inst.port), 30, source_address=(source, 0))
        c.sock = ctx.wrap_socket(sock, server_hostname=inst.host)
        c.request('GET', path, headers={'Host': f'{inst.host}:{inst.port}', 'Accept': 'application/json'})
        resp = c.getresponse()
        body = resp.read()
        c.close()
        return resp.status, body

    def connect_shell(self, side, code):
        return self.insts[side].shell(SHELL_PRELUDE + code)

    def monitor(self, side, *, due_now=True):
        """One pass of the real monitor command. due_now: the harness moves
        the next check to now (the delay the app scheduled is recorded first)."""
        inst = self.insts[side]
        return inst.shell(MONITOR_CODE % {'due_now': due_now})


SEED_CODE = r'''
import json, secrets
from django.contrib.auth.models import User
from django_otp.plugins.otp_totp.models import TOTPDevice
from core.models import Organization
from connect import identity
from connect.models import InstallationIdentity
out = {'otp': {}}
for name, pw in (('admin1', '%(pw1)s'), ('admin2', '%(pw2)s')):
    u = User.objects.create_superuser(name, name + '@%(side)s.interop.test', pw)
    key = secrets.token_hex(20)
    TOTPDevice.objects.create(user=u, name='harness', key=key, confirmed=True)
    out['otp'][name] = key
orgs = []
for n in ('Acme', 'Globex'):
    o = Organization.objects.create(name=n + ' (%(side)s)', slug=n.lower() + '-%(side)s'.lower())
    orgs.append({'pk': o.pk, 'name': o.name})
out['orgs'] = orgs
ident = identity.get()
InstallationIdentity.objects.filter(pk=ident.pk).update(display_name='Interop %(side)s')
out['installation_id'] = str(ident.installation_id)
print(json.dumps(out))
'''

SHELL_PRELUDE = r'''
import json
from connect.models import Connection
def _conn():
    return Connection.objects.exclude(state__in=('revoked', 'failed')).order_by('-created_at').first()
'''

MONITOR_CODE = r'''
import json, io
from django.core.management import call_command
from django.utils import timezone
from connect.models import Connection
before = []
for c in Connection.objects.filter(state__in=('active', 'testing')):
    before.append({'id': str(c.pk), 'scheduled_delay_s': (c.next_check_at - c.last_check_at).total_seconds()
                   if c.next_check_at and c.last_check_at else None,
                   'next_check_at': c.next_check_at.isoformat() if c.next_check_at else None})
    if %(due_now)s and c.next_check_at:
        Connection.objects.filter(pk=c.pk).update(next_check_at=timezone.now())
buf = io.StringIO()
call_command('connect_monitor', budget=5, stdout=buf)
after = [{'id': str(c.pk), 'state': c.state, 'health': c.health, 'circuit': c.circuit, 'retry_step': c.retry_step,
          'consecutive_fail': c.consecutive_fail, 'consecutive_ok': c.consecutive_ok,
          'security_block_code': c.security_block_code, 'last_error': c.last_error,
          'next_check_at': c.next_check_at.isoformat() if c.next_check_at else None,
          'scheduled_delay_s': (c.next_check_at - c.last_check_at).total_seconds()
          if c.next_check_at and c.last_check_at else None}
         for c in Connection.objects.exclude(state__in=('revoked', 'failed'))]
print(json.dumps({'before': before, 'after': after, 'output': buf.getvalue()[-800:]}))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(infra.REPO, 'scripts', 'connect_interop', 'reports'))
    ap.add_argument('--work-dir', default=None, help='parent of the per-run directory (default: system temp)')
    ap.add_argument('--template-cache', default=None, help='keep the migrated template database here between runs')
    ap.add_argument('--keep', action='store_true', help='keep the run directory (databases, logs) afterwards')
    ap.add_argument('--stop-after', default='', help='stop after this step id (debugging)')
    args = ap.parse_args()
    import signal
    import scenario

    def _terminate(signum, frame):        # SIGTERM / SIGHUP: still stop the servers and clean up
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    h = Harness(args)
    rc = 1
    try:
        scenario.run(h)
    except Abort as e:
        infra.log(f'aborted at {e}')
    except KeyboardInterrupt:
        infra.log('interrupted')
    finally:
        h.cleanup()
        path = scenario.write_report(h, args.out)
        failed = [s for s in h.report.steps if s['result'] != 'pass']
        rc = 0 if not failed else 1
        infra.log(f'report: {path} ({len(h.report.steps) - len(failed)}/{len(h.report.steps)} passed)')
    return rc


if __name__ == '__main__':
    sys.exit(main())
