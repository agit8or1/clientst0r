"""The checks. Each ``check_<key>(ctx)`` returns an Outcome or raises Skip /
Fail / Await. They drive clientst0r through its real code paths:

* lifecycle: ``engine.queue`` (= ``manage.py office_managed --queue``) and
  ``engine.run_pending`` (= the scheduler's ``--run-pending``), so the job
  runner, drain, helper IPC, provisioning and verification all run as in
  production; the harness never calls Docker;
* editing: headless Chromium opens the real file page, submits its open
  form, types into the real editor, presses clientst0r's "Save now", leaves
  through the Back link; clientst0r's stored revision is then read back
  (number, source, sha256 of the bytes, typed text inside the OOXML).

Pure decision helpers (pick_upgrade, reinstall_problem, real-session
filtering) are separate so they are unit-tested without a server.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from . import ooxml, pathmode
from .state import PASSED


class Skip(Exception):
    def __init__(self, reason, evidence=None, not_applicable=False):
        super().__init__(reason)
        self.evidence = dict(evidence or {})
        if not_applicable:
            self.evidence['not_applicable'] = True


class Fail(Exception):
    def __init__(self, reason, evidence=None):
        super().__init__(reason)
        self.evidence = evidence or {}


class Await(Exception):
    """Hand over to the operator; the step continues on --resume."""
    def __init__(self, instructions, resume=None, evidence=None):
        super().__init__(instructions)
        self.resume = resume or {}
        self.evidence = evidence or {}


@dataclass
class Outcome:
    status: str = PASSED
    detail: str = ''
    evidence: dict = field(default_factory=dict)


def expect(cond, message, evidence=None):
    if not cond:
        raise Fail(message, evidence)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def version_key(v):
    try:
        return tuple(int(x) for x in str(v).split('.'))
    except ValueError:
        return (0,)


def pick_upgrade(releases, installed_id):
    """(newer release dict | None, reason). Needs >= 2 listed releases of
    the engine and edition, a newer one in the same compat group, and that
    one installable on this host (helper's own 'problem' empty)."""
    cur = next((r for r in releases if r.get('id') == installed_id), None)
    if cur is None:
        return None, f'the installed release {installed_id!r} is not in the release list'
    same = [r for r in releases if r.get('edition') == cur.get('edition')]
    if len(same) < 2:
        return None, (f'the release list has {len(same)} entry for this engine and edition; '
                      'upgrade/rollback needs at least 2')
    newer = [r for r in same if version_key(r.get('version')) > version_key(cur.get('version'))
             and r.get('compat') == cur.get('compat')]
    if not newer:
        return None, 'no newer release in the same compatibility group'
    ok = [r for r in newer if not r.get('problem')]
    if not ok:
        return None, 'the newer release cannot be installed here: ' + newer[0].get('problem', '')
    return max(ok, key=lambda r: version_key(r.get('version'))), ''


def reinstall_problem(releases, installed_id):
    """'' when the installed release could be installed again after an
    uninstall; otherwise why not (so the harness never uninstalls what it
    cannot put back)."""
    cur = next((r for r in releases if r.get('id') == installed_id), None)
    if cur is None:
        return f'the installed release {installed_id!r} is not in the release list'
    return cur.get('problem') or ''


def drain_order(progress, saved_at):
    """From a ManagedOfficeOperation's progress steps: when new sessions
    were blocked (drain start), when the helper operation was submitted, and
    whether `saved_at` (the revision's time) falls before the submission."""
    from datetime import datetime
    blocked = submitted = None
    for step in (progress or {}).get('steps') or []:
        msg, at = step.get('message', ''), step.get('at')
        if blocked is None and msg.startswith('New editing sessions are blocked'):
            blocked = at
        if submitted is None and msg.startswith('Running on the server'):
            submitted = at
    ok = False
    if submitted and saved_at is not None:
        ok = saved_at <= datetime.fromisoformat(submitted)
    return {'blocked_at': blocked, 'submitted_at': submitted,
            'saved_at': saved_at.isoformat() if saved_at is not None else None,
            'saved_before_submit': ok}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# the context the checks share
# ---------------------------------------------------------------------------

class Context:
    def __init__(self, *, state, engine, fixtures, browser, opts, redactor, operator,
                 base_url, sleep=time.sleep, monotonic=time.monotonic):
        self.state = state
        self.engine = engine
        self.fx = fixtures
        self.browser = browser
        self.opts = opts
        self.redactor = redactor
        self.operator = operator
        self.base_url = base_url.rstrip('/') + '/'
        self.sleep = sleep
        self.monotonic = monotonic
        self.shots = []
        self.run_id = state.data['run_id']

    # -- facts ---------------------------------------------------------
    @property
    def facts(self):
        return self.state.data.setdefault('facts', {})

    def docs(self):
        return self.state.data['fixtures'].setdefault('documents', {})

    def remember_doc(self, key, target):
        self.docs()[key] = target.pk
        self.state.save()

    # -- real users -----------------------------------------------------
    def real_sessions(self):
        from django.utils import timezone
        from office.models import EditSession
        from .fixtures import test_user_ids
        inst = self.engine.instance()
        if inst is None:
            return 0
        return (EditSession.objects.filter(instance=inst, state__in=EditSession.LIVE_STATES,
                                           expires_at__gt=timezone.now())
                .exclude(user_id__in=test_user_ids()).count())

    # -- lifecycle through clientst0r ---------------------------------------
    def run_op(self, action, release='', *, watch=None):
        """Queue `action` as the operator and drive it with --run-pending
        until it finishes. `watch(op)` is called after every slice."""
        from office.managed.jobs import DRAIN_ACTIONS
        if action in DRAIN_ACTIONS and not self.opts.get('allow_open_sessions'):
            n = self.real_sessions()
            if n:
                raise Skip(f'{n} real edit session(s) opened during the run; {action} not started '
                           'so no real user is drained')
        op = self.engine.queue(action, self.operator, release)
        deadline = self.monotonic() + int(self.opts.get('op_timeout', 3600))
        while True:
            self.engine.run_pending()
            op.refresh_from_db()
            if watch:
                watch(op)
            if not op.is_active:
                break
            if self.monotonic() > deadline:
                raise Fail(f'{action} did not finish in {self.opts.get("op_timeout", 3600)} s',
                           {'operation': op_evidence(op)})
            self.sleep(float(self.opts.get('poll_seconds', 5)))
        return op

    def run_op_ok(self, action, release='', **kw):
        op = self.run_op(action, release, **kw)
        expect(op.state == 'succeeded', f'{action}: {op.state}: {op.error}',
               {'operation': op_evidence(op)})
        return op

    # -- browser ----------------------------------------------------------
    def bctx(self, cid, role):
        self.browser.call('context', id=cid, base_url=self.browser_base(),
                          cookies=self.fx.cookies(role, self.browser_base()),
                          route_via=self.opts.get('route_via'))
        return cid

    def browser_base(self):
        return (self.opts.get('browser_base_url') or self.base_url).rstrip('/') + '/'

    def shot(self, cid, name):
        r = self.browser.call('screenshot', check=False, ctx=cid, name=f'{self.run_id}-{name}')
        if r.get('ok'):
            self.shots.append(r['path'])
        return r.get('path')

    def detail_url(self, target):
        from django.urls import reverse
        return reverse('office:target_detail', args=[target.code, target.pk])

    def open_editor(self, cid, target, mode='edit', name=''):
        r = self.browser.call('open', ctx=cid, detail_url=self.detail_url(target), mode=mode)
        if not r.get('opened'):
            self.shot(cid, f'{name or "open"}-not-opened')
            raise Fail(f'the {mode} editor did not open: {r.get("detail") or r.get("url")}')
        ready = self.browser.call('wait_ready', ctx=cid, editor=self.engine.browser,
                                  timeout=int(self.opts.get('editor_timeout', 180)))
        self.shot(cid, f'{name or target.extension}-{mode}-ready')
        return r['session_id'], ready

    def type_text(self, cid, fmt, text, name=''):
        r = self.browser.call('type', ctx=cid, editor=self.engine.browser, fmt=fmt, text=text)
        st = r['state']
        if st.get('state') not in ('dirty', 'saving', 'saved'):
            self.shot(cid, f'{name or fmt}-typed-not-dirty')
            raise Fail(f'typing did not register as a change in the editor (indicator: '
                       f'{st.get("state")} "{st.get("text")}")')
        return st

    def save_and_wait(self, cid, name=''):
        r = self.browser.call('save', ctx=cid, editor=self.engine.browser)
        expect(r.get('clicked'), f'no "Save now" button: {r.get("detail")}')
        st = self.browser.call('wait_state', ctx=cid, states=['saved', 'failed'],
                               timeout=int(self.opts.get('save_timeout', 180)))['state']
        self.shot(cid, f'{name or "save"}-{st.get("state")}')
        return st

    def leave(self, cid, session_id, *, wait_closed=True):
        self.browser.call('leave', ctx=cid)
        if wait_closed and session_id:
            self.wait_session_closed(session_id)

    def wait_session_closed(self, session_id, timeout=180):
        from office.models import EditSession
        deadline = self.monotonic() + timeout
        while self.monotonic() < deadline:
            s = EditSession.objects.filter(pk=session_id).first()
            if s is None or s.state not in EditSession.LIVE_STATES:
                return s.state if s else 'gone'
            self.sleep(3)
        return 'still open'

    # -- server-side evidence ----------------------------------------------
    def current(self, target):
        from office import storage
        target.refresh()
        return storage.current(target)

    def revision_evidence(self, rev, fmt, markers):
        from office import storage
        with storage.open_revision(rev) as fh:
            data = fh.read()
        digest = sha256(data)
        missing = [m for m in markers if not ooxml.contains(data, fmt, m)]
        ev = {'revision': rev.revision_number, 'source': rev.source, 'sha256': digest,
              'stored_sha256': rev.sha256, 'size': len(data)}
        expect(digest == rev.sha256 and len(data) == rev.size,
               f'r{rev.revision_number}: the stored bytes do not match the recorded checksum', ev)
        expect(not missing, f'r{rev.revision_number} does not contain the typed text {missing}', ev)
        return ev

    def expect_new_revision(self, target, before, fmt, markers):
        rev = self.current(target)
        expect(rev is not None and rev.revision_number > before,
               f'no new clientst0r revision (still r{getattr(rev, "revision_number", None)})')
        expect(rev.source == 'editor_save', f'r{rev.revision_number} source is {rev.source}')
        return rev, self.revision_evidence(rev, fmt, markers)

    def marker(self, label):
        return f'LIVECHECK {label} {self.run_id[-6:]}'

    def snapshot_docs(self):
        out = {}
        for key, pk in self.docs().items():
            rev = self.current(self.fx.target(pk))
            out[key] = (rev.revision_number, rev.sha256) if rev else None
        return out

    def expect_docs_intact(self, before):
        from office import storage
        after = self.snapshot_docs()
        changed = {k: (before[k], after.get(k)) for k in before if after.get(k) != before[k]}
        expect(not changed, f'documents changed: {changed}')
        for key, pk in self.docs().items():
            rev = self.current(self.fx.target(pk))
            if rev is not None:
                with storage.open_revision(rev) as fh:
                    expect(sha256(fh.read()) == rev.sha256, f'{key}: stored bytes do not match')
        return {'documents': len(after)}

    def browser_open_works(self, name):
        """Open the DOCX round-trip document in the editor and save a change."""
        pk = self.docs().get('roundtrip_docx')
        if pk is None:
            target = self.fx.new_document('docx', f'Live check reopen {self.run_id}')
            self.remember_doc('roundtrip_docx', target)
        else:
            target = self.fx.target(pk)
        before = self.current(target).revision_number
        cid = self.bctx(name, 'editor')
        try:
            sid, _ = self.open_editor(cid, target, name=name)
            m = self.marker(name)
            self.type_text(cid, 'docx', ' ' + m, name)
            st = self.save_and_wait(cid, name)
            expect(st.get('state') == 'saved', f'save after {name}: {st.get("state")} {st.get("text")}')
            rev, ev = self.expect_new_revision(target, before, 'docx', [m])
            self.leave(cid, sid)
            return ev
        finally:
            self.browser.call('close', check=False, ctx=cid)

    def helper_status(self):
        st = self.engine.status()
        return st


def op_evidence(op):
    steps = (op.progress or {}).get('steps') or []
    return {'id': op.pk, 'action': op.action, 'state': op.state, 'error': (op.error or '')[:500],
            'release': op.target_release, 'helper_submits': op.helper_submits,
            'steps': [s.get('message', '')[:160] for s in steps[-12:]]}


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def check_install(ctx):
    if ctx.opts.get('profile') == 'vm':
        st = ctx.helper_status()
        if not (st.get('installed') or {}).get('release'):
            ctx.run_op_ok('install')
    st = ctx.helper_status()
    inst = (st.get('installed') or {})
    cont = (st.get('container') or {})
    ev = {'release': inst.get('release'), 'digest': inst.get('digest'), 'image': cont.get('image'),
          'health': cont.get('health'), 'running': cont.get('running')}
    expect(inst.get('release'), 'nothing installed', ev)
    expect(str(inst.get('digest', '')).startswith('sha256:'), 'no pinned digest', ev)
    expect('@' + inst['digest'] in (cont.get('image') or ''),
           'the running container is not the pinned digest', ev)
    expect(cont.get('running') and cont.get('health') in ('healthy', 'ok'), 'not running/healthy', ev)
    instance = ctx.engine.instance()
    expect(instance is not None, f'no managed {ctx.engine.provider} editor instance', ev)
    expect(instance.enabled and instance.health_status == 'ok',
           f'editor instance enabled={instance.enabled} health={instance.health_status}', ev)
    rel = next((r for r in ctx.engine.releases() if r.get('id') == inst['release']), {})
    ctx.facts['release'] = {'id': inst['release'], 'version': inst.get('version'),
                            'edition': inst.get('edition'), 'image': rel.get('image', ''),
                            'digest': inst['digest'], 'listed_digest': rel.get('digest', ''),
                            'tested': rel.get('tested')}
    ctx.facts['engine_version'] = inst.get('version') or ''
    ctx.facts['url_mode'] = ctx.engine.url_mode(instance, ctx.base_url)
    ctx.facts['browser_url'] = instance.browser_url
    expect(rel.get('digest') == inst['digest'],
           'the installed digest differs from the release list entry', ev)
    ev['url_mode'] = ctx.facts['url_mode']
    return Outcome(detail=f'{inst["release"]} {inst["digest"][:19]}… healthy; '
                          f'{ctx.facts["url_mode"]} mode', evidence=ev)


def check_path_mode_cookies(ctx):
    instance = ctx.engine.instance()
    mode = ctx.engine.url_mode(instance, ctx.base_url)
    if mode != 'path':
        raise Skip(f'the editor has its own host name ({instance.browser_url}); cookies are '
                   'separated by origin', not_applicable=True)
    paths = ctx.engine.editor_paths
    expect(paths, f'path mode is not supported for {ctx.engine.name}')
    files = [ctx.opts['nginx_conf']] if ctx.opts.get('nginx_conf') else list(ctx.engine.nginx_candidates)
    text, read = '', []
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                text += '\n' + fh.read()
            read.append(f)
        except OSError:
            continue
    ok, findings, covered = pathmode.nginx_cookie_findings(text, paths) if read else \
        (False, ['no readable nginx configuration (pass --nginx-conf FILE)'], {})
    ev = {'nginx_files': read, 'covered': covered, 'findings': findings}
    # Browser side: the session cookie is HttpOnly and not readable in the frame.
    from django.conf import settings
    pk = ctx.docs().get('roundtrip_docx') or next(iter(ctx.docs().values()), None)
    target = ctx.fx.target(pk) if pk else ctx.fx.new_document('docx', f'Live check cookies {ctx.run_id}')
    if not pk:
        ctx.remember_doc('cookies', target)
    cid = ctx.bctx('cookies', 'reader')
    try:
        sid, _ = ctx.open_editor(cid, target, mode='view', name='cookies')
        c = ctx.browser.call('cookies', ctx=cid, editor=ctx.engine.browser)
        ctx.leave(cid, sid)
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
    name = settings.SESSION_COOKIE_NAME
    sess = [x for x in c['jar'] if x['name'] == name]
    ev.update(cookie_jar=c['jar'], frame_cookie_names=c.get('frame_cookie_names'),
              frame_detail=c.get('frame_detail'))
    if sess and not sess[0]['httpOnly']:
        findings.append(f'the {name} cookie is not HttpOnly: editor JavaScript can read it')
    if c.get('frame_cookie_names') and name in c['frame_cookie_names']:
        findings.append(f'the editor frame can read {name}')
    if c.get('frame_cookie_names') and settings.CSRF_COOKIE_NAME in c['frame_cookie_names']:
        ev['warning'] = f'the editor frame can read {settings.CSRF_COOKIE_NAME} (not a session secret)'
    expect(ok and not findings, '; '.join(findings), ev)
    return Outcome(detail=f'nginx drops Cookie for {", ".join(k for k, v in covered.items() if v)}; '
                          f'{name} is HttpOnly and not readable in the editor frame', evidence=ev)


def roundtrip(ctx, fmt):
    key = f'roundtrip_{fmt}'
    target = ctx.fx.new_document(fmt, f'Live check {fmt.upper()} {ctx.run_id}')
    ctx.remember_doc(key, target)
    rev1 = ctx.current(target)
    ev = {'created': {'revision': rev1.revision_number, 'sha256': rev1.sha256}}
    cid = ctx.bctx(key, 'editor')
    try:
        sid, ready = ctx.open_editor(cid, target, name=key)
        ev['editor_load_seconds'] = ready.get('seconds')
        m1 = ctx.marker(f'{fmt} one')
        ctx.type_text(cid, fmt, m1, key)
        st = ctx.save_and_wait(cid, f'{key}-1')
        expect(st.get('state') == 'saved', f'force-save: indicator {st.get("state")} "{st.get("text")}"', ev)
        rev2, ev['force_save'] = ctx.expect_new_revision(target, rev1.revision_number, fmt, [m1])
        ctx.leave(cid, sid)
        closed = ctx.wait_session_closed(sid)
        ev['closed'] = closed
        expect(closed in ('closed', 'gone'), f'session after close: {closed}', ev)
        cur = ctx.current(target)
        ev['after_close'] = ctx.revision_evidence(cur, fmt, [m1])
        # Reopen: the editor must load the stored revision, and a second edit lands.
        sid2, _ = ctx.open_editor(cid, target, name=f'{key}-reopen')
        from office.models import EditSession
        s2 = EditSession.objects.get(pk=sid2)
        expect(s2.base_revision_id == cur.pk,
               f'reopened on r{getattr(s2.base_revision, "revision_number", None)}, '
               f'not r{cur.revision_number}', ev)
        m2 = ctx.marker(f'{fmt} two')
        ctx.type_text(cid, fmt, m2, key)
        st = ctx.save_and_wait(cid, f'{key}-2')
        expect(st.get('state') == 'saved', f'second save: {st.get("state")}', ev)
        _, ev['reopen_save'] = ctx.expect_new_revision(target, cur.revision_number, fmt, [m1, m2])
        ctx.leave(cid, sid2)
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
    return Outcome(detail=f'r{rev1.revision_number} -> r{ev["reopen_save"]["revision"]}, both edits '
                          'stored, checksums match', evidence=ev)


def check_roundtrip_docx(ctx):
    return roundtrip(ctx, 'docx')


def check_roundtrip_xlsx(ctx):
    return roundtrip(ctx, 'xlsx')


def check_roundtrip_pptx(ctx):
    return roundtrip(ctx, 'pptx')


def check_readonly(ctx):
    from office import storage
    from office.models import EditSession
    target = ctx.fx.new_document('docx', f'Live check read-only {ctx.run_id}')
    ctx.remember_doc('readonly', target)
    before = ctx.current(target).revision_number
    reader = ctx.fx.users['reader']
    cid = ctx.bctx('readonly', 'reader')
    ev = {}
    try:
        # The file page offers no edit form to a reader.
        sid, _ = ctx.open_editor(cid, target, mode='view', name='readonly')
        st = ctx.browser.call('state', ctx=cid)['state']
        ev['page'] = st
        expect(st.get('state') == 'readonly' and st.get('readonly_badge') and not st.get('save_buttons'),
               f'the view page is not read-only: {st}', ev)
        # Server refuses: an edit open posted by hand.
        r = ctx.browser.call('post', ctx=cid, url=ctx.detail_url(target) + 'open/', data={'mode': 'edit'})
        edit_sessions = EditSession.objects.filter(user=reader, mode='edit').count()
        ev['edit_open_post'] = {'status': r.get('status'), 'edit_sessions': edit_sessions}
        expect(edit_sessions == 0, 'the server opened an edit session for the read-only user', ev)
        # Server refuses: a save into the reader's view session (provider endpoint,
        # then the storage layer every provider uses).
        if ctx.engine.provider == 'onlyoffice':
            r = ctx.browser.call('post', ctx=cid, url=f'/office/api/onlyoffice/session/{sid}/forcesave/')
            ev['forcesave_post'] = r.get('status')
            expect(r.get('status') == 409, f'forcesave on a view session answered {r.get("status")}', ev)
        session = EditSession.objects.get(pk=sid)
        with storage.open_revision(ctx.current(target)) as fh:
            data = fh.read()
        data = ooxml.with_comment(data, ctx.marker('readonly attempt'))
        outcome = storage.save_or_quarantine(target, data, user=reader, source='editor_save',
                                             session=session, original_name=target.filename)
        ev['storage_refusal'] = {'ok': outcome.ok, 'error': type(outcome.error).__name__
                                 if outcome.error else None}
        expect(not outcome.ok, 'storage accepted a save from a view session', ev)
        expect(ev['storage_refusal']['error'] == 'SessionRevoked',
               f'the save was refused for another reason: {ev["storage_refusal"]}', ev)
        ctx.leave(cid, sid)
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
    after = ctx.current(target).revision_number
    expect(after == before, f'revision changed r{before} -> r{after}', ev)
    return Outcome(detail='view only in the browser; edit open, provider save and storage save all '
                          'refused by the server', evidence=ev)


def check_concurrent(ctx):
    from office.models import EditSession
    target = ctx.fx.new_document('docx', f'Live check co-editing {ctx.run_id}')
    ctx.remember_doc('concurrent', target)
    before = ctx.current(target).revision_number
    a, b = ctx.bctx('co-a', 'editor'), ctx.bctx('co-b', 'editor2')
    try:
        sa, _ = ctx.open_editor(a, target, name='co-a')
        sb, _ = ctx.open_editor(b, target, name='co-b')
        ka = EditSession.objects.get(pk=sa).document_key
        kb = EditSession.objects.get(pk=sb).document_key
        expect(ka == kb, 'the two users did not join the same editing group')
        ma, mb = ctx.marker('co A'), ctx.marker('co B')
        ctx.type_text(a, 'docx', ma, 'co-a')
        ctx.type_text(b, 'docx', ' ' + mb, 'co-b')
        ctx.sleep(5)     # let the co-editing changes reach each other
        st = ctx.save_and_wait(a, 'co-a')
        expect(st.get('state') == 'saved', f'save by A: {st.get("state")}')
        rev, ev = ctx.expect_new_revision(target, before, 'docx', [ma, mb])
        ctx.shot(b, 'co-b-after')
        ctx.leave(a, sa)
        ctx.leave(b, sb)
    finally:
        ctx.browser.call('close', check=False, ctx=a)
        ctx.browser.call('close', check=False, ctx=b)
    return Outcome(detail=f'one group; r{rev.revision_number} holds both users\' text', evidence=ev)


def check_long_session(ctx):
    from office.models import EditSession
    minutes = float(ctx.opts.get('long_minutes', 12))
    target = ctx.fx.new_document('docx', f'Live check long session {ctx.run_id}')
    ctx.remember_doc('long_session', target)
    before = ctx.current(target).revision_number
    cid = ctx.bctx('long', 'editor')
    try:
        sid, _ = ctx.open_editor(cid, target, name='long')
        exp0 = EditSession.objects.get(pk=sid).expires_at
        m1 = ctx.marker('long early')
        ctx.type_text(cid, 'docx', m1, 'long')
        deadline = ctx.monotonic() + minutes * 60
        while ctx.monotonic() < deadline:
            ctx.sleep(min(60, max(0.0, deadline - ctx.monotonic())))
            st = ctx.browser.call('state', ctx=cid)['state']
            expect(st.get('state') != 'failed', f'the session failed while idle: {st}')
        m2 = ctx.marker('long late')
        ctx.type_text(cid, 'docx', ' ' + m2, 'long')
        st = ctx.save_and_wait(cid, 'long')
        expect(st.get('state') == 'saved', f'delayed save: {st.get("state")} {st.get("text")}')
        rev, ev = ctx.expect_new_revision(target, before, 'docx', [m1, m2])
        exp1 = EditSession.objects.get(pk=sid).expires_at
        ev.update(minutes=minutes, expires_before=exp0.isoformat(), expires_after=exp1.isoformat())
        if minutes >= 10:
            expect(exp1 > exp0, 'the session was not renewed during the long session', ev)
        ctx.leave(cid, sid)
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
    return Outcome(detail=f'{minutes:g} min open; the delayed save stored both edits', evidence=ev)


def check_restart_persistence(ctx):
    before = ctx.snapshot_docs()
    op = ctx.run_op_ok('restart')
    ev = {'operation': op_evidence(op)}
    ev.update(ctx.expect_docs_intact(before))
    ev['edit_after'] = ctx.browser_open_works('after-restart')
    return Outcome(detail='restart drained and verified; documents unchanged; editing works after',
                   evidence=ev)


def _wait_healthy(ctx, timeout=900):
    deadline = ctx.monotonic() + timeout
    last = {}
    while ctx.monotonic() < deadline:
        try:
            st = ctx.helper_status()
            last = st.get('container') or {}
            if last.get('running') and last.get('health') in ('healthy', 'ok'):
                return last
        except Exception as e:   # noqa: BLE001 - helper may still be starting
            last = {'error': str(e)[:200]}
        ctx.sleep(10)
    raise Fail(f'the editor container did not come back healthy: {last}')


def _operator_step(ctx, key, instructions):
    s = ctx.state.step(key)
    resume = s.get('resume') or {}
    if not s.get('resumed'):
        from .state import boot_id
        snap = ctx.snapshot_docs()
        raise Await(instructions, resume={'boot_id': boot_id(),
                                          'docs': {k: list(v) if v else None for k, v in snap.items()}})
    return resume


def check_engine_daemon_restart(ctx):
    resume = _operator_step(ctx, 'engine_daemon_restart',
                            'As root on this VM, restart the container engine: '
                            '`sudo systemctl restart docker` (the editor is not drained: this '
                            'simulates a crash). Then run the same command with --resume.')
    cont = _wait_healthy(ctx)
    ev = {'container': cont}
    snap = {k: tuple(v) if v else None for k, v in (resume.get('docs') or {}).items()}
    ev.update(ctx.expect_docs_intact(snap))
    ev['edit_after'] = ctx.browser_open_works('after-engine-restart')
    return Outcome(detail='container back healthy after the engine restart; documents intact',
                   evidence=ev)


def check_reboot(ctx):
    resume = _operator_step(ctx, 'reboot', 'Reboot this VM now: `sudo reboot`. After it is up, '
                                            'run the same command with --resume (or let the '
                                            'clientst0r-livecheck-resume unit do it).')
    from .state import boot_id
    if resume.get('boot_id') and resume['boot_id'] == boot_id():
        raise Await('The VM has not rebooted yet (same boot id). Reboot, then --resume.', resume=resume)
    cont = _wait_healthy(ctx)
    ev = {'container': cont, 'boot_id_changed': True}
    snap = {k: tuple(v) if v else None for k, v in (resume.get('docs') or {}).items()}
    ev.update(ctx.expect_docs_intact(snap))
    ev['edit_after'] = ctx.browser_open_works('after-reboot')
    return Outcome(detail='rebooted; editor healthy; documents intact; editing works', evidence=ev)


def check_connectivity(ctx):
    """The editor becomes unreachable while a user has the document open.

    Local profile: the office container is stopped through clientst0r
    (Stop drains first, so the edit made before it is stored). A save
    attempted afterwards must show the failure in the page, and after Start
    a reopened editor saves again. The helper has no verb that blocks only
    the container's callbacks, so stopping the container is the test."""
    target = ctx.fx.new_document('docx', f'Live check connectivity {ctx.run_id}')
    ctx.remember_doc('connectivity', target)
    before = ctx.current(target).revision_number
    cid = ctx.bctx('conn', 'editor')
    ev = {}
    stop_queued = False
    try:
        sid, _ = ctx.open_editor(cid, target, name='conn')
        m1 = ctx.marker('conn before')
        ctx.type_text(cid, 'docx', m1, 'conn')
        st = ctx.save_and_wait(cid, 'conn-baseline')
        expect(st.get('state') == 'saved', f'baseline save: {st.get("state")}')
        rev1, ev['baseline'] = ctx.expect_new_revision(target, before, 'docx', [m1])
        stop_queued = True
        op = ctx.run_op_ok('stop')
        ev['stop'] = op_evidence(op)
        ctx.browser.call('type', check=False, ctx=cid, editor=ctx.engine.browser, fmt='docx',
                         text=' ' + ctx.marker('conn during'))
        ctx.browser.call('save', check=False, ctx=cid, editor=ctx.engine.browser)
        st = ctx.browser.call('wait_state', ctx=cid, states=['failed'],
                              timeout=int(ctx.opts.get('save_timeout', 180)))['state']
        ctx.shot(cid, 'conn-unreachable')
        ev['while_down'] = st
        expect(st.get('state') == 'failed', f'no save failure shown while the editor is down: {st}', ev)
    except Skip:
        stop_queued = False      # the stop never started (real sessions): nothing to undo
        raise
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
        if stop_queued:
            # Whatever happened, bring the editor back.
            start = ctx.run_op('start')
            ev['start'] = op_evidence(start)
    expect(start.state == 'succeeded', f'start after the outage: {start.state} {start.error}', ev)
    cur = ctx.current(target)
    ev['kept'] = ctx.revision_evidence(cur, 'docx', [m1])
    cid = ctx.bctx('conn2', 'editor')
    try:
        sid, _ = ctx.open_editor(cid, target, name='conn-recovered')
        m3 = ctx.marker('conn after')
        ctx.type_text(cid, 'docx', ' ' + m3, 'conn')
        st = ctx.save_and_wait(cid, 'conn-recovered')
        expect(st.get('state') == 'saved', f'save after recovery: {st.get("state")}', ev)
        _, ev['recovered'] = ctx.expect_new_revision(target, cur.revision_number, 'docx', [m1, m3])
        ctx.leave(cid, sid)
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
    return Outcome(detail='failure shown while the editor was down; stored edits kept; saving works '
                          'after Start', evidence=ev)


def check_maintenance_drain(ctx):
    target = ctx.fx.new_document('docx', f'Live check drain {ctx.run_id}')
    ctx.remember_doc('maintenance_drain', target)
    before = ctx.current(target).revision_number
    cid = ctx.bctx('drain', 'editor')
    seen = {'states': [], 'saved_while': None}

    def watch(op):
        if not seen['states'] or seen['states'][-1] != op.state:
            seen['states'].append(op.state)
        if seen['saved_while'] is None:
            cur = ctx.current(target)
            if cur and cur.revision_number > before:
                seen['saved_while'] = op.state
    try:
        sid, _ = ctx.open_editor(cid, target, name='drain')
        m = ctx.marker('drain unsaved')
        ctx.type_text(cid, 'docx', m, 'drain')     # not saved by the user
        op = ctx.run_op('restart', watch=watch)
        ev = {'operation': op_evidence(op), 'op_states': seen['states'],
              'revision_appeared_during': seen['saved_while']}
        ctx.shot(cid, 'drain-after')
    finally:
        ctx.browser.call('close', check=False, ctx=cid)
    expect(op.state == 'succeeded', f'restart: {op.state} {op.error}', ev)
    rev, ev['saved'] = ctx.expect_new_revision(target, before, 'docx', [m])
    ordered = drain_order(op.progress, rev.created_at)
    ev['drain_order'] = ordered
    expect(ordered['blocked_at'], 'the restart never blocked new sessions and drained', ev)
    expect(ordered['submitted_at'], 'the restart never reached the server', ev)
    expect(ordered['saved_before_submit'],
           'the unsaved edit was stored after the helper restart was submitted, not during the drain', ev)
    return Outcome(detail=f'restart waited in draining; the unsaved edit landed as r{rev.revision_number} '
                          'before the editor restarted', evidence=ev)


def check_upgrade_rollback(ctx):
    st = ctx.helper_status()
    installed = (st.get('installed') or {}).get('release')
    releases = ctx.engine.releases()
    newer, reason = pick_upgrade(releases, installed)
    if newer is None:
        raise Skip(reason, {'releases': [r.get('id') for r in releases]})
    before = ctx.snapshot_docs()
    ev = {'from': installed, 'to': newer['id']}
    op = ctx.run_op_ok('update', newer['id'])
    ev['update'] = op_evidence(op)
    st = ctx.helper_status()
    expect((st.get('installed') or {}).get('release') == newer['id'], 'update did not install the release', ev)
    expect((st.get('installed') or {}).get('digest') == newer['digest'], 'updated digest mismatch', ev)
    expect(st.get('backups'), 'no pre-update backup listed', ev)
    ev.update(ctx.expect_docs_intact(before))
    ev['edit_on_new'] = ctx.browser_open_works('after-update')
    before = ctx.snapshot_docs()
    op = ctx.run_op_ok('rollback')
    ev['rollback'] = op_evidence(op)
    st = ctx.helper_status()
    expect((st.get('installed') or {}).get('release') == installed, 'rollback did not return', ev)
    ev.update(ctx.expect_docs_intact(before))
    ev['edit_after_rollback'] = ctx.browser_open_works('after-rollback')
    return Outcome(detail=f'{installed} -> {newer["id"]} -> {installed}; documents kept; editing works',
                   evidence=ev)


def check_uninstall_reinstall(ctx):
    st = ctx.helper_status()
    installed = (st.get('installed') or {}).get('release')
    problem = reinstall_problem(ctx.engine.releases(), installed)
    if problem:
        raise Skip(f'not uninstalling: reinstalling {installed} would be refused ({problem})')
    before = ctx.snapshot_docs()
    ev = {}
    op = ctx.run_op_ok('uninstall')
    ev['uninstall'] = op_evidence(op)
    st = ctx.helper_status()
    ev['after_uninstall'] = {'container_exists': (st.get('container') or {}).get('exists'),
                             'secrets_present': st.get('secrets_present'),
                             'data_bytes': st.get('data_bytes')}
    expect(not (st.get('container') or {}).get('exists'), 'the container still exists', ev)
    expect(st.get('secrets_present'), 'secrets were removed by uninstall', ev)
    expect(int(st.get('data_bytes') or 0) > 0, 'editor data was removed by uninstall', ev)
    inst = ctx.engine.instance()
    expect(inst is not None and not inst.enabled, 'the editor stayed open to users after uninstall', ev)
    ev.update(ctx.expect_docs_intact(before))
    op = ctx.run_op_ok('install')
    ev['install'] = op_evidence(op)
    ev.update(ctx.expect_docs_intact(before))
    ev['edit_after'] = ctx.browser_open_works('after-reinstall')
    return Outcome(detail='uninstall kept documents, data and secrets; reinstall opens and saves them',
                   evidence=ev)


def check_cleanup(ctx):
    from . import fixtures
    if ctx.opts.get('keep_test_data'):
        raise Skip('--keep-test-data: run --cleanup-only later')
    summary = fixtures.cleanup()
    left = fixtures.leftovers()
    expect(not left, f'left behind: {left}', summary)
    return Outcome(detail='removed: ' + ', '.join(f'{k}={v}' for k, v in summary.items()), evidence=summary)


CHECK_FUNCS = {name[len('check_'):]: fn for name, fn in dict(globals()).items()
               if name.startswith('check_') and callable(fn)}
