"""
Tenant Isolation Security Tests.

CRITICAL: These tests intentionally try to break tenant isolation.
They verify that users CANNOT access data from other organizations.

Run with: python manage.py test core.tests.test_tenant_isolation
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from assets.models import Asset
from audit.models import AuditLog
from core.models import Organization
from docs.models import Document
from vault.models import Password


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _login_in_org(client, user, org):
    """
    Log a user in via the test client and pin their session to ``org``.

    Uses ``force_login`` to bypass the django-axes auth backend (which requires
    a real request object). Sets ``current_organization_id`` on the session to
    mirror what the org switcher does in production, plus ``2fa_prompted`` so
    the optional-2FA middleware doesn't redirect.
    """
    client.force_login(user)
    session = client.session
    session['2fa_prompted'] = True
    session['current_organization_id'] = org.id
    session.save()


class TenantIsolationTestCase(TestCase):
    """
    Test that organization-based multi-tenancy is properly enforced.
    Users must NEVER be able to access data from other organizations.
    """

    def setUp(self):
        """Create two organizations with users and data."""
        self.org1 = Organization.objects.create(
            name='Organization 1',
            slug='org1',
            is_active=True,
        )
        self.user1 = User.objects.create_user(
            username='user1',
            password='testpass123',
            email='user1@org1.com',
        )
        Membership.objects.create(
            user=self.user1,
            organization=self.org1,
            role=Role.OWNER,
            is_active=True,
        )

        self.org2 = Organization.objects.create(
            name='Organization 2',
            slug='org2',
            is_active=True,
        )
        self.user2 = User.objects.create_user(
            username='user2',
            password='testpass123',
            email='user2@org2.com',
        )
        Membership.objects.create(
            user=self.user2,
            organization=self.org2,
            role=Role.OWNER,
            is_active=True,
        )

        self.password1 = Password.objects.create(
            organization=self.org1,
            title='Org1 Password',
            username='admin',
            password_type='server',
        )
        self.password1.set_password('secret123')
        self.password1.save()

        self.password2 = Password.objects.create(
            organization=self.org2,
            title='Org2 Password',
            username='admin',
            password_type='server',
        )
        self.password2.set_password('secret456')
        self.password2.save()

        self.asset1 = Asset.objects.create(
            organization=self.org1,
            name='Org1 Server',
            asset_type='server',
        )

        self.asset2 = Asset.objects.create(
            organization=self.org2,
            name='Org2 Server',
            asset_type='server',
        )

        self.doc1 = Document.objects.create(
            organization=self.org1,
            title='Org1 Document',
            body='Sensitive Org1 data',
        )

        self.doc2 = Document.objects.create(
            organization=self.org2,
            title='Org2 Document',
            body='Sensitive Org2 data',
        )

        self.client = Client()

    def test_password_isolation(self):
        """Users cannot access passwords from other organizations."""
        passwords = Password.objects.filter(organization=self.org1)
        self.assertEqual(passwords.count(), 1)
        self.assertEqual(passwords.first().title, 'Org1 Password')

        passwords = Password.objects.filter(organization=self.org2)
        self.assertEqual(passwords.count(), 1)
        self.assertEqual(passwords.first().title, 'Org2 Password')

        wrong_password = Password.objects.filter(organization=self.org1, id=self.password2.id)
        self.assertEqual(wrong_password.count(), 0)

    def test_asset_isolation(self):
        """Users cannot access assets from other organizations."""
        assets = Asset.objects.filter(organization=self.org1)
        self.assertEqual(assets.count(), 1)
        self.assertEqual(assets.first().name, 'Org1 Server')

        assets = Asset.objects.filter(organization=self.org2)
        self.assertEqual(assets.count(), 1)
        self.assertEqual(assets.first().name, 'Org2 Server')

        wrong_asset = Asset.objects.filter(organization=self.org1, id=self.asset2.id)
        self.assertEqual(wrong_asset.count(), 0)

    def test_document_isolation(self):
        """Users cannot access documents from other organizations."""
        docs = Document.objects.filter(organization=self.org1)
        self.assertEqual(docs.count(), 1)
        self.assertEqual(docs.first().title, 'Org1 Document')

        docs = Document.objects.filter(organization=self.org2)
        self.assertEqual(docs.count(), 1)
        self.assertEqual(docs.first().title, 'Org2 Document')

        wrong_doc = Document.objects.filter(organization=self.org1, id=self.doc2.id)
        self.assertEqual(wrong_doc.count(), 0)

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_cross_tenant_view_access(self):
        """Server-rendered detail views must reject cross-org access."""
        _login_in_org(self.client, self.user1, self.org1)

        response = self.client.get(reverse('vault:password_detail', args=[self.password2.id]))
        self.assertIn(response.status_code, (302, 403, 404))

        response = self.client.get(reverse('assets:asset_detail', args=[self.asset2.id]))
        self.assertIn(response.status_code, (302, 403, 404))

        response = self.client.get(reverse('docs:document_detail', args=[self.doc2.slug]))
        self.assertIn(response.status_code, (302, 403, 404))

    def test_audit_log_isolation(self):
        """Audit logs are isolated by organization."""
        AuditLog.objects.create(
            organization=self.org1,
            user=self.user1,
            username='user1',
            action='create',
            description='Org1 action',
        )
        AuditLog.objects.create(
            organization=self.org2,
            user=self.user2,
            username='user2',
            action='create',
            description='Org2 action',
        )

        # Membership creation in setUp is itself audited for its customer
        # (who was granted what); leave those rows out here.
        own = AuditLog.objects.exclude(object_type='membership')
        logs = own.filter(organization=self.org1)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().description, 'Org1 action')

        logs = own.filter(organization=self.org2)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().description, 'Org2 action')

    def test_bulk_operations_isolation(self):
        """Bulk operations respect tenant boundaries."""
        for i in range(5):
            Asset.objects.create(
                organization=self.org1,
                name=f'Org1 Asset {i}',
                asset_type='workstation',
            )
            Asset.objects.create(
                organization=self.org2,
                name=f'Org2 Asset {i}',
                asset_type='workstation',
            )

        org1_assets = Asset.objects.filter(organization=self.org1)
        self.assertEqual(org1_assets.count(), 6)

        org2_assets = Asset.objects.filter(organization=self.org2)
        self.assertEqual(org2_assets.count(), 6)

        for asset in org1_assets:
            self.assertEqual(asset.organization_id, self.org1.id)
        for asset in org2_assets:
            self.assertEqual(asset.organization_id, self.org2.id)

    def test_organization_manager_for_organization(self):
        """OrganizationManager.for_organization() filters to the requested org."""
        org1_passwords = Password.objects.for_organization(self.org1)
        self.assertEqual(org1_passwords.count(), 1)
        self.assertTrue(all(p.organization_id == self.org1.id for p in org1_passwords))

        org2_passwords = Password.objects.for_organization(self.org2)
        self.assertEqual(org2_passwords.count(), 1)
        self.assertTrue(all(p.organization_id == self.org2.id for p in org2_passwords))

        org1_assets = Asset.objects.for_organization(self.org1)
        self.assertTrue(all(a.organization_id == self.org1.id for a in org1_assets))

        org1_docs = Document.objects.for_organization(self.org1)
        self.assertTrue(all(d.organization_id == self.org1.id for d in org1_docs))

    def test_foreign_key_isolation(self):
        """FK relationships respect tenant boundaries."""
        self.assertEqual(self.password1.organization_id, self.org1.id)
        self.assertEqual(self.asset1.organization_id, self.org1.id)
        self.assertNotEqual(self.password1.organization_id, self.password2.organization_id)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TenantIsolationAPITestCase(TestCase):
    """
    Test API endpoints for tenant isolation.
    Ensures REST API properly enforces organization boundaries.
    """

    def setUp(self):
        self.org1 = Organization.objects.create(name='Org1', slug='org1', is_active=True)
        self.org2 = Organization.objects.create(name='Org2', slug='org2', is_active=True)

        self.user1 = User.objects.create_user('user1', 'user1@org1.com', 'pass')
        Membership.objects.create(
            user=self.user1, organization=self.org1, role=Role.OWNER, is_active=True,
        )

        self.user2 = User.objects.create_user('user2', 'user2@org2.com', 'pass')
        Membership.objects.create(
            user=self.user2, organization=self.org2, role=Role.OWNER, is_active=True,
        )

        self.client = Client()

    def test_api_list_endpoints_isolation(self):
        """API list endpoints only return data for the user's current org."""
        Password.objects.create(
            organization=self.org1, title='Org1 Password',
            username='user1', password_type='server',
        )
        Password.objects.create(
            organization=self.org2, title='Org2 Password',
            username='user2', password_type='server',
        )

        _login_in_org(self.client, self.user1, self.org1)

        response = self.client.get('/api/passwords/')
        self.assertEqual(response.status_code, 200)

        data = response.json()
        results = data['results'] if isinstance(data, dict) and 'results' in data else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Org1 Password')

    def test_api_detail_endpoint_isolation(self):
        """API detail endpoints reject cross-org access."""
        password1 = Password.objects.create(
            organization=self.org1, title='Org1 Password',
            username='user1', password_type='server',
        )
        password2 = Password.objects.create(
            organization=self.org2, title='Org2 Password',
            username='user2', password_type='server',
        )

        _login_in_org(self.client, self.user1, self.org1)

        response = self.client.get(f'/api/passwords/{password2.id}/')
        self.assertIn(response.status_code, (403, 404))

        response = self.client.get(f'/api/passwords/{password1.id}/')
        self.assertNotIn(response.status_code, (403, 404))


def run_tenant_isolation_tests():
    """
    Convenience function to run all tenant isolation tests.
    Can be called from a management command or CI/CD.
    """
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=2)
    failures = runner.run_tests(['core.tests.test_tenant_isolation'])
    return failures == 0
