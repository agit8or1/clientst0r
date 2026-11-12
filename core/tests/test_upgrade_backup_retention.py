"""Pre-upgrade backup retention (core/upgrade/retention.py, v3.17.667).

Every path here is a temporary directory: the backup root, the snapshots
in it, and anything an apply run would touch.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from core.models import ScheduledTask, SystemSetting
from core.upgrade import apply as upgrade_apply
from core.upgrade import journal, preflight, retention, snapshot
from core.upgrade.revision import Target

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
SHA1 = '1' * 40
SHA2 = '2' * 40
OLD = time.time() - 3600   # file mtimes: not "still being written"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_snap(root, days_old, *, verified=True, name=None, size=1000, manifest=True,
              version='3.17.600', touch_old=True, mtime=None):
    """A snapshot directory that snapshot.is_verified() accepts (or not)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    created = timezone.now() - timedelta(days=days_old)
    name = name or f"snapshot-{created.strftime('%Y%m%d-%H%M%S')}-v{version}"
    d = root / name
    d.mkdir(mode=0o700)
    db = d / 'database.sqlite3'
    db.write_bytes(os.urandom(size))
    if manifest:
        m = {'format': 1, 'created_at': created.isoformat(), 'app_version': version,
             'reason': 'test', 'files': {'database.sqlite3': {'sha256': _sha(db), 'size': size}}}
        (d / 'manifest.json').write_text(json.dumps(m))
        if verified:
            (d / 'verification.json').write_text(json.dumps({
                'ok': True, 'level': 'restore-test', 'verified_at': created.isoformat(),
                'manifest_sha256': _sha(d / 'manifest.json')}))
    if touch_old:
        t = mtime if mtime is not None else OLD
        for p in [*d.iterdir(), d]:
            os.utime(p, (t, t))
    return d


def names(root):
    return sorted(p.name for p in Path(root).iterdir() if p.name.startswith('snapshot-'))


class _Root:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix='cs0r-retention-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'backups'
        self.root.mkdir()
        o = override_settings(UPGRADE_BACKUP_DIR=self.root, UPGRADE_BACKUPS_KEEP=5,
                              UPGRADE_UNVERIFIED_GRACE_DAYS=14)
        o.enable()
        self.addCleanup(o.disable)

    def set_policy(self, keep=None, max_age=None):
        SystemSetting.get_settings()
        SystemSetting.objects.filter(pk=1).update(upgrade_backups_keep=keep,
                                                  upgrade_backups_max_age_days=max_age)

    def fail_journal(self, backup):
        journal.begin(target={'kind': 'release', 'ref': 'v9.9.9', 'sha': SHA1, 'version': '9.9.9'},
                      backup=str(backup))
        journal.stage('migrating')
        journal.finish('failed', error='migration failed', backup=str(backup))


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

class RetentionRuleTests(_Root, TestCase):
    def test_keeps_the_newest_by_count(self):
        snaps = [make_snap(self.root, d) for d in (1, 2, 3, 4, 5, 6, 7)]
        self.set_policy(keep=3)
        removed = retention.prune()
        self.assertEqual(sorted(removed), sorted(str(s) for s in snaps[3:]))
        self.assertEqual(names(self.root), sorted(s.name for s in snaps[:3]))

    def test_count_falls_back_to_the_environment(self):
        for d in range(1, 5):
            make_snap(self.root, d)
        self.set_policy(keep=None)
        with override_settings(UPGRADE_BACKUPS_KEEP=2):
            self.assertEqual(retention.policy().keep, 2)
            self.assertEqual(retention.policy().keep_from, 'environment')
            retention.prune()
        self.assertEqual(len(names(self.root)), 2)

    def test_setting_overrides_the_environment(self):
        self.set_policy(keep=4)
        with override_settings(UPGRADE_BACKUPS_KEEP=2):
            self.assertEqual(retention.policy().keep, 4)

    def test_maximum_age(self):
        keep = [make_snap(self.root, d) for d in (1, 10)]
        old = [make_snap(self.root, d) for d in (40, 50)]
        self.set_policy(keep=10, max_age=30)
        removed = retention.prune()
        self.assertEqual(sorted(removed), sorted(str(s) for s in old))
        self.assertEqual(names(self.root), sorted(s.name for s in keep))

    def test_newest_verified_survives_any_age_limit(self):
        snaps = [make_snap(self.root, d) for d in (100, 200)]
        self.set_policy(keep=5, max_age=30)
        retention.prune()
        self.assertEqual(names(self.root), [snaps[0].name])

    def test_keep_never_drops_below_one(self):
        make_snap(self.root, 1)
        make_snap(self.root, 2)
        retention.prune(keep=0)
        self.assertEqual(len(names(self.root)), 1)

    def test_reserve_leaves_room_for_the_new_backup_but_keeps_one(self):
        for d in (1, 2, 3):
            make_snap(self.root, d)
        self.set_policy(keep=3)
        retention.prune(reserve=1)
        self.assertEqual(len(names(self.root)), 2)
        self.set_policy(keep=1)
        retention.prune(reserve=1)
        self.assertEqual(len(names(self.root)), 1)

    def test_pinned_backup_is_never_removed(self):
        snaps = [make_snap(self.root, d) for d in (1, 2, 3)]
        self.fail_journal(snaps[2])   # oldest, but recovery needs it
        self.set_policy(keep=1)
        retention.prune(in_run=True)  # an upgrade run's own cleanup
        self.assertEqual(names(self.root), sorted([snaps[0].name, snaps[2].name]))

    def test_unverified_kept_within_grace_then_removed(self):
        fresh = make_snap(self.root, 3, verified=False)
        stale = make_snap(self.root, 20, verified=False)
        # no manifest: its age is the newest file time
        half = make_snap(self.root, 30, manifest=False, name='snapshot-20260101-000000-v1',
                         mtime=time.time() - 30 * 86400)
        good = make_snap(self.root, 1)
        removed = retention.prune()
        self.assertEqual(sorted(removed), sorted([str(stale), str(half)]))
        self.assertEqual(names(self.root), sorted([fresh.name, good.name]))

    def test_snapshot_being_written_is_not_touched(self):
        writing = make_snap(self.root, 30, manifest=False, name='snapshot-20260101-000000-v2',
                            touch_old=False)
        retention.prune()
        self.assertIn(writing.name, names(self.root))

    def test_a_damaged_newest_backup_does_not_cost_the_good_one(self):
        """Quick checks compare sizes; the kept backup is re-hashed."""
        older = make_snap(self.root, 5)
        newest = make_snap(self.root, 1)
        db = newest / 'database.sqlite3'
        db.write_bytes(os.urandom(db.stat().st_size))   # same size, other content
        self.set_policy(keep=1)
        retention.prune()
        self.assertIn(older.name, names(self.root))
        self.assertIn(newest.name, names(self.root), 'damaged but within the grace period')

    def test_refused_while_an_upgrade_is_running(self):
        for d in (1, 2, 3):
            make_snap(self.root, d)
        self.set_policy(keep=1)
        journal.begin(target={'kind': 'release', 'ref': 'v9.9.9', 'sha': SHA1})  # this pid: alive
        with self.assertRaises(retention.RetentionRefused):
            retention.prune()
        with self.assertRaises(retention.RetentionRefused):
            retention.delete(names(self.root)[0])
        self.assertEqual(len(names(self.root)), 3)

    def test_refused_while_the_upgrade_lock_is_held(self):
        for d in (1, 2):
            make_snap(self.root, d)
        self.set_policy(keep=1)
        with journal.upgrade_lock():
            with self.assertRaises(retention.RetentionRefused):
                retention.prune()
        self.assertEqual(len(names(self.root)), 2)

    def test_refused_while_recovery_is_needed(self):
        snaps = [make_snap(self.root, d) for d in (1, 2, 3)]
        self.fail_journal(snaps[0])
        self.set_policy(keep=1)
        with self.assertRaises(retention.RetentionRefused):
            retention.prune()
        self.assertEqual(len(names(self.root)), 3)

    def test_each_removal_is_audited(self):
        snaps = [make_snap(self.root, d) for d in (1, 2, 3)]
        self.set_policy(keep=1)
        retention.prune(trigger='scheduler')
        rows = AuditLog.objects.filter(action='delete', object_type='upgrade_backup')
        self.assertEqual(sorted(r.object_repr for r in rows), sorted(s.name for s in snaps[1:]))
        row = rows.first()
        self.assertEqual(row.username, 'system')
        self.assertEqual(row.extra_data['trigger'], 'scheduler')
        self.assertGreaterEqual(row.extra_data['size_bytes'], 1000)
        self.assertIn('verified backup', row.extra_data['reason'])

    def test_summary_lists_size_version_state_and_free_space(self):
        make_snap(self.root, 1, size=2048, version='3.17.666')
        make_snap(self.root, 2, verified=False)
        s = retention.summary()
        self.assertEqual(len(s['backups']), 2)
        b = s['backups'][0]
        self.assertEqual((b['app_version'], b['verified'], b['size']), ('3.17.666', True,
                                                                        b['size']))
        self.assertGreaterEqual(b['size'], 2048)
        self.assertTrue(b['protected'])
        self.assertGreater(s['total_bytes'], 3000)
        self.assertIsNotNone(s['free_bytes'])

    def test_summary_does_not_rehash(self):
        make_snap(self.root, 1)
        with mock.patch.object(snapshot, '_sha256', wraps=snapshot._sha256) as h:
            retention.summary()
        # only manifest.json is hashed (to detect a changed manifest), never the data
        hashed = {Path(c.args[0]).name for c in h.call_args_list}
        self.assertEqual(hashed, {'manifest.json'})


# ---------------------------------------------------------------------------
# deleting one
# ---------------------------------------------------------------------------

class DeleteOneTests(_Root, TestCase):
    def setUp(self):
        super().setUp()
        self.newest = make_snap(self.root, 1)
        self.older = make_snap(self.root, 5)

    def test_deletes_an_older_backup_and_audits_it(self):
        user = get_user_model().objects.create_user('del_su', is_superuser=True)
        retention.delete(self.older.name, user=user, trigger='web')
        self.assertEqual(names(self.root), [self.newest.name])
        row = AuditLog.objects.get(action='delete', object_type='upgrade_backup')
        self.assertEqual((row.user, row.object_repr), (user, self.older.name))
        self.assertEqual(row.extra_data['reason'], 'removed by request')

    def test_accepts_the_full_path(self):
        retention.delete(str(self.older))
        self.assertNotIn(self.older.name, names(self.root))

    def test_newest_verified_is_refused(self):
        with self.assertRaises(retention.RetentionRefused):
            retention.delete(self.newest.name)

    def test_pinned_is_refused(self):
        journal.write({'status': 'complete', 'stage': 'complete', 'backup': str(self.older)})
        with self.assertRaises(retention.RetentionRefused):
            retention.delete(self.older.name)
        self.assertIn(self.older.name, names(self.root))

    def test_path_traversal_and_outside_paths_are_refused(self):
        outside = self.tmp / 'elsewhere'
        victim = make_snap(outside, 9, name='snapshot-victim')
        (self.root / 'not-a-snapshot').mkdir()
        bad = [
            '', '..', '../elsewhere/snapshot-victim', 'snapshot-x/../../elsewhere/snapshot-victim',
            str(victim), str(self.root / '..' / 'elsewhere' / 'snapshot-victim'),
            '/etc', 'journal.json', 'not-a-snapshot', str(self.root), 'snapshot-missing',
            f'{self.older.name}/database.sqlite3',
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(retention.RetentionRefused):
                retention.delete(value)
        self.assertTrue(victim.is_dir())
        self.assertEqual(len(names(self.root)), 2)

    def test_symlinked_snapshot_is_refused(self):
        outside = make_snap(self.tmp / 'elsewhere', 9, name='snapshot-target')
        link = self.root / 'snapshot-link'
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(retention.RetentionRefused):
            retention.delete('snapshot-link')
        self.assertTrue((outside / 'database.sqlite3').is_file())
        # and a cleanup never follows it either
        self.set_policy(keep=1)
        retention.prune()
        self.assertTrue((outside / 'database.sqlite3').is_file())

    def test_symlinked_parent_is_refused(self):
        real = self.tmp / 'real'
        make_snap(real, 9, name='snapshot-via-link')
        (self.tmp / 'link').symlink_to(real, target_is_directory=True)
        with self.assertRaises(retention.RetentionRefused):
            retention.delete(str(self.tmp / 'link' / 'snapshot-via-link'))
        self.assertTrue((real / 'snapshot-via-link').is_dir())


# ---------------------------------------------------------------------------
# command line and scheduler
# ---------------------------------------------------------------------------

class CommandTests(_Root, TestCase):
    def test_prune_and_delete(self):
        snaps = [make_snap(self.root, d) for d in (1, 2, 3)]
        self.set_policy(keep=2)
        out = io.StringIO()
        call_command('upgrade_backup', '--prune', stdout=out)
        self.assertIn('Removed 1 backup(s)', out.getvalue())
        call_command('upgrade_backup', '--delete', str(snaps[1]), stdout=io.StringIO())
        self.assertEqual(names(self.root), [snaps[0].name])
        with self.assertRaises(CommandError):
            call_command('upgrade_backup', '--delete', str(snaps[0]), stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command('upgrade_backup', '--delete', '../../etc', stdout=io.StringIO())

    def test_prune_refused_on_the_command_line_skipped_by_the_scheduler(self):
        snaps = [make_snap(self.root, d) for d in (1, 2)]
        self.fail_journal(snaps[1])
        with self.assertRaises(CommandError):
            call_command('upgrade_backup', '--prune', stdout=io.StringIO())
        out = io.StringIO()
        call_command('upgrade_backup', '--prune', '--trigger', 'scheduler', stdout=out)
        self.assertIn('Skipped', out.getvalue())

    def test_creating_a_backup_grooms_before_and_after(self):
        for d in (2, 3, 4):
            make_snap(self.root, d)
        self.set_policy(keep=3)
        seen = {}

        def create(**kw):
            seen['before'] = len(names(self.root))
            return make_snap(self.root, 0, version='3.17.667')
        with mock.patch.object(snapshot, 'create', side_effect=create), \
                mock.patch.object(snapshot, 'verify', return_value={'ok': True, 'level': 'restore-test',
                                                                    'checks': []}):
            call_command('upgrade_backup', stdout=io.StringIO())
        self.assertEqual(seen['before'], 2, 'room made for the new backup first')
        self.assertEqual(len(names(self.root)), 3)

    def test_scheduler_hook(self):
        from core.management.commands import run_scheduler
        self.assertEqual(run_scheduler.COMMAND_TASKS['upgrade_backup_prune'][0], 'upgrade_backup')
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='upgrade_backup_prune')
        self.assertTrue(task.enabled)
        self.assertEqual(task.interval_minutes, 1440)
        snaps = [make_snap(self.root, d) for d in (1, 2, 3)]
        self.set_policy(keep=1)
        run_scheduler.Command().run_command_task('upgrade_backup_prune')
        self.assertEqual(names(self.root), [snaps[0].name])
        row = AuditLog.objects.filter(object_type='upgrade_backup').first()
        self.assertEqual(row.extra_data['trigger'], 'scheduler')

    def test_preflight_disk_message_points_at_the_cleanup(self):
        with mock.patch.object(preflight.shutil, 'disk_usage',
                               return_value=mock.Mock(free=1)):
            c = preflight.check_disk()
        self.assertEqual(c.status, 'fail')
        self.assertIn('Clean up now', c.hint)
        self.assertIn('upgrade_backup --prune', c.hint)


# ---------------------------------------------------------------------------
# every upgrade run grooms itself
# ---------------------------------------------------------------------------

MIGRATING = ('"$CLIENTST0R_PYTHON" -c "import json, sys; p = sys.argv[1]; d = json.load(open(p)); '
             'd[\'stage\'] = \'migrating\'; json.dump(d, open(p, \'w\'))" "$CLIENTST0R_JOURNAL"\n')


class UpgradeRunGroomsTests(_Root, TestCase):
    def setUp(self):
        super().setUp()
        self.seen = {}

        def create(**kw):
            self.seen['at_create'] = len([r for r in retention.inventory() if r['verified']])
            return make_snap(self.root, 0, version='99.0.0')
        patches = {
            'is_git_install': mock.patch.object(upgrade_apply, 'is_git_install', return_value=True),
            'head_sha': mock.patch.object(upgrade_apply, 'head_sha', return_value=SHA1),
            'check_remote_unchanged': mock.patch.object(upgrade_apply, 'check_remote_unchanged'),
            'fetch': mock.patch.object(upgrade_apply, 'fetch'),
            'verify_release_tag': mock.patch.object(upgrade_apply, 'verify_release_tag',
                                                    return_value='Good signature'),
            'version_at': mock.patch.object(upgrade_apply, 'version_at', return_value='99.0.0'),
            'preflight': mock.patch.object(upgrade_apply.preflight, 'run', return_value=[
                preflight.Check('disk space', 'ok', 'plenty')]),
            'create': mock.patch.object(upgrade_apply.snapshot, 'create', side_effect=create),
            'verify': mock.patch.object(upgrade_apply.snapshot, 'verify', return_value={
                'ok': True, 'level': 'restore-test', 'checks': []}),
        }
        for p in patches.values():
            p.start()
            self.addCleanup(p.stop)
        self.target = Target('release', 'v99.0.0', SHA2)

    def _script(self, body):
        path = self.tmp / f'update-{len(list(self.tmp.iterdir()))}.sh'
        path.write_text('#!/bin/bash\n' + body)
        os.chmod(path, 0o700)
        return mock.patch.object(upgrade_apply, 'extract_to_private_file', return_value=path)

    def _verified(self):
        return [r for r in retention.inventory() if r['verified']]

    def test_successful_run_leaves_the_root_within_retention(self):
        for d in (1, 2, 3, 4, 5, 6):
            make_snap(self.root, d)
        expired = make_snap(self.root, 30, verified=False)
        self.set_policy(keep=3)
        with self._script('echo "Update complete!"\n'):
            r = upgrade_apply.run(self.target)
        self.assertTrue(r['success'], r)
        self.assertEqual(self.seen['at_create'], 2, 'groomed before the new backup, counting it')
        self.assertEqual(len(self._verified()), 3)
        self.assertNotIn(expired.name, names(self.root))
        self.assertEqual(self._verified()[0]['path'], r['backup'])
        out = '\n'.join(r['output'])
        self.assertIn('Removed upgrade backup', out)
        self.assertTrue(AuditLog.objects.filter(object_type='upgrade_backup',
                                                extra_data__trigger='upgrade').exists())

    def test_failed_run_leaves_the_root_within_retention_and_keeps_its_backup(self):
        for d in (1, 2, 3, 4, 5):
            make_snap(self.root, d)
        expired = make_snap(self.root, 30, verified=False)
        self.set_policy(keep=2)
        with self._script(MIGRATING + 'echo "migration failed"; exit 3\n'):
            r = upgrade_apply.run(self.target)
        self.assertFalse(r['success'])
        self.assertTrue(journal.assess()['needs_recovery'])
        self.assertTrue(Path(r['backup']).is_dir(), 'recovery needs it')
        self.assertLessEqual(len(self._verified()), 2)
        self.assertNotIn(expired.name, names(self.root))

    def test_run_that_fails_before_the_script_still_grooms(self):
        for d in (1, 2, 3, 4):
            make_snap(self.root, d)
        self.set_policy(keep=2)
        with mock.patch.object(upgrade_apply, 'extract_to_private_file',
                               side_effect=RuntimeError('boom')):
            r = upgrade_apply.run(self.target)
        self.assertFalse(r['success'])
        self.assertLessEqual(len(self._verified()), 2)

    def test_run_refused_because_recovery_is_needed_touches_nothing(self):
        snaps = [make_snap(self.root, d) for d in (1, 2, 3, 4)]
        self.fail_journal(snaps[3])
        self.set_policy(keep=1)
        r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        self.assertEqual(len(names(self.root)), 4)

    def test_never_below_one_verified_before_the_new_one_verifies(self):
        make_snap(self.root, 1)
        self.set_policy(keep=1)
        with self._script('echo "Update complete!"\n'):
            r = upgrade_apply.run(self.target)
        self.assertTrue(r['success'], r)
        self.assertEqual(self.seen['at_create'], 1)
        self.assertEqual(len(self._verified()), 1)


# ---------------------------------------------------------------------------
# Settings -> Updates
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BackupViewTests(_Root, TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.su = User.objects.create_user('bk_su', 'su@x.invalid', 'pw', is_superuser=True,
                                           is_staff=True)
        self.staff = User.objects.create_user('bk_staff', 'st@x.invalid', 'pw', is_staff=True)
        self.plain = User.objects.create_user('bk_plain', 'p@x.invalid', 'pw')
        self.newest = make_snap(self.root, 1, version='3.17.666', size=4096)
        self.older = make_snap(self.root, 5, version='3.17.660')
        p = mock.patch('core.updater.UpdateService.check_for_updates', return_value={
            'update_available': False, 'target': None, 'current_version': '1',
            'latest_version': '1', 'channels': {}})
        p.start()
        self.addCleanup(p.stop)

    def test_page_lists_backups_with_size_total_and_free_space(self):
        self.client.force_login(self.su)
        html = self.client.get(reverse('core:system_updates')).content.decode()
        self.assertIn('Pre-upgrade backups', html)
        self.assertIn(self.newest.name, html)
        self.assertIn('v3.17.660', html)
        size = retention.summary()['backups'][0]['size_human']
        self.assertIn('KB', size)
        self.assertIn(size, html)
        self.assertIn(retention.summary()['total_human'], html)
        self.assertIn('Free disk space', html)
        self.assertIn('Clean up now', html)
        self.assertIn(reverse('core:upgrade_backup_delete'), html)
        self.assertIn('data-confirm="Delete the backup', html)
        self.assertNotIn('onclick=', html.split('id="preUpgradeBackups"', 1)[1].split('Debug Information')[0])

    def test_save_retention(self):
        self.client.force_login(self.su)
        self.client.post(reverse('core:upgrade_backup_settings'), {'keep': '3', 'max_age_days': '45'})
        s = SystemSetting.get_settings()
        self.assertEqual((s.upgrade_backups_keep, s.upgrade_backups_max_age_days), (3, 45))
        self.assertTrue(AuditLog.objects.filter(object_repr='Upgrade backup retention').exists())
        self.client.post(reverse('core:upgrade_backup_settings'), {'keep': '', 'max_age_days': ''})
        s = SystemSetting.get_settings()
        self.assertEqual((s.upgrade_backups_keep, s.upgrade_backups_max_age_days), (None, None))

    def test_invalid_retention_is_rejected(self):
        self.client.force_login(self.su)
        for data in ({'keep': '0'}, {'keep': 'abc'}, {'keep': '2', 'max_age_days': '0'}):
            self.client.post(reverse('core:upgrade_backup_settings'), data)
        self.assertIsNone(SystemSetting.get_settings().upgrade_backups_keep)

    def test_delete_and_clean_up_now(self):
        self.client.force_login(self.su)
        r = self.client.post(reverse('core:upgrade_backup_delete'), {'name': self.older.name})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(names(self.root), [self.newest.name])
        row = AuditLog.objects.get(object_type='upgrade_backup', action='delete',
                                   object_repr=self.older.name)
        self.assertEqual(row.user, self.su)
        self.assertEqual(row.extra_data['trigger'], 'web')
        # the newest verified one cannot be deleted
        self.client.post(reverse('core:upgrade_backup_delete'), {'name': self.newest.name})
        self.assertEqual(names(self.root), [self.newest.name])
        make_snap(self.root, 9)
        self.set_policy(keep=1)
        self.client.post(reverse('core:upgrade_backups_prune'))
        self.assertEqual(names(self.root), [self.newest.name])

    def test_delete_refuses_traversal(self):
        self.client.force_login(self.su)
        victim = make_snap(self.tmp / 'elsewhere', 9, name='snapshot-victim')
        for name in ('../elsewhere/snapshot-victim', str(victim), '..'):
            self.client.post(reverse('core:upgrade_backup_delete'), {'name': name})
        self.assertTrue(victim.is_dir())

    def test_only_superusers(self):
        for user in (self.staff, self.plain):
            self.client.force_login(user)
            for url, data in ((reverse('core:upgrade_backup_delete'), {'name': self.older.name}),
                              (reverse('core:upgrade_backups_prune'), {}),
                              (reverse('core:upgrade_backup_settings'), {'keep': '1'})):
                r = self.client.post(url, data)
                self.assertIn(r.status_code, (302, 403), (user.username, url))
                if r.status_code == 302:
                    self.assertIn('login', r['Location'])
        self.assertEqual(len(names(self.root)), 2)
        self.assertIsNone(SystemSetting.get_settings().upgrade_backups_keep)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(reverse('core:upgrade_backups_prune')).status_code, 405)
        self.assertEqual(len(names(self.root)), 2)

    def test_csrf_is_enforced(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.su)
        r = c.post(reverse('core:upgrade_backup_delete'), {'name': self.older.name})
        self.assertEqual(r.status_code, 403)
        r = c.post(reverse('core:upgrade_backups_prune'))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(names(self.root)), 2)
