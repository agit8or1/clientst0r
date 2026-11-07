"""
SVG artwork generated from layout geometry.

The renderer is deterministic and has no inputs beyond the catalog: a model's
layout, its name and manufacturer. Output is cached in ``RenderedArtwork``
keyed by model, layout version, face, variant and ``RENDERER_VERSION`` — bump
that constant whenever the drawing code changes and old cache rows are simply
ignored.

Every component element is emitted as::

    <g class="hw-el hw-port" data-key="<component template key>" ...>
      <use href="#c-rj45" x y width height/>      artwork
      <text …>12</text>                          printed number
      <rect class="hw-hit" x y width height/>   hit target, same rectangle
    </g>

so the clickable area can never drift from the drawing. Client data (VLANs,
cable state) is never baked into cached artwork; the page applies it as an
overlay keyed by ``data-key``.
"""
from __future__ import annotations

import html
import re

from . import connectors as C

RENDERER_VERSION = 7

# Chassis finishes. Illustrative colour only — not a claim about the exact
# paint of a particular model.
FINISHES = {
    'silver':   {'top': '#e9ecef', 'mid': '#cfd4d9', 'bot': '#b5bcc3', 'ear': '#a9b0b7', 'text': '#1e2328', 'sub': '#4a525a', 'edge': '#8c949c'},
    'graphite': {'top': '#4a5058', 'mid': '#353a40', 'bot': '#25292d', 'ear': '#2b2f34', 'text': '#f1f3f5', 'sub': '#b9c0c7', 'edge': '#16191c'},
    'black':    {'top': '#34373b', 'mid': '#222427', 'bot': '#151719', 'ear': '#1b1d20', 'text': '#f1f3f5', 'sub': '#a7adb3', 'edge': '#0a0b0c'},
    'white':    {'top': '#ffffff', 'mid': '#f1f3f5', 'bot': '#dfe3e7', 'ear': '#c8ced4', 'text': '#24292e', 'sub': '#59616a', 'edge': '#aab2ba'},
    'blue':     {'top': '#3b5b7d', 'mid': '#2c4864', 'bot': '#1f354b', 'ear': '#233a52', 'text': '#f1f6fb', 'sub': '#b8c8d8', 'edge': '#13222f'},
    'beige':    {'top': '#efeadf', 'mid': '#ddd6c6', 'bot': '#cac1ad', 'ear': '#bdb39d', 'text': '#2b2a26', 'sub': '#5c584e', 'edge': '#9e967f'},
}
_MFR_FINISH = {
    'dell': 'silver', 'force10': 'graphite', 'cisco': 'graphite', 'meraki': 'white', 'juniper': 'graphite',
    'ubiquiti': 'white', 'mikrotik': 'white', 'fortinet': 'black', 'sonicwall': 'black', 'sophos': 'graphite',
    'netgate': 'black', 'watchguard': 'black', 'ruckus': 'white', 'tp-link': 'graphite', 'hpe': 'graphite',
    'hp': 'graphite', 'aruba': 'graphite', 'extreme networks': 'graphite', 'supermicro': 'black', 'lenovo': 'black',
    'synology': 'black', 'qnap': 'black', 'apc': 'black', 'eaton': 'black', 'generic': 'graphite',
}


def finish_for(hm):
    name = hm.manufacturer.name.lower() if hm else ''
    if hm is not None and hm.category in ('access_point',):
        return FINISHES['white']
    if hm is not None and hm.category in ('wall_jack', 'outlet', 'workstation'):
        return FINISHES['white'] if hm.category != 'workstation' else FINISHES['graphite']
    return FINISHES[_MFR_FINISH.get(name, 'graphite')]


def esc(s):
    return html.escape(str(s), quote=True)


def _f(v):
    return f'{float(v):.2f}'.rstrip('0').rstrip('.')


# --------------------------------------------------------------------------- connector drawings
# Each symbol is drawn in a 10×-scaled box of its nominal size (connectors.CONNECTORS)
# and placed with <use width/height>, so it stays crisp at any zoom.

def _sym(cid, w, h, body):
    return (f'<symbol id="c-{cid}" viewBox="0 0 {_f(w * 10)} {_f(h * 10)}" preserveAspectRatio="none">'
            f'{body}</symbol>')


def connector_defs():
    S = []
    # RJ45 jack with shield, opening, latch notch, contacts and unlit LEDs
    S.append(_sym('rj45', 11.8, 10.4,
        '<rect x="0" y="0" width="118" height="104" rx="5" fill="url(#gShield)" stroke="#5b6168" stroke-width="2"/>'
        '<rect x="3" y="3" width="13" height="8" rx="1.5" fill="#29332b"/>'
        '<rect x="102" y="3" width="13" height="8" rx="1.5" fill="#3a3529"/>'
        '<path d="M12 16 H106 V80 H76 V94 H42 V80 H12 Z" fill="#101316" stroke="#000" stroke-width="1.5"/>'
        '<path d="M14 18 H104 V24 H14 Z" fill="#1d2226"/>'
        + ''.join(f'<rect x="{25 + i * 9.5:.1f}" y="19" width="3.2" height="17" fill="#c9a227"/>' for i in range(8)) +
        '<path d="M12 80 H106" stroke="#2b3136" stroke-width="2"/>'))
    S.append(_sym('rj11', 9.6, 8.4,
        '<rect x="0" y="0" width="96" height="84" rx="5" fill="url(#gShield)" stroke="#5b6168" stroke-width="2"/>'
        '<path d="M14 12 H82 V64 H60 V74 H36 V64 H14 Z" fill="#101316"/>'
        + ''.join(f'<rect x="{30 + i * 9:.1f}" y="15" width="3" height="13" fill="#c9a227"/>' for i in range(4))))
    def cage(cid, w, h):
        W, H = w * 10, h * 10
        return _sym(cid, w, h,
            f'<rect x="0" y="0" width="{W}" height="{H}" rx="3" fill="url(#gCage)" stroke="#6c737a" stroke-width="2"/>'
            f'<rect x="{W * 0.08:.1f}" y="{H * 0.2:.1f}" width="{W * 0.84:.1f}" height="{H * 0.6:.1f}" rx="2" fill="#0d0f11"/>'
            f'<rect x="{W * 0.1:.1f}" y="{H * 0.22:.1f}" width="{W * 0.8:.1f}" height="{H * 0.1:.1f}" fill="#22272b"/>'
            f'<path d="M{W * 0.2:.1f} {H * 0.08:.1f} h{W * 0.18:.1f} M{W * 0.62:.1f} {H * 0.08:.1f} h{W * 0.18:.1f}" '
            f'stroke="#8d949b" stroke-width="3" stroke-linecap="round"/>'
            f'<path d="M{W * 0.2:.1f} {H * 0.92:.1f} h{W * 0.6:.1f}" stroke="#8d949b" stroke-width="2"/>')
    S.append(cage('sfp', 14.0, 9.0))
    S.append(cage('qsfp', 19.0, 9.2))
    S.append(cage('osfp', 23.0, 10.0))
    S.append(cage('cfp', 30.0, 14.0))
    S.append(cage('xfp', 19.0, 10.0))
    S.append(cage('gbic', 15.0, 11.0))
    S.append(_sym('lc', 12.8, 7.0,
        '<rect x="0" y="0" width="128" height="70" rx="6" fill="#d8d2c2" stroke="#8f8774" stroke-width="2"/>'
        '<rect x="10" y="10" width="48" height="50" rx="4" fill="#1a1c1e"/>'
        '<rect x="70" y="10" width="48" height="50" rx="4" fill="#1a1c1e"/>'
        '<circle cx="34" cy="35" r="9" fill="#f4f1e8" stroke="#bbb" stroke-width="1.5"/>'
        '<circle cx="94" cy="35" r="9" fill="#f4f1e8" stroke="#bbb" stroke-width="1.5"/>'))
    S.append(_sym('sc', 9.4, 9.4,
        '<rect x="0" y="0" width="94" height="94" rx="6" fill="#3d6fb6" stroke="#244a80" stroke-width="2"/>'
        '<rect x="22" y="14" width="50" height="66" rx="4" fill="#15181b"/>'
        '<circle cx="47" cy="47" r="10" fill="#f4f1e8"/>'))
    S.append(_sym('st', 9.0, 9.0,
        '<circle cx="45" cy="45" r="43" fill="url(#gCage)" stroke="#666" stroke-width="2"/>'
        '<circle cx="45" cy="45" r="26" fill="#1b1d20"/><circle cx="45" cy="45" r="9" fill="#f4f1e8"/>'
        '<rect x="80" y="40" width="10" height="10" fill="#888"/>'))
    S.append(_sym('fc', 9.0, 9.0,
        '<circle cx="45" cy="45" r="43" fill="url(#gCage)" stroke="#666" stroke-width="2"/>'
        '<circle cx="45" cy="45" r="28" fill="#2a2d30"/><circle cx="45" cy="45" r="9" fill="#f4f1e8"/>'))
    S.append(_sym('mpo', 13.0, 6.5,
        '<rect x="0" y="0" width="130" height="65" rx="5" fill="#8a8f95" stroke="#555" stroke-width="2"/>'
        '<rect x="15" y="16" width="100" height="33" rx="3" fill="#131517"/>'
        + ''.join(f'<rect x="{24 + i * 7.3:.1f}" y="29" width="3" height="7" fill="#e9e5d9"/>' for i in range(12))))
    S.append(_sym('mini_fiber', 7.5, 6.5,
        '<rect x="0" y="0" width="75" height="65" rx="5" fill="#d8d2c2" stroke="#8f8774" stroke-width="2"/>'
        '<rect x="12" y="12" width="51" height="41" rx="3" fill="#1a1c1e"/><circle cx="37" cy="32" r="7" fill="#f4f1e8"/>'))
    S.append(_sym('coax', 9.0, 9.0,
        '<polygon points="45,2 83,24 83,66 45,88 7,66 7,24" fill="url(#gCage)" stroke="#555" stroke-width="2"/>'
        '<circle cx="45" cy="45" r="22" fill="#d9b34a" stroke="#8a6d1c" stroke-width="2"/>'
        '<circle cx="45" cy="45" r="12" fill="#f2efe6"/><circle cx="45" cy="45" r="3.5" fill="#b38b1d"/>'))
    def dshell(cid, w, h, top, bot):
        W, H = w * 10, h * 10
        sx = W * 0.16
        pins = ''.join(f'<circle cx="{sx + 18 + i * ((W - 2 * sx - 36) / max(1, top - 1)):.1f}" cy="{H * 0.4:.1f}" r="4.2" fill="#d5b44b"/>' for i in range(top))
        pins += ''.join(f'<circle cx="{sx + 30 + i * ((W - 2 * sx - 60) / max(1, bot - 1)):.1f}" cy="{H * 0.64:.1f}" r="4.2" fill="#d5b44b"/>' for i in range(bot))
        return _sym(cid, w, h,
            f'<rect x="0" y="{H * 0.08:.1f}" width="{W}" height="{H * 0.84:.1f}" rx="6" fill="url(#gCage)" stroke="#666" stroke-width="2"/>'
            f'<circle cx="{W * 0.065:.1f}" cy="{H / 2:.1f}" r="{H * 0.18:.1f}" fill="#9aa1a8" stroke="#555"/>'
            f'<circle cx="{W * 0.935:.1f}" cy="{H / 2:.1f}" r="{H * 0.18:.1f}" fill="#9aa1a8" stroke="#555"/>'
            f'<path d="M{sx:.1f} {H * 0.2:.1f} H{W - sx:.1f} L{W - sx - 14:.1f} {H * 0.82:.1f} H{sx + 14:.1f} Z" fill="#2a2d31" stroke="#111" stroke-width="2"/>'
            + pins)
    S.append(dshell('de9', 30.8, 12.6, 5, 4))
    S.append(dshell('db25', 53.0, 12.6, 13, 12))
    S.append(_sym('mini_din', 10.0, 10.0,
        '<circle cx="50" cy="50" r="48" fill="url(#gCage)" stroke="#555" stroke-width="2"/>'
        '<circle cx="50" cy="52" r="33" fill="#181a1c"/>'
        + ''.join(f'<circle cx="{50 + 20 * __import__("math").cos(a):.1f}" cy="{52 + 20 * __import__("math").sin(a):.1f}" r="3.5" fill="#d5b44b"/>'
                  for a in (3.5, 4.0, 4.6, 5.2, 5.9, 0.6, 1.6, 2.6))))
    S.append(_sym('usb_a', 13.2, 6.0,
        '<rect x="0" y="0" width="132" height="60" rx="3" fill="url(#gShield)" stroke="#5b6168" stroke-width="2"/>'
        '<rect x="10" y="10" width="112" height="40" fill="#0f1113"/>'
        '<rect x="16" y="14" width="100" height="14" fill="#1f5fbf"/>'
        + ''.join(f'<rect x="{30 + i * 20}" y="28" width="10" height="5" fill="#c9a227"/>' for i in range(4))))
    S.append(_sym('usb_b', 9.0, 8.5,
        '<rect x="0" y="0" width="90" height="85" rx="3" fill="url(#gShield)" stroke="#5b6168" stroke-width="2"/>'
        '<path d="M16 26 L28 12 H62 L74 26 V74 H16 Z" fill="#0f1113"/><rect x="30" y="30" width="30" height="30" fill="#1f5fbf"/>'))
    S.append(_sym('usb_c', 9.2, 3.6,
        '<rect x="0" y="0" width="92" height="36" rx="18" fill="url(#gShield)" stroke="#5b6168" stroke-width="2"/>'
        '<rect x="10" y="9" width="72" height="18" rx="9" fill="#0f1113"/><rect x="24" y="15" width="44" height="6" rx="2" fill="#2b2f33"/>'))
    S.append(_sym('usb_micro', 7.8, 3.4,
        '<path d="M2 2 H76 V22 L66 32 H12 L2 22 Z" fill="url(#gShield)" stroke="#5b6168" stroke-width="2"/>'
        '<path d="M10 9 H68 V20 L61 26 H17 L10 20 Z" fill="#0f1113"/>'))
    S.append(_sym('iec_c14', 27.0, 20.0,
        '<rect x="0" y="0" width="270" height="200" rx="10" fill="#18191b" stroke="#000" stroke-width="3"/>'
        '<path d="M40 30 H230 V170 H90 L40 120 Z" transform="scale(1,1)" fill="#0b0b0c" stroke="#333" stroke-width="3"/>'
        '<path d="M60 40 H210 V160 H100 L60 120 Z" fill="#202224"/>'
        '<rect x="88" y="80" width="12" height="40" rx="2" fill="#c7cbd0"/><rect x="170" y="80" width="12" height="40" rx="2" fill="#c7cbd0"/>'
        '<rect x="129" y="50" width="12" height="40" rx="2" fill="#c7cbd0"/>'))
    S.append(_sym('iec_c20', 30.0, 23.0,
        '<rect x="0" y="0" width="300" height="230" rx="10" fill="#18191b" stroke="#000" stroke-width="3"/>'
        '<rect x="40" y="35" width="220" height="160" rx="8" fill="#0b0b0c" stroke="#333" stroke-width="3"/>'
        '<rect x="80" y="110" width="40" height="12" fill="#c7cbd0"/><rect x="180" y="110" width="40" height="12" fill="#c7cbd0"/>'
        '<rect x="144" y="60" width="12" height="40" fill="#c7cbd0"/>'))
    S.append(_sym('iec_c13', 22.0, 16.0,
        '<path d="M8 8 H212 V152 H60 L8 100 Z" fill="#141516" stroke="#000" stroke-width="3"/>'
        '<rect x="62" y="64" width="10" height="34" fill="#000"/><rect x="146" y="64" width="10" height="34" fill="#000"/>'
        '<rect x="104" y="32" width="10" height="34" fill="#000"/>'))
    S.append(_sym('iec_c19', 26.0, 19.0,
        '<rect x="8" y="8" width="244" height="174" rx="8" fill="#141516" stroke="#000" stroke-width="3"/>'
        '<rect x="60" y="100" width="40" height="10" fill="#000"/><rect x="160" y="100" width="40" height="10" fill="#000"/>'
        '<rect x="125" y="50" width="10" height="36" fill="#000"/>'))
    S.append(_sym('iec_small', 18.0, 11.0,
        '<rect x="4" y="4" width="172" height="102" rx="40" fill="#141516" stroke="#000" stroke-width="3"/>'
        '<circle cx="60" cy="55" r="10" fill="#000"/><circle cx="120" cy="55" r="10" fill="#000"/>'))
    S.append(_sym('nema', 30.0, 34.0,
        '<rect x="0" y="0" width="300" height="340" rx="40" fill="#f2f0ea" stroke="#9b968a" stroke-width="3"/>'
        '<rect x="85" y="80" width="18" height="70" rx="3" fill="#2a2a2a"/><rect x="197" y="80" width="18" height="80" rx="3" fill="#2a2a2a"/>'
        '<path d="M130 220 a20 20 0 0 1 40 0 v30 h-40 Z" fill="#2a2a2a"/>'))
    S.append(_sym('iec_60309', 40.0, 40.0,
        '<circle cx="200" cy="200" r="196" fill="#2a64b8" stroke="#163c73" stroke-width="4"/>'
        '<circle cx="200" cy="200" r="130" fill="#1e2124"/>'
        '<circle cx="200" cy="110" r="22" fill="#000"/><circle cx="130" cy="240" r="16" fill="#000"/><circle cx="270" cy="240" r="16" fill="#000"/>'))
    S.append(_sym('dc', 16.0, 10.0,
        '<rect x="0" y="0" width="160" height="100" rx="8" fill="#26292c" stroke="#000" stroke-width="2"/>'
        '<circle cx="80" cy="50" r="32" fill="#0d0e0f" stroke="#777" stroke-width="3"/><circle cx="80" cy="50" r="9" fill="#c7cbd0"/>'))
    S.append(_sym('power_other', 18.0, 14.0,
        '<rect x="0" y="0" width="180" height="140" rx="10" fill="#26292c" stroke="#000" stroke-width="2"/>'
        '<rect x="30" y="30" width="120" height="80" rx="8" fill="#0d0e0f"/>'
        '<path d="M90 45 v28 M72 58 a26 26 0 1 0 36 0" stroke="#9aa1a8" stroke-width="7" fill="none" stroke-linecap="round"/>'))
    S.append(_sym('punch', 12.0, 6.0,
        '<rect x="0" y="0" width="120" height="60" rx="3" fill="#e9e6df" stroke="#999" stroke-width="2"/>'
        + ''.join(f'<rect x="{10 + i * 13}" y="12" width="6" height="36" fill="#6b6b6b"/>' for i in range(8))))
    S.append(_sym('keystone', 14.6, 16.0,
        '<rect x="0" y="0" width="146" height="160" rx="6" fill="#f3f1ec" stroke="#9b968a" stroke-width="2"/>'
        '<path d="M22 34 H124 V110 H90 V126 H56 V110 H22 Z" fill="#101316"/>'
        + ''.join(f'<rect x="{36 + i * 10.5:.1f}" y="38" width="3.4" height="18" fill="#c9a227"/>' for i in range(8))))
    S.append(_sym('stack', 16.0, 9.0,
        '<rect x="0" y="0" width="160" height="90" rx="4" fill="url(#gCage)" stroke="#555" stroke-width="2"/>'
        '<rect x="14" y="20" width="132" height="50" rx="3" fill="#121416"/>'
        + ''.join(f'<rect x="{24 + i * 14}" y="30" width="6" height="30" fill="#c9a227"/>' for i in range(8))))
    S.append(_sym('backplane', 10.0, 6.0,
        '<rect x="0" y="0" width="100" height="60" rx="4" fill="#555" stroke="#333" stroke-width="2"/>'))
    S.append(_sym('generic', 12.0, 10.0,
        '<rect x="0" y="0" width="120" height="100" rx="8" fill="url(#gCage)" stroke="#5b6168" stroke-width="2"/>'
        '<rect x="14" y="14" width="92" height="72" rx="6" fill="#16191c"/>'))
    return ''.join(S)


def finish_defs(f, uid, filters=True):
    """Gradients that depend on the chassis finish, namespaced by `uid`."""
    d = [
        f'<linearGradient id="gBody{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{f["top"]}"/><stop offset="0.5" stop-color="{f["mid"]}"/>'
        f'<stop offset="1" stop-color="{f["bot"]}"/></linearGradient>',
        f'<linearGradient id="gEar{uid}" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{f["ear"]}"/><stop offset="0.5" stop-color="{f["mid"]}"/>'
        f'<stop offset="1" stop-color="{f["ear"]}"/></linearGradient>',
        f'<pattern id="pBrush{uid}" width="6" height="0.7" patternUnits="userSpaceOnUse">'
        '<rect width="6" height="0.35" fill="#ffffff" opacity="0.05"/></pattern>',
    ]
    if filters:
        d.append(f'<filter id="fShadow{uid}" x="-5%" y="-10%" width="110%" height="130%">'
                 '<feDropShadow dx="0" dy="0.8" stdDeviation="0.9" flood-color="#000" flood-opacity="0.35"/></filter>')
    return ''.join(d)


def shared_defs():
    """Finish-independent definitions: connector symbols, cage/bay gradients, vents."""
    return ''.join([
        '<linearGradient id="gShield" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e3e6e9"/>'
        '<stop offset="0.55" stop-color="#b8bec4"/><stop offset="1" stop-color="#959ca3"/></linearGradient>',
        '<linearGradient id="gCage" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#dadee2"/>'
        '<stop offset="1" stop-color="#9aa1a8"/></linearGradient>',
        '<linearGradient id="gBay" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#15171a"/>'
        '<stop offset="1" stop-color="#2a2e33"/></linearGradient>',
        '<radialGradient id="gDisc" cx="0.45" cy="0.4" r="0.65"><stop offset="0" stop-color="#ffffff"/>'
        '<stop offset="0.8" stop-color="#eef0f2"/><stop offset="1" stop-color="#d3d8dd"/></radialGradient>',
        '<pattern id="pVent" width="3.2" height="3.2" patternUnits="userSpaceOnUse">'
        '<rect x="0.5" y="0.5" width="2.2" height="2.2" rx="0.6" fill="#000" opacity="0.55"/></pattern>',
        connector_defs(),
    ])


def common_defs(finish, filters=True, uid='a'):
    return f'<defs>{finish_defs(finish, uid, filters)}{shared_defs()}</defs>'


# --------------------------------------------------------------------------- chassis

def _ears(W, H, f, uid):
    out = []
    for x in (0, W - 21.3):
        out.append(f'<rect x="{_f(x)}" y="0" width="21.3" height="{_f(H)}" fill="url(#gEar{uid})"/>')
        units = max(1, round(H / 44.45))
        for u in range(units):
            for hy in (6.35, 38.1):
                cy = u * 44.45 + hy
                if cy > H - 2:
                    continue
                cx = x + 10.65
                out.append(f'<rect x="{_f(cx - 3.6)}" y="{_f(cy - 2.1)}" width="7.2" height="4.2" rx="2.1" '
                           f'fill="#1b1e21" stroke="{f["edge"]}" stroke-width="0.3"/>')
                out.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="1.5" fill="#8f979e" stroke="#555" stroke-width="0.2"/>')
    out.append(f'<path d="M21.3 0.4 V{_f(H - 0.4)} M{_f(W - 21.3)} 0.4 V{_f(H - 0.4)}" stroke="#000" stroke-opacity="0.25" stroke-width="0.4"/>')
    return ''.join(out)


def _decor(d, face, hm, f, W, H, uid):
    t = d.get('type')
    if t == 'ears':
        return _ears(W, H, f, uid)
    if t == 'brand':
        anchor = d.get('anchor', 'start')
        name = d.get('text') or (hm.manufacturer.name if hm else '')
        return (f'<text x="{_f(d["x"])}" y="{_f(d["y"])}" font-family="DejaVu Sans, Arial, sans-serif" '
                f'font-weight="700" font-size="{_f(d.get("size", 5))}" fill="{f["text"]}" text-anchor="{anchor}" '
                f'letter-spacing="0.2">{esc(name)}</text>')
    if t == 'model':
        anchor = d.get('anchor', 'start')
        name = d.get('text') or (hm.model if hm else '')
        return (f'<text x="{_f(d["x"])}" y="{_f(d["y"])}" font-family="DejaVu Sans, Arial, sans-serif" '
                f'font-size="{_f(d.get("size", 3))}" fill="{f["sub"]}" text-anchor="{anchor}">{esc(name)}</text>')
    if t == 'text':
        return (f'<text x="{_f(d["x"])}" y="{_f(d["y"])}" font-family="DejaVu Sans, Arial, sans-serif" '
                f'font-size="{_f(d.get("size", 2.4))}" fill="{d.get("color") or f["sub"]}" '
                f'text-anchor="{d.get("anchor", "start")}" font-weight="{d.get("weight", "400")}">{esc(d.get("text", ""))}</text>')
    if t == 'vent':
        return (f'<rect x="{_f(d["x"])}" y="{_f(d["y"])}" width="{_f(d["w"])}" height="{_f(d["h"])}" rx="1" '
                f'fill="url(#pVent)" stroke="#000" stroke-opacity="0.2" stroke-width="0.3"/>')
    if t == 'led':
        # LEDs are drawn unlit: artwork must never suggest an observed state.
        return (f'<circle cx="{_f(d["x"])}" cy="{_f(d["y"])}" r="{_f(d.get("r", 1.1))}" fill="#3b4147" '
                f'stroke="#1c1f22" stroke-width="0.25"/><circle cx="{_f(d["x"] - 0.3)}" cy="{_f(d["y"] - 0.35)}" '
                f'r="{_f(d.get("r", 1.1) * 0.35)}" fill="#fff" opacity="0.35"/>'
                + (f'<text x="{_f(d["x"])}" y="{_f(d["y"] + d.get("r", 1.1) + 2.2)}" font-family="DejaVu Sans, Arial, sans-serif" '
                   f'font-size="1.5" fill="{f["sub"]}" text-anchor="middle">{esc(d["text"])}</text>' if d.get('text') else ''))
    if t == 'button':
        return (f'<circle cx="{_f(d["x"])}" cy="{_f(d["y"])}" r="{_f(d.get("r", 1.6))}" fill="#2b2f33" stroke="{f["edge"]}" stroke-width="0.4"/>'
                + (f'<text x="{_f(d["x"])}" y="{_f(d["y"] + d.get("r", 1.6) + 2.2)}" font-family="DejaVu Sans, Arial, sans-serif" '
                   f'font-size="1.5" fill="{f["sub"]}" text-anchor="middle">{esc(d["text"])}</text>' if d.get('text') else ''))
    if t == 'box':
        return (f'<rect x="{_f(d["x"])}" y="{_f(d["y"])}" width="{_f(d["w"])}" height="{_f(d["h"])}" rx="{_f(d.get("rx", 0.8))}" '
                f'fill="none" stroke="{d.get("color") or f["sub"]}" stroke-width="{_f(d.get("sw", 0.3))}"/>')
    if t == 'led_ring':
        return (f'<circle cx="{_f(d["x"])}" cy="{_f(d["y"])}" r="{_f(d["r"])}" fill="none" stroke="#cfd6dc" '
                f'stroke-width="2.2"/><circle cx="{_f(d["x"])}" cy="{_f(d["y"])}" r="{_f(d["r"] - 1.6)}" fill="none" '
                f'stroke="#ffffff" stroke-opacity="0.8" stroke-width="0.6"/>')
    return ''


def _label(e, f):
    if not e.get('label') or e.get('label_pos') == 'none':
        return ''
    size = min(2.6, max(1.4, e['h'] * 0.27))
    cx = e['x'] + e['w'] / 2
    if e.get('label_pos') == 'below':
        y = e['y'] + e['h'] + size + 0.3
    elif e.get('label_pos') == 'inside':
        y = e['y'] + e['h'] / 2 + size / 3
    else:
        y = e['y'] - 0.7
    return (f'<text class="hw-num" x="{_f(cx)}" y="{_f(y)}" font-family="DejaVu Sans, Arial, sans-serif" '
            f'font-size="{_f(size)}" fill="{f["text"]}" text-anchor="middle">{esc(e["label"])}</text>')


def _element(e, f, labels=True):
    k = esc(e.get('key', ''))
    x, y, w, h = e['x'], e['y'], e['w'], e['h']
    rot = e.get('rot', 0) or 0
    title = f'<title>{esc(e.get("name", ""))}</title>'
    if e.get('kind') == 'bay':
        lab = esc(e.get('label') or e.get('name') or '')
        return (f'<g class="hw-el hw-bay" data-key="{k}" data-name="{esc(e.get("name", ""))}">{title}'
                f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" rx="0.8" fill="url(#gBay)" '
                f'stroke="{f["edge"]}" stroke-width="0.5"/>'
                f'<rect x="{_f(x + 0.6)}" y="{_f(y + 0.6)}" width="{_f(w - 1.2)}" height="{_f(h - 1.2)}" rx="0.6" '
                f'fill="none" stroke="#000" stroke-opacity="0.5" stroke-width="0.4"/>'
                f'<g class="hw-bay-fill"></g>'
                f'<text class="hw-bay-label" x="{_f(x + w / 2)}" y="{_f(y + h / 2 + 1)}" font-family="DejaVu Sans, Arial, sans-serif" '
                f'font-size="{_f(min(3.0, max(1.6, w / 12)))}" fill="#9aa3ab" text-anchor="middle">{lab}</text>'
                f'<rect class="hw-hit" x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="#000" fill-opacity="0"/></g>')
    conn = e.get('connector') or 'generic'
    if conn not in C.CONNECTORS:
        conn = 'generic'
    if rot:
        cx, cy = x + w / 2, y + h / 2
        # Rotated connectors are drawn in their own box, then rotated about the element centre.
        if rot in (90, 270):
            dw, dh = h, w
        else:
            dw, dh = w, h
        art = (f'<use href="#c-{conn}" x="{_f(cx - dw / 2)}" y="{_f(cy - dh / 2)}" width="{_f(dw)}" height="{_f(dh)}" '
               f'transform="rotate({rot} {_f(cx)} {_f(cy)})"/>')
    else:
        art = f'<use href="#c-{conn}" x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}"/>'
    return (f'<g class="hw-el hw-port" data-key="{k}" data-name="{esc(e.get("name", ""))}" data-connector="{conn}">'
            f'{title}{art}{_label(e, f) if labels else ""}'
            f'<rect class="hw-hit" x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="#000" fill-opacity="0"/></g>')


def render_face_body(hm, face_name, face, uid='a', labels=True, filters=True, finish=None):
    """The <g> for one face, without the outer <svg>. Used for embedding."""
    f = finish or finish_for(hm)
    W, H = float(face['width']), float(face['height'])
    parts = [f'<g class="hw-face" data-face="{esc(face_name)}">']
    shadow = f' filter="url(#fShadow{uid})"' if filters else ''
    if face.get('shape') == 'disc':
        r = min(W, H) / 2 - 1
        parts.append(f'<circle cx="{_f(W / 2)}" cy="{_f(H / 2)}" r="{_f(r)}" fill="url(#gDisc)" stroke="#b9c1c8" '
                     f'stroke-width="0.6"{shadow}/>')
    else:
        # Rear faces of rack gear have no ears: the body is inset, but the face
        # keeps the full 19" width so front and rear line up in elevations.
        ix = float(face.get('inset_x') or 0)
        bw = W - 2 * ix
        parts.append(f'<rect x="{_f(ix + 0.3)}" y="0.3" width="{_f(bw - 0.6)}" height="{_f(H - 0.6)}" rx="1.4" '
                     f'fill="url(#gBody{uid})" stroke="{f["edge"]}" stroke-width="0.5"{shadow}/>')
        parts.append(f'<rect x="{_f(ix + 0.3)}" y="0.3" width="{_f(bw - 0.6)}" height="{_f(H - 0.6)}" rx="1.4" '
                     f'fill="url(#pBrush{uid})"/>')
        parts.append(f'<path d="M{_f(ix + 1.6)} 1.0 H{_f(W - ix - 1.6)}" stroke="#fff" stroke-opacity="0.45" stroke-width="0.5"/>')
        parts.append(f'<path d="M{_f(ix + 1.6)} {_f(H - 0.9)} H{_f(W - ix - 1.6)}" stroke="#000" stroke-opacity="0.35" stroke-width="0.5"/>')
    for d in face.get('decor', []):
        parts.append(_decor(d, face_name, hm, f, W, H, uid))
    for e in face.get('elements', []):
        parts.append(_element(e, f, labels=labels))
    parts.append('</g>')
    return ''.join(parts)


def render_face(hm, face_name, face, px_per_mm=3.0, labels=True, filters=True, css_class='hw-art', uid='a'):
    W, H = float(face['width']), float(face['height'])
    f = finish_for(hm)
    title = esc(f'{hm.manufacturer.name} {hm.model} — {face_name}') if hm else esc(face_name)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="{css_class}" viewBox="0 0 {_f(W)} {_f(H)}" '
            f'width="{_f(W * px_per_mm)}" height="{_f(H * px_per_mm)}" data-face="{esc(face_name)}" '
            f'data-width-mm="{_f(W)}" data-height-mm="{_f(H)}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{common_defs(f, filters=filters, uid=uid)}'
            f'{render_face_body(hm, face_name, face, uid=uid, labels=labels, filters=filters, finish=f)}</svg>')


def cached_face_svg(hm, layout, face_name, variant='full'):
    """Artwork for a catalog face, from the cache or freshly rendered."""
    from .models import RenderedArtwork
    face = layout.faces.get(face_name)
    if not face:
        return ''
    row = RenderedArtwork.objects.filter(hardware_model=hm, layout_version=layout.version, face=face_name,
                                         variant=variant, renderer_version=RENDERER_VERSION).first()
    if row:
        return row.svg
    if variant == 'thumb':
        svg = render_face(hm, face_name, face, px_per_mm=1.0, labels=False, filters=False, css_class='hw-thumb', uid='t')
    else:
        svg = render_face(hm, face_name, face)
    if layout.pk:
        from django.db import IntegrityError, OperationalError
        try:
            RenderedArtwork.objects.get_or_create(hardware_model=hm, layout_version=layout.version, face=face_name,
                                                  variant=variant, renderer_version=RENDERER_VERSION,
                                                  defaults={'svg': svg})
        except (OperationalError, IntegrityError):
            pass  # cache write lost a race (e.g. SQLite busy); the artwork is still correct
    return svg


def nest_face(hm, layout, face_name, x, y, w, h, uid, labels=True):
    """Embed a face (e.g. a module in its bay) at x,y scaled to fit w×h.

    Returns (markup, defs). The caller adds `defs` once to its <defs>.
    """
    face = layout.faces.get(face_name) if layout else None
    if not face:
        return '', ''
    W, H = float(face['width']), float(face['height'])
    s = min(w / W, h / H)
    ox, oy = x + (w - W * s) / 2, y + (h - H * s) / 2
    f = finish_for(hm)
    body = render_face_body(hm, face_name, face, uid=uid, labels=labels, filters=False, finish=f)
    return (f'<g class="hw-nested" transform="translate({_f(ox)} {_f(oy)}) scale({s:.5f})">{body}</g>',
            finish_defs(f, uid, filters=False))
