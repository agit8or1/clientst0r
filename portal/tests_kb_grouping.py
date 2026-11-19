"""Customer-portal KB groups articles by category."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from docs.models import Document, DocumentCategory
from docs.tests_lifecycle import TEST_MIDDLEWARE
from psa.models import ClientPSASettings


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalKbGroupingTests(TestCase):
    def setUp(self):
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        self.org = Organization.objects.create(name='Grp Cust', slug='kbgrp')
        ClientPSASettings.objects.create(organization=self.org, portal_enabled=True)
        u = User.objects.create_user('grp-cust', 'g@kbgrp.test', 'pw')
        Membership.objects.create(user=u, organization=self.org, role=Role.READONLY, is_active=True)
        self.client = Client()
        self.client.force_login(u)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def _doc(self, title, cat, visible=True, **kw):
        return Document.objects.create(
            organization=self.org, is_global=True, title=title, slug=title.lower(),
            body='<p>x</p>', is_published=True, is_client_visible=visible,
            category=cat, **kw)

    def test_grouped_in_order_uncategorized_last_hidden_category_not_shown(self):
        late = DocumentCategory.objects.create(name='LateCat', slug='latecat', order=5)
        early = DocumentCategory.objects.create(name='EarlyCat', slug='earlycat', order=1)
        secret = DocumentCategory.objects.create(name='SecretCat', slug='secretcat', order=0)
        self._doc('InLate', late)
        self._doc('InEarly', early)
        self._doc('NoCat', None)
        self._doc('StaffOnly', secret, visible=False)
        r = self.client.get('/portal/kb/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([g['label'] for g in r.context['groups']],
                         ['EarlyCat', 'LateCat', 'Uncategorized'])
        html = r.content.decode()
        pos = [html.index(x) for x in ('EarlyCat', 'LateCat', 'Uncategorized')]
        self.assertEqual(pos, sorted(pos))
        self.assertNotContains(r, 'SecretCat')
        self.assertNotContains(r, 'StaffOnly')

    def test_featured_stay_on_top_and_not_repeated(self):
        cat = DocumentCategory.objects.create(name='Cat', slug='cat')
        self._doc('FeatDoc', cat, is_featured_in_portal=True)
        self._doc('PlainDoc', cat)
        r = self.client.get('/portal/kb/')
        self.assertEqual([a.title for a in r.context['featured']], ['FeatDoc'])
        self.assertEqual([a.title for a in r.context['articles']], ['PlainDoc'])
