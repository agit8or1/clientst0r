"""Background LDAP group mapping sync (accounts.ldap_group_sync).

Same fake directory as tests_ldap: ldap.initialize is patched, so the sync
runs its real code path against an in-memory directory.
"""
from datetime import timedelta
from io import StringIO

from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from accounts.ldap_group_sync import run_sync
from accounts.models import LDAPGroupMapping, Membership, RoleTemplate, UserProfile
from accounts.tests_ldap import (
    ALICE_DN, ALICE_PASSWORD, APP_USERS, BOB_DN, BOB_PASSWORD, CAROL_PASSWORD, NESTED,
    LDAPTestBase,
)
from audit.models import AuditLog
from core.models import Organization, ScheduledTask


class LDAPGroupBackgroundSyncTests(LDAPTestBase):

    def setUp(self):
        super().setUp()
        self.acme = Organization.objects.create(name='Acme', slug='lgs-acme')
        self.bravo = Organization.objects.create(name='Bravo', slug='lgs-bravo')
        self.viewer = RoleTemplate.objects.create(name='Viewer', is_system_template=True)
        self.mapping = LDAPGroupMapping.objects.create(
            group_dn=APP_USERS, organization=self.acme, role_template=self.viewer)
        self.alice = self.auth('alice', ALICE_PASSWORD)
        self.assertTrue(self._m('alice', self.acme).is_active)
        self._make_due()

    def _m(self, username, org):
        return Membership.objects.filter(user__username=username, organization=org).first()

    def _make_due(self):
        UserProfile.objects.update(ldap_groups_checked_at=None)

    def _remove_alice_from_group(self):
        self.directory.entries[APP_USERS.lower()]['member'] = [NESTED]

    # --- removals -------------------------------------------------------

    def test_removed_from_group_loses_membership_without_signing_in(self):
        self._remove_alice_from_group()
        report = run_sync()
        self.assertEqual(report.status, 'ok')
        m = self._m('alice', self.acme)
        self.assertFalse(m.is_active)
        self.assertIn(('alice', 'deactivate', self.acme.pk), report.changes)
        log = AuditLog.objects.get(object_type='membership', object_id=m.pk,
                                   extra_data__deactivated=True)
        self.assertEqual(log.extra_data['trigger'], 'background_sync')
        self.assertTrue(AuditLog.objects.filter(object_type='ldap_group_sync').exists())

    def test_still_member_is_unchanged(self):
        report = run_sync()
        self.assertEqual(report.changes, [])
        self.assertTrue(self._m('alice', self.acme).is_active)
        self.assertEqual(report.checked, 1)

    def test_manual_membership_is_never_touched(self):
        manual = Membership.objects.create(user=self.alice, organization=self.bravo,
                                           role_template=self.viewer)
        self._remove_alice_from_group()
        run_sync()
        manual.refresh_from_db()
        self.assertTrue(manual.is_active)

    # --- grants ---------------------------------------------------------

    def test_added_to_group_gets_membership(self):
        self.auth('bob', BOB_PASSWORD)  # LDAP user, not a member yet
        self.assertIsNone(self._m('bob', self.acme))
        self.directory.entries[APP_USERS.lower()]['member'].append(BOB_DN)
        self._make_due()
        run_sync()
        m = self._m('bob', self.acme)
        self.assertTrue(m.is_active)
        self.assertEqual(m.ldap_group_mapping, self.mapping)

    # --- fail safe ------------------------------------------------------

    def test_directory_unreachable_changes_nothing_and_reports(self):
        self._remove_alice_from_group()
        self.directory.down = True
        report = run_sync()
        self.assertEqual(report.status, 'failed')
        self.assertIn('nothing changed', report.message)
        self.assertTrue(self._m('alice', self.acme).is_active)
        # The user was not marked checked, so the next run retries them.
        self.assertIsNone(UserProfile.objects.get(user=self.alice).ldap_groups_checked_at)
        with self.assertRaises(CommandError):
            call_command('ldap_group_sync', stdout=StringIO())

    def test_bad_service_bind_changes_nothing(self):
        self._remove_alice_from_group()
        self.directory.passwords[next(iter(self.directory.passwords))] = 'changed'
        report = run_sync()
        self.assertEqual(report.status, 'failed')
        self.assertTrue(self._m('alice', self.acme).is_active)

    def test_user_missing_from_directory_is_skipped_not_deactivated(self):
        del self.directory.entries[ALICE_DN.lower()]
        report = run_sync()
        self.assertIn('alice', report.not_found)
        self.assertTrue(self._m('alice', self.acme).is_active)

    def test_unreadable_group_skips_that_customer(self):
        # Group gone from the directory (or unreadable): neither "member"
        # nor "not a member" is known, so no removal and no grant there.
        del self.directory.entries[APP_USERS.lower()]
        self.auth('carol', CAROL_PASSWORD)
        self._make_due()
        report = run_sync()
        self.assertTrue(self._m('alice', self.acme).is_active)
        self.assertIn(('alice', self.acme.pk), report.uncertain)
        self.assertEqual(report.changes, [])

    def test_directory_lost_mid_run_stops_without_changes_for_the_rest(self):
        self.auth('bob', BOB_PASSWORD)
        self._make_due()
        self._remove_alice_from_group()
        from accounts import ldap_group_sync
        real = ldap_group_sync._find_user
        calls = []

        def flaky(conn, cfg, username):
            calls.append(username)
            if len(calls) > 1:
                raise ldap_group_sync.DirectoryUnavailable('gone')
            return real(conn, cfg, username)

        UserProfile.objects.filter(user=self.alice).update(
            ldap_groups_checked_at=timezone.now() - timedelta(days=2))
        UserProfile.objects.filter(user__username='bob').update(
            ldap_groups_checked_at=timezone.now() - timedelta(days=3))
        from unittest import mock
        with mock.patch.object(ldap_group_sync, '_find_user', side_effect=flaky):
            report = run_sync()
        self.assertEqual(report.status, 'failed')
        self.assertEqual(calls, ['bob', 'alice'])
        self.assertTrue(self._m('alice', self.acme).is_active)

    def test_ldap_disabled_is_a_noop(self):
        self.configure(ldap_enabled=False)
        self._remove_alice_from_group()
        report = run_sync()
        self.assertEqual(report.status, 'skipped')
        self.assertTrue(self._m('alice', self.acme).is_active)
        self.assertEqual(self.initialize.call_count, 1)  # only alice's sign-in

    # --- throttle / batch -------------------------------------------------

    def test_throttled_per_user(self):
        run_sync()
        self._remove_alice_from_group()
        report = run_sync()
        self.assertEqual(report.checked, 0)
        self.assertTrue(self._m('alice', self.acme).is_active)
        UserProfile.objects.filter(user=self.alice).update(
            ldap_groups_checked_at=timezone.now() - timedelta(hours=2))
        run_sync()
        self.assertFalse(self._m('alice', self.acme).is_active)

    def test_batch_is_bounded_oldest_first(self):
        self.auth('bob', BOB_PASSWORD)
        self.auth('carol', CAROL_PASSWORD)
        now = timezone.now()
        UserProfile.objects.filter(user__username='alice').update(ldap_groups_checked_at=now - timedelta(days=1))
        UserProfile.objects.filter(user__username='bob').update(ldap_groups_checked_at=None)
        UserProfile.objects.filter(user__username='carol').update(ldap_groups_checked_at=now - timedelta(days=5))
        report = run_sync(batch_size=2)
        self.assertEqual(report.checked, 2)
        checked = set(UserProfile.objects.filter(
            ldap_groups_checked_at__gt=now - timedelta(minutes=1)).values_list('user__username', flat=True))
        self.assertEqual(checked, {'bob', 'carol'})

    # --- sessions -------------------------------------------------------

    def _session_for(self, user, **data):
        client = Client()
        client.force_login(user, backend='django.contrib.auth.backends.ModelBackend')
        session = client.session
        for k, v in data.items():
            session[k] = v
        session.save()
        return session.session_key

    def test_sign_in_keeps_auth_source_ldap_after_login_saves_the_user(self):
        # login() saves the user; the profile cached on it must not undo
        # the auth_source the backend just set (else the sync skips them).
        self.alice.save()
        self.assertEqual(UserProfile.objects.get(user=self.alice).auth_source, 'ldap')

    def test_user_with_no_access_left_is_signed_out(self):
        key = self._session_for(self.alice, current_organization_id=self.acme.pk)
        self._remove_alice_from_group()
        report = run_sync()
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(report.sessions_ended, 1)

    def test_session_drops_only_the_removed_customer(self):
        Membership.objects.create(user=self.alice, organization=self.bravo, role_template=self.viewer)
        key = self._session_for(self.alice, current_organization_id=self.acme.pk,
                                portal_org_id=self.acme.pk)
        other_key = self._session_for(self.alice, current_organization_id=self.bravo.pk)
        self._remove_alice_from_group()
        report = run_sync()
        data = Session.objects.get(session_key=key).get_decoded()
        self.assertIsNone(data.get('current_organization_id'))
        self.assertIsNone(data.get('portal_org_id'))
        self.assertEqual(Session.objects.get(session_key=other_key).get_decoded()
                         ['current_organization_id'], self.bravo.pk)
        self.assertEqual(report.sessions_trimmed, 1)

    # --- scheduler wiring -------------------------------------------------

    def test_scheduler_task_is_seeded_and_dispatches_the_command(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='ldap_group_sync')
        self.assertTrue(task.enabled)
        self.assertEqual(COMMAND_TASKS['ldap_group_sync'][0], 'ldap_group_sync')
        self._remove_alice_from_group()
        call_command('ldap_group_sync', stdout=StringIO())
        self.assertFalse(self._m('alice', self.acme).is_active)
