"""seed_module_samples --only security_customer (v3.17.655)."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.demo_samples import CUSTOMER_SLUGS, MSP_SLUG
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE

SEEDED = [
    'statuspage.StatusPage', 'statuspage.StatusPageService', 'statuspage.MaintenanceWindow',
    'statuspage.StatusPageIncident', 'statuspage.IncidentUpdate',
    'security_alerts.SecurityAlertRule', 'security_alerts.SecurityAlert',
    'security_alerts.SecurityIncident', 'security_alerts.SecurityIncidentEvent',
    'security_alerts.SecurityIncidentSLAPolicy', 'security_alerts.RemediationPlaybook',
    'security_alerts.RemediationPlaybookStep', 'portal.PortalAnnouncement',
    'assets.Relationship', 'assets.Service', 'assets.AssetGroup', 'assets.Vulnerability',
    'assets.SoftwarePolicy', 'assets.AssetBaseline', 'assets.ContactNote', 'assets.ContactRating',
    'vault.PasswordRelation', 'docs.DiagramAnnotation', 'core.Relation',
]


def _model(label):
    from django.apps import apps
    return apps.get_model(label)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecurityCustomerSamplesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from assets.models import Asset, Contact
        from docs.models import Diagram, Document
        from monitoring.models import WebsiteMonitor
        from vault.models import Password
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        cls.orgs = [Organization.objects.create(name=s.replace('-', ' ').title(), slug=s)
                    for s in CUSTOMER_SLUGS + (MSP_SLUG,)]
        org = cls.org = cls.orgs[0]
        cls.server = Asset.objects.create(organization=org, name='acme-dc-01', asset_type='server',
                                          manufacturer='Dell')
        Asset.objects.create(organization=org, name='acme-fw-01', asset_type='firewall')
        Asset.objects.create(organization=org, name='acme-ws-014', asset_type='desktop')
        Contact.objects.create(organization=org, first_name='Dana', last_name='Lopez')
        Contact.objects.create(organization=org, first_name='Sam', last_name='Ito')
        Password.objects.create(organization=org, title='Domain admin', encrypted_password='dummy')
        Password.objects.create(organization=org, title='Firewall admin', encrypted_password='dummy')
        Document.objects.create(organization=org, title='Network overview', body='b', created_by=cls.admin)
        Diagram.objects.create(organization=org, title='Office network', created_by=cls.admin)
        WebsiteMonitor.objects.create(organization=org, name='Website', url='https://www.acme.example',
                                      status='active')

    def _seed(self):
        out = StringIO()
        call_command('seed_module_samples', only=['security_customer'], stdout=out)
        return out.getvalue()

    def _counts(self):
        return {label: _model(label).objects.count() for label in SEEDED}

    def test_seeds_every_model_once(self):
        self._seed()
        first = self._counts()
        empty = [label for label, n in first.items() if not n]
        self.assertEqual(empty, [])
        self._seed()
        self.assertEqual(self._counts(), first)

    def test_nothing_that_talks_to_the_outside(self):
        from security_alerts.models import (RemediationPlaybookStep, SecurityVendorConnection,
                                            SIEMWebhookEndpoint)
        from monitoring.models import WebsiteMonitor
        self._seed()
        self.assertFalse(SecurityVendorConnection.objects.exists())
        self.assertFalse(SIEMWebhookEndpoint.objects.exists())
        self.assertFalse(RemediationPlaybookStep.objects.filter(action='send_email').exists())
        self.assertEqual(WebsiteMonitor.objects.count(), 1)

    def test_pages_render(self):
        from statuspage.models import StatusPage
        self._seed()
        self.client.force_login(self.admin)
        session = self.client.session
        session['current_organization_id'] = self.org.pk
        session.save()
        public = StatusPage.objects.filter(visibility='public', is_enabled=True).first()
        incident = _model('security_alerts.SecurityIncident').objects.first()
        for url in ['/status/', f'/status/{public.pk}/', '/security/alerts/', '/security/incidents/',
                    f'/security/incidents/{incident.pk}/', '/security/playbooks/', '/security/rules/',
                    '/admin/portal/portalannouncement/', f'/assets/{self.server.pk}/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.logout()
        self.assertEqual(self.client.get(public.get_public_url()).status_code, 200)
