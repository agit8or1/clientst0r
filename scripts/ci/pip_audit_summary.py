#!/usr/bin/env python3
"""Turn a pip-audit JSON report into a CI verdict.

Supported scanner: pip-audit 2.10.x, ``--format json``. That output is::

    {"dependencies": [{"name": str, "version": str,
                       "vulns": [{"id": str, "fix_versions": [str], "aliases": [str], ...}]}
                      | {"name": str, "skip_reason": str}],
     "fixes": [...]}

Four outcomes, each with its own exit code, so CI can never mistake a
parsing problem or a crashed scanner for a clean result:

    0  clean        no advisories, or only advisories covered by a current exception
    1  vulnerable   at least one advisory without a current exception
    2  malformed    the report is missing, not JSON, or not the schema above
    3  scanner      pip-audit itself failed (exit code other than 0/1)

pip-audit reports no severity, so this does not pretend to classify one:
every advisory blocks unless ``.github/security-exceptions.toml`` lists it
(by id or alias) with a reason, a mitigation, an owner and an expiry date.
Expired exceptions stop applying.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

CLEAN, VULNERABLE, MALFORMED, SCANNER = 0, 1, 2, 3
STATE = {CLEAN: 'clean', VULNERABLE: 'vulnerable', MALFORMED: 'malformed', SCANNER: 'scanner failure'}


class Malformed(Exception):
    pass


def load_report(path: Path):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise Malformed(f'report {path} was not written')
    except (OSError, ValueError) as exc:
        raise Malformed(f'report is not valid JSON: {exc}')
    if not isinstance(data, dict) or not isinstance(data.get('dependencies'), list):
        raise Malformed('report has no "dependencies" list (unsupported pip-audit output format)')
    vulns, skipped = [], []
    for i, dep in enumerate(data['dependencies']):
        if not isinstance(dep, dict) or not isinstance(dep.get('name'), str):
            raise Malformed(f'dependency #{i} has no name')
        if 'skip_reason' in dep:
            skipped.append((dep['name'], str(dep['skip_reason'])))
            continue
        items = dep.get('vulns')
        if not isinstance(items, list):
            raise Malformed(f'dependency {dep["name"]} has no "vulns" list')
        for v in items:
            if not isinstance(v, dict) or not isinstance(v.get('id'), str):
                raise Malformed(f'a vulnerability of {dep["name"]} has no id')
            vulns.append({'package': dep['name'], 'version': str(dep.get('version', '')), 'id': v['id'],
                          'aliases': [a for a in v.get('aliases') or [] if isinstance(a, str)],
                          'fix_versions': [f for f in v.get('fix_versions') or [] if isinstance(f, str)]})
    # pip-audit may list one advisory twice when several requirement files pull the package.
    unique = {(v['package'], v['version'], v['id']): v for v in vulns}
    return list(unique.values()), skipped


def load_exceptions(path: Path | None, today: dt.date):
    if path is None or not path.exists():
        return [], []
    if tomllib is None:
        raise Malformed('exceptions file needs Python 3.11+ (tomllib)')
    try:
        doc = tomllib.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Malformed(f'exceptions file is invalid: {exc}')
    active, expired = [], []
    for i, e in enumerate(doc.get('exception', [])):
        missing = [k for k in ('id', 'package', 'reason', 'mitigation', 'owner', 'expires') if not e.get(k)]
        if missing:
            raise Malformed(f'exception #{i} is missing {", ".join(missing)}')
        expires = e['expires'] if isinstance(e['expires'], dt.date) else dt.date.fromisoformat(str(e['expires']))
        (active if expires >= today else expired).append(dict(e, expires=expires))
    return active, expired


def covered(vuln, exceptions):
    ids = {vuln['id'], *vuln['aliases']}
    for e in exceptions:
        if e['package'].lower() == vuln['package'].lower() and e['id'] in ids:
            return e
    return None


def evaluate(report: Path, scanner_exit: int, exceptions_path: Path | None = None, today: dt.date | None = None):
    """(exit code, markdown lines)."""
    today = today or dt.date.today()
    lines = ['## Dependency audit (pip-audit)', '']
    if scanner_exit not in (0, 1):
        lines.append(f'**Scanner failure** — pip-audit exited {scanner_exit}. No result; this is not a clean run.')
        return SCANNER, lines
    try:
        vulns, skipped = load_report(report)
        active, expired = load_exceptions(exceptions_path, today)
    except Malformed as exc:
        lines.append(f'**Malformed scanner output** — {exc}. No result; this is not a clean run.')
        return MALFORMED, lines
    if scanner_exit == 1 and not vulns:
        lines.append('**Malformed scanner output** — pip-audit reported findings (exit 1) but the report lists none.')
        return MALFORMED, lines
    blocking, accepted = [], []
    for v in sorted(vulns, key=lambda v: (v['package'], v['id'])):
        e = covered(v, active)
        (accepted if e else blocking).append((v, e))
    if blocking:
        lines += [f'**{len(blocking)} advisory/advisories without an exception — blocking.**', '',
                  '| Package | Version | Advisory | Aliases | Fixed in |', '|---|---|---|---|---|']
        for v, _ in blocking:
            lines.append(f'| {v["package"]} | {v["version"]} | {v["id"]} | {", ".join(v["aliases"])} | '
                         f'{", ".join(v["fix_versions"]) or "no fix released"} |')
    else:
        lines.append('**Clean** — no advisories without a current exception.')
    if accepted:
        lines += ['', 'Accepted under `.github/security-exceptions.toml`:', '',
                  '| Package | Advisory | Mitigation | Owner | Expires |', '|---|---|---|---|---|']
        for v, e in accepted:
            lines.append(f'| {v["package"]} {v["version"]} | {v["id"]} | {e["mitigation"]} | {e["owner"]} | {e["expires"]} |')
    if expired:
        lines += ['', 'Expired exceptions (no longer applied): ' + ', '.join(f'{e["package"]} {e["id"]} ({e["expires"]})'
                                                                       for e in expired)]
    if skipped:
        lines += ['', 'Not audited (skipped by pip-audit): ' + ', '.join(f'{n} ({r})' for n, r in skipped)]
    return (VULNERABLE if blocking else CLEAN), lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--report', required=True, type=Path)
    ap.add_argument('--scanner-exit', required=True, type=int)
    ap.add_argument('--exceptions', type=Path)
    ap.add_argument('--summary', type=Path, help='append markdown here (e.g. $GITHUB_STEP_SUMMARY)')
    a = ap.parse_args(argv)
    code, lines = evaluate(a.report, a.scanner_exit, a.exceptions)
    text = '\n'.join(lines) + '\n'
    print(text)
    if a.summary:
        with a.summary.open('a') as fh:
            fh.write(text)
    level = 'notice' if code == CLEAN else 'error'
    print(f'::{level}::Dependency audit result: {STATE[code]}')
    return code


if __name__ == '__main__':
    sys.exit(main())
