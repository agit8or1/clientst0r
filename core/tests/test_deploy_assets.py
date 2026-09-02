"""
Files that deploy scripts copy must actually exist in the repo.

v3.17.516: `deploy/setup_mobile_build.sh` copies
`deploy/clientst0r-mobile-build-sudoers` into /etc/sudoers.d. The v3.17.492
rename deleted the old huduglue-named file, and the replacement could never be
committed — `.gitignore` carried a blanket `deploy/*-sudoers` rule intended for
generated output, so git ignored the new template silently. The script then had
nothing to copy, and the only symptom was a generic
"[WARN] Mobile build setup failed (non-critical)" on every single update.

Nothing failed loudly, so nothing got looked at. This test makes the repo
assert its own completeness instead.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class DeployAssetReferenceTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = Path(settings.BASE_DIR)
        cls.deploy = cls.base / 'deploy'

    def test_sudoers_templates_referenced_by_scripts_exist(self):
        """Every *-sudoers file a deploy script copies must be present."""
        missing = []
        referenced = set()
        for script in sorted(self.deploy.glob('*.sh')):
            text = script.read_text(encoding='utf-8')
            for name in re.findall(r'[\w./$(){}"-]*?([A-Za-z0-9_-]+-sudoers)\b', text):
                referenced.add((script.name, name))
                if not (self.deploy / name).is_file():
                    missing.append(f'{script.name} copies deploy/{name}, which does not exist')

        self.assertGreater(len(referenced), 0, 'no sudoers references found — did the scan break?')
        self.assertEqual(missing, [], 'Missing deploy assets:\n  ' + '\n  '.join(missing))

    def test_shipped_sudoers_templates_are_not_gitignored(self):
        """A template git refuses to track is a template that silently vanishes.

        Checked against .gitignore's own text rather than by shelling out to
        git, so this still holds in a source tarball with no .git directory.
        """
        gitignore = self.base / '.gitignore'
        if not gitignore.is_file():
            self.skipTest('no .gitignore in this tree')
        lines = [ln.strip() for ln in gitignore.read_text(encoding='utf-8').splitlines()]
        negated = {ln[1:] for ln in lines if ln.startswith('!')}

        broad = [ln for ln in lines if ln in ('deploy/*-sudoers', 'deploy/*sudoers')]
        if not broad:
            return          # no blanket rule, nothing to exempt from

        for template in sorted(self.deploy.glob('*-sudoers')):
            rel = f'deploy/{template.name}'
            self.assertIn(
                rel, negated,
                f'{rel} exists but .gitignore has {broad[0]!r} and no "!{rel}" '
                f'negation — git will silently refuse to track it.',
            )
