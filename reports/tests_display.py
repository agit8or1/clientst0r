"""
Wallboard displays without sign-in (reports/displays.py, docs/WALLBOARD_DISPLAYS.md).

Signed-in management views run under TEST_MIDDLEWARE (no 2FA / Axes). The TV
side is also exercised with the real middleware stack (DisplayRealMiddlewareTests)
to show the display paths need no exemption and open nothing else.
"""
from datetime import timedelta
import re

from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

DISPLAY = '/reports/wallboards/display/'
DATA = '/reports/wallboards/display/data/'
OPEN = '/reports/wallboards/display/link/open/'
STATUS = '/reports/wallboards/display/pair/status/'


def _make_msp_tech(user, global_role=None, scope_orgs=None):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = global_role
    if scope_orgs is not None:
        profile.client_scope = 'selected'
    profile.save()
    if scope_orgs is not None:
        profile.scope_organizations.set(scope_orgs)
    return user


class DisplayFixture:

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User
        from django.core.management import call_command
        from accounts.models import Membership, Role
        from core.models import Organization
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        from reports.models import Wallboard, WallboardWidget

        call_command('psa_seed_defaults', verbosity=0)
        cls.org_a = Organization.objects.create(name='Disp A', slug='disp-a')
        cls.org_b = Organization.objects.create(name='Disp B', slug='disp-b')

        # MSP technician with an Owner membership at A (legacy: acts at every
        # customer in scope), scoped to customer A only.
        cls.tech = User.objects.create_user('disp-tech', 'dt@x.com', 'pw')
        Membership.objects.create(user=cls.tech, organization=cls.org_a, role=Role.OWNER, is_active=True)
        _make_msp_tech(cls.tech, scope_orgs=[cls.org_a])
        # MSP technician whose role cannot edit wallboards.
        cls.viewer_tech = User.objects.create_user('disp-viewer', 'dv@x.com', 'pw')
        Membership.objects.create(user=cls.viewer_tech, organization=cls.org_a, role=Role.EDITOR,
                                  is_active=True)
        _make_msp_tech(cls.viewer_tech)
        # Customer B's own Owner (a customer user, not MSP staff).
        cls.cust_b = User.objects.create_user('disp-cust-b', 'cb@x.com', 'pw')
        Membership.objects.create(user=cls.cust_b, organization=cls.org_b, role=Role.OWNER, is_active=True)
        cls.admin = User.objects.create_superuser('disp-admin', 'da@x.com', 'pw')

        cls.board_a = Wallboard.objects.create(organization=cls.org_a, name='A board', refresh_seconds=30)
        cls.board_b = Wallboard.objects.create(organization=cls.org_b, name='B board')
        cls.board_g = Wallboard.objects.create(organization=None, name='Global board')
        for board in (cls.board_a, cls.board_b, cls.board_g):
            WallboardWidget.objects.create(wallboard=board, title='Open tickets', widget_type='metric',
                                           data_source='open_tickets_count', order=10)
        cls.vault_widget = WallboardWidget.objects.create(
            wallboard=cls.board_a, title='Vault events', widget_type='metric',
            data_source='vault_activity_24h', order=20)

        kw = dict(queue=Queue.objects.first(), status=TicketStatus.objects.filter(slug='new').first(),
                  priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first())
        for i in range(2):
            Ticket.objects.create(organization=cls.org_a, subject=f'A{i}', **kw)
        for i in range(3):
            Ticket.objects.create(organization=cls.org_b, subject=f'B{i}', **kw)

    def setUp(self):
        cache.clear()

    # -- helpers --
    def staff_client(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def tv_code(self, tv, **extra):
        r = tv.get(DISPLAY, **extra)
        self.assertEqual(r.status_code, 200)
        return r.context['code']

    def pair(self, approver, board, code, **fields):
        data = {'code': code, 'name': fields.pop('name', 'NOC TV')}
        data.update(fields)
        return self.staff_client(approver).post(
            f'/reports/wallboards/{board.pk}/displays/pair/', data, follow=True)

    def paired_tv(self, approver=None, board=None, **fields):
        tv = Client()
        code = self.tv_code(tv)
        self.pair(approver or self.tech, board or self.board_a, code, **fields)
        r = tv.get(STATUS)
        self.assertEqual(r.json()['state'], 'paired')
        return tv

    @staticmethod
    def msgs(resp):
        return [str(m) for m in resp.context['messages']] if resp.context else []

    @staticmethod
    def widget(payload, title):
        return next(w for w in payload['widgets'] if w['title'] == title)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DisplayPairingTests(DisplayFixture, TestCase):

    def test_pairing_happy_path(self):
        from reports.models import WallboardDisplay, WallboardPairingRequest
        from reports import displays as D
        tv = Client()
        code = self.tv_code(tv)
        self.assertRegex(code, r'^[A-Z2-9]{4}-[A-Z2-9]{4}$')
        self.assertEqual(tv.get(STATUS).json()['state'], 'pending')
        pr = WallboardPairingRequest.objects.get()
        self.assertEqual(pr.code_hash, D.hash_code(code))
        self.assertNotIn(D.normalize_code(code), pr.code_hash)

        r = self.pair(self.tech, self.board_a, code.lower().replace('-', ' '))
        self.assertIn('Paired "NOC TV"', ' '.join(self.msgs(r)))
        r = tv.get(STATUS)
        self.assertEqual(r.json()['state'], 'paired')
        cookie = r.cookies[D.COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(cookie['path'], D.DISPLAY_PATH)
        self.assertFalse(WallboardPairingRequest.objects.exists())

        d = WallboardDisplay.objects.get()
        self.assertEqual(d.credential_hash, D.hash_credential(cookie.value))
        self.assertEqual(d.scope['org_ids'], [self.org_a.pk])

        page = tv.get(DISPLAY)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'A board')
        self.assertEqual(page['Cache-Control'], 'no-store')
        self.assertNotContains(page, 'cdn.jsdelivr.net')
        self.assertEqual(tv.get(DATA).json()['state'], 'ok')
        # A second poll with the used pairing cookie gets nothing.
        self.assertEqual(tv.get(STATUS).json()['state'], 'expired')

    def test_https_cookie_is_secure(self):
        from reports import displays as D
        tv = Client()
        code = self.tv_code(tv, secure=True)
        self.pair(self.tech, self.board_a, code)
        r = tv.get(STATUS, secure=True)
        self.assertTrue(r.cookies[D.COOKIE_NAME]['secure'])

    def test_wrong_expired_and_used_codes_get_the_same_answer(self):
        from reports.models import WallboardPairingRequest
        from reports.display_views import GENERIC_CODE_ERROR
        tv = Client()
        code = self.tv_code(tv)
        wrong = self.msgs(self.pair(self.tech, self.board_a, 'ZZZZ-ZZZZ'))
        WallboardPairingRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = self.msgs(self.pair(self.tech, self.board_a, code))
        tv2 = Client()
        code2 = self.tv_code(tv2)
        self.pair(self.tech, self.board_a, code2)
        used = self.msgs(self.pair(self.tech, self.board_a, code2))
        self.assertEqual(wrong, [GENERIC_CODE_ERROR])
        self.assertEqual(expired, wrong)
        self.assertEqual(used, wrong)

    def test_expired_code_does_not_pair(self):
        from reports.models import WallboardDisplay, WallboardPairingRequest
        tv = Client()
        code = self.tv_code(tv)
        WallboardPairingRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.pair(self.tech, self.board_a, code)
        self.assertFalse(WallboardDisplay.objects.exists())
        self.assertEqual(tv.get(STATUS).json()['state'], 'expired')
        # Lazy cleanup removed the stale request.
        self.assertFalse(WallboardPairingRequest.objects.exists())

    def test_code_attempts_are_rate_limited(self):
        from reports.models import WallboardDisplay
        tv = Client()
        code = self.tv_code(tv)
        for _ in range(10):
            self.pair(self.tech, self.board_a, 'ZZZZ-ZZZZ')
        r = self.pair(self.tech, self.board_a, code)
        self.assertIn('Too many pairing attempts', ' '.join(self.msgs(r)))
        self.assertFalse(WallboardDisplay.objects.exists())

    def test_approval_requires_edit_rights_on_that_board(self):
        from reports.models import WallboardDisplay
        tv = Client()
        code = self.tv_code(tv)
        # Tech scoped to customer A: customer B's board is out of reach.
        r = self.staff_client(self.tech).post(
            f'/reports/wallboards/{self.board_b.pk}/displays/pair/', {'code': code, 'name': 'x'})
        self.assertIn(r.status_code, (403, 404))
        # Technician without the manage-dashboards permission.
        r = self.staff_client(self.viewer_tech).post(
            f'/reports/wallboards/{self.board_a.pk}/displays/pair/', {'code': code, 'name': 'x'})
        self.assertEqual(r.status_code, 403)
        # Customer B's own admin.
        r = self.staff_client(self.cust_b).post(
            f'/reports/wallboards/{self.board_b.pk}/displays/pair/', {'code': code, 'name': 'x'})
        self.assertIn(r.status_code, (302, 403, 404))
        self.assertFalse(WallboardDisplay.objects.exists())
        # The code still works for someone who may edit the board.
        self.pair(self.tech, self.board_a, code)
        self.assertEqual(WallboardDisplay.objects.count(), 1)

    def test_management_page_requires_edit_rights(self):
        self.assertEqual(self.staff_client(self.tech).get(
            f'/reports/wallboards/{self.board_a.pk}/displays/').status_code, 200)
        self.assertEqual(self.staff_client(self.viewer_tech).get(
            f'/reports/wallboards/{self.board_a.pk}/displays/').status_code, 403)
        self.assertEqual(Client().get(
            f'/reports/wallboards/{self.board_a.pk}/displays/').status_code, 302)

    def test_ip_rule_must_include_the_tv(self):
        from reports.models import WallboardDisplay
        tv = Client()
        code = self.tv_code(tv)
        r = self.pair(self.tech, self.board_a, code, allowed_networks='10.0.0.0/8')
        self.assertIn('outside the IP rule', ' '.join(self.msgs(r)))
        r = self.pair(self.tech, self.board_a, code, allowed_networks='not-an-ip')
        self.assertIn('Not an IP address', ' '.join(self.msgs(r)))
        self.assertFalse(WallboardDisplay.objects.exists())

    def test_audit_entries(self):
        from audit.models import AuditLog
        from reports.models import WallboardDisplay
        self.paired_tv()
        d = WallboardDisplay.objects.get()
        c = self.staff_client(self.tech)
        c.post(f'/reports/wallboards/{self.board_a.pk}/displays/link/', {'name': 'Lobby'})
        c.post(f'/reports/wallboards/{self.board_a.pk}/displays/{d.pk}/rename/', {'name': 'NOC 2'})
        c.post(f'/reports/wallboards/{self.board_a.pk}/displays/{d.pk}/revoke/')
        actions = list(AuditLog.objects.filter(object_type='wallboard_display')
                       .values_list('extra_data__action', flat=True))
        for a in ('wallboard_display_paired', 'wallboard_display_link_created',
                  'wallboard_display_renamed', 'wallboard_display_revoked'):
            self.assertIn(a, actions)
        entry = AuditLog.objects.filter(extra_data__action='wallboard_display_paired').get()
        self.assertEqual(entry.user, self.tech)
        self.assertEqual(entry.organization, self.org_a)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DisplayAccessTests(DisplayFixture, TestCase):

    def test_revoked_display_is_denied(self):
        from reports.models import WallboardDisplay
        tv = self.paired_tv()
        d = WallboardDisplay.objects.get()
        self.staff_client(self.tech).post(f'/reports/wallboards/{self.board_a.pk}/displays/{d.pk}/revoke/')
        r = tv.get(DATA)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json(), {'state': 'revoked'})
        page = tv.get(DISPLAY)
        self.assertEqual(page.status_code, 403)
        self.assertContains(page, 'Display revoked', status_code=403)
        self.assertNotContains(page, 'Open tickets', status_code=403)
        # "Pair again" starts a fresh pairing.
        self.assertIn('code', tv.get(DISPLAY + '?pair=1').context)

    def test_expired_display_is_denied(self):
        from reports.models import WallboardDisplay
        tv = self.paired_tv()
        WallboardDisplay.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(tv.get(DATA).status_code, 403)

    def test_inactive_or_deleted_board_is_denied(self):
        tv = self.paired_tv()
        type(self.board_a).objects.filter(pk=self.board_a.pk).update(is_active=False)
        self.assertEqual(tv.get(DATA).status_code, 403)

    def test_unknown_cookie_is_denied(self):
        from reports import displays as D
        tv = Client()
        tv.cookies[D.COOKIE_NAME] = 'x' * 64
        self.assertEqual(tv.get(DATA).status_code, 403)
        self.assertEqual(tv.get(DISPLAY).status_code, 403)

    def test_ip_allowlist_enforced(self):
        from reports.models import WallboardDisplay
        tv = self.paired_tv()
        WallboardDisplay.objects.update(allowed_networks='10.0.0.0/8')
        r = tv.get(DATA, REMOTE_ADDR='198.51.100.7')
        self.assertEqual(r.json(), {'state': 'network'})
        page = tv.get(DISPLAY, REMOTE_ADDR='198.51.100.7')
        self.assertEqual(page.status_code, 403)
        self.assertContains(page, 'Not allowed from this network', status_code=403)
        self.assertNotContains(page, 'Open tickets', status_code=403)
        # A forged X-Forwarded-For from an untrusted peer does not help.
        self.assertEqual(tv.get(DATA, REMOTE_ADDR='198.51.100.7',
                                HTTP_X_FORWARDED_FOR='10.1.2.3').status_code, 403)
        self.assertEqual(tv.get(DATA, REMOTE_ADDR='10.1.2.3').json()['state'], 'ok')
        d = WallboardDisplay.objects.get()
        self.assertEqual(d.last_seen_ip, '10.1.2.3')

    def test_display_cookie_opens_nothing_else(self):
        tv = self.paired_tv()
        for url in (f'/reports/wallboards/{self.board_a.pk}/',
                    f'/reports/wallboards/{self.board_b.pk}/',
                    f'/reports/wallboards/widgets/{self.vault_widget.pk}/data/',
                    f'/reports/wallboards/{self.board_a.pk}/displays/',
                    '/reports/wallboards/', '/core/dashboard/', '/admin/'):
            r = tv.get(url)
            self.assertIn(r.status_code, (301, 302, 401, 403, 404), url)
            if r.status_code in (301, 302):
                self.assertNotEqual(r['Location'].rstrip('/'), url.rstrip('/'), url)
                self.assertRegex(r['Location'], r'login|two_factor|account', url)
        r = tv.get('/api/organizations/')
        self.assertIn(r.status_code, (401, 403, 404, 302))
        # Still not a signed-in user.
        self.assertNotIn('_auth_user_id', tv.session)

    def test_signed_in_session_is_not_a_display(self):
        c = self.staff_client(self.admin)
        self.assertEqual(c.get(DATA).status_code, 403)

    def test_data_scope_customer_board(self):
        tv = self.paired_tv()
        data = tv.get(DATA).json()
        self.assertEqual(self.widget(data, 'Open tickets')['data']['value'], '2')

    def test_all_customers_scope_only_for_approver_who_sees_all(self):
        from reports.models import WallboardDisplay
        # Tech scoped to customer A may not authorise a global board.
        tv = Client()
        code = self.tv_code(tv)
        r = self.pair(self.tech, self.board_g, code)
        self.assertIn(r.status_code, (403, 404))
        self.assertFalse(WallboardDisplay.objects.exists())
        # A superuser may; the display then counts every customer.
        self.pair(self.admin, self.board_g, code)
        self.assertEqual(tv.get(STATUS).json()['state'], 'paired')
        self.assertIsNone(WallboardDisplay.objects.get().scope['org_ids'])
        self.assertEqual(self.widget(tv.get(DATA).json(), 'Open tickets')['data']['value'], '5')

    def test_superuser_on_customer_board_still_scoped_to_customer(self):
        tv = self.paired_tv(approver=self.admin, board=self.board_b)
        self.assertEqual(self.widget(tv.get(DATA).json(), 'Open tickets')['data']['value'], '3')

    def test_scope_is_what_was_recorded(self):
        from reports.models import WallboardDisplay
        tv = self.paired_tv()
        d = WallboardDisplay.objects.get()
        # Without tickets_view in the recorded scope the widget is restricted,
        # whatever the approver can do today.
        scope = dict(d.scope)
        scope['perm_orgs'] = {p: v for p, v in scope['perm_orgs'].items() if p != 'tickets_view'}
        WallboardDisplay.objects.filter(pk=d.pk).update(scope=scope)
        w = self.widget(tv.get(DATA).json(), 'Open tickets')
        self.assertTrue(w['data'].get('restricted'))
        # A scope that no longer matches the board's customer is refused.
        WallboardDisplay.objects.filter(pk=d.pk).update(scope={'org_ids': [self.org_b.pk], 'perm_orgs': {}})
        self.assertEqual(tv.get(DATA).status_code, 403)
        WallboardDisplay.objects.filter(pk=d.pk).update(scope={'org_ids': None, 'perm_orgs': {}})
        self.assertEqual(tv.get(DATA).status_code, 403)

    def test_unsafe_widget_not_served(self):
        tv = self.paired_tv(approver=self.admin)
        w = self.widget(tv.get(DATA).json(), 'Vault events')
        self.assertEqual(w['data'], {'error': 'Not available on displays', 'restricted': True})
        page = self.staff_client(self.tech).get(f'/reports/wallboards/{self.board_a.pk}/displays/')
        self.assertContains(page, 'Not available on displays')

    def test_layout_change_is_signalled(self):
        from reports.models import WallboardWidget
        tv = self.paired_tv()
        v1 = tv.get(DATA).json()['layout_version']
        WallboardWidget.objects.create(wallboard=self.board_a, title='More', widget_type='metric',
                                       data_source='overdue_tickets_count', order=30)
        self.assertNotEqual(tv.get(DATA).json()['layout_version'], v1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DisplayLinkTests(DisplayFixture, TestCase):

    def create_link(self, **fields):
        c = self.staff_client(self.tech)
        data = {'name': 'Lobby'}
        data.update(fields)
        page = c.post(f'/reports/wallboards/{self.board_a.pk}/displays/link/', data)
        self.assertEqual(page['Cache-Control'], 'no-store')
        m = re.search(r'/reports/wallboards/display/link/#([A-Za-z0-9_-]+)', page.content.decode())
        self.assertIsNotNone(m)
        again = c.get(f'/reports/wallboards/{self.board_a.pk}/displays/')
        self.assertNotContains(again, m.group(1))
        return m.group(1)

    def test_link_shown_once_and_stored_hashed(self):
        from reports.models import WallboardDisplay
        from reports import displays as D
        token = self.create_link()
        self.assertGreaterEqual(len(token), 60)
        d = WallboardDisplay.objects.get()
        self.assertEqual(d.kind, 'link')
        self.assertEqual(d.credential_hash, D.hash_credential(token))
        for f in d._meta.concrete_fields:
            self.assertNotIn(token, str(getattr(d, f.attname)), f.name)

    def test_link_sets_cookie_and_strips_token(self):
        from reports import displays as D
        token = self.create_link()
        tv = Client()
        # The link page itself carries no secret: the token is in the
        # fragment, which a browser never sends.
        landing = tv.get('/reports/wallboards/display/link/')
        self.assertEqual(landing.status_code, 200)
        self.assertEqual(landing['Referrer-Policy'], 'no-referrer')
        self.assertNotIn('_auth_user_id', tv.session)
        r = tv.post(OPEN, {'token': token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'state': 'ok', 'next': D.DISPLAY_PATH})
        self.assertTrue(r.cookies[D.COOKIE_NAME]['httponly'])
        self.assertEqual(r.cookies[D.COOKIE_NAME]['path'], D.DISPLAY_PATH)
        page = tv.get(D.DISPLAY_PATH)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'A board')
        self.assertNotContains(page, token)

    def test_bad_revoked_and_ip_restricted_links(self):
        from reports.models import WallboardDisplay
        token = self.create_link(allowed_networks='10.0.0.0/8', expires_days='5')
        tv = Client()
        self.assertEqual(tv.post(OPEN, {'token': token}).status_code, 403)
        self.assertEqual(tv.post(OPEN, {'token': token}, REMOTE_ADDR='10.9.9.9').status_code, 200)
        # Still usable after first use (a player that forgets cookies reopens it).
        self.assertEqual(Client().post(OPEN, {'token': token}, REMOTE_ADDR='10.9.9.9').status_code, 200)
        self.assertEqual(tv.post(OPEN, {'token': 'nope'}).status_code, 404)
        self.assertEqual(tv.post(OPEN, {}).status_code, 404)
        self.assertEqual(tv.get(OPEN).status_code, 405)
        WallboardDisplay.objects.update(revoked_at=timezone.now())
        self.assertEqual(Client().post(OPEN, {'token': token},
                                       REMOTE_ADDR='10.9.9.9').status_code, 404)
        self.assertEqual(tv.get(DATA, REMOTE_ADDR='10.9.9.9').status_code, 403)


@override_settings(SECURE_SSL_REDIRECT=False)
class DisplayRealMiddlewareTests(DisplayFixture, TestCase):
    """The full MIDDLEWARE (2FA enforcement and Axes included): the display
    paths work without a sign-in and nothing else opens for a display."""

    def test_display_paths_under_real_middleware(self):
        from reports.models import WallboardDisplay
        from reports import displays as D
        tv = Client()
        code = self.tv_code(tv)
        # Approve directly (the signed-in half is covered above).
        from reports.models import WallboardPairingRequest
        pr = WallboardPairingRequest.objects.get(code_hash=D.hash_code(code))
        d = WallboardDisplay.objects.create(
            wallboard=self.board_a, name='TV', scope={'org_ids': [self.org_a.pk],
                                                       'perm_orgs': {'tickets_view': [self.org_a.pk]}})
        WallboardPairingRequest.objects.filter(pk=pr.pk).update(display=d, approved_at=timezone.now())
        self.assertEqual(tv.get(STATUS).json()['state'], 'paired')
        self.assertEqual(tv.get(DISPLAY).status_code, 200)
        data = tv.get(DATA).json()
        self.assertEqual(self.widget(data, 'Open tickets')['data']['value'], '2')
        for url in (f'/reports/wallboards/{self.board_a.pk}/', f'/reports/wallboards/{self.board_b.pk}/',
                    f'/reports/wallboards/{self.board_a.pk}/displays/', '/reports/', '/', '/admin/'):
            r = tv.get(url)
            self.assertIn(r.status_code, (301, 302, 401, 403, 404), url)
        self.assertNotIn('_auth_user_id', tv.session)


@override_settings(SECURE_SSL_REDIRECT=False)
class DisplaySignedInBrowserTests(DisplayFixture, TestCase):
    """A display does not depend on who, if anyone, is signed in on the TV's
    browser: a customer user or a technician without report permissions does
    not turn the board into a 403."""

    def _paired_client(self, user):
        from reports.models import WallboardDisplay
        from reports import displays as D
        raw = D.new_credential()
        WallboardDisplay.objects.create(
            wallboard=self.board_a, name='TV', kind=WallboardDisplay.KIND_LINK,
            credential_hash=D.hash_credential(raw),
            scope={'org_ids': [self.org_a.pk], 'perm_orgs': {'tickets_view': [self.org_a.pk]}})
        c = Client()
        c.force_login(user)
        c.cookies[D.COOKIE_NAME] = raw
        return c

    def test_customer_user_signed_in_on_the_tv(self):
        from django.contrib.auth.models import User
        from accounts.models import Membership
        cust = User.objects.create_user('tv-cust', 'tvc@x.com', 'x')
        Membership.objects.create(user=cust, organization=self.org_a, role='viewer')
        c = self._paired_client(cust)
        with self.settings(MIDDLEWARE=TEST_MIDDLEWARE):
            self.assertEqual(c.get(DISPLAY).status_code, 200)
            self.assertEqual(c.get(DATA).status_code, 200)
            # The exemption covers the display paths only.
            self.assertIn(c.get(f'/reports/wallboards/{self.board_a.pk}/').status_code, (302, 403, 404))
