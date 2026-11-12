"""Customer-portal authorization (roles & permissions program, authz-ops).

The portal reads four customer-role permissions with a default of True
(portal/views.py: PORTAL_* and psa.visibility.CUSTOMER_ORG_TICKETS_FLAG), so
every existing membership keeps what it has today and a role that sets one
to False is refused. RoleTemplate doesn't carry these flags yet (roles-core
adds them), so the "role says no" cases patch Membership.get_permissions for
one user.
"""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def deny_flags(user, *flags):
    """Make `user`'s memberships answer False for `flags` (a role that
    withholds them); every other flag is the real role's."""
    original = Membership.get_permissions

    def fake(self):
        perms = original(self)
        if self.user_id != user.pk:
            return perms

        class Perms:
            def __getattr__(_, name):
                if name in flags:
                    return False
                return getattr(perms, name)
        return Perms()
    return mock.patch.object(Membership, 'get_permissions', fake)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalTicketAudienceTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from psa.models import ClientPSASettings, Queue, Ticket, TicketComment, TicketPriority, TicketStatus, TicketType
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_portal_voting_enabled = True
        s.psa_portal_escalation_enabled = True
        s.psa_portal_customer_approvals_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='Acme', slug='pz-acme')
        cls.other = Organization.objects.create(name='Other', slug='pz-other')
        for o in (cls.org, cls.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True, enabled=True)
        cls.pat = User.objects.create_user('pz-pat', 'pat@acme.test', 'pw')
        cls.sam = User.objects.create_user('pz-sam', 'sam@acme.test', 'pw')
        cls.olga = User.objects.create_user('pz-olga', 'olga@other.test', 'pw')
        for u, o in ((cls.pat, cls.org), (cls.sam, cls.org), (cls.olga, cls.other)):
            Membership.objects.create(user=u, organization=o, role=Role.READONLY, is_active=True)
        base = dict(queue=Queue.objects.filter(is_active=True).first(),
                    priority=TicketPriority.objects.first(),
                    ticket_type=TicketType.objects.filter(is_active=True).first(),
                    status=TicketStatus.objects.get(slug='new'),
                    visibility='client', client_can_view=True, source='portal')
        cls.pat_ticket = Ticket.objects.create(organization=cls.org, subject='Pat printer', created_by=cls.pat, **base)
        cls.mailed = Ticket.objects.create(organization=cls.org, subject='Pat emailed in',
                                           requester_email='PAT@acme.test', **base)
        cls.sam_ticket = Ticket.objects.create(organization=cls.org, subject='Sam payroll laptop',
                                               created_by=cls.sam, **base)
        cls.other_ticket = Ticket.objects.create(organization=cls.other, subject='Other secret',
                                                 created_by=cls.olga, **base)
        hidden = dict(base, client_can_view=False, visibility='staff')
        cls.internal_ticket = Ticket.objects.create(organization=cls.org, subject='Staff only', created_by=cls.pat,
                                                    **hidden)
        TicketComment.objects.create(ticket=cls.pat_ticket, body='INTERNAL-NOTE-XYZ', is_internal=True)
        TicketComment.objects.create(ticket=cls.pat_ticket, body='Public answer', is_internal=False)

    def setUp(self):
        self.c = _login(self.pat)

    def _detail(self, t):
        return self.c.get(f'/portal/t/{t.ticket_number}/')

    # --- defaults: today's behaviour is preserved -------------------------

    def test_default_role_sees_whole_organization(self):
        r = self.c.get('/portal/')
        self.assertContains(r, 'Pat printer')
        self.assertContains(r, 'Sam payroll laptop')
        self.assertNotContains(r, 'Other secret')
        self.assertNotContains(r, 'Staff only')
        self.assertEqual(self._detail(self.sam_ticket).status_code, 200)

    def test_other_customer_and_staff_only_tickets_404(self):
        for t in (self.other_ticket, self.internal_ticket):
            self.assertEqual(self._detail(t).status_code, 404)
            self.assertEqual(self.c.post(f'/portal/t/{t.ticket_number}/reply/', {'body': 'x'}).status_code, 404)

    def test_internal_comments_never_shown(self):
        r = self._detail(self.pat_ticket)
        self.assertContains(r, 'Public answer')
        self.assertNotContains(r, 'INTERNAL-NOTE-XYZ')

    # --- own-tickets-only role --------------------------------------------

    def test_own_only_role_sees_own_and_requested_tickets(self):
        with deny_flags(self.pat, 'portal_tickets_view_org'):
            r = self.c.get('/portal/')
            self.assertContains(r, 'Pat printer')
            self.assertContains(r, 'Pat emailed in')
            self.assertNotContains(r, 'Sam payroll laptop')
            self.assertEqual(self._detail(self.pat_ticket).status_code, 200)
            self.assertEqual(self._detail(self.mailed).status_code, 200)
            self.assertEqual(self._detail(self.sam_ticket).status_code, 404)

    def test_own_only_role_cannot_act_on_coworkers_ticket_by_url(self):
        from psa.models import TicketComment, TicketVote
        n = self.sam_ticket.ticket_number
        with deny_flags(self.pat, 'portal_tickets_view_org'):
            for path, data in ((f'/portal/t/{n}/reply/', {'body': 'hi'}),
                               (f'/portal/t/{n}/secure-reply/', {'reply': 'pw'}),
                               (f'/portal/t/{n}/escalate/', {'reason': 'now'}),
                               (f'/portal/t/{n}/vote/', {})):
                self.assertEqual(self.c.post(path, data).status_code, 404, path)
        self.assertFalse(TicketComment.objects.filter(ticket=self.sam_ticket).exists())
        self.assertFalse(TicketVote.objects.filter(ticket=self.sam_ticket).exists())
        self.sam_ticket.refresh_from_db()
        self.assertIsNone(self.sam_ticket.escalated_at)

    # --- read-only customer role ------------------------------------------

    def test_role_without_create_cannot_file_tickets(self):
        from psa.models import Ticket
        before = Ticket.objects.count()
        with deny_flags(self.pat, 'portal_tickets_create'):
            self.assertEqual(self.c.get('/portal/new/').status_code, 403)
            self.assertEqual(self.c.post('/portal/new/', {'subject': 'x'}).status_code, 403)
        self.assertEqual(Ticket.objects.count(), before)
        # Default role still files tickets.
        self.assertEqual(self.c.post('/portal/new/', {'subject': 'Allowed'}).status_code, 302)

    def test_role_without_reply_cannot_reply_escalate_or_vote(self):
        from psa.models import TicketComment
        n = self.pat_ticket.ticket_number
        before = TicketComment.objects.filter(ticket=self.pat_ticket).count()
        with deny_flags(self.pat, 'portal_tickets_reply'):
            for path, data in ((f'/portal/t/{n}/reply/', {'body': 'hi'}),
                               (f'/portal/t/{n}/secure-reply/', {'reply': 'pw'}),
                               (f'/portal/t/{n}/escalate/', {'reason': 'now'}),
                               (f'/portal/t/{n}/vote/', {})):
                self.assertEqual(self.c.post(path, data).status_code, 403, path)
            # The page still opens, read-only.
            self.assertEqual(self._detail(self.pat_ticket).status_code, 200)
        self.assertEqual(TicketComment.objects.filter(ticket=self.pat_ticket).count(), before)

    # --- approvals ----------------------------------------------------------

    def _approval(self, **kw):
        from psa.models import PSAApproval
        kw.setdefault('organization', self.org)
        return PSAApproval.objects.create(kind='change', object_type='psa.Ticket', object_id=1,
                                          is_client_approval=True, status='pending', **kw)

    def test_role_without_approve_cannot_decide_generic_approval(self):
        a = self._approval(related_ticket=self.pat_ticket, object_repr='Firewall change')
        with deny_flags(self.pat, 'portal_approve_requests'):
            self.c.post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'pending')
        self.c.post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')

    def test_own_only_role_does_not_see_coworkers_approvals(self):
        self._approval(related_ticket=self.sam_ticket, object_repr='SAM-APPROVAL', requested_by=self.sam)
        self._approval(related_ticket=self.pat_ticket, object_repr='PAT-APPROVAL')
        self.assertContains(self.c.get('/portal/approvals/'), 'SAM-APPROVAL')
        with deny_flags(self.pat, 'portal_tickets_view_org', 'portal_approve_requests'):
            r = self.c.get('/portal/approvals/')
        self.assertContains(r, 'PAT-APPROVAL')
        self.assertNotContains(r, 'SAM-APPROVAL')

    def test_other_customer_approval_404(self):
        a = self._approval(organization=self.other)
        self.assertEqual(self.c.post(f'/portal/approvals/{a.pk}/decide/', {'decision': 'approve'}).status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalQuoteSignGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from psa.models import Quote, QuoteLineItem
        _setup_seed()
        cls.org = Organization.objects.create(name='Acme', slug='qs-acme')
        cls.quote = Quote.objects.create(organization=cls.org, client_org=cls.org, title='Firewall',
                                         status='sent')
        QuoteLineItem.objects.create(quote=cls.quote, description='FW', quantity=1, unit_price=100)

    def _post(self):
        self.quote.refresh_from_db()
        return Client().post(f'/portal/quote/{self.quote.customer_token}/sign/', {
            'signed_by_name': 'Pat', 'signed_by_email': 'pat@acme.test',
            'signature_data': 'data:image/png;base64,AAAA',
            'content_hash': self.quote.content_hash()})

    def _signed(self):
        from psa.models import QuoteSignature
        return QuoteSignature.objects.filter(quote=self.quote).exists()

    def test_pending_internal_approval_blocks_signing(self):
        from psa.models import PSAApproval
        PSAApproval.objects.create(organization=self.org, kind='quote', object_type='psa.Quote',
                                   object_id=self.quote.pk, status='pending')
        self._post()
        self.assertFalse(self._signed())

    def test_denied_internal_approval_blocks_signing(self):
        from psa.models import PSAApproval
        PSAApproval.objects.create(organization=self.org, kind='quote', object_type='psa.Quote',
                                   object_id=self.quote.pk, status='denied')
        self._post()
        self.assertFalse(self._signed())

    def test_expired_quote_cannot_be_signed(self):
        type(self.quote).objects.filter(pk=self.quote.pk).update(valid_until=date.today() - timedelta(days=2))
        self._post()
        self.assertFalse(self._signed())

    def test_approved_quote_can_be_signed(self):
        from psa.models import PSAApproval
        PSAApproval.objects.create(organization=self.org, kind='quote', object_type='psa.Quote',
                                   object_id=self.quote.pk, status='approved')
        self._post()
        self.assertTrue(self._signed())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalAgreementEvidenceTests(TestCase):

    def setUp(self):
        from docs import agreements
        from docs.models import Document
        from docs.tests_agreements import PNG
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='Acme', slug='ag-acme')
        ClientPSASettings.objects.create(organization=self.org, portal_enabled=True)
        staff = User.objects.create_superuser('ag-admin', 'a@msp.test', 'pw')
        self.pat = User.objects.create_user('ag-pat', 'pat@acme.test', 'pw')
        self.sam = User.objects.create_user('ag-sam', 'sam@acme.test', 'pw')
        for u in (self.pat, self.sam):
            Membership.objects.create(user=u, organization=self.org, role=Role.READONLY, is_active=True)
        doc = Document.objects.create(organization=self.org, title='MSA', slug='ag-msa', body='<p>x</p>',
                                      content_type='html', is_published=True, created_by=staff,
                                      last_modified_by=staff)
        self.agreement = agreements.make_agreement(doc, staff, kind='msa', audience='each')
        rev = self.agreement.latest_revision
        for u in (self.pat, self.sam):
            _login(u).post(f'/portal/agreements/{self.agreement.pk}/', {
                'revision': rev.pk, 'content_hash': rev.content_hash, 'signed_by_name': u.username,
                'signed_by_email': u.email, 'accept': 'on', 'signature_data': PNG})
        from docs.agreement_models import AgreementSignature
        self.sam_sig = AgreementSignature.objects.get(user=self.sam)
        self.pat_sig = AgreementSignature.objects.get(user=self.pat)

    def test_coworker_evidence_follows_role(self):
        c = _login(self.pat)
        self.assertEqual(c.get(f'/portal/agreements/evidence/{self.sam_sig.pk}/').status_code, 200)
        with deny_flags(self.pat, 'portal_agreements_view_org'):
            self.assertEqual(c.get(f'/portal/agreements/evidence/{self.sam_sig.pk}/').status_code, 404)
            self.assertEqual(c.get(f'/portal/agreements/evidence/{self.pat_sig.pk}/').status_code, 200)
            r = c.get('/portal/agreements/')
        self.assertNotContains(r, 'sam@acme.test')
