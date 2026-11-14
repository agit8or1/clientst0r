"""
The ticket workspace (psa/ticket_workspace.py): the ?view= tabs of the ticket
list — Overview, Unassigned, SLA, Escalated, Approvals — plus the AI Inbox tab
and the dispatch board's unassigned → assignment path.

Pins: who gets each tab (MSP technician vs customer, PSA off, AI off), that
every view stays inside the user's ticket scope, the SLA buckets against
fixed deadlines, the unassigned filters, that approve / deny and the
assignment control only appear where the existing endpoints would accept
them (and those endpoints still refuse otherwise), and that deep links render
the right tab.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from accounts.models import Membership, Role
from core import navigation
from core.models import Organization, SystemSetting
from psa.models import (
    PSAApproval, Queue, Ticket, TicketPriority, TicketStatus, TicketType,
)
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed,
)

LIST = reverse('psa:ticket_list')


def _set_due(ticket, *, resolution=None, first_response=None, responded=None):
    Ticket.objects.filter(pk=ticket.pk).update(
        resolution_due_at=resolution, first_response_due_at=first_response,
        first_response_at=responded)
    ticket.refresh_from_db()
    return ticket


class _Fixture:
    @classmethod
    def _build(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Alpha Co', slug='alpha-tw')
        cls.org_b = Organization.objects.create(name='Bravo Co', slug='bravo-tw')
        cls.tech = cls._tech('tw_tech', Role.OWNER)
        cls.other_tech = cls._tech('tw_other', Role.OWNER)
        cls.ro_tech = cls._tech('tw_ro_tech', Role.READONLY)
        cls.customer = User.objects.create_user('tw_cust', 'c@alpha.test', 'pw')
        Membership.objects.create(user=cls.customer, organization=cls.org,
                                  role=Role.EDITOR, is_active=True)
        cls.prio_hi = TicketPriority.objects.order_by('sort_order').first()
        cls.prio_lo = TicketPriority.objects.order_by('sort_order').last()
        cls.types = list(TicketType.objects.order_by('sort_order')[:2])

    @classmethod
    def _tech(cls, name, role):
        u = _make_msp_tech(User.objects.create_user(name, f'{name}@msp.test', 'pw'))
        Membership.objects.create(user=u, organization=cls.org, role=role, is_active=True)
        return u

    @classmethod
    def _ticket(cls, subject, org=None, *, status='new', assignee=None, shared=True,
                prio=None, ttype=None, **kw):
        return Ticket.objects.create(
            organization=org or cls.org, subject=subject, client_can_view=shared,
            queue=Queue.objects.first(), priority=prio or cls.prio_lo,
            ticket_type=ttype or cls.types[0],
            status=TicketStatus.objects.get(slug=status), assigned_to=assignee, **kw)

    def _client(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = (org or self.org).id
        s['2fa_prompted'] = True
        s.save()
        return c


def _ctx(user, query='', ai=False, **extra):
    request = RequestFactory().get(LIST + query)
    request.resolver_match = resolve(LIST)
    request.user = user
    ctx = {'request': request, 'user': user, 'is_staff_user': False, 'psa_enabled': True,
           'system_settings': SimpleNamespace(psa_ai_enabled=ai)}
    ctx.update(extra)
    return ctx


def _labels(tabs):
    return [str(t['label']) for t in tabs]


# ---------------------------------------------------------------------------
# Tabs: gating, URL state, overflow
# ---------------------------------------------------------------------------

class TabNavigationTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()

    def test_technician_gets_the_workspace_tabs(self):
        st = navigation.nav_state(_ctx(self.tech))
        self.assertEqual(_labels(st['tabs']), [
            'All Tickets', 'Overview', 'My Queue', 'Unassigned', 'SLA', 'Escalated', 'Approvals'])

    def test_customer_keeps_the_plain_strip(self):
        st = navigation.nav_state(_ctx(self.customer, ai=True))
        for label in ('Overview', 'Unassigned', 'SLA', 'Escalated', 'Approvals', 'AI Inbox'):
            self.assertNotIn(label, _labels(st['tabs']))

    def test_ai_inbox_needs_optional_ai_and_a_technician(self):
        self.assertNotIn('AI Inbox', _labels(navigation.nav_state(_ctx(self.tech))['tabs']))
        on = navigation.nav_state(_ctx(self.tech, ai=True))
        self.assertIn('AI Inbox', _labels(on['tabs']))

    def test_psa_off_hides_the_strip(self):
        st = navigation.nav_state(_ctx(self.tech, psa_enabled=False))
        self.assertEqual(st['tabs'], [])

    def test_tabs_overflow_into_more_without_wrapping(self):
        st = navigation.nav_state(_ctx(self.tech, ai=True))
        self.assertEqual(len(st['tabs_visible']), navigation.STRIP_TABS)
        self.assertEqual(_labels(st['tabs_more']), ['Approvals', 'AI Inbox'])
        # The current view is never hidden in More.
        st = navigation.nav_state(_ctx(self.tech, '?view=approvals', ai=True))
        self.assertIn('Approvals', _labels(st['tabs_visible']))
        self.assertTrue(next(t for t in st['tabs_visible'] if t['label'] == 'Approvals')['active'])

    def test_exactly_one_tab_is_current(self):
        for query, label in (('', 'All Tickets'), ('?view=sla', 'SLA'),
                             ('?view=unassigned&priority=1', 'Unassigned'),
                             ('?view=bogus', 'All Tickets'), ('?assigned=me', 'All Tickets')):
            active = [str(t['label']) for t in navigation.nav_state(_ctx(self.tech, query))['tabs']
                      if t['active']]
            self.assertEqual(active, [label], query)

    def test_tab_hrefs_keep_existing_urls(self):
        hrefs = {str(t['label']): t['href'] for t in navigation.nav_state(_ctx(self.tech))['tabs']}
        self.assertEqual(hrefs['All Tickets'], LIST)
        self.assertEqual(hrefs['SLA'], LIST + '?view=sla')
        self.assertEqual(hrefs['My Queue'], reverse('psa:my_work'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DeepLinkTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()

    def test_each_view_renders_its_own_tab_as_current(self):
        c = self._client(self.tech)
        for view, label in (('overview', 'Overview'), ('unassigned', 'Unassigned'),
                            ('sla', 'SLA'), ('escalated', 'Escalated'), ('approvals', 'Approvals')):
            r = c.get(LIST, {'view': view})
            self.assertEqual(r.status_code, 200, view)
            self.assertEqual(r.context['view'], view)
            self.assertRegex(r.content.decode(),
                             r'class="nav-link active" href="%s\?view=%s"[^>]*aria-current="page"'
                             % (LIST, view))

    def test_plain_list_is_unchanged_for_bookmarks(self):
        r = self._client(self.tech).get(LIST, {'assigned': 'me', 'queue': 'open'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['view'], '')
        self.assertRegex(r.content.decode(), r'class="nav-link active" href="%s"' % LIST)

    def test_bad_parameters_are_ignored(self):
        r = self._client(self.tech).get(LIST, {
            'view': '<script>', 'sla': 'nope', 'age': '9y', 'sort': 'x', 'type': 'abc',
            'status': 'abc', 'priority': '1 OR 1', 'client': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['view'], '')
        self.assertNotContains(r, '<script>')

    def test_filters_keep_the_view(self):
        r = self._client(self.tech).get(LIST, {'view': 'unassigned'})
        self.assertContains(r, '<input type="hidden" name="view" value="unassigned">', html=True)

    def test_psa_off_404s_every_view(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        c = self._client(self.tech)
        for view in ('', 'overview', 'sla', 'approvals'):
            self.assertEqual(c.get(LIST, {'view': view}).status_code, 404)


# ---------------------------------------------------------------------------
# Scoping: customer vs technician, customer A vs B
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ScopingTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()
        cls.a_shared = cls._ticket('TW alpha shared')
        cls.a_internal = cls._ticket('TW alpha internal', shared=False)
        cls.b_ticket = cls._ticket('TW bravo ticket', org=cls.org_b)
        now = timezone.now()
        for t in (cls.a_shared, cls.a_internal, cls.b_ticket):
            _set_due(t, resolution=now - timedelta(hours=1))
            Ticket.objects.filter(pk=t.pk).update(escalated_at=now, escalation_reason='Down')

    def test_customer_views_fall_back_to_their_own_list(self):
        c = self._client(self.customer)
        for view in ('overview', 'unassigned', 'sla', 'escalated', 'approvals'):
            r = c.get(LIST, {'view': view})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.context['view'], '', view)
            subjects = {t.subject for t in r.context['tickets']}
            self.assertEqual(subjects, {'TW alpha shared'}, view)

    def test_customer_cannot_widen_with_client_or_sla(self):
        c = self._client(self.customer)
        r = c.get(LIST, {'client': self.org_b.pk})
        self.assertEqual(list(r.context['tickets']), [])
        r = c.get(LIST, {'sla': 'breached'})
        self.assertEqual({t.subject for t in r.context['tickets']}, {'TW alpha shared'})
        self.assertNotContains(r, 'TW alpha internal')
        self.assertNotContains(r, 'TW bravo')

    def test_overview_counts_follow_the_client_filter(self):
        c = self._client(self.tech)
        r = c.get(LIST, {'view': 'overview', 'client': self.org.pk})
        tiles = {t['key']: t['count'] for t in r.context['overview']['tiles']}
        self.assertEqual(tiles['open'], 2)
        self.assertEqual(tiles['breached'], 2)
        self.assertEqual(tiles['escalated'], 2)
        self.assertIn(f'client={self.org.pk}', r.context['overview']['tiles'][0]['href'])
        r = c.get(LIST, {'view': 'overview'})
        self.assertEqual({t['key']: t['count'] for t in r.context['overview']['tiles']}['open'], 3)

    def test_overview_counts_equal_the_lists_they_open(self):
        c = self._client(self.tech)
        r = c.get(LIST, {'view': 'overview'})
        for tile in r.context['overview']['tiles']:
            if tile['key'] == 'approvals':
                continue
            listed = c.get(tile['href'])
            n = len(listed.context['tickets'])
            self.assertEqual(n, tile['count'], tile['key'])


# ---------------------------------------------------------------------------
# SLA buckets against fixed deadlines
# ---------------------------------------------------------------------------

class SlaBucketTests(_Fixture, TestCase):
    NOW = datetime(2026, 11, 14, 12, 0, tzinfo=dt_timezone.utc)

    @classmethod
    def setUpTestData(cls):
        cls._build()
        n = cls.NOW
        cls.breached = _set_due(cls._ticket('B'), resolution=n - timedelta(minutes=1))
        cls.edge_now = _set_due(cls._ticket('Edge now'), resolution=n)
        cls.at_risk = _set_due(cls._ticket('R'), resolution=n + timedelta(hours=1))
        cls.edge_soon = _set_due(cls._ticket('Edge soon'), resolution=n + timedelta(hours=2))
        cls.on_track = _set_due(cls._ticket('T'), resolution=n + timedelta(hours=2, minutes=1))
        cls.no_sla = _set_due(cls._ticket('N'))
        cls.paused = _set_due(cls._ticket('P', status='waiting-on-client'),
                              resolution=n - timedelta(hours=3))
        # First response is the deadline that counts until one is sent.
        cls.fr_late = _set_due(cls._ticket('FR late'), first_response=n - timedelta(minutes=5),
                               resolution=n + timedelta(days=2))
        cls.fr_done = _set_due(cls._ticket('FR done'), first_response=n - timedelta(minutes=5),
                               resolution=n + timedelta(days=2), responded=n - timedelta(hours=1))

    def _bucket(self, key):
        from psa.my_work import annotate_activity, sla_bucket_qs
        qs = annotate_activity(Ticket.objects.filter(organization=self.org))
        return set(qs.filter(sla_bucket_qs('sla_due_at', self.NOW)[key])
                   .values_list('subject', flat=True))

    def test_buckets(self):
        self.assertEqual(self._bucket('breached'), {'B', 'FR late'})
        self.assertEqual(self._bucket('at_risk'), {'Edge now', 'R', 'Edge soon'})
        self.assertEqual(self._bucket('on_track'), {'T', 'FR done'})
        self.assertEqual(self._bucket('paused'), {'P'})
        self.assertEqual(self._bucket('no_sla'), {'N'})

    def test_every_ticket_is_in_exactly_one_bucket(self):
        from psa.my_work import SLA_BUCKETS
        seen = []
        for key in SLA_BUCKETS:
            seen += list(self._bucket(key))
        self.assertEqual(sorted(seen), sorted(Ticket.objects.filter(organization=self.org)
                                              .values_list('subject', flat=True)))

    def test_row_labels_match_the_filter(self):
        from psa.my_work import SLA_BUCKETS, annotate_activity, sla_bucket_of
        qs = annotate_activity(Ticket.objects.filter(organization=self.org)).select_related('status')
        for key in SLA_BUCKETS:
            for subject in self._bucket(key):
                self.assertEqual(sla_bucket_of(qs.get(subject=subject), self.NOW), key, subject)

    def test_time_remaining_never_invented(self):
        from psa.my_work import annotate_activity
        from psa.ticket_workspace import decorate_sla
        rows = decorate_sla(list(annotate_activity(Ticket.objects.filter(organization=self.org))
                                 .select_related('status')), now=self.NOW)
        by = {t.subject: t for t in rows}
        self.assertEqual(by['N'].sla_left, '')
        self.assertEqual(by['N'].sla_bucket_label, 'No SLA')
        self.assertEqual(by['R'].sla_left, '1h 00m left')
        self.assertEqual(by['B'].sla_left, '1m overdue')
        self.assertEqual(by['FR late'].sla_which, 'First response')
        self.assertEqual(by['FR done'].sla_which, 'Resolution')

    def test_dashboard_sla_counts_use_the_same_buckets(self):
        from unittest import mock
        from core import dashboard_widgets as dw
        req = RequestFactory().get('/')
        req.user = User.objects.create_superuser('tw_root', 'r@x.test', 'pw')
        with mock.patch('core.dashboard_widgets.timezone.now', return_value=self.NOW), \
                mock.patch('django.utils.timezone.now', return_value=self.NOW), \
                mock.patch.object(dw, 'visible_tickets',
                                  lambda request, org: Ticket.objects.filter(organization=org)):
            c = dw.sla_counts(req, self.org)
        self.assertEqual((c['overdue'], c['at_risk'], c['on_track'], c['paused'], c['no_sla']),
                         (2, 3, 2, 1, 1))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SlaViewTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()
        now = timezone.now()
        _set_due(cls._ticket('SV late', assignee=cls.tech), resolution=now - timedelta(hours=1))
        _set_due(cls._ticket('SV soon'), resolution=now + timedelta(minutes=30))
        _set_due(cls._ticket('SV later'), resolution=now + timedelta(days=1))
        cls._ticket('SV none')
        _set_due(cls._ticket('SV closed late', status='closed'), resolution=now - timedelta(hours=1))

    def test_bucket_filter_and_chip_counts(self):
        c = self._client(self.tech)
        r = c.get(LIST, {'view': 'sla', 'sla': 'breached'})
        self.assertEqual([t.subject for t in r.context['tickets']], ['SV late'])
        self.assertEqual(r.context['sla_counts']['breached'], 1)
        self.assertEqual(r.context['sla_counts']['at_risk'], 1)
        self.assertEqual(r.context['sla_counts']['no_sla'], 1)
        r = c.get(LIST, {'view': 'sla'})
        subjects = [t.subject for t in r.context['tickets']]
        self.assertNotIn('SV closed late', subjects)
        self.assertEqual(subjects[:3], ['SV late', 'SV soon', 'SV later'])
        self.assertContains(r, 'No SLA')

    def test_sla_param_works_on_all_tickets(self):
        r = self._client(self.tech).get(LIST, {'sla': 'at_risk'})
        self.assertEqual([t.subject for t in r.context['tickets']], ['SV soon'])


# ---------------------------------------------------------------------------
# Unassigned: filters, sort, assignment control
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UnassignedTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()
        now = timezone.now()
        cls.u_old = cls._ticket('UA old', prio=cls.prio_hi)
        Ticket.objects.filter(pk=cls.u_old.pk).update(created_at=now - timedelta(days=10))
        cls.u_new = cls._ticket('UA new', ttype=cls.types[-1])
        cls.u_late = _set_due(cls._ticket('UA late'), resolution=now - timedelta(hours=2))
        cls.u_b = cls._ticket('UA bravo', org=cls.org_b)
        cls._ticket('UA mine', assignee=cls.tech)
        cls._ticket('UA closed', status='closed')

    def _subjects(self, user=None, **params):
        r = self._client(user or self.tech).get(LIST, {'view': 'unassigned', **params})
        self.assertEqual(r.status_code, 200)
        return r, {t.subject for t in r.context['tickets']}

    def test_open_unassigned_only(self):
        _, s = self._subjects()
        self.assertEqual(s, {'UA old', 'UA new', 'UA late', 'UA bravo'})

    def test_filters(self):
        self.assertEqual(self._subjects(client=self.org_b.pk)[1], {'UA bravo'})
        self.assertEqual(self._subjects(priority=self.prio_hi.pk)[1], {'UA old'})
        if self.types[0] != self.types[-1]:
            self.assertEqual(self._subjects(type=self.types[-1].pk)[1], {'UA new'})
        self.assertEqual(self._subjects(age='7d')[1], {'UA old'})
        self.assertEqual(self._subjects(sla='breached')[1], {'UA late'})
        self.assertEqual(self._subjects(status=TicketStatus.objects.get(slug='closed').pk)[1], set())
        # assigned= can't turn the Unassigned view into someone's queue.
        self.assertNotIn('UA mine', self._subjects(assigned='me')[1])

    def test_sorts(self):
        r, _ = self._subjects(sort='age')
        self.assertEqual(r.context['tickets'][0].subject, 'UA old')
        r, _ = self._subjects()  # default: soonest deadline first
        self.assertEqual(r.context['tickets'][0].subject, 'UA late')

    def test_picker_only_where_dispatch_assign_would_accept(self):
        from psa.views import _can_assign
        r, _ = self._subjects()
        rows = {t.subject: t for t in r.context['tickets']}
        req = r.wsgi_request
        # In scope = the selected customer (dispatch_assign filters by it).
        self.assertTrue(_can_assign(req, self.org))
        self.assertTrue(rows['UA old'].can_assign)
        self.assertFalse(rows['UA bravo'].can_assign)
        # Outside the selected customer: "Assign to me" through the ticket's
        # quick action instead (dispatch_assign would 404 it).
        self.assertTrue(rows['UA bravo'].can_take)
        self.assertContains(r, 'data-assign-form')
        self.assertContains(r, reverse('psa:dispatch_assign'))

    def test_read_only_technician_gets_no_controls(self):
        r, _ = self._subjects(user=self.ro_tech)
        self.assertFalse(any(t.can_assign or t.can_take for t in r.context['tickets']))
        self.assertNotContains(r, 'data-assign-form')
        self.assertNotContains(r, 'value="assign_me"')

    def test_assigning_from_the_list_uses_the_endpoint(self):
        c = self._client(self.tech)
        r = c.post(reverse('psa:dispatch_assign'),
                   {'ticket_number': self.u_new.ticket_number, 'assignee': self.other_tech.pk})
        self.assertEqual(r.status_code, 200, r.content)
        self.u_new.refresh_from_db()
        self.assertEqual(self.u_new.assigned_to, self.other_tech)
        _, s = self._subjects()
        self.assertNotIn('UA new', s)

    def test_endpoint_still_refuses_customers_and_other_scopes(self):
        r = self._client(self.customer).post(
            reverse('psa:dispatch_assign'),
            {'ticket_number': self.u_old.ticket_number, 'assignee': self.customer.pk})
        self.assertIn(r.status_code, (403, 404))
        r = self._client(self.tech).post(
            reverse('psa:dispatch_assign'),
            {'ticket_number': self.u_b.ticket_number, 'assignee': self.tech.pk})
        self.assertEqual(r.status_code, 404)  # outside the selected customer
        self.u_old.refresh_from_db()
        self.assertIsNone(self.u_old.assigned_to)


# ---------------------------------------------------------------------------
# Escalated
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EscalatedTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()
        now = timezone.now()
        for subject, status, when in (('ES open', 'new', now),
                                      ('ES older', 'in-progress', now - timedelta(days=1)),
                                      ('ES closed', 'closed', now)):
            t = cls._ticket(subject, status=status)
            Ticket.objects.filter(pk=t.pk).update(escalated_at=when, escalated_by=cls.customer,
                                                  escalation_reason='<b>Still broken</b>')
        cls._ticket('ES calm')

    def test_open_escalated_newest_first(self):
        r = self._client(self.tech).get(LIST, {'view': 'escalated'})
        self.assertEqual([t.subject for t in r.context['tickets']], ['ES open', 'ES older'])
        self.assertContains(r, '&lt;b&gt;Still broken&lt;/b&gt;')
        self.assertNotContains(r, '<b>Still broken</b>')


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ApprovalsTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()
        cls.t = cls._ticket('AP ticket')
        cls.t_b = cls._ticket('AP bravo', org=cls.org_b)

        def approval(ticket, by, **kw):
            return PSAApproval.objects.create(
                organization=ticket.organization, kind=kw.pop('kind', 'expense'),
                object_type='psa.Ticket', object_id=ticket.pk, object_repr=kw.pop('repr', 'Spend'),
                requested_by=by, related_ticket=ticket, **kw)

        cls.ap_other = approval(cls.t, cls.other_tech, repr='Other asked')
        cls.ap_mine = approval(cls.t, cls.tech, repr='I asked')
        cls.ap_client = approval(cls.t, cls.other_tech, repr='Client signs', is_client_approval=True)
        cls.ap_b = approval(cls.t_b, cls.other_tech, repr='Bravo spend')
        cls.ap_done = approval(cls.t, cls.other_tech, repr='Done one', status='approved')
        PSAApproval.objects.create(organization=cls.org, kind='other', object_type='x.Y',
                                   object_id=1, object_repr='No ticket', requested_by=cls.other_tech)

    def _rows(self, user):
        r = self._client(user).get(LIST, {'view': 'approvals'})
        self.assertEqual(r.status_code, 200)
        return r, {row['title']: row for row in r.context.get('approval_rows') or []}

    def test_pending_ticket_approvals_of_the_selected_customer(self):
        _, rows = self._rows(self.tech)
        self.assertEqual(set(rows), {'Other asked', 'I asked', 'Client signs'})

    def test_buttons_only_where_decide_would_accept(self):
        r, rows = self._rows(self.tech)
        self.assertTrue(rows['Other asked']['can_decide'])
        self.assertFalse(rows['I asked']['can_decide'])
        self.assertFalse(rows['Client signs']['can_decide'])
        html = r.content.decode()
        self.assertIn(reverse('psa:approval_decide', args=[self.ap_other.pk]), html)
        self.assertNotIn(reverse('psa:approval_decide', args=[self.ap_mine.pk]), html)
        self.assertNotIn(reverse('psa:approval_decide', args=[self.ap_client.pk]), html)
        self.assertIn('csrfmiddlewaretoken', html)

    def test_read_only_technician_sees_but_cannot_decide(self):
        r, rows = self._rows(self.ro_tech)
        self.assertTrue(rows)
        self.assertFalse(any(row['can_decide'] for row in rows.values()))
        self.assertNotContains(r, 'value="approve"')
        resp = self._client(self.ro_tech).post(
            reverse('psa:approval_decide', args=[self.ap_other.pk]), {'decision': 'approve'})
        self.assertEqual(resp.status_code, 403)
        self.ap_other.refresh_from_db()
        self.assertEqual(self.ap_other.status, 'pending')

    def test_customer_gets_no_approvals_and_decide_refuses(self):
        r, rows = self._rows(self.customer)
        self.assertEqual(rows, {})
        self.assertEqual(r.context['view'], '')
        resp = self._client(self.customer).post(
            reverse('psa:approval_decide', args=[self.ap_other.pk]), {'decision': 'approve'})
        self.assertIn(resp.status_code, (403, 404))
        self.ap_other.refresh_from_db()
        self.assertEqual(self.ap_other.status, 'pending')

    def test_decide_still_refuses_self_approval(self):
        self._client(self.tech).post(
            reverse('psa:approval_decide', args=[self.ap_mine.pk]), {'decision': 'approve'})
        self.ap_mine.refresh_from_db()
        self.assertEqual(self.ap_mine.status, 'pending')

    def test_authorized_decision_goes_through(self):
        self._client(self.tech).post(
            reverse('psa:approval_decide', args=[self.ap_other.pk]), {'decision': 'approve'})
        self.ap_other.refresh_from_db()
        self.assertEqual(self.ap_other.status, 'approved')

    def test_overview_counts_pending_ticket_approvals(self):
        r = self._client(self.tech).get(LIST, {'view': 'overview'})
        tiles = {t['key']: t['count'] for t in r.context['overview']['tiles']}
        self.assertEqual(tiles['approvals'], 3)


# ---------------------------------------------------------------------------
# Dispatch board → unassigned → assignment (workflow C)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchBoardUnassignedTests(_Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()
        cls.u = cls._ticket('DB unassigned')
        cls._ticket('DB closed', status='closed')
        cls._ticket('DB mine', assignee=cls.tech)

    def test_board_links_to_unassigned_with_count(self):
        r = self._client(self.tech).get(reverse('psa:dispatch_board'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['unassigned_open_count'], 1)
        self.assertContains(r, f'{LIST}?view=unassigned&amp;client={self.org.pk}')

    def test_unassigned_cards_carry_the_picker(self):
        from psa.views import _can_assign
        r = self._client(self.tech).get(reverse('psa:dispatch_board'))
        self.assertTrue(_can_assign(r.wsgi_request, self.org))
        self.assertContains(r, 'data-assign-form')
        self.assertContains(r, f'id="assign-{self.u.pk}-db"')
        r = self._client(self.ro_tech).get(reverse('psa:dispatch_board'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'data-assign-form')
