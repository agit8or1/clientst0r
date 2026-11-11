"""Phase 60.6 — tickets carry the customer's site; routing rules can match it.

Covers: site inference at intake (asset, contact default, portal user default,
the customer's only site), never storing another customer's site, editing on
the ticket (and remembering the requester default), and the routing site
condition through the real portal intake path and the visual rule builder.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset, Contact
from core.models import Organization
from locations.models import Location
from psa.models import (
    ClientPSASettings, Queue, RequesterDefaultSite, Ticket, TicketComment, TicketPriority,
    TicketStatus, TicketType,
)
from psa.routing import engine
from psa.routing.models import RoutingDecision, RoutingRule
from psa.routing.tests import _login, _rule, _set_msp, _tech
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed
from psa.ticket_site import infer_site, remember_default, site_allowed, sites_for


def _loc(org, name, **kw):
    kw.setdefault('street_address', '1 Main St')
    kw.setdefault('city', 'Springfield')
    kw.setdefault('postal_code', '00001')
    return Location.objects.create(organization=org, name=name, **kw)


def _ticket(org, **kw):
    kw.setdefault('subject', 'Something broke')
    return Ticket.objects.create(
        organization=org, status=TicketStatus.objects.get(slug='new'),
        priority=TicketPriority.objects.order_by('sort_order').first(),
        queue=Queue.objects.first(), ticket_type=TicketType.objects.first(), **kw)


class SiteFixture:
    @classmethod
    def build(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Acme', slug='acme')
        cls.other = Organization.objects.create(name='Other Co', slug='other-co')
        for o in (cls.org, cls.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)
        cls.hq = _loc(cls.org, 'HQ', is_primary=True, latitude=Decimal('40.0'), longitude=Decimal('-75.0'))
        cls.branch = _loc(cls.org, 'Branch')
        cls.closed = _loc(cls.org, 'Old office', status='closed')
        cls.foreign = _loc(cls.other, 'Other HQ')
        cls.colo = Location.objects.create(name='Colo', is_shared=True, street_address='9 Rack Rd',
                                           city='X', postal_code='1')
        cls.colo.associated_organizations.add(cls.org)
        cls.portal = User.objects.create_user('acme-portal', 'jane@acme.example', 'pw')
        Membership.objects.create(user=cls.portal, organization=cls.org, role=Role.READONLY, is_active=True)
        cls.contact = Contact.objects.create(organization=cls.org, first_name='Bob', last_name='Ops',
                                             email='bob@acme.example')
        cls.tech = _tech('site-tech')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SiteInferenceTests(SiteFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()

    def test_sites_for_includes_shared_and_excludes_closed_and_foreign(self):
        names = set(sites_for(self.org).values_list('name', flat=True))
        self.assertEqual(names, {'HQ', 'Branch', 'Colo'})
        self.assertTrue(site_allowed(self.org, self.colo))
        self.assertFalse(site_allowed(self.org, self.foreign))
        self.assertFalse(site_allowed(self.other, self.colo))

    def test_no_determinable_site_leaves_blank(self):
        t = _ticket(self.org)
        self.assertIsNone(t.site_id)
        self.assertEqual(t.site_source, '')

    def test_only_site_is_used(self):
        solo = Organization.objects.create(name='Solo', slug='solo')
        only = _loc(solo, 'Only office')
        t = _ticket(solo)
        self.assertEqual((t.site, t.site_source), (only, 'only_site'))

    def test_contact_default_site_by_contact_and_by_requester_email(self):
        RequesterDefaultSite.objects.create(organization=self.org, contact=self.contact, location=self.branch)
        t = _ticket(self.org, contact=self.contact)
        self.assertEqual((t.site, t.site_source), (self.branch, 'contact'))
        t2 = _ticket(self.org, requester_email='BOB@acme.example')
        self.assertEqual((t2.site, t2.site_source), (self.branch, 'contact'))

    def test_portal_user_default_site_via_portal_intake(self):
        RequesterDefaultSite.objects.create(organization=self.org, user=self.portal, location=self.colo)
        c = Client()
        _login(c, self.portal)
        with self.captureOnCommitCallbacks(execute=True):
            c.post(reverse('portal:ticket_create'), {'subject': 'Printer jam', 'description': 'x'})
        t = Ticket.objects.get(subject='Printer jam')
        self.assertEqual((t.site, t.site_source), (self.colo, 'requester'))

    def test_asset_site_wins(self):
        from hardware.models import HardwareDevice, HardwareModel, Manufacturer
        m = Manufacturer.objects.create(name='SiteCo', slug='siteco')
        hm = HardwareModel.objects.create(manufacturer=m, model='Box', slug='box')
        asset = Asset.objects.create(organization=self.org, name='Switch 1')
        HardwareDevice.objects.create(organization=self.org, asset=asset, hardware_model=hm, site=self.hq)
        RequesterDefaultSite.objects.create(organization=self.org, contact=self.contact, location=self.branch)
        t = _ticket(self.org, contact=self.contact, related_asset=asset)
        self.assertEqual((t.site, t.site_source), (self.hq, 'asset'))

    def test_foreign_or_stale_default_is_never_stored(self):
        # A default pointing at another customer's site (data drift) is ignored.
        RequesterDefaultSite.objects.create(organization=self.org, contact=self.contact, location=self.foreign)
        t = _ticket(self.org, contact=self.contact)
        self.assertIsNone(t.site_id)
        # An explicit site from another customer is dropped at create.
        t2 = _ticket(self.org, site=self.foreign)
        self.assertIsNone(t2.site_id)
        t3 = _ticket(self.org, site=self.branch)
        self.assertEqual((t3.site, t3.site_source), (self.branch, 'manual'))

    def test_inference_is_read_only(self):
        before = RequesterDefaultSite.objects.count()
        infer_site(Ticket(organization=self.org, contact=self.contact))
        self.assertEqual(RequesterDefaultSite.objects.count(), before)

    def test_remember_default_contact_then_portal_user(self):
        t = _ticket(self.org, contact=self.contact)
        self.assertIn('contact', remember_default(t, self.hq))
        self.assertEqual(RequesterDefaultSite.objects.get(contact=self.contact).location, self.hq)
        t2 = _ticket(self.org, created_by=self.portal)
        self.assertIn('portal user', remember_default(t2, self.branch))
        self.assertEqual(RequesterDefaultSite.objects.get(user=self.portal).location, self.branch)
        # Never for another customer's site, never for a technician creator.
        self.assertEqual(remember_default(t2, self.foreign), '')
        t3 = _ticket(self.org, created_by=self.tech)
        self.assertEqual(remember_default(t3, self.hq), '')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketSiteEditTests(SiteFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()
        cls.admin = User.objects.create_superuser('site-admin', 'a@msp.example', 'pw')

    def test_technician_sets_and_clears_site(self):
        t = _ticket(self.org, contact=self.contact)
        c = Client()
        _login(c, self.admin)
        url = reverse('psa:ticket_quick_action', args=[t.ticket_number])
        page = c.get(reverse('psa:ticket_detail', args=[t.ticket_number]))
        self.assertContains(page, 'ticket-site-card')
        self.assertContains(page, 'Branch')
        self.assertNotContains(page, 'Other HQ')
        c.post(url, {'action': 'set_site', 'site': self.branch.pk, 'remember': 'on'})
        t.refresh_from_db()
        self.assertEqual((t.site, t.site_source), (self.branch, 'manual'))
        self.assertEqual(RequesterDefaultSite.objects.get(contact=self.contact).location, self.branch)
        self.assertTrue(TicketComment.objects.filter(ticket=t, is_internal=True, body__contains='Branch').exists())
        c.post(url, {'action': 'set_site', 'site': ''})
        t.refresh_from_db()
        self.assertIsNone(t.site_id)

    def test_foreign_site_refused_and_customer_cannot_edit(self):
        t = _ticket(self.org, site=self.hq)
        c = Client()
        _login(c, self.admin)
        url = reverse('psa:ticket_quick_action', args=[t.ticket_number])
        c.post(url, {'action': 'set_site', 'site': self.foreign.pk})
        t.refresh_from_db()
        self.assertEqual(t.site, self.hq)
        before = (t.organization_id, t.assigned_to_id, t.resolution_due_at, t.first_response_due_at)
        c.post(url, {'action': 'set_site', 'site': self.branch.pk})
        t.refresh_from_db()
        self.assertEqual(before, (t.organization_id, t.assigned_to_id, t.resolution_due_at,
                                  t.first_response_due_at))
        portal = Client()
        _login(portal, self.portal)
        portal.post(url, {'action': 'set_site', 'site': self.hq.pk})
        t.refresh_from_db()
        self.assertEqual(t.site, self.branch)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoutingSiteConditionTests(SiteFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()
        cls.admin = User.objects.create_superuser('site-route-admin', 'r@msp.example', 'pw')
        cls.team = Group.objects.create(name='Branch team')
        cls.branch_tech = _tech('branch-tech', cls.team)
        cls.colo_queue = Queue.objects.create(name='Colo hands', slug='colo-hands')
        cls.branch_rule = _rule('Branch office', cls.org, 10, {'sites': [cls.branch.pk]},
                                {'type': 'least_loaded', 'team_id': cls.team.pk, 'require_available': False})
        cls.no_site_rule = _rule('No site yet', cls.org, 20, {'site': 'unset'},
                                 {'type': 'queue', 'queue_id': cls.colo_queue.pk})

    def setUp(self):
        _set_msp(mode='auto')

    def test_condition_matches_site_through_portal_intake(self):
        RequesterDefaultSite.objects.create(organization=self.org, user=self.portal, location=self.branch)
        c = Client()
        _login(c, self.portal)
        with self.captureOnCommitCallbacks(execute=True):
            c.post(reverse('portal:ticket_create'), {'subject': 'Branch wifi', 'description': 'down'})
        t = Ticket.objects.get(subject='Branch wifi')
        self.assertEqual(t.site, self.branch)
        self.assertEqual(t.assigned_to, self.branch_tech)
        d = RoutingDecision.objects.get(ticket=t)
        self.assertEqual(d.rule, self.branch_rule)
        # Routing never changed the site, customer or SLA.
        self.assertEqual((t.organization, t.site_source), (self.org, 'requester'))

    def test_unset_condition_and_failure_reasons(self):
        t = Ticket(organization=self.org)
        facts = engine.ticket_facts(t, timezone.now(),
                                    engine.RoutingSettings.load())
        self.assertEqual(engine.condition_failures({'site': 'unset'}, facts), [])
        self.assertTrue(engine.condition_failures({'site': 'set'}, facts))
        self.assertIn('site is "none"', engine.condition_failures({'sites': [self.branch.pk]}, facts)[0])
        t.site = self.hq
        facts = engine.ticket_facts(t, timezone.now(),
                                    engine.RoutingSettings.load())
        self.assertIn('HQ', engine.condition_failures({'sites': [self.branch.pk]}, facts)[0])
        self.assertEqual(engine.condition_failures({'sites': [self.hq.pk, self.branch.pk], 'site': 'set'},
                                                   facts), [])

    def test_builder_offers_sites_reviews_and_round_trips(self):
        c = Client()
        _login(c, self.admin)
        form = c.get(reverse('ticket_routing:rule_new'))
        self.assertContains(form, 'name="sites"')
        self.assertContains(form, 'Acme — Branch')
        self.assertNotContains(form, 'Site is not offered')
        post = {'step': 'review', 'name': 'HQ only', 'organization': str(self.org.pk), 'priority': '5',
                'destination_type': 'queue', 'dest_queue_id': str(self.colo_queue.pk),
                'fallback_type': 'triage', 'activate': 'on', 'sites': [str(self.hq.pk)], 'site': 'set'}
        resp = c.post(reverse('ticket_routing:rule_new'), post)
        self.assertContains(resp, 'at site HQ')
        c.post(reverse('ticket_routing:rule_new'), {'step': 'confirm', 'payload': resp.context['payload_json']})
        rule = RoutingRule.objects.get(name='HQ only')
        self.assertTrue(rule.is_active)
        self.assertEqual(rule.current_version.conditions['sites'], [self.hq.pk])
        self.assertEqual(rule.current_version.conditions['site'], 'set')
        # A site from another customer is an error that blocks activation.
        post.update({'name': 'Foreign site', 'sites': [str(self.foreign.pk)]})
        resp = c.post(reverse('ticket_routing:rule_new'), post)
        self.assertContains(resp, 'do not belong to Acme')
        c.post(reverse('ticket_routing:rule_new'), {'step': 'confirm', 'payload': resp.context['payload_json']})
        self.assertFalse(RoutingRule.objects.get(name='Foreign site').is_active)

    def test_test_routing_sample_with_site(self):
        c = Client()
        _login(c, self.admin)
        resp = c.get(reverse('ticket_routing:test'), {'organization': self.org.pk, 'source': 'portal',
                                                      'subject': 'x', 'site': self.branch.pk})
        self.assertContains(resp, 'Branch office')
        # Another customer's site is ignored on the sample.
        resp = c.get(reverse('ticket_routing:test'), {'organization': self.org.pk, 'source': 'portal',
                                                      'subject': 'x', 'site': self.foreign.pk})
        self.assertContains(resp, 'No site yet')
