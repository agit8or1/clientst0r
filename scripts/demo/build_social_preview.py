"""Build docs/images/github/social-preview.png (1280x640, GitHub's size).

The wordmark, a one-line pitch, and two of the gallery screenshots (the
ticket page and the switch panel). Rebuild it after recapturing those two:

    /usr/bin/python3 scripts/demo/build_social_preview.py

Needs Playwright (system Python). GitHub has no API for the social preview,
so upload the result by hand: Settings -> General -> Social preview.
"""
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
IMG = ROOT / 'docs' / 'images' / 'github'
OUT = IMG / 'social-preview.png'
BACK = IMG / 'ticket-detail-light.png'
FRONT = IMG / 'hardware-device-light.png'
LOGO = ROOT / 'static' / 'images' / 'favicon.svg'

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; width: 1280px; height: 640px; overflow: hidden; }
body { font-family: "DejaVu Sans", "Segoe UI", Arial, sans-serif; color: #e6edf7;
       background: radial-gradient(circle at 0% 100%, #16305a 0, transparent 45%),
                   linear-gradient(135deg, #0b1220 0%, #0f1b30 60%, #0b1220 100%); }
.left { position: absolute; left: 72px; top: 104px; width: 540px; }
.brand { display: flex; align-items: center; gap: 18px; }
.brand img { width: 74px; height: 74px; }
.name { font-size: 40px; font-weight: 700; letter-spacing: .5px; }
.name b { color: #3b82f6; }
.tag { font-size: 13px; letter-spacing: 2px; color: #93a4bd; margin-top: 2px; }
h1 { font-size: 42px; line-height: 1.1; margin: 40px 0 22px; font-weight: 700; }
p { font-size: 21px; line-height: 1.45; color: #aab8cc; margin: 0 0 24px; }
.pills span { display: inline-block; font-size: 16px; padding: 6px 12px; margin-right: 6px;
              border: 1px solid #2c4366; border-radius: 999px; background: #13233d; color: #cfe0f7; }
.shot { position: absolute; border-radius: 10px; overflow: hidden;
        box-shadow: 0 18px 50px rgba(0,0,0,.55); background: #fff; }
.shot img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: left top; }
.back { left: 640px; top: 70px; width: 680px; height: 420px; }
.front { left: 770px; top: 300px; width: 560px; height: 300px; }
</style></head><body>
<div class="left">
  <div class="brand"><img src="LOGO" alt="">
    <div><div class="name">ClientSt<b>0</b>r</div><div class="tag">SELF-HOSTED IT DOCS &amp; SERVICE DESK</div></div></div>
  <h1>IT documentation and service desk for MSPs, self-hosted.</h1>
  <p>Client workspaces, runbooks, an encrypted vault, ticketing with SLAs and billing &mdash;
     and the physical network, drawn.</p>
  <div class="pills"><span>Multi-tenant</span><span>Open source</span><span>Docker or one-line install</span></div>
</div>
<div class="shot back"><img src="BACK" alt=""></div>
<div class="shot front"><img src="FRONT" alt=""></div>
</body></html>"""


def main():
    html = (HTML.replace('LOGO', LOGO.as_uri()).replace('BACK', BACK.as_uri())
            .replace('FRONT', FRONT.as_uri()))
    tmp = OUT.with_suffix('.html')
    tmp.write_text(html)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 640})
            page.goto(tmp.as_uri(), wait_until='networkidle')
            page.screenshot(path=str(OUT))
            browser.close()
    finally:
        tmp.unlink(missing_ok=True)
    print(OUT)


if __name__ == '__main__':
    main()
