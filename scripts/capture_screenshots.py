#!/usr/bin/env python3
"""Capture the documentation screenshot set from a running ClientSt0r instance.

Reads ``scripts/screenshot_manifest.json`` and drives a real browser over the
real application. It never touches production: it refuses to run unless the
settings module it is given points at a database other than the one in the
project's normal settings, and it is designed to be pointed at the isolated
demo instance created by ``scripts/demo/setup_demo.py``.

What it does per entry
----------------------
* switches theme through the application's own toggle (POST to
  ``accounts:toggle_theme``) and waits until ``<html data-theme>`` reflects it,
  rather than injecting CSS — so what is captured is the shipped theme;
* waits for network idle, fonts, and any Leaflet tiles;
* suppresses animations and transient toasts;
* crops to where the page's own content ends, so no capture carries a slab of
  empty background;
* writes an optimised PNG.

Usage
-----
    DEMO_DIR=/path/to/demo \\
    DJANGO_SETTINGS_MODULE=demo_settings_wt \\
    python scripts/capture_screenshots.py --out docs/images/github

    # a subset while iterating
    python scripts/capture_screenshots.py --out /tmp/shots --only tickets-light

Authentication uses a server-side Django session created for the manifest's
``user``; no password is typed and no credential is written to disk.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

DEFAULT_MANIFEST = pathlib.Path(__file__).resolve().parent / 'screenshot_manifest.json'


def _bootstrap_django() -> None:
    root = os.environ.get('DEMO_ROOT') or str(pathlib.Path(__file__).resolve().parent.parent)
    sys.path.insert(0, root)
    os.chdir(root)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()


_bootstrap_django()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from core.models import Organization  # noqa: E402

# Styles applied to every page before capture. Deliberately limited to hiding
# transient chrome and stopping motion — nothing here changes the design being
# photographed.
CAPTURE_CSS = """
  *, *::before, *::after {
      animation-duration: 0s !important;
      animation-delay: 0s !important;
      transition-duration: 0s !important;
      scroll-behavior: auto !important;
  }
  .toast, .toast-container, #djDebug, .debug-toolbar,
  #pwa-install-prompt, .pwa-install-banner { display: none !important; }
  a.skip-link, .skip-link, .visually-hidden-focusable {
      position: absolute !important; width: 1px !important; height: 1px !important;
      overflow: hidden !important; clip: rect(0 0 0 0) !important;
  }
"""

CONTENT_HEIGHT_JS = """() => {
    const root = document.querySelector('main')
              || document.querySelector('.container, .container-fluid')
              || document.body;
    let bottom = 0;
    root.querySelectorAll('*').forEach(el => {
        if (el.closest('footer')) return;
        const st = getComputedStyle(el);
        if (st.visibility === 'hidden' || st.display === 'none') return;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return;
        bottom = Math.max(bottom, r.bottom + window.scrollY);
    });
    return bottom || document.body.scrollHeight;
}"""


def guard_not_production() -> None:
    """Refuse to run against the project's normal database."""
    name = str(settings.DATABASES['default'].get('NAME', ''))
    engine = settings.DATABASES['default'].get('ENGINE', '')
    if 'sqlite' in engine and name and 'demo' not in name.lower():
        raise SystemExit(
            f'Refusing to run: DATABASES.default.NAME is {name!r}, which does not look\n'
            'like a demo database. Point DJANGO_SETTINGS_MODULE at the isolated demo\n'
            'settings (see scripts/demo/README.md).'
        )
    if 'mysql' in engine:
        raise SystemExit(
            'Refusing to run against a MySQL/MariaDB database — that is the production\n'
            'engine for this project. Use the isolated SQLite demo instance.'
        )


def make_session(username: str, org_name: str | None) -> str:
    User = get_user_model()
    user = User.objects.get(username=username)
    store = SessionStore()
    store['_auth_user_id'] = str(user.pk)
    store['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    store['_auth_user_hash'] = user.get_session_auth_hash()
    if org_name:
        org = Organization.objects.get(name=org_name)
        store['current_organization_id'] = org.pk
        store['organization_id'] = org.pk
    device = user.totpdevice_set.first()
    if device:
        store['otp_device_id'] = f'otp_totp.totpdevice/{device.pk}'
    store.create()
    return store.session_key


def current_theme(page) -> str:
    """'dark' or 'light', read from the attribute the app actually sets."""
    theme = page.evaluate("document.documentElement.getAttribute('data-theme') || ''")
    return 'dark' if theme in ('dark', 'dracula', 'monokai', 'nord') else 'light'


def ensure_theme(page, base: str, want: str) -> None:
    """Switch theme through the application's own control, then verify."""
    if current_theme(page) == want:
        return
    page.evaluate("""() => {
        const btn = document.querySelector('button[onclick^="toggleTheme"]');
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    try:
        page.wait_for_function(
            "want => (document.documentElement.getAttribute('data-theme') === 'dark') === (want === 'dark')",
            arg=want, timeout=15000,
        )
    except Exception:
        page.reload(wait_until='networkidle')
    if current_theme(page) != want:
        raise RuntimeError(f'theme did not settle on {want!r}')


def capture(entry, page, base, out_dir) -> pathlib.Path:
    url = base + entry['route']
    page.goto(url, wait_until='networkidle', timeout=60000)
    ensure_theme(page, base, entry.get('theme', 'light'))
    page.add_style_tag(content=CAPTURE_CSS)

    for text in entry.get('wait_for_text', []):
        try:
            page.wait_for_selector(f'text={text}', timeout=20000)
        except Exception:
            print(f'    ! waited in vain for {text!r}')

    try:
        page.wait_for_function('document.fonts ? document.fonts.status === "loaded" : true',
                               timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(entry.get('settle_ms', 1600))

    height = int(page.evaluate(CONTENT_HEIGHT_JS)) + 28
    height = max(entry.get('min_h', 640), min(height, entry.get('max_h', 1400)))
    page.set_viewport_size({'width': entry.get('width', 1440), 'height': height})
    page.wait_for_timeout(600)

    path = out_dir / f"{entry['name']}.png"
    page.screenshot(path=str(path),
                    clip={'x': 0, 'y': 0, 'width': entry.get('width', 1440), 'height': height})
    return path


def optimise(path: pathlib.Path, max_width: int | None = None) -> None:
    """Quantise to a 256-colour palette — flat UI survives it, and it roughly
    thirds the file size. No dithering, which would fuzz small text."""
    from PIL import Image
    im = Image.open(path).convert('RGB')
    if max_width and im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
    im.quantize(colors=256, dither=Image.NONE).save(path, optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', type=pathlib.Path, default=DEFAULT_MANIFEST)
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--base', default=os.environ.get('DEMO_BASE', 'http://127.0.0.1:8099'))
    ap.add_argument('--only', nargs='*', help='capture just these manifest names')
    ap.add_argument('--no-optimise', action='store_true')
    args = ap.parse_args()

    guard_not_production()

    manifest = json.loads(args.manifest.read_text())
    entries = manifest['screenshots']
    if args.only:
        entries = [e for e in entries if e['name'] in set(args.only)]
        if not entries:
            raise SystemExit('no manifest entries matched --only')

    args.out.mkdir(parents=True, exist_ok=True)
    defaults = manifest.get('defaults', {})

    # Sessions are minted up front: Django's ORM refuses to run inside the
    # greenlet Playwright's sync API drives the browser from.
    groups: dict[tuple, list] = {}
    for e in entries:
        key = (e.get('user', defaults.get('user', 'demo.tech')),
               e.get('organization', defaults.get('organization')))
        groups.setdefault(key, []).append(e)
    sessions = {key: make_session(*key) for key in groups}

    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--force-color-profile=srgb',
                                          '--font-render-hinting=none',
                                          '--hide-scrollbars'])
        # One context per (user, organization) so the session cookie matches.
        for key, group in groups.items():
            username, org_name = key
            ctx = browser.new_context(
                viewport={'width': defaults.get('width', 1440),
                          'height': defaults.get('height', 1000)},
                device_scale_factor=defaults.get('scale', 2),
                color_scheme='light',
            )
            ctx.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                              'value': sessions[key],
                              'domain': '127.0.0.1', 'path': '/'}])
            page = ctx.new_page()
            bad: list[str] = []
            page.on('response', lambda r: bad.append(f'HTTP {r.status} {r.url}')
                    if r.status >= 400 else None)
            for entry in group:
                bad.clear()
                try:
                    path = capture(entry, page, args.base, args.out)
                    if not args.no_optimise:
                        optimise(path, entry.get('optimise_width'))
                    size_kb = path.stat().st_size // 1024
                    print(f"  {entry['name']:<34} {entry.get('theme','light'):<5} {size_kb:>5} KB")
                    for b in dict.fromkeys(bad):
                        print(f'    ! {b}')
                        failures.append(f"{entry['name']}: {b}")
                except Exception as exc:  # keep going; report at the end
                    print(f"  {entry['name']:<34} FAILED: {type(exc).__name__}: {exc}")
                    failures.append(f"{entry['name']}: {exc}")
            ctx.close()
        browser.close()

    print(f'\n{len(entries) - len([f for f in failures if "FAILED" in f])}/{len(entries)} captured '
          f'into {args.out}')
    if failures:
        print('\nIssues:')
        for f in failures:
            print(' -', f)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
