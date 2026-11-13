#!/usr/bin/env python3
"""clientst0r Office live verification: the single entry point.

Runs as the clientst0r app user, from the app directory, with the app's
Python (the production venv; Playwright can live in another interpreter,
see --browser-python). Full guide: docs/office/LIVE_VERIFICATION.md.

    # what would run, and whether the guard would allow it (read only)
    run_live_checks.py run --engine collabora --operator ADMIN \\
        --local-production-run --confirm-base-url https://clientst0r.example/ --dry-run

    # the real run (local profile: this live install, test data of its own)
    run_live_checks.py run --engine collabora --operator ADMIN \\
        --local-production-run --confirm-base-url https://clientst0r.example/ \\
        --browser-python /path/to/python-with-playwright

    run_live_checks.py resume                    # continue an interrupted / awaiting run
    run_live_checks.py cleanup ...               # remove a previous run's test data only
    run_live_checks.py report [--run-dir D]      # rewrite results.json + report.md
    run_live_checks.py mark-tested --results D/results.json --engine collabora

Exit codes: 0 passed, 1 a check failed, 2 refused (nothing changed),
3 waiting for the operator (VM profile), 4 incomplete, 64 bad arguments.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from livecheck import catalog, engines, state as state_mod  # noqa: E402

EXIT_USAGE = 64
RESOLVE_RE = re.compile(r'^[a-z0-9.-]+=[0-9a-f.:]+$', re.I)
LOCAL_NGINX_RE = re.compile(r'^http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?/?$')


class UsageError(Exception):
    pass


def _csv(value):
    return [v.strip() for v in (value or '').split(',') if v.strip()]


def build_parser():
    p = argparse.ArgumentParser(prog='run_live_checks.py', description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='command', required=True)

    def common(sp, *, full=True):
        sp.add_argument('--profile', choices=catalog.PROFILES, default=None,
                        help='local (default): this live install; vm: a disposable VM '
                             '(resume: taken from the run)')
        sp.add_argument('--engine', choices=sorted(engines.ENGINES), default=None,
                        help='collabora (default) or onlyoffice (resume: taken from the run)')
        sp.add_argument('--operator', default='', help='existing superuser the operations are queued as')
        sp.add_argument('--state-dir', default=state_mod.default_state_dir())
        sp.add_argument('--local-production-run', action='store_true',
                        help='local profile: I know this acts on the live install')
        sp.add_argument('--confirm-base-url', default='', help='local profile: clientst0r\'s base URL')
        sp.add_argument('--i-understand-this-is-disposable', dest='disposable', action='store_true')
        sp.add_argument('--force-disposable', action='store_true')
        sp.add_argument('--production-pattern', dest='production_patterns', action='append', default=[])
        if not full:
            return
        sp.add_argument('--i-know-sessions-are-open', dest='allow_open_sessions', action='store_true')
        sp.add_argument('--browser-python', default='', help='a Python that can import playwright')
        sp.add_argument('--chromium', default='', help='Chromium executable (default: Playwright\'s)')
        sp.add_argument('--browser-base-url', default='',
                        help='URL the browser uses for clientst0r (default: the base URL)')
        sp.add_argument('--resolve', action='append', default=[], metavar='HOST=IP',
                        help='make the browser resolve HOST to IP (split DNS)')
        sp.add_argument('--via-local-nginx', default='', metavar='http://127.0.0.1',
                        help='send the browser\'s clientst0r requests to the local nginx with the '
                             'public Host header and X-Forwarded-Proto: https')
        sp.add_argument('--nginx-conf', default='', help='path-mode check: the nginx file to read')
        sp.add_argument('--long-minutes', type=float, default=12.0)
        sp.add_argument('--op-timeout', type=int, default=3600)
        sp.add_argument('--poll-seconds', type=float, default=5.0)
        sp.add_argument('--editor-timeout', type=int, default=180)
        sp.add_argument('--save-timeout', type=int, default=180)
        sp.add_argument('--only', type=_csv, default=[], help='comma list of checks')
        sp.add_argument('--skip', type=_csv, default=[], help='comma list of checks')
        sp.add_argument('--keep-test-data', action='store_true')
        sp.add_argument('--headed', action='store_true')
        sp.add_argument('--run-dir', default='')

    r = sub.add_parser('run', help='start a run')
    common(r)
    r.add_argument('--dry-run', action='store_true', help='show the guard and the plan; change nothing')
    rs = sub.add_parser('resume', help='continue the newest unfinished run')
    common(rs)
    c = sub.add_parser('cleanup', help='remove a previous run\'s test organization, users and documents')
    common(c, full=False)
    rp = sub.add_parser('report', help='rewrite results.json and report.md from a run\'s state')
    rp.add_argument('--state-dir', default=state_mod.default_state_dir())
    rp.add_argument('--run-dir', default='')
    m = sub.add_parser('mark-tested', help='mark a release tested from a passing results file')
    m.add_argument('--results', required=True)
    m.add_argument('--engine', choices=sorted(engines.ENGINES), required=True)
    m.add_argument('--release-file', default='')
    m.add_argument('--release-list', default='')
    m.add_argument('--allow-skipped', type=_csv, default=[])
    m.add_argument('--diff-only', action='store_true')
    return p


def options(argv):
    """Parse and validate; returns the options dict (UsageError on misuse)."""
    ns = build_parser().parse_args(argv)
    o = vars(ns)
    cmd = o['command']
    if cmd in ('report', 'mark-tested'):
        if cmd == 'mark-tested':
            bad = [k for k in o['allow_skipped'] if not catalog.CHECKS.get(k, {}).get('may_skip')]
            if bad:
                raise UsageError(f'--allow-skipped: {", ".join(bad)} may not be skipped '
                                 f'(allowed: {", ".join(k for k, c in catalog.CHECKS.items() if c["may_skip"])})')
        return o
    o['cleanup_only'] = cmd == 'cleanup'
    o['resume'] = cmd == 'resume'
    if cmd == 'resume' and (o['profile'] is None or o['engine'] is None):
        d = o.get('run_dir') or state_mod.RunState.latest(o['state_dir'])
        if d:
            data = state_mod.RunState.load(d).data
            o['profile'] = o['profile'] or data['profile']
            o['engine'] = o['engine'] or data['engine']
    o['profile'] = o['profile'] or 'local'
    o['engine'] = o['engine'] or 'collabora'
    if o['profile'] == 'local':
        if o['disposable'] or o['force_disposable'] or o['production_patterns']:
            raise UsageError('--i-understand-this-is-disposable, --force-disposable and '
                             '--production-pattern belong to --profile vm')
        if cmd != 'resume' and not o.get('dry_run'):
            if not o['local_production_run']:
                raise UsageError('the local profile needs --local-production-run')
            if not o['confirm_base_url']:
                raise UsageError('the local profile needs --confirm-base-url <clientst0r base URL>')
    else:
        if o['local_production_run']:
            raise UsageError('--local-production-run belongs to --profile local')
        if cmd != 'resume' and not o.get('dry_run') and not o['disposable']:
            raise UsageError('--profile vm needs --i-understand-this-is-disposable')
    if cmd != 'resume' and not o['operator']:
        raise UsageError('--operator <superuser> is required')
    if cmd == 'cleanup':
        return o
    try:
        catalog.plan(o['profile'], only=o['only'], skip=o['skip'])
    except ValueError as e:
        raise UsageError(str(e))
    for r in o['resolve']:
        if not RESOLVE_RE.match(r):
            raise UsageError(f'--resolve {r!r}: expected HOST=IP')
    if o['via_local_nginx'] and not LOCAL_NGINX_RE.match(o['via_local_nginx']):
        raise UsageError('--via-local-nginx must be http://127.0.0.1[:port] (the nginx on this host)')
    if not 0 < o['long_minutes'] <= 240:
        raise UsageError('--long-minutes must be between 0 and 240')
    for k in ('op_timeout', 'editor_timeout', 'save_timeout'):
        if o[k] <= 0:
            raise UsageError(f'--{k.replace("_", "-")} must be positive')
    if o['browser_python'] and not os.path.exists(o['browser_python']):
        raise UsageError(f'--browser-python {o["browser_python"]}: not found')
    if o['chromium'] and not os.path.exists(o['chromium']):
        raise UsageError(f'--chromium {o["chromium"]}: not found')
    return o


def setup_django():
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()


def finish_options(o):
    """Options that need Django or the base URL (route_via)."""
    if o.get('via_local_nginx'):
        from urllib.parse import urlsplit
        base = o.get('browser_base_url') or o.get('confirm_base_url')
        if not base:
            raise UsageError('--via-local-nginx needs --confirm-base-url or --browser-base-url')
        o['route_via'] = {'origin': base.rstrip('/'), 'to': o['via_local_nginx'].rstrip('/'),
                          'host': urlsplit(base).netloc}
    return o


def main(argv=None):
    try:
        o = options(sys.argv[1:] if argv is None else argv)
    except UsageError as e:
        print(f'run_live_checks.py: {e}', file=sys.stderr)
        return EXIT_USAGE
    cmd = o['command']
    if cmd == 'mark-tested':
        from livecheck import marktested
        eng = engines.get(o['engine'])
        try:
            marktested.run(o['results'], o['release_file'] or eng.release_file,
                           o['release_list'] or eng.release_list_name, engine=o['engine'],
                           allow_skipped=o['allow_skipped'], diff_only=o['diff_only'])
        except (marktested.Refused, ValueError, OSError) as e:
            print(f'mark-tested refused: {e}', file=sys.stderr)
            return 2
        return 0
    if cmd == 'report':
        from livecheck import results
        d = o['run_dir'] or state_mod.RunState.latest(o['state_dir'])
        if not d:
            print('no run found', file=sys.stderr)
            return 4
        jp, mp, doc = results.write(state_mod.RunState.load(d))
        print(f'{jp}\n{mp}\noverall: {doc["overall"]}')
        return 0
    try:
        o = finish_options(o)
    except UsageError as e:
        print(f'run_live_checks.py: {e}', file=sys.stderr)
        return EXIT_USAGE
    setup_django()
    from livecheck.runner import Runner
    runner = Runner(o, engines.get(o['engine']))
    if cmd == 'cleanup':
        return runner.cleanup_only()
    if cmd == 'run' and o.get('dry_run'):
        return runner.dry_run()
    return runner.run()


if __name__ == '__main__':
    sys.exit(main())
