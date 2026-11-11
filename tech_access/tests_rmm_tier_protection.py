"""Giving or taking an RMM tier is a two-administrator protected change.

  * Changing a technician's global role to or from a role template that
    carries an RMM tier (accounts user edit / create pages).
  * Changing a role template's rmm_tier.

Both follow tech_access.protected: proposed, confirmed by the requester with
a fresh password, approved by a different approver who is not affected.
Changes made outside the application (shell, scripts) are not blocked but
are audited.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import RoleTemplate, UserProfile, UserType
from audit.models import AuditLog
from psa.tests._base import _setup_seed
from tech_access import protected, services
from tech_access.models import ProtectedChange

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


class _Req:
    def __init__(self, user):
        self.user, self.session, self.META, self.path = user, {}, {}, '/test'


def fresh(user, password):
    r = _Req(user)
    assert protected.reauthenticate(r, password) == ''
    return r


def tier(t):
    return RoleTemplate.objects.get(rmm_tier=t, organization__isnull=True)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalRoleTierTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.alice = User.objects.create_superuser('alice', 'alice@msp.test', 'pw-alice-tier!')
        self.bob = User.objects.create_superuser('bob', 'bob@msp.test', 'pw-bob-tier!')
        self.carol = User.objects.create_user('carol', 'carol@msp.test', 'pw-carol-tier!')
        p = self.carol.profile
        p.user_type = UserType.STAFF
        p.save()
        self.plain = RoleTemplate.objects.create(name='Plain tech role', is_system_template=True,
                                                 tickets_view=True)

    def _edit_role(self, role):
        self.client.force_login(self.alice)
        return self.client.post(reverse('accounts:user_edit', args=[self.carol.pk]), {
            'username': 'carol', 'email': 'carol@msp.test', 'first_name': '', 'last_name': '',
            'is_active': 'on', 'user_type': 'staff', 'global_role_template': str(role.pk) if role else ''})

    def _role(self):
        return UserProfile.objects.get(user=self.carol).global_role_template

    def _change(self):
        return ProtectedChange.objects.get(kind='global_role', target_user=self.carol, status='pending')

    def test_giving_a_tier_role_waits_for_a_second_administrator(self):
        self._edit_role(tier('l2'))
        self.assertIsNone(self._role())
        change = self._change()
        self.assertEqual(change.requested_by, self.alice)
        # The requester cannot approve it, even after confirming.
        protected.confirm(change, fresh(self.alice, 'pw-alice-tier!'))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(change, fresh(self.alice, 'pw-alice-tier!'))
        self.assertIsNone(self._role())
        protected.approve(change, fresh(self.bob, 'pw-bob-tier!'))
        self.assertEqual(self._role(), tier('l2'))

    def test_removing_or_swapping_a_tier_role_is_held_too(self):
        p = self.carol.profile
        p.global_role_template = tier('l3')
        p.save()
        self._edit_role(self.plain)
        self.assertEqual(self._role(), tier('l3'))
        self.assertEqual(self._change().payload['role_template'], self.plain.pk)

    def test_roles_without_a_tier_apply_at_once(self):
        self._edit_role(self.plain)
        self.assertEqual(self._role(), self.plain)
        self.assertFalse(ProtectedChange.objects.filter(kind='global_role').exists())

    def test_the_rest_of_the_edit_still_saves(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('accounts:user_edit', args=[self.carol.pk]), {
            'username': 'carol', 'email': 'carol@msp.test', 'first_name': 'Carol', 'last_name': '',
            'is_active': 'on', 'user_type': 'staff', 'global_role_template': str(tier('l1').pk)})
        self.carol.refresh_from_db()
        self.assertEqual(self.carol.first_name, 'Carol')
        self.assertIsNone(self._role())

    def test_creating_a_user_with_a_tier_role_holds_the_role(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('accounts:user_create'), {
            'username': 'dave', 'email': 'dave@msp.test', 'first_name': '', 'last_name': '',
            'user_type': 'staff', 'global_role_template': str(tier('l1').pk),
            'password1': 'pw-dave-tier-long!', 'password2': 'pw-dave-tier-long!'})
        dave = User.objects.get(username='dave')
        self.assertIsNone(dave.profile.global_role_template)
        self.assertTrue(ProtectedChange.objects.filter(kind='global_role', target_user=dave).exists())

    def test_a_single_administrator_cannot_give_a_tier(self):
        self.bob.delete()
        r = self._edit_role(tier('l2'))
        self.assertEqual(r.status_code, 200)  # the form comes back with the reason
        self.assertIsNone(self._role())
        self.assertFalse(ProtectedChange.objects.filter(kind='global_role').exists())

    def test_the_role_changed_since_the_request_refuses_the_approval(self):
        self._edit_role(tier('l2'))
        change = self._change()
        protected.confirm(change, fresh(self.alice, 'pw-alice-tier!'))
        p = self.carol.profile
        p.global_role_template = self.plain
        p.save()
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(change, fresh(self.bob, 'pw-bob-tier!'))
        self.assertEqual(self._role(), self.plain)

    def test_a_change_outside_the_application_is_audited(self):
        p = self.carol.profile
        p.global_role_template = tier('l3')
        p.save()
        row = AuditLog.objects.get(extra_data__event='rmm_tier_changed_outside_approval')
        self.assertEqual(row.extra_data['target'], 'carol')


class TemplateTierTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.alice = User.objects.create_superuser('alice', 'alice@msp.test', 'pw-alice-tier!')
        self.bob = User.objects.create_superuser('bob', 'bob@msp.test', 'pw-bob-tier!')
        self.role = RoleTemplate.objects.create(name='Night desk', is_system_template=True, tickets_view=True)

    def test_setting_a_templates_tier_takes_two_administrators(self):
        change = services.propose_rmm_tier(self.role, 'l3', self.alice)
        self.role.refresh_from_db()
        self.assertEqual(self.role.rmm_tier, '')
        protected.confirm(change, fresh(self.alice, 'pw-alice-tier!'))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(change, fresh(self.alice, 'pw-alice-tier!'))
        protected.approve(change, fresh(self.bob, 'pw-bob-tier!'))
        self.role.refresh_from_db()
        self.assertEqual(self.role.rmm_tier, 'l3')

    def test_a_holder_of_the_template_cannot_approve_its_tier(self):
        p = self.bob.profile
        p.user_type, p.global_role_template = UserType.STAFF, self.role
        p.save()
        change = services.propose_rmm_tier(self.role, 'l2', self.alice)
        protected.confirm(change, fresh(self.alice, 'pw-alice-tier!'))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(change, fresh(self.bob, 'pw-bob-tier!'))

    def test_unknown_tier_and_no_change_are_refused(self):
        with self.assertRaises(ValueError):
            services.propose_rmm_tier(self.role, 'l9', self.alice)
        with self.assertRaises(ValueError):
            services.propose_rmm_tier(self.role, '', self.alice)

    def test_a_tier_change_outside_the_application_is_audited(self):
        self.role.rmm_tier = 'l1'
        self.role.save()
        row = AuditLog.objects.get(extra_data__event='rmm_tier_changed_outside_approval')
        self.assertEqual(row.extra_data['template'], 'Night desk')
