"""The webhook list needs the same admin role as create / edit / delete.

The list shows each webhook's URL, and a chat service's URL carries its
token, so an Editor, a Read-only member or a customer user must not see it.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership
from core.models import Organization, Webhook

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebhookListAccessTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Hook Co', slug='hook-co')
        Webhook.objects.create(organization=self.org, name='Chat',
                               url='https://hooks.example.test/services/SECRET-TOKEN')

    def member(self, role):
        u = get_user_model().objects.create_user(f'hook_{role}', f'{role}@x.com', 'pw')
        Membership.objects.create(user=u, organization=self.org, role=role)
        self.client.force_login(u)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))
        return u

    def test_editor_is_refused(self):
        self.member('editor')
        r = self.client.get(reverse('core:webhook_list'))
        self.assertIn(r.status_code, (302, 403))
        self.assertNotIn(b'SECRET-TOKEN', r.content)

    def test_read_only_member_is_refused(self):
        self.member('readonly')
        r = self.client.get(reverse('core:webhook_list'))
        self.assertIn(r.status_code, (302, 403))
        self.assertNotIn(b'SECRET-TOKEN', r.content)

    def test_owner_still_sees_the_list(self):
        self.member('owner')
        r = self.client.get(reverse('core:webhook_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Chat')
