#!/usr/bin/env python3
"""Headless Chromium worker for the live checks (Playwright, sync API).

Runs as its own process under any Python that has Playwright (the
production venv does not need it): the harness starts

    <browser python> browser_worker.py

and speaks JSON lines on stdin/stdout, one request -> one reply. It never
imports Django and never sees a database; it gets session cookies for the
test users and URLs, and returns what the page shows. Nothing it prints
contains the cookies (the harness redacts replies as well).

Requests ({"cmd": ..., ...}):

    start      {headless, executable, resolve: ["host=ip"], evidence_dir, slow_mo}
    context    {id, base_url, cookies: [...], route_via: {origin, to, host} | null}
    open       {ctx, detail_url, mode}            submit the file page's open form
    goto       {ctx, url}
    wait_ready {ctx, editor, timeout}             the engine's editor has loaded
    type       {ctx, editor, fmt, text, timeout}  click into the document and type
    save       {ctx, editor}                      press clientst0r's "Save now"
    wait_state {ctx, states, timeout}             #office-save-status data-state
    state      {ctx}
    post       {ctx, url, data}                   same-origin POST with the page's CSRF token
    cookies    {ctx, editor}                    cookie names/flags, names readable in the frame
    screenshot {ctx, name}
    leave      {ctx}                              follow the Back link (closes the session)
    close      {ctx}
    quit

`editor` is the engine's browser profile from engines.py (selectors, click
positions, keys). Replies: {"ok": true, ...} or {"ok": false, "error": ...}.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

SESSION_RE = re.compile(r'/office/edit/([0-9a-f-]{36})/')


class Worker:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.contexts = {}
        self.pages = {}
        self.evidence_dir = '.'

    # -- lifecycle -----------------------------------------------------
    def start(self, req):
        from playwright.sync_api import sync_playwright
        self.evidence_dir = req.get('evidence_dir') or '.'
        os.makedirs(self.evidence_dir, exist_ok=True)
        args = []
        if req.get('resolve'):
            rules = ', '.join(f'MAP {r.split("=", 1)[0]} {r.split("=", 1)[1]}'
                              for r in req['resolve'] if '=' in r)
            args.append(f'--host-resolver-rules={rules}')
        self.pw = sync_playwright().start()
        launch = dict(headless=req.get('headless', True), args=args)
        if req.get('executable'):
            launch['executable_path'] = req['executable']
        if req.get('slow_mo'):
            launch['slow_mo'] = int(req['slow_mo'])
        self.browser = self.pw.chromium.launch(**launch)
        return {'version': self.browser.version}

    def context(self, req):
        cid = req['id']
        if cid in self.contexts:
            self.contexts.pop(cid).close()
        ctx = self.browser.new_context(viewport={'width': 1600, 'height': 1000},
                                       ignore_https_errors=False)
        if req.get('cookies'):
            ctx.add_cookies(req['cookies'])
        via = req.get('route_via')
        if via:
            origin, to, host = via['origin'].rstrip('/'), via['to'].rstrip('/'), via['host']

            def handler(route, request):
                url = to + request.url[len(origin):]
                headers = dict(request.headers, host=host, **{'x-forwarded-proto': 'https'})
                resp = route.fetch(url=url, headers=headers)
                route.fulfill(response=resp)
            ctx.route(origin + '/**', handler)
        ctx.set_default_timeout(30000)
        self.contexts[cid] = ctx
        self.pages[cid] = ctx.new_page()
        self.pages[cid].base = req['base_url'].rstrip('/')
        return {}

    def page(self, req):
        try:
            return self.pages[req['ctx']]
        except KeyError:
            raise RuntimeError(f'no browser context {req.get("ctx")!r}')

    # -- navigation --------------------------------------------------------
    def goto(self, req):
        p = self.page(req)
        url = req['url'] if req['url'].startswith('http') else p.base + req['url']
        resp = p.goto(url, wait_until='domcontentloaded')
        return {'status': resp.status if resp else None, 'url': p.url}

    def open(self, req):
        """Open the file page and submit its open form for `mode`."""
        p = self.page(req)
        p.goto(p.base + req['detail_url'], wait_until='domcontentloaded')
        mode = req.get('mode', 'edit')
        sel = f'form[action$="/open/"]:has(input[name="mode"][value="{mode}"])'
        if p.locator(sel).count() == 0:
            return {'opened': False, 'url': p.url, 'detail': f'no "{mode}" open form on the file page'}
        with p.expect_navigation(wait_until='domcontentloaded', timeout=60000):
            p.locator(sel).first.evaluate('f => f.submit()')
        m = SESSION_RE.search(p.url)
        return {'opened': bool(m), 'session_id': m.group(1) if m else None, 'url': p.url}

    def leave(self, req):
        p = self.page(req)
        p.on('dialog', lambda d: d.accept())
        back = p.locator('[data-office-back]')
        if back.count():
            with p.expect_navigation(wait_until='domcontentloaded', timeout=60000):
                back.first.click()
        else:
            p.goto(p.base + '/', wait_until='domcontentloaded')
        return {'url': p.url}

    # -- editor ------------------------------------------------------------
    def _frame(self, p, editor):
        return p.frame_locator(editor['frame'])

    def wait_ready(self, req):
        p, ed = self.page(req), req['editor']
        timeout = int(req.get('timeout', 120)) * 1000
        t0 = time.time()
        p.wait_for_selector(editor_frame_selector(ed), state='attached', timeout=timeout)
        for sel in ed.get('ready_page') or []:
            p.wait_for_selector(sel, timeout=timeout)
        frame = self._frame(p, ed)
        for sel in ed.get('ready_frame') or []:
            frame.locator(sel).first.wait_for(state='visible', timeout=timeout)
        if ed.get('settle_ms'):
            p.wait_for_timeout(int(ed['settle_ms']))
        return {'seconds': round(time.time() - t0, 1), 'state': self._state(p)}

    def type(self, req):
        p, ed = self.page(req), req['editor']
        fmt = req['fmt']
        box = p.locator(editor_frame_selector(ed)).first.bounding_box()
        if not box:
            raise RuntimeError('the editor frame has no size')
        fx, fy = (ed.get('click') or {}).get(fmt, (0.5, 0.45))
        x, y = box['x'] + box['width'] * fx, box['y'] + box['height'] * fy
        clicks = (ed.get('clicks') or {}).get(fmt, 1)
        p.mouse.click(x, y, click_count=clicks)
        p.wait_for_timeout(500)
        for key in (ed.get('keys_before') or {}).get(fmt, []):
            p.keyboard.press(key)
        p.keyboard.type(req['text'], delay=int(ed.get('type_delay_ms', 40)))
        for key in (ed.get('keys_after') or {}).get(fmt, []):
            p.keyboard.press(key)
        state = self._wait_state(p, ['dirty', 'saving', 'saved'], int(req.get('timeout', 20)))
        return {'state': state}

    def save(self, req):
        p, ed = self.page(req), req['editor']
        btn = p.locator(ed['save_button'])
        if btn.count() == 0:
            return {'clicked': False, 'detail': 'no Save now button (read-only?)'}
        btn.first.wait_for(state='visible', timeout=30000)
        p.wait_for_function('b => !b.disabled', arg=btn.first.element_handle(), timeout=60000)
        btn.first.click()
        return {'clicked': True}

    def _state(self, p):
        return p.evaluate("""() => {
            const s = document.getElementById('office-save-status');
            const t = s ? s.querySelector('.office-save-text') : null;
            return {state: s ? s.getAttribute('data-state') : null,
                    text: t ? t.textContent.trim() : '',
                    readonly_badge: !!document.getElementById('office-readonly-badge'),
                    save_buttons: Array.from(document.querySelectorAll(
                        '#onlyoffice-save-now, #collabora-save-now')).filter(
                        b => b.offsetParent !== null).length,
                    url: location.pathname};
        }""")

    def _wait_state(self, p, states, timeout):
        try:
            p.wait_for_function(
                "states => { const s = document.getElementById('office-save-status');"
                " return s && states.includes(s.getAttribute('data-state')); }",
                arg=list(states), timeout=timeout * 1000, polling=500)
        except Exception:   # noqa: BLE001 - report what the page shows instead
            pass
        return self._state(p)

    def wait_state(self, req):
        return {'state': self._wait_state(self.page(req), req['states'], int(req.get('timeout', 60)))}

    def state(self, req):
        return {'state': self._state(self.page(req))}

    def post(self, req):
        p = self.page(req)
        return p.evaluate("""async ([url, data]) => {
            const cfgEl = document.getElementById('office-editor-config');
            let csrf = '';
            try { csrf = JSON.parse(cfgEl.textContent).csrfToken || ''; } catch (e) {}
            if (!csrf) { const i = document.querySelector('input[name=csrfmiddlewaretoken]');
                         csrf = i ? i.value : ''; }
            const body = new FormData();
            body.append('csrfmiddlewaretoken', csrf);
            Object.entries(data || {}).forEach(([k, v]) => body.append(k, v));
            const r = await fetch(url, {method: 'POST', body, credentials: 'same-origin',
                                        redirect: 'manual', headers: {'Accept': 'application/json'}});
            let json = null; try { json = await r.json(); } catch (e) {}
            return {status: r.status, type: r.type, json};
        }""", [req['url'], req.get('data') or {}])

    def cookies(self, req):
        """Cookie names and flags (never values), plus the cookie names the
        editor frame's own JavaScript can read (same origin only)."""
        p, ed = self.page(req), req['editor']
        jar = [{'name': c['name'], 'domain': c['domain'], 'path': c['path'],
                'httpOnly': c['httpOnly'], 'secure': c['secure'], 'sameSite': c.get('sameSite')}
               for c in p.context.cookies()]
        frame_names, frame_detail = None, ''
        el = p.query_selector(ed['frame'])
        frame = el.content_frame() if el else None
        if frame is None:
            frame_detail = 'no editor frame'
        else:
            try:
                raw = frame.evaluate('() => document.cookie')
                frame_names = sorted({kv.split('=', 1)[0].strip() for kv in raw.split(';') if kv.strip()})
            except Exception as e:  # noqa: BLE001 - cross-origin frame: JS cannot read cookies
                frame_detail = f'frame not readable from the page ({type(e).__name__}): cross-origin'
        return {'jar': jar, 'frame_cookie_names': frame_names, 'frame_detail': frame_detail}

    def screenshot(self, req):
        p = self.page(req)
        name = re.sub(r'[^A-Za-z0-9._-]', '_', req['name'])[:80] + '.png'
        path = os.path.join(self.evidence_dir, name)
        p.screenshot(path=path, full_page=False)
        return {'path': path}

    def close(self, req):
        cid = req['ctx']
        self.pages.pop(cid, None)
        ctx = self.contexts.pop(cid, None)
        if ctx:
            ctx.close()
        return {}

    def quit(self, req):
        for ctx in list(self.contexts.values()):
            ctx.close()
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()
        return {'bye': True}


def editor_frame_selector(ed):
    return ed['frame']


def main():
    w = Worker()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            cmd = req.get('cmd')
            fn = getattr(w, cmd, None) if cmd and not cmd.startswith('_') else None
            if fn is None or cmd in ('page',):
                raise RuntimeError(f'unknown command {cmd!r}')
            reply = dict(fn(req) or {}, ok=True)
        except Exception as e:  # noqa: BLE001 - every failure goes back to the harness
            reply = {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:1500]}'}
        sys.stdout.write(json.dumps(reply, default=str) + '\n')
        sys.stdout.flush()
        if req.get('cmd') == 'quit' if isinstance(req, dict) else False:
            break


if __name__ == '__main__':
    main()
