"""
ticket-rmm-v1 for any RMM (v3.17.658): provider-neutral pairing, and the
Phase 56.5 / 56.6 ClientSt0r side — handoffs, read-only diagnostics, remote
launch and fix referrals — against the test processor (this file playing
the RMM, as tests_assist.py does for analysis).
"""
import importlib
import json
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from integrations import ticket_rmm
from integrations.forms import RMMConnectionForm
from integrations.models import RMMConnection, RMMDevice
from psa.models import TicketComment
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed
from tech_access import catalog, protected, services as ta_services
from tech_access.models import ProtectedChange, ProtectionSettings
from tech_access.resolver import UNAVAILABLE, decide
from tech_access.testing import grant, make_tech, make_ticket

from .models import AnalysisJob, AnalysisRun, RMMRequest, RMMRequestEvent
from .services import processor, rmm_actions
from .tests_assist import IN_SECRET, OUT_SECRET, AssistBase, sign_in

EVENTS = '/api/integration/v1/events'
ALL_CAPS = ['analysis.jobs', 'rmm_handoff', 'diagnostics_readonly', 'remote_view', 'remote_control',
            'fix_request_low', 'signed_actions']
DIAGS = [{'key': 'disk_space', 'label': 'Disk space', 'description': 'Free space per volume',
          'device_classes': ['workstation', 'laptop']},
         {'key': 'server_roles', 'label': 'Server roles', 'device_classes': ['server']},
         {'key': 'BAD KEY', 'label': 'dropped'}]


def advertise(conn, caps=ALL_CAPS, tenant='biz-alpha', diagnostics=DIAGS):
    return ticket_rmm.record_capabilities(conn, {'contract': 'ticket-rmm-v1', 'tenant': {'id': tenant},
                                                 'capabilities': caps, 'diagnostics': diagnostics})


class _Req:
    def __init__(self, user):
        self.user, self.session, self.META, self.path = user, {}, {}, '/test'


def fresh(user):
    r = _Req(user)
    assert protected.reauthenticate(r, 'pw-' + user.username) == ''
    return r


# ---------------------------------------------------------------------------
# Pairing: migration, any provider, protected changes, tenant pin
# ---------------------------------------------------------------------------

class PairingMigrationTests(TestCase):
    """integrations 0034 moves the rem0te-only keys without touching state."""
    mod = importlib.import_module('integrations.migrations.0034_ticket_rmm_pairing_keys')

    def setUp(self):
        self.org = Organization.objects.create(name='Alpha', slug='alpha')

    def _legacy(self, provider='rem0te', name='', **mappings):
        conn = RMMConnection.objects.create(organization=self.org, provider_type=provider, name=name or provider,
                                            base_url='https://rem0te.example.com/api/v1/pub/v1',
                                            customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        conn.set_credentials({'api_key': 'rk_x', 'integration_outbound_secret': 'o' * 40,
                              'integration_inbound_secret': 'i' * 40})
        conn.field_mappings = mappings
        conn.save()
        return conn

    def test_live_rem0te_pairing_survives_with_no_reapproval(self):
        caps = {'capabilities': ['rmm_handoff'], 'contract': 'ticket-rmm-v1', 'fetched_at': 'x'}
        conn = self._legacy(rem0te_integration_enabled=True, rem0te_integration_key_id='kid-1',
                            rem0te_processing_location='local', rem0te_capabilities=caps,
                            rem0te_business_id='biz-1', device_type_map={'x': 'y'})
        pending = self._legacy(provider='rem0te', name='pending', rem0te_integration_enabled=False,
                               rem0te_integration_key_id='kid-2', rem0te_business_id='biz-2')
        untouched = self._legacy(provider='ninjaone', device_type_map={'a': 'b'})
        self.mod.forwards(django_apps, None)
        conn.refresh_from_db()
        self.assertEqual(conn.field_mappings, {
            'ticket_rmm_enabled': True, 'ticket_rmm_key_id': 'kid-1', 'ticket_rmm_location': 'local',
            'ticket_rmm_capabilities': caps, 'rem0te_business_id': 'biz-1', 'ticket_rmm_tenant_id': 'biz-1',
            'device_type_map': {'x': 'y'}})
        # Rem0te now pairs only with Ed25519 (integrations/rem0te/): the moved HMAC
        # pairing is no longer a processor and is never found by its HMAC key id;
        # 0036 marks it for re-pairing (integrations/tests_rem0te.py MigrationTests).
        s = ticket_rmm.settings(conn)
        self.assertEqual((s['auth'], s['tenant_id']), ('ed25519', 'biz-1'))
        self.assertFalse(ticket_rmm.is_processor(conn))
        self.assertIsNone(ticket_rmm.processor_for(self.org))
        self.assertIsNone(ticket_rmm.find_by_key_id('kid-1'))
        pending.refresh_from_db()
        self.assertIs(pending.field_mappings['ticket_rmm_enabled'], False)  # still waiting, not switched on
        untouched.refresh_from_db()
        self.assertEqual(untouched.field_mappings, {'device_type_map': {'a': 'b'}})
        # Idempotent, and reversible to exactly the old keys.
        self.mod.forwards(django_apps, None)
        self.mod.backwards(django_apps, None)
        conn.refresh_from_db()
        self.assertEqual(conn.field_mappings, {
            'rem0te_integration_enabled': True, 'rem0te_integration_key_id': 'kid-1',
            'rem0te_processing_location': 'local', 'rem0te_capabilities': caps, 'rem0te_business_id': 'biz-1',
            'device_type_map': {'x': 'y'}})

    def test_pending_protected_change_still_applies_after_migration(self):
        alice, bob = make_tech('alice', superuser=True), make_tech('bob', superuser=True)
        conn = self._legacy(rem0te_integration_enabled=False, rem0te_integration_key_id='kid-9',
                            rem0te_business_id='biz-9')
        change = ProtectedChange.objects.create(
            kind='business_mapping', summary='old proposal', payload={'connection': conn.pk, 'enable': True},
            widening=['ticket processing on'], requested_by=alice, expires_at=timezone.now() + timedelta(hours=1))
        self.mod.forwards(django_apps, None)
        protected.confirm(change, fresh(alice))
        protected.approve(ProtectedChange.objects.get(pk=change.pk), fresh(bob))
        conn.refresh_from_db()
        # The approved change still applies to the moved keys; the connection
        # still needs Rem0te's audience and keys before it can process tickets.
        self.assertIs(conn.field_mappings.get('ticket_rmm_enabled'), True)
        self.assertFalse(ticket_rmm.is_processor(conn))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AnyProviderPairingTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='Gamma Clinic', slug='gamma')
        self.alice = make_tech('alice', superuser=True)
        self.bob = make_tech('bob', superuser=True)
        ProtectionSettings.objects.update_or_create(pk=1, defaults={
            'recovery_email': 'sec@msp.test', 'recovery_verified_at': timezone.now()})

    def _data(self, provider='tactical_rmm', **over):
        data = {'provider_type': provider, 'name': f'{provider} conn', 'base_url': 'https://rmm.example.com',
                'customer_scope': RMMConnection.CUSTOMER_SCOPE_SINGLE, 'sync_enabled': 'on',
                'sync_devices': 'on', 'map_to_assets': 'on', 'sync_interval_minutes': 60,
                'ticket_rmm_enabled': 'on', 'ticket_rmm_key_id': f'kid-{provider}',
                'ticket_rmm_outbound_secret': OUT_SECRET, 'ticket_rmm_inbound_secret': IN_SECRET,
                'ticket_rmm_location': 'hosted',
                'tactical_api_key': 'k' * 30, 'atera_api_key': 'k' * 30, 'rem0te_api_key': 'rk_' + '0' * 40,
                'ninja_client_id': 'c', 'ninja_client_secret': 's', 'ninja_refresh_token': 'r',
                'datto_api_key': 'k', 'datto_api_secret': 's', 'cwa_server': 'https://cwa.example.com',
                'cwa_username': 'u', 'cwa_password': 'p'}
        data.update(over)
        return data

    def _save(self, instance=None, **over):
        form = RMMConnectionForm(data=self._data(**over), instance=instance, organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        return form.save(), form.pairing_request

    def _approve(self, conn, req):
        change = ta_services.propose_pairing(conn, req, self.alice)
        protected.confirm(change, fresh(self.alice))
        return protected.approve(ProtectedChange.objects.get(pk=change.pk), fresh(self.bob))

    def test_every_provider_needs_a_second_administrator(self):
        for provider, _label in RMMConnection.PROVIDER_TYPES:
            if provider == 'rem0te':  # Ed25519 only: integrations/tests_rem0te.py ConnectionFormAndPageTests
                continue
            conn, req = self._save(provider=provider, name=f'{provider} x')
            self.assertEqual(req, {'enable': True}, provider)
            self.assertFalse(ticket_rmm.settings(conn)['enabled'], provider)
            self.assertEqual(conn.get_credentials()['integration_inbound_secret'], IN_SECRET, provider)
            with self.assertRaises(protected.ProtectedChangeError):  # one admin is never enough
                change = ta_services.propose_pairing(conn, req, self.alice)
                protected.approve(change, fresh(self.alice))
            conn.refresh_from_db()
            self.assertFalse(ticket_rmm.settings(conn)['enabled'], provider)

    def test_third_party_rmm_pairs_and_becomes_a_processor(self):
        conn, req = self._save()
        self._approve(conn, req)
        conn.refresh_from_db()
        self.assertTrue(ticket_rmm.settings(conn)['enabled'])
        self.assertFalse(ticket_rmm.is_processor(conn))  # no tenant pinned yet
        self.assertEqual(ticket_rmm.status(conn)['state'], 'checking')
        doc = {'contract': 'ticket-rmm-v1', 'tenant': {'id': 'acme-77', 'name': 'Gamma Clinic'},
               'capabilities': ['rmm_handoff', 'made_up_thing']}
        with patch('psa_ai.services.processor._request', return_value=doc) as r:
            processor.refresh_capabilities(conn)
        self.assertEqual(r.call_args[0][1:3], ('GET', '/capabilities'))
        conn.refresh_from_db()
        self.assertEqual(ticket_rmm.settings(conn)['tenant_id'], 'acme-77')
        self.assertTrue(ticket_rmm.is_processor(conn))
        self.assertEqual(ticket_rmm.advertised(conn), {'rmm_handoff'})
        self.assertEqual(ticket_rmm.processor_for(self.org), conn)
        self.assertEqual(ticket_rmm.find_by_key_id('kid-tactical_rmm'), conn)
        # Signing works for it like for rem0te.
        self.assertEqual(ticket_rmm.secrets(conn), {'outbound': OUT_SECRET, 'inbound': IN_SECRET})

    def test_rmm_without_the_contract_never_pairs_and_says_why(self):
        conn, req = self._save(provider='atera')
        self._approve(conn, req)
        conn.refresh_from_db()
        with patch('psa_ai.services.processor._request',
                   side_effect=processor.ProcessorUnavailable('The RMM answered HTTP 404.')):
            processor.refresh_capabilities(conn)
        conn.refresh_from_db()
        self.assertFalse(ticket_rmm.is_processor(conn))
        st = ticket_rmm.status(conn)
        self.assertEqual(st['state'], 'error')
        self.assertIn('HTTP 404', st['detail'])
        with patch('psa_ai.services.processor._request', return_value={'contract': 'something-else'}):
            processor.refresh_capabilities(conn)
        conn.refresh_from_db()
        self.assertIn('does not implement ticket-rmm-v1', ticket_rmm.status(conn)['detail'])
        # No tenant in an otherwise valid answer: still not paired.
        with patch('psa_ai.services.processor._request',
                   return_value={'contract': 'ticket-rmm-v1', 'capabilities': ['rmm_handoff']}):
            processor.refresh_capabilities(conn)
        conn.refresh_from_db()
        self.assertFalse(ticket_rmm.is_processor(conn))
        self.assertIn('tenant', ticket_rmm.status(conn)['detail'])
        # The connection page shows it, and the console-link behaviour is unchanged.
        c = Client()
        c.force_login(self.alice)
        s = c.session
        s['current_organization_id'] = self.org.pk
        s.save()
        page = c.get(f'/integrations/rmm/{conn.pk}/').content.decode()
        self.assertIn('ticket-rmm-pairing-status', page)
        self.assertIn('data-pairing-state="error"', page)

    def test_pairing_section_is_on_the_form_for_every_provider(self):
        c = Client()
        c.force_login(self.alice)
        s = c.session
        s['current_organization_id'] = self.org.pk
        s.save()
        html = c.get('/integrations/rmm/create/').content.decode()
        self.assertIn('Ticket integration pairing (ticket-rmm-v1)', html)
        self.assertIn('must implement the ticket-rmm-v1 contract', html)
        # Outside every provider's credential section.
        self.assertIn('id="ticket-rmm-pairing"', html)
        rem0te_creds = html.split('id="creds-rem0te"', 1)[1].split('id="ticket-rmm-pairing"', 1)[0]
        self.assertNotIn('ticket_rmm_enabled', rem0te_creds)

    def test_multi_customer_connection_cannot_pair(self):
        form = RMMConnectionForm(data=self._data(customer_scope=RMMConnection.CUSTOMER_SCOPE_MULTI),
                                 organization=self.org)
        self.assertFalse(form.is_valid())
        self.assertIn('customer_scope', form.errors)

    def test_repairing_a_live_pairing_switches_it_off_until_approved(self):
        conn, req = self._save()
        self._approve(conn, req)
        conn.refresh_from_db()
        # Saving again without changes keeps it on and proposes nothing.
        same = self._data(ticket_rmm_outbound_secret='', ticket_rmm_inbound_secret='', tactical_api_key='')
        form = RMMConnectionForm(data=same, instance=conn, organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        conn = form.save()
        self.assertIsNone(form.pairing_request)
        self.assertTrue(ticket_rmm.settings(conn)['enabled'])
        for change in ({'ticket_rmm_inbound_secret': 'n' * 40}, {'ticket_rmm_key_id': 'kid-new'},
                       {'ticket_rmm_url': 'https://other.example.com'}, {'provider_type': 'atera'}):
            conn.refresh_from_db()
            conn, req = self._save(instance=conn, **change)
            self.assertFalse(ticket_rmm.settings(conn)['enabled'], change)
            self.assertEqual(req, {'enable': True}, change)
            self._approve(conn, req)
            conn.refresh_from_db()
            self.assertTrue(ticket_rmm.settings(conn)['enabled'], change)
        self.assertNotIn(ticket_rmm.TENANT_PIN, conn.field_mappings)  # provider change: pin afresh

    def test_change_after_proposal_cannot_be_approved(self):
        conn, req = self._save()
        change = ta_services.propose_pairing(conn, req, self.alice)
        protected.confirm(change, fresh(self.alice))
        creds = conn.get_credentials()
        creds['integration_inbound_secret'] = 'z' * 40
        conn.set_credentials(creds)
        conn.save()
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(ProtectedChange.objects.get(pk=change.pk), fresh(self.bob))
        conn.refresh_from_db()
        self.assertFalse(ticket_rmm.settings(conn)['enabled'])

    def test_on_premises_is_protected_too(self):
        conn, req = self._save(ticket_rmm_location='local', provider='ninjaone')
        self.assertEqual(req, {'enable': True, 'location': 'local'})
        self.assertEqual(ticket_rmm.settings(conn)['location'], 'hosted')


class TenantPinTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Alpha', slug='alpha')

    def _conn(self, provider, name='', **mappings):
        conn = RMMConnection.objects.create(organization=self.org, provider_type=provider, name=name or provider,
                                            base_url='https://rmm.example.com',
                                            customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        conn.set_credentials({'integration_outbound_secret': 'o' * 40, 'integration_inbound_secret': 'i' * 40})
        conn.field_mappings = dict({'ticket_rmm_enabled': True, 'ticket_rmm_key_id': 'k-' + provider}, **mappings)
        conn.save()
        return conn

    def test_first_success_pins_and_a_different_tenant_stops_the_pairing(self):
        conn = self._conn('datto_rmm')
        advertise(conn, tenant='t-1')
        self.assertTrue(ticket_rmm.is_processor(conn))
        advertise(conn, tenant='t-2')
        conn.refresh_from_db()
        self.assertEqual(ticket_rmm.settings(conn)['tenant_id'], 't-1')  # never re-pinned
        self.assertFalse(ticket_rmm.is_processor(conn))
        self.assertEqual(ticket_rmm.advertised(conn), set())
        self.assertEqual(ticket_rmm.status(conn)['state'], 'error')
        advertise(conn, tenant='t-1')  # back to its own tenant
        conn.refresh_from_db()
        self.assertTrue(ticket_rmm.is_processor(conn))

    def test_rem0te_pin_stays_compatible(self):
        old = self._conn('rem0te', rem0te_business_id='biz-1')
        ticket_rmm.record_capabilities(old, {'contract': 'ticket-rmm-v1', 'capabilities': ['rmm_handoff']})
        old.refresh_from_db()
        self.assertEqual(ticket_rmm.settings(old)['tenant_id'], 'biz-1')  # no tenant field yet: inventory pin
        new = self._conn('rem0te', name='other', rem0te_business_id='biz-2')
        advertise(new, tenant='biz-3')  # disagrees with the business its API key answers for
        new.refresh_from_db()
        self.assertFalse(ticket_rmm.is_processor(new))


class CapabilityMappingTests(TestCase):
    """Unavailable exactly until the paired RMM advertises the matching capability."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='Alpha', slug='alpha')
        self.tech = make_tech('lee')
        grant(self.tech, self.org, 'l3')
        self.ticket = make_ticket(self.org, assigned_to=self.tech)
        self.conn = RMMConnection.objects.create(organization=self.org, provider_type='ninjaone', name='Ninja',
                                                 base_url='https://app.ninjarmm.com',
                                                 customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        self.conn.set_credentials({'integration_outbound_secret': 'o' * 40, 'integration_inbound_secret': 'i' * 40})
        self.conn.field_mappings = {'ticket_rmm_enabled': True, 'ticket_rmm_key_id': 'k1'}
        self.conn.save()

    def test_every_rmm_remote_and_fix_capability_has_a_requirement(self):
        grouped = {k for k, v in catalog.OPTIONAL.items() if v[1] in ('RMM', 'Remote access', 'Fixes')}
        self.assertEqual(grouped, set(catalog.INTEGRATION_REQUIRES))

    def test_mapping(self):
        def state(cap):
            return decide(self.tech, self.org, cap, ticket=self.ticket).state
        for cap in catalog.INTEGRATION_REQUIRES:
            self.assertEqual(state(cap), UNAVAILABLE, cap)  # paired, never checked
        advertise(self.conn, caps=['rmm_handoff'], tenant='n-1')
        self.assertEqual(state('rmm_handoff'), catalog.ALLOWED)
        self.assertEqual(state('diagnostics_readonly'), UNAVAILABLE)
        self.assertEqual(state('fix_request_low'), UNAVAILABLE)
        advertise(self.conn, caps=['rmm_handoff', 'diagnostics_readonly', 'remote_view', 'signed_actions'],
                  tenant='n-1')
        self.assertEqual(state('diagnostics_readonly'), catalog.ALLOWED)
        self.assertEqual(state('remote_view'), catalog.REQUEST)
        self.assertEqual(state('remote_control'), UNAVAILABLE)
        for cap in ('fix_request_low', 'fix_request_high', 'fix_refer'):
            self.assertEqual(state(cap), catalog.ALLOWED, cap)
        # Switching the pairing off makes them Unavailable again.
        m = dict(self.conn.field_mappings, ticket_rmm_enabled=False)
        RMMConnection.objects.filter(pk=self.conn.pk).update(field_mappings=m)
        self.assertEqual(state('rmm_handoff'), UNAVAILABLE)
        # Ticket AI never depended on it.
        self.assertEqual(state('ai_analyze'), catalog.ALLOWED)


# ---------------------------------------------------------------------------
# 56.5 / 56.6 against the test processor
# ---------------------------------------------------------------------------

class RMMActionBase(AssistBase):
    LAUNCH_URL = 'https://rem0te.example.com/session/abc?ticket=1'

    def setUp(self):
        super().setUp()
        from assets.models import Asset
        advertise(self.conn_a)
        self.conn_a.refresh_from_db()
        self.asset = Asset.objects.create(organization=self.a, name='Front desk PC', hostname='FRONTDESK-01',
                                          asset_type='desktop')
        self.device = RMMDevice.objects.create(
            organization=self.a, connection=self.conn_a, external_id='c-1', device_name='FRONTDESK-01',
            device_type='workstation', client_id='biz-alpha', linked_asset=self.asset,
            data_refreshed_at=timezone.now())
        self.ticket.related_asset = self.asset
        self.ticket.save()
        self.launch_answer = {'url': self.LAUNCH_URL,
                              'expires_at': (timezone.now() + timedelta(minutes=2)).isoformat()}

    def _processor(self, conn, method, path, payload=None, idempotency_key=''):
        self.calls.append((conn.pk, method, path, payload, idempotency_key))
        if path in ('/handoffs', '/diagnostics/requests', '/fixes'):
            return {'status': 'accepted', 'remote_id': 'r-' + payload['request_id'][:8]}
        if path == '/remote/launch':
            return self.launch_answer
        return super()._processor(conn, method, path, payload, idempotency_key)

    def post(self, name, data, client=None, ticket=None):
        t = ticket or self.ticket
        return (client or self.c).post(f'/psa/rmm/{t.ticket_number}/{name}/', data)

    def event(self, req, type_, seq, key='kid-alpha', **extra):
        body = {'request_id': str(req.id), 'event_id': f'{type_}-{seq}-{extra.pop("eid", "")}',
                'type': type_, 'sequence': seq}
        body.update(extra)
        return self.signed(key, EVENTS, body)

    def last(self, kind):
        return RMMRequest.objects.filter(kind=kind).order_by('-created_at').first()


class HandoffTests(RMMActionBase):
    def test_preview_then_sent_only_on_confirmed_receipt(self):
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/', {'device': self.device.pk})
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertNotIn('hunter2', html)
        self.assertNotIn('vault entry 42', html)
        digest = page.context['context_digest']
        key = page.context['idempotency_key']
        data = {'device': self.device.pk, 'idempotency_key': key, 'context_digest': digest,
                'note': 'Call pat@alpha.test first'}
        self.assertEqual(self.post('handoff', data).status_code, 302)
        req = self.last('handoff')
        self.assertEqual(req.status, 'pending')  # accepted, not yet confirmed
        conn, method, path, payload, ikey = self.calls[-1]
        self.assertEqual((conn, method, path, ikey), (self.conn_a.pk, 'POST', '/handoffs', key))
        blob = json.dumps(payload)
        self.assertNotIn('hunter2', blob)
        self.assertNotIn('pat@alpha.test', blob)
        self.assertEqual(payload['device'], {'external_id': 'c-1', 'name': 'FRONTDESK-01'})
        self.assertEqual(payload['tenant_id'], 'biz-alpha')
        ticket_page = self.c.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('data-status="pending"', ticket_page)
        # A double submit is the same request.
        self.post('handoff', data)
        self.assertEqual(RMMRequest.objects.filter(kind='handoff').count(), 1)
        # Unsigned receipt does nothing; the signed one marks it Sent.
        self.assertEqual(Client().post(EVENTS, json.dumps({'request_id': str(req.id), 'event_id': 'x',
                                                           'type': 'handoff.received', 'sequence': 1}),
                                       content_type='application/json').status_code, 401)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')
        self.assertEqual(self.event(req, 'handoff.received', 1).json()['status'], 'applied')
        self.assertEqual(self.event(req, 'handoff.received', 1).json()['status'], 'duplicate')
        req.refresh_from_db()
        self.assertEqual(req.status, 'sent')
        self.assertIsNotNone(req.confirmed_at)
        self.assertTrue(AuditLog.objects.filter(object_type='psa_ai.RMMRequest', user=self.tech).exists())

    def test_changed_ticket_after_preview_and_outage_are_visible(self):
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/', {'device': self.device.pk})
        TicketComment.objects.create(ticket=self.ticket, author=self.tech, body='More info.')
        self.post('handoff', {'device': self.device.pk, 'idempotency_key': page.context['idempotency_key'],
                              'context_digest': page.context['context_digest']})
        self.assertFalse(RMMRequest.objects.exists())
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/', {'device': self.device.pk})

        def down(*a, **kw):
            raise processor.ProcessorUnavailable('The RMM could not be reached (ConnectionError).')
        with patch('psa_ai.services.processor._request', side_effect=down):
            self.post('handoff', {'device': self.device.pk, 'idempotency_key': page.context['idempotency_key'],
                                  'context_digest': page.context['context_digest']})
        req = self.last('handoff')
        self.assertEqual(req.status, 'unavailable')
        self.assertIn('could not be reached', self.c.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode())

    def test_works_with_ai_switched_off(self):
        s = SystemSetting.get_settings()
        s.psa_ai_enabled = False
        s.save()
        self.assertFalse(self.preview().json()['available'])  # analysis is AI-gated
        page = self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/', {'device': self.device.pk})
        self.assertEqual(page.status_code, 200)
        self.post('handoff', {'device': self.device.pk, 'idempotency_key': page.context['idempotency_key'],
                              'context_digest': page.context['context_digest']})
        self.assertEqual(self.last('handoff').status, 'pending')
        html = self.c.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('id="ticket-rmm-panel"', html)
        self.assertNotIn('data-ai-assist="analyze"', html)


class TargetBoundaryTests(RMMActionBase):
    def test_crafted_and_cross_customer_devices_are_refused(self):
        from assets.models import Asset
        asset_b = Asset.objects.create(organization=self.b, name='B PC', asset_type='desktop')
        dev_b = RMMDevice.objects.create(organization=self.b, connection=self.conn_b, external_id='b-1',
                                         device_name='B-PC', linked_asset=asset_b, data_refreshed_at=timezone.now())
        unlinked = RMMDevice.objects.create(organization=self.a, connection=self.conn_a, external_id='c-2',
                                            device_name='OTHER', data_refreshed_at=timezone.now())
        stray = RMMDevice.objects.create(organization=self.a, connection=self.conn_b, external_id='x',
                                         device_name='stray', linked_asset=self.asset,
                                         ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED,
                                         data_refreshed_at=timezone.now())
        # (A Rem0te computer reported under another business: psa_ai/tests_rem0te.py.)
        self.assertEqual([t.device.pk for t in rmm_actions.targets(self.ticket)], [self.device.pk])
        before = len(self.calls)
        for pk in (dev_b.pk, unlinked.pk, stray.pk, 999999, 'c-1'):
            self.post('diagnostic', {'device': pk, 'diagnostic': 'disk_space', 'idempotency_key': f'k{pk}abcdefgh'})
            self.post('launch', {'device': pk, 'mode': 'view'})
            self.assertEqual(self.c.get(f'/psa/rmm/{self.ticket.ticket_number}/handoff/',
                                        {'device': pk}).status_code, 404)
        self.assertEqual(len(self.calls), before)
        self.assertFalse(RMMRequest.objects.exists())

    def test_asset_from_another_customer_and_unpaired_connection_give_no_target(self):
        m = dict(self.conn_a.field_mappings, ticket_rmm_enabled=False)
        RMMConnection.objects.filter(pk=self.conn_a.pk).update(field_mappings=m)
        self.assertEqual(rmm_actions.targets(self.ticket), [])

    def test_other_customers_ticket_and_portal_users_get_nothing(self):
        ticket_b = make_ticket(self.b, assigned_to=self.tech)
        self.assertEqual(self.post('launch', {'device': self.device.pk}, ticket=ticket_b).status_code, 404)
        portal = User.objects.create_user('client', password='pw')
        Membership.objects.create(user=portal, organization=self.a, role=Role.OWNER)
        self.ticket.client_can_view = True
        self.ticket.save()
        pc = sign_in(portal, self.a)
        self.assertEqual(self.post('launch', {'device': self.device.pk}, client=pc).status_code, 404)
        page = pc.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertNotIn('ticket-rmm-panel', page)

    def test_unavailable_reasons_are_shown_disabled(self):
        l1 = make_tech('helpdesk')
        grant(l1, self.a, 'l1')
        self.ticket.assigned_to = l1
        self.ticket.save()
        html = sign_in(l1, self.a).get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        panel = html.split('id="ticket-rmm-panel"', 1)[1]
        self.assertIn('disabled data-rmm-action="handoff"', panel)
        self.assertIn('does not include this', panel)
        self.assertEqual(self.post('launch', {'device': self.device.pk, 'mode': 'view'},
                                   client=sign_in(l1, self.a)).status_code, 302)
        self.assertFalse(any(c[2] == '/remote/launch' for c in self.calls))


class DiagnosticTests(RMMActionBase):
    def test_result_is_staff_only_sanitised_and_size_limited(self):
        r = self.post('diagnostic', {'device': self.device.pk, 'diagnostic': 'disk_space',
                                     'idempotency_key': 'diag-key-0001'})
        self.assertEqual(r.status_code, 302)
        req = self.last('diagnostic')
        self.assertEqual((req.status, req.diagnostic_key), ('pending', 'disk_space'))
        payload = self.calls[-1][3]
        self.assertEqual((payload['diagnostic'], payload['readonly'], payload['max_result_bytes']),
                         ('disk_space', True, rmm_actions.MAX_RESULT_BYTES))
        self.assertEqual(self.event(req, 'diagnostic.accepted', 1).json()['status'], 'applied')
        big = '<script>alert(1)</script>\x1b[31mC: 12 GB free\npassword: hunter3\n' + 'x' * 40000
        self.assertEqual(self.event(req, 'diagnostic.completed', 2,
                                    result={'content_type': 'text/plain', 'text': big}).json()['status'], 'applied')
        req.refresh_from_db()
        self.assertEqual(req.status, 'completed')
        self.assertTrue(req.result_truncated)
        self.assertLessEqual(len(req.result_text.encode()), rmm_actions.MAX_RESULT_BYTES + 100)
        self.assertNotIn('hunter3', req.result_text)
        self.assertNotIn('\x1b', req.result_text)
        html = self.c.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('&lt;script&gt;alert(1)', html)
        self.assertNotIn('<script>alert(1)', html)
        self.assertEqual(TicketComment.objects.filter(ticket=self.ticket, body__contains='12 GB').count(), 0)
        from tech_access.models import ReadEvent
        self.assertTrue(ReadEvent.objects.filter(user=self.tech, kind='diagnostic_bytes', amount__gt=0).exists())
        # Customers never see it.
        portal = User.objects.create_user('client', password='pw')
        Membership.objects.create(user=portal, organization=self.a, role=Role.OWNER)
        self.ticket.client_can_view = True
        self.ticket.save()
        page = sign_in(portal, self.a).get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertNotIn('12 GB free', page)
        self.assertNotIn('Disk space', page)

    def test_only_advertised_diagnostics_for_this_device_class(self):
        for key in ('server_roles', 'BAD KEY', 'rm -rf'):
            self.post('diagnostic', {'device': self.device.pk, 'diagnostic': key, 'idempotency_key': 'k-' + key[:4] + 'zzzzzzzz'})
        self.assertFalse(RMMRequest.objects.exists())
        advertise(self.conn_a, caps=['rmm_handoff'])
        self.post('diagnostic', {'device': self.device.pk, 'diagnostic': 'disk_space', 'idempotency_key': 'kkkkkkkk1'})
        self.assertFalse(RMMRequest.objects.exists())

    def test_oversized_event_body_is_refused(self):
        self.post('diagnostic', {'device': self.device.pk, 'diagnostic': 'disk_space', 'idempotency_key': 'diag-key-02'})
        req = self.last('diagnostic')
        r = self.event(req, 'diagnostic.completed', 1, result={'text': 'y' * 70000})
        self.assertEqual(r.status_code, 413)


class LaunchTests(RMMActionBase):
    def test_launch_redirects_validates_and_audits_without_storing(self):
        r = self.post('launch', {'device': self.device.pk, 'mode': 'view'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], self.LAUNCH_URL)
        self.assertEqual(r['Cache-Control'], 'no-store')
        payload = self.calls[-1][3]
        self.assertEqual((payload['mode'], payload['grant'], payload['device']), ('view', 'request',
                                                                                    {'external_id': 'c-1'}))
        log = AuditLog.objects.filter(object_type='psa_ai.RemoteLaunch').latest('pk')
        self.assertTrue(log.success)
        self.assertNotIn('session/abc', json.dumps(log.extra_data) + log.description)
        self.assertFalse(RMMRequest.objects.exists())

    def test_bad_launch_urls_are_refused(self):
        soon = (timezone.now() + timedelta(minutes=2)).isoformat()
        for answer in ({'url': 'https://evil.example.net/s', 'expires_at': soon},
                       {'url': 'http://rem0te.example.com/s', 'expires_at': soon},
                       {'url': 'https://user:pw@rem0te.example.com/s', 'expires_at': soon},
                       {'url': 'https://rem0te.example.com/s?token=abc', 'expires_at': soon},
                       {'url': 'javascript:alert(1)', 'expires_at': soon},
                       {'url': self.LAUNCH_URL},
                       {'url': self.LAUNCH_URL, 'expires_at': (timezone.now() + timedelta(hours=2)).isoformat()}):
            self.launch_answer = answer
            r = self.post('launch', {'device': self.device.pk, 'mode': 'control'})
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r['Location'].startswith(f'/psa/t/{self.ticket.ticket_number}/'), answer)
        self.assertEqual(AuditLog.objects.filter(object_type='psa_ai.RemoteLaunch', success=False).count(), 7)

    def test_launch_needs_the_advertised_capability(self):
        advertise(self.conn_a, caps=['rmm_handoff', 'remote_view'])
        r = self.post('launch', {'device': self.device.pk, 'mode': 'control'})
        self.assertTrue(r['Location'].startswith('/psa/t/'))
        self.assertFalse(any(c[2] == '/remote/launch' for c in self.calls))


class FixReferralTests(RMMActionBase):
    def _refer(self, **over):
        data = {'device': self.device.pk, 'idempotency_key': over.pop('key', 'fix-key-0001'), 'risk': 'low',
                'title': 'Re-add printer by IP', 'description': 'Re-add the front desk printer by its IP.'}
        data.update(over)
        self.post('fix', data)
        return self.last('fix_referral')

    def test_needs_signed_actions(self):
        advertise(self.conn_a, caps=['rmm_handoff', 'fix_request_low'])
        self.assertIsNone(self._refer())

    def test_statuses_only_from_valid_signed_events_and_never_touch_the_ticket(self):
        req = self._refer()
        self.assertEqual(req.status, 'pending')
        self.assertEqual(self.calls[-1][2], '/fixes')
        self.assertEqual(self.calls[-1][3]['fix']['source'], {'type': 'technician'})
        status_before, comments_before = self.ticket.status_id, TicketComment.objects.count()
        body = {'request_id': str(req.id), 'event_id': 'f1', 'type': 'fix.approved', 'sequence': 1}
        # Forged (wrong secret, or ClientSt0r's own outbound secret), unsigned, other pairing.
        self.assertEqual(self.signed('kid-alpha', EVENTS, body, secret='w' * 40).status_code, 401)
        self.assertEqual(self.signed('kid-alpha', EVENTS, body, secret=OUT_SECRET + 'kid-alpha').status_code, 401)
        self.assertEqual(Client().post(EVENTS, json.dumps(body), content_type='application/json').status_code, 401)
        self.assertEqual(self.signed('kid-beta', EVENTS, body).status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')
        # Running before approval is not a valid step.
        self.assertEqual(self.event(req, 'fix.running', 1).json()['status'], 'recorded')
        nonce = 'r' * 24
        self.assertEqual(self.signed('kid-alpha', EVENTS, body, nonce=nonce).json()['status'], 'applied')
        replay = dict(body, event_id='f1-again', sequence=5)
        self.assertEqual(self.signed('kid-alpha', EVENTS, replay, nonce=nonce).status_code, 401)  # nonce reused
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertEqual(self.event(req, 'fix.received', 2).json()['status'], 'recorded')  # can't go back
        self.assertEqual(self.event(req, 'handoff.received', 3).status_code, 409)  # wrong kind
        self.assertEqual(self.event(req, 'fix.running', 4).json()['status'], 'applied')
        self.assertEqual(self.event(req, 'fix.succeeded', 3).json()['status'], 'recorded')  # out of order
        self.assertEqual(self.event(req, 'fix.succeeded', 6, message='Printer re-added.').json()['status'],
                         'applied')
        req.refresh_from_db()
        self.assertEqual((req.status, req.status_note), ('succeeded', 'Printer re-added.'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status_id, status_before)
        self.assertEqual(TicketComment.objects.count(), comments_before)
        self.assertGreaterEqual(RMMRequestEvent.objects.filter(request=req).count(), 6)

    def test_clientst0r_cannot_approve_and_has_no_route_for_it(self):
        from django.urls import NoReverseMatch, reverse
        req = self._refer()
        for name in ('approve', 'fix_approve', 'run'):
            with self.assertRaises(NoReverseMatch):
                reverse(f'ticket_rmm:{name}', args=[self.ticket.ticket_number])
        self.assertEqual(self.c.post(f'/psa/rmm/{self.ticket.ticket_number}/fix/approve/', {}).status_code, 404)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_from_an_analysis_suggestion_uses_the_stored_text(self):
        job = AnalysisJob.objects.create(
            organization=self.a, ticket=self.ticket, ticket_revision='r', actor=self.tech, kind='analyze',
            connection=self.conn_a, business_id='biz-alpha', evidence={}, evidence_digest='d', payload_digest='p',
            idempotency_key='j1', expires_at=timezone.now() + timedelta(minutes=5), status='completed')
        AnalysisRun.objects.create(job=job, profile=self.cheap, status='succeeded', finished_at=timezone.now(),
                                   result={'suggested_checks': [{'text': 'Re-add the printer by IP address.'}]})
        req = self._refer(title='', description='', suggestion=f'{job.id}:{self.cheap.pk}:0')
        self.assertEqual(req.payload['fix']['description'], 'Re-add the printer by IP address.')
        self.assertEqual(req.payload['fix']['source']['type'], 'analysis')
        self._refer(key='fix-key-0002', suggestion=f'{job.id}:{self.cheap.pk}:7')  # not a stored suggestion
        self.assertEqual(RMMRequest.objects.filter(kind='fix_referral').count(), 1)

    def test_higher_risk_needs_fix_request_high(self):
        self.assertIsNone(self._refer(risk='high'))  # L2 has only fix_request_low
