"""Quick Connect increment B1 (roadmap 79.10, 79.11, staging part of 79.14):
default-deny source policy for the Agit8or Connect endpoints
(docs/plans/quick-connect/INCREMENTS.md §B1, DESIGN.md §5, §11, §13.2)."""
import json
import time
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone

from .base import CONNECT_SETTINGS, CS_BASE, PEER_IP, ConnectTestCase, TEST_MIDDLEWARE

UI = '/settings/integrations/connected-apps/'
PEER_V6 = '2606:4700:4700::1111'
PEER_MAPPED = '::ffff:93.184.216.34'
OTHER_IP = '93.184.216.99'
OFFICE = '81.2.69.0/24'
OFFICE_IP = '81.2.69.10'


class _Req:
    def __init__(self, user):
        from tech_access import protected
        self.user, self.session = user, {protected.SESSION_KEY: int(time.time())}
        self.META, self.path = {}, '/'


def _hit(client, method, path, ip, body=b'', content_type='application/json', **headers):
    return client.generic(method, path, data=body, content_type=content_type, secure=True,
                          HTTP_HOST='clientst0r.test', REMOTE_ADDR=ip, **headers)


def _code(resp):
    try:
        data = json.loads(resp.content or b'{}')
    except ValueError:
        return ''
    err = data.get('error')
    return err.get('code') if isinstance(err, dict) else err


ROUTES = lambda cid: [   # noqa: E731
    ('GET', '/.well-known/agit8or-connect'), ('GET', '/connect/v1/health'),
    ('POST', '/connect/v1/pairing/requests'), ('POST', f'/connect/v1/pairing/requests/{cid}/status'),
    ('POST', '/connect/v1/token'), ('GET', f'/connect/v1/connections/{cid}/jwks'),
    ('POST', '/connect/v1/events'), ('GET', '/connect/v1/capabilities'), ('POST', '/connect/v1/test')]


def _wipe_rules():
    from connect import source_policy
    from connect.models import SourceRule
    ids = list(SourceRule.objects.exclude(status=SourceRule.REMOVED).values_list('pk', flat=True))
    if ids:
        source_policy.apply_direct(remove=ids, via='test')


class FreshEnableDeniesEverything(ConnectTestCase):
    def test_no_rules_every_route_refused_all_address_families(self):
        _wipe_rules()
        cid = '00000000-0000-0000-0000-000000000001'
        for ip in (PEER_IP, PEER_V6, PEER_MAPPED, '10.0.0.5', '127.0.0.1'):
            for method, path in ROUTES(cid):
                r = _hit(self.api, method, path, ip)
                self.assertEqual(r.status_code, 403, (ip, path))
                self.assertEqual(_code(r), 'source_not_authorised', (ip, path))

    def test_valid_dpop_token_does_not_help(self):
        pconn, conn = self.pair_inbound()
        token = self.peer.get_token(pconn.id)['access_token']
        self.assertEqual(self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities', token=token).status,
                         200)
        _wipe_rules()
        for url in ('/connect/v1/capabilities', '/connect/v1/test', '/connect/v1/health'):
            r = self.peer.call(pconn.id, 'POST' if url.endswith('test') else 'GET', CS_BASE + url, token=token)
            self.assertEqual(r.status, 403, url)
            self.assertEqual(json.loads(r.body)['error']['code'], 'source_not_authorised')
        r = self.peer.send_event(pconn.id, 'alert.raised', 'cust-1', {'x': 1})
        self.assertEqual(r.status, 403)

    def test_disabled_stays_404(self):
        with override_settings(AGIT8OR_CONNECT_ENABLED=False):
            self.assertEqual(_hit(self.api, 'GET', '/.well-known/agit8or-connect', PEER_IP).status_code, 404)

    def test_refusals_are_folded_with_the_connect_surface(self):
        from api_access.models import ApiAccessDecision
        _wipe_rules()
        for _ in range(30):
            _hit(self.api, 'GET', '/.well-known/agit8or-connect', OTHER_IP)
        rows = ApiAccessDecision.objects.filter(surface='connect', source_ip=OTHER_IP)
        self.assertEqual(rows.count(), 1)
        self.assertTrue(rows.get().reason.startswith('connect_source_'))


class AllowedSourceStillNeedsAuth(ConnectTestCase):
    def test_allowed_source_without_credentials(self):
        pconn, conn = self.pair_inbound()
        self.assertEqual(_hit(self.api, 'GET', '/.well-known/agit8or-connect', PEER_IP).status_code, 200)
        r = _hit(self.api, 'GET', '/connect/v1/capabilities', PEER_IP, HTTP_AUTHORIZATION='DPoP x.y.z')
        self.assertEqual(r.status_code, 403)   # names no connection -> refused before auth
        r = _hit(self.api, 'POST', '/connect/v1/token', PEER_IP, body=f'client_id={conn.pk}&grant_type=x',
                 content_type='application/x-www-form-urlencoded')
        self.assertEqual(r.status_code, 400)   # source ok, credentials still required
        self.assertEqual(_code(r), 'unsupported_grant_type')

    def test_unauthorised_source_denied(self):
        pconn, conn = self.pair_inbound()
        r = _hit(self.api, 'POST', '/connect/v1/token', OTHER_IP, body=f'client_id={conn.pk}',
                 content_type='application/x-www-form-urlencoded')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(_code(r), 'source_not_authorised')


class IndependentOfRestApiPolicy(ConnectTestCase):
    def _api_mode(self, mode, rules=()):
        from api_access import policy as P
        from api_access.models import ApiAccessRule, ApiAccessSettings
        s = ApiAccessSettings.get()
        s.api_mode = mode
        s.save()
        for net in rules:
            ApiAccessRule.objects.create(name='office', network=net, scope='global', surface='api')
        ApiAccessSettings.bump()
        P.reset_cache()

    def test_unrestricted_api_cannot_open_connect(self):
        self._api_mode('unrestricted')
        _wipe_rules()
        self.assertEqual(_hit(self.api, 'GET', '/.well-known/agit8or-connect', PEER_IP).status_code, 403)

    def test_api_allowlist_office_connect_peer(self):
        pconn, conn = self.pair_inbound()
        self._api_mode('allowlist', [OFFICE])
        from api_access.models import ApiAccessRule
        # Even an API rule aimed at the Connect group or integration is inert for Connect.
        ApiAccessRule.objects.create(name='x', network=OFFICE, scope='endpoint_group', target='connect_api')
        ApiAccessRule.objects.create(name='y', network=OFFICE, scope='integration', target='agit8or_connect')
        self.assertEqual(self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities').status, 200)
        self.assertEqual(_hit(self.api, 'GET', '/.well-known/agit8or-connect', OFFICE_IP).status_code, 403)
        # ...and the peer cannot reach the REST API, whose allowlist is the office only.
        self.assertEqual(_hit(self.api, 'GET', '/api/', PEER_IP).status_code, 403)

    def test_connect_rules_not_targetable_from_api_form(self):
        from api_access.forms import RuleForm, TestAddressForm
        f = RuleForm(data={'name': 'x', 'network': OFFICE, 'action': 'allow', 'surface': 'api',
                           'scope': 'endpoint_group', 'target': 'connect_api', 'is_active': True})
        self.assertFalse(f.is_valid())
        self.assertNotIn('connect_api', dict(TestAddressForm().fields['group'].choices))


class TwoLayers(ConnectTestCase):
    def setUp(self):
        super().setUp()
        self.pconn, self.conn = self.pair_inbound()

    def call(self):
        return self.peer.call(self.pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities').status

    def test_both_layers_must_allow(self):
        from connect import source_policy
        from connect.models import SourceRule
        self.assertEqual(self.call(), 200)
        conn_rule = SourceRule.objects.get(connection=self.conn, status='active')
        source_policy.apply_direct(remove=[conn_rule.pk])
        with self.assertRaises(Exception):   # token refused at the token endpoint
            self.call()
        source_policy.apply_direct([{'layer': 'connection', 'connection': self.conn.pk, 'network': PEER_IP}])
        self.assertEqual(self.call(), 200)
        source_policy.apply_direct(remove=[self.install_rule.pk])
        r = _hit(self.api, 'GET', f'/connect/v1/connections/{self.conn.pk}/jwks', PEER_IP)
        self.assertEqual(r.status_code, 403)

    def test_deny_in_either_layer_wins(self):
        from connect import source_policy
        r = source_policy.apply_direct([{'layer': 'installation', 'network': PEER_IP + '/32', 'action': 'deny'}])
        jwks = f'/connect/v1/connections/{self.conn.pk}/jwks'
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 403)
        source_policy.apply_direct(remove=[r[0].pk])
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 200)
        source_policy.apply_direct([{'layer': 'connection', 'connection': self.conn.pk, 'network': '93.184.0.0/16',
                                     'action': 'deny'}])
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 403)

    def test_x_forwarded_for(self):
        jwks = f'/connect/v1/connections/{self.conn.pk}/jwks'
        # Untrusted peer: its forged header is ignored, its own address is used.
        self.assertEqual(_hit(self.api, 'GET', jwks, OTHER_IP, HTTP_X_FORWARDED_FOR=PEER_IP).status_code, 403)
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP, HTTP_X_FORWARDED_FOR=OTHER_IP).status_code, 200)
        # Trusted proxy (loopback by default): the first untrusted hop counts.
        self.assertEqual(_hit(self.api, 'GET', jwks, '127.0.0.1',
                              HTTP_X_FORWARDED_FOR=f'{OTHER_IP}, {PEER_IP}').status_code, 200)
        self.assertEqual(_hit(self.api, 'GET', jwks, '127.0.0.1',
                              HTTP_X_FORWARDED_FOR=f'{PEER_IP}, {OTHER_IP}').status_code, 403)
        self.assertEqual(_hit(self.api, 'GET', jwks, '127.0.0.1').status_code, 403)   # the proxy itself

    def test_ipv6_and_mapped(self):
        from connect import source_policy
        jwks = f'/connect/v1/connections/{self.conn.pk}/jwks'
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_MAPPED).status_code, 200)   # same address
        self.assertEqual(_hit(self.api, 'GET', jwks, '::ffff:93.184.216.99').status_code, 403)
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_V6).status_code, 403)
        source_policy.apply_direct([{'layer': 'installation', 'network': '2606:4700::/32'},
                                    {'layer': 'connection', 'connection': self.conn.pk, 'network': PEER_V6}])
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_V6).status_code, 200)
        self.assertEqual(_hit(self.api, 'GET', jwks, '2606:4700:4700::1112').status_code, 403)
        # A mapped spelling of a /16 is folded to IPv4 and validated as such.
        with self.assertRaises(ValidationError):
            source_policy.validate_entry('::ffff:0.0.0.0/96')

    def test_private_client_refused_despite_firewall_lan_exemption(self):
        from core.models import FirewallSettings
        s = FirewallSettings.get_settings()
        s.ip_firewall_enabled = True
        s.save()
        for ip in ('10.0.0.5', '192.168.1.20', '127.0.0.2', '169.254.3.4', 'fe80::1'):
            r = _hit(self.api, 'GET', '/.well-known/agit8or-connect', ip)
            self.assertEqual(r.status_code, 403, ip)
            self.assertEqual(_code(r), 'source_not_authorised', ip)


class PerConnectionBinding(ConnectTestCase):
    def setUp(self):
        super().setUp()
        from agit8or_connect.reference_peer import ReferencePeer
        self.p2 = ReferencePeer('https://rmm2.test', self.net, app_type='rem0te', display_name='Second',
                                tenants={'cust-9': 'Nine'})
        self.pc1, self.c1 = self.pair_inbound()
        self.peer_ip = OTHER_IP
        from connect import source_policy
        source_policy.apply_direct([{'layer': 'installation', 'network': OTHER_IP}])
        self.pc2, self.c2 = self.pair_inbound(self.p2, tenant='cust-9', org=self.org_b)
        self.peer_ip = PEER_IP

    def test_p1_naming_c2_refused_before_auth(self):
        r = _hit(self.api, 'POST', '/connect/v1/token', PEER_IP, body=f'client_id={self.c2.pk}',
                 content_type='application/x-www-form-urlencoded')
        self.assertEqual(r.status_code, 403)
        r = _hit(self.api, 'GET', f'/connect/v1/connections/{self.c2.pk}/jwks', PEER_IP)
        self.assertEqual(r.status_code, 403)

    def test_stolen_c2_token_from_p1_is_a_binding_mismatch(self):
        from connect.models import ConnectAuditEvent
        self.peer_ip = OTHER_IP
        token = self.p2.get_token(self.pc2.id)['access_token']
        self.peer_ip = PEER_IP   # P1's address, allowed for C1 only
        # health is answered for any connection's allowed source; the token
        # proves C2, which this address is not allowed for -> step 11.
        r = self.p2.call(self.pc2.id, 'GET', f'{CS_BASE}/connect/v1/health', token=token)
        self.assertEqual(r.status, 403)
        self.assertEqual(json.loads(r.body)['error']['code'], 'source_not_authorised')
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='source.binding_mismatch',
                                                         connection_id=str(self.c2.pk)).exists())
        # A pre-authentication naming that disagrees with the proven connection
        # (parser differential) is caught the same way.
        with mock.patch('connect.source_policy.named_connection', return_value=str(self.c1.pk)):
            r = self.p2.call(self.pc2.id, 'GET', f'{CS_BASE}/connect/v1/capabilities', token=token)
        self.assertEqual(r.status, 403)

    def test_shared_address_separate_keys(self):
        """Two installations behind one NAT address: allowed for both, told
        apart by their keys."""
        from connect import source_policy
        source_policy.apply_direct([{'layer': 'connection', 'connection': self.c2.pk, 'network': PEER_IP}])
        self.assertEqual(self.p2.call(self.pc2.id, 'GET', f'{CS_BASE}/connect/v1/capabilities').status, 200)
        self.assertEqual(self.peer.call(self.pc1.id, 'GET', f'{CS_BASE}/connect/v1/capabilities').status, 200)


class Validation(TestCase):
    def test_refused_at_save(self):
        from connect import source_policy
        for bad in ('0.0.0.0/0', '::/0', '93.0.0.0/15', '2606::/31', '::ffff:0.0.0.0/96', 'nonsense'):
            with self.assertRaises(ValidationError, msg=bad):
                source_policy.validate_entry(bad)
        self.assertEqual(source_policy.validate_entry('93.184.0.0/16')[0], '93.184.0.0/16')
        self.assertEqual(source_policy.validate_entry('2606:4700::/32')[0], '2606:4700::/32')
        for private in ('10.0.0.5', '127.0.0.1', '169.254.1.1', 'fe80::1', 'fd00::5', '::ffff:10.0.0.5'):
            with self.assertRaises(ValidationError, msg=private):
                source_policy.validate_entry(private)
            net, flagged = source_policy.validate_entry(private, private=True)
            self.assertTrue(flagged)
        with self.assertRaises(ValidationError):   # private ranges: single addresses only
            source_policy.validate_entry('10.0.0.0/24', private=True)
        with self.assertRaises(ValidationError):
            source_policy.parse_pairing_sources(['93.184.216.0/24'])
        with self.assertRaises(ValidationError):
            source_policy.parse_pairing_sources([])


@override_settings(**CONNECT_SETTINGS)
class StagingAndRollback(ConnectTestCase):
    def test_widening_needs_second_admin_and_is_atomic(self):
        from connect import source_policy
        from connect.models import ConnectChange, SourceRule
        from tech_access import protected
        ch = source_policy.propose(add=[{'layer': 'installation', 'network': '81.2.69.0/24'}], user=self.admin)
        self.assertTrue(ch.widening)
        self.assertIn('installation 81.2.69.0/24', ch.preview['gains'])
        self.assertFalse(SourceRule.objects.filter(network='81.2.69.0/24').exists())   # staged: nothing yet
        pc = source_policy.approve(ch, _Req(self.admin))
        ch.refresh_from_db()
        self.assertEqual(ch.status, ConnectChange.AWAITING_SECOND)
        protected.confirm(pc, _Req(self.admin))
        with self.assertRaises(protected.ProtectedChangeError):
            protected.approve(pc, _Req(self.admin))                  # not by the proposer
        v0 = source_policy.current().version
        protected.approve(pc, _Req(self.admin2))
        ch.refresh_from_db()
        self.assertEqual(ch.status, ConnectChange.APPLIED)
        self.assertTrue(SourceRule.objects.filter(network='81.2.69.0/24', status='active').exists())
        self.assertGreater(source_policy.current().version, v0)

    def test_narrowing_one_admin_with_reauth_and_stale_fingerprint(self):
        from connect import source_policy
        ch = source_policy.propose(remove=[self.install_rule.pk], user=self.admin)
        self.assertFalse(ch.widening)
        req = _Req(self.admin)
        req.session = {}
        with self.assertRaises(source_policy.ChangeRefused):     # no fresh re-auth
            source_policy.approve(ch, req)
        other = source_policy.propose(add=[{'layer': 'installation', 'network': '81.2.69.0/24', 'action': 'deny'}],
                                      user=self.admin)
        source_policy.approve(other, _Req(self.admin))           # touches the same layer
        with self.assertRaises(source_policy.ChangeRefused):     # changed since proposed
            source_policy.approve(ch, _Req(self.admin))

    def test_lockout_preview(self):
        from connect import source_policy
        pconn, conn = self.pair_inbound()
        self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities')
        conn.refresh_from_db()
        self.assertEqual(conn.last_source_ip, PEER_IP)
        ch = source_policy.propose(remove=[self.install_rule.pk], user=self.admin)
        self.assertEqual([x['connection'] for x in ch.preview['lockout']], [str(conn.pk)])

    def test_rollback_never_widens(self):
        from connect import source_policy
        from connect.models import SourceRule
        deny = source_policy.apply_direct([{'layer': 'installation', 'network': '81.2.69.0/24', 'action': 'deny'}])[0]
        before_allow = set(SourceRule.objects.filter(status='active', action='allow').values_list('network', flat=True))
        ch = source_policy.propose(add=[{'layer': 'installation', 'network': '93.185.0.0/16'}], remove=[deny.pk],
                                   user=self.admin)
        source_policy.apply_change(ch, self.admin)   # (as the applier would after a second approval)
        ch.refresh_from_db()
        after_allow = set(SourceRule.objects.filter(status='active', action='allow').values_list('network', flat=True))
        source_policy.rollback(ch, _Req(self.admin))
        now_allow = set(SourceRule.objects.filter(status='active', action='allow').values_list('network', flat=True))
        now_deny = set(SourceRule.objects.filter(status='active', action='deny').values_list('network', flat=True))
        self.assertTrue(now_allow <= (before_allow & after_allow))
        self.assertIn('81.2.69.0/24', now_deny)
        # Rolling back a narrowing does not restore the removed allow rule.
        ch2 = source_policy.propose(remove=[self.install_rule.pk], user=self.admin)
        source_policy.approve(ch2, _Req(self.admin))
        ch2.refresh_from_db()
        source_policy.rollback(ch2, _Req(self.admin))
        self.assertFalse(SourceRule.objects.filter(network=PEER_IP + '/32', status='active').exists())

    def test_api_access_rollback_window_leaves_connect_rules(self):
        from api_access import rollback
        from api_access.models import ApiAccessRule
        from connect.models import SourceRule
        before = sorted(SourceRule.objects.values_list('pk', 'status', 'network'))
        rollback.arm(self.admin, 5)
        ApiAccessRule.objects.create(name='tmp', network=OFFICE)
        from connect import source_policy
        source_policy.apply_direct([{'layer': 'installation', 'network': '81.2.69.0/24'}])
        mid = sorted(SourceRule.objects.values_list('pk', 'status', 'network'))
        rollback.revert_if_due(force=True)
        self.assertEqual(sorted(SourceRule.objects.values_list('pk', 'status', 'network')), mid)
        self.assertNotEqual(before, mid)

    def test_ui_network_page_and_change_flow(self):
        r = self.ui.post(UI + 'network/', {'op': 'propose_rule', 'network': '0.0.0.0/0', 'action': 'allow'},
                         secure=True, HTTP_HOST='clientst0r.test', follow=True)
        self.assertContains(r, 'would allow every address')
        r = self.ui.post(UI + 'network/', {'op': 'propose_rule', 'network': '81.2.69.0/24', 'action': 'deny'},
                         secure=True, HTTP_HOST='clientst0r.test', follow=True)
        from connect.models import ConnectChange
        ch = ConnectChange.objects.get()
        self.assertContains(r, f'data-connect-change="{ch.pk}"')
        r = self.ui.post(UI + f'changes/{ch.pk}/', {'op': 'approve', 'password': 'pw-Admin-1!x'}, secure=True,
                         HTTP_HOST='clientst0r.test')
        self.assertEqual(r.status_code, 302)
        ch.refresh_from_db()
        self.assertEqual(ch.status, 'applied')
        r = self.ui.get(UI + 'network/?test_ip=81.2.69.5', secure=True, HTTP_HOST='clientst0r.test')
        self.assertContains(r, 'data-connect-test-result="refused"')


class CrossWorkerAndFailure(ConnectTestCase):
    def test_change_in_another_worker_is_seen(self):
        from connect import source_policy
        from connect.models import InstallationIdentity, SourceRule
        pconn, conn = self.pair_inbound()
        jwks = f'/connect/v1/connections/{conn.pk}/jwks'
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 200)
        # "Another worker" removes the rule: rows changed + version bumped, this
        # process's cache untouched.
        SourceRule.objects.filter(connection=conn).update(status='removed')
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 200)   # same version: cached
        InstallationIdentity.objects.update(connect_policy_version=F_plus())
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 403)
        source_policy.reset_cache()
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 403)

    def test_database_unavailable_fails_closed_after_60s(self):
        from connect import source_policy
        pconn, conn = self.pair_inbound()
        jwks = f'/connect/v1/connections/{conn.pk}/jwks'
        self.assertEqual(_hit(self.api, 'GET', jwks, PEER_IP).status_code, 200)
        compiled = source_policy._state['compiled']
        boom = mock.patch('connect.models.InstallationIdentity.objects.order_by', side_effect=DatabaseError('down'))
        with boom:
            self.assertEqual(source_policy.current(), compiled)          # fresh cache: used
            compiled.checked_at -= 61
            with self.assertRaises(source_policy.PolicyUnavailable):
                source_policy.current()
            r = source_policy.check(_fake_request(f'/connect/v1/connections/{conn.pk}/jwks'))
            self.assertFalse(r.allowed)
            self.assertEqual(r.reason, source_policy.R_UNAVAILABLE)
        source_policy.reset_cache()
        with boom:
            with self.assertRaises(source_policy.PolicyUnavailable):     # nothing cached
                source_policy.current()


def F_plus():
    from django.db.models import F
    return F('connect_policy_version') + 1


def _fake_request(path, ip=PEER_IP):
    from django.test import RequestFactory
    return RequestFactory().get(path, REMOTE_ADDR=ip, secure=True)


class ObserveMode(ConnectTestCase):
    def setUp(self):
        super().setUp()
        self.pconn, self.conn = self.pair_inbound()
        from connect import identity, source_policy
        from connect.models import InstallationIdentity, SourceRule
        # As the migration does for a connection that existed before B1: it
        # has no source rule of its own, and the observe period lists it.
        SourceRule.objects.filter(connection=self.conn).update(status='removed')
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(
            source_observe_until=timezone.now() + timedelta(days=14),
            source_observe_connections=[str(self.conn.pk)])
        source_policy.reset_cache()
        self.peer_ip = OTHER_IP     # an address no rule lists

    def test_existing_connection_keeps_working_and_sources_are_listed(self):
        from connect.models import SourceRule
        self.assertEqual(self.peer.call(self.pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities').status, 200)
        obs = SourceRule.objects.get(connection=self.conn, status='observed')
        self.assertEqual(obs.network, OTHER_IP + '/32')
        self.assertGreaterEqual(obs.match_count, 1)
        page = self.ui.get(UI + f'{self.conn.pk}/', secure=True, HTTP_HOST='clientst0r.test').content.decode()
        self.assertIn('Approve observed address', page)
        self.assertIn('data-connect-observe', self.ui.get(UI + 'network/', secure=True,
                                                          HTTP_HOST='clientst0r.test').content.decode())
        # Observe never covers new pairings or unlisted connections.
        r = _hit(self.api, 'POST', '/connect/v1/pairing/requests', OTHER_IP)
        self.assertEqual(r.status_code, 403)

    def test_enforcement_after_the_date(self):
        from connect import identity, source_policy
        from connect.models import InstallationIdentity
        InstallationIdentity.objects.filter(pk=identity.get().pk).update(
            source_observe_until=timezone.now() - timedelta(seconds=1))
        source_policy.reset_cache()
        r = _hit(self.api, 'GET', f'/connect/v1/connections/{self.conn.pk}/jwks', OTHER_IP)
        self.assertEqual(r.status_code, 403)

    def test_enforce_now_and_approve_observed(self):
        from connect import source_policy
        from connect.models import ConnectAuditEvent, ConnectChange, SourceRule
        self.peer.call(self.pconn.id, 'GET', f'{CS_BASE}/connect/v1/capabilities')
        obs = SourceRule.objects.get(connection=self.conn, status='observed')
        self.ui.post(UI + f'{self.conn.pk}/', {'op': 'approve_observed', 'rule': obs.pk}, secure=True,
                     HTTP_HOST='clientst0r.test')
        ch = ConnectChange.objects.get(connection=self.conn, status=ConnectChange.STAGED)
        self.assertTrue(ch.widening)   # never auto-added: a reviewed change
        self.assertEqual({e['layer'] for e in ch.payload['add']}, {'connection', 'installation'})
        self.assertTrue(source_policy.enforce_now(self.admin))
        self.assertTrue(ConnectAuditEvent.objects.filter(operation='source_policy.enforced').exists())
        r = _hit(self.api, 'GET', f'/connect/v1/connections/{self.conn.pk}/jwks', OTHER_IP)
        self.assertEqual(r.status_code, 403)

    def test_migration_starts_observe_only_with_existing_connections(self):
        import importlib
        from django.apps import apps
        from connect.models import InstallationIdentity
        mig = importlib.import_module('connect.migrations.0002_source_policy')
        InstallationIdentity.objects.update(source_observe_until=None, source_observe_connections=[])
        mig.start_observe_period(apps, None)
        ident = InstallationIdentity.objects.get()
        self.assertIsNotNone(ident.source_observe_until)
        self.assertEqual(ident.source_observe_connections, [str(self.conn.pk)])
        from connect import audit_log
        self.assertIsNone(audit_log.verify())   # the migration's chain record is valid
        from connect.models import Connection
        Connection.objects.update(state='revoked')
        InstallationIdentity.objects.update(source_observe_until=None, source_observe_connections=[])
        mig.start_observe_period(apps, None)
        self.assertIsNone(InstallationIdentity.objects.get().source_observe_until)


class PairingSources(ConnectTestCase):
    def test_invitation_requires_address_and_only_that_address_can_use_it(self):
        from connect import pairing
        with self.assertRaises(pairing.PairingFailed):
            pairing.create_invitation(self.admin)
        _, code = pairing.create_invitation(self.admin, peer_sources=[PEER_IP])
        self.peer_ip = OTHER_IP
        with self.assertRaises(Exception):
            self.peer.start_pairing(CS_BASE, code, requested_scopes=self.SCOPES, proposed_tenants=[])
        self.peer_ip = PEER_IP
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=self.SCOPES, proposed_tenants=[])
        self.assertTrue(pconn.request_id)

    def test_wrong_code_flood_from_strangers_cannot_burn(self):
        from connect import pairing
        from connect.models import PairingInvitation
        inv, code = pairing.create_invitation(self.admin, peer_sources=[PEER_IP])
        for _ in range(10):
            self.assertEqual(_hit(self.api, 'POST', '/connect/v1/pairing/requests', OTHER_IP,
                                  body=b'{"request": "x.y.z"}').status_code, 403)
        inv.refresh_from_db()
        self.assertEqual(inv.attempts, 0)
        self.assertTrue(inv.is_open)

    def test_rules_follow_the_connection_lifecycle(self):
        from connect import lifecycle
        from connect.models import SourceRule
        pconn, conn = self.pair_inbound()
        self.assertEqual(list(SourceRule.objects.filter(connection=conn, status='active')
                              .values_list('network', 'purpose')), [(PEER_IP + '/32', 'all')])
        self.assertFalse(SourceRule.objects.filter(connection=conn, status='temporary').exists())
        lifecycle.revoke(conn, self.admin)
        self.assertFalse(SourceRule.objects.filter(connection=conn, status__in=('active', 'temporary')).exists())

    def test_outbound_pairing_rule_scoped_to_pairing_until_approved(self):
        from connect.models import SourceRule
        conn, pconn = self.pair_outbound()
        self.assertTrue(SourceRule.objects.filter(connection=conn, status='active', purpose='all').exists())

    def test_rate_limit_keyed_by_address_and_connection(self):
        from connect import ratelimit
        pconn, conn = self.pair_inbound()
        jwks = f'/connect/v1/connections/{conn.pk}/jwks'
        with mock.patch.dict(ratelimit.LIMITS, {'jwks_ip': (2, 60)}):
            codes = [_hit(self.api, 'GET', jwks, PEER_IP).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


class RecoveryCommand(ConnectTestCase):
    def test_list_add_remove_enforce(self):
        from io import StringIO
        from connect.models import SourceRule
        out = StringIO()
        call_command('connect_source_rules', 'add', '--network', '81.2.69.0/24', stdout=out)
        rule = SourceRule.objects.get(network='81.2.69.0/24')
        call_command('connect_source_rules', 'list', stdout=out)
        self.assertIn('81.2.69.0/24', out.getvalue())
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('connect_source_rules', 'add', '--network', '0.0.0.0/0', stdout=out)
        call_command('connect_source_rules', 'remove', '--id', str(rule.pk), stdout=out)
        rule.refresh_from_db()
        self.assertEqual(rule.status, 'removed')
        call_command('connect_source_rules', 'enforce', stdout=out)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AGIT8OR_CONNECT_ENABLED=True,
                   AGIT8OR_CONNECT_PUBLIC_URL=CS_BASE)
class UnrelatedEndpointsUnaffected(TestCase):
    """No Connect rule exists: everything that is not Connect behaves as before."""

    def test_other_surfaces(self):
        from api_access.groups import classify
        for path in ('/api/', '/api/mobile/v1/tickets/', '/api/integration/v1/events', '/payments/webhooks/stripe/1/',
                     '/security/webhook/abc/', '/accounts/login/', '/'):
            r = self.client.get(path, REMOTE_ADDR=OTHER_IP, secure=True)
            self.assertNotEqual(_code(r), 'source_not_authorised', path)
            route = classify(path)
            self.assertTrue(route is None or route.surface != 'connect', path)
        from api_access.models import ApiAccessDecision
        self.assertFalse(ApiAccessDecision.objects.filter(surface='connect').exists())
