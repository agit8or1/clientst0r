"""Roles & permissions program (authz-tech): server-side vault checks.

Every test here is a regression test for a hole closed in this branch:
web TOTP / QR skipped the reveal-approval requirement, customer members
passed vault writes on any *_create flag, access-rule management combined a
flag from one customer with another customer's rules, any technician could
approve reveal requests anywhere, and link-only secure notes were readable by
primary key.
"""
import re

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization, SecureNote
from psa.tests._base import _make_msp_tech
from vault.models import Password, VaultAccessRule, VaultRevealRequest
from vault.tests_extension_gate import TEST_MIDDLEWARE


def _login(client, user, org=None):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.id
    s.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VaultAuthzTechTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Vault A', slug='authz-vault-a')
        cls.b = Organization.objects.create(name='Vault B', slug='authz-vault-b')
        # Can read + reveal, may create docs, but has no vault write flags.
        cls.docs_writer = RoleTemplate.objects.create(
            name='authz docs writer', vault_view=True, vault_view_password=True,
            vault_create=False, vault_edit=False, vault_delete=False, docs_create=True)
        cls.rules_admin = RoleTemplate.objects.create(
            name='authz rules admin', vault_view=True, vault_view_password=True,
            vault_manage_access_rules=True)
        cls.viewer = RoleTemplate.objects.create(
            name='authz vault viewer', vault_view=True, vault_view_password=False,
            vault_manage_access_rules=False)

        cls.member = User.objects.create_user('authz-vault-member', password='pw')
        Membership.objects.create(user=cls.member, organization=cls.a, role=Role.EDITOR,
                                  role_template=cls.docs_writer)
        cls.rules_user = User.objects.create_user('authz-vault-rules', password='pw')
        Membership.objects.create(user=cls.rules_user, organization=cls.a, role=Role.ADMIN,
                                  role_template=cls.rules_admin)
        Membership.objects.create(user=cls.rules_user, organization=cls.b, role=Role.READONLY,
                                  role_template=cls.viewer)
        cls.su = User.objects.create_superuser('authz-vault-su', 'su@x.test', 'pw')

        cls.otp = Password.objects.create(organization=cls.a, title='MFA seed',
                                          password_type='otp', requires_reveal_approval=True)
        cls.otp.set_otp_secret('JBSWY3DPEHPK3PXP')
        cls.otp.save()
        cls.entry = Password.objects.create(organization=cls.a, title='Router', username='admin')
        cls.entry.set_password('s3cret-value')
        cls.entry.save()
        cls.rule_b = VaultAccessRule.objects.create(
            organization=cls.b, name='Block B abroad', effect='deny', scope='organization',
            blocked_countries=['RU'])

    def setUp(self):
        cache.clear()
        self.c = Client()

    # --- TOTP / QR -----------------------------------------------------------

    def test_web_totp_and_qr_need_reveal_approval(self):
        _login(self.c, self.member, self.a)
        for name in ('vault:generate_otp', 'vault:password_qrcode'):
            with self.subTest(name):
                resp = self.c.get(reverse(name, args=[self.otp.pk]))
                self.assertEqual(resp.status_code, 403)
                self.assertTrue(resp.json().get('requires_approval'))

    # --- writes --------------------------------------------------------------

    def test_member_without_vault_edit_cannot_edit_or_delete(self):
        _login(self.c, self.member, self.a)
        resp = self.c.post(reverse('vault:password_edit', args=[self.entry.pk]),
                           {'title': 'Hijacked', 'password_type': 'website'})
        self.assertEqual(resp.status_code, 403)
        resp = self.c.post(reverse('vault:password_delete', args=[self.entry.pk]))
        self.assertEqual(resp.status_code, 403)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.title, 'Router')

    def test_member_without_vault_create_cannot_create(self):
        _login(self.c, self.member, self.a)
        before = Password.objects.count()
        resp = self.c.post(reverse('vault:password_create'),
                           {'title': 'New', 'password_type': 'website', 'password': 'x'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Password.objects.count(), before)

    # --- access rules ----------------------------------------------------------

    def test_rules_flag_in_one_customer_does_not_reach_another(self):
        _login(self.c, self.rules_user, self.b)
        resp = self.c.post(reverse('vault:access_rule_delete', args=[self.rule_b.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(VaultAccessRule.objects.filter(pk=self.rule_b.pk).exists())
        # In their own customer the page still works.
        _login(self.c, self.rules_user, self.a)
        self.assertEqual(self.c.get(reverse('vault:access_rule_list')).status_code, 200)

    def test_rule_target_password_must_belong_to_rule_customer(self):
        other = Password.objects.create(organization=self.b, title='B entry')
        _login(self.c, self.rules_user, self.a)
        self.c.post(reverse('vault:access_rule_create'), {
            'name': 'forged', 'effect': 'allow', 'scope': 'item',
            'target_password': str(other.pk), 'priority': '10', 'is_active': 'on'})
        self.assertFalse(VaultAccessRule.objects.filter(name='forged').exists())

    # --- reveal approvals ------------------------------------------------------

    def test_technician_without_vault_rights_cannot_approve(self):
        requester = User.objects.create_user('authz-vault-req', password='pw')
        req = VaultRevealRequest.objects.create(password=self.otp, requester=requester,
                                                justification='need it')
        tech = _make_msp_tech(User.objects.create_user('authz-vault-tech', password='pw'))
        _login(self.c, tech, self.a)
        resp = self.c.post(reverse('vault:reveal_request_decide', args=[req.pk]),
                           {'decision': 'approve'})
        self.assertEqual(resp.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')
        # A technician who holds reveal rights at that customer may.
        Membership.objects.create(user=tech, organization=self.a, role=Role.ADMIN,
                                  role_template=self.rules_admin)
        resp = self.c.post(reverse('vault:reveal_request_decide', args=[req.pk]),
                           {'decision': 'approve'})
        self.assertEqual(resp.status_code, 200)

    def test_reveal_request_list_scoped_to_vault_view(self):
        requester = User.objects.create_user('authz-vault-req2', password='pw')
        b_entry = Password.objects.create(organization=self.b, title='Clinic payroll admin')
        VaultRevealRequest.objects.create(password=b_entry, requester=requester, justification='x')
        tech = _make_msp_tech(User.objects.create_user('authz-vault-tech2', password='pw'))
        Membership.objects.create(user=tech, organization=self.a, role=Role.READONLY,
                                  role_template=self.viewer)
        _login(self.c, tech, self.a)
        resp = self.c.get(reverse('vault:reveal_request_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Clinic payroll admin')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecureNoteByIdTests(TestCase):
    def test_link_only_note_not_readable_by_primary_key(self):
        org = Organization.objects.create(name='Note A', slug='authz-note-a')
        other_org = Organization.objects.create(name='Note B', slug='authz-note-b')
        sender = User.objects.create_user('authz-note-sender', password='pw')
        Membership.objects.create(user=sender, organization=org, role=Role.OWNER)
        outsider = User.objects.create_user('authz-note-outsider', password='pw')
        Membership.objects.create(user=outsider, organization=other_org, role=Role.OWNER)
        c = Client()
        _login(c, sender, org)
        resp = c.post('/core/secure-notes/create/', {
            'title': 'wifi', 'content': 'the-wifi-password', 'link_only': 'on'})
        token = re.search(r'/core/secret/([^/]+)/', resp.context['share_url']).group(1)
        note = SecureNote.objects.get(title='wifi')

        c2 = Client()
        _login(c2, outsider, other_org)
        resp = c2.get(f'/core/secure-notes/{note.pk}/', follow=True)
        self.assertNotContains(resp, 'the-wifi-password')
        note.refresh_from_db()
        self.assertFalse(note.is_deleted)
        # The secret link still works.
        self.assertContains(Client().get(f'/core/secret/{token}/'), 'the-wifi-password')

    def test_recipients_limited_to_customer_members_and_staff(self):
        org = Organization.objects.create(name='Note C', slug='authz-note-c')
        other_org = Organization.objects.create(name='Note D', slug='authz-note-d')
        sender = User.objects.create_user('authz-note-s2', password='pw')
        Membership.objects.create(user=sender, organization=org, role=Role.OWNER)
        stranger = User.objects.create_user('authz-note-stranger', password='pw')
        Membership.objects.create(user=stranger, organization=other_org, role=Role.OWNER)
        colleague = User.objects.create_user('authz-note-colleague', password='pw')
        Membership.objects.create(user=colleague, organization=org, role=Role.EDITOR)
        c = Client()
        _login(c, sender, org)
        c.post('/core/secure-notes/create/', {
            'title': 'hello', 'content': 'body', 'recipients': [str(stranger.pk), str(colleague.pk)]})
        note = SecureNote.objects.get(title='hello')
        self.assertEqual(list(note.recipients.values_list('pk', flat=True)), [colleague.pk])
