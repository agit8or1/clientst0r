"""Mark one release as tested, only from a passing results file for that
exact image digest.

    run_live_checks.py mark-tested --results RUN/results.json [--engine E]
        [--release-file F] [--release-list NAME] [--allow-skipped KEY,...]
        [--diff-only]

Refuses unless:

* the file is a live-check results file whose ``results_sha256`` matches
  its content (an edited file is refused), not a dry run, overall PASSED;
* every required check of its profile is present and passed. A skipped
  check counts only when it was not applicable (path-mode check on a
  dedicated host name) or the operator names it in ``--allow-skipped`` and
  the catalog allows skipping it (upgrade/rollback with one release; the VM
  operator steps);
* the results' engine is the one asked for, the installed digest equals the
  digest the release list had at run time, and the release list in the
  repository has an entry with that id AND that exact digest.

Then it changes ``'tested': False`` to ``'tested': True`` in that one entry,
adds a comment line naming the run, profile, date, results checksum and any
accepted skips, and prints the unified diff. It writes only the working
tree file; it never runs git. A human reviews ``git diff`` and commits.
"""
from __future__ import annotations

import ast
import difflib
import os
import re

from . import catalog, results

DIGEST_RE = re.compile(r'^sha256:[0-9a-f]{64}$')


class Refused(Exception):
    pass


def validate(doc, *, engine=None, allow_skipped=()):
    if doc.get('results_sha256') != results.canonical_sha256(doc):
        raise Refused('the results file was modified after the run (results_sha256 does not match)')
    if doc.get('dry_run'):
        raise Refused('a dry run proves nothing')
    if engine and doc.get('engine') != engine:
        raise Refused(f'the results are for {doc.get("engine")}, not {engine}')
    if doc.get('overall') != 'passed':
        raise Refused(f'the run did not pass (overall: {doc.get("overall")})')
    rel = doc.get('release') or {}
    digest = rel.get('digest') or ''
    if not DIGEST_RE.match(digest):
        raise Refused('the results do not name an image digest')
    if rel.get('listed_digest') and rel['listed_digest'] != digest:
        raise Refused('the installed digest differed from the release list during the run')
    by_key = {c['key']: c for c in doc.get('checks') or []}
    accepted, missing = [], []
    for key in catalog.plan(doc['profile']):
        meta = catalog.CHECKS[key]
        if not meta['required']:
            continue
        c = by_key.get(key)
        if c is None:
            missing.append(f'{key} (not run)')
        elif c['status'] == 'passed':
            continue
        elif c['status'] == 'skipped' and (c.get('evidence') or {}).get('not_applicable'):
            accepted.append(f'{key}: not applicable')
        elif c['status'] == 'skipped' and meta['may_skip'] and key in allow_skipped:
            accepted.append(f'{key}: skipped ({c.get("detail", "")[:120]})')
        else:
            missing.append(f'{key} ({c["status"]})')
    if missing:
        raise Refused('required checks did not pass: ' + ', '.join(missing))
    return rel, accepted


def find_entry(source, list_name, release_id, digest):
    """(dict node, entry) of the release with that id and digest."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == list_name
                                                for t in node.targets):
            if not isinstance(node.value, ast.List):
                raise Refused(f'{list_name} is not a list literal')
            for el in node.value.elts:
                if not isinstance(el, ast.Dict):
                    continue
                try:
                    entry = {k.value: ast.literal_eval(v) for k, v in zip(el.keys, el.values)
                             if isinstance(k, ast.Constant)}
                except ValueError:
                    continue
                if entry.get('id') == release_id:
                    if entry.get('digest') != digest:
                        raise Refused(f'release {release_id} in the list has digest '
                                      f'{entry.get("digest")}, the run verified {digest}')
                    return el, entry
            raise Refused(f'release {release_id} is not in {list_name}')
    raise Refused(f'no {list_name} list in the release file')


def mark(source, list_name, doc, accepted, *, today):
    rel = doc['release']
    node, entry = find_entry(source, list_name, rel.get('id'), rel['digest'])
    if entry.get('tested') is True:
        return source, False
    lines = source.splitlines(keepends=True)
    start, end = node.lineno - 1, node.end_lineno
    span = ''.join(lines[start:end])
    n = len(re.findall(r"'tested':\s*False", span))
    if n != 1:
        raise Refused(f"expected one 'tested': False in the {rel['id']} entry, found {n}")
    span = re.sub(r"'tested':\s*False", "'tested': True", span)
    indent = re.match(r'\s*', lines[start]).group(0)
    note = (f'{indent}# tested {today}: live verification passed ({doc["profile"]} profile, run '
            f'{doc["run_id"]}, clientst0r {doc.get("clientstor_version", "")}, results sha256 '
            f'{doc["results_sha256"][:16]}…)\n')
    if accepted:
        note += f'{indent}#   accepted skips: {"; ".join(accepted)}\n'
    new = ''.join(lines[:start]) + note + span + ''.join(lines[end:])
    _, after = find_entry(new, list_name, rel['id'], rel['digest'])
    if after.get('tested') is not True:
        raise Refused('internal: the edit did not mark the entry tested')
    return new, True


def run(results_path, release_file, list_name, *, engine=None, allow_skipped=(), diff_only=False,
        today=None, out=print):
    import datetime
    doc = results.load(results_path)
    _, accepted = validate(doc, engine=engine, allow_skipped=allow_skipped)
    with open(release_file, encoding='utf-8') as f:
        source = f.read()
    new, changed = mark(source, list_name, doc, accepted,
                        today=today or datetime.date.today().isoformat())
    if not changed:
        out(f'{doc["release"]["id"]} is already marked tested; nothing to do.')
        return ''
    diff = ''.join(difflib.unified_diff(source.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f'a/{os.path.relpath(release_file)}',
                                        tofile=f'b/{os.path.relpath(release_file)}'))
    if not diff_only:
        mode = os.stat(release_file).st_mode
        tmp = release_file + '.marktested'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new)
        os.chmod(tmp, mode & 0o7777)
        os.replace(tmp, release_file)
    out(diff)
    out(('Written to ' + release_file if not diff_only else 'Not written (--diff-only).')
        + ' Review it (git diff) and commit it yourself; nothing was committed or pushed.')
    return diff
