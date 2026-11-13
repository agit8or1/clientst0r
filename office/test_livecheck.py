"""Tests for the Office live-verification harness (scripts/office/live).

The harness itself runs against a live editor; these tests use fakes: a
fake engine, fake checks, a fake browser, and (when a Python with
Playwright and its Chromium are present) a real headless Chromium against
a tiny fake editor page (livecheck/fake_editor_site.py). They cover the
safety guards, the resumable state machine (including a reboot hand-over),
redaction of everything written, mark-tested only from a matching passing
digest, CLI validation, the nginx path-mode cookie rule, OOXML text
extraction, and the isolated test data (create, sign-in, cleanup).
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import timedelta
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

LIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'scripts', 'office', 'live')
if LIVE_DIR not in sys.path:
    sys.path.insert(0, LIVE_DIR)

import run_live_checks as cli  # noqa: E402
from livecheck import (browser, catalog, checks, engines, fixtures, marktested, ooxml,  # noqa: E402
                       pathmode, results, runner, safety)
from livecheck.redact import MASK, Redactor  # noqa: E402
from livecheck.state import AWAITING, FAILED, PASSED, SKIPPED, RunState  # noqa: E402

BLANKS = os.path.join(os.path.dirname(__file__), 'templates_files')
DIGEST = 'sha256:' + 'ab' * 32
OTHER_DIGEST = 'sha256:' + 'cd' * 32
JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVl'


def blank(fmt):
    with open(os.path.join(BLANKS, f'blank.{fmt}'), 'rb') as fh:
        return fh.read()


def docx_with_text(text):
    src = zipfile.ZipFile(io.BytesIO(blank('docx')))
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == 'word/document.xml':
                data = data.replace(b'<w:p/>', f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'.encode())
            dst.writestr(info, data)
    return out.getvalue()


def local_facts(**over):
    f = {'hostname': 'app.example.test', 'base_url': 'https://app.example.test/',
         'test_org_exists': False, 'test_org_name': fixtures.TEST_ORG_NAME,
         'operator': {'exists': True, 'username': 'op', 'is_active': True, 'is_superuser': True},
         'browser_ok': True, 'browser_detail': 'fake',
         'engine': {'available': True, 'helper_reachable': True, 'installed_release': '25.04-code',
                    'running': True, 'health': 'healthy', 'instance_enabled': True,
                    'instance_health': 'ok', 'active_operation': ''},
         'real_sessions': 0}
    f.update(over)
    return f


LOCAL_OPTS = {'profile': 'local', 'engine': 'collabora', 'local_production_run': True,
              'confirm_base_url': 'https://app.example.test', 'operator': 'op'}


class GuardLocalTests(TestCase):
    def test_passes_when_everything_holds(self):
        g = safety.guard('local', local_facts(), LOCAL_OPTS)
        self.assertTrue(g.ok, g.reasons)

    def assert_refused(self, facts, opts, needle):
        g = safety.guard('local', facts, opts)
        self.assertFalse(g.ok)
        self.assertIn(needle, ' '.join(g.reasons))

    def test_needs_flag_and_exact_base_url(self):
        self.assert_refused(local_facts(), dict(LOCAL_OPTS, local_production_run=False),
                            '--local-production-run')
        self.assert_refused(local_facts(), dict(LOCAL_OPTS, confirm_base_url='https://other.test/'),
                            '--confirm-base-url must be exactly https://app.example.test/')
        self.assert_refused(local_facts(base_url=''), LOCAL_OPTS, 'base URL')

    def test_engine_must_be_installed_healthy_and_idle(self):
        eng = dict(local_facts()['engine'])
        self.assert_refused(local_facts(engine=dict(eng, available=False, detail='runs onlyoffice')),
                            LOCAL_OPTS, 'not available')
        self.assert_refused(local_facts(engine=dict(eng, installed_release=None)), LOCAL_OPTS,
                            'not installed')
        self.assert_refused(local_facts(engine=dict(eng, health='starting')), LOCAL_OPTS, 'healthy')
        self.assert_refused(local_facts(engine=dict(eng, instance_health='down')), LOCAL_OPTS,
                            'instance')
        self.assert_refused(local_facts(engine=dict(eng, active_operation='restart (running)')),
                            LOCAL_OPTS, 'already active')
        self.assert_refused(local_facts(engine=dict(eng, helper_reachable=False)), LOCAL_OPTS,
                            'unreachable')

    def test_real_sessions_refuse_unless_overridden(self):
        self.assert_refused(local_facts(real_sessions=2), LOCAL_OPTS, '2 real edit session(s)')
        g = safety.guard('local', local_facts(real_sessions=2), dict(LOCAL_OPTS, allow_open_sessions=True))
        self.assertTrue(g.ok)
        self.assertIn('overridden', g.warnings[0])

    def test_previous_test_org_needs_resume_or_cleanup(self):
        self.assert_refused(local_facts(test_org_exists=True), LOCAL_OPTS, '--cleanup-only')
        self.assertTrue(safety.guard('local', local_facts(test_org_exists=True),
                                     dict(LOCAL_OPTS, resume=True)).ok)

    def test_operator_and_browser(self):
        self.assert_refused(local_facts(operator={'exists': False}), LOCAL_OPTS, 'superuser')
        self.assert_refused(local_facts(operator={'exists': True, 'username': 'x', 'is_active': True,
                                                  'is_superuser': False}), LOCAL_OPTS, 'not an active')
        self.assert_refused(local_facts(browser_ok=False, browser_detail='no playwright'), LOCAL_OPTS,
                            'no playwright')
        # a dry run and a cleanup do not need a browser
        self.assertTrue(safety.guard('local', local_facts(browser_ok=False),
                                     dict(LOCAL_OPTS, dry_run=True)).ok)

    def test_cleanup_skips_engine_and_session_checks(self):
        g = safety.guard('local', local_facts(engine={'available': False}, real_sessions=5,
                                              test_org_exists=True),
                         dict(LOCAL_OPTS, cleanup_only=True))
        self.assertTrue(g.ok, g.reasons)


class GuardVmTests(TestCase):
    def vm_facts(self, **over):
        base = dict(marker=(True, ''), pattern_file=[], real_orgs=1, users=2,
                    real_session_history=0, office_hostname='office.vm.test')
        base.update(over)
        return local_facts(**base)

    def opts(self, **over):
        return dict({'profile': 'vm', 'disposable': True, 'operator': 'op'}, **over)

    def test_passes(self):
        g = safety.guard('vm', self.vm_facts(engine=dict(local_facts()['engine'], installed_release=None)),
                         self.opts())
        self.assertTrue(g.ok, g.reasons)    # vm may install from scratch

    def test_needs_flag_and_marker(self):
        self.assertFalse(safety.guard('vm', self.vm_facts(), self.opts(disposable=False)).ok)
        g = safety.guard('vm', self.vm_facts(marker=(False, 'missing')), self.opts())
        self.assertIn('marker', g.summary())

    def test_production_patterns(self):
        g = safety.guard('vm', self.vm_facts(), self.opts(production_patterns=['*.example.test']))
        self.assertFalse(g.ok)
        self.assertIn('production-like', g.summary())
        g = safety.guard('vm', self.vm_facts(pattern_file=['office.vm.*']), self.opts())
        self.assertFalse(g.ok)

    def test_live_looking_install(self):
        f = self.vm_facts(real_orgs=40, users=200, real_session_history=9)
        g = safety.guard('vm', f, self.opts())
        self.assertFalse(g.ok)
        self.assertIn('looks like a live install', g.summary())
        self.assertTrue(safety.guard('vm', f, self.opts(force_disposable=True)).ok)

    def test_marker_must_be_root_owned(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'm')
            with open(p, 'w') as fh:
                fh.write('DISPOSABLE=yes\n')
            ok, detail = safety.read_marker(p)
            if os.getuid() != 0:
                self.assertFalse(ok)
                self.assertIn('owned by root', detail)
            self.assertFalse(safety.read_marker(os.path.join(d, 'nope'))[0])
        finally:
            shutil.rmtree(d)


class StateTests(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_lifecycle_resume_and_interrupt(self):
        st = RunState.create(self.root, profile='local', engine='collabora',
                             plan=['guard', 'fixtures', 'cleanup'], options={})
        self.assertEqual(oct(os.stat(st.directory).st_mode & 0o777), '0o700')
        self.assertEqual(RunState.latest(self.root), st.directory)
        st.begin('guard')
        st.end('guard', PASSED, 'ok')
        st.begin('fixtures')     # harness killed here
        again = RunState.load(st.directory)
        self.assertEqual(again.next_step()['key'], 'cleanup')   # running is not re-run
        self.assertEqual(again.recover_interrupted(), ['fixtures'])
        self.assertEqual(again.step('fixtures')['status'], FAILED)
        self.assertIn('interrupted', again.step('fixtures')['detail'])
        again.begin('cleanup')
        again.end('cleanup', PASSED)
        again.mark_finished()
        self.assertIsNone(RunState.latest(self.root))

    def test_awaiting_step_resumes_with_flag(self):
        st = RunState.create(self.root, profile='vm', engine='onlyoffice', plan=['reboot'], options={})
        st.begin('reboot')
        self.assertFalse(st.step('reboot')['resumed'])
        st.end('reboot', AWAITING, 'reboot now')
        loaded = RunState.load(st.directory)
        self.assertEqual(loaded.next_step()['key'], 'reboot')
        loaded.begin('reboot')
        self.assertTrue(loaded.step('reboot')['resumed'])
        loaded.end('reboot', PASSED)
        self.assertIsNotNone(loaded.step('reboot')['seconds'])

    def test_corrupt_state_is_refused(self):
        d = os.path.join(self.root, 'x')
        os.makedirs(d)
        with open(os.path.join(d, 'state.json'), 'w') as fh:
            fh.write('{"steps": [{"key": "a", "status": "weird"}]}')
        with self.assertRaises(Exception):
            RunState.load(d)

    def test_state_file_is_redacted(self):
        red = Redactor(['super-secret-password-1'])
        st = RunState.create(self.root, profile='local', engine='collabora', plan=['guard'],
                             options={}, redactor=red)
        st.data['facts']['note'] = 'pw super-secret-password-1 jwt ' + JWT
        st.save()
        with open(os.path.join(st.directory, 'state.json')) as fh:
            text = fh.read()
        self.assertNotIn('super-secret-password-1', text)
        self.assertNotIn(JWT, text)


class RedactionTests(TestCase):
    def test_patterns_keys_and_literals(self):
        red = Redactor(['hunter2-session-key'])
        data = {'url': f'https://e.test/x?token=abc123&md5=ff&ok=1', 'jwt_secret': 'v',
                'headers': {'Authorization': 'Bearer abcdefghijkl'}, 'note': f'{JWT} hunter2-session-key',
                'session_id': 'keep-me', 'cookie': 'sessionid=zzz', 'list': ['access_token=q1w2e3'],
                'secrets_present': True, 'frame_cookie_names': ['csrftoken']}
        out = red.obj(data)
        self.assertEqual(out['url'], f'https://e.test/x?token={MASK}&md5={MASK}&ok=1')
        self.assertEqual(out['jwt_secret'], MASK)
        self.assertEqual(out['headers']['Authorization'], MASK)
        self.assertNotIn(JWT, out['note'])
        self.assertNotIn('hunter2-session-key', out['note'])
        self.assertEqual(out['session_id'], 'keep-me')
        self.assertEqual(out['cookie'], MASK)
        self.assertEqual(out['list'], [f'access_token={MASK}'])
        self.assertIs(out['secrets_present'], True)
        self.assertEqual(out['frame_cookie_names'], ['csrftoken'])

    def test_results_and_report_never_contain_secrets(self):
        root = tempfile.mkdtemp()
        try:
            red = Redactor(['pw-ABCDEFGH'])
            st = RunState.create(root, profile='local', engine='collabora', plan=['guard'], options={},
                                 redactor=red)
            st.begin('guard')
            st.end('guard', FAILED, f'callback refused for {JWT} pw-ABCDEFGH',
                   {'url': 'https://o.test/c?access_token=s3cr3t', 'token': 'x'})
            jp, mp, doc = results.write(st)
            for path in (jp, mp):
                with open(path) as fh:
                    text = fh.read()
                for secret in (JWT, 'pw-ABCDEFGH', 's3cr3t'):
                    self.assertNotIn(secret, text)
            self.assertEqual(doc['overall'], 'failed')
            self.assertEqual(doc['results_sha256'], results.canonical_sha256(doc))
        finally:
            shutil.rmtree(root)


# ---------------------------------------------------------------------------
# runner state machine with fakes
# ---------------------------------------------------------------------------

class FakeEngine:
    name = 'collabora'
    provider = 'collabora'
    browser = {}

    def instance(self):
        return None


class FakeFixtures:
    created = 0

    def __init__(self, redactor):
        self.redactor = redactor
        self.users = {}

    def create(self):
        FakeFixtures.created += 1
        return {'org': 1, 'users': {'editor': 1, 'editor2': 2, 'reader': 3}}

    @classmethod
    def load(cls, redactor, ids):
        return cls(redactor)


class FakeBrowser:
    def __init__(self, py):
        self.calls = []

    def call(self, cmd, check=True, timeout=None, **kw):
        self.calls.append(cmd)
        return {'ok': True}

    def close(self):
        self.calls.append('closed')


class RunnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_superuser('op', 'op@example.test', 'x')

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.root)

    def make(self, opts, funcs, facts=None):
        opts = dict(opts, state_dir=self.root)
        return runner.Runner(opts, FakeEngine(), out=lambda *a: None, browser_factory=FakeBrowser,
                             fixtures_cls=FakeFixtures,
                             facts_fn=lambda e, o: (facts or local_facts(), None), check_funcs=funcs)

    def ok(self, key):
        def fn(ctx):
            self.calls.append(key)
            return checks.Outcome(detail=f'{key} ok')
        return fn

    def test_full_local_run_passes_and_writes_results(self):
        funcs = {k: self.ok(k) for k in catalog.CHECKS}
        r = self.make(LOCAL_OPTS, funcs)
        self.assertEqual(r.run(), runner.EXIT_OK)
        expected = [k for k in catalog.plan('local') if k not in ('guard', 'fixtures')]
        self.assertEqual(self.calls, expected)
        with open(os.path.join(r.state.directory, 'results.json')) as fh:
            doc = json.load(fh)
        self.assertEqual(doc['overall'], 'passed')
        self.assertTrue(os.path.exists(os.path.join(r.state.directory, 'report.md')))

    def test_guard_refusal_runs_nothing(self):
        funcs = {k: self.ok(k) for k in catalog.CHECKS}
        before = FakeFixtures.created
        r = self.make(LOCAL_OPTS, funcs, facts=local_facts(real_sessions=1))
        self.assertEqual(r.run(), runner.EXIT_REFUSED)
        self.assertEqual(self.calls, [])
        self.assertEqual(FakeFixtures.created, before)
        self.assertTrue(all(s['status'] in (FAILED, SKIPPED) for s in r.state.steps))

    def test_prerequisite_failure_skips_the_rest_but_cleans_up(self):
        funcs = {k: self.ok(k) for k in catalog.CHECKS}

        def broken(ctx):
            raise checks.Fail('not healthy')
        funcs['install'] = broken
        r = self.make(LOCAL_OPTS, funcs)
        self.assertEqual(r.run(), runner.EXIT_FAILED)
        self.assertEqual(self.calls, ['cleanup'])
        self.assertEqual(r.state.step('roundtrip_docx')['status'], SKIPPED)

    def test_a_crash_fails_one_step_and_the_run_goes_on(self):
        funcs = {k: self.ok(k) for k in catalog.CHECKS}
        funcs['readonly'] = lambda ctx: 1 / 0
        funcs['upgrade_rollback'] = lambda ctx: (_ for _ in ()).throw(checks.Skip('one release'))
        r = self.make(LOCAL_OPTS, funcs)
        self.assertEqual(r.run(), runner.EXIT_FAILED)
        self.assertIn('ZeroDivisionError', r.state.step('readonly')['detail'])
        self.assertEqual(r.state.step('upgrade_rollback')['status'], SKIPPED)
        self.assertIn('uninstall_reinstall', self.calls)

    def test_reboot_hands_over_and_resumes(self):
        vm_opts = {'profile': 'vm', 'engine': 'collabora', 'disposable': True, 'operator': 'op',
                   'only': ['reboot']}
        facts = local_facts(marker=(True, ''), pattern_file=[], real_orgs=1, users=1,
                            real_session_history=0)
        seen = []

        def reboot(ctx):
            s = ctx.state.step('reboot')
            seen.append(s['resumed'])
            if not s['resumed']:
                raise checks.Await('reboot now', resume={'boot_id': 'old'})
            self.assertEqual(s['resume'], {'boot_id': 'old'})
            return checks.Outcome(detail='back')
        funcs = {k: self.ok(k) for k in catalog.CHECKS}
        funcs['reboot'] = reboot
        r = self.make(vm_opts, funcs, facts)
        self.assertEqual(r.run(), runner.EXIT_AWAITING)
        self.assertEqual(r.state.step('reboot')['status'], AWAITING)
        self.assertEqual(self.calls, [])          # cleanup waits until the end
        # a new process after the reboot
        r2 = self.make({'profile': 'vm', 'engine': 'collabora', 'resume': True}, funcs, facts)
        self.assertEqual(r2.run(), runner.EXIT_OK)
        self.assertEqual(seen, [False, True])
        self.assertEqual(r2.state.step('reboot')['status'], PASSED)
        self.assertEqual(self.calls, ['cleanup'])

    def test_console_output_is_redacted(self):
        lines = []

        def leaky(ctx):
            raise checks.Fail(f'editor said {JWT} at https://x.test/?access_token=abcdef123')
        funcs = {k: self.ok(k) for k in catalog.CHECKS}
        funcs['readonly'] = leaky
        r = runner.Runner(dict(LOCAL_OPTS, state_dir=self.root, only=['readonly']), FakeEngine(),
                          out=lines.append, browser_factory=FakeBrowser, fixtures_cls=FakeFixtures,
                          facts_fn=lambda e, o: (local_facts(), None), check_funcs=funcs)
        r.run()
        text = '\n'.join(lines)
        self.assertIn('readonly', text)
        self.assertNotIn(JWT, text)
        self.assertNotIn('abcdef123', text)

    def test_unfinished_run_blocks_a_new_one(self):
        st = RunState.create(self.root, profile='local', engine='collabora', plan=['guard'], options={})
        r = self.make(LOCAL_OPTS, {})
        self.assertEqual(r.run(), runner.EXIT_REFUSED)
        self.assertTrue(os.path.isdir(st.directory))

    def test_resume_refuses_other_engine(self):
        RunState.create(self.root, profile='local', engine='onlyoffice', plan=['guard'], options={})
        r = self.make(dict(LOCAL_OPTS, resume=True), {})
        self.assertEqual(r.run(), runner.EXIT_REFUSED)


# ---------------------------------------------------------------------------
# mark-tested
# ---------------------------------------------------------------------------

RELEASE_SOURCE = """RELEASES = [
    {'id': '25.04.1-code', 'version': '25.04.1', 'edition': 'code',
     'image': 'docker.io/collabora/code',
     'digest': '%s',
     'compat': 'code25', 'tested': False, 'published': '2026-10-01'},
    {'id': '25.04.2-code', 'version': '25.04.2', 'edition': 'code',
     'image': 'docker.io/collabora/code',
     'digest': '%s',
     'compat': 'code25', 'tested': False, 'published': '2026-11-01'},
]
""" % (DIGEST, OTHER_DIGEST)


def passing_doc(root, *, profile='local', release_id='25.04.1-code', digest=DIGEST, statuses=None):
    plan = catalog.plan(profile)
    st = RunState.create(root, profile=profile, engine='collabora', plan=plan, options={})
    st.data['facts']['release'] = {'id': release_id, 'digest': digest, 'listed_digest': digest,
                                   'image': 'docker.io/collabora/code'}
    for k in plan:
        st.begin(k)
        status, ev = (statuses or {}).get(k, (PASSED, {}))
        st.end(k, status, 'x', ev)
    st.mark_finished()
    _, _, doc = results.write(st)
    return doc


class MarkTestedTests(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_marks_only_the_matching_entry(self):
        doc = passing_doc(self.root)
        _, accepted = marktested.validate(doc, engine='collabora')
        new, changed = marktested.mark(RELEASE_SOURCE, 'RELEASES', doc, accepted, today='2026-11-13')
        self.assertTrue(changed)
        self.assertEqual(new.count("'tested': True"), 1)
        first = new.split("'id': '25.04.2-code'")[0]
        self.assertIn("'tested': True", first)
        self.assertIn('# tested 2026-11-13: live verification passed (local profile', new)
        again, changed = marktested.mark(new, 'RELEASES', doc, accepted, today='2026-11-13')
        self.assertFalse(changed)
        self.assertEqual(again, new)

    def test_refusals(self):
        doc = passing_doc(self.root)
        tampered = dict(doc, overall='passed', engine='collabora')
        tampered['checks'] = [dict(c, status='passed') for c in doc['checks']][:-1]
        with self.assertRaisesRegex(marktested.Refused, 'modified'):
            marktested.validate(tampered)
        with self.assertRaisesRegex(marktested.Refused, 'not onlyoffice'):
            marktested.validate(doc, engine='onlyoffice')
        failed = passing_doc(tempfile.mkdtemp(dir=self.root),
                             statuses={'concurrent': (FAILED, {})})
        with self.assertRaisesRegex(marktested.Refused, 'did not pass'):
            marktested.validate(failed)
        # a different digest than the list: refused
        other = passing_doc(tempfile.mkdtemp(dir=self.root), digest=OTHER_DIGEST)
        _, acc = marktested.validate(other)
        with self.assertRaisesRegex(marktested.Refused, 'has digest'):
            marktested.mark(RELEASE_SOURCE, 'RELEASES', other, acc, today='x')
        unknown = passing_doc(tempfile.mkdtemp(dir=self.root), release_id='99-code')
        with self.assertRaisesRegex(marktested.Refused, 'not in RELEASES'):
            marktested.mark(RELEASE_SOURCE, 'RELEASES', unknown, [], today='x')
        with self.assertRaisesRegex(marktested.Refused, 'no NOPE list'):
            marktested.mark(RELEASE_SOURCE, 'NOPE', doc, [], today='x')

    def test_skips_need_explicit_acceptance(self):
        doc = passing_doc(self.root, statuses={
            'upgrade_rollback': (SKIPPED, {}), 'path_mode_cookies': (SKIPPED, {'not_applicable': True})})
        with self.assertRaisesRegex(marktested.Refused, 'upgrade_rollback'):
            marktested.validate(doc)
        _, accepted = marktested.validate(doc, allow_skipped=['upgrade_rollback'])
        self.assertEqual(len(accepted), 2)
        new, _ = marktested.mark(RELEASE_SOURCE, 'RELEASES', doc, accepted, today='t')
        self.assertIn('accepted skips: ', new)
        # a required check that may not be skipped cannot be accepted
        bad = passing_doc(tempfile.mkdtemp(dir=self.root), statuses={'readonly': (SKIPPED, {})})
        with self.assertRaisesRegex(marktested.Refused, 'readonly'):
            marktested.validate(bad, allow_skipped=['readonly'])

    def test_dry_run_and_missing_checks_refused(self):
        doc = passing_doc(self.root)
        dry = dict(doc, dry_run=True)
        dry['results_sha256'] = results.canonical_sha256(dry)
        with self.assertRaisesRegex(marktested.Refused, 'dry run'):
            marktested.validate(dry)
        partial = dict(doc, checks=[c for c in doc['checks'] if c['key'] != 'long_session'])
        partial['results_sha256'] = results.canonical_sha256(partial)
        with self.assertRaisesRegex(marktested.Refused, 'long_session'):
            marktested.validate(partial)

    def test_run_writes_the_working_tree_file_only(self):
        doc = passing_doc(self.root)
        rp = os.path.join(self.root, 'results.json')
        with open(rp, 'w') as fh:
            json.dump(doc, fh)
        rel = os.path.join(self.root, 'helper')
        with open(rel, 'w') as fh:
            fh.write(RELEASE_SOURCE)
        out = []
        with mock.patch('subprocess.run') as sp, mock.patch('subprocess.Popen') as pp:
            diff = marktested.run(rp, rel, 'RELEASES', engine='collabora', out=out.append,
                                  diff_only=True)
            self.assertIn("+     'compat': 'code25', 'tested': True", diff)
            with open(rel) as fh:
                self.assertEqual(fh.read(), RELEASE_SOURCE)        # --diff-only
            marktested.run(rp, rel, 'RELEASES', engine='collabora', out=out.append)
            sp.assert_not_called()
            pp.assert_not_called()                                 # never git
        with open(rel) as fh:
            self.assertIn("'tested': True", fh.read())

    def test_works_on_the_real_helper_release_list(self):
        with open(engines.HELPER_FILE) as fh:
            src = fh.read()
        doc = passing_doc(self.root, release_id='10.0.0-community',
                          digest='sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3')
        doc = dict(doc, engine='onlyoffice')
        new, changed = marktested.mark(src, 'RELEASES', doc, [], today='t')
        self.assertTrue(changed)
        self.assertEqual(new.count("'tested': True"), 1)
        compile(new, 'helper', 'exec')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class CliTests(TestCase):
    BASE = ['run', '--operator', 'op']

    def bad(self, argv, needle):
        with self.assertRaises(cli.UsageError) as cm:
            cli.options(argv)
        self.assertIn(needle, str(cm.exception))

    def test_local_needs_its_flags(self):
        self.bad(self.BASE, '--local-production-run')
        self.bad(self.BASE + ['--local-production-run'], '--confirm-base-url')
        o = cli.options(self.BASE + ['--local-production-run', '--confirm-base-url', 'https://a.test/'])
        self.assertEqual((o['profile'], o['engine']), ('local', 'collabora'))
        self.assertTrue(cli.options(self.BASE + ['--dry-run'])['dry_run'])

    def test_profile_flags_do_not_mix(self):
        self.bad(self.BASE + ['--i-understand-this-is-disposable'], 'belong to --profile vm')
        self.bad(['run', '--operator', 'op', '--profile', 'vm'], '--i-understand-this-is-disposable')
        self.bad(['run', '--operator', 'op', '--profile', 'vm', '--local-production-run',
                  '--i-understand-this-is-disposable'], 'belongs to --profile local')

    def test_values_are_validated(self):
        ok = self.BASE + ['--local-production-run', '--confirm-base-url', 'https://a.test/']
        self.bad(['run', '--local-production-run', '--confirm-base-url', 'https://a.test/'], '--operator')
        self.bad(ok + ['--resolve', 'nonsense'], 'HOST=IP')
        self.bad(ok + ['--via-local-nginx', 'http://10.0.0.5'], '127.0.0.1')
        self.bad(ok + ['--only', 'roundtrip_docx,nope'], 'unknown check')
        self.bad(ok + ['--long-minutes', '0'], '--long-minutes')
        self.bad(ok + ['--browser-python', '/nonexistent/python'], 'not found')
        o = cli.options(ok + ['--via-local-nginx', 'http://127.0.0.1', '--resolve', 'a.test=127.0.0.1'])
        o = cli.finish_options(o)
        self.assertEqual(o['route_via'], {'origin': 'https://a.test', 'to': 'http://127.0.0.1',
                                          'host': 'a.test'})
        with self.assertRaises(SystemExit), mock.patch('sys.stderr', io.StringIO()):
            cli.options(['run', '--engine', 'wordpad'])

    def test_mark_tested_args(self):
        self.bad(['mark-tested', '--results', 'r.json', '--engine', 'collabora',
                  '--allow-skipped', 'readonly'], 'may not be skipped')
        o = cli.options(['mark-tested', '--results', 'r.json', '--engine', 'onlyoffice',
                         '--allow-skipped', 'upgrade_rollback,reboot'])
        self.assertEqual(o['allow_skipped'], ['upgrade_rollback', 'reboot'])

    def test_main_reports_usage_errors(self):
        err = io.StringIO()
        with mock.patch('sys.stderr', err):
            self.assertEqual(cli.main(['run', '--operator', 'op']), cli.EXIT_USAGE)
        self.assertIn('--local-production-run', err.getvalue())


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

class PureHelperTests(TestCase):
    def test_nginx_cookie_rule(self):
        good = """server {
            location ^~ /browser/ { proxy_pass http://127.0.0.1:9980; proxy_set_header Cookie ""; }
            location ^~ /cool/ { proxy_pass http://127.0.0.1:9980; proxy_set_header Cookie "";
                                 proxy_http_version 1.1; }
            location / { proxy_pass http://127.0.0.1:8000; }
        }"""
        ok, findings, covered = pathmode.nginx_cookie_findings(good, ['/browser/', '/cool/'])
        self.assertTrue(ok, findings)
        bad = good.replace('proxy_set_header Cookie ""; }\n            location ^~ /cool/',
                           '}\n            location ^~ /cool/')
        ok, findings, _ = pathmode.nginx_cookie_findings(bad, ['/browser/', '/cool/'])
        self.assertFalse(ok)
        self.assertIn('/browser/', findings[0])
        commented = good.replace('proxy_set_header Cookie "";', '# proxy_set_header Cookie "";')
        self.assertFalse(pathmode.nginx_cookie_findings(commented, ['/cool/'])[0])
        leak = good.replace('proxy_http_version 1.1;', 'proxy_pass_header Set-Cookie;')
        self.assertFalse(pathmode.nginx_cookie_findings(leak, ['/cool/'])[0])
        self.assertFalse(pathmode.nginx_cookie_findings('server { }', ['/cool/'])[0])
        regex = 'location ~ ^/(browser|cool)/ { proxy_pass http://x; proxy_set_header Cookie ""; }'
        self.assertTrue(pathmode.nginx_cookie_findings(regex, ['/browser/', '/cool/'])[0])

    def test_ooxml_text(self):
        self.assertTrue(ooxml.contains(docx_with_text('LIVECHECK docx one'), 'docx', 'LIVECHECK docx one'))
        self.assertFalse(ooxml.contains(blank('docx'), 'docx', 'LIVECHECK'))
        self.assertFalse(ooxml.contains(blank('xlsx'), 'xlsx', 'LIVECHECK'))
        self.assertFalse(ooxml.contains(blank('pptx'), 'pptx', 'LIVECHECK'))
        split = docx_with_text('LIVE</w:t></w:r><w:r><w:t>CHECK x')
        self.assertTrue(ooxml.contains(split, 'docx', 'LIVECHECK x'))
        other = ooxml.with_comment(blank('docx'), 'c')
        self.assertNotEqual(other, blank('docx'))
        zipfile.ZipFile(io.BytesIO(other)).testzip()

    def test_upgrade_and_reinstall_decisions(self):
        a = {'id': 'a', 'version': '25.04.1', 'edition': 'code', 'compat': 'c', 'problem': ''}
        b = dict(a, id='b', version='25.04.2')
        self.assertEqual(checks.pick_upgrade([a], 'a')[0], None)
        self.assertIn('at least 2', checks.pick_upgrade([a], 'a')[1])
        self.assertEqual(checks.pick_upgrade([a, b], 'a')[0]['id'], 'b')
        self.assertIsNone(checks.pick_upgrade([a, b], 'b')[0])
        self.assertIn('cannot be installed', checks.pick_upgrade([a, dict(b, problem='untested')], 'a')[1])
        self.assertIn('compatibility', checks.pick_upgrade([a, dict(b, compat='d')], 'a')[1])
        self.assertEqual(checks.reinstall_problem([a], 'a'), '')
        self.assertIn('untested', checks.reinstall_problem([dict(a, problem='untested')], 'a'))
        self.assertIn('not in the release list', checks.reinstall_problem([a], 'zz'))

    def test_drain_order(self):
        t0 = timezone.now()
        progress = {'steps': [
            {'at': t0.isoformat(), 'message': 'queued'},
            {'at': (t0 + timedelta(seconds=1)).isoformat(),
             'message': 'New editing sessions are blocked; asking the editor to save open documents.'},
            {'at': (t0 + timedelta(seconds=20)).isoformat(), 'message': 'Drained: every edit is stored.'},
            {'at': (t0 + timedelta(seconds=21)).isoformat(), 'message': 'Running on the server (h1).'}]}
        ok = checks.drain_order(progress, t0 + timedelta(seconds=10))
        self.assertTrue(ok['blocked_at'] and ok['saved_before_submit'])
        late = checks.drain_order(progress, t0 + timedelta(seconds=60))
        self.assertFalse(late['saved_before_submit'])
        self.assertFalse(checks.drain_order({'steps': []}, t0)['saved_before_submit'])

    def test_engine_url_mode_and_registry(self):
        eng = engines.get('collabora')

        class I:
            browser_url = 'https://app.example.test/'
        self.assertEqual(eng.url_mode(I, 'https://app.example.test/'), 'path')
        I.browser_url = 'https://office.example.test/'
        self.assertEqual(eng.url_mode(I, 'https://app.example.test/'), 'hostname')
        self.assertIn('/cool/', eng.editor_paths)
        with self.assertRaises(engines.EngineUnavailable):
            engines.get('nope')

    def test_plan(self):
        self.assertNotIn('reboot', catalog.plan('local'))
        self.assertIn('reboot', catalog.plan('vm'))
        self.assertEqual(catalog.plan('local', only=['readonly']), ['guard', 'fixtures', 'readonly', 'cleanup'])
        self.assertNotIn('cleanup', [k for k in catalog.plan('local', skip=['concurrent'])
                                     if k == 'concurrent'])
        self.assertIn('cleanup', catalog.plan('local', skip=['cleanup']))


# ---------------------------------------------------------------------------
# test data on a database (test DB)
# ---------------------------------------------------------------------------

class FixturesDbTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='livecheck-media-')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def test_create_sign_in_cleanup(self):
        from django.contrib.sessions.backends.db import SessionStore
        from audit.models import AuditLog
        from core.models import Organization
        from docs.models import Document
        from office import storage
        from office.models import FileRevision
        other = Organization.objects.create(name='Real Customer', slug='real-customer')
        red = Redactor()
        fx = fixtures.Fixtures(red)
        ids = fx.create()
        self.assertEqual(set(ids['users']), {'editor', 'editor2', 'reader'})
        self.assertEqual(fx.org.name, fixtures.TEST_ORG_NAME)
        with self.assertRaisesRegex(RuntimeError, 'previous run'):
            fixtures.Fixtures(red).create()
        # passwords are random and registered for redaction, never stored in clear
        self.assertTrue(red._literals)
        for u in fx.users.values():
            self.assertTrue(any(u.check_password(p) for p in red._literals))
            from accounts.models import UserProfile
            self.assertEqual(UserProfile.objects.get(user=u).user_type, 'staff')
        # sessions are signed in and OTP-verified
        cookies = fx.cookies('editor', 'https://app.example.test/')
        self.assertEqual(cookies[0]['domain'], 'app.example.test')
        self.assertTrue(cookies[0]['secure'] and cookies[0]['httpOnly'])
        s = SessionStore(session_key=cookies[0]['value'])
        self.assertEqual(s['_auth_user_id'], str(fx.users['editor'].pk))
        self.assertTrue(s['otp_device_id'])
        self.assertIn(cookies[0]['value'], red._literals)
        # documents through office.creation; reader cannot edit
        target = fx.new_document('docx', 'Live check test')
        self.assertTrue(target.can_edit(fx.users['editor']))
        self.assertFalse(target.can_edit(fx.users['reader']))
        rev = storage.current(target)
        path = storage._abs(rev.file.name)
        self.assertTrue(path.exists())
        other_doc = Document.objects.create(organization=other, title='Keep', slug='keep',
                                            content_type='html', body='x')
        reloaded = fixtures.Fixtures.load(red, ids)
        self.assertEqual(reloaded.org.pk, fx.org.pk)
        AuditLog.objects.create(user=fx.users['editor'], username='livecheck-editor',
                                action='create', organization=fx.org, description='live check')
        summary = fixtures.cleanup()
        self.assertEqual(summary['documents'], 1)
        self.assertEqual(fixtures.leftovers(), [])
        self.assertFalse(FileRevision.objects.filter(organization_id=ids['org']).exists())
        self.assertFalse(path.exists())
        self.assertFalse(SessionStore().exists(cookies[0]['value']))
        self.assertTrue(Document.objects.filter(pk=other_doc.pk).exists())
        self.assertTrue(Organization.objects.filter(pk=other.pk).exists())
        self.assertTrue(AuditLog.objects.filter(username='livecheck-editor').exists())


class RunOpTests(TestCase):
    """Context.run_op: queues through the engine, drives --run-pending,
    and refuses to drain when a real user opened a session."""

    def setUp(self):
        from core.models import Organization
        from office.models import EditorInstance
        self.org = Organization.objects.create(name='Cust', slug='cust')
        self.inst = EditorInstance.objects.create(
            provider='collabora', name='Managed', mode='managed_local',
            browser_url='https://app.example.test/', callback_base_url='https://app.example.test/',
            enabled=True, health_status='ok')
        self.root = tempfile.mkdtemp()
        self.state = RunState.create(self.root, profile='local', engine='collabora', plan=['x'], options={})

    def tearDown(self):
        shutil.rmtree(self.root)

    def ctx(self, engine, **opts):
        return checks.Context(state=self.state, engine=engine, fixtures=None, browser=None,
                              opts=dict({'poll_seconds': 0}, **opts), redactor=Redactor(),
                              operator=None, base_url='https://app.example.test/', sleep=lambda s: None)

    def engine(self, slices=3):
        inst = self.inst

        class Op:
            pk, action, target_release, helper_submits, error, progress = 7, 'restart', '', 1, '', {}

            def __init__(self):
                self.left = slices
                self.state = 'draining'

            @property
            def is_active(self):
                return self.left > 0

            def refresh_from_db(self):
                self.left -= 1
                self.state = 'succeeded' if self.left <= 0 else 'running'

        class E:
            name, provider = 'collabora', 'collabora'
            queued, pending = [], 0

            def instance(self):
                return inst

            def queue(self, action, user, release=''):
                self.queued.append(action)
                return Op()

            def run_pending(self):
                E.pending += 1
        return E()

    def test_drives_to_the_end(self):
        eng = self.engine()
        op = self.ctx(eng).run_op_ok('restart')
        self.assertEqual(op.state, 'succeeded')
        self.assertEqual(eng.queued, ['restart'])
        self.assertEqual(type(eng).pending, 3)

    def test_real_session_blocks_drain(self):
        from office.models import EditSession
        real = User.objects.create_user('real-user', 'r@example.test', 'x')
        EditSession.objects.create(organization=self.org, user=real, instance=self.inst,
                                   provider='collabora', mode='edit', document_key='k',
                                   expires_at=timezone.now() + timedelta(hours=1),
                                   max_expires_at=timezone.now() + timedelta(hours=8))
        eng = self.engine()
        with self.assertRaisesRegex(checks.Skip, 'real edit session'):
            self.ctx(eng).run_op('restart')
        self.assertEqual(eng.queued, [])
        # install/start do not drain: allowed
        self.ctx(eng).run_op('start')
        # and the override lets a drain through
        self.ctx(eng, allow_open_sessions=True).run_op('restart')
        self.assertEqual(eng.queued, ['start', 'restart'])

    def test_timeout_fails(self):
        eng = self.engine(slices=10 ** 6)
        clock = iter(range(0, 10 ** 7, 100))
        c = self.ctx(eng, op_timeout=250)
        c.monotonic = lambda: next(clock)
        with self.assertRaisesRegex(checks.Fail, 'did not finish'):
            c.run_op('restart')


# ---------------------------------------------------------------------------
# the browser worker against a fake editor page (real Chromium, if present)
# ---------------------------------------------------------------------------

_PY, _PY_DETAIL = browser.find_python()
_CHROME, _ = browser.chromium_present()


@skipUnless(_PY and _CHROME and os.environ.get('LIVECHECK_SKIP_BROWSER') != '1',
            'no Python with Playwright and Chromium for the worker test')
class BrowserWorkerTests(TestCase):
    def test_open_type_save_readonly_cookies(self):
        from livecheck import fake_editor_site
        server, base = fake_editor_site.serve()
        evidence = tempfile.mkdtemp()
        red = Redactor(['cookie-value-123456'])
        b = browser.Browser(_PY, redactor=red, timeout=120)
        try:
            b.call('start', evidence_dir=evidence)
            b.call('context', id='a', base_url=base, cookies=[{
                'name': 'sessionid', 'value': 'cookie-value-123456', 'domain': '127.0.0.1',
                'path': '/', 'httpOnly': True}])
            ed = engines.COLLABORA_BROWSER
            r = b.call('open', ctx='a', detail_url='/office/f/doc/1/', mode='edit')
            self.assertTrue(r['opened'] and r['session_id'])
            b.call('wait_ready', ctx='a', editor=ed, timeout=60)
            self.assertEqual(b.call('type', ctx='a', editor=ed, fmt='docx', text='MARK42')['state']['state'],
                             'dirty')
            self.assertTrue(b.call('save', ctx='a', editor=ed)['clicked'])
            st = b.call('wait_state', ctx='a', states=['saved', 'failed'], timeout=30)['state']
            self.assertEqual(st['state'], 'saved')
            self.assertEqual(server.site.saved, ['MARK42'])
            server.site.fail_saves = True
            b.call('type', ctx='a', editor=ed, fmt='docx', text='X')
            b.call('save', ctx='a', editor=ed)
            self.assertEqual(b.call('wait_state', ctx='a', states=['failed'], timeout=30)['state']['state'],
                             'failed')
            c = b.call('cookies', ctx='a', editor=ed)
            self.assertNotIn('cookie-value-123456', json.dumps(c))
            self.assertTrue([x for x in c['jar'] if x['name'] == 'sessionid'][0]['httpOnly'])
            self.assertNotIn('sessionid', c['frame_cookie_names'])
            self.assertEqual(b.call('post', ctx='a', url='/office/api/x/forcesave/')['status'], 409)
            self.assertTrue(os.path.exists(b.call('screenshot', ctx='a', name='w')['path']))
            b.call('leave', ctx='a')
            r = b.call('open', ctx='a', detail_url='/office/f/doc/1/', mode='view')
            st = b.call('wait_ready', ctx='a', editor=ed, timeout=60)['state']
            self.assertEqual((st['state'], st['readonly_badge'], st['save_buttons']), ('readonly', True, 0))
            self.assertFalse(b.call('nonsense', check=False)['ok'])
        finally:
            b.close()
            server.shutdown()
            shutil.rmtree(evidence, ignore_errors=True)


class RealFactsTests(TestCase):
    """gather_facts and the dry run against this clientst0r's real code,
    with no helper on the machine: read only, refused, nothing created."""

    @override_settings(OFFICE_MANAGED_SOCKET='/nonexistent/livecheck-helper.sock')
    def test_dry_run_without_helper_is_refused_and_changes_nothing(self):
        from core.models import Organization
        User.objects.create_superuser('op', 'op@example.test', 'x')
        root = tempfile.mkdtemp()
        try:
            lines = []
            r = runner.Runner(dict(LOCAL_OPTS, state_dir=root, dry_run=True), engines.get('onlyoffice'),
                              out=lines.append)
            orgs = Organization.objects.count()
            self.assertEqual(r.dry_run(), runner.EXIT_REFUSED)
            text = '\n'.join(lines)
            self.assertIn('helper', text)
            self.assertIn('roundtrip_docx', text)
            self.assertEqual(Organization.objects.count(), orgs)
            self.assertEqual(os.listdir(root), [])
            facts, _ = runner.gather_facts(engines.get('collabora'), LOCAL_OPTS)
            self.assertFalse(facts['engine']['available'])
            self.assertEqual(facts['real_sessions'], 0)
            self.assertTrue(facts['operator']['is_superuser'])
        finally:
            shutil.rmtree(root)

    def test_engine_command_options(self):
        eng = engines.get('onlyoffice')
        self.assertIn('run_pending', eng._command_options())
        self.assertEqual(eng._engine_kwargs(), {})     # no --engine switch on this base
