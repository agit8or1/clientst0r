"""
Contract ticket-rmm-v1 revision 2 (Rem0te 0.30, pinned in
integrations/rem0te/contract/PIN.json) with revision-1 peers still working:
Rem0te's recorded byte vectors (contract/examples), capability and revision
negotiation, the organization → business binding, containment pauses, the
one status model, backoff and outage recovery, the technician probe,
overlapping key rotation and the Settings → RMM → Rem0te wizard.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from core.models import Organization
from integrations import ticket_rmm
from integrations.models import IntegrationSyncHealth
from integrations.rem0te import health, identity, pairing, protocol, reconcile, schema, setup, testing as rt
from psa.tests._base import TEST_MIDDLEWARE

EX = schema.EXAMPLE_DIR
INDEX = json.loads((EX / 'index.json').read_text())


def example(name):
    return json.loads((EX / name).read_text())


def key(name):
    return (EX / 'keys' / name).read_text()


def with_defaults(value, sch):
    """The body as Rem0te parses it: the schema's `default`s filled in
    (req_sha256 covers the canonical JSON of the parsed body)."""
    if not isinstance(value, dict) or not isinstance(sch, dict):
        return value
    out = dict(value)
    for k, sub in (sch.get('properties') or {}).items():
        if k not in out and 'default' in sub:
            out[k] = json.loads(json.dumps(sub['default']))
        if k in out:
            out[k] = with_defaults(out[k], next((s for s in sub.get('anyOf', []) if s.get('type') == 'object'), sub))
    return out


def body_bytes(body):
    # Rem0te's recorder sent JSON.stringify of the body as shown (key order kept).
    return b'' if body is None else json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode()


class ExampleVectorTests(SimpleTestCase):
    """Rem0te's real exchanges, reproduced with ClientSt0r's own primitives."""

    def test_test_only_keys_match_their_public_halves(self):
        for who in ('clientst0r-request', 'clientst0r-delegation', 'rem0te-self'):
            priv = protocol.load_private_key(key(f'{who}.TEST-ONLY.pem'))
            self.assertTrue(protocol.same_public_key(protocol.public_pem(priv), key(f'{who}.pub.pem')), who)

    def test_request_signatures_reproduce_byte_for_byte(self):
        signed = 0
        for e in INDEX['examples']:
            x = example(e['file'])
            req = x['request']
            h = {k.lower(): v for k, v in req['headers'].items()}
            if 'rem0te-signature' not in h:
                continue
            to_rem0te = e['direction'] == 'clientst0r_to_rem0te'
            priv = protocol.load_private_key(key('clientst0r-request.TEST-ONLY.pem' if to_rem0te
                                                 else 'rem0te-self.TEST-ONLY.pem'))
            audience = INDEX['peer']['audience'] if to_rem0te else INDEX['peer']['peer_audience']
            msg = protocol.request_signing_string(audience, req['method'], req['path'], h['rem0te-timestamp'],
                                                  h['rem0te-nonce'], protocol.sha256_hex(body_bytes(req.get('body'))))
            # Ed25519 is deterministic: the same key and bytes give the same signature.
            self.assertEqual(protocol.sign(priv, msg), h['rem0te-signature'], e['name'])
            self.assertEqual(h['rem0te-key-id'], INDEX['peer']['request_key_id'] if to_rem0te
                             else INDEX['rem0te']['key_id'], e['name'])
            self.assertRegex(h['rem0te-nonce'], protocol.NONCE_RE)
            signed += 1
        self.assertEqual(signed, 10)

    def test_delegations_bind_the_canonical_body(self):
        pub = {INDEX['peer']['delegation_key_id']: protocol.load_public_key(key('clientst0r-delegation.pub.pem'))}
        seen = 0
        for e in INDEX['examples']:
            x = example(e['file'])
            req = x['request']
            token = req['headers'].get('rem0te-delegation')
            if not token:
                continue
            claims = protocol.verify_jws(token, pub)
            self.assertEqual(schema.errors('delegation-claims', claims), [], e['name'])
            self.assertEqual((claims['iss'], claims['aud']), (INDEX['peer']['id'], INDEX['peer']['audience']))
            self.assertLessEqual(claims['exp'] - claims['iat'], protocol.MAX_DELEGATION_TTL_S)
            body = req.get('body')
            if body is not None:
                parsed = with_defaults(body, schema.load(x['request_schema']))
                self.assertEqual(claims['req_sha256'], protocol.sha256_hex(protocol.canonical_json(parsed)), e['name'])
                self.assertEqual(schema.errors(x['request_schema'], parsed), [])
                self.assertEqual(claims['org'], body['organization_id'])
            # ClientSt0r's minting reproduces the token for the same claims.
            priv = protocol.load_private_key(key('clientst0r-delegation.TEST-ONLY.pem'))
            self.assertEqual(protocol.sign_jws(priv, INDEX['peer']['delegation_key_id'], claims).split('.')[2],
                             token.split('.')[2], e['name'])
            seen += 1
        self.assertEqual(seen, 5)

    def test_event_signatures_verify_with_domain_separation(self):
        keys = protocol.keyring([{'kid': 'rem0te-example-1', 'public_key_pem': key('rem0te-self.pub.pem')}])
        job = example('event.job-succeeded.json')['request']['body']
        self.assertEqual(protocol.verify_event_signature(job['event'], job['signature'], keys), '')
        self.assertNotEqual(protocol.verify_event_signature(job['event'], job['signature'], keys, alert=True), '')
        alert = example('alert-event.raised-with-patch-summary.json')['request']['body']
        self.assertEqual(protocol.verify_event_signature(alert['alert_event'], alert['signature'], keys, alert=True), '')
        self.assertNotEqual(protocol.verify_event_signature(alert['alert_event'], alert['signature'], keys), '')
        tampered = json.loads(json.dumps(alert['alert_event']))
        tampered['alert']['patch_summary']['reboot_required'] = False
        self.assertNotEqual(protocol.verify_event_signature(tampered, alert['signature'], keys, alert=True), '')

    def test_inference_response_is_signed_over_the_request_nonce(self):
        x = example('inference.json')
        pub = protocol.load_public_key(key('clientst0r-request.pub.pem'))
        priv = protocol.load_private_key(key('clientst0r-request.TEST-ONLY.pem'))
        resp = body_bytes(x['response']['body'])
        nonce = x['request']['headers']['rem0te-nonce']
        sig = x['response']['headers']['rem0te-response-signature']
        self.assertTrue(protocol.verify(pub, protocol.response_signing_string(nonce, protocol.sha256_hex(resp)), sig))
        self.assertEqual(protocol.sign_response(priv, nonce, resp), sig)

    def test_every_example_validates_against_the_pinned_schemas(self):
        n = 0
        for e in INDEX['examples']:
            x = example(e['file'])
            for side in ('request', 'response'):
                name, body = x.get(f'{side}_schema'), x[side].get('body')
                if name and body is not None:
                    self.assertEqual(schema.errors(name, body), [], f'{e["name"]} {side}')
                    n += 1
        self.assertEqual(n, 17)

    def test_revision_2_alert_is_refused_by_revision_1_schema_and_understood_now(self):
        signed = example('alert-event.raised-with-patch-summary.json')['request']['body']
        self.assertTrue(any('patch_summary' in e for e in schema.errors('signed-alert-event', signed, revision=1)))
        self.assertEqual(schema.errors_from_peer('signed-alert-event', signed, 2), ([], [], 2))
        self.assertEqual(schema.errors('patch-summary', signed['alert_event']['alert']['patch_summary']), [])
        with self.assertRaises(KeyError):
            schema.load('patch-summary', revision=1)

    def test_capabilities_example_and_revision_1_documents(self):
        caps = example('capabilities.json')['response']['body']
        self.assertEqual(caps['contract_revision'], 2)
        self.assertEqual(schema.errors_from_peer('capabilities', caps, 2)[0], [])
        rev1 = json.loads((schema.REV1_DIR / 'fixtures' / 'capabilities.lab.json').read_text())
        errs, unknown, rev = schema.errors_from_peer('capabilities', rev1, 1)
        self.assertEqual((errs, rev), ([], 1))

    def test_unknown_fields_only_from_a_newer_revision(self):
        caps = dict(example('capabilities.json')['response']['body'], contract_revision=3, future={'x': 1})
        self.assertTrue(schema.errors_from_peer('capabilities', caps, 2)[0])
        errs, unknown, rev = schema.errors_from_peer('capabilities', caps, 3)
        self.assertEqual((errs, unknown, rev), ([], ['future'], 2))


class _Rem0teCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Alpha', slug='alpha')
        self.other = Organization.objects.create(name='Beta', slug='beta')
        self.ident = rt.setup_identity()
        self.conn = rt.make_connection(self.org)
        self.fake = rt.FakeRem0te()
        self.own = pairing.organization_id(self.conn)

    def rev2(self, paused=(), business='cmbizalpha000000000000001', **over):
        orgs = [rt.organization(self.own, business, 'Alpha Dental', paused),
                rt.organization('org-somebody-else', 'cmbizbeta0000000000000001', 'Beta Law LLP')]
        return rt.capabilities(version='0.30.1', revision=2, organizations=orgs, **over)

    def check(self):
        with self.fake.running():
            doc = pairing.check(self.conn)
        self.conn.refresh_from_db()
        return doc

    def state(self):
        self.conn.refresh_from_db()
        return health.evaluate(self.conn)['state']


class CapabilityRevisionTests(_Rem0teCase):
    def test_revision_1_peer_still_pairs(self):
        doc = self.check()
        self.assertTrue(doc['ok'] and doc['compatible'], doc)
        self.assertEqual(doc['contract_revision'], 1)
        self.assertNotIn('organization', doc)
        self.assertEqual(self.state(), health.CONNECTED)
        business = next(i for i in setup.checklist(self.conn) if i['key'] == 'business')
        self.assertEqual(business['status'], setup.NA)
        self.assertIn('not supported by the connected rem0te', business['detail'].lower())

    def test_revision_2_binds_own_business_and_stores_no_other_customer(self):
        self.fake.caps = self.rev2()
        doc = self.check()
        self.assertTrue(doc['ok'] and doc['compatible'], doc)
        self.assertEqual(doc['contract_revision'], 2)
        self.assertEqual(doc['organization']['business_id'], 'cmbizalpha000000000000001')
        self.assertEqual(doc['organizations_count'], 2)
        self.assertEqual(doc['business_binding']['status'], 'match')
        stored = json.dumps(self.conn.field_mappings)
        self.assertNotIn('Beta Law', stored)
        self.assertNotIn('cmbizbeta', stored)
        self.assertNotIn('org-somebody-else', stored)
        # First binding pins the business, so the inventory sync refuses a key for any other one.
        self.assertEqual(self.conn.field_mappings[ticket_rmm.TENANT_PIN], 'cmbizalpha000000000000001')
        self.assertEqual(self.state(), health.CONNECTED)

    def test_business_mismatch_stops_the_pairing(self):
        self.conn.field_mappings = dict(self.conn.field_mappings, **{ticket_rmm.REM0TE_BUSINESS_PIN: 'cmbizother'})
        self.conn.save()
        self.fake.caps = self.rev2()
        doc = self.check()
        self.assertFalse(doc['ok'])
        self.assertEqual(doc['code'], pairing.BUSINESS_MISMATCH)
        self.assertIn('cmbizother', doc['error'])
        self.assertFalse(pairing.is_processor(self.conn))
        st = health.evaluate(self.conn)
        self.assertEqual(st['state'], health.CONFIG)
        self.assertEqual(st['reasons'][0]['code'], pairing.BUSINESS_MISMATCH)
        self.assertTrue(st['reasons'][0]['action'])

    def test_unmapped_organization_is_configuration_required(self):
        self.fake.caps = rt.capabilities(version='0.30.1', revision=2,
                                         organizations=[rt.organization('org-somebody-else')])
        doc = self.check()
        self.assertTrue(doc['compatible'])
        self.assertFalse(doc['org_mapped'])
        self.assertNotIn('organization', doc)
        self.assertEqual(self.state(), health.CONFIG)

    def test_pause_is_degraded_not_rejected(self):
        self.fake.caps = self.rev2(paused=['actions', 'integration'])
        doc = self.check()
        self.assertTrue(doc['ok'] and doc['compatible'])
        self.assertEqual(doc['organization']['paused'], ['actions', 'integration'])
        st = health.evaluate(self.conn)
        self.assertEqual(st['state'], health.DEGRADED)
        self.assertTrue(any(r['code'] == 'CONTAINED' for r in st['reasons']))
        self.assertTrue(any('containment pause' in w for w in doc['warnings']))

    def test_revision_rules(self):
        caps = self.rev2()
        caps['surprise'] = True
        self.fake.caps = caps
        self.assertEqual(self.check()['code'], 'CONTRACT_MISMATCH')  # revision 2 adds nothing unknown
        for bad in (0, '2', True, -1):
            self.fake.caps = self.rev2(contract_revision=bad)
            self.assertEqual(self.check()['code'], 'CONTRACT_MISMATCH', bad)
        no_rev = self.rev2()
        no_rev.pop('contract_revision')
        self.fake.caps = no_rev  # organizations without a revision is neither 1 nor 2
        self.assertEqual(self.check()['code'], 'CONTRACT_MISMATCH')

    def test_newer_revision_tolerated_with_logged_warning(self):
        caps = self.rev2(contract_revision=3)
        caps['future_feature'] = {'on': True}
        self.fake.caps = caps
        with self.assertLogs('integrations.rem0te', 'WARNING') as logs:
            doc = self.check()
        self.assertTrue(doc['ok'] and doc['compatible'], doc)
        self.assertEqual((doc['contract_revision'], doc['validated_revision']), (3, 2))
        self.assertEqual(doc['unknown_fields'], ['future_feature'])
        self.assertTrue(any('revision 3' in w for w in doc['warnings']))
        self.assertTrue(any('future_feature' in m for m in logs.output))


class HealthAndBackoffTests(_Rem0teCase):
    def test_states_follow_real_checks(self):
        self.assertEqual(self.state(), health.CONFIG)  # not tested yet
        self.fake.caps = self.rev2()
        self.check()
        self.assertEqual(self.state(), health.CONNECTED)
        self.fake.fail = lambda m, r: (401, 'UNAUTHENTICATED', 'Unknown key')
        self.check()
        self.assertEqual(self.state(), health.AUTH)
        self.fake.fail = lambda m, r: (429, 'RATE_LIMITED', 'slow down')
        self.check()
        self.assertEqual(self.state(), health.DEGRADED)
        self.fake.fail = None
        self.check()
        self.assertEqual(self.state(), health.CONNECTED)

    def test_outage_backs_off_and_recovers(self):
        self.fake.caps = self.rev2()
        self.check()
        self.fake.fail = lambda m, r: ('unreachable',)
        gaps = []
        for n in (1, 2, 3, 4):
            doc = self.check()
            self.assertEqual((doc['code'], doc['failures']), ('UNREACHABLE', n))
            self.assertTrue(doc['compatible'])  # last good capabilities kept during the outage
            at = reconcile.next_check_at(doc)
            checked = timezone.datetime.fromisoformat(doc['checked_at'].replace('Z', '+00:00'))
            gaps.append(round((at - checked).total_seconds()))
        self.assertEqual(gaps, [60, 120, 240, 480])
        self.assertEqual(self.state(), health.DISCONNECTED)
        st = health.evaluate(self.conn)
        self.assertTrue(st['reasons'][0]['action'])
        self.assertFalse(reconcile.check_due(self.conn))
        self.assertTrue(reconcile.check_due(self.conn, now=timezone.now() + timedelta(minutes=9)))
        many = dict(pairing.last_check(self.conn), failures=30)
        self.assertEqual(reconcile.next_check_at(many) - reconcile.next_check_at(dict(many, failures=31)),
                         timedelta(0))  # capped at an hour
        self.fake.fail = None
        with self.fake.running():
            out = reconcile.reconcile(self.conn, force_check=True)
        self.assertTrue(out['checked'])
        self.conn.refresh_from_db()
        doc = pairing.last_check(self.conn)
        self.assertEqual((doc['ok'], doc['failures']), (True, 0))
        self.assertEqual(self.state(), health.CONNECTED)
        r = health.row(self.conn)
        self.assertIsNotNone(r.last_success_at)

    def test_reconcile_waits_when_not_due_and_runs_on_recheck(self):
        self.fake.caps = self.rev2()
        self.check()
        with self.fake.running():
            self.assertFalse(reconcile.reconcile(self.conn)['checked'])
        from integrations.rem0te.alerts import _flag_recheck
        _flag_recheck(self.conn)
        self.conn.refresh_from_db()
        with self.fake.running():
            self.assertTrue(reconcile.reconcile(self.conn)['checked'])
        self.conn.refresh_from_db()
        self.assertFalse(pairing.last_check(self.conn).get('recheck'))

    def test_issues_are_visible_throttled_and_cleared(self):
        self.fake.caps = self.rev2()
        self.check()
        health.note(self.conn, 'inbound_auth', 'A request signed with Rem0te\'s key id did not verify.',
                    code='SIGNATURE')
        self.assertEqual(self.state(), health.AUTH)
        first = health.row(self.conn).issues[0]
        health.note(self.conn, 'inbound_auth', 'A request signed with Rem0te\'s key id did not verify.',
                    code='SIGNATURE')
        self.assertEqual(health.row(self.conn).issues[0].get('at'), first.get('at'))  # not rewritten within a minute
        health.clear(self.conn, 'inbound_auth')
        self.assertEqual(self.state(), health.CONNECTED)
        health.note(self.conn, 'alerts_gap', 'gap of 2 events', code='ALERT_GAP', action='keep polling')
        self.assertEqual(self.state(), health.DEGRADED)
        r = IntegrationSyncHealth.objects.get(object_id=self.conn.pk, kind=health.KIND)
        self.assertEqual((r.status, r.error, r.corrective_action), ('partial', 'gap of 2 events', 'keep polling'))

    def test_health_row_is_separate_from_the_inventory_sync_row(self):
        from integrations.health import get_health_row, record_sync
        record_sync(self.conn, 'rmm', status='success')
        health.note(self.conn, 'jobs', 'jobs waiting', code='UNAVAILABLE')
        self.assertEqual(IntegrationSyncHealth.objects.filter(object_id=self.conn.pk).count(), 2)
        self.assertEqual(get_health_row(self.conn).kind, 'rmm')
        self.assertEqual(get_health_row(self.conn, kind=health.KIND).kind, health.KIND)

    def test_clock_drift_is_degraded(self):
        self.fake.caps = self.rev2()
        self.check()
        mappings = dict(self.conn.field_mappings)
        mappings[ticket_rmm.CAPS] = dict(mappings[ticket_rmm.CAPS], clock_skew_s=75)
        self.conn.field_mappings = mappings
        self.conn.save()
        st = health.evaluate(self.conn)
        self.assertEqual(st['state'], health.DEGRADED)
        self.assertTrue(any(r['code'] == 'CLOCK_DRIFT' for r in st['reasons']))


class TechnicianProbeTests(_Rem0teCase):
    def setUp(self):
        super().setUp()
        from tech_access.testing import make_tech
        self.tech = make_tech('pat')
        self.fake.caps = self.rev2()
        self.check()

    def test_mapped_technician(self):
        with self.fake.running():
            out = setup.technician_probe(self.conn, self.tech)
        self.assertEqual(out['status'], setup.OK)
        method, route, body, headers = self.fake.calls[-1]
        self.assertEqual((method, route, body), ('GET', f'/jobs/{setup.PROBE_JOB}', b''))
        self.assertIn('rem0te-delegation', {k.lower() for k in headers})
        self.conn.refresh_from_db()
        self.assertEqual(pairing.last_check(self.conn)['technicians'][pairing.technician_id(self.tech)]['status'],
                         setup.OK)

    def test_unmapped_technician_is_shown_and_degrades(self):
        self.fake.mapped_techs = set()
        with self.fake.running():
            out = setup.technician_probe(self.conn, self.tech)
        self.assertEqual(out['status'], setup.FAIL)
        self.assertIn('Technician is not mapped', out['message'])
        st = health.evaluate(self.conn)
        self.assertEqual(st['state'], health.DEGRADED)
        self.assertTrue(any(r['code'] == 'TECHNICIAN_NOT_MAPPED' for r in st['reasons']))
        self.fake.mapped_techs = None
        with self.fake.running():
            setup.technician_probe(self.conn, self.tech)
        self.assertEqual(self.state(), health.CONNECTED)

    def test_capability_absent_skips_probe(self):
        caps = self.rev2()
        caps['features'] = dict(caps['features'], ticket_analysis=False)
        self.fake.caps = caps
        with self.fake.running():
            out = setup.test_connection(self.conn, self.tech)
        self.assertIsNone(out['technician'])
        st = health.evaluate(self.conn)
        self.assertTrue(any(r['code'] == 'CAPABILITY' for r in st['reasons']))


class KeyRotationOverlapTests(_Rem0teCase):
    def test_stage_promote_keeps_signing_throughout(self):
        old_req, old_del = self.ident.request_kid, self.ident.delegation_kid
        staged = identity.stage_next_keys()
        entry = identity.peer_entry(self.conn)
        self.assertEqual([k['kid'] for k in entry['requestKeys']], [old_req, staged.next_request_kid])
        self.assertEqual([k['kid'] for k in entry['delegationKeys']], [old_del, staged.next_delegation_kid])
        self.assertNotIn('PRIVATE', json.dumps(identity.public_view(), default=str))
        self.fake.caps = self.rev2()
        self.assertTrue(self.check()['ok'])  # still signing with the current keys
        with self.assertRaises(identity.IdentityError):
            identity.stage_next_keys()
        promoted = identity.promote_next_keys()
        self.assertEqual((promoted.request_kid, promoted.delegation_kid),
                         (staged.next_request_kid, staged.next_delegation_kid))
        self.assertFalse(identity.has_next_keys(promoted))
        self.assertIsNotNone(promoted.rotated_at)
        self.assertTrue(self.check()['ok'])  # the fake Rem0te now knows only the new keys
        with self.assertRaises(identity.IdentityError):
            identity.promote_next_keys()
        self.assertTrue(AuditLog.objects.filter(object_type='rem0te_identity',
                                                description__startswith='Switched').exists())

    def test_discard_and_hard_rotate_clear_staged_keys(self):
        identity.stage_next_keys()
        identity.discard_next_keys()
        self.assertFalse(identity.has_next_keys())
        self.assertEqual(len(identity.peer_entry(self.conn)['requestKeys']), 1)
        identity.stage_next_keys()
        identity.generate_keys(rotate=True)
        self.assertFalse(identity.has_next_keys())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SetupWizardTests(_Rem0teCase):
    def setUp(self):
        super().setUp()
        from psa_ai.tests_assist import sign_in
        from tech_access.testing import make_tech
        self.admin = make_tech('root', superuser=True)
        self.staff = make_tech('lee')
        self.c = sign_in(self.admin, self.org)
        self.url = reverse('integrations:rem0te_setup')

    def test_superuser_only(self):
        from psa_ai.tests_assist import sign_in
        c = sign_in(self.staff, self.org)
        self.assertNotEqual(c.get(self.url).status_code, 200)
        with self.fake.running():
            c.post(reverse('integrations:rem0te_setup_test', args=[self.conn.pk]))
        self.assertEqual(self.fake.calls, [])  # nothing was sent for a non-superuser
        r = self.c.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Configuration Required')
        self.assertContains(r, 'data-rem0te-state="config_required"')

    def test_test_connection_button(self):
        self.fake.caps = self.rev2()
        with self.fake.running():
            r = self.c.post(reverse('integrations:rem0te_setup_test', args=[self.conn.pk]))
        self.assertEqual(r.status_code, 302)
        self.conn.refresh_from_db()
        self.assertEqual(self.state(), health.CONNECTED)
        self.assertTrue(AuditLog.objects.filter(object_type='rmm_connection', object_id=self.conn.pk,
                                                description__contains='Connected').exists())
        page = self.c.get(self.url)
        self.assertContains(page, 'data-rem0te-state="connected"')
        self.assertContains(page, 'cmbizalpha000000000000001')
        self.assertNotContains(page, 'Beta Law')

    def test_identity_rotation_from_the_wizard(self):
        u = reverse('integrations:rem0te_setup_identity')
        self.assertEqual(self.c.post(u, {'op': 'stage'}).status_code, 302)
        self.assertTrue(identity.has_next_keys())
        page = self.c.get(self.url)
        self.assertContains(page, identity.get().next_request_kid)
        self.c.post(u, {'op': 'promote'})
        self.assertFalse(identity.has_next_keys())

    def test_settings_menu_and_integration_list_show_the_status(self):
        self.fake.caps = self.rev2()
        self.check()
        r = self.c.get(reverse('integrations:integration_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Rem0te: Connected')
        page = self.c.get(self.url)
        self.assertContains(page, 'RMM · Rem0te')
        self.assertContains(page, 'aria-current="page"')
