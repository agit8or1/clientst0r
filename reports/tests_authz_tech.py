"""Roles & permissions program (authz-tech): a scheduled report runs on its
creator's authority, so the creator is rechecked at run time. A schedule
whose creator was deactivated, is no longer MSP staff, or lost
reports_manage_scheduled for the customer is paused instead of run."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from psa.tests._base import _make_msp_tech
from reports.models import GeneratedReport, ReportTemplate, ScheduledReport


class ScheduledReportCreatorRecheckTests(TestCase):
    def _schedule(self, creator):
        org = Organization.objects.create(name=f'Sched {User.objects.count()}',
                                          slug=f'authz-sched-{User.objects.count()}')
        template = ReportTemplate.objects.create(
            name='Authz sched', report_type='organization_metrics',
            query_template='', is_global=True, created_by=creator)
        return ScheduledReport.objects.create(
            name='authz nightly', template=template, organization=org,
            frequency='daily', delivery_method='email', recipients=[], output_format='csv',
            is_active=True, created_by=creator, next_run=timezone.now() - timedelta(hours=1))

    def test_active_staff_creator_runs(self):
        tech = _make_msp_tech(User.objects.create_user('authz-sched-tech', password='pw'))
        s = self._schedule(tech)
        call_command('run_scheduled_reports', verbosity=0)
        s.refresh_from_db()
        self.assertTrue(s.is_active)
        self.assertEqual(GeneratedReport.objects.filter(scheduled_report=s).count(), 1)

    def test_deactivated_creator_pauses_schedule(self):
        tech = _make_msp_tech(User.objects.create_user('authz-sched-gone', password='pw'))
        s = self._schedule(tech)
        tech.is_active = False
        tech.save()
        call_command('run_scheduled_reports', verbosity=0)
        s.refresh_from_db()
        self.assertFalse(s.is_active)
        self.assertEqual(GeneratedReport.objects.filter(scheduled_report=s).count(), 0)

    def test_creator_no_longer_staff_pauses_schedule(self):
        user = User.objects.create_user('authz-sched-customer', password='pw')
        s = self._schedule(user)
        call_command('run_scheduled_reports', verbosity=0)
        s.refresh_from_db()
        self.assertFalse(s.is_active)
