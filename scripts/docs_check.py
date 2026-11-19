#!/usr/bin/env python3
"""Documentation health check for the README, FEATURES, COMPARISON and docs/.

Stdlib only; no Django import and no network unless --live is given.
Writes a markdown report (stdout, or --output PATH) and exits non-zero only
on hard errors (or on warnings too with --strict).

Checks:
  a. broken image references (error)
  b. broken relative links (error) and missing heading anchors (warning)
  c. gallery freshness: manifest vs docs/images/github/*.png
  d. markdown references to screenshot names missing from the manifest
  e. manifest routes: static prefix check, optional --live status codes
  f. ROADMAP.md phase statuses that look stale (report only, never edited)
  g. old "v3.17.NNN" mentions in README/FEATURES (info)

    python scripts/docs_check.py [--output PATH] [--strict]
                                 [--rebuild-gallery] [--live http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'scripts' / 'screenshot_manifest.json'
IMG_DIR = ROOT / 'docs' / 'images' / 'github'
SHOT_RE = re.compile(r'(?<![\w/])(?:docs/)?images/github/([A-Za-z0-9_.-]+?)\.png')
# Media kept in docs/images/github that the capture tooling does not produce:
# the walkthrough video poster and the GitHub social preview (uploaded by hand
# in the repository settings, so no markdown references it).
NON_MANIFEST_MEDIA = {'walkthrough-poster', 'social-preview'}
MD_IMG_RE = re.compile(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
HTML_SRC_RE = re.compile(r'<(?:img|source)\b[^>]*?\b(?:src|srcset)\s*=\s*["\']([^"\']+)["\']', re.I)
MD_LINK_RE = re.compile(r'(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
HEADER_RE = re.compile(r'^## Phase (\d+)\s+—\s+(.*)$')
SHIPPED_ANNOT_RE = re.compile(r'shipped\s+v?\d|\(shipped|\bshipped v', re.I)
PLANNED_BULLET_RE = re.compile(r'\((?:planned|not implemented)\b', re.I)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def markdown_files() -> list[Path]:
    files = [ROOT / n for n in ('README.md', 'FEATURES.md', 'COMPARISON.md')]
    files += sorted((ROOT / 'docs').rglob('*.md'))
    return [f for f in files if f.is_file()]


def strip_code(text: str) -> str:
    """Blank out fenced and inline code so examples are not checked as links."""
    text = re.sub(r'^(```|~~~).*?^\1[^\n]*$', lambda m: '\n' * m.group(0).count('\n'),
                  text, flags=re.S | re.M)
    return re.sub(r'`[^`\n]*`', '``', text)


def is_external(ref: str) -> bool:
    return bool(re.match(r'^(?:[a-z][a-z0-9+.-]*:|//|#|\{\{)', ref, re.I))


def resolve(md: Path, ref: str) -> tuple[Path, str]:
    path, _, frag = ref.partition('#')
    path = urllib.parse.unquote(path.split('?')[0])
    base = ROOT if path.startswith('/') else md.parent
    return (base / path.lstrip('/')).resolve(), frag


def slugify(heading: str) -> str:
    h = re.sub(r'<[^>]+>', '', heading)
    h = re.sub(r'[*_`]|!?\[([^\]]*)\]\([^)]*\)', r'\1', h).strip().lower()
    h = re.sub(r'[^\w\- ]', '', h)
    return h.replace(' ', '-')


_anchor_cache: dict[Path, set[str]] = {}


def anchors_of(path: Path) -> set[str]:
    if path not in _anchor_cache:
        seen: dict[str, int] = {}
        out: set[str] = set()
        text = strip_code(path.read_text(errors='replace'))
        for line in text.splitlines():
            m = re.match(r'^#{1,6}\s+(.*?)\s*#*\s*$', line)
            if m:
                s = slugify(m.group(1))
                n = seen.get(s, 0)
                out.add(s if n == 0 else f'{s}-{n}')
                seen[s] = n + 1
        out.update(re.findall(r'<a\s+[^>]*?(?:name|id)=["\']([^"\']+)', path.read_text(errors='replace')))
        _anchor_cache[path] = out
    return _anchor_cache[path]


def load_manifest() -> list[dict]:
    try:
        return json.loads(MANIFEST.read_text())['screenshots']
    except (OSError, ValueError, KeyError) as exc:
        print(f'cannot read manifest: {exc}', file=sys.stderr)
        return []


# --- a, b, d: images and links -------------------------------------------------

def check_links_and_images(rep: Report, files: list[Path], names: set[str]) -> set[str]:
    referenced: set[str] = set()
    for md in files:
        raw = md.read_text(errors='replace')
        text = strip_code(raw)
        for m in SHOT_RE.finditer(text):
            referenced.add(m.group(1))
        imgs = MD_IMG_RE.findall(text)
        for srcset in HTML_SRC_RE.findall(text):
            imgs += [part.split()[0] for part in srcset.split(',') if part.strip()]
        for ref in imgs:
            if is_external(ref):
                continue
            target, _ = resolve(md, ref)
            if not target.exists():
                rep.errors.append(f'Broken image in `{rel(md)}`: `{ref}`')
            else:
                m = SHOT_RE.search(rel(target))
                if m and names and m.group(1) not in names | NON_MANIFEST_MEDIA:
                    rep.warnings.append(f'Outdated screenshot name in `{rel(md)}`: `{m.group(1)}` is not in the manifest')
        for ref in MD_LINK_RE.findall(text):
            if (is_external(ref) and not ref.startswith('#')) or ref.startswith('/'):
                continue  # external URLs and site routes (e.g. /privacy-policy/) are not repo files
            if ref.startswith('#'):
                target, frag = md, ref[1:]
            else:
                target, frag = resolve(md, ref)
                if not target.exists():
                    rep.errors.append(f'Broken link in `{rel(md)}`: `{ref}`')
                    continue
            if frag and target.suffix == '.md' and target.is_file():
                if urllib.parse.unquote(frag).lower() not in anchors_of(target):
                    rep.warnings.append(f'Missing anchor in `{rel(md)}`: `{ref}` (no such heading in `{rel(target)}`)')
    return referenced


# --- c: gallery freshness ------------------------------------------------------

def check_gallery(rep: Report, names: set[str], referenced: set[str], rebuild: bool) -> None:
    if rebuild:
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_gallery.py')],
                              capture_output=True, text=True, cwd=ROOT)
        msg = (proc.stdout + proc.stderr).strip().replace('\n', ' ')
        if proc.returncode:
            rep.errors.append(f'Gallery rebuild failed: {msg}')
        else:
            rep.info.append(f'Gallery rebuilt with build_gallery.py: {msg or "ok"}')
    images = {p.stem for p in IMG_DIR.glob('*.png')} if IMG_DIR.is_dir() else set()
    for n in sorted(names - images):
        rep.errors.append(f'Manifest entry `{n}` has no image in docs/images/github/')
    for n in sorted(images - names - NON_MANIFEST_MEDIA):
        if n not in referenced:
            rep.warnings.append(f'Orphan image `{n}.png`: not in the manifest and not referenced by any markdown')
        else:
            rep.warnings.append(f'Image `{n}.png` is referenced in markdown but missing from the manifest')
    shots = ROOT / 'docs' / 'screenshots.md'
    if shots.is_file():
        listed = set(SHOT_RE.findall(shots.read_text(errors='replace')))
        stale = sorted(names - listed)
        if stale:
            rep.warnings.append('docs/screenshots.md does not list: ' + ', '.join(f'`{n}`' for n in stale)
                                + ' (rerun scripts/build_gallery.py)')


# --- e: routes -----------------------------------------------------------------

def check_routes(rep: Report, shots: list[dict], live: str | None) -> None:
    urls_py = (ROOT / 'config' / 'urls.py')
    root_urls = urls_py.read_text(errors='replace') if urls_py.is_file() else ''
    app_urls = [p.read_text(errors='replace') for p in ROOT.glob('*/urls.py')
                if 'venv' not in p.parts]
    root_segments = set(re.findall(r'''(?:re_)?path\(\s*r?['"]\^?([\w-]+)''', root_urls))
    routes = sorted({s['route'] for s in shots if s.get('route')})
    for route in routes:
        seg = route.strip('/').split('/')[0].split('?')[0]
        if not seg:
            continue
        if seg in root_segments:
            continue
        pat = re.compile(r'''['"]\^?%s[/$'"]''' % re.escape(seg))
        if any(pat.search(t) for t in app_urls + [root_urls]):
            continue
        rep.warnings.append(f'Route `{route}`: prefix `{seg}` not found in config/urls.py or app urls.py (static check)')
    if live:
        for route in routes:
            url = live.rstrip('/') + route
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'docs-check'})
                with urllib.request.urlopen(req, timeout=15) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except (urllib.error.URLError, OSError) as e:
                rep.warnings.append(f'Live `{route}`: request failed ({e})')
                continue
            if code >= 400:
                rep.warnings.append(f'Live `{route}`: HTTP {code}')
            else:
                rep.info.append(f'Live `{route}`: HTTP {code}')


# --- f: roadmap ----------------------------------------------------------------

def parse_status(title: str) -> str:
    low = title.lower()
    m = re.search(r'\[([^\]]+)\]\s*$', title.strip())
    marker = (m.group(1).lower() if m else '')
    if 'complete' in marker or 'complete' in low and '**— complete**' in low:
        return 'complete'
    if 'shipped' in marker or '**— shipped**' in low:
        return 'shipped'
    if 'in progress' in marker:
        return 'in_progress'
    return 'planned'


def check_roadmap(rep: Report) -> None:
    road = ROOT / 'docs' / 'ROADMAP.md'
    if not road.is_file():
        rep.warnings.append('docs/ROADMAP.md not found')
        return
    phases: list[dict] = []
    cur = None
    for line in road.read_text(errors='replace').splitlines():
        m = HEADER_RE.match(line)
        if m:
            cur = {'n': int(m.group(1)), 'title': m.group(2), 'status': parse_status(m.group(2)),
                   'bullets': []}
            phases.append(cur)
        elif line.startswith('## '):
            cur = None
        elif cur is not None and re.match(r'^\s*(?:[-*]|\d+\.)\s+', line):
            cur['bullets'].append(line)
    cl = ROOT / 'CHANGELOG.md'
    changelog = cl.read_text(errors='replace') if cl.is_file() else ''
    for p in phases:
        n, st, bl = p['n'], p['status'], p['bullets']
        shipped = [b for b in bl if SHIPPED_ANNOT_RE.search(b)]
        label = f'Phase {n} ({st.replace("_", " ")})'
        partial = [b for b in bl if re.search(r'\(partial|\bplanned\b|deferred', b, re.I)]
        if st == 'in_progress' and bl and len(shipped) == len(bl) and not partial:
            rep.warnings.append(f'{label}: every bullet is annotated shipped; consider marking it complete')
        if st in ('planned', 'in_progress') and not shipped and re.search(rf'\bPhase {n}\b(?!\d)', changelog):
            rep.warnings.append(f'{label}: no shipped bullets but CHANGELOG.md mentions Phase {n}')
        if st in ('complete', 'shipped'):
            left = [b for b in bl if PLANNED_BULLET_RE.search(b)]
            if left:
                rep.warnings.append(f'{label}: {len(left)} bullet(s) still say "(planned)"')
    rep.info.append(f'Roadmap: parsed {len(phases)} phases (report only; ROADMAP.md is never modified)')


# --- g: versions ---------------------------------------------------------------

def check_versions(rep: Report) -> None:
    vf = ROOT / 'config' / 'version.py'
    m = re.search(r"VERSION\s*=\s*['\"](\d+)\.(\d+)\.(\d+)", vf.read_text()) if vf.is_file() else None
    if not m:
        rep.info.append('config/version.py VERSION not found; skipped version check')
        return
    major, minor, patch = map(int, m.groups())
    history = re.compile(r'shipped|added|introduced|since|new in|released|changelog', re.I)
    for name in ('README.md', 'FEATURES.md'):
        f = ROOT / name
        if not f.is_file():
            continue
        old: list[tuple[int, str, int]] = []
        for i, line in enumerate(f.read_text(errors='replace').splitlines(), 1):
            if history.search(line):
                continue  # "shipped vX" style annotations are history, not stale claims
            for a, b, c in re.findall(r'\bv(\d+)\.(\d+)\.(\d+)\b', line):
                if (int(a), int(b)) == (major, minor) and patch - int(c) > 50:
                    old.append((i, f'v{a}.{b}.{c}', patch - int(c)))
        for i, v, gap in old[:10]:
            rep.info.append(f'`{name}:{i}` mentions {v}, {gap} patches older than {major}.{minor}.{patch}')
        if len(old) > 10:
            rep.info.append(f'`{name}`: {len(old) - 10} more outdated version mentions not listed')


# --- output --------------------------------------------------------------------

def render(rep: Report) -> str:
    out = ['# Documentation check', '', '## Summary', '',
           f'- Errors: {len(rep.errors)}', f'- Warnings: {len(rep.warnings)}', f'- Info: {len(rep.info)}', '']
    for title, items in (('Errors', rep.errors), ('Warnings', rep.warnings), ('Info', rep.info)):
        out += [f'## {title}', '']
        out += [f'- {i}' for i in items] if items else ['None.']
        out.append('')
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                 epilog='Exits 1 on errors (or warnings with --strict).')
    ap.add_argument('--output', help='write the markdown report here instead of stdout')
    ap.add_argument('--strict', action='store_true', help='treat warnings as failures')
    ap.add_argument('--rebuild-gallery', action='store_true', help='run scripts/build_gallery.py first')
    ap.add_argument('--live', metavar='BASE_URL', help='GET each manifest route on a running DEMO instance')
    ap.add_argument('--allow-remote', action='store_true', help='allow --live against non-local hosts')
    args = ap.parse_args()

    if args.live and not args.allow_remote and not re.match(r'^http://(127\.0\.0\.1|localhost)(:\d+)?(/|$)', args.live):
        ap.error('--live only accepts http://127.0.0.1 or http://localhost unless --allow-remote is given')

    rep = Report()
    shots = load_manifest()
    names = {s['name'] for s in shots}
    if not shots:
        rep.errors.append('Manifest missing or has no screenshots')
    referenced = check_links_and_images(rep, markdown_files(), names)
    check_gallery(rep, names, referenced, args.rebuild_gallery)
    check_routes(rep, shots, args.live)
    check_roadmap(rep)
    check_versions(rep)

    text = render(rep)
    if args.output:
        Path(args.output).write_text(text)
    else:
        print(text)
    return 1 if rep.errors or (args.strict and rep.warnings) else 0


if __name__ == '__main__':
    sys.exit(main())
