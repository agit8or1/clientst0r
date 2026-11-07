"""Tests for scripts/ci/pip_audit_summary.py — all four outcomes.

Run:  python -m unittest scripts/ci/test_pip_audit_summary.py
(also run in CI before the audit itself, and from the Django suite via
core.tests.test_ci_audit_summary).
"""
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pip_audit_summary as S  # noqa: E402

TODAY = dt.date(2026, 11, 6)

CLEAN_REPORT = {'dependencies': [{'name': 'django', 'version': '6.0.10', 'vulns': []},
                                 {'name': 'localpkg', 'skip_reason': 'Dependency not found on PyPI'}],
                'fixes': []}
VULN_REPORT = {'dependencies': [
    {'name': 'pillow', 'version': '12.3.0', 'vulns': [
        {'id': 'GHSA-78g4-xqwv-q3g8', 'fix_versions': ['13.0.0'], 'aliases': [], 'description': 'libopenjp2'}]},
    {'name': 'paramiko', 'version': '3.5.1', 'vulns': [
        {'id': 'PYSEC-2026-2858', 'fix_versions': [], 'aliases': ['GHSA-r374-rxx8-8654', 'CVE-2026-44405']},
        {'id': 'PYSEC-2026-2858', 'fix_versions': [], 'aliases': ['GHSA-r374-rxx8-8654', 'CVE-2026-44405']}]},
], 'fixes': []}
EXCEPTIONS = '''
[[exception]]
id = "GHSA-r374-rxx8-8654"
package = "paramiko"
reason = "no fix"
mitigation = "ssh-rsa disabled"
owner = "netconfig"
expires = 2027-02-01
'''


class SummaryOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, content):
        p = self.dir / name
        p.write_text(content if isinstance(content, str) else json.dumps(content))
        return p

    def run_eval(self, report, scanner_exit, exceptions=None, today=TODAY):
        return S.evaluate(report, scanner_exit, exceptions, today=today)

    # 1. clean
    def test_clean(self):
        code, lines = self.run_eval(self.write('r.json', CLEAN_REPORT), 0)
        self.assertEqual(code, S.CLEAN)
        text = '\n'.join(lines)
        self.assertIn('Clean', text)
        self.assertIn('localpkg', text)          # skipped deps are disclosed, not hidden

    # 2. vulnerabilities
    def test_vulnerabilities_block(self):
        code, lines = self.run_eval(self.write('r.json', VULN_REPORT), 1)
        self.assertEqual(code, S.VULNERABLE)
        text = '\n'.join(lines)
        self.assertIn('GHSA-78g4-xqwv-q3g8', text)
        self.assertIn('PYSEC-2026-2858', text)
        self.assertEqual(text.count('PYSEC-2026-2858'), 1, 'duplicate entries are reported once')

    def test_exception_by_alias_accepts_only_that_advisory(self):
        code, lines = self.run_eval(self.write('r.json', VULN_REPORT), 1, self.write('e.toml', EXCEPTIONS))
        self.assertEqual(code, S.VULNERABLE)          # pillow still blocks
        text = '\n'.join(lines)
        self.assertIn('Accepted', text)
        only_paramiko = {'dependencies': [VULN_REPORT['dependencies'][1]]}
        code, _ = self.run_eval(self.write('p.json', only_paramiko), 1, self.write('e.toml', EXCEPTIONS))
        self.assertEqual(code, S.CLEAN)

    def test_expired_exception_stops_applying(self):
        only_paramiko = {'dependencies': [VULN_REPORT['dependencies'][1]]}
        code, lines = self.run_eval(self.write('p.json', only_paramiko), 1, self.write('e.toml', EXCEPTIONS),
                                    today=dt.date(2027, 3, 1))
        self.assertEqual(code, S.VULNERABLE)
        self.assertIn('Expired exceptions', '\n'.join(lines))

    def test_incomplete_exception_is_malformed(self):
        bad = '[[exception]]\nid = "X"\npackage = "p"\n'
        code, _ = self.run_eval(self.write('r.json', CLEAN_REPORT), 0, self.write('e.toml', bad))
        self.assertEqual(code, S.MALFORMED)

    # 3. malformed output
    def test_malformed_outputs(self):
        cases = {
            'not json': 'pip-audit: error\n',
            'old assumed schema': {'vulnerabilities': [{'fix_versions': ['1.0']}]},
            'vulns not a list': {'dependencies': [{'name': 'x', 'version': '1', 'vulns': None}]},
            'vuln without id': {'dependencies': [{'name': 'x', 'version': '1', 'vulns': [{}]}]},
            'dependency without name': {'dependencies': [{'version': '1', 'vulns': []}]},
        }
        for label, content in cases.items():
            with self.subTest(label):
                code, lines = self.run_eval(self.write('m.json', content), 0)
                self.assertEqual(code, S.MALFORMED, label)
                self.assertNotIn('Clean', '\n'.join(lines))

    def test_missing_report_is_malformed(self):
        code, _ = self.run_eval(self.dir / 'never-written.json', 0)
        self.assertEqual(code, S.MALFORMED)

    def test_exit_one_with_empty_report_is_malformed(self):
        code, _ = self.run_eval(self.write('r.json', CLEAN_REPORT), 1)
        self.assertEqual(code, S.MALFORMED)

    # 4. scanner failure
    def test_scanner_failure(self):
        for exit_code in (2, 127, -9):
            with self.subTest(exit_code=exit_code):
                code, lines = self.run_eval(self.write('r.json', CLEAN_REPORT), exit_code)
                self.assertEqual(code, S.SCANNER)
                self.assertIn('Scanner failure', '\n'.join(lines))

    def test_cli_exit_codes_and_summary_file(self):
        import contextlib
        summary = self.dir / 'summary.md'
        out = io.StringIO()
        # Captured: printed to the real log, the ::error:: line would become a
        # GitHub annotation on a passing run.
        with contextlib.redirect_stdout(out):
            rc = S.main(['--report', str(self.write('r.json', VULN_REPORT)), '--scanner-exit', '1',
                         '--summary', str(summary)])
        self.assertIn('::error::Dependency audit result: vulnerable', out.getvalue())
        self.assertEqual(rc, S.VULNERABLE)
        self.assertIn('GHSA-78g4-xqwv-q3g8', summary.read_text())

    def test_repository_exception_file_is_valid(self):
        repo = Path(__file__).resolve().parents[2]
        active, expired = S.load_exceptions(repo / '.github' / 'security-exceptions.toml', TODAY)
        self.assertTrue(active)
        self.assertFalse(expired)


if __name__ == '__main__':
    unittest.main()
