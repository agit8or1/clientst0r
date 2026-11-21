"""core.nav_cache: the sidebar's gate decisions kept between requests.

* A render from kept decisions draws exactly what a render that decides
  everything afresh draws, for a superuser, an MSP technician, a technician
  whose reach comes from an access group, and a customer user, on several
  pages (a list, a query-string tab, the settings center, a settings page).
* The sidebar is never empty for those users (the template tag swallows
  errors, so a broken sidebar would otherwise pass as a 200).
* An access change shows on the next render: in this process through the
  signals (local generation), from another worker through the database row
  (shared generation), and a time-limited grant through the TTL.
"""
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.db.models import F
from django.test import override_settings
from django.urls import reverse

from accounts.models import AuthzGeneration, Membership, RoleTemplate
from core import nav_cache
from core.tests.test_navbar_grouping import TEST_MIDDLEWARE, NavbarTestBase, sidebar

User = get_user_model()


def frame(html):
    """The frame the navigation draws (top bar, sidebar, account menu, tab
    strip, settings workspace), with per-request tokens blanked."""
    head = html.split('id="main-content"', 1)[0]
    ws = re.search(r'<nav class="settings-ws"[^>]*>.*?</nav>', html, re.S)
    out = head + (ws.group(0) if ws else '')
    out = re.sub(r'nonce="[^"]*"', 'nonce=""', out)
    out = re.sub(r'(data-csrf|value|content)="[A-Za-z0-9]{32,}"', r'\1=""', out)
    return out


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NavCacheTests(NavbarTestBase):

    def setUp(self):
        super().setUp()
        nav_cache.clear()
        self.addCleanup(nav_cache.clear)

    # -- users -------------------------------------------------------------

    def group_tech(self):
        from tech_access.models import TechnicianGroup
        u = self.make_technician()
        group = TechnicianGroup.objects.get(seed_key='l1_tech')
        group.members.add(u)
        return u

    def customer(self):
        u = User.objects.create_user('nav_cache_cust', 'c@x.com', 'pw')
        Membership.objects.create(
            user=u, organization=self.org, role='readonly',
            role_template=RoleTemplate.objects.get(seed_key='customer_user', organization__isnull=True))
        return u

    def login(self, user):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))

    def render(self, path):
        r = self.client.get(path, follow=True)
        self.assertEqual(r.status_code, 200, path)
        return r.content.decode()

    def fresh(self, path):
        """The same page with nothing kept: every gate decided again."""
        with override_settings(NAV_DECISION_CACHE=False):
            return self.render(path)

    # -- identical output --------------------------------------------------

    def test_kept_decisions_draw_the_same_frame(self):
        users = {
            'superuser': self.make_superuser(),
            'tech': None,  # created below: make_technician has a fixed username
            'group_tech': None,
            'customer': self.customer(),
        }
        users['group_tech'] = self.group_tech()
        users['tech'] = User.objects.create_user('nav_cache_tech', 'tc@x.com', 'pw')
        users['tech'].profile.user_type = 'staff'
        users['tech'].profile.save()
        pages = [reverse('core:dashboard'), reverse('vault:password_list'),
                 reverse('psa:ticket_list') + '?view=sla', reverse('core:settings_home'),
                 reverse('accounts:profile')]
        for role, user in users.items():
            self.login(user)
            for path in pages:
                r = self.client.get(path, follow=True)
                if r.status_code != 200:
                    continue  # a page this user may not open
                nav_cache.clear()
                expected = frame(self.fresh(path))
                cold = frame(self.render(path))
                warm = frame(self.render(path))
                self.assertEqual(cold, expected, (role, path, 'first render'))
                self.assertEqual(warm, expected, (role, path, 'from kept decisions'))
                self.assertTrue(sidebar(warm), (role, path, 'sidebar must not be empty'))
            self.assertTrue(any(isinstance(k, tuple) and k[0] == 'gate'
                                for _exp, memo in nav_cache._store.values() for k in memo),
                            (role, 'decisions are kept'))

    # -- invalidation ------------------------------------------------------

    def links(self, path=None):
        html = self.render(path or reverse('core:dashboard'))
        nav = sidebar(html)
        self.assertTrue(nav, 'sidebar must not be empty')
        return frame(html)

    def test_access_group_change_shows_on_the_next_render(self):
        from tech_access.models import TechnicianGroup
        tech = self.make_technician()
        self.login(tech)
        before = self.links()
        self.assertEqual(before, self.links())  # kept
        TechnicianGroup.objects.get(seed_key='administrators').members.add(tech)
        after = self.links()
        self.assertNotEqual(before, after, 'joining Administrators changes the sidebar')
        self.assertEqual(after, frame(self.fresh(reverse('core:dashboard'))))
        TechnicianGroup.objects.get(seed_key='administrators').members.remove(tech)
        self.assertEqual(self.links(), before)

    def test_role_change_shows_on_the_next_render(self):
        tech = self.make_technician()
        self.login(tech)
        before = self.links()
        tech.profile.global_role_template = RoleTemplate.objects.get(
            seed_key='org_admin', organization__isnull=True)
        tech.profile.save()
        after = self.links()
        self.assertEqual(after, frame(self.fresh(reverse('core:dashboard'))))
        self.assertNotEqual(before, after)

    def test_change_from_another_worker_shows_through_the_shared_generation(self):
        from tech_access.models import TechnicianGroup
        tech = self.make_technician()
        admins = TechnicianGroup.objects.get(seed_key='administrators')
        admins.members.add(tech)
        self.login(tech)
        with_group = self.links()
        # Another worker removes the membership: this process hears no
        # signal (a queryset delete), only the database row moves.
        TechnicianGroup.members.through.objects.filter(techniciangroup=admins, user=tech).delete()
        self.assertEqual(self.links(), with_group, 'nothing told this process yet')
        AuthzGeneration.objects.filter(pk=1).update(value=F('value') + 1)
        self.assertNotEqual(self.links(), with_group)
        self.assertEqual(self.links(), frame(self.fresh(reverse('core:dashboard'))))

    def test_entries_expire(self):
        from tech_access.models import TechnicianGroup
        tech = self.make_technician()
        admins = TechnicianGroup.objects.get(seed_key='administrators')
        admins.members.add(tech)
        self.login(tech)
        with_group = self.links()
        TechnicianGroup.members.through.objects.filter(techniciangroup=admins, user=tech).delete()
        self.assertEqual(self.links(), with_group)
        real = nav_cache.time.monotonic
        with mock.patch.object(nav_cache.time, 'monotonic', lambda: real() + nav_cache.TTL + 1):
            self.assertNotEqual(self.links(), with_group)

    def test_unreadable_generation_keeps_nothing(self):
        self.login(self.make_superuser())
        with mock.patch('accounts.authz_cache.shared_generation', return_value=None):
            self.links()
        self.assertFalse(nav_cache._store)

    def test_bump_writes_the_shared_row(self):
        from accounts import authz_cache
        before = authz_cache.shared_generation()
        authz_cache.invalidate('test')
        self.assertEqual(authz_cache.shared_generation(), (before or 0) + 1)
