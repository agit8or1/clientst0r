"""Roles & permissions program (authz-tech): network config backups.

Linking a vault credential to a device hands its plaintext to the collector,
which sends it to the configured host: that is a reveal and needs
vault_view_password (plus approval and access rules), not just vault_view.
Changing connection settings, collecting, capturing and approving baselines
are edits of the device (assets_edit), not reads.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from assets.models import Asset
from core.models import Organization
from netconfig.models import BackupTarget, ConfigBackup
from vault.models import Password
from vault.tests_extension_gate import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class NetconfigAuthzTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Net authz', slug='authz-net')
        self.asset = Asset.objects.create(organization=self.org, name='edge-fw', asset_type='firewall')
        self.cred = Password.objects.create(organization=self.org, title='fw admin', username='admin')
        self.cred.set_password('top-secret')
        self.cred.save()
        self.c = Client()

    def _as(self, **flags):
        role = RoleTemplate.objects.create(name='authz net ' + '-'.join(sorted(flags)), **flags)
        user = User.objects.create_user('authz-net-' + str(RoleTemplate.objects.count()), password='pw')
        Membership.objects.create(user=user, organization=self.org, role=Role.EDITOR, role_template=role)
        self.c.force_login(user)
        s = self.c.session
        s['current_organization_id'] = self.org.id
        s['2fa_prompted'] = True
        s.save()
        return user

    def _save_target(self, host='203.0.113.9'):
        return self.c.post(f'/netconfig/device/{self.asset.pk}/connection/', {
            'host': host, 'username': 'admin', 'port': '22', 'credential': self.cred.pk,
            'adapter': 'generic', 'cadence_hours': '24'})

    def test_vault_view_without_reveal_cannot_link_credential(self):
        self._as(assets_view=True, assets_edit=True, vault_view=True, vault_view_password=False)
        self._save_target()
        self.assertFalse(BackupTarget.objects.filter(asset=self.asset, credential=self.cred).exists())

    def test_reveal_holder_can_link_credential(self):
        self._as(assets_view=True, assets_edit=True, vault_view=True, vault_view_password=True)
        self._save_target()
        self.assertTrue(BackupTarget.objects.filter(asset=self.asset, credential=self.cred).exists())

    def test_assets_view_only_cannot_change_target_or_capture(self):
        self._as(assets_view=True, assets_edit=False, vault_view=True, vault_view_password=True)
        self._save_target()
        self.assertFalse(BackupTarget.objects.filter(asset=self.asset).exists())
        self.c.post(f'/netconfig/device/{self.asset.pk}/capture/', {'body': 'hostname evil'})
        self.assertFalse(ConfigBackup.objects.filter(asset=self.asset).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StoredConfigReadTests(TestCase):
    """Stored configurations hold secrets: customer users need
    vault_view_password to read them; a changed address drops the approved
    host key."""
    setUp = NetconfigAuthzTests.setUp
    _as = NetconfigAuthzTests._as
    _save_target = NetconfigAuthzTests._save_target

    def _backup(self):
        from django.utils import timezone
        b, _ = ConfigBackup.record_for_asset(self.asset, 'enable secret 5 $1$abc\n',
                                             source='manual', captured_at=timezone.now())
        return b

    def test_assets_view_without_reveal_cannot_read_configs(self):
        b = self._backup()
        self._as(assets_view=True, vault_view=True, vault_view_password=False)
        self.assertEqual(self.c.get(f'/netconfig/backup/{b.pk}/').status_code, 403)
        self.assertEqual(self.c.get(f'/netconfig/device/{self.asset.pk}/compare/').status_code, 403)

    def test_reveal_holder_reads_configs(self):
        b = self._backup()
        self._as(assets_view=True, vault_view=True, vault_view_password=True)
        self.assertEqual(self.c.get(f'/netconfig/backup/{b.pk}/').status_code, 200)

    def test_changed_host_drops_approved_key(self):
        self._as(assets_view=True, assets_edit=True, vault_view=True, vault_view_password=True)
        self._save_target()
        t = BackupTarget.objects.get(asset=self.asset)
        t.host_key, t.host_key_fingerprint, t.host_key_type = 'AAAA', 'SHA256:x', 'ssh-ed25519'
        t.save()
        self._save_target(host='198.51.100.7')
        t.refresh_from_db()
        self.assertEqual(t.host, '198.51.100.7')
        self.assertEqual(t.host_key, '')
