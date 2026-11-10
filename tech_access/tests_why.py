"""
"Why can this technician do this here?" — the explain view, the assignment
and protected-change record pages, and the before/after audit entries they
read.
"""
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed

from . import catalog, protected, services
from .explain import BLOCKS, GRANTS, NOT_COUNTED, explain
from .models import AccessAssignment, ProtectedChange, ProtectionSettings, TechnicianGroup
from .testing import grant, make_tech

WHY = '/settings/security/technician-access/why/'


class _Req:
    def __init__(self, user):
        self.user, self.session, self.META, self.path = user, {}, {}, '/test'


def _fresh(user):
    r = _Req(user)
    assert protected.reauthenticate(r, 'pw-' + user.username) == ''
    return r


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WhyTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.a = Organization.objects.create(name='Alpha Dental', slug='alpha')
        self.b = Organization.objects.create(name='Beta Law', slug='beta')
        self.alice = make_tech('alice', superuser=True)
        self.bob = make_tech('bob', superuser=True)
        self.tech = make_tech('tech')
        ProtectionSettings.objects.update_or_create(pk=1, defaults={'recovery_email': ''})
        self.c = Client()
        self.c.force_login(self.alice)

    def _approved_l2(self, org):
        _, change, _ = services.assign(self.tech, org, services.builtin('l2'), self.alice,
                                       expires_at=timezone.now() + timedelta(days=7), note='on-call cover')
        protected.confirm(change, _fresh(self.alice))
        protected.approve(ProtectedChange.objects.get(pk=change.pk), _fresh(self.bob))
        return ProtectedChange.objects.get(pk=change.pk), AccessAssignment.objects.get(organization=org)

    def _get(self, cap, org=None, user=None):
        return self.c.get(WHY, {'user': (user or self.tech).pk, 'organization': (org or self.a).pk,
                                'capability': cap})

    # --- the chain ---------------------------------------------------------

    def test_approved_grant_shows_who_when_expiry_approval_and_audit(self):
        change, a = self._approved_l2(self.a)
        self.assertEqual(a.approved_change_id, change.pk)
        ex = explain(self.tech, self.a, 'ai_send')
        self.assertEqual(ex.outcome, catalog.ALLOWED)
        src = next(s for s in ex.sources if s.kind == 'assignment')
        self.assertTrue(src.decisive)
        self.assertEqual(src.effect, GRANTS)
        self.assertEqual(src.approval.pk, change.pk)
        self.assertIn('approved by bob', src.granted_by)
        self.assertEqual(ex.expires_at, a.expires_at)
        r = self._get('ai_send')
        self.assertContains(r, 'Allowed in scope')
        self.assertContains(r, f'/settings/security/technician-access/changes/{change.pk}/')
        self.assertContains(r, f'/settings/security/technician-access/assignments/{a.pk}/')
        self.assertContains(r, 'approved by bob')
        self.assertContains(r, 'on-call cover')
        self.assertContains(r, 'decides it')
        # Audit history: the assignment's creation (before — / after preset) and
        # the protected change's own lifecycle.
        self.assertContains(r, 'Protected change approved and applied')
        self.assertContains(r, '<code>preset</code>: <span class="text-muted">—</span> → <strong>L2', html=False)

    def test_expired_grant_is_shown_as_expired_and_not_counted(self):
        grant(self.tech, self.a, 'l3', expires_at=timezone.now() - timedelta(hours=1))
        ex = explain(self.tech, self.a, 'ai_analyze')
        self.assertEqual(ex.outcome, catalog.OFF)
        src = next(s for s in ex.sources if s.kind == 'assignment')
        self.assertEqual((src.status, src.effect, src.decisive), ('expired', NOT_COUNTED, False))
        r = self._get('ai_analyze')
        self.assertContains(r, '>expired<')
        self.assertContains(r, '(expired)')
        self.assertContains(r, 'Expired — not counted.')

    def test_revoked_grant_shows_revoker_and_before_after(self):
        a = grant(self.tech, self.a, 'l1')
        services.revoke(a, self.bob)
        a.refresh_from_db()
        self.assertEqual(a.revoked_by, self.bob)
        entry = AuditLog.objects.get(object_type='tech_access_assignment', object_id=a.pk, action='delete')
        self.assertIsNone(entry.extra_data['before']['revoked_at'])
        self.assertIsNotNone(entry.extra_data['after']['revoked_at'])
        ex = explain(self.tech, self.a, 'ai_analyze')
        src = next(s for s in ex.sources if s.kind == 'assignment')
        self.assertEqual((src.status, src.revoked_by), ('revoked', 'bob'))
        r = self._get('ai_analyze')
        self.assertContains(r, '>revoked<')
        self.assertContains(r, 'by bob')
        self.assertContains(r, '<code>revoked_at</code>', html=False)

    def test_request_outcome_and_group_assignment(self):
        group = TechnicianGroup.objects.create(name='Night shift')
        services.set_group_members(group, [self.tech], self.alice)  # empty group, L1 baseline → applies
        group.members.add(self.tech)
        grant(None, self.a, 'l2', group=group)
        # remote_view is a "request" in L2 but needs a paired RMM: unavailable here.
        ex = explain(self.tech, self.a, 'remote_view')
        self.assertEqual(ex.outcome, 'unavailable')
        self.assertTrue(any(s.kind == 'pairing' and s.effect == BLOCKS and s.decisive for s in ex.sources))
        ex = explain(self.tech, self.a, 'ai_compare')
        src = next(s for s in ex.sources if s.kind == 'assignment')
        self.assertTrue(src.decisive)
        self.assertIn('Night shift', src.detail)
        self.assertIn('leaves the group', ex.expiry_note)

    def test_locked_capability_names_the_safeguard(self):
        grant(self.tech, self.a, 'l3')
        ex = explain(self.tech, self.a, 'fix_approval')
        self.assertEqual(ex.outcome, 'locked')
        self.assertEqual([s.kind for s in ex.sources], ['safeguard'])
        self.assertContains(self._get('fix_approval'), 'Mandatory safeguard')

    def test_deny_and_membership_role_change_with_before_after(self):
        grant(self.tech, self.a, 'l2')
        m = Membership.objects.create(user=self.tech, organization=self.a, role=Role.READONLY, is_active=True)
        m.role = Role.EDITOR
        m.save()
        services.add_deny(self.tech, 'ai_send', self.alice, self.a, 'pending review',
                          timezone.now() + timedelta(days=1))
        ex = explain(self.tech, self.a, 'ai_send')
        self.assertEqual(ex.outcome, catalog.OFF)
        deny = next(s for s in ex.sources if s.kind == 'deny')
        self.assertTrue(deny.decisive)
        self.assertEqual(ex.expires_at, deny.expires_at)
        mem = next(s for s in ex.sources if s.kind == 'membership')
        changes = [e for e in mem.history if e.extra_data.get('event') == 'role_change']
        self.assertEqual(changes[0].extra_data['before']['role'], 'readonly')
        self.assertEqual(changes[0].extra_data['after']['role'], 'editor')
        r = self._get('ai_send')
        self.assertContains(r, 'pending review')
        self.assertContains(r, '<code>role</code>: <span class="text-muted">readonly</span> → <strong>editor</strong>',
                            html=False)

    # --- scope and permission ---------------------------------------------

    def test_other_customers_rows_never_appear(self):
        beta_only = services.clone_preset(services.builtin('l1'), 'Beta-only preset', self.alice)
        AccessAssignment.objects.create(preset=beta_only, organization=self.b, user=self.tech, note='beta secret')
        services.add_deny(self.tech, 'ai_draft', self.alice, self.b, 'beta deny reason')
        Membership.objects.create(user=self.tech, organization=self.b, role=Role.OWNER, is_active=True)
        grant(self.tech, self.a, 'l1')
        r = self._get('ai_draft')
        self.assertContains(r, 'Allowed in scope')
        for leaked in ('Beta-only preset', 'beta secret', 'beta deny reason', 'Beta Law:'):
            self.assertNotContains(r, leaked)

    def test_only_security_admins(self):
        a = grant(self.tech, self.a, 'l1')
        _, change, _ = services.assign(self.tech, self.b, services.builtin('l2'), self.alice)
        c = Client()
        c.force_login(self.tech)
        for url in (WHY + f'?user={self.tech.pk}&organization={self.a.pk}&capability=ai_send',
                    f'/settings/security/technician-access/assignments/{a.pk}/',
                    f'/settings/security/technician-access/changes/{change.pk}/'):
            self.assertNotEqual(c.get(url).status_code, 200, url)
            self.assertEqual(self.c.get(url).status_code, 200, url)
        self.assertEqual(self._get('not_a_capability').status_code, 404)

    def test_record_pages_link_grant_and_approval(self):
        change, a = self._approved_l2(self.a)
        r = self.c.get(f'/settings/security/technician-access/assignments/{a.pk}/')
        self.assertContains(r, f'Protected change #{change.pk}')
        self.assertContains(r, 'approved by bob')
        r = self.c.get(f'/settings/security/technician-access/changes/{change.pk}/')
        self.assertContains(r, f'Assignment #{a.pk}')
        self.assertContains(r, 'Applied')
        # The preview links each row to its "why".
        r = self.c.get('/settings/security/technician-access/', {'preview_user': self.tech.pk,
                                                                 'preview_org': self.a.pk})
        self.assertContains(r, 'capability=ai_send')

    def test_pre_upgrade_assignment_is_matched_to_its_change(self):
        change, a = self._approved_l2(self.a)
        AccessAssignment.objects.filter(pk=a.pk).update(approved_change=None)
        src = next(s for s in explain(self.tech, self.a, 'ai_send').sources if s.kind == 'assignment')
        self.assertEqual(src.approval.pk, change.pk)
