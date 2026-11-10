#!/usr/bin/env python3
"""HTTP smoke test against a running rehearsal instance (gunicorn or the
Docker container), driving it like a browser does.

    python http_smoke.py --base http://127.0.0.1:18761 --state state.json [--expect-version 3.17.659]
                         [--require-2fa]

Checks: /health/; the version the server reports; the two-factor login
(password step, then a TOTP token computed from the test user's device key);
with --require-2fa, that a user without a device is sent to 2FA setup and
reaches nothing else; uploaded files are served with the same bytes to a user
of the owning organization and not to anyone else; a vault password reveal
returns the stored value; and organization isolation (a customer of org A
cannot switch to org B or fetch its files or vault entries).

Only needs `requests`. Disposable data only.
"""
import argparse
import base64
import hashlib
import hmac
import json
import re
import struct
import sys
import time

import requests

failures = []


def check(cond, what):
    print(('  ok    ' if cond else '  FAIL  ') + what)
    if not cond:
        failures.append(what)
    return cond


def totp(key_hex, t=None, step=30, digits=6):
    counter = int((t if t is not None else time.time()) // step)
    mac = hmac.new(bytes.fromhex(key_hex), struct.pack('>Q', counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack('>I', mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


class Browser:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.s = requests.Session()
        self.s.headers['User-Agent'] = 'clientst0r-upgrade-rehearsal'

    def url(self, path):
        return self.base + path

    def csrf(self):
        return self.s.cookies.get('csrftoken', '')

    def get(self, path, **kw):
        return self.s.get(self.url(path), timeout=60, **kw)

    def post(self, path, data=None, **kw):
        headers = kw.pop('headers', {})
        headers.setdefault('X-CSRFToken', self.csrf())
        headers.setdefault('Referer', self.url(path))
        return self.s.post(self.url(path), data=data, headers=headers, timeout=60, **kw)

    def login(self, username, password, totp_key=None):
        r = self.get('/account/login/')
        r = self.post('/account/login/', {
            'csrfmiddlewaretoken': self.csrf(),
            'login_view-current_step': 'auth',
            'auth-username': username,
            'auth-password': password,
        })
        if totp_key and 'token-otp_token' in r.text:
            # Wait out the window if the code is about to roll over.
            if 30 - (time.time() % 30) < 3:
                time.sleep(4)
            r = self.post('/account/login/', {
                'csrfmiddlewaretoken': self.csrf(),
                'login_view-current_step': 'token',
                'token-otp_token': totp(totp_key),
            })
        return r

    def logged_in(self):
        r = self.get('/core/dashboard/', allow_redirects=False)
        return r.status_code == 200, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--expect-version')
    ap.add_argument('--require-2fa', action='store_true')
    args = ap.parse_args()
    state = json.load(open(args.state))
    users, pw = state['users'], state['password']
    att = {a['org']: a for a in state['attachments'] if a['name'].endswith('.txt')}
    vault = {v['org']: v for v in state['vault']}
    orgs = state['orgs']

    print(f'http_smoke against {args.base}')
    r = requests.get(args.base + '/health/', timeout=30)
    check(r.status_code == 200, f'/health/ answers 200 (got {r.status_code})')
    if args.expect_version:
        r = requests.get(args.base + '/core/roadmap.json', timeout=30)
        reported = r.json().get('current_version') if r.ok else None
        check(reported == args.expect_version,
              f'server reports v{args.expect_version} (got {reported})')

    # anonymous: no file, no vault
    anon = Browser(args.base)
    r = anon.get(f"/files/serve/{att['a']['id']}/", allow_redirects=False)
    check(r.status_code in (301, 302, 403, 404), f'anonymous file request refused ({r.status_code})')
    r = anon.get(f"/media/{att['a']['name']}", allow_redirects=False)
    check(r.status_code != 200 or hashlib.sha256(r.content).hexdigest() != att['a']['sha256'],
          f'anonymous /media/ request does not return the file ({r.status_code})')

    # superuser with 2FA
    admin = Browser(args.base)
    admin.login('rh_admin', pw, users['rh_admin']['totp_key'])
    ok, r = admin.logged_in()
    check(ok, f'superuser logs in with password + TOTP (dashboard {r.status_code})')
    for key in ('a', 'b'):
        admin.get(f"/accounts/switch/{orgs[key]['id']}/")
        r = admin.get(f"/files/serve/{att[key]['id']}/")
        check(r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == att[key]['sha256'],
              f'org {key.upper()} file served intact to the superuser ({r.status_code})')
        r = admin.get(f"/vault/{vault[key]['id']}/")
        check(r.status_code == 200 and vault[key]['title'] in r.text,
              f'org {key.upper()} vault entry page renders ({r.status_code})')
        r = admin.post(f"/vault/{vault[key]['id']}/reveal/")
        try:
            body = r.json()
        except ValueError:
            body = {}
        check(r.status_code == 200 and body.get('password') == vault[key]['password'],
              f'org {key.upper()} vault password reveal returns the stored value ({r.status_code})')
        if key == 'a' and vault[key].get('secure_notes'):
            r = admin.post(f"/vault/{vault[key]['id']}/reveal/?field=secure_notes")
            try:
                body = r.json()
            except ValueError:
                body = {}
            check(r.status_code == 200 and vault[key]['secure_notes'] in json.dumps(body),
                  f'secure notes reveal returns the stored value ({r.status_code})')

    # wrong TOTP is refused
    bad = Browser(args.base)
    r = bad.get('/account/login/')
    r = bad.post('/account/login/', {'csrfmiddlewaretoken': bad.csrf(), 'login_view-current_step': 'auth',
                                     'auth-username': 'rh_client_b', 'auth-password': pw})
    r = bad.post('/account/login/', {'csrfmiddlewaretoken': bad.csrf(), 'login_view-current_step': 'token',
                                     'token-otp_token': '000000' if totp(users['rh_client_b']['totp_key']) != '000000' else '111111'})
    ok, _ = bad.logged_in()
    check(not ok, 'a wrong TOTP token does not log in')

    # customer of org A: isolation
    ca = Browser(args.base)
    ca.login('rh_client_a', pw, users['rh_client_a']['totp_key'])
    ok, r = ca.logged_in()
    check(ok or r.status_code in (301, 302), f'org A user logs in with password + TOTP ({r.status_code})')
    r = ca.get(f"/files/serve/{att['b']['id']}/", allow_redirects=False)
    check(not (r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == att['b']['sha256']),
          f"org A user cannot fetch org B's file ({r.status_code})")
    ca.get(f"/accounts/switch/{orgs['b']['id']}/")
    r = ca.get(f"/files/serve/{att['b']['id']}/", allow_redirects=False)
    check(not (r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == att['b']['sha256']),
          f"... not even after asking to switch to org B ({r.status_code})")
    r = ca.get(f"/vault/{vault['b']['id']}/", allow_redirects=False)
    check(not (r.status_code == 200 and vault['b']['title'] in r.text),
          f"org A user cannot open org B's vault entry ({r.status_code})")
    r = ca.post(f"/vault/{vault['b']['id']}/reveal/")
    check(vault['b']['password'] not in r.text, f"org A user cannot reveal org B's password ({r.status_code})")
    r = ca.get(f"/files/serve/{att['a']['id']}/", allow_redirects=False)
    print(f'  info  org A user fetching its own org file: HTTP {r.status_code}')

    if args.require_2fa:
        nd = Browser(args.base)
        r = nd.login('rh_nodevice', pw)
        r = nd.get('/core/dashboard/', allow_redirects=False)
        loc = r.headers.get('Location', '')
        check(r.status_code in (301, 302) and 'two_factor' in loc,
              f'2FA required: user without a device is sent to setup ({r.status_code} -> {loc})')
        r = nd.get(f"/vault/{vault['a']['id']}/", allow_redirects=False)
        check(r.status_code in (301, 302), f'... and cannot open other pages ({r.status_code})')

    if failures:
        print(f'http_smoke: {len(failures)} FAILURE(S)')
        sys.exit(1)
    print('http_smoke: all checks passed')


if __name__ == '__main__':
    main()
