"""Structured support workflow editor (forms.py): it saves the same JSON
format as the JSON view, every save goes through validate_definition, and
the JSON view stays available as the advanced option."""
import json

from django.http import QueryDict
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from psa.tests._base import TEST_MIDDLEWARE
from tech_access.testing import make_tech

from . import engine, forms
from .builtins import BUILTINS
from .models import SupportWorkflowDefinition


def rows_to_post(rows):
    """What a browser would submit for the editor rendered from `rows`."""
    q = QueryDict(mutable=True)
    q['editor'] = 'form'
    for k in ('name', 'description', 'freshness_minutes', 'verify_within_minutes', 'requires_integration',
              'manual_steps'):
        q[k] = str(rows[k])
    q.setlist('categories', rows['categories'])
    q.setlist('evidence', rows['evidence'])

    def cond(prefix, c):
        q[f'{prefix}-mode'] = c['mode']
        q[f'{prefix}-json'] = c['json']
        for i, r in enumerate(c['rules']):
            q[f'{prefix}-r{i}-fact'] = r['fact']
            q[f'{prefix}-r{i}-op'] = r['op']
            q[f'{prefix}-r{i}-value'] = r['value']
    for i, c in enumerate(rows['causes']):
        q[f'cause{i}-text'] = c['text']
        cond(f'cause{i}', c['when'])
    for i, r in enumerate(rows['remediations']):
        q[f'rem{i}-action'] = r['action']
        q[f'rem{i}-impact'] = r['impact']
        cond(f'rem{i}', r['when'])
    return q


def _signed_in(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


class FormMappingTests(TestCase):
    def test_every_builtin_round_trips_through_the_form(self):
        for b in BUILTINS:
            want = {k: v for k, v in b.items() if k != 'slug'}
            got, errors = forms.from_post(rows_to_post(forms.to_rows(want)), base=want)
            self.assertEqual(errors, [], b['slug'])
            self.assertEqual(got, want, b['slug'])
            self.assertEqual(engine.validate_definition(got), [])

    def test_nested_condition_kept_as_json(self):
        nested = {'any': [{'all': [{'fact': 'severity', 'op': 'eq', 'value': 'critical'},
                                   {'fact': 'device_online', 'op': 'falsy'}]},
                          {'fact': 'occurrences', 'op': 'gte', 'value': 3}]}
        d = dict(engine.builtin('computer-offline'), causes=[{'text': 'Nested', 'when': nested}])
        d.pop('slug')
        rows = forms.to_rows(d)
        self.assertEqual(rows['causes'][0]['when']['mode'], 'json')
        got, errors = forms.from_post(rows_to_post(rows), base=d)
        self.assertEqual(errors, [])
        self.assertEqual(got['causes'][0]['when'], nested)

    def test_values(self):
        self.assertEqual(forms._value_text('2'), '"2"')  # a string "2" stays a string
        self.assertEqual(forms._parse_value('"2"', 'eq'), '2')
        self.assertEqual(forms._parse_value('2', 'eq'), 2)
        self.assertEqual(forms._parse_value('spooler', 'eq'), 'spooler')
        self.assertEqual(forms._parse_value('a, b', 'in'), ['a', 'b'])
        self.assertIsNone(forms._parse_value('x', 'truthy'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EditorViewTests(TestCase):
    def setUp(self):
        from core.models import SystemSetting
        from psa.tests._base import _setup_seed
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.c = _signed_in(make_tech('wfadmin', superuser=True))

    def test_save_through_the_editor_and_validation(self):
        url = reverse('support_workflows:admin_edit', args=['service-stopped'])
        page = self.c.get(url)
        self.assertContains(page, 'data-workflow-editor="form"')
        self.assertContains(page, 'Start the Print Spooler service')
        d = engine.builtin('service-stopped')
        d.pop('slug')
        post = rows_to_post(forms.to_rows(d))
        post['name'] = 'Service stopped (Alpha)'
        post['verify_within_minutes'] = '45'
        post['cause0-delete'] = 'on'
        post['manual_steps'] = 'Check the service.\n\nCall the user.'
        r = self.c.post(url, post)
        self.assertEqual(r.status_code, 302)
        row = SupportWorkflowDefinition.objects.get(slug='service-stopped')
        self.assertEqual(row.name, 'Service stopped (Alpha)')
        self.assertEqual(row.definition['verify_within_minutes'], 45)
        self.assertEqual(len(row.definition['causes']), len(d['causes']) - 1)
        self.assertEqual(row.definition['manual_steps'], ['Check the service.', 'Call the user.'])
        self.assertEqual(row.definition['remediations'], d['remediations'])
        # An unknown fact is refused by validate_definition and nothing changes.
        post['cause1-mode'] = 'all'
        post['cause1-r0-fact'] = 'shell'
        post['cause1-r0-op'] = 'eq'
        post['cause1-r0-value'] = 'rm'
        post['name'] = 'Changed again'
        r = self.c.post(url, post)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'unknown fact')
        self.assertEqual(SupportWorkflowDefinition.objects.get(slug='service-stopped').name,
                         'Service stopped (Alpha)')

    def test_new_workflow_more_rows_and_json_view(self):
        url = reverse('support_workflows:admin_new')
        post = {'editor': 'form', 'slug': 'Printer jam', 'name': 'Printer jam', 'categories': ['application'],
                'evidence': ['alert'], 'freshness_minutes': '30', 'verify_within_minutes': '60',
                'cause0-text': 'Paper jam', 'cause0-mode': 'any',
                'cause0-r0-fact': 'severity', 'cause0-r0-op': 'in', 'cause0-r0-value': 'warning, error',
                'rem0-action': 'windows.service.start@1', 'rem0-mode': 'always', 'manual_steps': 'Open the tray.'}
        r = self.c.post(url, dict(post, op='more'))
        self.assertEqual(r.status_code, 200)  # re-rendered with more rows, not saved
        self.assertFalse(SupportWorkflowDefinition.objects.exists())
        self.assertContains(r, 'name="cause3-text"')
        self.assertContains(r, 'Paper jam')
        r = self.c.post(url, post)
        self.assertEqual(r.status_code, 302)
        d = SupportWorkflowDefinition.objects.get(slug='printer-jam').definition
        self.assertEqual(d['causes'], [{'text': 'Paper jam', 'when': {'any': [
            {'fact': 'severity', 'op': 'in', 'value': ['warning', 'error']}]}}])
        self.assertEqual(d['remediations'], [{'action': 'windows.service.start@1', 'when': {}}])
        self.assertEqual(engine.validate_definition(d), [])
        # The JSON view shows and saves the same format.
        edit = reverse('support_workflows:admin_edit', args=['printer-jam'])
        page = self.c.get(edit + '?view=json')
        self.assertContains(page, 'data-workflow-editor="json"')
        self.assertContains(page, '&quot;Paper jam&quot;')
        r = self.c.post(edit, {'editor': 'json', 'definition': json.dumps(dict(d, name='Jam (JSON)'))})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SupportWorkflowDefinition.objects.get(slug='printer-jam').name, 'Jam (JSON)')
        r = self.c.post(edit, {'editor': 'json', 'definition': '{not json'})
        self.assertContains(r, 'Not valid JSON')

    def test_unknown_action_cannot_be_saved(self):
        url = reverse('support_workflows:admin_new')
        r = self.c.post(url, {'editor': 'form', 'slug': 'bad', 'name': 'Bad', 'categories': ['other'],
                              'freshness_minutes': '30', 'verify_within_minutes': '60',
                              'rem0-action': 'shell.exec@1', 'rem0-mode': 'always'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'action must be one of')
        self.assertFalse(SupportWorkflowDefinition.objects.exists())

    def test_technician_cannot_edit(self):
        c = _signed_in(make_tech('plainlee'))
        r = c.post(reverse('support_workflows:admin_new'), {'editor': 'form', 'slug': 'x', 'name': 'x'})
        self.assertIn(r.status_code, (302, 403, 404))
        self.assertFalse(SupportWorkflowDefinition.objects.exists())
