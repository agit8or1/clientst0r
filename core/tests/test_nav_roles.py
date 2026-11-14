"""Per-role navigation: nothing drawn that the server would refuse.

For seven kinds of user — superuser, MSP technician with no role, technician
with the RMM L1 role, Sales Representative, organization Owner (not a
superuser), Customer Administrator and Customer Standard User — render the
dashboard, collect every link the frame draws (sidebar, top-bar shortcuts,
account menu, bell, and the settings workspace when the user has one) and
open each. None may answer 403: hiding a link is presentation, but drawing
one the page refuses is a broken promise. Customers additionally get no
Reports or Administration group and no staff-only destination anywhere.
"""
import re

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate, UserType
from core.tests.test_navbar_grouping import STAFF_ONLY, TEST_MIDDLEWARE, NavbarTestBase, sidebar

User = get_user_model()


def builtin(key):
    return RoleTemplate.objects.get(seed_key=key, organization__isnull=True)


def frame_links(html):
    """Every same-site link drawn by the frame (not the page content)."""
    head = html.split('id="main-content"', 1)[0]
    ws = re.search(r'<nav class="settings-ws"[^>]*>.*?</nav>', html, re.S)
    hrefs = set(re.findall(r'href="(/[^"#?]*)"', head))
    if ws:
        hrefs |= set(re.findall(r'(?:href|data-href)="(/[^"#?]*)"', ws.group(0)))
    # Static files, sign-out and language switching are not destinations.
    return sorted(h for h in hrefs if not h.startswith(('/static/', '/media/', '/i18n/')))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleSidebarTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        cache.clear()

    # -- users ------------------------------------------------------------

    def staff(self, username, template_key=None):
        u = User.objects.create_user(username, f'{username}@x.com', 'pw')
        u.profile.user_type = UserType.STAFF
        if template_key:
            u.profile.global_role_template = builtin(template_key)
        u.profile.save()
        return u

    def users(self):
        su = self.make_superuser()
        tech = self.make_technician()
        l1 = self.staff('nav_l1', 'tech_l1')
        sales = self.staff('nav_sales', 'sales_rep')
        owner = self.staff('nav_owner')
        Membership.objects.create(user=owner, organization=self.org, role='owner',
                                  role_template=builtin('org_owner'))
        cadmin = User.objects.create_user('nav_cadmin', 'ca@x.com', 'pw')
        Membership.objects.create(user=cadmin, organization=self.org, role='admin',
                                  role_template=builtin('customer_admin'))
        cuser = User.objects.create_user('nav_cuser', 'cu@x.com', 'pw')
        Membership.objects.create(user=cuser, organization=self.org, role='readonly',
                                  role_template=builtin('customer_user'))
        return {'superuser': su, 'tech': tech, 'tech_l1': l1, 'sales_rep': sales,
                'org_owner': owner, 'customer_admin': cadmin, 'customer_user': cuser}

    def visit(self, user):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))
        r = self.client.get(reverse('core:dashboard'), follow=True)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def settings_page(self, html):
        """The first Administration category, or the account menu's
        Organization settings, when the user has one."""
        nav = sidebar(html)
        if nav.get('settings'):
            return nav['settings'][0]
        m = re.search(r'href="([^"]+)"[^>]*>\s*<i class="fas fa-users-cog[^"]*"[^>]*></i> Organization settings',
                      html)
        return m.group(1) if m else None

    # -- the test ----------------------------------------------------------

    def test_every_drawn_link_opens_for_every_role(self):
        for role, user in self.users().items():
            html = self.visit(user)
            links = set(frame_links(html))
            page = self.settings_page(html)
            if page:
                r = self.client.get(page, follow=True)
                self.assertNotEqual(r.status_code, 403, (role, page))
                if r.status_code == 200:
                    links |= set(frame_links(r.content.decode()))
            self.assertTrue(links, role)
            for href in sorted(links):
                with self.subTest(role=role, href=href):
                    code = self.client.get(href).status_code
                    self.assertNotEqual(code, 403, f'{role}: {href}')
                    self.assertNotEqual(code, 404, f'{role}: {href}')

    def test_customers_see_no_reports_settings_or_staff_pages(self):
        users = self.users()
        for role in ('customer_admin', 'customer_user'):
            html = self.visit(users[role])
            nav = sidebar(html)
            with self.subTest(role=role):
                self.assertNotIn('reports', nav)
                self.assertNotIn('settings', nav)
                self.assertNotIn('id="topbarSettings"', html)
                for name in STAFF_ONLY:
                    self.assertNotIn(f'href="{reverse(name)}"', html, f'{role}: {name}')

    def test_who_gets_administration(self):
        users = self.users()
        expect = {
            'superuser': 9, 'tech': 3, 'tech_l1': 2, 'sales_rep': 1, 'org_owner': 6,
        }
        for role, count in expect.items():
            with self.subTest(role=role):
                self.assertEqual(len(sidebar(self.visit(users[role])).get('settings', [])), count)

    def test_customer_admin_reaches_organization_settings_customer_user_does_not(self):
        users = self.users()
        self.assertIn('Organization settings', self.visit(users['customer_admin']))
        self.assertNotIn('Organization settings', self.visit(users['customer_user']))
