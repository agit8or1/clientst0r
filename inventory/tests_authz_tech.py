"""Roles & permissions program (authz-tech): inventory is MSP-staff only.

Inventory records (stock levels, unit cost, reorder vendors, tools) are the
MSP's own operational data. Customer users, whatever their role, get 403 on
every /inventory/ page, on the mobile inventory endpoints and on the inventory
leg of the mobile code-scan resolver, and the Inventory sidebar section is
hidden for them. MSP staff (superuser or profile user type Staff) keep access,
still limited to the customers they belong to.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from api_mobile.models import MobileAuthToken
from api_mobile.tests import NO_THROTTLE_REST, TEST_MIDDLEWARE, _clear_throttle_cache, _make_msp_tech
from core.models import Organization
from inventory.access import is_inventory_staff
from inventory.models import InventoryCategory, InventoryItem, InventoryLocation, Tool

CUSTOMER_ROLES = (Role.OWNER, Role.ADMIN, Role.EDITOR, Role.READONLY)


class _Base(TestCase):

    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='Inv Authz', slug='inv-authz')
        self.item = InventoryItem.objects.create(
            organization=self.org, name='Patch cable', quantity=10, unit_cost='4.50')
        self.category = InventoryCategory.objects.create(organization=self.org, name='Cables')
        self.location = InventoryLocation.objects.create(organization=self.org, name='Shelf A')
        self.tool = Tool.objects.create(organization=self.org, name='Crimper')

    def customer(self, role):
        u = User.objects.create_user(f'inv-cust-{role}', password='pw')
        Membership.objects.create(user=u, organization=self.org, role=role, is_active=True)
        return u

    def tech(self):
        u = _make_msp_tech(User.objects.create_user('inv-tech', password='pw'))
        Membership.objects.create(user=u, organization=self.org, role=Role.EDITOR, is_active=True)
        return User.objects.get(pk=u.pk)

    def login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.pk
        s['2fa_prompted'] = True
        s.save()
        return c

    def web_urls(self):
        i, cat, loc, tool = self.item.pk, self.category.pk, self.location.pk, self.tool.pk
        return [
            reverse('inventory:inventory_dashboard'),
            reverse('inventory:item_list'),
            reverse('inventory:item_create'),
            reverse('inventory:item_detail', args=[i]),
            reverse('inventory:item_edit', args=[i]),
            reverse('inventory:item_delete', args=[i]),
            reverse('inventory:item_adjust', args=[i]),
            reverse('inventory:item_scan', args=[self.item.qr_code]),
            reverse('inventory:category_list'),
            reverse('inventory:category_create'),
            reverse('inventory:category_edit', args=[cat]),
            reverse('inventory:category_delete', args=[cat]),
            reverse('inventory:location_list'),
            reverse('inventory:location_create'),
            reverse('inventory:location_edit', args=[loc]),
            reverse('inventory:location_delete', args=[loc]),
            reverse('inventory:tool_list'),
            reverse('inventory:tool_create'),
            reverse('inventory:tool_edit', args=[tool]),
            reverse('inventory:tool_delete', args=[tool]),
            reverse('inventory:transaction_list'),
            reverse('inventory:low_stock_report'),
        ]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InventoryWebTests(_Base):

    def test_every_inventory_url_is_covered(self):
        from inventory.urls import urlpatterns
        self.assertEqual(len(self.web_urls()), len(urlpatterns))

    def test_customer_users_get_403_on_every_page(self):
        for role in CUSTOMER_ROLES:
            c = self.login(self.customer(role))
            for url in self.web_urls():
                with self.subTest(role=role, url=url):
                    self.assertEqual(c.get(url).status_code, 403)

    def test_customer_admin_cannot_write(self):
        c = self.login(self.customer(Role.ADMIN))
        self.assertEqual(c.post(reverse('inventory:item_delete', args=[self.item.pk])).status_code, 403)
        self.assertEqual(c.post(reverse('inventory:item_adjust', args=[self.item.pk]),
                                {'transaction_type': 'stock_out', 'quantity_change': 10}).status_code, 403)
        self.assertEqual(c.post(reverse('inventory:item_create'), {'name': 'x'}).status_code, 403)
        self.assertTrue(InventoryItem.objects.filter(pk=self.item.pk, quantity=10).exists())
        self.assertFalse(InventoryItem.objects.filter(name='x').exists())

    def test_unit_cost_not_shown_to_customer(self):
        c = self.login(self.customer(Role.OWNER))
        r = c.get(reverse('inventory:item_detail', args=[self.item.pk]))
        self.assertNotContains(r, '4.50', status_code=403)

    def test_staff_and_superuser_keep_access(self):
        su = User.objects.create_superuser('inv-su', 'su@x.com', 'pw')
        for user in (self.tech(), su):
            c = self.login(user)
            for name, args in (('inventory:inventory_dashboard', []), ('inventory:item_list', []),
                               ('inventory:item_detail', [self.item.pk]),
                               ('inventory:low_stock_report', []), ('inventory:tool_list', [])):
                with self.subTest(user=user.username, name=name):
                    self.assertEqual(c.get(reverse(name, args=args)).status_code, 200)

    def test_anonymous_is_sent_to_login(self):
        r = Client().get(reverse('inventory:item_list'))
        self.assertEqual(r.status_code, 302)

    def test_helper(self):
        self.assertFalse(is_inventory_staff(self.customer(Role.OWNER)))
        self.assertTrue(is_inventory_staff(self.tech()))
        self.assertFalse(is_inventory_staff(None))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class InventoryMobileTests(_Base):

    def get(self, user, path):
        token, _ = MobileAuthToken.issue(user)
        return Client().get(path, HTTP_AUTHORIZATION=f'Token {token}')

    def paths(self):
        return ['/api/mobile/v1/inventory/', f'/api/mobile/v1/inventory/{self.item.pk}/',
                f'/api/mobile/v1/inventory/{self.item.pk}/transactions/']

    def test_customer_users_get_403(self):
        for role in CUSTOMER_ROLES:
            user = self.customer(role)
            for path in self.paths():
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.get(user, path).status_code, 403)

    def test_customer_admin_cannot_adjust_stock(self):
        import json
        token, _ = MobileAuthToken.issue(self.customer(Role.ADMIN))
        r = Client().post(f'/api/mobile/v1/inventory/{self.item.pk}/transactions/',
                          data=json.dumps({'transaction_type': 'stock_out', 'quantity_change': 3}),
                          content_type='application/json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(r.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)

    def test_staff_keep_access_with_unit_cost(self):
        tech = self.tech()
        for path in self.paths():
            with self.subTest(path=path):
                self.assertEqual(self.get(tech, path).status_code, 200)
        self.assertEqual(self.get(tech, self.paths()[1]).json()['unit_cost'], '4.50')

    def test_staff_still_limited_to_their_customers(self):
        other = Organization.objects.create(name='Inv Other', slug='inv-other')
        foreign = InventoryItem.objects.create(organization=other, name='Foreign', quantity=1)
        r = self.get(self.tech(), f'/api/mobile/v1/inventory/{foreign.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_scan_skips_inventory_for_customers(self):
        code = self.item.qr_code
        r = self.get(self.customer(Role.OWNER), f'/api/mobile/v1/scan/?code={code}')
        self.assertEqual(r.status_code, 404)
        r = self.get(self.tech(), f'/api/mobile/v1/scan/?code={code}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['kind'], 'inventory')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InventoryNavTests(_Base):

    def setUp(self):
        super().setUp()
        from core.models import SystemSetting
        row = SystemSetting.get_settings()
        row.inventory_enabled = True
        row.save()

    def sidebar(self, user):
        r = self.login(user).get(reverse('core:dashboard'), follow=True)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_customer_sidebar_has_no_inventory(self):
        href = f'href="{reverse("inventory:inventory_dashboard")}"'
        for role in (Role.OWNER, Role.READONLY):
            with self.subTest(role=role):
                self.assertNotIn(href, self.sidebar(self.customer(role)))

    def test_staff_sidebar_keeps_inventory(self):
        href = f'href="{reverse("inventory:inventory_dashboard")}"'
        self.assertIn(href, self.sidebar(self.tech()))
