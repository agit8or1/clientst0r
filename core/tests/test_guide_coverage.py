"""Every part of the application has a guide with an annotated figure (roadmap 112.1)."""
from django.test import SimpleTestCase

from core import guide_coverage as cov
from core.guides import GUIDES, GUIDES_BY_SLUG
from core.navigation import SECTIONS

# The size of each waiting list today. Lower these as guides land; never raise
# them: a new navigation section or guide arrives documented, with a figure.
PENDING_SECTIONS_CEILING = 26
GUIDES_WITHOUT_FIGURE_CEILING = 32


class SectionCoverageTests(SimpleTestCase):

    def test_every_section_is_documented_or_pending(self):
        keys = {s.key for s in SECTIONS}
        documented = set(cov.SECTION_GUIDES)
        self.assertEqual(sorted(keys - documented - cov.PENDING_SECTIONS), [],
                         'a navigation section with no guide: document it and add it to SECTION_GUIDES')
        self.assertEqual(sorted(documented & cov.PENDING_SECTIONS), [],
                         'documented now: remove it from PENDING_SECTIONS')
        self.assertEqual(sorted((documented | cov.PENDING_SECTIONS) - keys), [],
                         'no longer a navigation section: remove it')

    def test_sections_point_at_real_guides(self):
        for key, slug in cov.SECTION_GUIDES.items():
            self.assertIn(slug, GUIDES_BY_SLUG, key)
            self.assertEqual(cov.guide_for_section(key).slug, slug)
        self.assertIsNone(cov.guide_for_section('no_such_section'))

    def test_the_pending_list_only_shrinks(self):
        self.assertLessEqual(len(cov.PENDING_SECTIONS), PENDING_SECTIONS_CEILING)


class FigureCoverageTests(SimpleTestCase):

    def test_every_guide_has_a_figure_or_is_waiting_for_one(self):
        missing, done = [], []
        for g in GUIDES:
            if cov.has_figure(g):
                if g.slug in cov.GUIDES_WITHOUT_FIGURE:
                    done.append(g.slug)
            elif g.slug not in cov.GUIDES_WITHOUT_FIGURE:
                missing.append(g.slug)
        self.assertEqual(missing, [], 'add an annotated figure (scripts/guide_screenshots.json)')
        self.assertEqual(done, [], 'has a figure now: remove it from GUIDES_WITHOUT_FIGURE')
        self.assertEqual(sorted(cov.GUIDES_WITHOUT_FIGURE - set(GUIDES_BY_SLUG)), [], 'not a guide')

    def test_the_waiting_list_only_shrinks(self):
        self.assertLessEqual(len(cov.GUIDES_WITHOUT_FIGURE), GUIDES_WITHOUT_FIGURE_CEILING)
