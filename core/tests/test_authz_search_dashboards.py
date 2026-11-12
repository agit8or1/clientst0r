"""
Roles & permissions program (authz-ops): global search, favorites, the
dashboards and Customer Operations follow role flags and the customer ticket
audience server-side.
"""
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from core.models import Organization, SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _staff(username, global_role=None, **kw):
    user = User.objects.create_user(username, f'{username}@msp.test', 'pw-authz-123', **kw)
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = global_role
    profile.save()
    return user


def _login(user, org=None):
    c = Client()
    c.force_login(user)
    if org is not None:
        s = c.session
        s['current_organization_id'] = org.pk
        s.save()
    return c


def _tickets_fixture(cls):
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    call_command('psa_seed_defaults', verbosity=0)
    s = SystemSetting.get_settings()
    s.psa_enabled = True
    s.save()
    base = dict(queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(),
                status=TicketStatus.objects.filter(is_terminal=False, pauses_sla=False).first())
    cls.acme = Organization.objects.create(name='Acme', slug='authz-s-acme')
    cls.other = Organization.objects.create(name='Umbrella', slug='authz-s-umb')
    cls.alice = User.objects.create_user('authz_alice', 'alice@acme.test', 'pw-authz-123')
    cls.bob = User.objects.create_user('authz_bob', 'bob@acme.test', 'pw-authz-123')
    for u in (cls.alice, cls.bob):
        Membership.objects.create(user=u, organization=cls.acme, role=Role.READONLY)
    due = timezone.now() + timedelta(days=1)

    def t(org, subject, shared=True, **kw):
        tk = Ticket.objects.create(organization=org, subject=subject, **base, **kw)
        Ticket.objects.filter(pk=tk.pk).update(client_can_view=shared, resolution_due_at=due)
        return Ticket.objects.get(pk=tk.pk)

    cls.alice_t = t(cls.acme, 'Zebra alice printer', created_by=cls.alice)
    cls.bob_t = t(cls.acme, 'Zebra bob laptop', requester_email='bob@acme.test')
    cls.internal_t = t(cls.acme, 'Zebra internal only', shared=False)
    cls.other_t = t(cls.other, 'Zebra umbrella outage')


def _own_only(membership, flag, default=False):
    """Pretend every customer role is the own-tickets-only kind (the proposed
    portal_tickets_view_org flag set to False)."""
    if flag == 'portal_tickets_view_org':
        return False
    return bool(getattr(membership.get_permissions(), flag, default))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalSearchTicketScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _tickets_fixture(cls)

    def _subjects(self, user, org=None):
        r = _login(user, org or self.acme).get(reverse('core:search'), {'q': 'Zebra'})
        self.assertEqual(r.status_code, 200)
        return {t.subject for t in r.context['tickets']}

    def test_customer_never_finds_internal_or_other_customer_tickets(self):
        found = self._subjects(self.alice)
        self.assertNotIn('Zebra internal only', found)
        self.assertNotIn('Zebra umbrella outage', found)
        # Today's org-wide audience is kept: coworker's shared ticket visible.
        self.assertEqual(found, {'Zebra alice printer', 'Zebra bob laptop'})

    def test_own_only_customer_role_finds_only_their_tickets(self):
        with mock.patch('psa.visibility.membership_flag', _own_only):
            self.assertEqual(self._subjects(self.alice), {'Zebra alice printer'})
            self.assertEqual(self._subjects(self.bob), {'Zebra bob laptop'})

    def test_staff_whose_global_role_lacks_tickets_view_find_no_tickets(self):
        tech = _staff('authz_s_tech', RoleTemplate.objects.create(name='AuthzNoTickets', tickets_view=False))
        self.assertEqual(self._subjects(tech), set())

    def test_staff_without_global_role_find_every_ticket(self):
        tech = _staff('authz_s_legacy')
        self.assertIn('Zebra umbrella outage', self._subjects(tech))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FavoritesIdorTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from vault.models import Password
        cls.acme = Organization.objects.create(name='Acme', slug='authz-f-acme')
        cls.other = Organization.objects.create(name='Umbrella', slug='authz-f-umb')
        cls.user = User.objects.create_user('authz_fav', 'f@acme.test', 'pw-authz-123')
        Membership.objects.create(user=cls.user, organization=cls.acme, role=Role.EDITOR)
        cls.mine = Password.objects.create(organization=cls.acme, title='Acme router', username='a')
        cls.foreign = Password.objects.create(organization=cls.other, title='Umbrella payroll admin',
                                              username='b')
        cls.ct = ContentType.objects.get_for_model(Password)

    def _toggle(self, c, obj, method='post'):
        url = reverse('core:favorite_toggle', args=[self.ct.pk, obj.pk])
        return getattr(c, method)(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_cannot_favorite_another_customers_password(self):
        from core.models import Favorite
        c = _login(self.user, self.acme)
        self.assertEqual(self._toggle(c, self.foreign).status_code, 404)
        self.assertFalse(Favorite.objects.filter(user=self.user).exists())

    def test_toggle_is_post_only(self):
        c = _login(self.user, self.acme)
        self.assertEqual(self._toggle(c, self.mine, method='get').status_code, 405)

    def test_list_never_prints_a_foreign_objects_name(self):
        from core.models import Favorite
        # A row planted before this fix (or access revoked since).
        Favorite.objects.create(user=self.user, content_type=self.ct, object_id=self.foreign.pk)
        c = _login(self.user, self.acme)
        self.assertEqual(self._toggle(c, self.mine).status_code, 200)
        r = c.get(reverse('core:favorite_list'))
        self.assertContains(r, 'Acme router')
        self.assertNotContains(r, 'Umbrella payroll admin')

    def test_arbitrary_model_cannot_be_favorited(self):
        c = _login(self.user, self.acme)
        user_ct = ContentType.objects.get_for_model(User)
        r = c.post(reverse('core:favorite_toggle', args=[user_ct.pk, self.user.pk]))
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DashboardScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _tickets_fixture(cls)

    def test_dashboard_schedule_follows_customer_ticket_audience(self):
        from core.dashboard_panels import get_schedule
        titles = lambda u: {i['title'] for d in get_schedule(u, self.acme) for i in d.items}  # noqa: E731
        everything = titles(self.alice)
        self.assertTrue(any('alice printer' in t for t in everything))
        self.assertTrue(any('bob laptop' in t for t in everything))
        self.assertFalse(any('internal only' in t for t in everything))
        with mock.patch('psa.visibility.membership_flag', _own_only):
            own = titles(self.alice)
        self.assertTrue(any('alice printer' in t for t in own))
        self.assertFalse(any('bob laptop' in t for t in own))

    def test_global_dashboard_audit_feed_needs_audit_view(self):
        from audit.models import AuditLog
        AuditLog.log(user=None, action='update', organization=self.other,
                     object_type='x', object_id=1, object_repr='secret-change',
                     description='Rotated Umbrella payroll credentials')
        l1 = _staff('authz_d_l1', RoleTemplate.objects.create(name='AuthzDL1', audit_view=False))
        r = _login(l1).get(reverse('core:global_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.context['global_activity']), [])
        auditor = _staff('authz_d_aud', RoleTemplate.objects.create(name='AuthzDAud', audit_view=True))
        r = _login(auditor).get(reverse('core:global_dashboard'))
        self.assertTrue(len(list(r.context['global_activity'])) >= 1)

    def test_customer_ops_sla_section_follows_customer_ticket_audience(self):
        from types import SimpleNamespace
        from core import customer_ops as ops
        from psa.models import Ticket
        Ticket.objects.filter(pk__in=[self.alice_t.pk, self.bob_t.pk]).update(
            resolution_due_at=timezone.now() - timedelta(hours=1))
        req = SimpleNamespace(user=self.alice)
        titles = {i.title for i in ops.sla_section(req, self.acme).items}
        self.assertTrue(any('bob laptop' in t for t in titles))
        with mock.patch('psa.visibility.membership_flag', _own_only):
            titles = {i.title for i in ops.sla_section(req, self.acme).items}
        self.assertTrue(any('alice printer' in t for t in titles))
        self.assertFalse(any('bob laptop' in t for t in titles))
