"""One product name: Clientst0r (roadmap 67.29)."""
import importlib
import re
import subprocess
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from core.models import SystemSetting

ROOT = Path(settings.BASE_DIR)
OLD = re.compile(r'(Client St0r|ClientSt0r)(?![A-Za-z])')

# Kept on purpose: names other systems may match on (user agents) and the
# release history, which records what each release was called at the time.
KEPT_FILES = {'CHANGELOG.md', 'docs/ROADMAP_HISTORY.md'}
KEPT_LINE = re.compile(r'User-Agent|USER_AGENT')


class BrandNameTests(SimpleTestCase):

    def test_old_spellings_are_gone_from_text(self):
        files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True).stdout.split('\n')
        found = []
        for name in files:
            if (not name or name in KEPT_FILES or '/migrations/' in name
                    or not name.endswith(('.py', '.html', '.md', '.js', '.css', '.json', '.txt', '.sh', '.po',
                                          '.service', '.timer', '.yml', '.yaml', '.conf'))):
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            for no, line in enumerate(path.read_text(encoding='utf-8', errors='replace').split('\n'), 1):
                if OLD.search(line) and not KEPT_LINE.search(line) and name != 'core/tests/test_brand_name.py':
                    found.append(f'{name}:{no}')
        self.assertEqual(found, [], 'write "Clientst0r"')


class DefaultNameMigrationTests(TestCase):

    def migration(self):
        return importlib.import_module('core.migrations.0123_brand_name')

    def test_shipped_names_take_the_new_spelling(self):
        SystemSetting.objects.update_or_create(pk=1, defaults={'site_name': 'Client St0r',
                                                               'smtp_from_name': 'ClientSt0r'})
        self.migration().rename_default_names(apps, None)
        s = SystemSetting.objects.get(pk=1)
        self.assertEqual((s.site_name, s.smtp_from_name), ('Clientst0r', 'Clientst0r'))

    def test_a_chosen_name_is_left_alone(self):
        SystemSetting.objects.update_or_create(pk=1, defaults={'site_name': 'Beacon Managed IT',
                                                               'smtp_from_name': 'Beacon Service Desk'})
        self.migration().rename_default_names(apps, None)
        s = SystemSetting.objects.get(pk=1)
        self.assertEqual((s.site_name, s.smtp_from_name), ('Beacon Managed IT', 'Beacon Service Desk'))

    def test_new_installs_default_to_the_new_name(self):
        self.assertEqual(SystemSetting._meta.get_field('site_name').default, 'Clientst0r')
        self.assertEqual(SystemSetting._meta.get_field('smtp_from_name').default, 'Clientst0r')


class LogoTests(SimpleTestCase):

    def test_logos_spell_the_name_on_one_line(self):
        for name in ('logo.svg', 'logo-light.svg'):
            svg = (ROOT / 'static' / 'images' / name).read_text()
            self.assertIn('>Clientst<tspan', svg, name)
            self.assertNotIn('>Client</text>', svg, name)
            self.assertIn('<title>Clientst0r</title>', svg, name)
