#!/usr/bin/env python3
"""Regenerate core/iso3166.py from the Debian `iso-codes` package.

    sudo apt-get install iso-codes
    python scripts/gen_iso3166.py

Kept as a script rather than a runtime dependency: the table changes about
once a year, and the firewall stores these names, so a reproducible snapshot
in the repo beats resolving them at request time.
"""
from __future__ import annotations

import datetime
import io
import json
import pathlib
import sys

SOURCE = pathlib.Path('/usr/share/iso-codes/json/iso_3166-1.json')
TARGET = pathlib.Path(__file__).resolve().parent.parent / 'core' / 'iso3166.py'


def main() -> int:
    if not SOURCE.is_file():
        print(f'error: {SOURCE} not found — install the iso-codes package', file=sys.stderr)
        return 1

    entries = json.loads(SOURCE.read_text(encoding='utf-8'))['3166-1']
    rows = sorted(((c['alpha_2'], c.get('common_name') or c['name']) for c in entries),
                  key=lambda r: r[0])

    header = f'''"""
ISO 3166-1 alpha-2 country codes -> display names.

v3.17.522: needed by the GeoIP map so a country selected on the map can be
stored with a trustworthy name. Deliberately a static table rather than a
new dependency (pycountry/babel) or a trust-the-browser round trip — the
firewall stores these names, so they must not come from client input.

Generated from the Debian `iso-codes` package (iso_3166-1.json), which is
the ISO 3166-1 list maintained for Debian and shipped under LGPL-2.1+.
Regenerate with scripts/gen_iso3166.py. Snapshot taken {datetime.date.today().isoformat()}.
"""

from __future__ import annotations

COUNTRY_NAMES: dict[str, str] = {{
'''
    body = ''.join(f'    {code!r}: {name!r},\n' for code, name in rows)
    footer = '''}


def country_name(code: str, default: str = "") -> str:
    """Display name for an alpha-2 code, case-insensitively."""
    if not code:
        return default
    return COUNTRY_NAMES.get(code.strip().upper(), default or code.strip().upper())


def is_valid_code(code: str) -> bool:
    """True when `code` is a known ISO 3166-1 alpha-2 code."""
    return bool(code) and code.strip().upper() in COUNTRY_NAMES
'''
    io.open(TARGET, 'w', encoding='utf-8').write(header + body + footer)
    print(f'wrote {TARGET} with {len(rows)} countries')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
