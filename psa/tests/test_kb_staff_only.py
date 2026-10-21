"""v3.17.625 — the global KB is MSP staff only. Customer roles grant
kb_edit_articles / kb_move_articles by default; those no longer reach the
global KB, and /psa/kb/ shows drafts only to staff who can edit them."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, RoleTemplate, UserType
from core.models import Organization, SystemSetting
from docs.models import Document
from docs.permissions import can_edit
from psa.views import _check_kb_perm

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _client(user, org):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.pk
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalKBStaffOnlyTests(TestCase):
    def setUp(self):
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        self.org = Organization.objects.create(name='Cust', slug='cust')
        self.live = Document.objects.create(organization=self.org, title='KB live', slug='kb-live',
                                            body='SECRETWORD', is_global=True)
        self.draft = Document.objects.create(organization=self.org, title='KB draft', slug='kb-draft',
                                             is_global=True, is_published=False)
        self.customer_admin = User.objects.create_user('kbcust', password='pw')
        Membership.objects.create(user=self.customer_admin, organization=self.org, role='admin')

    def _staff(self, name, **flags):
        u = User.objects.create_user(name, password='pw')
        u.profile.user_type = UserType.STAFF
        u.profile.global_role_template = RoleTemplate.objects.create(name=f'{name}-role', **flags)
        u.profile.save()
        return u

    def test_customer_admin_has_no_global_kb_perms(self):
        for perm in ('kb_edit_articles', 'kb_move_articles', 'kb_manage_categories'):
            self.assertFalse(_check_kb_perm(self.customer_admin, perm), perm)
        self.assertFalse(can_edit(self.customer_admin, self.live))

    def test_customer_admin_blocked_from_kb_pages(self):
        c = _client(self.customer_admin, self.org)
        self.assertEqual(c.get('/psa/kb/').status_code, 403)
        self.assertEqual(c.get('/psa/kb/?q=SECRETWORD').status_code, 403)
        self.assertEqual(c.get('/docs/kb/create/').status_code, 403)
        self.assertEqual(c.post(f'/docs/kb/{self.live.slug}/edit/', {'title': 'x'}).status_code, 403)
        self.assertEqual(c.post('/psa/kb/move/', {'article_ids': [self.live.pk]}).status_code, 403)
        self.assertNotContains(c.get('/', follow=True), '/psa/kb/')

    def test_staff_reader_sees_published_only(self):
        reader = self._staff('kbreader', kb_view_articles=True, kb_edit_articles=False)
        r = _client(reader, self.org).get('/psa/kb/')
        self.assertContains(r, 'KB live')
        self.assertNotContains(r, 'KB draft')
        self.assertContains(r, f'/docs/kb/{self.live.slug}/')

    def test_staff_editor_sees_drafts(self):
        editor = self._staff('kbeditor', kb_view_articles=True, kb_edit_articles=True)
        self.assertTrue(_check_kb_perm(editor, 'kb_edit_articles'))
        r = _client(editor, self.org).get('/psa/kb/')
        self.assertContains(r, 'KB draft')
        self.assertContains(r, 'Draft</span>')
