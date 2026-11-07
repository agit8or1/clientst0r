"""Hostile strings in page-script data stay data (v3.17.629).

The saved-query editor embedded `json.dumps(filters)|safe` inside a
`<script type="application/json">` element. A filter value containing
`</script><script>…` ended that element and started an executable one, which
ran for anyone opening the editor — including a superuser editing another
user's query. Data now goes through Django's `json_script`, which escapes
`<`, `>` and `&`.

These tests parse the response the way a browser tokenizes it and assert:
there is no script element beyond the page's own, and the JSON element's
text parses back to exactly the stored value.
"""
import json
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from reports.tests import TEST_MIDDLEWARE

SENTINEL = 'xss_sentinel_7f3a'
HOSTILE = [
    f'</script><script>window.{SENTINEL}=1</script>',
    f'</SCRIPT ><img src=x onerror={SENTINEL}()>',
    f'<!--<script>{SENTINEL}()</script>-->',
    f'"; {SENTINEL}(); //',
    f"'><svg onload={SENTINEL}()>",
    '&lt;/script&gt; \u2028 \u2029 \\u003c',
]


class _Scripts(HTMLParser):
    """Collect every <script> element as the HTML tokenizer sees it."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self._cur = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._cur = {'attrs': dict(attrs), 'text': ''}
        elif tag in ('img', 'svg') and any(k.startswith('on') for k, _ in attrs):
            self.scripts.append({'attrs': dict(attrs), 'text': '', 'handler': tag})

    def handle_endtag(self, tag):
        if tag == 'script' and self._cur is not None:
            self.scripts.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur['text'] += data


def scripts_in(html):
    p = _Scripts()
    p.feed(html)
    return p.scripts


class JsonScriptPrimitiveTests(SimpleTestCase):
    """json_script output survives every hostile value as one inert element."""

    def test_old_pattern_is_detected(self):
        """Control: the pre-fix json.dumps|safe embedding yields an extra script element."""
        tpl = Template('<script type="application/json" id="x">{{ raw|safe }}</script>')
        html = tpl.render(Context({'raw': json.dumps([{'value': HOSTILE[0]}])}))
        found = scripts_in(html)
        self.assertGreater(len(found), 1)
        self.assertTrue(any(SENTINEL in s['text'] and s['attrs'].get('type') != 'application/json' for s in found))

    def test_hostile_values_round_trip_in_a_single_element(self):
        tpl = Template('{{ data|json_script:"payload" }}')
        for value in HOSTILE:
            html = tpl.render(Context({'data': {'value': value, 'list': [value]}}))
            found = scripts_in(html)
            self.assertEqual(len(found), 1, f'{value!r} produced extra elements: {found}')
            self.assertEqual(found[0]['attrs'].get('type'), 'application/json')
            self.assertEqual(json.loads(found[0]['text']), {'value': value, 'list': [value]})


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SavedQueryEditorXSSTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('sq_author', password='x', is_superuser=True, is_staff=True)
        self.admin = User.objects.create_superuser('sq_admin', 'a@example.com', 'x')
        from reports.models import SavedQuery
        self.filters = [{'field': 'subject', 'op': 'contains', 'value': v} for v in HOSTILE]
        self.sq = SavedQuery.objects.create(owner=self.author, name='Hostile', target_model='psa.Ticket',
                                            filters=self.filters, columns=['subject'])

    def _page(self, user):
        self.client.force_login(user)
        resp = self.client.get(reverse('reports:saved_query_edit', args=[self.sq.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_superuser_editing_another_users_query_gets_no_injected_script(self):
        html = self._page(self.admin)
        found = scripts_in(html)
        self.assertFalse([s for s in found if s.get('handler')], 'an event-handler element was injected')
        executable = [s for s in found if s['attrs'].get('type') != 'application/json']
        self.assertFalse([s for s in executable if SENTINEL in s['text']], 'hostile text reached executable script')
        # Same number of script elements as the page with harmless filter values.
        from reports.models import SavedQuery
        benign = SavedQuery.objects.create(owner=self.author, name='Benign', target_model='psa.Ticket',
                                           filters=[{'field': 'subject', 'op': 'contains', 'value': 'printer'}],
                                           columns=['subject'])
        self.client.force_login(self.admin)
        benign_html = self.client.get(reverse('reports:saved_query_edit', args=[benign.pk])).content.decode()
        self.assertEqual(len(found), len(scripts_in(benign_html)))
        by_id = {s['attrs'].get('id'): s for s in found if s['attrs'].get('id')}
        self.assertIn('sq-existing-filters', by_id)
        self.assertEqual(json.loads(by_id['sq-existing-filters']['text']), self.filters)
        self.assertEqual(json.loads(by_id['sq-existing-columns']['text']), ['subject'])
        self.assertIn('psa.Ticket', json.loads(by_id['sq-config']['text']))
        # The raw closing sequence must not appear anywhere in the page.
        self.assertNotIn('</script><script>window.' + SENTINEL, html)

    def test_hostile_values_survive_a_save_round_trip(self):
        """Legitimate (and hostile) filter text is stored and shown unchanged."""
        self.client.force_login(self.author)
        resp = self.client.post(reverse('reports:saved_query_edit', args=[self.sq.pk]), {
            'name': 'Hostile', 'target_model': 'psa.Ticket',
            'filter_field': ['subject'] * len(HOSTILE), 'filter_op': ['contains'] * len(HOSTILE),
            'filter_value': HOSTILE, 'column': ['subject'],
        })
        self.assertEqual(resp.status_code, 302)
        self.sq.refresh_from_db()
        self.assertEqual([f['value'] for f in self.sq.filters], HOSTILE)
        by_id = {s['attrs'].get('id'): s for s in scripts_in(self._page(self.author)) if s['attrs'].get('id')}
        self.assertEqual([f['value'] for f in json.loads(by_id['sq-existing-filters']['text'])], HOSTILE)

    def test_edit_permission_unchanged(self):
        User = get_user_model()
        other = User.objects.create_user('sq_other', password='x', is_staff=True)
        self.client.force_login(other)
        resp = self.client.get(reverse('reports:saved_query_edit', args=[self.sq.pk]))
        self.assertNotEqual(resp.status_code, 200)


class NoUnsafeJsonEmbeddingTests(SimpleTestCase):
    """Guard against the pattern coming back: json.dumps / *_json piped through |safe in a template."""

    def test_no_json_safe_in_templates(self):
        import re
        from pathlib import Path
        from django.conf import settings
        pattern = re.compile(r'\{\{\s*[\w.]*(_json|json_dumps|sla_matrix)[\w.]*\s*\|\s*safe\s*\}\}')
        offenders = []
        roots = [Path(settings.BASE_DIR) / 'templates'] + list(Path(settings.BASE_DIR).glob('*/templates'))
        for root in roots:
            for p in root.rglob('*.html'):
                for i, line in enumerate(p.read_text(errors='ignore').splitlines(), 1):
                    if pattern.search(line):
                        offenders.append(f'{p.relative_to(settings.BASE_DIR)}:{i}: {line.strip()}')
        self.assertEqual(offenders, [], 'Use |json_script instead:\n' + '\n'.join(offenders))
