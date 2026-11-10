"""
Rem0te's Ed25519 protocol (contract ticket-rmm-v1, pinned in
integrations/rem0te/contract/PIN.json): fixture vectors, schemas, signing,
delegation, Check pairing failure reasons, inbound authentication, the
HMAC → Ed25519 migration and the connection page. The in-process Rem0te is
integrations/rem0te/testing.py; the real one is scripts/e2e/cross_peer/.
"""
import importlib
import json
import time
from unittest.mock import patch

from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings

from core.models import Organization
from integrations import ticket_rmm
from integrations.forms import RMMConnectionForm
from integrations.models import RMMConnection, Rem0teIdentity, Rem0teReplayGuard
from integrations.rem0te import client, identity, inbound, pairing, protocol, schema, testing as rt
from psa.tests._base import TEST_MIDDLEWARE

FIX = schema.FIXTURE_DIR


def fixture(name):
    return json.loads((FIX / name).read_text())


def pem(name):
    return (FIX / name).read_text()


class FixtureVectorTests(SimpleTestCase):
    def test_job_event_fixture_verifies_with_its_key_only(self):
        signed = fixture('signed-event.job-succeeded.json')
        keys = protocol.keyring([{'kid': 'fixture-signing-key', 'public_key_pem': pem('fixture-signing-key.pub.pem')}])
        self.assertEqual(protocol.verify_event_signature(signed['event'], signed['signature'], keys), '')
        # The alert prefix must not verify a job event (domain separation).
        self.assertNotEqual(protocol.verify_event_signature(signed['event'], signed['signature'], keys, alert=True), '')
        tampered = json.loads(json.dumps(signed['event']))
        tampered['sequence'] += 1
        self.assertNotEqual(protocol.verify_event_signature(tampered, signed['signature'], keys), '')
        other = protocol.keyring([{'kid': 'fixture-signing-key',
                                   'public_key_pem': pem('fixture-alert-signing-key.pub.pem')}])
        self.assertNotEqual(protocol.verify_event_signature(signed['event'], signed['signature'], other), '')

    def test_alert_event_fixture_verifies_with_its_key_only(self):
        signed = fixture('signed-alert-event.raised.json')
        keys = protocol.keyring([{'kid': 'fixture-alert-signing-key',
                                  'public_key_pem': pem('fixture-alert-signing-key.pub.pem')}])
        ev, sig = signed['alert_event'], signed['signature']
        self.assertEqual(protocol.verify_event_signature(ev, sig, keys, alert=True), '')
        self.assertNotEqual(protocol.verify_event_signature(ev, sig, keys, alert=False), '')
        unknown = protocol.keyring([{'kid': 'someone-else', 'public_key_pem': pem('fixture-alert-signing-key.pub.pem')}])
        self.assertNotEqual(protocol.verify_event_signature(ev, sig, unknown, alert=True), '')

    def test_canonical_json_matches_javascript(self):
        value = {'z': [1, -0.000001, 1e-7, 123.456, 5e-324, 2 ** 53 - 1],
                 'é': 'x \x7f\x01"\\\n\t\ud800', 'A': {'b': None, 'a': True}, '😀': 1, '０': 2}
        self.assertEqual(protocol.canonical_json(value),
                         '{"A":{"a":true,"b":null},"z":[1,-0.000001,1e-7,123.456,5e-324,9007199254740991],'
                         '"é":"x \x7f\\u0001\\"\\\\\\n\\t\\ud800","😀":1,"０":2}')

    def test_request_hash_matches_rem0te_fixtures(self):
        req = fixture('job-request.ticket-with-device.json')
        sha = protocol.sha256_hex(protocol.canonical_json(req))
        self.assertEqual(sha, 'b16fb8ff5f2517f65d910cc4af6c78e8057834c257f9646824c65188e5e83857')
        self.assertEqual(fixture('job.queued.json')['payload_sha256'], sha)
        self.assertEqual(fixture('delegation-claims.submit.json')['req_sha256'], sha)

    def test_valid_fixtures_pass_and_invalid_fixtures_are_rejected(self):
        names = sorted(p.name for p in FIX.glob('*.json'))
        self.assertGreaterEqual(len(names), 25)
        invalid = [n for n in names if '.invalid-' in n]
        self.assertEqual(len(invalid), 8)
        for n in names:
            sch = n.split('.')[0]
            errs = schema.errors(sch, fixture(n))
            if '.invalid-' in n:
                self.assertTrue(errs, f'{n} should be rejected')
            else:
                self.assertEqual(errs, [], n)

    def test_signing_strings_are_exact(self):
        self.assertEqual(protocol.request_signing_string('aud', 'POST', '/p?q=1', '1700000000', 'n' * 16, 'ab'),
                         'rem0te-http-req-v1\naud\nPOST\n/p?q=1\n1700000000\n' + 'n' * 16 + '\nab')
        self.assertEqual(protocol.response_signing_string('nonce', 'cd'), 'rem0te-http-resp-v1\nnonce\ncd')

    def test_request_headers_verify_and_delegation_round_trips(self):
        key = protocol.load_private_key(protocol.generate_private_key_pem())
        pub = protocol.load_public_key(protocol.public_pem(key))
        h = protocol.request_headers(key, 'cs/k1', 'rem0te:x', 'GET', '/api/integration/v1/capabilities', b'')
        self.assertRegex(h[protocol.H_NONCE], protocol.NONCE_RE)
        msg = protocol.request_signing_string('rem0te:x', 'GET', '/api/integration/v1/capabilities',
                                              h[protocol.H_TIMESTAMP], h[protocol.H_NONCE], protocol.sha256_hex(b''))
        self.assertTrue(protocol.verify(pub, msg, h[protocol.H_SIGNATURE]))
        self.assertFalse(protocol.verify(pub, msg.replace('rem0te:x', 'rem0te:y'), h[protocol.H_SIGNATURE]))
        claims = protocol.delegation_claims(peer_id='cs', audience='rem0te:x', technician_id='tech-1',
                                            organization_id='org-1', scope='ticket_analysis:submit',
                                            req_sha256='a' * 64)
        self.assertLessEqual(claims['exp'] - claims['iat'], protocol.MAX_DELEGATION_TTL_S)
        self.assertEqual(schema.errors('delegation-claims', claims), [])
        token = protocol.sign_jws(key, 'd1', claims)
        header, payload, _, _ = protocol.parse_jws(token)
        self.assertEqual(header, {'alg': 'EdDSA', 'kid': 'd1', 'typ': 'rem0te-delegation+jwt'})
        self.assertEqual(protocol.verify_jws(token, {'d1': pub}), claims)
        with self.assertRaises(protocol.ProtocolError):
            protocol.delegation_claims(peer_id='cs', audience='a', technician_id='t', organization_id='o',
                                       scope='ticket_analysis:submit', ttl=301)

    def test_pin_records_the_tested_rem0te(self):
        pin = pairing.pin()
        self.assertEqual(pin['contract'], 'ticket-rmm-v1')
        self.assertEqual(pin['rem0te_sha'], '1bff01a4a3b52fd745e001352e0c417909199aeb')


class SigningKeyParsingTests(SimpleTestCase):
    def test_pem_blocks_and_json(self):
        a, b = pem('fixture-signing-key.pub.pem'), pem('fixture-alert-signing-key.pub.pem')
        keys = pairing.parse_signing_keys(f'k-1\n{a}\nk-2\n{b}')
        self.assertEqual([k['kid'] for k in keys], ['k-1', 'k-2'])
        caps = fixture('capabilities.lab.json')
        self.assertEqual(pairing.parse_signing_keys(json.dumps(caps))[0]['kid'], 'fixture-signing-key')
        self.assertEqual(pairing.parse_signing_keys(pairing.format_signing_keys(keys)), keys)

    def test_refusals(self):
        priv = protocol.generate_private_key_pem()
        for text, why in ((f'k\n{priv}', 'private key'), (pem('fixture-signing-key.pub.pem'), 'key id'),
                          ('bad kid!\n' + pem('fixture-signing-key.pub.pem'), 'not a valid key id'),
                          ('k\n-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----', 'Key "k"'),
                          ('[{"kid": "a"}]', 'Key "a"')):
            with self.assertRaisesMessage(ValueError, why):
                pairing.parse_signing_keys(text)
        five = '\n'.join(f'k{i}\n{pem("fixture-signing-key.pub.pem")}' for i in range(5))
        with self.assertRaisesMessage(ValueError, 'At most 4'):
            pairing.parse_signing_keys(five)


class IdentityTests(TestCase):
    def test_keys_encrypted_at_rest_and_never_in_the_public_view(self):
        ident = rt.setup_identity()
        from django.db import connection as db
        with db.cursor() as cur:
            cur.execute('SELECT request_private_key, delegation_private_key FROM integrations_rem0te_identity')
            raw = cur.fetchone()
        for value in raw:
            self.assertNotIn('PRIVATE KEY', value)
        self.assertIn('PRIVATE KEY', ident.request_private_key)
        view = json.dumps(identity.public_view(ident), default=str)
        self.assertNotIn('PRIVATE', view)
        entry = json.loads(identity.peer_entry_json())
        self.assertEqual(entry['id'], rt.PEER_ID)
        self.assertEqual(entry['peerAudience'], rt.CS_AUDIENCE)
        self.assertEqual(entry['inferenceUrl'], 'https://cs.example.com/api/integration/v1/inference')
        self.assertNotIn('PRIVATE', json.dumps(entry))
        self.assertNotEqual(ident.request_kid, ident.delegation_kid)

    def test_rotation_replaces_keys(self):
        ident = rt.setup_identity()
        before = (ident.request_kid, protocol.public_pem(ident.request_private_key))
        identity.generate_keys(rotate=True)
        ident = identity.get()
        self.assertNotEqual(before, (ident.request_kid, protocol.public_pem(ident.request_private_key)))

    def test_base_url_rules(self):
        self.assertEqual(identity.validate_base_url('https://cs.example.com'), '')
        self.assertEqual(identity.validate_base_url('http://127.0.0.1:8123'), '')
        self.assertNotEqual(identity.validate_base_url('http://cs.example.com'), '')
        self.assertNotEqual(identity.validate_base_url('https://u:p@cs.example.com'), '')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CheckPairingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Alpha', slug='alpha')
        self.ident = rt.setup_identity()
        self.conn = rt.make_connection(self.org)
        self.fake = rt.FakeRem0te()

    def check(self):
        with self.fake.running():
            doc = pairing.check(self.conn)
        self.conn.refresh_from_db()
        return doc

    def assertNoSecrets(self, text):
        for secret in (self.ident.request_private_key, self.ident.delegation_private_key):
            body = ''.join(secret.strip().splitlines()[1:-1])
            self.assertNotIn(body[:20], text)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('rk_test', text)

    def test_success(self):
        doc = self.check()
        self.assertTrue(doc['ok'] and doc['compatible'], doc)
        self.assertTrue(doc['org_mapped'])
        self.assertTrue(pairing.is_processor(self.conn))
        self.assertEqual(pairing.advertised(self.conn), {'analysis.jobs', 'signed_actions', 'alerts'})
        self.assertTrue(ticket_rmm.is_processor(self.conn))
        method, route, _, headers = self.fake.calls[0]
        self.assertEqual((method, route), ('GET', '/capabilities'))
        self.assertEqual(headers[protocol.H_KEY_ID], f'{rt.PEER_ID}/{self.ident.request_kid}')
        self.assertEqual(pairing.status(self.conn)['state'], 'ok')

    def _fails(self, code, **fake):
        for k, v in fake.items():
            setattr(self.fake, k, v)
        doc = self.check()
        self.assertFalse(doc['ok'])
        self.assertEqual(doc['code'], code, doc)
        self.assertTrue(doc['error'])
        self.assertNoSecrets(json.dumps(doc))
        self.assertNoSecrets(json.dumps(pairing.status(self.conn), default=str).replace(
            json.dumps(identity.peer_entry_json(self.conn)), ''))
        return doc

    def test_failure_reasons(self):
        doc = self._fails('UNREACHABLE', fail=lambda m, r: ('unreachable',))
        self.assertIn('rem0te.example.com', doc['error'])
        doc = self._fails('NOT_CONFIGURED', fail=lambda m, r: (404, 'NOT_CONFIGURED', 'x'))
        self.assertIn('INTEGRATION_PEERS_FILE', doc['error'])
        doc = self._fails('KEY_UNKNOWN', fail=lambda m, r: (401, 'UNAUTHENTICATED', 'Unknown key'))
        self.assertIn(self.ident.request_kid, doc['error'])
        doc = self._fails('CLOCK_SKEW', fail=lambda m, r: (401, 'UNAUTHENTICATED', 'Timestamp outside the allowed window'))
        doc = self._fails('SIGNATURE_REJECTED', fail=lambda m, r: (401, 'UNAUTHENTICATED', 'Request signature invalid'))
        self.assertIn(rt.REM0TE_AUDIENCE, doc['error'])
        self._fails('REPLAYED', fail=lambda m, r: (401, 'REPLAYED', 'Nonce already used'))
        self._fails('CLIENT_CERT', fail=lambda m, r: (401, 'UNAUTHENTICATED', 'Client certificate not presented or not pinned'))
        self._fails('RATE_LIMITED', fail=lambda m, r: (429, 'RATE_LIMITED', 'slow down'))

    def test_wrong_audience_is_rejected_by_rem0te(self):
        m = dict(self.conn.field_mappings, **{pairing.AUDIENCE: 'rem0te:other'})
        self.conn.field_mappings = m
        self.conn.save()
        doc = self.check()
        self.assertEqual(doc['code'], 'SIGNATURE_REJECTED')
        self.assertIn('rem0te:other', doc['error'])

    def test_incompatible_peer_is_refused(self):
        self.fake.caps = rt.capabilities(version='0.25.9')
        self.assertEqual(self.check()['code'], 'VERSION_INCOMPATIBLE')
        self.fake.caps = rt.capabilities(contract='ticket-rmm-v2')
        self.assertEqual(self.check()['code'], 'CONTRACT_MISMATCH')
        self.fake.caps = dict(rt.capabilities(), surprise=True)
        self.assertEqual(self.check()['code'], 'CONTRACT_MISMATCH')
        self.fake.caps = rt.capabilities(peer_id='someone-else')
        self.assertEqual(self.check()['code'], 'PEER_MISMATCH')
        other = protocol.public_pem(protocol.generate_private_key_pem())
        self.fake.caps = rt.capabilities(signing_keys=[{'kid': rt.KID, 'alg': 'Ed25519', 'public_key_pem': other}])
        doc = self.check()
        self.assertEqual(doc['code'], 'SIGNING_KEY_MISMATCH')
        self.assertFalse(pairing.is_processor(self.conn))
        self.fake.caps = rt.capabilities(version='0.30.1')
        doc = self.check()
        self.assertTrue(doc['compatible'])
        self.assertTrue(any('different release' in w for w in doc['warnings']))

    def test_unmapped_organization_is_a_warning(self):
        self.fake.mapped_orgs = set()
        doc = self.check()
        self.assertTrue(doc['compatible'])
        self.assertFalse(doc['org_mapped'])
        self.assertTrue(any(pairing.organization_id(self.conn) in w for w in doc['warnings']))

    def test_outage_after_good_check_keeps_capabilities(self):
        self.check()
        self.fake.fail = lambda m, r: ('unreachable',)
        doc = self.check()
        self.assertEqual(doc['code'], 'UNREACHABLE')
        self.assertTrue(doc['compatible'])

    def test_local_side_incomplete(self):
        Rem0teIdentity.objects.update(audience='')
        doc = self.check()
        self.assertEqual(doc['code'], 'NOT_CONFIGURED_LOCAL')
        self.assertEqual(self.fake.calls, [])

    def test_never_hmac_for_rem0te(self):
        from psa_ai.services import integration_auth, processor
        self.conn.set_credentials({'api_key': 'rk_test', 'integration_outbound_secret': 'o' * 40,
                                   'integration_inbound_secret': 'i' * 40})
        self.conn.field_mappings = dict(self.conn.field_mappings, ticket_rmm_key_id='kid-old')
        self.conn.save()
        with self.assertRaises(processor.ProcessorUnavailable):
            processor._request(self.conn, 'GET', '/capabilities')
        self.assertIsNone(ticket_rmm.find_by_key_id('kid-old'))
        self.assertEqual(ticket_rmm.settings(self.conn)['has_secrets'], False)
        headers = integration_auth.sign('i' * 40, 'POST', '/api/integration/v1/events', b'{}', 'kid-old')
        r = Client().post('/api/integration/v1/events', b'{}', content_type='application/json',
                          **{'HTTP_' + k.upper().replace('-', '_'): v for k, v in headers.items()})
        self.assertIn(r.status_code, (401, 403))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InboundAuthTests(TestCase):
    PATH = '/api/integration/v1/events'

    def setUp(self):
        call_command('psa_seed_defaults', verbosity=0)
        self.org = Organization.objects.create(name='Alpha', slug='alpha')
        rt.setup_identity()
        self.conn = rt.make_connection(self.org)
        self.c = Client()

    def body(self):
        fake = rt.FakeRem0te()
        return fake.alert_event(pairing.organization_id(self.conn), 1)

    def test_accepts_signed_and_refuses_replay(self):
        nonce = 'n' * 22
        r = rt.signed_post(self.c, self.PATH, self.body(), nonce=nonce)
        self.assertEqual(r.status_code, 200, r.content)
        r = rt.signed_post(self.c, self.PATH, self.body(), nonce=nonce)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['error']['code'], 'REPLAYED')
        self.assertTrue(Rem0teReplayGuard.objects.filter(key__endswith=nonce).exists())

    def test_refusals(self):
        other = protocol.load_private_key(protocol.generate_private_key_pem())
        cases = [dict(key=other), dict(kid='unknown-kid'), dict(audience='clientst0r:other'),
                 dict(ts=str(int(time.time()) - 300))]
        for kw in cases:
            r = rt.signed_post(self.c, self.PATH, self.body(), **kw)
            self.assertEqual(r.status_code, 401, kw)
            self.assertNotIn('PRIVATE', r.content.decode())
        r = self.c.post(self.PATH, b'{}', content_type='application/json', HTTP_REM0TE_KEY_ID='rem0te/x')
        self.assertEqual(r.status_code, 401)

    def test_unit_authenticate_binds_connection_by_key(self):
        org_b = Organization.objects.create(name='Beta', slug='beta')
        conn_b = rt.make_connection(org_b, name='B')
        r = rt.signed_post(self.c, self.PATH, rt.FakeRem0te().alert_event(pairing.organization_id(conn_b), 1))
        self.assertEqual(r.status_code, 200)
        from psa_ai.models import Rem0teAlertEvent
        self.assertTrue(Rem0teAlertEvent.objects.filter(connection=conn_b).exists())
        self.assertFalse(Rem0teAlertEvent.objects.filter(connection=self.conn).exists())
        # An organization with no Rem0te pairing here is 404.
        r = rt.signed_post(self.c, self.PATH, rt.FakeRem0te().alert_event('org-99999', 1))
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UnreadyPSATests(TestCase):
    """An alert that cannot open its ticket yet is not acknowledged."""

    def test_alert_without_psa_setup_is_retried_not_lost(self):
        from psa.models import Queue, Ticket
        from psa_ai.models import Rem0teAlertEvent
        Queue.objects.all().delete()
        org = Organization.objects.create(name='Alpha', slug='alpha')
        rt.setup_identity()
        conn = rt.make_connection(org)
        body = rt.FakeRem0te().alert_event(pairing.organization_id(conn), 1)
        r = rt.signed_post(Client(), '/api/integration/v1/events', body)
        self.assertEqual(r.status_code, 503, r.content)
        self.assertEqual(r.json()['error']['code'], 'UNAVAILABLE')
        self.assertFalse(Rem0teAlertEvent.objects.exists())  # not recorded: the retry is applied
        call_command('psa_seed_defaults', verbosity=0)
        r = rt.signed_post(Client(), '/api/integration/v1/events', body)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Ticket.objects.filter(organization=org, source='rmm').count(), 1)


class MigrationTests(TestCase):
    mod = importlib.import_module('integrations.migrations.0036_rem0te_hmac_needs_repair')

    def setUp(self):
        self.org = Organization.objects.create(name='Alpha', slug='alpha')

    def _conn(self, provider, **m):
        conn = RMMConnection.objects.create(organization=self.org, provider_type=provider,
                                            name=m.pop('name', provider),
                                            base_url='https://rmm.example.com',
                                            customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
        conn.set_credentials({'api_key': 'k', 'integration_outbound_secret': 'o' * 40,
                              'integration_inbound_secret': 'i' * 40})
        conn.field_mappings = m
        conn.save()
        return conn

    def test_hmac_rem0te_pairing_needs_repair_and_reverses(self):
        caps = {'contract': 'ticket-rmm-v1', 'capabilities': ['rmm_handoff']}
        old = {'ticket_rmm_enabled': True, 'ticket_rmm_key_id': 'kid-1', 'ticket_rmm_capabilities': caps,
               'ticket_rmm_location': 'local', 'ticket_rmm_tenant_id': 'biz-1'}
        conn = self._conn('rem0te', **old)
        never = self._conn('rem0te', name='never paired', device_type_map={'a': 'b'})
        other = self._conn('tactical_rmm', **old)
        self.mod.forwards(django_apps, None)
        conn.refresh_from_db()
        m = conn.field_mappings
        self.assertIs(m['ticket_rmm_enabled'], False)
        self.assertTrue(m['ticket_rmm_needs_repair'])
        self.assertEqual(m['ticket_rmm_auth'], 'ed25519')
        self.assertNotIn('ticket_rmm_key_id', m)
        self.assertNotIn('ticket_rmm_capabilities', m)
        s = ticket_rmm.settings(conn)
        self.assertFalse(s['enabled'])
        self.assertIn('paired again with Ed25519', s['incomplete'])
        self.assertEqual(ticket_rmm.status(conn)['label'], 'Needs re-pairing (Ed25519)')
        self.assertFalse(ticket_rmm.is_processor(conn))
        self.assertEqual(conn.get_credentials()['integration_outbound_secret'], 'o' * 40)  # kept, unused
        never.refresh_from_db()
        self.assertEqual(never.field_mappings, {'device_type_map': {'a': 'b'}})
        other.refresh_from_db()
        self.assertEqual(other.field_mappings, old)
        self.mod.forwards(django_apps, None)  # idempotent
        self.mod.backwards(django_apps, None)
        conn.refresh_from_db()
        self.assertEqual(conn.field_mappings, old)
        other.refresh_from_db()
        self.assertEqual(other.field_mappings, old)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConnectionFormAndPageTests(TestCase):
    def setUp(self):
        from tech_access.testing import make_tech
        self.org = Organization.objects.create(name='Alpha', slug='alpha')
        self.admin = make_tech('root', superuser=True)
        from psa_ai.tests_assist import sign_in
        self.c = sign_in(self.admin, self.org)

    def form(self, instance=None, **data):
        base = {'provider_type': 'rem0te', 'name': 'Rem0te', 'base_url': 'https://rem0te.example.com',
                'rem0te_api_key': 'rk_x', 'sync_interval_minutes': 60, 'customer_scope': 'single',
                'ticket_rmm_location': 'hosted'}
        base.update(data)
        return RMMConnectionForm(base, instance=instance, organization=self.org)

    def test_rem0te_pairs_with_keys_not_secrets(self):
        f = self.form(ticket_rmm_enabled='on')
        self.assertFalse(f.is_valid())
        self.assertIn('rem0te_audience', f.errors)
        self.assertIn('rem0te_signing_keys', f.errors)
        self.assertNotIn('ticket_rmm_outbound_secret', f.errors)
        f = self.form(ticket_rmm_enabled='on', rem0te_audience=rt.REM0TE_AUDIENCE,
                      rem0te_signing_keys=f'{rt.KID}\n{rt.rem0te_public_pem()}',
                      ticket_rmm_outbound_secret='o' * 40, ticket_rmm_inbound_secret='i' * 40)
        self.assertTrue(f.is_valid(), f.errors)
        conn = f.save()
        self.assertEqual(f.pairing_request, {'enable': True})
        m = conn.field_mappings
        self.assertEqual(m[pairing.AUDIENCE], rt.REM0TE_AUDIENCE)
        self.assertEqual(m[pairing.SIGNING_KEYS][0]['kid'], rt.KID)
        self.assertEqual(m[pairing.AUTH], 'ed25519')
        self.assertNotIn('integration_outbound_secret', conn.get_credentials())
        self.assertFalse(m.get(ticket_rmm.ENABLED))  # waits for the second administrator

    def test_repairing_clears_needs_repair(self):
        conn = rt.make_connection(self.org, enabled=False, **{pairing.NEEDS_REPAIR: True,
                                                              pairing.LEGACY: {'ticket_rmm_enabled': True}})
        f = self.form(instance=conn, ticket_rmm_enabled='on', rem0te_audience=rt.REM0TE_AUDIENCE,
                      rem0te_signing_keys=f'{rt.KID}\n{rt.rem0te_public_pem()}')
        self.assertTrue(f.is_valid(), f.errors)
        conn = f.save()
        self.assertNotIn(pairing.NEEDS_REPAIR, conn.field_mappings)
        self.assertIn(pairing.LEGACY, conn.field_mappings)

    def test_changing_keys_of_a_live_pairing_switches_it_off(self):
        conn = rt.make_connection(self.org)
        other = protocol.public_pem(protocol.generate_private_key_pem())
        f = self.form(instance=conn, ticket_rmm_enabled='on', rem0te_audience=rt.REM0TE_AUDIENCE,
                      rem0te_signing_keys=f'{rt.KID}\n{other}')
        self.assertTrue(f.is_valid(), f.errors)
        conn = f.save()
        self.assertIs(conn.field_mappings[ticket_rmm.ENABLED], False)
        self.assertEqual(f.pairing_request, {'enable': True})

    def test_hmac_providers_unchanged(self):
        f = self.form(provider_type='tactical_rmm', tactical_api_key='t', ticket_rmm_enabled='on')
        self.assertFalse(f.is_valid())
        self.assertIn('ticket_rmm_outbound_secret', f.errors)

    def test_connection_page_shows_steps_and_public_keys_only(self):
        rt.setup_identity()
        conn = rt.make_connection(self.org, **{pairing.NEEDS_REPAIR: True})
        html = self.c.get(f'/integrations/rmm/{conn.pk}/').content.decode()
        self.assertIn('Needs re-pairing (Ed25519)', html)
        self.assertIn('data-rem0te-steps', html)
        self.assertIn('requestKeys', html)
        self.assertIn(pairing.organization_id(conn), html)
        self.assertNotIn('PRIVATE KEY', html)
        self.assertNotIn('Secret ClientSt0r signs with', html.split('data-rem0te-pairing')[1].split('</details>')[0])

    def test_identity_actions_superuser_only(self):
        conn = rt.make_connection(self.org)
        r = self.c.post(f'/integrations/rmm/{conn.pk}/pairing/rem0te-identity/', {'op': 'generate'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(identity.has_keys())
        r = self.c.post(f'/integrations/rmm/{conn.pk}/pairing/rem0te-identity/',
                        {'op': 'update', 'peer_id': 'cs-1', 'audience': 'clientst0r:x',
                         'public_base_url': 'https://cs.example.com'})
        self.assertEqual(identity.get().peer_id, 'cs-1')
        from accounts.models import Membership, Role
        from tech_access.testing import make_tech
        from psa_ai.tests_assist import sign_in
        admin = make_tech('orgadmin')
        Membership.objects.create(user=admin, organization=self.org, role=Role.ADMIN, is_active=True)
        c2 = sign_in(admin, self.org)
        c2.post(f'/integrations/rmm/{conn.pk}/pairing/rem0te-identity/', {'op': 'update', 'peer_id': 'evil',
                                                                          'audience': 'x', 'public_base_url': 'https://e.example.com'})
        self.assertEqual(identity.get().peer_id, 'cs-1')

    def test_check_pairing_view_reports_reason(self):
        rt.setup_identity()
        conn = rt.make_connection(self.org)
        fake = rt.FakeRem0te()
        fake.fail = lambda m, r: (401, 'UNAUTHENTICATED', 'Unknown key')
        with fake.running():
            r = self.c.post(f'/integrations/rmm/{conn.pk}/pairing/check/', follow=True)
        text = r.content.decode()
        self.assertIn('Unknown key', text)
        self.assertNotIn('PRIVATE', text)
