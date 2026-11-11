"""
Security finding S2: the older AI routes (generate-reply, generate-actions,
triage) called Anthropic with the install-wide key and never applied the
customer's AI policy. They now go through the same path as AI Troubleshoot:
customer AI policy (exclusion, analysis on, allowed profiles, local-only,
credential owner), the daily/monthly budget, the sharing rules, and the
gateway's provider call. The install-wide ANTHROPIC_API_KEY is never used.

Providers are mocked at gateway.call_provider; nothing leaves the process.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _setup_seed
from tech_access.testing import grant, make_tech, make_ticket

from .models import AIBudgetDay, AIBusinessPolicy, AIModelProfile, AISuggestion
from .services import gateway_keys

KEY_DIR = tempfile.mkdtemp(prefix='aigw-legacy-test-')
REPLY = json.dumps({'body': 'Thanks, we are looking into the printer.', 'confidence': 0.9, 'risk_level': 'low'})
TRIAGE = json.dumps({'summary': 'Printer offline', 'likely_causes': ['network'], 'next_steps': ['check IP']})


def _profile(name, org, provider='anthropic', **kw):
    p = AIModelProfile.objects.create(name=name, provider=provider, model='test-model', enabled=True,
                                      economical=True, credential_owner=AIModelProfile.OWNER_MSP,
                                      input_price_per_1k=10, output_price_per_1k=50, **kw)
    if provider != 'ollama':
        p.set_api_key('sk-ant-' + 'k' * 30)
    p.save()
    p.assigned_organizations.add(org)
    return p


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AI_GATEWAY_KEY_DIR=KEY_DIR,
                   AI_GATEWAY_MODE='in_process', ALLOWED_HOSTS=['*'])
class LegacyRoutesFollowPolicyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (Path(KEY_DIR) / 'private.key').exists():
            gateway_keys.generate(Path(KEY_DIR))

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = s.psa_ai_enabled = True
        s.save()
        self.org = Organization.objects.create(name='Alpha Dental', slug='alpha')
        _enable_psa_for(self.org)
        self.tech = make_tech('lee')
        grant(self.tech, self.org, 'l3')
        self.ticket = make_ticket(self.org, assigned_to=self.tech, subject='Front desk printer offline',
                                  description='Pat Smith says the printer at 10.0.0.12 is offline.',
                                  requester_name='Pat Smith')
        Membership.objects.get_or_create(user=self.tech, organization=self.org,
                                         defaults={'role': Role.EDITOR, 'is_active': True})
        self.c = Client()
        self.c.force_login(self.tech)
        sess = self.c.session
        sess['current_organization_id'] = self.org.pk
        sess.save()
        self.calls = []
        self.sdk_calls = []
        env = patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-install-wide-key-should-not-be-used'})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        # Checked for every test: the install-wide SDK path never ran.
        self.assertEqual(self.sdk_calls, [], 'the install-wide Anthropic key was used')
        super().tearDown()

    def _provider(self, text):
        def fake(profile, system, user_text):
            self.calls.append({'profile': profile, 'system': system, 'user': user_text})
            return text, 300, 100
        return patch('psa_ai.services.gateway.call_provider', side_effect=fake)

    def _policy(self, **kw):
        kw.setdefault('analysis_enabled', True)
        kw.setdefault('daily_budget_cents', 500)
        profiles = kw.pop('profiles', [])
        pol = AIBusinessPolicy.objects.create(organization=self.org, **kw)
        pol.allowed_profiles.set(profiles)
        return pol

    def _no_install_key_call(self):
        """The install-wide Anthropic SDK path must never run."""
        def sdk(*a, **kw):
            self.sdk_calls.append(kw)
            raise AssertionError('install-wide Anthropic key used')
        from contextlib import ExitStack
        stack = ExitStack()
        for mod in ('reply_generator', 'action_generator', 'triage_generator'):
            stack.enter_context(patch(f'psa_ai.services.{mod}.Anthropic', side_effect=sdk, create=True))
        return stack

    def post(self, route):
        return self.c.post(f'/psa/ai/{route}/{self.ticket.ticket_number}/')

    def test_no_policy_means_no_model_call(self):
        with self._provider(REPLY), self._no_install_key_call():
            for route in ('generate-reply', 'generate-actions', 'triage'):
                self.post(route)
        self.assertEqual(self.calls, [])
        self.assertFalse(AISuggestion.objects.filter(review_state='draft').exists())

    def test_reply_goes_through_policy_profile_and_budget(self):
        p = _profile('Economy', self.org)
        self._policy(profiles=[p])
        with self._provider(REPLY), self._no_install_key_call():
            self.assertEqual(self.post('generate-reply').status_code, 302)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['profile'], p)
        s = AISuggestion.objects.get(native_ticket=self.ticket)
        self.assertEqual(s.review_state, 'draft')
        self.assertIn('test-model', s.model_name)
        self.assertGreater(AIBudgetDay.objects.get(organization=self.org).spent, 0)

    def test_excluded_customer_refused(self):
        p = _profile('Economy', self.org)
        self._policy(profiles=[p], ai_excluded=True)
        with self._provider(REPLY), self._no_install_key_call():
            self.post('generate-reply')
            self.post('triage')
        self.assertEqual(self.calls, [])

    def test_local_only_refuses_cloud_profile(self):
        p = _profile('Cloud', self.org)
        self._policy(profiles=[p], local_only=True)
        with self._provider(REPLY), self._no_install_key_call():
            self.post('generate-reply')
        self.assertEqual(self.calls, [])

    def test_budget_exhausted_refused(self):
        p = _profile('Economy', self.org)
        self._policy(profiles=[p], daily_budget_cents=0)
        with self._provider(REPLY), self._no_install_key_call():
            self.post('generate-reply')
        self.assertEqual(self.calls, [])

    def test_sharing_rules_apply_to_legacy_context(self):
        p = _profile('Economy', self.org)
        self._policy(profiles=[p])  # contact data and network identifiers off by default
        with self._provider(TRIAGE), self._no_install_key_call():
            self.post('triage')
        self.assertEqual(len(self.calls), 1)
        sent = self.calls[0]['user'] + self.calls[0]['system']
        self.assertNotIn('Pat Smith', sent)
        self.assertNotIn('10.0.0.12', sent)
        self.assertIn('printer', sent.lower())

    def test_ticket_text_withheld_refuses(self):
        p = _profile('Economy', self.org)
        self._policy(profiles=[p], share_ticket_text=False)
        with self._provider(REPLY), self._no_install_key_call():
            self.post('generate-reply')
        self.assertEqual(self.calls, [])
