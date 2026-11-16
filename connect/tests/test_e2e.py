"""Full pairing → token → API call → webhook path, both directions, with the
in-memory reference peer as the other application."""
import json

from agit8or_connect.reference_peer import API

from .base import CS_BASE, ConnectTestCase


class InboundEndToEnd(ConnectTestCase):
    def test_peer_pairs_gets_token_calls_api_and_sends_event(self):
        from connect.models import Connection, InboundEvent
        pconn, conn = self.pair_inbound()
        self.assertEqual(conn.state, Connection.ACTIVE)
        self.assertEqual(conn.direction, Connection.INBOUND)
        r = self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(json.loads(r.body), {'tenant': 'cust-1', 'name': 'Acme Customer'})
        r = self.peer.call(pconn.id, 'POST', f'{CS_BASE}/connect/v1/test')
        self.assertEqual(json.loads(r.body)['ok'], True)
        r = self.peer.send_event(pconn.id, 'alert.raised', 'cust-1', {'alert_id': 'A-1'})
        self.assertEqual(json.loads(r.body)['status'], 'accepted', r.body)
        self.assertEqual(InboundEvent.objects.get().tenant_grant.organization, self.org_a)
        # And Clientst0r can call the peer with what the peer granted back.
        from connect import client
        r = client.call(conn, 'GET', f'{self.peer.base}{API}/customers/current', tenant_org=self.org_a)
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(json.loads(r.body)['name'], 'Peer Customer One')


class OutboundEndToEnd(ConnectTestCase):
    def test_clientst0r_pairs_calls_peer_and_peer_calls_back(self):
        from connect import client, events, lifecycle
        from connect.models import Connection, OutboundEvent
        conn, pconn = self.pair_outbound()
        self.assertEqual(conn.state, Connection.ACTIVE)
        r = client.call(conn, 'GET', f'{self.peer.base}{API}/customers/current', tenant_org=self.org_a)
        self.assertEqual(json.loads(r.body)['name'], 'Peer Customer One')
        # peer → Clientst0r with the scopes we approved locally
        r = self.peer.call(pconn.id, 'GET', f'{CS_BASE}/connect/v1/customers/current', tenant='cust-1')
        self.assertEqual(json.loads(r.body)['name'], 'Acme Customer')
        # our signed event reaches the peer through the queue
        grant = conn.tenant_grants.get()
        ev = events.enqueue(conn, 'alert.raised', {'alert_id': 'X'}, grant=grant)
        self.assertEqual(events.deliver_due()['delivered'], 1)
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboundEvent.DELIVERED)
        self.assertEqual(pconn.received_events[-1]['tenant'], self.org_id(self.org_a))
        report = lifecycle.test_connection(conn, self.admin)
        self.assertTrue(report['ok'], report)
