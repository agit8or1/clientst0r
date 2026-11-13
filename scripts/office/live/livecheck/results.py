"""Results: machine-readable JSON and a human markdown report.

results.json
    {
      "schema": "clientst0r-office-livecheck/1", "harness_version": "1",
      "run_id", "profile", "engine", "dry_run": false,
      "release": {"id", "version", "edition", "image", "digest"},
      "clientstor_version", "host": {"hostname"}, "base_url",
      "started_at", "finished_at", "overall": "passed" | "failed" | "incomplete",
      "counts": {...},
      "checks": [{"key", "title", "status", "required", "may_skip", "seconds",
                  "started_at", "finished_at", "detail", "evidence"}],
      "results_sha256": "<sha256 of this document without this key>"
    }

overall is ``passed`` only when no check failed and nothing is left
pending/running/awaiting. A skipped check does not fail the run, but
mark-tested treats a skipped required check as missing evidence unless the
operator names it (see marktested.py).

Everything is passed through the run's Redactor before it is written.
"""
from __future__ import annotations

import hashlib
import json
import os

from . import HARNESS_VERSION, catalog
from .redact import Redactor
from .state import FAILED, PASSED, SKIPPED, now_iso

SCHEMA = 'clientst0r-office-livecheck/1'


def canonical_sha256(doc):
    body = {k: v for k, v in doc.items() if k != 'results_sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


def overall(steps):
    statuses = [s['status'] for s in steps]
    if any(s == FAILED for s in statuses):
        return 'failed'
    if all(s in (PASSED, SKIPPED) for s in statuses) and statuses:
        return 'passed'
    return 'incomplete'


def build(state, *, dry_run=False):
    d = state.data
    facts = d.get('facts') or {}
    checks = []
    for s in d['steps']:
        meta = catalog.CHECKS.get(s['key'], {})
        checks.append({
            'key': s['key'], 'title': catalog.title(s['key']), 'status': s['status'],
            'required': bool(meta.get('required')), 'may_skip': bool(meta.get('may_skip')),
            'seconds': s.get('seconds'), 'started_at': s.get('started_at'),
            'finished_at': s.get('finished_at'), 'detail': s.get('detail') or '',
            'evidence': s.get('evidence') or {},
        })
    doc = {
        'schema': SCHEMA, 'harness_version': HARNESS_VERSION,
        'run_id': d['run_id'], 'profile': d['profile'], 'engine': d['engine'],
        'dry_run': bool(dry_run),
        'release': facts.get('release') or {},
        'clientstor_version': facts.get('clientstor_version', ''),
        'engine_version': facts.get('engine_version', ''),
        'host': {'hostname': facts.get('hostname', '')},
        'base_url': facts.get('base_url', ''),
        'started_at': d.get('created_at'), 'finished_at': d.get('finished_at') or now_iso(),
        'overall': overall(d['steps']),
        'counts': state.counts(),
        'checks': checks,
    }
    return doc


def write(state, *, dry_run=False, redactor=None):
    """Write results.json and report.md into the run directory; returns
    (json_path, md_path, doc)."""
    red = redactor or state.redactor or Redactor()
    doc = red.obj(build(state, dry_run=dry_run))
    doc['results_sha256'] = canonical_sha256(doc)
    jp = os.path.join(state.directory, 'results.json')
    mp = os.path.join(state.directory, 'report.md')
    _write(jp, json.dumps(doc, indent=1, default=str) + '\n')
    _write(mp, red.text(markdown(doc)))
    return jp, mp, doc


def _write(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load(path):
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        raise ValueError(f'{path} is not a live-check results file ({SCHEMA})')
    return doc


ICON = {'passed': 'PASS', 'failed': 'FAIL', 'skipped': 'SKIP', 'pending': 'not run',
        'running': 'interrupted', 'awaiting': 'awaiting operator'}


def _cell(text, limit=300):
    text = ' '.join(str(text or '').split())
    if len(text) > limit:
        text = text[:limit - 1] + '…'
    return text.replace('|', '\\|')


def markdown(doc):
    rel = doc.get('release') or {}
    lines = [
        f'# Office live verification: {doc["engine"]} ({doc["profile"]} profile)',
        '',
        f'**Overall: {doc["overall"].upper()}**' + ('  (dry run: nothing was executed)'
                                                     if doc.get('dry_run') else ''),
        '',
        '| | |', '|---|---|',
        f'| Run | `{doc["run_id"]}` |',
        f'| Host | {_cell(doc["host"].get("hostname"))} |',
        f'| clientst0r URL | {_cell(doc.get("base_url"))} |',
        f'| clientst0r version | {_cell(doc.get("clientstor_version"))} |',
        f'| Engine version | {_cell(doc.get("engine_version"))} |',
        f'| Release | {_cell(rel.get("id"))} ({_cell(rel.get("edition"))}) |',
        f'| Image | `{_cell(rel.get("image"))}` |',
        f'| Digest | `{_cell(rel.get("digest"))}` |',
        f'| Started / finished | {doc.get("started_at")} / {doc.get("finished_at")} |',
        f'| Harness | v{doc.get("harness_version")}, results sha256 `{doc.get("results_sha256", "")}` |',
        '',
        '## Checks', '',
        '| # | Check | Result | Time | Detail |', '|---|---|---|---|---|',
    ]
    for n, c in enumerate(doc['checks'], 1):
        secs = '' if c.get('seconds') is None else f'{c["seconds"]:.0f} s'
        lines.append(f'| {n} | {_cell(c["title"])} (`{c["key"]}`) | {ICON.get(c["status"], c["status"])} '
                     f'| {secs} | {_cell(c["detail"])} |')
    lines += ['', '## Evidence', '']
    for c in doc['checks']:
        ev = c.get('evidence') or {}
        if not ev:
            continue
        lines.append(f'### {c["title"]}')
        lines.append('')
        for k, v in ev.items():
            if k == 'screenshots' and isinstance(v, list):
                for shot in v:
                    lines.append(f'- screenshot: [{shot}](evidence/{os.path.basename(str(shot))})')
            else:
                lines.append(f'- {k}: `{_cell(json.dumps(v, default=str), 500)}`')
        lines.append('')
    lines += ['## How to read this', '',
              '- PASS: the check ran and every assertion held. FAIL: see Detail; screenshots are in '
              '`evidence/`. SKIP: not applicable or not allowed in this profile; Detail gives the reason.',
              '- A release can be marked tested only from a results file whose overall result is PASSED '
              'for that exact image digest (`run_live_checks.py mark-tested`).',
              '- Secrets, tokens, JWTs, session keys and passwords are redacted from this report.', '']
    return '\n'.join(lines)
