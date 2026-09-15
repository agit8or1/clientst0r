#!/usr/bin/env python3
"""Generate docs/screenshots.md from scripts/screenshot_manifest.json.

The manifest is the single source of truth for what was captured, in which
theme, and what each image shows — so the gallery, its alt text and its
captions cannot drift from the images on disk.

    python scripts/build_gallery.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'scripts' / 'screenshot_manifest.json'
OUT = ROOT / 'docs' / 'screenshots.md'
IMG_DIR = ROOT / 'docs' / 'images' / 'github'

GROUPS = [
    ('overview',   'Overview and dashboards',
     'Where a technician starts the day, and where an owner looks at the whole book of business.'),
    ('insights',   'Visual insights and monitoring',
     'The views that answer a question at a glance — schedules, elevations, address space, margins.'),
    ('workflows',  'Everyday workflows',
     'Ticket to resolution, quote to invoice, and the documentation that hangs off both.'),
    ('management', 'Management and configuration',
     'The commercial side: what is quoted, what is billed, and what each client is entitled to.'),
    ('access',     'Access and administration',
     'Tenancy, membership and the switches that decide which modules exist.'),
]


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    shots = manifest['screenshots']

    missing = [s['name'] for s in shots if not (IMG_DIR / f"{s['name']}.png").exists()]
    if missing:
        print('missing images for:', ', '.join(missing), file=sys.stderr)
        return 1

    light = sum(1 for s in shots if s['theme'] == 'light')
    dark = len(shots) - light

    out: list[str] = []
    w = out.append

    w('# ClientSt0r — screenshot gallery')
    w('')
    w(f'{len(shots)} views of the running application — {light} in the light theme, '
      f'{dark} in dark. Every one is a capture of ClientSt0r against an isolated '
      'demo database; no mockups, no composites.')
    w('')
    w('All organizations, people, hostnames, addresses and credentials below are '
      'invented. Domains use the reserved `.example` TLD and addresses are RFC 1918. '
      'Nothing is masked after the fact because nothing needed masking — the '
      'application never renders a secret into a list, a ticket or a report.')
    w('')
    w('> Regenerate this set with `scripts/capture_screenshots.py`. '
      'See [scripts/demo/README.md](../scripts/demo/README.md) for how the demo '
      'instance is built and why it cannot reach production data.')
    w('')
    w('[← Back to the README](../README.md)')
    w('')
    w('## Contents')
    w('')
    for key, title, _ in GROUPS:
        n = sum(1 for s in shots if s['group'] == key)
        anchor = title.lower().replace(' ', '-')
        w(f'- [{title}](#{anchor}) — {n} view{"s" if n != 1 else ""}')
    w('')
    w('---')
    w('')

    for key, title, blurb in GROUPS:
        group = [s for s in shots if s['group'] == key]
        if not group:
            continue
        w(f'## {title}')
        w('')
        w(blurb)
        w('')
        for s in group:
            theme = 'Light' if s['theme'] == 'light' else 'Dark'
            rel = f"images/github/{s['name']}.png"
            w(f"### {s['heading']}")
            w('')
            w(f'**{theme} theme**')
            w('')
            w(f"[![{s['alt']}]({rel})]({rel})")
            w('')
            w(s['caption'])
            w('')
        w('---')
        w('')

    w('## About these captures')
    w('')
    w('- Viewport 1440 px wide at device pixel ratio 2, so text stays sharp when '
      'you open an image full size.')
    w('- Themes are switched through the application\'s own theme control, not by '
      'injecting CSS — what you see is the shipped theme.')
    w('- Each image is cropped to where the page\'s content ends, so none of them '
      'carry a slab of empty background.')
    w('- Route, theme, viewport and the demo data each view needs are recorded in '
      '[`scripts/screenshot_manifest.json`](../scripts/screenshot_manifest.json).')
    w('')
    w('Prefer moving pictures? The '
      '[3-minute walkthrough](https://github.com/agit8or1/clientst0r/releases/download/'
      'v3.17.558/clientst0r-walkthrough.mp4) covers the same ground end to end, in both '
      'themes.')
    w('')
    w('Older captures from previous releases are kept in '
      '[`docs/screenshots/`](screenshots/README.md).')
    w('')
    w('---')
    w('')
    w('[← Back to the README](../README.md) · '
      '[MSP Reboot](https://mspreboot.com) — the MSP consulting practice behind ClientSt0r')
    w('')

    OUT.write_text('\n'.join(out))
    print(f'wrote {OUT.relative_to(ROOT)} — {len(shots)} views ({light} light / {dark} dark)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
