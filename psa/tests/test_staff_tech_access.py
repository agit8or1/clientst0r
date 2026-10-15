"""
Staff-type MSP techs are first-class: assignable on any customer's ticket
without a membership, and their global role's capabilities apply to
membership-checked permissions.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Membership, Role, RoleTemplate
from accounts.permission_utils import user_has_perm
from core.models import Organization
from psa.tests._base import _make_msp_tech
from psa.views import _eligible_assignees


class StaffTechAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.cust = Organization.objects.create(name='Staff Co', slug='staff-co')
        cls.tech = _make_msp_tech(User.objects.create_user('st_tech', 't@msp.test', 'pw-st-123'))
        cls.member = User.objects.create_user('st_member', 'm@c.test', 'pw-st-123')
        Membership.objects.create(user=cls.member, organization=cls.cust,
                                  role=Role.EDITOR, is_active=True)
        cls.outsider = User.objects.create_user('st_out', 'o@c.test', 'pw-st-123')

    def test_staff_tech_assignable_without_membership(self):
        ids = set(_eligible_assignees(self.cust).values_list('id', flat=True))
        self.assertIn(self.tech.id, ids)
        self.assertIn(self.member.id, ids)
        self.assertNotIn(self.outsider.id, ids)

    def test_global_role_grants_membership_checked_permission(self):
        self.assertFalse(user_has_perm(self.tech, 'change_approve_cab'))
        role = RoleTemplate.objects.create(name='Tech global', change_approve_cab=True)
        self.tech.profile.global_role_template = role
        self.tech.profile.save()
        self.assertTrue(user_has_perm(self.tech, 'change_approve_cab'))

    def test_global_role_never_removes_membership_grant(self):
        # A tech whose global role lacks a flag still has what a membership gives.
        role = RoleTemplate.objects.create(name='Tech narrow', change_approve_cab=False)
        self.tech.profile.global_role_template = role
        self.tech.profile.save()
        cab = RoleTemplate.objects.create(name='CAB', organization=self.cust,
                                          change_approve_cab=True)
        Membership.objects.create(user=self.tech, organization=self.cust,
                                  role=Role.EDITOR, role_template=cab, is_active=True)
        self.assertTrue(user_has_perm(self.tech, 'change_approve_cab'))

    def test_customer_user_unaffected(self):
        self.assertFalse(user_has_perm(self.outsider, 'change_approve_cab'))
