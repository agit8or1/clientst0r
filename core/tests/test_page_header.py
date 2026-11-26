"""Increment 113.8: one page header, shared vocabulary, section tab strip rule.

* The busiest pages render their title through the shared page header
  (templates/core/_page_header.html, {% page_header %}): exactly one <h1>,
  inside <header class="page-header">.
* "PSA" no longer appears in breadcrumbs or <title> of the main Service Desk
  and billing pages; the sidebar section for the MSP's customers is "Customers".
* The saved-views strip is not drawn when it has nothing to show.
* The section tab strip stays in the HTML (no server change); showing it only
  for the icon rail and phones is a CSS rule that is checked as text.
"""
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from core.tests.test_nav_overhaul import trail
from core.tests.test_page_budgets import PageBudgetBase

H1 = re.compile(r'<h1[\s>]')
TITLE = re.compile(r'<title>(.*?)</title>', re.S)


class PageHeaderTagTests(SimpleTestCase):

    def render(self, source, **ctx):
        return Template('{% load page_header %}' + source).render(Context(ctx))

    def test_renders_one_h1_with_slots(self):
        html = self.render(
            '{% page_header title=t icon="fas fa-box" title_suffix=s eyebrow="Eyebrow" %}'
            '{% ph_lead %}<img alt="" src="/x.png">{% end_ph_lead %}'
            '{% ph_badges %}<span class="badge">B</span>{% end_ph_badges %}'
            '{% ph_subtitle %}<b>Sub</b>{% end_ph_subtitle %}'
            '<a class="btn btn-primary" href="/go/">Go</a>{% endpage_header %}',
            t='My <title>', s='filtered')
        self.assertEqual(len(H1.findall(html)), 1)
        self.assertIn('My &lt;title&gt;', html)
        self.assertIn('page-header__title-suffix', html)
        self.assertIn('<b>Sub</b>', html)
        self.assertIn('page-header__actions', html)
        self.assertIn('page-header__lead', html)
        self.assertIn('badge', html)
        self.assertIn('Eyebrow', html)

    def test_minimal_header_has_no_empty_regions(self):
        html = self.render('{% page_header title="Only a title" %}{% endpage_header %}')
        self.assertEqual(len(H1.findall(html)), 1)
        for region in ('page-header__actions', 'page-header__sub', 'page-header__lead', 'page-header__eyebrow'):
            self.assertNotIn(region, html)

    def test_breadcrumb_argument(self):
        html = self.render('{% page_header title="T" breadcrumb=crumbs %}{% endpage_header %}',
                           crumbs=[('Home', '/'), ('Here', '')])
        self.assertIn('aria-current="page"', html)
        self.assertIn('href="/"', html)

    def test_title_is_required(self):
        from django.template import TemplateSyntaxError
        with self.assertRaises(TemplateSyntaxError):
            self.render('{% page_header icon="x" %}{% endpage_header %}')


@override_settings(AGIT8OR_CONNECT_ENABLED=True)
class BusyPagesUseThePageHeaderTests(PageBudgetBase):
    """Each of the ten busiest pages has exactly one <h1>, drawn by the component."""

    def setUp(self):
        super().setUp()
        from assets.models import Asset
        self.ticket = self.tickets(2, org=self.orgs[0])[0]
        self.asset = Asset.objects.create(organization=self.orgs[0], name='Header test switch', hostname='hdr.local')
        self.login(self.superuser, self.orgs[0])

    def pages(self):
        return {
            'ticket list': reverse('psa:ticket_list'),
            'ticket detail': reverse('psa:ticket_detail', args=[self.ticket.ticket_number]),
            'my work': reverse('psa:my_work'),
            'customer workspace': reverse('accounts:organization_detail', args=[self.orgs[0].id]),
            'asset list': reverse('assets:asset_list'),
            'asset detail': reverse('assets:asset_detail', args=[self.asset.pk]),
            'documents': reverse('docs:document_list'),
            'password vault': reverse('vault:password_list'),
            'invoices': reverse('psa:invoice_list'),
            'billing review': reverse('psa:billing_review'),
            'reports home': reverse('reports:home'),
        }

    def test_one_h1_from_the_component(self):
        for label, url in self.pages().items():
            with self.subTest(page=label):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                html = response.content.decode()
                self.assertEqual(len(H1.findall(html)), 1, f'{label}: expected one <h1>')
                header = re.search(r'<header class="page-header[^"]*">(.*?)</header>', html, re.S)
                self.assertIsNotNone(header, f'{label}: no page header')
                self.assertEqual(len(H1.findall(header.group(1))), 1, f'{label}: the h1 is outside the header')
                self.assertIn('page-header__title', header.group(1))

    def test_converted_list_pages_have_one_h1(self):
        """Pages that had no <h1> (the title was an h2) and now use the component."""
        names = ('canned_reply_list', 'service_catalog', 'project_list', 'recurring_list', 'kb_browse',
                 'contract_list', 'email_config_list', 'quote_list', 'workflow_rule_list', 'requisition_list',
                 'po_list', 'back_order_list', 'vendor_list', 'problem_list', 'release_list')
        for name in names:
            with self.subTest(page=name):
                response = self.client.get(reverse('psa:' + name))
                self.assertEqual(response.status_code, 200, name)
                html = response.content.decode()
                self.assertEqual(len(H1.findall(html)), 1, name)
                self.assertIn('class="page-header', html, name)

    def test_page_header_stylesheet_is_loaded(self):
        html = self.client.get(reverse('psa:ticket_list')).content.decode()
        self.assertIn('css/page_header.css', html)


@override_settings(AGIT8OR_CONNECT_ENABLED=True)
class VocabularyTests(PageBudgetBase):
    """Service Desk and Customers, not PSA / Clients, in what users read first."""

    def setUp(self):
        super().setUp()
        self.ticket = self.tickets(1, org=self.orgs[0])[0]
        self.login(self.superuser, self.orgs[0])

    def test_no_psa_in_breadcrumbs_or_titles_of_the_main_pages(self):
        urls = [reverse('psa:ticket_list'), reverse('psa:my_work'), reverse('psa:ticket_create'),
                reverse('psa:ticket_detail', args=[self.ticket.ticket_number]),
                reverse('psa:invoice_list'), reverse('psa:billing_review'), reverse('psa:quote_list'),
                reverse('psa:contract_list'), reverse('psa:aging_report'), reverse('psa:project_list'),
                reverse('psa:service_catalog'), reverse('reports:psa_reports_list'),
                reverse('psa:approval_list')]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                html = response.content.decode()
                crumbs = trail(html)
                self.assertFalse([c for c in crumbs if re.search(r'\bPSA\b(?!-)', c)], (url, crumbs))
                title = TITLE.search(html)
                self.assertIsNotNone(title)
                self.assertNotRegex(title.group(1), r'\bPSA\b(?!-)', url)

    def test_the_customers_section_is_called_customers(self):
        html = self.client.get(reverse('core:dashboard')).content.decode()
        sidebar = html[html.index('id="appNav"'):]
        labels = re.findall(r'app-nav__text">\s*([^<]+?)\s*<', sidebar)
        self.assertIn('Customers', labels)
        self.assertNotIn('Clients', labels)
        self.assertNotIn('PSA', labels)

    def test_customer_list_page_uses_customer_wording(self):
        html = self.client.get(reverse('accounts:organization_list')).content.decode()
        self.assertEqual(TITLE.search(html).group(1).split(' - ')[0].strip(), 'Customers')
        self.assertIn('Create Customer', html)
        self.assertNotIn('Create Organization', html)

    def test_navigation_labels(self):
        from core.navigation import PRIMARY
        labels = {str(g.label) for g in PRIMARY}
        self.assertIn('Customers', labels)
        self.assertNotIn('Clients', labels)


class SavedViewsAndTabStripTests(PageBudgetBase):

    def test_saved_views_strip_has_no_empty_hint_sentence(self):
        self.login(self.superuser, self.orgs[0])
        for url in (reverse('psa:ticket_list'), reverse('assets:asset_list'), reverse('psa:invoice_list')):
            html = self.client.get(url).content.decode()
            self.assertNotIn('saved-views__hint', html, url)

    def test_saved_views_strip_is_inside_the_page_frame(self):
        self.login(self.superuser, self.orgs[0])
        html = self.client.get(reverse('psa:ticket_list')).content.decode()
        if 'id="savedViews"' in html:
            frame = html.index('class="page-frame')
            self.assertGreater(html.index('id="savedViews"'), frame)
            self.assertLess(html.index('id="savedViews"'), html.index('<header class="page-header'))

    def test_tab_strip_is_a_css_rule_not_a_server_change(self):
        """The tabs stay in the HTML (for the rail and phones); the stylesheet
        hides them while the full sidebar lists the same pages."""
        self.login(self.superuser, self.orgs[0])
        html = self.client.get(reverse('psa:ticket_list')).content.decode()
        self.assertIn('data-section-tabs', html)
        css = (Path(settings.BASE_DIR) / 'static' / 'css' / 'navigation.css').read_text()
        self.assertRegex(css, r'body:not\(\.appnav-rail\) \.page-frame \.section-tabs\s*\{\s*display:\s*none')
        self.assertRegex(css, r'@media \(min-width: 768px\)')
