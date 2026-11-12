"""Server-side authorization regressions for scheduling (roles/permissions
program): the global wallboard is MSP-staff only; creating tasks needs write."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE
from scheduling.models import ScheduledTask, SchedulerWallboard


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SchedulingAuthzTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.cust = Organization.objects.create(name='S Cust', slug='authz-sched-cust')
        cls.owner = User.objects.create_user('sched-owner', 'o@c.test', 'pw')
        Membership.objects.create(user=cls.owner, organization=cls.cust, role=Role.OWNER)
        cls.ro = User.objects.create_user('sched-ro', 'r@c.test', 'pw')
        Membership.objects.create(user=cls.ro, organization=cls.cust, role=Role.READONLY)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.cust.pk
        s.save()
        return c

    def test_customer_owner_cannot_open_or_enable_wallboard(self):
        c = self._client(self.owner)
        self.assertEqual(c.get(reverse('scheduling:wallboard_settings')).status_code, 403)
        r = c.post(reverse('scheduling:wallboard_settings'), {'is_enabled': 'on'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(SchedulerWallboard.objects.filter(is_enabled=True).exists())

    def test_superuser_still_manages_wallboard(self):
        su = User.objects.create_superuser('sched-su', 's@x.test', 'pw')
        c = Client()
        c.force_login(su)
        self.assertEqual(c.get(reverse('scheduling:wallboard_settings')).status_code, 200)

    def test_read_only_member_cannot_create_task(self):
        r = self._client(self.ro).post(reverse('scheduling:task_create'), {
            'title': 'RO task', 'priority': 'medium', 'recurrence': 'none'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ScheduledTask.objects.filter(title='RO task').exists())
