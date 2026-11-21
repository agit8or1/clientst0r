"""Admin UI, permissions, navigation, management commands, row-bound AAD."""
import base64
import os
import uuid
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from .base import CONNECT_SETTINGS, CS_BASE, ConnectTestCase

UI = '/settings/integrations/connected-apps/'


def _get(client, path):
    return client.get(path, secure=True, HTTP_HOST='clientst0r.test')


def _post(client, path, data):
    return client.post(path, data, secure=True, HTTP_HOST='clientst0r.test')


class AdminPages(ConnectTestCase):
    def test_index_catalog_honest(self):
        r = _get(self.ui, UI)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Connected Applications', html)
        self.assertIn('not yet released', html)
        self.assertIn('Planned', html)
        self.assertIn('Emergency kill switch', html)

    def test_wizard_verify_then_pair_outbound(self):
        from connect.models import Connection
        r = _post(self.ui, UI + 'new/rem0te/', {'url': self.peer.base, 'op': 'verify'})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn(self.peer.installation_id, html)
        self.assertIn('Advanced settings', html)
        code = self.peer.create_invitation()
        r = _post(self.ui, UI + 'new/rem0te/', {'url': self.peer.base, 'op': 'pair', 'destination_addresses': '93.184.216.40', 'peer_sources': '93.184.216.34', 'pairing_secret': code,
                                               'scopes': ['customers:read'], 'orgs': [str(self.org_a.pk)]})
        self.assertEqual(r.status_code, 302, r.content[:500])
        conn = Connection.objects.get()
        self.assertEqual(conn.state, Connection.AWAITING_REMOTE)
        page = _get(self.ui, UI + f'{conn.pk}/').content.decode()
        self.assertIn(conn.sas, page)
        self.peer.approve(conn.pairing_request_id, scopes=['customers:read'],
                          tenant_grants=[{'remote_tenant': self.org_id(self.org_a), 'local_tenant': 'cust-1',
                                          'scopes': ['customers:read']}], requested_scopes=['customers:read'])
        _post(self.ui, UI + f'{conn.pk}/', {'op': 'poll'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.AWAITING_LOCAL)
        page = _get(self.ui, UI + f'{conn.pk}/').content.decode()
        self.assertIn('value="cust-1"', page)     # pre-filled from the peer's mapping
        _post(self.ui, UI + f'{conn.pk}/', {'op': 'approve_local', 'scopes': ['customers:read'], 'grant_rows': '2',
                                            'org_0': str(self.org_a.pk), 'tenant_0': 'cust-1',
                                            'scope_0': ['customers:read']})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.ACTIVE)
        self.assertEqual(conn.tenant_grants.get().remote_tenant_id, 'cust-1')

    def test_wizard_wrong_app_type_and_bad_code_are_friendly(self):
        from agit8or_connect.reference_peer import ReferencePeer
        other = ReferencePeer('https://office.test', self.net, app_type='office-unbound')
        r = _post(self.ui, UI + 'new/rem0te/', {'url': other.base, 'op': 'verify'})
        self.assertIn('not Rem0te', r.content.decode())
        r = _post(self.ui, UI + 'new/rem0te/', {'url': self.peer.base, 'op': 'pair', 'destination_addresses': '93.184.216.40', 'peer_sources': '93.184.216.34', 'pairing_secret': '00000-00000',
                                               'scopes': ['customers:read']})
        self.assertEqual(r.status_code, 200)
        self.assertIn('did not accept the pairing code', r.content.decode())
        self.assertNotIn('Traceback', r.content.decode())

    def test_planned_app_has_no_wizard(self):
        self.assertEqual(_get(self.ui, UI + 'new/exploithound/').status_code, 404)

    def test_invite_shows_code_once_with_qr(self):
        from connect.models import PairingInvitation
        r = _post(self.ui, UI + 'invite/', {'peer_sources': '93.184.216.34', 'label': 'lab'})
        html = r.content.decode()
        self.assertIn('<svg', html)
        inv = PairingInvitation.objects.get()
        self.assertNotIn(inv.code_hash, html)
        self.assertEqual(_get(self.ui, UI + 'invite/').status_code, 200)
        self.assertNotIn('data-connect-code', _get(self.ui, UI + 'invite/').content.decode())

    def test_inbound_review_approve_through_ui(self):
        from connect import pairing
        from connect.models import Connection, PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read', 'connection:read'],
                                        proposed_tenants=[{'id': 'cust-1', 'label': 'Acme Customer'}])
        preq = PairingRequest.objects.get(pk=pconn.request_id)
        page = _get(self.ui, UI + f'requests/{preq.pk}/').content.decode()
        self.assertIn(pconn.sas, page)
        self.assertIn('Acme Customer', page)
        r = _post(self.ui, UI + f'requests/{preq.pk}/', {
            'op': 'approve', 'destination_addresses': '93.184.216.40', 'scopes': ['customers:read', 'connection:read'], 'grant_rows': '2',
            'org_0': str(self.org_a.pk), 'tenant_0': 'cust-1', 'scope_0': ['customers:read', 'tickets:write'],
            'requested_scopes': ['customers:read']})
        self.assertEqual(r.status_code, 302, r.content[:800])
        conn = Connection.objects.get(pk=preq.connection_id)
        self.assertEqual(conn.tenant_grants.get().scopes, ['customers:read'])  # unticked scope dropped
        self.assertEqual(self.peer.poll(pconn.id), 'approved')
        self.peer.accept(pconn.id)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.TESTING)       # C3: active only after the test
        r = _post(self.ui, UI + f'{conn.pk}/', {'op': 'commit_test'})
        self.assertEqual(r.status_code, 302)
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.ACTIVE, conn.last_error)
        # detail ops
        r = _post(self.ui, UI + f'{conn.pk}/', {'op': 'test'})
        self.assertEqual(r.status_code, 302)
        r = _post(self.ui, UI + f'{conn.pk}/', {'op': 'revoke_grant', 'grant': conn.tenant_grants.get().pk})
        self.assertFalse(conn.tenant_grants.get().active)
        _post(self.ui, UI + f'{conn.pk}/', {'op': 'suspend'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.SUSPENDED)
        _post(self.ui, UI + f'{conn.pk}/', {'op': 'resume'})
        _post(self.ui, UI + f'{conn.pk}/', {'op': 'disconnect'})
        conn.refresh_from_db()
        self.assertEqual(conn.state, Connection.REVOKED)

    def test_reject_inbound(self):
        from connect import pairing
        from connect.models import PairingRequest
        _, code = pairing.create_invitation(self.admin, peer_sources=[self.peer_ip])
        pconn = self.peer.start_pairing(CS_BASE, code, requested_scopes=['customers:read'])
        _post(self.ui, UI + f'requests/{pconn.request_id}/', {'op': 'reject'})
        self.assertEqual(PairingRequest.objects.get(pk=pconn.request_id).status, PairingRequest.REJECTED)
        self.assertEqual(self.peer.poll(pconn.id), 'rejected')


class Permissions(ConnectTestCase):
    def setUp(self):
        super().setUp()
        from accounts.models import RoleTemplate, UserProfile, UserType
        self.viewer_role = RoleTemplate.objects.create(name='Connect viewer', view_app_connections=True)
        self.viewer = User.objects.create_user('viewer', 'v@example.test', 'pw-Viewer-1!x')
        prof, _ = UserProfile.objects.get_or_create(user=self.viewer)
        prof.user_type, prof.global_role_template = UserType.STAFF, self.viewer_role
        prof.save()
        # Fresh instance: the cached profile on the old one would be re-saved by
        # force_login's last_login update.
        self.viewer = User.objects.get(pk=self.viewer.pk)
        self.nobody = User.objects.create_user('nobody', 'n@example.test', 'pw-Nobody-1!x')

    def test_view_vs_manage(self):
        v = Client()
        v.force_login(self.viewer)
        self.assertEqual(_get(v, UI).status_code, 200)
        self.assertNotIn('Emergency kill switch', _get(v, UI).content.decode())
        self.assertEqual(_post(v, UI + 'kill-switch/', {}).status_code, 403)
        self.assertEqual(_post(v, UI + 'invite/', {'peer_sources': '93.184.216.34', }).status_code, 403)
        n = Client()
        n.force_login(self.nobody)
        self.assertEqual(_get(n, UI).status_code, 403)

    def test_registry_and_seeds(self):
        from accounts import permission_registry as reg
        from accounts.models import RoleTemplate
        self.assertTrue(reg.REGISTRY['view_app_connections'].staff_only)
        self.assertTrue(reg.REGISTRY['manage_app_connections'].staff_only)
        for f in ('view_app_connections', 'manage_app_connections'):
            RoleTemplate._meta.get_field(f)

    def test_navigation_tab_gated(self):
        from core import navigation
        r = _get(self.ui, UI)
        self.assertIn('Connected Applications', r.content.decode())
        self.assertTrue(navigation._app_connections_viewer({'user': self.admin}))
        self.assertFalse(navigation._app_connections_viewer({'user': self.nobody}))
        with override_settings(AGIT8OR_CONNECT_ENABLED=False):
            self.assertFalse(navigation._app_connections_viewer({'user': self.admin}))


class Commands(ConnectTestCase):
    def test_commands(self):
        from connect import identity
        pconn, conn = self.pair_inbound()
        out = StringIO()
        call_command('connect_verify_audit_chain', stdout=out)
        self.assertIn('intact', out.getvalue())
        call_command('connect_deliver_events', stdout=out)
        call_command('connect_rotate_keys', stdout=out)
        self.assertIn('rotated 0', out.getvalue())
        call_command('connect_kill_switch', stdout=out)
        self.assertTrue(identity.kill_switch_engaged())
        call_command('connect_kill_switch', '--release', stdout=out)
        self.assertFalse(identity.kill_switch_engaged())

    def test_scheduler_registration(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        types = dict(ScheduledTask.TASK_TYPES)
        for t in ('connect_deliver_events', 'connect_rotate_keys'):
            self.assertIn(t, types)
            self.assertEqual(COMMAND_TASKS[t][0], t)

    @override_settings(AGIT8OR_CONNECT_ENABLED=False)
    def test_scheduled_commands_noop_when_disabled(self):
        out = StringIO()
        call_command('connect_deliver_events', stdout=out)
        call_command('connect_rotate_keys', stdout=out)
        self.assertIn('off', out.getvalue())


@override_settings(**CONNECT_SETTINGS)
class RowBoundEncryption(TestCase):
    def test_rotate_encryption_key_keeps_row_binding(self):
        from connect import store
        from connect.models import Connection, ConnectionKey
        old = base64.b64encode(os.urandom(32)).decode()
        new = base64.b64encode(os.urandom(32)).decode()
        with override_settings(APP_MASTER_KEY=old, APP_MASTER_KEY_PREVIOUS=''):
            conn = Connection.objects.create(direction=Connection.OUTBOUND, base_url='https://x.test')
            row, _ = store.new_key(conn)
            pem = row.private_pem()
            fh = os.path.join(os.environ.get('TMPDIR', '/tmp'), f'connect-key-{uuid.uuid4().hex}')
            with open(fh, 'w') as f:
                f.write(new)
            self.addCleanup(os.unlink, fh)
            call_command('rotate_encryption_key', new_key_file=fh, stdout=StringIO())
        with override_settings(APP_MASTER_KEY=new, APP_MASTER_KEY_PREVIOUS=''):
            self.assertEqual(ConnectionKey.objects.get(pk=row.pk).private_pem(), pem)

    def test_row_aad_normalises_raw_pk(self):
        from connect.models import ConnectionKey
        f = ConnectionKey._meta.get_field('private_key')
        u = uuid.uuid4()
        self.assertEqual(f.row_aad(u.hex), f.row_aad(u))
        self.assertEqual(f.row_aad(str(u)), f'connect.ConnectionKey.private_key#{u}')
