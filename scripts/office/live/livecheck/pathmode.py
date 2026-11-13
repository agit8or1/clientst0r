"""Same-host path mode: the editor is served on clientst0r's own origin
(for example https://clientst0r.example/browser/..., /cool/...), proxied by
the existing nginx. The browser then sends clientst0r's cookies with every
editor request, so the proxy must drop them before they reach the editor.

Two kinds of evidence, both read-only:

* ``nginx_cookie_findings(text, paths)``: every nginx ``location`` that
  serves an editor path must clear the Cookie header
  (``proxy_set_header Cookie "";``) and must not pass the editor's
  Set-Cookie through for clientst0r's cookie names. A location that proxies
  an editor path without clearing Cookie is a finding; no location for a
  path is a finding too (nothing proves where it goes);
* the browser side (checks.py): the clientst0r session cookie is HttpOnly,
  so editor JavaScript on the same origin cannot read it, and the editor
  frame's ``document.cookie`` does not contain it.
"""
from __future__ import annotations

import re

LOCATION_RE = re.compile(r'location\s+(?:(=|~\*?|\^~)\s+)?("[^"]+"|\S+)\s*\{')
CLEAR_COOKIE_RE = re.compile(r'proxy_set_header\s+Cookie\s+(""|\'\')\s*;', re.I)
PASS_SET_COOKIE_RE = re.compile(r'proxy_pass_header\s+Set-Cookie\s*;', re.I)


def _strip_comments(text):
    return '\n'.join(line.split('#', 1)[0] for line in text.splitlines())


def locations(text):
    """[(modifier, path, body)] for every location block (nested included)."""
    text = _strip_comments(text)
    out = []
    for m in LOCATION_RE.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
            i += 1
        out.append((m.group(1) or '', m.group(2).strip('"'), text[m.end():i - 1]))
    return out


def _serves(modifier, loc_path, editor_path):
    probe = editor_path if editor_path.endswith('/') else editor_path + '/'
    if modifier in ('~', '~*'):
        try:
            return re.search(loc_path, probe, re.I if modifier == '~*' else 0) is not None
        except re.error:
            return False
    if modifier == '=':
        return loc_path.rstrip('/') == editor_path.rstrip('/')
    return probe.startswith(loc_path) and loc_path not in ('/', '')


def nginx_cookie_findings(text, paths):
    """(ok, findings, covered) for the given editor path prefixes."""
    findings, covered = [], {}
    locs = locations(text)
    for p in paths:
        serving = [(mod, lp, body) for mod, lp, body in locs if _serves(mod, lp, p)]
        proxied = [(mod, lp, body) for mod, lp, body in serving if 'proxy_pass' in body]
        if not proxied:
            covered[p] = None
            continue
        # nginx picks one location per request; every candidate must be safe.
        bad = [lp for _, lp, body in proxied if not CLEAR_COOKIE_RE.search(body)]
        leaky = [lp for _, lp, body in proxied if PASS_SET_COOKIE_RE.search(body)]
        covered[p] = [lp for _, lp, _ in proxied]
        for lp in bad:
            findings.append(f'location {lp} proxies {p} without proxy_set_header Cookie ""')
        for lp in leaky:
            findings.append(f'location {lp} passes the editor\'s Set-Cookie through')
    if not any(covered.values()):
        findings.append('no nginx location proxies any editor path: cannot prove cookies are dropped')
    return not findings, findings, covered
