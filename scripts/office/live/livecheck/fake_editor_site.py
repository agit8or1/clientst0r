"""A tiny stand-in for clientst0r's file page + editor page, used only by
the harness's own tests to drive browser_worker.py through a real Chromium
(the open form, the save-status indicator, a "Save now" button and an
editor iframe that reports typing). It imitates the page contract of
templates/office/editor.html and static/js/office-editor.js; it is not an
editor.

    server, base = serve()       # http://127.0.0.1:<port>
    ...
    server.shutdown()
"""
from __future__ import annotations

import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILE_PAGE = """<!doctype html><html><body><h1>Plan.docx</h1>
<form method="post" action="/office/f/doc/1/open/"><input type="hidden" name="mode" value="edit"><button>Edit</button></form>
<form method="post" action="/office/f/doc/1/open/"><input type="hidden" name="mode" value="view"><button>View</button></form>
</body></html>"""

EDITOR_PAGE = """<!doctype html><html><head><title>editor</title></head><body style="margin:0">
<header><a href="/office/f/doc/1/" data-office-back>Back</a>
%(badge)s
<div id="office-save-status" data-state="%(state)s"><span class="office-save-text">%(text)s</span></div>
%(button)s
</header>
<script type="application/json" id="office-editor-config">{"csrfToken": "fake-csrf"}</script>
<iframe id="collabora-frame" name="frameEditor" src="/frame" style="width:1200px;height:700px;border:0"></iframe>
<script>
var st = document.getElementById('office-save-status');
function set(s, t) { st.setAttribute('data-state', s); st.querySelector('.office-save-text').textContent = t; }
window.addEventListener('message', function (ev) {
  if (ev.data === 'loaded') { var b = document.getElementById('collabora-save-now'); if (b) b.disabled = false; }
  if (ev.data === 'modified' && st.getAttribute('data-state') !== 'readonly') set('dirty', 'Changes in editor');
});
var btn = document.getElementById('collabora-save-now');
if (btn) btn.addEventListener('click', function () {
  set('saving', 'Saving');
  fetch('/save', {method: 'POST', body: window.__typed || ''}).then(function (r) {
    if (r.ok) set('saved', 'Saved to clientst0r'); else set('failed', 'Save failed');
  });
});
</script></body></html>"""

FRAME = """<!doctype html><html><body style="margin:0">
<div id="document-container" tabindex="0" style="width:100%%;height:690px;background:#eee"></div>
%(welcome)s
<script>
var typed = '';
// Like Collabora CODE's "What's new" dialog: an iframe over the document
// that takes clicks and keys until its own close button is pressed.
window.addEventListener('message', function (ev) {
  if (ev.data === 'welcome-close') { var w = document.querySelector('.iframe-welcome-modal'); if (w) w.remove(); }
});
document.addEventListener('keydown', function (e) {
  if (document.querySelector('.iframe-welcome-modal')) return;
  if (e.key.length === 1) { typed += e.key; parent.__typed = typed; parent.postMessage('modified', '*'); }
});
document.getElementById('document-container').addEventListener('click', function () { this.focus(); });
parent.postMessage('loaded', '*');
</script></body></html>"""

WELCOME_IFRAME = ('<iframe class="iframe-welcome-modal" src="/welcome" '
                  'style="position:absolute;left:0;top:0;width:100%;height:690px;border:0;background:#fff"></iframe>')
WELCOME = """<!doctype html><html><body><h2>Explore the new version</h2>
<button id="welcome-close" onclick="parent.postMessage('welcome-close', '*')">x</button></body></html>"""


class Site:
    def __init__(self):
        self.saved = []
        self.fail_saves = False
        self.posts = []
        self.welcome = True        # the editor frame starts with a welcome dialog over it


def handler_for(site):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body='', ctype='text/html', headers=None):
            data = body.encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/office/f/doc/1/':
                return self._send(200, FILE_PAGE, headers={
                    'Set-Cookie': 'csrftoken=fake-csrf; Path=/'})
            if self.path.startswith('/office/edit/'):
                view = self.path.endswith('?view')
                return self._send(200, EDITOR_PAGE % {
                    'state': 'readonly' if view else 'clean',
                    'text': 'Viewing' if view else 'No unsaved changes',
                    'badge': '<span id="office-readonly-badge">Read-only</span>' if view else '',
                    'button': '' if view else '<button id="collabora-save-now" disabled>Save now</button>'})
            if self.path == '/frame':
                return self._send(200, FRAME % {'welcome': WELCOME_IFRAME if site.welcome else ''})
            if self.path == '/welcome':
                return self._send(200, WELCOME)
            return self._send(404, 'not found')

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(n).decode('utf-8', 'replace')
            site.posts.append((self.path, body))
            if self.path == '/office/f/doc/1/open/':
                view = 'value="view"' in body or 'mode=view' in body
                return self._send(302, '', headers={
                    'Location': f'/office/edit/{uuid.uuid4()}/' + ('?view' if view else '')})
            if self.path == '/save':
                if site.fail_saves:
                    return self._send(502, '{}', 'application/json')
                site.saved.append(body)
                return self._send(200, '{"ok": true}', 'application/json')
            return self._send(409, '{"ok": false}', 'application/json')
    return H


def serve():
    site = Site()
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(site))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.site = site
    return server, f'http://127.0.0.1:{server.server_address[1]}'
