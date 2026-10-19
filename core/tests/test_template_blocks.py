"""Page scripts load once, after the libraries they use.

  * A `{% block extra_js %}` written inside `{% block content %}` is rendered
    twice: once in place and again where the base template puts extra_js.
    Scripts then run twice (scheduled-task form: "Identifier
    'recurrenceSelect' has already been declared"; dashboards: listeners
    bound twice).
  * The customer portal loads Bootstrap's JS at the end of <body>; a page
    script that uses `bootstrap.` must go in extra_js, which comes after it
    (portal vault: "bootstrap is not defined").
"""
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.template.loader import get_template
from django.test import SimpleTestCase

SCRIPT_BLOCKS = ('extra_js', 'extra_css', 'extra_head', 'scripts')
TOKEN = re.compile(r'{%\s*(?:block\s+(\w+)|endblock(?:\s+\w+)?)\s*%}')
COMMENT = re.compile(r'{#.*?#}|{%\s*comment\s*%}.*?{%\s*endcomment\s*%}', re.S)


def _templates():
    root = Path(django_settings.BASE_DIR)
    for path in root.rglob('*.html'):
        rel = path.relative_to(root)
        if rel.parts[0] in ('venv', 'node_modules', '.git', 'staticfiles', 'htmlcov'):
            continue
        if 'templates' not in rel.parts or 'site-packages' in rel.parts:
            continue
        yield rel, path.read_text(encoding='utf-8', errors='ignore')


class TemplateScriptBlockTests(SimpleTestCase):

    def test_script_blocks_are_not_nested(self):
        nested = []
        count = 0
        for rel, text in _templates():
            count += 1
            stack = []
            for m in TOKEN.finditer(COMMENT.sub('', text)):
                if m.group(1):
                    if m.group(1) in SCRIPT_BLOCKS and stack:
                        nested.append(f'{rel}: {m.group(1)} inside {stack[-1]}')
                    stack.append(m.group(1))
                elif stack:
                    stack.pop()
        self.assertGreater(count, 300)
        self.assertEqual(nested, [], 'Script blocks nested in another block render twice: '
                         + ', '.join(nested))

    def test_portal_base_has_extra_js_after_bootstrap(self):
        src = get_template('portal/base.html').template.source
        self.assertLess(src.index('bootstrap.bundle'), src.index('{% block extra_js %}'))

    def test_portal_pages_use_bootstrap_only_from_extra_js(self):
        bad = []
        for rel, text in _templates():
            if 'portal' not in rel.parts or rel.name == 'base.html':
                continue
            if 'extends "portal/base.html"' not in text and "extends 'portal/base.html'" not in text:
                continue
            content = text.split('{% block extra_js %}')[0]
            if re.search(r'\bbootstrap\.\w', content):
                bad.append(str(rel))
        self.assertEqual(bad, [], 'Uses bootstrap before it loads: ' + ', '.join(bad))
