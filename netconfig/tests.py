"""
Phase 34.1 (v3.17.544) — config backup tests.

Most of these are about the two things that make a snapshot store worth having:
that it does not accumulate identical copies, and that a snapshot cannot be
quietly rewritten after the fact.
"""
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from assets.models import Asset
from core.models import Organization
from netconfig.adapters import (
    CiscoIOSAdapter, CollectionError, get_adapter,
)
from netconfig.models import BackupTarget, ConfigBackup

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

CONFIG_A = """hostname core-sw-01
!
interface GigabitEthernet0/1
 description uplink
 switchport mode trunk
!
end"""

CONFIG_B = """hostname core-sw-01
!
interface GigabitEthernet0/1
 description uplink to firewall
 switchport mode trunk
!
interface GigabitEthernet0/2
 description new AP
!
end"""


class ConfigBackupModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='NetCo', slug='net-co')
        cls.asset = Asset.objects.create(
            organization=cls.org, name='core-sw-01', asset_type='switch')

    def test_first_capture_is_created(self):
        backup, created = ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        self.assertTrue(created)
        self.assertEqual(backup.body, CONFIG_A)

    def test_identical_capture_does_not_duplicate(self):
        """A device nobody touches for a year should be one row, not 365."""
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        backup, created = ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        self.assertFalse(created)
        self.assertEqual(ConfigBackup.objects.count(), 1)

    def test_identical_capture_moves_last_seen(self):
        """The device was reachable and unchanged — worth recording without
        another copy of the text."""
        first, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=2))
        later = timezone.now()
        again, created = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=later)
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(again.last_seen_at, later)
        self.assertEqual(again.captured_at, first.captured_at)

    def test_changed_capture_creates_a_new_row(self):
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        _, created = ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        self.assertTrue(created)
        self.assertEqual(ConfigBackup.objects.count(), 2)

    def test_trailing_whitespace_is_not_a_change(self):
        """A device that starts padding lines has not changed its config."""
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        padded = '\n'.join(line + '   ' for line in CONFIG_A.splitlines())
        _, created = ConfigBackup.record_for_asset(self.asset, padded)
        self.assertFalse(created)

    def test_line_ending_change_is_not_a_change(self):
        """Switching CRLF to LF must not read as "everything changed"."""
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        crlf = CONFIG_A.replace('\n', '\r\n')
        _, created = ConfigBackup.record_for_asset(self.asset, crlf)
        self.assertFalse(created)

    def test_hash_differs_for_real_changes(self):
        self.assertNotEqual(
            ConfigBackup.hash_body(CONFIG_A), ConfigBackup.hash_body(CONFIG_B))

    def test_organization_is_denormalised_from_the_asset(self):
        backup, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        self.assertEqual(backup.organization_id, self.org.id)

    def test_previous_returns_the_one_before(self):
        old, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        new, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        self.assertEqual(new.previous(), old)
        self.assertIsNone(old.previous())

    def test_diff_against_none_is_empty_not_an_error(self):
        """The first capture of a device has nothing to compare against, and
        that is a normal state."""
        first, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        self.assertEqual(first.diff_against(None), [])

    def test_diff_shows_the_change(self):
        old, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        new, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        diff = '\n'.join(new.diff_against(old))
        self.assertIn('+interface GigabitEthernet0/2', diff)
        self.assertIn('- description uplink', diff)

    def test_diff_stats_count_added_and_removed(self):
        old, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        new, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        stats = new.diff_stats(old)
        self.assertEqual(stats['added'], 4)
        self.assertEqual(stats['removed'], 1)

    def test_diff_stats_ignore_the_file_headers(self):
        """+++ and --- are diff furniture, not changed lines."""
        old, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        same_text_new_row = ConfigBackup.objects.create(
            asset=self.asset, organization=self.org, body=CONFIG_A,
            content_hash=ConfigBackup.hash_body(CONFIG_A),
            captured_at=timezone.now(), last_seen_at=timezone.now())
        stats = same_text_new_row.diff_stats(old)
        self.assertEqual(stats, {'added': 0, 'removed': 0})

    def test_changed_from_previous(self):
        old, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        new, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        self.assertTrue(new.changed_from_previous)
        self.assertFalse(old.changed_from_previous)

    def test_line_count(self):
        backup, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        self.assertEqual(backup.line_count, 7)

    def test_empty_body_is_storable_without_crashing(self):
        backup, created = ConfigBackup.record_for_asset(self.asset, '')
        self.assertTrue(created)
        self.assertEqual(backup.line_count, 0)

    def test_backups_are_per_device(self):
        other = Asset.objects.create(
            organization=self.org, name='core-sw-02', asset_type='switch')
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        ConfigBackup.record_for_asset(other, CONFIG_A)
        self.assertEqual(ConfigBackup.objects.filter(asset=self.asset).count(), 1)
        self.assertEqual(ConfigBackup.objects.filter(asset=other).count(), 1)

    def test_backups_cascade_with_the_asset(self):
        doomed = Asset.objects.create(
            organization=self.org, name='gone', asset_type='router')
        ConfigBackup.record_for_asset(doomed, CONFIG_A)
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        doomed.delete()
        self.assertEqual(ConfigBackup.objects.count(), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConfigBackupViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='ViewNet', slug='view-net')
        self.asset = Asset.objects.create(
            organization=self.org, name='core-sw-01', asset_type='switch')
        self.laptop = Asset.objects.create(
            organization=self.org, name='someones-laptop', asset_type='laptop')
        self.user = User.objects.create_superuser(
            'netadmin', 'n@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.user)

    def test_anonymous_is_redirected(self):
        resp = Client().get('/netconfig/')
        self.assertIn(resp.status_code, (302, 403))

    def test_device_list_shows_network_gear(self):
        resp = self.client.get('/netconfig/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'core-sw-01')

    def test_device_list_excludes_non_network_assets(self):
        """A config backup of a laptop is not a thing, and offering it
        everywhere buries the devices it matters for."""
        self.assertNotContains(self.client.get('/netconfig/'), 'someones-laptop')

    def test_capture_stores_a_pasted_config(self):
        self.client.post(f'/netconfig/device/{self.asset.pk}/capture/',
                         {'body': CONFIG_A})
        self.assertEqual(ConfigBackup.objects.filter(asset=self.asset).count(), 1)

    def test_capture_records_who_did_it(self):
        self.client.post(f'/netconfig/device/{self.asset.pk}/capture/',
                         {'body': CONFIG_A})
        self.assertEqual(ConfigBackup.objects.first().captured_by, self.user)

    def test_empty_capture_is_refused(self):
        self.client.post(f'/netconfig/device/{self.asset.pk}/capture/',
                         {'body': '   '})
        self.assertEqual(ConfigBackup.objects.count(), 0)

    def test_capture_of_a_non_network_asset_404s(self):
        resp = self.client.post(f'/netconfig/device/{self.laptop.pk}/capture/',
                                {'body': CONFIG_A})
        self.assertEqual(resp.status_code, 404)

    def test_device_detail_renders_latest_change(self):
        ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        resp = self.client.get(f'/netconfig/device/{self.asset.pk}/')
        self.assertContains(resp, 'Latest change')
        self.assertContains(resp, 'GigabitEthernet0/2')

    def test_device_detail_with_one_snapshot_shows_no_diff_section(self):
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        self.assertNotContains(
            self.client.get(f'/netconfig/device/{self.asset.pk}/'), 'Latest change')

    def test_compare_defaults_to_the_two_newest(self):
        ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        resp = self.client.get(f'/netconfig/device/{self.asset.pk}/compare/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['right'].body, CONFIG_B)
        self.assertEqual(resp.context['left'].body, CONFIG_A)

    def test_compare_honours_explicit_picks(self):
        a, _ = ConfigBackup.record_for_asset(
            self.asset, CONFIG_A, captured_at=timezone.now() - timedelta(days=1))
        b, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_B)
        resp = self.client.get(
            f'/netconfig/device/{self.asset.pk}/compare/?left={b.pk}&right={a.pk}')
        self.assertEqual(resp.context['left'].pk, b.pk)
        self.assertEqual(resp.context['right'].pk, a.pk)

    def test_compare_with_no_snapshots_does_not_crash(self):
        resp = self.client.get(f'/netconfig/device/{self.asset.pk}/compare/')
        self.assertEqual(resp.status_code, 200)

    def test_view_backup_shows_the_config(self):
        backup, _ = ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        resp = self.client.get(f'/netconfig/backup/{backup.pk}/')
        self.assertContains(resp, 'switchport mode trunk')

    def test_repeat_capture_via_the_view_does_not_duplicate(self):
        for _ in range(3):
            self.client.post(f'/netconfig/device/{self.asset.pk}/capture/',
                             {'body': CONFIG_A})
        self.assertEqual(ConfigBackup.objects.filter(asset=self.asset).count(), 1)


# ---------------------------------------------------------------------------
# Phase 34.2 (v3.17.545) — SSH collection
# ---------------------------------------------------------------------------

class AdapterTests(TestCase):
    def test_unknown_key_falls_back_to_generic(self):
        """A device typed with a platform nobody wrote an adapter for should
        still be configurable, not 500."""
        self.assertEqual(get_adapter('nonsense').key, 'generic')
        self.assertEqual(get_adapter('').key, 'generic')

    def test_cisco_adapter_has_a_command_and_a_pager_fix(self):
        a = get_adapter('cisco_ios')
        self.assertEqual(a.config_command, 'show running-config')
        self.assertIn('terminal length 0', a.setup_commands)

    def test_clean_strips_the_echoed_command(self):
        a = CiscoIOSAdapter()
        raw = 'show running-config\nhostname sw1\n!\nend\nsw1#'
        self.assertEqual(a.clean(raw), 'hostname sw1\n!\nend')

    def test_clean_strips_a_trailing_prompt(self):
        a = CiscoIOSAdapter()
        self.assertEqual(a.clean('hostname sw1\nsw1#'), 'hostname sw1')

    def test_clean_leaves_a_plain_config_alone(self):
        a = CiscoIOSAdapter()
        self.assertEqual(a.clean('hostname sw1\nend'), 'hostname sw1\nend')

    def test_extract_version(self):
        a = CiscoIOSAdapter()
        raw = 'Cisco IOS Software, Version 15.2(4)E7, RELEASE SOFTWARE'
        self.assertEqual(a.extract_version(raw), '15.2(4)E7')

    def test_extract_version_missing_is_empty_not_an_error(self):
        self.assertEqual(CiscoIOSAdapter().extract_version('nothing here'), '')


class BackupTargetModelTests(TestCase):
    def setUp(self):
        from vault.models import Password
        self.org = Organization.objects.create(name='TgtCo', slug='tgt-co')
        self.asset = Asset.objects.create(
            organization=self.org, name='core-sw-01', asset_type='switch')
        self.cred = Password.objects.create(
            organization=self.org, title='switch admin', username='admin')
        self.cred.set_password('hunter2')
        self.cred.save()

    def _target(self, **kw):
        kw.setdefault('host', '10.0.0.2')
        kw.setdefault('username', 'admin')
        kw.setdefault('credential', self.cred)
        return BackupTarget.objects.create(asset=self.asset, **kw)

    def test_organization_is_taken_from_the_asset(self):
        self.assertEqual(self._target().organization_id, self.org.id)

    def test_cadence_has_a_floor_of_one_hour(self):
        """A device polled every minute is being hammered for a config that
        changes a few times a year."""
        self.assertEqual(self._target(cadence_hours=0).cadence_hours, 1)

    def test_a_never_collected_target_is_due(self):
        self.assertTrue(self._target().is_due)

    def test_a_recently_collected_target_is_not_due(self):
        t = self._target(cadence_hours=24)
        t.last_attempt_at = timezone.now()
        t.save()
        self.assertFalse(t.is_due)

    def test_an_overdue_target_is_due(self):
        t = self._target(cadence_hours=24)
        t.last_attempt_at = timezone.now() - timedelta(hours=30)
        t.save()
        self.assertTrue(t.is_due)

    def test_a_disabled_target_is_never_due(self):
        t = self._target(is_enabled=False)
        self.assertFalse(t.is_due)

    def test_no_credential_blocks_collection(self):
        t = self._target(credential=None)
        self.assertIn('No vault credential', t.blocking_reason())

    def test_no_host_blocks_collection(self):
        t = self._target()
        t.host = ''
        t.save()
        self.assertIn('No host', t.blocking_reason())

    def test_approval_gated_credential_blocks_unattended_collection(self):
        """The setting exists because somebody decided a human should sign off
        on each use. A nightly job cannot, and reading it anyway would defeat
        the control while leaving it switched on and looking effective."""
        self.cred.requires_reveal_approval = True
        self.cred.save(update_fields=['requires_reveal_approval'])
        t = self._target()
        t.refresh_from_db()
        self.assertIn('requires approval', t.blocking_reason())

    def test_a_fully_configured_target_is_not_blocked(self):
        self.assertIsNone(self._target().blocking_reason())

    def test_deleting_the_credential_disables_rather_than_falls_back(self):
        t = self._target()
        self.cred.delete()
        t.refresh_from_db()
        self.assertIsNone(t.credential)
        self.assertIsNotNone(t.blocking_reason())

    def test_one_target_per_asset(self):
        from django.db import IntegrityError, transaction
        self._target()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BackupTarget.objects.create(
                    asset=self.asset, host='10.0.0.3', username='admin')


class CollectorTests(TestCase):
    """The collector's failure handling. The SSH transport itself is stubbed —
    what matters here is that a device problem is recorded rather than raised,
    because one unreachable switch must not stop a run over two hundred."""

    def setUp(self):
        from vault.models import Password
        self.org = Organization.objects.create(name='ColCo', slug='col-co')
        self.asset = Asset.objects.create(
            organization=self.org, name='core-sw-01', asset_type='switch')
        self.cred = Password.objects.create(
            organization=self.org, title='switch admin', username='admin')
        self.cred.set_password('hunter2')
        self.cred.save()
        self.target = BackupTarget.objects.create(
            asset=self.asset, host='10.0.0.2', username='admin',
            credential=self.cred, adapter='cisco_ios')

    def test_blocked_target_records_the_reason_without_raising(self):
        from netconfig.collector import collect_target
        self.target.credential = None
        self.target.save()
        result = collect_target(self.target)
        self.assertFalse(result['ok'])
        self.target.refresh_from_db()
        self.assertIn('No vault credential', self.target.last_error)

    def test_a_connection_failure_is_recorded_not_raised(self):
        from unittest.mock import patch
        from netconfig.collector import collect_target
        with patch('netconfig.collector.collect_over_ssh',
                   side_effect=CollectionError('Could not connect: timed out')):
            result = collect_target(self.target)
        self.assertFalse(result['ok'])
        self.assertIn('timed out', result['message'])
        self.target.refresh_from_db()
        self.assertIn('timed out', self.target.last_error)
        self.assertIsNotNone(self.target.last_attempt_at)

    def test_an_unexpected_exception_is_contained(self):
        from unittest.mock import patch
        from netconfig.collector import collect_target
        with patch('netconfig.collector.collect_over_ssh',
                   side_effect=RuntimeError('kaboom')):
            result = collect_target(self.target)
        self.assertFalse(result['ok'])
        self.assertIn('kaboom', result['message'])

    def test_a_successful_collection_stores_a_snapshot(self):
        from unittest.mock import patch
        from netconfig.collector import collect_target
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '15.2(4)E7')):
            result = collect_target(self.target)
        self.assertTrue(result['ok'])
        self.assertTrue(result['created'])
        backup = ConfigBackup.objects.get()
        self.assertEqual(backup.source, 'ssh')
        self.assertEqual(backup.firmware_version, '15.2(4)E7')
        self.target.refresh_from_db()
        self.assertIsNotNone(self.target.last_success_at)
        self.assertEqual(self.target.last_error, '')

    def test_an_unchanged_collection_does_not_duplicate(self):
        from unittest.mock import patch
        from netconfig.collector import collect_target
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '')):
            collect_target(self.target)
            result = collect_target(self.target)
        self.assertTrue(result['ok'])
        self.assertFalse(result['changed'])
        self.assertEqual(ConfigBackup.objects.count(), 1)

    def test_a_success_clears_a_previous_error(self):
        from unittest.mock import patch
        from netconfig.collector import collect_target
        self.target.last_error = 'old failure'
        self.target.save()
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '')):
            collect_target(self.target)
        self.target.refresh_from_db()
        self.assertEqual(self.target.last_error, '')

    def test_collect_due_skips_targets_that_are_not_due(self):
        from unittest.mock import patch
        from netconfig.collector import collect_due
        self.target.last_attempt_at = timezone.now()
        self.target.save()
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '')):
            summary = collect_due()
        self.assertEqual(summary['attempted'], 0)

    def test_collect_due_force_ignores_cadence(self):
        from unittest.mock import patch
        from netconfig.collector import collect_due
        self.target.last_attempt_at = timezone.now()
        self.target.save()
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '')):
            summary = collect_due(force=True)
        self.assertEqual(summary['attempted'], 1)

    def test_one_failure_does_not_stop_the_run(self):
        from unittest.mock import patch
        from netconfig.collector import collect_due
        from vault.models import Password
        second_asset = Asset.objects.create(
            organization=self.org, name='core-sw-02', asset_type='switch')
        cred2 = Password.objects.create(
            organization=self.org, title='sw2', username='admin')
        cred2.set_password('pw')
        cred2.save()
        BackupTarget.objects.create(
            asset=second_asset, host='10.0.0.3', username='admin', credential=cred2)

        calls = {'n': 0}

        def flaky(target, password, timeout=30):
            calls['n'] += 1
            if calls['n'] == 1:
                raise CollectionError('unreachable')
            return CONFIG_A, ''

        with patch('netconfig.collector.collect_over_ssh', side_effect=flaky):
            summary = collect_due()
        self.assertEqual(summary['attempted'], 2)
        self.assertEqual(summary['ok'], 1)
        self.assertEqual(summary['failed'], 1)

    def test_collection_writes_an_audit_row(self):
        from unittest.mock import patch
        from audit.models import AuditLog
        from netconfig.collector import collect_target
        before = AuditLog.objects.count()
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '')):
            collect_target(self.target)
        self.assertGreater(AuditLog.objects.count(), before)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TargetViewTests(TestCase):
    def setUp(self):
        from vault.models import Password
        self.org = Organization.objects.create(name='TgtView', slug='tgt-view')
        self.other_org = Organization.objects.create(name='TgtOther', slug='tgt-other')
        self.asset = Asset.objects.create(
            organization=self.org, name='core-sw-01', asset_type='switch')
        self.cred = Password.objects.create(
            organization=self.org, title='switch admin', username='admin')
        self.cred.set_password('hunter2')
        self.cred.save()
        self.foreign_cred = Password.objects.create(
            organization=self.other_org, title='someone elses', username='admin')
        self.foreign_cred.set_password('nope')
        self.foreign_cred.save()
        self.user = User.objects.create_superuser(
            'tgtadmin', 't@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.user)
        # Pin the org the way the switcher does. Without this the middleware
        # auto-selects the first active organization for a superuser, which
        # with two orgs in play is not necessarily the one holding the asset.
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()

    def test_create_a_target(self):
        self.client.post(f'/netconfig/device/{self.asset.pk}/connection/', {
            'host': '10.0.0.2', 'username': 'admin', 'port': '22',
            'credential': self.cred.pk, 'adapter': 'cisco_ios',
            'cadence_hours': '24', 'is_enabled': 'on',
        })
        target = BackupTarget.objects.get(asset=self.asset)
        self.assertEqual(target.host, '10.0.0.2')
        self.assertEqual(target.credential, self.cred)

    def test_host_is_required(self):
        self.client.post(f'/netconfig/device/{self.asset.pk}/connection/', {
            'host': '  ', 'username': 'admin'})
        self.assertFalse(BackupTarget.objects.filter(asset=self.asset).exists())

    def test_cannot_link_another_clients_credential(self):
        """A switch in one client's rack must not be reachable with another
        client's credential."""
        self.client.post(f'/netconfig/device/{self.asset.pk}/connection/', {
            'host': '10.0.0.2', 'username': 'admin',
            'credential': self.foreign_cred.pk,
        })
        self.assertFalse(BackupTarget.objects.filter(asset=self.asset).exists())

    def test_delete_a_target_keeps_the_snapshots(self):
        ConfigBackup.record_for_asset(self.asset, CONFIG_A)
        BackupTarget.objects.create(
            asset=self.asset, host='10.0.0.2', username='admin', credential=self.cred)
        self.client.post(f'/netconfig/device/{self.asset.pk}/connection/',
                         {'action': 'delete'})
        self.assertFalse(BackupTarget.objects.filter(asset=self.asset).exists())
        self.assertEqual(ConfigBackup.objects.count(), 1)

    def test_collect_now_requires_post(self):
        BackupTarget.objects.create(
            asset=self.asset, host='10.0.0.2', username='admin', credential=self.cred)
        resp = self.client.get(f'/netconfig/device/{self.asset.pk}/collect/')
        self.assertEqual(resp.status_code, 302)

    def test_collect_now_runs_the_collector(self):
        from unittest.mock import patch
        BackupTarget.objects.create(
            asset=self.asset, host='10.0.0.2', username='admin', credential=self.cred)
        with patch('netconfig.collector.collect_over_ssh',
                   return_value=(CONFIG_A, '')):
            self.client.post(f'/netconfig/device/{self.asset.pk}/collect/')
        self.assertEqual(ConfigBackup.objects.count(), 1)
