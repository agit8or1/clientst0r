"""Roles & permissions program (authz-tech): /media/ rules for report files
and document attachments follow the owning record."""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Membership, Role, RoleTemplate
from core.media_views import _generated_report
from core.models import Organization
from psa.tests._base import _make_msp_tech
from reports.models import GeneratedReport, ReportTemplate


class GeneratedReportMediaRuleTests(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='Media A', slug='authz-media-a')
        self.b = Organization.objects.create(name='Media B', slug='authz-media-b')
        template = ReportTemplate.objects.create(name='m', report_type='organization_metrics',
                                                 query_template='', is_global=True)
        self.report_b = GeneratedReport.objects.create(template=template, organization=self.b)

    def test_customer_user_never_gets_report_files(self):
        user = User.objects.create_user('authz-media-cust', password='pw')
        Membership.objects.create(user=user, organization=self.b, role=Role.OWNER)
        self.assertFalse(_generated_report(user, self.report_b))

    def test_flag_is_checked_in_the_reports_customer(self):
        tech = _make_msp_tech(User.objects.create_user('authz-media-tech', password='pw'))
        tech.profile.global_role_template = None
        tech.profile.save()
        yes = RoleTemplate.objects.create(name='authz media rep', reports_view_dashboards=True)
        no = RoleTemplate.objects.create(name='authz media norep', reports_view_dashboards=False)
        Membership.objects.create(user=tech, organization=self.a, role=Role.EDITOR, role_template=yes)
        m = Membership.objects.create(user=tech, organization=self.b, role=Role.EDITOR, role_template=no)
        # Staff without a global role hold non-vault flags everywhere, so
        # use a global role that lacks the flag to prove the per-org check.
        tech.profile.global_role_template = no
        tech.profile.save()
        self.assertFalse(_generated_report(tech, self.report_b))
        tech.profile.global_role_template = yes
        tech.profile.save()
        self.assertTrue(_generated_report(tech, self.report_b))
        m.delete()
        tech = User.objects.get(pk=tech.pk)  # membership ids are cached per request
        self.assertFalse(_generated_report(tech, self.report_b))
