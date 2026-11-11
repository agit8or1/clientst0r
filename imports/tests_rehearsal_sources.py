"""61.6 — remaining rehearsal source types: Hudu procedures, IT Glue
domains, IT Glue non-network flexible assets. Synthetic fixtures served by
the same FakeTransport as the main rehearsal tests; nothing talks to a real
IT Glue or Hudu."""
from __future__ import annotations

import json

from assets.models import Asset
from docs.models import Document
from imports.migration import planner
from imports.migration.applier import apply_plan
from imports.migration.planner import build_plan, freeze
from imports.migration.report import build_report
from imports.migration.undo import rollback_plan
# Only the base class and fixtures: importing the test classes themselves
# would make the runner collect them twice.
from imports.tests_rehearsal import RehearsalTestBase, _attrs, hudu_routes, itglue_routes
from monitoring.models import WebsiteMonitor
from processes.models import Process, ProcessStage

TASKS = [
    {'id': 3, 'procedure_id': 1, 'name': 'Disable the account', 'description': '<p>In <b>AD</b></p>',
     'position': 2},
    {'id': 2, 'procedure_id': 1, 'name': 'Collect the laptop', 'description': '', 'position': 1},
]


def hudu_with_procedures(embedded=True):
    routes, files = hudu_routes()
    proc = {'id': 1, 'company_id': 77, 'name': 'Offboarding', 'description': 'Leaver checklist'}
    if embedded:
        proc['procedure_tasks_attributes'] = TASKS
    else:
        routes['/api/v1/procedure_tasks'] = lambda p: {'procedure_tasks': [
            t for t in TASKS if str(t['procedure_id']) == str(p.get('procedure_id'))] + [
            {'id': 9, 'procedure_id': 99, 'name': 'Someone else', 'position': 1}]}
    routes['/api/v1/procedures'] = {'procedures': [
        proc, {'id': 50, 'company_id': 12, 'name': 'Other company procedure'}]}
    return routes, files


def itglue_with_domains_and_flex():
    routes, files = itglue_routes()
    routes['/domains'] = {'data': [
        _attrs('domains', 'DOM1', name='acme.test', **{'registrar-name': 'Gandi', 'expires-on': '2027-03-01'}),
        _attrs('domains', 'DOM2', name='acme-old.test'),
        _attrs('domains', 'DOM-OTHER', name='other.test', **{'organization-id': 555}),
        _attrs('domains', 'DOM-BAD', name='not a domain'),
    ]}
    flex = routes['/flexible_assets']
    routes['/flexible_assets'] = lambda p: (
        {'data': [_attrs('flexible-assets', 'FA2', name='Office 365', traits={
            'seats': 20, 'license-type': {'values': [{'id': 1, 'name': 'E3'}]},
            'admin-password': 'hunter2-flex', 'serial': 'LIC-1'})]}
        if str(p.get('filter[flexible_asset_type_id]')) == '2' else flex(p))
    routes['/flexible_assets/FA2/relationships/attachments'] = {'data': []}
    return routes, files


class HuduProcedureTests(RehearsalTestBase):

    def hudu_plan(self, routes_files):
        plan = self.make_plan(self.org_a, system='hudu', host='hudu-a.test', source_org='77')
        self.stage(plan, routes_files)
        return plan

    def test_procedure_becomes_runbook_with_ordered_steps_and_rolls_back(self):
        plan = self.hudu_plan(hudu_with_procedures())
        item = self.item(plan, 'procedure', '1')
        self.assertEqual((item.target_kind, item.category), ('process', 'create'))
        self.assertFalse(plan.staged.filter(source_type='procedure', source_id='50').exists())
        freeze(plan, self.user)
        counts = apply_plan(plan, self.user)
        self.assertEqual(counts['failed'], 0)
        proc = Process.objects.get(organization=self.org_a, title='Offboarding')
        self.assertEqual(proc.description, 'Leaver checklist')
        steps = list(proc.stages.order_by('order').values_list('title', 'description'))
        self.assertEqual(steps, [('Collect the laptop', ''), ('Disable the account', 'In AD')])
        report = build_report(plan)
        rows = {r['kind']: r for r in report['summary']}
        self.assertEqual(rows['process']['applied'], 1)

        # Rerun with the same source: nothing to do.
        plan2 = self.hudu_plan(hudu_with_procedures())
        self.assertEqual(self.item(plan2, 'procedure', '1').category, 'unchanged')

        rollback_plan(plan, self.user)
        self.assertFalse(Process.objects.filter(pk=proc.pk).exists())
        self.assertFalse(ProcessStage.objects.filter(process_id=proc.pk).exists())

    def test_rollback_keeps_runbook_with_edited_step(self):
        plan = self.hudu_plan(hudu_with_procedures())
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        proc = Process.objects.get(organization=self.org_a, title='Offboarding')
        stage = proc.stages.get(order=1)
        stage.title = 'Collect the laptop and charger'
        stage.save()
        report = rollback_plan(plan, self.user)
        self.assertFalse(report['complete'])
        self.assertTrue(Process.objects.filter(pk=proc.pk).exists())
        self.assertEqual(list(proc.stages.values_list('title', flat=True)), ['Collect the laptop and charger'])
        self.assertTrue(any('ProcessStage' in line for line in report['kept']), report['kept'])

    def test_tasks_from_task_endpoint_scoped_to_the_procedure(self):
        plan = self.hudu_plan(hudu_with_procedures(embedded=False))
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        proc = Process.objects.get(organization=self.org_a, title='Offboarding')
        self.assertEqual(list(proc.stages.order_by('order').values_list('title', flat=True)),
                         ['Collect the laptop', 'Disable the account'])

    def test_operator_maps_procedures_to_documents_or_skips(self):
        plan = self.hudu_plan(hudu_with_procedures())
        planner.set_type_override(plan, 'hudu_procedures', 'all procedures', 'document')
        build_plan(plan)
        self.assertEqual(self.item(plan, 'procedure', '1').target_kind, 'document')
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        doc = Document.objects.get(organization=self.org_a, title='Offboarding')
        self.assertLess(doc.body.index('Collect the laptop'), doc.body.index('Disable the account'))
        self.assertFalse(Process.objects.filter(organization=self.org_a).exists())

        plan2 = self.make_plan(self.org_b, system='hudu', host='hudu-a.test', source_org='77')
        self.stage(plan2, hudu_with_procedures())
        planner.set_type_override(plan2, 'hudu_procedures', 'all procedures', 'skip')
        build_plan(plan2)
        self.assertEqual(self.item(plan2, 'procedure', '1').category, 'unavailable')
        with self.assertRaises(planner.PlanError):
            planner.set_type_override(plan2, 'hudu_procedures', 'all procedures', 'ticket')


class ITGlueDomainTests(RehearsalTestBase):

    def test_domains_become_disabled_monitors_with_expiry(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_with_domains_and_flex())
        self.assertFalse(plan.staged.filter(source_id='DOM-OTHER').exists())
        self.assertEqual(self.item(plan, 'domain', 'DOM-BAD').category, 'unavailable')
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        mon = WebsiteMonitor.objects.get(organization=self.org_a, url='https://acme.test')
        self.assertEqual((mon.name, mon.domain_registrar, mon.is_enabled), ('acme.test', 'Gandi', False))
        self.assertEqual(mon.domain_expires_at.date().isoformat(), '2027-03-01')
        self.assertIsNone(WebsiteMonitor.objects.get(url='https://acme-old.test').domain_expires_at)
        plan2 = self.make_plan(self.org_a)
        self.stage(plan2, itglue_with_domains_and_flex())
        self.assertEqual(self.item(plan2, 'domain', 'DOM1').category, 'unchanged')

    def test_existing_monitor_with_other_url_form_is_a_duplicate(self):
        existing = WebsiteMonitor.objects.create(organization=self.org_a, name='Acme site',
                                                 url='http://acme.test/')
        WebsiteMonitor.objects.create(organization=self.org_b, name='Other customer', url='https://acme-old.test')
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_with_domains_and_flex())
        dom1 = self.item(plan, 'domain', 'DOM1')
        self.assertEqual((dom1.category, dom1.target_id), ('duplicate', existing.pk))
        # The other customer's monitor never matches.
        self.assertEqual(self.item(plan, 'domain', 'DOM2').category, 'create')


class ITGlueFlexibleAssetTests(RehearsalTestBase):

    def test_unmapped_type_is_skipped_with_a_hint(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_with_domains_and_flex())
        item = self.item(plan, 'flexible_asset', 'FA2')
        self.assertEqual(item.category, 'unavailable')
        self.assertIn('Type mapping', item.reason)

    def test_type_mapped_to_document(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_with_domains_and_flex())
        planner.set_type_override(plan, 'itglue_flexible_types', 'Licensing', 'document')
        build_plan(plan)
        item = self.item(plan, 'flexible_asset', 'FA2')
        self.assertEqual((item.target_kind, item.category), ('document', 'create'))
        self.assertIn('admin-password (secret trait)', item.skipped_fields)
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        doc = Document.objects.get(organization=self.org_a, title='Licensing: Office 365')
        self.assertIn('E3', doc.body)
        self.assertNotIn('hunter2-flex', doc.body)
        report = rollback_plan(plan, self.user)
        self.assertTrue(report['complete'], report['kept'])
        self.assertFalse(Document.objects.filter(pk=doc.pk).exists())

    def test_type_mapped_to_asset_with_custom_fields(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_with_domains_and_flex())
        planner.set_type_override(plan, 'itglue_flexible_types', 'Licensing', 'asset')
        build_plan(plan)
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        asset = Asset.objects.get(organization=self.org_a, name='Office 365')
        self.assertEqual(asset.serial_number, 'LIC-1')
        cf = asset.custom_fields
        self.assertEqual((cf['seats'], cf['license_type'], cf['flexible_asset_type']), ('20', 'E3', 'Licensing'))
        self.assertNotIn('hunter2-flex', json.dumps(cf))
        self.assertNotIn('admin_password', cf)
