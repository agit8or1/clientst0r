"""Contract access through the roles program (accounts.contract_access,
accounts.scope, accounts.alert_access): one permission per action,
no self-approval, pricing, alert recipients re-checked at delivery and who
may sign."""
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client

from contracts import jobs, notify, services
from contracts import permissions as perms
from contracts.models import ContractInvitation, ContractJob, ContractNotification, ContractSignature

from .base import BROWSER, ContractTestCase, links_in_outbox, make_staff

ACTION_FLAG = {
    perms.PRICING: 'contracts_view_pricing', perms.EDIT: 'contracts_edit_draft',
    perms.SUBMIT: 'contracts_submit_approval', perms.APPROVE: 'contracts_approve', perms.SEND: 'contracts_send',
    perms.LINKS: 'contracts_manage_links', perms.COUNTERSIGN: 'contracts_countersign',
    perms.VOID: 'contracts_void', perms.DOWNLOAD: 'contracts_download_signed',
    perms.AUDIT: 'contracts_view_audit',
}


def _role(**flags):
    from accounts.models import RoleTemplate
    return RoleTemplate.objects.create(name=f'Contract role {RoleTemplate.objects.count()}', **flags)


def tech_with(username, **flags):
    """An MSP technician whose global role holds exactly `flags`."""
    u = make_staff(username)
    u.profile.global_role_template = _role(**flags)
    u.profile.save()
    return u


def customer(org, username, email, **flags):
    """A customer portal user; with `flags` the membership uses a role
    holding them, otherwise the simple Admin role."""
    from accounts.models import Membership
    u = User.objects.create_user(username, email, 'pw-Long-enough-123')
    if flags:
        Membership.objects.create(user=u, organization=org, role='admin', role_template=_role(**flags),
                                  is_active=True)
    else:
        Membership.objects.create(user=u, organization=org, role='admin', is_active=True)
    return u


class ActionFlagTests(ContractTestCase):

    def test_each_action_needs_its_own_flag(self):
        c = self.new_contract()
        for action, flag in ACTION_FLAG.items():
            with self.subTest(action):
                only_view = tech_with(f'v-{action}', contracts_view=True)
                both = tech_with(f'b-{action}', contracts_view=True, **{flag: True})
                self.assertFalse(perms.has(only_view, action, self.org))
                self.assertTrue(perms.has(both, action, self.org))
                others = {a for a in ACTION_FLAG if a != action and a != perms.APPROVE}
                self.assertFalse(any(perms.has(both, a, self.org) for a in others - {action}))
        self.assertIsNotNone(c)

    def test_provider_wide_actions(self):
        t = tech_with('tpl', contracts_view=True, contracts_manage_templates=True)
        s = tech_with('st', contracts_view=True, contracts_settings=True)
        self.assertTrue(perms.has_global(t, perms.TEMPLATES))
        self.assertFalse(perms.has_global(t, perms.SETTINGS))
        self.assertTrue(perms.has_global(s, perms.SETTINGS))
        self.assertFalse(perms.has_global(s, perms.TEMPLATES))

    def test_view_without_flag_sees_nothing(self):
        c = self.new_contract()
        u = tech_with('none')
        cl = Client()
        cl.force_login(u)
        self.assertEqual(cl.get('/contracts/').status_code, 403)
        self.assertEqual(cl.get(f'/contracts/{c.pk}/').status_code, 404)


class ApprovalTests(ContractTestCase):

    def test_nobody_approves_their_own_version(self):
        approver_flags = dict(contracts_view=True, contracts_edit_draft=True, contracts_submit_approval=True,
                              contracts_approve=True)
        author = tech_with('author', **approver_flags)
        other = tech_with('other', **approver_flags)
        c = self.new_contract(require_internal_approval=True)
        c.created_by = author
        c.save(update_fields=['created_by'])
        services.submit(c, author)
        c.refresh_from_db()
        v = c.current_version
        self.assertFalse(perms.flags_for(author, c)[perms.APPROVE])
        self.assertTrue(perms.flags_for(author, c)['may_approve'])
        with self.assertRaises(services.ContractError):
            services.decide(c, author, approve=True, content_hash=v.content_hash)
        services.decide(c, other, approve=True, content_hash=v.content_hash)
        c.refresh_from_db()
        self.assertEqual(c.status, 'ready_to_send')


class PricingTests(ContractTestCase):

    def test_view_without_pricing_hides_values_and_document(self):
        c = self.new_contract()
        services.submit(c, self.staff)
        c.refresh_from_db()
        v = c.current_version
        u = tech_with('nopricing', contracts_view=True)
        cl = Client()
        cl.force_login(u)
        r = cl.get(f'/contracts/{c.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, '500.00')   # one-time total (setup)
        self.assertNotContains(r, '250.00')   # recurring total (10 x 25)
        self.assertEqual(cl.get(f'/contracts/{c.pk}/preview/').status_code, 403)
        self.assertEqual(cl.get(f'/contracts/versions/{v.pk}/pdf/issued/').status_code, 403)
        self.assertEqual(cl.get(f'/contracts/versions/{v.pk}/snapshot/').status_code, 403)
        r = cl.get('/contracts/')
        self.assertContains(r, c.reference)
        self.assertNotContains(r, 'One-time value')
        priced = tech_with('pricing', contracts_view=True, contracts_view_pricing=True)
        cl.force_login(priced)
        self.assertEqual(cl.get(f'/contracts/versions/{v.pk}/pdf/issued/').status_code, 200)
        self.assertContains(cl.get('/contracts/'), 'One-time value')

    def test_editor_without_pricing_keeps_line_items(self):
        c = self.new_contract()
        before = c.line_items
        u = tech_with('ed', contracts_view=True, contracts_edit_draft=True)
        cl = Client()
        cl.force_login(u)
        r = cl.get(f'/contracts/{c.pk}/edit/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'data-lines')
        r = cl.post(f'/contracts/{c.pk}/autosave/', {'title': 'Renamed', 'draft_revision': c.draft_revision,
                                                     'currency': 'USD', 'tax_rate': '0'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn('one_time_total', r.json())
        c.refresh_from_db()
        self.assertEqual(c.title, 'Renamed')
        self.assertEqual(c.line_items, before)

    def test_signed_copy_needs_download_signed(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        jobs.run_due()
        v = c.versions.get()
        v.refresh_from_db()
        self.assertTrue(v.final_pdf)
        viewer = Client()
        viewer.force_login(tech_with('viewer', contracts_view=True, contracts_view_pricing=True))
        self.assertEqual(viewer.get(f'/contracts/versions/{v.pk}/pdf/signed/').status_code, 403)
        viewer.force_login(tech_with('dl', contracts_view=True, contracts_download_signed=True))
        self.assertEqual(viewer.get(f'/contracts/versions/{v.pk}/pdf/signed/').status_code, 200)


class LinkTests(ContractTestCase):

    def test_send_and_manage_links_are_separate(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        sender = tech_with('sender', contracts_view=True, contracts_send=True)
        linker = tech_with('linker', contracts_view=True, contracts_manage_links=True)
        cl = Client()
        cl.force_login(sender)
        self.assertEqual(cl.post(f'/contracts/invitations/{inv.pk}/link/').status_code, 403)
        self.assertEqual(cl.post(f'/contracts/invitations/{inv.pk}/revoke/').status_code, 403)
        self.assertEqual(cl.post(f'/contracts/invitations/{inv.pk}/resend/').status_code, 302)
        cl.force_login(linker)
        self.assertEqual(cl.post(f'/contracts/invitations/{inv.pk}/resend/').status_code, 403)
        self.assertEqual(cl.post(f'/contracts/invitations/{inv.pk}/link/').status_code, 200)


class AlertRecipientTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        self.watcher = tech_with('watcher', contracts_view=True)
        self.contract = self.new_contract()
        self.contract.notify_users.add(self.watcher)

    def _revoke_view(self):
        role = self.watcher.profile.global_role_template
        role.contracts_view = False
        role.save()
        self.watcher = User.objects.get(pk=self.watcher.pk)   # fresh object: no cached decision

    def test_recipient_who_lost_contracts_view_is_not_told(self):
        self._revoke_view()
        self.assertNotIn(self.watcher, notify.recipients(self.contract))
        notify.notify(self.contract, 'viewed', 'Viewed', 'test:lost', users=[self.watcher])
        notify.notify(self.contract, 'viewed', 'Viewed', 'test:lost2')
        self.assertFalse(ContractNotification.objects.filter(user=self.watcher).exists())
        self.assertFalse(ContractJob.objects.filter(kind='staff_email', payload__to=self.watcher.email).exists())

    def test_queued_email_is_dropped_when_access_is_lost_before_delivery(self):
        mail.outbox = []
        notify.notify(self.contract, 'viewed', 'Contract viewed', 'test:queued')
        self.assertTrue(ContractNotification.objects.filter(user=self.watcher).exists())
        job = ContractJob.objects.get(kind='staff_email', idempotency_key=f'staff:test:queued:{self.watcher.pk}')
        self._revoke_view()
        jobs.run_now([job])
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertFalse([m for m in mail.outbox if self.watcher.email in m.to])
        # and the in-app alert no longer lists it
        cl = Client()
        cl.force_login(self.watcher)
        self.assertEqual(cl.get('/contracts/').status_code, 403)

    def test_recipient_who_still_has_access_gets_the_email(self):
        mail.outbox = []
        notify.notify(self.contract, 'viewed', 'Contract viewed', 'test:ok')
        job = ContractJob.objects.get(kind='staff_email', idempotency_key=f'staff:test:ok:{self.watcher.pk}')
        jobs.run_now([job])
        self.assertTrue([m for m in mail.outbox if self.watcher.email in m.to])

    def test_inactive_or_customer_recipients_are_dropped(self):
        cust = customer(self.org, 'custwatch', 'cw@acme.test')
        self.watcher.is_active = False
        self.watcher.save()
        self.assertEqual(perms.alert_recipients([cust, self.watcher], self.contract), [])


class WhoMaySignTests(ContractTestCase):

    def _countersigned_contract(self, signer_user=None, email='boss@msp.test'):
        c = self.new_contract(require_countersignature=True, signers=[
            {'name': 'Pat Client', 'email': 'pat@acme.test'},
            {'name': 'Boss', 'email': email, 'role': 'internal', 'user': signer_user}])
        self.issue_and_send(c)
        client_inv = c.invitations.get(role='client')
        cl, _ = self.signer_client(links_in_outbox('pat@acme.test')[0])
        self.assertEqual(self.sign_post(cl, client_inv).status_code, 302)
        return c, c.invitations.get(role='internal')

    def test_customer_admin_without_signer_role_cannot_sign_client_invitation(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        admin = customer(self.org, 'custadmin', 'pat@acme.test')     # the invited person, signed in
        cl, _ = self.signer_client(links_in_outbox('pat@acme.test')[0])
        cl.force_login(admin)
        r = cl.get(f'/sign/i/{inv.public_id}/')
        self.assertContains(r, 'not an authorized contract signer')
        self.sign_post(cl, inv)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())

    def test_customer_with_signer_role_can_sign(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        signer = customer(self.org, 'custsign', 'pat@acme.test', portal_contract_sign=True)
        cl, _ = self.signer_client(links_in_outbox('pat@acme.test')[0])
        cl.force_login(signer)
        self.sign_post(cl, inv)
        self.assertTrue(ContractSignature.objects.filter(invitation=inv).exists())

    def test_customer_admin_cannot_countersign_for_the_provider(self):
        c, internal = self._countersigned_contract(email='custadmin@acme.test')
        admin = customer(self.org, 'custadmin2', 'custadmin@acme.test')
        token = links_in_outbox('custadmin@acme.test')[0]
        cl, _ = self.signer_client(token)
        # not signed in: a link alone never countersigns
        self.sign_post(cl, internal)
        self.assertFalse(ContractSignature.objects.filter(invitation=internal).exists())
        cl.force_login(admin)
        self.assertContains(cl.get(f'/sign/i/{internal.public_id}/'), 'signed from a staff account')
        self.sign_post(cl, internal)
        self.assertFalse(ContractSignature.objects.filter(invitation=internal).exists())
        # the staff countersign entry point is closed to them too
        self.assertEqual(cl.get(f'/contracts/invitations/{internal.pk}/countersign/').status_code, 403)

    def test_named_countersigner_needs_the_countersign_flag(self):
        boss = tech_with('boss', contracts_view=True)
        c, internal = self._countersigned_contract(signer_user=boss, email=boss.email)
        cl = Client(**BROWSER)
        cl.force_login(boss)
        self.assertEqual(cl.get(f'/contracts/invitations/{internal.pk}/countersign/').status_code, 403)
        role = boss.profile.global_role_template
        role.contracts_countersign = True
        role.save()
        r = cl.get(f'/contracts/invitations/{internal.pk}/countersign/')
        self.assertEqual(r.status_code, 302)
        self.sign_post(cl, internal)
        internal.refresh_from_db()
        self.assertEqual(internal.status, ContractInvitation.SIGNED)
        self.assertEqual(ContractSignature.objects.get(invitation=internal).verification_level,
                         ContractSignature.STAFF_ACCOUNT)

    def test_builder_refuses_a_countersigner_without_the_flag(self):
        from contracts import forms
        boss = tech_with('boss2', contracts_view=True)
        c = self.new_contract()
        post = {'title': 'T', 'currency': 'USD', 'tax_rate': '0', 'signer-0-name': 'Boss',
                'signer-0-email': boss.email, 'signer-0-role': 'internal', 'signer-0-user': str(boss.pk)}
        from django.http import QueryDict
        q = QueryDict(mutable=True)
        q.update(post)
        _data, errors = forms.parse_contract(q, c)
        self.assertTrue(any('cannot countersign' in e for e in errors), errors)
