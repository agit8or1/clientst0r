"""Tenant isolation, role enforcement, immutability and hash binding,
malicious HTML, no remote fetches in PDFs, headers and tokens."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client

from contracts import permissions as perms
from contracts import services
from contracts.models import (ContractApproval, ContractDocument as D, ContractEvent, ContractInvitation,
                              ContractSignature, ContractVersion, ImmutableError)
from contracts.sanitize import clean_html

from .base import BROWSER, ContractTestCase, links_in_outbox, make_org, make_staff


def _role(**flags):
    from accounts.models import RoleTemplate
    return RoleTemplate.objects.create(name=f'Role {RoleTemplate.objects.count()}', **flags)


class IsolationTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        self.other = make_org('Other Clinic', 'boss@other.test')
        self.c_mine = self.new_contract()
        self.c_other = self.new_contract(self.other, signers=[{'name': 'O', 'email': 'o@other.test'}])

    def _scoped_staff(self, **flags):
        """Django-staff user without a technician profile: reach comes from
        memberships, so it can be limited to one customer."""
        from accounts.models import Membership
        u = User.objects.create_user('scoped', 's@msp.test', 'pw-Long-enough-123', is_staff=True)
        role = _role(**{f'contracts_{k}': True for k in flags})
        Membership.objects.create(user=u, organization=self.org, role_template=role, is_active=True)
        return u

    def test_customer_users_are_refused(self):
        from accounts.models import Membership
        cust = User.objects.create_user('cust', 'c@acme.test', 'pw-Long-enough-123')
        Membership.objects.create(user=cust, organization=self.org, role='owner', is_active=True)
        cl = Client()
        cl.force_login(cust)
        for url in ('/contracts/', f'/contracts/{self.c_mine.pk}/', '/contracts/templates/', '/contracts/settings/'):
            with self.subTest(url):
                self.assertEqual(cl.get(url).status_code, 403)
        self.assertFalse(perms.has(cust, perms.VIEW, self.org))

    def test_scoped_staff_only_reach_their_customer(self):
        u = self._scoped_staff(view=True, edit_draft=True)
        cl = Client()
        cl.force_login(u)
        self.assertEqual(cl.get(f'/contracts/{self.c_mine.pk}/').status_code, 200)
        self.assertEqual(cl.get(f'/contracts/{self.c_other.pk}/').status_code, 404)
        r = cl.get('/contracts/')
        self.assertContains(r, self.c_mine.reference)
        self.assertNotContains(r, self.c_other.reference)
        # can't create for the other customer
        r = cl.post('/contracts/new/', {'client': self.other.pk, 'start': 'blank'})
        self.assertFalse(D.objects.filter(organization=self.other).exclude(pk=self.c_other.pk).exists())
        # no send permission
        services.submit(self.c_mine, self.staff)
        r = cl.post(f'/contracts/{self.c_mine.pk}/send/')
        self.assertEqual(r.status_code, 403)
        # no submit permission either (edit_draft alone does not freeze)
        self.assertEqual(cl.post(f'/contracts/{self.c_mine.pk}/submit/').status_code, 403)
        # no void / audit / settings
        self.assertEqual(cl.get(f'/contracts/{self.c_mine.pk}/void/').status_code, 403)
        self.assertEqual(cl.get(f'/contracts/settings/?org={self.org.pk}').status_code, 403)
        v = self.c_mine.versions.get()
        self.assertEqual(cl.get(f'/contracts/versions/{v.pk}/evidence/').status_code, 403)

    def test_each_permission_is_separate(self):
        flags = ['view_pricing', 'edit_draft', 'submit_approval', 'approve', 'send', 'manage_links', 'countersign',
                 'void', 'download_signed', 'view_audit']
        for f in flags:
            u = self._scoped_staff(view=True, **{f: True})
            got = {k for k, v in perms.flags_for(u, self.c_mine).items() if v} - {'may_approve'}
            self.assertEqual(got, {'view', f}, f)
            self.assertFalse(any(perms.flags_for(u, self.c_other).values()))
            u.delete()
        # every action flag needs contracts_view as well
        u = self._scoped_staff(send=True, void=True)
        self.assertFalse(any(perms.flags_for(u, self.c_mine).values()))

    def test_staff_global_role_without_contracts_view(self):
        u = make_staff('limited')
        u.profile.global_role_template = _role(contracts_view=False)
        u.profile.save()
        cl = Client()
        cl.force_login(u)
        self.assertEqual(cl.get('/contracts/').status_code, 403)
        self.assertEqual(cl.get(f'/contracts/{self.c_mine.pk}/').status_code, 404)

    def test_signing_session_is_per_invitation(self):
        self.issue_and_send(self.c_mine)
        self.issue_and_send(self.c_other)
        mine = self.c_mine.invitations.get()
        other = self.c_other.invitations.get()
        cl, _ = self.signer_client(links_in_outbox('pat@acme.test')[0])
        self.assertEqual(cl.get(f'/sign/i/{mine.public_id}/').status_code, 200)
        self.assertEqual(cl.get(f'/sign/i/{other.public_id}/').status_code, 403)
        self.sign_post(cl, other)
        self.assertFalse(ContractSignature.objects.filter(invitation=other).exists())
        self.assertEqual(cl.get(f'/sign/i/{other.public_id}/document.pdf').status_code, 403)

    def test_unknown_or_guessed_token(self):
        r = Client(**BROWSER).get('/sign/t/not-a-real-token/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r['Referrer-Policy'], 'no-referrer')

    def test_public_pages_are_rate_limited(self):
        cl = Client(**BROWSER)
        codes = [cl.get('/sign/t/nope/').status_code for _ in range(32)]
        self.assertIn(429, codes)


class ImmutabilityTests(ContractTestCase):

    def _signed(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        c.refresh_from_db()
        return c, c.current_version, ContractSignature.objects.get(invitation=inv)

    def test_versions_signatures_events_cannot_change(self):
        c, v, sig = self._signed()
        v.content = dict(v.content, contract=dict(v.content['contract'], title='Tampered'))
        with self.assertRaises(ImmutableError):
            v.save()
        v.refresh_from_db()
        v.final_pdf = b'%PDF-fake'
        with self.assertRaises(ImmutableError):
            v.save()
        with self.assertRaises(ImmutableError):
            ContractVersion.objects.get(pk=v.pk).delete()
        sig.printed_name = 'Someone else'
        with self.assertRaises(ImmutableError):
            sig.save()
        with self.assertRaises(ImmutableError):
            sig.delete()
        ev = c.events.first()
        ev.message = 'edited'
        with self.assertRaises(ImmutableError):
            ev.save()
        with self.assertRaises(Exception):
            c.delete()

    def test_hashes_detect_tampering_in_the_database(self):
        c, v, sig = self._signed()
        self.assertTrue(all(v.verify().values()))
        ContractVersion.objects.filter(pk=v.pk).update(rendered_html='<p>changed</p>')
        ContractVersion.objects.filter(pk=v.pk).update(
            content={**v.content, 'terms': {**v.content['terms'], 'payment_terms': 'Net 999'}})
        v.refresh_from_db()
        self.assertFalse(all(v.verify().values()))
        ContractSignature.objects.filter(pk=sig.pk).update(printed_name='Forged')
        sig.refresh_from_db()
        self.assertFalse(all(sig.verify().values()))

    def test_signature_bound_to_the_exact_version(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        r = self.sign_post(cl, inv, content_hash='f' * 64)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())
        r = self.sign_post(cl, inv, version_id=0)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())

    def test_signer_names_do_not_change_the_hash(self):
        c = self.new_contract()
        services.submit(c, self.staff)
        c.refresh_from_db()
        v = c.current_version
        self.assertNotIn('pat@acme.test', v.content_json().decode())

    def test_approval_rows_are_immutable(self):
        approver = make_staff('carol', superuser=True)
        c = self.new_contract(require_internal_approval=True)
        services.submit(c, self.staff)
        c.refresh_from_db()
        services.decide(c, approver, approve=True, content_hash=c.current_version.content_hash)
        a = ContractApproval.objects.get()
        a.comment = 'changed'
        with self.assertRaises(ImmutableError):
            a.save()

    def test_duplicate_and_concurrent_signing(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        self.sign_post(cl, inv)
        self.assertEqual(ContractSignature.objects.filter(invitation=inv).count(), 1)
        self.assertEqual(c.events.filter(kind='signed').count(), 1)
        # Even if two requests both pass the state check, the database refuses
        # a second signature row (OneToOne on the invitation).
        from django.db import IntegrityError, transaction
        sig = ContractSignature.objects.get(invitation=inv)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContractSignature.objects.create(
                invitation=inv, version=sig.version, role=sig.role, invited_name=sig.invited_name,
                invited_email=sig.invited_email, printed_name='x', method='typed', typed_signature='x',
                signing_date=sig.signing_date, intent_text='x', consent_text='x', verification_level='link',
                content_hash=sig.content_hash, snapshot_hash=sig.snapshot_hash)
        # the finalization job ran exactly once
        self.assertEqual(c.events.filter(kind='finalized').count(), 1)

    def test_concurrent_requests_on_one_invitation(self):
        """Two signing requests racing (simulated by a stale state check)."""
        from contracts import signing
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        with mock.patch('contracts.signing.page_state', return_value='open'):
            r = self.sign_post(cl, inv)
        self.assertEqual(ContractSignature.objects.filter(invitation=inv).count(), 1)
        self.assertEqual(r.status_code, 302)


class SanitizeAndPdfTests(ContractTestCase):

    EVIL = ('<p onclick="alert(1)">Hi<script>alert(2)</script></p><img src="https://evil.test/x.png">'
            '<a href="javascript:alert(3)">x</a><iframe src="https://evil.test"></iframe>'
            '<p style="background:url(https://evil.test/y)">s</p><svg onload="x()"></svg>'
            '<a href="https://ok.test/">ok</a><table><tr><td>cell</td></tr></table>')

    def test_clean_html(self):
        out = clean_html(self.EVIL)
        for bad in ('onclick', '<script', '<img', 'javascript:', '<iframe', 'style=', '<svg', 'evil.test'):
            self.assertNotIn(bad, out)
        self.assertIn('href="https://ok.test/"', out)
        self.assertIn('noopener', out)
        self.assertIn('<td>cell</td>', out)

    def test_editor_quirks_are_normalised(self):
        # The editor writes every space as &nbsp; (would stop wrapping), and a
        # merge field looks like a host name (must not become a link).
        out = clean_html('<p>We&nbsp;serve&nbsp;{{client.name}}\u00a0daily.</p>')
        self.assertEqual(out, '<p>We serve {{client.name}} daily.</p>')

    def test_builder_save_sanitizes_and_preview_is_clean(self):
        c = self.new_contract()
        post = {'title': 'T', 'kind': 'msa', 'currency': 'USD', 'tax_rate': '0', 'billing_frequency': 'monthly',
                'draft_revision': c.draft_revision, 'sections_present': '1',
                'section-0-key': '', 'section-0-title': '<b>Heading</b>', 'section-0-type': 'text',
                'section-0-body': self.EVIL, 'section-0-include': 'on', 'section-0-order': '1',
                'signer-0-role': 'client', 'signer-0-name': 'Pat', 'signer-0-email': 'pat@acme.test',
                'signer-0-order': '1'}
        r = self.client.post(f'/contracts/{c.pk}/autosave/', post)
        self.assertEqual(r.status_code, 200, r.content)
        c.refresh_from_db()
        body = c.sections[0]['body']
        self.assertNotIn('<script', body)
        self.assertNotIn('evil.test', body)
        self.assertEqual(c.sections[0]['title'], 'Heading')
        r = self.client.get(f'/contracts/{c.pk}/preview/')
        self.assertNotContains(r, 'alert(2)')
        self.assertNotContains(r, 'evil.test')

    def test_merge_values_are_escaped(self):
        self.org.name = 'Evil <script>alert(1)</script> Co'
        self.org.save()
        c = self.new_contract()
        content, body, unresolved = services.preview(c)
        self.assertNotIn('<script>', body)
        self.assertIn('&lt;script&gt;', body)

    def test_pdf_never_fetches_remote_resources(self):
        import socket
        import urllib.request
        c = self.new_contract(sections=[
            {'title': 'S', 'type': 'text',
             'body': '<p>x</p><img src="http://127.0.0.1:9/a.png"><a href="http://127.0.0.1:9/">l</a>'},
            {'title': 'Signatures', 'type': 'signatures', 'body': ''}])
        from reportlab.lib import utils as rl_utils
        with mock.patch.object(socket, 'create_connection', side_effect=AssertionError('network used')), \
                mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network used')), \
                mock.patch.object(urllib.request, 'urlopen', side_effect=AssertionError('network used')), \
                mock.patch.object(rl_utils, 'open_for_read', side_effect=AssertionError('file/url read')):
            content, _b, _u = services.preview(c)
            from contracts.pdf import build_pdf
            pdf = build_pdf(content, draft=True)
            self.assertTrue(pdf.startswith(b'%PDF'))
            services.submit(c, self.staff)
        c.refresh_from_db()
        self.assertTrue(bytes(c.current_version.pdf).startswith(b'%PDF'))

    def test_snapshot_is_sandboxed(self):
        c = self.new_contract()
        services.submit(c, self.staff)
        c.refresh_from_db()
        r = self.client.get(f'/contracts/versions/{c.current_version.pk}/snapshot/')
        self.assertIn('sandbox', r['Content-Security-Policy'])
        self.assertIn("default-src 'none'", r['Content-Security-Policy'])


class AuditTrailTests(ContractTestCase):

    def test_tokens_never_reach_the_audit_log(self):
        from audit.models import AuditLog
        c = self.new_contract()
        self.issue_and_send(c)
        token = links_in_outbox()[0]
        cl, page = self.signer_client(token)
        cl.get(page)
        self.client.get(f'/sign/t/{token}/')   # even a signed-in staff browser
        for row in AuditLog.objects.all():
            self.assertNotIn(token, str(row.__dict__))
        self.assertTrue(AuditLog.objects.filter(description__icontains=c.reference).exists()
                        or ContractEvent.objects.filter(contract=c, kind='sent').exists())

    def test_secret_storage_check_passes_with_live_tokens_and_codes(self):
        import io

        from django.core.management import call_command
        c = self.new_contract(require_email_verification=True)
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        cl.post(f'/sign/i/{inv.public_id}/code/')
        inv.refresh_from_db()
        self.assertEqual(len(inv.code_hash), 64)
        out = io.StringIO()
        call_command('check_secrets_storage', stdout=out)
        self.assertIn('No unprotected secrets found', out.getvalue())

    def test_staff_can_download_evidence_with_audit_permission(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        c.refresh_from_db()
        r = self.client.get(f'/contracts/versions/{c.current_version.pk}/evidence/')
        self.assertEqual(r.status_code, 200)
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(z.namelist())
        self.assertTrue({'content.json', 'snapshot.html', 'issued.pdf', 'signed.pdf', 'certificate.json',
                         'SHA256SUMS'} <= names)
        from contracts.models import sha256
        self.assertEqual(sha256(z.read('content.json')), c.current_version.content_hash)
