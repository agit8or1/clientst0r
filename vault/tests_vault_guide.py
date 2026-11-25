"""Fixes found while writing the Password Vault guide (docs/PASSWORD_VAULT.md).

* The vault list's JSON rows are inserted as HTML by DataTables, and the
  title, username and URL were written into it unescaped.
* Approve / Deny on the Reveal Requests page is a plain form post, and the
  view answered it with a raw JSON page.
* Reveals, TOTP codes and breach checks made in global view were filed in the
  audit log with no customer, so the customer's audit log did not show them.
* The audit middleware copied the first 100 characters of a license key, a
  vault entry's secure notes, a secure note's message and a My Vault note into
  the audit log, and recorded secret-link paths (the link's bearer token).
* A secure note sent with "Require password" and an empty password was
  readable with the empty password.
* The password page's copy helper called itself on HTTPS, so Copy failed.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SecureNote
from vault.models import Password, PersonalVault, VaultRevealRequest
from vault.tests_extension_gate import TEST_MIDDLEWARE


def _login(client, user, org=None):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.id
    s.save()


def _form_data(path):
    row = AuditLog.objects.filter(path=path).order_by('-pk').first()
    return (row.extra_data or {}).get('form_data', {}) if row else None


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   HIBP_CHECK_ON_SAVE=False, HIBP_ENABLED=False)
class VaultGuideFixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Guide Vault Org', slug='guide-vault-org')
        cls.owner = User.objects.create_user('guide-vault-owner', password='pw-guide-1!')
        Membership.objects.create(user=cls.owner, organization=cls.org, role=Role.OWNER, is_active=True)
        cls.su = User.objects.create_superuser('guide-vault-su', 'su@guide.example', 'pw')
        cls.pw = Password(organization=cls.org, title='<b>bold</b> entry',
                          username='<i>user</i>',
                          url='https://host.example/"onmouseover="x')
        cls.pw.set_password('guide-secret-1')
        cls.pw.set_otp_secret('JBSWY3DPEHPK3PXPJBSWY3DP')
        cls.pw.save()

    def setUp(self):
        cache.clear()
        self.c = Client()

    def test_list_rows_escape_typed_values(self):
        _login(self.c, self.owner, self.org)
        data = self.c.get(reverse('vault:password_list_datatables')).json()['data']
        row = ''.join(data[0])
        self.assertNotIn('<b>bold</b>', row)
        self.assertIn('&lt;b&gt;bold&lt;/b&gt;', row)
        self.assertNotIn('<i>user</i>', row)
        self.assertNotIn('"onmouseover="', row)

    def test_decide_from_list_redirects_with_message(self):
        requester = User.objects.create_user('guide-vault-req', password='pw')
        req = VaultRevealRequest.objects.create(password=self.pw, requester=requester,
                                                justification='Change window 14:00')
        _login(self.c, self.su)
        resp = self.c.post(reverse('vault:reveal_request_decide', args=[req.pk]),
                           {'decision': 'approve', 'next': 'list'})
        self.assertRedirects(resp, reverse('vault:reveal_request_list'), fetch_redirect_response=False)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        # Deciding again: an error message, still a redirect, not JSON.
        resp = self.c.post(reverse('vault:reveal_request_decide', args=[req.pk]),
                           {'decision': 'deny', 'next': 'list'}, follow=True)
        self.assertContains(resp, 'Request already approved')
        # Without next=list the endpoint still answers JSON.
        resp = self.c.post(reverse('vault:reveal_request_decide', args=[req.pk]), {'decision': 'deny'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Request already approved')

    def test_global_view_reveal_and_totp_filed_under_entry_customer(self):
        _login(self.c, self.su)  # no customer selected: global view
        resp = self.c.post(reverse('vault:password_reveal', args=[self.pw.pk]))
        self.assertEqual(resp.status_code, 200)
        row = AuditLog.objects.filter(action='reveal', object_id=self.pw.pk).latest('pk')
        self.assertEqual(row.organization_id, self.org.pk)
        resp = self.c.get(reverse('vault:generate_otp', args=[self.pw.pk]))
        self.assertEqual(resp.status_code, 200)
        row = AuditLog.objects.filter(description__startswith='TOTP code generated',
                                      object_id=self.pw.pk).latest('pk')
        self.assertEqual(row.organization_id, self.org.pk)

    def test_audit_form_data_redacts_vault_secrets(self):
        _login(self.c, self.owner, self.org)
        resp = self.c.post(reverse('vault:password_create'), {
            'title': 'Licensed app', 'password_type': 'software_license',
            'plaintext_password': 'pw-value-1', 'license_key': 'LIC-AAAA-BBBB',
            'plaintext_secure_notes': 'recovery 1111-2222', 'notes': 'plain note',
            'client_access_mode': 'none',
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context['form'].errors)
        data = _form_data(reverse('vault:password_create'))
        self.assertEqual(data['license_key'], '***REDACTED***')
        self.assertEqual(data['plaintext_secure_notes'], '***REDACTED***')
        self.assertEqual(data['plaintext_password'], '***REDACTED***')
        self.assertEqual(data['title'], 'Licensed app')

        self.c.post(reverse('vault:personal_vault_create'), {'title': 'Mine', 'content': 'my pin 4321'})
        self.assertTrue(PersonalVault.objects.filter(user=self.owner, title='Mine').exists())
        self.assertEqual(_form_data(reverse('vault:personal_vault_create'))['content'], '***REDACTED***')

        self.c.post(reverse('core:secure_note_create'),
                    {'title': 'For you', 'content': 'wifi key 9999', 'link_only': 'on'})
        self.assertEqual(_form_data(reverse('core:secure_note_create'))['content'], '***REDACTED***')
        self.assertFalse(AuditLog.objects.filter(extra_data__icontains='9999').exists())

    def test_secret_link_path_not_in_audit_log(self):
        note = SecureNote(sender=self.su, title='Link', link_only=True, max_views=3)
        note.set_content('door code 2468')
        token = note.generate_access_token()
        note.save()
        _login(self.c, self.owner, self.org)
        path = reverse('core:secure_note_view_link', args=[token])
        resp = self.c.post(path)
        self.assertContains(resp, 'door code 2468')
        self.assertFalse(AuditLog.objects.filter(path=path).exists())

    def test_secure_note_password_required_when_ticked(self):
        _login(self.c, self.owner, self.org)
        self.c.post(reverse('core:secure_note_create'), {
            'title': 'Empty pw', 'content': 'x', 'link_only': 'on',
            'require_password': 'on', 'access_password': '',
        })
        self.assertFalse(SecureNote.objects.filter(title='Empty pw').exists())

    def test_copy_helper_uses_clipboard_api(self):
        _login(self.c, self.owner, self.org)
        html = self.c.get(reverse('vault:password_detail', args=[self.pw.pk])).content.decode()
        self.assertIn('return navigator.clipboard.writeText(text);', html)
        self.assertNotIn('return copyToClipboard(text);', html)

    def test_secret_links_summary_counts(self):
        from datetime import timedelta
        from django.utils import timezone
        for title, views, expired in (('L1', 2, False), ('L2', 3, True)):
            n = SecureNote(sender=self.owner, title=title, link_only=True, read_count=views,
                           expires_at=timezone.now() + timedelta(days=-1 if expired else 1))
            n.set_content('x')
            n.generate_access_token()
            n.save()
        _login(self.c, self.owner, self.org)
        resp = self.c.get(reverse('core:secure_note_links_dashboard'))
        self.assertEqual(resp.context['total_views'], 5)
        self.assertEqual(resp.context['active_count'], 1)
        self.assertNotContains(resp, '2+3')

    def test_detail_shows_modified_date(self):
        _login(self.c, self.owner, self.org)
        html = self.c.get(reverse('vault:password_detail', args=[self.pw.pk])).content.decode()
        import re
        m = re.search(r'Modified:</dt>\s*<dd class="col-sm-9">([^<]*)<', html)
        self.assertTrue(m and m.group(1).strip(), 'Modified date is empty')
