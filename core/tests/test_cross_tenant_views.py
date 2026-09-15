"""Cross-tenant access tests for permission-gated views.

Companion to `test_tenant_isolation.py`, which covers model-level and API
isolation. This file covers a narrower, different failure: a view that gates on
a *capability* and then looks a record up by primary key alone.

`accounts.permission_utils.user_has_perm` answers "does this user hold the flag
on any active membership". That is the right question for "may they manage
holidays at all" and the wrong one for "may they manage *this* holiday". Where
a view asked only the first question, a member of one tenant could reach
another tenant's row by id.

Each test here failed before the corresponding fix; see the v3.17.559 commit.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization

User = get_user_model()

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CrossTenantAccessTests(TestCase):
    """One member of org A, one record in org B, for each flagged view."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='Tenant A', slug='tenant-a')
        cls.org_b = Organization.objects.create(name='Tenant B', slug='tenant-b')

        # A technician in org A only, holding every permission the views below
        # gate on — so any failure is a tenancy failure, not a permission one.
        cls.tpl = RoleTemplate.objects.create(
            organization=cls.org_a, name='Tech (all flags under test)',
        )
        for flag in ('reports_manage_dashboards', 'resourcing_manage_holidays'):
            if hasattr(cls.tpl, flag):
                setattr(cls.tpl, flag, True)
        cls.tpl.save()

        cls.user = User.objects.create_user('tech_a', 'tech_a@example.com', 'pw-not-secret')
        Membership.objects.create(user=cls.user, organization=cls.org_a,
                                  role=Role.ADMIN, role_template=cls.tpl, is_active=True)

        # Org B's records belong to org B's own technician. Without this, a
        # view that authorises on ownership would accept the request for the
        # right reason and the test would prove nothing about tenancy.
        cls.other = User.objects.create_user('tech_b', 'tech_b@example.com', 'pw-not-secret')
        Membership.objects.create(user=cls.other, organization=cls.org_b,
                                  role=Role.ADMIN, is_active=True)

    def setUp(self):
        self.client.force_login(self.user)

    def _assert_denied(self, response, what):
        """The request must not have been served.

        302 counts: several views in this codebase deny by redirecting with an
        error message rather than raising, and that is a legitimate pattern —
        `reports.saved_query_delete` does exactly this when `can_edit()` says
        no. What must never appear is 200, which would mean the view rendered
        another tenant's record.

        Status alone is weak evidence, so every test that can also asserts the
        underlying state: the row still exists, the status is unchanged, or the
        sensitive string is absent from the body.
        """
        self.assertIn(
            response.status_code, (302, 403, 404),
            f'{what}: org A member was served an org B record '
            f'(HTTP {response.status_code}); expected a redirect, 403 or 404',
        )

    # -- reports ---------------------------------------------------------
    def test_cannot_delete_another_orgs_saved_query(self):
        from reports.models import SavedQuery
        sq = SavedQuery.objects.create(
            organization=self.org_b, name='B private query', owner=self.other,
            target_model='assets.Asset', filters={}, columns=['name'], is_shared=True,
        )
        resp = self.client.post(reverse('reports:saved_query_delete', args=[sq.pk]))
        self._assert_denied(resp, 'saved_query_delete')
        self.assertTrue(
            SavedQuery.objects.filter(pk=sq.pk).exists(),
            'saved_query_delete: org B saved query was deleted by an org A member',
        )

    def test_cannot_add_widget_to_another_orgs_dashboard(self):
        from reports.models import Dashboard
        dash = Dashboard.objects.create(
            organization=self.org_b, name='B dashboard', created_by=self.other,
        )
        resp = self.client.get(reverse('reports:dashboard_widget_add', args=[dash.pk]))
        self._assert_denied(resp, 'dashboard_widget_add')

    # -- resourcing ------------------------------------------------------
    def test_cannot_edit_another_orgs_holiday(self):
        from datetime import date
        from resourcing.models import Holiday
        hol = Holiday.objects.create(
            organization=self.org_b, name='B company holiday', date=date(2026, 12, 25),
        )
        resp = self.client.get(reverse('resourcing:holiday_edit', args=[hol.pk]))
        self._assert_denied(resp, 'holiday_edit')
        if resp.status_code == 200:
            self.assertNotContains(resp, 'B company holiday')

    # -- psa_ai ----------------------------------------------------------
    def test_cannot_read_another_orgs_ai_suggestion(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        from psa_ai.models import AISuggestion
        sug = AISuggestion.objects.create(
            organization=self.org_b, kind='reply', model_name='test-model',
            suggested_body='B confidential draft',
        )
        resp = self.client.get(reverse('psa_ai:suggestion_detail', args=[sug.pk]))
        self._assert_denied(resp, 'suggestion_detail')
        if resp.status_code == 200:
            self.assertNotContains(resp, 'B confidential draft')

    def test_cannot_delete_another_orgs_holiday(self):
        from datetime import date
        from resourcing.models import Holiday
        hol = Holiday.objects.create(
            organization=self.org_b, name='B holiday', date=date(2026, 12, 26),
        )
        resp = self.client.post(reverse('resourcing:holiday_delete', args=[hol.pk]))
        self._assert_denied(resp, 'holiday_delete')
        self.assertTrue(
            Holiday.objects.filter(pk=hol.pk).exists(),
            'holiday_delete: org B holiday was deleted by an org A member',
        )

    def test_holiday_list_hides_other_orgs(self):
        """The list view leaked every tenant's holidays to every user."""
        from datetime import date
        from resourcing.models import Holiday
        Holiday.objects.create(organization=self.org_a, name='A day off',
                               date=date(2026, 5, 4))
        Holiday.objects.create(organization=self.org_b, name='B SECRET day off',
                               date=date(2026, 5, 5))
        resp = self.client.get(reverse('resourcing:holiday_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'A day off')
        self.assertNotContains(
            resp, 'B SECRET day off',
            msg_prefix='holiday_list leaked another tenant\'s holiday',
        )

    def test_holiday_list_still_shows_shared_national_holidays(self):
        """A NULL organization means "every tenant" — those must stay visible."""
        from datetime import date
        from resourcing.models import Holiday
        Holiday.objects.create(organization=None, name='New Year shared',
                               date=date(2027, 1, 1))
        resp = self.client.get(reverse('resourcing:holiday_list'))
        self.assertContains(resp, 'New Year shared')

    def test_cannot_edit_a_shared_national_holiday(self):
        """Editing a NULL-org holiday changes it for every tenant."""
        from datetime import date
        from resourcing.models import Holiday
        hol = Holiday.objects.create(organization=None, name='Shared day',
                                     date=date(2027, 7, 4))
        resp = self.client.get(reverse('resourcing:holiday_edit', args=[hol.pk]))
        self._assert_denied(resp, 'holiday_edit (shared national holiday)')

    def test_cannot_create_a_holiday_inside_another_org(self):
        """The form's organization select listed every tenant."""
        from datetime import date
        from resourcing.models import Holiday
        resp = self.client.post(reverse('resourcing:holiday_add'), {
            'organization': self.org_b.pk,
            'name': 'Planted in B', 'date': '2026-11-11',
            'is_recurring_yearly': '', 'notes': '',
        })
        self.assertFalse(
            Holiday.objects.filter(organization=self.org_b, name='Planted in B').exists(),
            'holiday_add: created a holiday inside an organization the user is not in',
        )

    # -- psa workflow suggestions (AI-derived, cross-tenant read) ---------
    def _enable_psa_ai(self):
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.psa_ai_enabled = True
        ss.save()

    def test_workflow_suggestion_list_hides_other_orgs(self):
        """The list rendered every tenant's AI suggestions to any signed-in user."""
        self._enable_psa_ai()
        from psa.models import WorkflowSuggestion
        WorkflowSuggestion.objects.create(
            organization=self.org_a, summary='A pattern', rationale='A rationale',
            suggested_payload={}, status='pending',
        )
        WorkflowSuggestion.objects.create(
            organization=self.org_b, summary='B SECRET pattern',
            rationale='B confidential rationale', suggested_payload={}, status='pending',
        )
        resp = self.client.get(reverse('psa:workflow_suggestion_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'A pattern')
        self.assertNotContains(
            resp, 'B SECRET pattern',
            msg_prefix="workflow_suggestion_list leaked another tenant's AI suggestion",
        )

    def test_cannot_decide_another_orgs_workflow_suggestion(self):
        self._enable_psa_ai()
        from psa.models import WorkflowSuggestion
        sug = WorkflowSuggestion.objects.create(
            organization=self.org_b, summary='B pattern', rationale='B rationale',
            suggested_payload={}, status='pending',
        )
        resp = self.client.post(
            reverse('psa:workflow_suggestion_decide', args=[sug.pk]), {'action': 'dismiss'})
        self._assert_denied(resp, 'workflow_suggestion_decide')
        sug.refresh_from_db()
        self.assertEqual(
            sug.status, 'pending',
            'workflow_suggestion_decide: an org A member changed org B\'s suggestion',
        )

