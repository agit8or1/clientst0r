"""
Technician access: presets, resolver, protected changes, theft detection
and the Settings → Security → Technician Access page.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed

from . import catalog, detection, protected, services
from .models import (AccessAssignment, AccessPreset, Containment, CustomerAccessPolicy, DetectionSettings,
                     ExplicitDeny, ProtectedChange, ProtectionSettings, ReadEvent, TechnicianGroup, TheftAlert)
from .resolver import LOCKED, UNAVAILABLE, decide, effective_access
from .testing import grant, make_tech, make_ticket

ALLOWED, OFF, REQUEST = catalog.ALLOWED, catalog.OFF, catalog.REQUEST
NON_REMOTE = [k for k, v in catalog.OPTIONAL.items() if v[1] not in ('RMM', 'Remote access', 'Fixes')]


def _orgs():
    return (Organization.objects.create(name='Alpha Dental', slug='alpha'),
            Organization.objects.create(name='Beta Law', slug='beta'))


class SeedingTests(TestCase):
    def test_builtins_exist_after_migrations(self):
        self.assertEqual(set(AccessPreset.objects.filter(builtin=True).values_list('key', flat=True)),
                         {'l1', 'l2', 'l3'})

    def test_seeding_is_idempotent_and_never_overwrites(self):
        l2 = AccessPreset.objects.get(key='l2')
        l2.capabilities = dict(l2.capabilities, ai_send=OFF)
        l2.save()
        for _ in range(3):
            out = services.seed_presets()
        self.assertEqual(out['l2'], 'differs')
        self.assertEqual(AccessPreset.objects.filter(key='l2').count(), 1)
        self.assertEqual(AccessPreset.objects.get(key='l2').capabilities['ai_send'], OFF)
        call_command('init_role_templates', verbosity=0, stdout=open('/dev/null', 'w'))
        self.assertEqual(AccessPreset.objects.filter(builtin=True).count(), 3)

    def test_seeding_keeps_a_custom_preset_with_the_same_name(self):
        AccessPreset.objects.filter(key='l1').delete()
        AccessPreset.objects.create(name='L1 — Help Desk', capabilities={})
        services.seed_presets()
        self.assertTrue(AccessPreset.objects.filter(key='l1', name='L1 — Help Desk (built in)').exists())
        self.assertTrue(AccessPreset.objects.filter(key__isnull=True, name='L1 — Help Desk').exists())

    def test_l3_grants_no_locked_safeguard_and_unattended_is_off_everywhere(self):
        for caps in (catalog.L1, catalog.L2, catalog.L3):
            for k in ('unattended_access', 'clipboard', 'file_transfer', 'export'):
                self.assertEqual(caps[k], OFF, k)
        self.assertFalse(set(catalog.LOCKED) & set(catalog.L3))


class PermissionMatrixTests(TestCase):
    """Every preset × every capability, at one customer, on a ticket the
    technician is assigned (fixture: no rem0te pairing, so RMM / remote /
    fix capabilities report Unavailable)."""

    def setUp(self):
        _setup_seed()
        self.a, _ = _orgs()

    def test_matrix(self):
        for key, caps in (('l1', catalog.L1), ('l2', catalog.L2), ('l3', catalog.L3)):
            tech = make_tech(f'tech-{key}')
            grant(tech, self.a, key)
            ticket = make_ticket(self.a, assigned_to=tech)
            for cap in catalog.OPTIONAL:
                d = decide(tech, self.a, cap, ticket=ticket)
                want = caps[cap] if cap in NON_REMOTE else UNAVAILABLE
                self.assertEqual(d.state, want, f'{key} {cap}: {d.reason}')
            for cap in catalog.LOCKED:
                self.assertEqual(decide(tech, self.a, cap).state, LOCKED)

    def test_matrix_with_paired_rem0te_that_offers_everything(self):
        tech = make_tech('tech-rmm')
        grant(tech, self.a, 'l2')
        ticket = make_ticket(self.a, assigned_to=tech)
        with patch('tech_access.resolver.unavailable_reason', return_value=''):
            for cap in catalog.OPTIONAL:
                self.assertEqual(decide(tech, self.a, cap, ticket=ticket).state, catalog.L2[cap], cap)


class ResolverTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.a, self.b = _orgs()
        self.tech = make_tech('morgan')

    def test_no_assignment_means_off(self):
        d = decide(self.tech, self.a, 'ai_analyze')
        self.assertEqual(d.state, OFF)
        self.assertIn('no technician access assignment', d.reason)

    def test_superuser_staff_and_owner_flags_never_imply_access(self):
        boss = make_tech('boss', superuser=True)
        boss.is_staff = True
        boss.save()
        Membership.objects.create(user=boss, organization=self.a, role=Role.OWNER)
        for cap in catalog.OPTIONAL:
            self.assertNotEqual(decide(boss, self.a, cap).state, ALLOWED, cap)

    def test_portal_users_are_outside_presets_even_with_an_assignment(self):
        portal = User.objects.create_user('client', password='pw')
        Membership.objects.create(user=portal, organization=self.a, role=Role.OWNER)
        AccessAssignment.objects.create(preset=services.builtin('l3'), organization=self.a, user=portal)
        d = decide(portal, self.a, 'ai_analyze')
        self.assertEqual(d.state, OFF)
        self.assertIn('portal', d.reason)

    def test_l3_at_one_customer_and_l1_at_another(self):
        grant(self.tech, self.a, 'l3')
        grant(self.tech, self.b, 'l1')
        other = make_tech('other')
        ta, tb = make_ticket(self.a, assigned_to=other), make_ticket(self.b, assigned_to=other)
        self.assertTrue(decide(self.tech, self.a, 'ai_compare', ticket=ta).allowed)
        self.assertEqual(decide(self.tech, self.b, 'ai_compare').state, OFF)
        # review_others from A must not widen B.
        self.assertTrue(decide(self.tech, self.a, 'ai_analyze', ticket=ta).allowed)
        self.assertEqual(decide(self.tech, self.b, 'ai_analyze', ticket=tb).state, OFF)
        # A ticket from B checked against A is refused outright.
        self.assertEqual(decide(self.tech, self.a, 'ai_analyze', ticket=tb).state, OFF)

    def test_overlapping_groups_best_assignment_wins_but_denies_beat_all(self):
        g1 = TechnicianGroup.objects.create(name='Help desk')
        g2 = TechnicianGroup.objects.create(name='Seniors')
        g1.members.add(self.tech)
        g2.members.add(self.tech)
        grant(None, self.a, 'l1', group=g1)
        grant(None, self.a, 'l3', group=g2)
        d = decide(self.tech, self.a, 'ai_compare')
        self.assertTrue(d.allowed)
        self.assertEqual(len(d.notes), 2)
        ExplicitDeny.objects.create(user=self.tech, capability='ai_compare', organization=self.a)
        self.assertEqual(decide(self.tech, self.a, 'ai_compare').source, 'Explicit deny')
        ExplicitDeny.objects.create(user=self.tech, capability='*')
        self.assertEqual(decide(self.tech, self.a, 'ai_analyze').state, OFF)

    def test_customer_restriction_wins(self):
        grant(self.tech, self.a, 'l3')
        CustomerAccessPolicy.objects.create(organization=self.a, restricted=['ai_compare'])
        self.assertEqual(decide(self.tech, self.a, 'ai_compare').source, 'Customer restriction')
        self.assertTrue(decide(self.tech, self.a, 'ai_analyze').allowed)

    def test_expiry_and_revocation_apply_on_the_next_call(self):
        a = grant(self.tech, self.a, 'l2', expires_at=timezone.now() + timedelta(minutes=5))
        self.assertTrue(decide(self.tech, self.a, 'ai_send').allowed)
        later = timezone.now() + timedelta(minutes=6)
        self.assertEqual(decide(self.tech, self.a, 'ai_send', now=later).state, OFF)
        services.revoke(a, self.tech)
        self.assertEqual(decide(self.tech, self.a, 'ai_send').state, OFF)

    def test_inactive_or_demoted_technician_loses_everything(self):
        grant(self.tech, self.a, 'l3')
        self.tech.profile.user_type = 'org_user'
        self.tech.profile.save()
        self.tech.refresh_from_db()
        self.assertEqual(decide(self.tech, self.a, 'ai_analyze').state, OFF)

    def test_ticket_scope_needs_assignment_or_review_others(self):
        grant(self.tech, self.a, 'l2')
        mine, theirs = make_ticket(self.a, assigned_to=self.tech), make_ticket(self.a)
        self.assertTrue(decide(self.tech, self.a, 'ai_analyze', ticket=mine).allowed)
        d = decide(self.tech, self.a, 'ai_analyze', ticket=theirs)
        self.assertEqual(d.state, OFF)
        self.assertIn('not assigned to you', d.reason)

    def test_readonly_diagnostics_cover_standard_workstations_only(self):
        from assets.models import Asset
        grant(self.tech, self.a, 'l2')
        server = Asset.objects.create(organization=self.a, name='DC01', asset_type='server')
        laptop = Asset.objects.create(organization=self.a, name='LT-7', asset_type='laptop')
        with patch('tech_access.resolver.unavailable_reason', return_value=''):
            self.assertTrue(decide(self.tech, self.a, 'diagnostics_readonly', asset=laptop).allowed)
            self.assertEqual(decide(self.tech, self.a, 'diagnostics_readonly', asset=server).state, OFF)

    def test_rmm_capabilities_unavailable_without_pairing(self):
        grant(self.tech, self.a, 'l3')
        d = decide(self.tech, self.a, 'rmm_handoff')
        self.assertEqual(d.state, UNAVAILABLE)
        self.assertIn('rem0te', d.reason)

    def test_effective_access_explains_every_entry(self):
        grant(self.tech, self.a, 'l1')
        rows = effective_access(self.tech, self.a)
        self.assertEqual(len(rows), len(catalog.OPTIONAL) + len(catalog.LOCKED))
        self.assertTrue(all(r.reason for r in rows))

    def test_custom_preset_clone_and_edit(self):
        admin = make_tech('admin1', superuser=True)
        clone = services.clone_preset(services.builtin('l2'), 'L2 no compare', admin)
        applied, change, plan = services.change_preset(clone, dict(clone.caps(), ai_compare=OFF), admin)
        self.assertTrue(applied)
        self.assertIsNone(change)
        grant_obj = AccessAssignment.objects.create(preset=clone, organization=self.a, user=self.tech)
        self.assertEqual(decide(self.tech, self.a, 'ai_compare').state, OFF)
        self.assertTrue(decide(self.tech, self.a, 'ai_send').allowed)
        grant_obj.delete()

    def test_builtin_presets_cannot_be_edited(self):
        admin = make_tech('admin1', superuser=True)
        with self.assertRaises(ValueError):
            services.change_preset(services.builtin('l1'), catalog.L3, admin)


class _Req:
    """Enough of a request for protected.* (session + user)."""
    def __init__(self, user):
        self.user = user
        self.session = {}
        self.META = {}
        self.path = '/test'


class ProtectedChangeTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.a, self.b = _orgs()
        self.alice = make_tech('alice', superuser=True)
        self.bob = make_tech('bob', superuser=True)
        self.tech = make_tech('tech')
        ProtectionSettings.objects.update_or_create(pk=1, defaults={
            'recovery_email': 'old-security@msp.test', 'recovery_verified_at': timezone.now()})

    def _fresh(self, user):
        r = _Req(user)
        self.assertEqual(protected.reauthenticate(r, 'pw-' + user.username), '')
        return r

    def test_l1_assignment_applies_at_once(self):
        a, change, plan = services.assign(self.tech, self.a, services.builtin('l1'), self.alice)
        self.assertIsNotNone(a)
        self.assertIsNone(change)
        self.assertFalse(plan.needs_review)

    def test_widening_needs_requester_confirmation_and_distinct_reviewer(self):
        a, change, plan = services.assign(self.tech, self.a, services.builtin('l2'), self.alice)
        self.assertIsNone(a)
        self.assertIn('ai_send', change.widening)
        self.assertIn(self.tech.pk, change.affected_users)
        self.assertFalse(AccessAssignment.objects.filter(user=self.tech).exists())
        # Not confirmed yet.
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(change, self._fresh(self.bob))
        # Requester must have re-authenticated.
        with self.assertRaises(protected.ProtectedChangeError):
            protected.confirm(change, _Req(self.alice))
        protected.confirm(change, self._fresh(self.alice))
        # Requester can't approve their own change.
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.alice))
        # Reviewer needs fresh auth too.
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), _Req(self.bob))
        protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.bob))
        self.assertTrue(decide(self.tech, self.a, 'ai_send').allowed)
        self.assertEqual(ProtectedChange.objects.get(pk=change.pk).status, 'applied')
        self.assertTrue(any('old-security@msp.test' in m.to for m in mail.outbox))

    def test_wrong_password_and_missing_otp_are_refused(self):
        r = _Req(self.alice)
        self.assertEqual(protected.reauthenticate(r, 'nope'), 'Password incorrect.')
        from django_otp.plugins.otp_totp.models import TOTPDevice
        TOTPDevice.objects.create(user=self.alice, name='phone', confirmed=True)
        self.assertEqual(protected.reauthenticate(r, 'pw-alice'), 'Authenticator code incorrect.')
        self.assertFalse(protected.has_fresh_auth(r))

    def test_self_promotion_is_refused(self):
        _, change, _ = services.assign(self.bob, self.a, services.builtin('l3'), self.alice)
        protected.confirm(change, self._fresh(self.alice))
        with self.assertRaisesMessage(protected.ProtectedChangeError, 'your own access'):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.bob))

    def test_recovery_contact_cannot_be_approved_by_its_owner_and_old_contact_is_told(self):
        change = services.propose_recovery_contact(self.bob.email, self.alice)
        protected.confirm(change, self._fresh(self.alice))
        with self.assertRaisesMessage(protected.ProtectedChangeError, 'your own address'):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.bob))
        carol = make_tech('carol', superuser=True)
        mail.outbox.clear()
        protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(carol))
        self.assertEqual(ProtectionSettings.load().recovery_email, self.bob.email)
        self.assertTrue(any('old-security@msp.test' in m.to for m in mail.outbox))

    def test_one_admin_install_cannot_widen(self):
        self.bob.delete()
        self.assertFalse(protected.can_widen_at_all(self.alice))
        _, change, _ = services.assign(self.tech, self.a, services.builtin('l2'), self.alice)
        protected.confirm(change, self._fresh(self.alice))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.alice))

    def test_expired_change_cannot_be_approved(self):
        _, change, _ = services.assign(self.tech, self.a, services.builtin('l2'), self.alice)
        protected.confirm(change, self._fresh(self.alice))
        ProtectedChange.objects.filter(pk=change.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaisesMessage(protected.ProtectedChangeError, 'expired'):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.bob))

    def test_group_member_addition_widening_is_reviewed_and_removal_is_not(self):
        g = TechnicianGroup.objects.create(name='Seniors')
        grant(None, self.a, 'l3', group=g)
        applied, change, _ = services.set_group_members(g, [self.tech], self.alice)
        self.assertFalse(applied)
        self.assertFalse(g.members.exists())
        g.members.add(self.tech)
        applied, change, _ = services.set_group_members(g, [], self.alice)
        self.assertTrue(applied)
        self.assertFalse(g.members.exists())

    def test_lifting_a_restriction_or_deny_is_reviewed(self):
        services.set_restrictions(self.a, ['ai_compare'], self.alice)
        self.assertEqual(CustomerAccessPolicy.objects.get(organization=self.a).restricted, ['ai_compare'])
        change = services.set_restrictions(self.a, [], self.alice)
        self.assertEqual(change.kind, 'security_limits')
        self.assertEqual(CustomerAccessPolicy.objects.get(organization=self.a).restricted, ['ai_compare'])
        d = services.add_deny(self.tech, 'ai_send', self.alice)
        change = services.remove_deny(d, self.alice)
        self.assertTrue(ExplicitDeny.objects.filter(pk=d.pk).exists())
        protected.confirm(change, self._fresh(self.alice))
        protected.approve(ProtectedChange.objects.get(pk=change.pk), self._fresh(self.bob))
        self.assertFalse(ExplicitDeny.objects.filter(pk=d.pk).exists())

    def test_demotion_while_pending_change_and_reset_preview(self):
        l2 = services.builtin('l2')
        l2.capabilities = dict(l2.capabilities, ai_compare=OFF)
        l2.save()
        grant(self.tech, self.a, 'l2')
        plan = services.reset_preview(l2)
        self.assertEqual(plan.widening, ['ai_compare'])
        self.assertEqual(plan.rows[0]['changes'][0]['key'], 'ai_compare')
        applied, change, _ = services.reset_preset(l2, self.alice)
        self.assertFalse(applied)
        self.assertEqual(decide(self.tech, self.a, 'ai_compare').state, OFF)


class DetectionTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.a, self.b = _orgs()
        self.tech = make_tech('reader')
        self.admin = make_tech('secadmin', superuser=True)
        s = DetectionSettings.load()
        s.thresholds = {'tickets': {'1h': 5}, 'customers': {'1h': 2}}
        s.save()

    def test_enabled_by_default(self):
        DetectionSettings.objects.all().delete()
        self.assertTrue(DetectionSettings.load().enabled)

    def test_distinct_reads_raise_one_alert_and_contain(self):
        tickets = [make_ticket(self.a, subject=f'Secret payroll issue {i}') for i in range(6)]
        for t in tickets + tickets:  # repeats don't count twice
            detection.record(self.tech, 'ticket', t.pk, self.a.pk, 'api')
        self.assertEqual(ReadEvent.objects.filter(user=self.tech, kind='ticket').count(), 6)
        alerts = TheftAlert.objects.filter(user=self.tech, rule='tickets')
        self.assertEqual(alerts.count(), 1)
        self.assertTrue(Containment.objects.filter(user=self.tech, lifted_at__isnull=True).exists())
        grant(self.tech, self.a, 'l3')
        self.assertEqual(decide(self.tech, self.a, 'ai_analyze').source, 'Containment')
        for m in mail.outbox:
            self.assertNotIn('payroll', m.body)
            self.assertNotIn('Secret', m.body)
        self.assertIn(self.admin.email, sum((m.to for m in mail.outbox), []))

    def test_alert_only_level_does_not_contain(self):
        s = DetectionSettings.load()
        s.containment = {'3': 'alert'}
        s.save()
        grant(self.tech, self.a, 'l3')
        for i in range(6):
            detection.record(self.tech, 'ticket', make_ticket(self.a).pk, self.a.pk)
        self.assertTrue(TheftAlert.objects.filter(user=self.tech, contained=False).exists())
        self.assertFalse(Containment.objects.filter(user=self.tech).exists())

    def test_cross_customer_breadth_is_counted(self):
        c = Organization.objects.create(name='Gamma', slug='gamma')
        for org in (self.a, self.b, c):
            detection.record(self.tech, 'ticket', make_ticket(org).pk, org.pk, 'mobile')
        self.assertTrue(TheftAlert.objects.filter(user=self.tech, rule='customers').exists())

    def test_disabled_detection_records_nothing(self):
        s = DetectionSettings.load()
        s.enabled = False
        s.save()
        detection.record(self.tech, 'ticket', 1, self.a.pk)
        self.assertFalse(ReadEvent.objects.exists())

    def test_loosening_needs_review_and_tightening_applies(self):
        self.assertIsNone(services.propose_detection({'thresholds': {'tickets': {'1h': 3}}}, self.admin))
        self.assertEqual(detection.thresholds()['tickets']['1h'], 3)
        change = services.propose_detection({'enabled': False}, self.admin)
        self.assertIn('detection disabled', change.widening)
        self.assertTrue(DetectionSettings.load().enabled)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StolenSessionDrillTests(TestCase):
    """A stolen technician session: bulk reads through UI and mobile API,
    contact takeover, remote control, cross-customer access."""

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.a, self.b = _orgs()
        for org in (self.a, self.b):
            _enable_psa_for(org)
        self.victim = make_tech('victim')
        grant(self.victim, self.a, 'l2')
        self.admin = make_tech('secadmin', superuser=True)
        s = DetectionSettings.load()
        s.thresholds = {'tickets': {'1h': 4}}
        s.save()
        self.c = Client()
        self.c.force_login(self.victim)

    def test_bulk_ui_reads_contain_the_session(self):
        own = make_ticket(self.a, assigned_to=self.victim)
        others = [make_ticket(self.a) for _ in range(5)]
        for t in others:
            self.c.get(f'/psa/t/{t.ticket_number}/')
        self.assertTrue(Containment.objects.filter(user=self.victim, lifted_at__isnull=True).exists())
        self.assertEqual(self.c.get(f'/psa/t/{others[0].ticket_number}/').status_code, 403)
        self.assertEqual(self.c.get(f'/psa/t/{own.ticket_number}/').status_code, 200)

    def test_bulk_mobile_api_reads_are_counted_and_contained(self):
        from api_mobile.models import MobileAuthToken
        Membership.objects.create(user=self.victim, organization=self.a, role=Role.EDITOR)
        raw, _ = MobileAuthToken.issue(self.victim)
        api = Client(HTTP_AUTHORIZATION=f'Token {raw}')
        codes = [api.get(f'/api/mobile/v1/tickets/{make_ticket(self.a).pk}/').status_code for _ in range(6)]
        self.assertEqual(codes[0], 200)
        self.assertTrue(ReadEvent.objects.filter(user=self.victim, channel='mobile', kind='ticket').exists())
        self.assertTrue(Containment.objects.filter(user=self.victim, lifted_at__isnull=True).exists())
        self.assertEqual(codes[-1], 403)  # token callers are refused on the response

    def test_contact_takeover_and_self_widening_need_another_admin(self):
        r = _Req(self.admin)
        change = services.propose_recovery_contact('attacker@evil.test', self.admin)
        protected.reauthenticate(r, 'pw-secadmin')
        protected.confirm(change, r)
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), r)
        self.assertEqual(ProtectionSettings.load().recovery_email, '')

    def test_remote_control_and_cross_customer_stay_closed(self):
        t_b = make_ticket(self.b, assigned_to=self.victim)
        self.assertNotEqual(decide(self.victim, self.a, 'remote_control').state, ALLOWED)
        self.assertEqual(decide(self.victim, self.b, 'ai_analyze', ticket=t_b).state, OFF)
        self.assertEqual(decide(self.victim, self.a, 'cross_customer').state, LOCKED)
        self.assertEqual(decide(self.victim, self.a, 'unattended_access').state, UNAVAILABLE)
        with patch('tech_access.resolver.unavailable_reason', return_value=''):
            self.assertEqual(decide(self.victim, self.a, 'remote_control').state, REQUEST)
            self.assertEqual(decide(self.victim, self.a, 'unattended_access').state, OFF)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TechnicianAccessPageTests(TestCase):
    URL = '/settings/security/technician-access/'

    def setUp(self):
        _setup_seed()
        self.a, self.b = _orgs()
        self.admin = make_tech('alice', superuser=True)
        self.other_admin = make_tech('bob', superuser=True)
        self.tech = make_tech('tech')
        self.c = Client()
        self.c.force_login(self.admin)

    def test_only_security_admins(self):
        c = Client()
        c.force_login(self.tech)
        self.assertNotEqual(c.get(self.URL).status_code, 200)
        r = self.c.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'L3 — Senior Technician')

    def test_preview_then_save_l1_and_propose_l2(self):
        l1, l2 = services.builtin('l1'), services.builtin('l2')
        r = self.c.post(self.URL, {'action': 'preview_assign', 'user': self.tech.pk, 'organization': self.a.pk,
                                   'preset': l2.pk, 'section': 'assignments'})
        self.assertContains(r, 'Widens')
        self.assertContains(r, 'Send reviewed AI replies')
        self.assertFalse(AccessAssignment.objects.exists())
        self.c.post(self.URL, {'action': 'save_assign', 'user': self.tech.pk, 'organization': self.a.pk,
                               'preset': l1.pk})
        self.assertTrue(AccessAssignment.objects.filter(user=self.tech, preset=l1).exists())
        self.c.post(self.URL, {'action': 'save_assign', 'user': self.tech.pk, 'organization': self.b.pk,
                               'preset': l2.pk})
        self.assertFalse(AccessAssignment.objects.filter(organization=self.b).exists())
        change = ProtectedChange.objects.get(status='pending')
        # Confirm → approve by the other admin, through the page.
        self.c.post(self.URL, {'action': 'reauth', 'password': 'pw-alice'})
        self.c.post(self.URL, {'action': 'confirm_change', 'change': change.pk})
        c2 = Client()
        c2.force_login(self.other_admin)
        c2.post(self.URL, {'action': 'approve_change', 'change': change.pk})
        self.assertFalse(AccessAssignment.objects.filter(organization=self.b).exists())  # no fresh auth yet
        c2.post(self.URL, {'action': 'reauth', 'password': 'pw-bob'})
        c2.post(self.URL, {'action': 'approve_change', 'change': change.pk})
        self.assertTrue(AccessAssignment.objects.filter(organization=self.b, preset=l2).exists())

    def test_effective_access_preview_and_new_technicians_start_with_nothing(self):
        r = self.c.get(self.URL, {'preview_user': self.tech.pk, 'preview_org': self.a.pk})
        self.assertContains(r, 'no technician access assignment')
        self.assertEqual(services.default_preset_for(self.a).key, 'l1')

    def test_lift_containment_needs_another_admin_and_fresh_auth(self):
        c = Containment.objects.create(user=self.admin, reason='test')
        self.c.post(self.URL, {'action': 'reauth', 'password': 'pw-alice'})
        self.c.post(self.URL, {'action': 'lift_containment', 'containment': c.pk})
        self.assertIsNone(Containment.objects.get(pk=c.pk).lifted_at)


class MappingReportTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.a, _ = _orgs()

    def test_report_lists_legacy_roles_and_unassigned_without_changing_anything(self):
        from .management.commands.tech_access_report import build_report
        boss = make_tech('boss', superuser=True)
        t = RoleTemplate.objects.create(name='Custom approvers', organization=self.a,
                                        psa_ai_view=True, psa_ai_approve_reply=True)
        tech = make_tech('plain')
        Membership.objects.create(user=tech, organization=self.a, role=Role.EDITOR, role_template=t)
        before = AccessAssignment.objects.count()
        r = build_report()
        self.assertIn('boss', r['privileged_not_l3'])
        self.assertIn('plain', r['unassigned'])
        self.assertTrue(any(row['template'] == 'Custom approvers' for row in r['ambiguous']))
        self.assertEqual(AccessAssignment.objects.count(), before)
        self.assertTrue(RoleTemplate.objects.filter(pk=t.pk, psa_ai_approve_reply=True).exists())
