"""Technician Access forms: a POST that leaves a control out does not clear it.

Selects post their value even when it is Off, but an emptied multi-select or
an unticked checkbox posts nothing — so "nothing posted" only means "clear"
when the form shows the control was rendered (a hidden sentinel).
"""
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings

from psa.tests._base import TEST_MIDDLEWARE, _setup_seed

from . import catalog
from .models import AccessPreset, CustomerAccessPolicy, DetectionSettings, ProtectionSettings, TechnicianGroup
from .testing import make_tech
from core.models import Organization

URL = '/settings/security/technician-access/'
ALLOWED, OFF = catalog.ALLOWED, catalog.OFF


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TechnicianAccessFormTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='Gamma Clinic', slug='ta-ff-gamma')
        self.admin = make_tech('ta_ff_admin', superuser=True)
        self.tech = make_tech('ta_ff_tech')
        self.c = Client()
        self.c.force_login(self.admin)
        self.c.get(URL)  # seeds the built-in presets
        caps = {k: OFF for k in catalog.OPTIONAL}
        caps['ai_analyze'] = ALLOWED
        caps['ai_draft'] = ALLOWED
        self.preset = AccessPreset.objects.create(name='Custom desk', capabilities=caps)

    def _errors(self, r):
        return [str(m) for m in get_messages(r.wsgi_request) if m.level_tag == 'danger' or m.level_tag == 'error']

    def test_a_preset_save_without_some_capabilities_keeps_them(self):
        r = self.c.post(URL, {'action': 'save_preset', 'preset': self.preset.pk, 'cap_ai_draft': OFF})
        self.assertEqual(r.status_code, 302)
        self.preset.refresh_from_db()
        self.assertEqual(self.preset.capabilities['ai_analyze'], ALLOWED)  # not posted → kept
        self.assertEqual(self.preset.capabilities['ai_draft'], OFF)        # posted Off → narrowed

    def test_a_malformed_capability_state_is_not_a_widening(self):
        self.c.post(URL, {'action': 'save_preset', 'preset': self.preset.pk, 'cap_ai_analyze': 'everything'})
        self.preset.refresh_from_db()
        self.assertIn(self.preset.capabilities['ai_analyze'], (OFF, ALLOWED))
        self.assertEqual(self.preset.capabilities['ai_send'], OFF)

    def test_customer_policy_without_the_lists_keeps_default_and_restrictions(self):
        CustomerAccessPolicy.objects.create(organization=self.org, default_preset=self.preset,
                                            restricted=['ai_draft'])
        self.c.post(URL, {'action': 'customer_policy', 'organization': self.org.pk})
        pol = CustomerAccessPolicy.objects.get(organization=self.org)
        self.assertEqual(pol.default_preset_id, self.preset.pk)
        self.assertEqual(pol.restricted, ['ai_draft'])

    def test_customer_policy_explicit_choices_still_apply(self):
        CustomerAccessPolicy.objects.create(organization=self.org, default_preset=self.preset, restricted=[])
        self.c.post(URL, {'action': 'customer_policy', 'organization': self.org.pk, 'default_preset': '',
                          'restricted_present': '1', 'restricted': ['ai_send']})
        pol = CustomerAccessPolicy.objects.get(organization=self.org)
        self.assertIsNone(pol.default_preset_id)  # "L1 (built in)" chosen on purpose
        self.assertEqual(pol.restricted, ['ai_send'])

    def test_group_members_post_without_the_sentinel_changes_nothing(self):
        g = TechnicianGroup.objects.create(name='Night shift')
        g.members.add(self.tech)
        r = self.c.post(URL, {'action': 'group_members', 'group': g.pk})
        self.assertEqual(list(g.members.all()), [self.tech])
        self.assertTrue(any('nothing was changed' in e for e in self._errors(r)))

    def test_group_members_emptied_on_purpose_are_removed(self):
        g = TechnicianGroup.objects.create(name='Night shift')
        g.members.add(self.tech)
        self.c.post(URL, {'action': 'group_members', 'group': g.pk, 'members_present': '1'})
        self.assertEqual(g.members.count(), 0)

    def test_detection_without_the_checkbox_sentinel_keeps_settings(self):
        s = DetectionSettings.load()
        s.enabled, s.notify_customers, s.recipients = True, True, 'soc@example.test'
        s.containment = {'1': 'alert'}
        s.save()
        self.c.post(URL, {'action': 'detection'})
        s = DetectionSettings.load()
        self.assertTrue(s.enabled)
        self.assertTrue(s.notify_customers)
        self.assertEqual(s.recipients, 'soc@example.test')
        self.assertEqual(s.containment.get('1'), 'alert')

    def test_detection_unticked_with_the_sentinel_is_a_real_change(self):
        from .models import ProtectedChange
        s = DetectionSettings.load()
        s.notify_customers = True
        s.save()
        # Unticking with the sentinel is a request to turn reports off; that
        # loosens detection, so it becomes a protected change.
        self.c.post(URL, {'action': 'detection', 'detection_flags': '1', 'enabled': 'on'})
        self.assertTrue(DetectionSettings.load().notify_customers)
        change = ProtectedChange.objects.get(status=ProtectedChange.PENDING)
        self.assertIn('customer reports off', change.widening)

    def test_detection_ticking_a_checkbox_with_the_sentinel_applies(self):
        s = DetectionSettings.load()
        s.notify_customers = False
        s.save()
        self.c.post(URL, {'action': 'detection', 'detection_flags': '1', 'enabled': 'on',
                          'notify_customers': 'on'})
        self.assertTrue(DetectionSettings.load().notify_customers)

    def test_a_post_without_the_sentinel_proposes_no_loosening(self):
        from .models import ProtectedChange
        s = DetectionSettings.load()
        s.enabled, s.notify_customers, s.recipients = True, True, 'soc@example.test'
        s.save()
        self.c.post(URL, {'action': 'detection'})
        self.assertFalse(ProtectedChange.objects.filter(status=ProtectedChange.PENDING).exists())

    def test_approvers_without_the_sentinel_are_left_alone(self):
        other = make_tech('ta_ff_other', superuser=True)
        ProtectionSettings.load().approvers.add(self.admin, other)
        r = self.c.post(URL, {'action': 'approvers'})
        self.assertEqual(ProtectionSettings.load().approvers.count(), 2)
        self.assertTrue(self._errors(r))

    def test_the_page_renders_every_sentinel(self):
        TechnicianGroup.objects.create(name='Night shift')
        r = self.c.get(URL)
        for name in ('members_present', 'restricted_present', 'detection_flags', 'approvers_present'):
            self.assertContains(r, f'name="{name}"')
