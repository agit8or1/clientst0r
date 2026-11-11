"""Agreement reminder e-mails: a per-agreement signed unsubscribe link, and an
opening sentence that says "a new version" only to someone who signed an
earlier revision (not merely because the version number is above 1)."""
import io
import re
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import SystemSetting
from psa.tests._base import TEST_MIDDLEWARE

from . import agreements
from . import tests_agreements as _base
from .agreement_models import AgreementReminder, AgreementReminderOptOut


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AgreementReminderUnsubscribeTests(TestCase):
    setUp = _base.AgreementTests.setUp
    _make = _base.AgreementTests._make
    _sign = _base.AgreementTests._sign
    _edit = _base.AgreementTests._edit

    def _smtp_on(self):
        s = SystemSetting.get_settings()
        s.smtp_enabled, s.smtp_host, s.smtp_from_email = True, 'smtp.test', 'msp@msp.test'
        s.site_url = 'https://msp.test'
        s.save()

    def _run(self):
        with mock.patch('core.mailer.get_smtp_connection', return_value=mail.get_connection()):
            call_command('agreement_reminders', stdout=io.StringIO())

    def _to(self, user):
        return [m for m in mail.outbox if m.to == [user.email]]

    @staticmethod
    def _link(msg):
        return re.search(r'Stop reminders about this agreement: (\S+)', msg.body).group(1)

    def test_first_sentence_depends_on_an_earlier_signature_not_the_version(self):
        self._smtp_on()
        agreement = self._make(mode='acknowledgment', audience='each')
        self._run()
        first = self._to(self.client_user)[0]
        self.assertIn('You are asked to acknowledge "', first.body)
        self.assertNotIn('new version', first.body)

        # client_user acknowledges v1; the colleague never does.
        self._sign(self.portal, agreement, signature_data='')
        self._edit('<p>Policy v2</p>')
        AgreementReminder.objects.update(sent_at=timezone.now() - timedelta(days=30))
        mail.outbox.clear()
        self._run()
        signed_before = self._to(self.client_user)[0]
        self.assertIn('There is a new version of "', signed_before.body)
        self.assertIn('version 2', signed_before.body)
        never_signed = self._to(self.colleague)[0]
        self.assertIn('version 2', never_signed.body)
        self.assertNotIn('new version', never_signed.body)
        self.assertIn('You are asked to acknowledge "', never_signed.body)

    def test_unsubscribe_link_stops_reminders_for_that_agreement_only(self):
        self._smtp_on()
        agreement = self._make(mode='acknowledgment', audience='each')
        self._run()
        msg = self._to(self.client_user)[0]
        link = self._link(msg)
        self.assertTrue(link.startswith('https://msp.test/portal/agreements/reminders/unsubscribe/'))
        self.assertEqual(msg.extra_headers['List-Unsubscribe'], f'<{link}>')

        anon = Client()
        path = link.replace('https://msp.test', '')
        r = anon.get(path)
        self.assertContains(r, 'Stop reminders about')
        self.assertFalse(AgreementReminderOptOut.objects.exists())  # GET alone changes nothing
        r = anon.post(path)
        self.assertContains(r, 'Reminders stopped')
        self.assertTrue(AgreementReminderOptOut.objects.filter(
            agreement=agreement, user=self.client_user).exists())

        AgreementReminder.objects.update(sent_at=timezone.now() - timedelta(days=30))
        mail.outbox.clear()
        self._run()
        self.assertEqual(self._to(self.client_user), [])
        self.assertEqual(len(self._to(self.colleague)), 1)  # someone else is unaffected

        # Still opted out after a new revision of the same agreement.
        self._edit('<p>Policy v3</p>')
        mail.outbox.clear()
        self._run()
        self.assertEqual(self._to(self.client_user), [])
        # And the agreement still waits for them in the portal.
        agreement.refresh_from_db()
        self.assertTrue(agreements.needs_signature(agreement, self.client_user))

    def test_bad_or_stale_tokens_are_refused(self):
        agreement = self._make(mode='acknowledgment', audience='each')
        self.assertEqual(Client().get('/portal/agreements/reminders/unsubscribe/not-a-token/').status_code, 404)
        url = agreements.reminder_unsubscribe_url(agreement, self.client_user)
        self.client_user.email = 'moved@elsewhere.test'
        self.client_user.save()
        self.assertEqual(Client().post(url).status_code, 404)
        self.assertFalse(AgreementReminderOptOut.objects.exists())
