"""Page cost budgets: how many queries the busiest pages may run.

Each page has a ceiling (measured count plus a little headroom) for a
superuser and for an MSP technician, so a new feature that adds a query per
row, per membership or per widget fails here instead of quietly slowing every
page load. A ceiling that is now too low after a deliberate addition is
raised in the same change, with the reason.

The scaling tests are the stronger guard: the ticket list, the ticket page and
a technician's pages must run the same number of queries whatever the number
of rows (tickets, time entries, charges) or customer memberships.

The rendered-HTML cache for the sidebar sections and the settings workspace
(core.nav_cache.group_html / settings_menu_html) is checked against a render
with the cache off, cold and warm, for every kind of user.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, RoleTemplate
from core import nav_cache
from core.models import Organization
from core.tests.test_navbar_grouping import ALL_FLAGS, TEST_MIDDLEWARE

User = get_user_model()

# Ceilings per page: (superuser, MSP technician). Measured on v3.17.754 +
# the second performance pass, with a few queries of headroom.
BUDGETS = {
    'psa:ticket_list': (31, 36),
    'core:dashboard': (31, 37),
    'assets:asset_list': (29, 33),
    'docs:document_list': (24, 28),
    'integrations:integration_list': (35, 39),
    'psa:ticket_detail': (96, 100),
    'psa:billing_review': (26, None),
    'connect:index': (27, None),
    'vault:password_list': (19, 24),
    'core:settings_home': (19, 22),
}


def _count(client, path):
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(path)
    return response, len(ctx.captured_queries)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AGIT8OR_CONNECT_ENABLED=True)
class PageBudgetBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        from core.models import SystemSetting
        from psa.tests._base import _enable_psa_for, _setup_seed
        row = SystemSetting.get_settings()
        for flag in ALL_FLAGS:
            setattr(row, flag, True)
        row.save()
        _setup_seed()
        cls.orgs = [Organization.objects.create(name=f'Budget Co {i}', slug=f'budget-co-{i}') for i in range(6)]
        # A child customer, so the descendant walk has something to find.
        Organization.objects.create(name='Budget Child', slug='budget-child', parent=cls.orgs[0])
        for org in cls.orgs:
            _enable_psa_for(org)
        cls.superuser = User.objects.create_user('budget_su', 'su@x.com', 'pw', is_staff=True, is_superuser=True)

    def setUp(self):
        nav_cache.clear()
        nav_cache.clear_html()

    # -- fixtures ----------------------------------------------------------

    def tickets(self, n, org=None, *, assigned=None):
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        priorities = list(TicketPriority.objects.order_by('sort_order'))
        out = []
        for i in range(n):
            out.append(Ticket.objects.create(
                organization=org or self.orgs[i % len(self.orgs)], subject=f'Budget ticket {i}',
                queue=Queue.objects.first(), priority=priorities[i % len(priorities)],
                ticket_type=TicketType.objects.first(), status=TicketStatus.objects.first(),
                assigned_to=assigned))
        return out

    def work(self, ticket, n):
        """`n` time entries, account charges and comments on `ticket`."""
        from psa.models import Charge, TicketComment, TicketTimeEntry
        # All on one work day (agreements are read once per customer and day).
        start = (timezone.localtime() - timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        for i in range(n):
            TicketTimeEntry.objects.create(
                ticket=ticket, user=self.superuser, started_at=start + timedelta(minutes=20 * i),
                ended_at=start + timedelta(minutes=20 * i + 15), duration_minutes=15, is_billable=True)
            Charge.objects.create(organization=ticket.organization, client_org=ticket.organization,
                                  description=f'Part {i}', amount=Decimal('10.00'),
                                  charge_date=timezone.localdate(), ticket=ticket)
            TicketComment.objects.create(ticket=ticket, author=self.superuser, body=f'Note {i}')

    def technician(self, username='budget_tech', orgs=None):
        from psa.tests._base import _make_msp_tech
        user = _make_msp_tech(User.objects.create_user(username, f'{username}@x.com', 'pw'))
        for org in (self.orgs if orgs is None else orgs):
            Membership.objects.create(user=user, organization=org, role='admin')
        return user

    def login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        if org is not None:
            self.client.get(reverse('accounts:switch_organization', args=[org.id]))

    def path(self, name, ticket=None):
        if name == 'psa:ticket_detail':
            return reverse(name, args=[ticket.ticket_number])
        return reverse(name)

    def warm_count(self, path):
        """Queries of a repeat visit (the first one also fills per-process
        caches and records the recent page)."""
        self.client.get(path)
        response, n = _count(self.client, path)
        return response, n


class PageQueryBudgetTests(PageBudgetBase):

    def check_budgets(self, user, column, org=None):
        tickets = self.tickets(4, org=org)
        self.work(tickets[0], 2)
        self.login(user, org)
        for name, ceilings in BUDGETS.items():
            ceiling = ceilings[column]
            if ceiling is None:
                continue
            path = self.path(name, tickets[0])
            with self.subTest(page=name):
                response, n = self.warm_count(path)
                self.assertEqual(response.status_code, 200, (name, path))
                self.assertLessEqual(n, ceiling, f'{name} ran {n} queries (budget {ceiling})')

    def test_superuser_pages_stay_within_budget(self):
        self.check_budgets(self.superuser, 0)

    def test_technician_pages_stay_within_budget(self):
        self.check_budgets(self.technician(), 1, org=self.orgs[0])


class QueriesDoNotGrowWithRowsTests(PageBudgetBase):
    """A query per row (per ticket, time entry, charge or membership) shows
    as a count that grows with the data."""

    def test_ticket_list_is_independent_of_ticket_count(self):
        self.login(self.superuser)
        path = reverse('psa:ticket_list')
        self.tickets(3)
        _r, few = self.warm_count(path)
        self.tickets(12)
        _r, many = self.warm_count(path)
        self.assertEqual(few, many)

    def test_unassigned_view_is_independent_of_ticket_count(self):
        tech = self.technician()
        self.login(tech, self.orgs[0])
        path = reverse('psa:ticket_list') + '?view=unassigned'
        self.tickets(2, org=self.orgs[0])
        _r, few = self.warm_count(path)
        self.tickets(8, org=self.orgs[0])
        _r, many = self.warm_count(path)
        self.assertEqual(few, many)

    def test_ticket_page_is_independent_of_time_entries_and_charges(self):
        ticket = self.tickets(1)[0]
        self.work(ticket, 1)
        self.login(self.superuser)
        path = reverse('psa:ticket_detail', args=[ticket.ticket_number])
        _r, few = self.warm_count(path)
        self.work(ticket, 5)
        _r, many = self.warm_count(path)
        self.assertEqual(few, many)

    def test_technician_pages_are_independent_of_membership_count(self):
        """The permission checks behind every page used to walk the customer
        tree once per membership."""
        few_user = self.technician('budget_few', orgs=self.orgs[:2])
        many_user = self.technician('budget_many', orgs=self.orgs)
        for name in ('core:settings_home', 'core:dashboard', 'vault:password_list', 'integrations:integration_list'):
            with self.subTest(page=name):
                self.login(few_user, self.orgs[0])
                _r, few = self.warm_count(reverse(name))
                self.login(many_user, self.orgs[0])
                _r, many = self.warm_count(reverse(name))
                self.assertEqual(few, many)


def _frame(html):
    head = html.split('id="main-content"', 1)[0]
    ws = re.search(r'<nav class="settings-ws"[^>]*>.*?</nav>', html, re.S)
    out = head + (ws.group(0) if ws else '')
    out = re.sub(r'nonce="[^"]*"', 'nonce=""', out)
    out = re.sub(r'(data-csrf|value|content)="[A-Za-z0-9]{32,}"', r'\1=""', out)
    return out


class RenderedNavigationCacheTests(PageBudgetBase):
    """The kept sidebar sections and settings workspace draw exactly what the
    templates draw."""

    PAGES = ('core:dashboard', 'psa:ticket_list', 'vault:password_list', 'core:settings_home',
             'integrations:integration_list', 'connect:index', 'psa:billing_review', 'accounts:profile')

    def customer(self):
        u = User.objects.create_user('budget_cust', 'bc@x.com', 'pw')
        Membership.objects.create(
            user=u, organization=self.orgs[0], role='readonly',
            role_template=RoleTemplate.objects.get(seed_key='customer_user', organization__isnull=True))
        return u

    def test_cached_html_matches_a_fresh_render(self):
        users = {'superuser': self.superuser, 'tech': self.technician(), 'customer': self.customer()}
        for role, user in users.items():
            self.login(user, self.orgs[0])
            for name in self.PAGES:
                path = reverse(name)
                with override_settings(NAV_HTML_CACHE=False):
                    r = self.client.get(path, follow=True)
                if r.status_code != 200:
                    continue  # a page this user may not open
                expected = _frame(r.content.decode())
                cold = _frame(self.client.get(path, follow=True).content.decode())
                warm = _frame(self.client.get(path, follow=True).content.decode())
                with self.subTest(role=role, page=name):
                    self.assertIn('id="appNav"', warm)
                    self.assertEqual(cold, expected)
                    self.assertEqual(warm, expected)
        self.assertTrue(nav_cache._html_store, 'sections are kept')

    def test_settings_workspace_is_kept_and_identical(self):
        self.login(self.superuser)
        path = reverse('integrations:integration_list')
        with override_settings(NAV_HTML_CACHE=False):
            expected = _frame(self.client.get(path).content.decode())
        self.assertIn('id="settingsWorkspace"', expected)
        self.client.get(path)
        self.assertTrue(any(k[0] == 'settings_menu' for k in nav_cache._html_store))
        self.assertEqual(_frame(self.client.get(path).content.decode()), expected)

    def test_active_page_and_language_are_part_of_the_key(self):
        """Moving between pages of one section changes its active link."""
        self.login(self.superuser)
        for name in ('vault:password_list', 'core:dashboard', 'vault:password_list'):
            path = reverse(name)
            html = self.client.get(path).content.decode()
            current = re.findall(r'class="app-nav__link active" href="([^"]+)"', html)
            with self.subTest(page=name):
                self.assertTrue(current)
                self.assertTrue(all(path.startswith(h) or h == path for h in current), current)

    def test_template_fields_are_all_in_the_key(self):
        """A field the templates read but the key leaves out would let one
        render's HTML stand in for a different one."""
        from django.template.loader import get_template

        def fields(template, var):
            src = get_template(template).template.source
            return set(re.findall(r'\b%s\.([a-z_]+)' % var, src))

        group = 'core/_primary_nav_group.html'
        self.assertLessEqual(fields(group, 'g') - {'entries'}, set(nav_cache.GROUP_FIELDS))
        self.assertLessEqual(fields(group, 'e'), set(nav_cache.ENTRY_FIELDS))
        self.assertLessEqual(fields(group, 'c'), set(nav_cache.CHILD_FIELDS))
        self.assertLessEqual(fields(group, 'pnav'), {'pin_edit'})
        self.assertLessEqual(fields(group, 'request'), {'path', 'get_full_path'})
        menu = 'core/_settings_menu.html'
        self.assertLessEqual(fields(menu, 'c') | fields(menu, 'cur'), set(nav_cache.CATEGORY_FIELDS))
        self.assertLessEqual(fields(menu, 't'), set(nav_cache.TAB_FIELDS))
        self.assertLessEqual(fields(menu, 'ws'), {'categories'})
        self.assertLessEqual(fields(menu, 'pnav'), {'workspace'})

    def test_store_is_bounded(self):
        for i in range(nav_cache.HTML_MAX_ENTRIES + 10):
            nav_cache._cached_html(('t', i), lambda: 'x')
        self.assertEqual(len(nav_cache._html_store), nav_cache.HTML_MAX_ENTRIES)


class RequestMemoTests(PageBudgetBase):
    """The per-request memos behind the fixes return what the uncached code
    returns, and a save inside the request is seen."""

    def bound(self):
        from django.test import RequestFactory

        from accounts import authz_cache
        request = RequestFactory().get('/')
        request.user = self.superuser
        token = authz_cache.bind_request(request)
        self.addCleanup(authz_cache.unbind, token)
        return request

    def test_descendants_match_the_database_walk(self):
        from core.utils import descendant_org_ids
        child = Organization.objects.get(slug='budget-child')
        grandchild = Organization.objects.create(name='Budget Grandchild', slug='budget-gc', parent=child)
        outside = {o.pk: descendant_org_ids(o) for o in Organization.objects.all()}
        self.assertEqual(outside[self.orgs[0].pk], {self.orgs[0].pk, child.pk, grandchild.pk})
        self.bound()
        with CaptureQueriesContext(connection) as ctx:
            inside = {o_pk: descendant_org_ids(o_pk) for o_pk in outside}
        self.assertEqual(inside, outside)
        self.assertEqual(len(ctx.captured_queries), 1)
        # A new child saved in the request is seen by the next check.
        late = Organization.objects.create(name='Budget Late', slug='budget-late', parent=self.orgs[1])
        self.assertEqual(descendant_org_ids(self.orgs[1]), {self.orgs[1].pk, late.pk})

    def test_priority_order_follows_a_save(self):
        from psa.models import TicketPriority
        from psa.templatetags.psa_ui import priority_tone
        self.bound()
        first, second = list(TicketPriority.objects.order_by('sort_order', 'id'))[:2]
        self.assertEqual(priority_tone(first), 'danger')
        with self.assertNumQueries(0):
            self.assertEqual(priority_tone(second), 'warn')
        first.sort_order = TicketPriority.objects.order_by('-sort_order').first().sort_order + 1
        first.save()
        self.assertEqual(priority_tone(second), 'danger')
        self.assertEqual(priority_tone(first), 'neutral')

    def test_membership_lookup_returns_a_private_copy(self):
        from core.decorators import get_user_membership
        tech = self.technician('budget_copy', orgs=self.orgs[:2])
        request = self.bound()
        request.user = tech
        request.session = {'current_organization_id': self.orgs[0].pk}
        m = get_user_membership(request)
        self.assertEqual((m.user_id, m.organization_id), (tech.pk, self.orgs[0].pk))
        m.role = 'changed'
        self.assertNotEqual(get_user_membership(request).role, 'changed')
        self.assertEqual(get_user_membership(request, self.orgs[1].pk).organization_id, self.orgs[1].pk)
        self.assertIsNone(get_user_membership(request, self.orgs[4].pk))
