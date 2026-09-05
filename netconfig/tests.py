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
from netconfig.models import ConfigBackup

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
