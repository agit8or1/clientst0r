"""Global KB articles appear in every customer portal; org articles only in
their own customer's portal, and only when ticked."""
import importlib

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa.models import ClientPSASettings

from .models import Document
from .tests_lifecycle import TEST_MIDDLEWARE, _Base


def _portal_client(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalScopeTests(TestCase):
    def setUp(self):
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        self.orgs, self.clients = [], []
        for n in ('a', 'b'):
            org = Organization.objects.create(name=f'Cust {n}', slug=f'kbg-{n}')
            ClientPSASettings.objects.create(organization=org, portal_enabled=True)
            u = User.objects.create_user(f'cust-{n}', f'{n}@kbg.test', 'pw')
            Membership.objects.create(user=u, organization=org, role=Role.READONLY, is_active=True)
            self.orgs.append(org)
            self.clients.append(_portal_client(u))
        a, b = self.orgs
        mk = Document.objects.create
        mk(organization=a, is_global=True, title='GlobalShown', slug='g-shown', body='<p>x</p>',
           is_published=True, is_client_visible=True)
        mk(organization=a, is_global=True, title='GlobalStaff', slug='g-staff', body='<p>x</p>',
           is_published=True, is_client_visible=False)
        mk(organization=a, title='OrgAShown', slug='a-shown', body='<p>x</p>',
           is_published=True, is_client_visible=True)
        mk(organization=a, title='OrgAHidden', slug='a-hidden', body='<p>x</p>', is_published=True)
        mk(organization=b, title='OrgBShown', slug='b-shown', body='<p>x</p>',
           is_published=True, is_client_visible=True)

    def test_global_visible_in_both_portals(self):
        for c in self.clients:
            self.assertContains(c.get('/portal/kb/'), 'GlobalShown')
            self.assertEqual(c.get('/portal/kb/g-shown/').status_code, 200)

    def test_staff_only_global_hidden(self):
        for c in self.clients:
            self.assertNotContains(c.get('/portal/kb/'), 'GlobalStaff')
            self.assertEqual(c.get('/portal/kb/g-staff/').status_code, 404)

    def test_org_article_only_in_own_portal_and_only_when_ticked(self):
        ca, cb = self.clients
        self.assertContains(ca.get('/portal/kb/'), 'OrgAShown')
        self.assertNotContains(ca.get('/portal/kb/'), 'OrgAHidden')
        self.assertNotContains(ca.get('/portal/kb/'), 'OrgBShown')
        self.assertNotContains(cb.get('/portal/kb/'), 'OrgAShown')
        self.assertContains(cb.get('/portal/kb/'), 'OrgBShown')
        self.assertEqual(cb.get('/portal/kb/a-shown/').status_code, 404)
        self.assertEqual(ca.get('/portal/kb/a-hidden/').status_code, 404)
        self.assertEqual(ca.get('/portal/kb/b-shown/').status_code, 404)


class MigrationTests(TestCase):
    def test_data_migration_function(self):
        org = Organization.objects.create(name='M', slug='kbg-m')
        mk = lambda **kw: Document.objects.create(organization=org, body='x', is_published=True, **kw)  # noqa: E731
        g = mk(title='g', slug='mg')
        Document.objects.filter(pk=g.pk).update(is_global=True)
        gt = mk(title='gt', slug='mgt', is_template=True)
        ga = mk(title='ga', slug='mga', is_archived=True)
        Document.objects.filter(pk__in=[gt.pk, ga.pk]).update(is_global=True)
        o = mk(title='o', slug='mo')
        mod = importlib.import_module('docs.migrations.0021_global_kb_portal_visible')
        mod.show_global_in_portals(django_apps, None)
        vis = lambda d: Document.objects.get(pk=d.pk).is_client_visible  # noqa: E731
        self.assertTrue(vis(g))
        self.assertFalse(vis(gt))
        self.assertFalse(vis(ga))
        self.assertFalse(vis(o))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FormDefaultsAndBulkTests(_Base):
    def setUp(self):
        self.g1 = Document.objects.create(organization=self.org, is_global=True, title='G1', slug='bg1',
                                          body='x', is_published=True)
        self.g2 = Document.objects.create(organization=self.org, is_global=True, title='G2', slug='bg2',
                                          body='x', is_published=True, is_client_visible=True)

    def test_global_create_form_defaults_on_and_labelled(self):
        r = self.client_for(self.staff).get('/docs/kb/create/')
        f = r.context['form']
        self.assertTrue(f['is_client_visible'].initial)
        self.assertEqual(f.fields['is_client_visible'].label, 'Show in every customer portal')
        self.assertContains(r, 'Off = staff only')

    def test_org_create_form_defaults_off_and_labelled(self):
        r = self.client_for(self.publisher).get('/docs/create/')
        f = r.context['form']
        self.assertFalse(f['is_client_visible'].initial)
        self.assertFalse(f['is_client_visible'].value())
        self.assertEqual(f.fields['is_client_visible'].label, "Show in this customer's portal")

    def test_bulk_show_and_hide_with_audit(self):
        c = self.client_for(self.staff)
        r = c.get('/docs/kb/')
        self.assertContains(r, 'Staff only')
        self.assertContains(r, 'All customers')
        c.post('/docs/kb/portal-visibility/', {'action': 'show', 'ids': [self.g1.pk]})
        self.g1.refresh_from_db()
        self.assertTrue(self.g1.is_client_visible)
        c.post('/docs/kb/portal-visibility/', {'action': 'hide', 'ids': [self.g1.pk, self.g2.pk]})
        self.g1.refresh_from_db()
        self.g2.refresh_from_db()
        self.assertFalse(self.g1.is_client_visible or self.g2.is_client_visible)
        self.assertEqual(AuditLog.objects.filter(object_type='docs.Document',
                                                 description__icontains='global KB').count(), 2)

    def test_bulk_requires_post_and_permission(self):
        c = self.client_for(self.staff)
        self.assertEqual(c.get('/docs/kb/portal-visibility/').status_code, 405)
        for user in (self.reader, self.outsider):
            r = self.client_for(user).post('/docs/kb/portal-visibility/',
                                           {'action': 'show', 'ids': [self.g1.pk]})
            self.assertIn(r.status_code, (302, 403, 404))
            self.g1.refresh_from_db()
            self.assertFalse(self.g1.is_client_visible)

    def test_bulk_never_touches_org_documents(self):
        o = Document.objects.create(organization=self.org, title='O', slug='bo', body='x', is_published=True)
        self.client_for(self.staff).post('/docs/kb/portal-visibility/', {'action': 'show', 'ids': [o.pk]})
        o.refresh_from_db()
        self.assertFalse(o.is_client_visible)
