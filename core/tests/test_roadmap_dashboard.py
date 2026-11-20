"""The roadmap dashboard stays generated from the phase records, and the JSON feed still reads every phase."""
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

from core.views import roadmap_status_json

ROOT = Path(settings.BASE_DIR)
ROADMAP = ROOT / 'docs' / 'ROADMAP.md'


class RoadmapDashboardTests(SimpleTestCase):
    def test_generated_sections_are_current(self):
        """Editing a phase record without running scripts/roadmap_dashboard.py fails here."""
        r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'roadmap_dashboard.py'), '--check'],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_phase_has_anchor_and_record(self):
        text = ROADMAP.read_text(encoding='utf-8')
        nums = re.findall(r'^## Phase (\d+) — ', text, re.M)
        self.assertGreaterEqual(len(nums), 108)
        self.assertEqual(len(nums), len(set(nums)), 'duplicate phase numbers')
        for n in nums:
            self.assertIn(f'<a id="phase-{n}"></a>', text)
            self.assertRegex(text, rf'(?m)^## Phase {n} — .*\n<!-- phase: ')

    def test_internal_links_resolve(self):
        text = ROADMAP.read_text(encoding='utf-8')
        anchors = set(re.findall(r'<a id="([^"]+)"></a>', text))
        missing = sorted(set(re.findall(r'\]\(#([^)]+)\)', text)) - anchors)
        self.assertEqual(missing, [])

    def test_json_feed_reads_every_phase(self):
        text = ROADMAP.read_text(encoding='utf-8')
        expected = len(re.findall(r'^## Phase \d+ — ', text, re.M))
        resp = roadmap_status_json(RequestFactory().get('/core/roadmap.json'))
        import json
        data = json.loads(resp.content)
        self.assertEqual(data['phase_count'], expected)
        self.assertTrue({p['status'] for p in data['phases']} <= {'planned', 'in_progress', 'shipped', 'complete'})
        by_num = {p['number']: p for p in data['phases']}
        self.assertEqual(by_num[101]['status'], 'planned')
        self.assertEqual(by_num[1]['status'], 'complete')
