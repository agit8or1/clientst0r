#!/usr/bin/env python3
"""Generate static/css/tokens.css (and the theme-token region of themes.css) from design-tokens.json.

    venv/bin/python scripts/ux/build_token_css.py              # (re)write both outputs
    venv/bin/python scripts/ux/build_token_css.py --check      # exit 1 when either is out of date
    venv/bin/python scripts/ux/build_token_css.py --stdout     # print tokens.css instead
    venv/bin/python scripts/ux/build_token_css.py --no-themes  # tokens.css only

The second output is the region of static/css/themes.css between the generated:theme-tokens
markers: one :root[data-theme="x"] block per colour theme that sets the semantic --cs-color-*
tokens from that theme's own palette (see "legacy themes -> tokens" below).

The stylesheet is the --cs-* custom properties of every token (primitives are not emitted: CSS reads
the semantic theme tokens): global sections on :root, the light theme on :root and
[data-cs-theme="light"], the dark theme on [data-cs-theme="dark"] and, under
prefers-color-scheme: dark, on :root[data-cs-theme="system"]; density, touch and reduced-motion
overrides. The mapping of names and contexts lives in check_design_tokens.py (css_variables /
emit_css) so the generator and the drift check can never disagree.

Output is deterministic (token order from the JSON, no timestamp), so --check is a plain comparison.
Never edit tokens.css by hand: change the JSON, bump meta.version, run this script.
Standard library only.
"""
import argparse
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOKENS = ROOT / 'docs' / 'ux' / 'design-tokens.json'
OUT = ROOT / 'static' / 'css' / 'tokens.css'
THEMES_CSS = ROOT / 'static' / 'css' / 'themes.css'
NAV_CSS = ROOT / 'static' / 'css' / 'navigation.css'


def _checker():
    spec = importlib.util.spec_from_file_location('check_design_tokens', HERE / 'check_design_tokens.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(tokens_path=TOKENS):
    """The complete tokens.css text. Raises ValueError when the token file fails its schema."""
    cdt = _checker()
    doc = cdt.load(tokens_path)
    errors = cdt.check_schema(doc)
    if errors:
        raise ValueError('design-tokens.json fails its schema:\n  ' + '\n  '.join(errors))
    header = (
        '/* static/css/tokens.css: the shared design tokens as CSS custom properties.\n'
        ' * Regenerate with: venv/bin/python scripts/ux/build_token_css.py\n'
        ' * core.tests.test_design_tokens fails when this file is out of date.\n'
        ' * The legacy colour themes set the semantic --cs-color-* tokens from their own\n'
        ' * palettes in static/css/themes.css ("Semantic design tokens" section). */\n'
    )
    return header + cdt.emit_css(doc)


# --------------------------------------------------------------------------- legacy themes -> tokens
# The twelve colour themes in themes.css keep their own palettes (the page looks exactly as before);
# what they gain is the semantic --cs-color-* tokens, set from their own palette so new markup that
# reads a token matches the theme it sits in. Each token takes the first legacy variable listed
# here that the theme defines; a token with no legacy source keeps the spec value of the theme's
# mode (light or dark) from tokens.css. Every contrast pair in the spec is then checked against the
# theme's resolved values; a token that falls short is nudged toward white or black just far
# enough to pass and written as a literal (with a comment naming what it was adjusted from).
REGION_START = '/* generated:theme-tokens:start'
REGION_END = '/* generated:theme-tokens:end */'

LEGACY_SOURCES = {
    'bg.page': ('background',),
    'bg.surface': ('surface',),
    'bg.raised': ('surface-raised', 'card-bg'),
    'bg.sunken': ('background-alt',),
    'bg.hover': ('surface-hover',),
    'bg.selected': ('primary-light',),
    'text.primary': ('text-primary',),
    'text.secondary': ('text-secondary',),
    'text.muted': ('text-muted',),
    'text.link': ('link-color', 'primary-color'),
    'text.link-hover': ('link-hover', 'primary-hover'),
    'border.subtle': ('border-color',),
    'border.default': ('border-color',),
    'border.strong': ('border-strong',),
    'focus.ring': ('focus-ring',),
    'action.primary.bg': ('primary-color',),
    'action.primary.bg-hover': ('primary-hover',),
    'status.success.text': ('success-ink',),
    'status.warning.text': ('warning-ink',),
    'status.danger.text': ('danger-ink',),
    'status.info.text': ('info-ink',),
    # The sidebar is the same in every theme (navigation.css :root --appnav-*).
    'nav.bg': ('appnav-bg',),
    'nav.bg-raised': ('appnav-bg-raised',),
    'nav.border': ('appnav-border',),
    'nav.text': ('appnav-text',),
    'nav.text-muted': ('appnav-muted',),
    'nav.text-strong': ('appnav-strong',),
    'nav.active-indicator': ('appnav-accent',),
    'nav.focus': ('appnav-focus',),
}
# Surfaces that are never adjusted: everything else is measured against them.
CORE_BGS = {'bg.page', 'bg.surface', 'bg.raised', 'bg.sunken', 'bg.hover', 'nav.bg', 'nav.bg-raised'}
_HEXVAR = re.compile(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})\b')


def legacy_palettes(themes_text):
    """{theme: {var: '#rrggbb'}} from the first [data-theme="x"] block of each theme (its palette)."""
    out = {}
    for name, body in re.findall(r'^\[data-theme="([\w-]+)"\]\s*\{(.*?)^\}', themes_text, re.S | re.M):
        if name not in out:
            out[name] = {k: v.lower() for k, v in _HEXVAR.findall(body)}
    return out


def nav_palette(nav_text):
    m = re.search(r':root\s*\{([^}]*--appnav-[^}]*)\}', nav_text)
    return {k: v.lower() for k, v in _HEXVAR.findall(m.group(1))} if m else {}


def theme_mode(palette, cdt):
    """'dark' when the page background is dark (matches accounts.context_processors.DARK_THEMES)."""
    return 'dark' if cdt.luminance(palette['background']) < 0.18 else 'light'


def _mix(hex_colour, target, t):
    a = [int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(target[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join('%02x' % round(x + (y - x) * t) for x, y in zip(a, b))


def _nudge(colour, others, cdt):
    """Smallest mix of colour toward white or black that meets every (other colour, min) given,
    or None. Deterministic: 1% steps, white tried before black on a tie."""
    best = None
    for target in ('#ffffff', '#000000'):
        for step in range(0, 101):
            c = _mix(colour, target, step / 100)
            if all(cdt.contrast(c, o) + 1e-9 >= m for o, m in others):
                if best is None or step < best[0]:
                    best = (step, c)
                break
    return None if best is None else best[1]


def resolve_theme(name, palette, nav, doc, cdt):
    """{token path: (value, source)} for one legacy theme; source is '--var', 'spec' or
    'adjusted from --var' / 'adjusted from spec'. Raises ValueError when a pair cannot pass."""
    mode = theme_mode(palette, cdt)
    spec = {'.'.join(p): cdt.resolve(doc, t) for p, t in cdt.walk(doc['theme'][mode]['color'])}
    values = {}
    for path, value in spec.items():
        values[path] = (value, 'spec')
        for var in LEGACY_SOURCES.get(path, ()):
            src = nav if var.startswith('appnav-') else palette
            if var in src:
                values[path] = (src[var], '--' + var)
                break
    pairs = [(p['fg'], p['bg'], float(p['min'])) for p in doc['contrast-pairs']['pairs'] if p['theme'] == mode]

    def opaque(path):
        return len(values[path][0]) == 7

    def failing():
        return [(fg, bg, m) for fg, bg, m in pairs if opaque(fg) and opaque(bg)
                and cdt.contrast(values[fg][0], values[bg][0]) + 1e-9 < m]

    def fix(token, core_only):
        # While main-surface pairs are being settled, a foreground is fitted to those alone (a
        # mid-tone selected background must not push muted text all the way to white).
        others = [(values[bg if fg == token else fg][0], m) for fg, bg, m in pairs
                  if token in (fg, bg) and opaque(fg) and opaque(bg)
                  and not (core_only and bg not in CORE_BGS)]
        new = _nudge(values[token][0], others, cdt)
        if new is None:
            return False
        if new != values[token][0]:
            value, source = values[token]
            values[token] = (new, source if source.startswith('adjusted') else 'adjusted from ' + source)
        return True

    for _ in range(500):
        todo = failing()
        if not todo:
            return values, mode
        # Pairs on the main surfaces first: a token is settled against the page and cards before
        # anything (a selected row, a hover) is fitted around it.
        fg, bg, _m = min(todo, key=lambda pair: (pair[1] not in CORE_BGS, pairs.index(pair)))
        # Adjust a spec-sourced side first, then a non-core background, then the foreground.
        order = [t for t in (fg, bg) if values[t][1] == 'spec']
        order += [t for t in (bg, fg) if t not in order and t not in CORE_BGS]
        if not any(fix(t, bg in CORE_BGS) for t in order):
            raise ValueError(f'theme {name}: {fg} on {bg} cannot reach {_m}:1')
    if failing():
        raise ValueError(f'theme {name}: contrast did not settle: {failing()}')
    return values, mode


def theme_token_css(doc, themes_text, nav_text, cdt):
    """The generated region of themes.css: one :root[data-theme="x"] block per legacy theme."""
    prefix = doc['meta']['cssPrefix'] + 'color-'
    nav = nav_palette(nav_text)
    lines = [REGION_START + ' (scripts/ux/build_token_css.py from the palettes above and '
             'design-tokens.json v%s; do not edit) */' % doc['meta']['version'],
             '/* Semantic design tokens for each colour theme. Nothing here changes how a theme looks:',
             '   it sets --cs-color-* (static/css/tokens.css) from the theme\'s own palette. Tokens not',
             '   listed keep the spec value of the theme\'s mode, from data-cs-theme on <html>. */']
    for name, palette in legacy_palettes(themes_text).items():
        values, mode = resolve_theme(name, palette, nav, doc, cdt)
        lines.append(f':root[data-theme="{name}"] {{ /* {mode} */')
        for path, (value, source) in values.items():
            css_name = prefix + path.replace('.', '-')
            if source == 'spec':
                continue
            if source.startswith('--'):
                lines.append(f'    {css_name}: var({source});')
            else:
                lines.append(f'    {css_name}: {value}; /* {source}, for contrast */')
        lines.append('}')
    lines.append(REGION_END)
    return '\n'.join(lines) + '\n'


def build_themes(themes_text, doc=None, tokens_path=TOKENS, nav_text=None):
    """themes.css with its generated region replaced (inserted before THEME APPLICATION if absent)."""
    cdt = _checker()
    doc = doc or cdt.load(tokens_path)
    nav_text = nav_text if nav_text is not None else NAV_CSS.read_text(encoding='utf-8')
    region = theme_token_css(doc, themes_text, nav_text, cdt)
    start = themes_text.find(REGION_START)
    if start >= 0:
        end = themes_text.index(REGION_END, start) + len(REGION_END) + 1
        return themes_text[:start] + region + themes_text[end:]
    marker = '/* ========================================\n   THEME APPLICATION'
    at = themes_text.index(marker)
    return themes_text[:at] + region + '\n' + themes_text[at:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tokens', default=str(TOKENS))
    ap.add_argument('--out', default=str(OUT))
    ap.add_argument('--check', action='store_true', help='exit 1 when the output file is out of date')
    ap.add_argument('--stdout', action='store_true', help='print tokens.css instead of writing it')
    ap.add_argument('--no-themes', action='store_true', help='leave the generated region of themes.css alone')
    args = ap.parse_args(argv)

    try:
        css = build(args.tokens)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    outputs = [(Path(args.out), css)]
    if not args.no_themes:
        themes_text = THEMES_CSS.read_text(encoding='utf-8')
        try:
            outputs.append((THEMES_CSS, build_themes(themes_text, tokens_path=args.tokens)))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
    if args.stdout:
        sys.stdout.write(css)
        return 0
    stale = []
    for out, text in outputs:
        current = out.read_text(encoding='utf-8') if out.exists() else None
        if current == text:
            print(f'{out}: up to date' if args.check else f'{out}: unchanged')
        elif args.check:
            stale.append(out)
        else:
            out.write_text(text, encoding='utf-8')
            print(f'wrote {out}')
    if stale:
        for out in stale:
            print(f'{out} is out of date with {args.tokens}; run scripts/ux/build_token_css.py', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
