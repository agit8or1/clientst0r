"""v3.17.653: optional second-administrator approval for granting superuser."""
from io import StringIO

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from audit.models import AuditLog
from tech_access import services
from tech_access.models import ProtectedChange, ProtectionSettings

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]
PAGE = 'tech_access:superuser_policy'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SuperuserApprovalTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_superuser('alice', 'alice@msp.test', 'pw-alice-653!')
        self.bob = User.objects.create_superuser('bob', 'bob@msp.test', 'pw-bob-653!')
        self.carol = User.objects.create_user('carol', 'carol@msp.test', 'pw-carol-653!')

    def _as(self, user, password):
        self.client.force_login(user)
        self.client.post(reverse(PAGE), {'action': 'reauth', 'password': password})

    def _post(self, **data):
        return self.client.post(reverse(PAGE), data, follow=True)

    def _enable(self):
        self._as(self.alice, 'pw-alice-653!')
        self._post(action='enable')
        self.assertTrue(services.superuser_policy_on())

    def _promote_carol(self):
        """Alice promotes Carol on the user edit page."""
        self.client.force_login(self.alice)
        return self.client.post(reverse('accounts:user_edit', args=[self.carol.pk]), {
            'username': 'carol', 'email': 'carol@msp.test', 'first_name': '', 'last_name': '',
            'is_active': 'on', 'is_superuser': 'on', 'user_type': 'staff'})

    def _grant(self):
        return ProtectedChange.objects.get(kind='superuser_grant', target_user=self.carol)

    # --- policy -----------------------------------------------------------

    def test_policy_is_off_on_upgrade_and_promotion_then_applies_at_once(self):
        self.assertFalse(ProtectionSettings.load().superuser_grant_requires_approval)
        self._promote_carol()
        self.carol.refresh_from_db()
        self.assertTrue(self.carol.is_superuser)
        self.assertFalse(ProtectedChange.objects.filter(kind='superuser_grant').exists())

    def test_single_admin_setup_cannot_turn_it_on(self):
        self.bob.delete()
        self._as(self.alice, 'pw-alice-653!')
        html = self.client.get(reverse(PAGE)).content.decode()
        self.assertIn('needs two different eligible administrators', html)
        self._post(action='enable')
        self.assertFalse(services.superuser_policy_on())
        with self.assertRaises(ValueError):
            services.enable_superuser_policy(self.alice)

    def test_non_superusers_cannot_open_the_page(self):
        self.client.force_login(self.carol)
        self.assertNotEqual(self.client.get(reverse(PAGE)).status_code, 200)
        self._post(action='enable')
        self.assertFalse(services.superuser_policy_on())

    def test_turning_it_on_is_audited(self):
        self._enable()
        row = AuditLog.objects.get(extra_data__event='superuser_policy_enabled')
        self.assertEqual(row.extra_data['requested_by'], 'alice')

    # --- grants -----------------------------------------------------------

    def test_promotion_waits_for_a_different_admin_and_is_logged(self):
        self._enable()
        self._promote_carol()
        self.carol.refresh_from_db()
        self.assertFalse(self.carol.is_superuser)
        change = self._grant()
        requested = AuditLog.objects.get(extra_data__event='superuser_grant_requested')
        self.assertEqual((requested.extra_data['requested_by'], requested.extra_data['target']), ('alice', 'carol'))

        self._as(self.alice, 'pw-alice-653!')
        self._post(action='confirm_change', change=change.pk)
        # Self-approval is refused.
        self._post(action='approve_change', change=change.pk)
        self.carol.refresh_from_db()
        self.assertFalse(self.carol.is_superuser)
        self.assertEqual(ProtectedChange.objects.get(pk=change.pk).status, ProtectedChange.PENDING)

        self._as(self.bob, 'pw-bob-653!')
        self._post(action='approve_change', change=change.pk)
        self.carol.refresh_from_db()
        self.assertTrue(self.carol.is_superuser)
        approved = AuditLog.objects.get(extra_data__event='superuser_grant_approved')
        self.assertEqual({k: approved.extra_data[k] for k in ('requested_by', 'approved_by', 'target', 'outcome')},
                         {'requested_by': 'alice', 'approved_by': 'bob', 'target': 'carol', 'outcome': 'applied'})
        self.assertFalse(AuditLog.objects.filter(extra_data__event='superuser_granted_outside_approval',
                                             extra_data__target='carol').exists())

    def test_duplicate_approval_and_duplicate_request(self):
        self._enable()
        self._promote_carol()
        self._promote_carol()
        self.assertEqual(ProtectedChange.objects.filter(kind='superuser_grant', target_user=self.carol).count(), 1)
        change = self._grant()
        self._as(self.alice, 'pw-alice-653!')
        self._post(action='confirm_change', change=change.pk)
        self._as(self.bob, 'pw-bob-653!')
        self._post(action='approve_change', change=change.pk)
        resp = self._post(action='approve_change', change=change.pk)
        self.assertContains(resp, 'already applied')
        self.assertEqual(AuditLog.objects.filter(extra_data__event='superuser_grant_approved').count(), 1)

    def test_approval_needs_the_requester_to_confirm_first(self):
        self._enable()
        self._promote_carol()
        self._as(self.bob, 'pw-bob-653!')
        self._post(action='approve_change', change=self._grant().pk)
        self.carol.refresh_from_db()
        self.assertFalse(self.carol.is_superuser)

    def test_rejection_is_logged_and_grants_nothing(self):
        self._enable()
        self._promote_carol()
        change = self._grant()
        self._as(self.bob, 'pw-bob-653!')
        self._post(action='reject_change', change=change.pk)
        self.carol.refresh_from_db()
        self.assertFalse(self.carol.is_superuser)
        row = AuditLog.objects.filter(object_type='protected_change', object_id=change.pk).order_by('-pk').first()
        self.assertEqual((row.extra_data['status'], row.extra_data['reviewed_by'], row.extra_data['target']),
                         ('rejected', 'bob', 'carol'))

    def test_creating_a_superuser_creates_an_ordinary_account_and_a_request(self):
        self._enable()
        self.client.force_login(self.alice)
        self.client.post(reverse('accounts:user_create'), {
            'username': 'dave', 'email': 'dave@msp.test', 'first_name': '', 'last_name': '',
            'is_superuser': 'on', 'user_type': 'staff', 'password1': 'pw-dave-653-long!',
            'password2': 'pw-dave-653-long!'})
        dave = User.objects.get(username='dave')
        self.assertFalse(dave.is_superuser)
        self.assertTrue(ProtectedChange.objects.filter(kind='superuser_grant', target_user=dave).exists())

    def test_django_admin_promotion_is_held(self):
        self._enable()
        self.client.force_login(self.alice)
        self.client.post(reverse('admin:auth_user_change', args=[self.carol.pk]), {
            'username': 'carol', 'email': 'carol@msp.test', 'is_active': 'on', 'is_staff': 'on',
            'is_superuser': 'on', 'date_joined_0': '2026-11-01', 'date_joined_1': '10:00:00',
            'initial-date_joined_0': '2026-11-01', 'initial-date_joined_1': '10:00:00'})
        self.carol.refresh_from_db()
        self.assertFalse(self.carol.is_superuser)
        self.assertTrue(self.carol.is_staff)
        self.assertTrue(ProtectedChange.objects.filter(kind='superuser_grant', target_user=self.carol).exists())

    def test_the_target_cannot_approve_their_own_grant(self):
        from tech_access.protected import approval_refusal
        self._enable()
        change = services.propose_superuser_grant(self.carol, self.alice)
        self.assertTrue(approval_refusal(change, self.carol))
        self.assertTrue(approval_refusal(change, self.alice))

    # --- turning it off -----------------------------------------------------

    def test_one_admin_cannot_turn_it_off_alone(self):
        self._enable()
        self._post(action='request_disable')
        self.assertTrue(services.superuser_policy_on())
        change = ProtectedChange.objects.get(kind='superuser_policy')
        self._post(action='confirm_change', change=change.pk)
        self._post(action='approve_change', change=change.pk)
        self.assertTrue(services.superuser_policy_on())
        self._as(self.bob, 'pw-bob-653!')
        self._post(action='approve_change', change=change.pk)
        self.assertFalse(services.superuser_policy_on())
        row = AuditLog.objects.get(extra_data__event='superuser_policy_disabled')
        self.assertEqual((row.extra_data['requested_by'], row.extra_data['approved_by']), ('alice', 'bob'))

    def test_last_admin_standing_needs_host_level_recovery(self):
        self._enable()
        self.bob.is_active = False
        self.bob.save()
        with self.assertRaises(ValueError):
            services.propose_disable_superuser_policy(self.alice)
        with self.assertRaises(ValueError):
            services.propose_superuser_grant(self.carol, self.alice)
        out = StringIO()
        call_command('superuser_policy', '--disable', '--reason', 'second admin left', stdout=out)
        self.assertFalse(services.superuser_policy_on())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='superuser_policy_disabled_on_host').exists())

    def test_host_grant_outside_the_application_is_recorded(self):
        self._enable()
        User.objects.create_superuser('erin', 'erin@msp.test', 'pw-erin-653!')
        row = AuditLog.objects.get(extra_data__event='superuser_granted_outside_approval', extra_data__target='erin')
        self.assertTrue(row.extra_data['policy_on'])
        self.assertFalse(row.extra_data['first_superuser'])
