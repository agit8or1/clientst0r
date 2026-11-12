"""End-to-end lifecycle: template → draft → preview → send → view → sign →
final PDF, plus multiple signers, countersigning, approval and decline."""
from datetime import timedelta

from django.core import mail
from django.utils import timezone

from contracts import services, signing
from contracts.models import (ContractDocument as D, ContractEvent, ContractInvitation, ContractSignature,
                              ContractTemplate, ContractVersion)

from .base import BROWSER, ContractTestCase, links_in_outbox, make_staff


class FullFlowTests(ContractTestCase):

    def test_template_to_signed_pdf(self):
        tpl = ContractTemplate.objects.get(name__icontains='Managed IT services', is_sample=True)
        r = self.client.post('/contracts/new/', {'client': self.org.pk, 'start': 'template', 'template': tpl.pk})
        self.assertEqual(r.status_code, 302)
        c = D.objects.latest('pk')
        self.assertEqual(c.template_version, tpl.latest_version)
        self.assertEqual(c.status, D.DRAFT)
        # the primary contact became the first client signer
        self.assertEqual(list(c.signers.values_list('email', flat=True)), ['owner@acme.test'])

        # The builder renders; the sample review note blocks issuing.
        self.assertEqual(self.client.get(f'/contracts/{c.pk}/edit/').status_code, 200)
        self.assertTrue(any('placeholder' in e for e in services.issue_errors(c)))
        r = self.client.post(f'/contracts/{c.pk}/submit/')
        c.refresh_from_db()
        self.assertEqual(c.status, D.DRAFT)

        # Remove notes and price placeholders the way a user would: edit the sections.
        import re
        sections = [dict(s, body=re.sub(r'\[\[[^\]]*\]\]', '', s['body'])) for s in c.sections]
        c.sections = sections
        c.save()
        self.assertEqual(services.issue_errors(c), [])
        self.assertEqual(self.client.get(f'/contracts/{c.pk}/preview/').status_code, 200)
        r = self.client.get(f'/contracts/{c.pk}/preview.pdf')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))

        self.client.post(f'/contracts/{c.pk}/submit/')
        c.refresh_from_db()
        self.assertEqual(c.status, D.READY)
        v = c.current_version
        self.assertTrue(v.pdf.startswith(b'%PDF') if isinstance(v.pdf, bytes) else bytes(v.pdf).startswith(b'%PDF'))
        self.client.post(f'/contracts/{c.pk}/send/', {'delivery': 'email'})
        c.refresh_from_db()
        self.assertEqual(c.status, D.SENT)
        inv = c.invitations.get()
        self.assertEqual(inv.status, ContractInvitation.ACTIVE)
        self.assertEqual(inv.delivery_status, 'accepted')
        tokens = links_in_outbox('owner@acme.test')
        self.assertEqual(len(tokens), 1)
        # the raw token is never stored
        self.assertFalse(inv.tokens.filter(token_hash=tokens[0]).exists())

        r = self.client_class(**BROWSER).get(f'/sign/t/{tokens[0]}/')
        self.assertEqual(r['Referrer-Policy'], 'no-referrer')   # the token URL itself
        cl, page = self.signer_client(tokens[0])
        r = cl.get(page)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Referrer-Policy'], 'same-origin')
        self.assertIn('no-store', r['Cache-Control'])
        self.assertContains(r, c.title)
        self.assertNotContains(r, 'cdn.')          # vendored assets only
        nonce = r.context['nonce']
        cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': nonce, 'interacted': '1'})
        c.refresh_from_db()
        self.assertEqual(c.status, D.VIEWED)
        self.assertEqual(c.view_count, 1)

        r = self.sign_post(cl, inv, printed_name='Pat Q. Client', title='Owner')
        self.assertEqual(r.status_code, 302)
        c.refresh_from_db()
        v.refresh_from_db()
        self.assertEqual(c.status, D.SIGNED)
        self.assertEqual(v.status, ContractVersion.SIGNED)
        self.assertEqual(v.finalization_status, 'done')
        self.assertTrue(bytes(v.final_pdf).startswith(b'%PDF'))
        self.assertTrue(all(v.verify().values()))
        sig = ContractSignature.objects.get(invitation=inv)
        self.assertEqual(sig.content_hash, v.content_hash)
        self.assertEqual(sig.printed_name, 'Pat Q. Client')
        self.assertTrue(all(sig.verify().values()))
        self.assertIn(sig.evidence_hash, v.certificate_json)
        # the signer got the final signed copy
        copies = [m for m in mail.outbox if 'owner@acme.test' in m.to and m.attachments]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].attachments[0][1].startswith(b'%PDF'))
        # and can download it from the page
        r = cl.get(f'/sign/i/{inv.public_id}/document.pdf')
        self.assertEqual(bytes(r.content), bytes(v.final_pdf))
        # staff see both PDFs
        self.assertEqual(self.client.get(f'/contracts/versions/{v.pk}/pdf/signed/').status_code, 200)
        self.assertEqual(self.client.get(f'/contracts/{c.pk}/').status_code, 200)
        kinds = set(c.events.values_list('kind', flat=True))
        for k in ('created', 'issued', 'sent', 'link_requested', 'human_view', 'consent', 'signed', 'completed',
                  'finalized'):
            self.assertIn(k, kinds)

    def test_links_only_delivery_and_copy_link(self):
        c = self.new_contract()
        self.issue_and_send(c, email=False)
        self.assertEqual(links_in_outbox(), [])
        inv = c.invitations.get()
        r = self.client.post(f'/contracts/invitations/{inv.pk}/link/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Cache-Control'], 'no-store')
        link = r.context['link']
        token = link.rstrip('/').rsplit('/', 1)[1]
        cl, page = self.signer_client(token)
        self.assertEqual(cl.get(page).status_code, 200)

    def test_drawn_signature_is_reencoded(self):
        import base64
        import io

        from PIL import Image
        img = Image.new('RGBA', (300, 100), (255, 255, 255, 0))
        for x in range(20, 280):
            img.putpixel((x, 50), (0, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        data = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, page = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv, method='drawn', typed_signature='', signature_data=data)
        sig = ContractSignature.objects.get(invitation=inv)
        self.assertEqual(sig.method, 'drawn')
        self.assertTrue(sig.signature_image.startswith('data:image/png;base64,'))
        # A blank or non-PNG drawing is refused.
        c2 = self.new_contract(signers=[{'name': 'Bo', 'email': 'bo@acme.test'}])
        self.issue_and_send(c2)
        inv2 = c2.invitations.get()
        cl2, _ = self.signer_client(links_in_outbox('bo@acme.test')[0])
        self.sign_post(cl2, inv2, method='drawn', signature_data='data:image/svg+xml;base64,PHN2Zz4=')
        self.assertFalse(ContractSignature.objects.filter(invitation=inv2).exists())


class MultipleSignerTests(ContractTestCase):

    def test_sequential_clients_then_countersign(self):
        bob = make_staff('bob')
        c = self.new_contract(signing_order='sequential', require_countersignature=True, signers=[
            {'name': 'Ann First', 'email': 'ann@acme.test', 'order': 1},
            {'name': 'Ben Second', 'email': 'ben@acme.test', 'order': 2},
            {'name': 'Bob Msp', 'email': 'bob@msp.test', 'role': 'internal', 'order': 1, 'user': bob}])
        self.issue_and_send(c)
        ann, ben, bobi = (c.invitations.get(email=e) for e in ('ann@acme.test', 'ben@acme.test', 'bob@msp.test'))
        self.assertEqual([ann.status, ben.status, bobi.status], ['active', 'waiting', 'waiting'])
        self.assertEqual(len(links_in_outbox('ben@acme.test')), 0)

        # Ben can't sign out of turn even with a link minted for him.
        raw, _tok = signing.mint_token(ben, 'link')
        clb, _ = self.signer_client(raw)
        r = self.sign_post(clb, ben)
        self.assertFalse(ContractSignature.objects.filter(invitation=ben).exists())

        cla, _ = self.signer_client(links_in_outbox('ann@acme.test')[0])
        self.sign_post(cla, ann)
        c.refresh_from_db()
        ben.refresh_from_db()
        self.assertEqual(c.status, D.PARTIALLY_SIGNED)
        self.assertEqual(ben.status, 'active')
        self.assertEqual(len(links_in_outbox('ben@acme.test')), 1)

        clb2, _ = self.signer_client(links_in_outbox('ben@acme.test')[0])
        self.sign_post(clb2, ben)
        bobi.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual(bobi.status, 'active')
        self.assertEqual(c.status, D.PARTIALLY_SIGNED)

        # The countersigner signs from their own signed-in account.
        staff_client = self.client_class()
        staff_client.defaults.update(BROWSER)
        from django.test import override_settings  # noqa: F401
        staff_client.force_login(bob)
        r = staff_client.get(f'/contracts/invitations/{bobi.pk}/countersign/')
        self.assertEqual(r.status_code, 302)
        # someone else cannot use that route
        self.assertEqual(self.client.get(f'/contracts/invitations/{bobi.pk}/countersign/').status_code, 403)
        self.sign_post(staff_client, bobi)
        c.refresh_from_db()
        self.assertEqual(c.status, D.SIGNED)
        sig = ContractSignature.objects.get(invitation=bobi)
        self.assertEqual(sig.verification_level, 'staff_account')
        self.assertEqual(c.current_version.signatures.count(), 3)

    def test_parallel_invites_everyone_at_once(self):
        c = self.new_contract(signers=[{'name': 'Ann', 'email': 'ann@acme.test'},
                                       {'name': 'Ben', 'email': 'ben@acme.test'}])
        self.issue_and_send(c)
        self.assertEqual(set(c.invitations.values_list('status', flat=True)), {'active'})
        self.assertEqual(len(links_in_outbox()), 2)

    def test_countersignature_required_without_internal_signer_blocks_issue(self):
        c = self.new_contract(require_countersignature=True)
        self.assertTrue(any('countersigner' in e for e in services.issue_errors(c)))

    def test_decline_closes_the_contract(self):
        c = self.new_contract(signers=[{'name': 'Ann', 'email': 'ann@acme.test'},
                                       {'name': 'Ben', 'email': 'ben@acme.test'}])
        self.issue_and_send(c)
        ann = c.invitations.get(email='ann@acme.test')
        cl, _ = self.signer_client(links_in_outbox('ann@acme.test')[0])
        cl.post(f'/sign/i/{ann.public_id}/decline/', {'reason': 'Price too high'})   # no confirm: refused
        ann.refresh_from_db()
        self.assertEqual(ann.status, 'active')
        cl.post(f'/sign/i/{ann.public_id}/decline/', {'reason': 'Price too high', 'confirm': 'yes'})
        c.refresh_from_db()
        ann.refresh_from_db()
        self.assertEqual(c.status, D.DECLINED)
        self.assertEqual(ann.decline_reason, 'Price too high')
        self.assertEqual(c.invitations.get(email='ben@acme.test').status, 'revoked')
        self.assertTrue(c.notifications.filter(kind='declined').exists())


class ApprovalTests(ContractTestCase):

    def test_approval_bound_to_version_and_reapproval(self):
        approver = make_staff('carol', superuser=True)
        c = self.new_contract(require_internal_approval=True)
        services.submit(c, self.staff)
        c.refresh_from_db()
        self.assertEqual(c.status, D.PENDING_APPROVAL)
        v1 = c.current_version
        # Sending before approval is refused on the server.
        c.status = D.PENDING_APPROVAL
        with self.assertRaises(services.ContractError):
            services.send(c, self.staff)
        # The author may not approve their own contract (default setting).
        with self.assertRaises(services.ContractError):
            services.decide(c, self.staff, approve=True, content_hash=v1.content_hash)
        # A stale hash is refused.
        with self.assertRaises(services.ContractError):
            services.decide(c, approver, approve=True, content_hash='0' * 64)
        services.decide(c, approver, approve=True, content_hash=v1.content_hash)
        c.refresh_from_db()
        self.assertEqual(c.status, D.READY)
        self.assertTrue(services.approval_valid(c.current_version))

        # A change after approval needs approval again.
        services.revise(c, self.staff, reason='price change')
        c.refresh_from_db()
        self.assertEqual(c.status, D.DRAFT)
        c.line_items[0]['unit_price'] = '650'
        c.save()
        services.submit(c, self.staff)
        c.refresh_from_db()
        self.assertEqual(c.status, D.PENDING_APPROVAL)
        self.assertNotEqual(c.current_version_id, v1.pk)
        self.assertFalse(services.approval_valid(c.current_version))
        v1.refresh_from_db()
        self.assertEqual(v1.status, ContractVersion.SUPERSEDED)

    def test_rejection_returns_to_draft(self):
        approver = make_staff('carol', superuser=True)
        c = self.new_contract(require_internal_approval=True)
        services.submit(c, self.staff)
        c.refresh_from_db()
        services.decide(c, approver, approve=False, content_hash=c.current_version.content_hash, comment='No')
        c.refresh_from_db()
        self.assertEqual(c.status, D.DRAFT)

    def test_unchanged_resubmit_reuses_the_version(self):
        c = self.new_contract()
        services.submit(c, self.staff)
        c.refresh_from_db()
        v = c.current_version
        services.revise(c, self.staff)
        c.refresh_from_db()
        services.submit(c, self.staff)
        c.refresh_from_db()
        self.assertEqual(c.current_version_id, v.pk)


class StatusMachineTests(ContractTestCase):

    def test_invalid_transitions_are_refused(self):
        c = self.new_contract()
        self.assertFalse(services.can_transition(D.DRAFT, D.SIGNED))
        self.assertFalse(services.can_transition(D.VOIDED, D.DRAFT))
        self.assertFalse(services.can_transition(D.SIGNED, D.DRAFT))
        with self.assertRaises(services.InvalidTransition):
            services.transition(c, D.SIGNED)
        # sending a draft
        with self.assertRaises(services.ContractError):
            services.send(c, self.staff)

    def test_void_needs_reason_and_kills_links(self):
        c = self.new_contract()
        self.issue_and_send(c)
        token = links_in_outbox()[0]
        with self.assertRaises(services.ContractError):
            services.void(c, self.staff, '')
        services.void(c, self.staff, 'Sent to the wrong client')
        c.refresh_from_db()
        self.assertEqual(c.status, D.VOIDED)
        cl = self.client_class(**BROWSER)
        r = cl.get(f'/sign/t/{token}/')
        self.assertEqual(r.status_code, 404)
        with self.assertRaises(services.InvalidTransition):
            services.revise(c, self.staff)

    def test_amend_renew_replace_from_signed(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl, inv)
        c.refresh_from_db()
        self.assertEqual(c.status, D.SIGNED)
        a = services.amend(c, self.staff)
        self.assertEqual((a.relation, a.related_contract_id, a.status), ('amends', c.pk, D.DRAFT))
        r = services.renew(c, self.staff)
        self.assertEqual(r.relation, 'renews')
        rep = services.renew(c, self.staff, replace=True)
        self.assertEqual(rep.relation, 'replaces')
        # Signing the replacement supersedes the original.
        mail.outbox = []
        self.issue_and_send(rep)
        inv2 = rep.invitations.get()
        cl2, _ = self.signer_client(links_in_outbox()[0])
        self.sign_post(cl2, inv2)
        c.refresh_from_db()
        self.assertEqual(c.status, D.SUPERSEDED)
        # A billing contract draft can be made from a signed contract.
        rep.refresh_from_db()
        bc = services.create_billing_contract(rep, self.staff)
        self.assertEqual(bc.status, 'draft')
        rep.refresh_from_db()
        self.assertEqual(rep.billing_contract_id, bc.pk)


class LinkStateTests(ContractTestCase):

    def _sent(self, **kw):
        c = self.new_contract(**kw)
        self.issue_and_send(c)
        return c, c.invitations.get(), links_in_outbox()[0]

    def test_revoked_link(self):
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)
        services.revoke(inv, self.staff, reason='wrong person')
        self.assertEqual(self.client_class(**BROWSER).get(f'/sign/t/{token}/').status_code, 404)
        r = cl.get(page)
        self.assertContains(r, 'withdrew')      # the reason, not the document
        self.assertNotContains(r, c.title)
        r = self.sign_post(cl, inv)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())

    def test_expired_link(self):
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)
        ContractInvitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        r = cl.get(page)
        self.assertContains(r, 'expired')
        self.sign_post(cl, inv)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())
        from contracts import maintenance
        maintenance.expire()
        inv.refresh_from_db()
        self.assertEqual(inv.status, ContractInvitation.EXPIRED)

    def test_acceptance_deadline_expires_contract(self):
        c, inv, token = self._sent()
        D.objects.filter(pk=c.pk).update(acceptance_deadline=timezone.localdate() - timedelta(days=1))
        from contracts import maintenance
        maintenance.expire()
        c.refresh_from_db()
        self.assertEqual(c.status, D.EXPIRED)

    def test_superseded_link_after_revision(self):
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)
        services.revise(c, self.staff, reason='typo')
        c.refresh_from_db()
        c.title = 'Managed services agreement (fixed)'
        c.save()
        mail.outbox = []
        self.issue_and_send(c)
        r = cl.get(page)
        self.assertContains(r, 'replaced')
        self.assertNotContains(r, 'Managed services agreement (fixed)')
        self.sign_post(cl, inv)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())
        new_inv = c.invitations.exclude(pk=inv.pk).get()
        self.assertEqual(new_inv.version, c.current_version)

    def test_replace_signer_keeps_version(self):
        c, inv, token = self._sent()
        mail.outbox = []
        new = services.replace_invitation(inv, self.staff, name='Dana New', email='dana@acme.test')
        self.assertEqual(new.version_id, inv.version_id)
        inv.refresh_from_db()
        self.assertEqual(inv.status, ContractInvitation.REVOKED)
        self.assertEqual(self.client_class(**BROWSER).get(f'/sign/t/{token}/').status_code, 404)
        self.assertEqual(len(links_in_outbox('dana@acme.test')), 1)

    def test_email_code_verification(self):
        c, inv, token = self._sent(require_email_verification=True)
        cl, page = self.signer_client(token)
        self.assertContains(cl.get(page), 'E-mail me a code')
        self.sign_post(cl, inv)
        self.assertFalse(ContractSignature.objects.filter(invitation=inv).exists())
        mail.outbox = []
        cl.post(f'/sign/i/{inv.public_id}/code/')
        import re
        code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)
        self.assertEqual(ContractEvent.objects.filter(kind='code_sent').count(), 1)
        cl.post(f'/sign/i/{inv.public_id}/verify/', {'code': '000000' if code != '000000' else '111111'})
        inv.refresh_from_db()
        self.assertEqual(inv.code_attempts, 1)
        cl.post(f'/sign/i/{inv.public_id}/verify/', {'code': code})
        self.sign_post(cl, inv)
        sig = ContractSignature.objects.get(invitation=inv)
        self.assertEqual(sig.verification_level, 'email_code')
        # and the code is single-use
        inv.refresh_from_db()
        self.assertEqual(inv.code_hash, '')
