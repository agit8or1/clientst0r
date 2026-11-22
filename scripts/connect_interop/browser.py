"""The harness's "browser": a requests session per administrator, speaking
HTTPS to an installation's admin pages exactly as a browser would (cookies,
CSRF token, Referer), trusting ONLY the per-run test CA (``verify=``).

The browser resolves ``*.interop.test`` to 127.0.0.1 (like a hosts-file
entry on an administrator's workstation); the installations themselves use
netshim's simulated addresses.
"""
from __future__ import annotations

import html
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests

_real_getaddrinfo = socket.getaddrinfo


PORTS = {}   # host name -> the installation's real port (https://name on 443 is forwarded there)


def _browser_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    h = host.decode() if isinstance(host, bytes) else str(host or '')
    h = h.lower().rstrip('.')
    if h.endswith('.interop.test'):
        p = int(port or 443)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', PORTS.get(h, p) if p == 443 else p))]
    return _real_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _browser_getaddrinfo

UI = '/settings/integrations/connected-apps/'
_LAST_T = {}   # (host, user) -> last TOTP time step used (django_otp refuses reuse)


def hotp(key: bytes, counter: int) -> str:
    from django_otp.oath import hotp as _hotp
    return f'{_hotp(key, counter) % 10 ** 6:06d}'


class Browser:
    def __init__(self, inst, username, password, otp_key_hex, ca):
        self.inst, self.username, self.password = inst, username, password
        PORTS[inst.host] = inst.port
        self.otp_key = bytes.fromhex(otp_key_hex)
        self.s = requests.Session()
        self.s.trust_env = False
        self.s.verify = ca
        self.fresh_at = 0.0

    def url(self, path):
        return path if path.startswith('https://') else self.inst.base + path

    def get(self, path, **kw):
        kw.setdefault('timeout', 120)
        return self.s.get(self.url(path), **kw)

    def _csrf(self):
        tok = self.s.cookies.get('csrftoken', domain=self.inst.host + '.local') or self.s.cookies.get('csrftoken')
        if not tok:
            self.get('/account/login/')
            tok = self.s.cookies.get('csrftoken')
        return tok

    def post(self, path, data, *, allow_redirects=False, **kw):
        kw.setdefault('timeout', 180)
        url = self.url(path)
        headers = {'X-CSRFToken': self._csrf(), 'Referer': url}
        return self.s.post(url, data=data, headers=headers, allow_redirects=allow_redirects, **kw)

    # --- authentication ----------------------------------------------------------------
    def otp(self) -> str:
        """A TOTP code django_otp accepts (tolerance 1 step) that was not used
        before by this user: waits for the next 30 s window when needed."""
        key = (self.inst.host, self.username)
        while True:
            now_t = int(time.time()) // 30
            # Never a past step: django_otp re-centres its window on the step a code matched
            # (drift), so a past code would make the next current one fail.
            t = max(now_t, _LAST_T.get(key, 0) + 1)
            if t <= now_t + 1:
                _LAST_T[key] = t
                return hotp(self.otp_key, t)
            time.sleep(1)

    def login(self):
        self.get('/account/login/')
        r = self.post('/account/login/', {'login_view-current_step': 'auth', 'auth-username': self.username,
                                          'auth-password': self.password})
        if r.status_code == 200 and 'token-otp_token' in r.text:
            r = self.post('/account/login/', {'login_view-current_step': 'token', 'token-otp_token': self.otp()})
        if r.status_code not in (302, 303):
            raise RuntimeError(f'{self.inst.label}/{self.username}: sign-in failed ({r.status_code})')
        return r

    def reauth(self, force=False):
        """Connect's "confirm it's you": password + authenticator code."""
        if not force and time.time() - self.fresh_at < 200:
            return
        r = self.post(UI + 'confirm/', {'password': self.password, 'otp': self.otp(), 'next': UI})
        if r.status_code != 302:
            raise RuntimeError(f'{self.inst.label}/{self.username}: re-authentication failed: '
                               f'{messages(r.text)}')
        self.fresh_at = time.time()

    def fresh_fields(self):
        """Inline re-authentication fields for forms that accept them."""
        self.fresh_at = time.time()
        return {'password': self.password, 'otp': self.otp()}

    # --- protected changes (second administrator) -------------------------------------------
    def ta_reauth(self):
        r = self.post('/settings/security/technician-access/', {'action': 'reauth', 'password': self.password,
                                                                 'otp': self.otp()})
        assert r.status_code == 302, r.status_code
        self.fresh_at = time.time()

    def confirm_protected(self, pk):
        self.ta_reauth()
        return self.post('/settings/security/technician-access/', {'action': 'confirm_change', 'change': pk})

    def approve_protected(self, pk):
        self.ta_reauth()
        return self.post('/settings/security/technician-access/', {'action': 'approve_change', 'change': pk})


def messages(text: str) -> list:
    """Django messages / errors shown on a page (for evidence)."""
    out = re.findall(r'class="[^"]*alert[^"]*"[^>]*>(.*?)</div>', text or '', re.S)
    clean = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m))).strip() for m in out]
    return [c for c in clean if c and 'GitHub' not in c][:6]


def follow(browser_by_host: dict, url: str, max_hops=5):
    """Follow redirects across installations, each hop in the browser
    session of the installation the URL points at (cookies per site)."""
    r = None
    for _ in range(max_hops):
        host = urlsplit(url).hostname
        b = browser_by_host[host]
        r = b.get(url, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers['Location'])
            continue
        return r, url
    return r, url
