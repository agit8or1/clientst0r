"""Tests for the one-customer IT Glue / Hudu migration rehearsal.

All source data is synthetic and served by ``FakeTransport`` (recorded-style
API payloads); no test talks to a real IT Glue or Hudu. Two customers are
set up with colliding names and colliding source identifiers (the same IDs
from a different source account) to prove nothing is matched across
customers or accounts.
"""
from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, Contact, Relationship
from audit.models import AuditLog
from core.models import Organization
from docs.models import Document
from files.models import Attachment
from imports.migration import planner, tasks
from imports.migration.applier import apply_plan
from imports.migration.planner import PlanChanged, PlanError, build_plan, freeze
from imports.migration.report import build_report, records_csv, summary_csv
from imports.migration.sources import stager_for
from imports.migration.targets import SPECS
from imports.migration.tasks import run_pending
from imports.migration.transport import DownloadRejected, SourceUnavailable
from imports.migration.undo import rollback_plan
from imports.models import (ImportJob, ImportMapping, MigrationPlan, PlanChange, PlanItem,
                            SourceMapping, StagedRecord)
from locations.models import Location
from monitoring.models import VLAN, IPAddress, Subnet, WebsiteMonitor
from vault.models import Password, PasswordRelation

User = get_user_model()

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

PDF = b'%PDF-1.4\n% synthetic test file\n'
SECRET = 'Acme-S3cret!'
OTP = 'JBSWY3DPEHPK3PXP'
HUDU_SECRET = 'Hudu-Pa55!'
HUDU_CONFIDENTIAL = 'HuduConf1dential!'


class FakeTransport:
    """Serves recorded-style payloads by path. Unknown paths are a 404."""

    def __init__(self, routes, files=None):
        self.routes = routes
        self.files = files or {}
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append(('json', path, dict(params or {})))
        route = self.routes.get(path)
        if route is None:
            raise SourceUnavailable('api_gap', 'HTTP 404', status=404)
        if isinstance(route, Exception):
            raise route
        if callable(route):
            route = route(params or {})
        return copy.deepcopy(route)

    def get_bytes(self, url, max_bytes):
        self.calls.append(('bytes', url))
        if url not in self.files:
            raise DownloadRejected('download returned HTTP 404')
        content, ctype = self.files[url]
        if len(content) > max_bytes:
            raise DownloadRejected('file exceeds the size limit')
        return content, ctype


def _attrs(kind, sid, **attrs):
    attrs.setdefault('organization-id', 101)
    return {'id': str(sid), 'type': kind, 'attributes': attrs}


def itglue_routes(host='itglue-a.test', hostname='acme-dc01', model='R740', doc_name='Backup runbook'):
    """One IT Glue organization (101). The same IDs are used for every host."""
    flex = {
        '1': {'data': [_attrs('flexible-assets', 'FA1', name='LAN', traits={
            'name': 'Office LAN', 'network': '10.0.0.0/24', 'gateway': '10.0.0.1', 'vlan': '10',
            'location': {'values': [{'id': 'L1', 'name': 'HQ'}]}})]},
        '2': {'data': [_attrs('flexible-assets', 'FA2', name='Office 365', traits={'seats': 20})]},
    }
    empty = {'data': []}
    routes = {
        '/organizations/101': {'data': {'id': '101', 'attributes': {'name': 'Acme Dental'}}},
        '/locations': {'data': [_attrs('locations', 'L1', name='HQ', **{
            'address-1': '1 Main St', 'city': 'Springfield', 'region-name': 'IL',
            'postal-code': '62701', 'country-name': 'United States', 'primary': True})]},
        '/contacts': {'data': [
            _attrs('contacts', 'C1', **{'first-name': 'Jane', 'last-name': 'Doe', 'title': 'Office Manager',
                                       'location-id': 'L1',
                                       'contact-emails': [{'value': 'jane@acme.test', 'primary': True}],
                                       'contact-phones': [{'value': '555-0100', 'primary': True}]}),
            _attrs('contacts', 'C2', **{'first-name': 'Bob', 'last-name': 'Stone', 'location-id': '999'}),
        ]},
        '/configurations': {'data': [
            _attrs('configurations', 'CFG1', name='ACME-DC01', **{
                'configuration-type-name': 'Server', 'serial-number': 'SN1', 'hostname': hostname,
                'model-name': model, 'primary-ip': '10.0.0.10', 'contact-id': 'C1', 'location-id': 'L1'}),
            _attrs('configurations', 'CFG2', name='ACME-FW', **{'configuration-type-name': 'Firewall',
                                                                'primary-ip': 'not-an-ip'}),
            # A record of another organization the filter failed to remove.
            _attrs('configurations', 'CFG-OTHER', name='OTHER-ORG-PC', **{'organization-id': 555}),
        ]},
        '/passwords': {'data': [
            _attrs('passwords', 'P1', name='Domain Admin', username='ACME\\administrator', password=SECRET,
                   url='https://acme-dc01.acme.test', **{'resource-type': 'Configuration',
                                                       'resource-id': 'CFG1', 'otp-secret': OTP}),
            _attrs('passwords', 'P2', name='Restricted vault item', username='svc'),
        ]},
        '/passwords/P2': SourceUnavailable('permission', 'HTTP 403', status=403),
        '/documents': {'data': [_attrs('documents', 'D1', name=doc_name, body='# Backups\nNightly.')]},
        '/flexible_asset_types': {'data': [{'id': '1', 'attributes': {'name': 'Network'}},
                                           {'id': '2', 'attributes': {'name': 'Licensing'}}]},
        '/flexible_assets': lambda p: flex[str(p.get('filter[flexible_asset_type_id]'))],
        '/configurations/CFG1/relationships/related_items': {'data': [
            {'id': 'R1', 'attributes': {'destination-type': 'Document', 'destination-id': 'D1',
                                        'destination-name': doc_name, 'notes': 'runbook'}}]},
        '/configurations/CFG2/relationships/related_items': empty,
        '/configurations/CFG1/relationships/attachments': {'data': [
            {'id': 'A1', 'attributes': {'attachment-file-name': 'diagram.pdf',
                                        'attachment-content-type': 'application/pdf',
                                        'attachment-file-size': len(PDF),
                                        'download-url': f'https://{host}/attachments/A1'}},
            {'id': 'A2', 'attributes': {'attachment-file-name': 'evil.exe', 'attachment-file-size': 10,
                                        'download-url': f'https://{host}/attachments/A2'}},
        ]},
        '/configurations/CFG2/relationships/attachments': empty,
        '/documents/D1/relationships/attachments': {'data': [
            {'id': 'A3', 'attributes': {'attachment-file-name': 'huge.pdf', 'attachment-file-size': 10 ** 10,
                                        'download-url': f'https://{host}/attachments/A3'}}]},
        '/passwords/P1/relationships/attachments': empty,
        '/passwords/P2/relationships/attachments': empty,
        '/flexible_assets/FA1/relationships/attachments': empty,
    }
    files = {f'https://{host}/attachments/A1': (PDF, 'application/pdf'),
             f'https://{host}/attachments/A2': (b'MZ\x90\x00', 'application/octet-stream')}
    return routes, files


def hudu_routes(host='hudu-a.test'):
    company = 77
    return {
        '/api/v1/companies/77': {'company': {'id': company, 'name': 'Globex', 'address_line_1': '9 Dock Rd',
                                             'city': 'Portsmouth', 'zip': '03801', 'country_name': 'United States',
                                             'phone_number': '555-0199'}},
        '/api/v1/assets': {'assets': [
            {'id': 501, 'company_id': company, 'name': 'GLX-SRV', 'asset_layout_name': 'Server', 'fields': [
                {'label': 'Serial Number', 'value': 'S-1'}, {'label': 'IP Address', 'value': '10.1.0.5'},
                {'label': 'Admin Password', 'value': HUDU_CONFIDENTIAL, 'field_type': 'Password'}]},
            {'id': 502, 'company_id': company, 'name': 'Ann Smith', 'asset_layout_name': 'People', 'fields': [
                {'label': 'Email', 'value': 'ann@globex.test'}, {'label': 'Phone', 'value': '555-0111'}]},
            {'id': 503, 'company_id': company, 'name': 'Main Site', 'asset_layout_name': 'Locations', 'fields': [
                {'label': 'Address 1', 'value': '10 Harbor Way'}, {'label': 'City', 'value': 'Portsmouth'},
                {'label': 'Zip', 'value': '03801'}]},
            {'id': 999, 'company_id': 12, 'name': 'Someone else', 'asset_layout_name': 'Server'},
        ]},
        '/api/v1/asset_passwords': {'asset_passwords': [
            {'id': 601, 'company_id': company, 'name': 'SRV admin', 'username': 'root', 'password': HUDU_SECRET,
             'otp_secret': OTP, 'passwordable_type': 'Asset', 'passwordable_id': 501}]},
        '/api/v1/articles': {'articles': [{'id': 701, 'company_id': company, 'name': 'Runbook',
                                           'content': '<p>Steps</p>'}]},
        '/api/v1/websites': {'websites': [{'id': 801, 'company_id': company, 'name': 'globex.test'}]},
        '/api/v1/networks': {'networks': [{'id': 901, 'company_id': company, 'name': 'Server LAN',
                                           'address': '10.1.0.0/24', 'location_id': 503, 'vlan_id': 5}]},
        '/api/v1/ip_addresses': {'ip_addresses': [{'id': 951, 'company_id': company, 'address': '10.1.0.5',
                                                   'status': 'assigned', 'network_id': 901, 'asset_id': 501}]},
        '/api/v1/relations': {'relations': [
            {'id': 1, 'fromable_type': 'Asset', 'fromable_id': 501, 'toable_type': 'Article', 'toable_id': 701},
            {'id': 2, 'fromable_type': 'Asset', 'fromable_id': 9999, 'toable_type': 'Article', 'toable_id': 8888},
        ]},
        '/api/v1/uploads': {'uploads': [
            {'id': 1001, 'name': 'invoice.pdf', 'mime': 'application/pdf', 'size': len(PDF),
             'uploadable_type': 'Asset', 'uploadable_id': 501, 'url': f'https://{host}/uploads/1001'},
            {'id': 1002, 'name': 'other.pdf', 'mime': 'application/pdf', 'size': len(PDF),
             'uploadable_type': 'Asset', 'uploadable_id': 999, 'url': f'https://{host}/uploads/1002'},
        ]},
        '/api/v1/procedures': {'procedures': [{'id': 1, 'company_id': company, 'name': 'Onboarding'}]},
    }, {f'https://{host}/uploads/1001': (PDF, 'application/pdf')}


class RehearsalTestBase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='rehearsal-media-')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('migrator', 'm@example.com', 'pw', is_superuser=True)
        self.org_a = Organization.objects.create(name='Acme Dental', slug='acme-dental')
        self.org_b = Organization.objects.create(name='Acme Dental (Branch)', slug='acme-dental-branch')
        VLAN.objects.create(organization=self.org_a, vlan_id=10, name='Office')

    def make_plan(self, org, system='itglue', host='itglue-a.test', source_org='101'):
        job = ImportJob.objects.create(source_type=system, source_url=f'https://{host}',
                                       source_api_key=f'KEY-{host}-do-not-leak', target_organization=org,
                                       started_by=self.user, dry_run=True)
        return MigrationPlan.objects.create(import_job=job, source_account=host,
                                            source_organization_id=source_org)

    def stage(self, plan, routes_files):
        routes, files = routes_files
        transport = FakeTransport(routes, files)
        stager_for(plan, transport).stage()
        build_plan(plan)
        plan.refresh_from_db()
        return transport

    def run_full(self, org, host='itglue-a.test', **kw):
        plan = self.make_plan(org, host=host)
        self.stage(plan, itglue_routes(host=host, **kw))
        freeze(plan, self.user)
        counts = apply_plan(plan, self.user)
        plan.refresh_from_db()
        return plan, counts

    def item(self, plan, source_type, source_id):
        return plan.items.get(source_type=source_type, source_id=source_id)

    def counts(self, org):
        return {
            'location': Location.objects.filter(organization=org).count(),
            'contact': Contact.objects.filter(organization=org).count(),
            'asset': Asset.objects.filter(organization=org).count(),
            'network': Subnet.objects.filter(organization=org).count(),
            'password': Password.objects.filter(organization=org).count(),
            'document': Document.objects.filter(organization=org).count(),
            'relationship': Relationship.objects.filter(organization=org).count(),
            'attachment': Attachment.objects.filter(organization=org).count(),
        }


class StagingAndPlanTests(RehearsalTestBase):

    def test_plan_counts_before_writing(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        rows = {r['kind']: r for r in planner.summary(plan)['rows']}
        self.assertEqual(rows['location']['create'], 1)
        self.assertEqual(rows['contact']['create'], 2)
        self.assertEqual(rows['contact']['broken_links'], 1)  # Bob -> location 999
        self.assertEqual(rows['asset']['create'], 2)
        self.assertEqual(rows['asset']['unavailable'], 1)      # flexible asset type "Licensing"
        self.assertEqual(rows['network']['create'], 1)
        self.assertEqual(rows['password']['create'], 1)
        self.assertEqual(rows['password']['unavailable'], 1)   # value not readable (403)
        self.assertEqual(rows['document']['create'], 1)
        self.assertEqual(rows['relation']['create'], 1)
        self.assertEqual(rows['attachment']['create'], 1)
        self.assertEqual(rows['attachment']['unavailable'], 2)  # .exe and oversized
        # Nothing written to the customer yet.
        self.assertEqual(sum(self.counts(self.org_a).values()), 0)
        self.assertEqual(Contact.objects.count(), 0)
        # The other organization's record that slipped past the filter was dropped.
        self.assertFalse(plan.staged.filter(source_id='CFG-OTHER').exists())
        reasons = {i.source_id: i.reason for i in plan.items.filter(category='unavailable')}
        self.assertIn('permissions', reasons['P2'])
        self.assertIn('not allowed', reasons['A2'])
        self.assertIn('limit', reasons['A3'])
        # Network picked up the location name and the existing VLAN.
        net = self.item(plan, 'flexible_asset', 'FA1')
        self.assertEqual(net.proposed['location'], 'HQ')
        self.assertEqual(net.proposed['vlan_id'], VLAN.objects.get(organization=self.org_a).pk)

    def test_secrets_never_in_raw_staging_or_plan(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        for rec in plan.staged.all():
            self.assertNotIn(SECRET, json.dumps(rec.raw))
            self.assertNotIn(OTP, json.dumps(rec.raw))
        for item in plan.items.all():
            self.assertNotIn(SECRET, json.dumps([item.proposed, item.before, item.links]))
        p1 = plan.staged.get(source_type='password', source_id='P1')
        self.assertEqual(p1.secret_data, {'password': SECRET, 'otp_secret': OTP})
        with connection.cursor() as cur:
            cur.execute('SELECT secret_data FROM import_staged_records')
            stored = [row[0] or '' for row in cur.fetchall()]
        self.assertTrue(all(SECRET not in s and OTP not in s for s in stored))
        self.assertTrue(any(s.startswith('enc2$') for s in stored))
        self.assertEqual(self.item(plan, 'password', 'P1').proposed['password'], '[secret]')

    def test_no_network_during_apply(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        with mock.patch('imports.migration.transport.RequestsTransport.get_json',
                        side_effect=AssertionError('network used during apply')), \
                mock.patch('requests.Session.request', side_effect=AssertionError('network used')):
            counts = apply_plan(plan, self.user)
        self.assertEqual(counts['failed'], 0)


class ApplyTests(RehearsalTestBase):

    def test_apply_creates_records_with_relationships(self):
        plan, counts = self.run_full(self.org_a)
        self.assertEqual(plan.status, 'applied')
        self.assertEqual(counts['failed'], 0)
        self.assertEqual(plan.import_job.status, 'completed')
        self.assertFalse(plan.import_job.dry_run)
        c = self.counts(self.org_a)
        self.assertEqual(c, {'location': 1, 'contact': 2, 'asset': 2, 'network': 1, 'password': 1,
                             'document': 1, 'relationship': 3, 'attachment': 1})
        jane = Contact.objects.get(organization=self.org_a, email='jane@acme.test')
        hq = Location.objects.get(organization=self.org_a, name='HQ')
        self.assertTrue(hq.is_primary)
        dc = Asset.objects.get(organization=self.org_a, serial_number='SN1')
        self.assertEqual(dc.primary_contact, jane)
        self.assertEqual(dc.asset_type, 'server')
        self.assertTrue(Relationship.objects.filter(source_type='contact', source_id=jane.pk,
                                                    target_type='location', target_id=hq.pk).exists())
        self.assertTrue(Relationship.objects.filter(source_type='asset', source_id=dc.pk,
                                                    target_type='location', target_id=hq.pk).exists())
        doc = Document.objects.get(organization=self.org_a)
        self.assertTrue(Relationship.objects.filter(source_type='asset', source_id=dc.pk,
                                                    target_type='document', target_id=doc.pk).exists())
        pw = Password.objects.get(organization=self.org_a)
        self.assertNotIn(SECRET, pw.encrypted_password)
        self.assertEqual(pw.get_password(), SECRET)
        self.assertEqual(pw.get_otp_secret(), OTP)
        self.assertTrue(PasswordRelation.objects.filter(password=pw, relation_type='asset',
                                                        relation_id=dc.pk).exists())
        net = Subnet.objects.get(organization=self.org_a)
        self.assertEqual((net.network, net.location, net.vlan.vlan_id), ('10.0.0.0/24', 'HQ', 10))
        att = Attachment.objects.get(organization=self.org_a)
        self.assertEqual((att.entity_type, att.entity_id, att.original_filename),
                         ('asset', dc.pk, 'diagram.pdf'))
        with att.file.open('rb') as fh:
            self.assertEqual(fh.read(), PDF)
        # Legacy job bookkeeping is kept in step.
        self.assertTrue(ImportMapping.objects.filter(import_job=plan.import_job, target_model='Asset').exists())

    def test_rerun_is_idempotent(self):
        self.run_full(self.org_a)
        before = self.counts(self.org_a)
        plan2 = self.make_plan(self.org_a)
        self.stage(plan2, itglue_routes())
        cats = set(plan2.items.values_list('category', flat=True))
        self.assertEqual(cats, {'unchanged', 'unavailable'})
        freeze(plan2, self.user)
        counts = apply_plan(plan2, self.user)
        self.assertEqual(counts['applied'], 0)
        self.assertEqual(PlanChange.objects.filter(plan=plan2).count(), 0)
        self.assertEqual(self.counts(self.org_a), before)

    def test_source_change_updates_only_changed_fields(self):
        self.run_full(self.org_a)
        plan2 = self.make_plan(self.org_a)
        self.stage(plan2, itglue_routes(hostname='acme-dc01-new'))
        item = self.item(plan2, 'configuration', 'CFG1')
        self.assertEqual(item.category, 'update')
        self.assertEqual(item.changed_fields, ['hostname'])
        freeze(plan2, self.user)
        apply_plan(plan2, self.user)
        self.assertEqual(Asset.objects.get(organization=self.org_a, serial_number='SN1').hostname,
                         'acme-dc01-new')

    def test_local_edit_plus_source_change_is_a_conflict(self):
        self.run_full(self.org_a)
        dc = Asset.objects.get(organization=self.org_a, serial_number='SN1')
        dc.hostname = 'tech-chosen'
        dc.save()
        plan2 = self.make_plan(self.org_a)
        self.stage(plan2, itglue_routes(hostname='source-new'))
        item = self.item(plan2, 'configuration', 'CFG1')
        self.assertEqual((item.category, item.action), ('conflict', 'skip'))
        freeze(plan2, self.user)
        apply_plan(plan2, self.user)
        dc.refresh_from_db()
        self.assertEqual(dc.hostname, 'tech-chosen')
        # The operator decides to take the source value.
        plan3 = self.make_plan(self.org_a)
        self.stage(plan3, itglue_routes(hostname='source-new'))
        planner.apply_correction(self.item(plan3, 'configuration', 'CFG1'), 'update', user=self.user)
        freeze(plan3, self.user)
        apply_plan(plan3, self.user)
        dc.refresh_from_db()
        self.assertEqual(dc.hostname, 'source-new')

    def test_update_refuses_to_overwrite_edit_made_after_review(self):
        self.run_full(self.org_a)
        plan2 = self.make_plan(self.org_a)
        self.stage(plan2, itglue_routes(hostname='source-new'))
        freeze(plan2, self.user)
        Asset.objects.filter(organization=self.org_a, serial_number='SN1').update(hostname='edited-now')
        apply_plan(plan2, self.user)
        item = self.item(plan2, 'configuration', 'CFG1')
        self.assertEqual(item.outcome, 'failed')
        self.assertIn('changed in ClientSt0r after review', item.outcome_message)
        self.assertEqual(Asset.objects.get(organization=self.org_a, serial_number='SN1').hostname,
                         'edited-now')


class CorrectionTests(RehearsalTestBase):

    def test_duplicate_defaults_to_mapping_existing_and_can_be_corrected(self):
        existing = Contact.objects.create(organization=self.org_a, first_name='Jane', last_name='Doe',
                                          email='JANE@acme.test', phone='999')
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        item = self.item(plan, 'contact', 'C1')
        self.assertEqual((item.category, item.action, item.target_id), ('duplicate', 'link', existing.pk))
        # Map to existing: nothing about the existing record changes.
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        existing.refresh_from_db()
        self.assertEqual(existing.phone, '999')
        self.assertEqual(Contact.objects.filter(organization=self.org_a).count(), 2)  # Jane + Bob
        dc = Asset.objects.get(organization=self.org_a, serial_number='SN1')
        self.assertEqual(dc.primary_contact, existing)

    def test_corrections_create_new_override_and_skip(self):
        Contact.objects.create(organization=self.org_a, first_name='Jane', last_name='Doe',
                               email='jane@acme.test')
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        planner.apply_correction(self.item(plan, 'contact', 'C1'), 'create', user=self.user,
                                 note='different person')
        planner.apply_correction(self.item(plan, 'configuration', 'CFG2'), 'create',
                                 field_overrides={'name': 'ACME-FW-01', 'asset_type': 'firewall'},
                                 user=self.user)
        planner.apply_correction(self.item(plan, 'document', 'D1'), 'skip', user=self.user)
        with self.assertRaises(PlanError):
            planner.apply_correction(self.item(plan, 'configuration', 'CFG1'), 'create',
                                     field_overrides={'custom_fields': {}}, user=self.user)
        # Corrections survive a rebuild from staging.
        build_plan(plan)
        self.assertTrue(self.item(plan, 'contact', 'C1').corrected)
        self.assertEqual(self.item(plan, 'document', 'D1').action, 'skip')
        # Skipping the document breaks the relation that needs it.
        rel = self.item(plan, 'related_item', 'R1')
        self.assertEqual((rel.category, rel.action), ('unavailable', 'skip'))
        freeze(plan, self.user)
        apply_plan(plan, self.user)
        self.assertEqual(Contact.objects.filter(organization=self.org_a, email='jane@acme.test').count(), 2)
        self.assertTrue(Asset.objects.filter(organization=self.org_a, name='ACME-FW-01',
                                             asset_type='firewall').exists())
        self.assertFalse(Document.objects.filter(organization=self.org_a).exists())

    def test_correction_cannot_target_another_customer(self):
        other = Contact.objects.create(organization=self.org_b, first_name='Jane', last_name='Doe',
                                       email='jane@acme.test')
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        with self.assertRaises(PlanError):
            planner.apply_correction(self.item(plan, 'contact', 'C1'), 'link', target_id=other.pk,
                                     user=self.user)

    def test_type_mapping_correction(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        planner.set_type_override(plan, 'itglue_flexible_types', 'Network', 'skip')
        build_plan(plan)
        self.assertEqual(self.item(plan, 'flexible_asset', 'FA1').category, 'unavailable')


class ReviewFreezeTests(RehearsalTestBase):

    def test_apply_requires_review(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        with self.assertRaises(PlanError):
            apply_plan(plan, self.user)

    def test_staging_changed_after_review_is_refused(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        rec = plan.staged.get(source_type='contact', source_id='C1')
        raw = rec.raw
        raw['attributes']['first-name'] = 'Janet'
        StagedRecord.objects.filter(pk=rec.pk).update(raw=raw)
        with self.assertRaises(PlanChanged):
            apply_plan(plan, self.user)
        self.assertEqual(Contact.objects.count(), 0)

    def test_plan_changed_after_review_is_refused(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        PlanItem.objects.filter(plan=plan, source_id='CFG2').update(action='skip')
        with self.assertRaises(PlanChanged):
            apply_plan(plan, self.user)
        self.assertEqual(Asset.objects.count(), 0)

    def test_correction_unfreezes_the_plan(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        planner.apply_correction(self.item(plan, 'document', 'D1'), 'skip', user=self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'planned')
        with self.assertRaises(PlanError):
            apply_plan(plan, self.user)


class _Crash(BaseException):
    """Simulates the process dying mid-apply (not caught per item)."""


class ResumeTests(RehearsalTestBase):

    def test_resume_after_item_failure(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        with mock.patch.object(SPECS['document'], 'save_new', side_effect=RuntimeError('disk full')):
            counts = apply_plan(plan, self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'partially_applied')
        self.assertEqual(plan.import_job.status, 'completed_with_errors')
        self.assertEqual(counts['failed'], 2)  # the document and the relation that needs it
        self.assertEqual(self.item(plan, 'document', 'D1').outcome, 'failed')
        assets_before = Asset.objects.filter(organization=self.org_a).count()
        counts = apply_plan(plan, self.user)
        plan.refresh_from_db()
        self.assertEqual((plan.status, counts['failed']), ('applied', 0))
        self.assertEqual(Asset.objects.filter(organization=self.org_a).count(), assets_before)
        self.assertEqual(Document.objects.filter(organization=self.org_a).count(), 1)
        self.assertEqual(self.counts(self.org_a)['relationship'], 3)

    def test_resume_after_crash(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        with mock.patch.object(SPECS['password'], 'new', side_effect=_Crash()):
            with self.assertRaises(_Crash):
                apply_plan(plan, self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'applying')
        self.assertEqual(Asset.objects.filter(organization=self.org_a).count(), 2)
        self.assertEqual(Password.objects.filter(organization=self.org_a).count(), 0)
        apply_plan(plan, self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'applied')
        self.assertEqual(self.counts(self.org_a), {'location': 1, 'contact': 2, 'asset': 2, 'network': 1,
                                                    'password': 1, 'document': 1, 'relationship': 3,
                                                    'attachment': 1})
        self.assertEqual(SourceMapping.objects.filter(organization=self.org_a).count(),
                         plan.items.filter(outcome='applied').count())


class RollbackTests(RehearsalTestBase):

    def test_rollback_keeps_later_edits_and_records_in_use(self):
        plan, _ = self.run_full(self.org_a)
        jane = Contact.objects.get(organization=self.org_a, email='jane@acme.test')
        jane.phone = '555-9999'  # technician edit after the import
        jane.save()
        doc = Document.objects.get(organization=self.org_a)
        tech_asset = Asset.objects.create(organization=self.org_a, name='Tech added')
        Relationship.objects.create(organization=self.org_a, source_type='asset', source_id=tech_asset.pk,
                                    target_type='document', target_id=doc.pk)
        report = rollback_plan(plan, self.user)
        plan.refresh_from_db()
        self.assertFalse(report['complete'])
        self.assertEqual(plan.status, 'partially_rolled_back')
        self.assertEqual(plan.import_job.status, 'partially_rolled_back')
        kept = ' '.join(report['kept'])
        self.assertIn('edited after the import (phone)', kept)
        self.assertIn('in use by relationship', kept)
        self.assertTrue(Contact.objects.filter(pk=jane.pk, phone='555-9999').exists())
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())
        self.assertEqual(list(Asset.objects.filter(organization=self.org_a)), [tech_asset])
        self.assertFalse(Contact.objects.filter(organization=self.org_a, first_name='Bob').exists())
        self.assertFalse(Password.objects.filter(organization=self.org_a).exists())
        self.assertFalse(Attachment.objects.filter(organization=self.org_a).exists())
        # Kept records keep their mapping, so a rerun recognises them.
        self.assertTrue(SourceMapping.objects.filter(organization=self.org_a, source_id='C1').exists())
        self.assertFalse(SourceMapping.objects.filter(organization=self.org_a, source_id='C2').exists())

    def test_rollback_of_update_restores_only_untouched_fields(self):
        self.run_full(self.org_a)
        plan2 = self.make_plan(self.org_a)
        self.stage(plan2, itglue_routes(hostname='new-host', model='R750'))
        self.assertEqual(sorted(self.item(plan2, 'configuration', 'CFG1').changed_fields),
                         ['hostname', 'model'])
        freeze(plan2, self.user)
        apply_plan(plan2, self.user)
        dc = Asset.objects.get(organization=self.org_a, serial_number='SN1')
        dc.model = 'R760'  # technician edit after the second import
        dc.save()
        report = rollback_plan(plan2, self.user)
        dc.refresh_from_db()
        self.assertEqual(dc.hostname, 'acme-dc01')   # restored
        self.assertEqual(dc.model, 'R760')           # later edit preserved
        self.assertIn('model', ' '.join(report['kept']))
        self.assertFalse(report['complete'])

    def test_full_rollback_through_import_job(self):
        plan, _ = self.run_full(self.org_a)
        job = plan.import_job
        self.assertTrue(job.can_rollback())
        stats = job.rollback(self.user)
        self.assertTrue(stats['complete'])
        self.assertEqual(sum(self.counts(self.org_a).values()), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, 'rolled_back')
        self.assertFalse(SourceMapping.objects.filter(organization=self.org_a).exists())
        self.assertTrue(Organization.objects.filter(pk=self.org_a.pk).exists())


class CrossTenantTests(RehearsalTestBase):
    """Same record names and the same source IDs, different customer and
    different source account."""

    def test_no_matching_across_customers_or_accounts(self):
        plan_b, _ = self.run_full(self.org_b, host='itglue-b.test')
        b_before = self.counts(self.org_b)
        b_jane = Contact.objects.get(organization=self.org_b, email='jane@acme.test')

        # Customer A from account A: same IDs and names exist only in B.
        plan_a = self.make_plan(self.org_a, host='itglue-a.test')
        self.stage(plan_a, itglue_routes(host='itglue-a.test'))
        cats = set(plan_a.items.exclude(category='unavailable').values_list('category', flat=True))
        self.assertEqual(cats, {'create'})
        freeze(plan_a, self.user)
        apply_plan(plan_a, self.user)
        self.assertEqual(self.counts(self.org_b), b_before)
        a_jane = Contact.objects.get(organization=self.org_a, email='jane@acme.test')
        self.assertNotEqual(a_jane.pk, b_jane.pk)
        self.assertEqual(Asset.objects.get(organization=self.org_a, serial_number='SN1').primary_contact,
                         a_jane)

        # Account B's IDs are mapped in customer B only: against customer A they
        # are duplicates by natural key, never "already imported".
        plan_x = self.make_plan(self.org_a, host='itglue-b.test')
        self.stage(plan_x, itglue_routes(host='itglue-b.test'))
        c1 = self.item(plan_x, 'contact', 'C1')
        self.assertEqual((c1.category, c1.target_id), ('duplicate', a_jane.pk))
        self.assertFalse(plan_x.items.filter(category__in=('unchanged', 'update')).exists())

        # Account A into customer B: B's records are only natural-key matches.
        plan_y = self.make_plan(self.org_b, host='itglue-a.test')
        self.stage(plan_y, itglue_routes(host='itglue-a.test'))
        c1 = self.item(plan_y, 'contact', 'C1')
        self.assertEqual((c1.category, c1.target_id), ('duplicate', b_jane.pk))
        for item in plan_y.items.exclude(target_id=None):
            obj = SPECS[item.target_kind].model._base_manager.get(pk=item.target_id)
            org_id = obj.subnet.organization_id if item.target_kind == 'ip_address' else obj.organization_id
            self.assertEqual(org_id, self.org_b.pk)

        # Rolling back customer A leaves customer B alone.
        rollback_plan(plan_a, self.user)
        self.assertEqual(self.counts(self.org_b), b_before)
        self.assertEqual(sum(self.counts(self.org_a).values()), 0)


class HuduTests(RehearsalTestBase):

    def test_hudu_flow(self):
        plan = self.make_plan(self.org_a, system='hudu', host='hudu-a.test', source_org='77')
        transport = self.stage(plan, hudu_routes())
        rows = {r['kind']: r for r in planner.summary(plan)['rows']}
        self.assertEqual(rows['location']['create'], 2)   # company address + "Locations" layout asset
        self.assertEqual(rows['contact']['create'], 1)    # "People" layout asset
        self.assertEqual(rows['asset']['create'], 1)
        for kind in ('password', 'document', 'website', 'network', 'ip_address', 'relation', 'attachment'):
            self.assertEqual(rows[kind]['create'], 1, kind)
        gaps = {e['source_type']: e for e in plan.unavailable}
        self.assertEqual(gaps['procedure']['kind'], 'not_supported')
        self.assertEqual(gaps['vlan']['kind'], 'api_gap')
        # Other companies' records never reach the staging.
        self.assertFalse(plan.staged.filter(source_id__in=['999', '2', '1002']).exists())
        self.assertNotIn(('bytes', 'https://hudu-a.test/uploads/1002'), transport.calls)
        srv = plan.staged.get(source_type='asset', source_id='501')
        self.assertNotIn(HUDU_CONFIDENTIAL, json.dumps(srv.raw))
        self.assertIn('Admin Password (confidential field)', self.item(plan, 'asset', '501').skipped_fields)

        freeze(plan, self.user)
        counts = apply_plan(plan, self.user)
        self.assertEqual(counts['failed'], 0)
        srv = Asset.objects.get(organization=self.org_a, name='GLX-SRV')
        self.assertEqual(str(srv.ip_address), '10.1.0.5')
        self.assertNotIn(HUDU_CONFIDENTIAL, json.dumps(srv.custom_fields))
        self.assertTrue(Contact.objects.filter(organization=self.org_a, email='ann@globex.test').exists())
        site = Location.objects.get(organization=self.org_a, name='Main Site')
        net = Subnet.objects.get(organization=self.org_a)
        self.assertEqual(net.location, site.name)
        ip = IPAddress.objects.get(subnet=net)
        self.assertEqual((ip.ip_address, ip.asset_id, ip.status), ('10.1.0.5', srv.pk, 'assigned'))
        pw = Password.objects.get(organization=self.org_a)
        self.assertEqual((pw.get_password(), pw.get_otp_secret()), (HUDU_SECRET, OTP))
        self.assertTrue(PasswordRelation.objects.filter(password=pw, relation_id=srv.pk).exists())
        site_monitor = WebsiteMonitor.objects.get(organization=self.org_a)
        self.assertEqual((site_monitor.url, site_monitor.is_enabled), ('https://globex.test', False))
        doc = Document.objects.get(organization=self.org_a)
        self.assertTrue(Relationship.objects.filter(source_type='asset', source_id=srv.pk,
                                                    target_type='document', target_id=doc.pk).exists())
        self.assertTrue(Attachment.objects.filter(organization=self.org_a, entity_type='asset',
                                                  entity_id=srv.pk, original_filename='invoice.pdf').exists())
        # Rerun: nothing to do.
        plan2 = self.make_plan(self.org_a, system='hudu', host='hudu-a.test', source_org='77')
        self.stage(plan2, hudu_routes())
        self.assertEqual(set(plan2.items.values_list('category', flat=True)), {'unchanged'})

    def test_hudu_layout_override_changes_target_type(self):
        plan = self.make_plan(self.org_a, system='hudu', host='hudu-a.test', source_org='77')
        self.stage(plan, hudu_routes())
        planner.set_type_override(plan, 'hudu_layouts', 'People', 'asset')
        build_plan(plan)
        self.assertEqual(self.item(plan, 'asset', '502').target_kind, 'asset')


class ReportRedactionTests(RehearsalTestBase):

    def test_report_has_counts_ids_and_no_secrets(self):
        plan = self.make_plan(self.org_a)
        routes, files = itglue_routes(doc_name='Vault notes token=SUPERSECRET123')
        self.stage(plan, (routes, files))
        freeze(plan, self.user)
        with mock.patch.object(SPECS['password'], 'save_new',
                               side_effect=RuntimeError(f'cannot store {SECRET}')):
            apply_plan(plan, self.user)
        report = build_report(plan)
        blob = json.dumps(report) + records_csv(report) + summary_csv(report)
        for secret in (SECRET, OTP, 'KEY-itglue-a.test-do-not-leak', 'SUPERSECRET123'):
            self.assertNotIn(secret, blob)
        p1 = next(r for r in report['records'] if r['source_id'] == 'P1')
        self.assertEqual(p1['outcome'], 'failed')
        self.assertIn('[redacted]', p1['detail'])
        rows = {r['kind']: r for r in report['summary']}
        self.assertEqual(rows['asset']['source_records'], 3)
        self.assertEqual(rows['asset']['reconciled_in_clientst0r'], 2)
        self.assertEqual(rows['password']['failed'], 1)
        self.assertEqual(rows['password']['not_reconciled'], 1)
        self.assertEqual(report['customer']['id'], self.org_a.pk)
        self.assertIn('CFG1', records_csv(report))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RehearsalViewTests(RehearsalTestBase):

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)

    def test_full_flow_through_the_ui(self):
        resp = self.client.post(reverse('imports:rehearsal_create'), {
            'source_type': 'itglue', 'source_url': 'https://itglue-a.test', 'source_api_key': 'KEY-ui',
            'source_organization_id': '101', 'target_organization': self.org_a.pk})
        plan = MigrationPlan.objects.get()
        self.assertRedirects(resp, reverse('imports:rehearsal_detail', args=[plan.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(plan.source_account, 'itglue-a.test')
        routes, files = itglue_routes()
        with mock.patch('imports.migration.sources.RequestsTransport',
                        lambda *a, **k: FakeTransport(routes, files)):
            resp = self.client.post(reverse('imports:rehearsal_stage', args=[plan.pk]))
            self.assertEqual(resp.status_code, 302)
            plan.refresh_from_db()
            # The request only queued the fetch; nothing was fetched yet.
            self.assertEqual((plan.status, plan.task_action, plan.task_state), ('draft', 'stage', 'queued'))
            detail = self.client.get(reverse('imports:rehearsal_detail', args=[plan.pk]))
            self.assertContains(detail, 'rehearsal-autorefresh')
            self.assertContains(detail, 'Background work')
            self.assertEqual(run_pending(), [(plan.pk, 'done')])
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state), ('planned', 'done'))
        detail = self.client.get(reverse('imports:rehearsal_detail', args=[plan.pk]))
        self.assertContains(detail, 'What will transfer')
        self.assertContains(self.client.get(reverse('imports:rehearsal_items', args=[plan.pk])), 'Jane Doe')
        pw_item = self.item(plan, 'password', 'P1')
        page = self.client.get(reverse('imports:rehearsal_item', args=[plan.pk, pw_item.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, SECRET)
        self.assertNotContains(page, OTP)
        fw = self.item(plan, 'configuration', 'CFG2')
        self.client.post(reverse('imports:rehearsal_item', args=[plan.pk, fw.pk]),
                         {'action': 'create', 'field_name': 'ACME-FW-01', 'note': 'rename'})
        fw.refresh_from_db()
        self.assertEqual(fw.field_overrides, {'name': 'ACME-FW-01'})
        self.client.post(reverse('imports:rehearsal_freeze', args=[plan.pk]))
        self.client.post(reverse('imports:rehearsal_apply', args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state), ('reviewed', 'queued'))
        self.assertFalse(Asset.objects.filter(organization=self.org_a).exists())
        call_command('run_migration_rehearsals', stdout=io.StringIO())
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'applied')
        self.assertNotContains(self.client.get(reverse('imports:rehearsal_detail', args=[plan.pk])),
                               'rehearsal-autorefresh')
        self.assertTrue(Asset.objects.filter(organization=self.org_a, name='ACME-FW-01').exists())
        self.assertTrue(AuditLog.objects.filter(object_type='migration_rehearsal', object_id=plan.pk,
                                                action='import', success=True).exists())
        csv_resp = self.client.get(reverse('imports:rehearsal_report', args=[plan.pk]) + '?format=csv')
        self.assertEqual(csv_resp['Content-Type'], 'text/csv')
        self.assertNotIn(SECRET, csv_resp.content.decode())
        json_resp = self.client.get(reverse('imports:rehearsal_report', args=[plan.pk]))
        self.assertNotIn('KEY-ui', json_resp.content.decode())
        self.client.post(reverse('imports:rehearsal_rollback', args=[plan.pk]))
        run_pending()
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'rolled_back')
        self.assertTrue(AuditLog.objects.filter(object_type='migration_rehearsal', object_id=plan.pk,
                                                action='delete').exists())
        # Rehearsal jobs cannot be started through the legacy run path.
        resp = self.client.get(reverse('imports:import_start', args=[plan.import_job.pk]))
        self.assertRedirects(resp, reverse('imports:rehearsal_detail', args=[plan.pk]),
                             fetch_redirect_response=False)

    def test_changed_plan_refusal_is_audited(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        PlanItem.objects.filter(plan=plan, source_id='CFG2').update(action='skip')
        self.client.post(reverse('imports:rehearsal_apply', args=[plan.pk]))
        self.assertTrue(AuditLog.objects.filter(object_id=plan.pk, success=False).exists())
        self.assertEqual(Asset.objects.count(), 0)

    def test_non_staff_cannot_reach_rehearsals(self):
        plain = User.objects.create_user('plain', 'p@example.com', 'pw')
        c = Client()
        c.force_login(plain)
        plan = self.make_plan(self.org_a)
        for name in ('rehearsal_list', 'rehearsal_create'):
            self.assertNotEqual(c.get(reverse(f'imports:{name}')).status_code, 200)
        self.assertNotEqual(c.get(reverse('imports:rehearsal_detail', args=[plan.pk])).status_code, 200)
        for name in ('rehearsal_stage', 'rehearsal_apply', 'rehearsal_rollback'):
            c.post(reverse(f'imports:{name}', args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state), ('draft', 'idle'))

    def test_double_post_queues_once_and_edits_wait(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        self.client.post(reverse('imports:rehearsal_build', args=[plan.pk]))
        self.client.post(reverse('imports:rehearsal_build', args=[plan.pk]))
        self.assertEqual(AuditLog.objects.filter(object_id=plan.pk, description__startswith='Queued').count(), 1)
        self.client.post(reverse('imports:rehearsal_freeze', args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state), ('planned', 'queued'))
        self.assertEqual(run_pending(), [(plan.pk, 'done')])
        self.client.post(reverse('imports:rehearsal_freeze', args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'reviewed')


class BackgroundTaskTests(RehearsalTestBase):
    """enqueue -> run -> resume after a crash -> never run twice."""

    def reviewed_plan(self):
        plan = self.make_plan(self.org_a)
        self.stage(plan, itglue_routes())
        freeze(plan, self.user)
        return plan

    def test_enqueue_then_run(self):
        plan = self.reviewed_plan()
        self.assertTrue(tasks.enqueue(plan, 'apply', self.user))
        self.assertEqual(plan.task_state, 'queued')
        self.assertFalse(Asset.objects.filter(organization=self.org_a).exists())
        out = io.StringIO()
        call_command('run_migration_rehearsals', stdout=out)
        self.assertIn(f'rehearsal {plan.pk}: done', out.getvalue())
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state, plan.task_attempts), ('applied', 'done', 1))
        self.assertEqual(plan.task_result['applied'], plan.items.filter(outcome='applied').count())
        self.assertTrue(AuditLog.objects.filter(object_id=plan.pk, action='import', success=True,
                                                path='scheduler:run_migration_rehearsals').exists())
        out = io.StringIO()
        call_command('run_migration_rehearsals', stdout=out)
        self.assertIn('no rehearsal work queued', out.getvalue())

    def test_second_enqueue_and_second_claim_are_refused(self):
        plan = self.reviewed_plan()
        self.assertTrue(tasks.enqueue(plan, 'apply', self.user))
        self.assertFalse(tasks.enqueue(plan, 'rollback', self.user))
        plan.refresh_from_db()
        self.assertEqual(plan.task_action, 'apply')
        token = tasks.claim(plan.pk)
        self.assertIsNotNone(token)
        self.assertIsNone(tasks.claim(plan.pk))      # second worker gets nothing
        self.assertFalse(tasks.enqueue(plan, 'apply', self.user))  # still running
        self.assertEqual(tasks.run_pending(), [])     # fresh lease: not claimable
        self.assertEqual(tasks.run_claimed(plan.pk, token), 'done')
        before = self.counts(self.org_a)
        self.assertIsNone(tasks.claim(plan.pk))      # finished tasks are not rerun
        self.assertEqual(tasks.run_pending(), [])
        self.assertEqual(self.counts(self.org_a), before)

    def test_crash_mid_apply_resumes_after_stale_lease(self):
        plan = self.reviewed_plan()
        tasks.enqueue(plan, 'apply', self.user)
        with mock.patch.object(SPECS['password'], 'new', side_effect=_Crash()):
            with self.assertRaises(_Crash):
                tasks.run_pending()
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state), ('applying', 'running'))
        self.assertEqual(Password.objects.filter(organization=self.org_a).count(), 0)
        assets = Asset.objects.filter(organization=self.org_a).count()
        self.assertEqual(assets, 2)
        # The dead worker's lease is still fresh: nobody may take over yet.
        self.assertEqual(tasks.run_pending(), [])
        MigrationPlan.objects.filter(pk=plan.pk).update(
            task_heartbeat_at=timezone.now() - timedelta(seconds=tasks.lease_seconds() + 5))
        self.assertEqual(tasks.run_pending(), [(plan.pk, 'done')])
        plan.refresh_from_db()
        self.assertEqual((plan.status, plan.task_state, plan.task_attempts), ('applied', 'done', 2))
        self.assertEqual(Asset.objects.filter(organization=self.org_a).count(), assets)
        self.assertEqual(self.counts(self.org_a), {'location': 1, 'contact': 2, 'asset': 2, 'network': 1,
                                                    'password': 1, 'document': 1, 'relationship': 3,
                                                    'attachment': 1})
        self.assertEqual(SourceMapping.objects.filter(organization=self.org_a).count(),
                         plan.items.filter(outcome='applied').count())

    def test_worker_that_lost_its_lease_stops(self):
        plan = self.reviewed_plan()
        tasks.enqueue(plan, 'apply', self.user)
        old = tasks.claim(plan.pk)
        MigrationPlan.objects.filter(pk=plan.pk).update(task_heartbeat_at=None)  # looks stale
        new = tasks.claim(plan.pk)
        self.assertNotEqual(old, new)
        self.assertEqual(tasks.run_claimed(plan.pk, old), 'lost')
        self.assertFalse(Asset.objects.filter(organization=self.org_a).exists())
        self.assertEqual(tasks.run_claimed(plan.pk, new), 'done')
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'applied')

    def test_long_apply_is_sliced_and_requeued(self):
        plan = self.reviewed_plan()
        tasks.enqueue(plan, 'apply', self.user)
        total = plan.items.count()
        with override_settings(IMPORT_REHEARSAL_SLICE_SECONDS=0):
            self.assertEqual(tasks.run_pending(), [(plan.pk, 'queued')])
            plan.refresh_from_db()
            self.assertEqual(plan.task_state, 'queued')
            self.assertLess(plan.task_progress['done'], plan.task_progress['total'])
            runs = 1
            while plan.task_state == 'queued' and runs < 100:
                tasks.run_pending()
                plan.refresh_from_db()
                runs += 1
        self.assertEqual((plan.status, plan.task_state), ('applied', 'done'))
        self.assertGreater(runs, 2)
        self.assertLessEqual(runs, total + 1)
        self.assertEqual(self.counts(self.org_a)['password'], 1)

    def test_failure_is_recorded_without_secrets(self):
        plan = self.make_plan(self.org_a)
        tasks.enqueue(plan, 'stage', self.user)
        with mock.patch('imports.migration.sources.RequestsTransport',
                        side_effect=SourceUnavailable('error', f'boom {plan.import_job.source_api_key}')):
            self.assertEqual(tasks.run_pending(), [(plan.pk, 'failed')])
        plan.refresh_from_db()
        self.assertEqual(plan.task_state, 'failed')
        self.assertIn('SourceUnavailable', plan.task_error)
        self.assertNotIn('do-not-leak', plan.task_error)
        self.assertTrue(tasks.enqueue(plan, 'stage', self.user))  # retry is allowed after failure

    def test_rollback_runs_in_background(self):
        plan = self.reviewed_plan()
        tasks.enqueue(plan, 'apply', self.user)
        tasks.run_pending()
        tasks.enqueue(plan, 'rollback', self.user)
        self.assertEqual(tasks.run_pending(), [(plan.pk, 'done')])
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'rolled_back')
        self.assertEqual(self.counts(self.org_a)['asset'], 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InventoryExportTests(RehearsalTestBase):

    def setUp(self):
        super().setUp()
        self.run_full(self.org_a)

    def test_superuser_export_is_metadata_only_and_audited(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse('imports:inventory_export', args=[self.org_a.pk]) + '?format=json')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['counts']['passwords'], 1)
        self.assertEqual(data['counts']['assets'], 2)
        self.assertEqual(data['counts']['networks'], 1)
        body = resp.content.decode()
        self.assertNotIn(SECRET, body)
        self.assertNotIn(OTP, body)
        self.assertNotIn('encrypted_password', body)
        csv_body = c.get(reverse('imports:inventory_export', args=[self.org_a.pk])).content.decode()
        self.assertIn('Domain Admin', csv_body)
        self.assertNotIn(SECRET, csv_body)
        self.assertTrue(AuditLog.objects.filter(action='export', organization=self.org_a,
                                                object_type='organization').exists())

    def test_staff_without_vault_permission_gets_no_passwords(self):
        from accounts.models import UserProfile, UserType
        tech = User.objects.create_user('tech', 't@example.com', 'pw')
        # Update the cached profile: force_login() re-saves it via a signal.
        try:
            profile = tech.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=tech)
        profile.user_type = UserType.STAFF
        profile.save()
        c = Client()
        c.force_login(tech)
        resp = c.get(reverse('imports:inventory_export', args=[self.org_a.pk]) + '?format=json')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertNotIn('passwords', data['sections'])
        self.assertIn('passwords', data['omitted_sections'])
        self.assertNotIn('Domain Admin', resp.content.decode())

    def test_non_staff_cannot_export(self):
        plain = User.objects.create_user('plain', 'p@example.com', 'pw')
        c = Client()
        c.force_login(plain)
        resp = c.get(reverse('imports:inventory_export', args=[self.org_a.pk]))
        self.assertNotEqual(resp.status_code, 200)


class AttachmentRuleTests(TestCase):

    def test_upload_rules(self):
        from files import upload_rules
        self.assertEqual(upload_rules.check_file('a.pdf', PDF, 'application/pdf'), '')
        self.assertIn('not allowed', upload_rules.check_file('a.exe', b'MZ', ''))
        self.assertIn('does not match', upload_rules.check_file('a.pdf', b'not a pdf', ''))
        self.assertIn('content type', upload_rules.check_file('a.pdf', PDF, 'image/png'))
        self.assertIn('limit', upload_rules.check_file('a.pdf', PDF * 10, '', max_bytes=len(PDF)))

    def test_api_key_only_sent_to_the_api_host(self):
        from imports.migration.transport import RequestsTransport

        class Resp:
            status_code = 200
            headers = {'Content-Type': 'application/pdf'}

            def iter_content(self, chunk_size):
                yield PDF

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        sessions = []

        def fake_guard(session, policy, max_retries=0):
            session.get = mock.MagicMock(return_value=Resp())
            sessions.append(session)
            return session

        with mock.patch('core.safe_http.guard_session', side_effect=fake_guard):
            t = RequestsTransport('https://api.itglue.test', {'x-api-key': 'KEY', 'Accept': 'x'})
            t.get_bytes('https://files.example-storage.test/a.pdf?sig=1', 1000)
            t.get_bytes('https://api.itglue.test/attachments/1', 1000)
        foreign = sessions[1].get.call_args
        self.assertEqual(foreign.kwargs['headers'], {})
        own = sessions[0].get.call_args
        self.assertEqual(own.kwargs['headers'].get('x-api-key'), 'KEY')
        with mock.patch('core.safe_http.guard_session', side_effect=fake_guard):
            t = RequestsTransport('https://api.itglue.test', {'x-api-key': 'KEY'})
            with self.assertRaises(DownloadRejected):
                t.get_bytes('https://api.itglue.test/big', 5)


class LegacyImporterMappingTests(TestCase):
    """The all-organizations importer now maps contacts, locations and
    networks through the same field mapping."""

    def setUp(self):
        self.user = User.objects.create_user('legacy', 'l@example.com', 'pw')
        self.org = Organization.objects.create(name='Acme Dental', slug='acme-dental')

    def _run(self, source_type, routes):
        from imports.services import get_import_service

        class R:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return copy.deepcopy(self.payload)

        job = ImportJob.objects.create(
            source_type=source_type, source_url='https://src.test', source_api_key='k',
            target_organization=self.org, started_by=self.user, dry_run=False,
            import_assets=False, import_passwords=False, import_documents=False,
            import_contacts=True, import_locations=True, import_networks=True)
        service = get_import_service(job)

        def fake(method, endpoint, **kw):
            route = routes.get(endpoint)
            if callable(route):
                route = route(kw.get('params') or {})
            return R(route or ({'data': []} if source_type == 'itglue' else {}))
        with mock.patch.object(service, '_make_request', side_effect=fake):
            service.run_import()
        job.refresh_from_db()
        return job

    def test_itglue_contacts_locations_networks(self):
        routes, _ = itglue_routes()
        job = self._run('itglue', routes)
        self.assertEqual(job.status, 'completed', job.import_log)
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 2)
        self.assertEqual(Location.objects.filter(organization=self.org, name='HQ').count(), 1)
        self.assertEqual(Subnet.objects.get(organization=self.org).network, '10.0.0.0/24')
        stats = job.rollback(self.user)
        self.assertTrue(stats['complete'], stats)
        self.assertFalse(Subnet.objects.filter(organization=self.org).exists())

    def test_hudu_contacts_locations_networks(self):
        routes, _ = hudu_routes()
        routes = dict(routes)
        routes['/api/v1/companies'] = {'companies': [routes['/api/v1/companies/77']['company']]}
        job = self._run('hudu', routes)
        self.assertIn(job.status, ('completed', 'completed_with_errors'), job.import_log)
        self.assertTrue(Contact.objects.filter(organization=self.org, email='ann@globex.test').exists())
        self.assertTrue(Location.objects.filter(organization=self.org, name='Main Site').exists())
        self.assertTrue(Location.objects.filter(organization=self.org, name__startswith='Globex').exists())
        self.assertEqual(Subnet.objects.get(organization=self.org).network, '10.1.0.0/24')
