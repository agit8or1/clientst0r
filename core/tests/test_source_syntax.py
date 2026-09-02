"""
Every Python file the app ships must at least parse.

v3.17.513: `core/management/commands/seed_all.py` carried a SyntaxError —
`'... they don\\'t need'`, an escaped backslash followed by a quote, which
terminates the string early. The file could not be imported at all, so
`manage.py seed_all` would have died on invocation. It went unnoticed because
Django imports a management command lazily, only when that command is run, and
nothing else in the test suite touched the module.

It surfaced when the update script started pre-compiling bytecode
(`python -m compileall`) ahead of the graceful reload — compileall parses every
file, so it found in seconds what had been sitting there unnoticed. This test
keeps that guarantee in the suite rather than leaving it to the deploy script.
"""
from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase


# Top-level directories that are not this project's own Python source.
_NOT_OURS = {
    'venv', '.venv', 'env', 'node_modules', 'mobile', 'mobile-app',
    'android-sdk', 'snap', 'local_apps', '.dev-worktree', '.git',
    'agit8or-npm-audit', 'media', 'uploads', 'static_collected', 'data',
}


def _project_packages(base: Path) -> list[Path]:
    """Top-level dirs holding an __init__.py — the same set the update script
    purges and pre-compiles (deploy/update_instructions.sh, step 5)."""
    return sorted(
        child for child in base.iterdir()
        if child.is_dir()
        and child.name not in _NOT_OURS
        and (child / '__init__.py').is_file()
    )


class SourceSyntaxTests(SimpleTestCase):
    """No database, no fixtures — just parse everything we ship."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.conf import settings
        cls.base = Path(settings.BASE_DIR)
        cls.packages = _project_packages(cls.base)

    def test_project_packages_are_discovered(self):
        """Guard the guard: if discovery silently returns nothing, the syntax
        test below would pass vacuously."""
        names = {p.name for p in self.packages}
        self.assertGreater(len(names), 10, f'only found {names}')
        for expected in ('core', 'docs', 'psa', 'vault', 'accounts'):
            self.assertIn(expected, names)

    def test_every_shipped_python_file_parses(self):
        failures = []
        checked = 0
        for package in self.packages:
            for path in package.rglob('*.py'):
                if '__pycache__' in path.parts:
                    continue
                checked += 1
                try:
                    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
                except SyntaxError as exc:
                    rel = path.relative_to(self.base)
                    failures.append(f'{rel}:{exc.lineno}: {exc.msg}')
                except UnicodeDecodeError as exc:
                    failures.append(f'{path.relative_to(self.base)}: not valid UTF-8 ({exc})')

        self.assertGreater(checked, 100, 'suspiciously few files scanned')
        self.assertEqual(
            failures, [],
            'Python files that will not parse:\n  ' + '\n  '.join(failures),
        )
