"""52.23 — knowledge suggestions without AI: deterministic matching by tag,
alert kind and asset type, scoped to what the viewer may see."""
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import Client, TestCase, override_settings

from assets.models import Asset
from core.models import Organization, Tag
from docs.models import CustomerGroup, Document, DocumentCategory
from processes.models import Process
from psa.kb_suggest import suggest_for_ticket
from psa.models import Queue, Ticket, TicketKBLink, TicketPriority, TicketStatus, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed


class KBSuggestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Acme', slug='acme')
        cls.other = Organization.objects.create(name='Other', slug='other')
        _enable_psa_for(cls.org)
        cls.tech = _make_msp_tech(User.objects.create_user('kbs_tech', 't@msp.test', 'pw-kbs-123'))
        cls.customer = User.objects.create_user('kbs_cust', 'c@acme.test', 'pw-kbs-123')
        cls.tag_printers = Tag.objects.create(organization=cls.org, name='Printers', slug='printers')
        cls.tag_backup = Tag.objects.create(organization=cls.org, name='backup', slug='backup')

    def ticket(self, subject='Printer will not print', tags=None, asset=None, org=None, custom=None):
        return Ticket.objects.create(
            organization=org or self.org, subject=subject, tags=tags or [], related_asset=asset,
            custom_fields=custom or {}, queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.filter(slug='new').first())

    def doc(self, title, org=None, tags=(), category=None, **kw):
        d = Document.objects.create(organization=org or self.org, title=title, slug=title.lower().replace(' ', '-'),
                                    category=category, **kw)
        for t in tags:
            d.tags.add(t)
        return d


class MatchTests(KBSuggestBase):
    def test_match_by_ticket_tag_and_category(self):
        cat = DocumentCategory.objects.create(organization=None, name='Printers', slug='printers')
        by_tag = self.doc('Fix jams', tags=[self.tag_printers], is_global=True)
        by_cat = self.doc('Toner guide', category=cat, is_global=True)
        self.doc('Unrelated', is_global=True)
        out = suggest_for_ticket(self.ticket(tags=['printers']), self.tech)
        self.assertEqual({s.title for s in out}, {'Fix jams', 'Toner guide'})
        self.assertTrue(all('ticket tag printers' in s.reason for s in out))

    def test_match_by_asset_type(self):
        asset = Asset.objects.create(organization=self.org, name='HP1', asset_type='printer')
        self.doc('Printer basics', tags=[self.tag_printers])
        out = suggest_for_ticket(self.ticket(asset=asset), self.tech)
        self.assertEqual([s.title for s in out], ['Printer basics'])
        self.assertIn('matches asset type', out[0].why[0])
        self.assertEqual(out[0].kind, 'article')

    def test_match_by_alert_kind_for_article_and_runbook(self):
        self.doc('Backup failed', tags=[self.tag_backup])
        Process.objects.create(organization=self.org, title='Restore a backup', slug='restore', category='backup')
        t = self.ticket(subject='[Alert] job', tags=['alert', 'alert:backup'],
                        custom={'alert_policy': {'category': 'backup'}})
        out = suggest_for_ticket(t, self.tech)
        self.assertEqual({(s.kind, s.title) for s in out},
                         {('article', 'Backup failed'), ('runbook', 'Restore a backup')})
        self.assertTrue(all('alert kind backup' in s.reason for s in out))
        self.assertIn('/processes/restore/', [s.url for s in out if s.kind == 'runbook'][0])

    def test_ranking_and_reasons(self):
        asset = Asset.objects.create(organization=self.org, name='HP1', asset_type='printer')
        both = self.doc('Printers deep dive', tags=[self.tag_printers])
        only_tag = Tag.objects.create(organization=self.org, name='scanning', slug='scanning')
        weak = self.doc('Scanning tips', tags=[only_tag])
        t = self.ticket(subject='Printers offline', tags=['printers', 'scanning'], asset=asset)
        out = suggest_for_ticket(t, self.tech)
        self.assertEqual([s.title for s in out], ['Printers deep dive', 'Scanning tips'])
        self.assertGreater(out[0].score, out[1].score)
        self.assertIn('matches ticket tag printers', out[0].why)
        self.assertIn('matches asset type printers', out[0].why)
        self.assertTrue(any(w.startswith('title shares') for w in out[0].why))

    def test_limit_of_five(self):
        for i in range(8):
            self.doc(f'Printers {i}', tags=[self.tag_printers])
        self.assertEqual(len(suggest_for_ticket(self.ticket(tags=['printers']), self.tech)), 5)

    def test_no_signal_no_suggestions_and_linked_excluded(self):
        d = self.doc('Fix jams', tags=[self.tag_printers])
        self.assertEqual(suggest_for_ticket(self.ticket(tags=['zzz']), self.tech), [])
        t = self.ticket(tags=['printers'])
        TicketKBLink.objects.create(ticket=t, article=d)
        self.assertEqual(suggest_for_ticket(t, self.tech), [])


class AccessTests(KBSuggestBase):
    def test_other_customers_private_article_never_suggested(self):
        self.doc('Other secret', org=self.other, tags=[self.tag_printers])
        Process.objects.create(organization=self.other, title='Other runbook', slug='orb', category='other')
        mine = self.doc('Mine', tags=[self.tag_printers])
        out = suggest_for_ticket(self.ticket(tags=['printers']), self.tech)
        self.assertEqual([s.title for s in out], ['Mine'])

    def test_global_article_audience_respected(self):
        self.doc('For everyone', org=self.other, tags=[self.tag_printers], is_global=True, audience='all')
        sel = self.doc('Selected only', org=self.other, tags=[self.tag_printers], is_global=True, audience='selected')
        shared = self.doc('Shared to Acme', org=self.other, tags=[self.tag_printers], is_global=True,
                          audience='selected')
        shared.shared_with.add(self.org)
        grp = CustomerGroup.objects.create(name='G')
        grp.organizations.add(self.org)
        viagrp = self.doc('Via group', org=self.other, tags=[self.tag_printers], is_global=True,
                          audience='selected')
        viagrp.shared_with_groups.add(grp)
        out = {s.title for s in suggest_for_ticket(self.ticket(tags=['printers']), self.tech)}
        self.assertEqual(out, {'For everyone', 'Shared to Acme', 'Via group'})

    def test_drafts_archived_and_unpublished_excluded(self):
        self.doc('Live', tags=[self.tag_printers])
        self.doc('Draft', tags=[self.tag_printers], is_draft=True)
        self.doc('Unpub', tags=[self.tag_printers], is_published=False)
        self.doc('Archived', tags=[self.tag_printers], is_archived=True)
        Process.objects.create(organization=self.org, title='Draft run', slug='dr', category='backup',
                               is_published=False)
        out = suggest_for_ticket(self.ticket(tags=['printers', 'alert:backup']), self.tech)
        self.assertEqual([s.title for s in out], ['Live'])

    def test_customer_users_get_nothing(self):
        self.doc('Live', tags=[self.tag_printers])
        self.assertEqual(suggest_for_ticket(self.ticket(tags=['printers']), self.customer), [])


class QueryBoundTests(KBSuggestBase):
    def test_query_count_is_bounded(self):
        asset = Asset.objects.create(organization=self.org, name='HP1', asset_type='printer')
        for i in range(12):
            self.doc(f'Printers {i}', tags=[self.tag_printers])
            Process.objects.create(organization=self.org, title=f'Run {i}', slug=f'run-{i}', category='backup')
        t = self.ticket(tags=['printers', 'alert:backup'], asset=asset)
        t = Ticket.objects.get(pk=t.pk)
        with CaptureQueriesContext(connection) as ctx:
            suggest_for_ticket(t, self.tech)
        self.assertLessEqual(len(ctx), 12)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketPageTests(KBSuggestBase):
    def _web(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def test_card_renders_for_staff_only(self):
        self.doc('Fix jams', tags=[self.tag_printers], is_global=True)
        t = self.ticket(tags=['printers'], custom=None)
        r = self._web(self.tech).get(f'/psa/t/{t.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Suggested articles')
        self.assertContains(r, 'Fix jams')
        self.assertContains(r, 'matches ticket tag printers')

    def test_card_absent_without_matches(self):
        t = self.ticket(tags=['zzz'])
        r = self._web(self.tech).get(f'/psa/t/{t.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Suggested articles')
