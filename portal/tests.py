"""Tests for portal app — Phase 12 v2 portal announcements."""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalAnnouncementTests(TestCase):
    """v3.17.232: portal announcements rendered to portal users."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from portal.models import PortalAnnouncement
        from psa.models import ClientPSASettings

        s = SystemSetting.get_settings()
        s.psa_enabled = True
        # v3.17.243: this test predates the toggle; flip it on.
        s.psa_portal_announcements_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='PortalCo', slug='portal-co')
        cls.other_org = Organization.objects.create(name='OtherCo', slug='portal-other')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        ClientPSASettings.objects.create(organization=cls.other_org, portal_enabled=True)

        cls.user = User.objects.create_user('portal-user', 'p@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.outsider = User.objects.create_user('portal-outsider', 'o@x.com', 'pw')
        Membership.objects.create(user=cls.outsider, organization=cls.other_org,
                                   role=Role.READONLY, is_active=True)

        cls.active = PortalAnnouncement.objects.create(
            organization=cls.org, title='Maintenance window', body='Saturday 2am',
            severity='warning',
        )
        cls.inactive = PortalAnnouncement.objects.create(
            organization=cls.org, title='Old draft', body='Hidden',
            severity='info', is_active=False,
        )
        cls.expired = PortalAnnouncement.objects.create(
            organization=cls.org, title='Past notice', body='gone',
            severity='info',
            expires_at=timezone.now() - timedelta(days=1),
        )
        cls.other_org_ann = PortalAnnouncement.objects.create(
            organization=cls.other_org, title='OtherCo only', body='secret',
            severity='info',
        )
        cls.critical = PortalAnnouncement.objects.create(
            organization=cls.org, title='Critical breach', body='all hands',
            severity='danger', is_dismissable=False,
        )

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_active_for_org_filters_inactive_and_expired(self):
        from portal.models import PortalAnnouncement
        active = list(PortalAnnouncement.active_for_org(self.org).values_list('title', flat=True))
        self.assertIn('Maintenance window', active)
        self.assertIn('Critical breach', active)
        self.assertNotIn('Old draft', active)
        self.assertNotIn('Past notice', active)

    def test_portal_home_shows_active_announcement(self):
        c = Client()
        self._login(c, self.user)
        r = c.get('/portal/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Maintenance window')
        self.assertContains(r, 'Critical breach')
        self.assertNotContains(r, 'Old draft')
        self.assertNotContains(r, 'Past notice')

    def test_portal_home_does_not_leak_other_orgs_announcement(self):
        c = Client()
        self._login(c, self.user)
        r = c.get('/portal/')
        self.assertNotContains(r, 'OtherCo only')

    def test_dismiss_endpoint_filters_announcement_from_subsequent_renders(self):
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/portal/announcement/{self.active.pk}/dismiss/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['ok'], True)
        # Subsequent home render should not include the dismissed one,
        # but should still include the non-dismissable critical one.
        r = c.get('/portal/')
        self.assertNotContains(r, 'Maintenance window')
        self.assertContains(r, 'Critical breach')

    def test_dismiss_endpoint_rejects_non_dismissable(self):
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/portal/announcement/{self.critical.pk}/dismiss/')
        self.assertEqual(r.status_code, 400)

    def test_dismiss_endpoint_404s_cross_org(self):
        c = Client()
        self._login(c, self.user)
        # The user can't dismiss OtherCo's announcement.
        r = c.post(f'/portal/announcement/{self.other_org_ann.pk}/dismiss/')
        self.assertEqual(r.status_code, 404)

    def test_portal_renders_org_brand_color_when_set(self):
        c = Client()
        self._login(c, self.user)
        r = c.get('/portal/')
        body = r.content.decode('utf-8')
        # No color set → no override CSS.
        self.assertNotIn('--bs-primary:', body)
        self.org.portal_primary_color = '#ff7700'
        self.org.save(update_fields=['portal_primary_color'])
        r = c.get('/portal/')
        self.assertContains(r, '#ff7700')

    def test_critical_announcement_has_no_dismiss_button(self):
        c = Client()
        self._login(c, self.user)
        r = c.get('/portal/')
        body = r.content.decode('utf-8')
        # The critical announcement is rendered, but its alert should NOT
        # contain the dismiss-button class.
        self.assertIn('Critical breach', body)
        # Find the critical announcement's div (data-announcement-id) and
        # verify there's no js-dismiss-announcement inside it.
        import re
        match = re.search(
            r'data-announcement-id="' + str(self.critical.pk) + r'"(.*?)</div>',
            body, re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertNotIn('js-dismiss-announcement', match.group(1))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalThreadedRepliesTests(TestCase):
    """v3.17.237: threaded customer comments via parent_comment FK."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import (
            ClientPSASettings, Queue, Ticket, TicketComment,
            TicketPriority, TicketStatus, TicketType,
        )
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='ThreadCo', slug='thread-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('thread-user', 't@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Thread test',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            client_can_view=True,
        )
        cls.parent_comment = TicketComment.objects.create(
            ticket=cls.ticket, body='Top-level question',
            is_internal=False, source='portal', author=cls.user,
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_post_reply_with_parent_id_sets_parent(self):
        from psa.models import TicketComment
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/reply/', data={
            'body': 'A reply to the question',
            'parent_id': str(self.parent_comment.id),
        })
        self.assertEqual(r.status_code, 302)
        reply = TicketComment.objects.filter(
            ticket=self.ticket, body='A reply to the question',
        ).first()
        self.assertIsNotNone(reply)
        self.assertEqual(reply.parent_comment_id, self.parent_comment.id)

    def test_post_reply_without_parent_id_creates_top_level(self):
        from psa.models import TicketComment
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/reply/', data={
            'body': 'Just a top-level reply',
        })
        self.assertEqual(r.status_code, 302)
        reply = TicketComment.objects.filter(body='Just a top-level reply').first()
        self.assertIsNone(reply.parent_comment_id)

    def test_invalid_parent_id_falls_back_to_top_level(self):
        from psa.models import TicketComment
        c = Client()
        self._login(c)
        c.post(f'/portal/t/{self.ticket.ticket_number}/reply/', data={
            'body': 'Bad parent test',
            'parent_id': '999999',
        })
        reply = TicketComment.objects.filter(body='Bad parent test').first()
        self.assertIsNone(reply.parent_comment_id)

    def test_ticket_detail_renders_thread_tree(self):
        from psa.models import TicketComment
        TicketComment.objects.create(
            ticket=self.ticket, body='nested reply',
            is_internal=False, source='portal', author=self.user,
            parent_comment=self.parent_comment,
        )
        c = Client()
        self._login(c)
        r = c.get(f'/portal/t/{self.ticket.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        threads = r.context['threads']
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].id, self.parent_comment.id)
        self.assertEqual(len(threads[0].replies_in_thread), 1)
        self.assertEqual(threads[0].replies_in_thread[0].body, 'nested reply')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalTicketEscalateTests(TestCase):
    """v3.17.236: portal-side escalation."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import (
            ClientPSASettings, Queue, Ticket, TicketPriority,
            TicketStatus, TicketType,
        )
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_portal_escalation_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='EscCo', slug='esc-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('esc-user', 'esc@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Servers slow',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            client_can_view=True,
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_escalate_sets_fields_and_creates_comment(self):
        from psa.models import Ticket, TicketComment
        c = Client()
        self._login(c)
        before = TicketComment.objects.filter(ticket=self.ticket).count()
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/escalate/', data={
            'reason': 'Whole office offline since 9am',
        })
        self.assertEqual(r.status_code, 302)
        ticket = Ticket.objects.get(pk=self.ticket.pk)
        self.assertIsNotNone(ticket.escalated_at)
        self.assertEqual(ticket.escalated_by_id, self.user.id)
        self.assertEqual(ticket.escalation_reason, 'Whole office offline since 9am')
        # Public comment created with the [Escalated by client] tag.
        after = TicketComment.objects.filter(ticket=self.ticket).count()
        self.assertEqual(after, before + 1)
        last = TicketComment.objects.filter(ticket=self.ticket).order_by('-created_at').first()
        self.assertIn('Escalated by client', last.body)

    def test_escalate_rejects_empty_reason(self):
        from psa.models import Ticket
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/escalate/', data={
            'reason': '   ',
        })
        self.assertEqual(r.status_code, 302)
        ticket = Ticket.objects.get(pk=self.ticket.pk)
        self.assertIsNone(ticket.escalated_at)

    def test_second_escalate_updates_reason(self):
        from psa.models import Ticket
        c = Client()
        self._login(c)
        c.post(f'/portal/t/{self.ticket.ticket_number}/escalate/', data={'reason': 'first'})
        c.post(f'/portal/t/{self.ticket.ticket_number}/escalate/', data={'reason': 'second'})
        ticket = Ticket.objects.get(pk=self.ticket.pk)
        self.assertEqual(ticket.escalation_reason, 'second')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalTicketVoteTests(TestCase):
    """v3.17.235: portal user 'I'm affected too' vote on a ticket."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import (
            ClientPSASettings, Queue, Ticket, TicketPriority,
            TicketStatus, TicketType,
        )
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_portal_voting_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='VoteCo', slug='vote-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('vote-user', 'vu@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.user2 = User.objects.create_user('vote-user2', 'vu2@x.com', 'pw')
        Membership.objects.create(user=cls.user2, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Email is down',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            client_can_view=True,
        )

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_vote_creates_ticketvote_row(self):
        from psa.models import TicketVote
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        self.assertIn(r.status_code, [200, 302])
        self.assertEqual(TicketVote.objects.filter(ticket=self.ticket).count(), 1)

    def test_vote_toggles_off_on_second_post(self):
        from psa.models import TicketVote
        c = Client()
        self._login(c, self.user)
        c.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        c.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        self.assertEqual(TicketVote.objects.filter(ticket=self.ticket).count(), 0)

    def test_vote_count_aggregates_across_users(self):
        from psa.models import TicketVote
        c1 = Client()
        c2 = Client()
        self._login(c1, self.user)
        self._login(c2, self.user2)
        c1.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        c2.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        self.assertEqual(TicketVote.objects.filter(ticket=self.ticket).count(), 2)

    def test_ticket_detail_renders_vote_button(self):
        c = Client()
        self._login(c, self.user)
        r = c.get(f'/portal/t/{self.ticket.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "I'm affected")

    def test_xhr_vote_returns_json(self):
        c = Client()
        self._login(c, self.user)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/vote/',
                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['voted'])
        self.assertEqual(body['count'], 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalKBEnhancementTests(TestCase):
    """v3.17.234: Customer-facing KB — featured + view counts."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from docs.models import Document
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='KBCo', slug='kb-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('kb-user', 'kb@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.featured = Document.objects.create(
            organization=cls.org, title='How to file a ticket',
            slug='how-to-file', body='Steps...',
            is_published=True, is_client_visible=True,
            is_featured_in_portal=True,
        )
        cls.regular = Document.objects.create(
            organization=cls.org, title='Vacation FAQ',
            slug='vacation-faq', body='When out...',
            is_published=True, is_client_visible=True,
        )
        cls.popular = Document.objects.create(
            organization=cls.org, title='Reset your password',
            slug='reset-pw', body='Click...',
            is_published=True, is_client_visible=True,
            portal_view_count=42,
        )
        cls.staff_only = Document.objects.create(
            organization=cls.org, title='Staff only — runbook',
            slug='staff-runbook', body='internal',
            is_published=True, is_client_visible=False,
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_kb_list_shows_featured_section(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/kb/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Featured')
        self.assertContains(r, 'How to file a ticket')

    def test_kb_list_orders_by_views_below_featured(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/kb/')
        ctx = r.context
        # Featured row not in 'articles'
        article_titles = [a.title for a in ctx['articles']]
        self.assertNotIn('How to file a ticket', article_titles)
        # Popular (42 views) ahead of regular (0 views)
        self.assertEqual(article_titles[0], 'Reset your password')

    def test_kb_list_excludes_staff_only_articles(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/kb/')
        self.assertNotContains(r, 'Staff only')

    def test_kb_detail_increments_view_count(self):
        from docs.models import Document
        c = Client()
        self._login(c)
        before = Document.objects.get(pk=self.regular.pk).portal_view_count
        c.get(f'/portal/kb/{self.regular.slug}/')
        after = Document.objects.get(pk=self.regular.pk).portal_view_count
        self.assertEqual(after, before + 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalPreferencesTests(TestCase):
    """v3.17.233: portal notification preferences."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role, UserProfile
        from core.models import Organization, SystemSetting
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='PrefsCo', slug='prefs-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('prefs-user', 'pp@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        UserProfile.objects.get_or_create(user=cls.user)

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_get_preferences_renders_three_switches(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/preferences/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Reply to my tickets')
        self.assertContains(r, 'Status changes')
        self.assertContains(r, 'CSAT survey invitations')

    def test_post_persists_preferences(self):
        from accounts.models import UserProfile
        c = Client()
        self._login(c)
        r = c.post('/portal/preferences/', data={
            'reply': 'on',
            # status omitted → False
            'csat': 'on',
        })
        self.assertEqual(r.status_code, 302)
        from django.contrib.auth.models import User as _U
        fresh = _U.objects.get(pk=self.user.pk)
        self.assertTrue(fresh.profile.portal_notify_ticket_reply)
        self.assertFalse(fresh.profile.portal_notify_status_change)
        self.assertTrue(fresh.profile.portal_notify_csat_invite)

    def test_post_persists_phone_and_sms_preference(self):
        from django.contrib.auth.models import User as _U
        c = Client()
        self._login(c)
        c.post('/portal/preferences/', data={
            'phone': '+15551234567',
            'sms_status': 'on',
        })
        fresh = _U.objects.get(pk=self.user.pk)
        self.assertEqual(fresh.profile.phone, '+15551234567')
        self.assertTrue(fresh.profile.portal_notify_sms_status_change)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class Phase12FeatureToggleTests(TestCase):
    """v3.17.243: SystemSetting toggles gate the Phase 12 portal features."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import (
            ClientPSASettings, PSAApproval, Queue, Ticket,
            TicketPriority, TicketStatus, TicketType,
        )
        from portal.models import PortalAnnouncement
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        # All Phase 12 toggles default off.
        s.psa_portal_announcements_enabled = False
        s.psa_portal_voting_enabled = False
        s.psa_portal_escalation_enabled = False
        s.psa_portal_customer_approvals_enabled = False
        s.save()

        cls.org = Organization.objects.create(name='ToggleCo', slug='toggle-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('toggle-user', 'tu@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.ann = PortalAnnouncement.objects.create(
            organization=cls.org, title='Maintenance window', severity='info',
        )
        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Toggle test',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            client_can_view=True,
        )
        cls.approval = PSAApproval.objects.create(
            organization=cls.org, kind='quote',
            object_type='psa.Quote', object_id=1,
            object_repr='Quote XYZ',
            is_client_approval=True,
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def _set_toggle(self, name, value):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        setattr(s, name, value)
        s.save()

    # --- Announcements ---------------------------------------------------

    def test_announcements_hidden_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/')
        self.assertNotContains(r, 'Maintenance window')

    def test_announcements_visible_when_toggle_on(self):
        self._set_toggle('psa_portal_announcements_enabled', True)
        c = Client()
        self._login(c)
        r = c.get('/portal/')
        self.assertContains(r, 'Maintenance window')

    def test_announcement_dismiss_404_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.post(f'/portal/announcement/{self.ann.pk}/dismiss/')
        self.assertEqual(r.status_code, 404)

    # --- Voting ----------------------------------------------------------

    def test_vote_endpoint_404_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        self.assertEqual(r.status_code, 404)

    def test_vote_button_hidden_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.get(f'/portal/t/{self.ticket.ticket_number}/')
        body = r.content.decode('utf-8')
        self.assertNotIn("I'm affected", body)
        self.assertNotIn('btn-outline-warning', body)

    def test_vote_endpoint_works_when_toggle_on(self):
        self._set_toggle('psa_portal_voting_enabled', True)
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/vote/')
        self.assertIn(r.status_code, [200, 302])

    # --- Escalation ------------------------------------------------------

    def test_escalate_endpoint_404_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/escalate/',
                   data={'reason': 'Production down'})
        self.assertEqual(r.status_code, 404)

    def test_escalate_form_hidden_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.get(f'/portal/t/{self.ticket.ticket_number}/')
        self.assertNotContains(r, 'Escalate this ticket')

    def test_escalate_endpoint_works_when_toggle_on(self):
        self._set_toggle('psa_portal_escalation_enabled', True)
        c = Client()
        self._login(c)
        r = c.post(f'/portal/t/{self.ticket.ticket_number}/escalate/',
                   data={'reason': 'Office offline since 9am, 50 users blocked'})
        self.assertEqual(r.status_code, 302)

    # --- Customer approvals ----------------------------------------------

    def test_approvals_list_404_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/approvals/')
        self.assertEqual(r.status_code, 404)

    def test_approvals_decide_404_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.post(f'/portal/approvals/{self.approval.pk}/decide/',
                   data={'decision': 'approve'})
        self.assertEqual(r.status_code, 404)

    def test_approvals_link_hidden_in_nav_when_toggle_off(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/')
        # Nav entry only renders when the toggle is on.
        self.assertNotContains(r, 'Approvals waiting on you')

    def test_approvals_list_works_when_toggle_on(self):
        self._set_toggle('psa_portal_customer_approvals_enabled', True)
        c = Client()
        self._login(c)
        r = c.get('/portal/approvals/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Quote XYZ')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalApprovalTests(TestCase):
    """v3.17.239: customer-side approval workflow."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization, SystemSetting
        from psa.models import ClientPSASettings, PSAApproval
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_portal_customer_approvals_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='ApproveCo', slug='approve-co')
        cls.other_org = Organization.objects.create(name='OtherApproveCo', slug='other-approve')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('approve-user', 'a@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        cls.client_pending = PSAApproval.objects.create(
            organization=cls.org, kind='quote',
            object_type='psa.Quote', object_id=1,
            object_repr='Q-2026-00001 — Network refresh',
            request_comment='Please sign off on this quote',
            is_client_approval=True,
        )
        cls.staff_pending = PSAApproval.objects.create(
            organization=cls.org, kind='time',
            object_type='psa.TicketTimeEntry', object_id=99,
            object_repr='Internal time approval',
            is_client_approval=False,
        )
        cls.other_org_client = PSAApproval.objects.create(
            organization=cls.other_org, kind='quote',
            object_type='psa.Quote', object_id=2,
            object_repr='OTHER-ORG-QUOTE-99',
            is_client_approval=True,
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_list_shows_only_client_approvals_for_user_org(self):
        c = Client()
        self._login(c)
        r = c.get('/portal/approvals/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Network refresh')
        self.assertNotContains(r, 'Internal time approval')
        self.assertNotContains(r, 'OTHER-ORG-QUOTE-99')

    def test_decide_approve_marks_approval(self):
        from psa.models import PSAApproval
        c = Client()
        self._login(c)
        r = c.post(f'/portal/approvals/{self.client_pending.pk}/decide/', data={
            'decision': 'approve',
            'comment': 'Looks good',
        })
        self.assertEqual(r.status_code, 302)
        approval = PSAApproval.objects.get(pk=self.client_pending.pk)
        self.assertEqual(approval.status, 'approved')
        self.assertEqual(approval.decided_by_id, self.user.id)
        self.assertEqual(approval.decision_comment, 'Looks good')

    def test_decide_deny_marks_approval(self):
        from psa.models import PSAApproval
        c = Client()
        self._login(c)
        c.post(f'/portal/approvals/{self.client_pending.pk}/decide/', data={
            'decision': 'deny',
            'comment': 'Out of budget',
        })
        approval = PSAApproval.objects.get(pk=self.client_pending.pk)
        self.assertEqual(approval.status, 'denied')

    def test_decide_cant_touch_staff_only_approval(self):
        c = Client()
        self._login(c)
        r = c.post(f'/portal/approvals/{self.staff_pending.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 404)

    def test_decide_cant_touch_other_org_approval(self):
        c = Client()
        self._login(c)
        r = c.post(f'/portal/approvals/{self.other_org_client.pk}/decide/', data={
            'decision': 'approve',
        })
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalSMSNotifyTests(TestCase):
    """v3.17.238: SMS portal user on ticket status change."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role, UserProfile
        from core.models import Organization, SystemSetting
        from psa.models import (
            ClientPSASettings, Queue, Ticket, TicketPriority,
            TicketStatus, TicketType,
        )
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.sms_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='SMSCo', slug='sms-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('sms-user', 'sms@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                   role=Role.READONLY, is_active=True)
        profile, _ = UserProfile.objects.get_or_create(user=cls.user)
        profile.phone = '+15551234567'
        profile.portal_notify_sms_status_change = True
        profile.save()

        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='SMS test',
            requester_email='sms@x.com',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            client_can_view=True,
        )

    def test_notify_portal_status_change_sends_sms_when_user_opted_in(self):
        from psa.notifications import notify_portal_status_change
        from unittest.mock import patch
        with patch('psa.notifications.core_send_sms_proxy', create=True):
            with patch('core.sms.send_sms') as mock_send:
                mock_send.return_value = {'success': True}
                result = notify_portal_status_change(self.ticket)
                self.assertEqual(result['sms'], 'sent')
                self.assertTrue(mock_send.called)
                args, kwargs = mock_send.call_args
                self.assertEqual(args[0], '+15551234567')
                self.assertIn(self.ticket.ticket_number, args[1])

    def test_notify_portal_status_change_skips_when_opted_out(self):
        from accounts.models import UserProfile
        from psa.notifications import notify_portal_status_change
        UserProfile.objects.filter(user=self.user).update(portal_notify_sms_status_change=False)
        result = notify_portal_status_change(self.ticket)
        self.assertEqual(result['sms'], 'opted out')

    def test_notify_portal_status_change_skips_when_no_user_account(self):
        from psa.notifications import notify_portal_status_change
        self.ticket.requester_email = 'unknown-person@example.com'
        self.ticket.save(update_fields=['requester_email'])
        result = notify_portal_status_change(self.ticket)
        self.assertEqual(result['sms'], 'no user account')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalVaultRevealTests(TestCase):
    """v3.17.615: Reveal on the portal's Shared Credentials page returns the
    password (it read a non-existent attribute and always failed), and is
    still limited to credentials shared with the customer."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        from psa.models import ClientPSASettings
        from core.models import SystemSetting
        from vault.models import Password

        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='VaultCo', slug='vault-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('vault-portal', 'v@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org,
                                  role=Role.READONLY, is_active=True)
        cls.shared = Password(organization=cls.org, title='Wi-Fi', username='guest',
                              client_visible=True, client_access_mode='all_org')
        cls.shared.set_password('correct-horse')
        cls.shared.save()
        cls.staff_only = Password(organization=cls.org, title='Firewall admin',
                                  client_visible=True, client_access_mode='none')
        cls.staff_only.set_password('not-for-you')
        cls.staff_only.save()

    def setUp(self):
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def test_reveal_returns_shared_password_and_is_audited(self):
        from audit.models import AuditLog
        r = self.client.post(f'/portal/vault/{self.shared.pk}/reveal/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['password'], 'correct-horse')
        self.assertEqual(r.json()['username'], 'guest')
        self.assertTrue(AuditLog.objects.filter(
            object_type='vault.Password', object_id=self.shared.pk, action='view').exists())

    def test_staff_only_password_is_not_revealed(self):
        r = self.client.post(f'/portal/vault/{self.staff_only.pk}/reveal/')
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn(b'not-for-you', r.content)

    def test_list_page_scripts_load_after_bootstrap(self):
        r = self.client.get('/portal/vault/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertContains(r, 'Wi-Fi')
        self.assertLess(html.index('bootstrap.bundle'), html.index('new bootstrap.Modal'))
