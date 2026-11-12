"""Roles & permissions program (authz-tech): integrations enforcement.

* Inside a customer, the role flag for the level is checked
  (integrations_configure to manage, integrations_sync to test/sync), not
  only Owner/Admin or "any *_create flag".
* UniFi / M365 / Omada / Grandstream test and sync no longer change state on GET.
* Synced PSA companies, contacts and tickets are MSP-staff only.
* A technician's cross-customer UniFi lookup needs the flag at that customer.
* RMM devices of a customer's own connection can only be placed within that
  customer.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech

from .models import RMMConnection, RMMDevice
from .tests_platform_ownership import _rmm, _unifi


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class IntegrationFlagTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Int A', slug='authz-int-a')
        self.other = Organization.objects.create(name='Int B', slug='authz-int-b')
        self.unifi = _unifi(self.org)
        self.unifi_b = _unifi(self.other, name='B controller')
        self.c = Client()

    def _member(self, role, template=None):
        u = User.objects.create_user(f'authz-int-{role}-{User.objects.count()}', password='pw')
        Membership.objects.create(user=u, organization=self.org, role=role, role_template=template)
        _login(self.c, u, self.org)
        return u

    def test_sync_needs_post(self):
        self._member(Role.OWNER)
        url = reverse('integrations:unifi_sync', args=[self.unifi.pk])
        self.assertEqual(self.c.get(url).status_code, 405)

    def test_editor_without_integrations_sync_cannot_sync(self):
        # Built-in Editor: integrations_sync is off (it passed require_write).
        self._member(Role.EDITOR)
        with mock.patch('integrations.views._get_unifi_provider') as gp:
            resp = self.c.post(reverse('integrations:unifi_sync', args=[self.unifi.pk]))
        self.assertEqual(resp.status_code, 403)
        gp.assert_not_called()

    def test_admin_template_without_configure_cannot_edit(self):
        role = RoleTemplate.objects.create(name='authz int no configure', integrations_view=True,
                                           integrations_configure=False, org_manage_settings=True)
        self._member(Role.ADMIN, role)
        resp = self.c.get(reverse('integrations:unifi_edit', args=[self.unifi.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_customer_user_cannot_read_synced_psa_data(self):
        self._member(Role.OWNER)
        for name in ('psa_companies', 'psa_contacts', 'psa_tickets'):
            with self.subTest(name):
                self.assertEqual(self.c.get(reverse(f'integrations:{name}')).status_code, 403)

    def test_tech_cross_customer_unifi_needs_flag_there(self):
        viewer = RoleTemplate.objects.create(name='authz int tech no b', integrations_view=False)
        tech = _make_msp_tech(User.objects.create_user('authz-int-tech', password='pw'))
        tech.profile.global_role_template = viewer
        tech.profile.save()
        Membership.objects.create(user=tech, organization=self.org, role=Role.ADMIN)
        _login(self.c, tech, self.org)
        from integrations.views import _get_unifi_connection
        from django.http import Http404
        req = mock.Mock(user=tech, is_staff_user=True, current_organization=self.org)
        with mock.patch('integrations.views.get_request_organization', return_value=self.org):
            with self.assertRaises(Http404):
                _get_unifi_connection(req, self.unifi_b.pk, 'write')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RMMAssignScopeTests(TestCase):
    def test_customer_connection_devices_stay_in_that_customer(self):
        org = Organization.objects.create(name='RMM A', slug='authz-rmm-a')
        other = Organization.objects.create(name='RMM B', slug='authz-rmm-b')
        conn = _rmm(org, customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        device = RMMDevice.objects.create(connection=conn, external_id='d1', device_name='pc-1')
        su = User.objects.create_superuser('authz-rmm-su', 'su@x.test', 'pw')
        c = Client()
        _login(c, su, org)
        resp = c.post(reverse('integrations:rmm_device_decide', args=[device.pk]),
                      {'action': 'assign_customer', 'organization': other.pk})
        self.assertEqual(resp.status_code, 403)
        device.refresh_from_db()
        self.assertNotEqual(device.organization_id, other.pk)
