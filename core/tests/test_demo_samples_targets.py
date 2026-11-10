"""Pointing the demo seeders at other organizations (docs demo instance):
seed_module_samples --customers/--msp/--techs/--owner and
psa_seed_sample_conversations --org-map. The default slugs are covered by
test_demo_samples_* and psa.tests.test_ticket_cc_secure."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import Membership, Role
from core.demo_samples import CUSTOMER_SLUGS, MSP_SLUG, TECHS
from core.models import Organization, SystemSetting
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed

User = get_user_model()


class ModuleSampleTargetsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customers = [Organization.objects.create(name=n, slug=s) for n, s in
                         (('Northwind Example', 'nw-example'), ('Ridge Example', 'ridge-example'))]
        cls.msp = Organization.objects.create(name='Beacon Example', slug='beacon-example')
        cls.owner = User.objects.create_superuser('owner.tech', 'owner@example.com', 'pw-not-used')
        cls.tech = User.objects.create_user('existing.tech', 'tech@example.com', 'pw-not-used', is_staff=True)

    def _run(self, **opts):
        call_command('seed_module_samples', only=['operations'], stdout=StringIO(), **opts)

    def test_named_customers_msp_and_existing_techs(self):
        from inventory.models import InventoryItem
        from resourcing.models import UserSkill
        self._run(customers='nw-example,ridge-example', msp='beacon-example', techs='existing.tech',
                  owner='owner.tech')
        # No demo technicians were created; the named one got memberships.
        self.assertFalse(User.objects.filter(email__in=[t[2] for t in TECHS]).exists())
        for org in [self.msp, *self.customers]:
            self.assertTrue(Membership.objects.filter(user=self.tech, organization=org).exists())
        self.assertTrue(UserSkill.objects.filter(user=self.tech).exists())
        orgs = set(InventoryItem.objects.values_list('organization_id', flat=True))
        self.assertTrue(orgs <= {o.pk for o in [self.msp, *self.customers]})
        # The built-in demo slugs were not involved.
        self.assertFalse(Organization.objects.filter(slug__in=CUSTOMER_SLUGS + (MSP_SLUG,)).exists())

    def test_unknown_tech_or_owner_is_refused(self):
        with self.assertRaises(CommandError):
            self._run(customers='nw-example', techs='nobody.here')
        with self.assertRaises(CommandError):
            self._run(customers='nw-example', owner='existing.tech')  # not a superuser

    def test_no_matching_customers_is_refused(self):
        with self.assertRaises(CommandError):
            self._run(customers='missing-slug')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConversationOrgMapTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.nw = Organization.objects.create(name='Northwind Example', slug='nw-example',
                                              website='https://northwind.example')
        self.tech = User.objects.create_superuser('admin658', 'admin@msp.test', 'pw-not-used')
        # A customer person already at the target with a sample person's name.
        self.dana = User.objects.create_user('nw.dana', 'dana@example.com', 'pw-not-used',
                                             first_name='Dana', last_name='Whitfield')
        Membership.objects.create(user=self.dana, organization=self.nw, role=Role.ADMIN, is_active=True)

    def test_mapped_samples_land_in_the_target_with_rewritten_names(self):
        from psa.models import Ticket
        call_command('psa_seed_sample_conversations', org_map=['demo-globex=nw-example'], stdout=StringIO())
        call_command('psa_seed_sample_conversations', org_map=['demo-globex=nw-example'], stdout=StringIO())
        tickets = Ticket.objects.all()
        self.assertEqual(tickets.count(), 2)  # only the two Globex samples, once
        self.assertEqual(set(tickets.values_list('organization_id', flat=True)), {self.nw.pk})
        outlook = tickets.get(subject='Outlook keeps asking for my password')
        self.assertIn('Northwind Example', outlook.description)
        self.assertNotIn('Globex', outlook.description)
        self.assertEqual(outlook.cc_emails, ['office.manager@northwind.example'])
        # Dana was reused, Marcus created with the target's domain.
        self.assertEqual(outlook.requester_email, 'dana@example.com')
        self.assertFalse(User.objects.filter(username='demo.dana.whitfield').exists())
        self.assertEqual(User.objects.get(username='demo.marcus.bell').email, 'marcus.bell@northwind.example')

    def test_bad_map_is_refused(self):
        for bad in ('demo-globex', 'not-a-sample=nw-example', 'demo-globex=missing'):
            with self.subTest(bad), self.assertRaises(CommandError):
                call_command('psa_seed_sample_conversations', org_map=[bad], stdout=StringIO())
