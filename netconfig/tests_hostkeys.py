"""SSH host-key pinning against a real (disposable, in-process) SSH server — v3.17.629.

The server records every authentication attempt, so these tests can show not
only that collection fails on an unknown or changed key, but that the vault
password was never sent.
"""
import socket
import threading

import paramiko
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from assets.models import Asset
from audit.models import AuditLog
from core.models import Organization
from netconfig import hostkeys
from netconfig.models import BackupTarget, ConfigBackup

CONFIG = 'hostname lab-sw-01\ninterface Gi1/0/1\n description uplink\nend\n'


class _Iface(paramiko.ServerInterface):
    def __init__(self, log):
        self.log = log

    def get_allowed_auths(self, username):
        return 'password'

    def check_auth_password(self, username, password):
        self.log.append(('auth', username, password))
        return paramiko.AUTH_SUCCESSFUL if password == 'lab-pw' else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode()
        self.log.append(('exec', cmd))

        def reply():
            channel.sendall((CONFIG if 'running-config' in cmd else 'Cisco IOS Software, Version 15.2(4)E\n').encode())
            channel.send_exit_status(0)
            channel.close()
        threading.Thread(target=reply, daemon=True).start()
        return True


class DisposableSSHServer:
    """One host key, any number of connections, everything logged."""

    def __init__(self, key, disabled_algorithms=None):
        self.key = key
        self.disabled = disabled_algorithms or {}
        self.log = []
        self.connections = 0
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self._threads = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            t = paramiko.Transport(conn, disabled_algorithms=self.disabled)
            t.add_server_key(self.key)
            try:
                t.start_server(server=_Iface(self.log))
            except Exception:  # noqa: BLE001 — client may abort negotiation
                continue
            self._threads.append(t)

    def close(self):
        self._stop = True
        self.sock.close()
        for t in self._threads:
            t.close()


def fp_of(key):
    return hostkeys.fingerprint(key.asbytes())


class HostKeyPinningTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_a = paramiko.ECDSAKey.generate()
        cls.key_b = paramiko.ECDSAKey.generate()

    def setUp(self):
        from vault.models import Password
        self.user = get_user_model().objects.create_user('netops', password='x')
        self.org = Organization.objects.create(name='LabCo', slug='lab-co')
        self.asset = Asset.objects.create(organization=self.org, name='lab-sw-01', asset_type='switch')
        cred = Password.objects.create(organization=self.org, title='lab', username='admin')
        cred.set_password('lab-pw')
        cred.save()
        self.servers = []
        self.server = self._server(self.key_a)
        self.target = BackupTarget.objects.create(asset=self.asset, host='127.0.0.1', port=self.server.port,
                                                  username='admin', credential=cred, adapter='cisco_ios')

    def tearDown(self):
        for s in self.servers:
            s.close()

    def _server(self, key, **kw):
        s = DisposableSSHServer(key, **kw)
        self.servers.append(s)
        return s

    def _collect(self):
        from netconfig.collector import collect_target
        return collect_target(self.target, timeout=10)

    def _auths(self, server):
        return [e for e in server.log if e[0] == 'auth']

    def test_no_approved_key_blocks_before_connecting(self):
        result = self._collect()
        self.assertFalse(result['ok'])
        self.assertIn('host key has not been approved', result['message'])
        self.assertEqual(self.server.connections, 0)

    def test_enrollment_flow_then_collection(self):
        key_type, fp, same = hostkeys.fetch_host_key(self.target, user=self.user)
        self.assertFalse(same)
        self.assertEqual(fp, fp_of(self.key_a))
        self.target.refresh_from_db()
        self.assertEqual(self.target.pending_host_key_fingerprint, fp)
        self.assertEqual(self.target.host_key, '')
        self.assertEqual(self._auths(self.server), [], 'fetching a key must not authenticate')
        self.assertTrue(AuditLog.objects.filter(object_type='backuptarget', extra_data__event='host_key_fetched').exists())

        hostkeys.approve_pending(self.target, self.user, fp)
        self.target.refresh_from_db()
        self.assertEqual(self.target.host_key_fingerprint, fp)
        self.assertEqual(self.target.host_key_approved_by, self.user)
        self.assertEqual(self.target.pending_host_key, '')

        result = self._collect()
        self.assertTrue(result['ok'], result['message'])
        self.assertEqual(self._auths(self.server), [('auth', 'admin', 'lab-pw')])
        self.assertIn(('exec', 'show running-config'), self.server.log)
        self.assertEqual(ConfigBackup.objects.get(asset=self.asset).firmware_version, '15.2(4)E')

    def test_changed_key_is_refused_before_the_password_is_sent(self):
        hostkeys._set_approved(self.target, self.user, self.key_a.get_name(),
                               __import__('base64').b64encode(self.key_a.asbytes()).decode(), fp_of(self.key_a),
                               source='test')
        impostor = self._server(self.key_b)
        self.target.port = impostor.port
        self.target.save()

        result = self._collect()
        self.assertFalse(result['ok'])
        self.assertIn('HOST KEY MISMATCH', result['message'])
        self.assertIn(fp_of(self.key_a), result['message'])
        self.assertIn(fp_of(self.key_b), result['message'])
        self.assertEqual(self._auths(impostor), [], 'the password reached a server with the wrong key')
        self.target.refresh_from_db()
        self.assertEqual(self.target.host_key_fingerprint, fp_of(self.key_a), 'a changed key must not be auto-approved')
        self.assertEqual(self.target.pending_host_key_fingerprint, fp_of(self.key_b))

        # Explicit rotation: approve the new key, audited with both fingerprints.
        hostkeys.approve_pending(self.target, self.user, fp_of(self.key_b))
        entry = AuditLog.objects.filter(extra_data__event='host_key_rotated').latest('timestamp')
        self.assertEqual(entry.extra_data['old_fingerprint'], fp_of(self.key_a))
        self.assertEqual(entry.extra_data['new_fingerprint'], fp_of(self.key_b))
        self.assertTrue(self._collect()['ok'])
        self.assertEqual(self._auths(impostor), [('auth', 'admin', 'lab-pw')])

    def test_stale_approval_is_rejected(self):
        hostkeys.fetch_host_key(self.target, user=self.user)
        with self.assertRaises(hostkeys.HostKeyError):
            hostkeys.approve_pending(self.target, self.user, 'SHA256:not-what-was-shown')
        self.target.refresh_from_db()
        self.assertEqual(self.target.host_key, '')

    def test_paste_known_key(self):
        import base64
        line = f'[127.0.0.1]:{self.server.port} {self.key_a.get_name()} {base64.b64encode(self.key_a.asbytes()).decode()}'
        fp = hostkeys.approve_pasted(self.target, self.user, line)
        self.assertEqual(fp, fp_of(self.key_a))
        self.assertTrue(self._collect()['ok'])
        with self.assertRaises(hostkeys.HostKeyError):
            hostkeys.approve_pasted(self.target, self.user, 'ssh-ed25519 not-base64!!')

    def test_sha1_ssh_rsa_is_refused_unless_explicitly_allowed(self):
        rsa = paramiko.RSAKey.generate(2048)
        # A server that can only sign with SHA-1 "ssh-rsa".
        legacy = self._server(rsa, disabled_algorithms={'keys': ['rsa-sha2-256', 'rsa-sha2-512']})
        self.target.port = legacy.port
        self.target.save()
        with self.assertRaises(hostkeys.HostKeyError):
            hostkeys.fetch_host_key(self.target, user=self.user)
        hostkeys.set_legacy_rsa(self.target, self.user, True)
        self.assertTrue(AuditLog.objects.filter(extra_data__event='legacy_ssh_rsa').exists())
        _, fp, _ = hostkeys.fetch_host_key(self.target, user=self.user)
        self.assertEqual(fp, fp_of(rsa))

    def test_rsa_key_works_over_sha2_by_default(self):
        rsa = paramiko.RSAKey.generate(2048)
        modern = self._server(rsa)
        self.target.port = modern.port
        self.target.save()
        _, fp, _ = hostkeys.fetch_host_key(self.target, user=self.user)
        hostkeys.approve_pending(self.target, self.user, fp)
        self.assertTrue(self._collect()['ok'])


@override_settings(SECURE_SSL_REDIRECT=False)
class HostKeyViewPermissionTests(TestCase):
    def setUp(self):
        from accounts.models import Membership, Role
        from django.conf import settings
        self._mw = override_settings(MIDDLEWARE=[m for m in settings.MIDDLEWARE
                                                 if 'Enforce2FA' not in m and 'Axes' not in m])
        self._mw.enable()
        User = get_user_model()
        self.org = Organization.objects.create(name='ViewCo', slug='view-co')
        self.asset = Asset.objects.create(organization=self.org, name='sw', asset_type='switch')
        self.target = BackupTarget.objects.create(asset=self.asset, host='10.0.0.9', username='admin')
        self.editor = User.objects.create_user('hk_editor', password='x')
        Membership.objects.create(user=self.editor, organization=self.org, role=Role.EDITOR, is_active=True)
        self.reader = User.objects.create_user('hk_reader', password='x')
        Membership.objects.create(user=self.reader, organization=self.org, role=Role.READONLY, is_active=True)
        self.key = paramiko.ECDSAKey.generate()

    def tearDown(self):
        self._mw.disable()

    def _post(self, user, **data):
        import base64
        self.client.force_login(user)
        s = self.client.session
        s['current_organization_id'] = self.org.pk
        s.save()
        data.setdefault('public_key', f'{self.key.get_name()} {base64.b64encode(self.key.asbytes()).decode()}')
        return self.client.post(f'/netconfig/device/{self.asset.pk}/connection/', data)

    def test_read_only_user_cannot_approve_a_key(self):
        self._post(self.reader, action='hostkey_paste')
        self.target.refresh_from_db()
        self.assertEqual(self.target.host_key, '')

    def test_editor_can_approve_and_it_is_audited(self):
        self._post(self.editor, action='hostkey_paste')
        self.target.refresh_from_db()
        self.assertEqual(self.target.host_key_fingerprint, fp_of(self.key))
        log = AuditLog.objects.get(extra_data__event='host_key_approved')
        self.assertEqual(log.user, self.editor)
