"""Runs the plan step by step; resumable (state.py).

Exit codes: 0 all passed, 1 a check failed, 2 refused by the guard (nothing
was changed), 3 waiting for the operator (VM profile; continue with
--resume), 4 incomplete for another reason.
"""
from __future__ import annotations

import socket
import traceback

from . import catalog, checks, results, safety
from .browser import Browser, chromium_present, find_python
from .redact import Redactor
from .state import AWAITING, FAILED, PASSED, PENDING, SKIPPED, RunState, StateError

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_AWAITING, EXIT_INCOMPLETE = 0, 1, 2, 3, 4
# A failure of one of these makes the remaining checks meaningless.
PREREQUISITES = ('guard', 'fixtures', 'install')


# ---------------------------------------------------------------------------
# facts for the guard (read only)
# ---------------------------------------------------------------------------

def base_url_of(status):
    url = ((status or {}).get('config') or {}).get('clientstor_url') or ''
    if not url:
        from core.models import SystemSetting
        url = SystemSetting.get_settings().site_url or ''
    return safety.normalize_url(url)


def gather_facts(engine, opts):
    from django.contrib.auth import get_user_model
    from core.models import Organization
    from office.models import EditSession
    from . import fixtures
    f = {'hostname': socket.getfqdn(), 'test_org_name': fixtures.TEST_ORG_NAME}
    left = fixtures.leftovers()
    f['test_org_exists'] = bool(left)
    f['leftovers'] = left
    User = get_user_model()
    op = User.objects.filter(username=opts.get('operator') or '').first()
    f['operator'] = {'exists': op is not None, 'username': opts.get('operator'),
                     'is_active': bool(op and op.is_active), 'is_superuser': bool(op and op.is_superuser)}
    py, detail = find_python(opts.get('browser_python'))
    chrome_ok, chrome_detail = chromium_present(opts.get('chromium'))
    f['browser_ok'] = bool(py) and chrome_ok
    f['browser_python'] = py
    f['browser_detail'] = f'{detail}; {chrome_detail}'
    eng = {'available': False}
    status = None
    ok, why = engine.available()
    eng['available'] = ok
    eng['detail'] = why
    if ok:
        try:
            status = engine.status()
            eng['helper_reachable'] = True
        except Exception as e:   # noqa: BLE001
            eng['helper_reachable'] = False
            eng['detail'] = str(e)[:300]
    if status:
        inst = status.get('installed') or {}
        cont = status.get('container') or {}
        eng.update(installed_release=inst.get('release'), digest=inst.get('digest'),
                   running=cont.get('running'), health=cont.get('health'))
        f['office_hostname'] = (status.get('config') or {}).get('office_hostname', '')
        instance = engine.instance()
        eng['instance_enabled'] = bool(instance and instance.enabled)
        eng['instance_health'] = instance.health_status if instance else None
        active = engine.active_operation()
        eng['active_operation'] = f'{active.action} ({active.state})' if active else ''
    f['engine'] = eng
    f['base_url'] = base_url_of(status) if status is not None else base_url_of(None)
    test_ids = fixtures.test_user_ids()
    instance = engine.instance() if status else None
    if instance is not None:
        from django.utils import timezone
        f['real_sessions'] = (EditSession.objects.filter(
            instance=instance, state__in=EditSession.LIVE_STATES, expires_at__gt=timezone.now())
            .exclude(user_id__in=test_ids).count())
    else:
        f['real_sessions'] = 0
    if opts.get('profile') == 'vm':
        f['marker'] = safety.read_marker()
        f['pattern_file'] = safety.read_patterns()
        f['real_orgs'] = Organization.objects.exclude(slug=fixtures.TEST_ORG_SLUG).count()
        f['users'] = User.objects.exclude(pk__in=test_ids).count()
        f['real_session_history'] = EditSession.objects.exclude(user_id__in=test_ids).count()
    return f, status


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

class Runner:
    def __init__(self, opts, engine, *, out=print, browser_factory=None, fixtures_cls=None,
                 facts_fn=gather_facts, check_funcs=None, sleep=None):
        self.opts = opts
        self.engine = engine
        self.redactor = Redactor()
        # Console output is redacted like everything else the run writes.
        self.out = lambda msg='': out(self.redactor.text(str(msg)))
        self.browser_factory = browser_factory or (lambda py: Browser(py, redactor=self.redactor))
        self.fixtures_cls = fixtures_cls
        self.facts_fn = facts_fn
        self.check_funcs = check_funcs or checks.CHECK_FUNCS
        self.sleep = sleep
        self.browser = None
        self.state = None
        self.fx = None
        self.facts = {}

    # -- entry points -------------------------------------------------------
    def plan(self):
        return catalog.plan(self.opts['profile'], only=self.opts.get('only'), skip=self.opts.get('skip'))

    def dry_run(self):
        facts, _ = self.facts_fn(self.engine, dict(self.opts, dry_run=True))
        g = safety.guard(self.opts['profile'], facts, dict(self.opts, dry_run=True))
        self.out(f'Profile {self.opts["profile"]}, engine {self.engine.name}; base URL '
                 f'{facts.get("base_url") or "unknown"}')
        self.out(f'Guard: {g.summary()}')
        self.out(f'Browser: {facts.get("browser_detail")}')
        self.out('Plan (dry run, nothing is executed):')
        for n, key in enumerate(self.plan(), 1):
            self.out(f'  {n:2}. {key:22} {catalog.title(key)}')
        return EXIT_OK if g.ok else EXIT_REFUSED

    def cleanup_only(self):
        from . import fixtures
        facts, _ = self.facts_fn(self.engine, dict(self.opts, cleanup_only=True))
        g = safety.guard(self.opts['profile'], facts, dict(self.opts, cleanup_only=True))
        self.out(f'Guard: {g.summary()}')
        if not g.ok:
            return EXIT_REFUSED
        if not facts.get('leftovers'):
            self.out('Nothing to clean up.')
            return EXIT_OK
        summary = fixtures.cleanup()
        self.out('Removed: ' + ', '.join(f'{k}={v}' for k, v in summary.items()))
        left = fixtures.leftovers()
        if left:
            self.out('Still present: ' + ', '.join(left))
            return EXIT_FAILED
        return EXIT_OK

    def run(self):
        root = self.opts['state_dir']
        if self.opts.get('resume'):
            d = self.opts.get('run_dir') or RunState.latest(root)
            if not d:
                self.out('No unfinished run to resume.')
                return EXIT_INCOMPLETE
            self.state = RunState.load(d, self.redactor)
            if self.state.data['profile'] != self.opts['profile'] or \
                    self.state.data['engine'] != self.engine.name:
                self.out(f'The run in {d} is {self.state.data["profile"]}/{self.state.data["engine"]}; '
                         'resume it with the same --profile and --engine.')
                return EXIT_REFUSED
            hit = self.state.recover_interrupted()
            if hit:
                self.out('Interrupted steps marked failed: ' + ', '.join(hit))
            self.opts = dict(self.state.data.get('options') or {}, **{
                k: v for k, v in self.opts.items() if v not in (None, False, [], '')})
            # Light guard on resume: the flags and the site, not the engine
            # health (it may be coming back from the step being resumed).
            facts, _ = self.facts_fn(self.engine, self.opts)
            g = safety.guard(self.opts['profile'], facts, dict(self.opts, skip_engine=True, resume=True))
            self.out(f'Guard (resume): {g.summary()}')
            if not g.ok:
                return EXIT_REFUSED
            self.facts = facts
            self._load_fixtures()
        else:
            existing = RunState.latest(root)
            if existing:
                self.out(f'An unfinished run exists in {existing}: --resume it, or --cleanup-only and '
                         'start again.')
                return EXIT_REFUSED
            self.state = RunState.create(root, profile=self.opts['profile'], engine=self.engine.name,
                                         plan=self.plan(), options=_persistable(self.opts),
                                         redactor=self.redactor)
            self.out(f'Run {self.state.data["run_id"]} in {self.state.directory}')
        try:
            code = self._loop()
        finally:
            if self.browser is not None:
                self.browser.close()
        jp, mp, doc = results.write(self.state, redactor=self.redactor)
        self.out(f'Results: {jp}\nReport:  {mp}\nOverall: {doc["overall"]}')
        return code

    # -- internals ----------------------------------------------------------
    def _load_fixtures(self):
        ids = self.state.data.get('fixtures') or {}
        if ids.get('org'):
            from .fixtures import Fixtures
            cls = self.fixtures_cls or Fixtures
            self.fx = cls.load(self.redactor, ids)

    def _context(self):
        if self.browser is None:
            py = self.facts.get('browser_python')
            self.browser = self.browser_factory(py)
            self.browser.call('start', headless=not self.opts.get('headed'),
                              executable=self.opts.get('chromium'), resolve=self.opts.get('resolve') or [],
                              evidence_dir=self.state.directory + '/evidence', timeout=300)
        kw = {}
        if self.sleep is not None:
            kw['sleep'] = self.sleep
        return checks.Context(state=self.state, engine=self.engine, fixtures=self.fx,
                              browser=self.browser, opts=self.opts, redactor=self.redactor,
                              operator=self._operator(), base_url=self.facts.get('base_url') or '', **kw)

    def _operator(self):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.get(username=self.opts['operator'], is_superuser=True,
                                            is_active=True)

    def _skip_rest(self, reason):
        for s in self.state.steps:
            if s['status'] == PENDING and s['key'] != 'cleanup':
                self.state.end(s['key'], SKIPPED, reason)

    def _loop(self):
        while True:
            s = self.state.next_step()
            if s is None:
                break
            key = s['key']
            self.state.begin(key)
            self.out(f'-> {key}: {catalog.title(key)}')
            try:
                status, detail, evidence = self._run_step(key)
            except checks.Await as a:
                s = self.state.step(key)
                s['resume'] = a.resume
                self.state.end(key, AWAITING, str(a), a.evidence)
                self.out(f'   AWAITING OPERATOR: {a}')
                return EXIT_AWAITING
            except checks.Skip as e:
                status, detail, evidence = SKIPPED, str(e), e.evidence
            except checks.Fail as e:
                status, detail, evidence = FAILED, str(e), e.evidence
            except StateError:
                raise
            except Exception as e:   # noqa: BLE001 - a crash fails the step, the run goes on
                status, detail = FAILED, f'{type(e).__name__}: {e}'
                evidence = {'traceback': traceback.format_exc(limit=6)[-2000:]}
            self.state.end(key, status, detail, evidence)
            self.out(f'   {status.upper()}: {detail[:300]}')
            if status == FAILED and key in PREREQUISITES:
                self._skip_rest(f'not run: the prerequisite "{key}" failed')
                if key == 'guard':
                    self.state.end('cleanup', SKIPPED, 'nothing was created (the guard refused)')
                    self.state.mark_finished()
                    return EXIT_REFUSED
        self.state.mark_finished()
        counts = self.state.counts()
        if counts[FAILED]:
            return EXIT_FAILED
        return EXIT_OK if counts[PASSED] + counts[SKIPPED] == len(self.state.steps) else EXIT_INCOMPLETE

    def _run_step(self, key):
        if key == 'guard':
            facts, _ = self.facts_fn(self.engine, self.opts)
            self.facts = facts
            g = safety.guard(self.opts['profile'], facts, self.opts)
            from config.version import VERSION
            f = self.state.data.setdefault('facts', {})
            f.update(hostname=facts.get('hostname'), base_url=facts.get('base_url'),
                     clientstor_version=VERSION, browser=facts.get('browser_detail'))
            ev = {'warnings': g.warnings, 'real_sessions': facts.get('real_sessions'),
                  'engine': facts.get('engine')}
            if not g.ok:
                raise checks.Fail(g.summary(), ev)
            return PASSED, g.summary(), ev
        if key == 'fixtures':
            from .fixtures import Fixtures
            cls = self.fixtures_cls or Fixtures
            self.fx = cls(self.redactor)
            ids = self.fx.create()
            self.state.data['fixtures'] = dict(ids, documents={})
            self.state.save()
            return PASSED, f'organization and {len(ids["users"])} users created', {'users': list(ids['users'])}
        fn = self.check_funcs[key]
        ctx = self._context() if key != 'cleanup' else checks.Context(
            state=self.state, engine=self.engine, fixtures=self.fx, browser=None, opts=self.opts,
            redactor=self.redactor, operator=None, base_url=self.facts.get('base_url') or 'x')
        try:
            out = fn(ctx)
        except (checks.Fail, checks.Skip) as e:
            if ctx.shots:
                e.evidence = dict(e.evidence or {}, screenshots=ctx.shots)
            raise
        ev = dict(out.evidence or {})
        if ctx.shots:
            ev['screenshots'] = ctx.shots
        return out.status, out.detail, ev


def _persistable(opts):
    keep = ('profile', 'engine', 'operator', 'confirm_base_url', 'local_production_run', 'disposable',
            'force_disposable', 'production_patterns', 'allow_open_sessions', 'browser_python',
            'chromium', 'browser_base_url', 'resolve', 'route_via', 'long_minutes', 'op_timeout',
            'poll_seconds', 'editor_timeout', 'save_timeout', 'keep_test_data', 'nginx_conf',
            'headed', 'only', 'skip')
    return {k: opts.get(k) for k in keep if k in opts}
