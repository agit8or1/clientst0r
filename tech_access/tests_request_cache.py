"""113.7: the per-request memo of technician-access rows
(tech_access/request_cache.py).

* The memo never changes a decision: for a matrix of technicians and rules,
  every capability check answers exactly what it answers with no memo
  (state, reason, source and the per-assignment notes), for the resolver,
  the RMM permission layer and the AI capability checks built on it.
* The memo exists only inside a request's authorization context and dies
  with it; outside a request (jobs, commands) nothing is memoised.
* A rule the request itself changes through the ORM (save, delete, group
  membership) is re-read by the request's next check. A change that sends no
  signal (another process, or a QuerySet.update()) is picked up by the next
  request: no code may rely on seeing it part-way through a request.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts import authz_cache
from accounts.models import Membership, Role
from core.models import Organization
from psa.tests._base import _setup_seed

from . import catalog, request_cache, resolver, services
from .models import AccessAssignment, Containment, CustomerAccessPolicy, ExplicitDeny, TechnicianGroup
from .testing import grant, make_tech, make_ticket


def _sig(d):
    return (d.state, d.reason, d.source, d.capability, list(d.notes))


class _Bound:
    """Open a request authorization context like CurrentOrganizationMiddleware."""

    def __init__(self, user=None):
        self.request = RequestFactory().get('/')
        self.request.user = user

    def __enter__(self):
        self.token = authz_cache.bind_request(self.request)
        return self.request

    def __exit__(self, *exc):
        authz_cache.unbind(self.token)


class MemoMatchesTheDatabaseTests(TestCase):
    """Same answers with and without the memo, for a matrix of users and rules."""

    @classmethod
    def setUpTestData(cls):
        from assets.models import Asset
        _setup_seed()
        cls.a = Organization.objects.create(name='Alpha Dental', slug='alpha')
        cls.b = Organization.objects.create(name='Beta Law', slug='beta')
        cls.c = Organization.objects.create(name='Gamma Labs', slug='gamma')
        now = timezone.now()
        cls.l1 = make_tech('m-l1')
        grant(cls.l1, cls.a, 'l1')
        cls.l2 = make_tech('m-l2')
        grant(cls.l2, cls.a, 'l2')
        grant(cls.l2, cls.b, 'l3', expires_at=now - timedelta(minutes=1))        # expired
        cls.l3 = make_tech('m-l3')
        grant(cls.l3, cls.a, 'l3')
        grant(cls.l3, cls.b, 'l1')
        revoked = grant(cls.l3, cls.c, 'l3')
        AccessAssignment.objects.filter(pk=revoked.pk).update(revoked_at=now)    # revoked
        cls.grouped = make_tech('m-group')
        g1 = TechnicianGroup.objects.create(name='Help desk')
        g2 = TechnicianGroup.objects.create(name='Seniors')
        g1.members.add(cls.grouped)
        g2.members.add(cls.grouped)
        grant(None, cls.a, 'l1', group=g1)
        grant(None, cls.a, 'l3', group=g2)
        grant(None, cls.b, 'l2', group=g2)
        cls.denied = make_tech('m-denied')
        grant(cls.denied, cls.a, 'l3')
        grant(cls.denied, cls.b, 'l3')
        ExplicitDeny.objects.create(user=cls.denied, capability='ai_compare', organization=cls.a, reason='audit')
        ExplicitDeny.objects.create(user=cls.denied, capability='ai_send', reason='everywhere')
        ExplicitDeny.objects.create(user=cls.denied, capability='*', organization=cls.b,
                                    expires_at=now + timedelta(hours=1))
        ExplicitDeny.objects.create(user=cls.denied, capability='ai_analyze',
                                    expires_at=now - timedelta(hours=1))                  # expired deny
        cls.contained = make_tech('m-contained')
        grant(cls.contained, cls.a, 'l3')
        Containment.objects.create(user=cls.contained, reason='Unusually broad reads')
        cls.lifted = make_tech('m-lifted')
        grant(cls.lifted, cls.a, 'l2')
        Containment.objects.create(user=cls.lifted, reason='old', lifted_at=now)
        cls.boss = make_tech('m-boss', superuser=True)                                   # no assignment
        cls.portal = User.objects.create_user('m-portal', password='pw')
        Membership.objects.create(user=cls.portal, organization=cls.a, role=Role.OWNER)
        AccessAssignment.objects.create(preset=services.builtin('l3'), organization=cls.a, user=cls.portal)
        cls.inactive = make_tech('m-inactive')
        grant(cls.inactive, cls.a, 'l3')
        cls.inactive.is_active = False
        cls.inactive.save()
        CustomerAccessPolicy.objects.create(organization=cls.b, restricted=['ai_draft', 'review_others'])
        cls.users = [cls.l1, cls.l2, cls.l3, cls.grouped, cls.denied, cls.contained, cls.lifted, cls.boss,
                     cls.portal, cls.inactive]
        cls.tickets = {
            org.pk: [make_ticket(org, assigned_to=cls.l2), make_ticket(org, assigned_to=cls.l3), make_ticket(org)]
            for org in (cls.a, cls.b, cls.c)}
        cls.assets = {org.pk: [Asset.objects.create(organization=org, name=f'{org.slug}-lt', asset_type='laptop'),
                               Asset.objects.create(organization=org, name=f'{org.slug}-dc', asset_type='server')]
                      for org in (cls.a, cls.b, cls.c)}

    def _cases(self):
        caps = list(catalog.OPTIONAL) + list(catalog.LOCKED)[:2] + ['not_a_capability']
        for user in self.users:
            for org in (self.a, self.b, self.c, None):
                for cap in caps:
                    yield user, org, cap, {}
                    if org is None:
                        continue
                    for t in self.tickets[org.pk] + [self.tickets[self.c.pk][0]]:
                        if cap in catalog.TICKET_SCOPED:
                            yield user, org, cap, {'ticket': t}
                    if cap == 'diagnostics_readonly':
                        for a in self.assets[org.pk]:
                            yield user, org, cap, {'asset': a}

    def _decide_all(self):
        out = []
        for user, org, cap, kw in self._cases():
            out.append(_sig(resolver.decide(user, org, cap, **kw)))
            out.append(resolver.has_any_assignment(user, org) if org is not None else None)
        return out

    def test_resolver_matrix_identical(self):
        self.assertFalse(request_cache.active())
        plain = self._decide_all()
        with _Bound():
            self.assertTrue(request_cache.active())
            memo_first = self._decide_all()
            memo_again = self._decide_all()   # served from the memo
        self.assertEqual(memo_first, plain)
        self.assertEqual(memo_again, plain)

    def test_resolver_matrix_identical_with_a_paired_rmm(self):
        """The 'paired' memo (what the customer's RMMs advertise)."""
        with patch('integrations.ticket_rmm.paired_connections', return_value=[object()]), \
                patch('integrations.ticket_rmm.advertised', return_value={'remote_view', 'signed_actions'}):
            plain = self._decide_all()
            with _Bound():
                memo = self._decide_all()
        self.assertEqual(memo, plain)

    def test_decisions_at_another_time_use_that_time(self):
        """Expiry is evaluated per call (`now`), not frozen in the memo."""
        later = timezone.now() + timedelta(hours=2)   # the '*' deny at B has expired by then
        plain = [_sig(resolver.decide(self.denied, self.b, cap, now=later)) for cap in catalog.OPTIONAL]
        with _Bound():
            for cap in catalog.OPTIONAL:
                resolver.decide(self.denied, self.b, cap)          # fills the memo at "now"
            memo = [_sig(resolver.decide(self.denied, self.b, cap, now=later)) for cap in catalog.OPTIONAL]
        self.assertEqual(memo, plain)
        self.assertNotEqual(plain[0][2], 'Explicit deny')

    def test_rmm_permission_and_ai_checks_identical(self):
        from psa_ai.permissions import decision as ai_decision
        from rmm_permissions import can
        from rmm_permissions import catalog as rmm_catalog

        def run():
            out = []
            for user in self.users:
                for org in (self.a, self.b):
                    for action in sorted(rmm_catalog.ACTIONS)[:12]:
                        d = can(user, org, action, ticket=self.tickets[org.pk][0])
                        out.append((d.allowed, d.reason, d.source))
                    for cap in ('view_output', 'analyze', 'send_reply', 'diagnose', 'profile_admin'):
                        out.append(_sig(ai_decision(user, org, cap, ticket=self.tickets[org.pk][1])))
            return out
        plain = run()
        with _Bound():
            memo = run()
        self.assertEqual(memo, plain)

    def test_repeat_checks_in_a_request_read_nothing_again(self):
        with _Bound():
            for cap in catalog.OPTIONAL:                       # first pass reads the rows once
                resolver.decide(self.l2, self.a, cap)
            with CaptureQueriesContext(connection) as ctx:
                for cap in catalog.OPTIONAL:
                    resolver.decide(self.l2, self.a, cap)
        tables = ' '.join(q['sql'] for q in ctx.captured_queries)
        for table in ('tech_access_containments', 'tech_access_denies', 'tech_access_customer_policies',
                      'tech_access_assignments', 'rmm_connections'):
            self.assertNotIn(table, tables)

    def test_no_memo_outside_a_request(self):
        """Jobs, commands and the scheduler read the rows on every call."""
        self.assertFalse(request_cache.active())
        resolver.decide(self.l2, self.a, 'ai_analyze')
        with CaptureQueriesContext(connection) as ctx:
            resolver.decide(self.l2, self.a, 'ai_analyze')
        self.assertTrue(any('tech_access_assignments' in q['sql'] for q in ctx.captured_queries))


class ChangesDuringARequestTests(TestCase):
    """Per-request semantics: what a request changes itself is seen at once;
    what changes elsewhere is seen from the next request."""

    def setUp(self):
        _setup_seed()
        self.a = Organization.objects.create(name='Alpha Dental', slug='alpha')
        self.tech = make_tech('morgan')
        self.assignment = grant(self.tech, self.a, 'l3')

    def allowed(self, cap='ai_analyze'):
        return resolver.decide(self.tech, self.a, cap).allowed

    def test_deny_saved_in_the_request_applies_to_the_next_check(self):
        with _Bound():
            self.assertTrue(self.allowed())
            ExplicitDeny.objects.create(user=self.tech, capability='ai_analyze', organization=self.a)
            self.assertFalse(self.allowed())

    def test_containment_saved_in_the_request_applies_to_the_next_check(self):
        with _Bound():
            self.assertTrue(self.allowed())
            self.assertIsNone(resolver.active_containment(self.tech))
            Containment.objects.create(user=self.tech, reason='drill')
            self.assertFalse(self.allowed())
            self.assertIsNotNone(resolver.active_containment(self.tech))

    def test_revocation_restriction_and_group_removal_apply_to_the_next_check(self):
        with _Bound():
            self.assertTrue(self.allowed('ai_compare'))
            CustomerAccessPolicy.objects.create(organization=self.a, restricted=['ai_compare'])
            self.assertFalse(self.allowed('ai_compare'))
            self.assertTrue(self.allowed('ai_analyze'))
            services.revoke(self.assignment, self.tech)
            self.assertFalse(self.allowed('ai_analyze'))
        group = TechnicianGroup.objects.create(name='Seniors')
        grant(None, self.a, 'l3', group=group)
        group.members.add(self.tech)
        with _Bound():
            self.assertTrue(self.allowed('ai_analyze'))
            group.members.remove(self.tech)
            self.assertFalse(self.allowed('ai_analyze'))

    def test_a_change_that_sends_no_signal_is_seen_by_the_next_request(self):
        """A QuerySet.update() (or another process's commit) mid-request is
        not part of this request's snapshot; the next request reads it.
        Code that updates rule rows with update() inside a request calls
        request_cache.invalidate() (integrations.ticket_rmm._save does)."""
        with _Bound():
            self.assertTrue(self.allowed())
            AccessAssignment.objects.filter(pk=self.assignment.pk).update(revoked_at=timezone.now())
            self.assertTrue(self.allowed())          # this request's snapshot
            request_cache.invalidate()
            self.assertFalse(self.allowed())         # after an explicit invalidate
        AccessAssignment.objects.filter(pk=self.assignment.pk).update(revoked_at=None)
        with _Bound():
            self.assertTrue(self.allowed())
            AccessAssignment.objects.filter(pk=self.assignment.pk).update(revoked_at=timezone.now())
        with _Bound():                               # the next request
            self.assertFalse(self.allowed())
        self.assertFalse(self.allowed())             # and outside any request

    def test_the_memo_is_private_to_its_request(self):
        with _Bound():
            self.assertTrue(self.allowed())
            with _Bound():                           # e.g. another request on a reused thread
                self.assertFalse(any(isinstance(k, tuple) and k and k[0] == request_cache.PREFIX
                                     for k in authz_cache.current_context().memo))
        self.assertFalse(request_cache.active())

    def test_middleware_order_opens_the_context_before_read_tracking(self):
        """ReadTrackingMiddleware's containment check and every view run
        inside CurrentOrganizationMiddleware's context."""
        from django.conf import settings
        mw = list(settings.MIDDLEWARE)
        self.assertLess(mw.index('core.middleware.CurrentOrganizationMiddleware'),
                        mw.index('tech_access.middleware.ReadTrackingMiddleware'))
