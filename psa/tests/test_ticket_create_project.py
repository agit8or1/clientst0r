"""Project page "New Ticket" (?project=<id>) attaches the ticket to the project."""
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

from core.models import Organization
from core.tests._r681_fixture import TEST_MIDDLEWARE, R681Base
from psa.models import Project, Queue, Ticket, TicketPriority, TicketStatus, TicketType


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketCreateProjectTests(R681Base):

    def test_get_preselects_project_and_client(self):
        p = Project.objects.create(organization=self.a, client_org=self.a, name='Rollout qzx')
        r = self.login(self.manager, self.a).get(reverse('psa:ticket_create') + f'?project={p.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['preselected_project'], p)
        self.assertEqual(r.context['preselected_client_id'], self.a.pk)
        self.assertContains(r, 'name="project"')

    def test_foreign_project_is_ignored(self):
        p = Project.objects.create(organization=self.b, client_org=self.b, name='Bravo proj')
        r = self.login(self.manager, self.a).get(reverse('psa:ticket_create') + f'?project={p.pk}')
        self.assertIsNone(r.context['preselected_project'])

    def test_post_attaches_project(self):
        p = Project.objects.create(organization=self.a, client_org=self.a, name='Rollout qzx')
        c = self.login(self.manager, self.a)
        c.post(reverse('psa:ticket_create'), {
            'client': self.a.pk, 'subject': 'attach me', 'description': 'd', 'project': p.pk,
            'queue': Queue.objects.first().pk, 'status': TicketStatus.objects.first().pk,
            'priority': TicketPriority.objects.first().pk, 'ticket_type': TicketType.objects.first().pk,
        })
        self.assertEqual(Ticket.objects.get(subject='attach me').project, p)
