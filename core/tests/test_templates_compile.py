"""Every template must compile.

A template that uses an unknown filter or tag only fails when its page is
opened (v3.17.628: `|replace` 500'd the equipment model and navigation-link
pages). Compiling them all here catches that class of bug in CI.
"""
from pathlib import Path

from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase


def _template_names():
    roots = [Path(d) for d in settings.TEMPLATES[0]['DIRS']]
    from django.apps import apps
    roots += [Path(a.path) / 'templates' for a in apps.get_app_configs()
              if str(a.path).startswith(str(settings.BASE_DIR)) and 'venv' not in str(a.path)]
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob('*.html'):
            yield p.relative_to(root).as_posix()


class TemplatesCompileTests(SimpleTestCase):
    def test_every_template_compiles(self):
        engine = engines['django']
        failures = []
        names = sorted(set(_template_names()))
        self.assertGreater(len(names), 50)
        for name in names:
            try:
                engine.get_template(name)
            except Exception as e:  # noqa: BLE001
                failures.append(f'{name}: {type(e).__name__}: {e}')
        self.assertEqual(failures, [], '\n'.join(failures))
