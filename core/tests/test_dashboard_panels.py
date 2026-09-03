"""
Dashboard Schedule + Tasks panels (v3.17.524).

These replaced three panels that showed history (My Recent, Recent Activity) or
sat alone (Expiring Soon). The tests pin the two behaviours that make the change
worth it: expiring things appear as tasks, and the most urgent item sorts first.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.dashboard_panels import (
    EXPIRY_GRACE_DAYS, EXPIRY_WINDOW_DAYS, TaskRow, get_schedule, get_tasks,
)
from core.models import Organization


class TaskRowTests(TestCase):
    def test_overdue_and_days_until(self):
        past = TaskRow(kind='task', title='x', due=timezone.now() - timedelta(days=2))
        soon = TaskRow(kind='task', title='y', due=timezone.now() + timedelta(days=3))
        self.assertTrue(past.is_overdue)
        self.assertFalse(soon.is_overdue)
        self.assertEqual(soon.days_until, 3)

    def test_undated_row_is_never_overdue(self):
        row = TaskRow(kind='task', title='z', due=None)
        self.assertFalse(row.is_overdue)
        self.assertIsNone(row.days_until)


class SchedulePanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SchedCo', slug='sched-co')
        cls.user = User.objects.create_user('sched', 's@x.com', 'pw')

    def _task(self, title, days, status='pending'):
        from scheduling.models import ScheduledTask
        return ScheduledTask.objects.create(
            organization=self.org, title=title, status=status,
            due_date=timezone.now() + timedelta(days=days))

    def test_groups_by_day_and_skips_empty_days(self):
        self._task('Tomorrow A', 1)
        self._task('Tomorrow B', 1)
        self._task('Day five', 5)
        days = get_schedule(self.user, self.org)
        self.assertEqual(len(days), 2, 'empty days must not be returned')
        self.assertEqual(len(days[0].items), 2)

    def test_excludes_completed_and_out_of_window_tasks(self):
        self._task('Done', 1, status='completed')
        self._task('Far future', 30)
        self.assertEqual(get_schedule(self.user, self.org), [])

    def test_window_is_clamped(self):
        self._task('Day ten', 10)
        self.assertEqual(len(get_schedule(self.user, self.org, days=999)), 1)
        self.assertEqual(get_schedule(self.user, self.org, days=1), [])

    def test_other_organisations_are_excluded(self):
        other = Organization.objects.create(name='Other', slug='other-sched')
        from scheduling.models import ScheduledTask
        ScheduledTask.objects.create(
            organization=other, title='Not mine', status='pending',
            due_date=timezone.now() + timedelta(days=1))
        self.assertEqual(get_schedule(self.user, self.org), [])


class TasksPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='TaskCo', slug='task-co')
        cls.user = User.objects.create_user('tasker', 't@x.com', 'pw')

    def test_expiring_password_appears_as_a_task(self):
        """The point of folding Expiring Soon into Tasks."""
        from vault.models import Password
        Password.objects.create(
            organization=self.org, title='Router admin',
            expires_at=timezone.now() + timedelta(days=5))
        rows = get_tasks(None, self.org)
        self.assertEqual([r.kind for r in rows], ['password'])
        self.assertIn('Router admin', rows[0].title)

    def test_expiry_beyond_the_window_is_excluded(self):
        from vault.models import Password
        Password.objects.create(
            organization=self.org, title='Later',
            expires_at=timezone.now() + timedelta(days=EXPIRY_WINDOW_DAYS + 10))
        self.assertEqual(get_tasks(None, self.org), [])

    def test_most_urgent_sorts_first_with_undated_last(self):
        from scheduling.models import ScheduledTask
        from vault.models import Password
        ScheduledTask.objects.create(
            organization=self.org, title='No due date', status='pending')
        ScheduledTask.objects.create(
            organization=self.org, title='Due in 20d', status='pending',
            due_date=timezone.now() + timedelta(days=20))
        Password.objects.create(
            organization=self.org, title='Expires in 2d',
            expires_at=timezone.now() + timedelta(days=2))
        titles = [r.title for r in get_tasks(None, self.org)]
        self.assertIn('Expires in 2d', titles[0])
        self.assertEqual(titles[-1], 'No due date')

    def test_recently_lapsed_expiry_still_shows_as_overdue(self):
        from vault.models import Password
        Password.objects.create(
            organization=self.org, title='Lapsed last week',
            expires_at=timezone.now() - timedelta(days=7))
        rows = get_tasks(None, self.org)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].is_overdue)

    def test_long_expired_item_does_not_pin_the_panel(self):
        """Rows sort earliest-first, so an ancient expiry would sit on top forever."""
        from vault.models import Password
        Password.objects.create(
            organization=self.org, title='Lapsed in another era',
            expires_at=timezone.now() - timedelta(days=EXPIRY_GRACE_DAYS + 5))
        self.assertEqual(get_tasks(None, self.org), [])

    def test_soonest_expiry_wins_when_there_are_more_than_the_slice(self):
        """Ordering must happen before the slice, not after.

        Password's default ordering is by `title` and WebsiteMonitor's by
        `name`, so an unordered `qs[:10]` took the alphabetically-first ten and
        silently dropped the urgent ones. 'zz-urgent' sorts last by title but
        expires first, so it only appears if the query orders by expiry.
        """
        from vault.models import Password
        for i in range(12):
            Password.objects.create(
                organization=self.org, title=f'aa-filler-{i:02d}',
                expires_at=timezone.now() + timedelta(days=20))
        Password.objects.create(
            organization=self.org, title='zz-urgent',
            expires_at=timezone.now() + timedelta(hours=6))
        titles = [r.title for r in get_tasks(None, self.org)]
        self.assertIn('zz-urgent', titles[0])

    def test_undated_tasks_do_not_crowd_out_dated_ones(self):
        """SQLite sorts NULLs first ascending, so undated tasks filled the slice."""
        from scheduling.models import ScheduledTask
        for i in range(30):
            ScheduledTask.objects.create(
                organization=self.org, title=f'Undated {i:02d}', status='pending')
        ScheduledTask.objects.create(
            organization=self.org, title='Due tomorrow', status='pending',
            due_date=timezone.now() + timedelta(days=1))
        titles = [r.title for r in get_tasks(None, self.org)]
        self.assertEqual(titles[0], 'Due tomorrow')

    def test_assigned_filter_returns_only_my_tasks(self):
        from scheduling.models import ScheduledTask
        mine = ScheduledTask.objects.create(
            organization=self.org, title='Mine', status='pending',
            due_date=timezone.now() + timedelta(days=1))
        mine.assigned_to.add(self.user)
        ScheduledTask.objects.create(
            organization=self.org, title='Someone else', status='pending',
            due_date=timezone.now() + timedelta(days=1))
        titles = [r.title for r in get_tasks(self.user, self.org)]
        self.assertEqual(titles, ['Mine'])

    def test_a_missing_field_would_not_be_swallowed(self):
        """Regression guard: a broad `except Exception` here once hid an
        AttributeError (Password.name vs .title) and the panel just looked
        empty. The data-fetching paths may catch ImportError/LookupError only
        — an optional app being absent is fine, a coding error is not.

        `panel_url` is the one exception: catching NoReverseMatch is the whole
        point of that helper, so it gets NoReverseMatch and nothing else. The
        allowance is scoped to that function rather than added to the global
        list, or the next hand-written `except NoReverseMatch` around a query
        would sail through.

        Checked by parsing the AST rather than grepping the source — a string
        search matches this module's own prose explaining the rule, which is
        exactly how it first failed.
        """
        import ast
        import inspect
        from core import dashboard_panels

        base = {'ImportError', 'LookupError'}
        per_function = {'panel_url': base | {'NoReverseMatch'}}

        tree = ast.parse(inspect.getsource(dashboard_panels))
        offenders = []
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            allowed = per_function.get(func.name, base)
            for node in ast.walk(func):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                caught = node.type
                if caught is None:                       # bare `except:`
                    offenders.append(f'line {node.lineno}: bare except')
                    continue
                names = ([e.id for e in caught.elts if isinstance(e, ast.Name)]
                         if isinstance(caught, ast.Tuple)
                         else ([caught.id] if isinstance(caught, ast.Name) else []))
                too_broad = [n for n in names if n not in allowed]
                if too_broad:
                    offenders.append(
                        f'line {node.lineno} (in {func.name}): '
                        f'catches {", ".join(too_broad)}')
        self.assertEqual(
            offenders, [],
            'dashboard_panels may only catch ImportError/LookupError '
            '(plus NoReverseMatch inside panel_url):\n  '
            + '\n  '.join(offenders))

class PanelUrlTests(TestCase):
    """Every link a panel emits must resolve.

    The first cut of this module hand-wrote five paths and three were wrong:
    tickets are at /psa/t/<pk>/ not /psa/tickets/<pk>/, expirations live under
    monitoring not core, and bare /monitoring/ has no route at all. Nothing
    caught it because a dead href renders exactly like a live one.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='UrlCo', slug='url-co')
        cls.user = User.objects.create_user('urls', 'u@x.com', 'pw')

    def _assert_resolves(self, url, label):
        from django.urls import Resolver404, resolve
        self.assertTrue(url, f'{label} produced an empty url')
        try:
            resolve(url)
        except Resolver404:
            self.fail(f'{label} produced an unroutable url: {url}')

    def test_schedule_item_urls_resolve(self):
        from scheduling.models import ScheduledTask
        ScheduledTask.objects.create(
            organization=self.org, title='Onsite', status='pending',
            due_date=timezone.now() + timedelta(days=1))
        items = [i for day in get_schedule(self.user, self.org) for i in day.items]
        self.assertTrue(items)
        for item in items:
            self._assert_resolves(item['url'], f"schedule {item['kind']}")

    def test_task_row_urls_resolve(self):
        from monitoring.models import Expiration, WebsiteMonitor
        from scheduling.models import ScheduledTask
        from vault.models import Password
        soon = timezone.now() + timedelta(days=3)
        ScheduledTask.objects.create(
            organization=self.org, title='Task', status='pending', due_date=soon)
        Password.objects.create(
            organization=self.org, title='Secret', expires_at=soon)
        Expiration.objects.create(
            organization=self.org, name='Domain', expires_at=soon)
        WebsiteMonitor.objects.create(
            organization=self.org, name='Site', url='https://example.com',
            ssl_expires_at=soon)

        rows = get_tasks(None, self.org)
        kinds = {r.kind for r in rows}
        self.assertEqual(kinds, {'task', 'password', 'expiration', 'ssl'},
                         'all four row kinds should be exercised')
        for row in rows:
            self._assert_resolves(row.url, f'task row {row.kind}')

    def test_panel_url_returns_empty_for_an_unknown_route(self):
        from core.dashboard_panels import panel_url
        self.assertEqual(panel_url('nope:does_not_exist', 1), '')


_TEST_MIDDLEWARE = [
    m for m in settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DashboardRenderTests(TestCase):
    """End-to-end render of the page the panels live on.

    v3.17.524 deleted three panels and, with them, the `recent_logs`,
    `activity_feed` and three `expiring_*` context keys plus the five queries
    behind them. There was no test rendering this view at all, so a template
    still referencing a dropped key would only have surfaced in production.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='RenderCo', slug='render-co')
        cls.user = User.objects.create_superuser('renderer', 'r@x.com', 'pw')

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_renders_with_both_panels(self):
        from scheduling.models import ScheduledTask
        from vault.models import Password
        ScheduledTask.objects.create(
            organization=self.org, title='Swap the firewall', status='pending',
            due_date=timezone.now() + timedelta(days=2))
        Password.objects.create(
            organization=self.org, title='Core switch',
            expires_at=timezone.now() + timedelta(days=4))

        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Schedule (next 7 days)', body)
        self.assertIn('Swap the firewall', body)
        self.assertIn('Core switch', body)

    def test_removed_panels_are_gone(self):
        response = self.client.get(reverse('core:dashboard'))
        body = response.content.decode()
        for gone in ('My Recent', 'Recent Activity', 'Expiring Soon'):
            self.assertNotIn(gone, body, f'{gone} panel should have been removed')
        for gone_key in ('recent_logs', 'activity_feed', 'expiring_passwords',
                         'expiring_items', 'expiring_ssl'):
            self.assertNotIn(gone_key, response.context,
                             f'{gone_key} is dead context — nothing reads it')

    def test_empty_state_renders(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Nothing scheduled in the next 7 days', body)
        self.assertIn('Nothing outstanding', body)
