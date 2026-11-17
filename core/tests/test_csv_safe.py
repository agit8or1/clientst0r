"""core.csv_safe: spreadsheet formula escaping for CSV exports (v3.17.695)."""
import csv
import io
from decimal import Decimal

from django.test import SimpleTestCase

from core import csv_safe


class SafeCellTests(SimpleTestCase):
    def test_formula_prefixes_are_neutralised(self):
        for v in ('=1+1', '+cmd', '-2+3', '@SUM(A1)', '\t=x', '\r=x', '=cmd|\' /C calc\'!A0', '-x'):
            self.assertEqual(csv_safe.safe_cell(v), "'" + v, v)

    def test_plain_text_and_numbers_unchanged(self):
        for v in ('hello', 'a=b', '', ' =x', '-12.50', '+3', '-.5', '1e5', '-1E-3', 42, -7, 1.5,
                  Decimal('-3.10'), None, True):
            self.assertEqual(csv_safe.safe_cell(v), v, repr(v))

    def test_writer_round_trip(self):
        buf = io.StringIO()
        w = csv_safe.writer(buf)
        w.writerow(['=evil()', 'ok', -5, '-5'])
        w.writerows([['@x'], ['y']])
        rows = list(csv.reader(io.StringIO(buf.getvalue())))
        self.assertEqual(rows, [["'=evil()", 'ok', '-5', '-5'], ["'@x"], ['y']])

    def test_dict_writer(self):
        buf = io.StringIO()
        w = csv_safe.DictWriter(buf, fieldnames=['a', 'b'])
        w.writeheader()
        w.writerows([{'a': '+1+1', 'b': 'fine'}])
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        self.assertEqual(rows, [{'a': "'+1+1", 'b': 'fine'}])
