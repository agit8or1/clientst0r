#!/usr/bin/env python3
"""Regenerate the dashboard tables in docs/ROADMAP.md from the phase records.

The canonical record for each phase is two lines in docs/ROADMAP.md:

    ## Phase N — Title **(size · priority · area)** [status]
    <!-- phase: ws=A stage=1 state=partial view=next order=2 deps="…" next="…" blocker="…" unblock="…" note="…" -->

* The header line is what /core/roadmap.json and the in-app roadmap page read. Its bracket marker stays one of
  [planned], [in progress], [shipped — vX.Y.Z], [complete] (or the legacy **— shipped** / **— complete**).
* The comment refines it: state=partial|blocked|deferred|verify, the workstream (ws), program stage, NOW/NEXT/LATER
  view, dependencies, next action and blocker. Priority comes from the header (P0–P4); without one, the stage
  table's priority is shown with an asterisk.

Everything between `<!-- generated:NAME -->` and `<!-- /generated:NAME -->`, and the `**Status:**` line under
each phase record, is written by this script. Edit the records, then run:

    python3 scripts/roadmap_dashboard.py          # rewrite docs/ROADMAP.md
    python3 scripts/roadmap_dashboard.py --check  # exit 1 if the file is out of date (used by the test suite)

Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROADMAP = ROOT / 'docs' / 'ROADMAP.md'
HISTORY_URL = 'https://github.com/agit8or1/clientst0r/blob/main/docs/ROADMAP_HISTORY.md'

# Same pattern as core.views.roadmap_status_json.
HEADER_RE = re.compile(
    r'^##\s+Phase\s+(?P<num>\d+(?:\.\d+)?)'
    r'\s*[—\-]\s*(?P<title>.+?)'
    r'(?:\s*\*\*\((?P<size>[^)]+)\)\*\*)?'
    r'(?:\s*\*\*[—\-]\s*(?P<inline_status>shipped|complete)\*\*)?'
    r'(?:\s*\[(?P<bracket_status>[^\]]+)\])?'
    r'\s*$',
    re.MULTILINE,
)
META_RE = re.compile(r'^<!-- phase:(?P<body>.*?)-->\s*$')
PAIR_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')

WORKSTREAMS = {
    'A': 'Core PSA & Ticketing',
    'B': 'Billing & Financial Management',
    'C': 'Asset Management & Documentation',
    'D': 'RMM & Platform Integrations',
    'E': 'Sales & CRM',
    'F': 'Security & Administration',
    'G': 'Customer Portal & Communications',
    'H': 'Reporting, Analytics & Optional AI',
    'I': 'Deployment, Updates & Reliability',
}
STAGE_PRIORITY = {1: 'P0', 2: 'P1', 3: 'P2', 4: 'P3', 5: 'P3', 6: 'P3'}
STAGES = [
    (1, 'Core completion: PSA/RMM workflow, quote conversion, billing correctness, security, ticket workflow, setup'),
    (2, 'Backup management: St0r/UrBackup, Comet, one overview, alerts, reports, billing'),
    (3, 'Device management: MDM, compliance, Linux/macOS visibility, one device record'),
    (4, 'Sales and documentation: CRM discovery, estimator, quotes, documentation, discovery staging'),
    (5, 'Reporting and customer portal'),
    (6, 'Advanced integrations and optional AI'),
    (7, 'Polish, regression coverage, documentation, completion checklist'),
]
ICON = {
    'complete': '✅ Complete', 'verify': '✅ Complete — verify', 'in_progress': '🔵 In progress',
    'partial': '🟡 Partial', 'planned': '⬜ Planned', 'blocked': '🔴 Blocked', 'deferred': '⏸️ Deferred',
}


def header_status(m: re.Match) -> str:
    bracket = (m.group('bracket_status') or '').strip().lower()
    inline = (m.group('inline_status') or '').strip().lower()
    if 'complete' in bracket or inline == 'complete' or 'shipped' in bracket or inline == 'shipped':
        return 'complete'
    if 'in progress' in bracket or 'in-progress' in bracket:
        return 'in_progress'
    return 'planned'


def parse(text: str) -> list[dict]:
    lines = text.split('\n')
    phases = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if not m:
            continue
        meta = {}
        if i + 1 < len(lines):
            mm = META_RE.match(lines[i + 1])
            if mm:
                for k, q, b in PAIR_RE.findall(mm.group('body')):
                    meta[k] = q if q else b
        size = (m.group('size') or '').strip()
        pr = re.search(r'\bP([0-4])\b', size)
        base = header_status(m)
        state = meta.get('state', '')
        if state in ('partial', 'blocked', 'deferred'):
            shown = state
        elif state == 'verify' and base == 'complete':
            shown = 'verify'
        else:
            shown = base
        stage = int(meta['stage']) if meta.get('stage', '').isdigit() else None
        if pr:
            prio = f'P{pr.group(1)}'
        elif stage in STAGE_PRIORITY and shown not in ('complete', 'verify'):
            prio = STAGE_PRIORITY[stage] + '\\*'
        else:
            prio = '—'
        version = re.search(r'v(\d+\.\d+\.\d+)', m.group('bracket_status') or '')
        phases.append({
            'num': m.group('num'), 'title': re.sub(r'\*\*', '', m.group('title')).strip(),
            'base': base, 'shown': shown, 'prio': prio, 'stage': stage, 'line': i,
            'version': version.group(1) if version else '', 'meta': meta,
            'has_meta': bool(meta),
        })
    return phases


def link(p: dict) -> str:
    return f'[{p["title"]}](#phase-{p["num"]})'


def cell(v: str) -> str:
    return (v or '—').replace('|', '/')


def is_open(p: dict) -> bool:
    return p['shown'] not in ('complete', 'verify')


def gen_counts(ph: list[dict], version: str) -> str:
    c = {k: sum(1 for p in ph if p['shown'] == k) for k in ICON}
    done = c['complete'] + c['verify']
    stages = sorted({p['stage'] for p in ph if p['stage'] and is_open(p) and p['meta'].get('view') == 'now'})
    active = f'Stage {stages[0]}' if stages else '—'
    rows = [
        '| | |', '|---|---|',
        '| Latest release | ![Latest release](https://img.shields.io/github/v/release/agit8or1/clientst0r?label=release) '
        '— see the [changelog](../CHANGELOG.md) |',
        '| Last roadmap audit | 2026-11-20 |',
        f'| Active stage | {active} — core completion (P0) |',
        f'| Phases | **{len(ph)}** in total |',
        f'| ✅ Complete | {done} (of which {c["verify"]} marked for verification) |',
        f'| 🔵 In progress | {c["in_progress"]} |',
        f'| 🟡 Partial | {c["partial"]} |',
        f'| ⬜ Planned | {c["planned"]} |',
        f'| 🔴 Blocked | {c["blocked"]} (plus blocked items inside other phases — see [Blockers](#blockers)) |',
        f'| ⏸️ Deferred | {c["deferred"]} |',
    ]
    return '\n'.join(rows)


def gen_view(ph: list[dict], view: str) -> str:
    sel = sorted((p for p in ph if p['meta'].get('view') == view and is_open(p)),
                 key=lambda p: (int(p['meta'].get('order', 99)), float(p['num'])))
    out = ['| # | Phase | Priority | Status | Next step | Depends on |', '|---|---|---|---|---|---|']
    for i, p in enumerate(sel, 1):
        out.append(f'| {i} | {p["num"]} — {link(p)} | {p["prio"]} | {ICON[p["shown"]]} | '
                   f'{cell(p["meta"].get("next"))} | {cell(p["meta"].get("deps"))} |')
    return '\n'.join(out)


def gen_later(ph: list[dict]) -> str:
    out = []
    for ws, name in WORKSTREAMS.items():
        sel = [p for p in ph if p['meta'].get('ws') == ws and is_open(p) and p['meta'].get('view') == 'later']
        if sel:
            out.append(f'- **{ws}. {name}:** ' + ', '.join(f'{p["num"]} {link(p)} ({p["prio"]})' for p in sel))
    return '\n'.join(out)


def gen_blockers(ph: list[dict]) -> str:
    out = ['| Phase | Blocker | Depends on | Decision / action needed | State |', '|---|---|---|---|---|']
    for p in ph:
        b = p['meta'].get('blocker')
        if b:
            out.append(f'| {p["num"]} — {link(p)} | {cell(b)} | {cell(p["meta"].get("deps"))} | '
                       f'{cell(p["meta"].get("unblock"))} | {ICON[p["shown"]]} |')
    return '\n'.join(out)


def gen_stages(ph: list[dict]) -> str:
    out = ['| Stage | Content | Priority | Phases |', '|---|---|---|---|']
    for n, text in STAGES:
        nums = [p['num'] for p in ph if p['stage'] == n]
        pr = STAGE_PRIORITY.get(n, '—')
        out.append(f'| {n} | {text} | {pr} | ' + (', '.join(f'[{x}](#phase-{x})' for x in nums) or 'remaining items') + ' |')
    out.append('| 8 | Rem0te functional expansion (separate backlog) | after Stage 7 | '
               '[Rem0te backlog](plans/platform-program/REM0TE_FEATURE_EXPANSION_ROADMAP.md) |')
    return '\n'.join(out)


def gen_matrix(ph: list[dict]) -> str:
    out = []
    for ws, name in WORKSTREAMS.items():
        sel = [p for p in ph if p['meta'].get('ws') == ws]
        open_ = [p for p in sel if is_open(p)]
        done = [p for p in sel if not is_open(p)]
        out.append(f'### {ws}. {name}\n')
        if open_:
            out.append('| ID | Feature / deliverable | Priority | Status | Dependencies | Next action |')
            out.append('|---|---|---|---|---|---|')
            for p in open_:
                out.append(f'| {p["num"]} | {link(p)} | {p["prio"]} | {ICON[p["shown"]]} | '
                           f'{cell(p["meta"].get("deps"))} | {cell(p["meta"].get("next"))} |')
            out.append('')
        if done:
            out.append(f'<details markdown="1">\n<summary>{len(done)} completed phases</summary>\n')
            out.append('| ID | Feature | Status | Released | Note |')
            out.append('|---|---|---|---|---|')
            for p in done:
                out.append(f'| {p["num"]} | {link(p)} | {ICON[p["shown"]]} | '
                           f'{("v" + p["version"]) if p["version"] else "—"} | {cell(p["meta"].get("note"))} |')
            out.append('\n</details>\n')
    return '\n'.join(out).rstrip()


def gen_unprioritized(ph: list[dict]) -> str:
    sel = [p for p in ph if is_open(p) and p['prio'] == '—']
    return '\n'.join(f'- {p["num"]} — {link(p)} ({ICON[p["shown"]]})' for p in sel) or '- none'


def gen_verify(ph: list[dict]) -> str:
    out = ['| Phase | What to verify |', '|---|---|']
    for p in ph:
        if p['meta'].get('state') == 'verify':
            out.append(f'| {p["num"]} — {link(p)} | {cell(p["meta"].get("note") or p["meta"].get("next"))} |')
    return '\n'.join(out)


def status_line(p: dict) -> str:
    bits = [f'**Status:** {ICON[p["shown"]]}', f'**Priority:** {p["prio"]}']
    ws = p['meta'].get('ws')
    if ws:
        bits.append(f'**Workstream:** {ws}. {WORKSTREAMS[ws]}')
    if p['meta'].get('deps'):
        bits.append(f'**Depends on:** {p["meta"]["deps"]}')
    line = ' · '.join(bits)
    if is_open(p) and p['meta'].get('next'):
        line += f'  \n**Next:** {p["meta"]["next"]}'
    if p['meta'].get('blocker'):
        line += f'  \n**Blocked:** {p["meta"]["blocker"]} — *unblocks when:* {p["meta"].get("unblock", "—")}'
    if p['meta'].get('note'):
        line += f'  \n**Note:** {p["meta"]["note"]}'
    return line


def render(text: str, version: str) -> str:
    ph = parse(text)
    blocks = {
        'counts': gen_counts(ph, version), 'now': gen_view(ph, 'now'), 'next': gen_view(ph, 'next'),
        'later': gen_later(ph), 'blockers': gen_blockers(ph), 'stages': gen_stages(ph),
        'matrix': gen_matrix(ph), 'verify': gen_verify(ph), 'unprioritized': gen_unprioritized(ph),
    }
    for name, body in blocks.items():
        pat = re.compile(r'(<!-- generated:%s -->)\n.*?(<!-- /generated:%s -->)' % (name, name), re.S)
        if not pat.search(text):
            raise SystemExit(f'docs/ROADMAP.md: markers for generated block "{name}" are missing')
        # blank lines keep Markdown parsers from treating the block as part of the HTML comment
        text = pat.sub(lambda m: m.group(1) + '\n\n' + body + '\n\n' + m.group(2), text)
    lines = text.split('\n')
    ph_lines = parse('\n'.join(lines))  # line numbers after the block rewrites above
    for p in reversed(ph_lines):  # bottom-up so earlier line numbers stay valid
        i = p['line'] + 2  # header, meta, status
        if p['has_meta'] and i < len(lines):
            if lines[i].startswith('**Status:**'):
                # a status line may span several lines joined by two-space breaks
                j = i
                while j + 1 < len(lines) and lines[j].endswith('  ') and lines[j + 1].startswith('**'):
                    j += 1
                lines[i:j + 1] = status_line(p).split('\n')
            else:
                lines[i:i] = status_line(p).split('\n') + ['']
    return '\n'.join(lines)


def current_version() -> str:
    m = re.search(r"VERSION\s*=\s*'([^']+)'", (ROOT / 'config' / 'version.py').read_text())
    return m.group(1) if m else '?'


def problems(text: str) -> list[str]:
    out = []
    for p in parse(text):
        if not p['has_meta']:
            out.append(f'Phase {p["num"]}: no <!-- phase: … --> record under the header')
        elif p['meta'].get('ws') not in WORKSTREAMS:
            out.append(f'Phase {p["num"]}: workstream must be one of {", ".join(WORKSTREAMS)}')
        if f'<a id="phase-{p["num"]}"></a>' not in text:
            out.append(f'Phase {p["num"]}: missing anchor <a id="phase-{p["num"]}"></a>')
    return out


def main(argv: list[str]) -> int:
    text = ROADMAP.read_text(encoding='utf-8')
    new = render(text, current_version())
    errs = problems(new)
    if '--check' in argv:
        if new != text:
            print('docs/ROADMAP.md dashboard is out of date: run python3 scripts/roadmap_dashboard.py')
            return 1
        for e in errs:
            print(e)
        return 1 if errs else 0
    ROADMAP.write_text(new, encoding='utf-8')
    for e in errs:
        print(e)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
