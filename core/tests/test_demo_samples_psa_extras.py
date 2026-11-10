"""seed_module_samples --only psa_extras: fills the PSA / CRM modules on the
demo customers, adds nothing on a second run, and the list pages render."""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.apps import apps
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.demo_samples import CUSTOMER_SLUGS, MSP_SLUG
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed

SEEDED = [
    'psa.CannedReply', 'psa.ChangeRequest', 'psa.ChangeRequestTransition', 'psa.CABVote', 'psa.Problem',
    'psa.ProblemNote', 'psa.ReleaseWindow', 'psa.PurchaseRequisition', 'psa.PurchaseRequisitionLineItem',
    'psa.PurchaseOrder', 'psa.PurchaseOrderLineItem', 'psa.POReceipt', 'psa.POReceiptLine', 'psa.POBackOrder',
    'psa.TicketCSATSurvey', 'psa.TicketExpense', 'psa.PSAApproval', 'psa.SiteVisit', 'psa.MileageLog',
    'psa.TicketChecklistItem', 'psa.TicketKitItem', 'psa.TicketKBLink', 'psa.ContractMeter',
    'psa.ProjectTemplate', 'psa.ProjectTemplateTask', 'psa.TimesheetSubmission',
    'psa.RecurringPurchaseTemplate', 'crm.Campaign', 'crm.Lead', 'crm.Opportunity', 'crm.SalesActivity',
    'crm.CommissionRule', 'crm.Commission',
]


def _count(label):
    return apps.get_model(label).objects.count()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PsaExtrasSamplesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from assets.models import Vendor
        from docs.models import Document
        from psa.models import Contract, Queue, Ticket, TicketPriority, TicketStatus, TicketType
        _setup_seed()
        _enable_psa_global()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        cls.msp = Organization.objects.create(name='Demo MSP', slug=MSP_SLUG)
        cls.customers = [Organization.objects.create(name=f'Customer {s}', slug=s) for s in CUSTOMER_SLUGS[:3]]
        Vendor.objects.create(name='Dell Technologies', slug='dell-tech')
        queue = Queue.objects.first()
        prio = TicketPriority.objects.get(code='P3')
        incident = TicketType.objects.get(name='Incident')
        open_s, closed_s = TicketStatus.objects.get(name='In Progress'), TicketStatus.objects.get(name='Closed')
        subjects = ['Outlook keeps asking for my password', 'VPN drops every 20 minutes',
                    'Printer offline in accounts', 'New starter laptop']
        for org in cls.customers:
            for i, subject in enumerate(subjects):
                Ticket.objects.create(organization=org, subject=subject, queue=queue, priority=prio,
                                      ticket_type=incident, status=closed_s if i % 2 else open_s,
                                      requester_name='Pat User', requester_email='pat@example.com')
            Document.objects.create(organization=org, title='VPN troubleshooting', slug='vpn-troubleshooting',
                                    body='<p>Steps</p>')
            Contract.objects.create(organization=cls.msp, client_org=org, name='Managed Services',
                                    contract_type='managed_services', status='active',
                                    start_date=date.today() - timedelta(days=90),
                                    recurring_amount=Decimal('1500.00'))

    def _seed(self):
        out = StringIO()
        call_command('seed_module_samples', only=['psa_extras'], stdout=out)
        return out.getvalue()

    def test_seeds_every_model_once(self):
        self._seed()
        first = {label: _count(label) for label in SEEDED}
        empty = [label for label, n in first.items() if not n]
        self.assertEqual(empty, [], f'nothing seeded for {empty}')
        before_tickets = _count('psa.Ticket')

        out = self._seed()
        self.assertEqual({label: _count(label) for label in SEEDED}, first)
        self.assertEqual(_count('psa.Ticket'), before_tickets)
        self.assertIn('Module samples: 0 rows created.', out)

    def test_only_demo_orgs_touched(self):
        from psa.models import ChangeRequest, PurchaseOrder
        from crm.models import Lead
        other = Organization.objects.create(name='Real Customer', slug='real-customer')
        self._seed()
        self.assertFalse(ChangeRequest.objects.filter(organization=other).exists())
        self.assertEqual(set(PurchaseOrder.objects.values_list('organization_id', flat=True)), {self.msp.pk})
        self.assertEqual(set(Lead.objects.values_list('organization_id', flat=True)), {self.msp.pk})

    def test_change_with_cab_approvals(self):
        from psa.models import ChangeRequest
        self._seed()
        cr = ChangeRequest.objects.get(organization=self.customers[0],
                                       ticket__subject='Firewall firmware upgrade to FortiOS 7.4.4')
        self.assertEqual(cr.implementation_status, 'approved')
        self.assertTrue(cr.can_implement())
        self.assertEqual(list(cr.transitions.order_by('at').values_list('to_status', flat=True)),
                         ['pending_cab', 'approved'])
        self.assertNotEqual(cr.ticket.assigned_to_id, self.admin.pk)  # no notifications to a real user

    def _get(self, client, name, org, **kwargs):
        session = client.session
        session['current_organization_id'] = org.id
        session['2fa_prompted'] = True
        session.save()
        r = client.get(reverse(name, kwargs=kwargs or None))
        self.assertEqual(r.status_code, 200, f'{name} returned {r.status_code}')
        return r

    def test_list_pages_render(self):
        self._seed()
        c = Client()
        c.force_login(self.admin)
        cust = self.customers[0]
        self.assertContains(self._get(c, 'psa:change_request_list', cust), 'FortiOS')
        self.assertContains(self._get(c, 'psa:problem_list', cust), 'Outlook credential prompts')
        self._get(c, 'psa:release_list', cust)
        self._get(c, 'psa:canned_reply_list', cust)
        self.assertContains(self._get(c, 'psa:po_list', self.msp), 'Laptop refresh')
        self._get(c, 'psa:requisition_list', self.msp)
        self._get(c, 'psa:project_template_list', self.msp)
        self._get(c, 'psa:timesheet_approval_queue', self.msp)
        self.assertContains(self._get(c, 'crm:lead_list', self.msp), 'Harbor Dental Group')
        self.assertContains(self._get(c, 'crm:opportunity_list', self.msp), 'Managed security add-on')
        self._get(c, 'crm:campaign_list', self.msp)
        self._get(c, 'crm:commission_list', self.msp)

    def test_detail_pages_render(self):
        from crm.models import Lead, Opportunity
        from psa.models import ChangeRequest, Problem, PurchaseOrder, PurchaseRequisition, ReleaseWindow
        self._seed()
        c = Client()
        c.force_login(self.admin)
        for cr in ChangeRequest.objects.select_related('ticket', 'organization'):
            self._get(c, 'psa:change_request_detail', cr.organization, ticket_number=cr.ticket.ticket_number)
        for p in Problem.objects.select_related('organization'):
            self._get(c, 'psa:problem_detail', p.organization, pk=p.pk)
        for rw in ReleaseWindow.objects.select_related('organization'):
            self._get(c, 'psa:release_detail', rw.organization, pk=rw.pk)
        for po in PurchaseOrder.objects.all():
            self._get(c, 'psa:po_detail', self.msp, pk=po.pk)
        for pr in PurchaseRequisition.objects.all():
            self._get(c, 'psa:requisition_detail', self.msp, pk=pr.pk)
        for lead in Lead.objects.all():
            self._get(c, 'crm:lead_detail', self.msp, pk=lead.pk)
        for opp in Opportunity.objects.all():
            self._get(c, 'crm:opportunity_detail', self.msp, pk=opp.pk)
