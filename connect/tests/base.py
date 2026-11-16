"""Shared fixtures: this Django Clientst0r plus in-memory reference peers
(agit8or_connect.reference_peer) wired together through a Network.

Clientst0r's outbound transport is replaced by the Network; requests to
https://clientst0r.test are served by the Django test client. Nothing
leaves the process.
"""
from __future__ import annotations

from unittest import mock
from urllib.parse import urlsplit

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from agit8or_connect.http import Response
from agit8or_connect.reference_peer import Network, ReferencePeer

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
CS_BASE = 'https://clientst0r.test'
PEER_BASE = 'https://rmm.test'

CONNECT_SETTINGS = dict(
    MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AGIT8OR_CONNECT_ENABLED=True,
    AGIT8OR_CONNECT_PUBLIC_URL=CS_BASE, ALLOWED_HOSTS=['clientst0r.test', 'testserver', 'localhost'],
)


def django_handler(client: Client):
    def handle(method, url, headers, body):
        p = urlsplit(url)
        path = p.path + (f'?{p.query}' if p.query else '')
        extra, ct = {}, 'application/octet-stream'
        for k, v in (headers or {}).items():
            if k.lower() == 'content-type':
                ct = v
                continue
            extra['HTTP_' + k.upper().replace('-', '_')] = v
        r = client.generic(method, path, data=body or b'', content_type=ct, secure=True,
                           HTTP_HOST='clientst0r.test', **extra)
        return Response(r.status_code, {k: v for k, v in r.items()}, r.content)
    return handle


@override_settings(**CONNECT_SETTINGS)
class ConnectTestCase(TestCase):
    SCOPES = ['connection:read', 'customers:read', 'events:publish']
    PEER_SCOPES = ['connection:read', 'customers:read', 'events:publish']   # what Clientst0r may do at the peer

    def setUp(self):
        from core.models import Organization
        from django.core.cache import cache
        from connect import client as cclient
        cache.clear()          # rate-limit windows live in the cache
        self.addCleanup(cache.clear)
        cclient.clear_cache()
        self.net = Network()
        self.api = Client()
        self.net.register(CS_BASE, django_handler(self.api))
        self.peer = ReferencePeer(PEER_BASE, self.net, app_type='rem0te', display_name='Rem0te lab',
                                  tenants={'cust-1': 'Peer Customer One', 'cust-2': 'Peer Customer Two'})
        p = mock.patch('connect.transport.factory', lambda **kw: self.net)
        p.start()
        self.addCleanup(p.stop)
        self.admin = User.objects.create_superuser('admin1', 'a1@example.test', 'pw-Admin-1!x')
        self.admin2 = User.objects.create_superuser('admin2', 'a2@example.test', 'pw-Admin-2!x')
        self.org_a = Organization.objects.create(name='Acme Customer', slug='acme-c')
        self.org_b = Organization.objects.create(name='Beta Customer', slug='beta-c')
        self.ui = Client()
        self.ui.force_login(self.admin)

    def org_id(self, org):
        return f'org-{org.pk}'

    # --- pairing helpers ------------------------------------------------------------
    def pair_inbound(self, peer=None, *, tenant='cust-1', org=None, scopes=None, grant_scopes=None):
        """The peer connects TO Clientst0r (Clientst0r is the responder)."""
        from connect import pairing
        from connect.models import PairingRequest
        peer = peer or self.peer
        org = org or self.org_a
        scopes = scopes or self.SCOPES
        _, code = pairing.create_invitation(self.admin)
        pconn = peer.start_pairing(CS_BASE, code, requested_scopes=scopes,
                                   proposed_tenants=[{'id': tenant, 'label': 'Peer customer'}])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        self.assertEqual(preq.connection.sas, pconn.sas)
        pairing.approve_inbound(preq, scopes=scopes, grants=[(org.pk, tenant, grant_scopes or
                                                               ['customers:read', 'events:publish'])],
                                requested_scopes=self.PEER_SCOPES, user=self.admin)
        self.assertEqual(peer.poll(pconn.id), 'approved')
        peer.accept(pconn.id, scopes=self.PEER_SCOPES,
                    tenant_grants=[{'remote_tenant': self.org_id(org), 'local_tenant': tenant,
                                    'scopes': ['customers:read', 'events:publish']}])
        preq.refresh_from_db()
        return pconn, preq.connection

    def pair_outbound(self, peer=None, *, tenant='cust-1', org=None):
        """Clientst0r connects to the peer (Clientst0r is the initiator)."""
        from connect import pairing
        peer = peer or self.peer
        org = org or self.org_a
        code = peer.create_invitation()
        info = pairing.discover(peer.base)
        conn = pairing.start_outbound(info, code, requested_scopes=self.PEER_SCOPES,
                                      organizations=[org], user=self.admin)
        pconn = peer.connections[peer.requests[conn.pairing_request_id]]
        self.assertEqual(conn.sas, pconn.sas)
        peer.approve(conn.pairing_request_id, scopes=self.PEER_SCOPES,
                     tenant_grants=[{'remote_tenant': self.org_id(org), 'local_tenant': tenant,
                                     'scopes': ['customers:read', 'events:publish']}],
                     requested_scopes=self.SCOPES)
        self.assertEqual(pairing.poll(conn), 'approved')
        conn.refresh_from_db()
        pairing.approve_local(conn, scopes=self.SCOPES, grants=[(org.pk, tenant, ['customers:read',
                                                                                  'events:publish'])],
                              user=self.admin)
        conn.refresh_from_db()
        return conn, pconn
