#!/usr/bin/env python3
"""Write the annotated screenshots and their legends into the guides.

Each guide marks where a figure goes:

    <!-- guide-figure: guide-billing-ready -->
    <!-- /guide-figure -->

and this script fills the block from ``scripts/guide_screenshots.json``: the
image (with its alt text and caption) and a numbered legend whose numbers
match the callouts drawn on the capture. Edit the manifest, not the block.

    python scripts/guide_figures.py          # rewrite the blocks
    python scripts/guide_figures.py --check  # exit 1 if any block is stale
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'scripts' / 'guide_screenshots.json'
IMG_DIR = ROOT / 'docs' / 'images' / 'guides'
BLOCK_RE = re.compile(r'(<!-- guide-figure: ([\w-]+) -->\n)(.*?)(<!-- /guide-figure -->)', re.S)


def figure_markdown(entry: dict, md_path: pathlib.Path) -> str:
    rel = os.path.relpath(IMG_DIR / f"{entry['name']}.png", md_path.parent).replace(os.sep, '/')
    caption = entry.get('caption', '').replace('"', "'")
    title = f' "{caption}"' if caption else ''
    lines = [f"![{entry['alt']}]({rel}{title})", '']
    for i, a in enumerate(entry.get('annotate') or [], 1):
        lines.append(f"{a.get('label') or i}. {a['note']}")
    return '\n'.join(lines) + '\n'


def render(text: str, md_path: pathlib.Path, entries: dict, errors: list) -> str:
    def sub(m):
        name = m.group(2)
        entry = entries.get(name)
        if entry is None:
            errors.append(f'{md_path.relative_to(ROOT)}: no manifest entry {name!r}')
            return m.group(0)
        return m.group(1) + figure_markdown(entry, md_path) + m.group(4)
    return BLOCK_RE.sub(sub, text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    entries = {e['name']: e for e in json.loads(MANIFEST.read_text())['screenshots']}
    errors: list[str] = []
    stale: list[str] = []
    used: set[str] = set()
    for md in sorted(list((ROOT / 'docs').glob('*.md')) + [ROOT / 'README.md']):
        if not md.is_file():
            continue
        text = md.read_text(encoding='utf-8')
        used.update(m.group(2) for m in BLOCK_RE.finditer(text))
        new = render(text, md, entries, errors)
        if new != text:
            stale.append(str(md.relative_to(ROOT)))
            if not args.check:
                md.write_text(new, encoding='utf-8')
    for name, e in entries.items():
        if not (IMG_DIR / f'{name}.png').is_file():
            errors.append(f'docs/images/guides/{name}.png is missing (capture it)')
        if name not in used:
            errors.append(f'{name} is not placed in any guide')
    for e in errors:
        print('error:', e, file=sys.stderr)
    if args.check and stale:
        print('stale figure blocks (run scripts/guide_figures.py): ' + ', '.join(stale), file=sys.stderr)
        return 1
    if stale and not args.check:
        print('updated: ' + ', '.join(stale))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
