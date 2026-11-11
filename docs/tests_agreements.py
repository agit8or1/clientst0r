"""
Version-specific agreements: MSAs, SOWs and policy acknowledgments bound
to an exact document revision, with downloadable, hash-verifiable evidence.
"""
import hashlib
import io
import json
import zipfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.tests._base import TEST_MIDDLEWARE

from . import agreements
from .agreement_models import Agreement, AgreementRevision, AgreementSignature
from .models import Document

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _login(user):
    c = Client(HTTP_USER_AGENT='AgreementTest/1.0')
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AgreementTests(TestCase):
    def setUp(self):
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='Acme Clinic', slug='acme')
        self.other = Organization.objects.create(name='Other Co', slug='otherco')
        for o in (self.org, self.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)
        self.staff = User.objects.create_superuser('msp-admin', 'admin@msp.test', 'pw')
        self.client_user = User.objects.create_user('pat', 'pat@acme.test', 'pw', first_name='Pat', last_name='Lee')
        Membership.objects.create(user=self.client_user, organization=self.org, role=Role.READONLY, is_active=True)
        self.colleague = User.objects.create_user('sam', 'sam@acme.test', 'pw')
        Membership.objects.create(user=self.colleague, organization=self.org, role=Role.READONLY, is_active=True)
        self.outsider = User.objects.create_user('olga', 'olga@other.test', 'pw')
        Membership.objects.create(user=self.outsider, organization=self.other, role=Role.READONLY, is_active=True)
        self.doc = Document.objects.create(organization=self.org, title='Master Services Agreement', slug='msa',
                                           body='<p>Term: 12 months.</p>', content_type='html',
                                           is_published=True, created_by=self.staff, last_modified_by=self.staff)
        self.portal = _login(self.client_user)

    def _make(self, **kw):
        kw.setdefault('kind', 'msa')
        return agreements.make_agreement(self.doc, self.staff, **kw)

    def _sign(self, client, agreement, rev=None, **extra):
        rev = rev or agreement.latest_revision
        data = {'revision': rev.pk, 'content_hash': rev.content_hash, 'signed_by_name': 'Pat Lee',
                'signed_by_email': 'pat@acme.test', 'signed_by_title': 'Office manager', 'accept': 'on',
                'signature_data': PNG}
        data.update(extra)
        return client.post(f'/portal/agreements/{agreement.pk}/', data, REMOTE_ADDR='203.0.113.7')

    def _edit(self, body):
        self.doc.body = body
        self.doc.last_modified_by = self.staff
        self.doc.save()

    @staticmethod
    def _zip(response):
        return zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content) if response.streaming
                                          else response.content))

    # --- the core promise ------------------------------------------------------

    def test_sign_v1_edit_to_v2_keeps_v1_evidence_and_needs_new_signature(self):
        agreement = self._make()
        v1 = agreement.latest_revision
        self.assertEqual(v1.version_number, 1)
        r = self.portal.get(f'/portal/agreements/{agreement.pk}/')
        self.assertContains(r, 'Term: 12 months.')
        self.assertContains(r, 'Sign version 1')
        self._sign(self.portal, agreement)
        sig = AgreementSignature.objects.get()
        self.assertEqual((sig.revision_id, sig.signed_by_name, sig.method), (v1.pk, 'Pat Lee', 'signature'))
        self.assertEqual(sig.ip_address, '203.0.113.7')
        self.assertEqual(sig.user_agent, 'AgreementTest/1.0')
        self.assertEqual(sig.content_hash, v1.content_hash)
        self.assertTrue(sig.verified)
        self.assertFalse(agreements.needs_signature(agreement, self.client_user))
        before = self._zip(_login(self.staff).get(f'/docs/lifecycle/agreements/evidence/{sig.pk}/'))
        before_files = {n: before.read(n) for n in before.namelist()}

        self._edit('<p>Term: 24 months.</p>')
        agreement.refresh_from_db()
        v2 = agreement.latest_revision
        self.assertEqual(v2.version_number, 2)
        self.assertNotEqual(v2.content_hash, v1.content_hash)
        self.assertTrue(agreements.needs_signature(agreement, self.client_user))
        r = self.portal.get(f'/portal/agreements/{agreement.pk}/')
        self.assertContains(r, 'Term: 24 months.')
        self.assertContains(r, 'Sign version 2')
        self.assertContains(r, '(earlier version)')

        # v1's evidence is unchanged, downloadable by staff and by the customer, and every hash checks out.
        v1.refresh_from_db()
        sig.refresh_from_db()
        self.assertIn('Term: 12 months.', v1.rendered_html)
        self.assertTrue(all(sig.verify().values()))
        for client in (_login(self.staff), self.portal):
            url = (f'/docs/lifecycle/agreements/evidence/{sig.pk}/' if client is not self.portal
                   else f'/portal/agreements/evidence/{sig.pk}/')
            z = self._zip(client.get(url))
            files = {n: z.read(n) for n in z.namelist()}
            for name in ('content.json', 'snapshot.html', 'evidence.json', 'signature.png'):
                self.assertEqual(files[name], before_files[name], name)
            evidence = json.loads(files['evidence.json'])
            self.assertEqual(_sha(files['content.json']), evidence['revision']['content_hash'])
            self.assertEqual(_sha(files['content.json']), v1.content_hash)
            self.assertEqual(_sha(files['snapshot.html']), evidence['revision']['snapshot_hash'])
            self.assertEqual(_sha(files['evidence.json']), sig.evidence_hash)
            if 'document.pdf' in files:
                self.assertEqual(_sha(files['document.pdf']), evidence['revision']['pdf_hash'])
            self.assertIn('Term: 12 months.', json.loads(files['content.json'])['body'])
            self.assertEqual(evidence['revision']['version'], 1)
            self.assertEqual(evidence['signer']['email'], 'pat@acme.test')
            self.assertEqual(evidence['ip_address'], '203.0.113.7')
            self.assertIn(f'{sig.evidence_hash}', files['SHA256SUMS'].decode())

        # v2 needs (and takes) its own signature.
        self._sign(self.portal, agreement, v2)
        self.assertEqual(AgreementSignature.objects.filter(revision=v2).count(), 1)
        self.assertEqual(AgreementSignature.objects.filter(revision=v1).count(), 1)

    def test_stale_version_and_second_signature_are_refused(self):
        agreement = self._make()
        v1 = agreement.latest_revision
        self._edit('<p>Changed while the customer was reading.</p>')
        self._sign(self.portal, agreement, v1)
        self.assertFalse(AgreementSignature.objects.exists())
        v2 = Agreement.objects.get(pk=agreement.pk).latest_revision
        self._sign(self.portal, agreement, v2)
        self._sign(_login(self.colleague), agreement, v2)  # one signature for the customer is enough
        self.assertEqual(AgreementSignature.objects.count(), 1)
        # Missing signature in signature mode is refused.
        self._edit('<p>v3</p>')
        v3 = Agreement.objects.get(pk=agreement.pk).latest_revision
        self._sign(self.portal, agreement, v3, signature_data='')
        self.assertFalse(AgreementSignature.objects.filter(revision=v3).exists())

    def test_records_are_immutable(self):
        agreement = self._make()
        self._sign(self.portal, agreement)
        sig = AgreementSignature.objects.get()
        sig.signed_by_name = 'Someone else'
        with self.assertRaises(ValueError):
            sig.save()
        with self.assertRaises(ValueError):
            sig.delete()
        rev = AgreementRevision.objects.get()
        rev.body = 'rewritten'
        with self.assertRaises(ValueError):
            rev.save()

    def test_only_live_approved_content_is_issued(self):
        agreement = self._make()
        self.doc.is_draft, self.doc.body = True, '<p>Draft awaiting approval</p>'
        self.doc.save()
        self.assertEqual(agreement.revisions.count(), 1)
        r = self.portal.get(f'/portal/agreements/{agreement.pk}/')
        self.assertContains(r, 'Term: 12 months.')
        self.assertNotContains(r, 'Draft awaiting approval')
        self.doc.is_draft = False
        self.doc.save()
        self.assertEqual(agreement.revisions.count(), 2)

    def test_document_deletion_keeps_evidence(self):
        agreement = self._make()
        self._sign(self.portal, agreement)
        self.doc.delete()
        sig = AgreementSignature.objects.get()
        self.assertTrue(sig.verified)
        self.assertEqual(self.portal.get(f'/portal/agreements/evidence/{sig.pk}/').status_code, 200)

    # --- scope -----------------------------------------------------------------

    def test_cross_customer_denial(self):
        agreement = self._make()
        self._sign(self.portal, agreement)
        sig = AgreementSignature.objects.get()
        other = _login(self.outsider)
        self.assertEqual(other.get(f'/portal/agreements/{agreement.pk}/').status_code, 404)
        self.assertEqual(other.get(f'/portal/agreements/evidence/{sig.pk}/').status_code, 404)
        self.assertEqual(self._sign(other, agreement).status_code, 404)
        self.assertNotContains(other.get('/portal/agreements/'), 'Master Services Agreement')
        self.assertEqual(AgreementSignature.objects.count(), 1)
        with self.assertRaises(agreements.AgreementError):
            agreements.sign(agreement, agreement.latest_revision.pk, agreement.latest_revision.content_hash,
                            self.outsider, self.other, name='O', email='o@x.test', accepted=True,
                            signature_data=PNG)
        # Customer users never reach the staff pages.
        for url in ('/docs/lifecycle/agreements/', f'/docs/id/{self.doc.pk}/agreement/',
                    f'/docs/lifecycle/agreements/evidence/{sig.pk}/',
                    f'/docs/lifecycle/agreements/revisions/{sig.revision_id}/'):
            self.assertNotEqual(self.portal.get(url).status_code, 200, url)

    def test_global_and_fileless_documents_cannot_be_agreements(self):
        self.doc.content_type = 'file'  # an uploaded-file document with no file
        with self.assertRaises(agreements.AgreementError):
            agreements.make_agreement(self.doc, self.staff)
        kb = Document.objects.create(title='Global', slug='global', body='x', is_global=True,
                                     created_by=self.staff)
        with self.assertRaises(agreements.AgreementError):
            agreements.make_agreement(kb, self.staff)

    # --- staff view ------------------------------------------------------------

    def test_acknowledgment_list_shows_who_and_who_is_outstanding(self):
        staff = _login(self.staff)
        r = staff.post(f'/docs/id/{self.doc.pk}/agreement/', {'action': 'setup', 'kind': 'policy',
                                                              'mode': 'acknowledgment', 'audience': 'each'})
        self.assertEqual(r.status_code, 302)
        agreement = Agreement.objects.get()
        self.assertEqual((agreement.kind, agreement.mode, agreement.audience), ('policy', 'acknowledgment', 'each'))
        r = staff.get(f'/docs/id/{self.doc.pk}/agreement/')
        self.assertContains(r, 'pat@acme.test')
        self.assertContains(r, 'sam@acme.test')
        self.assertNotContains(r, 'olga@other.test')
        self.assertNotContains(r, 'admin@msp.test</span>')

        self._sign(self.portal, agreement, signature_data='')
        sig = AgreementSignature.objects.get()
        self.assertEqual((sig.method, sig.signature_data), ('acknowledgment', ''))
        status = agreements.status(agreement)
        self.assertEqual([u.username for u in status['outstanding']], ['sam'])
        r = staff.get(f'/docs/id/{self.doc.pk}/agreement/')
        self.assertContains(r, 'Pat Lee &lt;pat@acme.test&gt;')
        self.assertContains(r, '1 outstanding')
        self.assertContains(staff.get('/docs/lifecycle/agreements/'), 'Master Services Agreement')

        self._sign(_login(self.colleague), agreement, signature_data='', signed_by_name='Sam',
                   signed_by_email='sam@acme.test')
        self.assertContains(staff.get(f'/docs/id/{self.doc.pk}/agreement/'), 'Nobody outstanding.')
        # An edit re-opens it for both.
        self._edit('<p>Updated acceptable use policy.</p>')
        status = agreements.status(Agreement.objects.get())
        self.assertEqual(sorted(u.username for u in status['outstanding']), ['pat', 'sam'])
        r = staff.get(f'/docs/lifecycle/agreements/revisions/{sig.revision_id}/')
        self.assertContains(r, 'hashes verified')
        self.assertContains(r, sig.revision.content_hash)
