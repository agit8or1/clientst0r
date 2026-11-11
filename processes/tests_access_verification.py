"""Phase 38 — access removal verification for offboarding runs.

Microsoft Graph is mocked (a fake provider, or requests patched at the
HTTP layer); nothing talks to a real tenant or RMM."""
from __future__ import annotations

from unittest import mock

import requests
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, UserProfile, UserType
from api.models import APIKey
from audit.models import AuditLog
from core.models import Organization
from integrations.models import M365Connection, RMMConnection
from integrations.providers.m365 import M365Provider
from processes import access_verification
from processes.models import AccessRemovalCheck, Process, ProcessExecution, ProcessExecutionAuditLog
from vault.models import Password

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


class FakeGraph:
    def __init__(self, user=None, error=None):
        self.user, self.error, self.calls = user, error, []

    def get_user_access(self, sign_in):
        self.calls.append(sign_in)
        if self.error:
            raise self.error
        return self.user


def _staff(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.user_type = UserType.STAFF
    profile.save()
    user.profile = profile
    return user


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Leaver Co', slug='leaver-co')
        self.other = Organization.objects.create(name='Other Co', slug='other-co')
        self.tech = _staff(User.objects.create_user('tech', 'tech@msp.test', 'pw'))
        self.leaver = User.objects.create_user('jane', 'jane@leaver.test', 'pw')
        self.process = Process.objects.create(organization=self.org, title='Employee offboarding',
                                              category='offboarding', created_by=self.tech)
        self.execution = ProcessExecution.objects.create(process=self.process, organization=self.org,
                                                         assigned_to=self.tech, subject_email='jane@leaver.test')

    def by_system(self, rows):
        return {r.system: r for r in rows}


class ClientSt0rCheckTests(Base):
    def test_orphaned_access_is_listed(self):
        Membership.objects.create(user=self.leaver, organization=self.org, role=Role.READONLY, is_active=True)
        pw = Password.objects.create(organization=self.org, title='Shared wifi', created_by=self.tech)
        pw.client_allowed_users.add(self.leaver)
        APIKey.create_key(self.org, self.leaver, 'script')
        # Access to another customer is not this run's business.
        APIKey.create_key(self.other, self.leaver, 'elsewhere')
        rows = access_verification.verify(self.execution, self.tech, m365_provider_factory=lambda c: FakeGraph())
        cs = self.by_system(rows)['clientst0r']
        self.assertEqual(cs.status, 'orphaned')
        active = {f['item'] for f in cs.findings if f['state'] == 'active'}
        # A customer user's membership is their portal sign-in.
        self.assertIn('Portal sign-in: Leaver Co', active)
        self.assertIn('Vault items shared to them', active)
        self.assertIn('API keys', active)
        keys = next(f for f in cs.findings if f['item'] == 'API keys')['detail']
        self.assertEqual(keys.count('…'), 1)

    def test_removed_when_everything_is_gone(self):
        Membership.objects.create(user=self.leaver, organization=self.org, role=Role.READONLY, is_active=False)
        key, _ = APIKey.create_key(self.org, self.leaver, 'old')
        key.is_active = False
        key.save()
        rows = access_verification.verify(self.execution, self.tech, m365_provider_factory=lambda c: FakeGraph())
        cs = self.by_system(rows)['clientst0r']
        self.assertEqual(cs.status, 'removed', cs.findings)

    def test_no_account_and_no_subject(self):
        self.execution.subject_email = 'nobody@leaver.test'
        rows = access_verification.check_clientst0r(self.execution)
        self.assertEqual(rows[0]['status'], 'removed')
        self.execution.subject_email = ''
        rows = access_verification.check_clientst0r(self.execution)
        self.assertEqual(rows[0]['status'], 'not_verifiable')

    def test_run_is_audited(self):
        access_verification.verify(self.execution, self.tech, m365_provider_factory=lambda c: FakeGraph())
        self.assertTrue(ProcessExecutionAuditLog.objects.filter(execution=self.execution,
                                                                action_type='access_verified').exists())
        self.assertTrue(AuditLog.objects.filter(object_type='process_execution', object_id=self.execution.pk,
                                                description__contains='Verified access removal').exists())


class M365CheckTests(Base):
    def setUp(self):
        super().setUp()
        self.conn = M365Connection.objects.create(organization=self.org, name='Tenant', tenant_id='t-1')
        self.conn.set_credentials({'client_id': 'c', 'client_secret': 's'})
        self.conn.save()

    def check(self, graph):
        return access_verification.check_m365(self.execution, provider_factory=lambda c: graph)[0]

    def test_enabled_and_licensed_is_orphaned(self):
        graph = FakeGraph({'userPrincipalName': 'jane@leaver.test', 'accountEnabled': True,
                           'assignedLicenses': [{'skuId': 'x'}]})
        r = self.check(graph)
        self.assertEqual(r['status'], 'orphaned')
        self.assertEqual(graph.calls, ['jane@leaver.test'])

    def test_blocked_and_unlicensed_is_removed(self):
        r = self.check(FakeGraph({'accountEnabled': False, 'assignedLicenses': []}))
        self.assertEqual(r['status'], 'removed')

    def test_licences_left_on_blocked_user_is_orphaned(self):
        r = self.check(FakeGraph({'accountEnabled': False, 'assignedLicenses': [{'skuId': 'x'}]}))
        self.assertEqual(r['status'], 'orphaned')
        self.assertIn('licenses', r['summary'])

    def test_deleted_user_is_removed(self):
        self.assertEqual(self.check(FakeGraph(None))['status'], 'removed')

    def test_graph_error_is_recorded(self):
        r = self.check(FakeGraph(error=RuntimeError('boom')))
        self.assertEqual(r['status'], 'error')

    def test_no_connection_is_not_verifiable(self):
        self.conn.is_active = False
        self.conn.save()
        r = access_verification.check_m365(self.execution)[0]
        self.assertEqual(r['status'], 'not_verifiable')

    def test_provider_only_issues_get_requests(self):
        """get_user_access at the HTTP layer: GETs only, 404 falls back to
        a mail lookup."""
        def fake_get(url, headers=None, params=None, timeout=None):
            resp = mock.Mock()
            if '/users/' in url:
                resp.status_code = 404
                resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
            else:
                resp.status_code = 200
                resp.raise_for_status.return_value = None
                resp.json.return_value = {'value': [{'accountEnabled': False, 'assignedLicenses': []}]}
            return resp
        provider = M365Provider('t', 'c', 's')
        provider._token = 'tok'
        with mock.patch('integrations.providers.m365.requests.get', side_effect=fake_get) as get, \
                mock.patch('integrations.providers.m365.requests.post') as post, \
                mock.patch('integrations.providers.m365.requests.patch') as patch:
            user = provider.get_user_access("o'brien@leaver.test")
        self.assertEqual(user['accountEnabled'], False)
        self.assertEqual(get.call_count, 2)
        self.assertIn("o''brien@leaver.test", get.call_args_list[1].kwargs['params']['$filter'])
        post.assert_not_called()
        patch.assert_not_called()


class RMMCheckTests(Base):
    def test_rmm_is_not_verifiable(self):
        RMMConnection.objects.create(organization=self.org, name='RMM', provider_type='ninjaone',
                                     base_url='https://rmm.test')
        rows = access_verification.check_rmm(self.execution)
        self.assertEqual(rows[0]['status'], 'not_verifiable')
        self.assertIn('by hand', rows[0]['summary'])

    def test_no_rmm_no_row(self):
        self.assertEqual(access_verification.check_rmm(self.execution), [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AccessVerificationViewTests(Base):
    def login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def test_tech_sets_subject_and_runs_checks(self):
        Membership.objects.create(user=self.tech, organization=self.org, role=Role.ADMIN, is_active=True)
        Membership.objects.create(user=self.leaver, organization=self.org, role=Role.READONLY, is_active=True)
        c = self.login(self.tech)
        url = f'/processes/execution/{self.execution.pk}/access-verification/'
        resp = c.post(url, {'action': 'subject', 'subject_email': 'jane@leaver.test'})
        self.assertEqual(resp.status_code, 302)
        resp = c.post(url, {'action': 'verify'})
        self.assertEqual(resp.status_code, 302)
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Orphaned access')
        self.assertContains(resp, 'Portal sign-in: Leaver Co')
        self.assertTrue(AccessRemovalCheck.objects.filter(execution=self.execution, system='clientst0r',
                                                          status='orphaned').exists())

    def test_customer_user_cannot_see_it(self):
        Membership.objects.create(user=self.leaver, organization=self.org, role=Role.ADMIN, is_active=True)
        c = self.login(self.leaver)
        resp = c.get(f'/processes/execution/{self.execution.pk}/access-verification/')
        self.assertEqual(resp.status_code, 404)

    def test_other_customers_execution_is_404(self):
        Membership.objects.create(user=self.tech, organization=self.org, role=Role.ADMIN, is_active=True)
        other_proc = Process.objects.create(organization=self.other, title='Other offboarding',
                                            category='offboarding', created_by=self.tech)
        other_ex = ProcessExecution.objects.create(process=other_proc, organization=self.other,
                                                   assigned_to=self.tech)
        c = self.login(self.tech)
        resp = c.post(f'/processes/execution/{other_ex.pk}/access-verification/', {'action': 'verify'})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(AccessRemovalCheck.objects.exists())
