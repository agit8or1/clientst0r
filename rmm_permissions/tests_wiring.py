"""The ticket RMM panel goes through rmm_permissions: overrides, approvals
and the audit apply to handoffs, diagnostics, launches and fix referrals."""
from django.test import override_settings

from audit.models import AuditLog
from psa.tests._base import TEST_MIDDLEWARE
from psa_ai.models import RMMRequest
from psa_ai.tests_rmm import RMMActionBase
from tech_access.testing import grant, make_tech

from . import approvals, overrides
from .models import RMMApproval, RMMPermissionOverride as O
from .tests import fresh


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PanelWiringTests(RMMActionBase):
    def setUp(self):
        super().setUp()
        self.admin = make_tech('secadmin', superuser=True)
        self.peer = make_tech('peer')
        grant(self.peer, self.a, 'l2')

    def _handoff(self):
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/', {'device': self.device.pk})
        return self.post('handoff', {'device': self.device.pk, 'idempotency_key': page.context['idempotency_key'],
                                     'context_digest': page.context['context_digest']})

    def test_unchanged_without_overrides_and_audited(self):
        self._handoff()
        self.assertEqual(RMMRequest.objects.filter(kind='handoff').count(), 1)
        log = AuditLog.objects.filter(object_type='rmm_permission', user=self.tech).latest('pk')
        self.assertTrue(log.success)
        self.assertEqual(log.extra_data['action'], 'rmm.handoff')

    def test_deny_override_blocks_the_panel_action(self):
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/', {'device': self.device.pk})
        data = {'device': self.device.pk, 'idempotency_key': page.context['idempotency_key'],
                'context_digest': page.context['context_digest']}
        overrides.create(self.admin, action='rmm.handoff', effect=O.DENY, organization=self.a, user=self.tech)
        self.assertEqual(self.c.get(f'/psa/t/{self.ticket.ticket_number}/').status_code, 200)
        self.assertIsNone(self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/',
                                     {'device': self.device.pk}).context)  # preview refused
        self.post('handoff', data)
        self.assertFalse(RMMRequest.objects.exists())
        log = AuditLog.objects.filter(object_type='rmm_permission', user=self.tech).latest('pk')
        self.assertFalse(log.success)

    def test_require_approval_files_a_request_then_runs_once_approved(self):
        overrides.create(self.admin, action='rmm.handoff', effect=O.REQUIRE_APPROVAL, organization=self.a)
        self._handoff()
        self.assertFalse(RMMRequest.objects.exists())
        a = RMMApproval.objects.get()
        self.assertEqual((a.requester, a.action, a.status), (self.tech, 'rmm.handoff', RMMApproval.PENDING))
        self.assertFalse(approvals.approve(a, fresh(self.tech))[0])
        self.assertTrue(approvals.approve(a, fresh(self.peer))[0])
        self._handoff()
        self.assertEqual(RMMRequest.objects.filter(kind='handoff').count(), 1)
        a.refresh_from_db()
        self.assertEqual(a.status, RMMApproval.CONSUMED)
