"""CSV exports that a spreadsheet cannot run as formulas.

A cell whose text starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage
return is read by Excel, LibreOffice and Google Sheets as a formula
(``=HYPERLINK(...)``, ``=cmd|' /C calc'!A0``, ``@SUM(...)``). Exports carry
text other people typed — ticket subjects, client names, notes — so such a
cell is written with a leading ``'``, which spreadsheets show as text and
hide (OWASP "CSV Injection").

Numbers are left alone: ints, floats and Decimals are not text, and a string
that is just a number (``-12.50``) is written unchanged so amounts stay
numeric.

Use ``csv_safe.writer(f)`` / ``csv_safe.DictWriter(f, fieldnames)`` in place of
``csv.writer`` / ``csv.DictWriter`` for anything a person downloads.
"""
import csv
import re

FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
_NUMBER = re.compile(r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?')


def safe_cell(value):
    """Return `value`, with a leading ``'`` if it is text a spreadsheet would run."""
    if not isinstance(value, str) or not value.startswith(FORMULA_PREFIXES):
        return value
    if _NUMBER.fullmatch(value):
        return value
    return "'" + value


def safe_row(row):
    return [safe_cell(v) for v in row]


class _Writer:
    def __init__(self, inner):
        self._w = inner

    def writerow(self, row):
        return self._w.writerow(safe_row(row))

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

    @property
    def dialect(self):
        return self._w.dialect


def writer(f, *args, **kwargs):
    """Like ``csv.writer``; every cell goes through ``safe_cell``."""
    return _Writer(csv.writer(f, *args, **kwargs))  # nosemgrep: python.django.security.injection.csv-writer-injection.csv-writer-injection -- every cell goes through safe_cell


class DictWriter(csv.DictWriter):
    """Like ``csv.DictWriter``; every value goes through ``safe_cell``.
    The header row (field names) is code, not user data, and is written as is."""

    def writerow(self, rowdict):
        return super().writerow({k: safe_cell(v) for k, v in rowdict.items()})

    def writerows(self, rowdicts):
        for r in rowdicts:
            self.writerow(r)
