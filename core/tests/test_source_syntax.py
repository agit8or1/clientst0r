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

    def test_no_invalid_escape_sequences(self):
        """v3.17.514: a backslash Python doesn't recognise as an escape is a
        `SyntaxWarning` today and a `SyntaxError` in a future release — but the
        dangerous case is the one that raises nothing at all. A Windows path
        written `"root\\cimv2\\terminalservices"` in a non-raw literal makes
        `\\t` a TAB, so the seeded article silently shipped
        `root\\cimv2<TAB>erminalservices` and the `t` was simply gone. Same for
        `C:\\Data\\file.txt` (`\\f` formfeed) and `C:\\Tasks\\backup.xml`
        (`\\b` backspace).

        Warnings are the tractable signal for the whole class, so the suite
        holds the codebase at zero.
        """
        import warnings

        offenders = []
        for package in self.packages:
            for path in package.rglob('*.py'):
                if '__pycache__' in path.parts:
                    continue
                source = path.read_text(encoding='utf-8')
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    try:
                        compile(source, str(path), 'exec')
                    except SyntaxError:
                        continue        # reported by the parse test instead
                    for item in caught:
                        if issubclass(item.category, SyntaxWarning):
                            rel = path.relative_to(self.base)
                            offenders.append(f'{rel}:{item.lineno}: {item.message}')

        self.assertEqual(
            offenders, [],
            'SyntaxWarnings (use a raw string, or double the backslash):\n  '
            + '\n  '.join(offenders),
        )

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


class TemplateCommentTests(SimpleTestCase):
    """Django's `{# #}` comment is single-line only.

    Spread one over two lines and it stops being a comment: Django renders the
    text verbatim into the page. There is no error and no warning — the note you
    wrote for the next developer is simply displayed to every user.

    v3.17.525: ten templates were doing this. One of them printed a rationale
    about which sudo commands the updater is granted onto the Settings > Updates
    page. `{% comment %}...{% endcomment %}` is the multi-line form.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = Path(__file__).resolve().parent.parent.parent
        cls.templates = sorted((cls.base / 'templates').rglob('*.html'))

    def test_templates_are_discovered(self):
        self.assertGreater(len(self.templates), 50,
                           'template sweep found suspiciously few files')

    def test_no_multi_line_hash_comments(self):
        offenders = []
        for path in self.templates:
            text = path.read_text(encoding='utf-8', errors='replace')
            for lineno, line in enumerate(text.splitlines(), 1):
                head, sep, tail = line.partition('{#')
                if sep and '#}' not in tail:
                    rel = path.relative_to(self.base)
                    offenders.append(f'{rel}:{lineno}: {tail.strip()[:60]}')

        self.assertEqual(
            offenders, [],
            'Unterminated `{#` — Django renders these to the user verbatim. '
            'Use {% comment %}...{% endcomment %} for multi-line comments:\n  '
            + '\n  '.join(offenders),
        )
