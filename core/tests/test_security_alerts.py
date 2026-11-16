"""Code-scanning alert fixes (v3.17.691 onward).

Each test pins one fix for a GitHub code-scanning alert, so the pattern the
alert found cannot come back unnoticed.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)


class KanbanDropUrlTests(SimpleTestCase):
    """CodeQL js/request-forgery: the pipeline board built its POST URL from
    the drag payload, which another page or application can supply."""

    def setUp(self):
        self.src = (ROOT / 'templates/crm/pipeline_kanban.html').read_text()

    def test_url_id_does_not_come_from_drag_payload(self):
        drop = self.src.split("col.addEventListener('drop'", 1)[1]
        self.assertNotIn('getData(', drop)
        self.assertIn('dragged.dataset.oppId', drop)

    def test_only_a_numeric_id_reaches_the_url(self):
        drop = self.src.split("col.addEventListener('drop'", 1)[1]
        check = drop.index("/^[0-9]+$/.test(")
        fetch_at = drop.index('fetch(')
        self.assertLess(check, fetch_at)
        self.assertRegex(drop, re.escape('encodeURIComponent(oppId)'))
