"""The resumable run state: one JSON file per run, written atomically.

    {
      "run_id": "...", "profile": "local", "engine": "collabora",
      "created_at": ..., "boot_id": "...",
      "options": {...},                 # the CLI options that shape the plan
      "fixtures": {...},                # ids of the test org/users/documents
      "facts": {...},                   # release id, digest, versions seen
      "steps": [{"key", "status", "started_at", "finished_at", "seconds",
                 "detail", "evidence", "resume"}, ...]
    }

Step status: pending -> running -> passed | failed | skipped, plus
``awaiting`` for a step that hands over to the operator (VM profile: reboot,
engine restart from a root shell) and continues on ``--resume``.

On resume a step left ``running`` (the harness was killed mid-step) is
marked failed with "interrupted": the harness never re-runs a half-done
lifecycle step blindly. An ``awaiting`` step is handed back to its check,
which decides from the evidence (for a reboot: a new boot id) whether it
can continue.

The file is redacted on every write (redact.Redactor), and lives in a
directory only the app user can read (0700).
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from datetime import datetime, timezone

from .redact import Redactor

PENDING, RUNNING, PASSED, FAILED, SKIPPED, AWAITING = (
    'pending', 'running', 'passed', 'failed', 'skipped', 'awaiting')
DONE = (PASSED, FAILED, SKIPPED)
STATUSES = (PENDING, RUNNING, PASSED, FAILED, SKIPPED, AWAITING)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def boot_id():
    try:
        with open('/proc/sys/kernel/random/boot_id', encoding='ascii') as f:
            return f.read().strip()
    except OSError:
        return ''


def default_state_dir():
    base = os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')
    return os.path.join(base, 'clientst0r-livecheck')


class StateError(Exception):
    pass


class RunState:
    FILE = 'state.json'

    def __init__(self, directory, data, redactor=None):
        self.directory = directory
        self.data = data
        self.redactor = redactor or Redactor()

    # -- creation / loading ----------------------------------------------
    @classmethod
    def create(cls, root, *, profile, engine, plan, options, redactor=None, clock=None):
        run_id = (clock or time.strftime)('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3)
        directory = os.path.join(root, run_id)
        os.makedirs(directory, mode=0o700, exist_ok=False)
        os.makedirs(os.path.join(directory, 'evidence'), mode=0o700, exist_ok=True)
        data = {
            'run_id': run_id, 'profile': profile, 'engine': engine,
            'created_at': now_iso(), 'boot_id': boot_id(), 'options': options,
            'fixtures': {}, 'facts': {}, 'finished': False,
            'steps': [{'key': k, 'status': PENDING, 'started_at': None, 'finished_at': None,
                       'seconds': None, 'detail': '', 'evidence': {}, 'resume': {}}
                      for k in plan],
        }
        st = cls(directory, data, redactor)
        st.save()
        return st

    @classmethod
    def load(cls, directory, redactor=None):
        path = os.path.join(directory, cls.FILE)
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise StateError(f'cannot read run state {path}: {e}')
        if not isinstance(data, dict) or not isinstance(data.get('steps'), list):
            raise StateError(f'{path} is not a live-check run state')
        for s in data['steps']:
            if s.get('status') not in STATUSES:
                raise StateError(f'{path}: step {s.get("key")} has an unknown status')
        return cls(directory, data, redactor)

    @staticmethod
    def latest(root):
        """The newest unfinished run directory under root, or None."""
        if not os.path.isdir(root):
            return None
        for name in sorted(os.listdir(root), reverse=True):
            d = os.path.join(root, name)
            p = os.path.join(d, RunState.FILE)
            if os.path.isfile(p):
                try:
                    with open(p, encoding='utf-8') as f:
                        if not json.load(f).get('finished'):
                            return d
                except (OSError, ValueError):
                    continue
        return None

    # -- persistence ------------------------------------------------------
    def save(self):
        path = os.path.join(self.directory, self.FILE)
        payload = json.dumps(self.redactor.obj(self.data), indent=1, sort_keys=False, default=str)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix='.state-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # -- steps --------------------------------------------------------------
    @property
    def steps(self):
        return self.data['steps']

    def step(self, key):
        for s in self.steps:
            if s['key'] == key:
                return s
        raise KeyError(key)

    def next_step(self):
        """The first step that still has to run (pending or awaiting)."""
        for s in self.steps:
            if s['status'] in (PENDING, AWAITING):
                return s
        return None

    def recover_interrupted(self):
        """Mark steps left 'running' by a killed harness as failed. Returns
        their keys."""
        hit = []
        for s in self.steps:
            if s['status'] == RUNNING:
                s['status'] = FAILED
                s['finished_at'] = now_iso()
                s['detail'] = ('interrupted: the harness stopped while this step ran; it is not '
                               're-run automatically. ' + (s.get('detail') or '')).strip()
                hit.append(s['key'])
        if hit:
            self.save()
        return hit

    def begin(self, key):
        s = self.step(key)
        if s['status'] in DONE:
            raise StateError(f'step {key} already finished ({s["status"]})')
        s['resumed'] = s['status'] == AWAITING
        if not s['resumed']:
            s['started_at'] = now_iso()
            s['_t0'] = time.time()
        s['status'] = RUNNING
        self.save()
        return s

    def end(self, key, status, detail='', evidence=None):
        if status not in DONE + (AWAITING,):
            raise StateError(f'bad final status {status}')
        s = self.step(key)
        s['status'] = status
        s['detail'] = str(detail)[:4000]
        if evidence:
            s['evidence'] = dict(s.get('evidence') or {}, **evidence)
        if status != AWAITING:
            s['finished_at'] = now_iso()
            t0 = s.pop('_t0', None)
            if t0 is not None:
                s['seconds'] = round(time.time() - t0, 1)
        self.save()
        return s

    def mark_finished(self):
        self.data['finished'] = True
        self.data['finished_at'] = now_iso()
        self.save()

    def counts(self):
        out = {k: 0 for k in STATUSES}
        for s in self.steps:
            out[s['status']] += 1
        return out
