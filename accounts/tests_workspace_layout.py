"""113.9: Workspace layout presets are presentation only."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, UserProfile
from accounts.permission_utils import has_perm_for_org
from core.models import Organization, SystemSetting
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _make_msp_tech, _setup_seed

LEVELS = ('essentials', 'standard', 'advanced')
FLAGS = ('tickets_view', 'tickets_edit', 'vault_view', 'integrations_configure', 'view_profitability')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkspaceLayoutTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME', slug='acme')
        _enable_psa_for(self.org)
        self.user = _make_msp_tech(User.objects.create_user('tech', password='pw', email='t@x.com'))
        Membership.objects.update_or_create(
            user=self.user, organization=self.org, defaults={'role': Role.READONLY, 'is_active': True})
        self.client = Client(); self.client.force_login(self.user)
        s = self.client.session; s['current_organization_id'] = self.org.id; s.save()
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='T', queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(is_terminal=False).first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first())

    def _set(self, level):
        p = UserProfile.objects.get(user=self.user); p.workspace_level = level; p.save()

    def test_default_is_standard(self):
        self.assertEqual(UserProfile.objects.get(user=self.user).workspace_level, 'standard')
        html = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('data-workspace="standard"', html)

    def test_account_menu_sets_level_and_rejects_junk(self):
        r = self.client.post('/accounts/profile/workspace-layout/',
                             {'workspace_level': 'essentials', 'next': '/psa/my-work/'})
        self.assertEqual(r.status_code, 302); self.assertEqual(r['Location'], '/psa/my-work/')
        self.assertEqual(UserProfile.objects.get(user=self.user).workspace_level, 'essentials')
        self.client.post('/accounts/profile/workspace-layout/', {'workspace_level': 'root'})
        self.assertEqual(UserProfile.objects.get(user=self.user).workspace_level, 'essentials')
        r = self.client.post('/accounts/profile/workspace-layout/',
                             {'workspace_level': 'advanced', 'next': 'https://evil.example/'})
        self.assertNotIn('evil', r['Location'])
        self.assertEqual(self.client.get('/accounts/profile/workspace-layout/').status_code, 405)

    def test_profile_form_has_the_field(self):
        html = self.client.get('/accounts/profile/edit/').content.decode()
        self.assertIn('name="workspace_level"', html)

    def test_presets_never_change_authorization(self):
        base_perms = None; base_status = None
        for level in LEVELS:
            self._set(level)
            perms = {f: has_perm_for_org(self.user, self.org.id, f) for f in FLAGS}
            codes = {}
            c = Client(); c.force_login(self.user)
            s = c.session; s['current_organization_id'] = self.org.id; s.save()
            codes['detail'] = c.get(f'/psa/t/{self.ticket.ticket_number}/').status_code
            codes['mywork'] = c.get('/psa/my-work/').status_code
            codes['start'] = c.post(f'/psa/t/{self.ticket.ticket_number}/timer/start/',
                                    HTTP_ACCEPT='application/json').status_code
            codes['stop'] = c.post(f'/psa/t/{self.ticket.ticket_number}/timer/stop/',
                                   HTTP_ACCEPT='application/json').status_code
            codes['manual'] = c.post(f'/psa/t/{self.ticket.ticket_number}/time/manual/', {'minutes': '5'}).status_code
            TicketTimeEntry.objects.all().delete()
            if base_perms is None:
                base_perms, base_status = perms, codes
            self.assertEqual(perms, base_perms, level)
            self.assertEqual(codes, base_status, level)

    def test_hidden_controls_stay_in_the_page_under_every_preset(self):
        import re
        ids = {}
        for level in ('standard', 'essentials', 'advanced'):
            self._set(level)
            html = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
            self.assertIn(f'data-workspace="{level}"', html)
            ids[level] = set(re.findall(r'id="([\w-]+)"', html))
            mw = self.client.get('/psa/my-work/').content.decode()
            self.assertIn('id="mw-waiting"', mw)
            self.assertIn('workspace_layout.js', mw)
        self.assertIn('ticketTimerInline', ids['standard'])
        self.assertIn('time-charges', ids['standard'])
        # Folding is client-side: every element of the Standard page is still
        # in the Essentials and Advanced HTML (so hidden controls are reachable).
        self.assertLessEqual(ids['standard'], ids['essentials'])
        self.assertLessEqual(ids['standard'], ids['advanced'])
        from django.conf import settings
        import os
        js = open(os.path.join(settings.BASE_DIR, 'static/js/workspace_layout.js')).read()
        self.assertIn("'More'", js); self.assertIn('aria-expanded', js)
