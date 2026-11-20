"""SR-37 (roadmap 51.20): remediation playbooks run only with approval.

- Opening an incident from an alert no longer runs a matching playbook unless
  the playbook has `auto_run` set; it records a "suggested" timeline event.
- A technician with security_alerts_acknowledge approves and runs it from the
  incident; the approver is recorded on the timeline.
- The run_workflow_rule step refuses another customer's rule and never
  reports 'ok' (it runs nothing).
"""
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import RoleTemplate
from core.models import Organization
from psa.models import WorkflowRule
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from security_alerts.models import (
    RemediationPlaybook,
    RemediationPlaybookStep,
    SecurityAlert,
    SecurityIncident,
    SecurityVendorConnection,
    _correlate_alert_to_incident,
    execute_playbook,
)

_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class _Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='PB Org', slug='sr37-pb-org')
        self.other = Organization.objects.create(name='PB Other', slug='sr37-pb-other')
        self.conn = SecurityVendorConnection.objects.create(
            organization=self.org, name='c', provider='defender', category='edr')

    def _playbook(self, **kw):
        pb = RemediationPlaybook.objects.create(organization=self.org, name='Mail SOC', **kw)
        RemediationPlaybookStep.objects.create(
            playbook=pb, order=10, action='send_email', config={'to': 'soc@example.com'})
        return pb

    def _alert(self, ext='forged-1'):
        return SecurityAlert.objects.create(
            connection=self.conn, organization=self.org, external_id=ext,
            severity='critical', title='Forged alert', asset_hint='host-1')


class AutoRunDefaultTests(_Base):
    def test_auto_run_defaults_off(self):
        self.assertFalse(self._playbook().auto_run)

    def test_incident_from_alert_does_not_run_playbook_by_default(self):
        self._playbook()
        inc = _correlate_alert_to_incident(self._alert())
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(inc.events.filter(kind='playbook_action').exists())
        suggested = inc.events.filter(kind='playbook_suggested')
        self.assertEqual(suggested.count(), 1)
        self.assertIn('awaiting approval', suggested.get().message)

    def test_auto_run_playbook_runs_as_before(self):
        self._playbook(auto_run=True)
        inc = _correlate_alert_to_incident(self._alert())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['soc@example.com'])
        self.assertTrue(inc.events.filter(kind='playbook_action', message__contains='status=ok').exists())
        self.assertFalse(inc.events.filter(kind='playbook_suggested').exists())

    def test_dry_run_still_sends_nothing(self):
        pb = self._playbook()
        inc = SecurityIncident.objects.create(organization=self.org, title='t', severity='high')
        results = execute_playbook(pb, inc, dry_run=True)
        self.assertEqual([r[1] for r in results], ['dry'])
        self.assertEqual(len(mail.outbox), 0)

    def test_email_step_without_recipient_is_not_ok(self):
        pb = RemediationPlaybook.objects.create(organization=self.org, name='no-to')
        RemediationPlaybookStep.objects.create(playbook=pb, order=10, action='send_email', config={})
        inc = SecurityIncident.objects.create(organization=self.org, title='t', severity='high')
        self.assertEqual(execute_playbook(pb, inc)[0][1], 'skip')
        self.assertEqual(len(mail.outbox), 0)


class WorkflowRuleStepTests(_Base):
    def _run(self, rule):
        pb = RemediationPlaybook.objects.create(organization=self.org, name='wf')
        RemediationPlaybookStep.objects.create(
            playbook=pb, order=10, action='run_workflow_rule', config={'rule_id': rule.pk})
        inc = SecurityIncident.objects.create(organization=self.org, title='t', severity='high')
        return inc, execute_playbook(pb, inc)[0]

    def test_other_customers_rule_is_refused(self):
        rule = WorkflowRule.objects.create(organization=self.other, name='Other rule', trigger='ticket_created')
        inc, (_, status, msg) = self._run(rule)
        self.assertEqual(status, 'refused')
        self.assertIn('another customer', msg)
        self.assertFalse(inc.events.filter(message__contains='status=ok').exists())

    def test_own_or_global_rule_never_reports_ok(self):
        for org in (self.org, None):
            rule = WorkflowRule.objects.create(organization=org, name='Own rule', trigger='ticket_created')
            inc, (_, status, msg) = self._run(rule)
            self.assertEqual(status, 'skip')
            self.assertIn('not supported', msg)
            self.assertFalse(inc.events.filter(message__contains='status=ok').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, STORAGES=_STORAGES)
class RunPlaybookViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.pb = self._playbook()
        self.inc = _correlate_alert_to_incident(self._alert())
        self.url = reverse('security_alerts:incident_run_playbook', args=[self.inc.pk])

    def _client(self, username, acknowledge):
        user = _make_msp_tech(User.objects.create_user(username, password='pw'))
        user.profile.global_role_template = RoleTemplate.objects.create(
            name=f'{username} role', security_alerts_view=True,
            security_alerts_acknowledge=acknowledge)
        user.profile.save()
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c, user

    def test_viewer_without_acknowledge_cannot_run(self):
        c, _ = self._client('sr37-viewer', acknowledge=False)
        resp = c.post(self.url, {'playbook': self.pb.pk})
        self.assertIn(resp.status_code, (302, 403))
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(self.inc.events.filter(kind='playbook_action').exists())

    def test_get_is_not_allowed(self):
        c, _ = self._client('sr37-get', acknowledge=True)
        self.assertEqual(c.get(self.url).status_code, 405)

    def test_approver_runs_and_is_recorded(self):
        c, user = self._client('sr37-acker', acknowledge=True)
        detail = c.get(reverse('security_alerts:incident_detail', args=[self.inc.pk]))
        self.assertContains(detail, 'Approve and run')
        resp = c.post(self.url, {'playbook': self.pb.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        events = self.inc.events.filter(kind='playbook_action')
        self.assertTrue(events.exists())
        self.assertTrue(all(e.actor_id == user.pk for e in events))
        self.assertTrue(events.filter(message__contains='approved by sr37-acker').exists())

    def test_playbook_from_another_tenant_is_refused(self):
        foreign = RemediationPlaybook.objects.create(organization=self.other, name='Foreign')
        RemediationPlaybookStep.objects.create(
            playbook=foreign, order=10, action='send_email', config={'to': 'x@example.com'})
        c, _ = self._client('sr37-acker2', acknowledge=True)
        c.post(self.url, {'playbook': foreign.pk})
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(self.inc.events.filter(kind='playbook_action').exists())
