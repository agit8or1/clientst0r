"""A form opened for one client is not saved under another.

The current client is per session, shared by every tab. form_guard.js stamps
POST forms with `_org_context` (the client the page was rendered for);
core.org_context_guard refuses a POST whose stamp no longer matches.
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Organization
from psa.models import Contract
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OrgContextGuardTests(TestCase):
    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.a = Organization.objects.create(name='Alpha Freight', slug='ocg-alpha')
        self.b = Organization.objects.create(name='Bravo Dental', slug='ocg-bravo')
        for org in (self.a, self.b):
            _enable_psa_for(org)
        self.admin = User.objects.create_superuser('ocg_admin', 'o@x.test', 'pw-ocg-123')
        self.c = Client()
        self.c.force_login(self.admin)
        self._switch(self.a)
        self.contract = Contract.objects.create(organization=self.a, client_org=self.a, name='Alpha MSA',
                                                status='active', start_date=date(2026, 1, 1))
        self.url = reverse('psa:contract_edit', kwargs={'pk': self.contract.pk})

    def _switch(self, org):
        s = self.c.session
        s['2fa_prompted'] = True
        if org is None:
            s.pop('current_organization_id', None)
            s['global_view_mode'] = True
        else:
            s['current_organization_id'] = org.pk
            s['global_view_mode'] = False
        s.save()

    def test_the_guard_is_installed(self):
        from django.conf import settings
        self.assertIn('core.org_context_guard.OrgContextGuardMiddleware', settings.MIDDLEWARE)

    def test_pages_carry_the_rendered_client_and_load_the_script(self):
        r = self.c.get(self.url)
        self.assertContains(r, f'data-org-context="{self.a.pk}"')
        self.assertContains(r, 'js/form_guard.js')

    def test_a_save_after_switching_client_elsewhere_is_refused(self):
        self._switch(self.b)  # another tab switched to Bravo
        r = self.c.post(self.url, {'name': 'Renamed', '_org_context': str(self.a.pk)})
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, 'opened for Alpha Freight', status_code=409)
        self.assertContains(r, 'switched to Bravo Dental', status_code=409)
        self.assertContains(r, reverse('accounts:switch_organization', args=[self.a.pk]), status_code=409)
        self.assertEqual(Contract.objects.get(pk=self.contract.pk).name, 'Alpha MSA')

    def test_a_save_in_the_same_client_goes_through(self):
        r = self.c.post(self.url, {'name': 'Renamed', '_org_context': str(self.a.pk)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Contract.objects.get(pk=self.contract.pk).name, 'Renamed')

    def test_a_post_without_the_stamp_is_not_affected(self):
        self._switch(self.b)
        r = self.c.post(self.url, {'name': 'Renamed'})
        self.assertEqual(r.status_code, 302)

    def test_a_form_opened_in_global_view_is_refused_after_picking_a_client(self):
        self._switch(self.b)
        r = self.c.post(self.url, {'name': 'Renamed', '_org_context': ''})
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, 'opened for Global View', status_code=409)

    def test_ajax_callers_get_json(self):
        self._switch(self.b)
        r = self.c.post(self.url, {'name': 'Renamed', '_org_context': str(self.a.pk)},
                        HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'org_context_changed')

    def test_a_client_the_user_cannot_see_is_not_named(self):
        customer = User.objects.create_user('ocg_cust', 'c@x.test', 'pw')
        from accounts.models import Membership, Role
        Membership.objects.create(user=customer, organization=self.b, role=Role.EDITOR, is_active=True)
        c = Client()
        c.force_login(customer)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.b.pk
        s.save()
        r = c.post('/accounts/profile/edit/', {'_org_context': str(self.a.pk)})
        self.assertEqual(r.status_code, 409)
        self.assertNotContains(r, 'Alpha Freight', status_code=409)
