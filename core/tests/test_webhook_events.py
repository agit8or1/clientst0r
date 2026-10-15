"""Webhook events fire from the model/service layer with a consistent envelope.

The Webhooks page offered 32 event types; only asset.created / asset.updated
ever fired, and only from the web form views. These tests cover each wired
event, organization scoping, the absence of secrets in vault payloads, and
that a failing receiver never breaks the save that triggered it.
"""
import json
from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.test import TestCase, override_settings

from accounts.models import Membership
from core.models import Organization, SystemSetting, Webhook, WebhookDelivery
from core.webhook_events import SUPPORTED_EVENTS
from core.webhook_sender import generate_signature


class FakeResponse:
    def __init__(self, status_code=200, text='ok'):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.trust_env = True

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({'url': url, 'data': data, 'headers': headers or {}})
        if self.fail:
            import requests
            raise requests.ConnectionError('receiver unreachable')
        return FakeResponse()


@override_settings(WEBHOOK_DELIVERY_ASYNC=False)
class WebhookEventTestBase(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Acme', slug='acme')
        self.other = Organization.objects.create(name='Other', slug='other')
        settings = SystemSetting.get_settings()
        settings.webhooks_enabled = True
        settings.save()
        self.session = FakeSession()
        patcher = mock.patch('core.webhook_sender.guard_session',
                             side_effect=lambda s, p: self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hook(self, events, org=None, secret=''):
        return Webhook.objects.create(
            organization=org or self.org, name='h', url='https://hooks.example.test/in',
            events=list(events), secret=secret,
        )

    def payloads(self, event=None):
        out = [json.loads(c['data']) for c in self.session.calls]
        if event:
            out = [p for p in out if p['event'] == event]
        return out

    def run_commit(self, fn):
        with self.captureOnCommitCallbacks(execute=True):
            return fn()


class EnvelopeAndScopingTests(WebhookEventTestBase):

    def test_asset_created_envelope(self):
        from assets.models import Asset
        hook = self.hook(['asset.created'], secret='s3cret')
        self.run_commit(lambda: Asset.objects.create(
            organization=self.org, name='Server-01', asset_type='server'))

        self.assertEqual(len(self.session.calls), 1)
        call = self.session.calls[0]
        body = json.loads(call['data'])
        self.assertEqual(set(body), {'event', 'timestamp', 'organization', 'data', 'webhook_id'})
        self.assertEqual(body['event'], 'asset.created')
        self.assertEqual(body['organization'], 'acme')
        self.assertEqual(body['webhook_id'], hook.pk)
        self.assertEqual(body['data']['asset_name'], 'Server-01')
        self.assertIsInstance(body['timestamp'], int)
        # Signed with the webhook secret; delivery logged.
        self.assertEqual(call['headers']['X-Webhook-Signature'],
                         generate_signature(call['data'], 's3cret'))
        delivery = WebhookDelivery.objects.get(webhook=hook)
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_SUCCESS)
        self.assertEqual(delivery.event_type, 'asset.created')

    def test_asset_updated_and_deleted(self):
        from assets.models import Asset
        self.hook(['asset.updated', 'asset.deleted'])
        a = self.run_commit(lambda: Asset.objects.create(
            organization=self.org, name='A', asset_type='server'))
        self.assertEqual(self.session.calls, [])  # not subscribed to created
        a.name = 'B'
        self.run_commit(a.save)
        self.run_commit(a.delete)
        self.assertEqual([p['event'] for p in self.payloads()],
                         ['asset.updated', 'asset.deleted'])

    def test_other_org_webhook_not_called(self):
        from assets.models import Asset
        self.hook(['asset.created'], org=self.other)
        self.run_commit(lambda: Asset.objects.create(
            organization=self.org, name='A', asset_type='server'))
        self.assertEqual(self.session.calls, [])

    def test_inactive_or_globally_disabled_sends_nothing(self):
        from assets.models import Asset
        h = self.hook(['asset.created'])
        h.is_active = False
        h.save()
        self.run_commit(lambda: Asset.objects.create(
            organization=self.org, name='A', asset_type='server'))
        self.assertEqual(self.session.calls, [])

        h.is_active = True
        h.save()
        s = SystemSetting.get_settings()
        s.webhooks_enabled = False
        s.save()
        self.run_commit(lambda: Asset.objects.create(
            organization=self.org, name='B', asset_type='server'))
        self.assertEqual(self.session.calls, [])

    def test_nothing_sent_before_commit(self):
        from assets.models import Asset
        self.hook(['asset.created'])
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            Asset.objects.create(organization=self.org, name='A', asset_type='server')
        self.assertEqual(self.session.calls, [])
        self.assertEqual(len(callbacks), 1)

    def test_send_webhook_without_org_is_not_broadcast(self):
        from core.webhook_sender import send_webhook
        self.hook(['asset.created'])
        self.hook(['asset.created'], org=self.other)
        self.assertEqual(send_webhook('asset.created', {'x': 1}, organization=None), 0)
        self.assertEqual(self.session.calls, [])


class FailureIsolationTests(WebhookEventTestBase):

    def test_receiver_failure_does_not_break_save(self):
        from assets.models import Asset
        self.session.fail = True
        hook = self.hook(['asset.created'])
        a = self.run_commit(lambda: Asset.objects.create(
            organization=self.org, name='A', asset_type='server'))
        self.assertTrue(Asset.objects.filter(pk=a.pk).exists())
        delivery = WebhookDelivery.objects.get(webhook=hook)
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_FAILED)

    def test_dispatcher_crash_does_not_break_save(self):
        from assets.models import Asset
        self.hook(['asset.created'])
        with mock.patch('core.webhook_sender.deliver_webhook', side_effect=RuntimeError('boom')):
            a = self.run_commit(lambda: Asset.objects.create(
                organization=self.org, name='A', asset_type='server'))
        self.assertTrue(Asset.objects.filter(pk=a.pk).exists())

    def test_payload_builder_crash_does_not_break_save(self):
        from assets.models import Asset
        self.hook(['asset.created'])
        with mock.patch('core.webhook_events.asset_data', side_effect=RuntimeError('boom')):
            a = self.run_commit(lambda: Asset.objects.create(
                organization=self.org, name='A', asset_type='server'))
        self.assertTrue(Asset.objects.filter(pk=a.pk).exists())
        self.assertEqual(self.session.calls, [])


class VaultEventTests(WebhookEventTestBase):

    SECRET = 'Hunter2-Plaintext!'

    def make_password(self, **kw):
        from vault.models import Password
        pw = Password(organization=self.org, title='Router admin',
                      username='admin-user', url='https://router.acme.test',
                      notes='private note', license_key='LIC-123', **kw)
        pw.set_password(self.SECRET)
        pw.save()
        return pw

    def assert_no_secrets(self, raw):
        for needle in (self.SECRET, 'admin-user', 'private note', 'LIC-123',
                       'encrypted_password', 'otp_secret', 'router.acme.test'):
            self.assertNotIn(needle, raw)

    def test_password_created_updated_deleted_metadata_only(self):
        self.hook(['password.created', 'password.updated', 'password.deleted'])
        pw = self.run_commit(self.make_password)
        pw.title = 'Router admin 2'
        self.run_commit(pw.save)
        self.run_commit(pw.delete)
        self.assertEqual([p['event'] for p in self.payloads()],
                         ['password.created', 'password.updated', 'password.deleted'])
        for call in self.session.calls:
            self.assert_no_secrets(call['data'])
        data = self.payloads()[0]['data']
        self.assertEqual(set(data), {'password_id', 'title', 'password_type', 'folder_id'})
        # Stored delivery log carries no secret either.
        for d in WebhookDelivery.objects.all():
            self.assert_no_secrets(json.dumps(d.payload))

    def test_personal_password_never_announced(self):
        self.hook(['password.created'])
        owner = User.objects.create_user('me', password='x')
        self.run_commit(lambda: self.make_password(is_personal=True, personal_owner=owner))
        self.assertEqual(self.session.calls, [])

    def test_password_accessed_on_reveal_audit(self):
        from audit.models import AuditLog
        pw = self.make_password()
        self.hook(['password.accessed'])
        user = User.objects.create_user('tech', password='x')
        self.run_commit(lambda: AuditLog.objects.create(
            organization=self.org, user=user, username='tech', action='reveal',
            object_type='password', object_id=pw.pk, object_repr=pw.title))
        # A blocked attempt and a plain view are not "accessed".
        self.run_commit(lambda: AuditLog.objects.create(
            organization=self.org, user=user, username='tech', action='read',
            object_type='vault.Password', object_id=pw.pk,
            extra_data={'event': 'vault_extension_reveal', 'blocked_reason': 'no'}))
        self.run_commit(lambda: AuditLog.objects.create(
            organization=self.org, user=user, username='tech', action='read',
            object_type='password', object_id=pw.pk))
        payloads = self.payloads('password.accessed')
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]['data']['accessed_by'], 'tech')
        self.assert_no_secrets(self.session.calls[0]['data'])


class OtherModelEventTests(WebhookEventTestBase):

    def test_document_events_and_global_kb_skipped(self):
        from docs.models import Document
        self.hook(['document.created', 'document.updated'])
        d = self.run_commit(lambda: Document.objects.create(
            organization=self.org, title='Runbook', body='SECRET BODY'))
        d.is_published = False
        self.run_commit(d.save)
        self.run_commit(lambda: Document.objects.create(
            organization=None, title='Global KB', body='x', is_global=True))
        events = [p['event'] for p in self.payloads()]
        self.assertEqual(events, ['document.created', 'document.updated'])
        self.assertNotIn('SECRET BODY', self.session.calls[0]['data'])
        self.assertFalse(self.payloads()[1]['data']['is_published'])

    def test_location_events(self):
        from locations.models import Location
        self.hook(['location.created', 'location.deleted'])
        loc = self.run_commit(lambda: Location.objects.create(
            organization=self.org, name='HQ', street_address='1 Main', city='Austin',
            state='TX', postal_code='78701', country='United States'))
        self.run_commit(loc.delete)
        self.assertEqual([p['event'] for p in self.payloads()],
                         ['location.created', 'location.deleted'])

    def test_organization_updated(self):
        self.hook(['organization.updated'])
        self.org.name = 'Acme Corp'
        self.run_commit(self.org.save)
        p = self.payloads('organization.updated')
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['data']['name'], 'Acme Corp')

    def test_workflow_events(self):
        from processes.models import Process, ProcessExecution
        self.hook(['workflow.started', 'workflow.completed', 'workflow.failed'])
        proc = Process.objects.create(organization=self.org, title='Onboard',
                                      slug='onboard', is_published=True)
        tech = User.objects.create_user('tech', password='x')
        ex = self.run_commit(lambda: ProcessExecution.objects.create(
            process=proc, organization=self.org, status='in_progress', assigned_to=tech))
        self.run_commit(ex.save)  # same status: no event
        ex.status = 'completed'
        self.run_commit(ex.save)
        reloaded = ProcessExecution.objects.get(pk=ex.pk)
        reloaded.status = 'failed'
        self.run_commit(reloaded.save)
        self.assertEqual([p['event'] for p in self.payloads()],
                         ['workflow.started', 'workflow.completed', 'workflow.failed'])
        self.assertEqual(self.payloads()[0]['data']['process_title'], 'Onboard')

    def test_user_events_go_to_member_orgs_only(self):
        self.hook(['user.login', 'user.login_failed', 'user.password_changed'])
        self.hook(['user.login'], org=self.other)
        u = User.objects.create_user('alice', password='old-pass')
        Membership.objects.create(user=u, organization=self.org, role='admin')
        self.run_commit(lambda: user_logged_in.send_robust(sender=User, request=None, user=u))
        self.run_commit(lambda: user_login_failed.send_robust(
            sender=__name__, credentials={'username': 'alice', 'password': 'guess'}, request=None))
        u = User.objects.get(pk=u.pk)
        u.set_password('new-pass')
        self.run_commit(u.save)
        u.first_name = 'Al'
        self.run_commit(u.save)  # not a password change
        events = [p['event'] for p in self.payloads()]
        self.assertEqual(events, ['user.login', 'user.login_failed', 'user.password_changed'])
        for p in self.payloads():
            self.assertEqual(p['organization'], 'acme')
        for call in self.session.calls:
            self.assertNotIn('guess', call['data'])
            self.assertNotIn('new-pass', call['data'])

    def _login(self, user):
        self.run_commit(lambda: user_logged_in.send_robust(sender=User, request=None, user=user))

    def test_msp_staff_activity_sends_no_user_events(self):
        from accounts.models import UserType
        self.hook(['user.login', 'user.logout', 'user.login_failed', 'user.password_changed'])
        superuser = User.objects.create_superuser('root', 'r@x.test', 'pw')
        django_staff = User.objects.create_user('djstaff', password='pw', is_staff=True)
        tech = User.objects.create_user('tech', password='pw')
        tech.profile.user_type = UserType.STAFF
        tech.profile.save()
        for u in (superuser, django_staff, tech):
            Membership.objects.create(user=u, organization=self.org, role='admin')
            self._login(u)
            self.run_commit(lambda: user_login_failed.send_robust(
                sender=__name__, credentials={'username': u.username}, request=None))
            u = User.objects.get(pk=u.pk)
            u.set_password('changed-pw')
            self.run_commit(u.save)
        self.assertEqual(self.session.calls, [])

    def test_customer_user_login_delivered_to_own_org_only(self):
        self.hook(['user.login'])
        self.hook(['user.login'], org=self.other)
        customer = User.objects.create_user('bob', password='pw')
        Membership.objects.create(user=customer, organization=self.org, role='admin')
        self._login(customer)
        p = self.payloads('user.login')
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]['organization'], 'acme')
        self.assertEqual(p[0]['data']['username'], 'bob')

    def test_integration_sync_events(self):
        from integrations.sync import fire_sync_webhook
        self.hook(['integration.synced', 'integration.failed'])
        conn = mock.Mock(pk=7, organization_id=self.org.pk, provider_type='ninjaone')
        conn.name = 'Ninja'
        self.run_commit(lambda: fire_sync_webhook(
            conn, 'rmm', 'success', {'devices': {'created': 2, 'errors': 0}, 'note': 'x'}))
        self.run_commit(lambda: fire_sync_webhook(conn, 'rmm', 'error', {}))
        p = self.payloads()
        self.assertEqual([x['event'] for x in p], ['integration.synced', 'integration.failed'])
        self.assertEqual(p[0]['data']['stats'], {'devices': {'created': 2, 'errors': 0}})


class OfferedEventsTests(TestCase):

    def test_form_offers_only_events_that_fire(self):
        from core.webhook_forms import WebhookForm
        offered = {v for v, _ in WebhookForm().fields['events'].choices}
        self.assertEqual(offered, set(SUPPORTED_EVENTS))
        model_events = {v for v, _ in Webhook.EVENT_CHOICES}
        self.assertTrue(set(SUPPORTED_EVENTS) <= model_events)


@override_settings(WEBHOOK_DELIVERY_ASYNC=True)
class AsyncWorkerTests(TestCase):

    def test_background_worker_delivers_and_exits(self):
        import threading
        from core import webhook_events
        done = threading.Event()
        seen = []

        def fake_deliver(job):
            seen.append(job)
            done.set()

        with mock.patch.object(webhook_events, '_subscribed_hook_ids', return_value=[1]), \
             mock.patch.object(webhook_events, '_deliver_job', side_effect=fake_deliver), \
             mock.patch.object(webhook_events, 'db_connection'):
            webhook_events._after_commit('asset.created', 1, {'asset_id': 5})
            self.assertTrue(done.wait(5))
            worker = webhook_events._worker
            if worker is not None:
                worker.join(10)
        self.assertEqual(seen, [('asset.created', [1], {'asset_id': 5})])
        self.assertIsNone(webhook_events._worker)

    def test_no_subscribers_starts_no_thread(self):
        from core import webhook_events
        with mock.patch.object(webhook_events, '_subscribed_hook_ids', return_value=[]), \
             mock.patch.object(webhook_events.threading, 'Thread') as thread:
            webhook_events._after_commit('asset.created', 1, {})
        thread.assert_not_called()
