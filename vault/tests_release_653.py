"""v3.17.653: vault titles stay inside the customers a technician is assigned
to, and the offline cache holds no secret whose reveal needs a live check."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from accounts.permission_utils import orgs_with_perm
from audit.models import AuditLog
from core.models import Organization
from psa.tests._base import _make_msp_tech
from vault.access_rules import ONLINE_ONLY_MESSAGE
from vault.models import Password, VaultAccessRule, WebExtensionAuthToken
from vault.permissions import visible_passwords
from vault.tests_extension_gate import TEST_MIDDLEWARE


class _Customers(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Example Accounting', slug='ex-acct-653')
        cls.b = Organization.objects.create(name='Example Clinic', slug='ex-clinic-653')
        cls.see_only = RoleTemplate.objects.create(name='See vault, no reveal', vault_view=True,
                                                   vault_view_password=False)
        cls.reveal = RoleTemplate.objects.create(name='See and reveal', vault_view=True, vault_view_password=True)
        cls.everywhere = RoleTemplate.objects.create(name='Global vault', vault_view=True,
                                                     vault_view_password=True)
        # A technician assigned only to Customer A, with no global role.
        cls.tech = _make_msp_tech(User.objects.create_user('tech-a', 'a@msp.test', 'pw-653-tech!'))
        Membership.objects.create(user=cls.tech, organization=cls.a, role=Role.READONLY,
                                  role_template=cls.see_only, is_active=True)
        # A technician explicitly given every customer by a global role.
        cls.global_tech = _make_msp_tech(User.objects.create_user('tech-all', 'g@msp.test', 'pw-653-tech!'))
        cls.global_tech.profile.global_role_template = cls.everywhere
        cls.global_tech.profile.save()
        cls.su = User.objects.create_superuser('su-653', 'su@msp.test', 'pw-653-su!')
        cls.wifi = Password.objects.create(organization=cls.a, title='Office Wi-Fi', username='frontdesk')
        cls.gated = Password.objects.create(organization=cls.a, title='Domain admin',
                                            requires_reveal_approval=True)
        cls.payroll = Password.objects.create(organization=cls.b, title='Payroll Administrator',
                                              username='payroll')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TitleVisibilityTests(_Customers):
    def setUp(self):
        cache.clear()

    def _global_view(self, user):
        self.client.force_login(user)
        s = self.client.session
        s['global_view_mode'] = True
        s.pop('current_organization_id', None)
        s.save()

    def test_scope_follows_memberships_unless_a_global_role_grants_it(self):
        self.assertEqual(orgs_with_perm(self.tech, 'vault_view'), {self.a.pk})
        self.assertEqual(orgs_with_perm(self.tech, 'vault_view_password'), set())
        self.assertIsNone(orgs_with_perm(self.global_tech, 'vault_view'))
        self.assertIsNone(orgs_with_perm(self.su, 'vault_view'))
        # Outside the vault, staff without a global role keep their reach.
        self.assertIsNone(orgs_with_perm(self.tech, 'docs_view'))

    def test_vault_list_and_counts_leave_out_other_customers(self):
        self._global_view(self.tech)
        data = self.client.get(reverse('vault:password_list_datatables')).json()
        text = str(data)
        self.assertIn('Office Wi-Fi', text)
        self.assertNotIn('Payroll Administrator', text)
        self.assertEqual(data['recordsTotal'], 2)
        searched = self.client.get(reverse('vault:password_list_datatables'), {'search[value]': 'Payroll'}).json()
        self.assertEqual(searched['recordsFiltered'], 0)

    def test_global_tech_and_superuser_still_see_every_customer(self):
        for user in (self.global_tech, self.su):
            with self.subTest(user.username):
                self._global_view(user)
                data = self.client.get(reverse('vault:password_list_datatables')).json()
                self.assertIn('Payroll Administrator', str(data))
                self.assertEqual(data['recordsTotal'], 3)

    def test_other_customer_entry_by_direct_url_is_not_found(self):
        self._global_view(self.tech)
        self.assertEqual(self.client.get(reverse('vault:password_detail', args=[self.payroll.pk])).status_code, 404)

    def test_selecting_the_other_customer_is_refused(self):
        self.client.force_login(self.tech)
        s = self.client.session
        s['current_organization_id'] = self.b.pk
        s.save()
        self.assertEqual(self.client.get(reverse('vault:password_list')).status_code, 403)

    def test_global_search_leaves_out_other_customers(self):
        self._global_view(self.tech)
        html = self.client.get(reverse('core:search'), {'q': 'Payroll'}).content.decode()
        self.assertNotIn('Payroll Administrator', html)
        html = self.client.get(reverse('core:search'), {'q': 'Wi-Fi'}).content.decode()
        self.assertIn('Office Wi-Fi', html)

    def test_mobile_and_shared_helper_agree(self):
        from api_mobile.views_vault import _visible_passwords
        mobile = set(_visible_passwords(self.tech).values_list('pk', flat=True))
        shared = set(visible_passwords(self.tech).values_list('pk', flat=True))
        self.assertEqual(mobile, {self.wifi.pk, self.gated.pk})
        self.assertEqual(shared, mobile)

    def test_rest_api_lists_only_assigned_customers(self):
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(self.tech)
        resp = api.get('/api/passwords/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Payroll Administrator', resp.content.decode())

    def test_extension_without_a_customer_lists_only_assigned_customers(self):
        secret, _ = WebExtensionAuthToken.issue(user=self.tech, organization=None)
        with patch('vault.extension_views._has_extension_permission', return_value=True):
            resp = Client().get('/vault/api/extension/sync/', HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r['id'] for r in resp.json()['passwords']}, {self.wifi.pk, self.gated.pk})

    def test_process_stage_picker_offers_only_visible_entries(self):
        from processes.forms import ProcessStageForm
        global_form = ProcessStageForm(user=self.tech)
        self.assertEqual(set(global_form.fields['linked_password'].queryset), {self.wifi, self.gated})
        other = ProcessStageForm(user=self.tech, organization=self.b)
        self.assertFalse(other.fields['linked_password'].queryset.exists())
        self.assertFalse(ProcessStageForm().fields['linked_password'].queryset.exists())

    def test_linked_titles_elsewhere_are_checked_where_shown(self):
        from vault.templatetags.vault_access import vault_visible
        self.assertTrue(vault_visible(self.wifi, self.tech))
        self.assertFalse(vault_visible(self.payroll, self.tech))
        self.assertTrue(vault_visible(self.payroll, self.global_tech))

    def test_seeing_an_entry_is_separate_from_revealing_it(self):
        self.client.force_login(self.tech)
        s = self.client.session
        s['current_organization_id'] = self.a.pk
        s.save()
        self.assertEqual(self.client.get(reverse('vault:password_detail', args=[self.gated.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('vault:password_reveal', args=[self.wifi.pk])).status_code, 403)

    def test_a_tech_who_may_reveal_finds_and_requests_an_approval_gated_entry(self):
        Membership.objects.filter(user=self.tech, organization=self.a).update(role_template=self.reveal)
        self.client.force_login(self.tech)
        s = self.client.session
        s['current_organization_id'] = self.a.pk
        s.save()
        self.assertIn('Domain admin', str(self.client.get(reverse('vault:password_list_datatables')).json()))
        resp = self.client.post(reverse('vault:password_request_reveal', args=[self.gated.pk]),
                                {'justification': 'Rotating the service account'})
        self.assertIn(resp.status_code, (200, 201))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VisibilityReportTests(_Customers):
    def test_report_lists_who_lost_cross_customer_visibility(self):
        from core.settings_views import vault_visibility_changes
        rows = {r['user'].username: r for r in vault_visibility_changes()}
        self.assertEqual(set(rows), {'tech-a'})
        self.assertEqual(rows['tech-a']['lost'], ['Example Clinic'])
        self.assertEqual(rows['tech-a']['keeps'], ['Example Accounting'])
        self.assertEqual(rows['tech-a']['entries_lost'], 1)

    def test_report_page_is_superuser_only_and_grants_nothing(self):
        self.client.force_login(self.su)
        html = self.client.get(reverse('core:vault_visibility')).content.decode()
        self.assertIn('tech-a', html)
        self.assertIn('Example Clinic', html)
        self.assertEqual(orgs_with_perm(self.tech, 'vault_view'), {self.a.pk})
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse('core:vault_visibility')).status_code, 403)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OfflineCacheRestrictionTests(_Customers):
    def setUp(self):
        cache.clear()
        self.wifi.set_password('synthetic-wifi-pass')
        self.wifi.save()
        # The extension sync no longer hands out ciphertext the user may not
        # reveal (authz-tech), so this technician needs reveal rights at A.
        Membership.objects.filter(user=self.tech, organization=self.a).update(role_template=self.reveal)
        self.secret, _ = WebExtensionAuthToken.issue(user=self.tech, organization=self.a)

    def _sync(self):
        with patch('vault.extension_views._has_extension_permission', return_value=True):
            resp = Client().get('/vault/api/extension/sync/', HTTP_AUTHORIZATION=f'Bearer {self.secret}')
        self.assertEqual(resp.status_code, 200)
        return resp.json(), {r['id']: r for r in resp.json()['passwords']}

    def _rule(self, **kw):
        kw.setdefault('scope', 'organization')
        kw.setdefault('allowed_countries', ['US'])
        return VaultAccessRule.objects.create(organization=self.a, name='US only', effect='allow', **kw)

    def test_entry_cached_yesterday_and_restricted_today_loses_its_cached_secret(self):
        body, day1 = self._sync()
        self.assertTrue(day1[self.wifi.pk]['encrypted_password'])
        self.assertFalse(day1[self.wifi.pk]['online_only'])
        self.assertEqual(body['cache_policy'], 'replace')
        self._rule()  # today the customer's entries need a country check
        _, day2 = self._sync()
        row = day2[self.wifi.pk]
        self.assertIsNone(row['encrypted_password'])
        self.assertTrue(row['online_only'])
        self.assertEqual(row['message'], ONLINE_ONLY_MESSAGE)
        self.assertEqual(ONLINE_ONLY_MESSAGE, 'Connect to ClientSt0r to reveal this password.')
        self.assertFalse(row['totp_available'])
        self.assertEqual(AuditLog.objects.filter(extra_data__event='vault_extension_sync').order_by('-pk')
                         .first().extra_data['online_only'], 2)

    def test_entry_made_approval_gated_today_loses_its_cached_secret(self):
        _, day1 = self._sync()
        self.assertTrue(day1[self.wifi.pk]['encrypted_password'])
        Password.objects.filter(pk=self.wifi.pk).update(requires_reveal_approval=True)
        _, day2 = self._sync()
        self.assertIsNone(day2[self.wifi.pk]['encrypted_password'])
        self.assertTrue(day2[self.wifi.pk]['online_only'])

    def test_item_address_and_time_rules_each_make_an_entry_online_only(self):
        from datetime import time
        for kw in ({'scope': 'item', 'target_password': self.wifi},
                   {'allowed_cidrs': ['10.0.0.0/8'], 'allowed_countries': []},
                   {'allowed_hour_start': time(8), 'allowed_hour_end': time(18), 'allowed_countries': []}):
            with self.subTest(kw):
                rule = self._rule(**kw)
                _, rows = self._sync()
                self.assertIsNone(rows[self.wifi.pk]['encrypted_password'])
                rule.delete()

    def test_rule_on_this_user_applies_and_rule_on_someone_else_does_not(self):
        rule = self._rule(scope='user', target_user=self.global_tech)
        _, rows = self._sync()
        self.assertTrue(rows[self.wifi.pk]['encrypted_password'])
        rule.target_user = self.tech
        rule.save()
        _, rows = self._sync()
        self.assertIsNone(rows[self.wifi.pk]['encrypted_password'])

    def test_inactive_rules_and_other_customers_rules_do_not_restrict(self):
        self._rule(is_active=False)
        VaultAccessRule.objects.create(organization=self.b, name='Clinic', scope='organization',
                                       effect='deny')
        _, rows = self._sync()
        self.assertTrue(rows[self.wifi.pk]['encrypted_password'])
