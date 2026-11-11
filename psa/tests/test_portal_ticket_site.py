"""Phase 60.6 follow-up: site picker on the portal new-ticket form, and the
staff page that sets a contact's / portal user's default site."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from assets.models import Contact
from audit.models import AuditLog
from psa.models import RequesterDefaultSite, Ticket
from psa.routing.tests import _login
from psa.tests._base import TEST_MIDDLEWARE
from psa.tests.test_ticket_site import SiteFixture


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalSitePickerTests(SiteFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        self.c = Client()
        _login(self.c, self.portal)

    def _post(self, **data):
        data.setdefault('subject', 'Printer jam')
        data.setdefault('description', 'x')
        with self.captureOnCommitCallbacks(execute=True):
            return self.c.post(reverse('portal:ticket_create'), data)

    def test_picker_lists_only_own_active_sites(self):
        r = self.c.get(reverse('portal:ticket_create'))
        names = {loc.name for loc in r.context['sites']}
        self.assertEqual(names, {'HQ', 'Branch'})  # no closed, shared or foreign site
        self.assertNotContains(r, 'Other HQ')
        self.assertNotContains(r, 'Colo')

    def test_defaults_to_the_users_default_site(self):
        RequesterDefaultSite.objects.create(organization=self.org, user=self.portal, location=self.branch)
        r = self.c.get(reverse('portal:ticket_create'))
        self.assertEqual(r.context['default_site_id'], self.branch.pk)
        self.assertContains(r, f'<option value="{self.branch.pk}" selected>')

    def test_chosen_site_is_stored(self):
        self._post(site=str(self.branch.pk))
        t = Ticket.objects.get(subject='Printer jam')
        self.assertEqual((t.site, t.site_source), (self.branch, 'portal'))

    def test_another_customers_site_is_rejected(self):
        self._post(site=str(self.foreign.pk))
        self.assertFalse(Ticket.objects.filter(subject='Printer jam').exists())

    def test_closed_or_shared_site_is_rejected(self):
        for loc in (self.closed, self.colo):
            self._post(site=str(loc.pk), subject=f'Try {loc.name}')
            self.assertFalse(Ticket.objects.filter(subject=f'Try {loc.name}').exists())

    def test_no_site_falls_back_to_intake_rules(self):
        RequesterDefaultSite.objects.create(organization=self.org, user=self.portal, location=self.hq)
        self._post()
        t = Ticket.objects.get(subject='Printer jam')
        self.assertEqual((t.site, t.site_source), (self.hq, 'requester'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RequesterSitesPageTests(SiteFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()
        cls.other_contact = Contact.objects.create(organization=cls.other, first_name='Eve',
                                                   last_name='Else', email='eve@other.example')
        cls.other_user = User.objects.create_user('other-portal', 'o@other.example', 'pw')
        Membership.objects.create(user=cls.other_user, organization=cls.other, role=Role.READONLY)

    def _staff(self, org=None):
        c = Client()
        _login(c, self.tech)
        s = c.session
        s['current_organization_id'] = (org or self.org).pk
        s.save()
        return c

    def test_page_lists_contacts_and_portal_users(self):
        r = self._staff().get(reverse('psa:requester_sites'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c for c, _ in r.context['contact_rows']], [self.contact])
        self.assertEqual([u for u, _ in r.context['user_rows']], [self.portal])

    def test_set_and_clear_contact_default(self):
        c = self._staff()
        c.post(reverse('psa:requester_sites'), {'kind': 'contact', 'target': self.contact.pk,
                                                'site': self.branch.pk})
        row = RequesterDefaultSite.objects.get(organization=self.org, contact=self.contact)
        self.assertEqual(row.location, self.branch)
        self.assertEqual(row.updated_by, self.tech)
        self.assertTrue(AuditLog.objects.filter(object_type='psa.RequesterDefaultSite').exists())
        c.post(reverse('psa:requester_sites'), {'kind': 'contact', 'target': self.contact.pk, 'site': ''})
        self.assertFalse(RequesterDefaultSite.objects.filter(contact=self.contact).exists())

    def test_set_portal_user_default_feeds_the_portal_form(self):
        self._staff().post(reverse('psa:requester_sites'), {'kind': 'user', 'target': self.portal.pk,
                                                            'site': self.hq.pk})
        pc = Client()
        _login(pc, self.portal)
        self.assertEqual(pc.get(reverse('portal:ticket_create')).context['default_site_id'], self.hq.pk)

    def test_another_customers_site_or_requester_is_rejected(self):
        c = self._staff()
        url = reverse('psa:requester_sites')
        c.post(url, {'kind': 'contact', 'target': self.contact.pk, 'site': self.foreign.pk})
        c.post(url, {'kind': 'contact', 'target': self.other_contact.pk, 'site': self.hq.pk})
        c.post(url, {'kind': 'user', 'target': self.other_user.pk, 'site': self.hq.pk})
        c.post(url, {'kind': 'contact', 'target': self.contact.pk, 'site': self.closed.pk})
        self.assertFalse(RequesterDefaultSite.objects.exists())

    def test_customer_users_are_refused(self):
        c = Client()
        _login(c, self.portal)
        r = c.post(reverse('psa:requester_sites'), {'kind': 'user', 'target': self.portal.pk,
                                                    'site': self.hq.pk})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(RequesterDefaultSite.objects.exists())

    def test_contact_page_shows_the_default(self):
        RequesterDefaultSite.objects.create(organization=self.org, contact=self.contact, location=self.branch)
        r = self._staff().get(reverse('assets:contact_detail', args=[self.contact.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['default_ticket_site'], self.branch)
        self.assertContains(r, reverse('psa:requester_sites'))
