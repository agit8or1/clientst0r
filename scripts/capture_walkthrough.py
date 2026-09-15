#!/usr/bin/env python3
"""Record the ClientSt0r walkthrough against the isolated demo instance.

Produces, into --out:

    walkthrough.mp4        3-5 minute caption-led tour, 1920x1080 @ 30 fps, H.264
    walkthrough-short.mp4  30-60 second highlight cut
    walkthrough-poster.png poster frame for the README
    walkthrough.vtt        WebVTT captions matching the on-screen text
    walkthrough.txt        plain transcript / narration-ready script

There is no narration: no text-to-speech engine is available in this
environment, so the video is caption-led and `walkthrough.txt` doubles as a
narration script if you want to record voice over it later. Nothing here claims
otherwise.

Frames are captured deterministically (one screenshot per frame at a fixed
interval) rather than by screen-recording, so pacing is exact and there are no
dropped frames or loading flashes. ffmpeg comes from the imageio-ffmpeg wheel
already in the virtualenv.

    DEMO_DIR=... DJANGO_SETTINGS_MODULE=demo_settings_wt \
    python scripts/capture_walkthrough.py --out /var/tmp/clientst0r-media
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys


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

W, H = 1920, 1080
FPS = 30
BASE = os.environ.get('DEMO_BASE', 'http://127.0.0.1:8099')

HIDE = """
  *, *::before, *::after {
      animation-duration: 0s !important; transition-duration: 0s !important;
      scroll-behavior: auto !important;
  }
  .toast, .toast-container, #djDebug { display: none !important; }
  a.skip-link, .skip-link { position: absolute !important; width: 1px !important;
      height: 1px !important; overflow: hidden !important; clip: rect(0 0 0 0) !important; }
"""

CAPTION_CSS = """
#wt-cap { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483647;
  background: rgba(12,18,32,.94); color: #f8fafc;
  font: 500 24px/1.45 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif;
  padding: 20px 34px; letter-spacing: .1px; }
#wt-cap b { color: #8fc0ff; font-weight: 700; }
#wt-card { position: fixed; inset: 0; z-index: 2147483646; background: #0b1220;
  color: #f8fafc; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 18px; text-align: center;
  font-family: -apple-system,'Segoe UI',Helvetica,Arial,sans-serif; }
#wt-card .t { font-size: 62px; font-weight: 700; letter-spacing: -1px; }
#wt-card .s { font-size: 28px; color: #9fb3d1; max-width: 1100px; line-height: 1.4; }
#wt-card .u { font-size: 24px; color: #8fc0ff; margin-top: 10px; }
"""


def session_for(username: str, org_name: str | None) -> str:
    User = get_user_model()
    user = User.objects.get(username=username)
    st = SessionStore()
    st['_auth_user_id'] = str(user.pk)
    st['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    st['_auth_user_hash'] = user.get_session_auth_hash()
    if org_name:
        org = Organization.objects.get(name=org_name)
        st['current_organization_id'] = org.pk
        st['organization_id'] = org.pk
    dev = user.totpdevice_set.first()
    if dev:
        st['otp_device_id'] = f'otp_totp.totpdevice/{dev.pk}'
    st.create()
    return st.session_key


class Recorder:
    """Writes numbered PNG frames and keeps a caption timeline."""

    def __init__(self, page, frames_dir: pathlib.Path):
        self.page = page
        self.dir = frames_dir
        self.n = 0
        self.captions: list[dict] = []
        self._open: dict | None = None

    # -- frames ----------------------------------------------------------
    def frame(self, count: int = 1) -> None:
        for _ in range(count):
            self.page.screenshot(path=str(self.dir / f'{self.n:05d}.png'))
            self.n += 1

    def seconds(self, secs: float) -> None:
        self.frame(max(1, round(secs * FPS)))

    # -- captions --------------------------------------------------------
    def say(self, html: str, plain: str) -> None:
        self._close_caption()
        self.page.evaluate("""(t) => {
            let el = document.getElementById('wt-cap');
            if (!el) { el = document.createElement('div'); el.id = 'wt-cap';
                       document.body.appendChild(el); }
            el.innerHTML = t;
        }""", html)
        self._open = {'start': self.n / FPS, 'text': plain}

    def _close_caption(self) -> None:
        if self._open:
            self._open['end'] = self.n / FPS
            if self._open['end'] > self._open['start']:
                self.captions.append(self._open)
            self._open = None

    def finish(self) -> None:
        self._close_caption()

    # -- motion ----------------------------------------------------------
    def glide(self, to_y: int, secs: float = 1.4) -> None:
        steps = max(2, round(secs * FPS))
        start = self.page.evaluate('window.scrollY')
        for i in range(1, steps + 1):
            self.page.evaluate(f'window.scrollTo(0, {start + (to_y - start) * i / steps})')
            self.frame()

    def card(self, title: str, subtitle: str, url: str, secs: float = 3.0) -> None:
        # A card is a full-screen statement; the running caption must not sit
        # on top of it.
        self._close_caption()
        self.page.evaluate("document.getElementById('wt-cap')?.remove()")
        self.page.evaluate("""(d) => {
            let el = document.getElementById('wt-card');
            if (!el) { el = document.createElement('div'); el.id = 'wt-card';
                       document.body.appendChild(el); }
            el.innerHTML = `<div class="t">${d.t}</div><div class="s">${d.s}</div>`
                         + `<div class="u">${d.u}</div>`;
        }""", {'t': title, 's': subtitle, 'u': url})
        self.seconds(secs)
        self.page.evaluate("document.getElementById('wt-card')?.remove()")


def vtt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'


def write_captions(caps: list[dict], out: pathlib.Path) -> None:
    lines = ['WEBVTT', '']
    for i, c in enumerate(caps, 1):
        lines += [str(i), f"{vtt_time(c['start'])} --> {vtt_time(c['end'])}", c['text'], '']
    out.write_text('\n'.join(lines))


def encode(ffmpeg: str, frames: pathlib.Path, dest: pathlib.Path,
           start_frame: int = 0, frame_count: int | None = None) -> None:
    cmd = [ffmpeg, '-y', '-framerate', str(FPS), '-start_number', str(start_frame),
           '-i', str(frames / '%05d.png')]
    if frame_count:
        cmd += ['-frames:v', str(frame_count)]
    cmd += ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-vf', f'scale={W}:{H}:flags=lanczos', str(dest)]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--keep-frames', action='store_true')
    args = ap.parse_args()

    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    frames = out / 'frames'
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir()

    sess_client = session_for('demo.tech', 'Northwind Logistics')
    sess_msp = session_for('demo.tech', 'Beacon Managed IT')

    script_path = pathlib.Path(__file__).resolve().parent / 'walkthrough_script.json'
    beats = json.loads(script_path.read_text())

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--force-color-profile=srgb', '--hide-scrollbars'])
        ctx = browser.new_context(viewport={'width': W, 'height': H}, device_scale_factor=1,
                                  color_scheme='light')
        ctx.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': sess_client,
                          'domain': '127.0.0.1', 'path': '/'}])
        page = ctx.new_page()
        rec = Recorder(page, frames)
        highlight_range: list[int] = []
        poster_at: list[int] = []

        def visit(route: str, wait_text: str | None = None) -> None:
            page.goto(BASE + route, wait_until='networkidle', timeout=60000)
            page.add_style_tag(content=HIDE)
            page.add_style_tag(content=CAPTION_CSS)
            if wait_text:
                try:
                    page.wait_for_selector(f'text={wait_text}', timeout=15000)
                except Exception:
                    pass
            page.wait_for_timeout(900)

        def set_theme(want: str) -> None:
            cur = page.evaluate("document.documentElement.getAttribute('data-theme')||''")
            is_dark = cur in ('dark', 'dracula', 'monokai', 'nord')
            if (want == 'dark') == is_dark:
                return
            page.evaluate("document.querySelector('button[onclick^=\"toggleTheme\"]')?.click()")
            page.wait_for_timeout(1800)
            page.add_style_tag(content=HIDE)
            page.add_style_tag(content=CAPTION_CSS)

        # Load a real page and its styles up front. The opening beat is a card,
        # and a card drawn on about:blank has no stylesheet to draw with.
        visit('/core/dashboard/')

        for beat in beats:
            kind = beat.get('kind', 'page')
            if kind == 'card':
                rec.card(beat['title'], beat['subtitle'], beat.get('url', ''),
                         beat.get('secs', 3.0))
                continue
            if beat.get('org') == 'msp':
                ctx.clear_cookies()
                ctx.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': sess_msp,
                                  'domain': '127.0.0.1', 'path': '/'}])
            elif beat.get('org') == 'client':
                ctx.clear_cookies()
                ctx.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': sess_client,
                                  'domain': '127.0.0.1', 'path': '/'}])

            visit(beat['route'], beat.get('wait_for_text'))
            if beat.get('theme'):
                set_theme(beat['theme'])
            if beat.get('highlight_start'):
                highlight_range.append(rec.n)
            if beat.get('poster_frame'):
                poster_at.append(rec.n + FPS)  # a second in, once settled
            rec.say(beat['caption_html'], beat['caption_text'])
            rec.seconds(beat.get('hold', 3.0))
            for scroll in beat.get('scrolls', []):
                rec.glide(scroll['to'], scroll.get('secs', 1.5))
                if scroll.get('caption_html'):
                    rec.say(scroll['caption_html'], scroll['caption_text'])
                rec.seconds(scroll.get('hold', 2.5))
            if beat.get('highlight_end'):
                highlight_range.append(rec.n)

        rec.finish()

        # Poster: a frame of the application, not the opening title card.
        # `poster_frame` is set by the beat that reads best as a still.
        poster_idx = poster_at[0] if poster_at else min(400, rec.n - 1)
        shutil.copy(frames / f'{poster_idx:05d}.png', out / 'walkthrough-poster.png')

        browser.close()

    print(f'{rec.n} frames ({rec.n / FPS:.1f}s)')
    encode(ffmpeg, frames, out / 'walkthrough.mp4')
    if len(highlight_range) >= 2:
        start, end = highlight_range[0], highlight_range[1]
        encode(ffmpeg, frames, out / 'walkthrough-short.mp4',
               start_frame=start, frame_count=end - start)
    write_captions(rec.captions, out / 'walkthrough.vtt')
    (out / 'walkthrough.txt').write_text(
        'ClientSt0r walkthrough — transcript\n'
        '(caption-led; no narration track. Use this as a narration script.)\n\n'
        + '\n'.join(f"[{vtt_time(c['start'])}] {c['text']}" for c in rec.captions) + '\n')

    if not args.keep_frames:
        shutil.rmtree(frames)
    for f in sorted(out.iterdir()):
        print(f'  {f.name:<26} {f.stat().st_size // 1024:>7} KB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
