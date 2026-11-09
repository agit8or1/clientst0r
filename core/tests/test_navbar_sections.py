"""Section tabs: the local navigation that replaced the long dropdowns.

Each navbar entry lands on a section page; the section's other pages are a row
of pills above the content (core/navigation.py → core/_section_tabs.html).
These tests walk every tab of every section as a superuser: the deep link
still opens, the strip is there, every sibling is linked and the current one
is marked. Then they check the gates — what a technician and a customer user
get on the same pages.
"""
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.urls import resolve, reverse

from core import navigation
from core.tests.test_navbar_grouping import ALL_FLAGS, TEST_MIDDLEWARE, NavbarTestBase


def strip(html):
    m = re.search(r'<nav class="section-tabs[^"]*"[^>]*>(.*?)</nav>', html, re.S)
    return m.group(1) if m else None


def ctx_for(user, view_name, args=(), **extra):
    """A template-context-like dict for navigation.nav_state()."""
    request = RequestFactory().get(reverse(view_name, args=args))
    request.resolver_match = resolve(request.path)
    request.user = user
    ctx = {'request': request, 'user': user, 'is_staff_user': False}
    ctx.update({f: True for f in ALL_FLAGS})
    ctx.update(extra)
    return ctx


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EveryTabOpensTests(NavbarTestBase):
    """Deep links: every tab URL still opens, and carries its section strip."""

    def setUp(self):
        super().setUp()
        self.flags(psa_ai_enabled=True)  # so the AI Inbox tab and page exist
        self.su = self.make_superuser()
        self.client.force_login(self.su)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))

    def test_every_tab(self):
        checked = 0
        for section in navigation.SECTIONS:
            for tab in section.tabs:
                if tab.modal or tab.download:
                    continue
                url = reverse(tab.url_name, args=tab.args)
                with self.subTest(section=section.key, url=url):
                    r = self.client.get(url, follow=True)
                    self.assertNotIn(r.status_code, (404, 500), url)
                    if r.status_code != 200:
                        continue
                    final = r.resolver_match.view_name if r.resolver_match else ''
                    if final != tab.url_name:
                        continue  # redirected elsewhere (e.g. a setup step)
                    checked += 1
                    html = r.content.decode()
                    if not section.render_tabs or len(section.tabs) < 2:
                        self.assertIsNone(strip(html), url)
                        continue
                    pills = strip(html)
                    self.assertIsNotNone(pills, f'{url} lost its section tabs')
                    for sibling in section.tabs:
                        if sibling.modal:
                            self.assertIn(f'data-bs-target="#{sibling.modal}"', pills)
                        else:
                            self.assertIn(
                                f'href="{reverse(sibling.url_name, args=sibling.args)}"', pills)
                    self.assertRegex(
                        pills, r'class="nav-link active" href="%s" aria-current="page"'
                        % re.escape(url))
        # Most pages render directly for a superuser with a client selected.
        self.assertGreater(checked, 50)

    def test_navbar_marks_the_current_menu_and_entry(self):
        html = self.client.get(reverse('psa:recurring_list')).content.decode()
        self.assertIn('class="nav-link dropdown-toggle active" href="#" id="psaDropdown"', html)
        self.assertRegex(html, r'class="dropdown-item active" href="%s" aria-current="page"'
                         % re.escape(reverse('psa:ticket_list')))
        self.assertIn('class="nav-link dropdown-toggle" href="#" id="opsDropdown"', html)

    def test_detail_pages_light_their_menu_without_a_strip(self):
        html = self.client.get(reverse('psa:ticket_create')).content.decode()
        self.assertIn('class="nav-link dropdown-toggle active" href="#" id="psaDropdown"', html)
        self.assertIsNone(strip(html))

    def test_help_tabs_open_the_same_modals_the_menu_did(self):
        pills = strip(self.client.get(reverse('core:help_index')).content.decode())
        self.assertIn('data-bs-target="#reportBugModal"', pills)
        self.assertIn('data-bs-target="#supportProjectModal"', pills)
        for name in ('core:about', 'core:roadmap'):
            self.assertIn(f'href="{reverse(name)}"', pills)

    def test_apps_tabs_keep_downloads_and_the_pwa_hook(self):
        pills = strip(self.client.get(reverse('core:install_app')).content.decode())
        self.assertIn('id="menu-install-pwa"', pills)
        self.assertIn(reverse('core:download_mobile_app', args=['android']), pills)
        self.assertIn(reverse('core:download_browser_extension'), pills)
        self.assertIn(reverse('core:beta_test_signup'), pills)

    def test_hardware_keeps_its_own_tabs(self):
        html = self.client.get(reverse('hardware:device_list')).content.decode()
        self.assertIn('hw-subnav', html)
        self.assertIsNone(strip(html))
        for name in ('hardware:cable_list', 'hardware:labels', 'hardware:catalog'):
            self.assertIn(reverse(name), html)
        self.assertIn(reverse('hardware:diagram', args=['connectivity']), html)


class RegistryTests(NavbarTestBase):

    def test_tab_budget(self):
        for section in navigation.SECTIONS:
            self.assertLessEqual(len(section.tabs), 7, section.key)

    def test_every_old_menu_destination_has_a_home(self):
        """Everything the pre-condensed navbar linked is a navbar entry or a tab."""
        old = [
            'psa:recurring_list', 'psa:project_template_list', 'psa:contract_list',
            'psa:quote_list', 'psa:invoice_list', 'psa:aging_report', 'psa:requisition_list',
            'psa:po_list', 'psa:back_order_list', 'psa:vendor_list', 'psa:service_catalog',
            'psa:catalog_change_list', 'psa:kb_browse', 'psa:approval_list',
            'psa:change_request_list', 'psa:problem_list', 'psa:release_list',
            'psa:workflow_rule_list', 'psa:canned_reply_list', 'psa:email_config_list',
            'psa_ai:inbox', 'inventory:item_list', 'inventory:low_stock_report',
            'inventory:tool_list', 'scheduling:wallboard_settings', 'scheduling:my_tasks',
            'scheduling:task_calendar', 'monitoring:wan_monitor_list',
            'monitoring:expiration_list', 'statuspage:list', 'netconfig:device_list',
            'vehicles:service_alert_list', 'security_alerts:connection_list',
            'security_alerts:rule_list', 'core:snyk_scans', 'crm:pipeline', 'crm:lead_list',
            'crm:opportunity_list', 'crm:campaign_list', 'crm:commission_list',
            'crm:commission_rule_list', 'reports:dashboard_list', 'reports:wallboard_list',
            'reports:template_list', 'reports:generated_list', 'hardware:cable_list',
            'hardware:labels', 'hardware:catalog', 'monitoring:network_closet_list',
            'monitoring:subnet_list', 'monitoring:vlan_list', 'assets:custom_field_list',
            'locations:floor_plan_import', 'docs:kb_approval_queue', 'docs:kb_review_queue',
            'docs:document_archived_list', 'docs:kb_analytics', 'core:system_status',
            'core:system_updates', 'core:settings_snyk', 'accounts:access_management',
            'core:webhook_list', 'resourcing:my_leave', 'resourcing:my_billable_target',
            'core:about', 'core:roadmap', 'core:beta_test_admin',
            'core:download_mobile_app', 'core:download_browser_extension',
            'core:beta_test_signup',
        ]
        missing = [n for n in old if navigation.section_for(n) is None]
        self.assertEqual(missing, [])

    def test_hardware_and_monitoring_vlans_stay_distinct(self):
        self.assertEqual(navigation.section_for('hardware:vlan_list').key, 'assets_hardware')
        self.assertEqual(navigation.section_for('monitoring:vlan_list').key, 'assets_infra')
        self.assertNotEqual(reverse('hardware:vlan_list'), reverse('monitoring:vlan_list'))
        self.assertEqual(navigation.menu_for('monitoring:rack_detail'), 'assets')
        self.assertEqual(navigation.menu_for('monitoring:website_monitor_detail'), 'ops')


class GateTests(NavbarTestBase):
    """Tabs follow the gates the old menu entries had."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.customer = User.objects.create_user('gate_cust', 'gc@x.com', 'pw')
        self.su = User.objects.create_user('gate_su', 'gs@x.com', 'pw', is_superuser=True)

    def labels(self, state):
        return [str(t['label']) for t in state['tabs']]

    def test_customer_gets_no_staff_tabs(self):
        st = navigation.nav_state(ctx_for(self.customer, 'psa:service_catalog'))
        self.assertNotIn('Approvals', self.labels(st))
        self.assertNotIn('Knowledge Base', self.labels(st))
        self.assertIn('Change Requests', self.labels(st))
        st = navigation.nav_state(ctx_for(self.customer, 'docs:document_drafts_list'))
        self.assertNotIn('KB Analytics', self.labels(st))

    def test_customer_gets_no_module_or_admin_strips(self):
        for name in ('reports:home', 'crm:home', 'security_alerts:alert_list',
                     'core:system_status', 'core:security_dashboard',
                     'integrations:integration_list', 'core:mobile_apps_admin',
                     'assets:vendor_list', 'accounts:organization_list'):
            self.assertEqual(navigation.nav_state(ctx_for(self.customer, name))['tabs'], [], name)

    def test_technician_gets_staff_tabs_but_not_superuser_ones(self):
        st = navigation.nav_state(ctx_for(self.customer, 'psa:service_catalog', is_staff_user=True))
        self.assertIn('Approvals', self.labels(st))
        st = navigation.nav_state(ctx_for(self.customer, 'accounts:organization_list',
                                          is_staff_user=True))
        self.assertEqual(st['tabs'], [])  # Access Management is superuser-only
        st = navigation.nav_state(ctx_for(self.su, 'accounts:organization_list'))
        self.assertEqual(self.labels(st), ['Organizations', 'Access Management'])

    def test_feature_flags_hide_strips(self):
        st = navigation.nav_state(ctx_for(self.su, 'crm:home', crm_enabled=False))
        self.assertEqual(st['tabs'], [])
        st = navigation.nav_state(ctx_for(self.su, 'inventory:item_list', inventory_enabled=False))
        self.assertEqual(st['tabs'], [])

    def test_ai_inbox_tab_follows_the_optional_ai_switch(self):
        from types import SimpleNamespace
        off = navigation.nav_state(ctx_for(self.su, 'psa:ticket_list',
                                           system_settings=SimpleNamespace(psa_ai_enabled=False)))
        on = navigation.nav_state(ctx_for(self.su, 'psa:ticket_list',
                                          system_settings=SimpleNamespace(psa_ai_enabled=True)))
        self.assertNotIn('AI Inbox', self.labels(off))
        self.assertIn('AI Inbox', self.labels(on))

    def test_signed_out_gets_nothing(self):
        st = navigation.nav_state(ctx_for(AnonymousUser(), 'core:about'))
        self.assertEqual(st, {'menu': '', 'section': '', 'section_label': '', 'tabs': []})
