#!/usr/bin/env python3
"""Validate docs/ux/design-tokens.json and report CSS drift.

    venv/bin/python scripts/ux/check_design_tokens.py            # validate + drift summary
    venv/bin/python scripts/ux/check_design_tokens.py --contrast # markdown table of every contrast pair
    venv/bin/python scripts/ux/check_design_tokens.py --emit-css # the --cs-* custom properties the tokens map to
    venv/bin/python scripts/ux/check_design_tokens.py --verbose  # also list every not-yet-implemented variable

Checks, in order:
  1. Schema: meta.version is semver; every token has a known $type and a value of that type;
     aliases ({a.b.c}) resolve without cycles; the light and dark themes define the same tokens;
     every icon concept names a Font Awesome icon that exists in the vendored stylesheet.
  2. Contrast: every pair under contrast-pairs meets its minimum (WCAG 2.x relative luminance).
  3. Drift: each token maps to one CSS custom property (--cs-...). static/css/*.css is scanned;
     a property that is defined with a literal value different from the token fails (declarations
     inside an application colour theme, a [data-theme="..."] selector, are not compared). A property that
     is not defined anywhere is reported as "not yet implemented" (not a failure), and one defined
     through var()/calc() is reported as indirect (not compared).

Exit status 1 when schema, contrast or drift fails. Standard library only, so other applications
that adopt the spec can copy this file unchanged and point --tokens / --css at their own paths.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / 'docs' / 'ux' / 'design-tokens.json'
CSS_DIR = ROOT / 'static' / 'css'
FA_CSS = ROOT / 'static' / 'vendor' / 'fontawesome' / '6.5.1' / 'css' / 'all.min.css'

TYPES = {'color', 'dimension', 'duration', 'number', 'fontWeight', 'fontFamily', 'cubicBezier', 'shadow'}
HEX = re.compile(r'^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
ALIAS = re.compile(r'^\{([a-zA-Z0-9.\-]+)\}$')
DIMENSION = re.compile(r'^-?\d+(\.\d+)?(px|rem|em|ch|%)$')
DURATION = re.compile(r'^\d+(\.\d+)?ms$')
SEMVER = re.compile(r'^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$')
KEY = re.compile(r'^[a-z0-9][a-z0-9-]*$')
ICON_NAME = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


# --------------------------------------------------------------------------- helpers
def walk(node, path=()):
    """Yield (path tuple, token dict) for every token (a dict with $value)."""
    if isinstance(node, dict):
        if '$value' in node:
            yield path, node
            return
        for k, v in node.items():
            if k.startswith('$'):
                continue
            yield from walk(v, path + (k,))
    elif isinstance(node, list):
        return


def get(doc, dotted):
    node = doc
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def resolve(doc, token, seen=()):
    """Final $value of a token, following {alias} chains."""
    value = token['$value']
    m = ALIAS.match(value) if isinstance(value, str) else None
    if not m:
        return value
    target = m.group(1)
    if target in seen:
        raise ValueError('alias cycle: ' + ' -> '.join(seen + (target,)))
    node = get(doc, target)
    if not isinstance(node, dict) or '$value' not in node:
        raise ValueError(f'alias target not found: {target}')
    return resolve(doc, node, seen + (target,))


def luminance(hex_colour):
    h = hex_colour.lstrip('#')[:6]
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    chans = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --------------------------------------------------------------------------- 1. schema
def check_value(path, token, value, errors):
    t = token.get('$type')
    where = '.'.join(path)
    if t not in TYPES:
        errors.append(f'{where}: unknown $type {t!r}')
        return
    ok = True
    if t == 'color':
        ok = isinstance(value, str) and bool(HEX.match(value))
    elif t == 'dimension':
        ok = isinstance(value, str) and bool(DIMENSION.match(value))
    elif t == 'duration':
        ok = isinstance(value, str) and bool(DURATION.match(value))
    elif t == 'number':
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif t == 'fontWeight':
        ok = isinstance(value, int) and 100 <= value <= 900 and value % 100 == 0
    elif t == 'fontFamily':
        ok = isinstance(value, list) and value and all(isinstance(v, str) and v for v in value)
    elif t == 'cubicBezier':
        ok = (isinstance(value, list) and len(value) == 4 and all(isinstance(v, (int, float)) for v in value)
              and 0 <= value[0] <= 1 and 0 <= value[2] <= 1)
    elif t == 'shadow':
        ok = isinstance(value, str) and bool(value.strip())
    if not ok:
        errors.append(f'{where}: value {value!r} is not a valid {t}')


def check_keys(node, path, errors):
    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith('$'):
                continue
            if not KEY.match(k):
                errors.append(f'{".".join(path + (k,))}: key must be lower-case letters, digits and hyphens')
            if '$value' not in node:
                check_keys(v, path + (k,), errors)


def check_schema(doc, fa_css_text=None):
    errors = []
    meta = doc.get('meta') or {}
    if not SEMVER.match(str(meta.get('version', ''))):
        errors.append('meta.version must be semver (N.N.N)')
    prefix = meta.get('cssPrefix', '')
    if not re.match(r'^--[a-z]+-$', prefix):
        errors.append('meta.cssPrefix must look like "--xx-"')
    if set(meta.get('themes', [])) != {'light', 'dark'}:
        errors.append('meta.themes must be ["light", "dark"]')
    for section in ('primitive', 'theme', 'space', 'font', 'radius', 'border-width', 'motion', 'density',
                    'breakpoint', 'z-index', 'layout', 'icon', 'contrast-pairs'):
        if section not in doc:
            errors.append(f'missing top-level section {section!r}')
    check_keys({k: v for k, v in doc.items() if k not in ('meta', 'contrast-pairs', 'icon')}, (), errors)

    for path, token in walk({k: v for k, v in doc.items() if k not in ('meta', 'contrast-pairs', 'icon')}):
        if '$type' not in token:
            errors.append(f'{".".join(path)}: missing $type')
            continue
        try:
            value = resolve(doc, token)
        except ValueError as exc:
            errors.append(f'{".".join(path)}: {exc}')
            continue
        check_value(path, token, value, errors)

    themes = doc.get('theme', {})
    light = {p for p, _ in walk(themes.get('light', {}))}
    dark = {p for p, _ in walk(themes.get('dark', {}))}
    for p in sorted(light - dark):
        errors.append(f'theme.dark is missing {".".join(p)}')
    for p in sorted(dark - light):
        errors.append(f'theme.light is missing {".".join(p)}')

    icons = (doc.get('icon') or {}).get('concepts') or {}
    if not icons:
        errors.append('icon.concepts is empty')
    for concept, entry in icons.items():
        if not KEY.match(concept):
            errors.append(f'icon.concepts.{concept}: bad key')
        for lib in ('fa', 'lucide'):
            name = entry.get(lib, '')
            if not ICON_NAME.match(name or ''):
                errors.append(f'icon.concepts.{concept}.{lib}: missing or malformed icon name')
        if fa_css_text is not None and entry.get('fa'):
            if not re.search(r'\.fa-%s(?=[:{,\s])' % re.escape(entry['fa']), fa_css_text):
                errors.append(f'icon.concepts.{concept}.fa: fa-{entry["fa"]} is not in the vendored Font Awesome')
    return errors


# --------------------------------------------------------------------------- 2. contrast
def contrast_results(doc):
    """[(pair, ratio or None, error or None)]"""
    out = []
    for pair in (doc.get('contrast-pairs') or {}).get('pairs', []):
        theme = pair.get('theme')
        try:
            fg = _theme_colour(doc, theme, pair['fg'])
            bg = _theme_colour(doc, theme, pair['bg'])
        except (KeyError, ValueError) as exc:
            out.append((pair, None, str(exc)))
            continue
        out.append((pair, contrast(fg, bg), None))
    return out


def _theme_colour(doc, theme, path):
    token = get(doc, f'theme.{theme}.color.{path}')
    if not isinstance(token, dict) or '$value' not in token:
        raise KeyError(f'no token theme.{theme}.color.{path}')
    value = resolve(doc, token)
    if not (isinstance(value, str) and re.match(r'^#[0-9a-fA-F]{6}$', value)):
        raise ValueError(f'theme.{theme}.color.{path} is not an opaque #RRGGBB colour ({value!r})')
    return value


def check_contrast(doc):
    errors = []
    pairs = contrast_results(doc)
    if not pairs:
        errors.append('contrast-pairs.pairs is empty')
    for pair, ratio, err in pairs:
        label = f'{pair.get("theme")}: {pair.get("fg")} on {pair.get("bg")}'
        if err:
            errors.append(f'{label}: {err}')
        elif ratio + 1e-9 < float(pair.get('min', 4.5)):
            errors.append(f'{label}: {ratio:.2f}:1 is under {pair["min"]}:1')
    return errors


# --------------------------------------------------------------------------- 3. CSS mapping + drift
def css_value(token_type, value):
    if token_type == 'fontFamily':
        return ', '.join(f'"{v}"' if ' ' in v else v for v in value)
    if token_type == 'cubicBezier':
        return 'cubic-bezier(%s)' % ', '.join(f'{v:g}' for v in value)
    if token_type == 'color' and isinstance(value, str):
        return value.lower()
    return str(value)


def css_variables(doc):
    """{(context, --name): (token path, css value)} for every token the spec emits as CSS."""
    prefix = doc['meta']['cssPrefix']
    out = {}

    def put(context, name, path, token):
        out[(context, prefix + name)] = ('.'.join(path), css_value(token['$type'], resolve(doc, token)))

    for theme in ('light', 'dark'):
        for path, token in walk(doc['theme'][theme]):
            put(f'theme.{theme}', '-'.join(path), ('theme', theme) + path, token)
    for section, short in (('space', 'space'), ('font', 'font'), ('radius', 'radius'),
                           ('border-width', 'border-width'), ('breakpoint', 'breakpoint'), ('z-index', 'z'),
                           ('layout', 'layout')):
        for path, token in walk(doc[section]):
            put('global', short + '-' + '-'.join(path), (section,) + path, token)
    for path, token in walk(doc['motion']):
        if path[0] == 'reduced':
            put('motion.reduced', 'motion-' + '-'.join(path[1:]), ('motion',) + path, token)
        else:
            put('global', 'motion-' + '-'.join(path), ('motion',) + path, token)
    for mode in ('compact', 'comfortable', 'touch'):
        for path, token in walk(doc['density'][mode]):
            put(f'density.{mode}', '-'.join(path), ('density', mode) + path, token)
    return out


def _strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def css_declarations(text):
    """[(prelude chain joined, --name, value)] for every custom property in a stylesheet."""
    text = _strip_comments(text)
    found = []
    stack, buf = [], ''
    for ch in text:
        if ch == '{':
            stack.append(buf.strip())
            buf = ''
        elif ch == '}':
            for m in re.finditer(r'(--[\w-]+)\s*:\s*([^;]+)', buf):
                found.append((' '.join(stack), m.group(1), m.group(2).strip()))
            if stack:
                stack.pop()
            buf = ''
        else:
            buf += ch
    return found


def context_of(prelude):
    p = prelude.lower()
    if 'data-theme=' in p:
        # An application's own colour theme (Clientst0r: the legacy palettes in themes.css map
        # themselves onto the tokens). Not one of the spec's light/dark contexts, so not compared;
        # their contrast is checked by the application (scripts/ux/build_token_css.py).
        return 'app-theme'
    if 'prefers-reduced-motion' in p:
        return 'motion.reduced'
    if 'max-width' in p and '767' in p:
        return 'density.touch'
    if 'comfortable' in p:
        return 'density.comfortable'
    if 'dark' in p:
        return 'theme.dark'
    return 'default'


def _matches(token_context, css_context):
    if css_context == 'default':
        return token_context in ('global', 'theme.light', 'density.compact')
    return token_context == css_context


def _norm(v):
    v = v.replace('!important', '').strip().lower()
    v = re.sub(r'\s+', ' ', v)
    v = re.sub(r'\s*([,()])\s*', r'\1', v)
    v = v.replace("'", '"')
    if re.match(r'^0(px|rem|ms)?$', v):
        return '0'
    m = re.match(r'^#([0-9a-f]{3})$', v)
    if m:
        v = '#' + ''.join(ch * 2 for ch in m.group(1))
    return v


def check_drift(doc, css_files):
    expected = css_variables(doc)
    prefix = doc['meta']['cssPrefix']
    by_name = {}
    for (ctx, name), (path, value) in expected.items():
        by_name.setdefault(name, []).append((ctx, path, value))

    defined = {}   # (ctx, name) -> [(file, value)]
    unknown = set()
    for f in css_files:
        for prelude, name, value in css_declarations(Path(f).read_text(encoding='utf-8', errors='replace')):
            if not name.startswith(prefix):
                continue
            if name not in by_name:
                unknown.add(name)
                continue
            for ctx, _path, _value in by_name[name]:
                if _matches(ctx, context_of(prelude)):
                    defined.setdefault((ctx, name), []).append((Path(f).name, value))

    errors, indirect, implemented, missing = [], [], [], []
    for key, (path, value) in sorted(expected.items()):
        if key not in defined:
            missing.append(key)
            continue
        implemented.append(key)
        for fname, actual in defined[key]:
            if 'var(' in actual or 'calc(' in actual or 'color-mix(' in actual:
                indirect.append(f'{key[1]} [{key[0]}] in {fname}: {actual}')
            elif _norm(actual) != _norm(value):
                errors.append(f'{key[1]} [{key[0]}] in {fname} is {actual!r}; token {path} is {value!r}')
    return {'errors': errors, 'indirect': indirect, 'implemented': implemented, 'missing': missing,
            'unknown': sorted(unknown), 'total': len(expected)}


def emit_css(doc):
    contexts = doc['meta']['cssContexts']
    groups = {}
    for (ctx, name), (_path, value) in css_variables(doc).items():
        groups.setdefault(ctx, []).append(f'  {name}: {value};')
    order = [('global', ':root'), ('theme.light', contexts['theme.light']),
             ('theme.dark', contexts['theme.dark']), ('density.compact', contexts['density.compact']),
             ('density.comfortable', contexts['density.comfortable'])]
    lines = [f'/* Generated from docs/ux/design-tokens.json v{doc["meta"]["version"]} — do not edit. */']
    for ctx, selector in order:
        lines += [f'{selector} {{'] + groups.get(ctx, []) + ['}']
    # System-following theme: the dark values again, under the user's OS preference.
    lines += ['@media (prefers-color-scheme: dark) {', '  :root[data-cs-theme="system"] {']
    lines += ['  ' + ln for ln in groups.get('theme.dark', [])] + ['  }', '}']
    for ctx in ('density.touch', 'motion.reduced'):
        lines += [contexts[ctx] + ' {', '  :root {'] + ['  ' + ln for ln in groups.get(ctx, [])] + ['  }', '}']
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------- CLI
def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run(tokens_path=TOKENS, css_files=None, fa_css=FA_CSS):
    """Everything the test needs: {'schema': [...], 'contrast': [...], 'drift': {...}}."""
    doc = load(tokens_path)
    fa_text = Path(fa_css).read_text(encoding='utf-8', errors='replace') if fa_css and Path(fa_css).exists() else None
    schema = check_schema(doc, fa_text)
    result = {'doc': doc, 'schema': schema, 'contrast': [], 'drift': None}
    if schema:
        return result
    result['contrast'] = check_contrast(doc)
    if css_files is None:
        css_files = sorted(CSS_DIR.glob('*.css')) if CSS_DIR.exists() else []
    result['drift'] = check_drift(doc, css_files)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tokens', default=str(TOKENS))
    ap.add_argument('--css', nargs='*', help='stylesheets to scan (default static/css/*.css)')
    ap.add_argument('--fa-css', default=str(FA_CSS))
    ap.add_argument('--contrast', action='store_true', help='print every contrast pair as a markdown table')
    ap.add_argument('--emit-css', action='store_true', help='print the --cs-* custom properties')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args(argv)

    res = run(args.tokens, args.css, args.fa_css)
    doc = res['doc']
    if args.emit_css and not res['schema']:
        sys.stdout.write(emit_css(doc))
        return 0
    if args.contrast and not res['schema']:
        print('| Theme | Foreground | Background | Ratio | Min | Use | Result |')
        print('|---|---|---|---|---|---|---|')
        for pair, ratio, err in contrast_results(doc):
            if err:
                print(f'| {pair["theme"]} | {pair["fg"]} | {pair["bg"]} | – | {pair["min"]} | {pair["use"]} | {err} |')
                continue
            fg = _theme_colour(doc, pair['theme'], pair['fg'])
            bg = _theme_colour(doc, pair['theme'], pair['bg'])
            ok = 'pass' if ratio + 1e-9 >= pair['min'] else 'FAIL'
            print(f'| {pair["theme"]} | {pair["fg"]} `{fg.upper()}` | {pair["bg"]} `{bg.upper()}` | '
                  f'{ratio:.2f} | {pair["min"]} | {pair["use"]} | {ok} |')
        return 0

    failed = False
    print(f'design tokens v{doc.get("meta", {}).get("version", "?")}: {args.tokens}')
    if res['schema']:
        failed = True
        print(f'SCHEMA: {len(res["schema"])} error(s)')
        for e in res['schema']:
            print('  - ' + e)
        return 1
    print('schema: ok')
    pairs = len(doc['contrast-pairs']['pairs'])
    if res['contrast']:
        failed = True
        print(f'CONTRAST: {len(res["contrast"])} of {pairs} pair(s) fail')
        for e in res['contrast']:
            print('  - ' + e)
    else:
        print(f'contrast: ok ({pairs} pairs)')
    d = res['drift']
    print(f'css: {len(d["implemented"])} of {d["total"]} token variables implemented, '
          f'{len(d["missing"])} not yet implemented')
    if d['indirect']:
        print(f'  {len(d["indirect"])} defined through var()/calc() (not compared)')
        if args.verbose:
            for e in d['indirect']:
                print('    ' + e)
    if d['unknown']:
        print(f'  {len(d["unknown"])} {doc["meta"]["cssPrefix"]}* variable(s) with no token: ' + ', '.join(d['unknown']))
    if args.verbose:
        for ctx, name in d['missing']:
            print(f'    not yet implemented: {name} [{ctx}]')
    if d['errors']:
        failed = True
        print(f'DRIFT: {len(d["errors"])} mismatch(es)')
        for e in d['errors']:
            print('  - ' + e)
    else:
        print('drift: ok')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
