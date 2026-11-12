"""Roles & permissions program (authz-tech): mobile API enforcement.

Writes check the flag in the record's own customer (not "any membership"),
Read-Only members cannot create assets or adjust stock, customer users get
neither time entries nor the service fleet, a new password ends every mobile
session, required 2FA cannot be skipped through the mobile login, and push
devices cannot be taken over by a known device id.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from api_mobile.models import MobileAuthToken
from field_ops.models import MobileDevice
from api_mobile.tests import NO_THROTTLE_REST, TEST_MIDDLEWARE, _clear_throttle_cache, _make_msp_tech
from assets.models import Asset
from core.models import Organization


def _auth(client, method, path, token, data=None):
    import json
    kwargs = {'HTTP_AUTHORIZATION': f'Token {token}'}
    if data is not None:
        kwargs.update(data=json.dumps(data), content_type='application/json')
    return getattr(client, method)(path, **kwargs)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileWriteScopeTests(TestCase):
    def setUp(self):
        _clear_throttle_cache()
        self.a = Organization.objects.create(name='Mob A', slug='authz-mob-a')
        self.b = Organization.objects.create(name='Mob B', slug='authz-mob-b')
        self.user = User.objects.create_user('authz-mob-user', password='pw')
        Membership.objects.create(user=self.user, organization=self.a, role=Role.EDITOR)
        Membership.objects.create(user=self.user, organization=self.b, role=Role.READONLY)
        self.asset_b = Asset.objects.create(organization=self.b, name='B server', asset_type='server')
        self.token, _ = MobileAuthToken.issue(self.user)
        self.c = Client()

    def test_edit_flag_from_one_customer_does_not_edit_another(self):
        resp = _auth(self.c, 'patch', f'/api/mobile/v1/assets/{self.asset_b.pk}/', self.token,
                     {'name': 'renamed'})
        self.assertEqual(resp.status_code, 403)
        self.asset_b.refresh_from_db()
        self.assertEqual(self.asset_b.name, 'B server')

    def test_readonly_member_cannot_create_asset(self):
        resp = _auth(self.c, 'post', '/api/mobile/v1/assets/', self.token,
                     {'organization_id': self.b.pk, 'name': 'new', 'asset_type': 'server'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Asset.objects.filter(name='new').exists())

    def test_readonly_member_cannot_adjust_stock(self):
        from inventory.models import InventoryItem
        item = InventoryItem.objects.create(organization=self.b, name='Cable', quantity=5)
        resp = _auth(self.c, 'post', f'/api/mobile/v1/inventory/{item.pk}/transactions/', self.token,
                     {'transaction_type': 'stock_out', 'quantity_change': 5})
        self.assertEqual(resp.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)

    def test_customer_user_gets_no_fleet_and_no_time_entries(self):
        self.assertEqual(_auth(self.c, 'get', '/api/mobile/v1/vehicles/', self.token).status_code, 403)
        from psa.models import Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType, Queue
        from psa.tests._base import _setup_seed
        _setup_seed()
        ticket = Ticket.objects.create(
            organization=self.a, subject='Printer', client_can_view=True,
            status=TicketStatus.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), queue=Queue.objects.first())
        self.assertEqual(_auth(self.c, 'get', f'/api/mobile/v1/tickets/{ticket.pk}/time/',
                               self.token).status_code, 403)
        resp = _auth(self.c, 'post', f'/api/mobile/v1/tickets/{ticket.pk}/time/', self.token,
                     {'duration_minutes': 100000})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(TicketTimeEntry.objects.filter(ticket=ticket).exists())

    def test_password_change_revokes_mobile_tokens(self):
        self.assertEqual(_auth(self.c, 'get', '/api/mobile/v1/auth/me/', self.token).status_code, 200)
        self.user.set_password('a-new-password-1!')
        self.user.save()
        self.assertEqual(_auth(self.c, 'get', '/api/mobile/v1/auth/me/', self.token).status_code, 401)

    def test_hash_upgrade_save_does_not_revoke(self):
        self.user.save(update_fields=['password'])
        self.assertEqual(_auth(self.c, 'get', '/api/mobile/v1/auth/me/', self.token).status_code, 200)

    def test_known_device_id_is_not_taken_over(self):
        victim = User.objects.create_user('authz-mob-victim', password='pw')
        dev = MobileDevice.objects.create(user=victim, device_id=uuid.uuid4(), platform='ios',
                                          expo_push_token='ExponentPushToken[victim]')
        resp = _auth(self.c, 'post', '/api/mobile/v1/notifications/register/', self.token,
                     {'device_id': str(dev.device_id), 'platform': 'ios',
                      'token': 'ExponentPushToken[attacker]'})
        self.assertIn(resp.status_code, (200, 201))
        dev.refresh_from_db()
        self.assertEqual(dev.user_id, victim.pk)
        self.assertEqual(dev.expo_push_token, 'ExponentPushToken[victim]')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileLogin2FAPolicyTests(TestCase):
    def setUp(self):
        _clear_throttle_cache()
        self.user = User.objects.create_user('authz-mob-2fa', password='pw-authz-2fa!')

    def _login(self):
        import json
        return Client().post('/api/mobile/v1/auth/login/',
                             data=json.dumps({'username': 'authz-mob-2fa', 'password': 'pw-authz-2fa!'}),
                             content_type='application/json')

    def test_required_2fa_without_device_gets_no_token(self):
        with mock.patch('core.security_policy.require_2fa', return_value=True):
            resp = self._login()
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.json().get('mfa_enrollment_required'))
        self.assertFalse(MobileAuthToken.objects.filter(user=self.user).exists())

    def test_optional_2fa_still_issues_token(self):
        with mock.patch('core.security_policy.require_2fa', return_value=False):
            resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.json())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileStaffOnlyTests(TestCase):
    def test_msp_tech_keeps_the_fleet(self):
        _clear_throttle_cache()
        tech = _make_msp_tech(User.objects.create_user('authz-mob-tech', password='pw'))
        token, _ = MobileAuthToken.issue(tech)
        self.assertEqual(_auth(Client(), 'get', '/api/mobile/v1/vehicles/', token).status_code, 200)
