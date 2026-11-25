"""P0-2 (docs/ux/STANDALONE_REQUIREMENTS.md, rules F1, F3, F4; matrix H):
a configured but unreachable peer never affects page rendering.

The fixture has a Rem0te provider row, a third-party RMM connection with a
device linked to an asset, a ticket on that asset, an RMM request in flight and
an active Connect pairing. Rendering the ticket, asset, device workspace,
client workspace, dashboards and the RMM / integration pages must not call
out at all: ``attempts == 0`` under peer_unreachable() (which makes every
HTTP call fail instantly, in both "refused" and "timeout" flavours).
"""
import time
import uuid

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.tests.standalone import peer_unreachable
from integrations.models import RMMConnection
from integrations.rem0te import testing as rem0te_testing
from psa.tests._base import TEST_MIDDLEWARE
from psa_ai.tests_assist import KEY_DIR
from psa_ai.tests_rmm import RMMActionBase


def _connect_pairing():
    from connect.models import Connection
    return Connection.objects.create(
        direction=Connection.OUTBOUND, state=Connection.ACTIVE, remote_app_type='rem0te',
        remote_installation_id='inst-' + uuid.uuid4().hex[:8], remote_display_name='Rem0te (unreachable)',
        base_url='https://rem0te.example.com')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, AI_GATEWAY_KEY_DIR=KEY_DIR,
                   AI_GATEWAY_MODE='in_process', ALLOWED_HOSTS=['*'], AGIT8OR_CONNECT_ENABLED=True)
class PeerUnreachablePagesTests(RMMActionBase):

    def setUp(self):
        super().setUp()
        self.rem0te = rem0te_testing.make_connection(self.a, name='Rem0te (unreachable)')
        self.pairing = _connect_pairing()
        from psa_ai.models import RMMRequest
        self.request_row = RMMRequest.objects.filter(ticket=self.ticket).first()
        self.calls.clear()

    def pages(self):
        return {
            'ticket detail': f'/psa/t/{self.ticket.ticket_number}/',
            'asset detail': f'/assets/{self.asset.pk}/',
            'device workspace': f'/assets/{self.asset.pk}/workspace/',
            'client workspace': reverse('accounts:organization_detail', args=[self.a.pk]),
            'dashboard': reverse('core:dashboard'),
            'ticket list': reverse('psa:ticket_list'),
            'asset list': reverse('assets:asset_list'),
            'rmm devices': reverse('integrations:rmm_devices'),
            'rmm alerts': reverse('integrations:rmm_alerts'),
            'integrations': reverse('integrations:integration_list'),
        }

    def _render_all(self, mode):
        failures = []
        with peer_unreachable(mode) as peer:
            for label, path in self.pages().items():
                before = len(peer.attempts)
                t0 = time.monotonic()
                r = self.c.get(path)
                if r.status_code != 200:
                    failures.append(f'{label} {path}: HTTP {r.status_code}')
                if len(peer.attempts) != before:
                    failures.append(f'{label} {path}: outbound {peer.attempts[before:]}')
                if time.monotonic() - t0 > 20:
                    failures.append(f'{label} {path}: slow')
        self.assertEqual(failures, [], '\n'.join(failures))
        self.assertEqual(len(peer.attempts), 0)
        self.assertEqual(self.calls, [], 'a page called the ticket-rmm processor while rendering')

    def test_pages_render_with_a_peer_that_times_out(self):
        self._render_all('timeout')

    def test_pages_render_with_a_peer_that_refuses_connections(self):
        self._render_all('refuse')

    def test_global_dashboard_for_a_superuser(self):
        from django.contrib.auth import get_user_model
        from django.test import Client
        su = get_user_model().objects.create_superuser('p02_root', 'r@x.test', 'pw')
        c = Client()
        c.force_login(su)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        with peer_unreachable('timeout') as peer:
            for name in ('core:dashboard', 'core:global_dashboard', 'integrations:rmm_devices',
                         'integrations:rmm_alerts', 'connect:index'):
                r = c.get(reverse(name))
                self.assertEqual(r.status_code, 200, name)
        self.assertEqual(peer.attempts, [])

    def test_the_fixture_really_is_unreachable(self):
        """The guard works: an explicit call to the peer is refused and recorded."""
        import requests
        with peer_unreachable('timeout') as peer:
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                requests.get('https://rem0te.example.com/api/x', timeout=3)
        self.assertEqual(len(peer.attempts), 1)
        self.assertTrue(RMMConnection.objects.filter(provider_type='rem0te').exists())
        self.assertIsNotNone(timezone.now())
