"""Ticket role flags on the RMM ticket actions (roles & permissions program,
authz-ops): changing affected devices needs tickets_edit and verify-then-close
needs tickets_close at the ticket's customer; a technician without a global
role keeps today's access."""
from django.test import override_settings

from accounts.models import RoleTemplate
from psa.models import TicketAffectedAsset, TicketStatus
from psa.tests._base import TEST_MIDDLEWARE

from .tests_assist import KEY_DIR
from .tests_device_panel import DevicePanelBase


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AI_GATEWAY_KEY_DIR=KEY_DIR,
                   AI_GATEWAY_MODE='in_process', ALLOWED_HOSTS=['*'])
class RMMTicketActionRoleFlagTests(DevicePanelBase):

    def _role(self, **flags):
        role = RoleTemplate.objects.create(name='Restricted tech', **flags)
        profile = self.tech.profile
        profile.global_role_template = role
        profile.save()

    def test_no_global_role_keeps_access(self):
        self.post('affected', {'op': 'add', 'asset': self.asset2.pk})
        self.assertTrue(TicketAffectedAsset.objects.filter(ticket=self.ticket, asset=self.asset2).exists())

    def test_affected_devices_need_tickets_edit(self):
        self._role(tickets_view=True, tickets_edit=False)
        r = self.post('affected', {'op': 'add', 'asset': self.asset2.pk})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TicketAffectedAsset.objects.filter(ticket=self.ticket, asset=self.asset2).exists())

    def test_verify_close_needs_tickets_close(self):
        TicketStatus.objects.get_or_create(slug='closed', defaults={'name': 'Closed', 'is_terminal': True,
                                                                     'sort_order': 99})
        self._role(tickets_view=True, tickets_edit=True, tickets_close=False)
        r = self.post('verify/close', {'resolution_summary': 'x', 'closure_category': 'fixed',
                                       'acknowledge': '1'})
        self.assertEqual(r.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.closed_at)

    def test_verify_page_needs_tickets_view(self):
        self._role(tickets_view=False)
        r = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/verify/')
        self.assertEqual(r.status_code, 404)
