"""v3.17.659: the password page always shows a Notes card and a Two-factor
card; secure notes are encrypted at rest and only come out of the audited,
rate-limited, approval-gated reveal endpoint."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from vault.models import Password, VaultRevealRequest, WebExtensionAuthToken
from vault.tests_extension_gate import TEST_MIDDLEWARE

SECRET_NOTE = 'Recovery codes: 1111-2222 3333-4444'


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


def _raw(pk, column):
    with connection.cursor() as cur:
        cur.execute(f'SELECT {connection.ops.quote_name(column)} FROM passwords WHERE id = %s', [pk])
        return cur.fetchone()[0]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecureNotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Notes Org', slug='notes-org-657')
        cls.other = Organization.objects.create(name='Other Org', slug='other-org-657')
        cls.owner = User.objects.create_user('notes-owner', password='pw-657-owner!')
        Membership.objects.create(user=cls.owner, organization=cls.org, role=Role.OWNER, is_active=True)
        cls.reader = User.objects.create_user('notes-reader', password='pw-657-reader!')
        Membership.objects.create(user=cls.reader, organization=cls.org, role=Role.READONLY, is_active=True)

        cls.bare = Password(organization=cls.org, title='Bare entry', username='u')
        cls.bare.set_password('bare-pass')
        cls.bare.save()
        cls.full = Password(organization=cls.org, title='Full entry', username='admin',
                            notes='Plain note visible to everyone', otp_issuer='Example')
        cls.full.set_password('full-pass')
        cls.full.set_secure_notes(SECRET_NOTE)
        cls.full.set_otp_secret('JBSWY3DPEHPK3PXPJBSWY3DP')
        cls.full.save()

    def setUp(self):
        cache.clear()
        self.c = Client()
        _login(self.c, self.owner, self.org)

    def _detail(self, pw, client=None):
        resp = (client or self.c).get(reverse('vault:password_detail', args=[pw.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _reveal(self, pw, client=None):
        return (client or self.c).post(reverse('vault:password_reveal', args=[pw.pk]) + '?field=secure_notes')

    # --- cards -------------------------------------------------------------

    def test_empty_entry_shows_notes_and_two_factor_cards(self):
        html = self._detail(self.bare)
        self.assertIn('id="notes-card"', html)
        self.assertIn('No notes yet', html)
        self.assertIn('id="secure-notes-empty"', html)
        self.assertIn('No 2FA secret stored', html)
        self.assertIn('id="add-2fa-link"', html)
        self.assertIn(reverse('vault:password_edit', args=[self.bare.pk]) + '#section-otp', html)
        self.assertIn('Add notes', html)

    def test_read_only_user_sees_empty_states_without_edit_links(self):
        c = Client()
        _login(c, self.reader, self.org)
        html = self._detail(self.bare, c)
        self.assertIn('No notes yet', html)
        self.assertIn('No 2FA secret stored', html)
        self.assertNotIn('id="add-2fa-link"', html)
        self.assertNotIn('#notes-section', html)

    def test_filled_entry_shows_notes_live_code_and_masked_secure_notes(self):
        html = self._detail(self.full)
        self.assertIn('Plain note visible to everyone', html)
        self.assertNotIn('No notes yet', html)
        self.assertIn('id="otp-code"', html)
        self.assertNotIn('No 2FA secret stored', html)
        self.assertIn('reveal-secure-notes-btn', html)
        self.assertNotIn(SECRET_NOTE, html)
        self.assertNotIn('1111-2222', html)

    # --- encryption at rest --------------------------------------------------

    def test_secure_notes_are_encrypted_at_rest(self):
        raw = _raw(self.full.pk, 'encrypted_notes')
        self.assertTrue(raw)
        self.assertNotIn('1111-2222', raw)
        self.assertNotIn('Recovery', raw)
        fresh = Password.objects.get(pk=self.full.pk)
        self.assertEqual(fresh.get_secure_notes(), SECRET_NOTE)
        # Bound to the entry's organization: the same ciphertext under another
        # customer does not decrypt.
        moved = Password(organization=self.other, encrypted_notes=raw)
        with self.assertRaises(Exception):
            moved.get_secure_notes()

    def test_form_seals_replaces_keeps_and_clears(self):
        url = reverse('vault:password_edit', args=[self.bare.pk])
        base = {'title': 'Bare entry', 'password_type': 'website', 'username': 'u',
                'hibp_scan_frequency': '24', 'client_access_mode': 'none'}
        with self.settings(HIBP_CHECK_ON_SAVE=False):
            resp = self.c.post(url, {**base, 'plaintext_secure_notes': 'PIN 4321'})
            self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context['form'].errors)
            pw = Password.objects.get(pk=self.bare.pk)
            self.assertEqual(pw.get_secure_notes(), 'PIN 4321')
            self.assertNotIn('4321', _raw(pw.pk, 'encrypted_notes'))
            # The edit form never echoes the stored notes.
            self.assertNotIn('PIN 4321', self.c.get(url).content.decode())
            # Blank keeps them.
            self.c.post(url, {**base, 'plaintext_secure_notes': ''})
            self.assertEqual(Password.objects.get(pk=pw.pk).get_secure_notes(), 'PIN 4321')
            # The clear box removes them.
            self.c.post(url, {**base, 'clear_secure_notes': 'on'})
            self.assertEqual(Password.objects.get(pk=pw.pk).encrypted_notes, '')

    # --- reveal --------------------------------------------------------------

    def test_reveal_returns_secure_notes_and_is_audited(self):
        resp = self._reveal(self.full)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'secure_notes': SECRET_NOTE})
        log = AuditLog.objects.filter(action='reveal', object_id=self.full.pk,
                                      extra_data__field='secure_notes').first()
        self.assertIsNotNone(log)
        self.assertIn('Secure notes', log.description)

    def test_reveal_of_entry_without_secure_notes_is_404(self):
        self.assertEqual(self._reveal(self.bare).status_code, 404)

    def test_reveal_needs_reveal_permission(self):
        c = Client()
        outsider = User.objects.create_user('notes-outsider', password='pw-657-out!')
        Membership.objects.create(user=outsider, organization=self.other, role=Role.OWNER, is_active=True)
        _login(c, outsider, self.other)
        resp = self._reveal(self.full, c)
        self.assertIn(resp.status_code, (403, 404))
        self.assertNotIn('1111-2222', resp.content.decode())

    def test_reveal_shares_the_vault_reveal_rate_limit(self):
        for _ in range(30):
            self.c.post(reverse('vault:password_reveal', args=[self.full.pk]))
        resp = self._reveal(self.full)
        self.assertIn(resp.status_code, (403, 429))
        self.assertNotIn('1111-2222', resp.content.decode())

    def test_approval_gated_entry_needs_an_approval_for_secure_notes(self):
        Password.objects.filter(pk=self.full.pk).update(requires_reveal_approval=True)
        resp = self._reveal(self.full)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(resp.json().get('requires_approval'))
        self.assertNotIn('1111-2222', resp.content.decode())
        approval = VaultRevealRequest.objects.create(
            password=self.full, requester=self.owner, status='approved', decided_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1), justification='test')
        resp = self._reveal(self.full)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['secure_notes'], SECRET_NOTE)
        approval.refresh_from_db()
        self.assertIsNotNone(approval.revealed_at)
        # Single use: the next reveal needs a new approval.
        self.assertEqual(self._reveal(self.full).status_code, 403)

    # --- other channels ------------------------------------------------------

    def test_extension_api_never_returns_secure_notes(self):
        secret, _ = WebExtensionAuthToken.issue(user=self.owner, organization=self.org)
        raw = _raw(self.full.pk, 'encrypted_notes')
        auth = {'HTTP_AUTHORIZATION': f'Bearer {secret}'}
        with patch('vault.extension_views._has_extension_permission', return_value=True):
            sync = Client().get('/vault/api/extension/sync/', **auth)
            autofill = Client().get('/vault/api/extension/autofill/', {'url': 'https://example.com'}, **auth)
            reveal = Client().post(f'/vault/api/extension/{self.full.pk}/reveal/', **auth)
        self.assertEqual(sync.status_code, 200)
        for resp in (sync, autofill, reveal):
            body = resp.content.decode()
            self.assertNotIn('1111-2222', body)
            self.assertNotIn(raw, body)
            self.assertNotIn('secure_notes', body)
            self.assertNotIn('encrypted_notes', body)

    def test_rest_api_does_not_return_secure_notes(self):
        from api.serializers import PasswordDetailSerializer
        self.assertNotIn('encrypted_notes', PasswordDetailSerializer.Meta.fields)
        self.assertNotIn('secure_notes', PasswordDetailSerializer.Meta.fields)

    def test_export_carries_ciphertext_only(self):
        from core.settings_views import _serialize_password
        data = _serialize_password(Password.objects.get(pk=self.full.pk), 'json')
        self.assertEqual(data['secure_notes_encrypted'], _raw(self.full.pk, 'encrypted_notes'))
        self.assertNotIn('1111-2222', str(data))

    def test_key_rotation_covers_secure_notes(self):
        from vault.secret_fields import V2_ROW_FIELDS
        self.assertIn(('vault', 'Password', 'encrypted_notes'), {r[:3] for r in V2_ROW_FIELDS})
