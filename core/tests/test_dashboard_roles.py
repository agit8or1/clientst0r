"""Dashboard overhaul: role-based defaults on the real built-in roles, the
service-desk figures (scoping and definitions), the header's primary actions
and their gates, layout save / restore and the Classic fallback."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile
from core import dashboard_widgets as dw
from core.models import Organization, SystemSetting
from core.tests.test_dashboard_widgets import _req
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed

User = get_user_model()

SERVICE_KPIS = {'kpi_my_open', 'kpi_sla_risk', 'kpi_overdue', 'kpi_unassigned',
                'kpi_approvals', 'kpi_due_today'}


def _role(seed):
    from accounts.role_seeds import seed_builtin_roles
    row = RoleTemplate.objects.filter(seed_key=seed, organization__isnull=True).first()
    if row is None:  # --keepdb can lose the migration-seeded rows
        seed_builtin_roles(RoleTemplate)
        row = RoleTemplate.objects.get(seed_key=seed, organization__isnull=True)
    return row


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        s = SystemSetting.get_settings()
        s.crm_enabled = True
        s.save()
        cls.org_a = Organization.objects.create(name='Role Alpha', slug='role-alpha')
        cls.org_b = Organization.objects.create(name='Role Bravo', slug='role-bravo')
        cls.root = User.objects.create_superuser('role_root', 'r@x.com', 'pw')
        cls.users = {}
        for seed in ('org_owner', 'org_admin', 'service_manager', 'tech_l1', 'tech_l2', 'tech_l3',
                     'sales_rep', 'sales_manager', 'billing_finance', 'auditor'):
            u = _make_msp_tech(User.objects.create_user(f'role_{seed}', f'{seed}@x.com', 'pw'))
            u.profile.global_role_template = _role(seed)
            u.profile.save()
            # An Editor membership in Alpha: the create pages' @require_write.
            Membership.objects.create(user=u, organization=cls.org_a, role=Role.EDITOR)
            cls.users[seed] = u
        cls.customer = User.objects.create_user('role_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=cls.customer, organization=cls.org_a, role=Role.EDITOR,
                                  role_template=_role('customer_user'))
        cls.cust_admin = User.objects.create_user('role_cust_admin', 'ca@x.com', 'pw')
        Membership.objects.create(user=cls.cust_admin, organization=cls.org_a, role=Role.ADMIN,
                                  role_template=_role('customer_admin'))

    def user(self, seed):
        return User.objects.get(pk=self.users[seed].pk)

    def _login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = (org or self.org_a).pk
        s.save()

    def _shown(self, user, org=None):
        """Keys the default dashboard shows this user (gates applied)."""
        req = _req(user, org or self.org_a)
        layout = dw.effective_layout(req)[0]
        return {p.key for p in dw.visible_widgets(req, layout) if not p.hidden}


class RolePresetTests(_Base):

    def test_real_roles_map_to_presets(self):
        expected = {
            'org_owner': dw.PRESET_ADMIN, 'org_admin': dw.PRESET_ADMIN,
            'service_manager': dw.PRESET_MANAGER, 'billing_finance': dw.PRESET_MANAGER,
            'auditor': dw.PRESET_MANAGER,
            'tech_l1': dw.PRESET_L1, 'tech_l2': dw.PRESET_L2, 'tech_l3': dw.PRESET_L3,
            'sales_rep': dw.PRESET_SALES, 'sales_manager': dw.PRESET_SALES,
        }
        for seed, preset in expected.items():
            with self.subTest(seed=seed):
                self.assertEqual(dw.preset_for_user(self.user(seed)), preset)
        self.assertEqual(dw.preset_for_user(self.customer), dw.PRESET_CUSTOMER)
        self.assertEqual(dw.preset_for_user(self.cust_admin), dw.PRESET_CUSTOMER)

    def test_rmm_tier_templates(self):
        from accounts.rmm_role_templates import BUILTIN_RMM_TEMPLATES
        for name, tier, _desc, _flags in BUILTIN_RMM_TEMPLATES:
            role = RoleTemplate.objects.filter(name=name, organization__isnull=True).first()
            if role is None:
                role = RoleTemplate.objects.create(name=name, rmm_tier=tier, is_system_template=True)
            u = _make_msp_tech(User.objects.create_user(f'rmm_{tier}', f'{tier}@x.com', 'pw'))
            u.profile.global_role_template = role
            u.profile.save()
            want = {'l1': dw.PRESET_L1, 'l2': dw.PRESET_L2, 'l3': dw.PRESET_L3,
                    'platform_admin': dw.PRESET_ADMIN}[tier]
            with self.subTest(tier=tier):
                self.assertEqual(dw.preset_for_user(User.objects.get(pk=u.pk)), want)

    def test_legacy_system_templates(self):
        role = RoleTemplate.objects.create(name='Tech Manager', is_system_template=True)
        u = _make_msp_tech(User.objects.create_user('legacy_tm', 'tm@x.com', 'pw'))
        u.profile.global_role_template = role
        u.profile.save()
        self.assertEqual(dw.preset_for_user(User.objects.get(pk=u.pk)), dw.PRESET_MANAGER)
        # The same name on a role an administrator made is not trusted.
        role.is_system_template = False
        role.save()
        self.assertEqual(dw.preset_for_user(User.objects.get(pk=u.pk)), dw.PRESET_L2)

    def test_technician_defaults(self):
        for seed in ('tech_l1', 'tech_l2', 'tech_l3'):
            shown = self._shown(self.user(seed))
            with self.subTest(seed=seed):
                self.assertIn('my_queue', shown)
                self.assertIn('sla_overview', shown)
                self.assertIn('kpi_my_open', shown)
                self.assertIn('kpi_sla_risk', shown)
                self.assertIn('kpi_overdue', shown)
                self.assertNotIn('system_status', shown)
                self.assertNotIn('quick_actions', shown)
        self.assertIn('my_time', self._shown(self.user('tech_l1')))

    def test_dispatcher_defaults(self):
        shown = self._shown(self.user('service_manager'))
        for key in ('unassigned_queue', 'workload', 'sla_overview', 'kpi_unassigned',
                    'kpi_approvals', 'kpi_sla_risk', 'ticket_activity'):
            self.assertIn(key, shown)

    def test_admin_defaults(self):
        shown = self._shown(self.root)
        self.assertTrue(SERVICE_KPIS <= shown, SERVICE_KPIS - shown)
        for key in ('my_queue', 'sla_overview', 'workload', 'recent_activity', 'system_status'):
            self.assertIn(key, shown)

    def test_sales_defaults(self):
        shown = self._shown(self.user('sales_rep'))
        for key in ('crm_pipeline', 'crm_closing', 'kpi_crm_open', 'kpi_crm_leads'):
            self.assertIn(key, shown)
        self.assertNotIn('my_queue', shown)

    def test_crm_off_hides_sales_widgets(self):
        s = SystemSetting.get_settings()
        s.crm_enabled = False
        s.save()
        shown = self._shown(self.user('sales_rep'))
        self.assertFalse({'crm_pipeline', 'crm_closing', 'kpi_crm_open', 'kpi_crm_leads'} & shown)

    def test_customers_get_customer_widgets_only(self):
        for user in (self.customer, self.cust_admin):
            req = _req(user, self.org_a)
            allowed = {w.key for w in dw.WIDGETS if w.allowed(req)}
            with self.subTest(user=user.username):
                # No MSP-only figure or panel passes a customer's gates.
                self.assertFalse(allowed & dw.MSP_ONLY - {'kpi_psa_companies', 'kpi_psa_tickets'},
                                 allowed & dw.MSP_ONLY)
                shown = self._shown(user)
                self.assertFalse(shown & dw.MSP_ONLY)

    def test_customer_role_default_never_lists_msp_panels(self):
        from core.models import DashboardRoleDefault
        DashboardRoleDefault.objects.create(preset=dw.PRESET_CUSTOMER, layout={
            'order': ['kpi_psa_companies', 'my_queue', 'tasks'], 'hidden': [], 'sizes': {}})
        layout, source, _ = dw.effective_layout(_req(self.customer, self.org_a))
        self.assertEqual(source, 'role')
        self.assertIn('kpi_psa_companies', layout['hidden'])
        self.assertIn('my_queue', layout['hidden'])
        self.assertNotIn('tasks', layout['hidden'])

    def test_every_preset_fits_two_rows(self):
        for preset in dw.PRESET_KEYS:
            layout = dw.preset_layout(preset)
            hidden = set(layout['hidden'])
            cells = sum(layout['sizes'].get(k, dw.BY_KEY[k].size) for k in layout['order']
                        if k not in hidden and dw.BY_KEY[k].zone == 'grid')
            kpis = [k for k in layout['order'] if k not in hidden and dw.BY_KEY[k].zone == 'kpi']
            with self.subTest(preset=preset):
                self.assertLessEqual(cells, 6)
                self.assertLessEqual(len(kpis), 7)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ServiceFigureTests(_Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        cls.tech = cls.users['tech_l2']
        running = TicketStatus.objects.filter(is_terminal=False, pauses_sla=False).first()
        paused = TicketStatus.objects.filter(is_terminal=False, pauses_sla=True).first()
        closed = TicketStatus.objects.filter(is_terminal=True).first()
        now = timezone.now()
        base = dict(queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                    ticket_type=TicketType.objects.first(), client_can_view=True)

        def mk(org, subject, status=running, **kw):
            t = Ticket.objects.create(organization=org, subject=subject, status=status,
                                      **dict(base, **kw))
            # Ticket.save may fill SLA deadlines from the priority; set ours.
            Ticket.objects.filter(pk=t.pk).update(
                first_response_due_at=kw.get('first_response_due_at'),
                first_response_at=now - timedelta(days=3),
                resolution_due_at=kw.get('resolution_due_at'))
            return t

        for org, tag in ((cls.org_a, 'A'), (cls.org_b, 'B')):
            mk(org, f'{tag}-mine-overdue', assigned_to=cls.tech,
               resolution_due_at=now - timedelta(hours=1))
            mk(org, f'{tag}-mine-risk', assigned_to=cls.tech,
               resolution_due_at=now + timedelta(minutes=30))
            mk(org, f'{tag}-unassigned-later', resolution_due_at=now + timedelta(days=3))
            if paused is not None:
                mk(org, f'{tag}-paused-late', status=paused, assigned_to=cls.tech,
                   resolution_due_at=now - timedelta(hours=5))
            mk(org, f'{tag}-closed', status=closed, assigned_to=cls.tech,
               resolution_due_at=now - timedelta(hours=5))
        cls.has_paused = paused is not None

    def test_counts_are_for_the_selected_customer_only(self):
        req = _req(self.tech, self.org_a)
        mine = 3 if self.has_paused else 2
        self.assertEqual(dw.build_kpi_my_open(req, self.org_a)['value'], mine)
        self.assertEqual(dw.build_kpi_overdue(req, self.org_a)['value'], 1)  # paused not late
        self.assertEqual(dw.build_kpi_sla_risk(req, self.org_a)['value'], 1)
        self.assertEqual(dw.build_kpi_unassigned(req, self.org_a)['value'], 1)
        c = dw.sla_counts(req, self.org_a)
        self.assertEqual(c['open'], 4 if self.has_paused else 3)
        queue = dw.build_my_queue(req, self.org_a)
        subjects = [r['subject'] for r in queue['rows']]
        self.assertTrue(all(s.startswith('A-') for s in subjects), subjects)
        # Running clocks first, soonest deadline first; paused ones last.
        self.assertEqual(subjects[:2], ['A-mine-overdue', 'A-mine-risk'])
        workload = dw.build_workload(req, self.org_a)
        self.assertEqual(sum(r['count'] for r in workload['rows']), c['open'])

    def test_org_a_user_never_counts_org_b(self):
        # A technician whose global role reaches Alpha only (customer
        # restriction through orgs_with_perm) gets no Bravo figures: the
        # gates refuse Bravo, and Alpha's numbers hold no Bravo tickets.
        from accounts.permission_utils import orgs_with_perm
        req_b = _req(self.tech, self.org_b)
        allowed = orgs_with_perm(self.tech, 'tickets_view')
        if allowed is not None and self.org_b.pk not in allowed:
            self.assertFalse(dw.gate_staff_tickets(req_b))
        body = ''
        self._login(self.tech, self.org_a)
        for key in ('my_queue', 'unassigned_queue', 'workload', 'ticket_recent'):
            r = self.client.get(reverse('core:dashboard_widget', args=[key]))
            self.assertEqual(r.status_code, 200, key)
            body += r.content.decode()
        self.assertIn('A-mine-risk', body)
        self.assertNotIn('B-', body)

    def test_customer_gets_no_msp_figures(self):
        self._login(self.customer, self.org_a)
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        keys = {p.key for p in r.context['kpis']} | {p.key for p in r.context['grid']}
        self.assertFalse(keys & dw.MSP_ONLY)
        for key in ('kpi_my_open', 'kpi_overdue', 'kpi_approvals', 'my_queue', 'workload',
                    'sla_overview', 'crm_pipeline'):
            self.assertEqual(self.client.get(
                reverse('core:dashboard_widget', args=[key])).status_code, 404, key)

    def test_tiles_link_to_real_ticket_list_filters(self):
        req = _req(self.tech, self.org_a)
        base = reverse('psa:ticket_list')
        self.assertEqual(dw.build_kpi_my_open(req, self.org_a)['href'],
                         f'{base}?client={self.org_a.pk}&assigned=me&queue=open')
        self.assertEqual(dw.build_kpi_unassigned(req, self.org_a)['href'],
                         f'{base}?client={self.org_a.pk}&assigned=unassigned&queue=open')
        self.assertEqual(dw.build_kpi_overdue(req, self.org_a)['href'],
                         f'{base}?client={self.org_a.pk}&queue=open')

    def test_approvals_only_for_approvers(self):
        self.assertTrue(dw.gate_approvals(_req(self.root, self.org_a)))
        self.assertFalse(dw.gate_approvals(_req(self.customer, self.org_a)))
        # A technician without write rights at the customer can't decide one.
        reader = _make_msp_tech(User.objects.create_user('role_ro_tech', 'ro@x.com', 'pw'))
        Membership.objects.create(user=reader, organization=self.org_a, role=Role.READONLY)
        self.assertFalse(dw.gate_approvals(_req(User.objects.get(pk=reader.pk), self.org_a)))

    def test_approvals_kpi_is_lazy(self):
        self._login(self.root, self.org_a)
        r = self.client.get(reverse('core:dashboard'))
        self.assertContains(r, 'data-kpi="kpi_approvals" data-dash-lazy')
        r = self.client.get(reverse('core:dashboard_widget', args=['kpi_approvals']))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Pending approvals')


class HeaderActionTests(_Base):

    def _keys(self, user, org=None):
        return [a['key'] for a in dw.header_actions(_req(user, org or self.org_a))]

    def test_superuser_gets_all_five(self):
        self.assertEqual(self._keys(self.root),
                         ['new_ticket', 'log_time', 'add_client', 'create_project',
                          'dispatch_board'])

    def test_technician_with_write(self):
        keys = self._keys(self.user('tech_l1'))
        for k in ('new_ticket', 'log_time', 'dispatch_board', 'create_project', 'add_client'):
            self.assertIn(k, keys)

    def test_customer_user(self):
        keys = self._keys(self.customer)
        for k in ('log_time', 'dispatch_board', 'add_client'):
            self.assertNotIn(k, keys)

    def test_psa_off(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        self.assertEqual(self._keys(self.root), ['add_client'])

    def test_technician_without_write(self):
        tech = _make_msp_tech(User.objects.create_user('role_nowrite', 'nw@x.com', 'pw'))
        keys = self._keys(User.objects.get(pk=tech.pk))
        self.assertNotIn('new_ticket', keys)
        self.assertNotIn('create_project', keys)
        self.assertIn('dispatch_board', keys)

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_rendered_header(self):
        self._login(self.customer, self.org_a)
        r = self.client.get(reverse('core:dashboard'))
        self.assertNotContains(r, 'data-dash-action="dispatch_board"')
        self.assertNotContains(r, 'data-dash-action="log_time"')
        self._login(self.root, self.org_a)
        r = self.client.get(reverse('core:dashboard'))
        self.assertContains(r, 'data-dash-action="dispatch_board"')
        self.assertContains(r, reverse('psa:dispatch_board'))
        self.assertContains(r, 'Good ')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PersonalisationTests(_Base):

    def _post(self, payload):
        return self.client.post(reverse('core:dashboard_layout_save'),
                                data=json.dumps(payload), content_type='application/json')

    def test_save_hide_restore(self):
        tech = self.user('tech_l2')
        self._login(tech, self.org_a)
        r = self.client.get(reverse('core:dashboard'))
        self.assertIn('my_queue', {p.key for p in r.context['grid']})
        self.assertEqual(r.context['layout_source'], 'preset')
        layout = json.loads(r.context['layout_json'])
        layout['hidden'].append('my_queue')
        layout['order'].remove('sla_overview')
        layout['order'].insert(0, 'sla_overview')
        self.assertEqual(self._post({'layout': layout}).status_code, 200)
        r = self.client.get(reverse('core:dashboard'))
        grid = [p.key for p in r.context['grid']]
        self.assertNotIn('my_queue', grid)
        self.assertEqual(grid[0], 'sla_overview')
        self.assertEqual(r.context['layout_source'], 'personal')
        self.assertEqual(self._post({'action': 'reset'}).status_code, 200)
        r = self.client.get(reverse('core:dashboard'))
        self.assertIn('my_queue', {p.key for p in r.context['grid']})
        self.assertEqual(r.context['layout_source'], 'preset')

    def test_personal_layout_never_grants(self):
        self._login(self.customer, self.org_a)
        UserProfile.objects.filter(user=self.customer).update(dashboard_layout={
            'order': ['my_queue', 'kpi_overdue', 'workload'], 'hidden': [], 'sizes': {}})
        r = self.client.get(reverse('core:dashboard'))
        keys = {p.key for p in r.context['kpis']} | {p.key for p in r.context['grid']}
        self.assertFalse(keys & {'my_queue', 'kpi_overdue', 'workload'})

    def test_classic_fallback_still_renders(self):
        for user in (self.root, self.user('tech_l1'), self.customer):
            with self.subTest(user=user.username):
                self._login(user, self.org_a)
                r = self.client.get(reverse('core:dashboard') + '?layout=classic')
                self.assertEqual(r.status_code, 200)
                self.assertTemplateUsed(r, 'core/dashboard_classic.html')

    def test_every_role_dashboard_renders(self):
        for seed in self.users:
            with self.subTest(seed=seed):
                self._login(self.user(seed), self.org_a)
                r = self.client.get(reverse('core:dashboard'))
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.context['widget_errors'], [])
                for p in r.context['grid']:
                    if p.widget.lazy:
                        w = self.client.get(reverse('core:dashboard_widget', args=[p.key]))
                        self.assertEqual(w.status_code, 200, p.key)
