"""113.4: no visible form control without a label and no icon-only control
without an accessible name on the shared partials and the worst pages of the
2026-11 UX audit.

To cover another page, add a name to CHECKED_PAGES (a URL name with no
arguments) or to `detail_pages()` below. The checker is core/a11y_lint.py.

Set A11Y_REPORT=/path/out.json to also write the finding count of every
navigation landing page (not an assertion) for docs/ux/UX_AUDIT.md.
"""
import json
import os

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from core.a11y_lint import check_html, summarize
from core.tests.test_page_budgets import PageBudgetBase

# URL names without arguments that must have zero findings.
CHECKED_PAGES = [
    'core:dashboard', 'psa:ticket_list', 'psa:ticket_create', 'assets:asset_create',
    'assets:asset_list', 'security_alerts:alert_list', 'accounts:user_list', 'audit:audit_log_list',
    'monitoring:rack_list', 'psa:change_request_list', 'scheduling:task_list',
]


class CheckerTests(SimpleTestCase):
    """The checker itself."""

    def kinds(self, html):
        return [f['kind'] for f in check_html(html)]

    def test_unlabelled_controls_are_found(self):
        self.assertEqual(self.kinds('<input type="text" name="q"><select></select><textarea></textarea>'),
                         ['unlabelled-control'] * 3)

    def test_labelled_controls_pass(self):
        html = ('<label for="a">A</label><input id="a"><label>B <input></label><input aria-label="C">'
                '<input title="D"><input type="hidden"><input type="submit"><input type="checkbox" '
                'aria-labelledby="x"><div style="display:none"><input></div><template><input></template>'
                '<div aria-hidden="true"><select></select></div>')
        self.assertEqual(check_html(html), [])

    def test_icon_only_controls(self):
        self.assertEqual(self.kinds('<a href="/x"><i class="fa fa-edit"></i></a><button><i></i></button>'),
                         ['unnamed-control'] * 2)
        ok = ('<a href="/x" aria-label="Edit"><i></i></a><button title="Go"><i></i></button>'
              '<a href="/y"><img src="a" alt="Logo"></a><a href="/z"><span class="visually-hidden">Hi</span></a>'
              '<a href="/z">Text</a><a name="anchor"></a>')
        self.assertEqual(check_html(ok), [])


@override_settings(AGIT8OR_CONNECT_ENABLED=True)
class RenderedPagesTests(PageBudgetBase):

    def setUp(self):
        super().setUp()
        self.seed()
        self.login(self.superuser, self.orgs[0])

    def seed(self):
        from accounts.models import Membership
        from audit.models import AuditLog
        from monitoring.models import Rack
        from psa.models import Project, ProjectTask
        org = self.orgs[0]
        self.tickets(3, org=org)
        project = Project.objects.create(organization=org, name='A11y project')
        ProjectTask.objects.create(project=project, title='Task one')
        self.project = project
        Rack.objects.create(organization=org, name='A11y rack')
        for i in range(3):
            AuditLog.objects.create(user=self.superuser, username='budget_su', action='update',
                                    object_type='asset', object_repr=f'Thing {i}', description='x')
        user = self.technician('a11y_tech', orgs=[org])
        Membership.objects.get_or_create(user=user, organization=org, defaults={'role': 'admin'})

    def detail_pages(self):
        return [reverse('psa:project_detail', args=[self.project.pk])]

    def pages(self):
        return [reverse(n) for n in CHECKED_PAGES] + self.detail_pages()

    def test_pages_have_labels_and_names(self):
        problems = {}
        for path in self.pages():
            response = self.client.get(path, follow=True)
            self.assertEqual(response.status_code, 200, path)
            found = check_html(response.content.decode())
            if found:
                problems[path] = found
        self.assertEqual(problems, {}, '\n'.join(f'{p} ({len(f)})\n{summarize(f)}' for p, f in problems.items()))

    def test_report_landing_pages(self):
        out = os.environ.get('A11Y_REPORT')
        if not out:
            self.skipTest('set A11Y_REPORT to write the landing page counts')
        from core.tests.nav_landing_routes import landing_routes
        report = {'landing': {}, 'checked': {}}
        for path in self.pages():
            r = self.client.get(path, follow=True)
            report['checked'][path] = len(check_html(r.content.decode())) if r.status_code == 200 else None
        for name in sorted(landing_routes()):
            try:
                path = reverse(name)
            except Exception:
                continue
            try:
                r = self.client.get(path, follow=True)
            except Exception as exc:  # a page that errors is reported, not fatal
                report['landing'][path] = f'error {type(exc).__name__}'
                continue
            report['landing'][path] = len(check_html(r.content.decode())) if r.status_code == 200 else f'HTTP {r.status_code}'
        with open(out, 'w') as fh:
            json.dump(report, fh, indent=1)
