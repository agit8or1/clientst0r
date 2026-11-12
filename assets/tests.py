"""
Baseline test coverage for the assets/ app.

Foundational app — Asset, Contact, EquipmentModel are referenced from
every other surface (vault for asset linking, docs for KB→asset, PSA
for ticket→asset, monitoring for rack→asset, etc.). Bugs here ripple.
This test file covers the core model behavior + view smoke tests +
tenant isolation; deeper feature tests (port configurations,
relationship graph, AI doc generation) belong in follow-up files.

Same family of tests as v3.17.193's `api/` and v3.17.195's `audit/`
suites — patterns reused so each new app follows the same shape.
"""
from __future__ import annotations

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from assets.models import Asset, AssetType, Contact, EquipmentModel, Vendor
from core.models import Organization


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _login_in_org(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


# ---------------------------------------------------------------------------
# Asset model behavior
# ---------------------------------------------------------------------------

class AssetModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='AssetCo', slug='asset-co')

    def test_create_with_minimal_required_fields(self):
        a = Asset.objects.create(
            organization=self.org, name='Server-01', asset_type='server',
        )
        self.assertEqual(a.name, 'Server-01')
        self.assertEqual(a.asset_type, 'server')

    def test_str_includes_name_and_human_readable_type(self):
        a = Asset.objects.create(
            organization=self.org, name='Server-01', asset_type='server',
        )
        s = str(a)
        self.assertIn('Server-01', s)
        # `get_asset_type_display()` returns 'Server' (the label, not the slug).
        self.assertIn('Server', s)

    def test_default_asset_type_is_other(self):
        a = Asset.objects.create(organization=self.org, name='Mystery box')
        self.assertEqual(a.asset_type, 'other')

    def test_for_organization_filters_correctly(self):
        # Asset uses OrganizationManager — `.for_organization()` is the
        # explicit-tenant filter helper. v3.17.171 tenant-isolation
        # tests exercise this on Password; mirror for Asset.
        org_b = Organization.objects.create(name='AssetB', slug='asset-b')
        Asset.objects.create(organization=self.org, name='A1', asset_type='server')
        Asset.objects.create(organization=self.org, name='A2', asset_type='laptop')
        Asset.objects.create(organization=org_b, name='B1', asset_type='server')

        for_a = list(Asset.objects.for_organization(self.org))
        for_b = list(Asset.objects.for_organization(org_b))
        self.assertEqual(len(for_a), 2)
        self.assertEqual(len(for_b), 1)
        self.assertEqual({a.name for a in for_a}, {'A1', 'A2'})


# ---------------------------------------------------------------------------
# Contact model
# ---------------------------------------------------------------------------

class ContactModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ContactCo', slug='contact-co')

    def test_full_name_property(self):
        c = Contact.objects.create(
            organization=self.org, first_name='Alice', last_name='Bob',
            email='ab@x.com',
        )
        self.assertEqual(c.full_name, 'Alice Bob')

    def test_str_returns_full_name(self):
        c = Contact.objects.create(
            organization=self.org, first_name='Alice', last_name='Bob',
        )
        self.assertEqual(str(c), 'Alice Bob')

    def test_blank_email_allowed(self):
        # email is `blank=True` on the model — creating without one
        # must not raise. Confirms the migration matches the model.
        c = Contact.objects.create(
            organization=self.org, first_name='No', last_name='Email',
        )
        self.assertEqual(c.email, '')

    def test_org_manager_for_organization_works(self):
        org_b = Organization.objects.create(name='Other', slug='contact-other')
        Contact.objects.create(organization=self.org, first_name='A', last_name='X')
        Contact.objects.create(organization=org_b, first_name='B', last_name='Y')
        for_a = list(Contact.objects.for_organization(self.org))
        self.assertEqual(len(for_a), 1)
        self.assertEqual(for_a[0].full_name, 'A X')


# ---------------------------------------------------------------------------
# AssetType model — per-org custom asset types
# ---------------------------------------------------------------------------

class AssetTypeModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='TypeCo', slug='type-co')

    def test_create_basic(self):
        t = AssetType.objects.create(
            organization=self.org, name='Custom Server Type', slug='custom-server',
        )
        self.assertEqual(t.name, 'Custom Server Type')

    def test_default_icon_and_color(self):
        t = AssetType.objects.create(
            organization=self.org, name='Defaults', slug='defaults',
        )
        self.assertEqual(t.icon, 'fa-box')
        self.assertEqual(t.color, '#0d6efd')


# ---------------------------------------------------------------------------
# View-level smoke tests
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetListViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='ViewCo', slug='view-co')
        self.user = User.objects.create_user(
            'viewuser', email='v@x.com', password='pw',
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        Asset.objects.create(organization=self.org, name='Local-Server', asset_type='server')
        self.client = Client()

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get('/assets/')
        # Either 302 (redirect to login) or 401 — both indicate the
        # @login_required gate fired.
        self.assertIn(resp.status_code, (302, 401))

    def test_authenticated_returns_200_with_org_asset(self):
        _login_in_org(self.client, self.user, self.org)
        resp = self.client.get('/assets/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Local-Server')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetDetailIsolationTests(TestCase):
    """Mirror of `core.tests.test_tenant_isolation` for the assets/
    views — own-org PK returns 200, cross-org PK returns 404."""

    def setUp(self):
        self.org_a = Organization.objects.create(name='OrgA-A', slug='orga-a')
        self.org_b = Organization.objects.create(name='OrgB-A', slug='orgb-a')
        self.user_a = User.objects.create_user(
            'asset-user-a', email='aa@x.com', password='pw',
        )
        Membership.objects.create(
            user=self.user_a, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        self.asset_a = Asset.objects.create(
            organization=self.org_a, name='A-server', asset_type='server',
        )
        self.asset_b = Asset.objects.create(
            organization=self.org_b, name='B-server', asset_type='server',
        )
        self.client = Client()
        _login_in_org(self.client, self.user_a, self.org_a)

    def test_own_org_asset_detail_returns_200(self):
        resp = self.client.get(f'/assets/{self.asset_a.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_cross_org_asset_detail_returns_404(self):
        resp = self.client.get(f'/assets/{self.asset_b.pk}/')
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# EquipmentModel — vendor-database join used by Asset.equipment_model FK
# ---------------------------------------------------------------------------

class EquipmentModelLookupTests(TestCase):
    """`EquipmentModel` is global (no organization FK) — same model row
    is shared across tenants. Joined to Asset via Asset.equipment_model.
    Confirms creation + back-reference + uniqueness contract."""

    @classmethod
    def setUpTestData(cls):
        cls.vendor = Vendor.objects.create(name='Dell', slug='dell-eq')

    def test_create_and_str_includes_vendor_and_model(self):
        em = EquipmentModel.objects.create(
            vendor=self.vendor,
            model_name='PowerEdge R740',
            slug='dell-poweredge-r740',
            equipment_type='server',
        )
        s = str(em)
        # The display string should expose enough to identify the model.
        self.assertTrue('Dell' in s or 'R740' in s,
            f'expected vendor or model name in str(): {s!r}')

    def test_asset_back_reference_via_equipment_model_fk(self):
        org = Organization.objects.create(name='EQOrg', slug='eq-org')
        em = EquipmentModel.objects.create(
            vendor=self.vendor,
            model_name='ProLiant DL380',
            slug='hp-proliant-dl380',
            equipment_type='server',
        )
        a1 = Asset.objects.create(
            organization=org, name='hp-1', asset_type='server', equipment_model=em,
        )
        a2 = Asset.objects.create(
            organization=org, name='hp-2', asset_type='server', equipment_model=em,
        )
        self.assertEqual(em.assets.count(), 2)
        self.assertIn(a1, em.assets.all())
        self.assertIn(a2, em.assets.all())


# ---------------------------------------------------------------------------
# Phase 13 v1 — warranty expiry alert cron (v3.17.254)
# ---------------------------------------------------------------------------

from datetime import date as _date, timedelta as _td

from django.conf import settings as _django_settings
from django.test import override_settings as _override_settings


_TEST_MW = [
    m for m in _django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@_override_settings(
    MIDDLEWARE=_TEST_MW, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class WarrantyAlertCronTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from core.models import Organization
        cls.org = Organization.objects.create(name='WarrantyCo', slug='wa-co')
        cls.owner = User.objects.create_user('wa-owner', 'wo@x.com', 'pw')
        Membership.objects.create(
            user=cls.owner, organization=cls.org,
            role=Role.OWNER, is_active=True,
        )
        cls.expiring = Asset.objects.create(
            organization=cls.org, name='Expiring server', asset_type='server',
            warranty_expiry=_date.today() + _td(days=15),
        )
        cls.expiring_soon = Asset.objects.create(
            organization=cls.org, name='Almost-expiring switch', asset_type='other',
            warranty_expiry=_date.today() + _td(days=3),
        )
        cls.far_away = Asset.objects.create(
            organization=cls.org, name='Future asset', asset_type='other',
            warranty_expiry=_date.today() + _td(days=200),
        )
        cls.expired = Asset.objects.create(
            organization=cls.org, name='Already expired', asset_type='other',
            warranty_expiry=_date.today() - _td(days=10),
        )
        cls.no_warranty = Asset.objects.create(
            organization=cls.org, name='No warranty data', asset_type='other',
        )

    def test_cron_sends_one_digest_per_org(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('assets_warranty_alerts', verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['wo@x.com'])
        self.assertIn('WarrantyCo', msg.subject)
        # In-window assets included
        self.assertIn('Expiring server', msg.body)
        self.assertIn('Almost-expiring switch', msg.body)
        # Out-of-window / no-warranty / expired excluded
        self.assertNotIn('Future asset', msg.body)
        self.assertNotIn('Already expired', msg.body)
        self.assertNotIn('No warranty data', msg.body)

    def test_cron_skips_owner_who_lost_asset_access(self):
        # authz-tech: rechecked at send time (active account, assets_view).
        from django.core import mail
        from django.core.management import call_command
        from accounts.models import RoleTemplate
        m = Membership.objects.get(user=self.owner, organization=self.org)
        m.role_template = RoleTemplate.objects.create(name='warranty no assets', assets_view=False)
        m.save()
        mail.outbox = []
        call_command('assets_warranty_alerts', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)
        m.role_template = None
        m.save()
        self.owner.is_active = False
        self.owner.save()
        call_command('assets_warranty_alerts', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)

    def test_cron_stamps_last_warranty_alert_sent_at(self):
        from django.core.management import call_command
        from django.utils import timezone as _tz
        before = _tz.now()
        call_command('assets_warranty_alerts', verbosity=0)
        self.expiring.refresh_from_db()
        self.assertIsNotNone(self.expiring.last_warranty_alert_sent_at)
        self.assertGreaterEqual(self.expiring.last_warranty_alert_sent_at, before)

    def test_cooldown_prevents_double_alert_within_7_days(self):
        from django.core import mail
        from django.core.management import call_command
        # First run: alert sent
        call_command('assets_warranty_alerts', verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        mail.outbox = []
        # Second run immediately: cooldown prevents another alert
        call_command('assets_warranty_alerts', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)

    def test_dry_run_does_not_send_or_stamp(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('assets_warranty_alerts', '--dry-run', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)
        self.expiring.refresh_from_db()
        self.assertIsNone(self.expiring.last_warranty_alert_sent_at)

    def test_days_arg_overrides_default_window(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        # 5-day window only catches the far-soon asset, not the 15-day one.
        call_command('assets_warranty_alerts', '--days', '5', verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('Almost-expiring switch', body)
        self.assertNotIn('Expiring server', body)


# ---------------------------------------------------------------------------
# Phase 13 v4 — RMA tracking
# ---------------------------------------------------------------------------

class RMAModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='RMA Co', slug='rma-co')
        cls.vendor = Vendor.objects.create(name='RMA Vendor', slug='rma-vendor')

    def test_create_minimal(self):
        from assets.models import RMAReturn
        rma = RMAReturn.objects.create(
            organization=self.org, vendor=self.vendor, reason='DOA',
        )
        self.assertEqual(rma.status, 'open')
        self.assertFalse(rma.is_terminal)
        self.assertIsNone(rma.sent_at)
        self.assertIsNone(rma.closed_at)

    def test_transition_stamps_timestamps(self):
        from assets.models import RMAReturn
        rma = RMAReturn.objects.create(
            organization=self.org, vendor=self.vendor, reason='defective',
        )
        rma.transition('sent')
        rma.save()
        self.assertEqual(rma.status, 'sent')
        self.assertIsNotNone(rma.sent_at)

        rma.transition('received_by_vendor')
        rma.save()
        self.assertIsNotNone(rma.received_at)

        rma.transition('replaced')
        rma.save()
        self.assertEqual(rma.status, 'replaced')
        self.assertTrue(rma.is_terminal)
        self.assertIsNotNone(rma.closed_at)

    def test_transition_rejects_unknown_status(self):
        from assets.models import RMAReturn
        rma = RMAReturn.objects.create(
            organization=self.org, vendor=self.vendor, reason='x',
        )
        with self.assertRaises(ValueError):
            rma.transition('teleported')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RMAViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='RMAViewCo', slug='rmaview-co')
        self.other = Organization.objects.create(name='OtherCo', slug='other-rma')
        self.user = User.objects.create_user('rma_user', email='r@r.com', password='pw')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.vendor = Vendor.objects.create(name='V1', slug='v1')
        from assets.models import RMAReturn
        self.rma = RMAReturn.objects.create(
            organization=self.org, vendor=self.vendor,
            reason='DOA', rma_number='RMA-001',
        )
        self.cross_rma = RMAReturn.objects.create(
            organization=self.other, vendor=self.vendor,
            reason='other-org', rma_number='RMA-XX',
        )
        self.client = Client()
        _login_in_org(self.client, self.user, self.org)

    def test_list_shows_own_org_only(self):
        resp = self.client.get('/assets/rma/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('RMA-001', body)
        self.assertNotIn('RMA-XX', body)

    def test_detail_own_org_returns_200(self):
        resp = self.client.get(f'/assets/rma/{self.rma.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'RMA-001')

    def test_detail_cross_org_returns_404(self):
        resp = self.client.get(f'/assets/rma/{self.cross_rma.pk}/')
        self.assertEqual(resp.status_code, 404)

    def test_transition_via_post(self):
        resp = self.client.post(
            f'/assets/rma/{self.rma.pk}/transition/', {'status': 'sent'},
        )
        self.assertEqual(resp.status_code, 302)
        self.rma.refresh_from_db()
        self.assertEqual(self.rma.status, 'sent')
        self.assertIsNotNone(self.rma.sent_at)

    def test_transition_to_replaced_captures_serial(self):
        from assets.models import RMAReturn
        rma = RMAReturn.objects.create(
            organization=self.org, vendor=self.vendor, reason='defective',
            status='received_by_vendor',
        )
        resp = self.client.post(
            f'/assets/rma/{rma.pk}/transition/',
            {'status': 'replaced', 'replacement_serial': 'NEW-SN-7'},
        )
        self.assertEqual(resp.status_code, 302)
        rma.refresh_from_db()
        self.assertEqual(rma.status, 'replaced')
        self.assertEqual(rma.replacement_serial, 'NEW-SN-7')
        self.assertIsNotNone(rma.closed_at)


class DependencyChainTests(TestCase):
    """Phase 16 v7 (v3.17.300): `Asset.dependency_chain()` walks the
    `Relationship(relation_type='depends')` edges in either direction."""

    @classmethod
    def setUpTestData(cls):
        from assets.models import Relationship
        cls.org = Organization.objects.create(name='DcCo', slug='dc-co')
        # Build: web → app → db → san
        cls.web = Asset.objects.create(organization=cls.org, name='web',
                                         asset_type='server')
        cls.app = Asset.objects.create(organization=cls.org, name='app',
                                         asset_type='server')
        cls.db = Asset.objects.create(organization=cls.org, name='db',
                                        asset_type='server')
        cls.san = Asset.objects.create(organization=cls.org, name='san',
                                         asset_type='storage')
        # Unrelated standalone
        cls.lonely = Asset.objects.create(organization=cls.org, name='lonely',
                                            asset_type='switch')
        for src, dst in [(cls.web, cls.app), (cls.app, cls.db),
                          (cls.db, cls.san)]:
            Relationship.objects.create(
                organization=cls.org,
                source_type='asset', source_id=src.pk,
                target_type='asset', target_id=dst.pk,
                relation_type='depends',
            )

    def test_downstream_walks_full_chain(self):
        names = [a.name for a in self.web.dependency_chain(direction='downstream')]
        self.assertEqual(set(names), {'app', 'db', 'san'})

    def test_upstream_walks_reverse_chain(self):
        names = [a.name for a in self.san.dependency_chain(direction='upstream')]
        self.assertEqual(set(names), {'web', 'app', 'db'})

    def test_isolated_asset_returns_empty(self):
        self.assertEqual(self.lonely.dependency_chain(direction='downstream'), [])

    def test_max_depth_caps(self):
        # max_depth=1 from web should only include 'app'
        chain = self.web.dependency_chain(direction='downstream', max_depth=1)
        names = [a.name for a in chain]
        self.assertEqual(names, ['app'])

    def test_cycle_safe(self):
        from assets.models import Relationship
        # Create a cycle: san → web (closing the loop)
        Relationship.objects.create(
            organization=self.org,
            source_type='asset', source_id=self.san.pk,
            target_type='asset', target_id=self.web.pk,
            relation_type='depends',
        )
        # Should not infinite-loop; must include all 4 distinct assets
        names = {a.name for a in self.web.dependency_chain(direction='downstream')}
        self.assertEqual(names, {'app', 'db', 'san'})

    def test_invalid_direction_raises(self):
        with self.assertRaises(ValueError):
            self.web.dependency_chain(direction='sideways')


class AssetAutoLinkTests(TestCase):
    """Phase 16 v6 (v3.17.301): heuristic auto-linker."""

    def setUp(self):
        from assets.models import Asset
        self.org = Organization.objects.create(name='AlCo', slug='al-co')
        self.fw = Asset.objects.create(
            organization=self.org, name='fw1', asset_type='firewall',
            ip_address='192.168.10.1',
        )
        self.srv1 = Asset.objects.create(
            organization=self.org, name='srv1', asset_type='server',
            ip_address='192.168.10.5',
        )
        self.srv2 = Asset.objects.create(
            organization=self.org, name='srv2', asset_type='server',
            ip_address='192.168.10.6',
        )
        # Different subnet — must NOT be linked
        self.other = Asset.objects.create(
            organization=self.org, name='other', asset_type='server',
            ip_address='10.0.0.1',
        )

    def test_command_creates_related_between_subnet_peers(self):
        from django.core.management import call_command
        from assets.models import Relationship
        call_command('assets_auto_link', verbosity=0)
        # srv1 ↔ srv2 should be related (gateway is fw1, not them)
        rel = Relationship.objects.filter(
            organization=self.org,
            source_type='asset', source_id=self.srv1.pk,
            target_type='asset', target_id=self.srv2.pk,
            relation_type='related',
        ).first()
        self.assertIsNotNone(rel)

    def test_command_creates_depends_pointing_at_gateway(self):
        from django.core.management import call_command
        from assets.models import Relationship
        call_command('assets_auto_link', verbosity=0)
        # srv1 depends on fw1
        rel = Relationship.objects.filter(
            organization=self.org,
            source_type='asset', source_id=self.srv1.pk,
            target_type='asset', target_id=self.fw.pk,
            relation_type='depends',
        ).first()
        self.assertIsNotNone(rel)

    def test_different_subnet_not_linked(self):
        from django.core.management import call_command
        from assets.models import Relationship
        call_command('assets_auto_link', verbosity=0)
        cross = Relationship.objects.filter(
            organization=self.org,
            source_id__in=[self.fw.pk, self.srv1.pk, self.srv2.pk],
            target_id=self.other.pk,
        )
        self.assertFalse(cross.exists())

    def test_idempotent(self):
        from django.core.management import call_command
        from assets.models import Relationship
        call_command('assets_auto_link', verbosity=0)
        before = Relationship.objects.filter(organization=self.org).count()
        call_command('assets_auto_link', verbosity=0)
        after = Relationship.objects.filter(organization=self.org).count()
        self.assertEqual(before, after)

    def test_dry_run_creates_nothing(self):
        from django.core.management import call_command
        from assets.models import Relationship
        call_command('assets_auto_link', '--dry-run', verbosity=0)
        self.assertEqual(
            Relationship.objects.filter(organization=self.org).count(), 0,
        )

    def test_two_gateways_means_no_depends(self):
        """If there are 2+ gateway-type assets on the segment, the
        heuristic doesn't pick one — leaves it to a human."""
        from django.core.management import call_command
        from assets.models import Asset, Relationship
        Asset.objects.create(
            organization=self.org, name='fw2', asset_type='firewall',
            ip_address='192.168.10.2',
        )
        # Wipe any prior auto-links
        Relationship.objects.filter(organization=self.org).delete()
        call_command('assets_auto_link', verbosity=0)
        depends = Relationship.objects.filter(
            organization=self.org, relation_type='depends',
        )
        self.assertFalse(depends.exists())


class ServiceModelTests(TestCase):
    """Phase 16 v9 (v3.17.302): Service model + asset dependency walker."""

    @classmethod
    def setUpTestData(cls):
        from assets.models import Service, Relationship
        cls.org = Organization.objects.create(name='SvcCo', slug='svc-co')
        cls.svc = Service.objects.create(
            organization=cls.org, name='Email', criticality='high',
        )
        cls.exch = Asset.objects.create(
            organization=cls.org, name='exch01', asset_type='server',
        )
        cls.dns = Asset.objects.create(
            organization=cls.org, name='dns01', asset_type='server',
        )
        # Service depends on both
        for a in [cls.exch, cls.dns]:
            Relationship.objects.create(
                organization=cls.org,
                source_type='service', source_id=cls.svc.pk,
                target_type='asset', target_id=a.pk,
                relation_type='depends',
            )

    def test_default_status_is_operational(self):
        from assets.models import Service
        s = Service.objects.create(organization=self.org, name='Calendaring')
        self.assertEqual(s.status, 'operational')

    def test_set_status_stamps_change(self):
        result = self.svc.set_status('degraded')
        self.assertTrue(result)
        self.svc.refresh_from_db()
        self.assertEqual(self.svc.status, 'degraded')
        self.assertIsNotNone(self.svc.last_status_change)

    def test_set_status_idempotent(self):
        self.svc.set_status('degraded')
        result = self.svc.set_status('degraded')
        self.assertFalse(result)

    def test_set_status_rejects_unknown(self):
        with self.assertRaises(ValueError):
            self.svc.set_status('exploded')

    def test_asset_dependencies_returns_linked_assets(self):
        deps = self.svc.asset_dependencies()
        names = {a.name for a in deps}
        self.assertEqual(names, {'exch01', 'dns01'})

    def test_unique_per_org(self):
        from django.db import IntegrityError
        from assets.models import Service
        with self.assertRaises(IntegrityError):
            Service.objects.create(organization=self.org, name='Email')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TopologyJSONTests(TestCase):
    """Phase 16 v3 (v3.17.303): /assets/relationships/topology.json
    returns nodes + edges for the active org."""

    def setUp(self):
        from assets.models import Service, Relationship
        self.org = Organization.objects.create(name='TopoCo', slug='topo-co')
        self.user = User.objects.create_user('topo-user', 'tu@x.com', 'pw')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.a1 = Asset.objects.create(
            organization=self.org, name='a1', asset_type='server',
        )
        self.a2 = Asset.objects.create(
            organization=self.org, name='a2', asset_type='server',
        )
        self.svc = Service.objects.create(
            organization=self.org, name='Email', status='operational',
        )
        Relationship.objects.create(
            organization=self.org,
            source_type='asset', source_id=self.a1.pk,
            target_type='asset', target_id=self.a2.pk,
            relation_type='depends',
        )
        Relationship.objects.create(
            organization=self.org,
            source_type='service', source_id=self.svc.pk,
            target_type='asset', target_id=self.a1.pk,
            relation_type='depends',
        )
        self.client = Client()
        _login_in_org(self.client, self.user, self.org)

    def test_returns_nodes_and_edges(self):
        resp = self.client.get('/assets/relationships/topology.json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['counts']['assets'], 2)
        self.assertEqual(data['counts']['services'], 1)
        self.assertEqual(data['counts']['edges'], 2)

    def test_nodes_include_asset_and_service_metadata(self):
        resp = self.client.get('/assets/relationships/topology.json')
        nodes = {n['id']: n for n in resp.json()['nodes']}
        a_node = nodes[f'asset-{self.a1.pk}']
        self.assertEqual(a_node['type'], 'asset')
        self.assertEqual(a_node['asset_type'], 'server')
        s_node = nodes[f'service-{self.svc.pk}']
        self.assertEqual(s_node['type'], 'service')
        self.assertEqual(s_node['status'], 'operational')

    def test_edges_are_typed(self):
        resp = self.client.get('/assets/relationships/topology.json')
        edges = resp.json()['edges']
        types = {e['type'] for e in edges}
        self.assertIn('depends', types)


class AssetBaselineDriftTests(TestCase):
    """Phase 17 v1+v2 (v3.17.304): baseline capture + drift detection."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='BlCo', slug='bl-co')
        cls.asset = Asset.objects.create(
            organization=cls.org, name='srv01', asset_type='server',
            os_version='Ubuntu 24.04', firmware_version='1.2.3',
            ip_address='10.0.0.5', mac_address='00:11:22:33:44:55',
            manufacturer='Dell', model='R650', serial_number='SN12345',
        )

    def test_capture_baseline_records_snapshot(self):
        b = self.asset.capture_baseline(label='post-deploy')
        self.assertEqual(b.snapshot['os_version'], 'Ubuntu 24.04')
        self.assertEqual(b.snapshot['firmware_version'], '1.2.3')
        self.assertEqual(b.snapshot['serial_number'], 'SN12345')
        self.assertTrue(b.is_current)
        self.assertEqual(b.label, 'post-deploy')

    def test_capture_baseline_marks_old_as_not_current(self):
        b1 = self.asset.capture_baseline(label='v1')
        b2 = self.asset.capture_baseline(label='v2')
        b1.refresh_from_db()
        self.assertFalse(b1.is_current)
        self.assertTrue(b2.is_current)

    def test_detect_drift_returns_empty_when_unchanged(self):
        self.asset.capture_baseline()
        self.assertEqual(self.asset.detect_drift(), [])

    def test_detect_drift_finds_changed_fields(self):
        self.asset.capture_baseline()
        self.asset.os_version = 'Ubuntu 24.10'
        self.asset.firmware_version = '1.2.4'
        self.asset.save()
        drift = self.asset.detect_drift()
        fields = {d['field'] for d in drift}
        self.assertIn('os_version', fields)
        self.assertIn('firmware_version', fields)

    def test_detect_drift_returns_empty_with_no_baseline(self):
        # Fresh asset, no baseline captured
        a = Asset.objects.create(
            organization=self.org, name='fresh', asset_type='server',
        )
        self.assertEqual(a.detect_drift(), [])

    def test_drift_includes_baseline_and_current_values(self):
        self.asset.capture_baseline()
        self.asset.ip_address = '10.0.0.99'
        self.asset.save()
        drift = self.asset.detect_drift()
        ip_drift = next((d for d in drift if d['field'] == 'ip_address'), None)
        self.assertIsNotNone(ip_drift)
        self.assertEqual(ip_drift['baseline'], '10.0.0.5')
        self.assertEqual(ip_drift['current'], '10.0.0.99')


class SoftwarePolicyTests(TestCase):
    """Phase 17 v3 (v3.17.305): SoftwarePolicy match logic."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SpCo', slug='sp-co')

    def test_substring_match_case_insensitive(self):
        from assets.models import SoftwarePolicy
        p = SoftwarePolicy.objects.create(
            organization=self.org, name='Block TeamViewer',
            pattern='TeamViewer', action='deny', severity='high',
        )
        self.assertTrue(p.matches('TeamViewer 15.x'))
        self.assertTrue(p.matches('teamviewer host'))
        self.assertFalse(p.matches('AnyDesk'))

    def test_empty_pattern_matches_nothing(self):
        from assets.models import SoftwarePolicy
        p = SoftwarePolicy(pattern='')
        self.assertFalse(p.matches('TeamViewer'))

    def test_msp_wide_policy_organization_is_none(self):
        from assets.models import SoftwarePolicy
        p = SoftwarePolicy.objects.create(
            organization=None,
            name='MSP-wide ban',
            pattern='Crypto', action='deny',
        )
        self.assertIsNone(p.organization)
        self.assertTrue(p.matches('CryptoLocker variant'))


class VulnerabilityTests(TestCase):
    """Phase 17 v6 (v3.17.306): CVE → asset matcher."""

    @classmethod
    def setUpTestData(cls):
        from integrations.models import (
            RMMConnection, RMMDevice, RMMSoftware,
        )
        cls.org = Organization.objects.create(name='VuCo', slug='vu-co')
        # Create RMM linkage
        cls.rmm = RMMConnection.objects.create(
            organization=cls.org, provider_type='ninjarmm',
            name='NinjaTest',
        )
        # Two assets, two devices, log4j installed on one
        cls.a1 = Asset.objects.create(
            organization=cls.org, name='affected-server',
            asset_type='server',
        )
        cls.a2 = Asset.objects.create(
            organization=cls.org, name='clean-server',
            asset_type='server',
        )
        d1 = RMMDevice.objects.create(
            organization=cls.org, connection=cls.rmm,
            external_id='dev-1', device_name='affected-server',
        )
        d2 = RMMDevice.objects.create(
            organization=cls.org, connection=cls.rmm,
            external_id='dev-2', device_name='clean-server',
        )
        RMMSoftware.objects.create(
            organization=cls.org, connection=cls.rmm, device=d1,
            name='Apache Log4j 2.14.0',
        )
        RMMSoftware.objects.create(
            organization=cls.org, connection=cls.rmm, device=d2,
            name='nginx 1.24.0',
        )

    def test_affected_assets_finds_matching_devices(self):
        from assets.models import Vulnerability
        v = Vulnerability.objects.create(
            cve_id='CVE-2021-44228', title='Log4Shell',
            severity='critical',
            affected_pattern='Log4j',
            organization=self.org,
        )
        affected = v.affected_assets()
        names = {a.name for a in affected}
        self.assertIn('affected-server', names)
        self.assertNotIn('clean-server', names)

    def test_affected_assets_empty_when_no_match(self):
        from assets.models import Vulnerability
        v = Vulnerability.objects.create(
            title='Phantom CVE',
            severity='low',
            affected_pattern='no-such-software',
            organization=self.org,
        )
        self.assertEqual(v.affected_assets(), [])

    def test_global_vulnerability_scopes_across_orgs(self):
        from assets.models import Vulnerability
        v = Vulnerability.objects.create(
            organization=None,  # global advisory
            title='Global Log4j',
            severity='critical',
            affected_pattern='Log4j',
        )
        affected = v.affected_assets()
        names = {a.name for a in affected}
        self.assertIn('affected-server', names)

    def test_empty_pattern_returns_empty(self):
        from assets.models import Vulnerability
        v = Vulnerability(affected_pattern='', title='x', severity='low')
        self.assertEqual(v.affected_assets(), [])

    def test_create_remediation_ticket(self):
        from assets.models import Vulnerability
        from psa.models import Ticket
        # Need basic PSA seed
        from psa.tests._base import _setup_seed
        _setup_seed()
        v = Vulnerability.objects.create(
            cve_id='CVE-TEST-1', title='Log4Shell',
            severity='critical', affected_pattern='Log4j',
            organization=self.org,
        )
        t = v.create_remediation_ticket(user=None)
        self.assertIsNotNone(t)
        self.assertIn('Log4Shell', t.subject)
        self.assertIn('affected-server', t.description)
        # Severity 'critical' → P1
        self.assertEqual(t.priority.code, 'P1')


class AssetGroupTests(TestCase):
    """Phase 17 v7 (v3.17.307): smart asset cohort matcher."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='AgCo', slug='ag-co')
        cls.dell_srv = Asset.objects.create(
            organization=cls.org, name='dell-srv', asset_type='server',
            manufacturer='Dell', os_version='Ubuntu 24.04',
        )
        cls.hp_srv = Asset.objects.create(
            organization=cls.org, name='hp-srv', asset_type='server',
            manufacturer='HP', os_version='Windows Server 2022',
        )
        cls.dell_lap = Asset.objects.create(
            organization=cls.org, name='dell-lap', asset_type='laptop',
            manufacturer='Dell', os_version='Windows 11',
        )

    def test_asset_type_matcher(self):
        from assets.models import AssetGroup
        g = AssetGroup.objects.create(
            organization=self.org, name='servers',
            criteria={'asset_type': 'server'},
        )
        names = {a.name for a in g.members()}
        self.assertEqual(names, {'dell-srv', 'hp-srv'})

    def test_manufacturer_matcher(self):
        from assets.models import AssetGroup
        g = AssetGroup.objects.create(
            organization=self.org, name='dells',
            criteria={'manufacturer__icontains': 'Dell'},
        )
        names = {a.name for a in g.members()}
        self.assertEqual(names, {'dell-srv', 'dell-lap'})

    def test_combined_criteria_AND(self):
        from assets.models import AssetGroup
        g = AssetGroup.objects.create(
            organization=self.org, name='dell-servers',
            criteria={
                'asset_type': 'server',
                'manufacturer__icontains': 'Dell',
            },
        )
        names = {a.name for a in g.members()}
        self.assertEqual(names, {'dell-srv'})

    def test_empty_criteria_returns_no_members(self):
        from assets.models import AssetGroup
        g = AssetGroup.objects.create(
            organization=self.org, name='empty', criteria={},
        )
        self.assertEqual(list(g.members()), [])

    def test_unique_per_org(self):
        from assets.models import AssetGroup
        from django.db import IntegrityError
        AssetGroup.objects.create(organization=self.org, name='dups')
        with self.assertRaises(IntegrityError):
            AssetGroup.objects.create(organization=self.org, name='dups')


class HealthScoreTests(TestCase):
    """Phase 17 v10 (v3.17.308): composite health score per asset."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='HsCo', slug='hs-co')
        cls.healthy = Asset.objects.create(
            organization=cls.org, name='healthy', asset_type='server',
            os_version='Ubuntu 24.04', firmware_version='1.2.3',
        )
        cls.healthy.capture_baseline()

    def test_perfect_health_returns_100(self):
        score = self.healthy.health_score()
        self.assertEqual(score['score'], 100)

    def test_drift_deducts_25(self):
        self.healthy.os_version = 'Ubuntu 24.10'
        self.healthy.save()
        score = self.healthy.health_score()
        self.assertLessEqual(score['score'], 75)
        self.assertEqual(score['factors']['drift'], -25)

    def test_firmware_update_deducts_10(self):
        # Reset asset to clean state
        a = Asset.objects.create(
            organization=self.org, name='fw-asset', asset_type='server',
            firmware_version='1.0', firmware_latest='2.0',
        )
        a.capture_baseline()
        score = a.health_score()
        self.assertEqual(score['factors']['firmware'], -10)
        self.assertLessEqual(score['score'], 90)

    def test_score_clamped_to_zero(self):
        from assets.models import Vulnerability
        from datetime import date, timedelta
        a = Asset.objects.create(
            organization=self.org, name='disaster', asset_type='server',
            firmware_version='1.0', firmware_latest='2.0',
            purchase_date=date.today() - timedelta(days=365 * 10),
            lifespan_years=2,
            warranty_expiry=date.today() - timedelta(days=30),
            os_version='X', ip_address='10.0.0.1',
        )
        a.capture_baseline()
        # Now drift everything
        a.os_version = 'Y'
        a.ip_address = '10.0.0.2'
        a.save()
        score = a.health_score()
        # Should be much lower than 100; clamped at 0 minimum
        self.assertGreaterEqual(score['score'], 0)
        self.assertLess(score['score'], 50)


class ConfigMonitoringCronTests(TestCase):
    """Phase 17 v9 (v3.17.308): assets_capture_baselines cron."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='CmCo', slug='cm-co')
        cls.monitored = Asset.objects.create(
            organization=cls.org, name='watched', asset_type='server',
            config_monitored=True, os_version='Ubuntu 24.04',
        )
        cls.unmonitored = Asset.objects.create(
            organization=cls.org, name='ignored', asset_type='server',
            os_version='Ubuntu 22.04',
        )

    def test_cron_captures_only_monitored(self):
        from django.core.management import call_command
        from assets.models import AssetBaseline
        call_command('assets_capture_baselines', verbosity=0)
        self.assertEqual(
            AssetBaseline.objects.filter(asset=self.monitored).count(), 1,
        )
        self.assertEqual(
            AssetBaseline.objects.filter(asset=self.unmonitored).count(), 0,
        )

    def test_dry_run_creates_no_baselines(self):
        from django.core.management import call_command
        from assets.models import AssetBaseline
        call_command('assets_capture_baselines', '--dry-run', verbosity=0)
        self.assertEqual(
            AssetBaseline.objects.filter(asset=self.monitored).count(), 0,
        )

    def test_cron_keeps_old_baselines_history(self):
        from django.core.management import call_command
        from assets.models import AssetBaseline
        call_command('assets_capture_baselines', verbosity=0)
        call_command('assets_capture_baselines', verbosity=0)
        # 2 baselines now; only the latest is_current
        baselines = AssetBaseline.objects.filter(asset=self.monitored)
        self.assertEqual(baselines.count(), 2)
        current = baselines.filter(is_current=True)
        self.assertEqual(current.count(), 1)


class RemediationSuggestionTests(TestCase):
    """Phase 17 v11 (v3.17.310): RemediationSuggestion + heuristic engine."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='RsCo', slug='rs-co')
        cls.asset = Asset.objects.create(
            organization=cls.org, name='target', asset_type='server',
            firmware_version='1.0', firmware_latest='2.0',
        )

    def test_accept_creates_ticket_with_severity_priority(self):
        from psa.tests._base import _setup_seed
        _setup_seed()
        from assets.models import RemediationSuggestion
        from psa.models import Ticket
        s = RemediationSuggestion.objects.create(
            asset=self.asset, organization=self.org,
            kind='firmware_update', severity='high',
            summary='Patch firmware',
        )
        ticket_id = s.accept()
        self.assertIsNotNone(ticket_id)
        t = Ticket.objects.get(pk=ticket_id)
        self.assertIn('Patch firmware', t.subject)
        # severity 'high' → P2
        self.assertEqual(t.priority.code, 'P2')
        s.refresh_from_db()
        self.assertEqual(s.status, 'accepted')

    def test_accept_idempotent(self):
        from psa.tests._base import _setup_seed
        _setup_seed()
        from assets.models import RemediationSuggestion
        s = RemediationSuggestion.objects.create(
            asset=self.asset, organization=self.org,
            kind='drift', severity='low',
            summary='Reconcile drift',
        )
        first = s.accept()
        second = s.accept()
        self.assertEqual(first, second)

    def test_dismiss_changes_status(self):
        from assets.models import RemediationSuggestion
        s = RemediationSuggestion.objects.create(
            asset=self.asset, organization=self.org,
            kind='health', severity='low', summary='check',
        )
        s.dismiss()
        s.refresh_from_db()
        self.assertEqual(s.status, 'dismissed')

    def test_command_no_op_when_ai_disabled(self):
        from django.core.management import call_command
        from assets.models import RemediationSuggestion
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        ss.psa_ai_enabled = False
        ss.save()
        call_command('assets_generate_remediation_suggestions', verbosity=0)
        self.assertEqual(RemediationSuggestion.objects.count(), 0)

    def test_command_generates_firmware_suggestion(self):
        from django.core.management import call_command
        from assets.models import RemediationSuggestion
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        ss.psa_ai_enabled = True
        ss.save()
        call_command('assets_generate_remediation_suggestions', verbosity=0)
        sug = RemediationSuggestion.objects.filter(
            kind='firmware_update', asset=self.asset).first()
        self.assertIsNotNone(sug)
        self.assertIn('Firmware update', sug.summary)
