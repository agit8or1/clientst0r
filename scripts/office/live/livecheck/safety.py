"""Safety guards. Pure functions over a facts dict, so they are unit-tested
without Django; checks.gather_guard_facts() collects the facts on the host.

Local profile (the default; a live production install):

* ``--local-production-run`` must be given, and ``--confirm-base-url`` must
  equal clientst0r's own base URL (what the managed helper reports as
  CLIENTSTOR_URL, else SystemSetting.site_url): the operator states which
  site the run will act on;
* the managed engine must already be installed, running and healthy, and
  its editor instance enabled; the local profile never installs from
  scratch, never installs Docker and never reboots;
* no real edit sessions may be open on the managed editor (sessions of
  anyone other than the harness's own test users), because restart / stop /
  update / uninstall drain every session; ``--i-know-sessions-are-open``
  overrides this, and the harness re-checks before every disruptive step;
* a previous run's test organization must not exist unless the operator
  resumes that run or cleans it up (``--resume`` / ``--cleanup-only``);
* the operator account (``--operator``) must be an active superuser: the
  lifecycle operations are queued and audited under that name.

VM profile (optional, a disposable machine):

* ``--i-understand-this-is-disposable`` and the root-owned marker
  ``/etc/clientst0r/livecheck-disposable`` containing ``DISPOSABLE=yes``
  (written by bootstrap_vm.sh);
* the host name, clientst0r's URL and the office host name must not match
  any production pattern the operator lists (``--production-pattern``,
  repeatable, plus ``/etc/clientst0r/livecheck-production-patterns``);
* the install must not look live: more than ``LIVE_ORG_LIMIT`` real
  organizations, more than ``LIVE_USER_LIMIT`` users, or any edit session
  ever opened by a non-test user refuses unless ``--force-disposable``.
"""
from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MARKER = '/etc/clientst0r/livecheck-disposable'
PATTERN_FILE = '/etc/clientst0r/livecheck-production-patterns'
LIVE_ORG_LIMIT = 3
LIVE_USER_LIMIT = 10


@dataclass
class GuardResult:
    ok: bool = True
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def refuse(self, reason):
        self.ok = False
        self.reasons.append(reason)

    def summary(self):
        if self.ok:
            return 'guard passed' + (f' ({"; ".join(self.warnings)})' if self.warnings else '')
        return 'REFUSED: ' + ' | '.join(self.reasons)


def normalize_url(url):
    p = urlsplit((url or '').strip())
    if not p.scheme or not p.hostname:
        return ''
    port = f':{p.port}' if p.port and p.port != {'https': 443, 'http': 80}.get(p.scheme) else ''
    return f'{p.scheme.lower()}://{p.hostname.lower()}{port}/'


def read_marker(path=MARKER):
    """(ok, detail): root-owned, not writable by others, DISPOSABLE=yes."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False, f'{path} does not exist (run bootstrap_vm.sh as root on the disposable VM)'
    except OSError as e:
        return False, f'{path}: {e}'
    if st.st_uid != 0 or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False, f'{path} must be owned by root and writable only by root'
    try:
        with open(path, encoding='utf-8') as f:
            lines = {ln.strip() for ln in f if ln.strip() and not ln.startswith('#')}
    except OSError as e:
        return False, f'{path}: {e}'
    if 'DISPOSABLE=yes' not in lines:
        return False, f'{path} does not contain DISPOSABLE=yes'
    return True, ''


def read_patterns(path=PATTERN_FILE):
    try:
        with open(path, encoding='utf-8') as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    except OSError:
        return []


def matches_production(names, patterns):
    hits = []
    for name in names:
        if not name:
            continue
        for pat in patterns:
            if fnmatch.fnmatch(name.lower(), pat.lower()):
                hits.append(f'{name} matches {pat}')
    return hits


def common_checks(f, opts, g):
    if f.get('test_org_exists') and not (opts.get('resume') or opts.get('cleanup_only')):
        g.refuse(f'a previous run\'s test organization "{f.get("test_org_name")}" still exists: '
                 'resume that run (--resume) or remove it (--cleanup-only) first')
    op = f.get('operator') or {}
    if not op.get('exists'):
        g.refuse('--operator must name an existing superuser (operations are queued and audited '
                 'under that account)')
    elif not (op.get('is_active') and op.get('is_superuser')):
        g.refuse(f'operator {op.get("username")} is not an active superuser')
    if not (opts.get('dry_run') or opts.get('cleanup_only')) and not f.get('browser_ok'):
        g.refuse('no headless browser: ' + (f.get('browser_detail') or 'Playwright/Chromium not found')
                 + ' (see LIVE_VERIFICATION.md, "Browser")')


def engine_checks(f, opts, g, *, require_installed):
    eng = f.get('engine') or {}
    if not eng.get('available'):
        g.refuse(f'the {opts.get("engine")} managed engine is not available in this clientst0r: '
                 + (eng.get('detail') or 'unknown'))
        return
    if not eng.get('helper_reachable'):
        g.refuse('the Office service helper is unreachable: ' + (eng.get('detail') or ''))
        return
    if require_installed:
        if not eng.get('installed_release'):
            g.refuse('the managed engine is not installed (local profile never installs from scratch)')
        elif not eng.get('running') or eng.get('health') not in ('healthy', 'ok'):
            g.refuse(f'the managed engine is not running and healthy '
                     f'(running={eng.get("running")}, health={eng.get("health")})')
        if not eng.get('instance_enabled') or eng.get('instance_health') != 'ok':
            g.refuse(f'the managed editor instance is not open to users and healthy '
                     f'(enabled={eng.get("instance_enabled")}, health={eng.get("instance_health")})')
    if eng.get('active_operation'):
        g.refuse(f'a managed operation is already active ({eng.get("active_operation")}); wait for it')


def sessions_check(f, opts, g):
    n = int(f.get('real_sessions') or 0)
    if n and not opts.get('allow_open_sessions'):
        g.refuse(f'{n} real edit session(s) are open on the managed editor; the run would drain '
                 'them. Ask users to close their documents, or pass --i-know-sessions-are-open')
    elif n:
        g.warnings.append(f'{n} real edit session(s) open; overridden with --i-know-sessions-are-open')


def guard_local(f, opts):
    g = GuardResult()
    if not opts.get('local_production_run'):
        g.refuse('the local profile acts on this live install: pass --local-production-run')
    base = normalize_url(f.get('base_url'))
    confirm = normalize_url(opts.get('confirm_base_url'))
    if not base:
        g.refuse('cannot determine clientst0r\'s base URL (helper CLIENTSTOR_URL or Settings → site URL)')
    elif confirm != base:
        g.refuse(f'--confirm-base-url must be exactly {base} (got {opts.get("confirm_base_url") or "nothing"})')
    if opts.get('profile_flags_vm'):
        g.refuse('--i-understand-this-is-disposable / --force-disposable are VM-profile flags')
    common_checks(f, opts, g)
    if not (opts.get('cleanup_only') or opts.get('skip_engine')):
        engine_checks(f, opts, g, require_installed=True)
        sessions_check(f, opts, g)
    return g


def guard_vm(f, opts):
    g = GuardResult()
    if not opts.get('disposable'):
        g.refuse('the VM profile needs --i-understand-this-is-disposable')
    ok, detail = f.get('marker', (False, 'marker not checked'))
    if not ok:
        g.refuse(f'root disposable marker: {detail}')
    patterns = list(opts.get('production_patterns') or []) + list(f.get('pattern_file') or [])
    names = [f.get('hostname'), urlsplit(f.get('base_url') or '').hostname,
             f.get('office_hostname')]
    for hit in matches_production(names, patterns):
        g.refuse(f'production-like name: {hit}')
    live = []
    if int(f.get('real_orgs') or 0) > LIVE_ORG_LIMIT:
        live.append(f'{f["real_orgs"]} organizations')
    if int(f.get('users') or 0) > LIVE_USER_LIMIT:
        live.append(f'{f["users"]} users')
    if int(f.get('real_session_history') or 0) > 0:
        live.append(f'{f["real_session_history"]} edit sessions by real users')
    if live:
        if opts.get('force_disposable'):
            g.warnings.append('looks like a live install (' + ', '.join(live) + '); --force-disposable')
        else:
            g.refuse('this looks like a live install (' + ', '.join(live) + '); use the local profile, '
                     'or --force-disposable if this VM really is disposable')
    common_checks(f, opts, g)
    if not (opts.get('cleanup_only') or opts.get('skip_engine')):
        engine_checks(f, opts, g, require_installed=False)
        sessions_check(f, opts, g)
    return g


def guard(profile, facts, opts):
    return guard_local(facts, opts) if profile == 'local' else guard_vm(facts, opts)
