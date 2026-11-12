"""
Server-side authorization on the PSA staff pages (roles & permissions
program, authz-ops).

Each test drives a URL directly, the way a hand-crafted request would, so a
check that only lived in a template (a hidden button) fails here.

Customer users are org users with memberships (no staff profile); MSP
technicians carry the Staff user type (`_make_msp_tech`), optionally with a
global role template that decides their flags.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.models import (
    Contract, Invoice, Project, PSAApproval, Queue, Quote, ServiceCatalogChange,
    ServiceCatalogItem, Ticket, TicketComment, TicketPriority, TicketStatus,
    TicketTimeEntry, TicketType, TicketWatcher, TimesheetSubmission, WorkflowRule,
)
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed,
)


def _staff_with_role(user, org=None, **flags):
    """An MSP technician whose global role template holds exactly `flags`
    (every other boolean flag False). `org` adds an Editor membership there,
    which @require_write wants for the selected customer; the global role,
    not that membership, decides the flags."""
    from accounts.models import RoleTemplate as RT
    from django.db import models as dj
    values = {f.name: False for f in RT._meta.get_fields()
              if isinstance(f, dj.BooleanField) and f.name != 'is_system_template'}
    values.update(flags)
    role = RT.objects.create(name=f'role-{user.username}', **values)
    _make_msp_tech(user)
    user.profile.global_role_template = role
    user.profile.save()
    if org is not None:
        Membership.objects.create(user=user, organization=org, role=Role.EDITOR, is_active=True)
    return user


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AuthzOpsBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.a = Organization.objects.create(name='Authz A', slug='authz-a')
        cls.b = Organization.objects.create(name='Authz B', slug='authz-b')
        for org in (cls.a, cls.b):
            _enable_psa_for(org)
        cls.superuser = User.objects.create_superuser('az_root', 'root@msp.test', 'pw-az-123')
        cls.tech = _make_msp_tech(User.objects.create_user('az_tech', 'tech@msp.test', 'pw-az-123'))
        # Customer users of A.
        cls.editor_a = User.objects.create_user('az_editor', 'editor@a.test', 'pw-az-123')
        Membership.objects.create(user=cls.editor_a, organization=cls.a, role=Role.EDITOR, is_active=True)
        cls.owner_a = User.objects.create_user('az_owner', 'owner@a.test', 'pw-az-123')
        Membership.objects.create(user=cls.owner_a, organization=cls.a, role=Role.OWNER, is_active=True)
        # Editor in A, Read-Only in B: one role must not lend its flags to the other.
        cls.mixed = User.objects.create_user('az_mixed', 'mixed@a.test', 'pw-az-123')
        Membership.objects.create(user=cls.mixed, organization=cls.a, role=Role.OWNER, is_active=True)
        Membership.objects.create(user=cls.mixed, organization=cls.b, role=Role.READONLY, is_active=True)

    def _ticket(self, org, subject='Printer', **kw):
        kw.setdefault('client_can_view', True)
        kw.setdefault('ticket_type', TicketType.objects.first())
        return Ticket.objects.create(
            organization=org, subject=subject, description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            status=TicketStatus.objects.filter(is_terminal=False).first(), **kw)

    def _c(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.pk
        else:
            s['global_view_mode'] = True
        s.save()
        return c


class TicketScopeTests(AuthzOpsBase):

    def test_staff_global_role_without_tickets_view_sees_no_tickets(self):
        t = self._ticket(self.a)
        nobody = _staff_with_role(User.objects.create_user('az_noview', 'nv@msp.test', 'pw'))
        c = self._c(nobody)
        self.assertEqual(c.get(f'/psa/t/{t.ticket_number}/').status_code, 404)
        self.assertNotContains(c.get('/psa/'), t.ticket_number)
        viewer = _staff_with_role(User.objects.create_user('az_view', 'v@msp.test', 'pw'), tickets_view=True)
        self.assertEqual(self._c(viewer).get(f'/psa/t/{t.ticket_number}/').status_code, 200)

    def test_staff_without_global_role_keep_every_customer(self):
        t = self._ticket(self.b)
        self.assertEqual(self._c(self.tech).get(f'/psa/t/{t.ticket_number}/').status_code, 200)

    def test_customer_own_tickets_only_when_role_disallows_org_wide(self):
        from psa.visibility import customer_ticket_q
        mine = self._ticket(self.a, 'Mine', created_by=self.editor_a)
        by_email = self._ticket(self.a, 'Emailed', requester_email='EDITOR@a.test')
        coworker = self._ticket(self.a, 'Coworker', created_by=self.owner_a)
        internal = self._ticket(self.a, 'Internal', created_by=self.editor_a, client_can_view=False)
        m = Membership.objects.get(user=self.editor_a, organization=self.a)
        own_only = SimpleNamespace(organization_id=self.a.pk,
                                   get_permissions=lambda: SimpleNamespace(portal_tickets_view_org=False))
        seen = set(Ticket.objects.filter(customer_ticket_q(self.editor_a, [own_only]))
                   .values_list('pk', flat=True))
        self.assertEqual(seen, {mine.pk, by_email.pk})
        # Today's roles don't define the flag: org-wide, shared tickets only.
        seen = set(Ticket.objects.filter(customer_ticket_q(self.editor_a, [m])).values_list('pk', flat=True))
        self.assertEqual(seen, {mine.pk, by_email.pk, coworker.pk})
        self.assertNotIn(internal.pk, seen)

    def test_read_only_role_in_one_customer_cannot_reply_there(self):
        tb = self._ticket(self.b)
        ta = self._ticket(self.a)
        c = self._c(self.mixed, self.a)  # Owner of A selected; Read-Only in B
        r = c.post(f'/psa/t/{tb.ticket_number}/comment/', {'body': 'from A'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TicketComment.objects.filter(ticket=tb, body='from A').exists())
        c.post(f'/psa/t/{ta.ticket_number}/comment/', {'body': 'ok in A'})
        self.assertTrue(TicketComment.objects.filter(ticket=ta, body='ok in A').exists())

    def test_customer_cannot_log_time(self):
        t = self._ticket(self.a)
        c = self._c(self.editor_a, self.a)
        self.assertEqual(c.post(f'/psa/t/{t.ticket_number}/time/manual/', {'minutes': '30'}).status_code, 403)
        self.assertEqual(c.post(f'/psa/t/{t.ticket_number}/timer/start/').status_code, 403)
        self.assertFalse(TicketTimeEntry.objects.filter(ticket=t).exists())

    def test_customer_cannot_open_email_log(self):
        t = self._ticket(self.a)
        r = self._c(self.editor_a, self.a).get(f'/psa/t/{t.ticket_number}/conversation/')
        self.assertEqual(r.status_code, 403)

    def test_reassign_needs_tickets_assign(self):
        t = self._ticket(self.a)
        tech = _staff_with_role(User.objects.create_user('az_l1', 'l1@msp.test', 'pw'), self.a,
                                tickets_view=True, tickets_edit=True)
        r = self._c(tech, self.a).post(f'/psa/t/{t.ticket_number}/action/',
                               {'action': 'set_assignee', 'assignee_id': str(self.tech.pk)})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertIsNone(t.assigned_to_id)
        # Assigning yourself stays available.
        self._c(tech, self.a).post(f'/psa/t/{t.ticket_number}/action/', {'action': 'assign_me'})
        t.refresh_from_db()
        self.assertEqual(t.assigned_to_id, tech.pk)

    def test_close_needs_tickets_close(self):
        t = self._ticket(self.a)
        tech = _staff_with_role(User.objects.create_user('az_noclose', 'nc@msp.test', 'pw'), self.a,
                                tickets_view=True, tickets_edit=True)
        r = self._c(tech, self.a).post(f'/psa/t/{t.ticket_number}/action/',
                               {'action': 'close', 'resolution_summary': 'done',
                                'closure_category': 'resolved'})
        self.assertEqual(r.status_code, 403)
        t.refresh_from_db()
        self.assertIsNone(t.closed_at)


class NotificationRecipientTests(AuthzOpsBase):

    def _smtp_on(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.smtp_enabled, s.smtp_host = True, 'smtp.test'
        s.save()

    def test_internal_note_not_mailed_to_customer_watcher(self):
        from psa.views import _notify_watchers
        self._smtp_on()
        t = self._ticket(self.a)
        TicketWatcher.objects.create(ticket=t, user=self.editor_a)
        TicketWatcher.objects.create(ticket=t, user=self.tech)
        note = TicketComment.objects.create(ticket=t, author=self.superuser, body='secret plan',
                                            is_internal=True)
        with mock.patch('django.core.mail.get_connection'), \
                mock.patch('django.core.mail.send_mail') as send:
            _notify_watchers(t, note, self.superuser)
        recipients = [c.kwargs['recipient_list'][0] for c in send.call_args_list]
        self.assertEqual(recipients, ['tech@msp.test'])

    def test_watcher_who_lost_access_gets_nothing(self):
        from psa.views import _notify_watchers
        self._smtp_on()
        t = self._ticket(self.a)
        TicketWatcher.objects.create(ticket=t, user=self.editor_a)
        Membership.objects.filter(user=self.editor_a).update(is_active=False)
        reply = TicketComment.objects.create(ticket=t, author=self.superuser, body='hello')
        with mock.patch('django.core.mail.get_connection'), \
                mock.patch('django.core.mail.send_mail') as send:
            _notify_watchers(t, reply, self.superuser)
        send.assert_not_called()

    def test_customer_mentioned_in_internal_note_is_not_added(self):
        from psa.views import _process_mentions
        t = self._ticket(self.a)
        note = TicketComment.objects.create(ticket=t, author=self.superuser,
                                            body='ask @az_editor later', is_internal=True)
        _process_mentions(t, note, self.superuser)
        self.assertFalse(TicketWatcher.objects.filter(ticket=t, user=self.editor_a).exists())


class ProviderCostTests(AuthzOpsBase):

    def test_customer_never_sees_project_or_contract_margin(self):
        project = Project.objects.create(organization=self.a, client_org=self.a, name='Rollout')
        contract = Contract.objects.create(organization=self.a, client_org=self.a, name='MSA',
                                           start_date=date(2026, 1, 1), hourly_rate=Decimal('150'))
        c = self._c(self.owner_a, self.a)
        r = c.get(f'/psa/projects/{project.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['profit'])
        self.assertNotContains(r, 'Labour cost')
        r = c.get(f'/psa/contracts/{contract.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['snapshot'])
        self.assertNotContains(r, 'Profitability snapshot')
        # MSP staff still see it.
        r = self._c(self.superuser, self.a).get(f'/psa/projects/{project.pk}/')
        self.assertContains(r, 'Labour cost')

    def test_technician_without_financial_flag_sees_no_margin(self):
        project = Project.objects.create(organization=self.a, client_org=self.a, name='Rollout')
        tech = _staff_with_role(User.objects.create_user('az_nofin', 'nf@msp.test', 'pw'), tickets_view=True)
        r = self._c(tech, self.a).get(f'/psa/projects/{project.pk}/')
        self.assertIsNone(r.context['profit'])

    def test_customer_cannot_reach_procurement(self):
        from psa.models import PurchaseOrder
        po = PurchaseOrder.objects.create(organization=self.a, client_org=self.a, title='Switches')
        c = self._c(self.editor_a, self.a)  # Editor holds procurement_view by default
        self.assertEqual(c.get('/psa/purchase-orders/').status_code, 403)
        self.assertEqual(c.get(f'/psa/purchase-orders/{po.pk}/').status_code, 403)
        self.assertEqual(c.get(f'/psa/purchase-orders/{po.pk}/pdf/').status_code, 403)


class MspConfigurationTests(AuthzOpsBase):

    def test_customer_admin_cannot_write_msp_wide_workflow_rules(self):
        c = self._c(self.owner_a, self.a)  # passes @require_admin for A
        self.assertEqual(c.get('/psa/rules/').status_code, 403)
        self.assertEqual(c.get('/psa/rules/templates/').status_code, 403)
        r = c.post('/psa/rules/new/', {'name': 'planted', 'trigger': 'ticket_created',
                                       'conditions': '{}', 'actions': '[]'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(WorkflowRule.objects.filter(name='planted').exists())

    def test_customer_cannot_open_dispatch(self):
        c = self._c(self.editor_a, self.a)
        self.assertEqual(c.get('/psa/dispatch/').status_code, 403)
        self.assertEqual(c.get('/psa/dispatch/heatmap/').status_code, 403)

    def test_customer_owner_cannot_publish_catalog_change(self):
        item = ServiceCatalogItem.objects.create(name='Laptop', slug='az-laptop')
        change = ServiceCatalogChange.objects.create(
            catalog_item=item, proposed_by=self.tech, after_snapshot={'name': 'Hacked'})
        r = self._c(self.owner_a, self.a).post(f'/psa/catalog-changes/{change.pk}/decide/',
                                                {'action': 'approve'})
        self.assertEqual(r.status_code, 404)
        change.refresh_from_db()
        self.assertEqual(change.status, 'pending')

    def test_email_config_needs_integrations_configure_and_own_connection(self):
        from integrations.models import M365Connection
        from psa.models import EmailIngestionConfig
        conn_b = M365Connection.objects.create(organization=self.b, name='B tenant', tenant_id='t-b')
        conn_a = M365Connection.objects.create(organization=self.a, name='A tenant', tenant_id='t-a')
        data = {'client_org_id': str(self.a.pk), 'name': 'Support', 'source': 'graph',
                'graph_mailbox': 'ceo@b.test', 'm365_connection': str(conn_b.pk),
                'default_queue': str(Queue.objects.first().pk),
                'default_priority': str(TicketPriority.objects.first().pk),
                'default_type': str(TicketType.objects.first().pk), 'is_active': 'on'}
        # Editor: no integrations_configure.
        self.assertEqual(self._c(self.editor_a, self.a).post('/psa/email-configs/new/', data).status_code, 403)
        # Owner of A: may configure A, but not with B's tenant connection.
        r = self._c(self.owner_a, self.a).get('/psa/email-configs/new/')
        self.assertEqual(list(r.context['m365_connections']), [conn_a])
        self._c(self.owner_a, self.a).post('/psa/email-configs/new/', data)
        self.assertFalse(EmailIngestionConfig.objects.filter(m365_connection=conn_b).exists())


class CommercialRecordTests(AuthzOpsBase):

    def test_customer_cannot_edit_or_accept_quote(self):
        quote = Quote.objects.create(organization=self.a, client_org=self.a, title='Firewall')
        c = self._c(self.owner_a, self.a)
        self.assertEqual(c.get(f'/psa/quotes/{quote.pk}/edit/').status_code, 403)
        self.assertEqual(c.post(f'/psa/quotes/{quote.pk}/accept/').status_code, 403)
        quote.refresh_from_db()
        self.assertNotEqual(quote.status, 'accepted')
        # Reading their quote is unchanged.
        self.assertEqual(c.get(f'/psa/quotes/{quote.pk}/').status_code, 200)

    def test_quote_writing_needs_pipeline_flag_for_staff_roles(self):
        quote = Quote.objects.create(organization=self.a, client_org=self.a, title='Firewall')
        l1 = _staff_with_role(User.objects.create_user('az_q1', 'q1@msp.test', 'pw'), self.a, tickets_view=True)
        self.assertEqual(self._c(l1, self.a).get(f'/psa/quotes/{quote.pk}/edit/').status_code, 403)
        sales = _staff_with_role(User.objects.create_user('az_q2', 'q2@msp.test', 'pw'), self.a,
                                 crm_manage_pipeline=True)
        self.assertEqual(self._c(sales, self.a).get(f'/psa/quotes/{quote.pk}/edit/').status_code, 200)

    def test_invoicing_paths_need_billing_flag(self):
        t = self._ticket(self.a)
        c = self._c(self.editor_a, self.a)
        self.assertEqual(c.post(f'/psa/invoices/from-ticket/{t.ticket_number}/').status_code, 403)
        self.assertEqual(c.post(f'/psa/clients/{self.a.pk}/charge/',
                                {'description': 'x', 'amount': '10'}).status_code, 403)
        self.assertEqual(c.post(f'/psa/clients/{self.a.pk}/charge/invoice/').status_code, 403)
        inv = Invoice.objects.create(organization=self.a, client_org=self.a, title='Inv',
                                     invoice_date=date.today())
        self.assertEqual(c.post(f'/psa/invoices/{inv.pk}/request-approval/').status_code, 403)
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)

    def test_aging_needs_billing_view_aging(self):
        Invoice.objects.create(organization=self.b, client_org=self.b, title='B inv',
                               invoice_date=date.today(), status='sent')
        self.assertEqual(self._c(self.editor_a, self.a).get('/psa/aging/').status_code, 403)
        tech = _staff_with_role(User.objects.create_user('az_noage', 'na@msp.test', 'pw'), tickets_view=True)
        self.assertEqual(self._c(tech).get('/psa/aging/').status_code, 403)
        # A customer Owner (who holds the flag) sees only their own customer.
        r = self._c(self.owner_a, self.a).get('/psa/aging/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(self.b, [row['client'] for row in r.context['rows']])


class SeparationOfDutiesTests(AuthzOpsBase):

    def test_requester_cannot_approve_own_request(self):
        approval = PSAApproval.objects.create(
            organization=self.a, kind='expense', object_type='psa.Expense', object_id=1,
            object_repr='Hotel', requested_by=self.tech)
        Membership.objects.create(user=self.tech, organization=self.a, role=Role.OWNER, is_active=True)
        self._c(self.tech, self.a).post(f'/psa/approvals/{approval.pk}/decide/', {'decision': 'approve'})
        approval.refresh_from_db()
        self.assertEqual(approval.status, 'pending')

    def test_technician_cannot_approve_own_timesheet(self):
        sub = TimesheetSubmission.objects.create(
            user=self.tech, period_start=date.today() - timedelta(days=7),
            period_end=date.today() - timedelta(days=1), status='pending')
        self._c(self.tech).post(f'/psa/timesheet-approvals/{sub.pk}/decide/', {'decision': 'approve'})
        self._c(self.tech).post('/psa/timesheet-approvals/bulk/',
                                {'decision': 'approve', 'submission_ids': [sub.pk]})
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'pending')


class ChangeRequestScopeTests(AuthzOpsBase):

    def test_cab_flag_from_one_customer_does_not_vote_in_another(self):
        change_type = TicketType.objects.filter(slug='change').first()
        if change_type is None:
            self.skipTest('no change ticket type seeded')
        t = self._ticket(self.b, ticket_type=change_type)
        c = self._c(self.mixed, self.a)  # Owner of A (CAB), Read-Only in B
        r = c.post(f'/psa/t/{t.ticket_number}/change/vote/', {'vote': 'approve'})
        self.assertEqual(r.status_code, 403)


class PortalInviteTests(AuthzOpsBase):

    def test_invite_never_targets_an_msp_account(self):
        c = self._c(self.owner_a, self.a)
        before = Membership.objects.filter(user=self.superuser).count()
        c.post(f'/psa/clients/{self.a.pk}/invite-portal/', {'email': 'ROOT@msp.test'})
        self.assertEqual(Membership.objects.filter(user=self.superuser).count(), before)
        self.assertEqual(len(mail.outbox), 0)

    def test_invite_of_existing_account_sends_no_password_link_and_keeps_role(self):
        other = User.objects.create_user('az_existing', 'existing@b.test', 'real-password-1')
        Membership.objects.create(user=other, organization=self.a, role=Role.ADMIN, is_active=True)
        self._c(self.owner_a, self.a).post(f'/psa/clients/{self.a.pk}/invite-portal/',
                                           {'email': 'existing@b.test'})
        self.assertEqual(len(mail.outbox), 0)
        m = Membership.objects.get(user=other, organization=self.a)
        self.assertEqual(m.role, Role.ADMIN)
        other.refresh_from_db()
        self.assertTrue(other.check_password('real-password-1'))

    def test_new_invite_still_mails_a_link(self):
        self._c(self.owner_a, self.a).post(f'/psa/clients/{self.a.pk}/invite-portal/',
                                           {'email': 'new.person@a.test', 'full_name': 'New Person'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Membership.objects.filter(user__email='new.person@a.test',
                                                  organization=self.a).exists())


class PartnerWebhookTests(AuthzOpsBase):

    def test_share_without_secret_rejects_forged_signature(self):
        import hashlib
        import hmac
        import json
        from psa.models import TicketShare
        partner = Organization.objects.create(name='Partner', slug='az-partner',
                                              is_outsourcing_partner=True)
        t = self._ticket(self.a)
        share = TicketShare.objects.create(ticket=t, partner_org=partner, status='accepted')
        body = json.dumps({'event': 'comment', 'payload': {'body': 'forged'}}).encode()
        sig = hmac.new(b'', body, hashlib.sha256).hexdigest()
        r = Client().post(f'/psa/partners/webhook/{share.pk}/', body, content_type='application/json',
                          HTTP_X_CST0R_SIGNATURE=sig)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TicketComment.objects.filter(ticket=t, body='forged').exists())
