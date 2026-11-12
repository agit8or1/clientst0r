"""Named approvers per request type and customer (guided service requests)."""
from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings

from portal.tests_guided_requests import TEST_MIDDLEWARE, _Base


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NamedApproverTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from accounts.models import Membership, Role
        cls.item.approval_policy = 'customer'
        cls.item.save()
        # self.approver (org admin, from _Base) is NOT named below.
        cls.dana = User.objects.create_user('gr-dana', 'dana@x.com', 'pw',
                                            first_name='Dana', last_name='Whitfield')
        Membership.objects.create(user=cls.dana, organization=cls.org,
                                  role=Role.READONLY, is_active=True)
        cls.sam = User.objects.create_user('gr-sam', 'sam@x.com', 'pw', first_name='Sam')
        Membership.objects.create(user=cls.sam, organization=cls.org,
                                  role=Role.READONLY, is_active=True)
        cls.outsider = User.objects.create_user('gr-out', 'out@x.com', 'pw', first_name='Priya')
        Membership.objects.create(user=cls.outsider, organization=cls.other,
                                  role=Role.READONLY, is_active=True, is_org_admin=True)

    def name(self, *users, org=None):
        from psa.models import ServiceRequestApprover
        for u in users:
            ServiceRequestApprover.objects.create(
                catalog_item=self.item, organization=org or self.org, user=u)

    def submit(self, user=None):
        from psa.models import PSAApproval, Ticket
        c = self.login(user)
        c.post('/portal/requests/onboard-someone/', {'f_full_name': 'Ann'})
        t = Ticket.objects.filter(organization=self.org).latest('pk')
        return PSAApproval.objects.get(related_ticket=t)

    def decide(self, user, approval, decision='approve'):
        self.login(user).post(f'/portal/approvals/{approval.pk}/decide/',
                              {'decision': decision})
        approval.refresh_from_db()
        return approval.status

    def test_named_approver_can_approve(self):
        self.name(self.dana)
        a = self.submit()
        self.assertEqual(self.decide(self.dana, a), 'approved')
        self.assertEqual(a.decided_by, self.dana)

    def test_admin_not_named_cannot_approve_when_names_set(self):
        from audit.models import AuditLog
        self.name(self.dana)
        a = self.submit()
        self.assertEqual(self.decide(self.approver, a), 'pending')
        self.assertTrue(AuditLog.objects.filter(
            object_type='psa.PSAApproval', object_id=a.pk, success=False,
            user=self.approver).exists())
        # Approval list shows who it's waiting on and no buttons for the admin.
        r = self.login(self.approver).get('/portal/approvals/')
        self.assertContains(r, 'Approver: Dana Whitfield')
        self.assertFalse(r.context['pending'][0].can_decide)

    def test_any_one_of_several_approves(self):
        self.name(self.dana, self.sam)
        a = self.submit()
        self.assertEqual(self.decide(self.sam, a, 'deny'), 'denied')

    def test_no_names_falls_back_to_admins(self):
        a = self.submit()
        self.assertEqual(self.decide(self.dana, a), 'pending')  # plain member
        self.assertEqual(self.decide(self.approver, a), 'approved')

    def test_requester_only_named_approver_falls_back_to_admins(self):
        from psa.service_requests import SOURCE_REQUESTER_ONLY, approvers_for_approval
        self.name(self.user)
        a = self.submit(self.user)
        self.assertEqual(approvers_for_approval(a)['source'], SOURCE_REQUESTER_ONLY)
        self.assertEqual(self.decide(self.user, a), 'pending')
        r = self.login(self.approver).get('/portal/approvals/')
        self.assertContains(r, 'only named approver')
        self.assertEqual(self.decide(self.approver, a), 'approved')

    def test_requester_never_approves_own_even_when_named_with_others(self):
        self.name(self.user, self.dana)
        a = self.submit(self.user)
        self.assertEqual(self.decide(self.user, a), 'pending')
        self.assertEqual(self.decide(self.approver, a), 'pending')
        self.assertEqual(self.decide(self.dana, a), 'approved')

    def test_other_org_user_cannot_approve_even_if_row_forged(self):
        # A row naming another customer's person (bypassing the UI) is ignored.
        self.name(self.outsider)
        a = self.submit()
        r = self.login(self.outsider).post(f'/portal/approvals/{a.pk}/decide/',
                                           {'decision': 'approve'})
        self.assertEqual(r.status_code, 404)
        a.refresh_from_db()
        self.assertEqual(a.status, 'pending')
        # Treated as "no names" → org admins.
        self.assertEqual(self.decide(self.approver, a), 'approved')

    def test_departed_member_ignored(self):
        from accounts.models import Membership
        from psa.service_requests import approvers_for
        self.name(self.dana, self.sam)
        Membership.objects.filter(user=self.dana, organization=self.org).update(is_active=False)
        info = approvers_for(self.item, self.org, self.user)
        self.assertEqual([u.pk for u in info['users']], [self.sam.pk])
        self.assertEqual([r.user_id for r in info['departed']], [self.dana.pk])
        a = self.submit()
        self.assertEqual(self.decide(self.dana, a), 'pending')
        # Everyone named left → back to admins.
        Membership.objects.filter(user=self.sam, organization=self.org).update(is_active=False)
        self.assertEqual(self.decide(self.approver, a), 'approved')

    def test_notifications_go_to_named_approvers(self):
        self.name(self.dana)
        mail.outbox = []
        self.submit()
        self.assertEqual([m.to for m in mail.outbox], [['dana@x.com']])
        self.assertIn('Approval needed', mail.outbox[0].subject)

    def test_notifications_go_to_admins_without_names(self):
        mail.outbox = []
        self.submit()
        self.assertEqual([m.to for m in mail.outbox], [['ap@x.com']])

    def test_no_notification_when_no_approval_needed(self):
        self.item.approval_policy = 'none'
        self.item.save()
        self.name(self.dana)
        mail.outbox = []
        self.login().post('/portal/requests/onboard-someone/', {'f_full_name': 'Ann'})
        self.assertEqual(mail.outbox, [])

    def test_names_are_per_customer(self):
        from accounts.models import Membership, Role
        from psa.service_requests import approvers_for
        priya = User.objects.create_user('gr-priya', 'priya@x.com', 'pw')
        Membership.objects.create(user=priya, organization=self.other,
                                  role=Role.READONLY, is_active=True)
        self.name(self.dana)
        self.name(priya, org=self.other)
        self.assertEqual([u.pk for u in approvers_for(self.item, self.org)['users']], [self.dana.pk])
        self.assertEqual([u.pk for u in approvers_for(self.item, self.other)['users']], [priya.pk])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NamedApproverConfigTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from accounts.models import Membership, Role
        cls.dana = User.objects.create_user('gr-dana', 'dana@x.com', 'pw', first_name='Dana')
        Membership.objects.create(user=cls.dana, organization=cls.org,
                                  role=Role.READONLY, is_active=True)
        cls.outsider = User.objects.create_user('gr-out', 'out@x.com', 'pw')
        Membership.objects.create(user=cls.outsider, organization=cls.other,
                                  role=Role.READONLY, is_active=True)
        from psa.tests._base import _make_msp_tech
        cls.tech = User.objects.create_user('gr-tech', 'tech@x.com', 'pw')
        _make_msp_tech(cls.tech)
        Membership.objects.create(user=cls.tech, organization=cls.org,
                                  role=Role.ADMIN, is_active=True)

    def url(self):
        return f'/psa/catalog/{self.item.pk}/approvers/'

    def test_staff_saves_approvers_and_change_is_audited(self):
        from audit.models import AuditLog
        from psa.models import ServiceRequestApprover
        c = self.login(self.staff)
        r = c.get(self.url() + f'?org={self.org.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Dana')
        self.assertNotContains(r, 'out@x.com')     # other customer's people
        self.assertNotContains(r, 'tech@x.com')    # MSP staff aren't customer people
        r = c.post(self.url(), {'organization_id': self.org.pk,
                                'approver_user_ids': [self.dana.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(list(ServiceRequestApprover.objects.values_list('user_id', flat=True)),
                         [self.dana.pk])
        log = AuditLog.objects.filter(object_type='psa.ServiceCatalogItem',
                                      object_id=self.item.pk, organization=self.org).latest('pk')
        self.assertEqual(log.extra_data['added_user_ids'], [self.dana.pk])
        # Clearing goes back to admins.
        c.post(self.url(), {'organization_id': self.org.pk})
        self.assertFalse(ServiceRequestApprover.objects.exists())
        # Editor links to the page.
        r = c.get(f'/psa/catalog/{self.item.pk}/edit/')
        self.assertContains(r, self.url())

    def test_other_org_user_cannot_be_named(self):
        from psa.models import ServiceRequestApprover
        c = self.login(self.staff)
        for bad in ([self.outsider.pk], [self.dana.pk, self.outsider.pk],
                    [self.tech.pk], ['x']):
            c.post(self.url(), {'organization_id': self.org.pk, 'approver_user_ids': bad})
            self.assertFalse(ServiceRequestApprover.objects.exists(), bad)

    def test_customer_not_offered_item_cannot_be_configured(self):
        from psa.models import ServiceRequestApprover
        self.item.exclude_organizations.set([self.org])
        c = self.login(self.staff)
        c.post(self.url(), {'organization_id': self.org.pk, 'approver_user_ids': [self.dana.pk]})
        self.assertFalse(ServiceRequestApprover.objects.exists())

    def test_staff_only(self):
        from psa.models import ServiceRequestApprover
        for user in (self.user, self.approver, self.dana):
            c = self.login(user)
            # Customer portal users never reach staff pages: they are sent to
            # the portal (core.portal_surface.PortalUserGuardMiddleware).
            for r in (c.get(self.url()),
                      c.post(self.url(), {'organization_id': self.org.pk,
                                          'approver_user_ids': [user.pk]})):
                if r.status_code == 302:
                    self.assertEqual(r['Location'], '/portal/')
                else:
                    self.assertEqual(r.status_code, 404)
        self.assertFalse(ServiceRequestApprover.objects.exists())

    def test_msp_tech_can_configure(self):
        c = self.login(self.tech)
        self.assertEqual(c.get(self.url()).status_code, 200)

    def test_departed_flagged_in_ui(self):
        from accounts.models import Membership
        from psa.models import ServiceRequestApprover
        ServiceRequestApprover.objects.create(catalog_item=self.item, organization=self.org,
                                              user=self.dana)
        Membership.objects.filter(user=self.dana).update(is_active=False)
        r = self.login(self.staff).get(self.url() + f'?org={self.org.pk}')
        self.assertContains(r, 'no longer active people')
