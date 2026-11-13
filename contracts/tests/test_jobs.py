"""Background jobs: e-mail failures and retries, PDF/finalization retries,
reminders and their cancellation, idempotency, scheduler wiring."""
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from contracts import jobs, maintenance, services
from contracts.models import (ContractDocument as D, ContractInvitation, ContractJob, ContractSettings,
                              ContractVersion)

from .base import ContractTestCase, links_in_outbox


class EmailJobTests(ContractTestCase):

    def test_failed_invitation_email_retries_with_a_fresh_token(self):
        c = self.new_contract()
        with mock.patch('contracts.mail.send_invitation', side_effect=OSError('smtp down')):
            self.issue_and_send(c)
        inv = c.invitations.get()
        job = ContractJob.objects.get(kind='invitation_email', invitation=inv)
        self.assertEqual((job.status, job.attempts), ('pending', 1))
        self.assertIn('smtp down', job.last_error)
        inv.refresh_from_db()
        self.assertEqual(inv.delivery_status, 'failed')
        # the token minted for the failed attempt no longer works
        self.assertFalse(inv.tokens.filter(revoked_at__isnull=True).exists())
        # not yet due → nothing happens
        self.assertEqual(jobs.run_due(), {})
        later = timezone.now() + timedelta(minutes=2)
        self.assertEqual(jobs.run_due(now=later), {'done': 1})
        inv.refresh_from_db()
        self.assertEqual(inv.delivery_status, 'accepted')
        self.assertEqual(len(links_in_outbox()), 1)
        self.assertEqual(inv.tokens.filter(revoked_at__isnull=True).count(), 1)

    def test_gives_up_after_max_attempts(self):
        c = self.new_contract()
        with mock.patch('contracts.mail.send_invitation', side_effect=OSError('nope')):
            self.issue_and_send(c)
            job = ContractJob.objects.get(kind='invitation_email')
            t = timezone.now()
            for _ in range(10):
                t += timedelta(hours=7)
                jobs.run_due(now=t)
        job.refresh_from_db()
        self.assertEqual(job.status, ContractJob.FAILED)
        self.assertEqual(job.attempts, job.max_attempts)
        self.assertTrue(c.events.filter(kind='email_failed').exists())

    def test_idempotent_enqueue_and_claim(self):
        c = self.new_contract()
        j1, created1 = jobs.enqueue('staff_email', 'same-key', contract=c, payload={
            'to': self.staff.email, 'user_id': self.staff.pk, 'subject': 's', 'body': 'b'})
        j2, created2 = jobs.enqueue('staff_email', 'same-key', contract=c)
        self.assertEqual((j1.pk, created1, created2), (j2.pk, True, False))
        self.assertEqual(jobs.run_job(j1), 'done')
        self.assertIsNone(jobs.run_job(j1))   # already done: not claimed again
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_after_signing_is_refused(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        inv.refresh_from_db()
        with self.assertRaises(services.ContractError):
            services.resend(inv, self.staff)

    def test_mail_not_configured_is_reported(self):
        from contracts import mail as cmail
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'), \
                mock.patch('core.mailer.get_smtp_connection', return_value=None):
            with self.assertRaises(cmail.MailNotConfigured):
                cmail.connection()


class FinalizationTests(ContractTestCase):

    def test_pdf_failure_is_retried_and_the_signature_kept(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        with mock.patch('contracts.pdf.build_pdf', side_effect=RuntimeError('font missing')):
            self.sign_post(cl, inv)
        c.refresh_from_db()
        v = c.current_version
        self.assertEqual(c.status, D.SIGNED)          # the signature stands
        self.assertEqual(v.finalization_status, 'failed')
        self.assertIsNone(v.final_pdf)
        job = ContractJob.objects.get(kind='finalize')
        self.assertEqual(job.status, 'pending')
        # The page tells the signer the copy is coming; no final PDF yet.
        r = cl.get(f'/sign/i/{inv.public_id}/')
        self.assertNotContains(r, 'Download the signed copy')
        jobs.run_due(now=timezone.now() + timedelta(minutes=2))
        v.refresh_from_db()
        self.assertEqual(v.finalization_status, 'done')
        self.assertTrue(bytes(v.final_pdf).startswith(b'%PDF'))
        self.assertEqual(len([m for m in mail.outbox if m.attachments]), 1)
        # running it again changes nothing
        signing_final = bytes(v.final_pdf)
        from contracts import signing
        signing.finalize_version(v)
        v.refresh_from_db()
        self.assertEqual(bytes(v.final_pdf), signing_final)
        self.assertEqual(len([m for m in mail.outbox if m.attachments]), 1)

    def test_maintenance_requeues_failed_finalization(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        with mock.patch('contracts.pdf.build_pdf', side_effect=RuntimeError('x')):
            self.sign_post(cl, inv)
        ContractJob.objects.filter(kind='finalize').update(status='failed')
        self.assertEqual(maintenance.retry_finalization(), 1)
        jobs.run_due()
        c.current_version.refresh_from_db()
        self.assertEqual(ContractVersion.objects.get(pk=c.current_version_id).finalization_status, 'done')


class ReminderTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        s = ContractSettings.deployment_default()
        s.reminders_enabled, s.reminder_first_after_days, s.reminder_interval_days, s.reminder_max = True, 2, 3, 2
        s.save()

    def _sent(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        ContractInvitation.objects.filter(pk=inv.pk).update(activated_at=timezone.now() - timedelta(days=3))
        mail.outbox = []
        return c, inv

    def test_reminders_are_queued_capped_and_sent(self):
        c, inv = self._sent()
        now = timezone.now()
        self.assertEqual(maintenance.queue_reminders(now), 1)
        self.assertEqual(maintenance.queue_reminders(now), 0)   # same reminder number: one job
        jobs.run_due(now=timezone.now())
        inv.refresh_from_db()
        self.assertEqual(inv.reminders_sent, 1)
        self.assertEqual(len(links_in_outbox()), 1)
        self.assertIn('Reminder', mail.outbox[0].subject)
        self.assertEqual(maintenance.queue_reminders(now + timedelta(days=1)), 0)   # interval not reached
        self.assertEqual(maintenance.queue_reminders(now + timedelta(days=4)), 1)
        jobs.run_due(now=now + timedelta(days=4))
        self.assertEqual(maintenance.queue_reminders(now + timedelta(days=30)), 0)  # reminder_max reached

    def test_reminders_cancelled_by_signing_revoking_voiding(self):
        for how in ('sign', 'revoke', 'void', 'disable'):
            with self.subTest(how):
                mail.outbox = []
                c, inv = self._sent()
                maintenance.queue_reminders()
                ContractJob.objects.filter(kind='reminder_email', invitation=inv).update(
                    next_attempt_at=timezone.now() + timedelta(hours=1))
                if how == 'sign':
                    from contracts import signing
                    raw, _ = signing.mint_token(inv, 'link')
                    cl, _ = self.signer_client(raw)
                    self.sign_post(cl, inv)
                elif how == 'revoke':
                    services.revoke(inv, self.staff)
                elif how == 'void':
                    services.void(c, self.staff, 'no longer needed')
                else:
                    D.objects.filter(pk=c.pk).update(reminders_enabled=False)
                mail.outbox = []
                jobs.run_due(now=timezone.now() + timedelta(hours=2))
                self.assertEqual([m for m in mail.outbox if 'Reminder' in m.subject], [])
                job = ContractJob.objects.get(kind='reminder_email', invitation=inv)
                self.assertEqual(job.status, ContractJob.CANCELLED)

    def test_term_alerts_once(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        D.objects.filter(pk=c.pk).update(expiration_date=timezone.localdate() + timedelta(days=10))
        self.assertEqual(maintenance.term_alerts(), 2)   # renewal (60 d) and expiring (14 d)
        self.assertEqual(maintenance.term_alerts(), 0)

    def test_retention_blanks_ip_on_access_events_only(self):
        s = ContractSettings.deployment_default()
        s.access_log_retention_days = 30
        s.save()
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        from contracts.models import ContractEvent, ContractSignature
        ContractEvent.objects.filter(contract=c).update(at=timezone.now() - timedelta(days=40))
        self.assertGreater(maintenance.apply_retention(), 0)
        self.assertFalse(ContractEvent.objects.filter(contract=c, kind='link_requested',
                                                      ip_address__isnull=False).exists())
        self.assertTrue(ContractSignature.objects.get(invitation=inv).ip_address)


class SchedulerWiringTests(ContractTestCase):

    def test_scheduler_tasks_exist(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        types = dict(ScheduledTask.TASK_TYPES)
        self.assertIn('contracts_jobs', types)
        self.assertIn('contracts_maintenance', types)
        self.assertIn('contracts_jobs', COMMAND_TASKS)
        self.assertIn('contracts_maintenance', COMMAND_TASKS)

    def test_management_commands_run(self):
        call_command('contracts_jobs', verbosity=0)
        call_command('contracts_maintenance', verbosity=0)
        call_command('contracts_seed_templates', verbosity=0)
        from contracts.models import ContractTemplate
        self.assertEqual(ContractTemplate.objects.filter(is_sample=True, organization__isnull=True).count(), 7)
