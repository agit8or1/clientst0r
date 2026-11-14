"""Phase 67 compact dashboard: widget gates, lazy endpoint, layouts, the
classic switch, role presets and role defaults, quick-action checks and
current-organization scoping (core/dashboard_widgets.py)."""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from core import dashboard_widgets as dw
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed

User = get_user_model()

ALL_ON = dict(vault_view=True, docs_view=True, assets_view=True, files_view=True,
              monitoring_view=True, integrations_view=True, tickets_view=True)


def _req(user, org):
    """What the gates read: the user and the selected customer."""
    return SimpleNamespace(user=user, current_organization=org, session={})


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org_a = Organization.objects.create(name='Dash Alpha', slug='dash-alpha')
        cls.org_b = Organization.objects.create(name='Dash Bravo', slug='dash-bravo')
        cls.root = User.objects.create_superuser('dash_root', 'r@x.com', 'pw')
        cls.tech = _make_msp_tech(User.objects.create_user('dash_tech', 't@x.com', 'pw'))
        # A customer user (non-portal, on base.html) with the simple
        # Read-Only role.
        cls.reader = User.objects.create_user('dash_reader', 'c@x.com', 'pw')
        Membership.objects.create(user=cls.reader, organization=cls.org_a, role=Role.READONLY)
        # A customer user whose role lacks vault_view, docs_view and
        # monitoring_view.
        cls.narrow_role = RoleTemplate.objects.create(
            name='Dash narrow', organization=cls.org_a,
            **dict(ALL_ON, vault_view=False, docs_view=False, monitoring_view=False,
                   vault_create=True, assets_create=True))
        cls.narrow = User.objects.create_user('dash_narrow', 'n@x.com', 'pw')
        Membership.objects.create(user=cls.narrow, organization=cls.org_a, role=Role.EDITOR,
                                  role_template=cls.narrow_role)

    def _login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.pk
        s.save()

    def _allowed(self, user, org=None):
        org = org or self.org_a
        req = _req(user, org)
        return {w.key for w in dw.WIDGETS if w.allowed(req)}


class WidgetGateTests(_Base):

    def test_superuser_sees_every_widget(self):
        allowed = self._allowed(self.root)
        for key in ('kpi_tickets', 'kpi_assets', 'kpi_documents', 'kpi_passwords', 'kpi_monitors',
                    'kpi_rmm_alerts', 'kpi_tasks', 'schedule', 'tasks', 'monitors', 'map',
                    'ticket_status', 'ticket_activity', 'recent_activity', 'system_status',
                    'rmm_alerts', 'quick_actions'):
            self.assertIn(key, allowed)

    def test_msp_tech(self):
        allowed = self._allowed(self.tech)
        for key in ('kpi_tickets', 'kpi_assets', 'kpi_documents', 'kpi_monitors', 'kpi_rmm_alerts',
                    'rmm_alerts', 'ticket_status', 'monitors', 'map'):
            self.assertIn(key, allowed)
        # Not a superuser, and no membership to administer the audit log.
        self.assertNotIn('system_status', allowed)
        self.assertNotIn('recent_activity', allowed)
        # Vault flags are membership-scoped for staff without a global role.
        self.assertNotIn('kpi_passwords', allowed)

    def test_customer_readonly(self):
        allowed = self._allowed(self.reader)
        for key in ('kpi_rmm_alerts', 'rmm_alerts', 'system_status', 'recent_activity'):
            self.assertNotIn(key, allowed)
        self.assertIn('schedule', allowed)
        self.assertIn('tasks', allowed)

    def test_role_without_section_flags(self):
        allowed = self._allowed(self.narrow)
        for key in ('kpi_passwords', 'kpi_documents', 'kpi_monitors', 'monitors'):
            self.assertNotIn(key, allowed)
        self.assertIn('kpi_assets', allowed)
        self.assertNotIn('rmm_alerts', allowed)

    def test_gates_follow_the_selected_customer(self):
        # The narrow user holds nothing in Bravo.
        self.assertNotIn('kpi_assets', self._allowed(self.narrow, self.org_b))

    def test_failing_gate_fails_closed(self):
        w = dw.Widget('x', 'X', 'fa-x', gate=lambda r: 1 / 0, build=lambda r, o: {}, template='')
        self.assertFalse(w.allowed(_req(self.root, self.org_a)))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DashboardViewTests(_Base):

    def _get(self, user, path=None, org=None):
        self._login(user, org or self.org_a)
        return self.client.get(path or reverse('core:dashboard'))

    def test_new_dashboard_is_the_default(self):
        r = self._get(self.root)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, 'core/dashboard_modern.html')
        self.assertContains(r, 'Classic dashboard')
        self.assertEqual(r.context['widget_errors'], [])

    def test_layout_query_is_one_off(self):
        r = self._get(self.root, reverse('core:dashboard') + '?layout=classic')
        self.assertTemplateUsed(r, 'core/dashboard_classic.html')
        self.assertContains(r, 'New dashboard')
        self.root.refresh_from_db()
        self.assertEqual(UserProfile.objects.get(user=self.root).dashboard_variant, 'modern')

    def test_switch_saves_the_choice(self):
        self._login(self.root, self.org_a)
        r = self.client.post(reverse('core:dashboard_variant_save'), {'variant': 'classic'})
        self.assertRedirects(r, reverse('core:dashboard'), fetch_redirect_response=False)
        self.assertEqual(UserProfile.objects.get(user=self.root).dashboard_variant, 'classic')
        self.assertTemplateUsed(self.client.get(reverse('core:dashboard')), 'core/dashboard_classic.html')
        r = self.client.get(reverse('core:dashboard') + '?layout=modern')
        self.assertTemplateUsed(r, 'core/dashboard_modern.html')
        self.client.post(reverse('core:dashboard_variant_save'), {'variant': 'bogus'})
        self.assertEqual(UserProfile.objects.get(user=self.root).dashboard_variant, 'classic')

    def test_switch_needs_post(self):
        self._login(self.root, self.org_a)
        self.assertEqual(self.client.get(reverse('core:dashboard_variant_save')).status_code, 405)

    def test_gated_widgets_are_not_rendered(self):
        r = self._get(self.narrow)
        self.assertEqual(r.status_code, 200)
        keys = {p.key for p in r.context['grid']} | {p.key for p in r.context['kpis']}
        for key in ('kpi_passwords', 'kpi_documents', 'kpi_monitors', 'monitors', 'rmm_alerts',
                    'system_status'):
            self.assertNotIn(key, keys)
        listed = {p.key for p in r.context['customize']['grid']}
        self.assertNotIn('monitors', listed)

    def _set_layout(self, user, layout):
        # After force_login, which re-saves the profile cached on the user.
        UserProfile.objects.filter(user=user).update(dashboard_layout=layout)

    def test_hidden_widget_is_not_built(self):
        self._login(self.root, self.org_a)
        self._set_layout(self.root, {'order': [], 'hidden': ['kpi_monitors', 'monitors'], 'sizes': {}})
        with mock.patch.object(dw, '_monitor_counts', side_effect=AssertionError('built')) as m:
            r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        m.assert_not_called()
        self.assertNotIn('monitors', {p.key for p in r.context['grid']})

    def test_lazy_endpoint(self):
        self._login(self.root, self.org_a)
        url = reverse('core:dashboard_widget', args=['ticket_activity'])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:dashboard_widget', args=['nope'])).status_code, 404)
        # Banner / toolbar widgets aren't served on their own.
        self.assertEqual(self.client.get(
            reverse('core:dashboard_widget', args=['security_2fa'])).status_code, 404)

    def test_lazy_endpoint_404_when_gated(self):
        for user, key in ((self.narrow, 'monitors'), (self.narrow, 'kpi_passwords'),
                          (self.reader, 'rmm_alerts'), (self.tech, 'system_status'),
                          (self.reader, 'recent_activity'), (self.tech, 'kpi_passwords')):
            with self.subTest(user=user.username, key=key):
                self._login(user, self.org_a)
                r = self.client.get(reverse('core:dashboard_widget', args=[key]))
                self.assertEqual(r.status_code, 404)

    def test_lazy_endpoint_ignores_layout(self):
        # Hiding a widget doesn't grant or remove access; the gate decides.
        self._login(self.narrow, self.org_a)
        self._set_layout(self.narrow, {'order': ['monitors'], 'hidden': [], 'sizes': {}})
        self.assertEqual(self.client.get(
            reverse('core:dashboard_widget', args=['monitors'])).status_code, 404)

    def test_every_lazy_widget_renders_for_superuser(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.crm_enabled = True  # the sales widgets follow the CRM module
        s.save()
        self._login(self.root, self.org_a)
        for w in dw.WIDGETS:
            if w.zone in ('grid', 'kpi') and w.key not in ('kpi_psa_companies', 'kpi_psa_tickets'):
                with self.subTest(key=w.key):
                    r = self.client.get(reverse('core:dashboard_widget', args=[w.key]))
                    self.assertEqual(r.status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CrossOrgTests(_Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from audit.models import AuditLog
        from monitoring.models import WebsiteMonitor
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        from scheduling.models import ScheduledTask
        status = TicketStatus.objects.filter(is_terminal=False).first()
        for org, tag in ((cls.org_a, 'ALPHA'), (cls.org_b, 'BRAVO')):
            Ticket.objects.create(
                organization=org, subject=f'{tag}-ticket', queue=Queue.objects.first(),
                priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
                status=status, client_can_view=True)
            WebsiteMonitor.objects.create(organization=org, name=f'{tag}-monitor',
                                          url='https://x.example', status='down')
            AuditLog.objects.create(organization=org, user=cls.root, username='dash_root',
                                    action='update', object_repr=f'{tag}-audit')
            task = ScheduledTask.objects.create(organization=org, title=f'{tag}-task',
                                                status='pending',
                                                due_date=timezone.now() + timedelta(days=1))
            task.assigned_to.set([cls.root])

    def test_only_the_current_customer(self):
        self._login(self.root, self.org_a)
        body = self.client.get(reverse('core:dashboard')).content.decode()
        for key in ('ticket_status', 'ticket_activity', 'recent_activity', 'monitors', 'tasks',
                    'schedule', 'kpi_tickets', 'kpi_monitors', 'kpi_tasks'):
            body += self.client.get(reverse('core:dashboard_widget', args=[key])).content.decode()
        self.assertIn('ALPHA-audit', body)
        self.assertIn('ALPHA-task', body)
        self.assertNotIn('BRAVO', body)

    def test_counts_are_per_customer(self):
        req = _req(self.root, self.org_a)
        self.assertEqual(dw.build_kpi_tickets(req, self.org_a)['value'], 1)
        self.assertEqual(dw.build_kpi_monitors(req, self.org_a)['value'], 1)
        self.assertEqual(dw.build_kpi_tasks(req, self.org_a)['value'], 1)
        self.assertEqual(dw.build_ticket_status(req, self.org_a)['total'], 1)
        self.assertEqual(dw.build_ticket_activity(req, self.org_a)['opened_total'], 1)

    def test_customer_sees_only_shared_own_tickets(self):
        from psa.models import Ticket
        Ticket.objects.filter(subject='ALPHA-ticket').update(client_can_view=False)
        req = _req(self.reader, self.org_a)
        if dw.gate_tickets(req):
            self.assertEqual(dw.build_kpi_tickets(req, self.org_a)['value'], 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LayoutSaveTests(_Base):

    def _post(self, payload, url=None):
        return self.client.post(url or reverse('core:dashboard_layout_save'),
                                data=json.dumps(payload), content_type='application/json')

    def test_validation(self):
        self._login(self.tech, self.org_a)
        r = self._post({'layout': {
            'order': ['tasks', 'bogus', 'tasks', 'map', 42],
            'hidden': ['map', 'nonsense', 'security_2fa'],
            'sizes': {'map': 9, 'tasks': 0, 'bogus': 2, 'kpi_tickets': 3, 'schedule': 'x'},
        }, 'density': 'comfortable', 'quick_actions': ['add_asset', 'add_asset', 'zzz']})
        self.assertEqual(r.status_code, 200, r.content)
        p = UserProfile.objects.get(user=self.tech)
        self.assertEqual(p.dashboard_layout['order'], ['tasks', 'map'])
        # The 2FA warning can't be hidden.
        self.assertEqual(p.dashboard_layout['hidden'], ['map'])
        self.assertEqual(p.dashboard_layout['sizes'], {'map': 3, 'tasks': 1})
        self.assertEqual(p.ui_density, 'comfortable')
        self.assertEqual(p.quick_actions_config, ['add_asset'])

    def test_bad_requests(self):
        self._login(self.tech, self.org_a)
        self.assertEqual(self._post({'layout': []}).status_code, 400)
        self.assertEqual(self._post({'layout': {'order': 'tasks'}}).status_code, 400)
        self.assertEqual(self._post({'density': 'huge'}).status_code, 400)
        self.assertEqual(self._post({}).status_code, 400)
        r = self.client.post(reverse('core:dashboard_layout_save'), data='not json',
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('errors', r.json())

    def test_lists_are_capped(self):
        self._login(self.tech, self.org_a)
        self._post({'layout': {'order': list(dw.KEYS) * 20}})
        p = UserProfile.objects.get(user=self.tech)
        self.assertEqual(len(p.dashboard_layout['order']), len(dw.KEYS))

    def test_only_own_layout(self):
        other = UserProfile.objects.get(user=self.reader)
        other.dashboard_layout = {'order': ['tasks'], 'hidden': [], 'sizes': {}}
        other.save()
        self._login(self.tech, self.org_a)
        self._post({'layout': {'order': ['map']}, 'user': self.reader.pk,
                    'user_id': self.reader.pk})
        other.refresh_from_db()
        self.assertEqual(other.dashboard_layout['order'], ['tasks'])
        self.assertEqual(UserProfile.objects.get(user=self.tech).dashboard_layout['order'], ['map'])

    def test_reset(self):
        self._login(self.tech, self.org_a)
        self._post({'layout': {'order': ['map']}})
        self._post({'action': 'reset'})
        self.assertEqual(UserProfile.objects.get(user=self.tech).dashboard_layout, {})

    def test_csrf_required(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.tech)
        r = c.post(reverse('core:dashboard_layout_save'), data='{"action": "reset"}',
                   content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_saved_layout_never_grants(self):
        self._login(self.narrow, self.org_a)
        UserProfile.objects.filter(user=self.narrow).update(
            dashboard_layout={'order': ['monitors', 'kpi_passwords'], 'hidden': [], 'sizes': {}})
        r = self.client.get(reverse('core:dashboard'))
        keys = {x.key for x in r.context['grid']} | {x.key for x in r.context['kpis']}
        self.assertNotIn('monitors', keys)
        self.assertNotIn('kpi_passwords', keys)


class PresetTests(_Base):

    def _staff_with(self, name, seed='', tier=''):
        role = RoleTemplate.objects.create(name=f'role {name}', seed_key=seed, rmm_tier=tier)
        user = _make_msp_tech(User.objects.create_user(name, f'{name}@x.com', 'pw'))
        user.profile.global_role_template = role
        user.profile.save()
        return User.objects.get(pk=user.pk)

    def test_selection(self):
        self.assertEqual(dw.preset_for_user(self.root), dw.PRESET_ADMIN)
        self.assertEqual(dw.preset_for_user(self.reader), dw.PRESET_CUSTOMER)
        self.assertEqual(dw.preset_for_user(self.narrow), dw.PRESET_CUSTOMER)
        self.assertEqual(dw.preset_for_user(self.tech), dw.PRESET_L2)
        cases = {
            ('p_l1', 'tech_l1', ''): dw.PRESET_L1,
            ('p_l2', 'tech_l2', ''): dw.PRESET_L2,
            ('p_l3', 'tech_l3', ''): dw.PRESET_L3,
            ('p_sm', 'service_manager', ''): dw.PRESET_MANAGER,
            ('p_sr', 'sales_rep', ''): dw.PRESET_SALES,
            ('p_smgr', 'sales_manager', ''): dw.PRESET_SALES,
            ('p_own', 'org_owner', ''): dw.PRESET_ADMIN,
            ('p_adm', 'org_admin', ''): dw.PRESET_ADMIN,
            ('p_pa', '', 'platform_admin'): dw.PRESET_ADMIN,
            ('p_tier', '', 'l1'): dw.PRESET_L1,
        }
        for (name, seed, tier), expected in cases.items():
            with self.subTest(seed=seed, tier=tier):
                self.assertEqual(dw.preset_for_user(self._staff_with(name, seed, tier)), expected)

    def test_presets_are_valid_layouts(self):
        for key in dw.PRESET_KEYS:
            layout = dw.preset_layout(key)
            self.assertEqual(dw.clean_layout(layout)[0], layout)
            self.assertEqual(sorted(layout['order']), sorted(dw.KEYS))

    def test_preset_never_shows_a_gated_widget(self):
        # The admin preset lists system_status; a technician still can't see it.
        req = _req(self.tech, self.org_a)
        placed = dw.visible_widgets(req, dw.preset_layout(dw.PRESET_ADMIN))
        self.assertNotIn('system_status', {p.key for p in placed})


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleDefaultTests(_Base):

    def _post(self, payload):
        return self.client.post(reverse('core:dashboard_role_default_save'),
                                data=json.dumps(payload), content_type='application/json')

    def test_requires_permission(self):
        from core.models import DashboardRoleDefault
        for user in (self.tech, self.reader, self.narrow):
            with self.subTest(user=user.username):
                self._login(user, self.org_a)
                r = self._post({'preset': 'tech_l2', 'layout': {'order': ['map']}})
                self.assertEqual(r.status_code, 403)
        self.assertFalse(DashboardRoleDefault.objects.exists())

    def test_customer_org_admin_with_roles_manage_cannot(self):
        # roles_manage at one customer doesn't reach an installation-wide default.
        admin = User.objects.create_user('dash_cust_admin', 'ca@x.com', 'pw')
        Membership.objects.create(user=admin, organization=self.org_a, role=Role.ADMIN)
        self._login(admin, self.org_a)
        self.assertEqual(self._post({'preset': 'customer', 'layout': {}}).status_code, 403)

    def test_superuser_saves_and_it_applies(self):
        self._login(self.root, self.org_a)
        r = self._post({'preset': 'tech_l2', 'layout': {'order': ['map', 'tasks'],
                                                        'hidden': ['schedule']}})
        self.assertEqual(r.status_code, 200, r.content)
        layout, source, preset = dw.effective_layout(_req(self.tech, self.org_a))
        self.assertEqual(source, 'role')
        self.assertEqual(layout['order'][:2], ['map', 'tasks'])
        self.assertIn('schedule', layout['hidden'])
        # A personal layout wins.
        p = UserProfile.objects.get(user=self.tech)
        p.dashboard_layout = {'order': ['tasks'], 'hidden': [], 'sizes': {}}
        p.save()
        tech = User.objects.get(pk=self.tech.pk)
        self.assertEqual(dw.effective_layout(_req(tech, self.org_a))[1], 'personal')
        self._post({'preset': 'tech_l2', 'action': 'clear'})
        p.dashboard_layout = {}
        p.save()
        tech = User.objects.get(pk=self.tech.pk)
        self.assertEqual(dw.effective_layout(_req(tech, self.org_a))[1], 'preset')

    def test_staff_with_roles_manage(self):
        role = RoleTemplate.objects.create(name='Dash role admin', roles_manage=True)
        user = _make_msp_tech(User.objects.create_user('dash_rm', 'rm@x.com', 'pw'))
        user.profile.global_role_template = role
        user.profile.save()
        self._login(user, self.org_a)
        self.assertEqual(self._post({'preset': 'sales', 'layout': {'order': ['tasks']}}).status_code, 200)
        self.assertEqual(self._post({'preset': 'nobody', 'layout': {}}).status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuickActionGateTests(_Base):

    def _keys(self, user, org=None, flags=None):
        from core.quick_actions import QUICK_ACTIONS_REGISTRY, resolve_for_user
        p = UserProfile.objects.get(user=user)
        p.quick_actions_config = [a['key'] for a in QUICK_ACTIONS_REGISTRY]
        p.save()
        user = User.objects.get(pk=user.pk)
        ctx = dict({'psa_enabled': True, 'vehicles_enabled': True, 'reports_enabled': True,
                    'current_organization': org or self.org_a}, **(flags or {}))
        return {a['key'] for a in resolve_for_user(user, ctx)}

    def test_superuser_gets_all(self):
        from core.quick_actions import QUICK_ACTIONS_REGISTRY
        self.assertEqual(self._keys(self.root), {a['key'] for a in QUICK_ACTIONS_REGISTRY})

    def test_readonly_customer(self):
        keys = self._keys(self.reader)
        for k in ('new_password', 'add_asset', 'add_document', 'new_quote', 'wallboard',
                  'agreement_recon', 'scan_receipt', 'new_invoice'):
            self.assertNotIn(k, keys)

    def test_role_without_vault_view(self):
        keys = self._keys(self.narrow)
        self.assertNotIn('new_password', keys)    # no vault_view
        self.assertNotIn('add_document', keys)    # no docs_view
        self.assertIn('add_asset', keys)          # assets_view + assets_create
        self.assertNotIn('new_quote', keys)       # MSP staff only
        self.assertNotIn('wallboard', keys)       # /reports/ is staff only

    def test_tech(self):
        keys = self._keys(self.tech)
        self.assertIn('scan_receipt', keys)
        # @require_write wants an Editor-or-above membership (or Django
        # is_staff) in the selected customer; a technician without one is
        # turned away by the create pages, so the tiles aren't offered.
        self.assertNotIn('new_quote', keys)
        self.assertNotIn('new_ticket', keys)
        member = _make_msp_tech(User.objects.create_user('dash_tech_m', 'tm@x.com', 'pw'))
        Membership.objects.create(user=member, organization=self.org_a, role=Role.EDITOR)
        keys = self._keys(member)
        self.assertIn('new_quote', keys)
        self.assertIn('new_ticket', keys)
        self.assertIn('add_asset', keys)
        self.assertNotIn('evidence_pack', self._keys(self.reader))

    def test_rendered_toolbar_hides_them(self):
        req = _req(self.narrow, self.org_a)
        ctx = dw.build_quick_actions(req, self.org_a)
        self.assertNotIn('new_password', {a['key'] for a in ctx['actions']})

    def test_editor_dedupes_and_caps(self):
        from core.quick_actions import MAX_SAVED
        self._login(self.root, self.org_a)
        r = self.client.post(reverse('accounts:quick_actions_edit'),
                             {'selected': ['add_asset', 'add_asset', 'wallboard'] + ['x'] * 100})
        self.assertEqual(r.status_code, 302)
        p = UserProfile.objects.get(user=self.root)
        self.assertEqual(p.quick_actions_config, ['add_asset', 'wallboard'])
        self.assertLessEqual(len(p.quick_actions_config), MAX_SAVED)
