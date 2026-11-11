"""
Agreements: uploaded-file documents as agreements, signer-role limits,
reminder e-mails, and revisions issued on save/publish/scheduler only
(never on a page view).
"""
import io
import json
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership
from core.models import SystemSetting
from psa.tests._base import TEST_MIDDLEWARE

from . import agreements
from .agreement_models import Agreement, AgreementReminder, AgreementSignature
from .models import Document
from . import tests_agreements as _base
from .tests_agreements import _login, _sha

_MEDIA = tempfile.mkdtemp(prefix='agreement-test-media-')


def tearDownModule():
    shutil.rmtree(_MEDIA, ignore_errors=True)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=_MEDIA,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AgreementFileRuleReminderTests(TestCase):
    setUp = _base.AgreementTests.setUp
    _make = _base.AgreementTests._make
    _sign = _base.AgreementTests._sign
    _edit = _base.AgreementTests._edit
    _zip = staticmethod(_base.AgreementTests._zip)

    def _file_doc(self, data=b'%PDF-1.4 signed terms v1', name='msa-2026.pdf'):
        return Document.objects.create(
            organization=self.org, title='Signed MSA (PDF)', slug='msa-pdf', content_type='file',
            file=SimpleUploadedFile(name, data, content_type='application/pdf'), file_type='application/pdf',
            is_published=True, created_by=self.staff, last_modified_by=self.staff)

    # --- uploaded files ---------------------------------------------------------

    def test_file_agreement_binds_to_file_hash_and_keeps_a_copy(self):
        doc = self._file_doc()
        agreement = agreements.make_agreement(doc, self.staff)
        v1 = agreement.latest_revision
        self.assertEqual(v1.file_sha256, _sha(b'%PDF-1.4 signed terms v1'))
        self.assertEqual(bytes(v1.file_data), b'%PDF-1.4 signed terms v1')
        self.assertEqual(json.loads(v1.content_json())['file']['sha256'], v1.file_sha256)
        self.assertEqual(_sha(v1.content_json()), v1.content_hash)
        self.assertTrue(all(v1.verify().values()))
        self.assertContains(self.portal.get(f'/portal/agreements/{agreement.pk}/'), 'msa-2026.pdf')
        self.assertEqual(self.portal.get(f'/portal/agreements/revisions/{v1.pk}/file/').content,
                         b'%PDF-1.4 signed terms v1')
        self._sign(self.portal, agreement)
        sig = AgreementSignature.objects.get()
        self.assertTrue(sig.verified)

        # Replacing the file issues v2; v1's stored copy and evidence are unchanged.
        doc.file = SimpleUploadedFile('msa-2026.pdf', b'%PDF-1.4 signed terms v2', content_type='application/pdf')
        doc.save()
        agreement.refresh_from_db()
        v2 = agreement.latest_revision
        self.assertEqual(v2.version_number, 2)
        self.assertNotEqual(v2.file_sha256, v1.file_sha256)
        self.assertTrue(agreements.needs_signature(agreement, self.client_user))
        z = self._zip(_login(self.staff).get(f'/docs/lifecycle/agreements/evidence/{sig.pk}/'))
        files = {n: z.read(n) for n in z.namelist()}
        self.assertEqual(files['file/msa-2026.pdf'], b'%PDF-1.4 signed terms v1')
        self.assertEqual(json.loads(files['evidence.json'])['revision']['file_sha256'], v1.file_sha256)
        self.assertIn(f'{v1.file_sha256}  file/msa-2026.pdf', files['SHA256SUMS'].decode())
        self.assertEqual(_login(self.staff).get(f'/docs/lifecycle/agreements/revisions/{v1.pk}/file/').content,
                         b'%PDF-1.4 signed terms v1')
        self.assertContains(_login(self.staff).get(f'/docs/lifecycle/agreements/revisions/{v1.pk}/'),
                            v1.file_sha256)
        self.assertEqual(_login(self.outsider).get(f'/portal/agreements/revisions/{v1.pk}/file/').status_code, 404)

    def test_file_over_limit_is_refused(self):
        doc = self._file_doc()
        with mock.patch.object(agreements, 'FILE_MAX', 8):
            with self.assertRaises(agreements.AgreementError):
                agreements.make_agreement(doc, self.staff)

    # --- signer-role limits -----------------------------------------------------

    def test_org_admin_rule_limits_who_signs_for_the_customer(self):
        Membership.objects.filter(user=self.colleague, organization=self.org).update(is_org_admin=True)
        agreement = self._make(signer_rule=Agreement.ORG_ADMINS)
        self.assertFalse(agreements.may_sign(agreement, self.client_user))
        r = self.portal.get(f'/portal/agreements/{agreement.pk}/')
        self.assertContains(r, 'needs to be signed by an org admin of Acme Clinic')
        self.assertNotContains(r, 'id="sign-form"')
        self._sign(self.portal, agreement)
        self.assertFalse(AgreementSignature.objects.exists())
        self._sign(_login(self.colleague), agreement, signed_by_name='Sam', signed_by_email='sam@acme.test')
        self.assertEqual(AgreementSignature.objects.get().user, self.colleague)

    def test_named_signers_rule_via_staff_form(self):
        staff = _login(self.staff)
        staff.post(f'/docs/id/{self.doc.pk}/agreement/', {
            'action': 'setup', 'kind': 'sow', 'mode': 'signature', 'audience': 'one',
            'signer_rule': 'named', 'allowed_signers': [self.client_user.pk, self.outsider.pk, self.staff.pk],
            'reminders_enabled': 'on', 'reminder_interval_days': '3'})
        agreement = Agreement.objects.get()
        # Only this customer's portal users can be named: the outsider and staff are dropped.
        self.assertEqual(list(agreement.allowed_signers.all()), [self.client_user])
        self.assertEqual((agreement.signer_rule, agreement.reminder_interval_days), ('named', 3))
        self._sign(_login(self.colleague), agreement, signed_by_name='Sam', signed_by_email='sam@acme.test')
        self.assertFalse(AgreementSignature.objects.exists())
        self._sign(self.portal, agreement)
        self.assertEqual(AgreementSignature.objects.get().user, self.client_user)
        with self.assertRaises(agreements.AgreementError):
            agreements.make_agreement(self.doc, self.staff, signer_rule='named', allowed_signers=[])

    def test_each_audience_expects_only_allowed_signers(self):
        Membership.objects.filter(user=self.client_user, organization=self.org).update(is_org_admin=True)
        agreement = self._make(mode='acknowledgment', audience='each', signer_rule=Agreement.ORG_ADMINS)
        self.assertEqual([u.username for u in agreements.status(agreement)['outstanding']], ['pat'])

    # --- no issuing on GET --------------------------------------------------------

    def test_get_never_issues_a_revision(self):
        agreement = self._make()
        # Content changes without a save signal (as if the save-time issue failed).
        Document.objects.filter(pk=self.doc.pk).update(body='<p>Changed behind the signal.</p>')
        for url in (f'/portal/agreements/{agreement.pk}/', '/portal/agreements/'):
            self.portal.get(url)
        staff = _login(self.staff)
        staff.get(f'/docs/id/{self.doc.pk}/agreement/')
        staff.get('/docs/lifecycle/agreements/')
        self.assertEqual(agreement.revisions.count(), 1)
        # The scheduler path catches up.
        self.assertEqual(agreements.issue_pending_revisions(), 1)
        self.assertEqual(agreement.revisions.count(), 2)

    # --- reminders ----------------------------------------------------------------

    def _smtp_on(self):
        s = SystemSetting.get_settings()
        s.smtp_enabled, s.smtp_host, s.smtp_from_email = True, 'smtp.test', 'msp@msp.test'
        s.site_url = 'https://msp.test'
        s.save()

    def _run(self):
        call_command('agreement_reminders', stdout=io.StringIO())

    def test_reminders_throttled_opt_out_and_new_revision(self):
        from accounts.models import UserProfile
        self._smtp_on()
        agreement = self._make(mode='acknowledgment', audience='each')
        UserProfile.objects.update_or_create(user=self.colleague, defaults={'email_notifications': False})
        with mock.patch('core.mailer.get_smtp_connection', return_value=mail.get_connection()):
            self._run()
            self.assertEqual([m.to for m in mail.outbox], [['pat@acme.test']])  # sam opted out
            self.assertIn(f'https://msp.test/portal/agreements/{agreement.pk}/', mail.outbox[0].body)
            self._run()
            self.assertEqual(len(mail.outbox), 1)  # throttled
            AgreementReminder.objects.update(sent_at=timezone.now() - timedelta(days=8))
            self._run()
            self.assertEqual(len(mail.outbox), 2)
            self.assertTrue(mail.outbox[1].subject.startswith('Reminder:'))
            # Acknowledged: no more reminders for this version.
            self._sign(self.portal, agreement, signature_data='')
            AgreementReminder.objects.update(sent_at=timezone.now() - timedelta(days=30))
            self._run()
            self.assertEqual(len(mail.outbox), 2)
            # A new revision needs acknowledging again: first notice right away.
            self._edit('<p>Policy v2</p>')
            self._run()
            self.assertEqual(len(mail.outbox), 3)
            self.assertIn('version 2', mail.outbox[2].subject)
            # Reminders off for this agreement: nothing.
            agreement.refresh_from_db()
            agreement.reminders_enabled = False
            agreement.save()
            AgreementReminder.objects.update(sent_at=timezone.now() - timedelta(days=30))
            self._run()
            self.assertEqual(len(mail.outbox), 3)

    def test_reminders_capped_per_revision_and_skipped_without_smtp(self):
        agreement = self._make()
        self._run()  # SMTP not configured
        self.assertEqual(len(mail.outbox), 0)
        self._smtp_on()
        rev = agreement.latest_revision
        for _ in range(agreements.REMINDER_MAX_PER_REVISION):
            for u in (self.client_user, self.colleague):
                AgreementReminder.objects.create(revision=rev, user=u, email=u.email,
                                                 sent_at=timezone.now() - timedelta(days=60))
        with mock.patch('core.mailer.get_smtp_connection', return_value=mail.get_connection()):
            self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_one_signature_any_rule_reminds_org_admins_only(self):
        Membership.objects.filter(user=self.colleague, organization=self.org).update(is_org_admin=True)
        agreement = self._make()
        self.assertEqual([u.username for u in agreements.reminder_recipients(agreement, agreement.latest_revision)],
                         ['sam'])
