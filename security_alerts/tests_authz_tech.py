"""Roles & permissions program (authz-tech): security alerts.

Action flags (acknowledge, manage connections, create rules) are checked in
the record's own customer; a flag held at one customer no longer applies to
every customer the user can view. Digest subscribers tied to a user account
are rechecked at send time.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from security_alerts.digest import recipient_still_eligible
from security_alerts.models import SecurityAlert, SecurityDigestSubscription, SecurityVendorConnection


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AlertActionScopeTests(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='Sec A', slug='authz-sec-a')
        self.b = Organization.objects.create(name='Sec B', slug='authz-sec-b')
        viewer = RoleTemplate.objects.create(name='authz sec viewer', security_alerts_view=True,
                                             security_alerts_acknowledge=False)
        acker = RoleTemplate.objects.create(name='authz sec acker', security_alerts_view=True,
                                            security_alerts_acknowledge=True)
        # MSP tech whose global role views every customer but does not
        # acknowledge; an Editor membership at A carries acknowledge. The
        # global role decides for staff, so the membership flag no longer
        # leaks into every customer the role can view.
        self.tech = _make_msp_tech(User.objects.create_user('authz-sec-tech', password='pw'))
        self.tech.profile.global_role_template = viewer
        self.tech.profile.save()
        Membership.objects.create(user=self.tech, organization=self.a, role=Role.EDITOR, role_template=acker)
        self.alert_a = self._alert(self.a, 'a-1')
        self.alert_b = self._alert(self.b, 'b-1')
        self.c = Client()
        self.c.force_login(self.tech)
        s = self.c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.a.id
        s.save()

    def _alert(self, org, ext):
        conn = SecurityVendorConnection.objects.create(organization=org, name=f'c-{ext}',
                                                       provider='defender', category='edr')
        return SecurityAlert.objects.create(connection=conn, organization=org, external_id=ext,
                                            severity='high', title=f'alert {ext}')

    def test_membership_flag_does_not_leak_into_other_customers(self):
        url_b = reverse('security_alerts:alert_decide', args=[self.alert_b.pk])
        self.assertEqual(self.c.post(url_b, {'decision': 'dismiss'}).status_code, 404)
        self.alert_b.refresh_from_db()
        self.assertNotEqual(self.alert_b.status, 'dismissed')

    def test_global_role_with_acknowledge_still_acts(self):
        self.tech.profile.global_role_template = RoleTemplate.objects.create(
            name='authz sec global acker', security_alerts_view=True, security_alerts_acknowledge=True)
        self.tech.profile.save()
        self.c.post(reverse('security_alerts:alert_decide', args=[self.alert_b.pk]), {'decision': 'dismiss'})
        self.alert_b.refresh_from_db()
        self.assertEqual(self.alert_b.status, 'dismissed')

    def test_bulk_skips_other_customers(self):
        self.c.post(reverse('security_alerts:alert_bulk_decide'),
                    {'decision': 'resolve', 'alert_ids': [self.alert_a.pk, self.alert_b.pk]})
        self.alert_b.refresh_from_db()
        self.assertNotEqual(self.alert_b.status, 'resolved')

    def test_still_views_every_customer(self):
        resp = self.c.get(reverse('security_alerts:alert_detail', args=[self.alert_b.pk]))
        self.assertEqual(resp.status_code, 200)


class DigestRecipientRecheckTests(TestCase):
    def test_deactivated_or_removed_user_gets_no_digest(self):
        org = Organization.objects.create(name='Digest org', slug='authz-digest')
        user = User.objects.create_user('authz-digest-user', password='pw')
        m = Membership.objects.create(user=user, organization=org, role=Role.READONLY)
        sub = SecurityDigestSubscription.objects.create(organization=org, email='u@example.test', user=user)
        self.assertTrue(recipient_still_eligible(sub))
        m.is_active = False
        m.save()
        self.assertFalse(recipient_still_eligible(sub))
        m.is_active = True
        m.save()
        user.is_active = False
        user.save()
        sub.refresh_from_db()
        self.assertFalse(recipient_still_eligible(sub))

    def test_contact_only_subscription_unchanged(self):
        org = Organization.objects.create(name='Digest org 2', slug='authz-digest-2')
        sub = SecurityDigestSubscription.objects.create(organization=org, email='office@example.test')
        self.assertTrue(recipient_still_eligible(sub))
