"""LDAP group -> customer membership mappings (accounts.ldap_mapping).

Uses the fake directory from accounts.tests_ldap: ldap.initialize is patched,
so django-auth-ldap and our backend run their real code paths.
"""
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from accounts.models import LDAPGroupMapping, Membership, RoleTemplate
from accounts.tests_ldap import (
    ALICE_DN, ALICE_PASSWORD, APP_USERS, BOB_PASSWORD, CAROL_PASSWORD, NESTED,
    STAFF, TEST_MIDDLEWARE, LDAPTestBase,
)
from audit.models import AuditLog
from core.models import Organization

User = get_user_model()


class LDAPGroupMappingSignInTests(LDAPTestBase):

    def setUp(self):
        super().setUp()
        self.acme = Organization.objects.create(name='Acme', slug='ldm-acme')
        self.bravo = Organization.objects.create(name='Bravo', slug='ldm-bravo')
        self.viewer = RoleTemplate.objects.create(name='Viewer', is_system_template=True)
        self.editor = RoleTemplate.objects.create(name='Editor role', is_system_template=True)
        self.bravo_only = RoleTemplate.objects.create(name='Bravo custom', organization=self.bravo)

    def _map(self, dn, org, role, **kw):
        return LDAPGroupMapping.objects.create(group_dn=dn, organization=org, role_template=role, **kw)

    def _membership(self, username, org):
        return Membership.objects.filter(user__username=username, organization=org).first()

    def test_mapped_group_creates_membership_with_role(self):
        mapping = self._map(APP_USERS, self.acme, self.viewer)
        user = self.auth('alice', ALICE_PASSWORD)
        self.assertIsNotNone(user)
        m = self._membership('alice', self.acme)
        self.assertTrue(m.is_active)
        self.assertEqual(m.role_template, self.viewer)
        self.assertEqual(m.ldap_group_mapping, mapping)
        log = AuditLog.objects.get(object_type='membership', object_id=m.pk, action='create',
                                   extra_data__source='ldap_group_mapping')
        self.assertEqual(log.organization, self.acme)
        self.assertEqual(log.extra_data['source'], 'ldap_group_mapping')
        self.assertIn(APP_USERS, log.description)

    def test_nested_group_counts(self):
        self._map(APP_USERS, self.acme, self.viewer)
        self.auth('carol', CAROL_PASSWORD)  # in NESTED, which is in APP_USERS
        self.assertTrue(self._membership('carol', self.acme).is_active)

    def test_non_member_gets_nothing(self):
        self._map(APP_USERS, self.acme, self.viewer)
        self.assertIsNotNone(self.auth('bob', BOB_PASSWORD))
        self.assertFalse(Membership.objects.filter(user__username='bob').exists())

    def test_group_dn_is_case_insensitive(self):
        self._map(APP_USERS.upper(), self.acme, self.viewer)
        self.auth('alice', ALICE_PASSWORD)
        self.assertIsNotNone(self._membership('alice', self.acme))
        self.assertEqual(LDAPGroupMapping.objects.get().group_dn_normalized, APP_USERS.lower())

    def test_mapping_only_creates_its_own_customer(self):
        self._map(APP_USERS, self.acme, self.viewer)
        self.auth('alice', ALICE_PASSWORD)
        self.assertFalse(Membership.objects.filter(user__username='alice', organization=self.bravo).exists())
        self.assertEqual(Membership.objects.filter(user__username='alice').count(), 1)

    def test_role_from_another_customer_is_never_applied(self):
        self._map(APP_USERS, self.acme, self.bravo_only)  # invalid: Bravo's own role
        self.auth('alice', ALICE_PASSWORD)
        self.assertFalse(Membership.objects.filter(user__username='alice').exists())

    def test_role_change_is_applied_and_audited(self):
        mapping = self._map(APP_USERS, self.acme, self.viewer)
        self.auth('alice', ALICE_PASSWORD)
        mapping.role_template = self.editor
        mapping.save()
        self.auth('alice', ALICE_PASSWORD)
        m = self._membership('alice', self.acme)
        self.assertEqual(m.role_template, self.editor)
        log = AuditLog.objects.filter(object_type='membership', object_id=m.pk, action='update', extra_data__source='ldap_group_mapping').latest('timestamp')
        self.assertIn('Viewer', log.description)
        self.assertIn('Editor role', log.description)

    def test_removed_from_group_deactivates_and_return_reactivates(self):
        self._map(APP_USERS, self.acme, self.viewer)
        self.auth('alice', ALICE_PASSWORD)
        group = self.directory.entries[APP_USERS.lower()]
        group['member'] = [NESTED]
        self.assertIsNotNone(self.auth('alice', ALICE_PASSWORD))
        m = self._membership('alice', self.acme)
        self.assertFalse(m.is_active)
        self.assertTrue(AuditLog.objects.filter(
            object_type='membership', object_id=m.pk, extra_data__deactivated=True).exists())
        group['member'] = [ALICE_DN, NESTED]
        self.auth('alice', ALICE_PASSWORD)
        m.refresh_from_db()
        self.assertTrue(m.is_active)

    def test_paused_mapping_deactivates_its_memberships(self):
        mapping = self._map(APP_USERS, self.acme, self.viewer)
        self.auth('alice', ALICE_PASSWORD)
        mapping.is_active = False
        mapping.save()
        self.auth('alice', ALICE_PASSWORD)
        self.assertFalse(self._membership('alice', self.acme).is_active)

    def test_manual_membership_is_never_touched(self):
        self._map(APP_USERS, self.acme, self.viewer)
        alice = self.auth('alice', ALICE_PASSWORD)
        Membership.objects.filter(user=alice).delete()
        manual_role = RoleTemplate.objects.create(name='Manual', is_system_template=True)
        manual = Membership.objects.create(user=alice, organization=self.acme, role_template=manual_role)
        other = Membership.objects.create(user=alice, organization=self.bravo, role_template=manual_role)
        self.auth('alice', ALICE_PASSWORD)  # in group: manual one must keep its role
        manual.refresh_from_db()
        self.assertEqual(manual.role_template, manual_role)
        self.assertIsNone(manual.ldap_group_mapping)
        self.directory.entries[APP_USERS.lower()]['member'] = []
        self.auth('alice', ALICE_PASSWORD)  # out of group: still untouched
        manual.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(manual.is_active)
        self.assertTrue(other.is_active)

    def test_two_customers_from_two_groups(self):
        self._map(APP_USERS, self.acme, self.viewer)
        self._map(STAFF, self.bravo, self.bravo_only)
        self.auth('alice', ALICE_PASSWORD)
        self.assertEqual(self._membership('alice', self.acme).role_template, self.viewer)
        self.assertEqual(self._membership('alice', self.bravo).role_template, self.bravo_only)
        # Leaving the staff group removes Bravo only.
        self.directory.entries[STAFF.lower()]['member'] = []
        self.auth('alice', ALICE_PASSWORD)
        self.assertTrue(self._membership('alice', self.acme).is_active)
        self.assertFalse(self._membership('alice', self.bravo).is_active)

    def test_missing_group_in_directory_is_not_membership(self):
        self._map('cn=gone,ou=groups,dc=example,dc=com', self.acme, self.viewer)
        self.assertIsNotNone(self.auth('alice', ALICE_PASSWORD))
        self.assertFalse(Membership.objects.filter(user__username='alice').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LDAPGroupMappingPageTests(LDAPTestBase):
    enable = False

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('ldm-root', 'r@example.com', 'Root-Admin-Pw-1')
        self.client = Client()
        self.client.force_login(self.admin)
        self.acme = Organization.objects.create(name='Acme', slug='ldmp-acme')
        self.bravo = Organization.objects.create(name='Bravo', slug='ldmp-bravo')
        self.viewer = RoleTemplate.objects.create(name='Viewer', is_system_template=True)
        self.bravo_only = RoleTemplate.objects.create(name='Bravo custom', organization=self.bravo)
        self.url = reverse('accounts:ldap_group_mappings')

    def test_add_list_and_audit(self):
        r = self.client.post(self.url, {'group_dn': APP_USERS, 'organization': self.acme.pk,
                                        'role_template': self.viewer.pk})
        self.assertEqual(r.status_code, 302)
        mapping = LDAPGroupMapping.objects.get()
        self.assertEqual(mapping.created_by, self.admin)
        self.assertTrue(AuditLog.objects.filter(object_type='ldap_group_mapping',
                                                object_id=mapping.pk, action='create').exists())
        self.assertContains(self.client.get(self.url), APP_USERS)

    def test_rejects_other_customers_role_and_duplicates(self):
        self.client.post(self.url, {'group_dn': APP_USERS, 'organization': self.acme.pk,
                                    'role_template': self.bravo_only.pk})
        self.assertFalse(LDAPGroupMapping.objects.exists())
        self.client.post(self.url, {'group_dn': APP_USERS, 'organization': self.acme.pk,
                                    'role_template': self.viewer.pk})
        self.client.post(self.url, {'group_dn': APP_USERS.upper(), 'organization': self.acme.pk,
                                    'role_template': self.viewer.pk})
        self.assertEqual(LDAPGroupMapping.objects.count(), 1)

    def test_update_role(self):
        mapping = LDAPGroupMapping.objects.create(group_dn=APP_USERS, organization=self.bravo,
                                                  role_template=self.viewer)
        self.client.post(self.url, {'action': 'update', 'pk': mapping.pk,
                                    'role_template': self.bravo_only.pk, 'is_active': 'on'})
        mapping.refresh_from_db()
        self.assertEqual(mapping.role_template, self.bravo_only)

    def test_delete_deactivates_managed_memberships_only(self):
        mapping = LDAPGroupMapping.objects.create(group_dn=APP_USERS, organization=self.acme,
                                                  role_template=self.viewer)
        u1 = User.objects.create_user('ldm-u1')
        u2 = User.objects.create_user('ldm-u2')
        managed = Membership.objects.create(user=u1, organization=self.acme,
                                            role_template=self.viewer, ldap_group_mapping=mapping)
        manual = Membership.objects.create(user=u2, organization=self.acme, role_template=self.viewer)
        r = self.client.post(reverse('accounts:ldap_group_mapping_delete', args=[mapping.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(LDAPGroupMapping.objects.exists())
        managed.refresh_from_db()
        manual.refresh_from_db()
        self.assertFalse(managed.is_active)
        self.assertTrue(manual.is_active)
        self.assertTrue(AuditLog.objects.filter(object_type='ldap_group_mapping', action='delete').exists())

    def test_non_superusers_are_refused(self):
        staff = User.objects.create_user('ldm-staff', password='Staff-Pw-123456')
        staff.profile.user_type = 'staff'
        staff.profile.save()
        c = Client()
        c.force_login(staff)
        self.assertNotEqual(c.get(self.url).status_code, 200)
        c.post(self.url, {'group_dn': APP_USERS, 'organization': self.acme.pk,
                          'role_template': self.viewer.pk})
        self.assertFalse(LDAPGroupMapping.objects.exists())

    def test_directory_page_links_to_mappings(self):
        self.assertContains(self.client.get(reverse('core:settings_directory')), self.url)
