"""
Issue #141 — saving global PSA settings raised
`TypeError: Object of type Decimal is not JSON serializable`.

`psa_ai_min_confidence` is a Decimal. The audit-log change diff put the raw
Decimal into the AuditLog.extra_data JSONField (which uses the plain
json.JSONEncoder), crashing the save on every POST. It also always showed as
"changed" because the `previous` snapshot stringified it while the current value
stayed a Decimal (str != Decimal). Both are fixed by normalising both sides to
str before diffing.
"""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from audit.models import AuditLog
from core.models import SystemSetting

from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalPSASettingsSaveTests(TestCase):

    def setUp(self):
        _enable_psa_global()  # else @require_psa_enabled 404s the route
        self.admin = User.objects.create_user(
            username='psa-admin', password='pw', email='a@x.com',
            is_staff=True, is_superuser=True)
        self.client = Client()
        self.client.force_login(self.admin)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()

    def test_save_does_not_crash_on_decimal(self):
        """POSTing the settings form must not 500 on Decimal serialization."""
        resp = self.client.post('/psa/settings/', {
            'action': 'save_globals',
            'psa_ai_enabled': 'on',
            'psa_ai_min_confidence': '0.80',
        })
        self.assertEqual(resp.status_code, 302)
        SystemSetting.get_settings().refresh_from_db()
        self.assertEqual(str(SystemSetting.get_settings().psa_ai_min_confidence), '0.80')

    def test_audit_extra_data_is_json_serializable(self):
        """The recorded change diff must round-trip through JSON (no Decimal)."""
        self.client.post('/psa/settings/', {
            'action': 'save_globals',
            'psa_ai_enabled': 'on',
            'psa_ai_min_confidence': '0.90',
        })
        entry = AuditLog.objects.filter(object_type='core.SystemSetting').latest('id')
        # Must not raise — proves no Decimal leaked into extra_data.
        json.dumps(entry.extra_data)
        changed = entry.extra_data.get('changed_fields', {})
        if 'psa_ai_min_confidence' in changed:
            self.assertEqual(changed['psa_ai_min_confidence']['to'], '0.90')

    def test_unchanged_min_confidence_not_reported_as_changed(self):
        """Re-saving the same confidence must not falsely report it changed
        (the str-vs-Decimal bug flagged it on every save)."""
        ss = SystemSetting.get_settings()
        ss.psa_ai_min_confidence = 0.75
        ss.save()
        self.client.post('/psa/settings/', {
            'action': 'save_globals',
            'psa_ai_min_confidence': '0.75',
        })
        entry = AuditLog.objects.filter(object_type='core.SystemSetting').latest('id')
        changed = entry.extra_data.get('changed_fields', {})
        self.assertNotIn('psa_ai_min_confidence', changed)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalPSASettingsDefaultSubmitTests(TestCase):
    """Enter in a text field submits with the form's first submit button; that
    must be the main Save Settings, not "Save follow-up settings"."""

    def setUp(self):
        _enable_psa_global()
        self.admin = User.objects.create_user(
            username='psa-admin2', password='pw', is_staff=True, is_superuser=True)
        self.client = Client()
        self.client.force_login(self.admin)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()

    def _first_submit_in_settings_form(self, html):
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.forms, self.cur = [], None

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == 'form':
                    self.cur = {'submits': [], 'has_followup': False}
                    self.forms.append(self.cur)
                elif self.cur is not None and tag in ('button', 'input'):
                    if a.get('type', 'submit' if tag == 'button' else 'text') == 'submit':
                        self.cur['submits'].append(a)
                        if a.get('value') == 'save_followup':
                            self.cur['has_followup'] = True

            def handle_endtag(self, tag):
                if tag == 'form':
                    self.cur = None

        p = P()
        p.feed(html)
        form = next(f for f in p.forms if f['has_followup'])
        return form['submits'][0]

    def test_first_submit_button_is_the_main_save(self):
        r = self.client.get('/psa/settings/')
        self.assertEqual(r.status_code, 200)
        first = self._first_submit_in_settings_form(r.content.decode())
        self.assertEqual(first.get('name'), 'action')
        self.assertEqual(first.get('value'), 'save_globals')

    def test_default_submit_saves_globals_not_followup(self):
        from psa.models import FollowUpPolicy
        before = FollowUpPolicy.get().enabled
        r = self.client.post('/psa/settings/', {
            'action': 'save_globals', 'psa_closeout_require_time': 'on',
            'followup_enabled': '' if before else 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(SystemSetting.get_settings().psa_closeout_require_time)
        self.assertEqual(FollowUpPolicy.get().enabled, before)
