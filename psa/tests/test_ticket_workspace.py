"""
Ticket page workflow: private reply drafts, presence (collision warning),
optimistic concurrency on posting, unified closeout (resolution + checklist +
sign-off gate surfaced as messages, never a 500) and drafting a KB article
from a resolved ticket.
"""
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import (
    Queue, Ticket, TicketChecklistItem, TicketComment, TicketDraft, TicketKBLink,
    TicketPresence, TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed


def _msgs(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class _WorkspaceBase(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.org = Organization.objects.create(name='Acme', slug='acme-ws')
        self.other_org = Organization.objects.create(name='Other', slug='other-ws')
        self.alice = self._tech('alice_ws')
        self.bob = self._tech('bob_ws')
        self.customer = User.objects.create_user('cust_ws', password='pw', email='c@acme.test')
        Membership.objects.create(user=self.customer, organization=self.org,
                                  role=Role.EDITOR, is_active=True)
        self.ticket = self._ticket(self.org, shared=True)
        self.unshared = self._ticket(self.org, shared=False)
        self.foreign = self._ticket(self.other_org, shared=True)

    def _tech(self, username):
        user = _make_msp_tech(User.objects.create_user(username, password='pw', email=f'{username}@msp.test'))
        Membership.objects.create(user=user, organization=self.org, role=Role.OWNER, is_active=True)
        return user

    def _ticket(self, org, shared=True, **kw):
        return Ticket.objects.create(
            organization=org, subject='Printer offline', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.get(slug='new'),
            client_can_view=shared, **kw)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        session = c.session
        session['current_organization_id'] = self.org.id
        session['2fa_prompted'] = True
        session.save()
        return c

    def url(self, ticket, suffix=''):
        return f'/psa/t/{ticket.ticket_number}/{suffix}'


class TicketDraftTests(_WorkspaceBase):

    def test_save_restore_and_discard(self):
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'draft/'), {'body': 'half-written', 'is_internal': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['saved'])
        d = TicketDraft.objects.get(user=self.alice, ticket=self.ticket)
        self.assertEqual(d.body, 'half-written')
        self.assertTrue(d.is_internal)
        # Restored on page load.
        page = c.get(self.url(self.ticket))
        self.assertContains(page, 'half-written')
        # Explicit discard.
        c.post(self.url(self.ticket, 'draft/'), {'action': 'discard'})
        self.assertFalse(TicketDraft.objects.filter(user=self.alice, ticket=self.ticket).exists())

    def test_other_user_cannot_read_or_overwrite(self):
        TicketDraft.objects.create(user=self.alice, ticket=self.ticket, body='alice secret')
        cb = self._client(self.bob)
        r = cb.get(self.url(self.ticket, 'draft/'))
        self.assertEqual(r.json()['body'], '')
        self.assertNotContains(cb.get(self.url(self.ticket)), 'alice secret')
        # Bob saving/discarding only touches Bob's own draft.
        cb.post(self.url(self.ticket, 'draft/'), {'body': 'bob text'})
        cb.post(self.url(self.ticket, 'draft/'), {'action': 'discard'})
        self.assertEqual(TicketDraft.objects.get(user=self.alice, ticket=self.ticket).body, 'alice secret')
        self.assertFalse(TicketDraft.objects.filter(user=self.bob).exists())

    def test_draft_refused_for_ticket_user_cannot_see(self):
        cc = self._client(self.customer)
        for t in (self.unshared, self.foreign):
            self.assertEqual(cc.post(self.url(t, 'draft/'), {'body': 'x'}).status_code, 404)
            self.assertEqual(cc.get(self.url(t, 'draft/')).status_code, 404)
        self.assertFalse(TicketDraft.objects.filter(user=self.customer).exists())

    def test_customer_draft_never_internal(self):
        cc = self._client(self.customer)
        cc.post(self.url(self.ticket, 'draft/'), {'body': 'hello', 'is_internal': '1'})
        self.assertFalse(TicketDraft.objects.get(user=self.customer).is_internal)

    def test_successful_post_deletes_draft(self):
        TicketDraft.objects.create(user=self.alice, ticket=self.ticket, body='draft')
        c = self._client(self.alice)
        c.post(self.url(self.ticket, 'comment/'), {'body': 'final', 'last_seen_comment_id': '0'})
        self.assertTrue(TicketComment.objects.filter(ticket=self.ticket, body='final').exists())
        self.assertFalse(TicketDraft.objects.filter(user=self.alice, ticket=self.ticket).exists())


class StalePostTests(_WorkspaceBase):

    def test_new_activity_holds_the_post_and_keeps_text(self):
        seen = TicketComment.objects.create(ticket=self.ticket, author=self.alice, body='old')
        TicketComment.objects.create(ticket=self.ticket, author=self.bob, body='bob jumped in')
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'comment/'), {
            'body': 'my reply', 'last_seen_comment_id': str(seen.pk)})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'stale_since={seen.pk}', r['Location'])
        self.assertFalse(TicketComment.objects.filter(body='my reply').exists())
        self.assertEqual(TicketDraft.objects.get(user=self.alice, ticket=self.ticket).body, 'my reply')
        self.assertTrue(any('NOT posted' in m for m in _msgs(r)))
        # Re-render shows the new activity flagged and the text preserved.
        page = c.get(r['Location'])
        self.assertContains(page, 'new since you started writing')
        self.assertContains(page, 'my reply')

    def test_confirm_posts_anyway(self):
        seen = TicketComment.objects.create(ticket=self.ticket, author=self.alice, body='old')
        TicketComment.objects.create(ticket=self.ticket, author=self.bob, body='bob jumped in')
        c = self._client(self.alice)
        c.post(self.url(self.ticket, 'comment/'), {
            'body': 'my reply', 'last_seen_comment_id': str(seen.pk), 'confirm_stale': '1'})
        self.assertTrue(TicketComment.objects.filter(body='my reply').exists())

    def test_own_comments_and_up_to_date_marker_do_not_block(self):
        seen = TicketComment.objects.create(ticket=self.ticket, author=self.alice, body='mine')
        c = self._client(self.alice)
        c.post(self.url(self.ticket, 'comment/'), {
            'body': 'next', 'last_seen_comment_id': str(seen.pk - 1)})
        self.assertTrue(TicketComment.objects.filter(body='next').exists())

    def test_internal_note_unseen_by_customer_does_not_block_customer(self):
        seen = TicketComment.objects.create(ticket=self.ticket, author=self.alice, body='public')
        TicketComment.objects.create(ticket=self.ticket, author=self.bob, body='internal', is_internal=True)
        cc = self._client(self.customer)
        r = cc.post(self.url(self.ticket, 'comment/'), {
            'body': 'customer reply', 'last_seen_comment_id': str(seen.pk)})
        self.assertTrue(TicketComment.objects.filter(body='customer reply').exists())
        self.assertNotIn('stale_since', r['Location'])

    def test_customer_cannot_post_internal_note(self):
        cc = self._client(self.customer)
        cc.post(self.url(self.ticket, 'comment/'), {'body': 'sneaky', 'is_internal': '1'})
        self.assertFalse(TicketComment.objects.get(body='sneaky').is_internal)


class PresenceTests(_WorkspaceBase):

    def test_heartbeat_reports_other_staff(self):
        cb = self._client(self.bob)
        cb.post(self.url(self.ticket, 'presence/'), {'mode': 'replying'})
        ca = self._client(self.alice)
        r = ca.post(self.url(self.ticket, 'presence/'), {'mode': 'viewing'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['others'], [{'name': 'bob_ws', 'mode': 'replying'}])
        page = ca.get(self.url(self.ticket))
        self.assertContains(page, '<strong>bob_ws</strong> is replying', html=False)
        # Leaving clears the row.
        cb.post(self.url(self.ticket, 'presence/'), {'mode': 'left'})
        self.assertEqual(ca.post(self.url(self.ticket, 'presence/')).json()['others'], [])

    def test_customer_gets_no_presence(self):
        TicketPresence.objects.create(user=self.bob, ticket=self.ticket, mode='viewing',
                                      last_seen=timezone.now())
        cc = self._client(self.customer)
        self.assertEqual(cc.post(self.url(self.ticket, 'presence/')).status_code, 403)
        page = cc.get(self.url(self.ticket))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'bob_ws')
        self.assertFalse(TicketPresence.objects.filter(user=self.customer).exists())


class CloseoutTests(_WorkspaceBase):

    def _status(self, slug):
        return TicketStatus.objects.get(slug=slug)

    def test_set_status_terminal_without_resolution_is_refused(self):
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'action/'), {
            'action': 'set_status', 'status': self._status('resolved').pk})
        self.assertEqual(r.status_code, 302)
        self.assertIn('closeout=', r['Location'])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status.slug, 'new')
        self.assertTrue(any('resolution summary is required' in m for m in _msgs(r)))

    def test_set_status_terminal_with_resolution_succeeds(self):
        c = self._client(self.alice)
        c.post(self.url(self.ticket, 'action/'), {
            'action': 'set_status', 'status': self._status('resolved').pk,
            'resolution_summary': 'Replaced toner', 'closure_category': 'fixed'})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status.slug, 'resolved')
        self.assertEqual(self.ticket.resolution_summary, 'Replaced toner')
        self.assertIsNotNone(self.ticket.resolved_at)

    def test_required_checklist_blocks_close_with_message(self):
        TicketChecklistItem.objects.create(ticket=self.ticket, label='Verify backups', is_required=True)
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'action/'), {
            'action': 'close', 'resolution_summary': 'done', 'closure_category': 'fixed'})
        self.assertEqual(r.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.closed_at)
        self.assertTrue(any('Verify backups' in m for m in _msgs(r)))

    def test_signoff_gate_is_message_not_500(self):
        closed = self._status('closed')
        closed.requires_signoff = True
        closed.save()
        c = self._client(self.alice)
        # Close path.
        r = c.post(self.url(self.ticket, 'action/'), {
            'action': 'close', 'resolution_summary': 'done', 'closure_category': 'fixed'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any('sign-off' in m for m in _msgs(r)))
        # Non-terminal status flagged requires_signoff hits the model signal
        # directly — still a message, not a 500.
        sched = self._status('scheduled')
        sched.requires_signoff = True
        sched.save()
        r = c.post(self.url(self.ticket, 'action/'), {'action': 'set_status', 'status': sched.pk})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any('sign-off' in m for m in _msgs(r)))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status.slug, 'new')

    def test_signal_gate_raised_on_save_becomes_message(self):
        """Gate in psa/signals.py: requires_signoff + signed off + outstanding
        checklist → ValidationError at save time; still never a 500."""
        sched = self._status('scheduled')
        sched.requires_signoff = True
        sched.save()
        self.ticket.signed_off_at = self.ticket.created_at
        self.ticket.save(update_fields=['signed_off_at'])
        TicketChecklistItem.objects.create(ticket=self.ticket, label='Photos', is_required=True)
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'action/'), {'action': 'set_status', 'status': sched.pk})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any('checklist' in m for m in _msgs(r)))

    def test_checklist_ui_and_signoff_unblock_close(self):
        closed = self._status('closed')
        closed.requires_signoff = True
        closed.save()
        c = self._client(self.alice)
        c.post(self.url(self.ticket, 'checklist/add/'), {'label': 'Verify backups', 'is_required': '1'})
        item = TicketChecklistItem.objects.get(ticket=self.ticket)
        page = c.get(self.url(self.ticket))
        self.assertContains(page, 'Verify backups')
        c.post(self.url(self.ticket, f'checklist/{item.pk}/toggle/'))
        item.refresh_from_db()
        self.assertTrue(item.is_completed)
        c.post(self.url(self.ticket, 'sign-off/'), {'note': 'all good'})
        r = c.post(self.url(self.ticket, 'action/'), {
            'action': 'close', 'resolution_summary': 'done', 'closure_category': 'fixed'})
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.closed_at, _msgs(r))
        self.assertEqual(self.ticket.status.slug, 'closed')

    def test_customer_cannot_manage_checklist(self):
        cc = self._client(self.customer)
        r = cc.post(self.url(self.ticket, 'checklist/add/'), {'label': 'x'})
        self.assertEqual(r.status_code, 403)
        r = cc.post(self.url(self.ticket, 'sign-off/'))
        self.assertEqual(r.status_code, 403)

    def test_require_time_setting(self):
        s = SystemSetting.get_settings()
        s.psa_closeout_require_time = True
        s.save()
        c = self._client(self.alice)
        data = {'action': 'close', 'resolution_summary': 'done', 'closure_category': 'fixed'}
        r = c.post(self.url(self.ticket, 'action/'), data)
        self.assertTrue(any('Log time' in m for m in _msgs(r)))
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.closed_at)
        c.post(self.url(self.ticket, 'time/manual/'), {'minutes': '15'})
        self.assertTrue(TicketTimeEntry.objects.filter(ticket=self.ticket).exists())
        c.post(self.url(self.ticket, 'action/'), data)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.closed_at)

    def test_refused_closeout_preserves_summary(self):
        TicketChecklistItem.objects.create(ticket=self.ticket, label='Step', is_required=True)
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'action/'), {
            'action': 'close', 'resolution_summary': 'Typed fix text', 'closure_category': 'fixed'})
        page = c.get(r['Location'])
        self.assertContains(page, 'Typed fix text')


class KBDraftTests(_WorkspaceBase):

    def setUp(self):
        super().setUp()
        self.ticket.status = TicketStatus.objects.get(slug='resolved')
        self.ticket.resolution_summary = 'Cleared the print spooler.'
        self.ticket.closure_category = 'fixed'
        self.ticket.resolved_at = self.ticket.created_at
        self.ticket.save()
        TicketComment.objects.create(ticket=self.ticket, author=self.customer, body='It is broken again')
        TicketComment.objects.create(ticket=self.ticket, author=self.alice, body='Restart the spooler service')
        TicketComment.objects.create(ticket=self.ticket, author=self.alice, body='Admin pw is in vault',
                                     is_internal=True)

    def test_creates_unpublished_draft_linked_to_ticket(self):
        from docs.models import Document
        c = self._client(self.alice)
        r = c.post(self.url(self.ticket, 'kb-draft/'))
        doc = Document.objects.get(psa_ticket_links__ticket=self.ticket)
        self.assertRedirects(r, f'/docs/{doc.slug}/edit/', fetch_redirect_response=False)
        self.assertTrue(doc.is_draft)
        self.assertFalse(doc.is_published)
        self.assertIsNone(doc.published_at)
        self.assertFalse(doc.is_client_visible)
        self.assertEqual(doc.owner, self.alice)
        self.assertEqual(doc.organization, self.org)
        self.assertEqual(doc.title, 'Printer offline')
        self.assertIn('Cleared the print spooler.', doc.body)
        self.assertIn('Restart the spooler service', doc.body)
        self.assertNotIn('Admin pw is in vault', doc.body)
        self.assertNotIn('cust_ws', doc.body)
        self.assertTrue(TicketKBLink.objects.filter(ticket=self.ticket, article=doc).exists())
        # A second click reopens the same draft instead of duplicating it.
        c.post(self.url(self.ticket, 'kb-draft/'))
        self.assertEqual(Document.objects.filter(psa_ticket_links__ticket=self.ticket).count(), 1)

    def test_include_internal_notes_opt_in(self):
        from docs.models import Document
        self._client(self.alice).post(self.url(self.ticket, 'kb-draft/'), {'include_internal': '1'})
        self.assertIn('Admin pw is in vault', Document.objects.get().body)

    def test_customer_refused(self):
        from docs.models import Document
        r = self._client(self.customer).post(self.url(self.ticket, 'kb-draft/'))
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Document.objects.exists())

    def test_unresolved_ticket_refused(self):
        from docs.models import Document
        open_ticket = self._ticket(self.org)
        self._client(self.alice).post(self.url(open_ticket, 'kb-draft/'))
        self.assertFalse(Document.objects.exists())
