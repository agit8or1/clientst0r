"""Clock-in must not accept foreign keys pointing at other tenants.

`clock_in_view` built a TimeclockEntry straight from the request body:

    organization_id=data.get('organization_id') or None,
    location_id=data.get('location_id') or None,
    ticket_id=data.get('ticket_id') or None,
    project_id=data.get('project_id') or None,

Nothing checked that those rows belonged to a client the technician works for.
Every other mobile endpoint that accepts an organization_id validates it
against `accessible_org_ids` (see views_tickets, views_vault, views_dispatch
and views_workflows); this one did not.

It matters beyond the record itself: TimeclockEntry carries
`derived_time_entry`, so a clock-in can become a billable time entry against
whichever organization it names.
"""
import json

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token

from accounts.models import Membership, Role
from core.models import Organization

User = get_user_model()

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
NO_THROTTLE_REST = {
    **getattr(django_settings, 'REST_FRAMEWORK', {}),
    'DEFAULT_THROTTLE_RATES': {},
    'DEFAULT_THROTTLE_CLASSES': [],
}

CLOCK_IN = '/api/mobile/v1/timeclock/clock-in/'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class ClockInTenantScopingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='Clock A', slug='clock-a')
        cls.org_b = Organization.objects.create(name='Clock B', slug='clock-b')
        cls.tech = User.objects.create_user('clocktech', 'clock@example.com', 'pw-not-secret')
        Membership.objects.create(user=cls.tech, organization=cls.org_a,
                                  role=Role.EDITOR, is_active=True)
        cls.token = Token.objects.create(user=cls.tech).key

    def setUp(self):
        cache.clear()

    def _post(self, payload):
        return self.client.post(
            CLOCK_IN, data=json.dumps(payload), content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )

    def test_cannot_clock_in_against_an_unrelated_organization(self):
        from field_ops.models import TimeclockEntry
        resp = self._post({'organization_id': self.org_b.pk})
        self.assertIn(
            resp.status_code, (400, 403, 404),
            f'clock-in accepted an organization the technician is not a member of '
            f'(HTTP {resp.status_code})',
        )
        self.assertFalse(
            TimeclockEntry.objects.filter(organization=self.org_b).exists(),
            'a timeclock entry was written against another tenant',
        )

    def test_can_clock_in_against_own_organization(self):
        """The fix must not break the normal path."""
        from field_ops.models import TimeclockEntry
        resp = self._post({'organization_id': self.org_a.pk})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertTrue(
            TimeclockEntry.objects.filter(organization=self.org_a, tech=self.tech).exists())

    def test_can_clock_in_with_no_organization(self):
        """organization_id is optional — omitting it must still work."""
        from field_ops.models import TimeclockEntry
        resp = self._post({})
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.assertTrue(
            TimeclockEntry.objects.filter(tech=self.tech, organization__isnull=True).exists())

    def test_cannot_attach_another_orgs_ticket(self):
        from field_ops.models import TimeclockEntry
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        st = TicketStatus.objects.create(name='Open-cl', slug='open-cl')
        pr = TicketPriority.objects.create(code='PC', name='Normal-cl')
        tt = TicketType.objects.create(name='Incident-cl')
        q = Queue.objects.create(name='Helpdesk-cl')
        t = Ticket.objects.create(organization=self.org_b, subject='B ticket',
                                  status=st, priority=pr, ticket_type=tt, queue=q)
        resp = self._post({'organization_id': self.org_a.pk, 'ticket_id': t.pk})
        entry = TimeclockEntry.objects.filter(tech=self.tech).first()
        if resp.status_code in (200, 201) and entry is not None:
            self.assertIsNone(
                entry.ticket_id,
                'clock-in attached a ticket belonging to another tenant',
            )
        else:
            self.assertIn(resp.status_code, (400, 403, 404))
