"""
AI Troubleshoot polish (OPTIONAL AI): the installation-wide monthly cap, the
read-only command allowlist, the status endpoint behind the page's polling,
and KB / runbook matching. Providers are mocked (tests_troubleshoot base).
"""
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from core.models import SystemSetting
from docs.models import Document, DocumentCategory
from processes.models import Process
from core.models import Tag
from tech_access.testing import grant, make_tech

from .models import AIBudgetDay, AIBudgetInstallMonth, AIBudgetMonth, AIInstallationSettings, TroubleshootSession
from .services import budget, troubleshoot, troubleshoot_result
from .tests_troubleshoot import TroubleshootBase, answer


def _cap(cents):
    row = AIInstallationSettings.load()
    row.monthly_budget_cents = cents
    row.save()


class InstallationCapTests(TroubleshootBase):
    def test_no_cap_by_default_but_tracked(self):
        self.start()
        s = TroubleshootSession.objects.get()
        self.assertEqual(s.status, 'completed')
        run = s.runs.get()
        row = AIBudgetInstallMonth.objects.get(month=budget.month_start())
        self.assertEqual((row.reserved, row.spent), (0, run.actual_cost))
        self.assertIsNone(budget.installation_remaining())

    def test_cap_reached_refuses_every_customer_cleanly(self):
        _cap(0)
        r = self.start()
        self.assertEqual(r.status_code, 302)
        self.assertFalse(TroubleshootSession.objects.exists())
        self.assertEqual(self.calls, [])
        ok, reasons, _ = troubleshoot.availability(self.tech, ticket=self.ticket)
        self.assertFalse(ok)
        self.assertIn(budget.INSTALLATION_MESSAGE, reasons)
        r = self.c.post(f'/psa/ai/troubleshoot/ticket/{self.ticket.ticket_number}/',
                        {'idempotency_key': 'capkey1234'}, HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code, 429)
        self.assertIn('installation', r.json()['error'])

    def test_cap_enforced_in_reserve_and_gives_back_the_customer_reservations(self):
        _cap(1)  # 100 units of 1/100 cent
        self.policy.monthly_budget_cents = 100
        self.policy.save()
        self.assertTrue(budget.reserve(self.a, 60, 50000))
        self.assertFalse(budget.reserve(self.b, 60, 50000))  # the other customer shares the cap
        self.assertEqual(AIBudgetDay.objects.get(organization=self.b).reserved, 0)
        self.assertEqual(AIBudgetMonth.objects.get(organization=self.b).reserved, 0)
        self.assertEqual(budget.installation_refusal(60), budget.INSTALLATION_MESSAGE)
        self.assertEqual(budget.installation_refusal(40), '')
        budget.settle(self.a, 60, 30)
        install = AIBudgetInstallMonth.objects.get(month=budget.month_start())
        self.assertEqual((install.reserved, install.spent), (0, 30))
        self.assertTrue(budget.reserve(self.b, 60, 50000))
        budget.release(self.b, 60)
        install.refresh_from_db()
        self.assertEqual(install.reserved, 0)

    def test_superuser_setting_and_display(self):
        boss = make_tech('boss', superuser=True)
        c = Client()
        c.force_login(boss)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        url = reverse('psa_ai:profiles')
        r = c.post(url, {'action': 'installation', 'monthly_budget_cents': '2500',
                         'command_allowlist': 'Get-Service *\n# comment\nipconfig /all'})
        self.assertEqual(r.status_code, 302)
        row = AIInstallationSettings.load()
        self.assertEqual(row.monthly_budget_cents, 2500)
        self.assertEqual(row.updated_by, boss)
        page = c.get(url)
        self.assertContains(page, 'Installation-wide limits')
        self.assertContains(page, '2500¢')
        self.assertContains(c.get(reverse('psa_ai:policy', args=[self.a.pk])), 'Installation-wide monthly cap')
        # A pattern the denylist forbids is rejected with a reason.
        r = c.post(url, {'action': 'installation', 'monthly_budget_cents': '', 'command_allowlist': 'Restart-Service *'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'denylist')
        self.assertEqual(AIInstallationSettings.load().monthly_budget_cents, 2500)
        # Technicians can't reach the page.
        self.assertNotEqual(self.c.post(url, {'action': 'installation', 'monthly_budget_cents': ''}).status_code, 200)
        self.assertEqual(AIInstallationSettings.load().monthly_budget_cents, 2500)


class AllowlistTests(TestCase):
    STEPS = {'technician_summary': 'x', 'diagnostic_steps': [
        {'text': 'Check the spooler.', 'command': 'Get-Service Spooler'},
        {'text': 'Show the addresses.', 'command': 'IPCONFIG   /all'},
        {'text': 'List processes.', 'command': 'Get-Process'},
        {'text': 'Look at the queue in the Printers settings page.'},
        {'text': 'Stop it.', 'command': 'Stop-Service Spooler'},
    ]}

    def parse(self, allowlist=None):
        import json
        return troubleshoot_result.parse(json.dumps(self.STEPS), set(), set(), set(), allowlist=allowlist)

    def test_empty_allowlist_is_denylist_only(self):
        out = self.parse()
        self.assertEqual([s['command'] for s in out['diagnostic_steps']],
                         ['Get-Service Spooler', 'IPCONFIG   /all', 'Get-Process', ''])

    def test_installation_allowlist_narrows_commands_and_denylist_still_applies(self):
        row = AIInstallationSettings.load()
        row.command_allowlist = '# read-only checks\nget-service *\nipconfig /all\nStop-Service *'
        row.save()
        out = self.parse()
        self.assertEqual([s['command'] for s in out['diagnostic_steps']],
                         ['Get-Service Spooler', 'IPCONFIG   /all', ''])  # text-only step stays
        self.assertTrue(any('allowlist' in w for w in out['warnings']))
        self.assertTrue(any('would change the system' in w for w in out['warnings']))

    def test_patterns(self):
        pats = troubleshoot_result.parse_allowlist('  Get-Service  *\n\n#x\nping -n ? *\n')
        self.assertEqual(pats, ['get-service *', 'ping -n ? *'])
        self.assertTrue(troubleshoot_result.allowlisted('ping  -n 4 printer01', pats))
        self.assertFalse(troubleshoot_result.allowlisted('ping printer01', pats))
        self.assertTrue(troubleshoot_result.allowlist_errors('*'))
        self.assertTrue(troubleshoot_result.allowlist_errors('rm *'))
        self.assertEqual(troubleshoot_result.allowlist_errors('Get-EventLog -LogName System*'), [])


class StatusPollingTests(TroubleshootBase):
    def test_status_json_and_page_has_no_meta_refresh(self):
        from django.test import override_settings
        with override_settings(AI_GATEWAY_MODE='worker'):
            self.start()
        s = TroubleshootSession.objects.get()
        url = reverse('psa_ai:troubleshoot_status', args=[s.id])
        d = self.c.get(url).json()
        self.assertEqual(d['status'], 'running')
        self.assertFalse(d['terminal'])
        self.assertEqual([(r['status'], r['finished']) for r in d['runs']], [('dispatched', False)])
        self.assertNotIn('layers', d)  # status only: no observations or results
        page = self.c.get(reverse('psa_ai:troubleshoot_session', args=[s.id]))
        self.assertNotContains(page, 'http-equiv="refresh"')
        self.assertContains(page, 'troubleshoot_session.js')
        self.assertContains(page, 'data-ts-refresh')
        self.assertContains(page, f'data-status-url="{url}"')

    def test_status_is_scoped_and_gated(self):
        self.start()
        s = TroubleshootSession.objects.get()
        url = reverse('psa_ai:troubleshoot_status', args=[s.id])
        self.assertTrue(self.c.get(url).json()['terminal'])
        page = self.c.get(reverse('psa_ai:troubleshoot_session', args=[s.id]))
        self.assertNotContains(page, 'troubleshoot_session.js')  # finished: nothing polls
        other = make_tech('kim')
        grant(other, self.b, 'l2')
        self.assertEqual(self.sign_in(other, self.b).get(url).status_code, 404)
        st = SystemSetting.get_settings()
        st.psa_ai_enabled = False
        st.save()
        self.assertEqual(self.c.get(url).status_code, 404)


class RunbookMatchingTests(TroubleshootBase):
    def setUp(self):
        super().setUp()
        self.cat = DocumentCategory.objects.create(organization=self.a, name='Printing')
        self.tag = Tag.objects.create(organization=self.a, name='spooler', slug='spooler')

    def doc(self, title, body='', org=None, **kw):
        tags = kw.pop('tags', [])
        d = Document.objects.create(organization=org if org is not None else self.a, title=title, body=body,
                                    content_type='markdown', **kw)
        d.tags.set(tags)
        return d

    def titles(self, user=None):
        obs = troubleshoot.build_observations(user or self.tech, ticket=self.ticket)
        return [r['title'] for r in obs['runbooks']], obs

    def test_tags_category_and_body_are_scored(self):
        self.doc('Front desk printer checklist')
        self.doc('Queue reset guide', tags=[self.tag], category=self.cat)
        self.doc('Weekly notes', body='When nothing prints, check the printer driver and FRONTDESK queue.')
        self.doc('Unrelated', body='Payroll export steps.')
        self.doc('Body mentions once', body='It stopped.')  # score 1: below the bar
        titles, obs = self.titles()
        self.assertEqual(titles[0], 'Front desk printer checklist')
        self.assertIn('Queue reset guide', titles)
        self.assertIn('Weekly notes', titles)
        self.assertNotIn('Unrelated', titles)
        self.assertNotIn('Body mentions once', titles)
        by = {r['title']: r for r in obs['runbooks']}
        self.assertEqual(by['Queue reset guide']['matched_on'], ['tags'])
        self.assertEqual(by['Weekly notes']['matched_on'], ['body'])

    def test_drafts_archived_templates_and_other_customers_never_match(self):
        self.doc('Printer draft', is_draft=True)
        self.doc('Printer archived', is_archived=True)
        self.doc('Printer template', is_template=True)
        self.doc('Printer at Beta', org=self.b)
        self.doc('Printer global', org=None, is_global=True)
        Process.objects.create(organization=self.b, title='Printer runbook at Beta')
        Process.objects.create(organization=self.a, title='Printer spooler runbook')
        titles, obs = self.titles()
        self.assertEqual(sorted(titles), ['Printer global', 'Printer spooler runbook'])

    def test_technician_access_and_internal_flag(self):
        self.doc('Printer FAQ', is_client_visible=True)
        self.doc('Printer internal notes')
        self.doc('Printer global', org=None, is_global=True)
        titles, obs = self.titles()
        flags = {r['title']: r['client_visible'] for r in obs['runbooks']}
        self.assertEqual(flags['Printer FAQ'], True)
        self.assertEqual(flags['Printer internal notes'], False)
        prompt = troubleshoot.prompt_text(obs)
        self.assertIn('(customer-visible): Printer FAQ', prompt)
        self.assertIn('(internal only): Printer internal notes', prompt)
        # Without docs access at this customer only the global KB remains.
        with patch('accounts.permission_utils.has_perm_for_org', return_value=False):
            titles, _ = self.titles()
        self.assertEqual(titles, ['Printer global'])

    def test_kb_titles_withheld_by_sharing_rules(self):
        self.doc('Printer FAQ')
        self.policy.share_kb_titles = False
        self.policy.save()
        titles, obs = self.titles()
        self.assertEqual(titles, [])
        self.assertIn('kb_titles', obs['sharing']['withheld'])

    def test_session_shows_matched_runbook(self):
        self.doc('Printer spooler fix', is_client_visible=True)
        self.answers['Economy'] = answer(runbooks=[{'id': 'R1', 'why': 'matches'}])
        self.start()
        s = TroubleshootSession.objects.get()
        page = self.c.get(reverse('psa_ai:troubleshoot_session', args=[s.id]))
        self.assertContains(page, 'Printer spooler fix')
        self.assertContains(page, 'customer-visible')
